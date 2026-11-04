"""Bounded durable job journal. A restart never silently restarts side effects."""
import copy
import json
from pathlib import Path
from threading import RLock
import time
from .paths import DOWNLOADS, PRIVATE, atomic_json, ordinary_tree

ACTIVE = ('queued', 'starting', 'downloading', 'verifying', 'cancelling')
MAX_ACTIVE = 4


def resource_key(job):
    """Admission follows physical files, never a display name or UI profile."""
    kind = job.get('kind')
    if kind == 'asr':
        return 'whisper:' + ('medium' if job.get('profile') == 'gpu-quality' else 'small')
    if kind == 'tts':
        return 'silero:ru'
    if kind in ('llm', 'llm_offline') and job.get('model'):
        return 'ollama:' + job['model']
    return 'job:' + job['id']


class JobStore:
    def __init__(self, path=None, *, legacy_path=None):
        self.path = Path(path) if path else None
        self.lock = RLock()
        self.jobs = {}
        self._samples = {}
        source = self.path
        if source and not source.exists() and legacy_path and Path(legacy_path).exists():
            source = Path(legacy_path)
            # Continue using the owner's existing journal in place. Relocating
            # files requires the reviewed storage plan, including for metadata.
            self.path = source
        if source and source.exists():
            try:
                ordinary_tree(source)
                if source.stat().st_size > 1048576:
                    raise ValueError('Oversized journal')
                data = json.loads(source.read_text(encoding='utf-8'))
                if not isinstance(data, list) or len(data) > 32:
                    raise ValueError('Invalid journal')
                for job in data:
                    if not isinstance(job, dict) or not isinstance(job.get('id'), str):
                        raise ValueError('Invalid job')
                    if job.get('status') in ACTIVE:
                        message = ('Поток прерван перезапуском. Работа Ollama не проверена; повтор — только по кнопке.'
                                   if job.get('kind') in ('llm', 'llm_offline') else
                                   'Подготовка прервана перезапуском. Нажмите «Повторить».')
                        job.update(status='interrupted', error=message)
                    job.update(bytes_per_second=None, eta_seconds=None)
                    self.jobs[job['id']] = job
                self.save()
            except (OSError, ValueError, TypeError, KeyError):
                # Preserve an unreadable journal for diagnosis; fail closed.
                self.jobs = {}
                self.path = None
                self.unavailable = True

    def save(self):
        if getattr(self, 'unavailable', False):
            raise ValueError('Журнал загрузок повреждён или недоступен. Восстановите хранилище приложения.')
        if self.path:
            atomic_json(self.path, list(self.jobs.values()))

    def snapshot(self, key=None):
        with self.lock:
            if getattr(self, 'unavailable', False):
                raise ValueError('Журнал загрузок повреждён или недоступен. Восстановите хранилище приложения.')
            if key is not None:
                if key not in self.jobs:
                    raise ValueError('Задача недоступна.')
                return copy.deepcopy(self.jobs[key])
            return copy.deepcopy(list(self.jobs.values()))

    def update(self, key, **fields):
        with self.lock:
            previous = copy.deepcopy(self.jobs[key])
            self.jobs[key].update(fields)
            job = self.jobs[key]
            # A first observation may include cached layers, not network traffic.
            # Rate only measures subsequent positive byte deltas in this process.
            if 'completed' in fields:
                current, now = job.get('completed'), time.monotonic()
                sample = self._samples.get(key)
                if isinstance(current, (int, float)) and not isinstance(current, bool) and current >= 0:
                    if sample and current >= sample[1] and now - sample[0] >= 1:
                        rate = (current - sample[1]) / (now - sample[0])
                        job['bytes_per_second'] = rate if rate > 0 else None
                        total = job.get('total')
                        job['eta_seconds'] = ((total - current) / rate
                            if rate > 0 and isinstance(total, (int, float)) and total >= current else None)
                        self._samples[key] = (now, current)
                    elif sample is None or current < sample[1]:
                        self._samples[key] = (now, current)
                        job.update(bytes_per_second=None, eta_seconds=None)
            if job.get('status') != 'downloading':
                job.update(bytes_per_second=None, eta_seconds=None)
            job['updated_at'] = time.time()
            try:
                self.save()
            except Exception:
                self.jobs[key] = previous
                raise

    def terminal_failure(self, key, *, status='failed', **fields):
        """Release admission even when a failed worker cannot write its journal.

        Progress/readiness updates remain transactional. Only a terminal error
        may fall back to memory, with an explicit warning about persistence.
        A later successful journal write persists this state; after a restart
        an older active row is safely shown as interrupted, never auto-retried.
        """
        if status not in ('failed', 'cancelled', 'cancelled_unverified', 'interrupted'):
            raise ValueError('Ожидается завершающее состояние ошибки.')
        with self.lock:
            try:
                self.update(key, status=status, **fields)
            except (OSError, ValueError):
                message = ('Не удалось сохранить журнал загрузок. Освободите место и проверьте доступ к хранилищу; '
                           'затем нажмите «Повторить».')
                error = fields.get('error') or 'Подготовка остановлена.'
                self.jobs[key].update(fields, status='failed', ready=False,
                    error=error + ' ' + message, persistence_error=message,
                    bytes_per_second=None, eta_seconds=None, updated_at=time.time())
                self._samples.pop(key, None)

    def dismiss(self, key):
        with self.lock:
            job = self.snapshot(key)
            if job.get('status') in ACTIVE:
                raise ValueError('Сначала дождитесь завершения задачи.')
            self.update(key, dismissed=True)
            return self.snapshot(key)

    def insert(self, job):
        with self.lock:
            active = [j for j in self.jobs.values() if j['status'] in ACTIVE]
            if any(resource_key(existing) == resource_key(job) for existing in active):
                raise ValueError('Подготовка этого ресурса уже выполняется. Смотрите «Загрузки».')
            if len(active) >= MAX_ACTIVE:
                raise ValueError('Все места загрузки заняты. Дождитесь завершения одной из задач.')
            evicted = None
            if len(self.jobs) >= 32:
                evicted_key = next((key for key, old in self.jobs.items() if old['status'] not in ACTIVE), None)
                if evicted_key is None:
                    raise ValueError('Журнал заполнен выполняющимися задачами.')
                evicted = (evicted_key, self.jobs.pop(evicted_key))
            self.jobs[job['id']] = job
            try:
                self.save()
            except Exception:
                self.jobs.pop(job['id'], None)
                if evicted:
                    self.jobs[evicted[0]] = evicted[1]
                raise


store = JobStore(DOWNLOADS / 'jobs.json', legacy_path=PRIVATE / 'downloads.json')
