"""Ownership/startup safety; real binary/inference evidence is separate."""
import hashlib
import json
import time
from unittest.mock import Mock, AsyncMock

import httpx
import pytest
from localmind import ollama_runtime as module


class Child:
    pid = 421
    def __init__(self): self.code = None; self.terminated = 0
    def poll(self): return self.code
    def terminate(self): self.code = 1; self.terminated += 1
    def kill(self): self.code = 2
    def wait(self, timeout=None): return self.code


@pytest.fixture
def runtime(tmp_path, monkeypatch):
    child, job = Child(), Mock()
    spawn = Mock(return_value=child)
    value = module.OllamaRuntime(tmp_path/'engine',tmp_path/'models',endpoint='http://127.0.0.1:11540',
                                popen=spawn, job_factory=Mock(return_value=job))
    monkeypatch.setattr(module, 'PRIVATE', tmp_path/'private')
    monkeypatch.setattr(value, '_occupied', lambda: False)
    monkeypatch.setattr(value, '_executable', lambda: tmp_path/'engine/ollama.exe')
    monkeypatch.setattr('localmind.ollama_storage.listener_process', lambda: child)
    yield value, child, job, spawn
    value.close()


def test_shared_compatible_daemon_is_reused_and_never_terminated(runtime, monkeypatch):
    value, child, job, spawn = runtime
    monkeypatch.setattr(value, 'probe', lambda: '0.40.14')
    assert value._ensure() is False and value.status()['state'] == 'ready'
    value.close()
    spawn.assert_not_called(); job.close.assert_not_called()
    assert child.terminated == 0


def test_unrelated_listener_blocks_start_without_killing_any_process(runtime, monkeypatch):
    value, child, _, spawn = runtime
    monkeypatch.setattr(value, 'probe', Mock(side_effect=ValueError('wrong service')))
    monkeypatch.setattr(value, '_occupied', lambda: True)
    with pytest.raises(module.RuntimeFailure, match='порт занят'): value._ensure()
    spawn.assert_not_called(); assert child.terminated == 0


def test_own_process_is_explicit_loopback_offline_and_owned_only(runtime, monkeypatch):
    value, child, job, spawn = runtime
    monkeypatch.setattr(value, 'probe', Mock(side_effect=[httpx.ConnectError('absent'), '0.40.14']))
    monkeypatch.setenv('OLLAMA_HOST', '0.0.0.0:11434')
    monkeypatch.setenv('OLLAMA_NO_CLOUD', '0')
    assert value._ensure() is True
    args, options = spawn.call_args
    assert args[0] == [str(value.bundle.parent/'engine/ollama.exe'),'serve']
    assert options['shell'] is False and options['env']['OLLAMA_HOST'] == '127.0.0.1:11540'
    assert options['env']['OLLAMA_NO_CLOUD'] == '1' and options['env']['OLLAMA_MODELS'] == str(value.models)
    assert value.status()['owned'] and value.status()['pid'] == child.pid
    value.close(); job.close.assert_called_once(); assert child.terminated == 1


@pytest.mark.parametrize('url', ['http://0.0.0.0:11434','https://127.0.0.1:11434','http://evil.test',
    'http://user:password@127.0.0.1:11434','http://127.0.0.1:11434/api/chat'])
def test_runtime_cannot_expose_or_redirect_endpoint(url):
    with pytest.raises(ValueError): module.OllamaRuntime(endpoint=url)._url()


def test_start_is_single_flight_and_nonblocking(runtime, monkeypatch):
    value, _, _, spawn = runtime
    entered, release = module.Event(), module.Event()
    def probe(): entered.set(); release.wait(2); return '0.40.14'
    monkeypatch.setattr(value, 'probe', probe)
    started = time.monotonic(); value.start(); value.start()
    assert time.monotonic()-started < .5 and entered.wait(1)
    release.set(); value.thread.join(2)
    assert value.status()['state'] == 'ready'; spawn.assert_not_called()


def test_failed_job_assignment_disposes_only_owned_process(runtime, monkeypatch):
    value, child, _, spawn = runtime
    monkeypatch.setattr(value, 'probe', Mock(side_effect=httpx.ConnectError('absent')))
    value.job_factory = Mock(side_effect=module.RuntimeFailure('job unavailable'))
    value._work()
    assert value.status()['state'] == 'error' and child.terminated == 1 and spawn.call_count == 1


def test_automatic_recovery_has_three_attempt_limit(runtime, monkeypatch):
    value, child, _, _ = runtime
    attempts=[]
    class Stop:
        def is_set(self): return False
        def wait(self, delay): return False
    value.stop=Stop()
    def ensure(): attempts.append(1); child.code=1; value.process=child; return True
    monkeypatch.setattr(value, '_ensure', ensure)
    value._work()
    assert len(attempts)==3 and value.status()['state']=='error'
    value.stop=module.Event()


@pytest.mark.skipif(module.os.name!='nt', reason='Windows bundle')
def test_manifest_tampering_is_rejected_before_launch(tmp_path):
    folder=tmp_path/'bundle';folder.mkdir()
    (folder/'ollama.exe').write_bytes(b'tampered')
    (folder/'runtime-manifest.json').write_text(json.dumps({'version':'0.40.14',
        'files':{'ollama.exe':hashlib.sha256(b'original').hexdigest()}}))
    value=module.OllamaRuntime(folder)
    with pytest.raises(module.RuntimeFailure, match='изменились'):value._executable()


def test_download_not_ready_when_actual_generation_fails(monkeypatch):
    import asyncio
    from localmind import model_catalog as cat
    original=httpx.AsyncClient
    transport=httpx.MockTransport(lambda request:httpx.Response(200,content=b'{"status":"success"}\n'))
    monkeypatch.setattr(cat.httpx,'AsyncClient',lambda **kw:original(transport=transport,**kw))
    monkeypatch.setattr(cat,'installed_detail',lambda name:{'digest':'real-fixture'})
    monkeypatch.setattr('localmind.model_manager.manager.verify_download',AsyncMock(side_effect=ValueError('probe failed')))
    from tests.test_model_catalog import prepare_job
    jobs=cat.DownloadJobs();key=prepare_job(jobs)
    asyncio.run(jobs._pull(key,'qwen3:4b-q4_K_M'))
    result=jobs.snapshot(key)
    assert result['status']=='failed' and not result.get('ready') and result['stage']=='inference_verification'


def test_cancelling_health_check_closes_actual_http_stream(monkeypatch, tmp_path):
    import asyncio
    from localmind import model_manager as manager_module
    entered, closed = [], []
    class Pending(httpx.AsyncByteStream):
        async def __aiter__(self):
            entered.append(True)
            await asyncio.sleep(30)
            yield b'{}'
        async def aclose(self): closed.append(True)
    original = httpx.AsyncClient
    transport = httpx.MockTransport(lambda request: httpx.Response(200,stream=Pending()))
    monkeypatch.setattr(manager_module.httpx,'AsyncClient',lambda **kw:original(transport=transport,**kw))
    monkeypatch.setattr(manager_module,'installed_detail',lambda name:{'digest':'fixture'})
    monkeypatch.setattr('localmind.model_memory.memory._cleanup_locked',lambda *a,**k:None)
    async def run():
        task=asyncio.create_task(manager_module.ModelManager(tmp_path/'active.json').verify_download('qwen3:4b'))
        for _ in range(100):
            if entered: break
            await asyncio.sleep(.01)
        assert entered
        task.cancel()
        with pytest.raises(asyncio.CancelledError):await task
    asyncio.run(run())
    assert closed
