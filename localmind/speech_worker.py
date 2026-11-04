"""Single supervised warm TTS process, bounded admission and framed replies.

Hard deadlines kill only our worker, including hung native inference. No text or
audio is retained on disk. Release workers use private CPython; fixed legacy
candidate venvs remain supported in source checkouts.
"""
import atexit
import base64
import io
import json
import os
from pathlib import Path
from queue import Empty, Full, Queue
import subprocess
import sys
import time
from threading import Lock, Thread
import uuid
import wave

from .paths import APP_ROOT as ROOT, DATA_ROOT, python_runtime
MAX_FRAME = 17 * 1024 * 1024
TIMEOUT = 120
CANDIDATES = {
    'silero-v5_6-ru': ('silero', ('models/silero/v5_6_ru.pt',)),
    'chatterbox-v3-ru': ('chatterbox', tuple('models/chatterbox-v3/' + name for name in
        ('ve.pt', 't3_mtl23ls_v3.safetensors', 's3gen.pt', 'grapheme_mtl_merged_expanded_v1.json', 'conds.pt'))),
}


def interpreter(voice):
    if voice not in CANDIDATES:
        return python_runtime()
    name, _ = CANDIDATES[voice]
    release = ROOT / 'runtime/core/python.exe'
    if release.is_file():
        return release
    legacy = ROOT / '.voice-envs' / name / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
    return legacy if legacy.is_file() else python_runtime()


def candidate_ready(voice):
    try:
        return interpreter(voice).is_file() and all((DATA_ROOT / path).is_file() and (DATA_ROOT / path).stat().st_size > 0 for path in CANDIDATES[voice][1])
    except OSError:
        return False


class SpeechWorkerError(Exception):
    pass


class WarmSpeechWorker:
    def __init__(self):
        self.lock = Lock()
        self.process = None
        self.voice = None
        self.reader = None
        self.writer = None
        self.replies = None
        self.state_lock = Lock()
        self.active_token = None
        self.cancelled = False
        self.retired = {}
        self.closing = False

    def reopen(self):
        """Only a new application lifespan may admit work after shutdown."""
        with self.lock, self.state_lock:
            if self.process is not None:
                raise SpeechWorkerError('worker_cleanup')
            self.closing = False
            self.cancelled = False

    def begin_shutdown(self):
        """Stop native work before waiting for the request's operation lock."""
        with self.state_lock:
            self.closing = True
            self.cancelled = True
            if self.process is not None:
                try:
                    self.process.kill()
                except OSError:
                    pass
            if self.replies is not None:
                try:
                    self.replies.put_nowait({'error': 'Worker shutting down'})
                except Full:
                    pass

    def _expire_retired(self):
        now = time.monotonic()
        self.retired = {token: expiry for token, expiry in self.retired.items() if expiry > now}

    def cancel(self, token):
        """Cancel only the exact active playback generation, never a successor."""
        with self.state_lock:
            if token is None:
                return False
            self._expire_retired()
            if token not in self.retired and len(self.retired) >= 256:
                # Reject admission instead of forgetting a recent cancellation.
                # No successor with a fresh token can enter until expiry.
                self.retired['*'] = time.monotonic() + 600
            else:
                self.retired[token] = time.monotonic() + 600
            if token != self.active_token:
                return True
            self.cancelled = True
            if self.process is not None:
                try:
                    self.process.kill()
                except OSError:
                    pass
            return True

    def _close(self):
        process = self.process
        if process is not None:
            try:
                if process.poll() is None:
                    process.kill()
                process.wait(timeout=5)
            except (OSError, subprocess.TimeoutExpired) as exc:
                # Retain ownership if the OS cannot reap our process; do not
                # spawn a replacement while native inference may still be alive.
                if process.poll() is None:
                    raise SpeechWorkerError('worker_cleanup') from exc
            # Killing/reaping the pipe's reader releases a blocked WriteFile.
            # Join the sender BEFORE closing BufferedWriter: close itself can
            # otherwise wait forever for the sender's internal stream lock.
            if self.writer is not None:
                self.writer.join(timeout=2)
                if self.writer.is_alive():
                    raise SpeechWorkerError('worker_cleanup')
                self.writer = None
            for stream in (process.stdin, process.stdout):
                if stream:
                    try:
                        stream.close()
                    except OSError:
                        pass
        self.process, self.voice = None, None
        if self.reader:
            self.reader.join(timeout=2)
            self.reader = None

    def close(self):
        self.begin_shutdown()
        with self.lock:
            self._close()

    @staticmethod
    def _read(stream, replies):
        try:
            while True:
                raw = stream.readline(MAX_FRAME + 1)
                if not raw or len(raw) > MAX_FRAME or not raw.endswith(b'\n'):
                    raise ValueError('Invalid worker frame')
                replies.put_nowait(json.loads(raw))
                # Idle warm workers retain engines, not the last audio/text frame.
                raw = None
        except (OSError, ValueError, Full):
            try:
                replies.put_nowait({'error': 'Worker disconnected'})
            except Full:
                pass

    def _receive(self):
        try:
            payload = self.replies.get(timeout=max(0, self.deadline - time.monotonic()))
        except Empty as exc:
            raise SpeechWorkerError('timeout') from exc
        from .voice_diagnostics import MESSAGES
        if isinstance(payload, dict) and payload.get('error_code') in MESSAGES:
            raise SpeechWorkerError(payload['error_code'])
        if not isinstance(payload, dict) or payload.get('error'):
            raise SpeechWorkerError('worker')
        return payload

    def _send(self, frame):
        completed = Queue(maxsize=1)
        stream = self.process.stdin

        def write():
            try:
                if stream.write(frame) != len(frame):
                    raise OSError('Incomplete worker write')
                stream.flush()
                completed.put_nowait(True)
            except Exception:
                completed.put_nowait(False)

        self.writer = Thread(target=write, daemon=True, name='localmind-tts-send')
        self.writer.start()
        try:
            success = completed.get(timeout=max(0, self.deadline - time.monotonic()))
        except Empty as exc:
            # synthesize's exception path reaps our exact child and joins sender.
            raise SpeechWorkerError('timeout') from exc
        self.writer.join(timeout=2)
        if self.writer.is_alive():
            raise SpeechWorkerError('worker_cleanup')
        self.writer = None
        if not success:
            raise SpeechWorkerError('worker')

    def _start(self, voice):
        if self.process and self.voice == voice and self.process.poll() is None:
            return
        self._close()
        self.replies = Queue(maxsize=2)
        env = {**os.environ, 'HF_HUB_OFFLINE': '1', 'HF_HUB_DISABLE_TELEMETRY': '1', 'DO_NOT_TRACK': '1',
               'OMP_NUM_THREADS': '4', 'MKL_NUM_THREADS': '4', 'PYTHONIOENCODING': 'utf-8'}
        with self.state_lock:
            if self.closing or self.cancelled:
                raise SpeechWorkerError('cancelled')
            self.process = subprocess.Popen([str(interpreter(voice)), '-m', 'localmind.tts_worker', voice],
                cwd=ROOT, env=env, shell=False, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        self.voice = voice
        self.reader = Thread(target=self._read, args=(self.process.stdout, self.replies), daemon=True,
                             name='localmind-tts-pipe')
        self.reader.start()
        if self._receive() != {'ready': True}:
            raise SpeechWorkerError('worker')

    def synthesize(self, text, voice, token=None):
        # Queues live in the client; server admission is bounded to one caller.
        if not self.lock.acquire(blocking=False):
            raise SpeechWorkerError('busy')
        try:
            self.deadline = time.monotonic() + TIMEOUT
            with self.state_lock:
                if self.closing:
                    raise SpeechWorkerError('cancelled')
                self._expire_retired()
                if token is not None and (token in self.retired or '*' in self.retired):
                    raise SpeechWorkerError('cancelled')
                self.active_token, self.cancelled = token, False
            self._start(voice)
            request_id = uuid.uuid4().hex
            self._send((json.dumps({'id': request_id, 'text': text}, ensure_ascii=False) + '\n').encode('utf-8'))
            payload = self._receive()
            if payload.get('id') != request_id or not isinstance(payload.get('audio'), str):
                raise SpeechWorkerError('worker')
            audio = base64.b64decode(payload['audio'], validate=True)
            if len(audio) > 12 * 1024 * 1024:
                raise SpeechWorkerError('worker')
            with wave.open(io.BytesIO(audio), 'rb') as decoded:
                if decoded.getnchannels() != 1 or decoded.getsampwidth() != 2 or decoded.getframerate() not in (8000, 16000, 22050, 24000, 44100, 48000) or decoded.getnframes() > decoded.getframerate() * 120:
                    raise SpeechWorkerError('worker')
            with self.state_lock:
                if self.cancelled:
                    raise SpeechWorkerError('cancelled')
            return audio
        except (OSError, ValueError, wave.Error, SpeechWorkerError) as exc:
            self._close()
            if isinstance(exc, SpeechWorkerError):
                raise
            raise SpeechWorkerError('worker') from exc
        finally:
            with self.state_lock:
                self.active_token = None
            self.lock.release()


worker = WarmSpeechWorker()
atexit.register(worker.close)
