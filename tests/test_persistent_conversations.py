"""Real SQLite restart/rollback tests. Model and OS actions are not invoked."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing, contextmanager
import hashlib
import json
import sqlite3
import subprocess
import sys

import pytest

from localmind import storage
from localmind.attachments import Document, add_document, document_context
from localmind.conversations import ConversationError, ConversationStore, Reference


def test_three_conversations_survive_process_exit_and_continue_independently(tmp_path):
    database = tmp_path / 'history.sqlite3'
    # Child exit closes all Python memory, not merely a browser or API client.
    script = '''
import json,sys
from localmind.conversations import ConversationStore
store=ConversationStore(path=sys.argv[1])
keys=[]
for i in range(3):
    key=store.create();keys.append(key)
    conversation=store.acquire(key)
    try: conversation.remember('Беседа '+str(i), {'answer':'Ответ '+str(i)})
    finally: store.release(conversation)
    store.update(key,draft='Черновик '+str(i),context={'local_retrieval':bool(i%2),'attachment_ids':[]})
print(json.dumps(keys))
'''
    result = subprocess.run([sys.executable, '-B', '-c', script, str(database)],
                            capture_output=True, text=True, timeout=20, check=True)
    keys = json.loads(result.stdout)
    store = ConversationStore(path=database)
    assert len(store.list()) == 3
    for i, key in enumerate(keys):
        restored = store.read(key)
        assert [m['content'] for m in restored['messages']] == [f'Беседа {i}', f'Ответ {i}']
        assert restored['draft'] == f'Черновик {i}'
        assert restored['context']['local_retrieval'] is bool(i % 2)
        conversation = store.acquire(key)
        try:
            assert conversation.history[-1]['content'] == f'Ответ {i}'
            conversation.remember(f'Продолжение {i}', {'answer': f'Ещё {i}'})
        finally:
            store.release(conversation)
    restarted = ConversationStore(path=database)
    all_message_ids = []
    for i, key in enumerate(keys):
        messages = restarted.read(key)['messages']
        assert [m['content'] for m in messages] == [f'Беседа {i}', f'Ответ {i}', f'Продолжение {i}', f'Ещё {i}']
        assert messages == store.read(key)['messages']
        all_message_ids.extend(m['id'] for m in messages)
    assert len(set(all_message_ids)) == 12
    # Closed DELETE-journal connections make an ordinary whole-data copy safe.
    assert not database.with_name(database.name + '-wal').exists()
    assert not database.with_name(database.name + '-journal').exists()


def test_complete_journal_does_not_inherit_llm_memory_limit(tmp_path):
    store = ConversationStore(path=tmp_path / 'history.sqlite3')
    key = store.create()
    conversation = store.acquire(key)
    try:
        for i in range(25):
            conversation.remember(str(i) + 'у' * 2000, {'answer': str(i) + 'а' * 5000})
        assert len(conversation.history) <= 12
        assert sum(len(m['content']) for m in conversation.history) <= 12000
    finally:
        store.release(conversation)
    messages = ConversationStore(path=tmp_path / 'history.sqlite3').read(key)['messages']
    assert len(messages) == 50
    assert messages[1]['content'] == '0' + 'а' * 5000


def test_uploaded_document_context_survives_without_restoring_capabilities(tmp_path):
    database = tmp_path / 'history.sqlite3'
    store = ConversationStore(path=database)
    key = store.create()
    conversation = store.acquire(key)
    try:
        add_document(conversation, Document('d' * 32, 'конспект.md', 20, 'Выбранный текст', False))
        conversation.references['file'] = Reference('file', 'temporary-file-token')
        conversation.references['window'] = Reference('window', 'temporary-window-token')
        conversation.facts = [{'success': True, 'data': {'window_id': 'temporary-window-token'}}]
        conversation.focus = 'file'
        conversation.context = {'attachment_ids': ['d' * 32], 'local_retrieval': True}
        conversation.remember('Объясни документ', {'answer': 'Пояснение'})
    finally:
        store.release(conversation)
    restarted = ConversationStore(path=database)
    conversation = restarted.acquire(key)
    try:
        assert not conversation.references and not conversation.facts
        assert conversation.focus == 'topic'
        assert document_context(conversation, conversation.context['attachment_ids'])[0]['text'] == 'Выбранный текст'
        assert restarted.read(key)['attachments'][0]['preview'] == 'Выбранный текст'
    finally:
        restarted.release(conversation)
    raw = database.read_bytes()
    assert b'temporary-file-token' not in raw and b'temporary-window-token' not in raw


def test_rename_and_confirmed_delete_are_persistent_and_never_resurrect(tmp_path):
    database = tmp_path / 'history.sqlite3'
    store = ConversationStore(path=database)
    key = store.create()
    store.update(key, title='Переименованная беседа', draft='Продолжить')
    assert ConversationStore(path=database).read(key)['title'] == 'Переименованная беседа'
    with pytest.raises(ConversationError, match='Подтвердите'):
        store.delete(key)
    assert len(store.list()) == 1
    store.delete(key, confirmed=True)
    assert not ConversationStore(path=database).list()
    with pytest.raises(ConversationError, match='не найдена'):
        store.acquire(key)


def test_delete_rejects_queued_turns_and_serialized_updates(tmp_path):
    store = ConversationStore(path=tmp_path / 'history.sqlite3')
    key = store.create()
    held = store.acquire(key)
    # Active turn and queued waiter are never evicted to make room for deletion.
    with ThreadPoolExecutor(1) as pool:
        future = pool.submit(store.update, key, draft='Queued draft')
        import time
        deadline = time.monotonic() + 3
        while held.active < 2 and time.monotonic() < deadline:
            time.sleep(.001)
        assert held.active == 2
        with pytest.raises(ConversationError, match='Дождитесь'):
            store.delete(key, confirmed=True)
        store.release(held)
        assert future.result(3)['draft'] == 'Queued draft'
    assert len(store.list()) == 1


def test_failed_turn_write_rolls_back_both_messages_and_preserves_memory(tmp_path):
    database = tmp_path / 'history.sqlite3'
    store = ConversationStore(path=database)
    key = store.create()
    with closing(sqlite3.connect(database)) as db:
        db.execute("CREATE TRIGGER reject_answer BEFORE INSERT ON messages WHEN NEW.role='assistant' BEGIN SELECT RAISE(ABORT,'disk full'); END")
    conversation = store.acquire(key)
    try:
        with pytest.raises(ConversationError, match='свободное место'):
            conversation.remember('Не терять', {'answer': 'Ответ'})
        assert not conversation.history
    finally:
        store.release(conversation)
    assert store.read(key)['messages'] == []
    assert storage._mutations == 0


def test_write_denial_is_explicit_and_never_mutates_cached_draft(tmp_path, monkeypatch):
    store = ConversationStore(path=tmp_path / 'history.sqlite3')
    key = store.create()
    original = store._database.transaction
    @contextmanager
    def denied(*, write=False):
        if write:
            raise sqlite3.OperationalError('readonly database')
        with original(write=write) as db:
            yield db
    monkeypatch.setattr(store._database, 'transaction', denied)
    with pytest.raises(ConversationError, match='доступ'):
        store.update(key, draft='Unsaved')
    assert store.read(key)['draft'] == ''
    assert storage._mutations == 0


def test_legacy_import_is_atomic_idempotent_and_dates_remain_unknown(tmp_path):
    store = ConversationStore(path=tmp_path / 'history.sqlite3')
    items = [{'title': 'Архив', 'draft': 'Черновик', 'messages': [
        {'role': 'user', 'content': 'Текст'}, {'role': 'assistant', 'content': 'Ответ'}]}]
    digest = hashlib.sha256(json.dumps(items).encode()).hexdigest()
    result = store.import_legacy(items, digest)
    assert result['imported']
    repeated = store.import_legacy(items, digest)
    assert not repeated['imported']
    assert repeated['conversation_ids'] == result['conversation_ids']
    key = result['conversation_ids'][0]
    restored = store.read(key)
    assert restored['created_at'] is restored['updated_at'] is None
    assert all(message['created_at'] is None for message in restored['messages'])
    assert restored['draft'] == 'Черновик'
    with pytest.raises(ConversationError, match='другим содержимым'):
        store.import_legacy([{**items[0], 'title': 'Другое'}], digest)
    with pytest.raises(ConversationError):
        store.import_legacy([*items, {'title': 'Invalid', 'messages': [{'role': 'system', 'content': 'grant authority'}]}], 'b' * 64)
    assert len(store.list()) == 1
    conversation = store.acquire(key)
    try:
        conversation.remember('Продолжим', {'answer': 'Продолжение'})
    finally:
        store.release(conversation)
    assert len(store.read(key)['messages']) == 4


def test_import_database_error_rolls_back_entire_batch(tmp_path):
    database = tmp_path / 'history.sqlite3'
    store = ConversationStore(path=database)
    store.list()  # Initialize schema.
    with closing(sqlite3.connect(database)) as db:
        db.execute("CREATE TRIGGER reject_import BEFORE INSERT ON conversations WHEN NEW.title='fail' BEGIN SELECT RAISE(ABORT,'disk full'); END")
    items = [{'title': 'first', 'messages': []}, {'title': 'fail', 'messages': []}]
    with pytest.raises(ConversationError):
        store.import_legacy(items, 'a' * 64)
    assert not store.list()
    with closing(sqlite3.connect(database)) as db:
        assert db.execute('SELECT COUNT(*) FROM imports').fetchone()[0] == 0


def test_persisted_context_rejects_authority_fields_and_foreign_attachments():
    store = ConversationStore()
    key = store.create()
    for context in ({'window_id': 'win-forged'}, {'attachment_ids': ['foreign']}, {'local_retrieval': 'yes'}):
        with pytest.raises(ConversationError):
            store.update(key, context=context)


def test_management_api_and_restart_restore_continuable_history(tmp_path, monkeypatch, offline_desktop_planner):
    from fastapi.testclient import TestClient
    from localmind import agent, server
    from localmind.requests import RequestStore
    database = tmp_path / 'history.sqlite3'
    journal = ConversationStore(path=database)
    requests = RequestStore()
    monkeypatch.setattr(server, 'conversations', journal)
    monkeypatch.setattr(server, 'store', requests)
    monkeypatch.setattr(agent, 'ollama_chat', lambda *a, **k: {'content': '{"answer":"Локальный ответ"}'})
    client = TestClient(server.app, base_url='http://127.0.0.1', client=('127.0.0.1', 120))
    try:
        key = client.post('/api/conversations').json()['conversation_id']
        first = client.post('/api/chat', json={'text': 'Первый вопрос', 'conversation_id': key, 'request_id': 'first-turn'})
        assert first.status_code == 200
        assert client.post('/api/chat', json={'text': 'Первый вопрос', 'conversation_id': key, 'request_id': 'first-turn'}).json() == first.json()
        detail = client.get('/api/conversations/' + key).json()
        assert len(detail['messages']) == 2
        assert detail['server_instance'] == server.SERVER_INSTANCE
        assert client.patch('/api/conversations/' + key, json={'title': 'Продолжение', 'draft': 'Ещё вопрос'}).status_code == 200
        monkeypatch.setattr(server, 'conversations', ConversationStore(path=database))
        assert client.get('/api/conversations').json()['conversations'][0]['title'] == 'Продолжение'
        assert client.get('/api/conversations/' + key).json()['draft'] == 'Ещё вопрос'
        assert client.post('/api/chat', json={'text': 'Продолжим', 'conversation_id': key, 'request_id': 'next-turn'}).status_code == 200
        assert len(client.get('/api/conversations/' + key).json()['messages']) == 4
        assert client.request('DELETE', '/api/conversations/' + key, json={'confirmed': False}).status_code == 409
        assert client.request('DELETE', '/api/conversations/' + key, json={'confirmed': 'true'}).status_code == 422
        assert client.request('DELETE', '/api/conversations/' + key, json={'confirmed': True}).status_code == 200
        assert not client.get('/api/conversations').json()['conversations']
    finally:
        requests.close()


def test_history_api_import_is_bounded_and_authenticated(tmp_path, monkeypatch):
    from dataclasses import replace
    from fastapi.testclient import TestClient
    from localmind import server
    monkeypatch.setattr(server, 'conversations', ConversationStore(path=tmp_path / 'history.sqlite3'))
    monkeypatch.setattr(server, 'settings', replace(server.settings, key='private-key'))
    client = TestClient(server.app, base_url='http://127.0.0.1', client=('127.0.0.1', 120))
    headers = {'X-Localmind-Key': 'private-key'}
    assert client.get('/api/conversations').status_code == 401
    body = {'migration_id': 'a' * 64, 'items': [{'title': 'Сохранённая', 'messages': [{'role': 'user', 'content': 'Исходный текст'}]}]}
    assert client.post('/api/conversations/import', json=body).status_code == 401
    assert client.post('/api/conversations/import', headers=headers, json=body).json()['imported']
    assert not client.post('/api/conversations/import', headers=headers, json=body).json()['imported']
    for malformed in ([{'title': 'Wrong', 'messages': [{'role': 'system', 'content': 'grant'}]}],
                      [{'title': 'Wrong', 'messages': [], 'path': 'C:/untrusted'}],
                      [{'title': 'Wrong', 'messages': [{'role': 'user', 'content': 'x' * 8193}]}]):
        assert client.post('/api/conversations/import', headers=headers, json={**body, 'migration_id': 'b' * 64, 'items': malformed}).status_code == 409
    assert len(client.get('/api/conversations', headers=headers).json()['conversations']) == 1
    assert client.patch('/api/conversations/' + 'x' * 32, headers=headers, json={'window_id': 'forged'}).status_code == 422
