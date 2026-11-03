"""Intentional Hub metadata discovery; only server-constructed allowlisted pulls.

No credentials, repository scripts, arbitrary URLs, paths, Modelfiles or HTML.
"""
import asyncio
import copy
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
from threading import Lock, Thread
import time
import uuid

import httpx
from .settings import ROOT
from .download_store import JobStore, store as shared_store
from .download_errors import record_download_error
from .model_manager import installed_detail, ollama_json, positive

REPO = re.compile(r'[A-Za-z0-9][A-Za-z0-9_-]{0,95}/[A-Za-z0-9][A-Za-z0-9._-]{0,95}')
QUANTS = frozenset(('Q4_K_M', 'Q5_K_M', 'Q8_0', 'Q4_0', 'Q5_0', 'Q6_K'))
# Conservative text-only subset. Version support is an estimate until local
# tags/show and a successful health check confirm this particular artifact.
ARCHITECTURES = {'llama': '0.3.0', 'qwen2': '0.3.0', 'qwen3': '0.6.6', 'gemma2': '0.3.0'}
GIB = 1073741824
CURATED = json.loads((ROOT / 'config/model_catalog.json').read_text(encoding='utf-8'))


def repo_id(value):
    if not isinstance(value, str) or not REPO.fullmatch(value) or '..' in value or '--' in value:
        raise ValueError('Недопустимый Hugging Face repository ID.')
    return value


def version_tuple(value):
    match = re.match(r'^(\d+)\.(\d+)\.(\d+)', str(value))
    return tuple(map(int, match.groups())) if match else None


def hub_json(path, params=None):
    # path is constructed solely from a validated ID or the fixed models path.
    with httpx.Client(timeout=15, trust_env=False, follow_redirects=False) as client:
        with client.stream('GET', 'https://huggingface.co/api/models' + path, params=params) as response:
            if response.status_code == 429:
                raise ValueError('Hugging Face ограничил частоту запросов. Повторите позже.')
            response.raise_for_status()
            content = bytearray()
            deadline = time.monotonic() + 20
            for chunk in response.iter_bytes():
                content.extend(chunk)
                if len(content) > 2097152 or time.monotonic() > deadline:
                    raise ValueError('Метаданные превышают допустимый объём или время.')
            return json.loads(content)


def search_hub(query):
    if not isinstance(query, str) or not 1 <= len(query.strip()) <= 100:
        raise ValueError('Введите от 1 до 100 символов для поиска.')
    data = hub_json('', {'search': query.strip(), 'filter': 'gguf', 'limit': 12, 'full': 'true'})
    if not isinstance(data, list):
        raise ValueError('Некорректный ответ Hub.')
    rows = []
    for item in data[:12]:
        try:
            identity = repo_id(item.get('id'))
        except (ValueError, AttributeError):
            continue
        rows.append({'id': identity, 'publisher': identity.split('/')[0],
                     'source_url': 'https://huggingface.co/' + identity,
                     'available': not (item.get('private') or item.get('gated') or item.get('disabled'))})
    return rows


def disk_status():
    # The local Ollama daemon may run as a different user or with another store.
    # Never substitute this project's disk or assume the current user's home.
    configured = os.getenv('OLLAMA_MODELS')
    if os.getenv('LOCALMIND_OLLAMA_STORAGE_VERIFIED', '').lower() != 'true' or not configured:
        return {'free': None, 'status': 'unknown: хранилище Ollama не подтверждено оператором'}
    try:
        path = Path(configured)
        if not path.is_absolute() or not path.is_dir():
            raise OSError()
        return {'free': shutil.disk_usage(path).free, 'status': 'configured Ollama storage'}
    except OSError:
        return {'free': None, 'status': 'unavailable'}


def memory_estimate(row, context):
    size = row.get('size')
    kv = None
    if all(positive(row.get(k)) for k in ('kv_layers', 'kv_heads', 'head_dim')):
        kv = int(2 * row['kv_layers'] * row['kv_heads'] * row['head_dim'] * 2 * context)
    known = positive(size) and kv is not None
    minimum = int(size + kv + GIB) if known else None
    recommended = int(minimum * 1.2 + 2 * GIB) if known else None
    return {'weights': size, 'kv_cache': kv, 'runtime_overhead': GIB,
            'ram_minimum': minimum, 'ram_recommended': recommended,
            'vram_minimum': minimum, 'vram_recommended': recommended,
            'target_12gb_fit': minimum <= 12 * GIB - 2 * GIB if minimum else None,
            'context': context, 'assumptions': 'Estimate only: FP16 K/V, single sequence, 1 GiB runtime; recommended adds 20% and 2 GiB for ASR. CPU RAM and full GPU placement alternatives, not a placement measurement.'}


def enrich(row, context=4096):
    if context not in (2048, 4096, 8192):
        raise ValueError('Допустимый контекст: 2048, 4096 или 8192.')
    row = copy.deepcopy(row)
    identity = {key: row.get(key) for key in ('id', 'source', 'revision', 'license', 'quantization', 'size', 'architecture', 'max_context', 'artifact', 'artifact_sha256')}
    row['fingerprint'] = hashlib.sha256(json.dumps(identity, sort_keys=True, allow_nan=False).encode()).hexdigest()
    row['disk'] = disk_status()
    row['memory'] = memory_estimate(row, context)
    row['recommended_context'] = min(4096, row.get('max_context') or 4096)
    row['benchmark_notice'] = 'Нет проверенных benchmark для этого варианта. Популярность не является точностью.'
    version = None
    try:
        version = ollama_json('GET', 'version').get('version')
    except (httpx.HTTPError, ValueError):
        pass
    row['ollama_version'] = version
    minimum = row.get('minimum_ollama') or ARCHITECTURES.get(row.get('architecture'))
    compatible = (minimum and version_tuple(version) and version_tuple(version) >= version_tuple(minimum))
    row['compatibility'] = 'estimated' if compatible else 'blocked'
    row['warning'] = ('Совместимость предполагается по архитектуре и версии. Проверка конкретного файла — после загрузки; GPU размещение не гарантируется.'
                      if compatible else 'Архитектура или версия Ollama не подтверждена. Загрузка заблокирована.')
    if row.get('blocked_reason'):
        row['compatibility'] = 'blocked'
        row['warning'] = row['blocked_reason']
    if row.get('max_context') and context > row['max_context']:
        row.update(compatibility='blocked', warning='Контекст превышает предел модели.')
    return row


def curated(context=4096):
    return [enrich(row, context) for row in CURATED]


def hub_variants(identity, context=4096):
    identity = repo_id(identity)
    data = hub_json('/' + identity, {'blobs': 'true'})
    if not isinstance(data, dict) or data.get('id') != identity:
        raise ValueError('Метаданные репозитория не совпадают с запросом.')
    gguf = data.get('gguf') or {}
    card = data.get('cardData') or {}
    siblings = data.get('siblings') or []
    if not isinstance(gguf, dict) or not isinstance(card, dict) or not isinstance(siblings, list):
        raise ValueError('Некорректные метаданные Hub.')
    siblings = [item for item in siblings if isinstance(item, dict)]
    blocked = None
    if data.get('private') or data.get('gated') or data.get('disabled'):
        blocked = 'Закрытая/gated модель: доступ в приложении не поддерживается.'
    if data.get('pipeline_tag') not in ('text-generation', None):
        blocked = 'Поддерживаются только текстовые chat GGUF.'
    license_name = card.get('license')
    if not isinstance(license_name, str) or not license_name.strip() or len(license_name) > 200:
        blocked = 'Лицензия не указана; проверьте права у издателя.'
    groups = {}
    for file in siblings[:2000]:
        name = file.get('rfilename', '')
        if not isinstance(name, str):
            continue
        lfs = file.get('lfs')
        if lfs is not None and not isinstance(lfs, dict):
            raise ValueError('Некорректные метаданные GGUF.')
        if isinstance(lfs, dict) and lfs.get('sha256') is not None and not re.fullmatch('[a-f0-9]{64}', str(lfs['sha256'])):
            raise ValueError('Некорректная контрольная сумма GGUF в metadata.')
        # Filenames are only inspected as text; never used in a URL or path.
        if not name.lower().endswith('.gguf') or 'mmproj' in name.lower():
            continue
        match = re.search(r'(?:^|[-._])(' + '|'.join(sorted(QUANTS, key=len, reverse=True)) + r')(?=[-._]|$)', name, re.I)
        if match:
            groups.setdefault(match[1].upper(), []).append(file)
    rows = []
    for quant, files in groups.items():
        reason = blocked
        name = files[0]['rfilename']
        if len(files) != 1 or re.search(r'-\d{5}-of-\d{5}', name):
            reason = 'Sharded или неоднозначные GGUF для этой квантизации не поддерживаются.'
        row = {'id': identity, 'name': identity + ' / ' + quant, 'publisher': identity.split('/')[0],
               'source': 'huggingface', 'source_url': 'https://huggingface.co/' + identity,
               'revision': data.get('sha'), 'metadata_date': data.get('lastModified'),
               'artifact': name, 'artifact_sha256': (files[0].get('lfs') or {}).get('sha256'),
               'license': license_name if isinstance(license_name, str) else None,
               'parameters': gguf.get('total') if positive(gguf.get('total')) else None, 'quantization': quant,
               'size': (sum(f['size'] for f in files) if all(positive(f.get('size')) for f in files) else None),
               'architecture': gguf.get('architecture') if isinstance(gguf.get('architecture'), str) else None,
               'max_context': gguf.get('context_length') if positive(gguf.get('context_length')) else None,
               'capabilities': {'chat': 'estimated' if gguf.get('chat_template') else 'unknown',
                                'tools': 'unknown', 'vision': 'unsupported', 'reasoning': 'unknown'},
               'benchmarks': [], 'blocked_reason': reason}
        rows.append(enrich(row, context))
    preference = ('Q4_K_M', 'Q5_K_M', 'Q6_K', 'Q8_0', 'Q4_0', 'Q5_0')
    rows.sort(key=lambda r: (r['compatibility'] == 'blocked', preference.index(r['quantization'])))
    for index, row in enumerate(rows):
        row['recommended'] = index == 0 and row['compatibility'] != 'blocked'
    return rows


def resolve_pull(source, identity, quant, context):
    if quant not in QUANTS:
        raise ValueError('Выберите явную поддерживаемую квантизацию.')
    if source == 'ollama':
        row = next((r for r in curated(context) if r['id'] == identity and r['quantization'] == quant), None)
        reference = identity
    elif source == 'huggingface':
        identity = repo_id(identity)
        row = next((r for r in hub_variants(identity, context) if r['quantization'] == quant), None)
        reference = 'hf.co/' + identity + ':' + quant
    else:
        raise ValueError('Неизвестный источник.')
    if not row or row['compatibility'] == 'blocked':
        raise ValueError('Этот вариант несовместим или недоступен.')
    return reference, row


class DownloadJobs:
    """One bounded pull stream; restarting never resumes it implicitly."""
    def __init__(self, journal=None):
        self.journal = journal or JobStore()
        self.lock = self.journal.lock
        self.jobs = self.journal.jobs
        self.controls = {}

    def start(self, source, identity, quant, context=4096, *, accept_license=False, acknowledge_unknown_disk=False, fingerprint=None):
        if not accept_license:
            raise ValueError('Подтвердите проверку лицензии перед загрузкой.')
        reference, row = resolve_pull(source, identity, quant, context)
        from .model_manager import manager
        if manager.active == reference:
            raise ValueError('Активная модель не перезаписывается загрузкой. Сначала выберите другую установленную модель.')
        if fingerprint != row['fingerprint']:
            raise ValueError('Метаданные, лицензия или вариант изменились. Откройте карточку заново и подтвердите актуальные сведения.')
        disk, size = row['disk'], row.get('size')
        if (disk['free'] is None or not positive(size)) and not acknowledge_unknown_disk:
            raise ValueError('Размер или свободное место неизвестны. Нужно явное подтверждение предупреждения.')
        if positive(size) and disk['free'] is not None and disk['free'] < size * 1.1 + GIB:
            raise ValueError('Недостаточно места в подтверждённом хранилище Ollama.')
        with self.lock:
            if any(j['status'] in ('starting', 'downloading', 'verifying', 'cancelling') for j in self.jobs.values()):
                raise ValueError('Другая загрузка ещё выполняется.')
            if len(self.jobs) >= 32:
                # Evict only completed jobs, never grow an unbounded task log.
                self.jobs.pop(next(iter(self.jobs)))
            key = uuid.uuid4().hex
            self.jobs[key] = {'id': key, 'kind': 'llm', 'model': reference, 'status': 'starting', 'layers': {},
                              'expected_sha256': row.get('artifact_sha256'),
                              'request': {'source': source, 'identity': identity, 'quantization': quant, 'context': context, 'fingerprint': fingerprint, 'accept_license': accept_license, 'acknowledge_unknown_disk': acknowledge_unknown_disk},
                              'error': None, 'cancel_supported': 'disconnect; daemon stop unverified'}
            try:
                self.journal.save()
            except Exception:
                self.jobs.pop(key, None)
                raise
            self.controls[key] = {'loop': None, 'task': None, 'cancel': False}
            try:
                Thread(target=lambda: asyncio.run(self._pull(key, reference)), daemon=True, name='localmind-pull').start()
            except RuntimeError:
                self.jobs.pop(key, None)
                self.controls.pop(key, None)
                self.journal.save()
                raise ValueError('Не удалось запустить обработчик загрузки. Повторите позже.')
            return copy.deepcopy(self.jobs[key])

    def stop_all(self):
        with self.lock:
            keys = list(self.controls)
        for key in keys:
            try:
                self.cancel(key)
            except ValueError:
                pass

    def snapshot(self, key=None):
        with self.lock:
            if getattr(self.journal, 'unavailable', False):
                raise ValueError('Журнал загрузок повреждён или недоступен.')
            if key is not None:
                if key not in self.jobs:
                    raise ValueError('Задача недоступна после перезапуска или истечения срока.')
                return copy.deepcopy(self.jobs[key])
            return [copy.deepcopy(j) for j in self.jobs.values()]

    def update(self, key, **fields):
        with self.lock:
            self.jobs[key].update(fields)
            self.journal.save()

    def cancel(self, key):
        with self.lock:
            if key not in self.controls:
                raise ValueError('Задача уже завершена или недоступна.')
            if self.jobs[key]['status'] not in ('starting', 'downloading', 'verifying', 'cancelling'):
                raise ValueError('Задача уже завершена.')
            control = self.controls[key]
            control['cancel'] = True
            self.jobs[key]['status'] = 'cancelling'
            self.journal.save()
            if control['loop'] and control['task']:
                control['loop'].call_soon_threadsafe(control['task'].cancel)
        return self.snapshot(key)

    async def _pull(self, key, reference):
        from .agent import _local_ollama_url
        with self.lock:
            control = self.controls[key]
            control.update(loop=asyncio.get_running_loop(), task=asyncio.current_task())
            cancelled = control['cancel']
        try:
            if cancelled:
                raise asyncio.CancelledError()
            self.update(key, status='downloading', stage='pull')
            success, buffer, count = False, b'', 0
            async with httpx.AsyncClient(timeout=httpx.Timeout(30, connect=3), trust_env=False, follow_redirects=False) as client:
                async with client.stream('POST', _local_ollama_url() + '/api/pull', json={'model': reference, 'stream': True}) as response:
                    response.raise_for_status()
                    async for chunk in response.aiter_bytes():
                        count += len(chunk)
                        buffer += chunk
                        if len(buffer) > 262144 or count > 16777216:
                            raise ValueError('Oversized progress stream')
                        while b'\n' in buffer:
                            line, buffer = buffer.split(b'\n', 1)
                            if not line.strip():
                                continue
                            event = json.loads(line)
                            if event.get('error'):
                                raise ValueError(str(event['error'])[:2000])
                            digest, total, completed = event.get('digest'), event.get('total'), event.get('completed')
                            if isinstance(digest, str) and re.fullmatch(r'sha256:[a-f0-9]{64}', digest):
                                if positive(total) and positive(completed, zero=True) and completed <= total:
                                    with self.lock:
                                        layers = self.jobs[key]['layers']
                                        if len(layers) >= 128 and digest not in layers:
                                            raise ValueError('Too many layers')
                                        layers[digest] = {'total': total, 'completed': completed}
                                        self.jobs[key].update(total=sum(x['total'] for x in layers.values()), completed=sum(x['completed'] for x in layers.values()))
                                        self.journal.save()
                            if event.get('status') == 'success':
                                success = True
                    if buffer.strip():
                        # A truncated NDJSON record is never a successful download.
                        raise ValueError('Interrupted progress record')
            if not success:
                raise ValueError('Interrupted download')
            self.update(key, status='verifying', stage='installed_verification')
            detail = await asyncio.to_thread(installed_detail, reference)
            expected = self.jobs[key].get('expected_sha256')
            if expected and (not isinstance(expected, str) or not re.fullmatch('[a-f0-9]{64}', expected) or detail.get('weight_sha256') != expected):
                raise ValueError('Файл несовместим: GGUF изменился после подтверждения metadata или его SHA-256 не подтверждён Ollama.')
            with self.lock:
                if control['cancel']:
                    raise asyncio.CancelledError()
                self.update(key, status='succeeded', digest=detail.get('digest'), ready=True, completed=self.jobs[key].get('total', 0))
        except asyncio.CancelledError:
            self.update(key, status='cancelled_unverified', error='Поток закрыт. Остановка скачивания внутри Ollama не подтверждена; общий pull другого клиента может продолжаться.')
        except Exception as exc:
            diagnostic = record_download_error(exc, self.jobs[key].get('stage', 'pull'))
            self.update(key, status='failed', error=diagnostic['message'], diagnostic=diagnostic)
        finally:
            with self.lock:
                self.controls.pop(key, None)


downloads = DownloadJobs(shared_store)
