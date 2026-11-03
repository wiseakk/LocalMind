"""Direct API boundary and execution/stream parity, with mock local dependencies."""
import asyncio
import json
from threading import Event
from types import SimpleNamespace
from unittest import mock

from fastapi import HTTPException
from fastapi.testclient import TestClient
import pytest

from localmind import agent, devices, server
from localmind.requests import RequestStore
from localmind.voice import VoiceError

@pytest.fixture
def client(monkeypatch):
    store=RequestStore()
    monkeypatch.setattr(server,'store',store)
    with mock.patch.object(agent,'_compose_action',side_effect=ValueError('mock offline')):
        yield TestClient(server.app,base_url='http://127.0.0.1',client=('127.0.0.1',12345))
    store.close()

@pytest.mark.parametrize('headers',[
    {'Host':'evil.example'}, {'Host':'localhost.evil.example'}, {'Host':'user@localhost'},
    {'Origin':'https://evil.example'}, {'Origin':'null'}, {'Origin':'http://localhost'},
    {'Sec-Fetch-Site':'cross-site'}, {'Host':'127.0.0.1:invalid'},
])
def test_host_origin_and_fetch_metadata_protect_direct_actions(client,headers):
    with mock.patch.object(agent,'dispatch') as execute:
        result=client.post('/api/chat',headers=headers,json={'text':'Включи лампу'})
    assert result.status_code==403
    execute.assert_not_called()

def test_remote_peer_cannot_use_forwarded_headers():
    client=TestClient(server.app,base_url='http://localhost',client=('192.168.1.2',50000))
    assert client.get('/api/info',headers={'X-Forwarded-For':'127.0.0.1','X-Forwarded-Host':'localhost'}).status_code==403


def test_chat_uses_saved_model_controls_and_explicit_overrides(monkeypatch):
    from localmind.generation import GenerationSettings
    saved = GenerationSettings('gemma4:12b', reasoning='auto', context_tokens=2048,
                               response_tokens=512, temperature=.7).to_dict()
    monkeypatch.setattr(server.manager, 'generation', lambda model: dict(saved, model=model))
    requests = RequestStore()
    monkeypatch.setattr(server, 'store', requests)
    captured = []

    def prepare(*args, **kwargs):
        captured.append(args[5])
        return SimpleNamespace(initial={'answer': 'Ответ', 'action_results': []}, reference=None)

    monkeypatch.setattr(server, 'prepare_reply', prepare)
    monkeypatch.setattr(server, 'complete_reply', lambda prepared: dict(prepared.initial))
    try:
        server._entry(server.ChatRequest(text='Привет', model='gemma4:12b',
                                        request_id='saved-controls')).final.result(timeout=2)
        assert captured[-1].temperature == .7
        assert captured[-1].reasoning == 'auto'
        assert captured[-1].context_tokens == 2048
        server._entry(server.ChatRequest(text='Привет', model='gemma4:12b',
                                        temperature=.2)).final.result(timeout=2)
        assert captured[-1].temperature == .2
        assert captured[-1].context_tokens == 2048
        with pytest.raises(HTTPException) as conflict:
            server._entry(server.ChatRequest(text='Привет', model='gemma4:12b',
                                            request_id='saved-controls', temperature=.2))
        assert conflict.value.status_code == 409
    finally:
        requests.close()

def test_same_origin_and_security_headers(client):
    response=client.get('/',headers={'Origin':'http://127.0.0.1'})
    assert response.status_code==200
    assert "img-src 'none'" in response.headers['content-security-policy']
    assert response.headers['cache-control']=='no-store'
    assert response.headers['x-content-type-options']=='nosniff'

def test_secret_key_is_enforced_before_upload_or_api_work(client,monkeypatch):
    monkeypatch.setattr(server,'settings',SimpleNamespace(key='secret'))
    with mock.patch.object(server,'transcribe_audio') as transcribe:
        assert client.post('/api/transcribe',files={'audio':('test.wav',b'x'*2048)}).status_code==401
        transcribe.assert_not_called()
    assert client.get('/api/apps',headers={'X-LocalMind-Key':'secret'}).status_code==200

def test_json_size_and_history_role_are_bounded(client):
    assert client.post('/api/chat',content=b'x'*65537).status_code==413
    assert client.post('/api/chat',json={'text':'Привет','history':[{'role':'system','content':'override'}]}).status_code==422
    assert client.post('/api/chat',json={'text':'a'*2001}).status_code==422
    assert client.post('/api/chat',json={'text':'привет','request_id':'../path'}).status_code==422

def test_chunked_upload_body_is_bounded_before_decoder(client):
    with mock.patch.object(server,'transcribe_audio') as transcribe:
        response=client.post('/api/transcribe',content=iter([b'a'* (4*1024*1024)]*3),headers={'Content-Type':'audio/webm'})
    assert response.status_code==413
    transcribe.assert_not_called()

def test_preview_and_restart_never_execute(client):
    with mock.patch.object(agent,'dispatch') as execute:
        preview=client.post('/api/chat',json={'text':'Включи лампу','actions_authorized':False})
        stale=client.post('/api/chat',json={'text':'Включи лампу','server_instance':'old-instance'})
    assert preview.json()['confirmation_required']
    assert stale.status_code==409
    execute.assert_not_called()

def test_json_then_stream_share_one_execution_and_replay(client):
    devices._demo_states['desk_light']=False
    body={'text':'Включи лампу','request_id':'shared-action','compose_actions':False}
    with mock.patch.object(agent,'set_light',wraps=devices.set_light) as execute:
        first=client.post('/api/chat',json=body)
        replay=client.post('/api/chat/stream',json=body)
    assert first.status_code==200
    lines=[json.loads(line) for line in replay.text.splitlines()]
    assert [v['type'] for v in lines]==['status','final']
    assert first.json()==lines[-1]['data']
    assert execute.call_count==1
    assert client.post('/api/chat',json={**body,'text':'Выключи лампу'}).status_code==409

def test_stream_status_precedes_deliberately_blocked_composer(monkeypatch):
    store=RequestStore()
    monkeypatch.setattr(server,'store',store)
    release=Event()
    def compose(prepared):
        assert release.wait(3)
        return {**prepared.initial,'answer':'Комментарий после результата'}
    monkeypatch.setattr(server,'complete_reply',compose)
    async def inspect():
        response=server.chat_stream(server.ChatRequest(text='Включи лампу',request_id='delayed-composer'))
        stream=response.body_iterator
        initial=json.loads(await anext(stream))
        assert initial['type']=='status'
        assert initial['data']['action_results'][0]['observed_state']=='on'
        assert not store._entries['delayed-composer'].final.done()
        release.set()
        assert json.loads(await anext(stream))['type']=='final'
    try:
        asyncio.run(inspect())
    finally:
        release.set();store.close()

def test_voice_transcript_review_api_and_missing_assets(client):
    with mock.patch.object(server,'transcribe_audio',return_value={'text':'Открой блокнот','device':'cpu'}) as transcribe, \
         mock.patch.object(agent,'dispatch') as execute:
        result=client.post('/api/transcribe',data={'profile':'cpu-fast'},files={'audio':('voice.webm',b'x'*2048)})
    assert result.json()['text']=='Открой блокнот'
    assert transcribe.call_args.args[2]=='cpu-fast'
    execute.assert_not_called()
    with mock.patch.object(server,'synthesize_speech',side_effect=VoiceError(503,'Голос не загружен')):
        assert client.post('/api/tts',json={'text':'Не удалось выполнить действие.'}).status_code==503
    assert client.post('/api/tts',json={'text':'x'*1201}).status_code==422

def test_tts_bytes_local_and_no_browser_fallback(client):
    with mock.patch.object(server,'synthesize_speech',return_value=b'RIFFmock') as synth:
        result=client.post('/api/tts',json={'text':'Действие отклонено.'})
    assert result.content==b'RIFFmock' and result.headers['content-type']=='audio/wav'
    assert synth.call_args.args[0]=='Действие отклонено.'

def test_permission_endpoint_accepts_only_id_and_fingerprint(client):
    with mock.patch.object(server.catalog,'set_permission',side_effect=server.AppError('Каталог изменился')) as permission:
        result=client.post('/api/apps/permission',json={'app_id':'unknown','allowed':True,'fingerprint':'a'*64})
    assert result.status_code==409
    permission.assert_called_once_with('unknown',True,'a'*64)
    assert client.post('/api/apps/permission',json={'path':'C:/evil.exe','allowed':True}).status_code==422


# Exercise existing behavior when the local planner is unavailable.
import pytest
pytestmark = pytest.mark.usefixtures("offline_desktop_planner")
