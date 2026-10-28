"""Evaluate explicitly consented local recordings; prints metrics, never audio.

CSV: id,path,reference. Relative paths resolve beside the manifest. No downloads.
Run: python scripts/eval_stt.py recordings.csv --consent --profile balanced
"""
from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path
import re
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from localmind.voice import MAX_UPLOAD_BYTES, PROFILES, VoiceError, transcribe_audio


def normalize(text: str) -> str:
    return ' '.join(re.sub(r'[^\w\s]', ' ', text.lower().replace('ё', 'е')).split())


def edit_distance(reference, hypothesis) -> int:
    previous = list(range(len(hypothesis) + 1))
    for index, expected in enumerate(reference, 1):
        current = [index]
        for position, observed in enumerate(hypothesis, 1):
            current.append(min(current[-1] + 1, previous[position] + 1,
                               previous[position - 1] + (expected != observed)))
        previous = current
    return previous[-1]


def score(reference: str, hypothesis: str) -> dict:
    expected, observed = normalize(reference), normalize(hypothesis)
    words, characters = expected.split(), expected.replace(' ', '')
    return {'word_errors': edit_distance(words, observed.split()), 'words': len(words),
            'character_errors': edit_distance(characters, observed.replace(' ', '')), 'characters': len(characters)}


def percentile(values: list[float], fraction: float) -> float | None:
    """Nearest-rank percentile; failure counts remain separately visible."""
    return sorted(values)[max(0, math.ceil(len(values) * fraction) - 1)] if values else None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('manifest', type=Path)
    parser.add_argument('--profile', choices=PROFILES, default='balanced')
    parser.add_argument('--consent', action='store_true', help='I have permission to process all listed recordings locally')
    args = parser.parse_args()
    if not args.consent:
        parser.error('Explicit --consent is required before reading recordings.')
    manifest = args.manifest.resolve(strict=True)
    if manifest.stat().st_size > 1024 * 1024:
        parser.error('Manifest is larger than 1 MB.')
    with manifest.open(encoding='utf-8-sig', newline='') as source:
        rows = list(csv.DictReader(source))
    if not rows or len(rows) > 200 or not {'id', 'path', 'reference'} <= rows[0].keys():
        parser.error('CSV must contain id,path,reference and 1–200 rows.')
    totals = {'word_errors': 0, 'words': 0, 'character_errors': 0, 'characters': 0}
    durations, failures = [], 0
    for row in rows:
        path = (manifest.parent / row['path']).resolve(strict=True)
        reference = row['reference']
        if not reference.strip() or len(reference) > 4000:
            parser.error('Each reference must contain 1–4000 characters.')
        started = time.monotonic()
        try:
            if path.stat().st_size > MAX_UPLOAD_BYTES:
                raise VoiceError(413, 'Recording is larger than 8 MB.')
            result = transcribe_audio(path.read_bytes(), path.suffix.lower(), args.profile)
            duration = round((time.monotonic() - started) * 1000, 2)
            metrics = score(reference, result['text'])
            for key in totals:
                totals[key] += metrics[key]
            durations.append(duration)
            print(json.dumps({'id': row['id'], **metrics, 'latency_ms': duration,
                              'device': result['device'], 'fallback': result['fallback']}, ensure_ascii=False))
        except VoiceError as exc:
            failures += 1
            print(json.dumps({'id': row['id'], 'error': exc.detail, 'status_code': exc.status_code}, ensure_ascii=False))
    print(json.dumps({'profile': args.profile, 'successful': len(durations), 'failed': failures,
                      'WER': totals['word_errors'] / totals['words'] if totals['words'] else None,
                      'CER': totals['character_errors'] / totals['characters'] if totals['characters'] else None,
                      'mean_latency_ms': sum(durations) / len(durations) if durations else None,
                      'max_latency_ms': max(durations) if durations else None,
                      'p50_latency_ms': percentile(durations, 0.5),
                      'p95_latency_ms': percentile(durations, 0.95),
                      'accuracy_denominator': 'successfully transcribed recordings only; failures reported separately',
                      'normalization': 'lowercase, ё→е, remove punctuation; CER excludes spaces',
                      'includes_model_load': True}, ensure_ascii=False))
    return 1 if failures else 0


if __name__ == '__main__':
    raise SystemExit(main())
