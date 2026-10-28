"""Ephemeral, bounded server memory. Text is context, never authority.

The turn lease spans preparation, execution and completion. HTTP reconnects use
RequestStore's same future and therefore neither acquire a second lease nor
append another turn. IDs and references are never accepted from model prose.
"""
from dataclasses import dataclass, field
from threading import Lock, RLock
import secrets
import time


class ConversationError(ValueError):
    pass


@dataclass(frozen=True)
class Reference:
    kind: str
    id: str


@dataclass
class Conversation:
    id: str
    touched: float
    history: list = field(default_factory=list)
    references: dict[str, Reference] = field(default_factory=dict)
    focus: str | None = None
    topic: str = ''
    facts: list = field(default_factory=list)
    active: int = 0
    lock: object = field(default_factory=RLock)

    def remember(self, text, final, reference=None):
        self.history.extend(({'role': 'user', 'content': text[:2000]},
                             {'role': 'assistant', 'content': final.get('answer', '')[:2600]}))
        self.history[:] = self.history[-12:]
        # Old prose is discarded whole, never summarized into a permission.
        while sum(len(m['content']) for m in self.history) > 12000:
            del self.history[:2]
        outcomes = final.get('action_results', [])
        if outcomes:
            self.facts.extend(outcomes)
            self.facts[:] = self.facts[-4:]
            if reference:
                self.references[reference.kind] = reference
                self.focus = reference.kind
                if reference.kind == 'application':
                    self.references.pop('window', None)
            for result in outcomes:
                data = result.get('data')
                if result.get('success') and isinstance(data, dict) and isinstance(data.get('window_id'), str):
                    self.references['window'] = Reference('window', data['window_id'])
                if result.get('success') and isinstance(data, dict) and isinstance(data.get('app_id'), str):
                    self.references['application'] = Reference('application', data['app_id'])
        else:
            self.topic = text[:300]
            self.focus = 'topic'

    def public_facts(self):
        return {'topic': self.topic, 'last_results': self.facts,
                'references': {k: {'kind': v.kind, 'id': v.id} for k, v in self.references.items()}}


class ConversationStore:
    def __init__(self, capacity=128, ttl=1800, clock=time.monotonic):
        self.capacity, self.ttl, self.clock = capacity, ttl, clock
        self._items, self._lock = {}, Lock()

    def _prune(self):
        now = self.clock()
        self._items = {k: v for k, v in self._items.items()
                       if v.active or now - v.touched < self.ttl}

    def create(self):
        with self._lock:
            self._prune()
            if len(self._items) >= self.capacity:
                raise ConversationError('Слишком много разговоров. Подожди или сбрось текущий.')
            key = secrets.token_urlsafe(24)
            self._items[key] = Conversation(key, self.clock())
            return key

    def acquire(self, key):
        with self._lock:
            self._prune()
            conversation = self._items.get(key)
            if conversation is None:
                raise ConversationError('Разговор истёк или сервер перезапущен. Начни новый разговор.')
            # Pin before waiting; a queued turn cannot expire under its waiter.
            conversation.active += 1
        if not conversation.lock.acquire(timeout=90):
            with self._lock:
                conversation.active -= 1
            raise ConversationError('Предыдущий ответ ещё обрабатывается.')
        return conversation

    def release(self, conversation):
        with self._lock:
            conversation.touched = self.clock()
            conversation.active -= 1
        conversation.lock.release()

    def reset(self, key):
        conversation = self.acquire(key)
        try:
            conversation.history.clear()
            conversation.references.clear()
            conversation.facts.clear()
            conversation.focus, conversation.topic = None, ''
        finally:
            self.release(conversation)


conversations = ConversationStore()
