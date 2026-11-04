"""ASR supervision and measured-report regressions; no microphone quality claim."""
import io
import json
from pathlib import Path
from types import SimpleNamespace
import wave

import pytest

from localmind import asr_worker, voice
from localmind.speech_worker import SpeechWorkerError


def model_stub(monkeypatch, fail_cuda=False):
    calls = []

    class Model:
        def __init__(self, directory, **options):
            calls.append(options)
            if fail_cuda and options['device'] == 'cuda':
                raise RuntimeError('GPU unavailable')

        def transcribe(self, signal, multilingual=False, **options):
            return [SimpleNamespace(text='Не открывай Obsidian')], SimpleNamespace(language='ru')

    monkeypatch.setitem(__import__('sys').modules, 'faster_whisper', SimpleNamespace(WhisperModel=Model))
    monkeypatch.setattr(voice, '_decode_bounded', lambda _: [.1] * 16000)
    return calls


def test_reuses_model_across_decoding_choices_and_remembers_cpu_fallback(monkeypatch):
    calls = model_stub(monkeypatch, fail_cuda=True)
    recognizer = voice.Recognizer()
    first = voice._recognize(Path('unused'), 'gpu-quality', recognizer=recognizer)
    second = voice._recognize(Path('unused'), 'gpu-quality', 'technical-auto', recognizer)
    assert first['fallback'] and not first['model_reused']
    assert second['fallback'] and second['model_reused']
    assert second['device'] == 'cpu' and second['compute_type'] == 'int8'
    assert len(calls) == 2  # One failed GPU load, one persistent CPU load.
    assert calls[-1]['local_files_only'] is True
    assert 'inference_ms' in first and 'model_load_ms' in first


def test_language_pairs_change_only_language_and_keep_defaults():
    for forced, automatic in [('baseline', 'baseline-auto'), ('technical-ru', 'technical-auto')]:
        assert voice.DECODINGS[forced]['language'] == 'ru'
        assert voice.DECODINGS[automatic]['language'] is None
        assert {k: v for k, v in voice.DECODINGS[forced].items() if k != 'language'} == {
            k: v for k, v in voice.DECODINGS[automatic].items() if k != 'language'}
    assert list(voice.PROFILES) == ['cpu-fast', 'balanced', 'gpu-quality']
    assert voice.EVALUATION_PROFILES['gpu-turbo']['model'] == 'large-v3-turbo'
    with pytest.raises(voice.VoiceError):
        voice.transcribe_audio(b'x' * 128, '.wav', 'gpu-turbo')


@pytest.mark.parametrize('profile,model', [('cpu-fast', 'small'), ('balanced', 'small'),
                                         ('gpu-quality', 'medium'), ('gpu-turbo', 'large-v3-turbo'), ('gpu-large', 'large-v3')])
def test_candidate_setup_uses_declared_model_only(tmp_path, monkeypatch, profile, model):
    calls = []
    monkeypatch.setattr(voice, 'MODELS', tmp_path / 'models')
    monkeypatch.setattr(__import__('sys'), 'argv', ['voice', 'setup-stt', '--profile', profile])
    monkeypatch.setitem(__import__('sys').modules, 'faster_whisper.utils', SimpleNamespace(
        download_model=lambda *args, **kwargs: calls.append((args, kwargs))))
    voice.main()
    assert calls[0][0] == (model,)
    assert Path(calls[0][1]['output_dir']) == tmp_path / 'models' / 'whisper' / model


def test_cli_base_is_rejected_before_any_download(monkeypatch):
    import sys
    monkeypatch.setattr(sys, 'argv', ['voice', 'setup-stt', '--profile', 'base'])
    with pytest.raises(SystemExit) as error:
        voice.main()
    assert error.value.code == 2


def test_unsupported_multilingual_is_explicit_not_silent_fallback(monkeypatch):
    class Model:
        def __init__(self, *args, **kwargs): pass
        def transcribe(self, signal, **kwargs):
            pytest.fail('Unsupported option must not be submitted')
    monkeypatch.setitem(__import__('sys').modules, 'faster_whisper', SimpleNamespace(WhisperModel=Model))
    monkeypatch.setattr(voice, '_decode_bounded', lambda _: [.1] * 16000)
    with pytest.raises(voice.VoiceError, match='multilingual'):
        voice._recognize(Path('unused'), 'gpu-quality', 'multilingual')


def fake_worker(monkeypatch):
    worker = asr_worker.WarmASRWorker()
    calls = []

    class Process:
        def __init__(self, command, **options):
            self.stdin, self.stdout = io.BytesIO(), io.BytesIO()
            self.returncode = None
            self.killed = False
            calls.append((command, options, self))
        def poll(self): return self.returncode
        def kill(self): self.killed = True; self.returncode = 1
        def wait(self, timeout): return self.returncode

    class Reader:
        def __init__(self, **kwargs): pass
        def start(self): pass
        def join(self, timeout): pass

    original_send = worker._send
    def send(frame):
        original_send(frame)
        request = json.loads(frame)
        worker.replies.put({'id': request['id'], 'text': 'Открой Obsidian'})
    monkeypatch.setattr(asr_worker.subprocess, 'Popen', Process)
    monkeypatch.setattr(asr_worker, 'Thread', Reader)
    monkeypatch.setattr(worker, '_receive', lambda: {'ready': True})
    monkeypatch.setattr(worker, '_send', send)
    return worker, calls


def test_supervisor_reuses_process_reaps_before_model_switch_and_shuts_down(monkeypatch):
    worker, calls = fake_worker(monkeypatch)
    for decoding in ('baseline', 'baseline-auto'):
        assert worker.transcribe(b'x' * 128, '.wav', 'balanced', decoding)['text'] == 'Открой Obsidian'
    assert len(calls) == 1
    worker.transcribe(b'x' * 128, '.wav', 'gpu-quality', 'baseline')
    assert len(calls) == 2 and calls[0][2].killed
    assert calls[1][0][-2:] == ['localmind.stt_worker', 'gpu-quality']
    assert calls[1][1]['shell'] is False and calls[1][1]['env']['HF_HUB_OFFLINE'] == '1'
    worker.close()
    assert calls[1][2].killed and worker.process is None


def test_timeout_kills_owned_child_and_releases_admission(monkeypatch):
    worker, calls = fake_worker(monkeypatch)
    monkeypatch.setattr(worker, '_send', lambda frame: None)
    monkeypatch.setattr(voice, 'WORKER_TIMEOUT_SECONDS', .02)
    with pytest.raises(SpeechWorkerError, match='timeout'):
        worker.transcribe(b'x' * 128, '.wav', 'balanced', 'baseline')
    assert calls[0][2].killed and worker.process is None
    assert worker.lock.acquire(blocking=False)
    worker.lock.release()


def test_bounded_admission_refuses_overlapping_requests():
    worker = asr_worker.WarmASRWorker()
    worker.lock.acquire()
    try:
        with pytest.raises(SpeechWorkerError, match='busy'):
            worker.transcribe(b'x' * 128, '.wav', 'balanced', 'baseline')
    finally:
        worker.lock.release()


def test_real_persistent_process_rejects_silence_without_model_loading():
    pytest.importorskip('av')
    stream = io.BytesIO()
    with wave.open(stream, 'wb') as audio:
        audio.setnchannels(1); audio.setsampwidth(2); audio.setframerate(16000)
        audio.writeframes(b'\0\0' * 16000)
    worker = asr_worker.WarmASRWorker()
    try:
        for _ in range(2):
            with pytest.raises(voice.VoiceError, match='Речь не обнаружена'):
                worker.transcribe(stream.getvalue(), '.wav', 'balanced', 'baseline')
        assert worker.process is not None and worker.process.poll() is None
    finally:
        worker.close()


def test_idle_worker_releases_previous_audio_frame_and_transcript(monkeypatch):
    import base64
    import inspect
    import sys
    from localmind import stt_worker
    protocol = io.StringIO()
    frame = json.dumps({'id': 'a' * 32, 'audio': base64.b64encode(b'x' * 128).decode('ascii'),
                        'suffix': '.wav', 'decoding': 'baseline'}).encode('ascii') + b'\n'

    class Input:
        calls = 0
        def readline(self, limit):
            self.calls += 1
            if self.calls == 1:
                return frame
            idle = inspect.currentframe().f_back.f_locals
            assert all(idle[name] is None for name in ('raw', 'request', 'data', 'payload'))
            return b''

    monkeypatch.setattr(sys, 'stdin', SimpleNamespace(buffer=Input()))
    monkeypatch.setattr(sys, 'argv', ['stt_worker', 'balanced'])
    monkeypatch.setattr(voice, '_recognize', lambda *args, **kwargs: {'text': 'Private transcript'})
    previous_stdout = sys.stdout
    try:
        sys.stdout = protocol
        stt_worker.main()
    finally:
        sys.stdout = previous_stdout
    assert json.loads(protocol.getvalue().splitlines()[-1])['text'] == 'Private transcript'


def test_evaluator_counts_failed_recordings_in_accuracy(tmp_path, monkeypatch, capsys):
    from scripts import eval_stt
    (tmp_path / 'sample.wav').write_bytes(b'x' * 128)
    def fail(*args, **kwargs): raise voice.VoiceError(503, 'unavailable')
    monkeypatch.setattr(eval_stt, 'transcribe_audio', fail)
    rows = [{'id': '1', 'path': 'sample.wav', 'reference': 'Не открывай Obsidian'}]
    assert eval_stt.evaluate(rows, tmp_path / 'manifest.csv', SimpleNamespace(profile='balanced', include_transcripts=False), 'baseline') == 1
    report = json.loads(capsys.readouterr().out.splitlines()[-1])
    assert report['WER'] == 1 and report['CER'] == 1
    assert report['technical_name_accuracy'] == 0 and report['negation_retention'] == 0
    assert report['negated_phrase_exact_accuracy'] == 0


def test_benchmark_protocol_requires_all_conditions_per_phrase():
    from scripts.eval_stt import corpus_report, REQUIRED_PHRASES
    phrases = [*REQUIRED_PHRASES, *(f'Ordinary phrase {number}' for number in range(24))]
    quiet = [{'id': str(index), 'path': f'{index}.wav', 'reference': phrase, 'condition': 'quiet'}
             for index, phrase in enumerate(phrases)]
    partial = [*quiet, {'id': 'noisy', 'path': 'noisy.wav', 'reference': phrases[0], 'condition': 'noisy'},
               {'id': 'low', 'path': 'low.wav', 'reference': phrases[0], 'condition': 'low-volume'}]
    report = corpus_report(partial)
    assert report['distinct_phrases'] == 30 and report['complete_condition_phrases'] == 1
    assert not report['benchmark_corpus_complete']
    assert len(report['incomplete_condition_phrases']) == 29
    complete = [{**row, 'id': row['id'] + condition, 'condition': condition}
                for row in quiet for condition in ('quiet', 'noisy', 'low-volume')]
    assert corpus_report(complete)['benchmark_corpus_complete']


@pytest.mark.parametrize('invalid', [None, '', ' ', '...'])
def test_manifest_rejects_malformed_late_reference_before_inference(tmp_path, monkeypatch, invalid):
    import sys
    from scripts import eval_stt
    manifest = tmp_path / 'recordings.csv'
    ending = 'second,second.wav' if invalid is None else 'second,second.wav,' + invalid
    manifest.write_text('id,path,reference\nfirst,first.wav,valid reference\n' + ending + '\n', encoding='utf-8')
    monkeypatch.setattr(sys, 'argv', ['eval_stt', str(manifest), '--consent'])
    monkeypatch.setattr(eval_stt, 'transcribe_audio', lambda *args, **kwargs: pytest.fail('Invalid corpus reached inference'))
    with pytest.raises(SystemExit) as error:
        eval_stt.main()
    assert error.value.code == 2
