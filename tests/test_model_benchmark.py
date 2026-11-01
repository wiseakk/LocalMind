import ast
import copy
import json
from threading import Event
import time
from unittest.mock import patch
import httpx
import pytest
from localmind import model_benchmark as b, agent


def detail(name='test:4b', tools=True):
    return {'name': name, 'digest': name + '-digest', 'capabilities': ['completion'] + (['tools'] if tools else []),
            'details': {'quantization_level': 'Q4_K_M'}}


def valid_chat(calls):
    def chat(method, endpoint, body, **kwargs):
        calls.append(copy.deepcopy(body))
        task = next(t for t in b.SUITE['tasks'] if t['prompt'] == body['messages'][1]['content'])
        kind, expected = task['check'], task['expected']
        message = {'content': ''}
        if kind == 'tool': message['tool_calls'] = [{'function': expected}]
        else: message['content'] = json.dumps(expected) if kind == 'json' else expected if kind == 'no_tool' else json.dumps({'answer':expected})
        return {'done': True, 'model': body['model'], 'done_reason': 'stop', 'message': message,
                'eval_count': 20, 'eval_duration': 1000000000, 'load_duration': 2000, 'total_duration': 1000002000}
    return chat


def test_fixed_suite_and_correct_screening_no_actions_or_code_execution():
    assert len(b.SUITE['tasks']) == 12 and len(b.SUITE_HASH) == 64
    calls=[]
    result = b.evaluate_model('test:4b', detail(), cancelled=Event(), publish=lambda rows: None, chat=valid_chat(calls))
    assert result['complete'] and result['scores']['factual']['passed'] == 3
    assert result['scores']['tools']['passed'] == 2
    assert result['scores']['performance']['tokens_per_second_mean'] == 20
    assert all(c['options'] == b.SUITE['settings'] and c['think'] is False for c in calls)


def test_code_ast_checker_never_executes_model_code():
    task=next(t for t in b.SUITE['tasks'] if t['category']=='coding')
    with patch('builtins.exec') as execute, patch('subprocess.Popen') as spawn:
        assert not b.score(task, {'content': "import os; os.system('calc')"})
        assert not b.score(task, {'content': '__import__("os").remove("secret")'})
        execute.assert_not_called(); spawn.assert_not_called()


def test_scores_separate_and_unsupported_tools_na():
    result=b.evaluate_model('test:4b', detail(tools=False), cancelled=Event(), publish=lambda rows:None, chat=valid_chat([]))
    assert result['complete']
    assert result['scores']['tools']['score'] is None and result['scores']['tools']['total']==0
    assert result['scores']['structured']['passed']==1
    assert result['scores']['coding']['passed']==1
    assert result['scores']['uncertainty']['passed']==1


@pytest.mark.parametrize('data', [
    {'done':True,'model':'other:4b','message':{'content':'привет'}},
    {'done':False,'model':'test:4b','message':{'content':'привет'}},
    {'done':True,'message':{'content':'привет'}},
    {'done':True,'model':'test:4b','done_reason':'length','message':{'content':'привет'}}])
def test_incomplete_or_wrong_identity_never_completed(data):
    result=b.evaluate_model('test:4b',detail(),cancelled=Event(),publish=lambda rows:None,chat=lambda *a,**kw:data)
    assert not result['complete'] and all(r['status']=='error' for r in result['results'])


def test_comparison_identical_inputs_no_switch_and_persisted_rating(tmp_path,monkeypatch):
    calls=[]
    monkeypatch.setattr(b,'installed_detail',detail)
    mock_chat=valid_chat(calls)
    monkeypatch.setattr(b,'ollama_json',lambda method,endpoint,body=None,**kw: {'models':[]} if endpoint=='ps' else mock_chat(method,endpoint,body,**kw))
    jobs=b.BenchmarkJobs(tmp_path)
    from localmind.model_manager import manager
    active=manager.active
    job=jobs.start(['first:4b','second:4b'])
    deadline=time.monotonic()+3
    while jobs.snapshot(job['id'])['status']=='running' and time.monotonic()<deadline: time.sleep(.01)
    result=jobs.snapshot(job['id'])
    assert result['status']=='completed' and result['progress']=={'completed':24,'total':24}
    assert [{k:v for k,v in c.items() if k!='model'} for c in calls[:12]] == [{k:v for k,v in c.items() if k!='model'} for c in calls[12:]]
    assert manager.active==active
    before=copy.deepcopy(result['models'])
    jobs.rate(job['id'],'first:4b',4)
    loaded=b.BenchmarkJobs(tmp_path).snapshot(job['id'])
    assert loaded['manual_ratings']=={'first:4b':4} and loaded['models']==before
    assert loaded['suite_hash']==b.SUITE_HASH


def test_busy_and_invalid_paths_no_files_or_actions(tmp_path,monkeypatch):
    monkeypatch.setattr(b,'installed_detail',detail)
    jobs=b.BenchmarkJobs(tmp_path)
    with agent._inference_slot():
        with pytest.raises(ValueError,match='занят'): jobs.start(['test:4b'])
    for key in ['../secret','C:/secret','a'*31,'f'*33]:
        with pytest.raises(ValueError): jobs.snapshot(key)
    assert jobs.snapshot()==[]


def test_cancellation_and_load_failure_incomplete():
    cancelled=Event();cancelled.set()
    assert not b.evaluate_model('test:4b',detail(),cancelled=cancelled,publish=lambda r:None,chat=valid_chat([]))['complete']
    def unavailable(*a,**kw):raise httpx.ConnectError('private-path-and-token')
    result=b.evaluate_model('test:4b',detail(),cancelled=Event(),publish=lambda r:None,chat=unavailable)
    assert not result['complete'] and 'private-path' not in str(result)


def test_json_booleans_are_not_integers():
    task=next(t for t in b.SUITE['tasks'] if t['check']=='json')
    assert not b.score(task,{'content':'{"action":"none","authorized":0}'})
    assert not b.score(task,{'content':'{"action":"none","authorized":false,"command":"calc"}'})


def test_changed_digest_prevents_completed_comparison(tmp_path,monkeypatch):
    calls=[]; seen=[]
    def changing(name):
        result=detail(name);seen.append(name)
        if len(seen)>1: result['digest']='changed'
        return result
    monkeypatch.setattr(b,'installed_detail',changing)
    mock_chat=valid_chat(calls)
    monkeypatch.setattr(b,'ollama_json',lambda method,endpoint,body=None,**kw: {'models':[]} if endpoint=='ps' else mock_chat(method,endpoint,body,**kw))
    jobs=b.BenchmarkJobs(tmp_path);job=jobs.start(['test:4b'])
    deadline=time.monotonic()+3
    while jobs.snapshot(job['id'])['status']=='running' and time.monotonic()<deadline:time.sleep(.01)
    assert jobs.snapshot(job['id'])['status']=='incomplete'


def test_failed_initial_save_releases_inference_and_does_not_leave_ghost_job(tmp_path,monkeypatch):
    monkeypatch.setattr(b,'installed_detail',detail)
    jobs=b.BenchmarkJobs(tmp_path)
    monkeypatch.setattr(jobs,'_save',lambda job: (_ for _ in ()).throw(OSError('disk full')))
    with pytest.raises(OSError): jobs.start(['test:4b'])
    assert not jobs.jobs and not jobs.cancel_events
    assert agent._inference_lock.acquire(blocking=False)
    agent._inference_lock.release()


def test_restarted_running_job_is_incomplete_and_never_resumed(tmp_path):
    key='a'*32
    job={'id':key,'status':'running','models':[],'requested_models':['test:4b'],'manual_ratings':{}}
    (tmp_path/(key+'.json')).write_text(json.dumps(job),encoding='utf-8')
    jobs=b.BenchmarkJobs(tmp_path)
    assert jobs.snapshot(key)['status']=='incomplete'
    assert not jobs.cancel_events


def test_deadline_and_failed_rating_do_not_fabricate_completion(tmp_path,monkeypatch):
    result=b.evaluate_model('test:4b',detail(),cancelled=Event(),publish=lambda rows:None,chat=valid_chat([]),deadline=0)
    assert not result['complete'] and result['scores']['factual']['score'] is None
    key='b'*32;jobs=b.BenchmarkJobs(tmp_path)
    jobs.jobs[key]={'id':key,'status':'completed','requested_models':['test:4b'],'manual_ratings':{}}
    monkeypatch.setattr(jobs,'_save',lambda job: (_ for _ in ()).throw(OSError('disk full')))
    with pytest.raises(OSError): jobs.rate(key,'test:4b',4)
    assert jobs.jobs[key]['manual_ratings']=={}
