"""Explicit candidate voice download. Never imported by the HTTP application.

Run only after reading docs/NEXT_VOICE.md. Inference uses fixed local files.
"""
import argparse
from contextlib import nullcontext
import hashlib
import json
from pathlib import Path
import urllib.request
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from localmind.paths import MODELS
from localmind.resource_lock import resource_download_lock
CHATTERBOX_REVISION = '5bb1f6ee58e50c3b8d408bc82a6d3740c2db6e18'
CHATTERBOX_FILES = ('ve.pt', 't3_mtl23ls_v3.safetensors', 's3gen.pt',
                    'grapheme_mtl_merged_expanded_v1.json', 'conds.pt', 'Cangjie5_TC.json')


def download(url, destination):
    temporary = destination.with_suffix(destination.suffix + '.partial')
    digest, count = hashlib.sha256(), 0
    try:
        with urllib.request.urlopen(url, timeout=30) as source, temporary.open('wb') as output:
            while chunk := source.read(1024 * 1024):
                count += len(chunk)
                if count > 3 * 1024 * 1024 * 1024:
                    raise ValueError('Asset exceeds download budget')
                output.write(chunk)
                digest.update(chunk)
        if count == 0:
            raise ValueError('Empty asset')
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)
    return {'filename': destination.name, 'bytes': count, 'sha256': digest.hexdigest(), 'source': url}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('candidate', choices=('silero', 'chatterbox'))
    parser.add_argument('--english-evaluation', action='store_true',
                        help='Silero only: also download v3_en for listening evaluation; no app routing')
    args = parser.parse_args()
    if args.english_evaluation and args.candidate != 'silero':
        parser.error('--english-evaluation requires silero')
    if args.candidate == 'silero':
        folder = MODELS / 'silero'
        urls = [('v5_6_ru.pt', 'https://models.silero.ai/models/tts/ru/v5_6_ru.pt')]
        if args.english_evaluation:
            urls.append(('v3_en.pt', 'https://models.silero.ai/models/tts/en/v3_en.pt'))
    else:
        folder = MODELS / 'chatterbox-v3'
        urls = [(name, f'https://huggingface.co/ResembleAI/chatterbox/resolve/{CHATTERBOX_REVISION}/{name}') for name in CHATTERBOX_FILES]
    # The evaluation CLI writes the same Russian Silero file as desktop setup.
    # Share its OS lock instead of racing the application's resumable transfer.
    with (resource_download_lock(MODELS, 'silero:ru') if args.candidate == 'silero' else nullcontext()):
        folder.mkdir(parents=True, exist_ok=True)
        manifest = [download(url, folder / name) for name, url in urls]
        (folder / 'download-manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    print('Assets downloaded locally; hashes recorded. No inference or voice quality claim was made.')


if __name__ == '__main__':
    main()
