"""Voice bounds and real decoding; model/accelerator calls are mocked."""
import io
from contextlib import contextmanager
import json
from pathlib import Path
import subprocess
from types import SimpleNamespace
from unittest import mock
import wave

import pytest

from localmind import voice


@pytest.fixture(autouse=True)
def worker_scratch(tmp_path, monkeypatch):
    @contextmanager
    def local_directory(**kwargs):
        directory = tmp_path / 'voice-worker'
        directory.mkdir()
        try:
            yield str(directory)
        finally:
            for entry in directory.iterdir():
                entry.unlink()
            directory.rmdir()
    monkeypatch.setattr(voice, '_temporary_directory', local_directory)


def wav_bytes(seconds=1, amplitude=2000):
    import math
    import struct
    stream = io.BytesIO()
    with wave.open(stream, 'wb') as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(16000)
        output.writeframes(b''.join(struct.pack('<h', int(amplitude * math.sin(i * 0.1))) for i in range(int(seconds * 16000))))
    return stream.getvalue()


def test_upload_validation_runs_before_model_loading():
    with pytest.raises(voice.VoiceError) as error:
        voice.transcribe_audio(b'x' * (voice.MAX_UPLOAD_BYTES + 1), '.wav')
    assert error.value.status_code == 413
    with pytest.raises(voice.VoiceError) as error:
        voice.transcribe_audio(b'x' * 128, '.exe')
    assert error.value.status_code == 415
    with pytest.raises(voice.VoiceError):
        voice.transcribe_audio(b'x' * 128, '.wav', '../model')


def test_missing_assets_never_start_a_worker_or_download():
    with mock.patch.object(voice, '_installed', return_value=True), mock.patch.object(voice, '_stt_ready', return_value=False), mock.patch.object(voice, '_run_worker') as worker:
        with pytest.raises(voice.VoiceError, match='setup-stt'):
            voice.transcribe_audio(b'x' * 1024, '.wav')
    worker.assert_not_called()
    with mock.patch.object(voice, '_installed', return_value=False), mock.patch.object(voice, '_run_worker') as worker:
        with pytest.raises(voice.VoiceError, match='setup-tts'):
            voice.synthesize_speech('Привет')
    worker.assert_not_called()


def test_tts_limits_and_voice_allowlist():
    for text, selection in [('', voice.DEFAULT_VOICE), ('a' * 1201, voice.DEFAULT_VOICE), ('Привет', '../../evil')]:
        with pytest.raises(voice.VoiceError) as error:
            voice.synthesize_speech(text, selection)
        assert error.value.status_code == 422


def test_worker_timeout_releases_slot_and_cleans_files():
    observed = []

    def timeout(command, **kwargs):
        observed.append(Path(command[-3]).parent)
        assert kwargs['shell'] is False
        assert kwargs['env']['HF_HUB_OFFLINE'] == '1'
        raise subprocess.TimeoutExpired(command, 120)

    with mock.patch.object(voice.subprocess, 'run', side_effect=timeout):
        with pytest.raises(voice.VoiceError) as error:
            voice._run_worker('stt', 'balanced', b'data', '.wav')
    assert error.value.status_code == 504
    assert not observed[0].exists()
    assert voice._operation.acquire(blocking=False)
    voice._operation.release()


def test_concurrent_voice_requests_are_rejected():
    assert voice._operation.acquire(blocking=False)
    try:
        with pytest.raises(voice.VoiceError) as error:
            voice._run_worker('stt', 'balanced', b'data', '.wav')
        assert error.value.status_code == 429
    finally:
        voice._operation.release()


def test_worker_returns_text_and_no_execution(tmp_path):
    seen = []

    def fake(command, **kwargs):
        source, result = Path(command[-3]), Path(command[-2])
        seen.append(source.parent)
        assert source.read_bytes() == b'voice'
        result.write_text(json.dumps({'text': 'Открой блокнот', 'device': 'cpu'}), encoding='utf-8')

    with mock.patch.object(voice.subprocess, 'run', side_effect=fake):
        result, audio = voice._run_worker('stt', 'balanced', b'voice', '.wav')
    assert result['text'] == 'Открой блокнот'
    assert audio == b''
    assert not seen[0].exists()


def test_real_audio_decoder_handles_speechlike_signal_silence_corrupt_and_duration(tmp_path):
    pytest.importorskip('av')
    pytest.importorskip('numpy')
    recording = tmp_path / 'voice.wav'
    recording.write_bytes(wav_bytes())
    signal = voice._decode_bounded(recording)
    assert len(signal) == 16000
    recording.write_bytes(wav_bytes(amplitude=0))
    with pytest.raises(voice.VoiceError, match='Речь не обнаружена'):
        voice._decode_bounded(recording)
    recording.write_bytes(wav_bytes(seconds=31))
    with pytest.raises(voice.VoiceError) as error:
        voice._decode_bounded(recording)
    assert error.value.status_code == 413
    recording.write_bytes(b'corrupt' * 100)
    with pytest.raises(Exception):
        voice._decode_bounded(recording)


def test_gpu_failure_retries_cpu_with_local_only_multilingual_model():
    calls = []

    class Model:
        def __init__(self, model, **kwargs):
            calls.append((model, kwargs))
            if kwargs['device'] == 'cuda':
                raise RuntimeError('CUDA unavailable')

        def transcribe(self, signal, **kwargs):
            assert kwargs['language'] == 'ru'
            assert kwargs['vad_filter'] is True
            assert 'Obsidian' in kwargs['initial_prompt']
            return [SimpleNamespace(text=' Блокнот ')], None

    fake = SimpleNamespace(WhisperModel=Model)
    with mock.patch.dict('sys.modules', {'faster_whisper': fake}), mock.patch.object(voice, '_decode_bounded', return_value=[1] * 16000):
        result = voice._recognize(Path('not-opened.wav'), 'gpu-quality')
    assert result['device'] == 'cpu'
    assert result['fallback'] is True
    assert result['text'] == 'Блокнот'
    assert calls[0][0].endswith('medium')
    assert calls[1][1]['local_files_only'] is True
    assert calls[1][1]['compute_type'] == 'int8'


def test_piper_generates_wav_from_literal_text_without_shell(tmp_path):
    source, destination = tmp_path / 'input.txt', tmp_path / 'output.wav'
    source.write_text('Не удалось открыть приложение.', encoding='utf-8')
    seen = []

    class Piper:
        @staticmethod
        def load(path, **options):
            assert path.endswith(voice.DEFAULT_VOICE + '.onnx')
            assert options == {'use_cuda': False}
            return Piper()

        def synthesize_wav(self, text, output):
            seen.append(text)
            output.setnchannels(1)
            output.setsampwidth(2)
            output.setframerate(22050)
            output.writeframes(b'\x00\x00' * 100)

    with mock.patch.dict('sys.modules', {'piper': SimpleNamespace(PiperVoice=Piper)}):
        result = voice._synthesize(source, voice.DEFAULT_VOICE, destination)
    assert seen == ['Не удалось открыть приложение.']
    assert destination.read_bytes().startswith(b'RIFF')
    assert result['voice'] == voice.DEFAULT_VOICE


def test_worker_suppresses_native_diagnostics_and_audio_details(tmp_path):
    result = tmp_path / 'result.json'
    with mock.patch.object(voice, '_recognize', side_effect=RuntimeError('secret model path or transcript')):
        voice._worker('stt', 'balanced', tmp_path / 'source', result, tmp_path / 'audio')
    assert 'secret' not in result.read_text(encoding='utf-8')
    assert json.loads(result.read_text(encoding='utf-8'))['status_code'] == 422


def test_real_isolated_worker_rejects_silence_without_model_assets():
    pytest.importorskip('av')
    pytest.importorskip('faster_whisper')
    with pytest.raises(voice.VoiceError, match='Речь не обнаружена') as error:
        voice._run_worker('stt', 'balanced', wav_bytes(amplitude=0), '.wav')
    assert error.value.status_code == 422


def test_uploaded_playlist_cannot_be_sniffed_as_network_media(tmp_path):
    pytest.importorskip('av')
    recording = tmp_path / 'voice.wav'
    recording.write_text('#EXTM3U\n#EXT-X-TARGETDURATION:10\n#EXTINF:10,\nhttp://127.0.0.1:1/private.wav\n', encoding='utf-8')
    with pytest.raises(Exception):
        voice._decode_bounded(recording)


def test_evaluation_metrics_have_known_edit_distance():
    from scripts.eval_stt import score, percentile
    assert score('Ёж, ест суп!', 'еж ест сок') == {
        'word_errors': 1, 'words': 3, 'character_errors': 2, 'characters': 8,
    }
    assert percentile([], 0.95) is None
    assert percentile([9, 1, 3, 5], 0.5) == 3
    assert percentile([9, 1, 3, 5], 0.95) == 9


@pytest.mark.parametrize('payload', ['[]', '{"error":[],"status_code":503}', '{"error":"bad","status_code":200}'])
def test_malformed_worker_output_fails_closed(payload):
    def fake(command, **kwargs):
        Path(command[-2]).write_text(payload, encoding='utf-8')
    with mock.patch.object(voice.subprocess, 'run', side_effect=fake):
        with pytest.raises(voice.VoiceError) as error:
            voice._run_worker('stt', 'balanced', b'voice', '.wav')
    assert error.value.status_code == 503


def test_unwritable_temporary_storage_returns_clear_safe_error(monkeypatch):
    def unavailable(**kwargs):
        raise PermissionError('private temporary path')
    monkeypatch.setattr(voice, '_temporary_directory', unavailable)
    with pytest.raises(voice.VoiceError) as error:
        voice._run_worker('stt', 'balanced', b'voice', '.wav')
    assert error.value.status_code == 503
    assert 'Временное хранилище' in error.value.detail
    assert 'private' not in error.value.detail
    assert voice._operation.acquire(blocking=False)
    voice._operation.release()
