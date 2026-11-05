"""Loopback API. Execution is shared by JSON and opt-in NDJSON streaming."""
import asyncio
from concurrent.futures import TimeoutError as FutureTimeout
import hashlib
import hmac
import ipaddress
import json
import threading
import time
import uuid
from typing import Annotated, Literal
from contextlib import asynccontextmanager
from urllib.parse import urlsplit
from pathlib import Path

from fastapi import FastAPI, File, Form, Header, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.exceptions import RequestValidationError
from fastapi.exception_handlers import request_validation_exception_handler
from pydantic import BaseModel, Field, model_validator
import httpx

from .settings import ROOT, settings
from .agent import reply, prepare_reply, complete_reply
from .devices import device_catalog, is_demo
from .apps import catalog, AppError
from .requests import RequestStore, RequestBusy, RequestConflict
from .generation import GenerationSettings
from .model_manager import manager
from .hardware import hardware_status
from .conversations import conversations, ConversationError
from .file_access import file_access, FileAccessError
from .attachments import (AttachmentError, MAX_FILE_BYTES, add_document,
                          document_context, extract_document)
from .voice import VoiceError, voice_status, transcribe_audio, synthesize_speech, MAX_UPLOAD_BYTES, DEFAULT_VOICE

@asynccontextmanager
async def lifespan(app):
    from .voice import warm_tts, shutdown_tts, shutdown_stt
    from .window_tools import window_tools
    from . import resource_setup, offline_model
    from .speech_worker import worker as tts_worker
    from .asr_worker import worker as stt_worker
    store.reopen()
    resource_setup.reopen()
    offline_model.reopen()
    tts_worker.reopen()
    stt_worker.reopen()
    catalog.set_personal_mode(file_access.known_app_launch_allowed())
    warm_task = asyncio.create_task(asyncio.to_thread(warm_tts))
    try:
        yield
    finally:
        from .model_catalog import downloads
        from .model_benchmark import benchmarks
        # Interrupt owned native work and reject new work before awaiting locks.
        store.cancel_all()
        tts_worker.begin_shutdown()
        stt_worker.begin_shutdown()
        results = await asyncio.gather(*(asyncio.to_thread(close) for close in
            (downloads.stop_all, benchmarks.stop_all, resource_setup.stop_all, offline_model.stop_all,
             shutdown_tts, shutdown_stt, store.close)), return_exceptions=True)
        warm_task.cancel()
        window_tools.close()
        if any(isinstance(result, BaseException) for result in results):
            raise RuntimeError('Не все фоновые задачи LocalMind удалось завершить.')


app = FastAPI(title='LocalMind', version='1.0.0', docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)


@app.exception_handler(ConversationError)
async def conversation_storage_error(request, exc):
    return JSONResponse({'detail': str(exc)}, status_code=409)


@app.exception_handler(RequestValidationError)
async def private_validation_error(request, exc):
    if request.url.path.startswith('/api/home'):
        # Pydantic's default "input" field can reflect a malformed secret.
        return JSONResponse({'detail': 'Проверьте поля подключения и разрешения Home Assistant.'}, status_code=422)
    return await request_validation_exception_handler(request, exc)

app.mount('/assets', StaticFiles(directory=ROOT / 'static' / 'assets'), name='assets')
from .model_routes import router as model_router, unified_router
app.include_router(model_router)
app.include_router(unified_router)
from .setup_routes import router as setup_router
app.include_router(setup_router)
from .home_routes import router as home_router
app.include_router(home_router)
store = RequestStore()
LOCAL_HOSTS = frozenset(('127.0.0.1', 'localhost', '::1'))
SERVER_INSTANCE = uuid.uuid4().hex
_body_slots = threading.BoundedSemaphore(4)
BODY_TIMEOUT_SECONDS = 15

class HistoryMessage(BaseModel):
    role: Literal['user', 'assistant']
    content: str = Field(max_length=4000)

class ChatRequest(BaseModel):
    text: str = Field(default='', max_length=2000)
    history: list[HistoryMessage] = Field(default_factory=list, max_length=8)
    actions_authorized: bool = True
    request_id: str | None = Field(default=None, min_length=8, max_length=80, pattern=r'^[a-zA-Z0-9_-]+$')
    response_length: Literal['brief', 'normal', 'detailed'] = 'normal'
    compose_actions: bool = True
    server_instance: str | None = Field(default=None, max_length=32)
    model: str | None = Field(default=None, min_length=1, max_length=240, pattern=r'^[a-zA-Z0-9][a-zA-Z0-9._:/-]*$')
    reasoning: Literal['off', 'on', 'auto'] = 'off'
    temperature: float = Field(default=0.2, ge=0, le=2, allow_inf_nan=False)
    context_tokens: int = Field(default=4096, ge=1024, le=8192)
    response_tokens: int = Field(default=768, ge=64, le=2048)
    keep_alive_seconds: int = Field(default=300, ge=0, le=900)
    conversation_id: str | None = Field(default=None, min_length=32, max_length=64, pattern=r'^[a-zA-Z0-9_-]+$')
    local_retrieval: bool = False
    attachment_ids: list[Annotated[str, Field(min_length=32, max_length=64, pattern=r'^[a-zA-Z0-9_-]+$')]] = Field(default_factory=list, max_length=8)

    @model_validator(mode='after')
    def require_content(self):
        if not self.text.strip() and not self.attachment_ids:
            raise ValueError('Нужен текст или вложение.')
        return self

class ConversationRequest(BaseModel):
    conversation_id: str = Field(min_length=32, max_length=64, pattern=r'^[a-zA-Z0-9_-]+$')

class AttachmentRemoveRequest(ConversationRequest):
    attachment_id: str = Field(min_length=32, max_length=64, pattern=r'^[a-zA-Z0-9_-]+$')
    server_instance: str = Field(min_length=32, max_length=32)

class FolderPermissionRequest(BaseModel):
    allowed: bool
    fingerprint: str = Field(min_length=64, max_length=64)

class PersonalModeRequest(BaseModel):
    enabled: bool
    roots: list[Annotated[str, Field(min_length=1, max_length=1024)]] = Field(default_factory=list, max_length=16)
    portable_roots: list[Annotated[str, Field(min_length=1, max_length=1024)]] = Field(default_factory=list, max_length=16)
    server_instance: str = Field(min_length=32, max_length=32)

class PolicyRevisionRequest(BaseModel):
    model_config = {'extra': 'forbid', 'strict': True}
    revision: str = Field(min_length=32, max_length=32)
    server_instance: str = Field(min_length=32, max_length=32)

class AccessPolicyRequest(PolicyRevisionRequest):
    mode: Literal['restricted', 'full_user']
    roots: list[Annotated[str, Field(min_length=1, max_length=1024)]] = Field(default_factory=list, max_length=16)
    operations: list[Literal['search', 'read', 'open', 'create', 'overwrite', 'move', 'delete']] = Field(max_length=7)

class RulePreviewRequest(PolicyRevisionRequest):
    text: str = Field(min_length=1, max_length=2000)
    scope: str | None = Field(default=None, min_length=1, max_length=1024)

class RuleApplyRequest(PolicyRevisionRequest):
    draft_id: str = Field(min_length=20, max_length=64, pattern=r'^[a-zA-Z0-9_-]+$')

class RuleRemoveRequest(PolicyRevisionRequest):
    rule_id: str = Field(min_length=24, max_length=24, pattern=r'^[a-f0-9]+$')

class FileSearchRequest(ConversationRequest):
    query: str = Field(default='', max_length=500)
    extensions: list[str] | None = Field(default=None, max_length=8)
    scope: str = Field(default='downloads', max_length=64)
    sort_by: Literal['modified', 'created', 'size', 'name'] = 'modified'
    order: Literal['asc', 'desc'] = 'desc'
    recursive: bool = False
    min_size: int | None = Field(default=None, ge=0, le=67108864)
    max_size: int | None = Field(default=None, ge=0, le=67108864)

class MutationConfirmation(ConversationRequest):
    confirmation_id: str = Field(min_length=20, max_length=128)
    approved: bool
    server_instance: str = Field(min_length=32, max_length=32)

class FilePermissionRequest(ConversationRequest):
    file_id: str = Field(min_length=20, max_length=64, pattern=r'^[a-zA-Z0-9_-]+$')
    allowed: bool

class SourcePermissionRequest(BaseModel):
    source_id: str = Field(min_length=1, max_length=64, pattern=r'^[a-zA-Z0-9_-]+$')
    allowed: bool
    fingerprint: str | None = Field(default=None, min_length=64, max_length=64)

class PermissionRequest(BaseModel):
    app_id: str = Field(min_length=1, max_length=100)
    allowed: bool
    fingerprint: str = Field(min_length=32, max_length=256)
    operation: Literal['launch', 'focus', 'close'] | None = None

class SpeechRequest(BaseModel):
    text: str = Field(min_length=1, max_length=1200)
    voice: Literal['ru_RU-denis-medium', 'silero-v5_6-ru', 'chatterbox-v3-ru'] = DEFAULT_VOICE
    generation_id: str | None = Field(default=None, pattern=r'^[a-f0-9]{32}$')

class SpeechCancelRequest(BaseModel):
    generation_id: str = Field(pattern=r'^[a-f0-9]{32}$')

class ChatCancelRequest(BaseModel):
    request_id: str = Field(min_length=8, max_length=80, pattern=r'^[a-zA-Z0-9_-]+$')
    server_instance: str = Field(max_length=32)

class WindowSelectionRequest(ConversationRequest):
    window_id: str = Field(min_length=20, max_length=80, pattern=r'^win-[a-f0-9]{32}$')

def is_loopback_address(host: str) -> bool:
    try:
        return ipaddress.ip_address(host.split('%', 1)[0]).is_loopback
    except ValueError:
        return False

def authorize(key: str | None):
    if settings.key and not hmac.compare_digest(key or '', settings.key):
        raise HTTPException(401, 'Неверный ключ доступа')


from .conversation_routes import install_conversation_routes
install_conversation_routes(app, authorize, SERVER_INSTANCE)

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
    if request.method in ('POST', 'PUT', 'PATCH', 'DELETE'):
        if not _body_slots.acquire(blocking=False):
            return JSONResponse({'detail':'Слишком много одновременных загрузок'},status_code=429)
        try:
            maximum = (MAX_UPLOAD_BYTES + 65536 if request.url.path == '/api/transcribe' else
                       MAX_FILE_BYTES + 65536 if request.url.path == '/api/attachments' else
                       3 * 1024 * 1024 + 65536 if request.url.path == '/api/conversations/import' else 65536)
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
    from . import storage
    mutating = request.method in ('POST', 'PUT', 'PATCH', 'DELETE') and request.url.path != '/api/setup/storage/apply'
    if mutating:
        try:
            storage.begin_mutation()
        except ValueError as exc:
            return JSONResponse({'detail': str(exc)}, status_code=409)
    try:
        response = await call_next(request)
    finally:
        if mutating:
            storage.end_mutation()
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
    return {'name':'LocalMind', 'version':'1.0.0', 'demo':is_demo(), 'model':manager.active,
            'server_instance':SERVER_INSTANCE,
            'devices':device_catalog(), 'voice_available':voice['stt_installed'], 'voice':voice}

def _entry(data: ChatRequest):
    if data.server_instance is not None and data.server_instance != SERVER_INSTANCE:
        raise HTTPException(409,'Сервер перезапущен. Автоматическое повторение действия отменено; проверьте его состояние вручную.')
    payload=data.model_dump()
    controls = {'reasoning', 'context_tokens', 'response_tokens', 'keep_alive_seconds', 'temperature'}
    try:
        model = data.model or manager.active
        values = manager.generation(model) or GenerationSettings(model).to_dict()
        for name in controls & data.model_fields_set:
            values[name] = getattr(data, name)
        generation = GenerationSettings(**values)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    # Wire identity is stable across a server selection change. The first
    # accepted closure captures immutable effective settings for all replays.
    payload.pop('request_id')
    # Omitting a control uses the saved per-model value. Explicitly supplying
    # its API default is a different request, even if model_dump is identical.
    payload['generation_overrides'] = sorted(controls & data.model_fields_set)
    fingerprint=hashlib.sha256(json.dumps(payload,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
    def prepare_turn():
        # Client history remains accepted for wire compatibility, but is never
        # used to establish memory, permissions, targets or outcomes.
        conversation = conversations.acquire(data.conversation_id or conversations.create())
        try:
            conversation.context = {'local_retrieval': data.local_retrieval,
                                    'attachment_ids': list(data.attachment_ids)}
            context = document_context(conversation, data.attachment_ids, query=data.text,
                max_characters=max(256, (generation.context_tokens - generation.response_tokens - 1200) * 2))
            # Persist the input before generation or trusted actions. A process
            # exit before final leaves a recoverable draft, never a fake answer.
            conversation.draft = data.text
            conversations._save_state(conversation)
            prepared = prepare_reply(data.text, [], data.actions_authorized, data.response_length,
                                     data.compose_actions, generation, conversation=conversation, local_retrieval=data.local_retrieval,
                                       document_facts=context, llm_first=True)
            prepared.initial.update(request_id=data.request_id, server_instance=SERVER_INSTANCE)
            from .results import output_channels
            prepared.initial.update(output_channels(prepared.initial['answer'], prepared.initial['action_results'], prepared.initial.get('speech_text')))
            def finish(final):
                try:
                    conversation.remember(data.text, final or prepared.initial, prepared.reference)
                finally:
                    conversations.release(conversation)
            prepared.finish_turn = finish
            return prepared
        except Exception:
            conversations.release(conversation)
            raise
    try:
        def admit():
            from .model_benchmark import benchmarks
            if benchmarks.running():
                raise RequestBusy('Локальный тест моделей занимает inference. Дождитесь его завершения или прервите тест.')
        return store.begin(data.request_id, fingerprint,
            prepare_turn,
            complete_reply, admit=admit)
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
    except (ConversationError, AttachmentError) as exc:
        raise HTTPException(409, str(exc)) from exc


@app.post('/api/conversations')
def create_conversation(x_localmind_key: Annotated[str | None, Header()] = None):
    authorize(x_localmind_key)
    try:
        return {'conversation_id': conversations.create(), 'server_instance': SERVER_INSTANCE}
    except ConversationError as exc:
        raise HTTPException(409, str(exc)) from exc


@app.get('/api/conversations/{conversation_id}')
def conversation_status(conversation_id: str, x_localmind_key: Annotated[str | None, Header()] = None):
    authorize(x_localmind_key)
    try:
        return {**conversations.read(conversation_id), 'server_instance': SERVER_INSTANCE}
    except ConversationError as exc:
        raise HTTPException(409, str(exc)) from exc


@app.post('/api/attachments')
def upload_attachment(file: Annotated[UploadFile, File()], conversation_id: Annotated[str, Form()],
                      server_instance: Annotated[str, Form()],
                      x_localmind_key: Annotated[str | None, Header()] = None):
    authorize(x_localmind_key)
    if server_instance != SERVER_INSTANCE:
        raise HTTPException(409, 'Сервер перезапущен. Добавь документ в новый разговор.')
    conversation = None
    try:
        conversation = conversations.acquire(conversation_id)
        data = file.file.read(MAX_FILE_BYTES + 1)
        document = extract_document(data, file.filename)
        add_document(conversation, document)
        return {**document.public(preview=True), 'conversation_id': conversation.id,
                'server_instance': SERVER_INSTANCE}
    except (ConversationError, AttachmentError) as exc:
        raise HTTPException(409, str(exc)) from exc
    finally:
        file.file.close()
        if conversation:
            conversations.release(conversation)


@app.post('/api/attachments/remove')
def remove_attachment(data: AttachmentRemoveRequest, x_localmind_key: Annotated[str | None, Header()] = None):
    authorize(x_localmind_key)
    if data.server_instance != SERVER_INSTANCE:
        raise HTTPException(409, 'Сервер перезапущен. Вложение больше недоступно.')
    conversation = None
    try:
        conversation = conversations.acquire(data.conversation_id)
        conversation.attachments.pop(data.attachment_id, None)
        return {'ok': True}
    except ConversationError as exc:
        raise HTTPException(409, str(exc)) from exc
    finally:
        if conversation:
            conversations.release(conversation)


@app.post('/api/conversations/reset')
def reset_conversation(data: ConversationRequest, x_localmind_key: Annotated[str | None, Header()] = None):
    authorize(x_localmind_key)
    try:
        conversations.reset(data.conversation_id)
        return {'ok': True}
    except ConversationError as exc:
        raise HTTPException(409, str(exc)) from exc


@app.post('/api/chat/cancel')
def cancel_chat(data: ChatCancelRequest, x_localmind_key: Annotated[str | None, Header()] = None):
    authorize(x_localmind_key)
    if data.server_instance != SERVER_INSTANCE:
        raise HTTPException(409, 'Сервер перезапущен. Старый запрос недоступен.')
    return {'cancelled': store.cancel(data.request_id)}


@app.post('/api/windows/select')
def select_window(data: WindowSelectionRequest, x_localmind_key: Annotated[str | None, Header()] = None):
    authorize(x_localmind_key)
    from .capabilities import _windows
    from .conversations import Reference
    conversation = None
    try:
        conversation = conversations.acquire(data.conversation_id)
        result = _windows().verify_selection(data.window_id)
        if not result.success:
            raise HTTPException(409, str(result))
        conversation.references['window'] = Reference('window', data.window_id)
        conversation.references['application'] = Reference('application', result.data['app_id'])
        conversation.focus = 'window'
        return result.to_dict()
    except ConversationError as exc:
        raise HTTPException(409, str(exc)) from exc
    finally:
        if conversation:
            conversations.release(conversation)


@app.get('/api/files')
def files(conversation_id: str | None = None, x_localmind_key: Annotated[str | None, Header()] = None):
    authorize(x_localmind_key)
    try:
        folder = file_access.folder_info()
        selected = None
        if conversation_id:
            conversation = conversations.acquire(conversation_id)
            try:
                ref = conversation.references.get('file')
                if ref:
                    selected = file_access.selected_info(conversation.id, ref.id)
            finally:
                conversations.release(conversation)
        return {'folder': folder, 'selected': selected, 'personal_mode': file_access.personal_info()}
    except (FileAccessError, ConversationError, OSError) as exc:
        raise HTTPException(409, str(exc) if isinstance(exc, ValueError) else 'Папка недоступна.') from exc


@app.get('/api/retrieval/sources')
def retrieval_sources(x_localmind_key: Annotated[str | None, Header()] = None):
    authorize(x_localmind_key)
    from .retrieval import retrieval
    return {'sources': retrieval.entries()}


@app.post('/api/retrieval/permission')
def retrieval_permission(data: SourcePermissionRequest, x_localmind_key: Annotated[str | None, Header()] = None):
    authorize(x_localmind_key)
    from .retrieval import retrieval, RetrievalError
    try:
        retrieval.set_permission(data.source_id, data.allowed, data.fingerprint)
        return {'ok': True}
    except RetrievalError as exc:
        raise HTTPException(409, str(exc)) from exc


@app.post('/api/files/folder-permission')
def folder_permission(data: FolderPermissionRequest, x_localmind_key: Annotated[str | None, Header()] = None):
    authorize(x_localmind_key)
    try:
        file_access.set_folder_permission(data.allowed, data.fingerprint)
        return {'ok': True}
    except (FileAccessError, OSError) as exc:
        raise HTTPException(409, 'Папка недоступна или изменилась. Проверь разрешение повторно.') from exc


@app.get('/api/permissions/personal')
def personal_permissions(x_localmind_key: Annotated[str | None, Header()] = None):
    authorize(x_localmind_key)
    return {**file_access.personal_info(), 'server_instance': SERVER_INSTANCE}


@app.get('/api/access-policy')
def access_policy(x_localmind_key: Annotated[str | None, Header()] = None):
    authorize(x_localmind_key)
    return {**file_access.personal_info(), 'server_instance': SERVER_INSTANCE}


def _policy_revision(data):
    if data.server_instance != SERVER_INSTANCE or data.revision != file_access.personal_mode.generation:
        raise HTTPException(409, 'Сервер или политика изменились. Обнови экран возможностей и повтори просмотр.')


def _policy_changed():
    file_access._sync_policy()
    return {**file_access.personal_info(), 'server_instance': SERVER_INSTANCE}


@app.post('/api/access-policy')
def set_access_policy(data: AccessPolicyRequest, x_localmind_key: Annotated[str | None, Header()] = None):
    authorize(x_localmind_key)
    try:
        with file_access._lock, file_access.personal_mode._lock:
            _policy_revision(data)
            file_access.personal_mode.configure(data.mode, data.roots, data.operations)
            return _policy_changed()
    except (OSError, ValueError) as exc:
        raise HTTPException(409, str(exc) if isinstance(exc, ValueError) else 'Не удалось сохранить политику. Изменения не применены.') from exc


@app.post('/api/access-policy/preview')
def preview_access_rule(data: RulePreviewRequest, x_localmind_key: Annotated[str | None, Header()] = None):
    authorize(x_localmind_key)
    try:
        # Catalog methods take policy -> catalog locks. Capture metadata before
        # entering the file transaction so preview never discovers under it.
        entries = catalog.entries()
        with file_access._lock, file_access.personal_mode._lock:
            _policy_revision(data)
            folders = {}
            basenames = {}
            for row in file_access.personal_info()['roots']:
                folders[row['path']] = row['path']
                name = Path(row['path']).name.casefold()
                basenames.setdefault(name, []).append(row['path'])
            for name, paths in basenames.items():
                if len(paths) == 1:
                    folders[name] = paths[0]
            try:
                downloads = file_access.folder_provider()
                folders['Загрузки'], folders['Downloads'] = str(downloads), str(downloads)
            except (OSError, ValueError):
                pass
            return file_access.personal_mode.preview(data.text, scope=data.scope, apps=entries, folders=folders)
    except (OSError, ValueError) as exc:
        raise HTTPException(409, str(exc) if isinstance(exc, ValueError) else 'Не удалось проверить правило.') from exc


@app.post('/api/access-policy/apply')
def apply_access_rule(data: RuleApplyRequest, x_localmind_key: Annotated[str | None, Header()] = None):
    authorize(x_localmind_key)
    try:
        with file_access._lock, file_access.personal_mode._lock:
            _policy_revision(data)
            file_access.personal_mode.apply(data.draft_id)
            return _policy_changed()
    except (OSError, ValueError) as exc:
        raise HTTPException(409, str(exc) if isinstance(exc, ValueError) else 'Не удалось сохранить правило. Изменения не применены.') from exc


@app.post('/api/access-policy/remove-rule')
def remove_access_rule(data: RuleRemoveRequest, x_localmind_key: Annotated[str | None, Header()] = None):
    authorize(x_localmind_key)
    try:
        with file_access._lock, file_access.personal_mode._lock:
            _policy_revision(data)
            file_access.personal_mode.remove_rule(data.rule_id)
            return _policy_changed()
    except (OSError, ValueError) as exc:
        raise HTTPException(409, str(exc) if isinstance(exc, ValueError) else 'Не удалось сохранить правило.') from exc


@app.get('/api/actions')
def action_log(x_localmind_key: Annotated[str | None, Header()] = None):
    authorize(x_localmind_key)
    from .action_journal import journal
    return {'actions': journal.snapshot()}


@app.post('/api/permissions/personal')
def set_personal_permissions(data: PersonalModeRequest, x_localmind_key: Annotated[str | None, Header()] = None):
    authorize(x_localmind_key)
    if data.server_instance != SERVER_INSTANCE:
        raise HTTPException(409, 'Сервер перезапущен. Проверь разрешения повторно.')
    try:
        # Revoke broad launch permission first so failed validation never leaves
        # a stale catalog permission in effect.
        catalog.set_personal_mode(False)
        file_access.set_personal_mode(data.enabled, data.roots)
        catalog.configure_portable_roots(data.portable_roots if data.enabled else [])
        catalog.set_personal_mode(file_access.known_app_launch_allowed())
        return file_access.personal_info()
    except (FileAccessError, AppError, OSError) as exc:
        raise HTTPException(409, str(exc) if isinstance(exc, ValueError) else 'Не удалось сохранить разрешения.') from exc


@app.post('/api/files/search')
def search_files(data: FileSearchRequest, x_localmind_key: Annotated[str | None, Header()] = None):
    authorize(x_localmind_key)
    conversation = None
    try:
        from .conversations import Reference
        conversation = conversations.acquire(data.conversation_id)
        result = file_access.search(conversation.id, **data.model_dump(exclude={'conversation_id'}))
        if result.success and result.data and result.data.get('file_id'):
            conversation.references['file'] = Reference('file', result.data['file_id'])
            conversation.focus = 'file'
        return result.to_dict()
    except ConversationError as exc:
        raise HTTPException(409, str(exc)) from exc
    finally:
        if conversation:
            conversations.release(conversation)


@app.post('/api/files/confirm')
def confirm_file_operation(data: MutationConfirmation, x_localmind_key: Annotated[str | None, Header()] = None):
    authorize(x_localmind_key)
    if data.server_instance != SERVER_INSTANCE:
        raise HTTPException(409, 'Подтверждение истекло после перезапуска сервера.')
    conversation = None
    try:
        from .file_mutations import file_mutations
        conversation = conversations.acquire(data.conversation_id)
        return file_mutations.confirm(conversation.id, data.confirmation_id, data.approved).to_dict()
    except (ConversationError, FileAccessError) as exc:
        raise HTTPException(409, str(exc)) from exc
    finally:
        if conversation:
            conversations.release(conversation)


@app.post('/api/files/open-permission')
def file_permission(data: FilePermissionRequest, x_localmind_key: Annotated[str | None, Header()] = None):
    authorize(x_localmind_key)
    conversation = None
    try:
        conversation = conversations.acquire(data.conversation_id)
        file_access.set_open_permission(conversation.id, data.file_id, data.allowed)
        return {'ok': True}
    except (FileAccessError, ConversationError, OSError) as exc:
        raise HTTPException(409, 'Файл или разговор изменился. Выбери и разреши PDF повторно.') from exc
    finally:
        if conversation:
            conversations.release(conversation)

@app.post('/api/chat/stream')
def chat_stream(data:ChatRequest, x_localmind_key: Annotated[str | None, Header()] = None):
    authorize(x_localmind_key)
    try:
        entry = _entry(data)
        initial = entry.initial.result(timeout=90)
    except FutureTimeout as exc:
        raise HTTPException(504, 'Ответ ещё обрабатывается. Повтори с тем же request_id.') from exc
    except (ConversationError, AttachmentError) as exc:
        raise HTTPException(409, str(exc)) from exc
    async def events():
        # result() runs in a separate waiter; cancellation cannot cancel shared futures.
        try:
            yield json.dumps({'type':'status','data':initial},ensure_ascii=False)+'\n'
            offset = 0
            deadline = time.monotonic() + 90
            while True:
                if time.monotonic() > deadline:
                    raise TimeoutError('Response still processing')
                deltas, finished = await asyncio.to_thread(entry.read_deltas, offset)
                for delta in deltas:
                    offset += 1
                    yield json.dumps({'type':'delta','text':delta,'sequence':offset},ensure_ascii=False)+'\n'
                if finished:
                    break
            final=await asyncio.to_thread(entry.final.result,90)
            yield json.dumps({'type':'final','data':final},ensure_ascii=False)+'\n'
        except ConversationError as exc:
            # Persistence errors already contain a safe, actionable user message.
            # The stream has started, so return an error event rather than hide
            # a failed commit behind a generic reconnect suggestion.
            yield json.dumps({'type':'error','detail':str(exc)},ensure_ascii=False)+'\n'
        except Exception:
            yield json.dumps({'type':'error','detail':'Не удалось получить ответ. Сохраните request_id для повторного запроса.'},ensure_ascii=False)+'\n'
    return StreamingResponse(events(),media_type='application/x-ndjson',headers={'X-Accel-Buffering':'no'})


@app.get('/api/models')
def models(x_localmind_key: Annotated[str | None, Header()] = None):
    authorize(x_localmind_key)
    try:
        return manager.inventory()
    except (httpx.HTTPError, ValueError, KeyError, TypeError):
        raise HTTPException(503, 'Локальный Ollama недоступен. Проверьте его запуск.')


class ModelSelection(BaseModel):
    model: str = Field(min_length=1, max_length=240)


@app.post('/api/models/select')
def select_model(data: ModelSelection):
    try:
        return manager.select(data.model)
    except (httpx.HTTPError, ValueError, OSError, TypeError):
        raise HTTPException(409, 'Проверка модели не пройдена или Ollama занят. Предыдущий выбор сохранён.')


@app.get('/api/models/hardware')
def model_hardware():
    return hardware_status()


@app.post('/api/transcribe')
async def transcribe(audio:Annotated[UploadFile,File()], profile:Annotated[str | None,Form()]=None,
                     x_localmind_key:Annotated[str | None,Header()]=None):
    authorize(x_localmind_key)
    from pathlib import Path
    try:
        data=await audio.read(MAX_UPLOAD_BYTES+1)
        result=await asyncio.to_thread(transcribe_audio,data,Path(audio.filename or '').suffix.lower(),profile)
        from .voice_diagnostics import normalize_stt_payload
        return normalize_stt_payload(result)
    except VoiceError as exc:
        raise HTTPException(exc.status_code,exc.detail) from exc
    finally:
        await audio.close()

@app.post('/api/tts')
def tts(data:SpeechRequest,x_localmind_key:Annotated[str | None,Header()]=None):
    authorize(x_localmind_key)
    try:
        wav = (synthesize_speech(data.text, data.voice, data.generation_id) if data.generation_id else
               synthesize_speech(data.text, data.voice))
        return Response(wav,media_type='audio/wav')
    except VoiceError as exc:
        raise HTTPException(exc.status_code,exc.detail) from exc

@app.post('/api/tts/cancel')
def cancel_speech(data: SpeechCancelRequest, x_localmind_key: Annotated[str | None, Header()] = None):
    authorize(x_localmind_key)
    from .voice import cancel_tts
    cancel_tts(data.generation_id)
    return {'ok': True}

@app.get('/api/apps')
def apps(x_localmind_key:Annotated[str | None,Header()]=None):
    authorize(x_localmind_key)
    return {'apps':catalog.entries(), 'statistics': catalog.statistics()}

@app.post('/api/apps/refresh')
def refresh_apps(x_localmind_key:Annotated[str | None,Header()]=None):
    authorize(x_localmind_key)
    return {'apps':catalog.refresh(), 'statistics': catalog.statistics()}

@app.post('/api/apps/permission')
def permission(data:PermissionRequest,x_localmind_key:Annotated[str | None,Header()]=None):
    authorize(x_localmind_key)
    try:
        if data.operation is None:
            entries = catalog.set_permission(data.app_id,data.allowed,data.fingerprint)
        else:
            entries = catalog.set_permission(data.app_id,data.allowed,data.fingerprint,operation=data.operation)
        return {'ok':True, 'apps': entries}
    except AppError as exc:
        raise HTTPException(409,str(exc)) from exc

@app.get('/api/diagnostics')
def diagnostics(x_localmind_key:Annotated[str | None,Header()]=None):
    authorize(x_localmind_key)
    from .agent import _local_ollama_url
    status={'ollama_reachable':False,'model_installed':False,'voice':voice_status(), 'demo':is_demo(),
            'gpu':'Не проверено: профиль GPU не означает наличие CUDA'}
    from .asr_worker import worker as asr_worker
    status['asr_worker'] = asr_worker.diagnostics()
    try:
        url=_local_ollama_url()
        with httpx.Client(timeout=3,trust_env=False) as client:
            result=client.get(url+'/api/tags');result.raise_for_status()
            status['ollama_reachable']=True
            status['model_installed']=any(m.get('name')==manager.active for m in result.json().get('models',[]))
            version=client.get(url+'/api/version');version.raise_for_status()
            status['ollama_version']=version.json().get('version')
            resident=client.get(url+'/api/ps');resident.raise_for_status()
            status['loaded_models']=[{k:m.get(k) for k in ('name','size','size_vram','context_length','expires_at')}
                                     for m in resident.json().get('models',[])]
            status['gpu']='size_vram — выделенная память Ollama, не измерение загрузки CUDA; совместная работа с GPU STT проверяется отдельно.'
    except Exception:
        status['ollama_message']='Проверьте локальный Ollama и ollama pull выбранной модели. Секреты и пути скрыты.'
    return status
