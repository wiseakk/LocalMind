"""Stdlib-only manifest validation, also usable by isolated TTS interpreters."""
import hashlib
import json
from .paths import APP_ROOT, MODELS, ordinary_tree


def verify_resources(kind, model='small'):
    manifest = json.loads((APP_ROOT / 'config/voice_resources.json').read_text(encoding='utf-8'))
    if kind == 'asr' and model not in ('base', 'small', 'medium'):
        raise ValueError('Неизвестная модель распознавания.')
    prefix = 'whisper/' + model + '/' if kind == 'asr' else 'silero/'
    for asset in manifest['assets']:
        if not asset['path'].startswith(prefix):
            continue
        path = ordinary_tree(MODELS / asset['path'])
        if path.stat().st_size != asset['bytes']:
            raise ValueError('Размер ресурса не совпадает с манифестом.')
        with path.open('rb') as stream:
            digest = hashlib.file_digest(stream, 'sha256').hexdigest()
        if digest != asset['sha256']:
            raise ValueError('Контрольная сумма ресурса не совпадает.')
