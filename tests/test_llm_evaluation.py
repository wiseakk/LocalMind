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


def test_next_corpus_has_real_russian_and_structured_tool_facts():
    corpus = json.loads(evaluation.CORPUS.read_text(encoding='utf-8'))
    cases = {case['id']: case for case in corpus['cases']}
    assert len(cases) >= 66
    assert cases['next-rsa-followup']['prompt'] == 'А кто его придумал?'
    assert cases['next-window-ambiguity']['prompt'] == 'Закрой это окно.'
    assert {'tool_facts', 'references', 'safety'} <= {case['category'] for case in cases.values()}
    assert cases['next-capability-truth']['runtime_facts']['last_result']['success'] is True
    messages = evaluation.messages_for(cases['next-capability-truth'], 'qwen3.5:4b')
    assert any(m['role'] == 'system' and 'apps.focus_window' in m['content'] for m in messages)
    evaluation.validate_candidate('qwen3.5:4b')


def test_percentiles_do_not_treat_missing_metrics_or_failures_as_zero():
    assert evaluation.distribution([None, 1, 2, 10, float('inf'), True]) == {'n': 3, 'p50': 2, 'p95': 10}
    result = evaluation.summary([{'wall_ms': 10}, {'error': {'type': 'timeout'}, 'wall_ms': 100}])
    assert result['attempts'] == 2 and result['failures'] == 1
    assert result['first_audible_audio_ms'] == {'n': 0, 'p50': None, 'p95': None}


def review_for(row, **changes):
    item = {'case_id': row['case_id'], 'answer_sha256': evaluation.answer_digest(row),
            'factual_correct': True, 'addresses_request': True, 'safe_and_truthful': True,
            'naturalness': 2, 'reason': 'Matches the full stated rubric, with no invented observations.'}
    item.update(changes)
    return {'method': 'ai-assisted', 'reviewer': 'test reviewer', 'answers': [item]}


def test_semantic_review_requires_exact_answer_binding_and_reasons():
    row = {'case_id': 'rsa', 'answer': 'Ответ'}
    ledger = review_for(row)
    score = evaluation.semantic_review([row], ledger)
    assert score['pass_rate'] == 1 and score['method'] == 'ai-assisted'
    assert score['reviewed'] == 1
    with pytest.raises(ValueError, match='retained answer'):
        evaluation.semantic_review([dict(row, answer='Другой ответ')], ledger)
    with pytest.raises(ValueError, match='reason'):
        evaluation.semantic_review([row], review_for(row, reason=''))
    with pytest.raises(ValueError, match='booleans'):
        evaluation.semantic_review([row], review_for(row, factual_correct='true'))


def test_partial_or_core_failure_review_cannot_promote_profiles():
    row = {'case_id': 'rsa', 'answer': 'Ответ'}
    entry = {'model': 'qwen3:4b', 'comparison': [row], 'cold_warm': []}
    document = {'full_corpus': False, 'models': [entry]}
    assert evaluation.select_profiles(document, {})['quality'] is None
    document.update(full_corpus=True, comparison_case_ids=['rsa'], core_regression_ids=['rsa'])
    result = evaluation.select_profiles(document, {'qwen3:4b': review_for(row, factual_correct=False)})
    assert result['quality'] is None
    assert 'core' in result['reasons'][0]


def test_incomplete_stream_is_retained_as_failure_even_if_json_is_valid(monkeypatch):
    monkeypatch.setattr(evaluation, 'gpu', lambda: {})
    monkeypatch.setattr(evaluation, 'memory', lambda: {})
    monkeypatch.setattr(evaluation, 'command', lambda args: {})
    def respond(request):
        if request.url.path == '/api/ps':
            return httpx.Response(200, json={'models': []})
        return httpx.Response(200, text=json.dumps({'message': {'content': '{"answer":"391"}'}}))
    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        row = evaluation.infer(client, 'http://127.0.0.1:11434', 'qwen3:4b',
                               {'id': 'x', 'category': 'mathematics', 'split': 'heldout', 'prompt': '?'})
    assert row['error']['type'] == 'ValueError'
    assert row['raw_first_token_ms'] is not None


def test_stream_line_budget_applies_before_unterminated_line_buffering():
    class Response:
        def iter_bytes(self):
            yield b'x' * 131073
    import time
    with pytest.raises(ValueError, match='Unterminated'):
        list(evaluation.bounded_lines(Response(), time.perf_counter()))
