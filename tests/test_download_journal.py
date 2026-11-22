import json
import httpx
import pytest
from localmind.download_store import JobStore
from localmind.download_errors import download_error
from localmind import download_store


def test_restart_retains_progress_and_requires_explicit_retry(tmp_path):
    path=tmp_path/'jobs.json'; journal=JobStore(path)
    journal.insert({'id':'one','status':'downloading','completed':25,'total':100,'kind':'asr'})
    restored=JobStore(path).snapshot('one')
    assert restored['status']=='interrupted' and restored['completed']==25
    assert json.loads(path.read_text(encoding='utf-8'))[0]['status']=='interrupted'


def test_legacy_journal_is_reused_without_deletion_or_automatic_download(tmp_path):
    legacy=tmp_path/'private/downloads.json';legacy.parent.mkdir()
    legacy.write_text(json.dumps([{'id':'one','kind':'llm','status':'downloading','completed':20,'total':100}]))
    target=tmp_path/'downloads/jobs.json'
    restored=JobStore(target,legacy_path=legacy)
    assert restored.snapshot('one')['status']=='interrupted'
    assert restored.snapshot('one')['completed']==20
    assert not target.exists() and legacy.is_file()
    assert restored.path == legacy
    assert json.loads(legacy.read_text(encoding='utf-8'))[0]['status'] == 'interrupted'


def test_shared_queue_admits_distinct_resources_and_deduplicates_physical_files(tmp_path):
    journal=JobStore(tmp_path/'jobs.json')
    journal.insert({'id':'llm','status':'verifying','kind':'llm'})
    journal.insert({'id':'voice','status':'starting','kind':'tts'})
    journal.insert({'id':'small','status':'starting','kind':'asr','profile':'cpu-fast'})
    with pytest.raises(ValueError, match='этого ресурса'):
        journal.insert({'id':'alias','status':'starting','kind':'asr','profile':'balanced'})
    with pytest.raises(ValueError, match='этого ресурса'):
        journal.insert({'id':'voice-alias','status':'starting','kind':'tts'})
    assert len(journal.snapshot())==3


def test_journal_eviction_never_removes_an_active_job(tmp_path):
    journal = JobStore(tmp_path / 'jobs.json')
    journal.insert({'id': 'active', 'status': 'downloading', 'kind': 'tts'})
    for index in range(31):
        journal.insert({'id': str(index), 'status': 'failed'})
    journal.insert({'id': 'new', 'status': 'starting', 'kind': 'asr'})
    assert len(journal.snapshot()) == 32
    assert journal.snapshot('active')['status'] == 'downloading'
    assert journal.snapshot('new')['status'] == 'starting'


def test_dismiss_is_durable_and_does_not_delete_assets(tmp_path):
    journal=JobStore(tmp_path/'jobs.json')
    model=tmp_path/'model.gguf';model.write_bytes(b'keep')
    journal.insert({'id':'one','status':'downloading','destination':str(model)})
    with pytest.raises(ValueError):journal.dismiss('one')
    journal.update('one',status='succeeded')
    journal.dismiss('one')
    assert JobStore(journal.path).snapshot('one')['dismissed'] is True
    assert model.read_bytes()==b'keep'


def test_rates_require_measured_delta_and_are_cleared_after_restart(tmp_path,monkeypatch):
    clock=iter([0.,.5,2.5])
    monkeypatch.setattr(download_store.time,'monotonic',lambda:next(clock))
    journal=JobStore(tmp_path/'jobs.json')
    journal.insert({'id':'one','status':'downloading','total':2000})
    journal.update('one',completed=1000)  # May already be cached.
    assert journal.snapshot('one').get('bytes_per_second') is None
    journal.update('one',completed=1100)
    assert journal.snapshot('one').get('bytes_per_second') is None
    journal.update('one',completed=1250)
    assert journal.snapshot('one')['bytes_per_second']==100
    assert journal.snapshot('one')['eta_seconds']==7.5
    restored=JobStore(journal.path).snapshot('one')
    assert restored['completed']==1250 and restored['bytes_per_second'] is None


def test_failed_journal_update_rolls_back_visible_state(monkeypatch):
    journal=JobStore();journal.insert({'id':'one','status':'downloading','completed':10})
    monkeypatch.setattr(journal,'save',lambda:(_ for _ in ()).throw(OSError('disk full')))
    with pytest.raises(OSError):journal.update('one',status='succeeded')
    assert journal.snapshot('one')['status']=='downloading'


def test_failed_terminal_write_marks_only_a_terminal_error_in_memory(monkeypatch):
    journal = JobStore()
    journal.insert({'id': 'one', 'status': 'downloading', 'completed': 10})
    monkeypatch.setattr(journal, 'save', lambda: (_ for _ in ()).throw(OSError('disk full')))
    journal.terminal_failure('one', status='cancelled', error='Stopped')
    state = journal.snapshot('one')
    assert state['status'] == 'failed' and state['ready'] is False
    assert state['persistence_error'] in state['error']
    with pytest.raises(ValueError):
        journal.terminal_failure('one', status='succeeded')


@pytest.mark.parametrize('error,expected',[(httpx.ConnectError('offline'),'network'),
    (ValueError('dial tcp: i/o timeout'),'network'), (PermissionError('read-only directory'),'permission_denied'),
    (ValueError('SHA-256 не совпадает'),'incompatible'),
    (ValueError('disk full'),'disk_full'),(ValueError('unsupported architecture'),'unsupported'),
    (ValueError('incompatible GGUF'),'incompatible'),(ValueError('interrupted pull'),'interrupted'),
    (ValueError('unauthorized Bearer secret-token'),'auth_required')])
def test_download_diagnostics_classify_and_remove_secrets(error,expected):
    result=download_error(error,'pull')
    assert result['code']==expected
    assert 'secret-token' not in str(result)


def test_http_auth_and_404_are_different():
    for code, expected in ((401,'auth_required'),(403,'auth_required'),(404,'unavailable')):
        response=httpx.Response(code,request=httpx.Request('GET','https://example.invalid/private?token=abc'))
        error=httpx.HTTPStatusError('failure https://user:pass@server/?token=abc',request=response.request,response=response)
        result=download_error(error,'metadata')
        assert result['code']==expected and 'pass' not in str(result) and 'abc' not in str(result)


def test_json_credentials_in_technical_error_are_removed():
    error=ValueError('{"token":"my-secret-value", "Authorization": "Bearer hf_longsecrettoken123456"}')
    result=download_error(error,'pull')
    assert 'my-secret-value' not in str(result) and 'hf_longsecrettoken123456' not in str(result)
