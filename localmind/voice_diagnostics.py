"""Non-sensitive domain failures shared by isolated stdlib worker transports."""
import hashlib
import importlib.metadata
import json
import math
import os
from pathlib import Path
import platform
import sys


def runtime_identity():
    packages = {}
    for name in ('faster-whisper', 'ctranslate2', 'av', 'numpy'):
        try:
            packages[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            packages[name] = None
    return {'python': platform.python_version(), 'executable': str(Path(sys.executable).resolve()),
            'os': platform.platform(), 'cpu': platform.processor() or None, 'packages': packages,
            'pid': os.getpid()}


def resource_identity(directory):
    """Fingerprint the files read by this worker, once per actual model load.

    A declared repository/revision is reported only when its file hashes match.
    CLI/legacy assets remain usable but are never assigned invented provenance.
    """
    from .paths import APP_ROOT, ordinary_tree
    directory = ordinary_tree(directory).resolve()
    manifest = json.loads((APP_ROOT / 'config/voice_resources.json').read_text(encoding='utf-8'))
    assets = {Path(a['path']).name: a for a in manifest['assets']
              if a['path'].startswith('whisper/' + directory.name + '/')}
    files, matched = {}, bool(assets)
    for name in ('model.bin', 'config.json', 'tokenizer.json', 'vocabulary.txt'):
        path = ordinary_tree(directory / name)
        if not path.is_file():
            files[name] = None
            matched = False
            continue
        with path.open('rb') as source:
            digest = hashlib.file_digest(source, 'sha256').hexdigest()
        files[name] = {'sha256': digest, 'bytes': path.stat().st_size}
        expected = assets.get(name, {})
        matched = matched and expected.get('sha256') == digest and expected.get('bytes') == path.stat().st_size
    urls = [a['url'] for a in assets.values()] if matched else []
    return {'path': str(directory), 'model_identifier': directory.name, 'files': files,
            'provenance': 'pinned manifest' if matched else 'local files; origin unconfirmed',
            'source_urls': urls}


def resource_measurement():
    """Current worker RSS and per-process VRAM where the driver exposes it.

    These are observations after inference, not peak or model-only allocation.
    WDDM often does not expose per-process VRAM; unknown stays null.
    """
    result = {'rss_bytes': None, 'vram_bytes': None, 'gpu': None,
              'cpu': platform.processor() or None, 'sample': 'worker process after inference; not peak'}
    try:
        import psutil
        result['rss_bytes'] = psutil.Process().memory_info().rss
    except Exception:
        # psutil.AccessDenied/NoSuchProcess are not OSError subclasses. This
        # optional observation must not turn successful inference into a failure.
        pass
    try:
        import pynvml as nv
        nv.nvmlInit()
        try:
            for index in range(nv.nvmlDeviceGetCount()):
                device = nv.nvmlDeviceGetHandleByIndex(index)
                for process in nv.nvmlDeviceGetComputeRunningProcesses(device):
                    if process.pid == os.getpid():
                        name = nv.nvmlDeviceGetName(device)
                        result['gpu'] = name.decode() if isinstance(name, bytes) else name
                        memory = process.usedGpuMemory
                        if isinstance(memory, int) and 0 <= memory < 1 << 60:
                            result['vram_bytes'] = (result['vram_bytes'] or 0) + memory
        finally:
            nv.nvmlShutdown()
    except Exception:
        pass  # Optional measurement must never break inference.
    return result


def normalize_stt_payload(payload):
    """Copy a JSON-shaped result, retaining only paths to invalid numbers.

    No audio, transcript, values or native exception messages are logged. Calling
    this again at a later boundary preserves the original diagnostic paths.
    """
    paths = []

    def visit(value, path):
        if isinstance(value, float) and not math.isfinite(value):
            paths.append(path)
            return None
        if isinstance(value, dict):
            return {key: visit(item, (path + '.' if path else '') + key
                               if key.isidentifier() else path + '[' + json.dumps(key) + ']')
                    for key, item in value.items()}
        if isinstance(value, (list, tuple)):
            return [visit(item, f'{path}[{index}]') for index, item in enumerate(value)]
        return value

    result = visit(payload, '')
    if paths:
        diagnostics = result.get('diagnostics')
        diagnostics = diagnostics if isinstance(diagnostics, dict) else {}
        previous = diagnostics.get('non_finite_fields', [])
        previous = previous if isinstance(previous, list) else []
        diagnostics['non_finite_fields'] = list(dict.fromkeys(
            [item for item in previous if isinstance(item, str)] + paths))
        result['diagnostics'] = diagnostics
    return result


MESSAGES = {
    'dependency_missing': 'Компоненты голоса отсутствуют. Восстановите LocalMind установщиком.',
    'model_missing': 'Модель отсутствует. Нажмите «Подготовить голос» в настройках.',
    'path_invalid': 'Ресурсы голоса недоступны по сохранённому пути. Подготовьте голос повторно.',
    'resource_corrupt': 'Ресурсы повреждены. Нажмите «Подготовить голос» для восстановления.',
    'library_incompatible': 'Библиотеки голоса несовместимы. Восстановите LocalMind установщиком.',
    'gpu_error': 'GPU недоступен или не хватает памяти. Выберите профиль CPU.',
}


def classify_voice_error(exc):
    text = str(exc).lower()
    if any(x in text for x in ('cuda', 'cudnn', 'cublas', 'out of memory')):
        return 'gpu_error'
    if any(x in text for x in ('dll load', 'undefined symbol', 'metadata_errors', 'incompatible')):
        return 'library_incompatible'
    if isinstance(exc, (ImportError, ModuleNotFoundError)):
        return 'dependency_missing'
    if isinstance(exc, FileNotFoundError):
        return 'path_invalid'
    return 'resource_corrupt'
