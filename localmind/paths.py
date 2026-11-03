"""Application resources are read-only; all durable state belongs to the user.

LOCALMIND_DATA_DIR is an operator/test override, never an HTTP or model argument.
Workers import this stdlib-only module, including from the private release runtime.
"""
import hashlib
import json
import os
from pathlib import Path
import sys
import secrets

APP_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ROOT = Path(os.environ.get('LOCALAPPDATA', Path.home() / '.local/share')) / 'LocalMind'
LOCATION_FILE = DEFAULT_ROOT / 'config' / 'storage-location.json'
ENVIRONMENT_OVERRIDE = bool(os.environ.get('LOCALMIND_DATA_DIR'))


def resolve_data_root():
    explicit = os.environ.get('LOCALMIND_DATA_DIR')
    if explicit:
        return Path(explicit).resolve()
    try:
        for item in (LOCATION_FILE, *LOCATION_FILE.parents):
            if _linked(item):
                raise RuntimeError('Сохранённый путь данных содержит ссылку. Проверьте настройку хранилища.')
        selected = json.loads(LOCATION_FILE.read_text(encoding='utf-8'))['data_root']
        if not isinstance(selected, str) or not Path(selected).is_absolute() or selected.startswith(('\\\\', '//')):
            raise RuntimeError('Сохранённый путь данных недопустим.')
        candidate = Path(selected)
        for item in (candidate, *candidate.parents):
            if _linked(item):
                raise RuntimeError('Сохранённый путь данных содержит ссылку.')
        candidate = candidate.resolve()
        forbidden = [APP_ROOT, *(Path(os.environ[k]).resolve() for k in ('ProgramFiles', 'ProgramFiles(x86)', 'WINDIR') if os.environ.get(k))]
        if candidate == Path(candidate.anchor) or any(candidate == p or p in candidate.parents or candidate in p.parents for p in forbidden):
            raise RuntimeError('Сохранённый путь данных пересекается с приложением или системным каталогом.')
        return candidate
    except (OSError, ValueError, KeyError, TypeError):
        pass
    return DEFAULT_ROOT.resolve()


def _linked(path):
    # lstat observes dangling links and Windows reparse points without following.
    if path.is_symlink():
        return True
    try:
        return bool(getattr(path.lstat(), 'st_file_attributes', 0) & 0x400)
    except FileNotFoundError:
        return False


DATA_ROOT = resolve_data_root()
# Children inherit the resolved choice, including private EXE runtimes.
os.environ.setdefault('LOCALMIND_DATA_DIR', str(DATA_ROOT))
MODELS = DATA_ROOT / 'models'
PRIVATE = DATA_ROOT / 'private'
LLM = MODELS / 'llm'
ASR = MODELS / 'whisper'
TTS = MODELS / 'silero'
CONFIG = DATA_ROOT / 'config'
HISTORY = DATA_ROOT / 'history'
LOGS = DATA_ROOT / 'logs'
DOWNLOADS = DATA_ROOT / 'downloads'


def python_runtime(kind='core'):
    release = APP_ROOT / 'runtime' / kind / 'python.exe'
    if release.is_file():
        return release
    if getattr(sys, 'frozen', False):
        raise RuntimeError('Приватный Python runtime отсутствует. Восстановите установку LocalMind.')
    return Path(sys.executable)


def ordinary_tree(path):
    """Never follow junctions/symlinks during automatic migration/import."""
    path = Path(path)
    for item in (path, *path.parents):
        if _linked(item):
            raise ValueError('Ресурс содержит ссылку или reparse point.')
    return path


def atomic_json(path, data):
    path = ordinary_tree(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.' + secrets.token_hex(8) + '.tmp')
    ordinary_tree(temporary)
    try:
        with temporary.open('x', encoding='utf-8') as stream:
            json.dump(data, stream, ensure_ascii=False, indent=2, allow_nan=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def legacy_preferences_plan(source=APP_ROOT, destination=DATA_ROOT):
    """Preview fixed preference files without reading values into the UI."""
    source, destination = ordinary_tree(source), ordinary_tree(destination)
    rows = []
    for old, new in (('.env', '.env'), ('results/private/active-model.json', 'private/active-model.json')):
        origin, target = ordinary_tree(source / old), ordinary_tree(destination / new)
        if origin.is_file() and not target.exists():
            rows.append({'source': str(origin), 'target': str(target), 'bytes': origin.stat().st_size,
                         'sha256': hashlib.sha256(origin.read_bytes()).hexdigest()})
    return rows


def _publish_migrated(path, content):
    """Publish exclusively: a setting created during preview always wins."""
    path = ordinary_tree(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = ordinary_tree(path.with_name(path.name + '.' + secrets.token_hex(8) + '.tmp'))
    try:
        with temporary.open('x', encoding='utf-8') as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.link(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def migrate_legacy(source=APP_ROOT, destination=DATA_ROOT, *, consent_assets=False,
                   consent=False, reviewed_plan=None):
    """Import benign preferences only after a reviewed, explicitly accepted plan.

    Incomplete copies have no marker and are safely retried. Existing user files
    win. Do not search other worktrees or personal directories implicitly.
    """
    source, destination = ordinary_tree(source), ordinary_tree(destination)
    if consent is not True:
        return []
    if reviewed_plan is None or reviewed_plan != legacy_preferences_plan(source, destination):
        raise ValueError('План переноса настроек изменился. Просмотрите его повторно.')
    destination.mkdir(parents=True, exist_ok=True)
    copied = []
    env = source / '.env'
    if env.is_file() and not (destination / '.env').exists():
        from dotenv import dotenv_values
        allowed = {'OLLAMA_MODEL', 'WHISPER_MODEL', 'LOCALMIND_PORT', 'OLLAMA_URL'}
        values = {k: v for k, v in dotenv_values(ordinary_tree(env)).items()
                  if k in allowed and v and '\n' not in v and '\r' not in v}
        # JSON quoted dotenv values prevent an old value injecting another key.
        target = ordinary_tree(destination / '.env')
        _publish_migrated(target, '\n'.join(k + '=' + json.dumps(v) for k, v in values.items()))
        copied.append('.env')
    active = source / 'results/private/active-model.json'
    target = destination / 'private/active-model.json'
    if active.is_file() and not target.exists():
        from .generation import GenerationSettings
        previous = json.loads(ordinary_tree(active).read_text(encoding='utf-8'))
        name = previous['model']
        GenerationSettings(name)
        controls = {}
        for key, values in previous.get('generation', {}).items() if isinstance(previous.get('generation'), dict) else ():
            if isinstance(values, dict):
                try:
                    validated = GenerationSettings(key, **values)
                    controls[key] = {k: v for k, v in validated.to_dict().items() if k != 'model'}
                except (TypeError, ValueError):
                    continue
        _publish_migrated(target, json.dumps({'model': name, 'generation': controls}, ensure_ascii=False, allow_nan=False))
        copied.append('active-model')
    old_models = source / 'models'
    if consent_assets and old_models.is_dir():
        raise ValueError('Для ресурсов используйте план миграции в настройках хранилища.')
    atomic_json(destination / 'migration.json', {'version': 2, 'permissions_migrated': False,
                                               'assets_copied': consent_assets})
    return copied
