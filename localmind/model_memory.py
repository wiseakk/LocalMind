"""Inference leases and conservative, verified Ollama VRAM lifecycle."""
from contextlib import contextmanager
from dataclasses import asdict, dataclass
import json
from pathlib import Path
from threading import RLock

import httpx
from .paths import CONFIG, atomic_json, ordinary_tree


@dataclass(frozen=True)
class RetentionPolicy:
    keep_alive_seconds: int = 300
    cleanup_temporary: bool = True
    unload_previous: bool = False

    def __post_init__(self):
        if type(self.keep_alive_seconds) is not int or not 0 <= self.keep_alive_seconds <= 900:
            raise ValueError('Хранение модели: от 0 до 900 секунд.')
        if type(self.cleanup_temporary) is not bool or type(self.unload_previous) is not bool:
            raise ValueError('Политика требует явного выбора.')


class ModelMemory:
    def __init__(self, path=None):
        self.path = Path(path or CONFIG / 'memory-retention.json')
        self.lock = RLock()
        self.uses = {}
        self.policy = RetentionPolicy()
        self.last_cleanup = None
        try:
            ordinary_tree(self.path)
            self.policy = RetentionPolicy(**json.loads(self.path.read_text(encoding='utf-8')))
        except (OSError, ValueError, TypeError):
            pass

    @contextmanager
    def using(self, name):
        from .generation import GenerationSettings
        GenerationSettings(name)
        with self.lock:
            self.uses[name] = self.uses.get(name, 0) + 1
        try:
            yield
        finally:
            with self.lock:
                self.uses[name] -= 1
                if not self.uses[name]:
                    del self.uses[name]

    def configure(self, **values):
        policy = RetentionPolicy(**values)
        with self.lock:
            atomic_json(self.path, asdict(policy))
            self.policy = policy
        return self.status()

    @contextmanager
    def test_model(self, name):
        """Caller holds the inference slot, including failure cleanup."""
        try:
            yield
        finally:
            try:
                self._cleanup_locked(name, reason='temporary')
            except Exception:
                with self.lock:
                    self.last_cleanup = {'model': name, 'state': 'unverified', 'reason': 'Проверка очистки недоступна.'}

    def status(self):
        with self.lock:
            return {'policy': asdict(self.policy), 'being_used': dict(self.uses),
                    'last_cleanup': self.last_cleanup,
                    'notice': 'Inactive — не выбрана в LocalMind. /api/ps не доказывает простой других клиентов. Автоочистка общего Ollama пропускается.'}

    def cleanup(self, name, *, reason='temporary', user_confirmed=False):
        from .agent import _inference_slot
        # All entry points, including selection and benchmark, serialize on this
        # lock. Call cleanup only after releasing their lease.
        with _inference_slot():
            return self._cleanup_locked(name, reason=reason, user_confirmed=user_confirmed)

    def _cleanup_locked(self, name, *, reason='temporary', user_confirmed=False):
        from .generation import GenerationSettings
        from .model_manager import manager, ollama_json
        from .ollama_storage import exclusive_managed
        GenerationSettings(name)
        with self.lock:
            explanation = None
            if self.uses.get(name):
                explanation = 'Модель используется запросом LocalMind.'
            elif name == manager.active:
                explanation = 'Текущая активная модель сохранена.'
            elif reason == 'temporary' and not self.policy.cleanup_temporary and not user_confirmed:
                explanation = 'Очистка временных моделей отключена.'
            elif reason == 'switch' and not self.policy.unload_previous and not user_confirmed:
                explanation = 'Выгрузка предыдущей модели отключена.'
            elif not user_confirmed and not exclusive_managed():
                explanation = 'Внешние запросы общего Ollama нельзя исключить. Автовыгрузка пропущена.'
            if explanation:
                result = {'model': name, 'state': 'skipped', 'reason': explanation}
            else:
                try:
                    tags = ollama_json('GET', 'tags').get('models')
                    valid_models = lambda rows: isinstance(rows, list) and all(
                        isinstance(m, dict) and isinstance(m.get('name', m.get('model')), str) for m in rows)
                    if not valid_models(tags) or not any(m.get('name', m.get('model')) == name for m in tags):
                        raise ValueError('Installed identity unavailable')
                    response = ollama_json('POST', 'generate', {'model': name, 'keep_alive': 0, 'stream': False}, timeout=20)
                    running = ollama_json('GET', 'ps').get('models')
                    installed = ollama_json('GET', 'tags').get('models')
                    if (response.get('done') is not True or not valid_models(running)
                            or any(m.get('name', m.get('model')) == name for m in running)
                            or not valid_models(installed)
                            or not any(m.get('name', m.get('model')) == name for m in installed)):
                        raise ValueError('Unload not verified')
                    result = {'model': name, 'state': 'unloaded_verified', 'installed': True,
                              'source': 'Ollama keep_alive:0 + /api/ps + /api/tags'}
                except (httpx.HTTPError, ValueError, TypeError, KeyError):
                    result = {'model': name, 'state': 'unverified', 'reason': 'Выгрузка или сохранность установленной модели не подтверждены.'}
            self.last_cleanup = result
            return dict(result)


memory = ModelMemory()
