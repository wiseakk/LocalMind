"""Opt-in local Piper filename samples, with no downloads or audio capture.

Example: python scripts/verify_filename_audio.py --consent --play
An optional --listener-feedback JSON file may contain a ``samples`` list with
``id``, ``heard_transcript``, ``correction`` and ``intelligibility`` fields. The
script records supplied listener answers separately from waveform measurements;
successful playback calls do not establish that a person heard the speech.
"""
import argparse
from array import array
import hashlib
import io
import json
import math
import os
from pathlib import Path
import sys
import time
import wave

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from localmind.results import ActionResult, file_output
from localmind.speech_text import normalize_speech
from localmind.tts_worker import synthesize

VOICE = 'ru_RU-denis-medium'
SAMPLES = (
    ('reported', 'Spisok_rabot pobeditelej_i_prizjorov_IB2026.pdf'),
    ('unseen-year', 'Otchet_proekt_2027.pdf'),
    ('unseen-unicode', 'План_работ_2028.pdf'),
    ('unseen-version', 'Python_v3.14_notes.txt'),
    ('unseen-opaque', '7b3f81eabc120f8790ec441eac85607ce2366a8894fb492733eb0140a2bf760e5.pdf'),
)


def audio_metrics(data):
    with wave.open(io.BytesIO(data), 'rb') as audio:
        rate, channels, width, count = (audio.getframerate(), audio.getnchannels(),
                                        audio.getsampwidth(), audio.getnframes())
        if channels != 1 or width != 2 or not 8000 <= rate <= 48000 or not 0 < count <= rate * 120:
            raise ValueError('Unexpected generated WAV format or duration')
        samples = array('h', audio.readframes(count))
        if sys.byteorder != 'little':
            samples.byteswap()
    rms = math.sqrt(math.fsum(float(value) ** 2 for value in samples) / len(samples)) / 32768
    peak = max(abs(value) for value in samples) / 32768
    return {'duration_seconds': round(count / rate, 3), 'sample_rate': rate,
            'channels': channels, 'sample_width_bytes': width,
            'rms': round(rms, 6), 'rms_dbfs': round(20 * math.log10(max(rms, 1e-9)), 3),
            'peak': round(peak, 6),
            'clipped_fraction': round(sum(abs(value) >= .99 * 32768 for value in samples) / len(samples), 6)}


def _feedback(path):
    if path is None:
        return None
    if not path.is_file() or path.stat().st_size > 64 * 1024:
        raise ValueError('Listener feedback must be a local JSON file smaller than 64 KiB')
    value = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(value, dict) or not isinstance(value.get('samples'), list):
        raise ValueError('Listener feedback requires a samples list')
    known = {sample_id for sample_id, _ in SAMPLES}
    cleaned = []
    for row in value['samples']:
        if not isinstance(row, dict) or row.get('id') not in known:
            raise ValueError('Unknown listener sample id')
        fields = {key: row.get(key) for key in ('heard_transcript', 'correction', 'intelligibility')}
        if any(item is not None and (not isinstance(item, str) or len(item) > 2000) for item in fields.values()):
            raise ValueError('Listener answers must be short strings or null')
        cleaned.append({'id': row['id'], **fields})
    return {'source': 'explicitly supplied listener feedback', 'samples': cleaned}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--consent', action='store_true', help='Retain these generated sample WAVs locally')
    parser.add_argument('--model-dir', type=Path, default=ROOT / 'models' / 'piper',
                        help='Read-only directory containing the declared Piper model and sidecar')
    parser.add_argument('--output', type=Path, default=ROOT / '.test-artifacts' / 'filename-audio',
                        help='Artifact directory, restricted to this checkout’s .test-artifacts')
    parser.add_argument('--play', action='store_true', help='Play only the five declared generated samples with Windows winsound')
    parser.add_argument('--listener-feedback', type=Path, help='Optional existing JSON with the listener’s own answers')
    args = parser.parse_args()
    if not args.consent:
        parser.error('--consent is required to retain generated audio evidence')
    output = args.output.resolve()
    if not output.is_relative_to((ROOT / '.test-artifacts').resolve()):
        parser.error('--output must stay within this checkout’s .test-artifacts')
    model = args.model_dir.resolve() / (VOICE + '.onnx')
    sidecar = model.with_suffix('.onnx.json')
    if not model.is_file() or not sidecar.is_file():
        parser.error('Local Piper model or sidecar missing; this script never downloads assets')
    feedback = _feedback(args.listener_feedback)
    os.environ.update(HF_HUB_OFFLINE='1', HF_HUB_DISABLE_TELEMETRY='1', DO_NOT_TRACK='1')
    from piper import PiperVoice
    started = time.monotonic()
    engine = PiperVoice.load(str(model), use_cuda=False)
    load_ms = round((time.monotonic() - started) * 1000, 3)
    output.mkdir(parents=True, exist_ok=True)
    report = {'voice': VOICE, 'engine': 'Piper', 'device': 'cpu', 'downloaded': False,
              'model_load_ms': load_ms, 'model_sha256': hashlib.sha256(model.read_bytes()).hexdigest(),
              'normalization_verification': 'actual production filename renderer and speech normalizer',
              'audible_quality_verified': False,
              'listener_feedback': feedback,
              'limitation': 'Waveform metrics and playback API completion do not prove audible quality or intelligibility.',
              'samples': []}
    for sample_id, filename in SAMPLES:
        result = ActionResult(True, 'files.search', 'fixture', 'observed', data={'filename': filename})
        _, speech_text = file_output(result)
        spoken = normalize_speech(speech_text)
        if normalize_speech(spoken) != spoken:
            raise ValueError('Prepared speech is not stable under repeated normalization')
        started = time.monotonic()
        data = synthesize(engine, VOICE, spoken)
        synthesis_ms = round((time.monotonic() - started) * 1000, 3)
        destination = output / (sample_id + '.wav')
        destination.write_bytes(data)
        sample = {'id': sample_id, 'filename': filename, 'speech_text': speech_text,
                  'spoken_text': spoken, 'wav': destination.name,
                  'sha256': hashlib.sha256(data).hexdigest(), 'synthesis_ms': synthesis_ms,
                  **audio_metrics(data), 'playback_api': 'not_requested'}
        if args.play:
            if os.name != 'nt':
                sample['playback_api'] = 'unsupported_platform'
            else:
                try:
                    import winsound
                    winsound.PlaySound(str(destination), winsound.SND_FILENAME | winsound.SND_NODEFAULT)
                    sample['playback_api'] = 'returned_successfully; audibility_unverified'
                except (RuntimeError, OSError) as exc:
                    sample['playback_api'] = 'failed: ' + type(exc).__name__
        report['samples'].append(sample)
    manifest = output / 'measurements.json'
    manifest.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    template = {'samples': [{'id': sample_id, 'heard_transcript': None, 'correction': None,
                             'intelligibility': None} for sample_id, _ in SAMPLES]}
    (output / 'listener_feedback.template.json').write_text(
        json.dumps(template, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'manifest': str(manifest.relative_to(ROOT)), 'samples': len(report['samples']),
                      'model_load_ms': load_ms, 'playback_api': [s['playback_api'] for s in report['samples']],
                      'audible_quality_verified': False}))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
