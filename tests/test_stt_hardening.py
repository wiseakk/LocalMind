"""Identity, resource selection and capture bounds; these do not measure ASR quality."""
import hashlib
import io
import json
import math
import struct
import wave

import pytest

from localmind import voice, voice_diagnostics, resource_setup


def test_pinned_profiles_prepare_only_their_own_model():
    for profile, model in [('cpu-fast', 'small'), ('balanced', 'small'), ('gpu-quality', 'medium')]:
        assets = resource_setup.assets_for('asr', profile)
        assert len(assets) == 4
        assert {a['path'].split('/')[1] for a in assets} == {model}
        assert sum(a['bytes'] for a in assets) > 100_000_000
        assert all('/resolve/' in a['url'] and len(a['sha256']) == 64 for a in assets)
    with pytest.raises(ValueError):
        resource_setup.assets_for('asr', '../../outside')
    assert resource_setup.assets_for('tts', 'cpu-fast') == resource_setup.assets_for('tts', 'balanced')


def test_profile_status_separates_unprepared_resources(tmp_path, monkeypatch):
    monkeypatch.setattr(resource_setup, 'MODELS', tmp_path)
    monkeypatch.setattr(resource_setup, 'dependencies', lambda _: True)
    rows = resource_setup.status()
    assert [(r['kind'], r['profile']) for r in rows] == [
        ('asr', 'cpu-fast'), ('asr', 'balanced'), ('asr', 'gpu-quality'), ('tts', None)]
    assert all(r['state'] == 'model_missing' for r in rows)
    assert [r['profile'] for r in rows if r['required'] and r['kind'] == 'asr'] == [voice.default_stt_profile()]


def test_worker_fingerprint_binds_provenance_to_actual_file_hashes(tmp_path, monkeypatch):
    from localmind import paths
    config = tmp_path / 'config'; config.mkdir()
    directory = tmp_path / 'whisper/small'; directory.mkdir(parents=True)
    assets = []
    for name in ('model.bin', 'config.json', 'tokenizer.json', 'vocabulary.txt'):
        data = (name + ': actual local bytes').encode()
        (directory / name).write_bytes(data)
        assets.append({'path': 'whisper/small/' + name, 'bytes': len(data),
                       'sha256': hashlib.sha256(data).hexdigest(),
                       'url': 'https://huggingface.co/Systran/faster-whisper-small/resolve/reviewed/' + name})
    (config / 'voice_resources.json').write_text(json.dumps({'assets': assets}), encoding='utf-8')
    monkeypatch.setattr(paths, 'APP_ROOT', tmp_path)
    identity = voice_diagnostics.resource_identity(directory)
    assert identity['path'] == str(directory.resolve())
    assert identity['provenance'] == 'pinned manifest'
    assert len(identity['source_urls']) == 4
    (directory / 'model.bin').write_bytes(b'replaced weights')
    changed = voice_diagnostics.resource_identity(directory)
    assert changed['files']['model.bin']['sha256'] != identity['files']['model.bin']['sha256']
    assert changed['provenance'] == 'local files; origin unconfirmed'
    assert changed['source_urls'] == []


def test_legacy_default_never_accepts_an_arbitrary_model_path(monkeypatch):
    for value, expected in [('base', 'cpu-fast'), ('small', 'balanced'), ('medium', 'gpu-quality'),
                            ('C:/outside/model', 'balanced'), ('large-v3', 'balanced')]:
        monkeypatch.setenv('WHISPER_MODEL', value)
        assert voice.default_stt_profile() == expected
    monkeypatch.delenv('WHISPER_MODEL')
    assert voice.default_stt_profile() == 'balanced'


def test_base_is_not_supported_and_existing_files_are_preserved(tmp_path, monkeypatch):
    from localmind import resource_integrity
    legacy = tmp_path / 'whisper/base/model.bin'
    legacy.parent.mkdir(parents=True)
    legacy.write_bytes(b'owner model must remain')
    monkeypatch.setattr(resource_integrity, 'MODELS', tmp_path)
    assert {p['model'] for p in voice.PROFILES.values()} == {'small', 'medium'}
    assert {a['path'].split('/')[1] for a in resource_setup.MANIFEST['assets']
            if a['path'].startswith('whisper/')} == {'small', 'medium'}
    with pytest.raises(ValueError, match='Неизвестная модель'):
        resource_integrity.verify_resources('asr', 'base')
    assert legacy.read_bytes() == b'owner model must remain'


def test_legacy_base_requires_small_preparation_without_inference(tmp_path, monkeypatch):
    directory = tmp_path / 'whisper/base'
    directory.mkdir(parents=True)
    for name in ('model.bin', 'config.json', 'tokenizer.json'):
        (directory / name).write_bytes(b'old base model')
    monkeypatch.setattr(voice, 'MODELS', tmp_path)
    monkeypatch.setenv('WHISPER_MODEL', 'base')
    monkeypatch.setattr(voice, '_installed', lambda _: True)
    monkeypatch.setattr(voice._asr_worker, 'transcribe', lambda *a: pytest.fail('Missing small reached inference'))
    with pytest.raises(voice.VoiceError, match='Подготовить голос') as error:
        voice.transcribe_audio(b'x' * 128, '.wav')
    assert error.value.status_code == 503
    assert len(list(directory.iterdir())) == 3


def test_explicit_profile_wins_over_legacy_base_preference(monkeypatch):
    seen = []
    monkeypatch.setenv('WHISPER_MODEL', 'base')
    monkeypatch.setattr(voice, '_installed', lambda _: True)
    monkeypatch.setattr(voice, '_stt_ready', lambda profile: seen.append(profile) or True)
    monkeypatch.setattr(voice._asr_worker, 'transcribe', lambda data, suffix, profile, decoding: {'profile': profile})
    assert voice.transcribe_audio(b'x' * 128, '.wav', 'gpu-quality')['profile'] == 'gpu-quality'
    assert voice.transcribe_audio(b'x' * 128, '.wav')['profile'] == 'cpu-fast'
    assert seen == ['gpu-quality', 'cpu-fast']


def test_shared_small_profiles_cannot_prepare_simultaneously(monkeypatch):
    from localmind.download_store import JobStore
    class PendingThread:
        def __init__(self, **kwargs): pass
        def start(self): pass
    monkeypatch.setattr(resource_setup, 'store', JobStore())
    monkeypatch.setattr(resource_setup, '_controls', {})
    monkeypatch.setattr(resource_setup, '_threads', {})
    monkeypatch.setattr(resource_setup, '_closing', False)
    monkeypatch.setattr(resource_setup, 'dependencies', lambda _: True)
    monkeypatch.setattr(resource_setup.threading, 'Thread', PendingThread)
    first = resource_setup.start('asr', 'cpu-fast')
    with pytest.raises(ValueError, match='этого ресурса уже выполняется'):
        resource_setup.start('asr', 'balanced')
    assert resource_setup.store.snapshot()[0]['id'] == first['id']
    assert resource_setup.verification_key('asr', 'cpu-fast') == resource_setup.verification_key('asr', 'balanced')


def test_model_download_lock_excludes_cli_and_http_until_released(tmp_path):
    from localmind.resource_lock import model_download_lock, ResourceBusyError
    with model_download_lock(tmp_path, 'small'):
        with pytest.raises(ResourceBusyError, match='другом процессе'):
            with model_download_lock(tmp_path, 'small'):
                pytest.fail('Concurrent setup acquired the same model')
        with model_download_lock(tmp_path, 'medium'):
            pass
    with model_download_lock(tmp_path, 'small'):
        pass
    with pytest.raises(ValueError, match='Неизвестная модель'):
        with model_download_lock(tmp_path, 'base'):
            pytest.fail('Base must not be downloadable')


def test_shared_small_verification_and_manifest_upgrade_do_not_delete_models(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from localmind.download_store import JobStore
    assets = []
    for model in ('small', 'medium'):
        for name in ('model.bin', 'config.json', 'tokenizer.json', 'vocabulary.txt'):
            data = (model + name).encode()
            path = tmp_path / 'models/whisper' / model / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
            assets.append({'path': f'whisper/{model}/{name}', 'bytes': len(data),
                           'sha256': hashlib.sha256(data).hexdigest(), 'url': 'https://invalid.test/never-requested'})
    data = b'tts'
    path = tmp_path / 'models/silero/voice.pt'; path.parent.mkdir(parents=True); path.write_bytes(data)
    assets.append({'path': 'silero/voice.pt', 'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()})
    old = tmp_path / 'models/whisper/base/model.bin'; old.parent.mkdir(parents=True); old.write_bytes(b'legacy')
    monkeypatch.setattr(resource_setup, 'MODELS', tmp_path / 'models')
    monkeypatch.setattr(resource_setup, 'PRIVATE', tmp_path / 'private')
    monkeypatch.setattr(resource_setup, 'MANIFEST', {'version': 2, 'assets': assets})
    monkeypatch.setattr(resource_setup, 'dependencies', lambda _: True)
    monkeypatch.setattr(resource_setup, 'store', JobStore())
    monkeypatch.setattr(resource_setup, '_controls', {})
    monkeypatch.setattr(resource_setup, '_run_probe', lambda *a, **k: SimpleNamespace(returncode=0))
    monkeypatch.setattr(resource_setup.httpx, 'stream', lambda *a, **k: pytest.fail('Verified files must not download'))
    resource_setup.store.insert({'id': 'prepare', 'status': 'verifying'})
    resource_setup._prepare('prepare', 'asr', resource_setup.threading.Event(), 'cpu-fast')
    rows = resource_setup.status()
    assert [r['state'] for r in rows[:2]] == ['ready', 'ready']
    resource_setup.MANIFEST['version'] = 3
    assert [r['state'] for r in resource_setup.status()[:2]] == ['unverified', 'unverified']
    assert old.read_bytes() == b'legacy'
    assert all((tmp_path / 'models' / a['path']).is_file() for a in assets)


@pytest.mark.parametrize('profile,model', [('cpu-fast', 'small'), ('balanced', 'small'), ('gpu-quality', 'medium')])
@pytest.mark.parametrize('phrase', ['Как сварить пельмени?', 'Не открывай калькулятор',
                                  'Не закрывай блокнот', 'Расскажи как открыть калькулятор'])
def test_russian_onset_and_negation_pass_through_without_actions(monkeypatch, profile, model, phrase):
    """A stub tests preservation and intent safety, never recognition accuracy."""
    import sys
    from pathlib import Path
    from types import SimpleNamespace
    from localmind.intents import parse_app_intent
    class Model:
        def __init__(self, directory, **options):
            assert Path(directory).name == model
            assert options['local_files_only']
        def transcribe(self, signal, **options):
            assert options['language'] == 'ru'
            assert options['condition_on_previous_text'] is False
            return [SimpleNamespace(text=' ' + phrase + ' ')], SimpleNamespace(language='ru')
    monkeypatch.setitem(sys.modules, 'faster_whisper', SimpleNamespace(WhisperModel=Model))
    monkeypatch.setattr(voice, '_decode_bounded', lambda _: [.1] * 16000)
    result = voice._recognize(Path('unused.wav'), profile)
    assert result['text'] == phrase
    assert parse_app_intent(result['text'], {'calculator': ('калькулятор',), 'notepad': ('блокнот',)}) is None


def test_loaded_diagnostics_come_from_reply_without_retaining_transcript(monkeypatch):
    from tests.test_asr_worker import fake_worker
    worker, _ = fake_worker(monkeypatch)
    original_send = worker._send
    def send(frame):
        original_send(frame)
        reply = worker.replies.get_nowait()
        reply.update(resource={'path': 'C:/actual/model'}, resources={'rss_bytes': 1234},
                     profile='balanced', device='cpu', compute_type='int8')
        worker.replies.put_nowait(reply)
    monkeypatch.setattr(worker, '_send', send)
    assert worker.diagnostics()['state'] == 'not_loaded'
    worker.transcribe(b'x' * 128, '.wav', 'balanced', 'baseline')
    diagnostics = worker.diagnostics()
    assert diagnostics['state'] == 'loaded'
    assert diagnostics['loaded']['resource']['path'] == 'C:/actual/model'
    assert 'text' not in diagnostics['loaded'] and 'audio' not in diagnostics['loaded']
    worker.close()
    assert worker.diagnostics()['state'] == 'not_loaded'


def test_real_resampler_preserves_onset_and_48khz_stereo_duration(tmp_path):
    pytest.importorskip('av'); np = pytest.importorskip('numpy')
    stream = io.BytesIO()
    with wave.open(stream, 'wb') as audio:
        audio.setnchannels(2); audio.setsampwidth(2); audio.setframerate(48000)
        audio.writeframes(b''.join(struct.pack('<hh', *([int(6000 * math.sin(i * .05))] * 2))
                                   for i in range(48000)))
    source = tmp_path / 'stereo.wav'; source.write_bytes(stream.getvalue())
    signal = voice._decode_bounded(source)
    assert len(signal) == 16000
    assert np.sqrt(np.mean(signal[:1600] ** 2)) > .05
    assert np.sqrt(np.mean(signal[-1600:] ** 2)) > .05


def test_resource_measurements_do_not_turn_unavailable_vram_into_zero():
    measurement = voice_diagnostics.resource_measurement()
    assert measurement['vram_bytes'] is None or measurement['vram_bytes'] >= 0
    assert 'not peak' in measurement['sample']


def test_optional_process_measurement_failure_never_fails_inference(monkeypatch):
    import sys
    from types import SimpleNamespace

    def unavailable():
        raise RuntimeError('Optional process information unavailable')

    monkeypatch.setitem(sys.modules, 'psutil', SimpleNamespace(Process=unavailable))
    result = voice_diagnostics.resource_measurement()
    assert result['rss_bytes'] is None


def test_empty_asr_reply_reports_the_still_loaded_model(monkeypatch):
    import base64
    from types import SimpleNamespace
    from localmind import stt_worker
    recognizer = SimpleNamespace(model=None, resource={'path':'C:/actual/small'}, runtime={'python':'3.11'},
                                 device='cpu', compute_type='int8', fallback=False)
    monkeypatch.setattr(voice, 'Recognizer', lambda: recognizer)
    def empty_result(*args, **kwargs):
        recognizer.model = SimpleNamespace(model=SimpleNamespace(device='cpu', compute_type='int8'))
        raise voice.VoiceError(422, 'Речь не обнаружена.')
    monkeypatch.setattr(voice, '_recognize', empty_result)
    frame = {'id':'a'*32, 'audio':base64.b64encode(b'x'*128).decode(), 'suffix':'.wav', 'decoding':'baseline'}
    output = io.StringIO()
    monkeypatch.setattr(stt_worker.sys, 'argv', ['stt_worker', 'balanced'])
    monkeypatch.setattr(stt_worker.sys, 'stdin', SimpleNamespace(buffer=io.BytesIO((json.dumps(frame)+'\n').encode())))
    monkeypatch.setattr(stt_worker.sys, 'stdout', output)
    stt_worker.main()
    response = json.loads(output.getvalue().splitlines()[-1])
    assert response['status_code'] == 422
    assert response['loaded_diagnostics']['resource']['path'] == 'C:/actual/small'
    assert response['loaded_diagnostics']['device'] == 'cpu'
    assert response['loaded_diagnostics']['last_request_state'] == 'rejected'
    assert 'text' not in response['loaded_diagnostics'] and 'audio' not in response['loaded_diagnostics']


def test_supervisor_updates_loaded_identity_on_domain_failure_without_audio_retention(monkeypatch):
    from tests.test_asr_worker import fake_worker
    worker, _ = fake_worker(monkeypatch)
    original_send = worker._send
    def send(frame):
        original_send(frame)
        reply = worker.replies.get_nowait()
        worker.replies.put_nowait({'id':reply['id'], 'error':'Речь не обнаружена.', 'status_code':422,
            'loaded_diagnostics':{'model':'small', 'resource':{'path':'C:/actual/small'},
                                  'device':'cpu', 'last_request_state':'rejected',
                                  'audio':'must never be retained', 'text':'must never be retained'}})
    monkeypatch.setattr(worker, '_send', send)
    with pytest.raises(voice.VoiceError):
        worker.transcribe(b'x'*128, '.wav', 'balanced', 'baseline')
    diagnostics = worker.diagnostics()
    assert diagnostics['state'] == 'loaded'
    assert diagnostics['loaded']['resource']['path'] == 'C:/actual/small'
    assert 'audio' not in diagnostics['loaded'] and 'text' not in diagnostics['loaded']
    assert diagnostics['measurements'] == {}
    worker.close()
