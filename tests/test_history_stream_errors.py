"""Production NDJSON must not report an uncommitted chat as successful."""
from contextlib import closing
import json
import sqlite3

from fastapi.testclient import TestClient

from localmind import agent, server
from localmind.conversations import ConversationStore
from localmind.requests import RequestStore


def test_failed_input_checkpoint_prevents_generation_and_action_preparation(tmp_path, monkeypatch):
    database = tmp_path / 'history.sqlite3'
    conversations = ConversationStore(path=database)
    key = conversations.create()
    with closing(sqlite3.connect(database)) as db:
        db.execute("CREATE TRIGGER reject_draft BEFORE UPDATE OF draft ON conversations BEGIN SELECT RAISE(ABORT,'disk full'); END")
    requests = RequestStore()
    monkeypatch.setattr(server, 'conversations', conversations)
    monkeypatch.setattr(server, 'store', requests)
    def forbidden(*args, **kwargs):
        raise AssertionError('preparation must not execute before the input checkpoint')
    monkeypatch.setattr(server, 'prepare_reply', forbidden)
    client = TestClient(server.app, base_url='http://127.0.0.1', client=('127.0.0.1', 120))
    try:
        result = client.post('/api/chat', json={'text': 'Включи лампу', 'conversation_id': key, 'request_id': 'no-disk-no-action'})
        assert result.status_code == 409 and 'свободное место' in result.json()['detail']
        assert conversations.read(key)['messages'] == []
    finally:
        requests.close()


def test_stream_surfaces_safe_persistence_error_without_final_or_duplicate_turn(tmp_path, monkeypatch, offline_desktop_planner):
    database = tmp_path / 'history.sqlite3'
    conversations = ConversationStore(path=database)
    key = conversations.create()
    with closing(sqlite3.connect(database)) as db:
        db.execute("CREATE TRIGGER reject_answer BEFORE INSERT ON messages WHEN NEW.role='assistant' BEGIN SELECT RAISE(ABORT,'disk full'); END")
    requests = RequestStore()
    monkeypatch.setattr(server, 'conversations', conversations)
    monkeypatch.setattr(server, 'store', requests)
    generated = []
    def generate(*args, **kwargs):
        generated.append(True)
        return {'content': '{"answer":"Ответ модели"}'}
    monkeypatch.setattr(agent, 'ollama_chat', generate)
    client = TestClient(server.app, base_url='http://127.0.0.1', client=('127.0.0.1', 120))
    body = {'text': 'Сохрани ответ', 'conversation_id': key, 'request_id': 'disk-failure-turn'}
    try:
        for _ in range(2):
            response = client.post('/api/chat/stream', json=body)
            events = [json.loads(line) for line in response.text.splitlines()]
            assert response.status_code == 200  # Headers preceded the failed commit.
            assert events[-1]['type'] == 'error'
            assert 'свободное место' in events[-1]['detail']
            assert not any(event['type'] == 'final' for event in events)
        assert len(generated) == 1
        assert conversations.read(key)['messages'] == []
        assert conversations.read(key)['draft'] == body['text']
        assert ConversationStore(path=database).read(key)['draft'] == body['text']
        assert not conversations._items[key].active
    finally:
        requests.close()
