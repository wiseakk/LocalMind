import hashlib
import io
import json
import stat
import threading
import zipfile
from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient

from localmind import asr_sources as sources, resource_setup as setup
from test_parallel_resources import asset, isolated, wait_job

FILES = {'config.json': b'{}', 'model.bin': b'model', 'tokenizer.json': b'tokenizer',
         'vocabulary.txt': b'vocabulary'}
PUBLIC = 'https://disk.yandex.ru/d/test-fixture'
DIRECT = 'https://downloader.disk.yandex.ru/disk/fixture?temporary=1'


def archive_bytes(files=FILES, prefix=''):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, 'w') as archive:
        for name, data in files.items():
            archive.writestr(prefix + name, data)
    return stream.getvalue()


@pytest.fixture
def models(isolated, monkeypatch):
    assets = [asset(data, 'whisper/small/' + name) for name, data in FILES.items()]
    monkeypatch.setattr(setup, 'MANIFEST', {'assets': assets})
    monkeypatch.setattr(sources, 'MIRRORS', isolated / 'mirrors.json')
    monkeypatch.setattr(setup, '_serial_probe', lambda *_: SimpleNamespace(returncode=0))
    return assets


def mirror(models, payload, digest=None):
    sources.MIRRORS.write_text(json.dumps({'small': {'url': PUBLIC, 'bytes': len(payload),
        'sha256': digest or hashlib.sha256(payload).hexdigest()}}))
    return sources.mirror_for('small', models)


def yandex_transport(monkeypatch, payload, href=DIRECT, *, download_error=None, on_read=None):
    seen = []
    client = httpx.Client

    class Payload(httpx.SyncByteStream):
        def __iter__(self):
            if on_read:
                on_read()
            yield payload

    def request(req):
        seen.append(req)
        if req.url.host == 'cloud-api.yandex.net':
            assert req.url.path == '/v1/disk/public/resources/download'
            assert req.url.params['public_key'] == PUBLIC
            link = json.dumps({'method': 'GET', 'templated': False, 'href': href}).encode()
            return httpx.Response(200, stream=httpx.ByteStream(link))
        if download_error:
            raise download_error
        return httpx.Response(200, headers={'Content-Length': str(len(payload))}, stream=Payload())

    monkeypatch.setattr(sources, 'DOWNLOAD_HOSTS', {'downloader.disk.yandex.ru'})
    monkeypatch.setattr(setup.httpx, 'Client', lambda **kwargs: client(transport=httpx.MockTransport(request), **kwargs))
    return seen


def test_official_source_installs_and_valid_local_files_skip_network_and_probe(models, monkeypatch):
    transfers = []
    probes = []

    def download(key, spec, target, cancel, completed, total):
        transfers.append(spec['path'])
        target.write_bytes(FILES[target.name])

    monkeypatch.setattr(setup, '_download_asset', download)
    monkeypatch.setattr(setup, '_serial_probe', lambda *args: probes.append(args) or SimpleNamespace(returncode=0))
    first = setup.start('asr', 'cpu-fast')
    wait_job(first['id'], 'succeeded')
    second = setup.start('asr', 'balanced')
    wait_job(second['id'], 'succeeded')
    assert len(transfers) == len(FILES) and len(probes) == 1
    assert setup._verified_stamp('asr', 'cpu-fast', models)


def test_official_network_failure_offers_mirror_only_with_explicit_consent(models, monkeypatch):
    payload = archive_bytes(prefix='small/')
    configured = mirror(models, payload)
    seen = yandex_transport(monkeypatch, payload)

    def offline(*_):
        raise httpx.ConnectError('offline')

    monkeypatch.setattr(setup, '_download_asset', offline)
    official = setup.start('asr', 'cpu-fast')
    wait_job(official['id'], 'failed')
    offer = setup.store.snapshot(official['id'])['asr_mirror']
    assert offer == {'type':'yandex_disk', 'fingerprint': configured['fingerprint'], 'bytes': len(payload)}
    assert not seen
    with pytest.raises(ValueError):
        setup.start('asr', 'cpu-fast', source='yandex', fingerprint='0'*64)
    job = setup.start('asr', 'cpu-fast', source='yandex', fingerprint=offer['fingerprint'])
    wait_job(job['id'], 'succeeded')
    assert [req.url.host for req in seen] == ['cloud-api.yandex.net', 'downloader.disk.yandex.ru']
    assert (setup.MODELS/'whisper/small/model.bin').read_bytes() == FILES['model.bin']
    assert setup._verified_stamp('asr', 'cpu-fast', models)


@pytest.mark.parametrize('failure', ['network', 'sha256', 'foreign-href', 'cancel'])
def test_mirror_failure_never_publishes_or_leaves_partial_model(models, monkeypatch, failure):
    payload = archive_bytes()
    configured = mirror(models, payload, '0'*64 if failure == 'sha256' else None)
    cancel = threading.Event()
    seen = yandex_transport(monkeypatch, payload,
        href='https://127.0.0.1/private' if failure == 'foreign-href' else DIRECT,
        download_error=httpx.ReadTimeout('offline') if failure == 'network' else None,
        on_read=cancel.set if failure == 'cancel' else None)
    setup.store.insert({'id': 'mirror', 'kind': 'asr', 'profile': 'cpu-fast', 'status': 'starting'})
    setup._prepare('mirror', 'asr', cancel, 'cpu-fast', source='yandex', mirror=configured)
    row = setup.store.snapshot('mirror')
    assert row['status'] == ('cancelled' if failure == 'cancel' else 'failed')
    if failure == 'network':
        assert 'импортируйте' in row['error']
    elif failure == 'sha256':
        assert 'SHA-256' in row['error']
    elif failure == 'foreign-href':
        assert len(seen) == 1
    assert not (setup.MODELS/'whisper/small').exists()
    assert not list((setup.MODELS/'whisper').glob('.asr-stage-*'))


@pytest.mark.parametrize('problem', ['corrupt', 'traversal', 'bomb', 'symlink', 'wrong-weights'])
def test_rejects_untrusted_archives_before_probe(models, isolated, monkeypatch, problem):
    payload = archive_bytes()
    if problem == 'corrupt':
        payload = payload[:-10]
    if problem == 'traversal':
        payload = archive_bytes(FILES, prefix='../')
    if problem == 'bomb':
        payload = archive_bytes({**FILES, 'model.bin': b'x'*1000})
    if problem == 'wrong-weights':
        payload = archive_bytes({**FILES, 'model.bin': b'other'})
    if problem == 'symlink':
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, 'w') as archive:
            item = zipfile.ZipInfo('model.bin')
            item.create_system = 3
            item.external_attr = (stat.S_IFLNK | 0o777) << 16
            archive.writestr(item, FILES['model.bin'])
            for name in FILES.keys() - {'model.bin'}:
                archive.writestr(name, FILES[name])
        payload = stream.getvalue()
    incoming = isolated/'import.zip'
    incoming.write_bytes(payload)
    probe_calls = []
    monkeypatch.setattr(setup, '_serial_probe', lambda *args: probe_calls.append(args))
    job = setup.start('asr', 'cpu-fast', source='local', incoming=incoming, mode='zip')
    wait_job(job['id'], 'failed')
    assert not probe_calls
    assert not (setup.MODELS/'whisper/small').exists()
    assert not (isolated/'model.bin').exists()


def test_streamed_directory_import_is_authenticated_and_pinned(models, monkeypatch):
    from localmind import server
    from dataclasses import replace
    monkeypatch.setattr(server, 'settings', replace(server.settings, key='test-local-key'))
    client = TestClient(server.app, base_url='http://127.0.0.1', client=('127.0.0.1', 1234))
    url = '/api/setup/asr-import?profile=cpu-fast&mode=directory'
    headers = {'Content-Type': 'application/octet-stream'}
    payload = b''.join(FILES.values())
    assert client.post(url, headers=headers, content=payload).status_code == 401
    headers['X-LocalMind-Key'] = 'test-local-key'
    assert client.post(url, headers={**headers, 'Origin':'https://example.invalid'}, content=payload).status_code == 403
    assert client.post(url, headers=headers, content=payload+b'overflow').status_code == 413
    response = client.post(url, headers=headers, content=payload)
    assert response.status_code == 200, response.text
    wait_job(response.json()['id'], 'succeeded')
    assert setup._verified_stamp('asr', 'balanced', models)
    assert {path.name for path in (setup.MODELS/'whisper/small').iterdir()} == FILES.keys()


def test_bad_or_unconfigured_mirror_is_never_offered(models, monkeypatch):
    sources.MIRRORS.write_text(json.dumps({'small': {'url':'https://disk.yandex.ru.evil.test/d/x', 'sha256':'0'*64}}))

    def offline(*_):
        raise httpx.ConnectError('offline')

    monkeypatch.setattr(setup, '_download_asset', offline)
    job = setup.start('asr', 'cpu-fast')
    wait_job(job['id'], 'failed')
    result = setup.store.snapshot(job['id'])
    assert result['asr_mirror'] is None and 'импортировать' in result['error']


def test_changed_mirror_is_not_advertised_from_persisted_failure(models, monkeypatch):
    from localmind import model_routes

    offer = mirror(models, archive_bytes())
    persisted = {'kind':'asr', 'profile':'cpu-fast', 'status':'failed',
                 'asr_mirror':{'bytes':offer['bytes'], 'fingerprint':offer['fingerprint']}}
    monkeypatch.setattr(model_routes.catalog.downloads, 'snapshot', lambda: [dict(persisted)])
    assert model_routes.list_pulls()['jobs'][0]['asr_mirror'] == {**persisted['asr_mirror'], 'type':'yandex_disk'}
    sources.MIRRORS.write_text('{"small": null}')
    assert model_routes.list_pulls()['jobs'][0]['asr_mirror'] is None


def test_probe_failure_preserves_previous_model_directory(models, isolated, monkeypatch):
    target = setup.MODELS/'whisper/small'
    target.mkdir(parents=True)
    (target/'model.bin').write_bytes(b'previous bytes')

    def probe(key, kind, cancel, profile, stage):
        assert stage != target and (stage/'model.bin').read_bytes() == FILES['model.bin']
        assert (target/'model.bin').read_bytes() == b'previous bytes'
        return SimpleNamespace(returncode=1, stdout=b'{"code":"library_incompatible"}')

    monkeypatch.setattr(setup, '_serial_probe', probe)
    incoming = isolated/'import.zip'
    incoming.write_bytes(archive_bytes())
    job = setup.start('asr', 'cpu-fast', source='local', incoming=incoming, mode='zip')
    wait_job(job['id'], 'failed')
    assert (target/'model.bin').read_bytes() == b'previous bytes'
    assert not setup._verified_stamp('asr', 'cpu-fast', models)


@pytest.mark.parametrize('model', ['small', 'medium'])
@pytest.mark.parametrize('variant', ['published', 'tampered', 'extra', 'mixed-prefix'])
def test_systran_windows_archive_keeps_only_pinned_lf_files(tmp_path, model, variant):
    pinned = {**FILES, 'config.json': b'{\n}\n', 'tokenizer.json': b'{\n}\n',
              'vocabulary.txt': b'word\nword2\n'}
    assets = [asset(data, f'whisper/{model}/{name}') for name, data in pinned.items()]
    folder = f'faster-whisper-{model}/'
    archive = tmp_path/'archive.zip'
    with zipfile.ZipFile(archive, 'w') as output:
        for name, data in pinned.items():
            data = data.replace(b'\n', b'\r\n') if name in sources.TEXT_ASSETS else data
            if name == 'config.json' and variant == 'tampered':
                data = data.replace(b'{', b'[')
            output.writestr(folder + name, data)
        output.writestr(('' if variant == 'mixed-prefix' else folder) + 'README.md', 'model notes')
        if variant == 'extra':
            output.writestr(folder + '.git/config', b'unexpected file')
    stage = tmp_path/'stage'
    stage.mkdir()
    if variant == 'published':
        sources.stage_import(archive, 'zip', stage, model, assets, threading.Event())
        assert {file.name:file.read_bytes() for file in stage.iterdir()} == pinned
    else:
        with pytest.raises(sources.ASRSourceError):
            sources.stage_import(archive, 'zip', stage, model, assets, threading.Event())
        assert not (stage/'README.md').exists()
