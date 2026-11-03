from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, SecretStr
from .home_assistant import home_assistant, HAError
from .devices import sync_devices, is_demo

router = APIRouter(prefix='/api/home')


@router.get('')
def connection():
    return {**home_assistant.public(), 'mode': 'DEMO' if is_demo() else 'REAL'}


class ConnectRequest(BaseModel):
    origin: str = Field(min_length=8, max_length=200)
    token: SecretStr = Field(min_length=10, max_length=4096)


@router.post('/connect')
def connect(data: ConnectRequest):
    try:
        result = home_assistant.connect(data.origin, data.token.get_secret_value())
        sync_devices()
        return result
    except HAError as exc:
        raise HTTPException(409, str(exc))
    except OSError:
        raise HTTPException(409, 'Windows не разрешила сохранить токен. Подключение не изменено.')


@router.post('/disconnect')
def disconnect():
    try:
        result = home_assistant.disconnect()
        sync_devices()
        return result
    except OSError:
        raise HTTPException(409, 'Не удалось удалить сохранённое подключение.')


@router.get('/devices')
def discover():
    try:
        return {'devices': home_assistant.discover()}
    except HAError as exc:
        raise HTTPException(409, str(exc))


class ApprovalRequest(BaseModel):
    device_id: str = Field(pattern=r'^ha-[a-f0-9]{24}$')
    allowed: bool
    name: str | None = Field(default=None, min_length=1, max_length=80)


@router.post('/permission')
def approve(data: ApprovalRequest):
    try:
        result = home_assistant.approve(data.device_id, data.allowed, data.name)
        sync_devices()
        return result
    except (HAError, OSError) as exc:
        raise HTTPException(409, str(exc) if isinstance(exc, HAError) else 'Не удалось сохранить разрешение.')
