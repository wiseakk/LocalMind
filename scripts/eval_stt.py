"""Evaluate explicitly consented local recordings; prints metrics, never audio.

CSV: id,path,reference. Relative paths resolve beside the manifest. No downloads.
Run: python scripts/eval_stt.py recordings.csv --consent --profile balanced
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.metadata
import json
import math
import os
import platform
from pathlib import Path
import re
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from localmind.voice import MAX_UPLOAD_BYTES, PROFILES, DECODINGS, VoiceError, transcribe_audio

TECHNICAL_TERMS = ('Downloads', 'Obsidian', 'PDF', 'Windows', 'Steam', 'Python', 'Warcraft', 'RSA')


def technical_score(reference, hypothesis, terms=None):
    def present(text, term):
        # Underscores separate names in filenames; partial words do not count.
        return bool(re.search(r'(?<![^\W_])' + re.escape(term) + r'(?![^\W_])', text, re.I))
    expected = terms or [term for term in TECHNICAL_TERMS if present(reference, term)]
    matched = [term for term in expected if present(hypothesis, term)]
    return {'technical_names': len(expected), 'technical_names_correct': len(matched),
            'missing_technical_names': [term for term in expected if term not in matched]}


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
    parser.add_argument('--decoding', choices=DECODINGS, default='baseline')
    parser.add_argument('--compare', action='store_true', help='Compare every declared decoding on identical bytes; no defaults changed')
    parser.add_argument('--include-transcripts', action='store_true', help='Explicitly print private raw transcripts and references; keep output local')
    parser.add_argument('--hardware-note', default='not supplied', help='Microphone, CPU/GPU, noise and input-level details; never inferred')
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
    versions = {}
    for package in ('faster-whisper', 'ctranslate2', 'av'):
        try:
            versions[package] = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            versions[package] = None
    print(json.dumps({'environment': {'os': platform.platform(), 'python': platform.python_version(),
        'processor': platform.processor(), 'logical_cpus': os.cpu_count(), 'packages': versions,
        'hardware_note': args.hardware_note}, 'consent': True, 'local_only': True,
        'manifest_sha256': hashlib.sha256(manifest.read_bytes()).hexdigest()}))
    failures = 0
    recording_hashes = {}
    for decoding in (DECODINGS if args.compare else [args.decoding]):
        failures += evaluate(rows, manifest, args, decoding, recording_hashes)
    return 1 if failures else 0


def evaluate(rows, manifest, args, decoding, recording_hashes=None):
    recording_hashes = {} if recording_hashes is None else recording_hashes
    totals = {'word_errors': 0, 'words': 0, 'character_errors': 0, 'characters': 0}
    durations, failures, technical_names, technical_correct = [], 0, 0, 0
    for row in rows:
        reference = row['reference']
        if not reference.strip() or len(reference) > 4000:
            raise ValueError('Each reference must contain 1–4000 characters.')
        started = time.monotonic()
        try:
            path = (manifest.parent / row['path']).resolve(strict=True)
            if path.stat().st_size > MAX_UPLOAD_BYTES:
                raise VoiceError(413, 'Recording is larger than 8 MB.')
            recording = path.read_bytes()
            digest = hashlib.sha256(recording).hexdigest()
            identity = str(path)
            if recording_hashes.setdefault(identity, digest) != digest:
                raise VoiceError(422, 'Recording changed during comparison; do not compare different audio bytes.')
            result = transcribe_audio(recording, path.suffix.lower(), args.profile, decoding)
            duration = round((time.monotonic() - started) * 1000, 2)
            metrics = score(reference, result['text'])
            for key in totals:
                totals[key] += metrics[key]
            durations.append(duration)
            technical = technical_score(reference, result['text'], [t.strip() for t in row.get('technical_terms', '').split('|') if t.strip()])
            technical_names += technical['technical_names']; technical_correct += technical['technical_names_correct']
            private = {'reference': reference, 'raw_transcript': result['text']} if args.include_transcripts else {}
            print(json.dumps({'id': row['id'], 'profile': args.profile, 'decoding': decoding, **metrics, **technical, **private,
                'latency_ms': duration, 'recording_sha256': digest,
                'condition': row.get('condition', 'unspecified'), 'input_level': row.get('input_level', 'unspecified'),
                **{k: result.get(k) for k in ('device', 'compute_type', 'fallback', 'model_load_ms', 'levels', 'quality', 'language', 'decoding_settings')}}, ensure_ascii=False))
        except (VoiceError, OSError) as exc:
            failures += 1
            print(json.dumps({'id': row['id'], 'decoding': decoding, 'error': exc.detail if isinstance(exc, VoiceError) else 'Recording unavailable',
                              'status_code': exc.status_code if isinstance(exc, VoiceError) else None}, ensure_ascii=False))
    print(json.dumps({'profile': args.profile, 'decoding': decoding, 'successful': len(durations), 'failed': failures,
                      'technical_name_accuracy': technical_correct / technical_names if technical_names else None,
                      'WER': totals['word_errors'] / totals['words'] if totals['words'] else None,
                      'CER': totals['character_errors'] / totals['characters'] if totals['characters'] else None,
                      'mean_latency_ms': sum(durations) / len(durations) if durations else None,
                      'max_latency_ms': max(durations) if durations else None,
                      'p50_latency_ms': percentile(durations, 0.5),
                      'p95_latency_ms': percentile(durations, 0.95),
                      'accuracy_denominator': 'successfully transcribed recordings only; failures reported separately',
                      'normalization': 'lowercase, ё→е, remove punctuation; CER excludes spaces',
                      'includes_model_load': True}, ensure_ascii=False))
    return failures


if __name__ == '__main__':
    raise SystemExit(main())
