"""GUI setup shares the same authenticated loopback boundary as chat."""
from typing import Literal
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
import httpx
from . import resource_setup
from .model_manager import manager, ollama_json
from .paths import APP_ROOT

router = APIRouter(prefix='/api/setup')


@router.get('')
def setup_status():
    from .offline_model import manifest
    try:
        tags = ollama_json('GET', 'tags').get('models', [])
        ollama = {'state': 'ready', 'active': manager.active,
                  'active_installed': any(m.get('name') == manager.active for m in tags if isinstance(m, dict)),
                  'installed': [m['name'] for m in tags if isinstance(m, dict) and isinstance(m.get('name'), str)]}
    except (httpx.HTTPError, ValueError, TypeError):
        ollama = {'state': 'unavailable', 'message': 'Запустите Ollama или восстановите его установку.'}
    try:
        offline_model = manifest()
    except (OSError, ValueError):
        offline_model = None
    from .model_catalog import disk_status
    return {'voice': resource_setup.status(), 'ollama': ollama, 'offline_model': offline_model,
            'offline_disk': disk_status() if offline_model else None,
            'offline_bundle': (APP_ROOT / 'offline-assets').is_dir()}


class ResourceRequest(BaseModel):
    kind: Literal['asr', 'tts']
    profile: Literal['cpu-fast', 'balanced', 'gpu-quality'] = 'balanced'


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
        return resource_setup.start(data.kind, data.profile)
    except (OSError, ValueError) as exc:
        raise HTTPException(409, str(exc) if isinstance(exc, ValueError) else 'Хранилище приложения недоступно.')


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
