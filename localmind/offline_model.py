"""Import a build-declared GGUF into local Ollama, without activating it."""
import hashlib
import json
import re
import threading
import time
import uuid
import httpx
from .paths import APP_ROOT, ordinary_tree
from .download_store import store
from .download_errors import record_download_error

_lock = threading.RLock()
_controls = {}


def manifest():
    path = APP_ROOT / 'config/offline_model.json'
    if not path.is_file():
        return None
    data = json.loads(ordinary_tree(path).read_text(encoding='utf-8'))
    if (not isinstance(data, dict) or data.get('model') != 'localmind-offline:1.0'
            or not re.fullmatch('[a-f0-9]{64}', str(data.get('sha256', '')))
            or type(data.get('bytes')) is not int or not 1000000 <= data['bytes'] <= 32 * 1024**3
            or not isinstance(data.get('license'), str) or not 1 <= len(data['license']) <= 200):
        raise ValueError('Манифест офлайн-модели повреждён. Восстановите установку.')
    return data


def artifact_fingerprint(data):
    return hashlib.sha256(json.dumps({key: data.get(key) for key in
        ('model', 'bytes', 'sha256', 'license')}, sort_keys=True).encode()).hexdigest()


def start(accept_license, *, expected_artifact=None, acknowledge_unknown_disk=False, retry=False):
    data = manifest()
    if not data or accept_license is not True:
        raise ValueError('Подтвердите лицензию модели из офлайн-комплекта.')
    fingerprint = artifact_fingerprint(data)
    if retry and fingerprint != expected_artifact:
        raise ValueError('Комплект или лицензия изменились. Подтвердите актуальную карточку.')
    from .model_catalog import disk_status, GIB
    disk = disk_status()
    if disk['free'] is None and not acknowledge_unknown_disk:
        raise ValueError('Не удалось проверить диск Ollama. Подтверждение доступно в экспертном режиме.')
    if disk['free'] is not None and disk['free'] < data['bytes'] * 1.1 + GIB:
        raise ValueError('Недостаточно места в хранилище Ollama.')
    from .model_manager import manager
    if manager.active == data['model']:
        raise ValueError('Активная модель не перезаписывается импортом. Сначала выберите другую модель.')
    key, event = uuid.uuid4().hex, threading.Event()
    job = {'id': key, 'kind': 'llm_offline', 'model': data['model'], 'status': 'starting', 'layers': {},
           'display_name': data.get('display_name', 'Лёгкая резервная/тестовая модель · Qwen 2.5 0.5B'),
           'destination': disk.get('path'), 'destination_source': disk.get('status'),
           'accepted_artifact': fingerprint, 'acknowledge_unknown_disk': acknowledge_unknown_disk,
           'created_at': time.time(), 'total': data['bytes'], 'completed': 0, 'error': None}
    with _lock:
        store.insert(job)
        _controls[key] = event
        try:
            threading.Thread(target=_import, args=(key, data, event), daemon=True, name='localmind-offline-import').start()
        except RuntimeError:
            _controls.pop(key, None)
            store.update(key, status='failed', error='Не удалось начать импорт. Повторите позже.')
            raise ValueError('Не удалось начать импорт.') from None
    return store.snapshot(key)


def cancel(key):
    with _lock:
        event = _controls.get(key)
        if not event or store.snapshot(key)['status'] not in ('starting', 'downloading', 'verifying', 'cancelling'):
            raise ValueError('Задача уже завершена.')
        event.set()
        store.update(key, status='cancelling')
    return store.snapshot(key)


def _import(key, data, event):
    from .agent import _local_ollama_url
    from .model_manager import installed_detail
    try:
        if event.is_set():
            raise InterruptedError()
        source = ordinary_tree(APP_ROOT / 'offline-llm/model.gguf')
        with source.open('rb') as stream:
            if stream.read(4) != b'GGUF' or source.stat().st_size != data['bytes']:
                raise ValueError('Файл несовместим с офлайн-комплектом')
            stream.seek(0)
            if hashlib.file_digest(stream, 'sha256').hexdigest() != data['sha256']:
                raise ValueError('Контрольная сумма GGUF не совпадает')
            if event.is_set():
                raise InterruptedError()
            stream.seek(0)
            def chunks():
                sent = 0
                while chunk := stream.read(1048576):
                    if event.is_set():
                        raise InterruptedError()
                    sent += len(chunk)
                    store.update(key, status='downloading', completed=sent)
                    yield chunk
            # Blob paths, digest, filename and model name are build-owned.
            with httpx.Client(timeout=httpx.Timeout(60, connect=3), trust_env=False, follow_redirects=False) as client:
                blob_url = _local_ollama_url() + '/api/blobs/sha256:' + data['sha256']
                check = client.head(blob_url)
                if check.status_code == 404:
                    with client.stream('POST', blob_url, content=chunks(), headers={'Content-Length': str(data['bytes'])}) as response:
                        response.raise_for_status()
                        received = 0
                        for chunk in response.iter_bytes():
                            received += len(chunk)
                            if received > 16384:
                                raise ValueError('Oversized blob response')
                else:
                    check.raise_for_status()
                    store.update(key, completed=data['bytes'])
                if event.is_set():
                    raise InterruptedError()
                store.update(key, status='verifying')
                done, buffer, count = False, b'', 0
                if event.is_set():
                    raise InterruptedError()
                with client.stream('POST', _local_ollama_url() + '/api/create', json={'model': data['model'],
                    'files': {'model.gguf': 'sha256:' + data['sha256']}, 'stream': True}) as result:
                    result.raise_for_status()
                    for chunk in result.iter_bytes():
                        if event.is_set():
                            raise InterruptedError()
                        count += len(chunk); buffer += chunk
                        if count > 16777216 or len(buffer) > 262144:
                            raise ValueError('Oversized creation stream')
                        while b'\n' in buffer:
                            line, buffer = buffer.split(b'\n', 1)
                            if not line.strip():
                                continue
                            event_data = json.loads(line)
                            if event_data.get('error'):
                                raise ValueError(str(event_data['error'])[:1000])
                            done = done or event_data.get('status') == 'success'
                if not done or buffer.strip():
                    raise ValueError('Interrupted creation stream')
        detail = installed_detail(data['model'])
        if detail.get('weight_sha256') != data['sha256']:
            raise ValueError('Файл несовместим: SHA-256 установленного GGUF не совпадает с офлайн-комплектом или не подтверждён Ollama.')
        with _lock:
            if event.is_set():
                raise InterruptedError()
            store.update(key, status='succeeded', ready=True, completed=data['bytes'], digest=detail.get('digest'))
    except InterruptedError:
        store.update(key, status='cancelled_unverified', error='Поток импорта закрыт. Состояние Ollama проверьте в установленных моделях.')
    except Exception as exc:
        diagnostic = record_download_error(exc, 'offline_import')
        store.update(key, status='failed', error=diagnostic['message'], diagnostic=diagnostic)
    finally:
        with _lock:
            _controls.pop(key, None)
