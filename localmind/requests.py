"""Bounded in-process request idempotency; workers outlive HTTP disconnects.

IDs are held for five minutes after completion, never evicted while executing.
This is intentionally not crash-persistent exactly-once delivery: a browser must
never automatically retry a request after restarting the server.
"""
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from threading import Lock, Condition, Event
import time
import uuid
from .generation import cancellation


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
    deltas: list[str] = field(default_factory=list)
    delta_chars: int = 0
    changed: Condition = field(default_factory=Condition)
    cancelled: Event = field(default_factory=Event)

    def publish(self, delta):
        with self.changed:
            if self.cancelled.is_set():
                raise ValueError('Generation cancelled')
            if not isinstance(delta, str) or not delta or self.delta_chars + len(delta) > 8192:
                return
            self.deltas.append(delta)
            self.delta_chars += len(delta)
            self.changed.notify_all()

    def read_deltas(self, offset):
        with self.changed:
            if len(self.deltas) == offset and not self.final.done():
                self.changed.wait(timeout=1)
            return self.deltas[offset:], self.final.done()

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
        # Bounded retired IDs are never silently reusable during this process.
        # Once full, admission fails closed until a server restart/new instance.
        self._retired: set[str] = set()
        self._lock = Lock()
        self._pool = ThreadPoolExecutor(max_workers=workers, thread_name_prefix='localmind-chat')

    def begin(self, request_id: str | None, fingerprint: str, prepare, complete) -> RequestEntry:
        key = request_id or uuid.uuid4().hex
        with self._lock:
            now = time.monotonic()
            expired = {k for k, v in self._entries.items() if v.finished is not None and now - v.finished >= self.ttl}
            if len(self._retired | expired) > 8192:
                raise RequestBusy('Лимит идентификаторов исчерпан. Перезапусти сервер и отправь новый запрос.')
            self._retired.update(expired)
            self._entries = {k: v for k, v in self._entries.items()
                             if v.finished is None or now - v.finished < self.ttl}
            if key in self._entries:
                entry = self._entries[key]
                if entry.fingerprint != fingerprint:
                    raise RequestConflict('Этот идентификатор уже использован для другого запроса.')
                return entry
            if key in self._retired:
                raise RequestConflict('Срок запроса истёк. Проверь результат вручную и отправь новый запрос с новым ID.')
            if len(self._entries) >= self.capacity:
                # Never evict an unexpired ID: a delayed retry must not execute twice.
                raise RequestBusy('Кэш запросов заполнен. Подожди несколько минут.')
            if sum(v.finished is None for v in self._entries.values()) >= self.workers:
                raise RequestBusy('Все обработчики заняты. Подожди завершения ответа.')
            entry = self._entries[key] = RequestEntry(fingerprint)
            self._pool.submit(self._run, entry, prepare, complete)
            return entry

    def _run(self, entry, prepare, complete):
        prepared, final = None, None
        token = cancellation.set(entry.cancelled)
        try:
            prepared = prepare()
            prepared.on_delta = entry.publish
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
            if entry.cancelled.is_set():
                final['cancelled'] = True
                if not final.get('action_results'):
                    final.update(answer='Ответ прерван.', engine='cancelled')
            entry.final.set_result(final)
        except Exception as exc:
            if not entry.initial.done():
                entry.initial.set_exception(exc)
            entry.final.set_exception(exc)
        finally:
            try:
                if prepared is not None and getattr(prepared, 'finish_turn', None):
                    prepared.finish_turn(final)
            finally:
                cancellation.reset(token)
                with entry.changed:
                    entry.changed.notify_all()
                with self._lock:
                    entry.finished = time.monotonic()

    def cancel(self, request_id):
        with self._lock:
            entry = self._entries.get(request_id)
            if entry is None or entry.finished is not None:
                return False
            entry.cancelled.set()
            return True

    def close(self):
        self._pool.shutdown(wait=True)
