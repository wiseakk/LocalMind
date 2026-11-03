"""Single supervised ASR child using the proven bounded speech pipe transport.

Profile changes reap the old process before starting another; decoding changes
reuse its one model. Uploaded audio and decoded samples stay in memory.
"""
import atexit
import base64
import json
import os
from queue import Queue, Empty
import subprocess
import sys
from threading import Thread
import time
import uuid

from .paths import python_runtime
from .speech_worker import WarmSpeechWorker, SpeechWorkerError, ROOT
from .voice_diagnostics import normalize_stt_payload


class WarmASRWorker(WarmSpeechWorker):
    def __init__(self):
        super().__init__()
        self.loaded_diagnostics = None
        self.measurements = {}

    def _close(self):
        super()._close()
        with self.state_lock:
            self.loaded_diagnostics = None

    def diagnostics(self):
        with self.state_lock:
            alive = self.process is not None and self.process.poll() is None
            return {'state': 'loaded' if alive and self.loaded_diagnostics else 'not_loaded',
                    'loaded': self.loaded_diagnostics if alive else None,
                    'measurements': dict(self.measurements)}

    def _start(self, profile):
        if self.process and self.voice == profile and self.process.poll() is None:
            return
        self._close()
        self.replies = Queue(maxsize=2)
        environment = {**os.environ, 'HF_HUB_OFFLINE': '1', 'HF_HUB_DISABLE_TELEMETRY': '1',
                       'DO_NOT_TRACK': '1', 'OMP_NUM_THREADS': '4', 'MKL_NUM_THREADS': '4',
                       'PYTHONIOENCODING': 'utf-8'}
        self.process = subprocess.Popen([str(python_runtime()), '-m', 'localmind.stt_worker', profile],
            cwd=ROOT, env=environment, shell=False, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        self.voice = profile
        self.reader = Thread(target=self._read, args=(self.process.stdout, self.replies),
                             daemon=True, name='localmind-asr-pipe')
        self.reader.start()
        if self._receive() != {'ready': True}:
            raise SpeechWorkerError('worker')

    def transcribe(self, data, suffix, profile, decoding):
        from .voice import VoiceError, WORKER_TIMEOUT_SECONDS, MAX_UPLOAD_BYTES
        if len(data) > MAX_UPLOAD_BYTES:
            raise VoiceError(413, 'Аудио слишком большое: максимум 8 МБ.')
        if not self.lock.acquire(blocking=False):
            raise SpeechWorkerError('busy')
        try:
            self.deadline = time.monotonic() + WORKER_TIMEOUT_SECONDS
            self._start(profile)
            request_id = uuid.uuid4().hex
            frame = {'id': request_id, 'audio': base64.b64encode(data).decode('ascii'),
                     'suffix': suffix, 'decoding': decoding}
            self._send((json.dumps(frame, allow_nan=False) + '\n').encode('utf-8'))
            # Domain failures are valid replies, not broken protocol frames.
            try:
                payload = self.replies.get(timeout=max(0, self.deadline - time.monotonic()))
            except Empty as exc:
                raise SpeechWorkerError('timeout') from exc
            if not isinstance(payload, dict) or payload.get('id') != request_id:
                raise SpeechWorkerError('worker')
            payload = normalize_stt_payload(payload)
            if 'error' in payload:
                if 'loaded_diagnostics' in payload:
                    loaded = payload['loaded_diagnostics']
                    if loaded is not None and not isinstance(loaded, dict):
                        raise SpeechWorkerError('worker')
                    with self.state_lock:
                        self.loaded_diagnostics = ({key: value for key, value in loaded.items()
                            if key in ('profile', 'model', 'resource', 'runtime', 'device', 'compute_type',
                                       'requested_device', 'requested_compute_type', 'fallback',
                                       'last_request_state')} if loaded is not None else None)
                elif payload.get('error_code'):
                    with self.state_lock:
                        self.loaded_diagnostics = None
                if not isinstance(payload['error'], str) or payload.get('status_code') not in (413, 415, 422, 503):
                    raise SpeechWorkerError('worker')
                raise VoiceError(payload['status_code'], payload['error'])
            if not isinstance(payload.get('text'), str) or not 1 <= len(payload['text']) <= 4000:
                raise SpeechWorkerError('worker')
            with self.state_lock:
                # Keep no transcript or audio in the diagnostics cache.
                self.loaded_diagnostics = {key: value for key, value in payload.items()
                    if key not in ('id', 'text')}
                self.measurements[profile] = {key: payload.get(key) for key in
                    ('resources', 'model_load_ms', 'inference_ms', 'device', 'compute_type', 'fallback')}
            return {key: value for key, value in payload.items() if key != 'id'}
        except (OSError, ValueError, SpeechWorkerError) as exc:
            self._close()
            if isinstance(exc, SpeechWorkerError):
                raise
            raise SpeechWorkerError('worker') from exc
        finally:
            self.lock.release()


worker = WarmASRWorker()
atexit.register(worker.close)
