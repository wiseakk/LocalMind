"""Component tests use declared fake bytes, never a user's models or network."""
from concurrent.futures import ThreadPoolExecutor
import errno
import hashlib
import threading
import time
from types import SimpleNamespace

import pytest

from localmind import resource_setup as setup
from localmind.download_store import JobStore
from localmind.resource_lock import resource_download_lock, ResourceBusyError


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(setup, 'MODELS', tmp_path / 'models')
    monkeypatch.setattr(setup, 'PRIVATE', tmp_path / 'private')
    monkeypatch.setattr(setup, 'APP_ROOT', tmp_path)
    monkeypatch.setattr(setup, 'store', JobStore())
    monkeypatch.setattr(setup, 'dependencies', lambda _: True)
    monkeypatch.setattr(setup, '_closing', False)
    for name in ('_controls', '_threads', '_probes', '_sources'):
        monkeypatch.setattr(setup, name, {})
    monkeypatch.setattr(setup, '_probe_slot', threading.Lock())
    yield tmp_path
    setup.stop_all()


class Response:
    def __init__(self, chunks, status=200, headers=None):
        self.status_code, self.headers = status, headers or {}
        self.chunks = chunks
        self.closed = False

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def close(self):
        self.closed = True

    def raise_for_status(self):
        assert self.status_code in (200, 206)

    def iter_bytes(self, size):
        yield from self.chunks


def asset(payload=b'abcdef', path='whisper/small/model.bin'):
    return {'path': path, 'url': 'https://invalid.test/declared', 'bytes': len(payload),
            'sha256': hashlib.sha256(payload).hexdigest()}


def transfer(isolated, spec, cancel=None):
    setup.store.insert({'id': 'one', 'kind': 'asr', 'status': 'starting'})
    target = setup.MODELS / spec['path']
    target.parent.mkdir(parents=True, exist_ok=True)
    setup._download_asset('one', spec, target, cancel or threading.Event(), 0, spec['bytes'])
    return target


def wait_job(key, state, timeout=3):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        current = setup.store.snapshot(key)['status']
        if current == state:
            return
        time.sleep(.01)
    pytest.fail(f'Job remained {current}; expected {state}')


def test_same_physical_resource_start_is_atomic_and_returns_one_job(isolated, monkeypatch):
    starts = []

    class DormantThread:
        def __init__(self, **kwargs):
            pass

        def start(self):
            starts.append(True)

        def is_alive(self):
            return False

        def join(self, **kwargs):
            pass

    monkeypatch.setattr(setup.threading, 'Thread', DormantThread)
    # ThreadPoolExecutor needs its actual Thread implementation.
    first = setup.start('asr', 'cpu-fast')
    assert setup.start('asr', 'balanced')['id'] == first['id']
    voice = setup.start('tts', 'balanced')
    assert setup.start('tts', 'gpu-quality')['id'] == voice['id']
    assert len(starts) == len(setup.store.snapshot()) == 2


def test_journal_admission_is_atomic_under_racing_requests(isolated):
    journal = JobStore()

    def insert(index):
        try:
            journal.insert({'id': str(index), 'kind': 'asr', 'profile': 'balanced', 'status': 'starting'})
            return True
        except ValueError:
            return False

    with ThreadPoolExecutor(max_workers=8) as pool:
        assert sum(pool.map(insert, range(20))) == 1
    assert len(journal.snapshot()) == 1


def test_silero_has_an_independent_cross_process_lock(isolated):
    with resource_download_lock(setup.MODELS, 'silero:ru'):
        with resource_download_lock(setup.MODELS, 'whisper:small'):
            with pytest.raises(ResourceBusyError):
                with resource_download_lock(setup.MODELS, 'silero:ru'):
                    pytest.fail('shared voice file was admitted twice')
    with resource_download_lock(setup.MODELS, 'silero:ru'):
        pass


def test_partial_resume_requires_valid_suffix_and_checks_full_hash(isolated, monkeypatch):
    target = setup.MODELS / 'whisper/small/model.bin'
    target.parent.mkdir(parents=True)
    partial = setup._partial_path(target)
    partial.write_bytes(b'abc')
    requests = []

    def stream(*args, **kwargs):
        requests.append(kwargs['headers'])
        return Response([b'def'], 206, {'Content-Range': 'bytes 3-5/6', 'Content-Length': '3'})

    monkeypatch.setattr(setup.httpx, 'stream', stream)
    assert transfer(isolated, asset()).read_bytes() == b'abcdef'
    assert requests == [{'Accept-Encoding': 'identity', 'Range': 'bytes=3-'}]
    assert not partial.exists()


def test_ignored_range_overwrites_instead_of_appending(isolated, monkeypatch):
    target = setup.MODELS / 'whisper/small/model.bin'
    target.parent.mkdir(parents=True)
    setup._partial_path(target).write_bytes(b'abc')
    monkeypatch.setattr(setup.httpx, 'stream', lambda *a, **kw: Response([b'abcdef']))
    assert transfer(isolated, asset()).read_bytes() == b'abcdef'


@pytest.mark.parametrize('headers', [
    {'Content-Range': 'bytes 0-5/6'},
    {'Content-Range': 'bytes 3-5/7'},
    {'Content-Range': 'bytes 3-5/6', 'Content-Length': '6'},
    {'Content-Range': 'bytes 3-5/6', 'Content-Encoding': 'gzip'},
])
def test_invalid_range_never_changes_saved_prefix_or_publishes(isolated, monkeypatch, headers):
    target = setup.MODELS / 'whisper/small/model.bin'
    target.parent.mkdir(parents=True)
    partial = setup._partial_path(target)
    partial.write_bytes(b'abc')
    monkeypatch.setattr(setup.httpx, 'stream', lambda *a, **kw: Response([b'def'], 206, headers))
    with pytest.raises(ValueError):
        transfer(isolated, asset())
    assert partial.read_bytes() == b'abc'
    assert not target.exists()


def test_cancel_preserves_prefix_for_an_explicit_resume(isolated, monkeypatch):
    cancel = threading.Event()

    def chunks():
        yield b'abc'
        cancel.set()
        yield b'def'

    monkeypatch.setattr(setup.httpx, 'stream', lambda *a, **kw: Response(chunks()))
    with pytest.raises(InterruptedError):
        transfer(isolated, asset(), cancel)
    target = setup.MODELS / 'whisper/small/model.bin'
    assert setup._partial_path(target).read_bytes() == b'abc'
    assert not target.exists()
    setup.store.update('one', status='cancelled')
    monkeypatch.setattr(setup.httpx, 'stream', lambda *a, **kw: Response([b'def'], 206, {'Content-Range': 'bytes 3-5/6'}))
    cancel.clear()
    # Reuse the same helper job after an explicit retry.
    setup._download_asset('one', asset(), target, cancel, 0, 6)
    assert target.read_bytes() == b'abcdef'


def test_wrong_hash_is_removed_without_replacing_existing_file(isolated, monkeypatch):
    target = setup.MODELS / 'whisper/small/model.bin'
    target.parent.mkdir(parents=True)
    target.write_bytes(b'previous file')
    monkeypatch.setattr(setup.httpx, 'stream', lambda *a, **kw: Response([b'xxxxxx']))
    with pytest.raises(ValueError, match='Контрольная сумма'):
        transfer(isolated, asset())
    assert target.read_bytes() == b'previous file'
    assert not setup._partial_path(target).exists()


def test_complete_verified_partial_is_published_without_network(isolated, monkeypatch):
    target = setup.MODELS / 'whisper/small/model.bin'
    target.parent.mkdir(parents=True)
    setup._partial_path(target).write_bytes(b'abcdef')
    monkeypatch.setattr(setup.httpx, 'stream', lambda *a, **kw: pytest.fail('complete bytes fetched twice'))
    assert transfer(isolated, asset()).read_bytes() == b'abcdef'


def test_downloads_overlap_but_inference_probes_are_serial_and_independently_cancellable(isolated, monkeypatch):
    specs = [asset(), asset(b'voice!', 'silero/voice.pt')]
    monkeypatch.setattr(setup, 'MANIFEST', {'assets': specs})
    downloaded = threading.Barrier(2)
    probe_entered, release_probe = threading.Event(), threading.Event()
    probes = []

    # The current resource name is carried by the declared URL for this test.
    specs[0]['url'] += '/asr'
    specs[1]['url'] += '/tts'

    def response(method, url, **kwargs):
        def chunks():
            downloaded.wait(timeout=2)
            yield b'abcdef' if url.endswith('/asr') else b'voice!'
        return Response(chunks())

    def probe(key, kind, cancel, profile):
        probes.append(key)
        probe_entered.set()
        assert release_probe.wait(2)
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(setup.httpx, 'stream', response)
    monkeypatch.setattr(setup, '_run_probe', probe)
    first = setup.start('asr')
    second = setup.start('tts')
    try:
        assert probe_entered.wait(2)
        wait_job(first['id'], 'verifying')
        wait_job(second['id'], 'verifying')
        assert len(probes) == 1
        waiting = second['id'] if probes[0] == first['id'] else first['id']
        setup.cancel(waiting)
        wait_job(waiting, 'cancelled')
        assert len(probes) == 1
    finally:
        release_probe.set()
    wait_job(probes[0], 'succeeded')
    assert all((setup.MODELS / spec['path']).read_bytes() for spec in specs)


def test_installed_verified_resource_does_not_download_or_probe_again(isolated, monkeypatch):
    spec = asset()
    monkeypatch.setattr(setup, 'MANIFEST', {'assets': [spec]})
    target = setup.MODELS / spec['path']
    target.parent.mkdir(parents=True)
    target.write_bytes(b'abcdef')
    setup.atomic_json(setup.PRIVATE / 'asr-verified.json', {
        'manifest': setup.manifest_digest(), 'files': setup.signatures([spec])})
    monkeypatch.setattr(setup.httpx, 'stream', lambda *a, **kw: pytest.fail('installed resource downloaded again'))
    monkeypatch.setattr(setup, '_run_probe', lambda *a, **kw: pytest.fail('ready resource loaded again'))
    job = setup.start('asr')
    wait_job(job['id'], 'succeeded')
    assert setup.store.snapshot(job['id'])['ready'] is True


def test_full_journal_disk_terminates_worker_and_allows_retry_after_space_restored(isolated, monkeypatch):
    spec = asset()
    journal = JobStore(isolated / 'downloads' / 'jobs.json')
    monkeypatch.setattr(setup, 'store', journal)
    monkeypatch.setattr(setup, 'MANIFEST', {'assets': [spec]})
    monkeypatch.setattr(setup, '_run_probe', lambda *a, **kw: SimpleNamespace(returncode=0))
    original_save = journal.save
    disk = {'inject': True, 'full': False}

    def save():
        if disk['inject'] and any(job.get('completed', 0) > 0 for job in journal.jobs.values()):
            disk['full'] = True
        if disk['full']:
            raise OSError(errno.ENOSPC, 'No space left on device')
        original_save()

    monkeypatch.setattr(journal, 'save', save)
    requests = []

    def response(*args, **kwargs):
        headers = kwargs['headers']
        requests.append(headers)
        if headers.get('Range') == 'bytes=3-':
            return Response([b'def'], 206, {'Content-Range': 'bytes 3-5/6'})
        return Response([b'abc', b'def'])

    monkeypatch.setattr(setup.httpx, 'stream', response)
    first = setup.start('asr')
    wait_job(first['id'], 'failed')
    # Wait for the worker's finally block, then prove the row is terminal even
    # though the attempted durable error write encountered the same full disk.
    deadline = time.monotonic() + 2
    while first['id'] in setup._controls and time.monotonic() < deadline:
        time.sleep(.01)
    assert first['id'] not in setup._controls and first['id'] not in setup._threads
    failed = journal.snapshot(first['id'])
    assert failed['ready'] is False
    assert failed['persistence_error'] in failed['error']
    assert 'журнал' in failed['persistence_error']
    target = setup.MODELS / spec['path']
    assert setup._partial_path(target).read_bytes() == b'abc'
    assert not target.exists()

    disk.update(inject=False, full=False)
    retry = setup.start('asr')
    assert retry['id'] != first['id']
    wait_job(retry['id'], 'succeeded')
    assert len(requests) == 2 and requests[1]['Range'] == 'bytes=3-'
    assert target.read_bytes() == b'abcdef'
    assert not setup._partial_path(target).exists()
    restored = JobStore(journal.path)
    assert restored.snapshot(first['id'])['status'] == 'failed'
    assert restored.snapshot(retry['id'])['status'] == 'succeeded'
