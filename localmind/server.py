"""Loopback API. Execution is shared by JSON and opt-in NDJSON streaming."""
import asyncio
from concurrent.futures import TimeoutError as FutureTimeout
import hashlib
import hmac
import ipaddress
import json
import threading
import uuid
from typing import Annotated, Literal
from urllib.parse import urlsplit

from fastapi import FastAPI, File, Form, Header, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
import httpx

from .settings import ROOT, settings
from .agent import reply, prepare_reply, complete_reply
from .devices import device_catalog
from .apps import catalog, AppError
from .requests import RequestStore, RequestBusy, RequestConflict
from .voice import VoiceError, voice_status, transcribe_audio, synthesize_speech, MAX_UPLOAD_BYTES

app = FastAPI(title='LocalMind', version='1.0.0', docs_url=None, redoc_url=None, openapi_url=None)
app.mount('/assets', StaticFiles(directory=ROOT / 'static' / 'assets'), name='assets')
store = RequestStore()
LOCAL_HOSTS = frozenset(('127.0.0.1', 'localhost', '::1'))
SERVER_INSTANCE = uuid.uuid4().hex
_body_slots = threading.BoundedSemaphore(4)
BODY_TIMEOUT_SECONDS = 15

class HistoryMessage(BaseModel):
    role: Literal['user', 'assistant']
    content: str = Field(max_length=4000)

class ChatRequest(BaseModel):
    text: str = Field(min_length=1, max_length=2000)
    history: list[HistoryMessage] = Field(default_factory=list, max_length=8)
    actions_authorized: bool = True
    request_id: str | None = Field(default=None, min_length=8, max_length=80, pattern=r'^[a-zA-Z0-9_-]+$')
    response_length: Literal['brief', 'normal', 'detailed'] = 'normal'
    compose_actions: bool = True
    server_instance: str | None = Field(default=None, max_length=32)

class PermissionRequest(BaseModel):
    app_id: str = Field(min_length=1, max_length=100)
    allowed: bool
    fingerprint: str = Field(min_length=32, max_length=256)

class SpeechRequest(BaseModel):
    text: str = Field(min_length=1, max_length=1200)
    voice: Literal['ru_RU-denis-medium'] = 'ru_RU-denis-medium'

def is_loopback_address(host: str) -> bool:
    try:
        return ipaddress.ip_address(host.split('%', 1)[0]).is_loopback
    except ValueError:
        return False

def authorize(key: str | None):
    if settings.key and not hmac.compare_digest(key or '', settings.key):
        raise HTTPException(401, 'Неверный ключ доступа')

def _valid_authority(value: str) -> bool:
    try:
        parsed = urlsplit('http://' + value)
        return (parsed.hostname in LOCAL_HOSTS and parsed.username is None and parsed.password is None
                and parsed.path == '' and parsed.query == '' and parsed.fragment == ''
                and (parsed.port is None or 0 < parsed.port <= 65535))
    except ValueError:
        return False

@app.middleware('http')
async def local_boundary(request: Request, call_next):
    # Peer checks never use proxy headers. start.py disables Uvicorn proxy trust.
    if not is_loopback_address(request.client.host if request.client else ''):
        return JSONResponse({'detail':'LocalMind доступен только с этого компьютера'}, status_code=403)
    authority = request.headers.get('host', '')
    if not _valid_authority(authority):
        return JSONResponse({'detail':'Недопустимый Host'}, status_code=403)
    origin = request.headers.get('origin')
    if origin:
        try:
            parsed = urlsplit(origin)
            good_origin = parsed.scheme == 'http' and parsed.netloc == authority and parsed.path == '' and not parsed.query and not parsed.fragment
        except ValueError:
            good_origin = False
        if not good_origin:
            return JSONResponse({'detail':'Недопустимый Origin'}, status_code=403)
    if request.headers.get('sec-fetch-site') == 'cross-site':
        return JSONResponse({'detail':'Межсайтовые запросы запрещены'}, status_code=403)
    # Reject unauthorized requests before reading/decoding a potentially large upload.
    if request.url.path.startswith('/api/'):
        try:
            authorize(request.headers.get('x-localmind-key'))
        except HTTPException as exc:
            return JSONResponse({'detail':exc.detail},status_code=exc.status_code)
    if request.method == 'POST':
        if not _body_slots.acquire(blocking=False):
            return JSONResponse({'detail':'Слишком много одновременных загрузок'},status_code=429)
        try:
            maximum = MAX_UPLOAD_BYTES + 65536 if request.url.path == '/api/transcribe' else 65536
            body = bytearray()
            async with asyncio.timeout(BODY_TIMEOUT_SECONDS):
                async for chunk in request.stream():
                    body.extend(chunk)
                    if len(body) > maximum:
                        return JSONResponse({'detail':'Запрос слишком большой'},status_code=413)
            request._body = bytes(body)
        except TimeoutError:
            return JSONResponse({'detail':'Превышено время загрузки запроса'},status_code=408)
        finally:
            _body_slots.release()
    response = await call_next(request)
    response.headers['Content-Security-Policy'] = "default-src 'none'; script-src 'self'; style-src 'self' 'unsafe-inline'; font-src 'self'; img-src 'none'; connect-src 'self'; media-src 'self' blob:; base-uri 'none'; frame-ancestors 'none'; form-action 'self'"
    response.headers['X-Content-Type-Options']='nosniff'
    response.headers['Referrer-Policy']='no-referrer'
    response.headers['Cache-Control']='no-store'
    response.headers['Permissions-Policy']='microphone=(self), camera=(), geolocation=()'
    return response

@app.get('/')
def home():
    return FileResponse(ROOT / 'static' / 'index.html')

@app.get('/api/info')
def info(x_localmind_key: Annotated[str | None, Header()] = None):
    authorize(x_localmind_key)
    voice = voice_status()
    return {'name':'LocalMind', 'version':'1.0.0', 'demo':settings.demo, 'model':settings.model,
            'server_instance':SERVER_INSTANCE,
            'devices':device_catalog(), 'voice_available':voice['stt_installed'], 'voice':voice}

def _entry(data: ChatRequest):
    if data.server_instance is not None and data.server_instance != SERVER_INSTANCE:
        raise HTTPException(409,'Сервер перезапущен. Автоматическое повторение действия отменено; проверьте его состояние вручную.')
    payload=data.model_dump()
    payload.pop('request_id')
    fingerprint=hashlib.sha256(json.dumps(payload,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
    try:
        return store.begin(data.request_id, fingerprint,
            lambda:prepare_reply(data.text,[m.model_dump() for m in data.history],data.actions_authorized,data.response_length,data.compose_actions),
            complete_reply)
    except RequestConflict as exc:
        raise HTTPException(409,str(exc)) from exc
    except RequestBusy as exc:
        raise HTTPException(429,str(exc)) from exc

@app.post('/api/chat')
def chat(data:ChatRequest, x_localmind_key: Annotated[str | None, Header()] = None):
    authorize(x_localmind_key)
    try:
        return _entry(data).final.result(timeout=90)
    except FutureTimeout as exc:
        raise HTTPException(504,'Ответ ещё обрабатывается. Повторите с тем же request_id.') from exc

@app.post('/api/chat/stream')
def chat_stream(data:ChatRequest, x_localmind_key: Annotated[str | None, Header()] = None):
    authorize(x_localmind_key)
    entry = _entry(data)
    async def events():
        # result() runs in a separate waiter; cancellation cannot cancel shared futures.
        try:
            initial=await asyncio.to_thread(entry.initial.result,90)
            yield json.dumps({'type':'status','data':initial},ensure_ascii=False)+'\n'
            final=await asyncio.to_thread(entry.final.result,90)
            yield json.dumps({'type':'final','data':final},ensure_ascii=False)+'\n'
        except Exception:
            yield json.dumps({'type':'error','detail':'Не удалось получить ответ. Сохраните request_id для повторного запроса.'},ensure_ascii=False)+'\n'
    return StreamingResponse(events(),media_type='application/x-ndjson',headers={'X-Accel-Buffering':'no'})

@app.post('/api/transcribe')
async def transcribe(audio:Annotated[UploadFile,File()], profile:Annotated[str,Form()]='balanced',
                     x_localmind_key:Annotated[str | None,Header()]=None):
    authorize(x_localmind_key)
    from pathlib import Path
    try:
        data=await audio.read(MAX_UPLOAD_BYTES+1)
        result=await asyncio.to_thread(transcribe_audio,data,Path(audio.filename or '').suffix.lower(),profile)
        return result
    except VoiceError as exc:
        raise HTTPException(exc.status_code,exc.detail) from exc
    finally:
        await audio.close()

@app.post('/api/tts')
def tts(data:SpeechRequest,x_localmind_key:Annotated[str | None,Header()]=None):
    authorize(x_localmind_key)
    try:
        return Response(synthesize_speech(data.text,data.voice),media_type='audio/wav')
    except VoiceError as exc:
        raise HTTPException(exc.status_code,exc.detail) from exc

@app.get('/api/apps')
def apps(x_localmind_key:Annotated[str | None,Header()]=None):
    authorize(x_localmind_key)
    return {'apps':catalog.entries()}

@app.post('/api/apps/refresh')
def refresh_apps(x_localmind_key:Annotated[str | None,Header()]=None):
    authorize(x_localmind_key)
    return {'apps':catalog.refresh()}

@app.post('/api/apps/permission')
def permission(data:PermissionRequest,x_localmind_key:Annotated[str | None,Header()]=None):
    authorize(x_localmind_key)
    try:
        catalog.set_permission(data.app_id,data.allowed,data.fingerprint)
        return {'ok':True}
    except AppError as exc:
        raise HTTPException(409,str(exc)) from exc

@app.get('/api/diagnostics')
def diagnostics(x_localmind_key:Annotated[str | None,Header()]=None):
    authorize(x_localmind_key)
    from .agent import _local_ollama_url
    status={'ollama_reachable':False,'model_installed':False,'voice':voice_status(), 'demo':settings.demo,
            'gpu':'Не проверено: профиль GPU не означает наличие CUDA'}
    try:
        url=_local_ollama_url()
        with httpx.Client(timeout=3,trust_env=False) as client:
            result=client.get(url+'/api/tags');result.raise_for_status()
            status['ollama_reachable']=True
            status['model_installed']=any(m.get('name')==settings.model for m in result.json().get('models',[]))
    except Exception:
        status['ollama_message']='Проверьте локальный Ollama и ollama pull выбранной модели. Секреты и пути скрыты.'
    return status
