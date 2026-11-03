import json
import httpx
import pytest
from localmind.download_store import JobStore
from localmind.download_errors import download_error


def test_restart_retains_progress_and_requires_explicit_retry(tmp_path):
    path=tmp_path/'jobs.json'; journal=JobStore(path)
    journal.insert({'id':'one','status':'downloading','completed':25,'total':100,'kind':'asr'})
    restored=JobStore(path).snapshot('one')
    assert restored['status']=='interrupted' and restored['completed']==25
    assert json.loads(path.read_text(encoding='utf-8'))[0]['status']=='interrupted'


def test_shared_queue_serializes_model_and_voice_downloads(tmp_path):
    journal=JobStore(tmp_path/'jobs.json')
    journal.insert({'id':'llm','status':'verifying','kind':'llm'})
    with pytest.raises(ValueError):journal.insert({'id':'voice','status':'starting','kind':'tts'})
    journal.update('llm',status='succeeded')
    journal.insert({'id':'voice','status':'starting','kind':'tts'})
    assert len(journal.snapshot())==2


@pytest.mark.parametrize('error,expected',[(httpx.ConnectError('offline'),'network'),
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
