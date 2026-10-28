"""The evaluator is offline in CI; real benchmark evidence is separately retained."""
import importlib.util
import json
from pathlib import Path

import pytest
import httpx

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('eval_llm', ROOT / 'scripts/eval_llm.py')
evaluation = importlib.util.module_from_spec(spec)
spec.loader.exec_module(evaluation)


def test_corpus_has_six_balanced_categories_heldout_and_required_regressions():
    corpus = json.loads(evaluation.CORPUS.read_text(encoding='utf-8'))
    cases = corpus['cases']
    assert corpus['scoring']['frozen_before_comparison']
    assert len({c['id'] for c in cases}) == len(cases)
    for category in ('facts', 'everyday', 'followups', 'mathematics', 'code', 'dialogue'):
        assert len([c for c in cases if c['category'] == category and c['split'] == 'calibration']) >= 6
        assert any(c['category'] == category and c['split'] == 'heldout' for c in cases)
    assert {'Что такое RSA?', 'Как сварить пельмени?', 'Открой, пожалуйста, Steam',
            'Не открывай Steam', 'Что ты умеешь?'} <= {c['prompt'] for c in cases}


@pytest.mark.parametrize('url', ['https://localhost:11434', 'http://example.com', 'http://127.0.0.1@evil.test', 'http://localhost:11434?token=x'])
def test_evaluation_refuses_remote_or_credential_endpoints(url):
    with pytest.raises(ValueError):
        evaluation.local_url(url)


def test_screening_is_not_presented_as_semantic_accuracy():
    case = {'must_match': ['ривест', 'шамир', 'адлеман']}
    result = evaluation.objective_score(case, 'Ривест, Шамир, Адлеман')
    assert result['passed']
    assert result['human_review'] == 'pending'
    assert not evaluation.objective_score(case, 'Ривест')['passed']


def test_qwen_prefill_is_scoped_to_qwen3_not_other_models():
    case = {'prompt': 'Привет'}
    assert evaluation.messages_for(case, 'qwen3:8b')[-1]['role'] == 'assistant'
    assert evaluation.messages_for(case, 'qwen3.5:9b')[-1]['role'] == 'user'
    assert evaluation.messages_for(case, 'qwen3:8b', False)[-1]['role'] == 'user'


@pytest.mark.parametrize('name,metadata', [
    ('qwen3:cloud', {}), ('qwen3:8b', {'remote_host': 'https://example.com'}),
    ('qwen3.5:9b', {'remote_model': 'cloud-model'})])
def test_evaluation_never_selects_cloud_models(name, metadata):
    with pytest.raises(ValueError):
        evaluation.validate_candidate(name, metadata)


def test_evidence_save_keeps_previous_snapshot_on_write_failure(tmp_path, monkeypatch):
    output = tmp_path / 'evidence.json'
    evaluation.save(output, {'complete': True})
    original = output.read_bytes()
    write_text = Path.write_text
    def fail_temporary(path, *args, **kwargs):
        if path.name.endswith('.tmp'):
            raise OSError('simulated interrupted write')
        return write_text(path, *args, **kwargs)
    monkeypatch.setattr(Path, 'write_text', fail_temporary)
    with pytest.raises(OSError):
        evaluation.save(output, {'complete': False})
    assert output.read_bytes() == original


@pytest.mark.parametrize('show_status,show_data', [
    (200, {'remote_model': 'qwen3:8b', 'remote_host': 'https://cloud.invalid'}),
    (503, {'error': 'metadata unavailable'})])
def test_cli_denies_remapped_candidate_or_failed_metadata_before_inference(tmp_path, monkeypatch, show_status, show_data):
    requested = []
    def respond(request):
        requested.append(request.url.path)
        if request.url.path == '/api/version':
            return httpx.Response(200, json={'version': 'test'})
        if request.url.path == '/api/tags':
            return httpx.Response(200, json={'models': [{'name': 'qwen3:8b'}]})
        if request.url.path == '/api/show':
            return httpx.Response(show_status, json=show_data)
        raise AssertionError('Unsafe inference or unload attempted before metadata validation')
    client_type = httpx.Client
    monkeypatch.setattr(evaluation.httpx, 'Client', lambda **kwargs: client_type(transport=httpx.MockTransport(respond)))
    monkeypatch.setattr(evaluation, 'gpu', lambda: {})
    monkeypatch.setattr(evaluation, 'memory', lambda: {})
    output = tmp_path / 'denied.json'
    monkeypatch.setattr(evaluation.sys, 'argv', ['eval_llm.py', '--models', 'qwen3:8b', '--limit', '1', '--output', str(output)])
    evaluation.main()
    document = json.loads(output.read_text(encoding='utf-8'))
    assert document['models'][0]['error']
    assert document['models'][0]['comparison'] == []
    assert requested == ['/api/version', '/api/tags', '/api/show']


def test_inference_retains_api_metrics_and_separates_browser_timing(monkeypatch):
    monkeypatch.setattr(evaluation, 'gpu', lambda: {'unavailable': 'CI'})
    monkeypatch.setattr(evaluation, 'memory', lambda: {'unavailable': 'CI'})
    monkeypatch.setattr(evaluation, 'command', lambda args: {'unavailable': 'CI'})
    def respond(request):
        if request.url.path == '/api/ps':
            return httpx.Response(200, json={'models': []})
        return httpx.Response(200, text='\n'.join([
            json.dumps({'message': {'content': '{"answer":"391"}'}}),
            json.dumps({'done': True, 'eval_count': 4, 'eval_duration': 100000000,
                        'load_duration': 12, 'prompt_eval_duration': 24})]))
    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        result = evaluation.infer(client, 'http://127.0.0.1:11434', 'qwen3:4b',
                                  {'id': 'test', 'category': 'mathematics', 'split': 'heldout',
                                   'prompt': '17*23', 'must_match': ['391']})
    assert result['answer'] == '391'
    assert result['tokens_per_second'] == 40
    assert result['first_generated_text_ms'] is not None
    assert result['first_browser_visible_text_ms'] is None
    assert result['objective']['passed']


def test_inference_retains_malformed_output_as_failed_run(monkeypatch):
    monkeypatch.setattr(evaluation, 'gpu', lambda: {})
    monkeypatch.setattr(evaluation, 'memory', lambda: {})
    monkeypatch.setattr(evaluation, 'command', lambda args: {})
    def respond(request):
        if request.url.path == '/api/ps':
            return httpx.Response(200, json={'models': []})
        return httpx.Response(200, text=json.dumps({'done': True, 'message': {'content': '{"answer":'}}))
    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        result = evaluation.infer(client, 'http://127.0.0.1:11434', 'qwen3:4b',
                                  {'id': 'test', 'category': 'facts', 'split': 'heldout', 'prompt': '?'})
    assert result['raw_content'] == '{"answer":'
    assert result['error']['type'] == 'JSONDecodeError'
    assert not result['objective']['passed']
