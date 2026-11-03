import hashlib
import json
import threading
import httpx
import pytest
from localmind import offline_model as module
from localmind.download_store import JobStore


@pytest.mark.parametrize('reported_sha', ['matching', 'different', None])
def test_offline_import_uploads_verified_blob_then_checks_inventory_without_selection(tmp_path,monkeypatch,reported_sha):
    root=tmp_path/'app';(root/'offline-llm').mkdir(parents=True)
    content=b'GGUF'+b'x'*1000000
    (root/'offline-llm/model.gguf').write_bytes(content)
    data={'model':'localmind-offline:1.0','bytes':len(content),'sha256':hashlib.sha256(content).hexdigest(),'license':'apache-2.0'}
    journal=JobStore();journal.insert({'id':'test','kind':'llm_offline','status':'starting'})
    monkeypatch.setattr(module,'APP_ROOT',root);monkeypatch.setattr(module,'store',journal)
    calls=[];original=httpx.Client
    def handle(request):
        calls.append(request.url.path)
        if '/blobs/' in request.url.path:
            if request.method=='HEAD':
                return httpx.Response(404)
            assert request.content==content
            return httpx.Response(201)
        assert json.loads(request.content)['files']=={'model.gguf':'sha256:'+data['sha256']}
        return httpx.Response(200,content=b'{"status":"success"}\n')
    monkeypatch.setattr(module.httpx,'Client',lambda **kw:original(transport=httpx.MockTransport(handle),**kw))
    from localmind.model_manager import manager
    before=manager.active
    actual_sha = data['sha256'] if reported_sha == 'matching' else '0'*64 if reported_sha == 'different' else None
    monkeypatch.setattr('localmind.model_manager.installed_detail',lambda name:{'digest':'verified','weight_sha256':actual_sha})
    module._import('test',data,threading.Event())
    result = journal.snapshot('test')
    assert result['status'] == ('succeeded' if reported_sha == 'matching' else 'failed')
    if reported_sha != 'matching':
        assert not result.get('ready') and result['diagnostic']['code'] == 'incompatible'
    assert '/api/blobs/sha256:' in calls[0] and '/api/blobs/sha256:' in calls[1] and calls[2]=='/api/create'
    assert manager.active==before


def test_corrupt_offline_gguf_never_reaches_ollama(tmp_path,monkeypatch):
    root=tmp_path/'app';(root/'offline-llm').mkdir(parents=True)
    (root/'offline-llm/model.gguf').write_bytes(b'GGUFcorrupted')
    journal=JobStore();journal.insert({'id':'test','kind':'llm_offline','status':'starting'})
    monkeypatch.setattr(module,'APP_ROOT',root);monkeypatch.setattr(module,'store',journal)
    monkeypatch.setattr(module.httpx,'Client',lambda **kwargs:(_ for _ in ()).throw(AssertionError('No network for corrupt file')))
    module._import('test',{'model':'localmind-offline:1.0','bytes':13,'sha256':'0'*64},threading.Event())
    assert journal.snapshot('test')['status']=='failed'


def test_offline_retry_requires_same_license_and_artifact(monkeypatch):
    previous={'model':'localmind-offline:1.0','bytes':1000000,'sha256':'a'*64,'license':'apache-2.0'}
    expected=module.artifact_fingerprint(previous)
    monkeypatch.setattr(module,'manifest',lambda:{**previous,'license':'changed'})
    with pytest.raises(ValueError,match='изменились'):
        module.start(True,expected_artifact=expected,retry=True,acknowledge_unknown_disk=True)


def test_offline_known_disk_shortfall_cannot_be_overridden(monkeypatch):
    monkeypatch.setattr(module,'manifest',lambda:{'model':'localmind-offline:1.0','bytes':1000000,'sha256':'a'*64,'license':'apache-2.0'})
    monkeypatch.setattr('localmind.model_catalog.disk_status',lambda:{'free':1,'path':'verified'})
    with pytest.raises(ValueError,match='Недостаточно'):
        module.start(True,acknowledge_unknown_disk=True)


@pytest.mark.parametrize('cancellation_point', ['hash', 'head'])
def test_cancel_during_hash_or_cached_blob_check_never_creates_model(tmp_path,monkeypatch,cancellation_point):
    root=tmp_path/'app';(root/'offline-llm').mkdir(parents=True)
    content=b'GGUF'+b'x'*1000000
    (root/'offline-llm/model.gguf').write_bytes(content)
    data={'model':'localmind-offline:1.0','bytes':len(content),'sha256':hashlib.sha256(content).hexdigest()}
    journal=JobStore();journal.insert({'id':'test','kind':'llm_offline','status':'starting'})
    monkeypatch.setattr(module,'APP_ROOT',root);monkeypatch.setattr(module,'store',journal)
    event=threading.Event();calls=[]
    original_digest=hashlib.file_digest
    def digest(*args,**kwargs):
        result=original_digest(*args,**kwargs)
        if cancellation_point=='hash':event.set()
        return result
    monkeypatch.setattr(module.hashlib,'file_digest',digest)
    original_client=httpx.Client
    def handle(request):
        calls.append((request.method,request.url.path))
        assert request.method=='HEAD', 'Cancellation must prevent blob upload and model creation'
        event.set()
        return httpx.Response(200)
    monkeypatch.setattr(module.httpx,'Client',lambda **kw:original_client(transport=httpx.MockTransport(handle),**kw))
    monkeypatch.setattr('localmind.model_manager.installed_detail',lambda name:pytest.fail('Cancelled import must not verify/install a model'))
    module._import('test',data,event)
    assert journal.snapshot('test')['status']=='cancelled_unverified'
    assert not any(method=='POST' for method,path in calls)
    assert len(calls)==(0 if cancellation_point=='hash' else 1)
