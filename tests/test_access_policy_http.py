"""Strict authenticated access policy endpoints; no native app execution."""
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from localmind import server
from localmind.apps import AppCatalog
from localmind.file_access import FileAccess
from localmind.personal_permissions import FILE_OPERATIONS


@pytest.fixture
def policy_client(tmp_path, monkeypatch):
    root = tmp_path / 'documents'
    root.mkdir()
    access = FileAccess(lambda: root)
    access.personal_mode.root_provider = lambda: [str(root)]
    catalog = AppCatalog(lambda: [], policy=access.personal_mode)
    catalog.refresh()
    monkeypatch.setattr(server, 'file_access', access)
    monkeypatch.setattr(server, 'catalog', catalog)
    monkeypatch.setattr(server, 'settings', SimpleNamespace(key='fixture-policy-key'))
    client = TestClient(server.app, base_url='http://127.0.0.1', client=('127.0.0.1', 12345))
    client.headers['X-LocalMind-Key'] = 'fixture-policy-key'
    return client, access, root


def credentials(client):
    result = client.get('/api/access-policy')
    assert result.status_code == 200
    return {key: result.json()[key] for key in ('revision', 'server_instance')}


def test_action_paths_and_denials_require_settings_auth(policy_client):
    client, _, _ = policy_client
    assert client.get('/api/actions').status_code == 200
    client.headers.pop('X-LocalMind-Key')
    assert client.get('/api/actions').status_code == 401


def enable(client, root, mode='restricted'):
    result = client.post('/api/access-policy', json={**credentials(client), 'mode': mode,
        'roots': [str(root)] if mode == 'restricted' else [], 'operations': sorted(FILE_OPERATIONS)})
    assert result.status_code == 200, result.text
    return result.json()


def test_policy_api_requires_authentication_before_processing(policy_client):
    client, _, root = policy_client
    good = credentials(client)
    client.headers.pop('X-LocalMind-Key')
    assert client.get('/api/access-policy').status_code == 401
    assert client.post('/api/access-policy', json={**good, 'mode': 'full_user',
        'roots': [], 'operations': []}).status_code == 401
    assert client.post('/api/access-policy/preview', json={**good,
        'text': 'Не трогай папку Загрузки'}).status_code == 401


def test_policy_api_explicit_full_and_stale_revision_are_distinct(policy_client):
    client, access, root = policy_client
    before = credentials(client)
    result = enable(client, root, 'full_user')
    assert result['mode'] == 'full_user'
    assert result['revision'] != before['revision']
    stale = client.post('/api/access-policy', json={**before, 'mode': 'restricted',
        'roots': [], 'operations': []})
    assert stale.status_code == 409
    assert access.personal_info()['mode'] == 'full_user'
    restarted = client.post('/api/access-policy', json={**credentials(client),
        'server_instance': '0' * 32, 'mode': 'restricted', 'roots': [], 'operations': []})
    assert restarted.status_code == 409
    assert access.personal_info()['mode'] == 'full_user'


@pytest.mark.parametrize('extra', [
    {'mode': 'admin'}, {'operations': ['execute']}, {'operations': 'read'},
    {'roots': 'C:\\'}, {'allow_shell': True}, {'rules': [{'effect': 'allow'}]},
])
def test_policy_schema_rejects_unknown_operations_raw_grants_and_extra_fields(policy_client, extra):
    client, access, root = policy_client
    body = {**credentials(client), 'mode': 'restricted', 'roots': [str(root)], 'operations': ['read'], **extra}
    result = client.post('/api/access-policy', json=body)
    assert result.status_code == 422
    assert access.personal_info()['roots'] == []


def test_rule_http_preview_cancel_clarify_apply_and_stale_draft(policy_client):
    client, access, root = policy_client
    enable(client, root)
    revision = credentials(client)
    draft = client.post('/api/access-policy/preview', json={**revision,
        'text': 'Не трогай папку Загрузки'})
    assert draft.status_code == 200 and draft.json()['draft_id']
    assert access.personal_info()['rules'] == []
    assert access.personal_mode.allows(root / 'ordinary.txt', 'read')
    # Cancellation is local and never sends apply; merely creating a second
    # preview must not apply any part of the first one.
    unclear = client.post('/api/access-policy/preview', json={**revision,
        'text': 'Разрешаю редактировать документы, но запрещаю удалять их'})
    assert unclear.status_code == 200
    assert unclear.json()['clarification'] and not unclear.json()['draft_id']
    assert access.personal_info()['rules'] == []
    result = client.post('/api/access-policy/apply', json={**revision,
        'draft_id': draft.json()['draft_id']})
    assert result.status_code == 200 and result.json()['rules']
    assert not access.personal_mode.allows(root / 'ordinary.txt', 'read')
    replay = client.post('/api/access-policy/apply', json={**credentials(client),
        'draft_id': draft.json()['draft_id']})
    assert replay.status_code == 409


def test_old_personal_endpoint_cannot_enable_full_mode(policy_client):
    client, access, root = policy_client
    enable(client, root, 'full_user')
    result = client.post('/api/permissions/personal', json={
        'server_instance': server.SERVER_INSTANCE, 'enabled': True, 'roots': [str(root)]})
    assert result.status_code == 200
    assert result.json()['mode'] == 'restricted'
    assert access.personal_info()['mode'] == 'restricted'


def test_rule_http_rejects_arbitrary_structured_policy_and_forged_draft(policy_client):
    client, access, root = policy_client
    enable(client, root)
    result = client.post('/api/access-policy/preview', json={**credentials(client),
        'text': 'Не трогай папку Загрузки', 'rules': [{'effect': 'allow', 'operations': ['execute']}]})
    assert result.status_code == 422
    forged = client.post('/api/access-policy/apply', json={**credentials(client), 'draft_id': 'a' * 32})
    assert forged.status_code == 409
    assert access.personal_info()['rules'] == []


def test_policy_http_audit_write_failure_does_not_claim_settings_rolled_back(policy_client, tmp_path, monkeypatch):
    from localmind.action_journal import journal
    client, access, root = policy_client
    access.personal_mode.persistence = tmp_path / 'policy.json'
    def audit_failure(*_, **__):
        raise OSError('fixture audit disk failure')
    monkeypatch.setattr(journal, 'record', audit_failure)
    result = enable(client, root, 'full_user')
    assert result['mode'] == 'full_user' and result['audit_warning']
    assert result['error'] is None
    assert access.personal_mode.persistence.exists()
    assert client.get('/api/access-policy').json()['audit_warning']
