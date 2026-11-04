"""Owned-process shutdown under blocked work; no microphone/model required."""
import hashlib
import io
import threading
import time
from types import SimpleNamespace

import pytest

from localmind import resource_setup, speech_worker, voice
from localmind.download_store import JobStore
from localmind.generation import cancellation
from localmind.requests import RequestStore, RequestBusy


@pytest.mark.parametrize('kind', ['stt', 'tts'])
def test_close_interrupts_blocked_inference_before_waiting_for_admission(monkeypatch, kind):
    if kind == 'stt':
        from tests.test_asr_worker import fake_worker
        worker, calls = fake_worker(monkeypatch)
        invoke = lambda: worker.transcribe(b'x' * 128, '.wav', 'balanced', 'baseline')
    else:
        from tests.test_speech_pipeline import fake_worker
        worker, calls = fake_worker(monkeypatch)
        invoke = lambda: worker.synthesize('Проверка.', voice.DEFAULT_VOICE)
    invoke()  # Idle resident child before a second, intentionally hung request.
    entered = threading.Event()
    errors = []
    monkeypatch.setattr(worker, '_send', lambda frame: entered.set())
    if kind == 'tts':
        monkeypatch.setattr(worker, '_receive', lambda: speech_worker.WarmSpeechWorker._receive(worker))
    def run():
        try:
            invoke()
        except speech_worker.SpeechWorkerError as exc:
            errors.append(str(exc))
    request = threading.Thread(target=run)
    request.start()
    assert entered.wait(1)
    started = time.monotonic()
    worker.close()
    request.join(timeout=1)
    assert time.monotonic() - started < 1
    assert not request.is_alive() and errors
    assert calls[0][2].killed and worker.process is None
    worker.close()  # Idempotent; shutdown cannot respawn a worker.
    with pytest.raises(speech_worker.SpeechWorkerError, match='cancelled'):
        invoke()
    assert len(calls) == 1
    worker.reopen()
    assert not worker.closing
    worker.close()


def test_close_interrupts_a_blocked_worker_pipe_write(monkeypatch):
    from tests.test_speech_pipeline import fake_worker
    worker, calls = fake_worker(monkeypatch)
    worker.synthesize('Прогрев.', voice.DEFAULT_VOICE)
    process = worker.process
    entered, killed = threading.Event(), threading.Event()
    errors = []
    class Pipe:
        def write(self, frame):
            entered.set()
            assert killed.wait(2)
            raise BrokenPipeError()
        def close(self): pass
    process.stdin = Pipe()
    original_kill = process.kill
    def kill():
        original_kill()
        killed.set()
    process.kill = kill
    def run():
        try:
            worker.synthesize('Зависшая запись.', voice.DEFAULT_VOICE)
        except speech_worker.SpeechWorkerError as exc:
            errors.append(str(exc))
    request = threading.Thread(target=run)
    request.start()
    assert entered.wait(1)
    worker.close()
    request.join(timeout=1)
    assert not request.is_alive() and errors
    assert worker.writer is None and worker.process is None
    assert len(calls) == 1


@pytest.fixture
def setup_state(monkeypatch):
    for name in ('_controls', '_threads', '_probes', '_sources'):
        monkeypatch.setattr(resource_setup, name, {})
    monkeypatch.setattr(resource_setup, '_closing', False)
    monkeypatch.setattr(resource_setup, 'store', JobStore())
    monkeypatch.setattr(resource_setup, 'dependencies', lambda _: True)


def test_setup_shutdown_reaps_owned_probe_and_rejects_late_start(monkeypatch, setup_state):
    entered, killed = threading.Event(), threading.Event()
    errors, calls = [], []
    cancel = threading.Event()
    class Process:
        returncode = None
        args = ['declared-worker']
        def __init__(self, command, **options):
            calls.append((command, options))
        def poll(self): return self.returncode
        def kill(self):
            self.returncode = 1
            killed.set()
        def wait(self, timeout): return self.returncode
        def communicate(self, timeout):
            entered.set()
            assert killed.wait(2)
            return b'', None
    monkeypatch.setattr(resource_setup.subprocess, 'Popen', Process)
    def run():
        try:
            resource_setup._run_probe('probe', 'asr', cancel, 'balanced')
        except InterruptedError:
            errors.append('cancelled')
    thread = threading.Thread(target=run)
    resource_setup._controls['probe'] = cancel
    resource_setup._threads['probe'] = thread
    thread.start()
    assert entered.wait(1)
    resource_setup.stop_all()
    assert killed.is_set() and cancel.is_set() and not thread.is_alive()
    assert errors == ['cancelled'] and not resource_setup._probes
    with pytest.raises(ValueError, match='завершает работу'):
        resource_setup.start('asr', 'cpu-fast')
    with pytest.raises(InterruptedError):
        resource_setup._run_probe('late', 'asr', threading.Event(), 'balanced')
    assert len(calls) == 1 and calls[0][1]['shell'] is False
    resource_setup._threads.clear()
    resource_setup.reopen()
    assert not resource_setup._closing


def test_setup_shutdown_closes_download_without_deleting_existing_models(tmp_path, monkeypatch, setup_state):
    entered, closed = threading.Event(), threading.Event()
    payload = b'downloaded bytes'
    manifest = {'assets': [{'path': 'whisper/small/model.bin', 'url': 'https://invalid.test/declared',
                            'bytes': len(payload), 'sha256': hashlib.sha256(payload).hexdigest()}]}
    monkeypatch.setattr(resource_setup, 'MANIFEST', manifest)
    monkeypatch.setattr(resource_setup, 'MODELS', tmp_path / 'models')
    monkeypatch.setattr(resource_setup, 'APP_ROOT', tmp_path)
    existing = tmp_path / 'models/whisper/base/model.bin'
    existing.parent.mkdir(parents=True)
    existing.write_bytes(b'owner model')
    class Response:
        status_code = 200
        headers = {}
        def __enter__(self): return self
        def __exit__(self, *args): self.close()
        def raise_for_status(self): pass
        def close(self): closed.set()
        def iter_bytes(self, size):
            entered.set()
            assert closed.wait(2)
            yield payload
    monkeypatch.setattr(resource_setup.httpx, 'stream', lambda *a, **k: Response())
    job = resource_setup.start('asr', 'cpu-fast')
    assert entered.wait(1)
    resource_setup.stop_all()
    assert resource_setup.store.snapshot(job['id'])['status'] == 'cancelled'
    assert closed.is_set() and not resource_setup._threads
    assert existing.read_bytes() == b'owner model'
    assert not (tmp_path / 'models/whisper/small/model.bin').exists()
    assert not list(tmp_path.rglob('*.partial'))


def test_request_store_shutdown_cancels_prepare_and_skips_downstream_work():
    store = RequestStore(workers=1)
    entered = threading.Event()
    downstream = []
    def prepare():
        event = cancellation.get()
        entered.set()
        assert event.wait(2)
        return SimpleNamespace(initial={'answer': 'Результат уже выполненного действия.',
            'action_results': [{'success': True}]}, finish_turn=None)
    entry = store.begin('shutdown-request', 'fingerprint', prepare, lambda p: downstream.append('must not run'))
    assert entered.wait(1)
    started = time.monotonic()
    store.close()
    assert time.monotonic() - started < 1
    assert entry.final.result()['cancelled'] and entry.final.result()['action_results'] == [{'success': True}]
    assert not downstream and not store.running()
    with pytest.raises(RequestBusy, match='завершает работу'):
        store.begin('late', 'other', prepare, lambda p: None)
    store.close()
    store.reopen()
    assert not store._closing
    store.close()
