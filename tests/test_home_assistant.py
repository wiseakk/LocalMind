import json
import os
import httpx
import pytest
from localmind.home_assistant import HomeAssistant, HAError, local_origin


@pytest.mark.parametrize('origin',['https://evil.example','http://8.8.8.8:8123','http://169.254.169.254',
    'file:///C:/Windows','http://user:pass@192.168.1.2','http://192.168.1.2/path','http://127.0.0.1?token=secret',
    'http://0.0.0.0','http://224.0.0.1','http://localhost:8123','http://192.168.1.2#token'])
def test_controller_origin_is_local_numeric_and_has_no_credentials_or_path(origin):
    with pytest.raises(HAError):local_origin(origin)


@pytest.mark.parametrize('origin',['http://127.0.0.1:8123','http://192.168.1.2:8123','https://10.1.2.3','http://[fd00::1]:8123'])
def test_local_controllers(origin):
    assert local_origin(origin)==origin


def gateway(tmp_path, handler):
    transport=httpx.MockTransport(handler)
    return HomeAssistant(tmp_path/'home.json',client_factory=lambda **kw:httpx.Client(transport=transport,**kw),
                         protect_token=lambda token:'encrypted-test-fixture',unprotect_token=lambda _: 'private-token',sleep=lambda _:None)


def test_discovery_is_not_a_grant_and_switch_command_is_verified(tmp_path):
    calls=[];state={'value':'off'}
    def handler(request):
        calls.append((request.method,request.url.path))
        assert request.headers['authorization']=='Bearer private-token'
        if request.url.path=='/api/config':return httpx.Response(200,json={'components':['light','switch']})
        if request.url.path=='/api/states':return httpx.Response(200,json=[
            {'entity_id':'switch.socket','state':'off','attributes':{'friendly_name':'Розетка'}},
            {'entity_id':'lock.front_door','state':'locked','attributes':{'secret':'do not leak'}}])
        if request.method=='POST':
            assert request.url.path=='/api/services/switch/turn_on'
            assert json.loads(request.content)=={'entity_id':'switch.socket'}
            state['value']='on';return httpx.Response(200,json=[])
        return httpx.Response(200,json={'entity_id':'switch.socket','state':state['value']})
    service=gateway(tmp_path,handler)
    service.connect('http://192.168.1.2:8123','private-token')
    [device]=service.discover()
    assert not device['allowed'] and 'secret' not in str(device)
    refused=service.command(device['id'],'on')
    assert refused.execution_status=='action_rejected' and not any(method=='POST' for method,_ in calls)
    service.approve(device['id'],True)
    result=service.command(device['id'],'on')
    assert result.success and result.execution_status=='observed' and result.observed_state=='on' and result.mode=='REAL'
    assert calls[-1]==('GET','/api/states/switch.socket')
    assert 'private-token' not in service.path.read_text(encoding='utf-8')
    assert 'private-token' not in str(service.public())


@pytest.mark.parametrize('failure', ['unavailable','rejected','unchanged','network'])
def test_real_failures_never_become_demo_or_success(tmp_path,failure):
    count={'reads':0}
    def handler(request):
        if request.method=='POST':
            if failure=='rejected':return httpx.Response(403,json={'error':'private-token'})
            if failure=='network':raise httpx.ConnectError('private-token')
            return httpx.Response(200,json=[])
        count['reads']+=1
        return httpx.Response(200,json={'entity_id':'light.desk','state':'unavailable' if failure=='unavailable' else 'off'})
    service=gateway(tmp_path,handler);service.origin='http://127.0.0.1:8123';service.token='private-token'
    service.approved={'lamp':{'name':'Лампа','entity_id':'light.desk','domain':'light'}}
    result=service.command('lamp','on')
    assert not result.success and result.mode=='REAL' and 'private-token' not in str(result.to_dict())
    assert result.execution_status=={'unavailable':'unavailable','rejected':'action_rejected','unchanged':'request_accepted','network':'unavailable'}[failure]


def test_controller_change_revokes_entity_grants(tmp_path):
    service=gateway(tmp_path,lambda _:httpx.Response(200,json={'components':[]}))
    service.connect('http://127.0.0.1:8123','private-token')
    service.approved={'old':{'entity_id':'light.desk'}}
    service.connect('http://127.0.0.2:8123','private-token')
    assert service.approved=={}


@pytest.mark.skipif(os.name!='nt',reason='Windows DPAPI only')
def test_windows_dpapi_round_trip_uses_ciphertext():
    from localmind.secret_store import protect,unprotect
    encoded=protect('synthetic-test-token-not-a-real-secret')
    assert 'synthetic' not in encoded
    assert unprotect(encoded)=='synthetic-test-token-not-a-real-secret'


def test_invalid_token_request_is_never_reflected_in_validation_response():
    from fastapi.testclient import TestClient
    from localmind.server import app
    client=TestClient(app,base_url='http://127.0.0.1',client=('127.0.0.1',12))
    response=client.post('/api/home/connect',json={'origin':'http://127.0.0.1:8123','token':{'secret':'never-reflect-this-secret'}})
    assert response.status_code==422 and 'never-reflect' not in response.text


def test_accepted_command_with_failed_read_remains_unverified(tmp_path):
    posted=[]
    def handler(request):
        if request.method=='POST':
            posted.append(True);return httpx.Response(200,json=[])
        if posted:raise httpx.ConnectError('read failed')
        return httpx.Response(200,json={'entity_id':'light.desk','state':'off'})
    service=gateway(tmp_path,handler);service.origin='http://127.0.0.1:8123';service.token='private-token'
    service.approved={'lamp':{'name':'Лампа','entity_id':'light.desk','domain':'light'}}
    result=service.command('lamp','on')
    assert not result.success and result.execution_status=='request_accepted' and result.observed_state is None


def test_explicit_demo_disconnect_drops_token_and_survives_restart(tmp_path):
    service=gateway(tmp_path,lambda _:httpx.Response(200,json={'components':[]}))
    service.connect('http://127.0.0.1:8123','private-token')
    service.disconnect()
    assert service.path.read_text(encoding='utf-8').find('token')==-1
    restored=HomeAssistant(service.path)
    assert restored.demo_requested and not restored.configured and not restored.token


def test_russian_accusative_alias_is_grounded_to_the_named_device():
    from localmind.home_assistant import device_aliases
    assert 'настольную лампу' in device_aliases('Настольная лампа','light.desk')
    assert 'умную розетку' in device_aliases('Умная розетка','switch.socket')
