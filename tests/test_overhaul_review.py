"""Independent adversarial checks for composition and stalled local inference."""
import json
from unittest import mock

import httpx
import pytest

from localmind import agent
from localmind.generation import defaults, effective_generation, text_delta
from localmind.results import ActionResult


@pytest.mark.parametrize('result,commentary', [
    (ActionResult(True, 'open_app', 'Steam', 'process_created'),
     'Окно Steam уже здесь, если что — скажи.'),
    (ActionResult(True, 'set_light', 'desk_light', 'observed', observed_state='on', mode='DEMO'),
     'Симуляция: лампа не горит.'),
    (ActionResult(True, 'set_light', 'desk_light', 'observed', observed_state='off', mode='DEMO'),
     'Симуляция: лампа не выключена.'),
])
def test_factual_echo_cannot_authorize_contradictory_prose(result, commentary):
    prepared = agent.PreparedReply('Проверенный запрос', [], 'normal', True, 0, {}, result=result)
    output = {'success': result.success, 'execution_status': result.execution_status,
              'observed_state': result.observed_state, 'commentary': commentary}
    with mock.patch.object(agent, 'ollama_chat', return_value={'content': json.dumps(output)}):
        with pytest.raises(ValueError):
            agent._compose_action(prepared)


def test_continuous_thinking_chunks_cannot_bypass_total_generation_deadline(monkeypatch):
    # No real waiting or inference: the daemon keeps producing valid chunks,
    # while the elapsed wall clock jumps hours forward. An idle/read timeout
    # alone never expires for this response.
    clock = [0.0]
    monkeypatch.setattr(agent.time, 'monotonic', lambda: clock[0])
    client = mock.MagicMock()
    client.__enter__.return_value = client
    client.get.return_value.json.return_value = {
        'models': [{'name': defaults().model, 'size': 1000}]}
    client.post.return_value.json.return_value = {}
    stream = client.stream.return_value.__enter__.return_value

    def lines():
        clock[0] = 10_000.0
        yield json.dumps({'message': {'thinking': 'Продолжаю рассуждение'}, 'done': False})
        yield json.dumps({'message': {'content': '{"answer":"Ответ"}'}, 'done': True})

    stream.iter_bytes.side_effect = lambda: ((line+'\n').encode('utf-8') for line in lines())
    monkeypatch.setattr(agent.httpx, 'Client', lambda **_: client)
    token = text_delta.set(lambda _: None)
    config_token = effective_generation.set(defaults())
    try:
        with pytest.raises((ValueError, TimeoutError, httpx.TimeoutException)):
            agent.ollama_chat([{'role': 'user', 'content': 'Вопрос'}], [])
    finally:
        effective_generation.reset(config_token)
        text_delta.reset(token)


def test_unterminated_model_line_is_bounded_before_full_body_is_read(monkeypatch):
    consumed = [0]

    class UnterminatedLine(httpx.SyncByteStream):
        def __iter__(self):
            for _ in range(64):
                consumed[0] += 16384
                yield b' ' * 16384
            yield b'\n'

    def transport(request):
        if request.url.path == '/api/tags':
            return httpx.Response(200, json={'models': [{'name': defaults().model, 'size': 1000}]})
        if request.url.path == '/api/chat':
            return httpx.Response(200, stream=UnterminatedLine())
        return httpx.Response(200, json={})

    original_client = httpx.Client
    monkeypatch.setattr(agent.httpx, 'Client',
                        lambda **kw: original_client(transport=httpx.MockTransport(transport), **kw))
    token = text_delta.set(lambda _: None)
    config_token = effective_generation.set(defaults())
    try:
        with pytest.raises((ValueError, TimeoutError, httpx.HTTPError)):
            agent.ollama_chat([{'role': 'user', 'content': 'Вопрос'}], [])
        assert consumed[0] <= 262144, 'Line limit must apply while receiving, before buffering the whole line'
    finally:
        effective_generation.reset(config_token)
        text_delta.reset(token)
