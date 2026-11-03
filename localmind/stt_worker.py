"""Private ASR framed pipe worker; no paths, URLs or commands in requests."""
import base64
import json
from pathlib import Path
import sys
import time

MAX_FRAME = 12 * 1024 * 1024


def main():
    protocol = sys.stdout
    sys.stdout = sys.stderr
    from .voice import (Recognizer, VoiceError, EVALUATION_PROFILES, DECODINGS,
                        SUPPORTED_SUFFIXES, MAX_UPLOAD_BYTES, _recognize)
    profile = sys.argv[1] if len(sys.argv) == 2 else ''
    if profile not in EVALUATION_PROFILES:
        return
    from .voice_diagnostics import MESSAGES, classify_voice_error
    recognizer = Recognizer()
    protocol.write(json.dumps({'ready': True}) + '\n')
    protocol.flush()
    while True:
        raw = sys.stdin.buffer.readline(MAX_FRAME + 1)
        if not raw or len(raw) > MAX_FRAME or not raw.endswith(b'\n'):
            return
        request = {}
        try:
            request = json.loads(raw)
            if not isinstance(request, dict) or set(request) != {'id', 'audio', 'suffix', 'decoding'}:
                return
            if not isinstance(request['id'], str) or len(request['id']) != 32:
                return
            if request['suffix'] not in SUPPORTED_SUFFIXES or request['decoding'] not in DECODINGS:
                return
            if not isinstance(request['audio'], str) or len(request['audio']) > 4 * ((MAX_UPLOAD_BYTES + 2) // 3):
                return
            data = base64.b64decode(request['audio'], validate=True)
            if not 128 <= len(data) <= MAX_UPLOAD_BYTES:
                raise VoiceError(422, 'Некорректный размер записи.')
            started = time.monotonic()
            # Fixed container and in-memory bytes; no upload paths or audio files.
            source = Path('input' + request['suffix'])
            payload = _recognize(source, profile, request['decoding'], recognizer, audio_data=data)
            payload['duration_ms'] = round((time.monotonic() - started) * 1000)
        except VoiceError as exc:
            payload = {'error': exc.detail, 'status_code': exc.status_code}
        except Exception as exc:
            # Keep native diagnostics, audio, paths and transcripts out of logs.
            recognizer.clear()
            code = classify_voice_error(exc)
            payload = {'error': MESSAGES[code], 'error_code': code, 'status_code': 503}
        payload['id'] = request.get('id') if isinstance(request, dict) else None
        protocol.write(json.dumps(payload, ensure_ascii=False) + '\n')
        protocol.flush()
        # The warm process may now wait indefinitely. Do not retain the last
        # upload, its base64 frame or transcript while awaiting another request.
        raw = request = data = payload = None


if __name__ == '__main__':
    main()
