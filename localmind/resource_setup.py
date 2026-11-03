"""Declared, hash-pinned online/offline assets; no caller-controlled URLs/paths."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import threading
import uuid
import httpx
from .paths import APP_ROOT, MODELS, PRIVATE, atomic_json, ordinary_tree, python_runtime
from .download_store import store
from .voice_diagnostics import MESSAGES, classify_voice_error

MANIFEST = json.loads((APP_ROOT / 'config/voice_resources.json').read_text(encoding='utf-8'))
_controls = {}
_lock = threading.Lock()
ASR_PROFILES = {'cpu-fast': 'base', 'balanced': 'small', 'gpu-quality': 'medium'}


def assets_for(kind, profile='balanced'):
    if kind not in ('asr', 'tts') or profile not in ASR_PROFILES:
        raise ValueError('Неизвестный ресурс или профиль.')
    prefix = 'whisper/' + ASR_PROFILES[profile] + '/' if kind == 'asr' else 'silero/'
    return [a for a in MANIFEST['assets'] if a['path'].startswith(prefix)]


def verification_key(kind, profile='balanced'):
    return kind if kind != 'asr' or profile == 'balanced' else kind + '-' + profile


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
        rows.append({'kind': kind, 'profile': profile if kind == 'asr' else None,
                     'required': kind != 'asr' or profile == default_stt_profile(),
                     'model': ASR_PROFILES[profile] if kind == 'asr' else 'Silero · xenia', 'state': state,
                     'action': 'Восстановить установку LocalMind' if state == 'dependency_missing' else 'Подготовить голос'})
    return rows


def manifest_digest():
    return hashlib.sha256(json.dumps(MANIFEST, sort_keys=True).encode()).hexdigest()


def signatures(assets):
    return {a['path']: [ordinary_tree(MODELS / a['path']).stat().st_size,
                       (MODELS / a['path']).stat().st_mtime_ns] for a in assets}


def file_digest(path):
    h = hashlib.sha256()
    with ordinary_tree(path).open('rb') as stream:
        while chunk := stream.read(1048576):
            h.update(chunk)
    return h.hexdigest()


def start(kind, profile='balanced'):
    if kind not in ('asr', 'tts'):
        raise ValueError('Неизвестный ресурс.')
    assets_for(kind, profile)  # Validate before a job/thread or download is created.
    if not dependencies(kind):
        raise ValueError('Компоненты голоса отсутствуют. Восстановите LocalMind установщиком; Python и pip не нужны.')
    key, cancel = uuid.uuid4().hex, threading.Event()
    job = {'id': key, 'kind': kind, 'model': 'Русская речь · ' + ASR_PROFILES[profile] if kind == 'asr' else 'Silero · xenia',
           'profile': profile if kind == 'asr' else None,
           'destination': str(MODELS / 'whisper' / ASR_PROFILES[profile] if kind == 'asr' else MODELS / 'silero'),
           'status': 'starting', 'completed': 0, 'total': 0, 'error': None, 'layers': {}}
    with _lock:
        if any(store.snapshot(existing).get('kind') == kind and
               (kind != 'asr' or store.snapshot(existing).get('profile', 'balanced') == profile)
               for existing in _controls):
            raise ValueError('Подготовка этого ресурса уже выполняется. Смотрите «Загрузки».')
        store.insert(job)
        _controls[key] = cancel
        try:
            threading.Thread(target=_prepare, args=(key, kind, cancel, profile), daemon=True, name='localmind-assets').start()
        except RuntimeError:
            _controls.pop(key, None)
            store.update(key, status='failed', error='Не удалось запустить подготовку. Повторите позже.')
            raise ValueError('Не удалось запустить подготовку. Повторите позже.') from None
    return store.snapshot(key)


def cancel(key):
    with _lock:
        event = _controls.get(key)
        if not event or store.snapshot(key)['status'] not in ('starting', 'queued', 'downloading', 'verifying', 'cancelling'):
            raise ValueError('Задача уже завершена.')
        event.set()
        store.update(key, status='cancelling')
    return store.snapshot(key)


def _prepare(key, kind, cancel, profile='balanced'):
    stamp_key = verification_key(kind, profile)
    try:
        assets = assets_for(kind, profile)
        total, completed = sum(a['bytes'] for a in assets), 0
        MODELS.mkdir(parents=True, exist_ok=True)
        if shutil.disk_usage(MODELS).free < total + 100 * 1048576:
            raise OSError('Недостаточно места')
        for asset in assets:
            if cancel.is_set():
                raise InterruptedError()
            target = ordinary_tree(MODELS / asset['path'])
            target.parent.mkdir(parents=True, exist_ok=True)
            if not target.is_file() or file_digest(target) != asset['sha256']:
                partial = ordinary_tree(target.with_suffix(target.suffix + '.partial'))
                bundled = ordinary_tree(APP_ROOT / 'offline-assets' / asset['path'])
                count, digest = 0, hashlib.sha256()
                try:
                    # Offline and online consume the exact same pinned manifest.
                    if bundled.is_file():
                        stream = bundled.open('rb')
                        chunks = iter(lambda: stream.read(1048576), b'')
                        context = stream
                    else:
                        context = httpx.stream('GET', asset['url'], timeout=30, follow_redirects=True, trust_env=False)
                    with context as source, partial.open('wb') as output:
                        if not bundled.is_file():
                            source.raise_for_status()
                            chunks = source.iter_bytes(1048576)
                        for chunk in chunks:
                            if cancel.is_set():
                                raise InterruptedError()
                            count += len(chunk)
                            if count > asset['bytes']:
                                raise ValueError('Размер ресурса не совпадает с манифестом')
                            digest.update(chunk); output.write(chunk)
                            store.update(key, status='downloading', total=total, completed=completed + count)
                    if count != asset['bytes'] or digest.hexdigest() != asset['sha256']:
                        raise ValueError('Контрольная сумма ресурса не совпадает')
                    os.replace(partial, target)
                finally:
                    partial.unlink(missing_ok=True)
            completed += asset['bytes']
            store.update(key, completed=completed, total=total)
        if cancel.is_set():
            raise InterruptedError()
        store.update(key, status='verifying')
        # Always use private python.exe, never the frozen GUI launcher.
        result = subprocess.run([str(python_runtime()), '-m', 'localmind.resource_worker', kind, profile],
                                cwd=APP_ROOT, shell=False, capture_output=True, timeout=180,
                                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        if result.returncode:
            try:
                code = json.loads(result.stdout)['code']
            except (ValueError, KeyError):
                code = 'library_incompatible'
            raise RuntimeError(code)
        with _lock:
            if cancel.is_set():
                raise InterruptedError()
            atomic_json(PRIVATE / (stamp_key + '-verified.json'), {'manifest': manifest_digest(), 'files': signatures(assets)})
            ordinary_tree(PRIVATE / (stamp_key + '-failure.json')).unlink(missing_ok=True)
            store.update(key, status='succeeded', ready=True)
    except InterruptedError:
        store.update(key, status='cancelled', error='Загрузка прервана. Можно повторить; проверенные файлы сохраняются.')
    except Exception as exc:
        from .download_errors import record_download_error
        error = record_download_error(exc, 'voice_setup')
        if str(exc) in MESSAGES:
            error.update(code=str(exc), message=MESSAGES[str(exc)])
            atomic_json(PRIVATE / (stamp_key + '-failure.json'), {'code': str(exc)})
        store.update(key, status='failed', error=error['message'], diagnostic=error)
    finally:
        with _lock:
            _controls.pop(key, None)
