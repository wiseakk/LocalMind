"""Reported RC3 commands: actual fixture files/policy, no real LLM or apps."""
import json
import os
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from localmind import agent, llm_planner as planner
from localmind.action_journal import ActionJournal
from localmind.conversations import Conversation
from localmind.file_access import FileAccess
from localmind.file_mutations import FileMutations
from localmind.file_requests import latest_download_request, read_request


@pytest.fixture(params=['restricted', 'full_user'])
def access_case(tmp_path, monkeypatch, request):
    qa, downloads = tmp_path / 'LocalMind_QA', tmp_path / 'Downloads'
    qa.mkdir(); downloads.mkdir()
    target = qa / '1.txt'
    target.write_text('CURRENT-562: данные текущего файла.', encoding='utf-8')
    access = FileAccess(lambda: downloads, opener=Mock())
    access.personal_mode.root_provider = lambda: [str(qa), str(downloads)]
    access.personal_mode.configure(request.param, [str(qa), str(downloads)], ['read', 'search', 'delete'])
    mutations = FileMutations(access)
    monkeypatch.setattr('localmind.file_access.file_access', access)
    monkeypatch.setattr('localmind.file_mutations.file_mutations', mutations)
    monkeypatch.setattr(agent, '_all_app_aliases', lambda: {})
    monkeypatch.setattr('localmind.model_manager.manager.native_tools_supported', lambda *a: False)
    monkeypatch.setattr(planner, 'journal', ActionJournal())
    return access, mutations, qa, downloads, target


def fake_model(monkeypatch, route, answer='Пересказ: CURRENT-562.'):
    generated = []
    def chat(messages, tools, **kwargs):
        if 'calls' in kwargs.get('response_format', {}).get('properties', {}):
            if route == 'empty':
                return {'content': '{"calls":[]}'}
            available = json.loads(messages[-1]['content'])['available']
            assert len(available) == 1
            name, schema = next(iter(available.items()))
            arguments = {key: field['enum'][0] for key, field in schema['properties'].items()}
            return {'content': json.dumps({'calls': [{'tool': name, 'arguments': arguments}]})}
        assert not tools
        generated.append(messages)
        return {'content': json.dumps({'answer': answer})}
    monkeypatch.setattr(agent, 'ollama_chat', chat)
    if route == 'offline':
        def unavailable(*a, **k):
            raise OSError('fixture planner unavailable')
        monkeypatch.setattr(planner, 'choose', unavailable)
    return generated


@pytest.mark.parametrize('prefix', ['про что файл', 'О чём файл', 'О чем документ',
                                    'Перескажи файл', 'Расскажи о файле', 'Расскажи про документ'])
@pytest.mark.parametrize('route', ['exact', 'schema', 'empty', 'offline'])
def test_summary_reads_exact_target_before_generation(access_case, monkeypatch, prefix, route):
    access, _, _, _, target = access_case
    generated = fake_model(monkeypatch, route)
    reader = Mock(wraps=access.read_file)
    monkeypatch.setattr(access, 'read_file', reader)
    prepared = agent.prepare_reply(f'{prefix} {target}', conversation=Conversation('owner', 0),
        actions_authorized=True, llm_first=route != 'exact', compose_actions=False)
    final = agent.complete_reply(prepared)
    assert final['engine'] == 'ollama' and final['action_results'][0]['action'] == 'files.read_file'
    assert final['action_results'][0]['success'] and final['action_results'][0]['data']['path'] == str(target)
    assert len(generated) == 1 and 'CURRENT-562' in json.dumps(generated, ensure_ascii=False)
    assert 'text' not in final['action_results'][0]['data']
    assert final['context_sources'][0]['id'] == prepared.result.resolved_target
    reader.assert_called_once()
    access.opener.assert_not_called()


def test_read_is_verbatim_but_summary_refusal_cannot_erase_success(access_case, monkeypatch):
    _, _, _, _, target = access_case
    refusal = 'Я не могу прочитать файл, нет разрешения.'
    generated = fake_model(monkeypatch, 'schema', answer=refusal)
    for prefix, engine, calls in [('Прочитай файл', 'file-content', 0), ('про что файл', 'ollama', 1)]:
        final = agent.complete_reply(agent.prepare_reply(f'{prefix} {target}', conversation=Conversation('owner', 0),
            actions_authorized=True, llm_first=True, compose_actions=False))
        assert final['engine'] == engine and final['action_results'][0]['success']
        assert target.read_text(encoding='utf-8') in final['answer'] and refusal not in final['answer']
        assert len(generated) == calls


@pytest.mark.parametrize('state', ['outside', 'no_read', 'deny', 'missing'])
def test_summary_denial_never_generates_a_model_refusal(access_case, monkeypatch, state):
    access, _, qa, downloads, target = access_case
    if state == 'outside':
        target = qa.parent / 'outside.txt'
        target.write_text('FORBIDDEN', encoding='utf-8')
    elif state == 'no_read':
        access.personal_mode.configure(access.personal_mode.mode, [str(qa), str(downloads)], ['search'])
    elif state == 'deny':
        draft = access.personal_mode.preview('Не трогай папку LocalMind_QA', folders={'LocalMind_QA': str(qa)})
        access.personal_mode.apply(draft['draft_id'])
    else:
        target = qa / 'missing.txt'
    generated = fake_model(monkeypatch, 'schema')
    final = agent.complete_reply(agent.prepare_reply(f'про что файл {target}', conversation=Conversation('owner', 0),
        actions_authorized=True, llm_first=True, compose_actions=False))
    assert final['action_results'] and not final['action_results'][0]['success']
    assert not generated and final['engine'] != 'ollama'


@pytest.mark.parametrize('text', ['Последний скачанный PDF файл в папке Download',
    'Последний скачанный PDF-файл в Downloads', 'Найди последний PDF файл в Загрузках',
    'Покажи самый новый PDF в папке Загрузки', 'Последний пдф в Download'])
@pytest.mark.parametrize('route', ['exact', 'schema', 'empty', 'offline'])
def test_latest_download_uses_real_mtime_without_inventing_download_time(access_case, monkeypatch, text, route):
    _, _, _, downloads, _ = access_case
    newer, older = downloads / 'z-newer.pdf', downloads / 'a-older.pdf'
    newer.write_bytes(b'%PDF-1.4\nfixture newer')
    older.write_bytes(b'%PDF-1.4\nfixture older')
    os.utime(newer, ns=(1700000200000000000, 1700000200000000000))
    os.utime(older, ns=(1700000100000000000, 1700000100000000000))
    generated = fake_model(monkeypatch, route)
    final = agent.complete_reply(agent.prepare_reply(text, conversation=Conversation('owner', 0),
        actions_authorized=True, llm_first=route != 'exact', compose_actions=False))
    result = final['action_results'][0]
    assert result['success'] and result['action'] == 'files.search'
    assert result['data']['filename'] == newer.name
    assert result['data']['timestamp_semantics'] == 'last_modified_not_download_time'
    assert result['data']['order'] == 'desc' and result['data']['sort_by'] == 'modified'
    assert 'время скачивания неизвестно' in final['answer']
    assert not generated


@pytest.mark.parametrize('state', ['empty', 'denied'])
def test_latest_download_empty_or_denied_does_not_invent_files(access_case, monkeypatch, state):
    access, _, qa, downloads, _ = access_case
    if state == 'denied':
        access.personal_mode.configure(access.personal_mode.mode, [str(qa), str(downloads)], ['read'])
    generated = fake_model(monkeypatch, 'schema')
    final = agent.complete_reply(agent.prepare_reply('Последний скачанный PDF файл в папке Download',
        conversation=Conversation('owner', 0), actions_authorized=True, llm_first=True, compose_actions=False))
    assert not final['action_results'][0]['success']
    assert final['action_results'][0]['execution_status'] == ('not_found' if state == 'empty' else 'permission_required')
    assert not generated


@pytest.mark.parametrize('text', ['Не пересказывай файл C:\\notes.txt', 'Как найти последний PDF в Downloads?',
    'Он сказал «Последний скачанный PDF файл в папке Download»', 'Если найду последний PDF в Download',
    'Последний PDF в Download и удали документы', 'Расскажи про World of Warcraft'])
def test_new_patterns_do_not_authorize_unrelated_or_quoted_actions(text):
    assert not latest_download_request(text)
    intent, _ = read_request(text)
    assert intent is None
    assert planner.offers(text, Conversation('owner', 0)) == {}


@pytest.mark.parametrize('approved', [True, False])
def test_delete_http_explicit_confirm_cancel_and_stale_owner(access_case, monkeypatch, approved):
    from fastapi.testclient import TestClient
    from localmind import server
    from localmind.conversations import ConversationStore
    from localmind.requests import RequestStore
    access, _, _, _, target = access_case
    store, memory = RequestStore(), ConversationStore()
    monkeypatch.setattr(server, 'store', store)
    monkeypatch.setattr(server, 'conversations', memory)
    monkeypatch.setattr(server, 'file_access', access)
    monkeypatch.setattr(server, 'settings', SimpleNamespace(key='fixture'))
    fake_model(monkeypatch, 'schema')
    client = TestClient(server.app, base_url='http://127.0.0.1', client=('127.0.0.1', 12))
    client.headers['X-LocalMind-Key'] = 'fixture'
    try:
        pending = client.post('/api/chat', json={'text': f'Удали файл {target}', 'compose_actions': False}).json()
        assert pending['confirmation_required'] and target.exists()
        # Ordinary chat text is never the confirmation endpoint.
        client.post('/api/chat', json={'text': 'УДАЛИ', 'conversation_id': pending['conversation_id'], 'compose_actions': False})
        assert target.exists()
        body = {'confirmation_id': pending['pending_operation']['confirmation_id'], 'conversation_id': pending['conversation_id'],
                'server_instance': server.SERVER_INSTANCE, 'approved': approved}
        assert client.post('/api/files/confirm', json={**body, 'server_instance': '0'*32}).status_code == 409
        assert not client.post('/api/files/confirm', json={**body, 'conversation_id': memory.create()}).json()['success']
        assert target.exists()
        result = client.post('/api/files/confirm', json=body).json()
        assert result['execution_status'] == ('observed' if approved else 'cancelled')
        assert target.exists() == (not approved)
        assert not client.post('/api/files/confirm', json=body).json()['success']
    finally:
        store.close()
