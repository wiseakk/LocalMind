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
    for profile, model in [('cpu-fast', 'base'), ('balanced', 'small'), ('gpu-quality', 'medium')]:
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
    directory = tmp_path / 'whisper/base'; directory.mkdir(parents=True)
    assets = []
    for name in ('model.bin', 'config.json', 'tokenizer.json', 'vocabulary.txt'):
        data = (name + ': actual local bytes').encode()
        (directory / name).write_bytes(data)
        assets.append({'path': 'whisper/base/' + name, 'bytes': len(data),
                       'sha256': hashlib.sha256(data).hexdigest(),
                       'url': 'https://huggingface.co/Systran/faster-whisper-base/resolve/reviewed/' + name})
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
