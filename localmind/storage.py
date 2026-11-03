"""Explicit, resumable, copy-only storage relocation; never a model tool."""
import hashlib
from contextlib import contextmanager
import os
from pathlib import Path
import secrets
import shutil
from threading import RLock
import time

from . import paths

_lock = RLock()
_plans = {}
_pending_root = None
_activity_lock = RLock()
_mutations = 0
_migrating = False


def begin_mutation():
    global _mutations
    with _activity_lock:
        if _migrating or _pending_root is not None:
            raise ValueError('Данные копируются или ожидают перезапуска. Перезапустите LocalMind перед дальнейшими изменениями.')
        _mutations += 1


def end_mutation():
    global _mutations
    with _activity_lock:
        _mutations -= 1


@contextmanager
def migration_guard():
    global _migrating
    with _activity_lock:
        if _migrating or _pending_root is not None or _mutations:
            raise ValueError('Дождитесь завершения запросов или перезапустите LocalMind после переноса.')
        _migrating = True
    try:
        from .server import store as requests
        from .model_benchmark import benchmarks
        if requests.running() or benchmarks.running():
            raise ValueError('Дождитесь завершения ответа или теста перед копированием.')
        yield
    finally:
        with _activity_lock:
            _migrating = False


def protected_roots():
    with _lock:
        return tuple({Path(p['destination']) for p in _plans.values()} | ({_pending_root} if _pending_root else set()))


def checked_destination(raw):
    if not isinstance(raw, str) or not 1 <= len(raw) <= 1024 or any(c in raw for c in '\r\n\x00'):
        raise ValueError('Укажите абсолютный локальный каталог данных.')
    candidate = Path(raw)
    if not candidate.is_absolute() or raw.startswith(('\\\\', '//')) or '..' in candidate.parts:
        raise ValueError('Нужен абсолютный локальный путь без ссылок и сетевых дисков.')
    paths.ordinary_tree(candidate)
    candidate = candidate.resolve()
    blocked = [paths.APP_ROOT, *(Path(os.environ[k]).resolve() for k in ('ProgramFiles', 'ProgramFiles(x86)', 'WINDIR') if os.environ.get(k))]
    if candidate == Path(candidate.anchor) or any(candidate == p or p in candidate.parents or candidate in p.parents for p in blocked):
        raise ValueError('Выберите отдельный каталог данных вне приложения и системных каталогов.')
    if os.name == 'nt':
        import ctypes
        if ctypes.windll.kernel32.GetDriveTypeW(candidate.anchor) == 4:
            raise ValueError('Сетевые диски не поддерживаются.')
    return candidate


def digest(path):
    paths.ordinary_tree(path)
    value = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            value.update(block)
    return value.hexdigest()


def files(source):
    paths.ordinary_tree(source)
    if not source.is_dir():
        return []
    result = []
    pending = [source]
    candidates = []
    while pending:
        directory = paths.ordinary_tree(pending.pop())
        with os.scandir(directory) as entries:
            for entry in entries:
                item = paths.ordinary_tree(Path(entry.path))
                relative = item.relative_to(source)
                if relative.parts[0] == 'webcache':
                    continue
                if entry.is_dir(follow_symlinks=False):
                    pending.append(item)
                elif entry.is_file(follow_symlinks=False):
                    candidates.append(item)
    for item in sorted(candidates):
        paths.ordinary_tree(item)
        relative = item.relative_to(source)
        # Web cache isn't portable; open transfer/temp files are not complete assets.
        if (relative.parts[0] in ('webcache',) or item.name.casefold() in ('lock', 'lockfile', 'singletonlock')
                or item.name.casefold().endswith(('.tmp', '.partial', '.lock'))):
            continue
        if item.is_file():
            result.append({'relative': str(relative), 'bytes': item.stat().st_size, 'sha256': digest(item)})
    return result


def free_space(destination):
    ancestor = destination
    while not ancestor.exists() and ancestor != ancestor.parent:
        ancestor = ancestor.parent
    paths.ordinary_tree(ancestor)
    return shutil.disk_usage(ancestor).free


def status():
    return {'data_root': str(paths.DATA_ROOT), 'default_root': str(paths.DEFAULT_ROOT),
            'pending_root': str(_pending_root) if _pending_root else None,
            'environment_override': paths.ENVIRONMENT_OVERRIDE,
            'directories': {name: str(getattr(paths, name)) for name in
                            ('LLM', 'ASR', 'TTS', 'CONFIG', 'HISTORY', 'LOGS', 'DOWNLOADS', 'PRIVATE')},
            'legacy_assets_available': (paths.APP_ROOT / 'models').is_dir(),
            'notice': 'Смена применяется после перезапуска. Исходные файлы сохраняются. История браузера остаётся в его профиле.'}


def plan(raw, source_kind='current'):
    destination = checked_destination(raw)
    source = paths.DATA_ROOT if source_kind == 'current' else paths.APP_ROOT / 'models'
    if source_kind == 'ollama_models':
        from .ollama_storage import storage_status
        observed = storage_status()
        if not observed['confirmed'] or not observed['path']:
            raise ValueError('Сначала подтвердите каталог работающего Ollama.')
        source = Path(observed['path'])
    if source_kind not in ('current', 'legacy_models', 'ollama_models'):
        raise ValueError('Неизвестный источник.')
    if source_kind == 'legacy_models':
        destination = paths.DATA_ROOT / 'models'
    paths.ordinary_tree(source)
    if destination == source or source in destination.parents or destination in source.parents:
        raise ValueError('Источник и назначение не должны пересекаться.')
    listing = files(source)
    required = 0
    for row in listing:
        target = paths.ordinary_tree(destination / row['relative'])
        if target.exists():
            if not target.is_file() or digest(target) != row['sha256']:
                raise ValueError('Конфликт файлов в назначении: ' + row['relative'])
        else:
            required += row['bytes']
    available = free_space(destination)
    if required + 16 * 1024 * 1024 > available:
        raise ValueError('Недостаточно места в выбранном каталоге.')
    key = secrets.token_hex(16)
    entry = {'id': key, 'source': str(source), 'destination': str(destination), 'files': listing,
             'bytes': sum(row['bytes'] for row in listing), 'required_bytes': required, 'free_bytes': available,
             'source_kind': source_kind, 'expires': time.monotonic() + 600}
    with _lock:
        for stale in [k for k, v in _plans.items() if v['expires'] < time.monotonic()]:
            _plans.pop(stale)
        if len(_plans) >= 8:
            raise ValueError('Слишком много планов. Повторите позже.')
        _plans[key] = entry
    return {k: v for k, v in entry.items() if k not in ('files', 'expires')}


def apply(key, consent=False):
    global _pending_root
    if consent is not True:
        raise ValueError('Подтвердите копирование и смену расположения.')
    from .agent import _inference_slot
    from .download_store import store, ACTIVE
    # Relocation has one writer; active requests and transfer workers must finish.
    with migration_guard(), _lock, store.lock, _inference_slot():
        entry = _plans.get(key)
        if entry is None or entry['expires'] < time.monotonic():
            raise ValueError('План истёк. Проверьте каталог повторно.')
        if any(j.get('status') in ACTIVE for j in store.snapshot()):
            raise ValueError('Дождитесь завершения загрузок перед копированием.')
        source, destination = Path(entry['source']), Path(entry['destination'])
        paths.ordinary_tree(source)
        paths.ordinary_tree(destination)
        if files(source) != entry['files']:
            raise ValueError('Данные изменились. Сформируйте новый план.')
        if free_space(destination) < entry['required_bytes'] + 16 * 1024 * 1024:
            raise ValueError('Недостаточно места для копирования.')
        destination.mkdir(parents=True, exist_ok=True)
        for row in entry['files']:
            origin = paths.ordinary_tree(source / row['relative'])
            target = paths.ordinary_tree(destination / row['relative'])
            if target.exists():
                if digest(target) != row['sha256']:
                    raise ValueError('Конфликт файлов; источник сохранён: ' + row['relative'])
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            temporary = paths.ordinary_tree(target.with_name(target.name + '.' + secrets.token_hex(8) + '.partial'))
            try:
                with origin.open('rb') as src, temporary.open('xb') as dst:
                    shutil.copyfileobj(src, dst, 1024 * 1024)
                    dst.flush()
                    os.fsync(dst.fileno())
                if digest(temporary) != row['sha256']:
                    raise ValueError('Проверка копии не пройдена; источник сохранён.')
                # Exclusive publication avoids replacing a file created during copy.
                os.link(temporary, target)
            finally:
                temporary.unlink(missing_ok=True)
        if files(source) != entry['files']:
            raise ValueError('Данные изменились во время копирования. Повторите план перед сменой пути.')
        if entry['source_kind'] == 'current':
            paths.atomic_json(paths.LOCATION_FILE, {'data_root': str(destination), 'version': 1})
            _pending_root = destination
        _plans.pop(key, None)
    return {'state': 'copied_verified', 'restart_required': entry['source_kind'] == 'current',
            'destination': str(destination), 'source_preserved': True}
