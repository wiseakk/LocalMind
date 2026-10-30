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
from localmind.voice import MAX_UPLOAD_BYTES, PROFILES, EVALUATION_PROFILES, DECODINGS, VoiceError, transcribe_audio, shutdown_stt

TECHNICAL_TERMS = ('Downloads', 'Obsidian', 'PDF', 'Windows', 'Steam', 'Python', 'Warcraft', 'RSA', 'Visual Studio Code', 'Arthas Menethil', 'World of Warcraft')
REQUIRED_PHRASES = ('Открой Obsidian', 'Найди последний PDF в Downloads', 'Выведи его на передний план',
                    'Скажи название последнего PDF-файла', 'Открой Python и Visual Studio Code',
                    'Расскажи про Arthas Menethil из World of Warcraft')
RECORDING_CONDITIONS = frozenset(('quiet', 'noisy', 'low-volume'))


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


def corpus_report(rows):
    """Validate the entire manifest before inference and disclose protocol gaps.

    IDs identify incomplete phrases without printing private references. Thirty
    phrases need all three conditions; their union across unrelated phrases is
    insufficient for the recording protocol.
    """
    if not rows or len(rows) > 200:
        raise ValueError('CSV must contain id,path,reference and 1–200 rows.')
    seen_ids, phrases = set(), {}
    for row in rows:
        if None in row or any(not isinstance(row.get(key), str) or not row[key].strip()
                              for key in ('id', 'path', 'reference')):
            raise ValueError('Every row must have nonempty id,path,reference strings and valid CSV columns.')
        if len(row['reference']) > 4000 or not normalize(row['reference']):
            raise ValueError('Each reference must contain 1–4000 characters and recognizable words.')
        if row['id'] in seen_ids:
            raise ValueError('Each recording row must have a unique id.')
        seen_ids.add(row['id'])
        for key in ('technical_terms', 'condition', 'input_level'):
            if key in row and not isinstance(row[key], str):
                raise ValueError('Optional manifest columns must contain strings, not missing CSV fields.')
        phrase = phrases.setdefault(normalize(row['reference']), {'ids': [], 'conditions': set()})
        phrase['ids'].append(row['id'])
        phrase['conditions'].add(row.get('condition', '').strip().casefold())
    complete = {text for text, phrase in phrases.items() if RECORDING_CONDITIONS <= phrase['conditions']}
    missing = [phrase for phrase in REQUIRED_PHRASES if normalize(phrase) not in phrases]
    required_incomplete = [phrase for phrase in REQUIRED_PHRASES if normalize(phrase) not in complete]
    incomplete = [{'recording_ids': phrase['ids'], 'missing_conditions': sorted(RECORDING_CONDITIONS - phrase['conditions'])}
                  for phrase in phrases.values() if not RECORDING_CONDITIONS <= phrase['conditions']]
    return {'distinct_phrases': len(phrases), 'complete_condition_phrases': len(complete),
            'conditions': sorted({condition for phrase in phrases.values() for condition in phrase['conditions']}),
            'required_phrases_missing': missing, 'required_phrases_missing_conditions': required_incomplete,
            'incomplete_condition_phrases': incomplete,
            'benchmark_corpus_complete': len(complete) >= 30 and not required_incomplete}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('manifest', type=Path)
    parser.add_argument('--profile', choices=EVALUATION_PROFILES, default='balanced')
    parser.add_argument('--decoding', choices=DECODINGS, default='baseline')
    parser.add_argument('--matrix', action='store_true', help='Compare all model profiles and decodings; requires 30 distinct phrases and quiet/noisy/low-volume conditions')
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
    try:
        corpus = corpus_report(rows)
    except ValueError as exc:
        parser.error(str(exc))
    if args.matrix and not corpus['benchmark_corpus_complete']:
        print(json.dumps(corpus, ensure_ascii=False))
        parser.error('--matrix requires at least 30 phrases, including all six requested phrases, each recorded in quiet/noisy/low-volume conditions.')
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
    print(json.dumps(corpus, ensure_ascii=False))
    failures = 0
    recording_hashes = {}
    profiles = EVALUATION_PROFILES if args.matrix else [args.profile]
    try:
        for profile in profiles:
            args.profile = profile
            shutdown_stt()  # First sample per model/decoding reports actual cold loading.
            for decoding in (DECODINGS if args.compare or args.matrix else [args.decoding]):
                shutdown_stt()
                failures += evaluate(rows, manifest, args, decoding, recording_hashes)
    finally:
        shutdown_stt()
    return 1 if failures else 0


def evaluate(rows, manifest, args, decoding, recording_hashes=None):
    recording_hashes = {} if recording_hashes is None else recording_hashes
    totals = {'word_errors': 0, 'words': 0, 'character_errors': 0, 'characters': 0}
    durations, warm_durations, cold_durations, inference_times = [], [], [], []
    failures, technical_names, technical_correct, negations, negations_correct, negated_exact = 0, 0, 0, 0, 0, 0
    for row in rows:
        reference = row['reference']
        if not reference.strip() or len(reference) > 4000:
            raise ValueError('Each reference must contain 1–4000 characters.')
        expected_terms = [t.strip() for t in row.get('technical_terms', '').split('|') if t.strip()]
        expected_technical = technical_score(reference, '', expected_terms)
        technical_names += expected_technical['technical_names']
        negated = bool(re.search(r'\b(?:не|нет|нельзя)\b', normalize(reference)))
        negations += int(negated)
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
            result = transcribe_audio(recording, path.suffix.lower(), args.profile, decoding, **({'evaluation': True} if args.profile not in PROFILES else {}))
            duration = round((time.monotonic() - started) * 1000, 2)
            metrics = score(reference, result['text'])
            for key in totals:
                totals[key] += metrics[key]
            durations.append(duration)
            (warm_durations if result.get('model_reused') else cold_durations).append(duration)
            if isinstance(result.get('inference_ms'), (int, float)):
                inference_times.append(result['inference_ms'])
            negation_preserved = not negated or bool(re.search(r'\b(?:не|нет|нельзя)\b', normalize(result['text'])))
            negations_correct += int(negated and negation_preserved)
            negated_exact += int(negated and normalize(reference) == normalize(result['text']))
            technical = technical_score(reference, result['text'], [t.strip() for t in row.get('technical_terms', '').split('|') if t.strip()])
            technical_correct += technical['technical_names_correct']
            private = {'reference': reference, 'raw_transcript': result['text']} if args.include_transcripts else {}
            print(json.dumps({'id': row['id'], 'profile': args.profile, 'decoding': decoding, **metrics, **technical, **private,
                'latency_ms': duration, 'recording_sha256': digest, 'negation_preserved': negation_preserved,
                'condition': row.get('condition', 'unspecified'), 'input_level': row.get('input_level', 'unspecified'),
                **{k: result.get(k) for k in ('device', 'compute_type', 'requested_device', 'requested_compute_type', 'fallback', 'model_load_ms', 'model_reused', 'inference_ms', 'levels', 'quality', 'language', 'decoding_settings')}}, ensure_ascii=False))
        except (VoiceError, OSError) as exc:
            failures += 1
            # Failed transcriptions count as deletions; excluding them would reward failures.
            metrics = score(reference, '')
            for key in totals:
                totals[key] += metrics[key]
            print(json.dumps({'id': row['id'], 'profile': args.profile, 'decoding': decoding, 'error': exc.detail if isinstance(exc, VoiceError) else 'Recording unavailable',
                              'status_code': exc.status_code if isinstance(exc, VoiceError) else None}, ensure_ascii=False))
    print(json.dumps({'profile': args.profile, 'decoding': decoding, 'successful': len(durations), 'failed': failures,
                      'technical_name_accuracy': technical_correct / technical_names if technical_names else None,
                      'negation_retention': negations_correct / negations if negations else None,
                      'negated_phrase_exact_accuracy': negated_exact / negations if negations else None,
                      'negation_examples': negations,
                      'cold_latency_ms': cold_durations,
                      'warm_p50_latency_ms': percentile(warm_durations, .5),
                      'warm_p95_latency_ms': percentile(warm_durations, .95),
                      'inference_p50_ms': percentile(inference_times, .5),
                      'inference_p95_ms': percentile(inference_times, .95),
                      'WER': totals['word_errors'] / totals['words'] if totals['words'] else None,
                      'CER': totals['character_errors'] / totals['characters'] if totals['characters'] else None,
                      'mean_latency_ms': sum(durations) / len(durations) if durations else None,
                      'max_latency_ms': max(durations) if durations else None,
                      'p50_latency_ms': percentile(durations, 0.5),
                      'p95_latency_ms': percentile(durations, 0.95),
                      'accuracy_denominator': 'all references; failures count as empty transcripts (deletions)',
                      'normalization': 'lowercase, ё→е, remove punctuation; CER excludes spaces',
                      'includes_model_load': True}, ensure_ascii=False))
    return failures


if __name__ == '__main__':
    raise SystemExit(main())
