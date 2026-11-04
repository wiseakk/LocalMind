"""Real loopback HTTP/SQLite/process tests; only LLM generation is a fixture.

No personal models, microphone, GUI, or OS action adapters are used.
"""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing, contextmanager
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import time

import httpx


SERVER = r'''
import json, socket, sys, time
from pathlib import Path
import uvicorn
from localmind import agent, server
from localmind.generation import check_cancelled

def generate(*args, **kwargs):
    while Path(sys.argv[2]).exists():
        check_cancelled()
        time.sleep(.01)
    return {'content': json.dumps({'answer': 'Fixture answer'})}

agent.ollama_chat = generate
sock = socket.socket()
sock.bind(('127.0.0.1', 0))
Path(sys.argv[1]).write_text(str(sock.getsockname()[1]))
uvicorn.Server(uvicorn.Config(server.app, log_level='error')).run(sockets=[sock])
'''


@contextmanager
def running_server(root):
    port_file, slow = root / 'port.txt', root / 'slow'
    port_file.unlink(missing_ok=True)
    environment = {**os.environ, 'LOCALMIND_DATA_DIR': str(root / 'data'),
                   'PYTHONIOENCODING': 'utf-8', 'LOCALMIND_KEY': '', 'DEMO_MODE': 'true'}
    with (root / 'server.log').open('a', encoding='utf-8') as log:
        process = subprocess.Popen([sys.executable, '-B', '-c', SERVER, str(port_file), str(slow)],
                                   env=environment, stdout=log, stderr=log,
                                   cwd=Path(__file__).resolve().parents[1])
        try:
            deadline = time.monotonic() + 15
            with httpx.Client(trust_env=False, timeout=2) as client:
                while time.monotonic() < deadline:
                    assert process.poll() is None, (root / 'server.log').read_text(encoding='utf-8')
                    if port_file.exists():
                        url = 'http://127.0.0.1:' + port_file.read_text()
                        try:
                            if client.get(url + '/api/info').status_code == 200:
                                break
                        except httpx.TransportError:
                            pass
                    time.sleep(.05)
                else:
                    raise AssertionError('Server startup timed out')
                yield client, url, process
        finally:
            # Only this fixture's child is stopped, including the crash test.
            if process.poll() is None:
                process.kill()
            process.wait(timeout=10)


def test_three_http_chats_keep_ids_drafts_context_and_continue_after_server_exit(tmp_path):
    snapshots = []
    with running_server(tmp_path) as (client, url, _):
        instance = client.get(url + '/api/info').json()['server_instance']
        for index in range(3):
            key = client.post(url + '/api/conversations').json()['conversation_id']
            body = {'conversation_id': key, 'server_instance': instance,
                    'request_id': f'original-{index}', 'text': f'Question {index}'}
            first = client.post(url + '/api/chat/stream', json=body)
            assert first.status_code == 200
            events = [json.loads(line) for line in first.text.splitlines()]
            assert events[-1]['type'] == 'final'
            assert client.post(url + '/api/chat', json=body).json() == events[-1]['data']
            upload = client.post(url + '/api/attachments', data={'conversation_id': key, 'server_instance': instance},
                                 files={'file': (f'reference-{index}.txt', f'Reference {index}'.encode(), 'text/plain')})
            assert upload.status_code == 200
            context = {'local_retrieval': bool(index % 2), 'attachment_ids': [upload.json()['id']]}
            assert client.patch(url + '/api/conversations/' + key,
                                json={'draft': f'Draft {index}', 'context': context}).status_code == 200
            snapshots.append(client.get(url + '/api/conversations/' + key).json())
    with running_server(tmp_path) as (client, url, _):
        new_instance = client.get(url + '/api/info').json()['server_instance']
        assert instance != new_instance
        assert len(client.get(url + '/api/conversations').json()['conversations']) == 3
        for index, before in enumerate(snapshots):
            key = before['conversation_id']
            restored = client.get(url + '/api/conversations/' + key).json()
            for field in ('messages', 'draft', 'context', 'conversation_id', 'attachments'):
                assert restored[field] == before[field]
            body = {'conversation_id': key, 'server_instance': instance,
                    'request_id': f'original-{index}', 'text': f'Question {index}'}
            # Old transport envelopes cannot execute after process restart.
            assert client.post(url + '/api/chat', json=body).status_code == 409
            result = client.post(url + '/api/chat', json={**body, **before['context'], 'server_instance': new_instance,
                                  'request_id': f'continued-{index}', 'text': f'Continue {index}'})
            assert result.status_code == 200
            assert [doc['id'] for doc in result.json()['context_sources']] == before['context']['attachment_ids']
            messages = client.get(url + '/api/conversations/' + key).json()['messages']
            assert len(messages) == 4 and messages[:2] == before['messages']


def test_process_crash_before_final_retains_input_without_completed_answer(tmp_path):
    (tmp_path / 'slow').touch()
    with running_server(tmp_path) as (client, url, process):
        key = client.post(url + '/api/conversations').json()['conversation_id']
        body = {'conversation_id': key, 'request_id': 'crashed-turn', 'text': 'Recover this input'}
        with ThreadPoolExecutor(1) as pool:
            future = pool.submit(client.post, url + '/api/chat', json=body, timeout=15)
            database = tmp_path / 'data/history/conversations.sqlite3'
            deadline = time.monotonic() + 8
            while time.monotonic() < deadline:
                with closing(sqlite3.connect(database)) as db:
                    row = db.execute('SELECT draft FROM conversations WHERE id=?', (key,)).fetchone()
                if row and row[0] == body['text']:
                    break
                time.sleep(.02)
            else:
                raise AssertionError('Input was not checkpointed before generation')
            process.kill()
            process.wait(timeout=5)
            try:
                future.result(timeout=5)
            except httpx.TransportError:
                pass
    (tmp_path / 'slow').unlink()
    with running_server(tmp_path) as (client, url, _):
        detail = client.get(url + '/api/conversations/' + key).json()
        assert detail['draft'] == body['text']
        assert detail['messages'] == []
        assert client.post(url + '/api/chat', json={**body, 'request_id': 'deliberate-new-turn'}).status_code == 200
        detail = client.get(url + '/api/conversations/' + key).json()
        assert len(detail['messages']) == 2 and detail['draft'] == ''


def test_disconnected_stream_cancels_and_replays_one_committed_turn(tmp_path):
    (tmp_path / 'slow').touch()
    with running_server(tmp_path) as (client, url, _):
        key = client.post(url + '/api/conversations').json()['conversation_id']
        instance = client.get(url + '/api/info').json()['server_instance']
        body = {'conversation_id': key, 'server_instance': instance,
                'request_id': 'disconnected-cancelled', 'text': 'Cancel this generation'}
        with client.stream('POST', url + '/api/chat/stream', json=body, timeout=10) as stream:
            assert json.loads(next(stream.iter_lines()))['type'] == 'status'
        # The worker survives HTTP disconnect; cancellation uses its original ID.
        cancelled = client.post(url + '/api/chat/cancel', json={
            'request_id': body['request_id'], 'server_instance': instance})
        assert cancelled.status_code == 200
        replay = client.post(url + '/api/chat', json=body, timeout=10)
        assert replay.status_code == 200 and replay.json()['cancelled'] is True
        assert client.post(url + '/api/chat', json=body).json() == replay.json()
        detail = client.get(url + '/api/conversations/' + key).json()
        assert [m['content'] for m in detail['messages']] == [body['text'], 'Ответ прерван.']
        assert detail['draft'] == ''
    with running_server(tmp_path) as (client, url, _):
        restored = client.get(url + '/api/conversations/' + key).json()
        assert restored['messages'] == detail['messages']
