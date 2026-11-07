"""Declared, hash-pinned online/offline assets; no caller-controlled URLs/paths."""
import hashlib
from contextlib import ExitStack
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import threading
import time
import uuid
import httpx
from .paths import APP_ROOT, MODELS, PRIVATE, atomic_json, ordinary_tree, python_runtime
from .download_store import store, ACTIVE, resource_key
from .voice_diagnostics import MESSAGES, classify_voice_error
from .resource_lock import resource_download_lock, ResourceBusyError
from . import asr_sources

MANIFEST = json.loads((APP_ROOT / 'config/voice_resources.json').read_text(encoding='utf-8'))
_controls = {}
_threads = {}
_probes = {}
_sources = {}
_closing = False
_lock = threading.Lock()
# Downloads never hold this slot. Only the bounded native load/synthesis probe
# uses it; independent downloads can continue while a probe waits or runs.
_probe_slot = threading.Lock()
ASR_PROFILES = {'cpu-fast': 'small', 'balanced': 'small', 'gpu-quality': 'medium'}


def assets_for(kind, profile='balanced'):
    if kind not in ('asr', 'tts') or profile not in ASR_PROFILES:
        raise ValueError('Неизвестный ресурс или профиль.')
    prefix = 'whisper/' + ASR_PROFILES[profile] + '/' if kind == 'asr' else 'silero/'
    assets = [a for a in MANIFEST['assets'] if a['path'].startswith(prefix)]
    if not assets:
        raise ValueError('Ресурс отсутствует в манифесте. Восстановите LocalMind установщиком.')
    return assets


def verification_key(kind, profile='balanced'):
    # Both small profiles prepare and probe the very same CPU/int8 files. Keep
    # the previous balanced stamp path; its manifest/signatures are rechecked.
    return kind if kind != 'asr' or ASR_PROFILES[profile] == 'small' else kind + '-' + profile


def dependencies(kind):
    modules = ('faster_whisper', 'av') if kind == 'asr' else ('torch', 'numpy')
    try:
        return all(importlib.util.find_spec(name) for name in modules)
    except (ImportError, ValueError):
        return False


def status():
    from .voice import default_stt_profile
    rows = []
    for kind, profile in [('asr', p) for p in ASR_PROFILES] + [('tts', 'balanced')]:
        assets = assets_for(kind, profile)
        stamp_key = verification_key(kind, profile)
        state = 'dependency_missing' if not dependencies(kind) else 'unverified'
        if state != 'dependency_missing':
            try:
                for asset in assets:
                    path = ordinary_tree(MODELS / asset['path'])
                    if not path.is_file():
                        state = 'model_missing'; break
                    if path.stat().st_size != asset['bytes']:
                        state = 'resource_corrupt'; break
                else:
                    stamp = json.loads((PRIVATE / (stamp_key + '-verified.json')).read_text(encoding='utf-8'))
                    if stamp.get('manifest') == manifest_digest() and stamp.get('files') == signatures(assets):
                        state = 'ready'
            except FileNotFoundError:
                pass
            except (OSError, ValueError):
                state = 'path_invalid'
        if state == 'unverified':
            try:
                failure = json.loads((PRIVATE / (stamp_key + '-failure.json')).read_text(encoding='utf-8'))
                if failure.get('code') in MESSAGES:
                    state = failure['code']
            except (OSError, ValueError):
                pass
        source_info = {}
        if kind == 'asr':
            mirror = asr_sources.mirror_for(ASR_PROFILES[profile], assets)
            source_info = {'download_bytes': sum(a['bytes'] for a in assets),
                           'import_files': [{'name': Path(a['path']).name, 'bytes': a['bytes']} for a in assets],
                           'mirror_configured': mirror is not None}
        rows.append({'kind': kind, 'profile': profile if kind == 'asr' else None,
                     'required': kind != 'asr' or profile == default_stt_profile(),
                     'model': ASR_PROFILES[profile] if kind == 'asr' else 'Silero · xenia', 'state': state,
                     'action': 'Восстановить установку LocalMind' if state == 'dependency_missing' else 'Подготовить голос',
                     **source_info})
    return rows


def manifest_digest():
    return hashlib.sha256(json.dumps(MANIFEST, sort_keys=True).encode()).hexdigest()


def mirror_offer(profile):
    if profile not in ASR_PROFILES:
        return None
    mirror = asr_sources.mirror_for(ASR_PROFILES[profile], assets_for('asr', profile))
    return {'fingerprint': mirror['fingerprint'], 'bytes': mirror['bytes']} if mirror else None


def signatures(assets):
    return {a['path']: [ordinary_tree(MODELS / a['path']).stat().st_size,
                       (MODELS / a['path']).stat().st_mtime_ns] for a in assets}


def file_digest(path, cancel=None):
    h = hashlib.sha256()
    with ordinary_tree(path).open('rb') as stream:
        while chunk := stream.read(1048576):
            if cancel is not None and cancel.is_set():
                raise InterruptedError()
            h.update(chunk)
    return h.hexdigest()


def start(kind, profile='balanced', *, source='huggingface', fingerprint=None, incoming=None, mode=None):
    if kind not in ('asr', 'tts'):
        raise ValueError('Неизвестный ресурс.')
    assets = assets_for(kind, profile)
    if (source not in ('huggingface', 'yandex', 'local') or kind != 'asr' and source != 'huggingface'
            or source == 'local' and (incoming is None or mode not in ('zip', 'directory'))):
        raise ValueError('Неизвестный источник голосового ресурса.')
    mirror = None
    if source == 'yandex':
        mirror = asr_sources.mirror_for(ASR_PROFILES[profile], assets)
        if not mirror or mirror['fingerprint'] != fingerprint:
            raise ValueError('Зеркало не настроено или изменилось. Повторите проверку источника.')
    if not dependencies(kind):
        raise ValueError('Компоненты голоса отсутствуют. Восстановите LocalMind установщиком; Python и pip не нужны.')
    key, cancel = uuid.uuid4().hex, threading.Event()
    job = {'id': key, 'kind': kind, 'model': 'Русская речь · ' + ASR_PROFILES[profile] if kind == 'asr' else 'Silero · xenia',
           'profile': profile if kind == 'asr' else None,
           'destination': str(MODELS / 'whisper' / ASR_PROFILES[profile] if kind == 'asr' else MODELS / 'silero'),
           'status': 'starting', 'completed': 0, 'total': 0, 'error': None, 'layers': {},
           'created_at': time.time(), 'resumable': True}
    if kind == 'asr':
        job.update(asr_source=source, resumable=source == 'huggingface')
        if mirror:
            job.update(mirror_fingerprint=fingerprint, total=mirror['bytes'])
    with _lock:
        if _closing:
            raise ValueError('LocalMind завершает работу. Новая подготовка недоступна.')
        for existing in store.snapshot():
            if existing.get('status') in ACTIVE and resource_key(existing) == resource_key(job):
                if source == 'local':
                    raise ValueError('Подготовка этой модели уже выполняется.')
                return existing
        store.insert(job)
        _controls[key] = cancel
        try:
            options = {} if source == 'huggingface' else {'source': source, 'mirror': mirror, 'incoming': incoming, 'mode': mode}
            thread = threading.Thread(target=_prepare, args=(key, kind, cancel, profile), kwargs=options,
                                      daemon=True, name='localmind-assets')
            _threads[key] = thread
            thread.start()
        except RuntimeError:
            _controls.pop(key, None)
            _threads.pop(key, None)
            store.terminal_failure(key, error='Не удалось запустить подготовку. Повторите позже.')
            raise ValueError('Не удалось запустить подготовку. Повторите позже.') from None
    return store.snapshot(key)


def cancel(key):
    with _lock:
        event = _controls.get(key)
        if not event or store.snapshot(key)['status'] not in ('starting', 'queued', 'downloading', 'verifying', 'cancelling'):
            raise ValueError('Задача уже завершена.')
        event.set()
        probe = _probes.get(key)
        if probe is not None:
            _stop_probe(probe)
        store.update(key, status='cancelling')
    return store.snapshot(key)


def reopen():
    """Explicit application startup, never an automatic retry of old jobs."""
    global _closing
    with _lock:
        if any(thread.is_alive() for thread in _threads.values()) or _probes:
            raise ValueError('Предыдущая подготовка ещё завершает работу.')
        _closing = False


def _stop_probe(process):
    try:
        if process.poll() is None:
            process.kill()
    except OSError:
        pass


def stop_all():
    """Cancel our downloads/probes only; never kill an external application."""
    global _closing
    with _lock:
        _closing = True
        for event in _controls.values():
            event.set()
        probes, sources, threads = list(_probes.values()), list(_sources.values()), list(_threads.values())
        for process in probes:
            _stop_probe(process)
    for source in sources:
        try:
            source.close()
        except (OSError, RuntimeError):
            pass
    for process in probes:
        try:
            process.wait(timeout=5)
        except (OSError, subprocess.TimeoutExpired):
            if process.poll() is None:
                raise RuntimeError('Не удалось завершить проверку голосовых ресурсов.') from None
    deadline = time.monotonic() + 6
    for thread in threads:
        if thread is not threading.current_thread():
            thread.join(timeout=max(0, deadline - time.monotonic()))
    if any(thread.is_alive() for thread in threads if thread is not threading.current_thread()):
        raise RuntimeError('Не удалось завершить подготовку голосовых ресурсов.')


def _partial_path(target):
    return ordinary_tree(target.with_suffix(target.suffix + '.partial'))


def _download_asset(key, asset, target, cancel, completed, total):
    """Resume a pinned asset; an unverified partial is never a ready model.

    Range responses must describe exactly the requested suffix. A server that
    ignores Range is safely restarted with wb. Interrupted transfers stay on
    disk; only known-invalid leftovers are discarded.
    """
    partial = _partial_path(target)
    expected = asset['bytes']
    offset = partial.stat().st_size if partial.is_file() else 0
    if offset > expected:
        partial.unlink()
        offset = 0
    if offset == expected:
        if file_digest(partial, cancel) == asset['sha256']:
            if cancel.is_set():
                raise InterruptedError()
            os.replace(partial, target)
            return
        partial.unlink()
        offset = 0
    bundled = ordinary_tree(APP_ROOT / 'offline-assets' / asset['path'])
    if bundled.is_file():
        context = bundled.open('rb')
    else:
        headers = {'Accept-Encoding': 'identity'}
        if offset:
            headers['Range'] = 'bytes=' + str(offset) + '-'
        context = httpx.stream('GET', asset['url'], headers=headers,
            timeout=httpx.Timeout(30, connect=5, read=5), follow_redirects=True, trust_env=False)
    try:
        with context as source:
            with _lock:
                if cancel.is_set() or _closing:
                    raise InterruptedError()
                _sources[key] = source
            if bundled.is_file():
                source.seek(offset)
                chunks = iter(lambda: source.read(1048576), b'')
            else:
                source.raise_for_status()
                if source.status_code == 200:
                    # Range ignored, or a fresh response. Never append a whole
                    # representation to the previously downloaded prefix.
                    offset = 0
                elif source.status_code == 206:
                    content_range = source.headers.get('Content-Range', '')
                    match = re.fullmatch(r'bytes (\d+)-(\d+)/(\d+)', content_range)
                    if not match or tuple(map(int, match.groups())) != (offset, expected - 1, expected):
                        raise ValueError('Сервер вернул неверный диапазон ресурса.')
                else:
                    raise ValueError('Сервер вернул неподходящий ответ загрузки.')
                if source.headers.get('Content-Encoding', 'identity').lower() != 'identity':
                    raise ValueError('Сервер изменил представление ресурса.')
                length = source.headers.get('Content-Length')
                if length is not None and (not length.isdecimal() or int(length) != expected - offset):
                    raise ValueError('Размер ответа не совпадает с манифестом.')
                chunks = source.iter_bytes(1048576)
            count = offset
            store.update(key, status='downloading', total=total, completed=completed + count)
            with partial.open('ab' if offset else 'wb') as output:
                for chunk in chunks:
                    if cancel.is_set():
                        raise InterruptedError()
                    count += len(chunk)
                    if count > expected:
                        # Invalidate after closing the handle (also on Windows).
                        raise _InvalidPartial('Размер ресурса не совпадает с манифестом.')
                    output.write(chunk)
                    store.update(key, status='downloading', total=total, completed=completed + count)
                output.flush()
                os.fsync(output.fileno())
            if count != expected:
                # A truncated response can be resumed; no publication or probe.
                raise OSError('Загрузка ресурса прервана до получения всех байтов.')
            if file_digest(partial, cancel) != asset['sha256']:
                raise _InvalidPartial('Контрольная сумма ресурса не совпадает.')
            if cancel.is_set():
                raise InterruptedError()
            os.replace(partial, target)
    except _InvalidPartial:
        partial.unlink(missing_ok=True)
        raise
    finally:
        with _lock:
            _sources.pop(key, None)
        if partial.is_file() and partial.stat().st_size == 0:
            partial.unlink()


class _InvalidPartial(ValueError):
    """Known-invalid bytes are discarded; recoverable transfers are retained."""


def _verified_stamp(kind, profile, assets):
    try:
        stamp = json.loads(ordinary_tree(PRIVATE / (verification_key(kind, profile) + '-verified.json')).read_text(encoding='utf-8'))
        return stamp.get('manifest') == manifest_digest() and stamp.get('files') == signatures(assets)
    except (OSError, ValueError):
        return False


def _serial_probe(key, kind, cancel, profile, stage=None):
    # A queued native probe is independently cancellable and owns no network
    # connection. Native resource-worker processes never overlap in this app.
    while not _probe_slot.acquire(timeout=.1):
        if cancel.is_set():
            raise InterruptedError()
    try:
        if cancel.is_set():
            raise InterruptedError()
        return _run_probe(key, kind, cancel, profile, stage) if stage else _run_probe(key, kind, cancel, profile)
    finally:
        _probe_slot.release()


def _run_probe(key, kind, cancel, profile, stage=None):
    # Publish ownership under the same lock that closes admission. Shutdown
    # cannot miss a just-started native process or allow a later one to start.
    with _lock:
        if _closing or cancel.is_set():
            raise InterruptedError()
        command = [str(python_runtime()), '-m', 'localmind.resource_worker', kind, profile]
        if stage is not None:
            command.append(stage.name)
        process = subprocess.Popen(command,
            cwd=APP_ROOT, shell=False, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        _probes[key] = process
    try:
        try:
            output, _ = process.communicate(timeout=180)
        except subprocess.TimeoutExpired:
            _stop_probe(process)
            process.communicate(timeout=5)
            raise
        if cancel.is_set():
            raise InterruptedError()
        return subprocess.CompletedProcess(process.args, process.returncode, stdout=output)
    finally:
        _stop_probe(process)
        process.wait(timeout=5)
        with _lock:
            _probes.pop(key, None)


def _require_probe(result):
    if result.returncode:
        try:
            code = json.loads(result.stdout)['code']
        except (ValueError, KeyError, TypeError):
            code = 'library_incompatible'
        raise RuntimeError(code)


def _mark_ready(key, kind, profile, assets):
    stamp_key = verification_key(kind, profile)
    atomic_json(PRIVATE / (stamp_key + '-verified.json'), {'manifest': manifest_digest(), 'files': signatures(assets)})
    ordinary_tree(PRIVATE / (stamp_key + '-failure.json')).unlink(missing_ok=True)
    store.update(key, status='succeeded', ready=True)


def _install_import(key, profile, cancel, assets, source, mirror, incoming, mode):
    model = ASR_PROFILES[profile]
    parent = ordinary_tree(MODELS / 'whisper')
    parent.mkdir(parents=True, exist_ok=True)
    target = ordinary_tree(parent / model)
    stage = parent / ('.asr-stage-' + uuid.uuid4().hex)
    stage.mkdir()
    try:
        if source == 'yandex':
            archive = stage / 'incoming.zip'
            mode = 'zip'
            if shutil.disk_usage(parent).free < sum(a['bytes'] for a in assets) + (mirror['bytes'] or asr_sources.archive_limit(assets)):
                raise OSError('Недостаточно места')

            def register(response):
                with _lock:
                    asr_sources.check_cancel(cancel)
                    _sources[key] = response

            with httpx.Client(timeout=httpx.Timeout(15, connect=5, read=5), follow_redirects=False, trust_env=False) as client:
                asr_sources.download_archive(client, mirror, archive, assets, cancel,
                    lambda completed, total: store.update(key, status='downloading', completed=completed, total=total), register)
        else:
            archive = ordinary_tree(incoming)
            received = archive.stat().st_size
            store.update(key, completed=received, total=received)
        store.update(key, status='verifying')
        asr_sources.stage_import(archive, mode, stage, model, assets, cancel)
        if source == 'yandex':
            archive.unlink()
        _require_probe(_serial_probe(key, 'asr', cancel, profile, stage))
        with _lock:
            asr_sources.check_cancel(cancel)
            ordinary_tree(stage)
            ordinary_tree(target)
            # Preserve an older directory, including partial HF files. Restore
            # it if publishing the verified replacement fails.
            backup = parent / (model + '.previous-' + uuid.uuid4().hex)
            had_target = target.exists()
            if had_target:
                target.rename(backup)
            try:
                stage.rename(target)
            except OSError:
                if had_target:
                    backup.rename(target)
                raise
            _mark_ready(key, 'asr', profile, assets)
    finally:
        if stage.exists():
            resolved = ordinary_tree(stage).resolve()
            if resolved.parent != parent.resolve() or resolved.name != stage.name:
                raise ValueError('Каталог проверки модели изменился.')
            shutil.rmtree(resolved)


def _remote_unavailable(exc):
    return isinstance(exc, httpx.RequestError) or isinstance(exc, httpx.HTTPStatusError) and (
        exc.response.status_code in (401, 403, 404, 408, 429) or exc.response.status_code >= 500)


def _prepare(key, kind, cancel, profile='balanced', *, source='huggingface', mirror=None, incoming=None, mode=None):
    stamp_key = verification_key(kind, profile)
    locks = ExitStack()
    try:
        if cancel.is_set():
            raise InterruptedError()
        locks.enter_context(resource_download_lock(MODELS, resource_key({'id': key, 'kind': kind, 'profile': profile})))
        assets = assets_for(kind, profile)
        total, completed = sum(a['bytes'] for a in assets), 0
        MODELS.mkdir(parents=True, exist_ok=True)
        pending = []
        needed = 0
        for asset in assets:
            if cancel.is_set():
                raise InterruptedError()
            target = ordinary_tree(MODELS / asset['path'])
            valid = (target.is_file() and target.stat().st_size == asset['bytes']
                     and file_digest(target, cancel) == asset['sha256'])
            if not valid:
                partial = _partial_path(target)
                retained = partial.stat().st_size if partial.is_file() else 0
                needed += max(0, asset['bytes'] - retained) if retained <= asset['bytes'] else asset['bytes']
                pending.append((asset, target))
        # Installed, verified resources do not require space for another copy.
        if pending and source != 'huggingface':
            _install_import(key, profile, cancel, assets, source, mirror, incoming, mode)
            return
        if pending and shutil.disk_usage(MODELS).free < needed + 100 * 1048576:
            raise OSError('Недостаточно места')
        pending_paths = {a['path'] for a, _ in pending}
        for asset in assets:
            if cancel.is_set():
                raise InterruptedError()
            if asset['path'] in pending_paths:
                target = ordinary_tree(MODELS / asset['path'])
                target.parent.mkdir(parents=True, exist_ok=True)
                _download_asset(key, asset, target, cancel, completed, total)
            completed += asset['bytes']
            store.update(key, completed=completed, total=total)
        if cancel.is_set():
            raise InterruptedError()
        if not _verified_stamp(kind, profile, assets):
            store.update(key, status='verifying')
            # Always use private python.exe, never the frozen GUI launcher.
            _require_probe(_serial_probe(key, kind, cancel, profile))
        with _lock:
            if cancel.is_set():
                raise InterruptedError()
            _mark_ready(key, kind, profile, assets)
    except InterruptedError:
        message = ('Загрузка прервана. Нажмите «Повторить»: загруженная часть сохранена.' if source == 'huggingface'
                   else 'Подготовка отменена. Для локального импорта выберите файл или папку снова.' if source == 'local'
                   else 'Загрузка отменена. Повтор начнёт скачивание архива заново.')
        store.terminal_failure(key, status='cancelled', error=message)
    except ResourceBusyError as exc:
        store.terminal_failure(key, error=str(exc))
    except Exception as exc:
        if cancel.is_set():
            store.terminal_failure(key, status='cancelled', error='Подготовка остановлена при завершении LocalMind. Загруженная часть сохранена.')
            return
        from .download_errors import record_download_error
        error = record_download_error(exc, 'voice_setup')
        if str(exc) in MESSAGES:
            error.update(code=str(exc), message=MESSAGES[str(exc)])
            try:
                atomic_json(PRIVATE / (stamp_key + '-failure.json'), {'code': str(exc)})
            except (OSError, ValueError):
                # The original failure must still terminate the visible job.
                pass
        fallback = None
        if kind == 'asr' and source == 'huggingface' and _remote_unavailable(exc):
            fallback = mirror_offer(profile)
            error['message'] = 'Hugging Face недоступен. Можно импортировать ZIP или папку с моделью.'
        elif source == 'yandex' and _remote_unavailable(exc):
            error['message'] = 'Яндекс Диск недоступен. Повторите попытку или импортируйте ZIP или папку с моделью.'
        elif isinstance(exc, asr_sources.ASRSourceError):
            error['message'] = str(exc)
        details = {'asr_mirror': fallback} if kind == 'asr' else {}
        store.terminal_failure(key, error=error['message'], diagnostic=error, **details)
    finally:
        if incoming is not None:
            try:
                incoming.unlink(missing_ok=True)
            except OSError:
                pass
        locks.close()
        with _lock:
            _sources.pop(key, None)
            _controls.pop(key, None)
            _threads.pop(key, None)
