"""Actual disk persistence and API boundaries, no model or hardware access."""
import importlib
import json
from dataclasses import replace

from fastapi.testclient import TestClient
import pytest

from localmind import paths, product_state, server, setup_routes


@pytest.fixture
def state_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, 'CONFIG', tmp_path / 'config')
    return paths.CONFIG


def test_onboarding_completion_and_optional_skips_survive_reload(state_dir):
    assert product_state.read()['onboarding']['completed'] is False
    product_state.update('onboarding', {'completed': True, 'profile': 'gpu-quality', 'skip_asr': False, 'skip_tts': True})
    importlib.reload(product_state)
    state = product_state.read()
    assert state['onboarding'] == {'completed': True, 'profile': 'gpu-quality', 'skip_asr': False, 'skip_tts': True}
    assert state['tour'] == {'completed': False, 'skipped': False}
    product_state.update('tour', {'skipped': True})
    assert product_state.read()['onboarding']['completed'] is True
    assert product_state.read()['tour']['skipped'] is True


def test_preference_writes_preserve_other_sections_and_are_utf8(state_dir):
    product_state.update('preferences', {'theme': 'light', 'voice_profile': 'gpu-quality', 'speak': True})
    product_state.update('preferences', {'reduce_motion': True})
    product_state.update('onboarding', {'completed': True})
    assert product_state.read()['preferences'] == {'theme': 'light', 'voice_profile': 'gpu-quality', 'speak': True, 'reduce_motion': True}
    assert json.loads((state_dir / 'product-state.json').read_bytes().decode('utf-8'))['version'] == 1
    for section, values in [('preferences', {'key': 'private'}), ('preferences', {'theme': 'invalid'}), ('onboarding', {'completed': 'yes'})]:
        with pytest.raises(ValueError):
            product_state.update(section, values)


def test_corruption_and_failed_replace_do_not_reset_completion(state_dir, monkeypatch):
    product_state.update('onboarding', {'completed': True})
    path = state_dir / 'product-state.json'
    original = path.read_bytes()
    monkeypatch.setattr(paths.os, 'replace', lambda *a: (_ for _ in ()).throw(OSError('disk full')))
    with pytest.raises(OSError):
        product_state.update('onboarding', {'completed': False})
    assert path.read_bytes() == original
    assert not list(state_dir.glob('*.tmp'))
    path.write_text('{broken', encoding='utf-8')
    with pytest.raises(ValueError, match='Исходный файл сохранён'):
        product_state.read()
    assert path.read_text(encoding='utf-8') == '{broken'


def test_completed_setup_independent_of_missing_models_and_auth(state_dir, monkeypatch):
    product_state.update('onboarding', {'completed': True, 'skip_asr': True, 'skip_tts': True})
    monkeypatch.setattr(setup_routes.resource_setup, 'status', lambda: [{'kind': 'asr', 'state': 'model_missing'}])
    monkeypatch.setattr(setup_routes, 'ollama_json', lambda *a: {'models': [{'name': 'gemma4:12b'}]})
    monkeypatch.setattr(server, 'settings', replace(server.settings, key='test-private'))
    client = TestClient(server.app, base_url='http://127.0.0.1', client=('127.0.0.1', 123))
    assert client.get('/api/setup').status_code == 401
    h = {'X-LocalMind-Key': 'test-private'}
    data = client.get('/api/setup', headers=h).json()
    assert data['onboarding']['completed'] is True
    assert data['voice'][0]['state'] == 'model_missing'
    assert 'gemma4:12b' in data['ollama']['installed']
    assert client.post('/api/setup/preferences', json={'permissions': True}, headers=h).status_code == 422
    assert client.post('/api/setup/preferences', json={'theme': 'light'}, headers=h).status_code == 200
    assert client.get('/api/setup/preferences', headers=h).json()['preferences']['theme'] == 'light'
    assert client.post('/api/setup/tour', json={'completed': True}, headers=h).status_code == 200
    assert client.get('/api/setup/preferences', headers=h).json()['onboarding']['completed'] is True
