"""Reported read requests: real policy persistence/I/O, fake Ollama only."""
import json
import os
from unittest.mock import Mock

import pytest

from localmind import agent, llm_planner as planner
from localmind.action_journal import ActionJournal
from localmind.capabilities import ToolIntent, registry
from localmind.conversations import Conversation, Reference
from localmind.file_access import FileAccess
from localmind.file_requests import read_request


@pytest.fixture
def saved_access(tmp_path, monkeypatch):
    desktop = tmp_path / 'Desktop'
    root = desktop / 'LocalMind_QA'
    root.mkdir(parents=True)
    target = root / 'readme.txt'
    target.write_text('Код проверки: ORBIT-739.', encoding='utf-8')
    state = tmp_path / 'policy.json'
    access = FileAccess(lambda: desktop, opener=Mock(), persistence=state)
    access.personal_mode.configure('restricted', [str(root)], ['read', 'search', 'open'])
    access = FileAccess(lambda: desktop, opener=Mock(), persistence=state)
    monkeypatch.setattr('localmind.file_access.file_access', access)
    from localmind.personal_permissions import known_folder
    monkeypatch.setattr('localmind.personal_permissions.known_folder',
                        lambda name: desktop if name == 'desktop' else known_folder(name))
    monkeypatch.setattr(agent, '_all_app_aliases', lambda: {})
    monkeypatch.setattr('localmind.model_manager.manager.native_tools_supported', lambda *a: False)
    monkeypatch.setattr(planner, 'journal', ActionJournal())
    return access, root, target


def request(target, style):
    return (f'Прочитай файл {target} и скажи код проверки.' if style == 'absolute' else
            'Прочитай содержимое файла readme.txt в папке LocalMind_QA на рабочем столе.')


@pytest.mark.parametrize('style', ['absolute', 'desktop'])
@pytest.mark.parametrize('route', ['exact', 'schema', 'native', 'offline'])
def test_saved_restricted_grants_reach_reader_and_answer(saved_access, monkeypatch, style, route):
    access, root, target = saved_access
    text = request(target, style)
    intent, error = read_request(text)
    assert not error and intent.name == 'files.read_file'
    assert intent.arguments == {'scope': access.personal_info()['roots'][0]['id'], 'relative_path': 'readme.txt'}
    seen = []

    def chat(messages, tools, **kwargs):
        seen.append(messages)
        if kwargs.get('response_format', {}).get('properties', {}).get('calls'):
            return {'content': json.dumps({'calls': [{'tool': intent.name, 'arguments': intent.arguments}]})}
        if tools:
            return {'tool_calls': [{'function': {'name': intent.name, 'arguments': intent.arguments}}]}
        return {'content': json.dumps({'answer': 'Код проверки: ORBIT-739.'})}

    monkeypatch.setattr(agent, 'ollama_chat', chat)
    if route == 'native':
        monkeypatch.setattr('localmind.model_manager.manager.native_tools_supported', lambda *a: True)
    if route == 'offline':
        def unavailable(*args, **kwargs):
            raise OSError('fixture planner offline')
        monkeypatch.setattr(planner, 'choose', unavailable)
    revision = access.personal_mode.generation
    prepared = agent.prepare_reply(text, actions_authorized=True, conversation=Conversation('owner', 0),
                                   llm_first=route != 'exact', compose_actions=False)
    assert prepared.result.success and prepared.result.action == 'files.read_file'
    assert prepared.result.observed_state == 'text_extracted'
    assert prepared.reference.kind == 'file' and prepared.reference.id == prepared.result.resolved_target
    assert prepared.document_facts[0]['text'] == 'Код проверки: ORBIT-739.'
    assert 'text' not in prepared.initial['action_results'][0]['data']
    final = agent.complete_reply(prepared)
    assert 'ORBIT-739' in final['answer']
    assert 'Код проверки: ORBIT-739.' in json.dumps(seen, ensure_ascii=False)
    assert access.personal_mode.generation == revision and access.personal_mode.mode == 'restricted'
    assert any(row['operation'] == 'read' and row['decision'] == 'observed' for row in access.personal_info()['access_log'])
    assert not access.read_selected('other', prepared.reference.id).success
    access.opener.assert_not_called()


@pytest.mark.skipif(os.name != 'nt', reason='real Windows path and held handles')
def test_absolute_windows_path_keeps_drive_backslashes_and_spaces(saved_access):
    access, root, _ = saved_access
    folder = root / 'Notes with spaces'
    folder.mkdir()
    target = folder / 'read me.txt'
    target.write_text('WINDOWS-821', encoding='utf-8')
    assert target.drive and '\\' in str(target)
    intent, error = read_request(request(target, 'absolute'))
    assert not error and intent.arguments['relative_path'] == r'Notes with spaces\read me.txt'
    result = registry.execute(intent, intent, 'owner')
    assert result.success and result.data['text'] == 'WINDOWS-821'


@pytest.mark.parametrize('llm_first', [False, True])
def test_unapproved_path_never_reads_or_uses_old_selection(saved_access, monkeypatch, llm_first):
    access, root, target = saved_access
    outside = root.parent / 'LocalMind_QA_other'
    outside.mkdir()
    forbidden = outside / 'readme.txt'
    forbidden.write_text('FORBIDDEN-CODE', encoding='utf-8')
    old = access.search('owner', scope='all')
    conversation = Conversation('owner', 0, references={'file': Reference('file', old.resolved_target)}, focus='file')
    text = request(forbidden, 'absolute')
    assert planner.offers(text, conversation) == {}
    reader = Mock(side_effect=AssertionError('reader must not run'))
    monkeypatch.setattr(access, 'read_selected', reader)
    monkeypatch.setattr(agent, 'ollama_chat', Mock(side_effect=AssertionError('LLM must not run')))
    prepared = agent.prepare_reply(text, actions_authorized=True, conversation=conversation, llm_first=llm_first)
    assert not prepared.dialogue and not prepared.result.success
    assert 'не разрешена' in prepared.initial['answer']
    assert not prepared.document_facts
    reader.assert_not_called()


def test_planner_cannot_substitute_filename_or_selected_file(saved_access):
    access, _, target = saved_access
    conversation = Conversation('owner', 0, references={'file': Reference('file', 'stale')}, focus='file')
    allowed = planner.offers(request(target, 'absolute'), conversation)
    assert set(allowed) == {'files.read_file'}
    scope = access.personal_info()['roots'][0]['id']
    for arguments in ({'scope': scope, 'relative_path': 'other.txt'},
                      {'scope': scope, 'relative_path': '..\\other.txt'},
                      {'scope': 'invented', 'relative_path': 'readme.txt'}):
        assert not planner.validates(ToolIntent('files.read_file', arguments), allowed)


@pytest.mark.parametrize('restriction', ['no_read', 'deny', 'revoke'])
def test_adapter_rechecks_live_saved_permission_before_read(saved_access, monkeypatch, restriction):
    access, root, target = saved_access
    intent, _ = read_request(request(target, 'absolute'))
    if restriction == 'deny':
        draft = access.personal_mode.preview('Не трогай папку LocalMind_QA', folders={'LocalMind_QA': str(root)})
        access.personal_mode.apply(draft['draft_id'])
    else:
        access.personal_mode.configure('restricted', [str(root)] if restriction == 'no_read' else [], ['search', 'open'])
    fingerprint = Mock(side_effect=AssertionError('denied file bytes must not be read'))
    monkeypatch.setattr('localmind.file_access._fingerprint', fingerprint)
    result = registry.execute(intent, intent, 'owner')
    assert not result.success and result.execution_status in ('denied', 'permission_required')
    fingerprint.assert_not_called()


def test_exact_read_needs_no_search_or_open_grant(saved_access):
    access, root, target = saved_access
    access.personal_mode.configure('restricted', [str(root)], ['read'])
    intent, error = read_request(request(target, 'absolute'))
    assert not error
    result = registry.execute(intent, intent, 'owner')
    assert result.success and 'ORBIT-739' in result.data['text']
    assert not access.open_selected('owner', result.resolved_target).success


@pytest.mark.parametrize('relative', ['..\\readme.txt', '..//readme.txt', 'C:\\readme.txt', '\\\\host\\share\\readme.txt',
                                      'readme.txt:stream', '.ssh/id_rsa.txt', 'run.exe'])
def test_adapter_rejects_unsafe_relative_paths(saved_access, relative):
    access, _, _ = saved_access
    scope = access.personal_info()['roots'][0]['id']
    assert not access.read_file('owner', scope, relative).success


def test_review_required_before_reading(saved_access, monkeypatch):
    access, _, target = saved_access
    reader = Mock(side_effect=AssertionError('unreviewed read'))
    monkeypatch.setattr(access, 'read_file', reader)
    prepared = agent.prepare_reply(request(target, 'absolute'), conversation=Conversation('owner', 0), llm_first=True)
    assert prepared.initial['confirmation_required']
    reader.assert_not_called()


@pytest.mark.parametrize('style', ['absolute', 'desktop'])
def test_http_saved_settings_and_chat_share_the_reloaded_policy(saved_access, monkeypatch, style):
    from fastapi.testclient import TestClient
    from types import SimpleNamespace
    from localmind import server
    from localmind.conversations import ConversationStore
    from localmind.requests import RequestStore
    access, root, target = saved_access
    store = RequestStore()
    monkeypatch.setattr(server, 'store', store)
    monkeypatch.setattr(server, 'conversations', ConversationStore())
    monkeypatch.setattr(server, 'settings', SimpleNamespace(key='fixture-read-key'))
    monkeypatch.setattr(server, 'file_access', access)

    def chat(messages, tools, **kwargs):
        if 'calls' in kwargs.get('response_format', {}).get('properties', {}):
            available = json.loads(messages[-1]['content'])['available']
            assert set(available) == {'files.read_file'}
            args = {key: definition['enum'][0] for key, definition in available['files.read_file']['properties'].items()}
            return {'content': json.dumps({'calls': [{'tool': 'files.read_file', 'arguments': args}]})}
        assert 'ORBIT-739' in json.dumps(messages, ensure_ascii=False)
        return {'content': json.dumps({'answer': 'Код проверки: ORBIT-739.'})}

    monkeypatch.setattr(agent, 'ollama_chat', chat)
    client = TestClient(server.app, base_url='http://127.0.0.1', client=('127.0.0.1', 1234))
    client.headers['X-LocalMind-Key'] = 'fixture-read-key'
    try:
        before = client.get('/api/access-policy').json()
        saved = client.post('/api/access-policy', json={'mode': 'restricted', 'roots': [str(root)],
            'operations': ['read', 'search', 'open'], 'revision': before['revision'], 'server_instance': server.SERVER_INSTANCE})
        assert saved.status_code == 200
        reloaded = FileAccess(lambda: root.parent, opener=Mock(), persistence=access.personal_mode.persistence)
        monkeypatch.setattr(server, 'file_access', reloaded)
        monkeypatch.setattr('localmind.file_access.file_access', reloaded)
        response = client.post('/api/chat', json={'text': request(target, style),
            'server_instance': server.SERVER_INSTANCE, 'compose_actions': False})
        assert response.status_code == 200, response.text
        body = response.json()
        assert body['engine'] == 'ollama' and body['planner_mode'] == 'schema'
        assert 'ORBIT-739' in body['answer']
        outcome = body['action_results'][0]
        assert outcome['success'] and outcome['action'] == 'files.read_file'
        assert outcome['resolved_target'] and outcome['data']['path'] == str(target)
        assert 'text' not in outcome['data']
        assert client.get('/api/access-policy').json()['operations'] == ['open', 'read', 'search']
    finally:
        store.close()
