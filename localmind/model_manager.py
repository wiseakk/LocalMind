"""Local installed models, transactional selection and request-owned observations."""
from contextvars import ContextVar
import json
import math
import os
import re
import time
from pathlib import Path
from threading import Lock

import httpx
from .generation import GenerationSettings
from .paths import PRIVATE
from .settings import ROOT, settings

observation = ContextVar('ollama_observation', default=None)
_last_lock = Lock()
_last = None


def positive(value, zero=False):
    return (isinstance(value, (int, float)) and not isinstance(value, bool)
            and (0 <= value <= 2**63 - 1) and math.isfinite(value)
            and (value >= 0 if zero else value > 0))


def response_metrics(data):
    def milliseconds(key):
        return round(data[key] / 1e6, 3) if positive(data.get(key), zero=True) else None
    count, duration = data.get('eval_count'), data.get('eval_duration')
    return {'actual_model': data.get('model') if isinstance(data.get('model'), str) else None,
            'tokens_per_second': round(count * 1e9 / duration, 3) if positive(count) and positive(duration) else None,
            'eval_count': count if positive(count, zero=True) else None,
            'load_ms': milliseconds('load_duration'), 'ollama_ms': milliseconds('total_duration')}


def observe(data):
    observation.set(response_metrics(data))


def record_last(result):
    global _last
    with _last_lock:
        _last = {key: result.get(key) for key in ('actual_model', 'metrics', 'latency_ms', 'engine')}


def local_model(item):
    name = item.get('name')
    try:
        GenerationSettings(name)
    except (ValueError, TypeError):
        return False
    return positive(item.get('size')) and not item.get('remote_host') and not item.get('remote_model')


def ollama_json(method, endpoint, body=None, timeout=4):
    from .agent import _local_ollama_url
    with httpx.Client(timeout=httpx.Timeout(timeout, connect=3), trust_env=False, follow_redirects=False) as client:
        deadline, content = time.monotonic() + timeout, bytearray()
        with client.stream(method, _local_ollama_url() + '/api/' + endpoint, json=body) as response:
            response.raise_for_status()
            for chunk in response.iter_bytes():
                content.extend(chunk)
                if len(content) > 2097152 or time.monotonic() > deadline:
                    raise ValueError('Ответ Ollama превысил объём или время.')
        data = json.loads(content)
        if not isinstance(data, dict) or data.get('error'):
            raise ValueError('Некорректный ответ локального Ollama.')
        return data


def installed_detail(name, tags=None):
    GenerationSettings(name)
    tags = tags if tags is not None else ollama_json('GET', 'tags').get('models', [])
    if not isinstance(tags, list):
        raise ValueError('Некорректный список моделей.')
    installed = next((m for m in tags if isinstance(m, dict) and m.get('name') == name and local_model(m)), None)
    if installed is None:
        raise ValueError('Выберите установленную локальную модель.')
    show = ollama_json('POST', 'show', {'model': name})
    if show.get('remote_host') or show.get('remote_model'):
        raise ValueError('Облачные модели отключены.')
    capabilities = show.get('capabilities', [])
    if not isinstance(capabilities, list) or 'completion' not in capabilities:
        raise ValueError('Модель не подтверждает поддержку чата. Обновите Ollama.')
    info = show.get('model_info', {})
    if not isinstance(info, dict) or not isinstance(show.get('details', {}), dict):
        raise ValueError('Некорректные сведения модели.')
    # Parse only the digest from Ollama's generated Modelfile. Never open or
    # execute the daemon-supplied path. This binds a HF pull to the reviewed GGUF.
    modelfile = show.get('modelfile')
    digest_match = re.search(r'^FROM\s+[^\r\n]*sha256[-:]([a-f0-9]{64})(?:["\s]|$)', modelfile, re.M) if isinstance(modelfile, str) else None
    return {**installed, 'details': show.get('details', installed.get('details', {})),
            'capabilities': capabilities,
            'weight_sha256': digest_match[1] if digest_match else None,
            'max_context': next((v for k, v in info.items() if k.endswith('.context_length')), None)}


def placement(item):
    size, vram = item.get('size'), item.get('size_vram')
    if not positive(size) or not positive(vram, zero=True) or vram > size:
        return 'unknown'
    return 'CPU' if vram == 0 else 'GPU' if vram == size else 'hybrid'


class ModelManager:
    def __init__(self, path=None):
        self.path = Path(path or PRIVATE / 'active-model.json')
        self._lock = Lock()
        self._active = settings.model
        self._capabilities = {}
        try:
            name = json.loads(self.path.read_text(encoding='utf-8'))['model']
            GenerationSettings(name)
            self._active = name
        except (OSError, ValueError, KeyError, TypeError):
            pass

    @property
    def active(self):
        with self._lock:
            return self._active

    def select(self, name):
        from . import agent
        # Same inference lock as chat; concurrent switches serialize and failure
        # leaves both the in-memory and durable selection unchanged.
        with agent._inference_slot():
            expected = installed_detail(name)
            data = ollama_json('POST', 'chat', {'model': name, 'stream': False, 'think': False,
                'messages': [{'role': 'user', 'content': 'Ответь одним словом: привет'}],
                'options': {'num_ctx': 4096, 'num_predict': 16, 'temperature': 0}, 'keep_alive': 300}, timeout=60)
            actual = data.get('model')
            if not actual or not data.get('message', {}).get('content', '').strip() or data.get('done') is not True:
                raise ValueError('Проверка генерации не пройдена. Предыдущий выбор сохранён.')
            # Response identity must refer to an installed local model as well.
            actual_detail = installed_detail(actual)
            if expected.get('digest') and expected.get('digest') != actual_detail.get('digest'):
                raise ValueError('Ollama ответил другой моделью; выбор сохранён.')
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.path.with_suffix('.tmp')
            try:
                temporary.write_text(json.dumps({'model': name}), encoding='utf-8')
                os.replace(temporary, self.path)
            finally:
                temporary.unlink(missing_ok=True)
            with self._lock:
                self._active = name
                self._capabilities[name] = expected.get('capabilities', [])
            agent._resident_model = name
            return {'active': name, 'health': response_metrics(data)}

    def inventory(self):
        rows = []
        tags = ollama_json('GET', 'tags')
        if not isinstance(tags.get('models'), list):
            raise ValueError('Некорректный список моделей.')
        try:
            loaded = ollama_json('GET', 'ps').get('models', [])
            if not isinstance(loaded, list) or any(not isinstance(item, dict) for item in loaded):
                loaded = None
        except (httpx.HTTPError, ValueError):
            loaded = None
        for model in tags.get('models', [])[:100]:
            if not isinstance(model, dict) or not isinstance(model.get('name'), str):
                continue
            row = {k: model.get(k) for k in ('name', 'size', 'digest', 'details')}
            try:
                detail = installed_detail(model['name'], tags.get('models', []))
                with self._lock:
                    self._capabilities[model['name']] = detail.get('capabilities', [])
                row.update({k: detail.get(k) for k in ('details', 'capabilities', 'max_context')}, selectable=True)
            except (httpx.HTTPError, ValueError, TypeError):
                row.update(selectable=False, warning='Локальная совместимость чата не подтверждена.')
            running = next((m for m in loaded or [] if m.get('name') == row['name']), None)
            row.update(placement=placement(running) if running else 'unknown' if loaded is None else 'unloaded',
                       size_vram=running.get('size_vram') if running else None,
                       context_length=running.get('context_length') if running else None)
            raw_details = row.get('details') if isinstance(row.get('details'), dict) else {}
            row['details'] = {k: raw_details.get(k) for k in
                              ('family', 'parameter_size', 'quantization_level', 'format')}
            rows.append(row)
        with _last_lock:
            last = dict(_last) if _last else None
        active = self.active
        return {'models': rows, 'default': active, 'active': active,
                'last_response': last, 'local_only': True, 'placement_source': 'Ollama /api/ps'}

    def native_tools_supported(self, name):
        # Populated by explicit inventory/selection. Unknown uses strict schema
        # on the same model, without adding discovery I/O to every action.
        with self._lock:
            return 'tools' in self._capabilities.get(name, [])


manager = ModelManager()
