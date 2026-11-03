import asyncio
import json
from unittest.mock import patch
import httpx
import pytest
from localmind import model_catalog as cat


@pytest.mark.parametrize('value', ['../evil', 'a/b/c', 'https://evil/a', 'a/b:Q4_K_M', 'a/b?x=1', 'a/b%2F..',
    'a/b\\x', 'a/b\n', 'a/b;calc', 'a/..', 'a/--x', 'a@b/c', 'a/b#x'])
def test_repo_validation(value):
    with pytest.raises(ValueError): cat.repo_id(value)


def hub_data(**changes):
    return {'id': 'Qwen/Test-GGUF', 'private': False, 'gated': False,
            'cardData': {'license': 'apache-2.0'},
            'gguf': {'architecture': 'qwen3', 'total': 4000000000, 'context_length': 40960, 'chat_template': 'x'},
            'siblings': [{'rfilename': 'Test-Q4_K_M.gguf', 'size': 2500000000}], **changes}


@pytest.fixture
def hub(monkeypatch):
    monkeypatch.setattr(cat, 'ollama_json', lambda *args: {'version': '0.40.13'})
    monkeypatch.setattr(cat, 'hub_json', lambda *args: hub_data())
    monkeypatch.setattr(cat, 'disk_status', lambda: {'free': None, 'status': 'unknown'})


def test_hf_reference_explicit_quantization_unknown_kv_and_provenance(hub):
    reference, row = cat.resolve_pull('huggingface', 'Qwen/Test-GGUF', 'Q4_K_M', 4096)
    assert reference == 'hf.co/Qwen/Test-GGUF:Q4_K_M'
    assert row['compatibility'] == 'estimated' and row['memory']['vram_minimum'] is None
    assert row['source_url'] == 'https://huggingface.co/Qwen/Test-GGUF'
    assert row['benchmarks'] == []


@pytest.mark.parametrize('changes', [
    {'gguf': {'architecture': 'unknown'}}, {'gated': 'auto'}, {'private': True},
    {'siblings': [{'rfilename': 'x-Q4_K_M-00001-of-00002.gguf', 'size': 10}]},
    {'siblings': [{'rfilename': 'mmproj-Q4_K_M.gguf', 'size': 10}]},
    {'cardData': {}}, {'pipeline_tag': 'image-text-to-text'}])
def test_incompatible_metadata_blocks(hub, monkeypatch, changes):
    monkeypatch.setattr(cat, 'hub_json', lambda *args: hub_data(**changes))
    with pytest.raises(ValueError): cat.resolve_pull('huggingface', 'Qwen/Test-GGUF', 'Q4_K_M', 4096)


def test_old_or_missing_ollama_blocks(hub, monkeypatch):
    monkeypatch.setattr(cat, 'ollama_json', lambda *args: {'version': '0.5.0'})
    assert cat.hub_variants('Qwen/Test-GGUF')[0]['compatibility'] == 'blocked'
    monkeypatch.setattr(cat, 'ollama_json', lambda *args: (_ for _ in ()).throw(httpx.ConnectError('secret path')))
    assert cat.curated()[0]['compatibility'] == 'blocked'


def test_malformed_lfs_metadata_is_a_domain_error(hub,monkeypatch):
    monkeypatch.setattr(cat,'hub_json',lambda *a:hub_data(siblings=[{'rfilename':'Test-Q4_K_M.gguf','size':100,'lfs':['invalid']}]))
    with pytest.raises(ValueError,match='метаданные'):
        cat.hub_variants('Qwen/Test-GGUF')


def test_disk_source_never_uses_project_drive(monkeypatch):
    monkeypatch.delenv('LOCALMIND_OLLAMA_STORAGE_VERIFIED', raising=False)
    monkeypatch.setenv('OLLAMA_MODELS', 'C:/fake')
    monkeypatch.setattr('localmind.ollama_storage.storage_status', lambda: {
        'confirmed': False, 'path': None, 'source': 'server environment unavailable'})
    with patch.object(cat.shutil, 'disk_usage') as disk:
        assert cat.disk_status()['free'] is None
        disk.assert_not_called()


def test_disk_uses_confirmed_server_location(tmp_path, monkeypatch):
    monkeypatch.setattr('localmind.ollama_storage.storage_status', lambda: {
        'confirmed': True, 'path': str(tmp_path), 'source': 'server process environment'})
    result = cat.disk_status()
    assert result['path'] == str(tmp_path) and result['free'] > 0


def test_disk_exhaustion_and_license_prevent_start(hub, monkeypatch):
    jobs = cat.DownloadJobs()
    fingerprint = cat.curated()[0]['fingerprint']
    with pytest.raises(ValueError): jobs.start('ollama', 'qwen3:4b-q4_K_M', 'Q4_K_M')
    with pytest.raises(ValueError): jobs.start('ollama', 'qwen3:4b-q4_K_M', 'Q4_K_M', accept_license=True, fingerprint=fingerprint)
    monkeypatch.setattr(cat, 'disk_status', lambda: {'free': 100, 'status': 'verified'})
    with pytest.raises(ValueError): jobs.start('ollama', 'qwen3:4b-q4_K_M', 'Q4_K_M', accept_license=True, fingerprint=fingerprint)
    assert jobs.snapshot() == []


def test_memory_includes_context_kv_and_runtime(hub):
    small, large = cat.curated(4096)[0], cat.curated(8192)[0]
    assert large['memory']['kv_cache'] == small['memory']['kv_cache'] * 2
    assert small['memory']['vram_minimum'] > small['size']
    assert small['memory']['vram_recommended'] > small['memory']['vram_minimum']


def prepare_job(jobs, key='test'):
    jobs.jobs[key] = {'id': key, 'model': 'qwen3:4b-q4_K_M', 'status': 'starting', 'layers': {}}
    jobs.controls[key] = {'loop': None, 'task': None, 'cancel': False}
    return key


def test_changed_hf_artifact_cannot_become_ready(monkeypatch):
    original = httpx.AsyncClient
    transport = httpx.MockTransport(lambda request: httpx.Response(200,content=b'{"status":"success"}\n'))
    monkeypatch.setattr(cat.httpx,'AsyncClient',lambda **kw:original(transport=transport,**kw))
    monkeypatch.setattr(cat,'installed_detail',lambda reference:{'weight_sha256':'b'*64})
    jobs=cat.DownloadJobs();key=prepare_job(jobs);jobs.jobs[key]['expected_sha256']='a'*64
    asyncio.run(jobs._pull(key,'hf.co/Qwen/Test-GGUF:Q4_K_M'))
    result=jobs.snapshot(key)
    assert result['status']=='failed' and result['diagnostic']['stage']=='installed_verification'
    assert result['diagnostic']['code']=='incompatible' and not result.get('ready')


@pytest.mark.parametrize('ending,expected', [(b'{"status":"success"}\n', 'succeeded'),
    (b'', 'failed'), (b'{"status":"success"', 'failed'), (b'{"error":"disk full /private/path"}\n', 'failed')])
def test_progress_interruption_verification_and_redaction(monkeypatch, ending, expected):
    digest = 'sha256:' + 'a'*64
    progress = json.dumps({'digest': digest, 'total': 100, 'completed': 50}).encode() + b'\n'
    original = httpx.AsyncClient
    transport = httpx.MockTransport(lambda request: httpx.Response(200, content=progress + ending))
    monkeypatch.setattr(cat.httpx, 'AsyncClient', lambda **kw: original(transport=transport, **kw))
    monkeypatch.setattr(cat, 'installed_detail', lambda reference: {'digest': 'abc'})
    jobs = cat.DownloadJobs(); key = prepare_job(jobs)
    asyncio.run(jobs._pull(key, 'qwen3:4b-q4_K_M'))
    result = jobs.snapshot(key)
    assert result['status'] == expected
    assert result['layers'][digest] == {'total': 100, 'completed': 50}
    assert '/private' not in str(result)


def test_cancel_closes_stream_but_doesnt_claim_daemon_stopped(monkeypatch):
    closed = []
    class WaitingStream(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield b'{"status":"pulling manifest"}\n'
            await asyncio.sleep(10)
        async def aclose(self): closed.append(True)
    original = httpx.AsyncClient
    transport = httpx.MockTransport(lambda request: httpx.Response(200, stream=WaitingStream()))
    monkeypatch.setattr(cat.httpx, 'AsyncClient', lambda **kw: original(transport=transport, **kw))
    jobs = cat.DownloadJobs(); key = prepare_job(jobs)
    async def run():
        task = asyncio.create_task(jobs._pull(key, 'qwen3:4b-q4_K_M'))
        await asyncio.sleep(.01); jobs.cancel(key); await task
    asyncio.run(run())
    assert closed and jobs.snapshot(key)['status'] == 'cancelled_unverified'
    assert not jobs.controls


def test_arbitrary_sources_and_quants_cannot_pull(hub):
    for source, identity, quant in [('url','http://evil','Q4_K_M'), ('ollama','evil:latest','Q4_K_M'),
                                    ('huggingface','Qwen/Test-GGUF','Q4_K_M;calc')]:
        with pytest.raises(ValueError): cat.resolve_pull(source, identity, quant, 4096)


def test_terminal_pull_cannot_become_permanently_cancelling():
    jobs=cat.DownloadJobs();key=prepare_job(jobs)
    jobs.jobs[key]['status']='succeeded'
    with pytest.raises(ValueError): jobs.cancel(key)
    assert jobs.snapshot(key)['status']=='succeeded'


def test_layer_events_are_replacements_and_new_cached_layers_do_not_invent_speed(monkeypatch):
    a, b = 'sha256:'+'a'*64, 'sha256:'+'b'*64
    events = [{'digest':a,'total':100},
              {'digest':a,'total':100,'completed':50},
              {'digest':a,'total':100,'completed':50},
              {'digest':b,'total':200,'completed':200},
              {'digest':a,'total':120,'completed':80}]
    payload = b''.join(json.dumps(event).encode()+b'\n' for event in events)
    original=httpx.AsyncClient
    transport=httpx.MockTransport(lambda request:httpx.Response(200,content=payload))
    monkeypatch.setattr(cat.httpx,'AsyncClient',lambda **kw:original(transport=transport,**kw))
    jobs=cat.DownloadJobs(); key=prepare_job(jobs)
    asyncio.run(jobs._pull(key,'qwen3:4b-q4_K_M'))
    job=jobs.snapshot(key)
    assert job['status']=='failed'  # Missing final success never installs.
    assert job['completed']==280 and job['total']==320
    assert job['layers'][a]=={'total':120,'completed':80}
    assert job['bytes_per_second'] is None and job['eta_seconds'] is None


@pytest.mark.parametrize('changes',[{'cardData':['bad']},{'gguf':['bad']},{'siblings':'bad'}])
def test_malformed_hub_metadata_is_safe(hub,monkeypatch,changes):
    monkeypatch.setattr(cat,'hub_json',lambda *a:hub_data(**changes))
    with pytest.raises(ValueError):cat.hub_variants('Qwen/Test-GGUF')


def test_changed_metadata_requires_new_acknowledgement_and_retry_is_explicit(hub,monkeypatch):
    rows=cat.hub_variants('Qwen/Test-GGUF');fingerprint=rows[0]['fingerprint']
    monkeypatch.setattr(cat,'hub_json',lambda *a:hub_data(cardData={'license':'different-license'}))
    jobs=cat.DownloadJobs()
    with pytest.raises(ValueError,match='изменились'):
        jobs.start('huggingface','Qwen/Test-GGUF','Q4_K_M',accept_license=True,acknowledge_unknown_disk=True,fingerprint=fingerprint)
    assert not jobs.jobs
    monkeypatch.setattr(cat,'hub_json',lambda *a:hub_data())
    starts=[]
    class DormantThread:
        def __init__(self,**kw):pass
        def start(self):starts.append(True)
    monkeypatch.setattr(cat,'Thread',DormantThread)
    first=jobs.start('huggingface','Qwen/Test-GGUF','Q4_K_M',accept_license=True,acknowledge_unknown_disk=True,fingerprint=fingerprint)
    with pytest.raises(ValueError,match='Другая'):
        jobs.start('huggingface','Qwen/Test-GGUF','Q4_K_M',accept_license=True,acknowledge_unknown_disk=True,fingerprint=fingerprint)
    jobs.update(first['id'],status='failed')
    second=jobs.start('huggingface','Qwen/Test-GGUF','Q4_K_M',accept_license=True,acknowledge_unknown_disk=True,fingerprint=fingerprint)
    assert len(starts)==2 and second['id']!=first['id']


def test_worker_start_failure_leaves_no_ghost_download(hub,monkeypatch):
    fingerprint=cat.curated()[0]['fingerprint']
    class FailedThread:
        def __init__(self,**kw):pass
        def start(self):raise RuntimeError('cannot start thread')
    monkeypatch.setattr(cat,'Thread',FailedThread)
    jobs=cat.DownloadJobs()
    with pytest.raises(ValueError,match='обработчик'):
        jobs.start('ollama','qwen3:4b-q4_K_M','Q4_K_M',accept_license=True,acknowledge_unknown_disk=True,fingerprint=fingerprint)
    assert jobs.snapshot()==[] and not jobs.controls
