"""Local Silero input-support/English comparison. No downloads or auto-routing.

Run in .voice-envs/silero with --retain-audio to create a listening worksheet.
Package loading and synthesis are measured separately; no acoustic claims.
"""
import argparse
from dataclasses import asdict
import hashlib
import html
import json
import os
from pathlib import Path
import platform
import re
import sys
import time
import wave

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from localmind.speech_text import clean_speech, language_spans, normalize_speech, prepare_speech, speech_preparation

REVIEW_ENTITIES = (
    ('warcraft-ii', 'Warcraft II'), ('warcraft-iii', 'Warcraft III'),
    ('diablo-immortal', 'Diablo Immortal'), ('diablo-iv', 'Diablo IV'),
    ('blizzard-entertainment', 'Blizzard Entertainment'), ('hearthstone', 'Hearthstone'),
    ('heroes-of-the-storm', 'Heroes of the Storm'),
    ('ai', 'AI'), ('api', 'API'), ('pdf', 'PDF'), ('rsa', 'RSA'), ('cpp', 'C++'),
    ('starcraft-ii', 'StarCraft II'), ('starcraft-iii', 'StarCraft III'),
    ('unseen-title', 'Zephyr XLII'), ('command-conquer', 'Command & Conquer'),
    ('cc', 'C&C'), ('rd', 'R&D'), ('ru-ampersand', 'труд & отдых'),
    ('year-1977', 'В 1977 году'), ('year-2014', 'В 2014 году'),
    ('year-2002', 'Выпущена в 2002 году'), ('year-1999', '1999 году'),
    ('year-2026', '2026 году'), ('year-2000', '2000 году'),
    ('apple-ii', 'Apple II'), ('coordinated-years', 'Вышли в 1997 и 2002 годах'),
    ('in-year-2026', 'В 2026 году'), ('python-version', 'Python 3.14'),
    ('node-version', 'Версия Node.js 24.19.0'),
    ('math-pi', 'Число пи примерно равно 3.14'), ('ip-address', 'IP-адрес 192.168.1.1'),
    ('cardinal', '42'), ('decimal-dot', '3.14'), ('decimal-comma', '3,14'),
    ('ip', '192.168.1.1'), ('version', 'v2.1'), ('yearlike-version', 'v2026.1'),
    ('ipv4-version', 'IPv4 v2.1'), ('date-dmy', '31.10.2026'), ('date-iso', '2026-10-31'),
)
PHRASES = tuple((key + '-standalone', text) for key, text in REVIEW_ENTITIES) + tuple(
    (key + '-sentence', f'Сегодня мы обсуждаем {text}. Расскажи об этом подробнее.')
    for key, text in REVIEW_ENTITIES) + (
    ('arthas', 'Расскажи про Arthas Menethil из World of Warcraft'),
    ('warcraft-iii', 'Warcraft III: Reign of Chaos'),
    ('frozen-throne', 'The Frozen Throne'),
    ('heroes', 'Heroes of the Storm'),
    ('hearthstone', 'Hearthstone'),
    ('obsidian', 'Открой Obsidian'),
    ('pdf-downloads', 'Найди PDF в Downloads'),
    ('python-cpp', 'Я программирую на Python и C++'),
)


def identity(path):
    with path.open('rb') as source:
        return hashlib.file_digest(source, 'sha256').hexdigest()


def english_input(text):
    """English evaluation uses the documented Latin alphabet, not RU spellings."""
    text = re.sub(r'\bWarcraft III\b', 'Warcraft three', text, flags=re.I)
    text = re.sub(r'\bPDF\b', 'P D F', text)
    return text.replace('C++', 'C plus plus').replace('C#', 'C sharp')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--retain-audio', action='store_true')
    parser.add_argument('--output', type=Path, default=ROOT / '.test-artifacts/bilingual')
    parser.add_argument('--current-only', action='store_true', help='Only current Russian xenia samples')
    parser.add_argument('--iterations', type=int, choices=range(1, 7), default=6)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    os.environ.update(HF_HUB_OFFLINE='1', HF_HUB_DISABLE_TELEMETRY='1', DO_NOT_TRACK='1')
    import torch
    import numpy as np
    torch.set_num_threads(4)
    report = {'python': platform.python_version(), 'torch': torch.__version__, 'platform': platform.platform(),
              'device': 'cpu', 'threads': 4, 'sample_rate': 24000, 'models': {}, 'rows': [],
              'browser_playback_start_ms': None, 'acoustic_latency_ms': None,
              'listening': {'intelligibility': None, 'names': None, 'voice_consistency': None,
                            'pauses': None, 'joins': None, 'reviewer': None},
              'routing_decision': 'No English routing enabled: listening and voice-consistency review pending'}
    selections = (('v5_6_ru', 'xenia'),) if args.current_only else (('v5_6_ru', 'xenia'), ('v3_en', 'en_0'))
    for model_id, speaker in selections:
        path = ROOT / 'models/silero' / (model_id + '.pt')
        if not path.is_file():
            report['models'][model_id] = {'unavailable': 'Local model missing; no download attempted'}
            continue
        before = time.perf_counter()
        model = torch.package.PackageImporter(str(path)).load_pickle('tts_models', 'model')
        model.to(torch.device('cpu'))
        load_ms = round((time.perf_counter() - before) * 1000, 3)
        report['models'][model_id] = {'sha256': identity(path), 'speaker': speaker,
                                      'cold_package_load_ms': load_ms,
                                      'symbols': getattr(model, 'symbols', None), 'phons': getattr(model, 'phons', None)}
        # Same declared rate for both models, separate WAVs: no concatenation or
        # untested sample-rate conversion/voice switch enters the application.
        for phrase_id, phrase in PHRASES:
            if model_id == 'v3_en':
                spans = [span.text for span in language_spans(clean_speech(phrase)) if span.language == 'en']
                variants = [('english-excerpt-' + str(index + 1), text) for index, text in enumerate(spans)]
            else:
                variants = [('current', prepare_speech(phrase, 'silero-v5_6-ru'))]
                if not args.current_only:
                    variants = [('literal', clean_speech(phrase)), ('legacy', normalize_speech(phrase))] + variants
            for mode, text in variants:
                row = {'phrase_id': phrase_id, 'original': phrase, 'mode': mode, 'model': model_id,
                       'speaker': speaker, 'input': text, 'synthesis_ms': [], 'audio_duration_s': None,
                       'listening': {'reviewer': None, 'observations': None, 'recognizable_names': None,
                                     'numerals': None, 'stress': None, 'pauses': None, 'joins': None}}
                if mode == 'current':
                    row.update(asdict(speech_preparation(phrase, 'silero-v5_6-ru')))
                if model_id == 'v3_en':
                    row['original_excerpt'] = text
                    text = english_input(text)
                    row['input'] = text
                for iteration in range(args.iterations):
                    started = time.perf_counter()
                    try:
                        samples = model.apply_tts(text=text, speaker=speaker, sample_rate=24000,
                                                  put_accent=True, put_yo=True)
                        row['synthesis_ms'].append(round((time.perf_counter() - started) * 1000, 3))
                        samples = samples.detach().cpu().numpy().reshape(-1)
                        row['audio_duration_s'] = len(samples) / 24000
                        if iteration == 0 and args.retain_audio:
                            filename = f'eval-{model_id}-{mode}-{phrase_id}.wav'
                            with wave.open(str(args.output / filename), 'wb') as output:
                                output.setnchannels(1); output.setsampwidth(2); output.setframerate(24000)
                                output.writeframes((np.clip(samples, -1, 1) * 32767).astype('<i2').tobytes())
                            row['audio'] = filename
                            row['audio_sha256'] = identity(args.output / filename)
                    except Exception as exc:
                        # Failed inputs remain failures, never silent WAV placeholders.
                        row['error'] = type(exc).__name__
                        break
                report['rows'].append(row)
        del model
    (args.output / 'evaluation.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    if args.retain_audio:
        rows = []
        for row in report['rows']:
            audio = ('<audio controls preload="none" src="' + html.escape(row['audio'], quote=True) + '"></audio>'
                     if row.get('audio') else 'Unsupported input: ' + html.escape(row.get('error', 'unavailable')))
            stages = '<br>'.join(html.escape(key + ': ' + row[key]) for key in
                ('original_text', 'cleaned_text', 'pronunciation_text', 'tts_input') if key in row)
            rows.append('<tr><td>' + html.escape(row['phrase_id'] + ': ' + row['original']) + '</td><td>'
                        + row['model'] + ' / ' + row['speaker'] + ' / ' + row['mode']
                        + '</td><td>' + (stages or html.escape(row['input'])) + '</td><td>' + audio
                        + '</td><td>Reviewer: pending<br>Names / numerals / stress / pauses / joins: unrated</td></tr>')
        (args.output / 'listen.html').write_text('<!doctype html><meta charset="utf-8"><title>Silero comparison</title>'
            '<h1>Listening review pending</h1><p>Compare intelligibility, recognizable names, voice consistency, pauses and joins. '
            'English files are excerpts with en_0, not xenia. WAV generation does not prove quality.</p>'
            '<p>Record reviewer and observations in each evaluation.json row. Match phrase ID and WAV SHA256.</p>'
            '<table border="1"><thead><tr><th>Original</th><th>Variant</th><th>Stages</th><th>Audio</th><th>Listening</th></tr></thead><tbody>'
            + ''.join(rows) + '</tbody></table>', encoding='utf-8')
    print(json.dumps({'rows': len(report['rows']), 'errors': sum('error' in row for row in report['rows']),
                      'output': str(args.output)}, ensure_ascii=False))
    current = [row for row in report['rows'] if row['mode'] == 'current']
    if len(current) != len(PHRASES) or any('error' in row for row in current):
        raise SystemExit(1)


if __name__ == '__main__':
    main()
