"""Behavioral acceptance checks for local model controls and safe streaming."""
from dataclasses import FrozenInstanceError, replace
from concurrent.futures import ThreadPoolExecutor
import json
from threading import Barrier, Event
from unittest.mock import Mock

from fastapi import HTTPException
import httpx
import pytest

from localmind import agent, server
from localmind.generation import GenerationSettings, effective_generation, json_answer_prefix, text_delta
from localmind.requests import RequestEntry, RequestStore
from localmind.results import ActionResult


@pytest.mark.parametrize('answer', [
    'Русский ответ с **Markdown** и формулой \\(x^2\\).',
    'Кавычка " и обратная косая \\ и новая\nстрока.',
    'Небазовый символ: \U0001f600.',
])
def test_json_prefix_preserves_every_complete_character(answer):
    payload = json.dumps({'answer': answer}, ensure_ascii=True)
    last = ''
    for stop in range(len(payload) + 1):
        prefix = json_answer_prefix(payload[:stop])
        assert answer.startswith(prefix)
        assert prefix.startswith(last)
        assert not any(0xD800 <= ord(char) <= 0xDFFF for char in prefix)
        last = prefix
    assert last == answer


@pytest.mark.parametrize('payload', [r'{"answer":"\q"}', r'{"answer":"\uGGGG"}',
                                         r'{"answer":"\uDC00"}', r'{"answer":"\uD800\u0041"}'])
def test_json_prefix_rejects_malformed_escape(payload):
    with pytest.raises(ValueError):
        json_answer_prefix(payload)


@pytest.mark.parametrize('payload', ['{"thinking":"secret","answer":"answer"}',
                                         '{"tool_calls":[{"name":"open_app"}]}', 'not JSON'])
def test_json_prefix_never_exposes_non_answer_fields(payload):
    assert json_answer_prefix(payload) == ''


@pytest.mark.parametrize('text,target', [
    ('Открой Steam', 'steam'), ('Открой, пожалуйста, Steam', 'steam'),
    ('Можешь открыть Steam?', 'steam'), ('Запусти мне Steam', 'steam'),
    ('Открой Obsidian, пожалуйста', 'obsidian'), ('Откройте, пожалуйста, Steam!', 'steam'),
    ('Прошу тебя запустить Steam.', 'steam'), ('Будь добра, открой Obsidian.', 'obsidian'),
    ('Я хочу, чтобы ты открыла Steam', 'steam'),
])
def test_russian_request_forms_resolve_same_safe_intent(monkeypatch, text, target):
    monkeypatch.setattr(agent.catalog, 'aliases', lambda: {'steam': ('steam', 'стим'), 'obsidian': ('obsidian',)})
    assessment = agent.assess_action(text)
    assert assessment.grant is not None
    assert assessment.grant.name == 'open_app' and assessment.grant.arguments == {'app': target}


@pytest.mark.parametrize('text', [
    'Не открывай Steam', 'Можешь не открыть Steam?', 'Никогда не запускай Steam',
    '«Открой Steam»', 'Открой "Steam"', 'Если я скажу открой Steam',
    'Расскажи, как открыть Steam', 'Можно ли открыть Steam?',
    'Открой Steam и Obsidian', 'Открой Steam, закрой Obsidian',
    'Открой Steam; включи лампу', 'Открой Steam https://example.com',
    'Открой C:\\Windows\\System32\\cmd.exe', 'Открой Steam --silent',
])
def test_negative_quoted_hypothetical_and_compound_never_authorize(monkeypatch, text):
    monkeypatch.setattr(agent.catalog, 'aliases', lambda: {'steam': ('steam',), 'obsidian': ('obsidian',)})
    assert agent.assess_action(text).grant is None


@pytest.mark.parametrize('alias', ['steam и открой obsidian', 'steam и obsidian', 'steam; включи лампу'])
def test_compound_catalog_display_alias_cannot_authorize_multiple_intents(monkeypatch, alias):
    # Catalog display names are user-controlled shortcut metadata, not grammar.
    monkeypatch.setattr(agent.catalog, 'aliases', lambda: {
        'steam': ('steam', alias), 'obsidian': ('obsidian',)})
    assert agent.assess_action('Открой ' + alias).grant is None


def test_generation_snapshot_is_frozen_and_per_request():
    first = agent.prepare_reply('Привет', generation=GenerationSettings('qwen3:4b', 'on', 2048, 128, 0))
    second = agent.prepare_reply('Привет', generation=GenerationSettings('qwen3:8b', 'off', 4096, 512, 300))
    with pytest.raises(FrozenInstanceError):
        first.generation.model = 'other'
    assert first.initial['generation'] == {'model': 'qwen3:4b', 'reasoning': 'on',
        'context_tokens': 2048, 'response_tokens': 128, 'keep_alive_seconds': 0}
    assert second.generation.model == 'qwen3:8b'


def test_simultaneous_generations_keep_request_context_separate(monkeypatch):
    barrier = Barrier(2)
    def generate(messages, tools, **kwargs):
        config = effective_generation.get()
        barrier.wait(timeout=2)
        assert effective_generation.get() is config
        return {'content': json.dumps({'answer': config.model})}
    monkeypatch.setattr(agent, 'ollama_chat', generate)
    prepared = [agent.prepare_reply('Привет', generation=GenerationSettings(model))
                for model in ('qwen3:4b', 'qwen3:8b')]
    with ThreadPoolExecutor(max_workers=2) as workers:
        answers = list(workers.map(agent.complete_reply, prepared))
    assert [reply['answer'] for reply in answers] == ['qwen3:4b', 'qwen3:8b']
    assert effective_generation.get() is None


def test_active_selection_change_replays_original_without_reexecuting(monkeypatch):
    store = RequestStore(workers=1)
    monkeypatch.setattr(server, 'store', store)
    execute = Mock(return_value=ActionResult(True, 'set_light', 'desk_light', 'observed',
                                           'on', mode='DEMO', status_text='Симуляция: лампа включена.'))
    monkeypatch.setattr(agent, 'dispatch', execute)
    monkeypatch.setattr(server.manager, '_active', 'qwen3:4b')
    data = server.ChatRequest(text='Включи лампу', request_id='overhaul-default', compose_actions=False)
    try:
        first = server._entry(data)
        assert first.final.result(timeout=2)['generation']['model'] == 'qwen3:4b'
        monkeypatch.setattr(server.manager, '_active', 'qwen3:8b')
        assert server._entry(data) is first
        assert first.final.result()['generation']['model'] == 'qwen3:4b'
        assert execute.call_count == 1
    finally:
        store.close()


@pytest.mark.parametrize('field,value', [('model', 'qwen3:8b'), ('reasoning', 'on'),
    ('context_tokens', 2048), ('response_tokens', 128), ('keep_alive_seconds', 0)])
def test_changed_generation_setting_is_part_of_replay_identity(monkeypatch, field, value):
    store = RequestStore(workers=1)
    monkeypatch.setattr(server, 'store', store)
    monkeypatch.setattr(server, 'complete_reply', lambda prepared: prepared.initial)
    data = server.ChatRequest(text='Привет', request_id='overhaul-settings')
    try:
        entry = server._entry(data)
        entry.final.result(timeout=2)
        assert server._entry(data) is entry
        with pytest.raises(HTTPException) as conflict:
            server._entry(data.model_copy(update={field: value}))
        assert conflict.value.status_code == 409
    finally:
        store.close()


def install_ollama_transport(monkeypatch, chunks, *, models=None, show=None):
    calls = []
    original_client = httpx.Client
    models = models if models is not None else [{'name': 'qwen3:4b', 'size': 100}]

    def handle(request):
        body = json.loads(request.content) if request.content else None
        calls.append((request.url.path, body))
        if request.url.path == '/api/tags':
            return httpx.Response(200, json={'models': models})
        if request.url.path == '/api/show':
            return httpx.Response(200, json=show or {})
        if request.url.path == '/api/generate':
            return httpx.Response(200, json={'done': True})
        assert request.url.path == '/api/chat'
        if body['stream']:
            lines = '\n'.join(json.dumps(chunk, ensure_ascii=True) for chunk in chunks) + '\n'
            return httpx.Response(200, content=lines.encode())
        assert len(chunks) == 1
        return httpx.Response(200, json=chunks[0])

    transport = httpx.MockTransport(handle)
    monkeypatch.setattr(agent.httpx, 'Client', lambda *args, **kwargs:
                        original_client(*args, transport=transport, **kwargs))
    monkeypatch.setattr(agent, '_resident_model', None)
    return calls


def test_real_ollama_text_chunks_are_decoded_streamed_and_keep_thinking_private(monkeypatch):
    first = 'Это содержательный русский ответ, который достаточно длинный для первого фрагмента. '
    second = 'Продолжение с формулой \\(x=2\\).'
    encoded = json.dumps({'answer': first + second}, ensure_ascii=False)
    split = encoded.index('Продолжение')
    calls = install_ollama_transport(monkeypatch, [
        {'message': {'thinking': 'secret private reasoning', 'content': encoded[:split]}, 'done': False},
        {'message': {'content': encoded[split:]}, 'done': True},
    ])
    prepared = agent.prepare_reply('Объясни пример', generation=GenerationSettings('qwen3:4b', 'on', 2048, 128, 0))
    seen = []
    prepared.on_delta = seen.append
    result = agent.complete_reply(prepared)
    assert result['engine'] == 'ollama'
    assert seen == [first, second]
    assert ''.join(seen) == result['answer']
    assert 'secret' not in str(result) + ''.join(seen)
    body = next(body for path, body in calls if path == '/api/chat')
    assert body['stream'] and body['think'] and body['tools'] == []
    assert body['options']['num_ctx'] == 2048 and body['options']['num_predict'] == 128
    assert body['keep_alive'] == 0
    assert effective_generation.get() is None and text_delta.get() is None


@pytest.mark.parametrize('kind', ['thinking', 'tool', 'interrupted'])
def test_unsafe_or_interrupted_initial_stream_does_not_expose_private_content(monkeypatch, kind):
    if kind == 'thinking':
        chunks = [{'message': {'content': json.dumps({'answer': '<think>private</think>Текст'})}, 'done': True}]
    elif kind == 'tool':
        chunks = [{'message': {'content': '{"answer":"текст"}', 'tool_calls': [{'function': {'name': 'open_app'}}]}, 'done': True}]
    else:
        chunks = [{'message': {'content': '{"answer":"короткий'}, 'done': False}]
    install_ollama_transport(monkeypatch, chunks)
    prepared = agent.prepare_reply('Привет')
    seen = []
    prepared.on_delta = seen.append
    result = agent.complete_reply(prepared)
    assert result['engine'] == 'offline-error' and seen == []


@pytest.mark.parametrize('escaped', [r'\ud800', r'\udc00'])
def test_isolated_surrogate_in_complete_model_answer_fails_safely(monkeypatch, escaped):
    install_ollama_transport(monkeypatch, [{'message': {'content': '{"answer":"' + escaped + '"}'}, 'done': True}])
    prepared = agent.prepare_reply('Привет')
    seen = []
    prepared.on_delta = seen.append
    result = agent.complete_reply(prepared)
    assert result['engine'] == 'offline-error' and seen == []
    json.dumps(result, ensure_ascii=False).encode('utf-8')


def action_prepared(result):
    prepared = agent.prepare_reply('Привет')
    prepared.dialogue = False
    prepared.result = result
    prepared.initial.update(answer=result.status_text, action_results=[result.to_dict()])
    return prepared


@pytest.mark.parametrize('status,state,text', [
    ('process_created', None, 'Окно Steam перед тобой.'),
    ('process_created', None, 'Steam уже работает.'),
    ('already_running', 'background', 'Запускаю Steam.'),
    ('already_running', 'background', 'Начал запуск Steam.'),
    ('already_running', 'background', 'Окно Steam открыто.'),
    ('launch_pending', None, 'Steam запустился.'),
    ('launch_pending', None, 'Создал новый процесс Steam.'),
])
def test_factual_json_echo_cannot_validate_false_app_prose(monkeypatch, status, state, text):
    result = ActionResult(True, 'open_app', 'Steam', status, state, status_text='Достоверный результат.')
    prepared = action_prepared(result)
    seen = []
    prepared.on_delta = seen.append
    answer = {key: result.to_dict()[key] for key in ('success', 'execution_status', 'observed_state')}
    answer['commentary'] = text
    install_ollama_transport(monkeypatch, [{'message': {'content': json.dumps(answer)}}])
    final = agent.complete_reply(prepared)
    assert final['answer'] == result.status_text
    assert final['commentary'] is None and seen == []


@pytest.mark.parametrize('state,text', [('on', 'В симуляции лампа выключена.'),
                                      ('off', 'В симуляции лампа включена.')])
def test_observed_light_state_cannot_be_inverted_in_prose(monkeypatch, state, text):
    result = ActionResult(True, 'set_light', 'desk_light', 'observed', state, mode='DEMO',
                          status_text='Достоверный результат симуляции.')
    prepared = action_prepared(result)
    seen = []
    prepared.on_delta = seen.append
    answer = {key: result.to_dict()[key] for key in ('success', 'execution_status', 'observed_state')}
    answer['commentary'] = text
    install_ollama_transport(monkeypatch, [{'message': {'content': json.dumps(answer)}}])
    assert agent.complete_reply(prepared)['commentary'] is None
    assert seen == []


def test_action_commentary_is_nonstreaming_until_full_validation(monkeypatch):
    result = ActionResult(True, 'open_app', 'Steam', 'process_created', status_text='Создан процесс.')
    prepared = action_prepared(result)
    prepared.generation = GenerationSettings('qwen3:4b', reasoning='on', response_tokens=2048)
    seen = []
    prepared.on_delta = seen.append
    commentary = 'Запускаю Steam; появление окна пока не подтверждено.'
    data = {'success': True, 'execution_status': 'process_created', 'observed_state': None,
            'commentary': commentary}
    calls = install_ollama_transport(monkeypatch, [{'message': {'content': json.dumps(data)}}])
    final = agent.complete_reply(prepared)
    assert final['answer'] == commentary and seen == [commentary]
    body = next(body for path, body in calls if path == '/api/chat')
    assert body['stream'] is False and body['think'] is False
    assert body['options']['num_predict'] <= 256


@pytest.mark.parametrize('metadata', ['missing', 'remote_tag', 'remote_show'])
def test_model_unavailability_preserves_completed_action_and_replay(monkeypatch, metadata):
    models = [] if metadata == 'missing' else [{'name': 'qwen3:4b', 'size': 100}]
    if metadata == 'remote_tag':
        models[0]['remote_host'] = 'remote.example'
    show = {'remote_model': 'remote-model'} if metadata == 'remote_show' else None
    calls = install_ollama_transport(monkeypatch, [], models=models, show=show)
    execute = Mock(return_value=ActionResult(True, 'set_light', 'desk_light', 'observed', 'on',
                                           mode='DEMO', status_text='Симуляция: лампа включена.'))
    monkeypatch.setattr(agent, 'dispatch', execute)
    store = RequestStore(workers=1)
    try:
        def prepare():
            return agent.prepare_reply('Включи лампу', actions_authorized=True)
        entry = store.begin('model-failure', 'same-settings', prepare, agent.complete_reply)
        final = entry.final.result(timeout=2)
        assert final['action_results'][0]['success']
        assert final['commentary'] is None and final.get('commentary_error')
        assert store.begin('model-failure', 'same-settings', prepare, agent.complete_reply) is entry
        assert execute.call_count == 1
        assert not any(path == '/api/chat' for path, body in calls)
    finally:
        store.close()


def test_delta_replay_is_bounded_and_identical_after_disconnect():
    store = RequestStore(workers=1)
    entered, release = Event(), Event()
    execution = Mock()
    try:
        def prepare():
            execution()
            return agent.prepare_reply('Привет')
        def complete(prepared):
            prepared.on_delta('Первая часть. ')
            entered.set()
            assert release.wait(2)
            prepared.on_delta('Вторая часть.')
            return {**prepared.initial, 'answer': 'Первая часть. Вторая часть.'}
        entry = store.begin('stream-replay', 'same', prepare, complete)
        assert entered.wait(1)
        initial, done = entry.read_deltas(0)
        assert initial == ['Первая часть. '] and not done
        assert entry.final.cancel() is False
        release.set()
        entry.final.result(timeout=2)
        replay = store.begin('stream-replay', 'same', prepare, complete)
        assert replay is entry and replay.read_deltas(0) == (['Первая часть. ', 'Вторая часть.'], True)
        execution.assert_called_once()
    finally:
        release.set()
        store.close()
    bounded = RequestEntry('bounds')
    bounded.publish('x' * 8192)
    bounded.publish('overflow')
    assert bounded.delta_chars == 8192
    assert bounded.deltas == ['x' * 8192]


@pytest.mark.parametrize('chunks', [[b'x' * 131073], [b'{"message":' + b' ' * 131073]])
def test_no_newline_model_data_is_bounded_before_decoding(chunks):
    response = Mock()
    response.iter_bytes.return_value = iter(chunks)
    with pytest.raises(ValueError):
        list(agent._model_lines(response))


def test_total_model_byte_budget_includes_private_thinking():
    response = Mock()
    response.iter_bytes.return_value = iter([b'x' * 1024] * 1025)
    with pytest.raises(ValueError):
        list(agent._bounded_bytes(response))


def test_nonstream_composition_response_is_bounded():
    response = Mock()
    response.iter_bytes.return_value = iter([b'x' * 131073])
    with pytest.raises(ValueError):
        list(agent._bounded_bytes(response, maximum=131072))


# Exercise existing behavior when the local planner is unavailable.
import pytest
pytestmark = pytest.mark.usefixtures("offline_desktop_planner")
