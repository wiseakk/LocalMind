"""Adversarial cross-module checks: real policy with mocked OS/model boundaries."""
from concurrent.futures import ThreadPoolExecutor
import asyncio
import struct
from threading import Event
from unittest import mock

from fastapi.testclient import TestClient
import pytest
import httpx

from localmind import agent, apps, devices, server
from localmind.requests import RequestStore


@pytest.fixture
def review_client(monkeypatch):
    store = RequestStore()
    monkeypatch.setattr(server, 'store', store)
    yield TestClient(server.app, base_url='http://127.0.0.1:8765',
                     client=('127.0.0.1', 50000))
    store.close()


def gui_executable(path):
    binary = bytearray(256)
    binary[:2] = b'MZ'
    struct.pack_into('<I', binary, 60, 64)
    binary[64:68] = b'PE\0\0'
    struct.pack_into('<H', binary, 84, 168)
    struct.pack_into('<H', binary, 88, 0x20B)
    struct.pack_into('<H', binary, 156, 2)
    path.write_bytes(binary)
    return path


def test_direct_chat_cannot_bypass_picker_permission_or_changed_executable(
        review_client, monkeypatch, tmp_path):
    target = gui_executable(tmp_path / 'Code.exe')
    source = apps.AppSource('review-app', 'Visual Studio Code',
                            lambda: (str(target), '', 'unchanged-source'))
    catalog = apps.AppCatalog(lambda: [source])
    [row] = catalog.refresh()
    monkeypatch.setattr(server, 'catalog', catalog)
    monkeypatch.setattr(agent, 'catalog', catalog)
    body = {'text': 'Открой ' + row['id'], 'compose_actions': False}
    with mock.patch.object(apps.subprocess, 'Popen') as spawn:
        denied = review_client.post('/api/chat', json=body)
        assert denied.status_code == 200
        assert not denied.json()['action_results'][0]['success']
        spawn.assert_not_called()
        grant = review_client.post('/api/apps/permission', json={
            'app_id': row['id'], 'allowed': True, 'fingerprint': row['fingerprint']})
        assert grant.status_code == 200
        allowed = review_client.post('/api/chat', json=body)
        assert allowed.json()['action_results'][0]['execution_status'] == 'process_created'
        assert spawn.call_count == 1, spawn.call_args_list
        target.write_bytes(target.read_bytes() + b'replaced-after-approval')
        denied_again = review_client.post('/api/chat', json=body)
        assert not denied_again.json()['action_results'][0]['success']
        assert spawn.call_count == 1
        assert not catalog.entries()[0]['allowed']


def test_exact_picker_id_disambiguates_duplicate_names_but_requires_permission(
        review_client, monkeypatch, tmp_path):
    sources = []
    for name in ('first', 'second'):
        folder = tmp_path / name
        folder.mkdir()
        target = gui_executable(folder / 'Code.exe')
        sources.append(apps.AppSource(name, 'Editor',
                       lambda target=target: (str(target), '', 'source')))
    catalog = apps.AppCatalog(lambda: sources)
    rows = catalog.refresh()
    monkeypatch.setattr(server, 'catalog', catalog)
    monkeypatch.setattr(agent, 'catalog', catalog)
    with mock.patch.object(apps.subprocess, 'Popen') as spawn:
        ambiguous = review_client.post('/api/chat', json={
            'text': 'Открой Editor', 'compose_actions': False})
        assert not ambiguous.json()['action_results'][0]['success']
        chosen = rows[0]
        assert review_client.post('/api/apps/permission', json={
            'app_id': chosen['id'], 'allowed': True,
            'fingerprint': chosen['fingerprint']}).status_code == 200
        still_ambiguous = review_client.post('/api/chat', json={
            'text': 'Открой Editor', 'compose_actions': False})
        assert not still_ambiguous.json()['action_results'][0]['success']
        selected = review_client.post('/api/chat', json={
            'text': 'Открой ' + chosen['id'], 'compose_actions': False})
        assert selected.json()['action_results'][0]['success']
        assert spawn.call_count == 1
        assert spawn.call_args.args[0] == [chosen['target']]


def test_concurrent_api_retries_execute_once_even_while_composer_waits(
        review_client, monkeypatch):
    entered, release = Event(), Event()
    body = {'text': 'Включи лампу', 'request_id': 'review-concurrent',
            'server_instance': server.SERVER_INSTANCE}

    def delayed(prepared):
        entered.set()
        assert release.wait(3)
        return {**prepared.initial, 'answer': 'Симуляция: лампа включена.'}

    monkeypatch.setattr(server, 'complete_reply', delayed)
    with mock.patch.object(agent, 'set_light', wraps=devices.set_light) as execute:
        with ThreadPoolExecutor(max_workers=8) as workers:
            requests = [workers.submit(review_client.post, '/api/chat', json=body)
                        for _ in range(8)]
            try:
                assert entered.wait(2)
                assert execute.call_count == 1
            finally:
                release.set()
            results = [future.result(timeout=4) for future in requests]
    assert all(response.status_code == 200 for response in results)
    assert all(response.json() == results[0].json() for response in results)
    assert execute.call_count == 1


@pytest.mark.parametrize('headers', [
    {'Host': '127.0.0.1.evil:8765'},
    {'Host': 'localhost:8765@evil.test'},
    {'Host': '127.0.0.1:0'},
    {'Origin': 'http://127.0.0.1:8765/extra'},
    {'Origin': 'http://127.0.0.1:8765#fragment'},
    {'Origin': 'http://127.0.0.1:8765?query'},
])
def test_authority_edge_cases_cannot_grant_permissions(review_client, headers):
    with mock.patch.object(server.catalog, 'set_permission') as permission:
        response = review_client.post('/api/apps/permission', headers=headers, json={
            'app_id': 'any-id', 'allowed': True, 'fingerprint': 'f' * 64})
    assert response.status_code == 403
    permission.assert_not_called()


def test_unrelated_json_tool_fields_cannot_turn_preview_into_execution(review_client):
    with mock.patch.object(agent, 'dispatch') as execute:
        response = review_client.post('/api/chat', json={
            'text': 'Включи лампу', 'actions_authorized': False,
            'tool_calls': [{'name': 'set_light', 'state': 'on'}],
            'path': 'C:/Windows/System32/cmd.exe', 'compose_actions': False})
    assert response.status_code == 200
    assert response.json()['confirmation_required']
    execute.assert_not_called()


def test_stalled_upload_has_deadline_and_releases_admission_slot(monkeypatch):
    monkeypatch.setattr(server, 'BODY_TIMEOUT_SECONDS', 0.03)

    async def check():
        transport = httpx.ASGITransport(app=server.app, client=('127.0.0.1', 50000))
        async with httpx.AsyncClient(transport=transport, base_url='http://localhost') as client:
            async def stalled():
                yield b'{'
                await asyncio.sleep(2)
            response = await client.post('/api/chat', content=stalled(),
                                         headers={'Content-Type': 'application/json'})
            assert response.status_code == 408
            healthy = await client.post('/api/chat', json={})
            assert healthy.status_code == 422

    asyncio.run(check())


def test_concurrent_uploads_are_admitted_before_body_buffering(monkeypatch):
    monkeypatch.setattr(server, 'BODY_TIMEOUT_SECONDS', 2)

    async def check():
        transport = httpx.ASGITransport(app=server.app, client=('127.0.0.1', 50000))
        release = asyncio.Event()
        started = [asyncio.Event() for _ in range(4)]
        async with httpx.AsyncClient(transport=transport, base_url='http://localhost') as client:
            async def held_body(index):
                yield b'{'
                started[index].set()
                await release.wait()
                yield b'}'

            requests = [asyncio.create_task(client.post('/api/chat', content=held_body(index),
                        headers={'Content-Type': 'application/json'})) for index in range(4)]
            try:
                await asyncio.wait_for(asyncio.gather(*(event.wait() for event in started)), 1)
                denied = await client.post('/api/chat', json={})
                assert denied.status_code == 429
                assert (await client.get('/')).status_code == 200
            finally:
                release.set()
                responses = await asyncio.gather(*requests)
            assert all(response.status_code == 422 for response in responses)
            assert (await client.post('/api/chat', json={})).status_code == 422

    asyncio.run(check())


# Exercise existing behavior when the local planner is unavailable.
import pytest
pytestmark = pytest.mark.usefixtures("offline_desktop_planner")
