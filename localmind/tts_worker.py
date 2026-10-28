"""Private local TTS pipe worker. Stdlib imports keep candidate venvs isolated.

Only parent-owned fixed paths and declared voice IDs enter this process. stdout
is a framed protocol, never diagnostics. Inference never downloads assets.
"""
import base64
import io
import json
import os
from pathlib import Path
import sys
import time
import wave

ROOT = Path(__file__).resolve().parents[1]
MAX_AUDIO_BYTES = 12 * 1024 * 1024


def load_engine(voice):
    if voice == 'ru_RU-denis-medium':
        from piper import PiperVoice
        return PiperVoice.load(str(ROOT / 'models' / 'piper' / (voice + '.onnx')), use_cuda=False)
    if voice == 'silero-v5_6-ru':
        import torch
        torch.set_num_threads(4)
        model = torch.package.PackageImporter(str(ROOT / 'models/silero/v5_6_ru.pt')).load_pickle('tts_models', 'model')
        model.to(torch.device('cpu'))
        return model
    if voice == 'chatterbox-v3-ru':
        import torch
        from chatterbox.mtl_tts import ChatterboxMultilingualTTS
        torch.set_num_threads(4)
        # Explicit v3; upstream defaults to v2. No from_pretrained/network calls.
        return ChatterboxMultilingualTTS.from_local(ROOT / 'models/chatterbox-v3', device='cuda' if torch.cuda.is_available() else 'cpu', t3_model='v3')
    raise ValueError('Undeclared voice')


def synthesize(engine, voice, text):
    output = io.BytesIO()
    with wave.open(output, 'wb') as audio:
        if voice == 'ru_RU-denis-medium':
            engine.synthesize_wav(text, audio)
        else:
            import numpy as np
            if voice == 'silero-v5_6-ru':
                samples = engine.apply_tts(text=text, speaker='xenia', sample_rate=24000, put_accent=True, put_yo=True)
                rate = 24000
            else:
                samples = engine.generate(text, language_id='ru')
                rate = engine.sr
            samples = samples.detach().cpu().numpy().reshape(-1)
            if len(samples) > rate * 120:
                raise ValueError('Audio duration budget')
            pcm = (np.clip(samples, -1, 1) * 32767).astype('<i2').tobytes()
            audio.setnchannels(1)
            audio.setsampwidth(2)
            audio.setframerate(rate)
            audio.writeframes(pcm)
    result = output.getvalue()
    if len(result) > MAX_AUDIO_BYTES:
        raise ValueError('Audio byte budget')
    return result


def main():
    protocol = sys.stdout
    sys.stdout = sys.stderr  # Imported packages cannot contaminate protocol stdout.
    voice = sys.argv[1] if len(sys.argv) == 2 else ''
    engine = load_engine(voice)
    # Warm native inference once; warm-up audio is discarded and never played.
    synthesize(engine, voice, 'Готов.')
    protocol.write(json.dumps({'ready': True}) + '\n')
    protocol.flush()
    for raw in sys.stdin:
        if len(raw) > 16384:
            break
        request = {}
        try:
            request = json.loads(raw)
            if set(request) != {'id', 'text'} or not isinstance(request['id'], str) or len(request['id']) > 64:
                break
            text = request['text']
            if not isinstance(text, str) or not 1 <= len(text) <= 2400:
                break
            started = time.monotonic()
            result = synthesize(engine, voice, text)
            payload = {'id': request['id'], 'audio': base64.b64encode(result).decode('ascii'),
                       'duration_ms': round((time.monotonic() - started) * 1000)}
        except Exception:
            payload = {'id': request.get('id') if isinstance(request, dict) else None, 'error': 'Local speech synthesis failed'}
        protocol.write(json.dumps(payload) + '\n')
        protocol.flush()


if __name__ == '__main__':
    os.environ.update(HF_HUB_OFFLINE='1', HF_HUB_DISABLE_TELEMETRY='1', DO_NOT_TRACK='1')
    main()
