"""Bounded loopback engine supervisor. Never search PATH or stop a shared daemon."""
import ctypes
from ctypes import wintypes as w
import hashlib
import json
import os
from pathlib import Path
import re
import socket
import subprocess
from threading import Event, RLock, Thread
import time
from urllib.parse import urlsplit

import httpx
from .paths import APP_ROOT, LLM, PRIVATE, ordinary_tree


class RuntimeFailure(ValueError):
    pass


class OwnedJob:
    """The Windows kernel owns the membership, including spawned GPU runners."""
    def __init__(self, process):
        self.handle = None
        if os.name != 'nt':
            return
        class Limits(ctypes.Structure):
            _fields_ = [('process_time', ctypes.c_int64), ('job_time', ctypes.c_int64),
                ('flags', w.DWORD), ('min_working', ctypes.c_size_t), ('max_working', ctypes.c_size_t),
                ('active', w.DWORD), ('affinity', ctypes.c_size_t), ('priority', w.DWORD), ('scheduling', w.DWORD)]
        class IO(ctypes.Structure):
            _fields_ = [(name, ctypes.c_uint64) for name in ('read_ops','write_ops','other_ops','read_bytes','write_bytes','other_bytes')]
        class Extended(ctypes.Structure):
            _fields_ = [('basic', Limits), ('io', IO), ('process_memory', ctypes.c_size_t),
                ('job_memory', ctypes.c_size_t), ('peak_process', ctypes.c_size_t), ('peak_job', ctypes.c_size_t)]
        self.kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        self.kernel.CreateJobObjectW.argtypes = [ctypes.c_void_p, w.LPCWSTR]
        self.kernel.CreateJobObjectW.restype = w.HANDLE
        self.kernel.SetInformationJobObject.argtypes = [w.HANDLE, ctypes.c_int, ctypes.c_void_p, w.DWORD]
        self.kernel.AssignProcessToJobObject.argtypes = [w.HANDLE, w.HANDLE]
        self.kernel.CloseHandle.argtypes = [w.HANDLE]
        handle = self.kernel.CreateJobObjectW(None, None)
        limits = Extended(); limits.basic.flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not handle:
            raise RuntimeFailure('Windows не разрешила создать контейнер процесса движка.')
        if (not self.kernel.SetInformationJobObject(handle, 9, ctypes.byref(limits), ctypes.sizeof(limits))
                or not self.kernel.AssignProcessToJobObject(handle, int(process._handle))):
            self.kernel.CloseHandle(handle)
            raise RuntimeFailure('Windows не разрешила безопасное управление дочерним движком.')
        self.handle = handle

    def close(self):
        if self.handle:
            self.kernel.CloseHandle(self.handle)
            self.handle = None


class OllamaRuntime:
    def __init__(self, bundle=None, models=None, *, endpoint=None, popen=subprocess.Popen, job_factory=OwnedJob):
        self.bundle = Path(bundle or APP_ROOT / 'runtime/ollama')
        self.models = Path(models or LLM)
        self.explicit_models = models is not None
        from .model_stores import ModelStores
        self.stores = ModelStores(self.models)
        self.endpoint = endpoint
        self.popen, self.job_factory = popen, job_factory
        self.lock, self.stop = RLock(), Event()
        self.thread = self.process = self.job = None
        self.info = {'state': 'idle', 'owned': False, 'message': 'Движок ещё не проверен.', 'attempts': 0}

    def _url(self):
        if self.endpoint is None:
            from .agent import _local_ollama_url
            raw = _local_ollama_url()
        else:
            raw = self.endpoint
        parsed = urlsplit(raw)
        if (parsed.scheme != 'http' or parsed.hostname not in ('127.0.0.1', 'localhost')
                or parsed.username or parsed.password or parsed.path not in ('', '/') or parsed.query or parsed.fragment):
            raise RuntimeFailure('Встроенный движок требует локальный адрес 127.0.0.1 без дополнительных параметров.')
        return 'http://127.0.0.1:' + str(parsed.port or 11434)

    def _set(self, **values):
        with self.lock:
            self.info.update(values)

    def status(self):
        with self.lock:
            return dict(self.info)

    def model_stores(self):
        rows = self.stores.discover()
        state = self.status()
        shared = state['state'] == 'ready' and not state['owned']
        return {'candidates': rows, 'choice_required': not shared and not self.explicit_models and self.stores.resolve() is None,
                'switch_available': not shared, 'current_path': str(self.models) if state['owned'] else None}

    def select_store(self, store_id, fingerprint):
        # A shared daemon's directory cannot be changed from this process.
        if self.process is None:
            try:
                self.probe()
            except (httpx.HTTPError, ValueError):
                pass
            else:
                raise RuntimeFailure('Работает общий Ollama. Его каталог и процесс LocalMind не изменяет.')
        root = self.stores.select(store_id, fingerprint)
        self.close()
        self.models = root
        return self.start()

    def start(self):
        with self.lock:
            if self.thread and self.thread.is_alive():
                return dict(self.info)
            self.stop.clear()
            self.info = {'state': 'checking', 'owned': False, 'message': 'Проверяем локальный движок…', 'attempts': 0}
            self.thread = Thread(target=self._work, daemon=True, name='LocalMind-Ollama')
            self.thread.start()
            return dict(self.info)

    def retry(self):
        with self.lock:
            owned = self.process is not None and self.process.poll() is None
            state = self.info['state']
        if owned and state == 'ready':
            try:
                self.probe()
            except (httpx.HTTPError, ValueError):
                self.close()  # Explicit retry can restart only our own unhealthy job.
        return self.start()

    def probe(self):
        with httpx.Client(timeout=1, trust_env=False, follow_redirects=False) as client:
            data = []
            for endpoint in ('version', 'tags'):
                deadline = time.monotonic() + 3
                with client.stream('GET', self._url() + '/api/' + endpoint) as response:
                    response.raise_for_status()
                    content = bytearray()
                    for chunk in response.iter_bytes():
                        content.extend(chunk)
                        if self.stop.is_set():
                            raise InterruptedError()
                        if len(content) > 2 * 1024**2 or time.monotonic() > deadline:
                            raise RuntimeFailure('Порт занят: ответ сервиса не похож на Ollama.')
                data.append(json.loads(content))
        match = re.fullmatch(r'(\d+)\.(\d+)\.(\d+)(?:[-+].*)?', str(data[0].get('version', '')))
        if not match or tuple(map(int, match.groups())) < (0, 6, 6) or not isinstance(data[1].get('models'), list):
            raise RuntimeFailure('Работающий движок несовместим. Обновите Ollama и нажмите «Повторить».')
        return data[0]['version']

    def _occupied(self):
        parsed = urlsplit(self._url())
        with socket.socket() as client:
            client.settimeout(.4)
            return client.connect_ex(('127.0.0.1', parsed.port)) == 0

    def _executable(self):
        if os.name != 'nt':
            raise RuntimeFailure('Встроенный движок поставляется для Windows x64.')
        index = ordinary_tree(self.bundle / 'runtime-manifest.json')
        if not index.is_file():
            raise RuntimeFailure('Встроенный движок отсутствует. Восстановите LocalMind новым установщиком.')
        data = json.loads(index.read_text(encoding='utf-8'))
        if data.get('version') != '0.40.14' or 'ollama.exe' not in data.get('files', {}):
            raise RuntimeFailure('Манифест движка повреждён. Восстановите установку.')
        actual = set()
        for path in self.bundle.rglob('*'):
            ordinary_tree(path)
            if path.is_file() and path.name != 'runtime-manifest.json':
                actual.add(path.relative_to(self.bundle).as_posix())
        if actual != set(data['files']):
            raise RuntimeFailure('Состав движка изменился. Восстановите установку LocalMind.')
        self._set(state='verifying', message='Проверяем файлы встроенного движка…')
        for name, expected in data['files'].items():
            fragment = Path(name)
            if fragment.is_absolute() or fragment.drive or '..' in fragment.parts or ':' in name:
                raise RuntimeFailure('Некорректный путь в манифесте движка.')
            path = ordinary_tree(self.bundle / fragment)
            digest = hashlib.sha256()
            with path.open('rb') as source:
                while chunk := source.read(1024**2):
                    if self.stop.is_set():
                        raise InterruptedError()
                    digest.update(chunk)
            if digest.hexdigest() != expected:
                raise RuntimeFailure('Файлы движка изменились. Восстановите установку LocalMind.')
        return ordinary_tree(self.bundle / 'ollama.exe')

    def _dispose(self):
        with self.lock:
            child, job = self.process, self.job
            self.process = self.job = None
        if job:
            job.close()  # Only members assigned by this instance, never a PID/name sweep.
        if child and child.poll() is None:
            child.terminate()
            try:
                child.wait(timeout=5)
            except subprocess.TimeoutExpired:
                child.kill(); child.wait(timeout=5)

    def _ensure(self):
        try:
            version = self.probe()
        except (httpx.HTTPError, ValueError, TypeError, KeyError):
            if self._occupied():
                raise RuntimeFailure('Локальный порт занят несовместимым сервисом. LocalMind не останавливает чужие процессы. Освободите порт и нажмите «Повторить».')
        else:
            self._set(state='ready', owned=False, version=version, message='Используется уже работающий локальный Ollama.')
            return False
        if not self.explicit_models:
            selected = self.stores.resolve()
            if selected is None:
                self._set(state='storage_choice_required', owned=False,
                    message='Найдены существующие модели Ollama. Выберите их каталог без копирования и повторной загрузки.')
                return False
            self.models = selected
        executable = self._executable()
        if self.stop.is_set():
            raise InterruptedError()
        ordinary_tree(self.models).mkdir(parents=True, exist_ok=True)
        if not self.explicit_models:
            self.stores.remember(self.models)
        home = ordinary_tree(PRIVATE / 'ollama-home'); home.mkdir(parents=True, exist_ok=True)
        environment = {k: v for k, v in os.environ.items() if not k.upper().startswith('OLLAMA_')}
        environment.update(OLLAMA_HOST=self._url().removeprefix('http://'), OLLAMA_NO_CLOUD='1',
            OLLAMA_MODELS=str(self.models), OLLAMA_NOPRUNE='1', OLLAMA_DEBUG='false', OLLAMA_KEEP_ALIVE='300',
            USERPROFILE=str(home), HOME=str(home))
        self._set(state='starting', owned=True, message='Запускаем встроенный движок…')
        child = self.popen([str(executable), 'serve'], cwd=str(self.bundle), env=environment, shell=False,
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        with self.lock:
            self.process = child
        self.job = self.job_factory(child)
        deadline = time.monotonic() + 45
        while not self.stop.is_set() and time.monotonic() < deadline and child.poll() is None:
            try:
                version = self.probe()
                from .ollama_storage import listener_process
                listener = listener_process()
                if listener is not None and listener.pid == child.pid:
                    self._set(state='ready', owned=True, pid=child.pid, version=version, message='Встроенный движок готов. Модель выбирается отдельно.')
                    return True
            except (httpx.HTTPError, ValueError, TypeError, KeyError):
                pass
            self.stop.wait(.25)
        raise RuntimeFailure('Движок не подтвердил готовность API. Проверьте свободное место и восстановите runtime; затем нажмите «Повторить».')

    def _work(self):
        try:
            for attempt in range(3):
                self._set(attempts=attempt + 1)
                if not self._ensure():
                    return
                while not self.stop.wait(1) and self.process.poll() is None:
                    pass
                self._dispose()
                if self.stop.is_set():
                    return
                if attempt == 2:
                    raise RuntimeFailure('Движок повторно завершился. Автозапуск остановлен; нажмите «Повторить» после проверки установки.')
                self._set(state='recovering', message='Движок завершился. Восстанавливаем собственный процесс…')
                if self.stop.wait(1):
                    return
        except Exception as exc:
            self._dispose()
            if not self.stop.is_set():
                self._set(state='error', owned=False, message=str(exc) if isinstance(exc, RuntimeFailure)
                    else 'Не удалось запустить встроенный движок. Восстановите установку и нажмите «Повторить».')

    def close(self):
        self.stop.set()
        thread = self.thread
        if thread:
            thread.join(timeout=10)
        self._dispose()
        self._set(state='stopped', owned=False, message='Движок LocalMind остановлен.')


runtime = OllamaRuntime()
