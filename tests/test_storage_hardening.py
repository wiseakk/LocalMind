import json
import os
from pathlib import Path
from threading import Event
from concurrent.futures import ThreadPoolExecutor

import pytest
import httpx
from localmind import paths, storage, model_memory as mem, model_manager as mm, ollama_storage


@pytest.fixture
def storage_roots(tmp_path, monkeypatch):
    source, target = tmp_path / 'данные старые', tmp_path / 'новые данные'
    source.mkdir()
    (source / 'config').mkdir()
    (source / 'models').mkdir()
    (source / 'config/preferences.json').write_text('{"model":"gemma4:12b"}', encoding='utf-8')
    (source / 'models/model.bin').write_bytes(b'model bytes')
    monkeypatch.setattr(paths, 'DATA_ROOT', source)
    monkeypatch.setattr(paths, 'APP_ROOT', tmp_path / 'application')
    monkeypatch.setattr(paths, 'DEFAULT_ROOT', tmp_path / 'bootstrap')
    monkeypatch.setattr(paths, 'LOCATION_FILE', tmp_path / 'bootstrap/config/storage-location.json')
    monkeypatch.setattr(storage, '_plans', {})
    monkeypatch.setattr(storage, '_pending_root', None)
    from localmind.download_store import store
    monkeypatch.setattr(store, 'snapshot', lambda: [])
    return source, target


def test_root_priority_explicit_saved_default(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, 'DEFAULT_ROOT', tmp_path / 'default')
    monkeypatch.setattr(paths, 'APP_ROOT', tmp_path / 'app')
    monkeypatch.setattr(paths, 'LOCATION_FILE', tmp_path / 'bootstrap/pointer.json')
    monkeypatch.delenv('LOCALMIND_DATA_DIR', raising=False)
    assert paths.resolve_data_root() == (tmp_path / 'default').resolve()
    paths.atomic_json(paths.LOCATION_FILE, {'data_root': str(tmp_path / 'saved')})
    assert paths.resolve_data_root() == tmp_path / 'saved'
    monkeypatch.setenv('LOCALMIND_DATA_DIR', str(tmp_path / 'explicit'))
    assert paths.resolve_data_root() == tmp_path / 'explicit'


def test_saved_root_cannot_point_into_installation(tmp_path, monkeypatch):
    monkeypatch.delenv('LOCALMIND_DATA_DIR', raising=False)
    monkeypatch.setattr(paths, 'APP_ROOT', tmp_path / 'installed')
    monkeypatch.setattr(paths, 'LOCATION_FILE', tmp_path / 'pointer.json')
    paths.atomic_json(paths.LOCATION_FILE, {'data_root': str(paths.APP_ROOT / 'dist/data')})
    with pytest.raises(RuntimeError):
        paths.resolve_data_root()


def test_copy_requires_consent_verifies_bytes_and_preserves_source(storage_roots):
    source, target = storage_roots
    planned = storage.plan(str(target))
    assert planned['bytes'] > 0 and planned['free_bytes'] > planned['required_bytes']
    assert not target.exists()
    with pytest.raises(ValueError):
        storage.apply(planned['id'])
    result = storage.apply(planned['id'], True)
    assert result['state'] == 'copied_verified' and result['source_preserved']
    assert storage.files(source) == storage.files(target)
    assert json.loads(paths.LOCATION_FILE.read_text(encoding='utf-8'))['data_root'] == str(target)


def test_changed_data_invalidates_reviewed_plan(storage_roots):
    source, target = storage_roots
    planned = storage.plan(str(target))
    (source / 'config/preferences.json').write_text('changed')
    with pytest.raises(ValueError, match='изменились'):
        storage.apply(planned['id'], True)
    assert not paths.LOCATION_FILE.exists()


def test_conflict_is_not_overwritten_and_identical_copy_is_resumable(storage_roots):
    source, target = storage_roots
    (target / 'models').mkdir(parents=True)
    (target / 'models/model.bin').write_bytes(b'conflict')
    with pytest.raises(ValueError, match='Конфликт'):
        storage.plan(str(target))
    assert (target / 'models/model.bin').read_bytes() == b'conflict'
    (target / 'models/model.bin').write_bytes(b'model bytes')
    planned = storage.plan(str(target))
    assert planned['required_bytes'] < planned['bytes']
    storage.apply(planned['id'], True)
    assert storage.files(source) == storage.files(target)


def test_known_shortfall_blocks_plan(storage_roots, monkeypatch):
    _, target = storage_roots
    monkeypatch.setattr(storage, 'free_space', lambda _: 0)
    with pytest.raises(ValueError, match='Недостаточно'):
        storage.plan(str(target))


def test_bootstrap_and_pending_root_excluded_from_personal_files(storage_roots):
    _, target = storage_roots
    from localmind.personal_permissions import ordinary_path
    storage.plan(str(target))
    assert not ordinary_path(paths.LOCATION_FILE)
    assert not ordinary_path(target / 'config/policy.json')


def test_no_implicit_asset_migration(storage_roots):
    source, target = storage_roots
    paths.migrate_legacy(source, target)
    assert not (target / 'models/model.bin').exists()


def test_model_lease_cleared_on_exception(tmp_path):
    memory = mem.ModelMemory(tmp_path / 'retention.json')
    with pytest.raises(RuntimeError), memory.using('test:4b'):
        assert memory.status()['being_used'] == {'test:4b': 1}
        raise RuntimeError('cancelled')
    assert memory.status()['being_used'] == {}


def test_shared_server_cleanup_skips_without_network_mutation(tmp_path, monkeypatch):
    memory = mem.ModelMemory(tmp_path / 'retention.json')
    monkeypatch.setattr(ollama_storage, 'exclusive_managed', lambda: False)
    monkeypatch.setattr(mm, 'ollama_json', lambda *a, **k: pytest.fail('Shared server must not be touched'))
    assert memory.cleanup('temporary:1b')['state'] == 'skipped'


def test_unload_verified_and_never_deletes_model(tmp_path, monkeypatch):
    memory = mem.ModelMemory(tmp_path / 'retention.json')
    calls=[]
    def api(method, endpoint, body=None, **kw):
        calls.append((method, endpoint, body))
        if endpoint == 'tags': return {'models': [{'name': 'test:4b'}]}
        if endpoint == 'generate': return {'done': True}
        if endpoint == 'ps': return {'models': []}
        pytest.fail(endpoint)
    monkeypatch.setattr(mm, 'ollama_json', api)
    assert memory.cleanup('test:4b', user_confirmed=True)['state'] == 'unloaded_verified'
    assert ('POST', 'generate', {'model': 'test:4b', 'stream': False, 'keep_alive': 0}) in calls
    assert all(method != 'DELETE' for method, _, _ in calls)


def test_unload_failed_verification_is_not_success(tmp_path, monkeypatch):
    memory = mem.ModelMemory(tmp_path / 'retention.json')
    def api(method, endpoint, body=None, **kw):
        if endpoint == 'generate': return {'done': True}
        return {'models': [{'name': 'test:4b'}]}
    monkeypatch.setattr(mm, 'ollama_json', api)
    assert memory.cleanup('test:4b', user_confirmed=True)['state'] == 'unverified'


def test_active_and_in_use_models_never_unloaded(tmp_path, monkeypatch):
    memory = mem.ModelMemory(tmp_path / 'retention.json')
    monkeypatch.setattr(mm, 'ollama_json', lambda *a, **kw: pytest.fail('must preserve'))
    assert memory.cleanup(mm.manager.active, user_confirmed=True)['state'] == 'skipped'
    with memory.using('test:4b'):
        assert memory._cleanup_locked('test:4b', user_confirmed=True)['state'] == 'skipped'


def test_retention_and_gemma_controls_persist_without_changing_selection(tmp_path):
    memory = mem.ModelMemory(tmp_path / 'retention.json')
    memory.configure(keep_alive_seconds=60, cleanup_temporary=False, unload_previous=True)
    assert mem.ModelMemory(memory.path).policy.keep_alive_seconds == 60
    active = tmp_path / 'active.json'
    paths.atomic_json(active, {'model': 'gemma4:12b'})
    manager = mm.ModelManager(active)
    saved = manager.save_generation({'reasoning':'auto','context_tokens':8192,'response_tokens':1536,'keep_alive_seconds':900})
    restored = mm.ModelManager(active)
    assert restored.active == 'gemma4:12b' and restored.generation() == saved


def test_storage_observes_server_environment_not_client(tmp_path, monkeypatch):
    class Process:
        pid = 42
        def environ(self): return {'OLLAMA_MODELS': str(tmp_path / 'actual')}
    monkeypatch.setenv('OLLAMA_MODELS', str(tmp_path / 'wrong-client'))
    monkeypatch.setattr(ollama_storage, 'listener_process', lambda: Process())
    observed = ollama_storage.storage_status()
    assert observed['confirmed'] and observed['path'] == str(tmp_path / 'actual')
    monkeypatch.setattr(ollama_storage, 'listener_process', lambda: None)
    assert not ollama_storage.storage_status()['confirmed']


def test_bad_generation_mapping_does_not_break_valid_selection(tmp_path):
    path = tmp_path / 'active.json'
    paths.atomic_json(path, {'model': 'gemma4:12b', 'generation': []})
    assert mm.ModelManager(path).active == 'gemma4:12b'


def test_stale_generation_save_rejected_after_selection_changed(tmp_path):
    path = tmp_path / 'active.json'
    paths.atomic_json(path, {'model': 'gemma4:12b'})
    manager = mm.ModelManager(path)
    with pytest.raises(ValueError, match='изменилась'):
        manager.save_generation({'context_tokens': 8192}, expected_model='old:4b')
    assert manager.generation() is None


def test_mutations_cannot_start_during_migration_or_before_restart(storage_roots):
    _, target = storage_roots
    with storage.migration_guard():
        with pytest.raises(ValueError):
            storage.begin_mutation()
    storage.begin_mutation()
    try:
        with pytest.raises(ValueError), storage.migration_guard():
            pytest.fail('must not begin migration while changing settings')
    finally:
        storage.end_mutation()
    reviewed = storage.plan(str(target))
    storage.apply(reviewed['id'], True)
    with pytest.raises(ValueError):
        storage.begin_mutation()


def test_ollama_copy_does_not_change_root_or_server_settings(storage_roots, monkeypatch):
    source, target = storage_roots
    monkeypatch.setattr(ollama_storage, 'storage_status', lambda: {'confirmed': True, 'path': str(source)})
    reviewed = storage.plan(str(target), 'ollama_models')
    result = storage.apply(reviewed['id'], True)
    assert not result['restart_required'] and storage.files(source) == storage.files(target)
    assert not paths.LOCATION_FILE.exists()
    assert storage._pending_root is None


def test_reparse_point_rejected_before_directory_walk(tmp_path, monkeypatch):
    source = tmp_path / 'source'
    child = source / 'junction'; child.mkdir(parents=True)
    original = paths.ordinary_tree
    def guard(path):
        if Path(path) == child:
            raise ValueError('reparse')
        return original(path)
    monkeypatch.setattr(paths, 'ordinary_tree', guard)
    with pytest.raises(ValueError, match='reparse'):
        storage.files(source)


def test_case_insensitive_server_environment_on_windows(tmp_path, monkeypatch):
    if os.name != 'nt':
        pytest.skip('Windows environment semantics')
    class Process:
        pid = 42
        def environ(self): return {'ollama_models': str(tmp_path / 'actual')}
    monkeypatch.setattr(ollama_storage, 'listener_process', lambda: Process())
    assert ollama_storage.storage_status()['path'] == str(tmp_path / 'actual')


@pytest.mark.parametrize('rows', [[None], [{}], [{'name': None}], 'malformed'])
def test_malformed_loaded_list_is_not_proof_of_unload(tmp_path, monkeypatch, rows):
    memory = mem.ModelMemory(tmp_path / 'retention.json')
    def api(method, endpoint, body=None, **kw):
        if endpoint == 'generate': return {'done': True}
        if endpoint == 'ps': return {'models': rows}
        return {'models': [{'name': 'test:4b'}]}
    monkeypatch.setattr(mm, 'ollama_json', api)
    assert memory.cleanup('test:4b', user_confirmed=True)['state'] == 'unverified'


def test_request_finish_turn_blocks_migration_even_after_final_future(storage_roots, monkeypatch):
    from localmind import server
    _, target = storage_roots
    reviewed = storage.plan(str(target))
    monkeypatch.setattr(server.store, 'running', lambda: True)
    with pytest.raises(ValueError, match='завершения ответа'):
        storage.apply(reviewed['id'], True)
    assert not paths.LOCATION_FILE.exists() and not storage._migrating


def test_dangling_reparse_detection_uses_lstat_without_exists():
    from types import SimpleNamespace
    class DanglingJunction:
        def is_symlink(self): return False
        def lstat(self): return SimpleNamespace(st_file_attributes=0x400)
        def exists(self): pytest.fail('exists follows a broken junction target')
    assert paths._linked(DanglingJunction())


def test_preexisting_dangling_link_cannot_become_saved_root(tmp_path, monkeypatch):
    monkeypatch.delenv('LOCALMIND_DATA_DIR', raising=False)
    monkeypatch.setattr(paths, 'LOCATION_FILE', tmp_path / 'pointer.json')
    linked = tmp_path / 'broken'
    paths.atomic_json(paths.LOCATION_FILE, {'data_root': str(linked / 'data')})
    original = paths._linked
    monkeypatch.setattr(paths, '_linked', lambda p: p == linked or original(p))
    with pytest.raises(RuntimeError, match='ссылку'):
        paths.resolve_data_root()
