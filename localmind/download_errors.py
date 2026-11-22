"""Actionable user errors plus bounded, redacted technical diagnostics."""
import errno
import re
import httpx
import json
from threading import RLock
from .paths import PRIVATE, atomic_json, ordinary_tree

_diagnostic_lock = RLock()
_diagnostics = []
_diagnostic_path = PRIVATE / 'download-diagnostics.json'
try:
    if _diagnostic_path.is_file() and ordinary_tree(_diagnostic_path).stat().st_size < 262144:
        _loaded = json.loads(_diagnostic_path.read_text(encoding='utf-8'))
        if isinstance(_loaded, list):
            _diagnostics = [item for item in _loaded[-32:] if isinstance(item, dict)]
except (OSError, ValueError):
    pass


def download_error(exc, stage):
    status = exc.response.status_code if isinstance(exc, httpx.HTTPStatusError) else None
    raw = str(exc)
    lower = raw.lower()
    code, message = 'unavailable', 'Модель недоступна'
    if status in (401, 403) or any(s in lower for s in ('unauthorized', 'forbidden', 'gated', 'авторизац')):
        code, message = 'auth_required', 'Требуется авторизация'
    elif status == 404:
        code, message = 'unavailable', 'Модель недоступна'
    elif isinstance(exc, (httpx.NetworkError, httpx.TimeoutException)) or any(s in lower for s in (
            'dial tcp', 'connection refused', 'connection reset', 'i/o timeout', 'no such host')):
        code, message = 'network', 'Нет соединения'
    elif getattr(exc, 'errno', None) == errno.ENOSPC or any(s in lower for s in ('disk full', 'no space', 'недостаточно места')):
        code, message = 'disk_full', 'Недостаточно места'
    elif isinstance(exc, PermissionError) or any(s in lower for s in ('permission denied', 'read-only file system')):
        code, message = 'permission_denied', 'Нет прав на каталог загрузки'
    elif any(s in lower for s in ('sha-256', 'checksum', 'контрольная сумма')):
        code, message = 'incompatible', 'Проверка SHA-256 не пройдена'
    elif any(s in lower for s in ('interrupt', 'прерван', 'cancel')):
        code, message = 'interrupted', 'Загрузка прервана'
    elif any(s in lower for s in ('unsupported', 'не поддерж', 'ollama version')):
        code, message = 'unsupported', 'Ollama не поддерживает этот вариант'
    elif any(s in lower for s in ('incompatib', 'несовмест', 'checksum', 'контрольная сумма', 'размер ресурса')):
        code, message = 'incompatible', 'Файл несовместим'
    # Retain the cause, but never tokens, URLs with credentials, paths or query strings.
    technical = re.sub(r'''(?ix)(bearer\s+|(?:token|key|authorization)["']?\s*[:=]\s*["']?)\S+''', r'\1[redacted]', raw)
    technical = re.sub(r'\bhf_[A-Za-z0-9]{10,}\b', '[redacted]', technical)
    technical = re.sub(r'https?://\S+|[A-Za-z]:[\\/]\S+|/(?:[^\s/]+/)*[^\s]+', '[location]', technical)
    return {'code': code, 'message': message, 'stage': stage, 'exception': type(exc).__name__,
            'http_status': status, 'technical': technical[:1000]}


def record_download_error(exc, stage):
    diagnostic = download_error(exc, stage)
    with _diagnostic_lock:
        _diagnostics.append(diagnostic)
        del _diagnostics[:-32]
        try:
            atomic_json(_diagnostic_path, _diagnostics)
        except (OSError, ValueError):
            # A full/unavailable disk must not hide the original download cause.
            pass
    return diagnostic


def diagnostics():
    with _diagnostic_lock:
        return list(_diagnostics)
