"""Observe the actual local daemon; environment of the client is not evidence."""
import json
import os
from pathlib import Path
import shutil
import subprocess
from threading import RLock
import time
from urllib.parse import urlsplit

from .paths import CONFIG, LLM, atomic_json, ordinary_tree

_lock = RLock()
_managed = None
_managed_path = None
_managed_identity = None


def listener_process():
    import psutil
    from .agent import _local_ollama_url
    endpoint = urlsplit(_local_ollama_url())
    port = endpoint.port or 11434
    for connection in psutil.net_connections(kind='tcp'):
        matching_address = bool(connection.laddr) and connection.laddr.ip in (
            ('127.0.0.1', '0.0.0.0') if endpoint.hostname in ('127.0.0.1', 'localhost') else ('::1', '::'))
        if (connection.status == psutil.CONN_LISTEN and matching_address
                and connection.laddr.port == port and connection.pid):
            process = psutil.Process(connection.pid)
            if process.name().casefold() in ('ollama.exe', 'ollama'):
                return process
    return None


def storage_status():
    result = {'path': None, 'confirmed': False, 'verified': False, 'source': 'unknown', 'managed': False,
              'suggested_path': str(LLM), 'notice': 'Общий сервер не останавливается. Окружение клиента не подтверждает каталог сервера.'}
    try:
        process = listener_process()
        if process is not None:
            environment = process.environ()
            if os.name == 'nt':
                environment = {key.upper(): value for key, value in environment.items()}
            configured = environment.get('OLLAMA_MODELS')
            # Windows daemon default is derived from its environment, not ours.
            if not configured and os.name == 'nt' and environment.get('USERPROFILE'):
                configured = str(Path(environment['USERPROFILE']) / '.ollama' / 'models')
            if configured and Path(configured).is_absolute():
                ordinary_tree(configured)
                result.update(path=str(Path(configured).resolve()), confirmed=True, verified=True,
                              source='Ollama listener process environment', pid=process.pid)
            with _lock:
                if (_managed is not None and _managed.poll() is None and process.pid == _managed.pid
                        and process.create_time() == _managed_identity):
                    result.update(path=str(_managed_path), managed=True, confirmed=True, verified=True,
                                  source='LocalMind launched Ollama; listener PID and start time verified')
    except (OSError, RuntimeError, ValueError):
        pass
    except Exception as exc:
        # psutil AccessDenied/NoSuchProcess do not prove a storage location.
        import psutil
        if not isinstance(exc, psutil.Error):
            raise
    return result


def instructions(raw):
    from .storage import checked_destination, free_space
    path = checked_destination(raw)
    return {'path': str(path), 'free_bytes': free_space(path), 'restart_required': True,
            'steps': ['Дождитесь завершения запросов всех приложений.',
                      'Если используете общий Ollama: самостоятельно выберите Quit в трее.',
                      'В настройках переменных среды пользователя Windows задайте OLLAMA_MODELS равным указанному пути.',
                      'Запустите Ollama снова и нажмите «Проверить». Каталог подтвердится по окружению процесса.',
                      'Старые модели остаются на исходном диске. Копирование требует отдельного согласия.'],
            'notice': 'LocalMind не изменяет системные переменные и не перезапускает общий сервер.'}


def start_managed(raw, consent=False):
    """Only start a new daemon when the configured endpoint is unoccupied."""
    global _managed, _managed_path, _managed_identity
    if consent is not True:
        raise ValueError('Подтвердите запуск отдельного Ollama для LocalMind.')
    from .storage import checked_destination
    from .agent import _local_ollama_url
    from .model_manager import ollama_json
    import httpx
    import psutil
    path = checked_destination(raw)
    endpoint = urlsplit(_local_ollama_url())
    if endpoint.hostname not in ('127.0.0.1', 'localhost'):
        raise ValueError('Управляемый сервер требует IPv4 loopback.')
    with _lock:
        try:
            ollama_json('GET', 'version')
        except httpx.ConnectError:
            pass
        else:
            raise ValueError('Ollama уже работает. Используйте настройку существующего сервера.')
        executable = shutil.which('ollama')
        if not executable or Path(executable).name.casefold() not in ('ollama', 'ollama.exe'):
            raise ValueError('Установите Ollama и повторите запуск.')
        ordinary_tree(executable)
        path.mkdir(parents=True, exist_ok=True)
        environment = dict(os.environ, OLLAMA_MODELS=str(path),
                           OLLAMA_HOST=f'127.0.0.1:{endpoint.port or 11434}', OLLAMA_NO_CLOUD='1')
        child = subprocess.Popen([str(Path(executable).resolve()), 'serve'], shell=False,
                                 env=environment, stdin=subprocess.DEVNULL,
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                 creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        _managed, _managed_path = child, path
        _managed_identity = psutil.Process(child.pid).create_time()
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline and child.poll() is None:
        state = storage_status()
        if state['managed'] and state['confirmed']:
            atomic_json(CONFIG / 'ollama-managed.json', {'path': str(path), 'auto_start': False})
            return state
        time.sleep(.2)
    raise ValueError('Процесс запущен, но сервер и путь не подтверждены. Проверьте диагностику Ollama.')


def exclusive_managed():
    # Other local applications can use any loopback daemon. PID ownership alone
    # never establishes exclusive inference ownership.
    return False
