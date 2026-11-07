"""GUI setup shares the same authenticated loopback boundary as chat."""
import asyncio
from pathlib import Path
import shutil
import tempfile
from threading import Lock
from typing import Literal
from fastapi import APIRouter, HTTPException, Request
from starlette.concurrency import run_in_threadpool
from starlette.requests import ClientDisconnect
from pydantic import BaseModel, Field
import httpx
from . import resource_setup
from .model_manager import manager, ollama_json
from .paths import APP_ROOT
from .asr_sources import archive_limit

router = APIRouter(prefix='/api/setup')
_asr_import_slot = Lock()


@router.get('')
def setup_status():
    from .offline_model import manifest
    from .product_state import read
    try:
        product = read()
    except (OSError, ValueError) as exc:
        raise HTTPException(409, str(exc) if isinstance(exc, ValueError) else 'Настройки недоступны. Проверьте каталог данных.')
    try:
        tags = ollama_json('GET', 'tags').get('models', [])
        installed = [m['name'] for m in tags if isinstance(m, dict) and isinstance(m.get('name'), str)]
        ollama = {'state': 'ready', 'active': manager.active if manager.active in installed else None,
                  'saved_model': manager.active,
                  'active_verified': manager.verified(tags),
                  'active_installed': any(m.get('name') == manager.active for m in tags if isinstance(m, dict)),
                  'installed': [m['name'] for m in tags if isinstance(m, dict) and isinstance(m.get('name'), str)]}
    except (httpx.HTTPError, ValueError, TypeError):
        from .ollama_runtime import runtime
        engine = runtime.status()
        ollama = {'state': 'unavailable', 'message': engine['message'] if engine['state'] != 'ready'
                  else 'Связь с движком потеряна. Нажмите «Повторить запуск движка».'}
    try:
        offline_model = manifest()
    except (OSError, ValueError):
        offline_model = None
    from .model_catalog import disk_status
    from .ollama_runtime import runtime
    from .hardware import hardware_status
    return {**product, 'voice': resource_setup.status(), 'ollama': ollama, 'engine': runtime.status(),
            'model_storage': runtime.model_stores(),
            'hardware': hardware_status(), 'model_disk': disk_status(), 'offline_model': offline_model,
            'offline_disk': disk_status() if offline_model else None,
            'offline_bundle': (APP_ROOT / 'offline-assets').is_dir()}


@router.post('/runtime/retry')
def retry_engine():
    from .ollama_runtime import runtime
    return runtime.retry()


class ModelStoreSelection(BaseModel):
    model_config = {'extra': 'forbid'}
    store_id: str = Field(pattern=r'^[a-f0-9]{24}$')
    fingerprint: str = Field(pattern=r'^[a-f0-9]{64}$')


@router.post('/runtime/storage')
def select_engine_storage(data: ModelStoreSelection):
    from .ollama_runtime import runtime
    from .model_catalog import downloads
    from .agent import _inference_slot
    def select():
        with _inference_slot(), downloads.lock:
            if any(job['status'] in ('starting', 'downloading', 'verifying', 'cancelling') for job in downloads.snapshot()):
                raise ValueError('Дождитесь завершения или отмены загрузок перед сменой каталога моделей.')
            return runtime.select_store(data.store_id, data.fingerprint)
    return setup_operation(select)


class OnboardingRequest(BaseModel):
    model_config = {'extra': 'forbid'}
    completed: bool | None = None
    step: int | None = Field(default=None, strict=True, ge=0, le=5)
    profile: Literal['cpu-fast', 'balanced', 'gpu-quality'] = 'cpu-fast'
    skip_asr: bool = False
    skip_tts: bool = False


class TourRequest(BaseModel):
    model_config = {'extra': 'forbid'}
    completed: bool = False
    skipped: bool = False


class PreferencesRequest(BaseModel):
    model_config = {'extra': 'forbid'}
    theme: Literal['dark', 'light'] | None = None
    reduce_motion: bool | None = None
    low_performance: bool | None = None
    voice_profile: Literal['cpu-fast', 'balanced', 'gpu-quality'] | None = None
    tts_voice: Literal['ru_RU-denis-medium', 'silero-v5_6-ru', 'chatterbox-v3-ru'] | None = None
    speak: bool | None = None


@router.get('/preferences')
def product_preferences():
    from .product_state import read
    return setup_operation(read)


@router.post('/onboarding')
def save_onboarding(data: OnboardingRequest):
    from .product_state import update
    return setup_operation(lambda: update('onboarding', data.model_dump(exclude_unset=True, exclude_none=True)))


@router.post('/tour')
def save_tour(data: TourRequest):
    from .product_state import update
    return setup_operation(lambda: update('tour', data.model_dump()))


@router.post('/preferences')
def save_product_preferences(data: PreferencesRequest):
    from .product_state import update
    return setup_operation(lambda: update('preferences', data.model_dump(exclude_none=True)))


class ResourceRequest(BaseModel):
    kind: Literal['asr', 'tts']
    profile: Literal['cpu-fast', 'balanced', 'gpu-quality'] = 'balanced'
    source: Literal['huggingface', 'yandex', 'yandex_disk', 'direct_https'] = 'huggingface'
    fingerprint: str | None = Field(default=None, pattern=r'^[a-f0-9]{64}$')


class OfflineModelRequest(BaseModel):
    accept_license: bool
    acknowledge_unknown_disk: bool = False


@router.post('/offline-model')
def offline_model(data: OfflineModelRequest):
    from .offline_model import start
    try:
        return start(data.accept_license, acknowledge_unknown_disk=data.acknowledge_unknown_disk)
    except (OSError, ValueError) as exc:
        raise HTTPException(409, str(exc) if isinstance(exc, ValueError) else 'Импорт недоступен. Проверьте состав комплекта.')


@router.post('/voice')
def prepare_voice(data: ResourceRequest):
    try:
        if data.source == 'huggingface':
            return resource_setup.start(data.kind, data.profile)
        return resource_setup.start(data.kind, data.profile, source=data.source, fingerprint=data.fingerprint)
    except (OSError, ValueError) as exc:
        raise HTTPException(409, str(exc) if isinstance(exc, ValueError) else 'Хранилище приложения недоступно.')


@router.post('/asr-import')
async def import_asr(request: Request, profile: Literal['cpu-fast', 'balanced', 'gpu-quality'],
                     mode: Literal['zip', 'directory']):
    """Accept bytes explicitly chosen by the browser. No filesystem paths enter this API."""
    from .paths import ordinary_tree

    if request.headers.get('content-type') != 'application/octet-stream':
        raise HTTPException(415, 'Выберите ZIP или папку Whisper.')
    assets = resource_setup.assets_for('asr', profile)
    required = sum(asset['bytes'] for asset in assets)
    limit = archive_limit(assets) if mode == 'zip' else required
    length = request.headers.get('content-length', '')
    if not length.isascii() or not length.isdecimal() or len(length) > 10:
        raise HTTPException(411, 'Для импорта нужен известный размер файлов.')
    length = int(length)
    if not 0 < length <= limit or mode == 'directory' and length != required:
        raise HTTPException(413, 'Размер не соответствует выбранной модели Whisper.')
    if not resource_setup.dependencies('asr'):
        raise HTTPException(409, 'Компоненты распознавания отсутствуют. Восстановите LocalMind установщиком.')
    if not _asr_import_slot.acquire(blocking=False):
        raise HTTPException(429, 'Другой импорт ещё передаёт файлы.')
    incoming = None
    try:
        folder = ordinary_tree(resource_setup.MODELS / 'whisper' / '.incoming')
        folder.mkdir(parents=True, exist_ok=True)
        if shutil.disk_usage(folder).free < length + required:
            raise HTTPException(409, 'Недостаточно места для проверки и установки модели.')
        with tempfile.NamedTemporaryFile(dir=folder, prefix='asr-', delete=False) as stream:
            incoming = Path(stream.name)
            received = 0
            chunks = request.stream().__aiter__()
            async with asyncio.timeout(600):
                while True:
                    chunk = await asyncio.wait_for(anext(chunks, None), timeout=15)
                    if chunk is None:
                        break
                    received += len(chunk)
                    if received > length:
                        raise HTTPException(413, 'Превышен размер импорта.')
                    await run_in_threadpool(stream.write, chunk)
        if received != length:
            raise HTTPException(400, 'Импорт получен не полностью.')
        result = resource_setup.start('asr', profile, source='local', incoming=incoming, mode=mode)
        incoming = None  # The queued worker owns this temporary file now.
        return result
    except (TimeoutError, ClientDisconnect):
        raise HTTPException(408, 'Передача файлов прервана. Выберите файл или папку снова.') from None
    except (OSError, ValueError) as exc:
        raise HTTPException(409, str(exc) if isinstance(exc, ValueError) else 'Хранилище модели недоступно.') from None
    finally:
        try:
            if incoming is not None:
                incoming.unlink(missing_ok=True)
        finally:
            _asr_import_slot.release()


class StoragePlanRequest(BaseModel):
    destination: str
    source: Literal['current', 'legacy_models', 'ollama_models'] = 'current'


class StorageApplyRequest(BaseModel):
    plan_id: str
    consent: bool = False


class OllamaStorageRequest(BaseModel):
    destination: str
    consent: bool = False


class GenerationRequest(BaseModel):
    model: str
    temperature: float = Field(default=0.2, ge=0, le=2, allow_inf_nan=False)
    reasoning: Literal['off', 'on', 'auto'] = 'off'
    context_tokens: Literal[2048, 4096, 8192] = 4096
    response_tokens: Literal[64, 256, 768, 1536, 2048] = 768
    keep_alive_seconds: int = 300


class RetentionRequest(BaseModel):
    keep_alive_seconds: int = 300
    cleanup_temporary: bool = True
    unload_previous: bool = False


class UnloadRequest(BaseModel):
    model: str
    confirm_no_external_requests: bool = False


def setup_operation(action):
    try:
        return action()
    except (OSError, ValueError, TypeError, httpx.HTTPError) as exc:
        raise HTTPException(409, str(exc) if isinstance(exc, ValueError) else 'Операция недоступна. Проверьте путь, права и состояние Ollama.')


@router.get('/storage')
def storage_status():
    from . import storage, ollama_storage
    return {'localmind': storage.status(), 'ollama': ollama_storage.storage_status()}


@router.post('/storage/plan')
def storage_plan(data: StoragePlanRequest):
    from .storage import plan
    return setup_operation(lambda: plan(data.destination, data.source))


@router.post('/storage/apply')
def storage_apply(data: StorageApplyRequest):
    from .storage import apply
    return setup_operation(lambda: apply(data.plan_id, data.consent))


@router.post('/storage/ollama-instructions')
def ollama_instructions(data: OllamaStorageRequest):
    from .ollama_storage import instructions
    return setup_operation(lambda: instructions(data.destination))


@router.post('/storage/ollama-start')
def ollama_start(data: OllamaStorageRequest):
    from .ollama_storage import start_managed
    return setup_operation(lambda: start_managed(data.destination, data.consent))


@router.get('/generation')
def generation_settings():
    return {'active': manager.active, 'generation': manager.generation()}


@router.post('/generation')
def save_generation(data: GenerationRequest):
    return setup_operation(lambda: manager.save_generation(data.model_dump(exclude={'model'}), expected_model=data.model))


@router.get('/memory')
def memory_status():
    from .model_memory import memory
    return memory.status()


@router.post('/memory')
def save_retention(data: RetentionRequest):
    from .model_memory import memory
    return setup_operation(lambda: memory.configure(**data.model_dump()))


@router.post('/memory/unload')
def unload_memory(data: UnloadRequest):
    from .model_memory import memory
    if not data.confirm_no_external_requests:
        raise HTTPException(409, 'Подтвердите отсутствие запросов других приложений к этой модели.')
    return setup_operation(lambda: memory.cleanup(data.model, reason='manual', user_confirmed=True))
