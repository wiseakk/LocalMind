"""Management routes inherit the existing trusted server middleware."""
from typing import Literal
import httpx
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import JSONResponse
from .download_errors import record_download_error, diagnostics
from pydantic import BaseModel, Field
from . import model_catalog as catalog
from .model_benchmark import benchmarks, BenchmarkBusy

router = APIRouter(prefix='/api/models')


@router.get('/catalog')
def catalog_list(context: int = 4096):
    try:
        return {'models': catalog.curated(context), 'source': 'ollama', 'network': False}
    except (ValueError, TypeError):
        raise HTTPException(422, 'Недопустимые параметры каталога.')


@router.get('/hub/search')
def hub_search(query: str = Query(min_length=1, max_length=100)):
    try:
        return {'models': catalog.search_hub(query)}
    except (httpx.HTTPError, ValueError, TypeError, KeyError) as exc:
        cause = record_download_error(exc, 'hf_search')
        return JSONResponse({'detail': cause['message'], 'diagnostic': cause}, status_code=503)


@router.get('/hub/variants')
def hub_variants(repo: str = Query(min_length=3, max_length=193), context: int = 4096):
    try:
        return {'models': catalog.hub_variants(repo, context)}
    except (httpx.HTTPError, ValueError, TypeError, KeyError) as exc:
        cause = record_download_error(exc, 'hf_metadata')
        return JSONResponse({'detail': cause['message'], 'diagnostic': cause}, status_code=409)


class PullRequest(BaseModel):
    source: Literal['ollama', 'huggingface']
    identity: str = Field(min_length=1, max_length=193)
    quantization: str = Field(min_length=1, max_length=16)
    context: Literal[2048, 4096, 8192] = 4096
    accept_license: bool = False
    acknowledge_unknown_disk: bool = False
    fingerprint: str = Field(min_length=64, max_length=64, pattern=r'^[a-f0-9]{64}$')


@router.post('/downloads')
def start_pull(data: PullRequest):
    try:
        return catalog.downloads.start(data.source, data.identity, data.quantization, data.context,
            accept_license=data.accept_license, acknowledge_unknown_disk=data.acknowledge_unknown_disk, fingerprint=data.fingerprint)
    except (httpx.HTTPError, ValueError, TypeError, KeyError, OSError) as exc:
        diagnostic = record_download_error(exc, 'metadata_validation')
        message = str(exc) if isinstance(exc, ValueError) else diagnostic['message']
        return JSONResponse({'detail': message, 'diagnostic': diagnostic}, status_code=409)


@router.get('/downloads')
def list_pulls():
    try:
        return {'jobs': catalog.downloads.snapshot()}
    except ValueError:
        raise HTTPException(503, 'Журнал загрузок повреждён или недоступен. Восстановите хранилище приложения.')


@router.post('/downloads/{job_id}/cancel')
def cancel_pull(job_id: str):
    try:
        job = catalog.downloads.snapshot(job_id)
        if job.get('kind') in ('asr', 'tts'):
            from .resource_setup import cancel
            return cancel(job_id)
        if job.get('kind') == 'llm_offline':
            from .offline_model import cancel
            return cancel(job_id)
        return catalog.downloads.cancel(job_id)
    except ValueError:
        raise HTTPException(409, 'Задача уже завершена или недоступна. Обновите список.')


class BenchmarkRequest(BaseModel):
    models: list[str] = Field(min_length=1, max_length=2)


@router.post('/benchmarks')
def start_benchmark(data: BenchmarkRequest):
    try:
        return benchmarks.start(data.models)
    except BenchmarkBusy:
        raise HTTPException(429, 'Inference занят. Дождитесь окончания ответа, переключения или другого теста.')
    except (httpx.HTTPError, ValueError, TypeError, KeyError, OSError):
        raise HTTPException(409, 'Тест не начат. Выберите разные установленные локальные chat-модели; дождитесь свободного inference и проверьте место для результатов.')


@router.get('/benchmarks')
def list_benchmarks():
    try:
        return {'jobs': benchmarks.snapshot()}
    except (OSError, ValueError):
        raise HTTPException(503, 'История тестов временно недоступна.')


@router.get('/benchmarks/{job_id}')
def benchmark_result(job_id: str):
    try:
        return benchmarks.snapshot(job_id)
    except (ValueError, OSError, KeyError, TypeError):
        raise HTTPException(404, 'Результат теста недоступен.')


@router.post('/benchmarks/{job_id}/cancel')
def cancel_benchmark(job_id: str):
    try:
        return benchmarks.cancel(job_id)
    except ValueError:
        raise HTTPException(409, 'Тест уже завершён или недоступен.')


class RatingRequest(BaseModel):
    model: str = Field(min_length=1, max_length=240)
    rating: int = Field(ge=1, le=5, strict=True)


@router.post('/benchmarks/{job_id}/rating')
def rate_benchmark(job_id: str, data: RatingRequest):
    try:
        return benchmarks.rate(job_id, data.model, data.rating)
    except (ValueError, OSError, KeyError, TypeError):
        raise HTTPException(409, 'Рейтинг не сохранён. Дождитесь завершения теста и выберите протестированную модель.')


@router.post('/downloads/{job_id}/retry')
def retry_pull(job_id: str):
    try:
        job = catalog.downloads.snapshot(job_id)
        if job['status'] in ('queued', 'starting', 'downloading', 'verifying', 'cancelling'):
            raise ValueError('Дождитесь завершения текущей задачи.')
        if job.get('kind') in ('asr', 'tts'):
            from .resource_setup import start
            return start(job['kind'])
        if job.get('kind') == 'llm_offline':
            from .offline_model import start
            return start(True)  # Exact same pinned installer artifact, explicit retry button.
        request = PullRequest(**job['request'])
        return start_pull(request)
    except (ValueError, KeyError, OSError):
        raise HTTPException(409, 'Повтор недоступен. Откройте карточку модели и подтвердите актуальные сведения.')


unified_router = APIRouter(prefix='/api/downloads')
unified_router.add_api_route('', list_pulls, methods=['GET'])
unified_router.add_api_route('/{job_id}/cancel', cancel_pull, methods=['POST'])
unified_router.add_api_route('/{job_id}/retry', retry_pull, methods=['POST'])
unified_router.add_api_route('/diagnostics', lambda: {'diagnostics': diagnostics()}, methods=['GET'])
