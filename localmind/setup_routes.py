"""GUI setup shares the same authenticated loopback boundary as chat."""
from typing import Literal
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
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
    return {'voice': resource_setup.status(), 'ollama': ollama, 'offline_model': offline_model,
            'offline_bundle': (APP_ROOT / 'offline-assets').is_dir()}


class ResourceRequest(BaseModel):
    kind: Literal['asr', 'tts']


class OfflineModelRequest(BaseModel):
    accept_license: bool


@router.post('/offline-model')
def offline_model(data: OfflineModelRequest):
    from .offline_model import start
    try:
        return start(data.accept_license)
    except (OSError, ValueError):
        raise HTTPException(409, 'Импорт недоступен. Проверьте состав комплекта и подтвердите лицензию.')


@router.post('/voice')
def prepare_voice(data: ResourceRequest):
    try:
        return resource_setup.start(data.kind)
    except (OSError, ValueError) as exc:
        raise HTTPException(409, str(exc) if isinstance(exc, ValueError) else 'Хранилище приложения недоступно.')
