import json
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from types import SimpleNamespace
from unittest import mock

import httpx
import pytest

from localmind import agent, devices
from localmind.requests import RequestBusy, RequestConflict, RequestStore
from localmind.results import ActionResult


def generated(result, text='В симуляции лампа включена. Можно продолжать.'):
    return {'content': json.dumps({'success': result.success,
                                  'execution_status': result.execution_status,
                                  'observed_state': result.observed_state,
                                  'commentary': text}, ensure_ascii=False)}


def test_action_is_available_before_composition_and_has_observed_demo_state():
    devices._demo_states['desk_light'] = False
    with mock.patch.object(agent, 'ollama_chat') as llm:
        prepared = agent.prepare_reply('Включи лампу', actions_authorized=True)
        llm.assert_not_called()
    assert devices._demo_states['desk_light']
    result = prepared.result
    assert result.success and result.mode == 'DEMO' and result.observed_state == 'on'
    assert prepared.initial['action_results'][0]['execution_status'] == 'observed'
    with mock.patch.object(agent, 'ollama_chat', return_value=generated(result)) as llm:
        final = agent.complete_reply(prepared)
    assert final['engine'] == 'ollama-action'
    assert final['answer'].startswith('В симуляции')
    assert final['status'].startswith('ДЕМО:')
    assert llm.call_args.args[1] == []
    schema = llm.call_args.kwargs['response_format']
    assert schema['properties']['success']['enum'] == [True]
    assert schema['properties']['observed_state']['enum'] == ['on']
    content = json.loads(llm.call_args.args[0][1]['content'])
    assert content['result']['observed_state'] == 'on'
    assert all(k in final for k in ('action_ms', 'llm_ms', 'latency_ms'))


@pytest.mark.parametrize('reply', [
    {'content': 'Успешно!'},
    {'content': '{}'},
    {'content': '[]'},
    {'content': None},
    {'content': '{"success":true,"execution_status":"denied","observed_state":null,"commentary":"Готово"}'},
    {'content': '{}', 'tool_calls': [{'function': 'launch'}]},
])
def test_malformed_or_contradictory_denial_commentary_keeps_truth(reply):
    prepared = agent.prepare_reply('Не открывай блокнот', actions_authorized=True)
    with mock.patch.object(agent, 'ollama_chat', return_value=reply):
        final = agent.complete_reply(prepared)
    assert final['answer'] == prepared.initial['answer']
    assert not final['action_results'][0]['success']
    assert final['commentary'] is None


def test_success_text_after_denial_is_rejected_even_if_json_facts_echo():
    prepared = agent.prepare_reply('Закрой блокнот', actions_authorized=True)
    with mock.patch.object(agent, 'ollama_chat', return_value=generated(prepared.result, 'Готово, закрыл блокнот.')):
        final = agent.complete_reply(prepared)
    assert final['answer'] == str(prepared.result)


@pytest.mark.parametrize('text', [
    'Всё выполнил, окно блокнота больше не работает.',
    'Операция выполнена. Можно продолжать.',
    'Всё исполнил, программа завершила работу.',
    'Сработало, окно исчезло.',
    'Успех, окно теперь не работает.',
    'Приложение больше не работает.',
    'Не могу закрыть окно автоматически, но всё выполнил.',
])
def test_denial_rejects_completion_paraphrases_and_missing_negative_anchor(text):
    prepared = agent.prepare_reply('Закрой блокнот', actions_authorized=True)
    with mock.patch.object(agent, 'ollama_chat', return_value=generated(prepared.result, text)):
        final = agent.complete_reply(prepared)
    assert final['answer'] == str(prepared.result)
    assert final['commentary'] is None


def test_denial_is_composed_without_execution():
    prepared = agent.prepare_reply('Открой cmd', actions_authorized=True)
    with mock.patch.object(agent, 'ollama_chat', return_value=generated(prepared.result, 'Не могу выбрать разрешённое приложение. Уточни название.')):
        final = agent.complete_reply(prepared)
    assert final['engine'] == 'ollama-action'
    assert final['action_results'][0]['execution_status'] == 'denied'
    assert final['actions'] == []


def test_safe_close_explanation_does_not_match_a_success_verb():
    prepared = agent.prepare_reply('Закрой блокнот', actions_authorized=True)
    text = 'Автоматическое закрытие недоступно. Закрыть окно можно вручную, сохранив текст.'
    with mock.patch.object(agent, 'ollama_chat', return_value=generated(prepared.result, text)):
        final = agent.complete_reply(prepared)
    assert final['answer'] == text and final['engine'] == 'ollama-action'


def test_timeout_does_not_repeat_action():
    original = devices.set_light
    with mock.patch.object(agent, 'set_light', wraps=original) as execution:
        prepared = agent.prepare_reply('Включи лампу', actions_authorized=True)
        with mock.patch.object(agent, 'ollama_chat', side_effect=httpx.ReadTimeout('test')):
            first = agent.complete_reply(prepared)
            second = agent.complete_reply(prepared)
    assert execution.call_count == 1
    assert first['answer'] == second['answer'] == str(prepared.result)


def test_preview_never_composes_or_executes():
    with mock.patch.object(agent, 'dispatch') as execute, mock.patch.object(agent, 'ollama_chat') as llm:
        final = agent.reply('Включи лампу', actions_authorized=False)
    execute.assert_not_called()
    llm.assert_not_called()
    assert final['confirmation_required']


def test_dynamic_apps_require_exact_unambiguous_alias_and_catalog_permission():
    aliases = {'one': ('visual studio code', 'code'), 'two': ('code insiders', 'code')}
    with mock.patch.object(agent.catalog, 'aliases', return_value=aliases), \
         mock.patch.object(agent.catalog, 'launch', return_value={
             'success': False, 'action': 'open_app', 'resolved_target': 'Visual Studio Code',
             'execution_status': 'not_executed', 'error': 'Сначала разреши приложение.',
             'status_text': 'Сначала разреши приложение.'}) as launch:
        assert agent.assess_action('Открой code').grant is None
        assert agent.assess_action('Открой Visual Studio Code').grant.arguments == {'app': 'one'}
        prepared = agent.prepare_reply('Открой Visual Studio Code', actions_authorized=True)
        assert not prepared.result.success
        launch.assert_called_once_with('one')


def test_discovered_shortcut_cannot_shadow_builtin_alias():
    with mock.patch.object(agent.catalog, 'aliases', return_value={'evil': ('блокнот', 'notepad')}):
        assert agent.assess_action('Открой блокнот').grant.arguments == {'app': 'notepad'}


def test_disappearing_catalog_entry_is_denied_without_key_error():
    with mock.patch.object(agent.catalog, 'aliases', return_value={}):
        assert not agent._matches_app_command('Открой исчезнувшее', 'open_app', 'removed-id')


def test_app_process_creation_is_not_window_observation(tmp_path):
    from localmind.windows_state import LaunchCoordinator, ApplicationState
    target = tmp_path / 'notepad.exe'
    target.touch()
    with mock.patch.object(agent, 'launch_coordinator', LaunchCoordinator(inspector=lambda _: ApplicationState('absent'))), \
         mock.patch.object(agent, 'resolve_windows_app', return_value=target), \
         mock.patch.object(agent.platform, 'system', return_value='Windows'), \
         mock.patch.object(agent.subprocess, 'Popen'):
        result = agent.open_app('notepad')
    assert result.success and result.execution_status == 'process_created'
    assert result.observed_state is None
    prepared = agent.prepare_reply('Не открывай блокнот')
    prepared.result = result
    with mock.patch.object(agent, 'ollama_chat', return_value=generated(result, 'Окно открыто.')):
        final = agent.complete_reply(prepared)
    assert final['commentary'] is None


def test_model_url_must_be_local_and_proxy_environment_ignored():
    with mock.patch.object(agent, 'settings', SimpleNamespace(ollama_url='http://example.com', model='test')):
        with pytest.raises(ValueError):
            agent.ollama_chat([], [])
    fake_client = mock.MagicMock()
    fake_client.__enter__.return_value.get.return_value.json.return_value = {'models': [{'name': agent.settings.model, 'size': 100}]}
    fake_client.__enter__.return_value.post.return_value.json.return_value = {'message': {'content': 'ok'}}
    fake_client.__enter__.return_value.stream.return_value.__enter__.return_value.iter_bytes.return_value = [b'{"message":{"content":"ok"}}']
    with mock.patch.object(agent.httpx, 'Client', return_value=fake_client) as client:
        agent.ollama_chat([], [])
    assert client.call_args.kwargs['trust_env'] is False
    body = fake_client.__enter__.return_value.stream.call_args.kwargs['json']
    assert body['think'] is False and body['tools'] == [] and body['stream'] is False


def test_dialogue_decodes_only_schema_answer_and_preserves_markdown_math():
    text = 'RSA использует **пару ключей**. Формула: \\(n=pq\\).'
    message = {'content': json.dumps({'answer': text}), 'thinking': 'private self-reasoning'}
    with mock.patch.object(agent, 'ollama_chat', return_value=message) as llm:
        result = agent.reply('Что такое RSA?')
    assert result['answer'] == text and result['engine'] == 'ollama'
    assert 'private' not in str(result)
    assert result['actions'] == []
    assert llm.call_args.args[1] == []
    assert llm.call_args.kwargs['response_format']['required'] == ['answer']


@pytest.mark.parametrize('content', [
    'Хорошо, мне нужно объяснить задачу.',
    'not json', '[]', '{}', '{"answer":null}', '{"answer":23}', '{"answer":" "}',
    json.dumps({'answer': 'Хорошо, мне нужно объяснить это сначала.'}),
    json.dumps({'answer': '<think>internal planning</think>Ответ'}),
])
def test_malformed_dialogue_or_visible_self_reasoning_fails_safely(content):
    with mock.patch.object(agent, 'ollama_chat', return_value={'content': content}):
        result = agent.reply('Объясни алгоритм')
    assert result['engine'] == 'offline-error' and result['actions'] == []
    assert content not in result['answer']


def test_long_dialogue_stops_at_sentence_boundary():
    sentence = 'Это полное предложение. '
    text = sentence * 40
    with mock.patch.object(agent, 'ollama_chat', return_value={'content': json.dumps({'answer': text})}):
        result = agent.reply('Объясни алгоритм', response_length='brief')
    assert len(result['answer']) <= 400
    assert result['answer'].endswith('.')
    assert text.startswith(result['answer'])


def test_answer_limit_uses_word_boundary_when_no_sentence_exists():
    text = 'длинноеслово ' * 100
    result = agent._trim_answer(text, 50)
    assert len(result) <= 50 and result.endswith('слово…')


def test_qwen3_empty_think_prefill_is_request_local():
    fake_client = mock.MagicMock()
    fake_client.__enter__.return_value.get.return_value.json.return_value = {'models': [{'name': 'qwen3:4b', 'size': 100}]}
    fake_client.__enter__.return_value.post.return_value.json.return_value = {'message': {'content': '{}'}}
    fake_client.__enter__.return_value.stream.return_value.__enter__.return_value.iter_bytes.return_value = [b'{"message":{"content":"{}"}}']
    configuration = SimpleNamespace(ollama_url='http://127.0.0.1:11434', model='qwen3:4b')
    original = [{'role': 'user', 'content': 'test'}]
    with mock.patch.object(agent, 'defaults', return_value=agent.GenerationSettings(configuration.model)), \
         mock.patch.object(agent, 'settings', configuration), \
         mock.patch.object(agent.httpx, 'Client', return_value=fake_client):
        agent.ollama_chat(original, [])
    body = fake_client.__enter__.return_value.stream.call_args.kwargs['json']
    assert body['messages'][-1] == {'role': 'assistant', 'content': '<think>\n\n</think>\n\n'}
    assert original == [{'role': 'user', 'content': 'test'}]
    configuration.model = 'other-model:latest'
    fake_client.__enter__.return_value.get.return_value.json.return_value = {'models': [{'name': configuration.model, 'size': 100}]}
    with mock.patch.object(agent, 'defaults', return_value=agent.GenerationSettings(configuration.model)), \
         mock.patch.object(agent, 'settings', configuration), \
         mock.patch.object(agent.httpx, 'Client', return_value=fake_client):
        agent.ollama_chat(original, [])
    assert fake_client.__enter__.return_value.stream.call_args.kwargs['json']['messages'] == original


def test_concurrent_duplicates_share_execution_and_immediate_result():
    store = RequestStore(workers=2)
    release = Event()
    calls = []
    def prepare():
        calls.append('execute')
        return SimpleNamespace(initial={'status': 'done'})
    def complete(prepared):
        release.wait(2)
        return {'answer': 'commentary'}
    try:
        with ThreadPoolExecutor(max_workers=10) as pool:
            entries = list(pool.map(lambda _: store.begin('same', 'same input', prepare, complete), range(10)))
        assert all(e is entries[0] for e in entries)
        assert entries[0].initial.result(timeout=1) == {'status': 'done'}
        assert not entries[0].final.done()
        assert calls == ['execute']
        with pytest.raises(RequestConflict):
            store.begin('same', 'different input', prepare, complete)
        release.set()
        assert entries[0].final.result(timeout=1)['answer'] == 'commentary'
        assert store.begin('same', 'same input', prepare, complete) is entries[0]
    finally:
        release.set()
        store.close()


def test_store_bounds_inflight_and_never_evicts_unexpired_id():
    store = RequestStore(capacity=1, workers=1)
    release = Event()
    def prepare():
        return SimpleNamespace(initial={})
    def complete(_):
        release.wait(2)
        return {}
    try:
        entry = store.begin('one', 'x', prepare, complete)
        with pytest.raises(RequestBusy):
            store.begin('two', 'x', prepare, complete)
        release.set()
        entry.final.result(timeout=1)
        with pytest.raises(RequestBusy):
            store.begin('two', 'x', prepare, complete)
    finally:
        release.set()
        store.close()


def test_disconnect_cancellation_cannot_destroy_execution_or_replay():
    store = RequestStore(workers=1)
    release = Event()
    calls = []
    def prepare():
        calls.append('execute')
        return SimpleNamespace(initial={'status': 'executed'})
    def complete(_):
        release.wait(2)
        return {'answer': 'final'}
    try:
        first = store.begin('disconnect', 'same', prepare, complete)
        assert first.initial.cancel() is False
        assert first.final.cancel() is False
        assert first.initial.result(timeout=1)['status'] == 'executed'
        release.set()
        assert first.final.result(timeout=1)['answer'] == 'final'
        replay = store.begin('disconnect', 'same', prepare, complete)
        assert replay is first and calls == ['execute']
    finally:
        release.set()
        store.close()


def test_home_assistant_acceptance_does_not_claim_observed_state():
    calls=[]
    real_client=httpx.Client
    def handler(request):
        calls.append(request.method)
        if request.method=='POST':return httpx.Response(200,json=[])
        return httpx.Response(200,json={'entity_id':'light.desk_lamp','state':'off'})
    transport=httpx.MockTransport(handler)
    configuration = SimpleNamespace(demo=False, ha_url='http://127.0.0.1:8123', ha_token='test-secret')
    with mock.patch.object(devices, 'settings', configuration), \
         mock.patch.object(devices.httpx, 'Client', side_effect=lambda **kw: real_client(transport=transport,**kw)) as client, \
         mock.patch('localmind.home_assistant.time.sleep'):
        result = devices.set_light('desk_light', 'on')
    assert not result.success and result.execution_status == 'request_accepted'
    assert result.observed_state == 'off' and result.mode == 'REAL'
    assert 'не подтверждено' in result.status_text
    assert 'test-secret' not in str(result.to_dict())
    assert client.call_args.kwargs['trust_env'] is False
    assert 'POST' in calls and calls[-1]=='GET'


def test_unexpected_composer_defect_keeps_trusted_outcome_and_dedup():
    store = RequestStore(workers=1)
    calls = []
    def prepare():
        calls.append('execute')
        return SimpleNamespace(initial={'answer': 'ДЕМО: лампа включена.', 'engine': 'rules',
                                        'action_results': [{'success': True}]})
    def complete(_):
        raise RuntimeError('private internal detail')
    try:
        entry = store.begin('bug', 'x', prepare, complete)
        final = entry.final.result(timeout=1)
        assert final['answer'] == 'ДЕМО: лампа включена.'
        assert final['action_results'][0]['success']
        assert 'private' not in str(final)
        assert store.begin('bug', 'x', prepare, complete) is entry
        assert calls == ['execute']
    finally:
        store.close()
