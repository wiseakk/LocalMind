"""Direct HTTPS mirrors use a bounded streaming transport and a pinned ZIP."""
import hashlib
import json
import threading

import httpx
import pytest

from localmind import asr_sources as sources, resource_setup as setup
from test_asr_sources import FILES, archive_bytes, models
from test_parallel_resources import isolated, wait_job

URL = 'https://mirror.example.test/models/whisper.zip'
ETAG = '"archive-v1"'


class Chunks(httpx.SyncByteStream):
    def __init__(self, chunks):
        self.chunks = chunks

    def __iter__(self):
        yield from self.chunks


def direct(models, payload, *, digest=None, url=URL):
    row = {'type':'direct_https', 'url':url, 'sha256':digest or hashlib.sha256(payload).hexdigest()}
    sources.MIRRORS.write_text(json.dumps({'small':row, 'medium':row}), encoding='utf-8')
    return sources.mirror_for('small', models)


def fetch(models, mirror, isolated, transport, cancel=None, progress=None):
    partial = isolated/'download.part'
    final = isolated/'verified.zip'
    with httpx.Client(transport=httpx.MockTransport(transport), follow_redirects=True) as client:
        sources.download_direct_archive(client, mirror, partial, final, models,
            cancel or threading.Event(), progress or (lambda *_: None), lambda _: None)
    return final


@pytest.mark.parametrize('url', ['http://mirror.example.test/file.zip', 'https://localhost/file.zip',
    'https://127.0.0.1/file.zip', 'https://[::1]/file.zip', 'https://192.168.1.1/file.zip',
    'https://user@mirror.example.test/file.zip', 'https://mirror.example.test/file.zip#fragment'])
def test_only_declared_public_https_links_are_configured(models, url):
    assert direct(models, b'zip', url=url) is None


def test_large_stream_writes_in_chunks_without_buffering_archive(isolated):
    chunk = b'z' * (1024 * 1024)
    blocks = 64
    total = len(chunk) * blocks
    digest = hashlib.sha256()
    for _ in range(blocks):
        digest.update(chunk)
    mirror = {'url':URL,'sha256':digest.hexdigest(),'bytes':total,'fingerprint':'f'*64}
    partial = isolated/'download.part'

    def chunks():
        for index in range(blocks):
            if index:
                assert partial.stat().st_size == index * len(chunk)
            yield chunk

    def response(req):
        assert req.url.scheme == 'https' and req.headers['accept-encoding'] == 'identity'
        return httpx.Response(200, headers={'Content-Length': str(total)}, stream=Chunks(chunks()))

    progress = []
    final = fetch([{'bytes':total}], mirror, isolated, response, progress=lambda *value: progress.append(value))
    assert final.stat().st_size == total
    assert progress[0] == (0,total) and progress[-1] == (total,total)
    assert not partial.exists()


@pytest.mark.parametrize('interruption', ['timeout', 'cancel'])
def test_resume_after_interruption_with_etag_and_precise_range(models, isolated, interruption):
    payload = archive_bytes()
    mirror = direct(models, payload)
    assert sources.mirror_for('medium', models)['type'] == 'direct_https'
    cancel = threading.Event()
    size = 20

    def interrupted():
        yield payload[:size]
        if interruption == 'timeout':
            raise httpx.ReadTimeout('fixture timeout')
        cancel.set()
        yield payload[size:]

    def first(req):
        assert 'range' not in req.headers
        return httpx.Response(200, headers={'Content-Length':str(len(payload)), 'ETag':ETAG},
                              stream=Chunks(interrupted()))

    with pytest.raises(httpx.ReadTimeout if interruption == 'timeout' else InterruptedError):
        fetch(models, mirror, isolated, first, cancel)
    assert (isolated/'download.part').read_bytes() == payload[:size]
    assert not (isolated/'verified.zip').exists()

    def resume(req):
        assert req.headers['range'] == f'bytes={size}-'
        assert req.headers['if-range'] == ETAG
        return httpx.Response(206, headers={'ETag':ETAG, 'Content-Length':str(len(payload)-size),
            'Content-Range':f'bytes {size}-{len(payload)-1}/{len(payload)}'}, stream=Chunks([payload[size:]]))

    progress = []
    assert fetch(models, mirror, isolated, resume, progress=lambda *value: progress.append(value)).read_bytes() == payload
    assert progress[0] == (size,len(payload))
    assert not (isolated/'download.json').exists()


@pytest.mark.parametrize('variant', ['200', '416', 'etag', 'range', 'length'])
def test_changed_or_invalid_range_response_never_appends_wrong_bytes(models, isolated, variant):
    payload = archive_bytes()
    mirror = direct(models, payload)
    offset = 11
    (isolated/'download.part').write_bytes(b'x'*offset)
    (isolated/'download.json').write_text(json.dumps({'etag':ETAG,'total':len(payload),
        'fingerprint':mirror['fingerprint']}))
    attempts = []

    def response(req):
        attempts.append(req)
        if len(attempts)==1:
            assert req.headers['if-range'] == ETAG
            if variant == '416':
                return httpx.Response(416)
            if variant in ('etag', 'range', 'length'):
                return httpx.Response(206, headers={
                    'ETag':'"changed"' if variant == 'etag' else ETAG,
                    'Content-Range':f'bytes {offset + (variant == "range")}-{len(payload)-1}/{len(payload)}',
                    'Content-Length':str(len(payload)-offset + (variant == "length")),
                },stream=Chunks([payload[offset:]]))
        else:
            assert 'range' not in req.headers
        return httpx.Response(200, headers={'ETag':'"changed"','Content-Length':str(len(payload))},
                              stream=Chunks([payload]))

    if variant in ('200','416'):
        assert fetch(models, mirror, isolated, response).read_bytes() == payload
        assert len(attempts) == (2 if variant=='416' else 1)
    else:
        with pytest.raises(sources.ASRSourceError, match='диапазон'):
            fetch(models, mirror, isolated, response)
        assert not (isolated/'verified.zip').exists()
    assert not (isolated/'download.part').exists()
    assert not (isolated/'download.json').exists()


def test_no_resume_with_weak_etag_and_no_following_redirect(models, isolated):
    payload = archive_bytes()
    mirror = direct(models, payload)

    def incomplete():
        yield payload[:16]
        raise httpx.ReadTimeout('offline')

    def first(req):
        return httpx.Response(200,headers={'ETag':'W/"weak"','Content-Length':str(len(payload))},
                              stream=Chunks(incomplete()))

    with pytest.raises(httpx.ReadTimeout):
        fetch(models, mirror, isolated, first)
    assert not (isolated/'download.part').exists()

    def redirect(req):
        assert str(req.url)==URL and 'range' not in req.headers
        return httpx.Response(302,headers={'Location':'http://mirror.example.test/unsafe.zip'})

    with pytest.raises(sources.ASRSourceError, match='перенаправления'):
        fetch(models, mirror, isolated, redirect)


@pytest.mark.parametrize('variant', ['valid', 'hash', 'broken', 'network'])
def test_direct_job_publishes_only_valid_zip_after_consent_and_reuses_installed_model(models, monkeypatch, variant):
    payload = b'broken zip' if variant=='broken' else archive_bytes()
    mirror = direct(models, payload, digest='0'*64 if variant=='hash' else None)
    client = httpx.Client
    requests = []

    def transport(req):
        requests.append(req)
        if variant == 'network':
            raise httpx.ConnectError('mirror offline')
        return httpx.Response(200, headers={'Content-Length':str(len(payload))}, stream=Chunks([payload]))

    def official_offline(*_):
        raise httpx.ConnectError('HF offline')

    monkeypatch.setattr(setup, '_download_asset', official_offline)
    monkeypatch.setattr(setup.httpx, 'Client', lambda **kw: client(transport=httpx.MockTransport(transport), **kw))
    official = setup.start('asr', 'cpu-fast')
    wait_job(official['id'], 'failed')
    offer = setup.store.snapshot(official['id'])['asr_mirror']
    assert offer['type'] == 'direct_https' and offer['fingerprint'] == mirror['fingerprint'] and not requests
    with pytest.raises(ValueError):
        setup.start('asr','cpu-fast',source='yandex',fingerprint=offer['fingerprint'])
    job = setup.start('asr','cpu-fast',source='direct_https',fingerprint=offer['fingerprint'])
    wait_job(job['id'], 'succeeded' if variant=='valid' else 'failed')
    target = setup.MODELS/'whisper/small/model.bin'
    if variant == 'valid':
        assert target.read_bytes() == FILES['model.bin']
        again = setup.start('asr','balanced',source='direct_https',fingerprint=offer['fingerprint'])
        wait_job(again['id'],'succeeded')
        assert len(requests) == 1
    else:
        assert not target.exists()
        error = setup.store.snapshot(job['id'])['error']
        assert {'hash':'SHA-256','broken':'ZIP','network':'HTTPS-зеркало недоступно'}[variant] in error
