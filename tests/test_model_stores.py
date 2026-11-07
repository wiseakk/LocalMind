"""Discovery is read-only and does not confuse manifests with a ready engine."""
import hashlib
import json
import os
from unittest.mock import Mock

import httpx
import pytest
from localmind.model_stores import ModelStores, manifest_models


def model(root, name='gemma4', tag='12b'):
    blobs = root / 'blobs'; blobs.mkdir(parents=True, exist_ok=True)
    def layer(content, kind):
        digest = hashlib.sha256(content).hexdigest()
        (blobs / ('sha256-' + digest)).write_bytes(content)
        return {'digest': 'sha256:' + digest, 'size': len(content), 'mediaType': kind}
    config = layer(b'{}', 'application/vnd.docker.container.image.v1+json')
    weight = layer(b'GGUFfixture', 'application/vnd.ollama.image.model')
    path = root / 'manifests/registry.ollama.ai/library' / name / tag
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({'schemaVersion': 2, 'config': config, 'layers': [weight]}))
    return path


def stores(tmp_path, **kw):
    return ModelStores(tmp_path/'local/models/llm', profile=tmp_path/'user', environment={},
                       registry=lambda: None, selection=tmp_path/'private/storage.json', **kw)


def snapshot(root):
    return {str(p.relative_to(root)): (p.read_bytes(), p.stat().st_mtime_ns)
            for p in root.rglob('*') if p.is_file()}


def test_existing_standard_store_wins_over_empty_own_only_after_explicit_choice(tmp_path):
    value = stores(tmp_path)
    root = value.profile/'.ollama/models'; model(root)
    value.owned.mkdir(parents=True)
    before = snapshot(root)
    candidates = value.discover()
    found = next(row for row in candidates if row['count'])
    assert found['models'] == ['gemma4:12b'] and found['requires_generation_check']
    assert value.resolve() is None and not value.selection.exists()
    assert value.select(found['id'], found['fingerprint']) == root
    assert stores(tmp_path).resolve() == root
    assert snapshot(root) == before and not list(value.owned.iterdir())


def test_clean_install_keeps_empty_private_download_wizard(tmp_path):
    value = stores(tmp_path)
    assert value.resolve() == value.owned
    assert value.discover()[0]['count'] == 0
    assert not value.owned.exists() and not value.selection.exists()


@pytest.mark.parametrize('source', ['process', 'registry'])
def test_custom_ollama_models_is_discovered_without_environment_changes(tmp_path, source):
    value = stores(tmp_path); root = tmp_path/'custom'; model(root, 'qwen3', '4b')
    value.environment = {'OLLAMA_MODELS': str(root)} if source == 'process' else {}
    value.registry = lambda: str(root) if source == 'registry' else None
    environment = dict(os.environ)
    found = next(row for row in value.discover() if row['count'])
    assert found['path'] == str(root) and found['models'] == ['qwen3:4b']
    assert dict(os.environ) == environment


def test_incomplete_corrupt_or_linked_models_are_not_offered(tmp_path):
    value = stores(tmp_path); root = value.profile/'.ollama/models'; path = model(root)
    data = json.loads(path.read_text()); data['layers'][0]['size'] += 1
    path.write_text(json.dumps(data))
    assert manifest_models(root) == [] and value.resolve() == value.owned
    path.write_text('null')
    assert manifest_models(root) == []


def test_stale_choice_and_unlisted_paths_cannot_be_selected(tmp_path):
    value = stores(tmp_path); root = value.profile/'.ollama/models'; path = model(root)
    row = next(row for row in value.discover() if row['count'])
    path.write_text('{}')
    with pytest.raises(ValueError): value.select(row['id'], row['fingerprint'])
    with pytest.raises(ValueError): value.select('0'*24, '0'*64)
    assert not value.selection.exists()


def test_missing_saved_store_requires_choice_instead_of_silent_fallback(tmp_path):
    value = stores(tmp_path); value.owned.mkdir(parents=True); value.remember(value.owned)
    value.owned.rmdir()
    assert value.resolve() is None


def test_runtime_waits_for_store_choice_and_reuses_persisted_directory(tmp_path, monkeypatch):
    from localmind import ollama_runtime as engine
    from tests.test_ollama_runtime import Child
    value = engine.OllamaRuntime(tmp_path/'engine', endpoint='http://127.0.0.1:11543',
                                 popen=Mock(return_value=Child()), job_factory=lambda child: Mock())
    value.stores = stores(tmp_path)
    root = value.stores.profile/'.ollama/models'; model(root)
    monkeypatch.setattr(value, 'probe', Mock(side_effect=httpx.ConnectError('offline')))
    monkeypatch.setattr(value, '_occupied', lambda: False)
    executable = Mock(return_value=tmp_path/'engine/ollama.exe')
    monkeypatch.setattr(value, '_executable', executable)
    assert value._ensure() is False
    assert value.status()['state'] == 'storage_choice_required'
    value.popen.assert_not_called(); executable.assert_not_called()
    row = next(row for row in value.model_stores()['candidates'] if row['count'])
    monkeypatch.setattr(value, 'start', lambda: value.status())
    value.select_store(row['id'], row['fingerprint'])
    monkeypatch.setattr(value, 'probe', Mock(side_effect=[httpx.ConnectError('offline'), '0.40.14']))
    monkeypatch.setattr(engine, 'PRIVATE', tmp_path/'private')
    monkeypatch.setattr('localmind.ollama_storage.listener_process', lambda: value.popen.return_value)
    value.stop.clear()
    try:
        assert value._ensure() is True and value.models == root
        environment = value.popen.call_args.kwargs['env']
        assert environment['OLLAMA_MODELS'] == str(root) and environment['OLLAMA_NOPRUNE'] == '1'
        assert stores(tmp_path).resolve() == root
    finally: value.close()


def test_shared_server_precedes_store_discovery_and_cannot_be_reconfigured(tmp_path, monkeypatch):
    from localmind.ollama_runtime import OllamaRuntime
    value = OllamaRuntime(); value.stores = stores(tmp_path)
    model(value.stores.profile/'.ollama/models')
    monkeypatch.setattr(value, 'probe', lambda: '0.40.14')
    spawn = Mock(); value.popen = spawn
    assert value._ensure() is False
    assert not value.model_stores()['choice_required'] and not value.model_stores()['switch_available']
    with pytest.raises(ValueError, match='общий Ollama'): value.select_store('0'*24, '0'*64)
    spawn.assert_not_called()
    assert not value.stores.selection.exists()


def test_saved_missing_model_is_not_reported_as_available(tmp_path, monkeypatch):
    from localmind import model_manager as mm
    manager = mm.ModelManager(tmp_path/'active.json')
    manager._active = 'gemma4:12b'
    monkeypatch.setattr(mm, 'ollama_json', lambda *a, **kw: {'models': []})
    result = manager.inventory()
    assert result['models'] == [] and result['active'] is None and result['default'] is None
    assert result['saved_model'] == 'gemma4:12b'


def test_linked_blob_is_rejected(tmp_path):
    root = tmp_path/'models'; path = model(root)
    data = json.loads(path.read_text())
    blob = root/'blobs'/data['layers'][0]['digest'].replace(':','-')
    target = tmp_path/'outside'; blob.rename(target)
    try: blob.symlink_to(target)
    except OSError: pytest.skip('symlinks require Windows developer mode')
    assert manifest_models(root) == []


def test_storage_selection_rejects_unreviewed_path_and_active_pull(monkeypatch):
    from pydantic import ValidationError
    from fastapi import HTTPException
    from localmind import setup_routes
    from localmind.ollama_runtime import runtime
    from localmind.model_catalog import downloads
    with pytest.raises(ValidationError):
        setup_routes.ModelStoreSelection(store_id='a'*24, fingerprint='b'*64, path='C:/unreviewed')
    select = Mock()
    monkeypatch.setattr(runtime, 'select_store', select)
    monkeypatch.setattr(downloads, 'snapshot', lambda: [{'status': 'downloading'}])
    with pytest.raises(HTTPException) as error:
        setup_routes.select_engine_storage(setup_routes.ModelStoreSelection(store_id='a'*24, fingerprint='b'*64))
    assert error.value.status_code == 409
    select.assert_not_called()
