import hashlib
import json
import threading
import httpx
from localmind import offline_model as module
from localmind.download_store import JobStore


def test_offline_import_uploads_verified_blob_then_checks_inventory_without_selection(tmp_path,monkeypatch):
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
    monkeypatch.setattr('localmind.model_manager.installed_detail',lambda name:{'digest':'verified'})
    module._import('test',data,threading.Event())
    assert journal.snapshot('test')['status']=='succeeded'
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
