"""Strict STT JSON boundaries. Generated audio/model doubles are not microphone evidence."""
import io
import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
import wave

from fastapi.testclient import TestClient
import pytest

from localmind import asr_worker, server, voice
from localmind.voice_diagnostics import normalize_stt_payload


BAD_NUMBERS = [float('nan'), float('inf'), -float('inf')]
FIELDS = ['mean_segment_logprob', 'max_no_speech_probability']


def strict_roundtrip(payload):
    return json.loads(json.dumps(payload, allow_nan=False))


@pytest.mark.parametrize('bad', BAD_NUMBERS)
@pytest.mark.parametrize('field', FIELDS)
def test_nested_normalizer_preserves_text_types_and_paths(bad, field, caplog):
    text = '  Не открывай Obsidian!\nNaN Infinity — слова.  '
    payload = {'text': text, 'quality': {field: bad},
               'diagnostics': {'segments': [{'values': [True, False, None, 2, .5, bad]}]},
               'odd.key': {'value': bad}}
    result = normalize_stt_payload(payload)
    assert result['text'] == text
    assert result['quality'][field] is None
    assert result['diagnostics']['segments'][0]['values'] == [True, False, None, 2, .5, None]
    assert result['diagnostics']['non_finite_fields'] == [
        'quality.' + field, 'diagnostics.segments[0].values[5]', '["odd.key"].value']
    assert isinstance(payload['quality'][field], float)  # no mutation
    assert normalize_stt_payload(result) == result  # original paths survive every boundary
    assert strict_roundtrip(result) == result
    assert caplog.text == ''


@pytest.mark.parametrize('bad', BAD_NUMBERS)
@pytest.mark.parametrize('field', FIELDS)
def test_quality_contamination_never_reloads_model_or_hides_in_max(monkeypatch, bad, field):
    loads = []

    class Model:
        def transcribe(self, signal, **options):
            segments = [SimpleNamespace(text='Не открывай', avg_logprob=-.2, no_speech_prob=.1),
                        SimpleNamespace(text='Obsidian', avg_logprob=-.3, no_speech_prob=.2)]
            setattr(segments[1], 'avg_logprob' if field == FIELDS[0] else 'no_speech_prob', bad)
            return segments, SimpleNamespace(language='ru')

    class Recognizer(voice.Recognizer):
        def load(self, *args):
            reused = self.model is not None
            if not reused:
                loads.append(args)
                self.model = Model()
            return self.model, 0, reused

    monkeypatch.setattr(voice, '_decode_bounded', lambda _: [.1] * 16000)
    recognizer = Recognizer()
    for reused in (False, True):
        result = voice._recognize(Path('input.wav'), 'gpu-quality', recognizer=recognizer)
        assert result['text'] == 'Не открывай Obsidian'
        assert result['quality'][field] is None
        assert result['quality']['review_recommended'] is True
        assert result['diagnostics']['non_finite_fields'] == ['quality.' + field]
        assert result['model_reused'] is reused and result['fallback'] is False
        strict_roundtrip(result)
    assert len(loads) == 1


def test_aggregation_overflow_is_reported_without_gpu_fallback(monkeypatch):
    model = SimpleNamespace(transcribe=lambda *args, **kwargs: (
        [SimpleNamespace(text='текст', avg_logprob=1.7e308) for _ in range(2)], None))
    recognizer = voice.Recognizer()
    monkeypatch.setattr(recognizer, 'load', lambda *args: (model, 0, True))
    monkeypatch.setattr(voice, '_decode_bounded', lambda _: [.1] * 16000)
    result = voice._recognize(Path('input.wav'), 'gpu-quality', recognizer=recognizer)
    assert result['text'] == 'текст текст' and result['fallback'] is False
    assert result['quality'][FIELDS[0]] is None
    assert result['quality']['review_recommended'] is True
    assert result['diagnostics']['non_finite_fields'] == ['quality.' + FIELDS[0]]
    strict_roundtrip(result)


@pytest.mark.parametrize('bad', BAD_NUMBERS)
def test_http_renders_contaminated_worker_reply_as_strict_json(monkeypatch, bad):
    payload = {'text': ' Не меняйте текст! ', 'quality': {FIELDS[0]: bad},
               'diagnostics': {'nested': [{'timing': bad}]}}
    monkeypatch.setattr(server, 'transcribe_audio', lambda *args: payload)
    client = TestClient(server.app, base_url='http://127.0.0.1', client=('127.0.0.1', 12345))
    for _ in range(2):
        response = client.post('/api/transcribe', files={'audio': ('voice.webm', b'x' * 128)})
        assert response.status_code == 200
        result = strict_roundtrip(response.json())
        assert result['text'] == payload['text']
        assert result['diagnostics']['non_finite_fields'] == [
            'quality.' + FIELDS[0], 'diagnostics.nested[0].timing']


def test_actual_missing_multipart_validation_body():
    client = TestClient(server.app, base_url='http://127.0.0.1', client=('127.0.0.1', 12345))
    response = client.post('/api/transcribe', data={'profile': 'balanced'})
    assert response.status_code == 422
    detail = response.json()['detail'][0]
    assert detail['loc'] == ['body', 'audio']
    assert detail['msg'] == 'Field required'


@pytest.mark.parametrize('data,suffix,status', [
    (b'', '.webm', 422), (b'x' * 100, '.wav', 422),
    (b'x' * 128, '.exe', 415), (b'x' * (voice.MAX_UPLOAD_BYTES + 1), '.wav', 413),
], ids=['empty', 'short', 'unsupported', 'too-large'])
def test_http_invalid_upload_remains_meaningful_4xx(data, suffix, status):
    client = TestClient(server.app, base_url='http://127.0.0.1', client=('127.0.0.1', 12345))
    response = client.post('/api/transcribe', files={'audio': ('voice' + suffix, data)})
    assert response.status_code == status
    assert isinstance(response.json()['detail'], str) and len(response.json()['detail']) > 10


def generated_wav(seconds=1, silence=False):
    stream = io.BytesIO()
    with wave.open(stream, 'wb') as recording:
        recording.setnchannels(1)
        recording.setsampwidth(2)
        recording.setframerate(16000)
        recording.writeframes((b'\0\0' if silence else b'\0\x10') * int(seconds * 16000))
    return stream.getvalue()


def test_real_framed_process_recovers_from_invalid_audio_and_reuses_model(monkeypatch):
    pytest.importorskip('av')
    # Real stdin/stdout transport and PyAV decoder; only the neural model is a double.
    # Inject contamination AFTER _recognize to exercise the worker's own boundary.
    code = '''
import sys
from types import SimpleNamespace
from localmind import voice, stt_worker
class Model:
    def transcribe(self, *args, **kwargs):
        return [SimpleNamespace(text="unchanged transcript")], None
def load(self, *args):
    reused = self.model is not None
    self.model = self.model or Model()
    return self.model, 0, reused
voice.Recognizer.load = load
original = voice._recognize
def recognize(*args, **kwargs):
    result = original(*args, **kwargs)
    result['quality']['mean_segment_logprob'] = float('nan')
    result['diagnostics'] = {'nested': [float('inf'), -float('inf')]}
    return result
voice._recognize = recognize
stt_worker.main()
'''
    original_popen = subprocess.Popen
    starts = []

    def popen(command, **options):
        starts.append(command)
        return original_popen([sys.executable, '-c', code, command[-1]], **options)

    monkeypatch.setattr(asr_worker.subprocess, 'Popen', popen)
    worker = asr_worker.WarmASRWorker()
    monkeypatch.setattr(voice, '_asr_worker', worker)
    monkeypatch.setattr(voice, '_installed', lambda _: True)
    monkeypatch.setattr(voice, '_stt_ready', lambda _: True)
    client = TestClient(server.app, base_url='http://127.0.0.1', client=('127.0.0.1', 12345))
    # Supervised frame consumer must see strict JSON bytes, before normalization.
    def read(stream, replies):
        def reject_constant(value):
            raise AssertionError('Non-standard JSON token on worker pipe')
        while raw := stream.readline(12 * 1024 * 1024 + 1):
            replies.put(json.loads(raw, parse_constant=reject_constant))
    monkeypatch.setattr(worker, '_read', read)
    try:
        for reused in (False, True, True):
            response = client.post('/api/transcribe', files={'audio': ('voice.wav', generated_wav())})
            assert response.status_code == 200
            result = response.json()
            assert result['text'] == 'unchanged transcript'
            assert result['model_reused'] is reused
            assert result['diagnostics']['non_finite_fields'] == [
                'quality.mean_segment_logprob', 'diagnostics.nested[0]', 'diagnostics.nested[1]']
            strict_roundtrip(result)
            for invalid in (b'corrupt' * 100, generated_wav(.05), generated_wav(silence=True)):
                response = client.post('/api/transcribe', files={'audio': ('voice.wav', invalid)})
                assert response.status_code == 422
                assert isinstance(response.json()['detail'], str) and len(response.json()['detail']) > 10
                assert worker.process.poll() is None
        assert len(starts) == 1
    finally:
        worker.close()


@pytest.mark.parametrize('bad', BAD_NUMBERS)
def test_asr_consumer_defends_against_older_contaminated_frames(monkeypatch, bad):
    from test_asr_worker import fake_worker
    worker, calls = fake_worker(monkeypatch)

    def send(frame):
        request = json.loads(frame)
        response = {'id': request['id'], 'text': 'текст', 'quality': {FIELDS[1]: bad}}
        stream = io.BytesIO((json.dumps(response) + '\n').encode())
        worker._read(stream, worker.replies)

    monkeypatch.setattr(worker, '_send', send)
    try:
        result = worker.transcribe(b'x' * 128, '.wav', 'balanced', 'baseline')
        assert result['text'] == 'текст' and result['quality'][FIELDS[1]] is None
        assert result['diagnostics']['non_finite_fields'] == ['quality.' + FIELDS[1]]
        strict_roundtrip(result)
    finally:
        worker.close()


def test_legacy_stt_result_file_is_strict_json(tmp_path, monkeypatch):
    monkeypatch.setattr(voice, '_recognize', lambda *args: {
        'text': 'исходный текст', 'quality': {FIELDS[0]: float('inf')},
        'diagnostics': {'nested': [float('nan')]}})
    result = tmp_path / 'result.json'
    voice._worker('stt', 'balanced', tmp_path / 'input.wav', result, tmp_path / 'out.wav')
    payload = json.loads(result.read_text(encoding='utf-8'))
    assert payload['text'] == 'исходный текст'
    assert payload['diagnostics']['non_finite_fields'] == [
        'quality.' + FIELDS[0], 'diagnostics.nested[0]']
    strict_roundtrip(payload)


def test_rejected_legacy_frame_cannot_poison_cached_diagnostics(monkeypatch):
    from test_asr_worker import fake_worker
    worker, _ = fake_worker(monkeypatch)

    def send(frame):
        request = json.loads(frame)
        worker.replies.put({'id': request['id'], 'error': 'Речь не обнаружена.', 'status_code': 422,
                            'loaded_diagnostics': {'model': 'small', 'runtime': {'timing': float('nan')}}})

    monkeypatch.setattr(worker, '_send', send)
    try:
        with pytest.raises(voice.VoiceError):
            worker.transcribe(b'x' * 128, '.wav', 'balanced', 'baseline')
        result = worker.diagnostics()
        assert result['state'] == 'loaded'
        assert result['loaded']['runtime']['timing'] is None
        strict_roundtrip(result)
    finally:
        worker.close()
