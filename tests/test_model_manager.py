import json
from unittest.mock import patch
import pytest
from localmind import model_manager as mm, agent
from localmind.generation import GenerationSettings


def test_invalid_metrics_and_real_identity():
    assert mm.response_metrics({'model': 'actual:4b', 'eval_count': 10, 'eval_duration': 2e9})['tokens_per_second'] == 5
    for value in (None, 0, -1, float('nan'), '10', True, 10**10000):
        assert mm.response_metrics({'eval_count': 10, 'eval_duration': value})['tokens_per_second'] is None
    assert mm.response_metrics({})['actual_model'] is None


@pytest.mark.parametrize('item,expected', [({}, 'unknown'), ({'size': 100, 'size_vram': 0}, 'CPU'),
    ({'size': 100, 'size_vram': 50}, 'hybrid'), ({'size': 100, 'size_vram': 100}, 'GPU'),
    ({'size': 100, 'size_vram': 101}, 'unknown')])
def test_placement(item, expected):
    assert mm.placement(item) == expected


def test_switch_is_transactional(tmp_path, monkeypatch):
    manager = mm.ModelManager(tmp_path / 'active.json')
    previous = manager.active
    monkeypatch.setattr(mm, 'installed_detail', lambda name: {})
    monkeypatch.setattr(mm, 'ollama_json', lambda *a, **k: {'done': True, 'model': 'new:4b', 'message': {'content': 'привет'}})
    manager.select('new:4b')
    assert manager.active == 'new:4b'
    assert mm.ModelManager(manager.path).active == 'new:4b'
    monkeypatch.setattr(mm, 'ollama_json', lambda *a, **k: {})
    with pytest.raises(ValueError): manager.select(previous)
    assert manager.active == 'new:4b'
    assert json.loads(manager.path.read_text())['model'] == 'new:4b'


def test_failed_persistence_and_concurrent_switches_preserve_working_selection(tmp_path, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event
    manager = mm.ModelManager(tmp_path / 'active.json')
    monkeypatch.setattr(mm, 'installed_detail', lambda name: {'digest': name})
    entered, release = Event(), Event()
    def health(method, endpoint, body=None, **kw):
        name = body['model']
        if name == 'good:4b': entered.set(); assert release.wait(2)
        return {'model': name, 'done': True, 'message': {'content': 'привет' if name == 'good:4b' else ''}}
    monkeypatch.setattr(mm, 'ollama_json', health)
    with ThreadPoolExecutor(2) as pool:
        first = pool.submit(manager.select, 'good:4b'); assert entered.wait(2)
        second = pool.submit(manager.select, 'bad:4b'); release.set()
        assert first.result()['active'] == 'good:4b'
        with pytest.raises(ValueError): second.result()
    assert manager.active == 'good:4b'
    with patch.object(mm.os, 'replace', side_effect=OSError('private path')):
        with pytest.raises(OSError): manager.select('good:4b')
    assert mm.ModelManager(manager.path).active == 'good:4b'


def test_rules_dont_reuse_metrics():
    mm.observe({'model': 'old'})
    result = agent.complete_reply(agent.prepare_reply('Не запускай калькулятор', compose_actions=False))
    assert result['actual_model'] is None and result['metrics'] is None


@pytest.mark.parametrize('remote', ['remote_host', 'remote_model'])
def test_cloud_alias_refused(monkeypatch, remote):
    monkeypatch.setattr(mm, 'ollama_json', lambda *a, **k: {'models': [{'name': 'alias:4b', 'size': 100, remote: 'x'}]})
    with pytest.raises(ValueError): mm.installed_detail('alias:4b')


def test_no_nvidia_does_not_break_start(monkeypatch):
    import sys
    from localmind.hardware import hardware_status
    monkeypatch.setitem(sys.modules, 'pynvml', None)
    assert hardware_status()['gpu_status'] == 'unavailable'


@pytest.mark.parametrize('value', [float('nan'), float('inf'), -float('inf'), -0.01, 2.01, True, '0.2', 10**1000])
def test_generation_rejects_nonfinite_and_invalid_temperature(value):
    with pytest.raises(ValueError):
        GenerationSettings('gemma4:12b', temperature=value)


def test_generation_preferences_are_independent_per_model_and_survive_restart(tmp_path, monkeypatch):
    manager = mm.ModelManager(tmp_path / 'model.json')
    monkeypatch.setattr(manager, '_active', 'gemma4:12b')
    manager.save_generation({'temperature': 0.35, 'reasoning': 'off', 'context_tokens': 2048, 'response_tokens': 256})
    monkeypatch.setattr(manager, '_active', 'ministral-3:8b')
    manager.save_generation({'temperature': 0.15, 'reasoning': 'off', 'context_tokens': 4096, 'response_tokens': 512})
    restored = mm.ModelManager(manager.path)
    assert restored.active == 'ministral-3:8b'
    assert restored.generation('gemma4:12b')['temperature'] == 0.35
    assert restored.generation('gemma4:12b')['context_tokens'] == 2048
    assert restored.generation()['temperature'] == 0.15
    assert restored.generation()['response_tokens'] == 512


def test_explicit_generation_controls_reach_actual_ollama_body(monkeypatch):
    from test_overhaul import install_ollama_transport
    calls = install_ollama_transport(monkeypatch, [{'model': 'gemma4:12b', 'message': {'thinking': 'private', 'content': '{"answer":"Привет"}'}, 'done': True}],
        models=[{'name': 'gemma4:12b', 'size': 100}])
    prepared = agent.prepare_reply('Привет', generation=GenerationSettings('gemma4:12b', reasoning='off', context_tokens=2048,
        response_tokens=256, keep_alive_seconds=60, temperature=0.35))
    result = agent.complete_reply(prepared)
    body = next(value for path, value in calls if path == '/api/chat')
    assert body['options'] == {'temperature': 0.35, 'num_ctx': 2048, 'num_predict': 256}
    assert body['think'] is False and body['keep_alive'] == 60
    assert body['messages'][0]['role'] == 'system'
    assert result['answer'] == 'Привет' and 'private' not in str(result)


@pytest.mark.parametrize('stream', [False, True])
def test_gemma_thought_channel_never_reaches_main_answer(monkeypatch, stream):
    from test_overhaul import install_ollama_transport
    secret = '<|channel>thought\nprivate analysis<channel|>Ответ'
    install_ollama_transport(monkeypatch, [{'model': 'gemma4:12b', 'message': {'content': json.dumps({'answer': secret})}, 'done': True}],
        models=[{'name': 'gemma4:12b', 'size': 100}])
    prepared = agent.prepare_reply('Привет', generation=GenerationSettings('gemma4:12b'))
    emitted = []
    if stream:
        prepared.on_delta = emitted.append
    result = agent.complete_reply(prepared)
    assert result['engine'] == 'offline-error'
    assert 'private analysis' not in str(result) + ''.join(emitted)


def test_benchmark_busy_does_not_poison_retry_or_block_accepted_replay(monkeypatch):
    from localmind import server
    from localmind.model_benchmark import benchmarks
    from localmind.requests import RequestStore
    from fastapi import HTTPException
    store = RequestStore()
    monkeypatch.setattr(server, 'store', store)
    monkeypatch.setattr(server, 'complete_reply', lambda prepared: prepared.initial)
    busy = [False]
    monkeypatch.setattr(benchmarks, 'running', lambda: busy[0])
    data = server.ChatRequest(text='Привет', request_id='model-busy-test')
    try:
        busy[0] = True
        with pytest.raises(HTTPException) as error: server._entry(data)
        assert error.value.status_code == 429 and not store._entries
        busy[0] = False
        entry = server._entry(data); entry.final.result(2)
        busy[0] = True
        assert server._entry(data) is entry
    finally:
        store.close()


def test_management_routes_inherit_origin_key_host_and_peer_boundary(monkeypatch):
    from dataclasses import replace
    from fastapi.testclient import TestClient
    from localmind import server
    from localmind import model_routes
    monkeypatch.setattr(server, 'settings', replace(server.settings, key='local-test-key'))
    local = TestClient(server.app, base_url='http://127.0.0.1', client=('127.0.0.1', 1))
    remote = TestClient(server.app, base_url='http://127.0.0.1', client=('192.168.1.1', 1))
    with patch.object(model_routes.catalog, 'search_hub', return_value=[]) as search:
        assert local.get('/api/models/hub/search?query=x').status_code == 401
        assert local.get('/api/models/hub/search?query=x', headers={'X-LocalMind-Key':'local-test-key','Origin':'https://evil.invalid'}).status_code == 403
        assert remote.get('/api/models/hub/search?query=x', headers={'X-LocalMind-Key':'local-test-key'}).status_code == 403
        assert local.get('/api/models/hub/search?query=x', headers={'X-LocalMind-Key':'local-test-key','Host':'evil.invalid'}).status_code == 403
        search.assert_not_called()
        assert local.get('/api/models/hub/search?query=x', headers={'X-LocalMind-Key':'local-test-key'}).status_code == 200
        search.assert_called_once_with('x')


@pytest.mark.parametrize('stream', [False, True])
def test_request_owned_metrics_survive_both_paths(monkeypatch, stream):
    from test_overhaul import install_ollama_transport
    data = {'model': 'actual:4b', 'message': {'content': '{"answer":"Привет"}'}, 'done': True,
            'eval_count': 20, 'eval_duration': 1000000000, 'load_duration': 500000, 'total_duration': 2000000000}
    install_ollama_transport(monkeypatch, [data])
    prepared = agent.prepare_reply('Привет', generation=GenerationSettings('qwen3:4b'))
    if stream: prepared.on_delta = lambda text: None
    result = agent.complete_reply(prepared)
    assert result['actual_model'] == 'actual:4b'
    assert result['metrics']['tokens_per_second'] == 20
