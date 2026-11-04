"""Owned offline-import lifetime tests use fake loopback HTTP, never Ollama."""
import hashlib
import threading
import time
from types import SimpleNamespace

import httpx
import pytest

from localmind import offline_model as module
from localmind.download_store import JobStore


@pytest.fixture
def offline_state(tmp_path, monkeypatch):
    content = b'GGUF' + b'x' * 1_000_000
    (tmp_path / 'offline-llm').mkdir()
    (tmp_path / 'offline-llm/model.gguf').write_bytes(content)
    data = {'model': 'localmind-offline:1.0', 'bytes': len(content),
            'sha256': hashlib.sha256(content).hexdigest(), 'license': 'apache-2.0'}
    monkeypatch.setattr(module, 'APP_ROOT', tmp_path)
    monkeypatch.setattr(module, 'store', JobStore())
    monkeypatch.setattr(module, 'manifest', lambda: data)
    monkeypatch.setattr(module, '_closing', False)
    for name in ('_controls', '_sources', '_threads'):
        monkeypatch.setattr(module, name, {})
    monkeypatch.setattr('localmind.model_catalog.disk_status', lambda: {'free': 10 * 1024**3, 'path': 'verified'})
    yield data
    module.stop_all()


def test_shutdown_closes_blocked_import_http_and_joins_owned_thread(offline_state, monkeypatch):
    entered, closed = threading.Event(), threading.Event()
    clients = []
    class Client:
        def __init__(self, **options):
            clients.append((self, options))
        def __enter__(self):
            return self
        def __exit__(self, *args):
            self.close()
        def close(self):
            closed.set()
        def head(self, url):
            entered.set()
            assert closed.wait(2)
            raise httpx.ReadError('Owned connection closed')
        def stream(self, *args, **kwargs):
            pytest.fail('A cancelled import must not upload or create a model')
    monkeypatch.setattr(module.httpx, 'Client', Client)
    job = module.start(True)
    assert entered.wait(1)
    owned = list(module._threads.values())
    started = time.monotonic()
    module.stop_all()
    assert time.monotonic() - started < 1
    assert closed.is_set() and all(not thread.is_alive() for thread in owned)
    assert not module._threads and not module._controls and not module._sources
    assert module.store.snapshot(job['id'])['status'] == 'cancelled_unverified'
    assert clients[0][1]['trust_env'] is False and clients[0][1]['follow_redirects'] is False
    assert clients[0][1]['timeout'].read == clients[0][1]['timeout'].write == 5
    with pytest.raises(ValueError, match='завершает работу'):
        module.start(True)
    module.reopen()
    assert not module._closing


def test_shutdown_cancels_hash_between_buffers_before_any_http(offline_state, monkeypatch):
    entered = threading.Event()
    original_digest = module.hashlib.file_digest
    def digest(stream, name):
        entered.set()
        assert stream.event.wait(2)
        return original_digest(stream, name)
    monkeypatch.setattr(module.hashlib, 'file_digest', digest)
    monkeypatch.setattr(module.httpx, 'Client', lambda **kw: pytest.fail('No HTTP after hash cancellation'))
    job = module.start(True)
    assert entered.wait(1)
    owned = list(module._threads.values())
    module.stop_all()
    assert all(not thread.is_alive() for thread in owned)
    assert module.store.snapshot(job['id'])['status'] == 'cancelled_unverified'
    assert not module._controls and not module._sources


def test_reopen_rejects_still_owned_import_thread(offline_state):
    module._threads['busy'] = SimpleNamespace(is_alive=lambda: True, join=lambda **kw: None)
    try:
        with pytest.raises(ValueError, match='ещё завершает'):
            module.reopen()
    finally:
        module._threads.clear()


def test_failed_import_thread_start_releases_controls_and_job_admission(offline_state, monkeypatch):
    class FailedThread:
        def __init__(self, **kwargs):
            pass
        def start(self):
            raise RuntimeError('No worker available')
    monkeypatch.setattr(module.threading, 'Thread', FailedThread)
    with pytest.raises(ValueError, match='Не удалось начать'):
        module.start(True)
    assert not module._controls and not module._threads
    assert module.store.snapshot()[0]['status'] == 'failed'


def test_offline_failure_on_full_journal_does_not_leave_active_job(offline_state, monkeypatch):
    journal = module.store
    journal.insert({'id': 'disk-full', 'kind': 'llm_offline', 'status': 'starting'})
    monkeypatch.setattr(journal, 'save', lambda: (_ for _ in ()).throw(OSError(28, 'No space left on device')))
    event = threading.Event()
    event.set()
    module._controls['disk-full'] = event
    module._import('disk-full', offline_state, event)
    state = journal.snapshot('disk-full')
    assert state['status'] == 'failed' and state['persistence_error']
    assert not module._controls
