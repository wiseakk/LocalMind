"""Read-only discovery of local Ollama manifests; selection never copies weights."""
import hashlib
import json
import os
from pathlib import Path
import re
from threading import RLock

from .generation import GenerationSettings
from .paths import LLM, PRIVATE, atomic_json, ordinary_tree

DIGEST = re.compile(r'sha256:([a-f0-9]{64})')


def windows_models_setting():
    """Read an updated user setting even if Explorer's environment is stale."""
    if os.name != 'nt':
        return None
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, 'Environment') as key:
            value, kind = winreg.QueryValueEx(key, 'OLLAMA_MODELS')
        return value if kind in (winreg.REG_SZ, winreg.REG_EXPAND_SZ) and isinstance(value, str) else None
    except OSError:
        return None


def checked_root(raw):
    path = Path(os.path.expandvars(str(raw)))
    if (not path.is_absolute() or str(path).startswith(('\\\\', '//')) or '..' in path.parts
            or ':' in str(path)[len(path.drive):] or len(str(path)) > 2048):
        raise ValueError('Нужен локальный абсолютный каталог моделей.')
    ordinary_tree(path)
    return path


def identity(path):
    value = path.stat()
    return [value.st_dev, value.st_ino]


def manifest_models(root):
    """Validate references/lengths and GGUF headers, not multi-GB weight hashes.

    These are discovery candidates, never evidence of compatibility. /tags,
    /show and actual generation establish availability after engine startup.
    """
    base = ordinary_tree(root / 'manifests')
    if not base.is_dir():
        return []
    models, pending, visited = [], [base], 0
    while pending:
        folder = pending.pop()
        with os.scandir(ordinary_tree(folder)) as entries:
            for entry in entries:
                visited += 1
                if visited > 4096:
                    raise ValueError('Слишком много объектов в каталоге manifests.')
                path = Path(entry.path)
                try:
                    ordinary_tree(path)
                    if entry.is_dir(follow_symlinks=False):
                        if len(path.relative_to(base).parts) < 5:
                            pending.append(path)
                        continue
                    parts = path.relative_to(base).parts
                    if not 4 <= len(parts) <= 5 or not entry.is_file(follow_symlinks=False) or path.stat().st_size > 1024**2:
                        continue
                    raw = path.read_bytes()
                    data = json.loads(raw)
                    if data.get('schemaVersion') != 2 or not isinstance(data.get('layers'), list):
                        continue
                    layers = [data['config'], *data['layers']]
                    if len(layers) > 128:
                        continue
                    has_weights = False
                    for layer in layers:
                        digest = DIGEST.fullmatch(layer['digest'])
                        if not digest or type(layer.get('size')) is not int or not 0 <= layer['size'] <= 128 * 1024**3:
                            raise ValueError('Некорректная ссылка на blob.')
                        blob = ordinary_tree(root / 'blobs' / ('sha256-' + digest[1]))
                        if not blob.is_file() or blob.stat().st_size != layer['size']:
                            raise ValueError('Файлы модели не полны.')
                        if layer.get('mediaType') == 'application/vnd.ollama.image.model':
                            with blob.open('rb') as source:
                                if source.read(4) != b'GGUF':
                                    raise ValueError('Формат весов не подтверждён.')
                            has_weights = True
                    if not has_weights:
                        continue
                    prefix = parts[2:-1] if parts[:2] == ('registry.ollama.ai', 'library') else parts[:-1]
                    name = '/'.join(prefix) + ':' + parts[-1]
                    GenerationSettings(name)
                    models.append({'name': name, 'manifest_sha256': hashlib.sha256(raw).hexdigest()})
                except (OSError, ValueError, TypeError, KeyError, AttributeError):
                    continue
    return sorted(models, key=lambda row: row['name'])


class ModelStores:
    def __init__(self, owned=None, *, profile=None, environment=None, registry=windows_models_setting, selection=None):
        self.owned = Path(owned or LLM)
        self.profile = Path(profile or Path.home())
        self.environment = environment if environment is not None else os.environ
        self.registry = registry
        self.selection = Path(selection or PRIVATE / 'engine-storage.json')
        self.lock = RLock()

    def _saved(self):
        if not self.selection.exists():
            return None
        try:
            path = ordinary_tree(self.selection)
            if path.stat().st_size > 8192:
                raise ValueError()
            value = json.loads(path.read_text(encoding='utf-8'))
            root = checked_root(value['path'])
            if value.get('version') != 1 or not root.is_dir() or identity(root) != value['identity']:
                raise ValueError()
            return root
        except (OSError, ValueError, KeyError, TypeError):
            return None

    def discover(self):
        with self.lock:
            saved = self._saved()
            roots = [('Сохранённое хранилище', saved), ('OLLAMA_MODELS', self.environment.get('OLLAMA_MODELS')),
                     ('OLLAMA_MODELS (Windows)', self.registry()),
                     ('Ollama — стандартный каталог', self.profile / '.ollama/models'),
                     ('LocalMind', self.owned), ('LocalMind — прежний каталог', self.owned.parent)]
            rows, seen = [], set()
            for source, raw in roots:
                if not raw:
                    continue
                try:
                    root = checked_root(raw)
                    key = str(root).casefold()
                    if key in seen:
                        continue
                    seen.add(key)
                    exists = root.is_dir()
                    models = manifest_models(root) if exists else []
                    if not models and root != self.owned:
                        continue
                    stamp = identity(root) if exists else None
                    identifier = hashlib.sha256(key.encode()).hexdigest()[:24]
                    fingerprint = hashlib.sha256(json.dumps([key, stamp, models], sort_keys=True).encode()).hexdigest()
                    rows.append({'id': identifier, 'path': str(root), 'source': source, 'models': [m['name'] for m in models],
                        'count': len(models), 'fingerprint': fingerprint, 'selected': root == saved,
                        'requires_generation_check': True})
                except (OSError, ValueError):
                    continue
            return rows

    def resolve(self):
        with self.lock:
            saved = self._saved()
            if saved is not None:
                return saved
            rows = self.discover()
            # A lost/replaced saved root is never silently substituted.
            if self.selection.exists() or any(row['count'] for row in rows):
                return None
            return self.owned

    def remember(self, root):
        root = checked_root(root)
        if not root.is_dir():
            raise ValueError('Выбранный каталог моделей недоступен.')
        atomic_json(self.selection, {'version': 1, 'path': str(root), 'identity': identity(root)})

    def select(self, store_id, fingerprint):
        with self.lock:
            row = next((row for row in self.discover() if row['id'] == store_id and row['fingerprint'] == fingerprint), None)
            if row is None:
                raise ValueError('Каталог или файлы моделей изменились. Обновите список.')
            root = checked_root(row['path'])
            if root == self.owned:
                root.mkdir(parents=True, exist_ok=True)
            self.remember(root)
            return root
