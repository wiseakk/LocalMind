"""Application resources are read-only; all durable state belongs to the user.

LOCALMIND_DATA_DIR is an operator/test override, never an HTTP or model argument.
Workers import this stdlib-only module, including from the private release runtime.
"""
import json
import os
from pathlib import Path
import shutil
import sys

APP_ROOT = Path(__file__).resolve().parents[1]
DATA_ROOT = Path(os.environ.get('LOCALMIND_DATA_DIR') or
                 Path(os.environ.get('LOCALAPPDATA', Path.home() / '.local/share')) / 'LocalMind').resolve()
MODELS = DATA_ROOT / 'models'
PRIVATE = DATA_ROOT / 'private'


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
        if item.exists() and (item.is_symlink() or getattr(item.stat(), 'st_file_attributes', 0) & 0x400):
            raise ValueError('Ресурс содержит ссылку или reparse point.')
    return path


def atomic_json(path, data):
    path = ordinary_tree(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.tmp')
    ordinary_tree(temporary)
    try:
        temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def migrate_legacy(source=APP_ROOT, destination=DATA_ROOT):
    """Idempotent copy, no deletion and no migration of permissions or secrets.

    Incomplete copies have no marker and are safely retried. Existing user files
    win. Do not search other worktrees or personal directories implicitly.
    """
    source, destination = ordinary_tree(source), ordinary_tree(destination)
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
        temporary = ordinary_tree(destination / '.env.migration.tmp')
        try:
            temporary.write_text('\n'.join(k + '=' + json.dumps(v) for k, v in values.items()), encoding='utf-8')
            os.replace(temporary, target)
        finally:
            temporary.unlink(missing_ok=True)
        copied.append('.env')
    active = source / 'results/private/active-model.json'
    target = destination / 'private/active-model.json'
    if active.is_file() and not target.exists():
        from .generation import GenerationSettings
        name = json.loads(ordinary_tree(active).read_text(encoding='utf-8'))['model']
        GenerationSettings(name)
        atomic_json(target, {'model': name})
        copied.append('active-model')
    old_models = source / 'models'
    if old_models.is_dir():
        for item in old_models.rglob('*'):
            ordinary_tree(item)
            if item.is_file() and not item.name.endswith(('.partial', '.tmp')):
                target = destination / 'models' / item.relative_to(old_models)
                ordinary_tree(target)
                if not target.exists():
                    target.parent.mkdir(parents=True, exist_ok=True)
                    partial = target.with_suffix(target.suffix + '.partial')
                    ordinary_tree(partial)
                    shutil.copyfile(item, partial)
                    os.replace(partial, target)
    atomic_json(destination / 'migration.json', {'version': 1, 'permissions_migrated': False})
    return copied
