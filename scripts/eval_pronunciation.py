"""Offline CMUdict/ARPAbet versus compact English sound-rule experiment.

Supply an explicitly downloaded CMUdict data file; no downloads or subprocesses.
The optional WAVs use the unchanged Russian xenia engine, never an English voice.
Textual coverage and WAV production do not establish perceptual quality.
"""
import argparse
import hashlib
import html
import json
import os
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from localmind.speech_text import transliterate_english

WORDS = ('Warcraft', 'Diablo', 'Immortal', 'Blizzard', 'Entertainment', 'Hearthstone',
         'Heroes', 'Storm', 'Crystal', 'Phoenix', 'Zephyr', 'Aurora', 'Silver',
         'Riven', 'Nebula', 'Notion', 'Qzora', 'Kubernetes')
ARPABET = dict(zip(
    'AA AE AH AO AW AY B CH D DH EH ER EY F G HH IH IY JH K L M N NG OW OY P R S SH T TH UH UW V W Y Z ZH'.split(),
    ('а', 'э', 'а', 'о', 'ау', 'ай', 'б', 'ч', 'д', 'з', 'э', 'ер', 'эй', 'ф',
     'г', 'х', 'и', 'и', 'дж', 'к', 'л', 'м', 'н', 'нг', 'оу', 'ой', 'п', 'р',
     'с', 'ш', 'т', 'т', 'у', 'у', 'в', 'в', 'й', 'з', 'ж')))


def phonemes_to_cyrillic(phonemes):
    """Evaluation approximation only; raises rather than dropping unknown phones."""
    return ''.join(ARPABET[re.sub(r'[012]$', '', phone)] for phone in phonemes)


def load_lexicon(path):
    lexicon = {}
    for line in path.read_text(encoding='utf-8').splitlines():
        if not line or line.startswith(';;;'):
            continue
        word, *phones = line.split(' #', 1)[0].split()
        word = re.sub(r'\(\d+\)$', '', word).casefold()
        lexicon.setdefault(word, phones)
    return lexicon


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--lexicon', type=Path, required=True)
    parser.add_argument('--output', type=Path, default=ROOT / '.test-artifacts/g2p')
    parser.add_argument('--retain-audio', action='store_true')
    args = parser.parse_args()
    lexicon = load_lexicon(args.lexicon)
    args.output.mkdir(parents=True, exist_ok=True)
    report = {'lexicon_sha256': hashlib.sha256(args.lexicon.read_bytes()).hexdigest(),
              'lexicon_bytes': args.lexicon.stat().st_size, 'lexicon_words': len(lexicon),
              'model': 'v5_6_ru', 'speaker': 'xenia', 'listening_reviewer': None,
              'rows': []}
    if args.retain_audio:
        os.environ.update(HF_HUB_OFFLINE='1', HF_HUB_DISABLE_TELEMETRY='1', DO_NOT_TRACK='1')
        from localmind.tts_worker import load_engine, synthesize
        engine = load_engine('silero-v5_6-ru')
    worksheet = []
    for word in WORDS:
        phones = lexicon.get(word.casefold())
        row = {'word': word, 'compact': transliterate_english(word), 'phonemes': phones,
               'lexicon': phonemes_to_cyrillic(phones) if phones else None,
               'observations': None, 'audio': {}}
        for mode in ('compact', 'lexicon'):
            if args.retain_audio and row[mode]:
                filename = f'{word.lower()}-{mode}.wav'
                data = synthesize(engine, 'silero-v5_6-ru', 'Название: ' + row[mode] + '.')
                (args.output / filename).write_bytes(data)
                row['audio'][mode] = {'filename': filename, 'sha256': hashlib.sha256(data).hexdigest()}
                worksheet.append('<tr><td>' + html.escape(word + ' / ' + mode) + '</td><td>'
                                 + html.escape(row[mode]) + '</td><td><audio controls src="'
                                 + filename + '"></audio></td></tr>')
        report['rows'].append(row)
    report['lexicon_hits'] = sum(row['lexicon'] is not None for row in report['rows'])
    (args.output / 'comparison.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    if args.retain_audio:
        (args.output / 'listen.html').write_text('<!doctype html><meta charset="utf-8"><title>G2P comparison</title>'
            '<h1>Listening pending: compact rules / CMUdict</h1><p>Same xenia voice. Text coverage is not sound quality.</p>'
            '<table>' + ''.join(worksheet) + '</table>', encoding='utf-8')
    print(json.dumps({'words': len(WORDS), 'lexicon_hits': report['lexicon_hits'], 'output': str(args.output)}))


if __name__ == '__main__':
    main()
