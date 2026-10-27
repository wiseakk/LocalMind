"""FastAPI server for browser terminal and future hardware satellite."""
import hmac
import logging
import os
import tempfile
from pathlib import Path
from typing import Annotated

from fastapi import FastAPI, File, Header, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from .settings import ROOT, settings
from .agent import reply
from .devices import device_catalog

log = logging.getLogger('localmind.voice')

app = FastAPI(title='LocalMind', version='0.1.1', docs_url=None, redoc_url=None)

class ChatRequest(BaseModel):
    text: str = Field(min_length=1, max_length=2000)
    history: list[dict] = Field(default_factory=list, max_length=8)

def authorize(key: str | None):
    if settings.key and not hmac.compare_digest(key or '', settings.key):
        raise HTTPException(401, 'Неверный ключ доступа')

@app.get('/')
def home():
    return FileResponse(ROOT / 'static' / 'index.html')

@app.get('/api/info')
def info(x_localmind_key: Annotated[str | None, Header()] = None):
    authorize(x_localmind_key)
    return {'name': 'LocalMind', 'version': '0.1.0',
            'demo': settings.demo, 'model': settings.model,
            'devices': device_catalog(), 'voice_available': _voice_installed()}

def _voice_installed():
    try:
        import faster_whisper  # noqa: F401
        return True
    except ImportError:
        return False

@app.post('/api/chat')
def chat(data: ChatRequest, x_localmind_key: Annotated[str | None, Header()] = None):
    authorize(x_localmind_key)
    return reply(data.text, data.history)

@app.post('/api/transcribe')
async def transcribe(audio: Annotated[UploadFile, File()],
                     x_localmind_key: Annotated[str | None, Header()] = None):
    authorize(x_localmind_key)
    suffix = Path(audio.filename or '').suffix.lower()
    if suffix not in ('.webm', '.ogg', '.mp4', '.wav', '.m4a'):
        raise HTTPException(415, 'Поддерживаются webm, ogg, mp4, wav, m4a')
    data = await audio.read(8 * 1024 * 1024 + 1)
    if len(data) > 8 * 1024 * 1024:
        raise HTTPException(413, 'Аудио слишком большое')
    if len(data) < 1024:
        raise HTTPException(422, 'Запись пустая или слишком короткая. Попробуй говорить 3–5 секунд.')
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        raise HTTPException(503, 'Для локального распознавания установи requirements-voice.txt')
    # Lazy-load heavy model once; model downloaded on first use.
    if not hasattr(app.state, 'whisper'):
        app.state.whisper = WhisperModel(settings.whisper_model, device='cpu', compute_type='int8')
    path = None
    try:
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as temp:
            path = temp.name
            temp.write(data)
        segments, _ = app.state.whisper.transcribe(path, language='ru', vad_filter=True)
        text = ' '.join(segment.text.strip() for segment in segments).strip()
        log.info('STT OK: %d bytes, format=%s, text_length=%d', len(data), suffix, len(text))
        return {'text': text}
    except Exception as exc:
        log.exception('STT ERROR: format=%s, size=%d bytes, error=%s: %s', suffix, len(data), type(exc).__name__, exc)
        raise HTTPException(422, 'Не удалось распознать запись. Подробности ошибки в PowerShell с сервером.') from exc
    finally:
        if path and os.path.exists(path):
            os.unlink(path)
