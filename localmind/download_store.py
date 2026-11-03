"""Bounded durable job journal. A restart never silently restarts side effects."""
import copy
import json
from pathlib import Path
from threading import RLock
from .paths import PRIVATE, atomic_json, ordinary_tree

ACTIVE = ('queued', 'starting', 'downloading', 'verifying', 'cancelling')


class JobStore:
    def __init__(self, path=None):
        self.path = Path(path) if path else None
        self.lock = RLock()
        self.jobs = {}
        if self.path and self.path.exists():
            try:
                ordinary_tree(self.path)
                if self.path.stat().st_size > 1048576:
                    raise ValueError('Oversized journal')
                data = json.loads(self.path.read_text(encoding='utf-8'))
                if not isinstance(data, list) or len(data) > 32:
                    raise ValueError('Invalid journal')
                for job in data:
                    if not isinstance(job, dict) or not isinstance(job.get('id'), str):
                        raise ValueError('Invalid job')
                    if job.get('status') in ACTIVE:
                        job.update(status='interrupted', error='Загрузка прервана перезапуском. Нажмите «Повторить».')
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
            self.jobs[key].update(fields)
            self.save()

    def insert(self, job):
        with self.lock:
            if any(j['status'] in ACTIVE for j in self.jobs.values()):
                raise ValueError('Другая загрузка ещё выполняется.')
            if len(self.jobs) >= 32:
                self.jobs.pop(next(iter(self.jobs)))
            self.jobs[job['id']] = job
            try:
                self.save()
            except Exception:
                self.jobs.pop(job['id'], None)
                raise


store = JobStore(PRIVATE / 'downloads.json')
