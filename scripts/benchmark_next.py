"""Loopback response/voice comparison, with no invented browser/audio metrics.

python scripts/benchmark_next.py --kind dialogue --n 5
python scripts/benchmark_next.py --kind voice --n 5
HTTP WAV bytes are not audible latency. No downloads, no user audio read, no audio
retained unless --retain-audio. Missing voices remain failed attempts.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import io
import json
from pathlib import Path
import sys
import time
import uuid
import wave

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent))
from eval_llm import bounded_lines, distribution, gpu, local_url, memory, save

ROOT = Path(__file__).resolve().parents[1]
SPEECH_SAMPLE = (
    'Привет! Python и C# — языки программирования. RSA использует открытый и закрытый ключи. '
    'Открой Obsidian, затем Steam. World of Warcraft — название игры. '
    'Вычислим: 17 умножить на 23 равно 391. Скидка 15 процентов.'
)


def measure_voice(client, base, voice, text, *, direct_synth=None):
    start = time.perf_counter()
    row = {'voice': voice, 'text': text, 'synthesis_ms': None, 'first_response_ms': None,
           'audio_duration_s': None, 'real_time_factor': None,
           'first_audible_audio_ms': None, 'voice_total_ms': None,
           'unavailable': 'No browser playback or acoustic capture; HTTP bytes are not audible audio',
           'ram_before': memory(), 'gpu_before': gpu(), 'audio_bytes': 0}
    data = bytearray()
    # Resource probes run outside the measured adapter/transport interval.
    start = time.perf_counter()
    try:
        if direct_synth is not None:
            row['transport'] = 'direct local supervised worker; no HTTP or playback'
            data.extend(direct_synth(text, voice))
        else:
            row['transport'] = 'loopback HTTP'
            with client.stream('POST', base + '/api/tts', json={'voice': voice, 'text': text}) as response:
                response.raise_for_status()
                for chunk in response.iter_bytes():
                    if row['first_response_ms'] is None:
                        row['first_response_ms'] = round((time.perf_counter() - start) * 1000, 3)
                    data.extend(chunk)
                    if len(data) > 16 * 1024 * 1024 or time.perf_counter() - start > 120:
                        raise ValueError('Audio response budget exceeded')
        row['synthesis_ms'] = round((time.perf_counter() - start) * 1000, 3)
        with wave.open(io.BytesIO(data), 'rb') as wav:
            if not wav.getframerate() or not wav.getnframes():
                raise ValueError('Empty audio waveform')
            row['audio_duration_s'] = wav.getnframes() / wav.getframerate()
        row['real_time_factor'] = row['synthesis_ms'] / 1000 / row['audio_duration_s']
        row['audio_bytes'] = len(data)
    except (httpx.HTTPError, ValueError, wave.Error, EOFError) as exc:
        row['error'] = {'type': type(exc).__name__, 'detail': str(exc)[:300]}
    row.update(wall_ms=round((time.perf_counter() - start) * 1000, 3), ram_after=memory(), gpu_after=gpu())
    return row, bytes(data) if not row.get('error') else b''


def measure_dialogue(client, base, info, text, *, light=False, model=None):
    start = time.perf_counter()
    row = {'text': text, 'first_delta_ms': None, 'first_status_ms': None, 'raw_first_token_ms': None,
           'first_browser_visible_text_ms': None, 'first_audible_audio_ms': None,
           'voice_total_ms': None, 'real_time_factor': None,
           'unavailable': 'HTTP client sees admitted deltas, not raw tokens, browser paint or audible audio',
           'ram_before': memory(), 'gpu_before': gpu(), 'delta_count': 0}
    payload = {'text': text, 'request_id': uuid.uuid4().hex, 'server_instance': info.get('server_instance'),
               'actions_authorized': light, 'compose_actions': False}
    if model:
        payload['model'] = model
    start = time.perf_counter()
    try:
        final = None
        with client.stream('POST', base + '/api/chat/stream', json=payload) as response:
            response.raise_for_status()
            for line in bounded_lines(response, start):
                if not line.strip():
                    continue
                event = json.loads(line)
                if event.get('type') == 'status' and row['first_status_ms'] is None:
                    row['first_status_ms'] = round((time.perf_counter() - start) * 1000, 3)
                if event.get('type') == 'delta' and event.get('text'):
                    row['delta_count'] += 1
                    if row['first_delta_ms'] is None:
                        row['first_delta_ms'] = round((time.perf_counter() - start) * 1000, 3)
                if event.get('type') == 'final':
                    final = event['data']
                if event.get('type') == 'error':
                    raise ValueError('Server stream error')
        if final is None:
            raise ValueError('Stream ended without final event')
        row['result'] = final
    except (httpx.HTTPError, ValueError, KeyError) as exc:
        row['error'] = {'type': type(exc).__name__, 'detail': str(exc)[:300]}
    row.update(wall_ms=round((time.perf_counter() - start) * 1000, 3), ram_after=memory(), gpu_after=gpu())
    return row


def summarize(rows):
    keys = ('first_delta_ms', 'first_response_ms', 'synthesis_ms', 'wall_ms', 'real_time_factor',
            'first_browser_visible_text_ms', 'first_audible_audio_ms', 'voice_total_ms')
    return {'attempts': len(rows), 'failures': sum(bool(row.get('error')) for row in rows),
            **{key: distribution([row.get(key) for row in rows]) for key in keys}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base', default='http://127.0.0.1:8765')
    parser.add_argument('--n', type=int, default=5)
    parser.add_argument('--key', default='')
    parser.add_argument('--kind', choices=('dialogue', 'voice', 'light'), default='dialogue')
    parser.add_argument('--voices', nargs='+', default=['ru_RU-denis-medium', 'silero-v5_6-ru', 'chatterbox-v3-ru'])
    parser.add_argument('--model')
    parser.add_argument('--text', help='Same text for all voices; no user recording is read')
    parser.add_argument('--allow-real', action='store_true', help='Explicit permission to actuate real configured light')
    parser.add_argument('--retain-audio', action='store_true', help='Save synthesized comparison WAVs beside output')
    parser.add_argument('--direct-voice', action='store_true', help='Use the local supervised voice adapter without a running HTTP server')
    parser.add_argument('--output', type=Path, default=ROOT / 'docs/evidence/next-response-benchmark.json')
    args = parser.parse_args()
    if not 1 <= args.n <= 500:
        parser.error('--n must be 1..500')
    if args.direct_voice and args.kind != 'voice':
        parser.error('--direct-voice requires --kind voice')
    base = local_url(args.base)
    if args.text is not None and not 1 <= len(args.text) <= 1200:
        parser.error('text must be 1..1200 characters')
    document = {'schema_version': 2, 'started_utc': datetime.now(timezone.utc).isoformat(),
                'kind': args.kind, 'rows': [], 'environment': {'ram': memory(), 'gpu': gpu()},
                'cold_semantics': 'First sample is first call observed; no claim OS caches or worker were cleared',
                'quality': {'naturalness': None, 'pronunciation': None, 'review': 'Listening required; no automatic quality claim'}}
    with httpx.Client(timeout=httpx.Timeout(125, connect=3), trust_env=False, headers={'X-LocalMind-Key': args.key}) as client:
        direct_synth = None
        if args.direct_voice:
            sys.path.insert(0, str(ROOT))
            from localmind.voice import synthesize_speech, VoiceError
            def direct_synth(text, voice):
                try:
                    return synthesize_speech(text, voice)
                except VoiceError as exc:
                    raise ValueError(f'VoiceError {exc.status_code}: {exc.detail}') from exc
            info = {}
        else:
            status = client.get(base + '/api/info')
            status.raise_for_status()
            info = status.json()
        if args.kind == 'light' and not info.get('demo') and not args.allow_real:
            parser.error('REAL light benchmark requires --allow-real')
        document['server_instance'] = info.get('server_instance')
        for voice_index, voice in enumerate(args.voices if args.kind == 'voice' else [None]):
            for index in range(args.n):
                if args.kind == 'voice':
                    row, audio = measure_voice(client, base, voice, args.text or SPEECH_SAMPLE, direct_synth=direct_synth)
                    if args.retain_audio and audio:
                        args.output.parent.mkdir(parents=True, exist_ok=True)
                        # External CLI voice name never becomes a path.
                        target = args.output.with_name(f'{args.output.stem}-voice-{voice_index}-{index + 1}.wav')
                        target.write_bytes(audio)
                        row['audio_artifact'] = target.name
                else:
                    if args.kind == 'light':
                        text = args.text or ('Включи настольную лампу' if index % 2 == 0 else 'Выключи лампу на столе')
                    else:
                        text = args.text or 'Чем оперативная память отличается от SSD?'
                    row = measure_dialogue(client, base, info, text, light=args.kind == 'light', model=args.model)
                row.update(iteration=index + 1, phase='first_observed' if index == 0 else 'warm_observed')
                document['rows'].append(row)
                document['summary'] = summarize(document['rows'])
                save(args.output, document)
                print(voice or args.kind, index + 1, row['wall_ms'], 'error' if row.get('error') else 'ok', flush=True)
    document['finished_utc'] = datetime.now(timezone.utc).isoformat()
    if args.kind == 'voice':
        document['voices'] = {
            voice: {'all': summarize([r for r in document['rows'] if r.get('voice') == voice]),
                    'warm_observed': summarize([r for r in document['rows'] if r.get('voice') == voice and r['phase'] == 'warm_observed'])}
            for voice in args.voices}
    save(args.output, document)


if __name__ == '__main__':
    main()
