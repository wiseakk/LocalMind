"""Bounded in-process request idempotency; workers outlive HTTP disconnects.

IDs are held for five minutes after completion, never evicted while executing.
This is intentionally not crash-persistent exactly-once delivery: a browser must
never automatically retry a request after restarting the server.
"""
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from threading import Lock
import time
import uuid


class RequestConflict(Exception):
    pass


class RequestBusy(Exception):
    pass


@dataclass
class RequestEntry:
    fingerprint: str
    initial: Future = field(default_factory=Future)
    final: Future = field(default_factory=Future)
    finished: float | None = None

    def __post_init__(self):
        # An HTTP task may cancel an asyncio wrapper when its client leaves.
        # These results belong to the execution, not that connection: marking
        # them running prevents cancellation from destroying later replays.
        self.initial.set_running_or_notify_cancel()
        self.final.set_running_or_notify_cancel()


class RequestStore:
    def __init__(self, capacity=128, workers=4, ttl=300):
        if capacity < 1 or workers < 1 or ttl <= 0:
            raise ValueError('Request store limits must be positive')
        self.capacity, self.workers, self.ttl = capacity, workers, ttl
        self._entries: dict[str, RequestEntry] = {}
        self._lock = Lock()
        self._pool = ThreadPoolExecutor(max_workers=workers, thread_name_prefix='localmind-chat')

    def begin(self, request_id: str | None, fingerprint: str, prepare, complete) -> RequestEntry:
        key = request_id or uuid.uuid4().hex
        with self._lock:
            now = time.monotonic()
            self._entries = {k: v for k, v in self._entries.items()
                             if v.finished is None or now - v.finished < self.ttl}
            if key in self._entries:
                entry = self._entries[key]
                if entry.fingerprint != fingerprint:
                    raise RequestConflict('Этот идентификатор уже использован для другого запроса.')
                return entry
            if len(self._entries) >= self.capacity:
                # Never evict an unexpired ID: a delayed retry must not execute twice.
                raise RequestBusy('Кэш запросов заполнен. Подожди несколько минут.')
            if sum(v.finished is None for v in self._entries.values()) >= self.workers:
                raise RequestBusy('Все обработчики заняты. Подожди завершения ответа.')
            entry = self._entries[key] = RequestEntry(fingerprint)
            self._pool.submit(self._run, entry, prepare, complete)
            return entry

    def _run(self, entry, prepare, complete):
        try:
            prepared = prepare()
            entry.initial.set_result(prepared.initial)
            try:
                final = complete(prepared)
            except Exception:
                # Generation is downstream of execution. Even an unexpected
                # composer defect must not erase the already trusted outcome
                # or invite the caller to execute again to obtain a response.
                final = dict(prepared.initial)
                final['commentary_error'] = 'Не удалось сформировать комментарий. Результат проверки сохранён.'
                if not final.get('action_results') and final.get('engine') == 'pending':
                    final.update(answer='Не удалось сформировать ответ локальной модели.', engine='offline-error')
            entry.final.set_result(final)
        except Exception as exc:
            if not entry.initial.done():
                entry.initial.set_exception(exc)
            entry.final.set_exception(exc)
        finally:
            with self._lock:
                entry.finished = time.monotonic()

    def close(self):
        self._pool.shutdown(wait=True)
