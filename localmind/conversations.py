"""Durable chat journal with bounded inference memory. Text is never authority.

The turn lease spans preparation, execution and completion. HTTP reconnects use
RequestStore's same future and therefore neither acquire a second lease nor
append another turn. IDs and references are never accepted from model prose.
"""
from dataclasses import dataclass, field
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import re
import sqlite3
from threading import RLock
import secrets
import time

from . import paths
from .conversation_db import ConversationDatabase


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
    attachments: dict = field(default_factory=dict)
    active: int = 0
    lock: object = field(default_factory=RLock)
    title: str = 'Новый чат'
    draft: str = ''
    context: dict = field(default_factory=lambda: {'local_retrieval': False, 'attachment_ids': []})
    created_at: str | None = None
    updated_at: str | None = None
    _persist_turn: object = field(default=None, repr=False)
    _saved_state: str = field(default='', repr=False)

    def remember(self, text, final, reference=None):
        # Commit the complete turn before changing the shorter inference window.
        # Failures propagate to the request result; no silent memory-only success.
        if self._persist_turn is not None:
            self._persist_turn(self, text, final)
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
    def __init__(self, capacity=128, ttl=1800, clock=time.monotonic, path=None):
        self.capacity, self.ttl, self.clock = capacity, ttl, clock
        self._items, self._lock = {}, RLock()
        self._database = ConversationDatabase(path)

    @contextmanager
    def _transaction(self, *, write=False):
        # Existing storage relocation refuses new mutations while copying. All
        # short-lived SQLite connections close before the mutation is released.
        from . import storage
        entered = False
        try:
            if write or self._database.path is not None:
                storage.begin_mutation()
                entered = True
            with self._database.transaction(write=write) as connection:
                yield connection
        except (sqlite3.Error, OSError) as exc:
            raise ConversationError('Не удалось сохранить или прочитать историю. Проверьте свободное место и доступ к каталогу данных.') from exc
        except ValueError as exc:
            if isinstance(exc, ConversationError):
                raise
            raise ConversationError(str(exc)) from exc
        finally:
            if entered:
                storage.end_mutation()

    @staticmethod
    def _now():
        return datetime.now(timezone.utc).isoformat(timespec='milliseconds')

    @staticmethod
    def _validate_key(key):
        if not isinstance(key, str) or not re.fullmatch(r'[a-zA-Z0-9_-]{32,64}', key):
            raise ConversationError('Недопустимый идентификатор беседы.')

    @staticmethod
    def _context(raw, attachments):
        if not isinstance(raw, dict) or set(raw) - {'local_retrieval', 'attachment_ids'}:
            raise ConversationError('Недопустимый контекст беседы.')
        enabled, selected = raw.get('local_retrieval', False), raw.get('attachment_ids', [])
        if (type(enabled) is not bool or not isinstance(selected, list) or len(selected) > 8
                or any(not isinstance(key, str) or key not in attachments for key in selected)
                or len(set(selected)) != len(selected)):
            raise ConversationError('Выбранные вложения недоступны или контекст недопустим.')
        return {'local_retrieval': enabled, 'attachment_ids': selected.copy()}

    @staticmethod
    def _state(conversation):
        # Uploads were explicitly selected by the user; only their decoded form
        # is retained. OS file/window tokens, action results and API keys never
        # appear here. Audio is not an allowed attachment type.
        from .attachments import ImageAttachment
        uploads = []
        for doc in conversation.attachments.values():
            row = dict(vars(doc))
            row['kind'] = 'image' if isinstance(doc, ImageAttachment) else 'document'
            uploads.append(row)
        context = dict(conversation.context)
        context['attachment_ids'] = [key for key in context.get('attachment_ids', []) if key in conversation.attachments]
        return json.dumps({'draft': conversation.draft, 'context': context,
                           'attachments': uploads}, ensure_ascii=False, allow_nan=False)

    def _save_state(self, conversation):
        state = self._state(conversation)
        if state == conversation._saved_state:
            return
        data = json.loads(state)
        with self._lock, self._transaction(write=True) as db:
            cursor = db.execute('UPDATE conversations SET draft=?, context=?, attachments=? WHERE id=?',
                       (data['draft'], json.dumps(data['context'], ensure_ascii=False),
                        json.dumps(data['attachments'], ensure_ascii=False), conversation.id))
            if cursor.rowcount != 1:
                raise ConversationError('Беседа удалена. Начните новый чат.')
        conversation._saved_state = state

    def _append_turn(self, conversation, text, final):
        answer = final.get('answer', '')
        if not isinstance(text, str) or not isinstance(answer, str):
            raise ConversationError('Текст ответа не удалось сохранить.')
        now = self._now()
        title = text.strip()[:80] if conversation.title == 'Новый чат' and text.strip() else conversation.title
        topic = text[:300] if not final.get('action_results') else conversation.topic
        state = self._state(conversation)
        data = json.loads(state)
        # Only the submitted input is consumed by this commit. A separate
        # user draft must survive; a failed commit must retain the input too.
        if data['draft'] == text:
            data['draft'] = ''
            state = json.dumps(data, ensure_ascii=False, allow_nan=False)
        with self._lock, self._transaction(write=True) as db:
            if db.execute('SELECT 1 FROM conversations WHERE id=?', (conversation.id,)).fetchone() is None:
                raise ConversationError('Беседа удалена. Начните новый чат.')
            sequence = db.execute('SELECT COALESCE(MAX(sequence),-1)+1 FROM messages WHERE conversation_id=?',
                                  (conversation.id,)).fetchone()[0]
            for offset, (role, content) in enumerate((('user', text), ('assistant', answer))):
                db.execute('INSERT INTO messages VALUES (?,?,?,?,?,?)',
                           (secrets.token_hex(16), conversation.id, sequence + offset, role, content, now))
            db.execute('UPDATE conversations SET title=?,updated_at=?,topic=?,draft=?,context=?,attachments=? WHERE id=?',
                       (title, now, topic, data['draft'], json.dumps(data['context'], ensure_ascii=False),
                        json.dumps(data['attachments'], ensure_ascii=False), conversation.id))
        conversation.title, conversation.updated_at = title, now
        conversation.draft = data['draft']
        conversation._saved_state = state

    def _load(self, key):
        from .attachments import Document, ImageAttachment
        with self._transaction() as db:
            row = db.execute('SELECT * FROM conversations WHERE id=?', (key,)).fetchone()
            if row is None:
                raise ConversationError('Беседа не найдена или удалена. Начните новый чат.')
            recent = db.execute('SELECT role,content FROM messages WHERE conversation_id=? ORDER BY sequence DESC LIMIT 12',
                                (key,)).fetchall()
        conversation = Conversation(key, self.clock(), title=row['title'], draft=row['draft'],
                                    created_at=row['created_at'], updated_at=row['updated_at'], topic=row['topic'])
        try:
            for upload in json.loads(row['attachments']):
                kind = upload.pop('kind')
                doc = ImageAttachment(**upload) if kind == 'image' else Document(**upload)
                conversation.attachments[doc.id] = doc
            conversation.context = self._context(json.loads(row['context']), conversation.attachments)
        except (ValueError, TypeError, KeyError) as exc:
            raise ConversationError('Сохранённый контекст повреждён. История сообщений сохранена; восстановите данные из копии.') from exc
        conversation.history = [{'role': m['role'], 'content': m['content'][:2000 if m['role'] == 'user' else 2600]}
                                for m in reversed(recent)]
        while sum(len(m['content']) for m in conversation.history) > 12000:
            del conversation.history[:2]
        # Runtime targets are deliberately empty after cache expiry or restart.
        conversation.focus = 'topic' if conversation.topic else None
        conversation._persist_turn = self._append_turn
        conversation._saved_state = self._state(conversation)
        return conversation

    def _prune(self):
        now = self.clock()
        self._items = {k: v for k, v in self._items.items()
                       if v.active or now - v.touched < self.ttl}

    def _make_room(self):
        self._prune()
        if len(self._items) >= self.capacity:
            available = [item for item in self._items.values() if not item.active]
            if not available:
                raise ConversationError('Все беседы сейчас обрабатываются. Подождите завершения ответа.')
            oldest = min(available, key=lambda item: item.touched)
            self._items.pop(oldest.id)

    def create(self):
        with self._lock:
            self._make_room()
            key = secrets.token_urlsafe(24)
            now = self._now()
            with self._transaction(write=True) as db:
                db.execute('INSERT INTO conversations(id,title,created_at,updated_at) VALUES(?,?,?,?)',
                           (key, 'Новый чат', now, now))
            self._items[key] = self._load(key)
            return key

    def acquire(self, key):
        self._validate_key(key)
        with self._lock:
            self._prune()
            conversation = self._items.get(key)
            if conversation is None:
                self._make_room()
                conversation = self._load(key)
                self._items[key] = conversation
            # Pin before waiting; a queued turn cannot expire under its waiter.
            conversation.active += 1
        if not conversation.lock.acquire(timeout=90):
            with self._lock:
                conversation.active -= 1
            raise ConversationError('Предыдущий ответ ещё обрабатывается.')
        with self._lock:
            if self._items.get(key) is not conversation:
                conversation.active -= 1
                conversation.lock.release()
                raise ConversationError('Беседа удалена. Начните новый чат.')
        return conversation

    def release(self, conversation):
        try:
            self._save_state(conversation)
        except ConversationError:
            # A failed upload/draft flush must not look saved on the next read.
            # Existing waiters fail the identity check instead of using context
            # that was never committed; reloading restores the last transaction.
            with self._lock:
                if self._items.get(conversation.id) is conversation:
                    self._items.pop(conversation.id)
            raise
        finally:
            with self._lock:
                conversation.touched = self.clock()
                conversation.active -= 1
            conversation.lock.release()

    def reset(self, key):
        conversation = self.acquire(key)
        try:
            now = self._now()
            with self._lock, self._transaction(write=True) as db:
                db.execute('DELETE FROM messages WHERE conversation_id=?', (key,))
                db.execute("UPDATE conversations SET topic='',draft='',context='{}',attachments='[]',updated_at=? WHERE id=?",
                           (now, key))
            conversation.history.clear()
            conversation.references.clear()
            conversation.facts.clear()
            conversation.attachments.clear()
            conversation.focus, conversation.topic = None, ''
            conversation.draft = ''
            conversation.context = {'local_retrieval': False, 'attachment_ids': []}
            conversation.updated_at = now
            conversation._saved_state = self._state(conversation)
        finally:
            self.release(conversation)

    def list(self):
        with self._lock, self._transaction() as db:
            return [dict(row) for row in db.execute('''SELECT c.id AS conversation_id,c.title,c.created_at,c.updated_at,
                (SELECT COUNT(*) FROM messages m WHERE m.conversation_id=c.id) AS message_count
                FROM conversations c ORDER BY c.updated_at IS NULL,c.updated_at DESC,c.rowid DESC''')]

    def read(self, key):
        conversation = self.acquire(key)
        try:
            with self._lock, self._transaction() as db:
                messages = [dict(row) for row in db.execute('SELECT id,role,content,created_at FROM messages WHERE conversation_id=? ORDER BY sequence', (key,))]
            return {'conversation_id': key, 'title': conversation.title, 'created_at': conversation.created_at,
                    'updated_at': conversation.updated_at, 'draft': conversation.draft,
                    'context': dict(conversation.context), 'messages': messages,
                    'attachments': [doc.public(preview=True) for doc in conversation.attachments.values()]}
        finally:
            self.release(conversation)

    def update(self, key, *, title=None, draft=None, context=None):
        if title is not None and (not isinstance(title, str) or not 1 <= len(title.strip()) <= 80):
            raise ConversationError('Название должно содержать от 1 до 80 символов.')
        if draft is not None and (not isinstance(draft, str) or len(draft) > 2000):
            raise ConversationError('Черновик должен содержать не более 2000 символов.')
        conversation = self.acquire(key)
        try:
            validated = self._context(context, conversation.attachments) if context is not None else conversation.context
            next_title = title.strip() if title is not None else conversation.title
            next_draft = draft if draft is not None else conversation.draft
            with self._lock, self._transaction(write=True) as db:
                db.execute('UPDATE conversations SET title=?,draft=?,context=? WHERE id=?',
                           (next_title, next_draft, json.dumps(validated, ensure_ascii=False), key))
            conversation.title, conversation.draft, conversation.context = next_title, next_draft, validated
            conversation._saved_state = self._state(conversation)
        finally:
            self.release(conversation)
        return self.read(key)

    def delete(self, key, *, confirmed=False):
        if confirmed is not True:
            raise ConversationError('Подтвердите удаление беседы.')
        conversation = self.acquire(key)
        try:
            with self._lock, self._transaction(write=True) as db:
                if conversation.active > 1:
                    raise ConversationError('Дождитесь завершения запросов к беседе перед удалением.')
                db.execute('DELETE FROM conversations WHERE id=?', (key,))
            with self._lock:
                self._items.pop(key, None)
        finally:
            # No release/save after deletion: a delayed save cannot resurrect it.
            with self._lock:
                conversation.active -= 1
            conversation.lock.release()

    def import_legacy(self, items, migration_id):
        if not isinstance(migration_id, str) or not re.fullmatch('[a-f0-9]{64}', migration_id):
            raise ConversationError('Недопустимый идентификатор переноса истории.')
        if not isinstance(items, list) or len(items) > 40:
            raise ConversationError('Перенос ограничен 40 беседами за один раз.')
        try:
            encoded = json.dumps(items, ensure_ascii=False, allow_nan=False, sort_keys=True)
        except (ValueError, TypeError, RecursionError) as exc:
            raise ConversationError('Старая история повреждена. Исходная копия сохранена.') from exc
        if len(encoded.encode('utf-8')) > 3_000_000:
            raise ConversationError('Старая история превышает безопасный размер переноса.')
        rows = []
        for item in items:
            if not isinstance(item, dict) or set(item) - {'title', 'draft', 'messages'}:
                raise ConversationError('Некорректная запись старой истории.')
            title, draft, messages = item.get('title'), item.get('draft', ''), item.get('messages')
            if (not isinstance(title, str) or not 1 <= len(title.strip()) <= 80
                    or not isinstance(draft, str) or len(draft) > 2000
                    or not isinstance(messages, list) or len(messages) > 80):
                raise ConversationError('Некорректное название, черновик или размер старой истории.')
            for message in messages:
                if (not isinstance(message, dict) or set(message) != {'role', 'content'}
                        or message.get('role') not in ('user', 'assistant')
                        or not isinstance(message.get('content'), str) or len(message['content']) > 8192):
                    raise ConversationError('Некорректное сообщение старой истории.')
            rows.append((secrets.token_urlsafe(24), title.strip(), draft, messages))
        payload_hash = hashlib.sha256(encoded.encode('utf-8')).hexdigest()
        with self._lock, self._transaction(write=True) as db:
            imported = db.execute('SELECT conversation_ids,payload_hash FROM imports WHERE digest=?', (migration_id,)).fetchone()
            if imported is not None:
                if imported['payload_hash'] != payload_hash:
                    raise ConversationError('Этот перенос уже выполнен с другим содержимым. Исходная копия сохранена.')
                return {'imported': False, 'conversation_ids': json.loads(imported[0])}
            for key, title, draft, messages in rows:
                # Legacy browser records contain no dates. NULL means unknown;
                # the import time must never be presented as a fabricated date.
                db.execute('INSERT INTO conversations(id,title,draft) VALUES(?,?,?)', (key, title, draft))
                for sequence, message in enumerate(messages):
                    db.execute('INSERT INTO messages VALUES(?,?,?,?,?,NULL)',
                               (secrets.token_hex(16), key, sequence, message['role'], message['content']))
            keys = [row[0] for row in rows]
            db.execute('INSERT INTO imports VALUES(?,?,?)', (migration_id, json.dumps(keys), payload_hash))
        return {'imported': True, 'conversation_ids': keys}


conversations = ConversationStore(path=paths.HISTORY / 'conversations.sqlite3')
