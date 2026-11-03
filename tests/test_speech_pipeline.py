"""Speech protocol/resource/cancellation checks; no claim of natural voice quality."""
import base64
import io
import json
import threading
import time
from types import SimpleNamespace
import wave

import pytest

from localmind import speech_worker, voice
from localmind.speech_text import normalize_speech


def wav():
    stream = io.BytesIO()
    with wave.open(stream, 'wb') as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(22050)
        output.writeframes(b'\0\0' * 10)
    return stream.getvalue()


def test_speech_normalization_is_readable_and_not_an_evaluator():
    text = normalize_speech('**Python**, C#, C++, RSA, Obsidian, Steam, World of Warcraft. '
        '[Документация](https://example.com). https://example.com/private?q=secret '
        '\\(x^2 = 25\\), 3.14 и 12%. ```python\neval("danger")\n```')
    for expected in ('Пайтон', 'си шарп', 'си плюс плюс', 'эр эс эй', 'Обсидиан',
                     'Стим', 'Ворлд оф Варкрафт', 'в квадрате', 'три целых четырнадцать сотых', 'процентов'):
        assert expected in text
    assert all(value not in text for value in ('https', 'private', 'secret', 'eval', '**', '\\('))
    assert normalize_speech('unknownEnglish словo') == 'unknownEnglish словo'


def test_voice_uses_normalized_text_in_warm_worker(monkeypatch):
    seen = []
    monkeypatch.setattr(voice, '_installed', lambda module: True)
    monkeypatch.setattr(voice, '_tts_ready', lambda selection: True)
    monkeypatch.setattr(voice._speech_worker, 'synthesize', lambda *args: seen.append(args) or wav())
    assert voice.synthesize_speech('**Python**', generation_id='a' * 32).startswith(b'RIFF')
    assert seen == [('Пайтон', voice.DEFAULT_VOICE, 'a' * 32)]


def fake_worker(monkeypatch):
    worker = speech_worker.WarmSpeechWorker()
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

    def receive():
        content = worker.process.stdin.getvalue()
        if not content:
            return {'ready': True}
        request = json.loads(content.splitlines()[-1])
        return {'id': request['id'], 'audio': base64.b64encode(wav()).decode('ascii')}

    monkeypatch.setattr(speech_worker.subprocess, 'Popen', Process)
    monkeypatch.setattr(speech_worker, 'Thread', lambda **kwargs:
        Reader(**kwargs) if kwargs.get('name') == 'localmind-tts-pipe' else threading.Thread(**kwargs))
    monkeypatch.setattr(worker, '_receive', receive)
    return worker, calls


def test_warm_worker_reuses_process_and_closes_on_shutdown(monkeypatch):
    worker, calls = fake_worker(monkeypatch)
    assert worker.synthesize('Первая фраза.', voice.DEFAULT_VOICE).startswith(b'RIFF')
    assert worker.synthesize('Вторая фраза.', voice.DEFAULT_VOICE).startswith(b'RIFF')
    assert len(calls) == 1
    assert calls[0][1]['shell'] is False
    assert calls[0][1]['env']['HF_HUB_OFFLINE'] == '1'
    assert calls[0][0][-1] == voice.DEFAULT_VOICE
    worker.close()
    assert calls[0][2].killed
    assert worker.process is None


def test_worker_timeout_kills_only_child_and_releases_admission(monkeypatch):
    worker, calls = fake_worker(monkeypatch)
    def timeout(): raise speech_worker.SpeechWorkerError('timeout')
    monkeypatch.setattr(worker, '_receive', timeout)
    with pytest.raises(speech_worker.SpeechWorkerError, match='timeout'):
        worker.synthesize('Фраза.', voice.DEFAULT_VOICE)
    assert calls[0][2].killed
    assert worker.process is None
    assert worker.lock.acquire(blocking=False)
    worker.lock.release()


def test_cancel_before_admission_rejects_late_request_and_stale_cancel_spares_successor(monkeypatch):
    worker, calls = fake_worker(monkeypatch)
    worker.cancel('old')
    with pytest.raises(speech_worker.SpeechWorkerError, match='cancelled'):
        worker.synthesize('Опоздавшая фраза.', voice.DEFAULT_VOICE, 'old')
    assert calls == []
    worker.synthesize('Новая фраза.', voice.DEFAULT_VOICE, 'new')
    worker.active_token = 'new'
    worker.cancel('old')
    assert not calls[0][2].killed
    worker.cancel('new')
    assert calls[0][2].killed
    worker.close()


def test_cancel_tombstones_are_bounded_and_fail_closed_at_capacity(monkeypatch):
    worker, calls = fake_worker(monkeypatch)
    for value in range(500): worker.cancel(str(value))
    assert len(worker.retired) <= 257
    with pytest.raises(speech_worker.SpeechWorkerError, match='cancelled'):
        worker.synthesize('Фраза.', voice.DEFAULT_VOICE, 'fresh')
    assert calls == []


def test_worker_rejects_mismatched_frame(monkeypatch):
    worker, calls = fake_worker(monkeypatch)
    worker.synthesize('Фраза.', voice.DEFAULT_VOICE)
    monkeypatch.setattr(worker, '_receive', lambda: {'id': 'forged', 'audio': base64.b64encode(wav()).decode('ascii')})
    with pytest.raises(speech_worker.SpeechWorkerError):
        worker.synthesize('Фраза.', voice.DEFAULT_VOICE)
    assert calls[0][2].killed


def test_cancellation_after_reply_never_returns_stale_audio(monkeypatch):
    worker, calls = fake_worker(monkeypatch)
    worker.synthesize('Прогрев.', voice.DEFAULT_VOICE)
    receive = worker._receive

    def late_reply():
        reply = receive()
        worker.cancel('generation')
        return reply

    monkeypatch.setattr(worker, '_receive', late_reply)
    with pytest.raises(speech_worker.SpeechWorkerError, match='cancelled'):
        worker.synthesize('Фраза.', voice.DEFAULT_VOICE, 'generation')
    assert calls[0][2].killed


def test_candidate_interpreters_use_private_runtime_or_declared_dev_python():
    from localmind.paths import python_runtime
    for voice_id in ('silero-v5_6-ru', 'chatterbox-v3-ru'):
        executable = speech_worker.interpreter(voice_id)
        assert executable == python_runtime() or executable.is_relative_to(speech_worker.ROOT / '.voice-envs')
        assert executable.name in ('python.exe', 'python')


@pytest.mark.parametrize('selection', ['silero-v5_6-ru', 'chatterbox-v3-ru'])
def test_missing_candidate_setup_message_does_not_misreport_piper(monkeypatch, selection):
    monkeypatch.setattr(voice, '_tts_ready', lambda value: False)
    expected = 'Подготовить голос' if selection == voice.DEFAULT_VOICE else 'NEXT_VOICE'
    with pytest.raises(voice.VoiceError, match=expected) as error:
        voice.synthesize_speech('Проверка.', selection)
    assert 'Piper не установлен' not in error.value.detail


@pytest.mark.parametrize('block_at', ['write', 'flush'])
def test_stalled_input_pipe_is_timed_out_reaped_and_sender_joined(monkeypatch, block_at):
    worker, calls = fake_worker(monkeypatch)
    worker.synthesize('Прогрев.', voice.DEFAULT_VOICE)
    process = worker.process
    entered, reaped = threading.Event(), threading.Event()
    threads = []

    class StalledPipe:
        closed = False
        def write(self, frame):
            if block_at == 'write':
                threads.append(threading.current_thread())
                entered.set()
                assert reaped.wait(timeout=2), 'supervisor failed to reap stalled reader'
                raise BrokenPipeError('Owned worker reaped')
            return len(frame)
        def flush(self):
            threads.append(threading.current_thread())
            entered.set()
            assert reaped.wait(timeout=2), 'supervisor failed to reap stalled reader'
            raise BrokenPipeError('Owned worker reaped')
        def close(self):
            # Closing while sender owns BufferedWriter's lock is the old hang.
            assert all(not thread.is_alive() for thread in threads)
            self.closed = True

    pipe = StalledPipe()
    process.stdin = pipe
    original_kill = process.kill
    def kill():
        original_kill()
        reaped.set()
    process.kill = kill
    monkeypatch.setattr(speech_worker, 'TIMEOUT', .03)
    started = time.monotonic()
    with pytest.raises(speech_worker.SpeechWorkerError, match='timeout'):
        worker.synthesize('Запись в зависший worker.', voice.DEFAULT_VOICE)
    assert entered.is_set() and reaped.is_set()
    assert time.monotonic() - started < 1
    assert threads and all(not thread.is_alive() for thread in threads)
    assert pipe.closed and worker.writer is None and worker.process is None
    # Admission and shutdown both recover; no leaked writer holds the lock.
    assert worker.lock.acquire(blocking=False)
    worker.lock.release()
    worker.close()
