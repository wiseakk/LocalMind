"""Exercise production upload -> context -> real local Ollama, with fixture data.

Run: .venv\Scripts\python.exe scripts/verify_multimodal.py
No model download, browser simulation, personal file read or desktop action.
The request observer records hashes/counts only and never substitutes inference.
"""
from __future__ import annotations

import argparse
import base64
from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import httpx
from fastapi.testclient import TestClient
from PIL import Image, ImageDraw, ImageFont
from pypdf import PdfWriter
from pypdf.generic import DictionaryObject, NameObject, DecodedStreamObject

from localmind import server

IMAGE_MARKER = 'LMV-8142'
DOCUMENT_MARKER = 'LM-DOC-9271'


def image_fixture():
    image = Image.new('RGB', (900, 700), 'white')
    draw = ImageDraw.Draw(image)
    draw.polygon([(450, 80), (160, 500), (740, 500)], fill='red')
    # The font is a read-only Windows system asset, never copied or modified.
    try:
        font = ImageFont.truetype('arial.ttf', 64)
    except OSError:
        font = ImageFont.load_default(size=64)
    draw.text((260, 570), IMAGE_MARKER, font=font, fill='black')
    output = io.BytesIO()
    image.save(output, 'PNG')
    return output.getvalue()


def pdf_fixture():
    writer = PdfWriter()
    font = DictionaryObject({NameObject('/Type'): NameObject('/Font'),
        NameObject('/Subtype'): NameObject('/Type1'), NameObject('/BaseFont'): NameObject('/Helvetica')})
    font_id = writer._add_object(font)
    for number in range(1, 23):
        page = writer.add_blank_page(width=600, height=800)
        page[NameObject('/Resources')] = DictionaryObject({NameObject('/Font'):
            DictionaryObject({NameObject('/F1'): font_id})})
        text = ('Background information. ' * 180 if number != 22 else
                f'Project code: {DOCUMENT_MARKER}. The approved budget is 731 rubles.')
        stream = DecodedStreamObject()
        stream.set_data(('BT /F1 12 Tf 20 700 Td (' + text + ') Tj ET').encode('ascii'))
        page[NameObject('/Contents')] = writer._add_object(stream)
    output = io.BytesIO()
    writer.write(output)
    return output.getvalue()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--model', default='qwen3.5:9b')
    parser.add_argument('--output', type=Path, default=ROOT / 'docs/evidence/redemption-multimodal.json')
    args = parser.parse_args()
    observed, rows = [], []
    original_send = httpx.Client.send

    def observe(client, request, *send_args, **send_kwargs):
        if request.url.port == 11434 and request.url.path == '/api/chat':
            body = json.loads(request.content)
            messages = body.get('messages', [])
            images = [image for message in messages for image in message.get('images', [])]
            text = '\n'.join(message.get('content', '') for message in messages)
            observed.append({'model': body['model'], 'path': '/api/chat', 'image_count': len(images),
                'image_sha256': [hashlib.sha256(base64.b64decode(image, validate=True)).hexdigest() for image in images],
                'document_marker_present': DOCUMENT_MARKER in text,
                'later_page_label_present': '[Страница 22]' in text,
                'request_sha256': hashlib.sha256(request.content).hexdigest()})
        return original_send(client, request, *send_args, **send_kwargs)

    client = TestClient(server.app, base_url='http://127.0.0.1', client=('127.0.0.1', 12))
    headers = {'X-LocalMind-Key': server.settings.key} if server.settings.key else {}

    def conversation():
        response = client.post('/api/conversations', json={}, headers=headers)
        response.raise_for_status()
        return response.json()['conversation_id']

    def upload(key, name, data):
        response = client.post('/api/attachments', headers=headers,
            data={'conversation_id': key, 'server_instance': server.SERVER_INSTANCE}, files={'file': (name, data)})
        response.raise_for_status()
        return response.json()

    def turn(key, text, ids, scenario, expected):
        start, before = time.monotonic(), len(observed)
        response = client.post('/api/chat', headers=headers, json={'conversation_id': key,
            'server_instance': server.SERVER_INSTANCE, 'text': text, 'attachment_ids': ids,
            'model': args.model, 'context_tokens': 8192, 'response_tokens': 512})
        elapsed = round((time.monotonic() - start) * 1000)
        result = response.json()
        sent = observed[before:]
        answer = result.get('answer', '')
        row = {'scenario': scenario, 'intent': 'attachment_question', 'tool': 'local_upload_and_inference',
            'resolved_target': ids, 'permission_decision': 'explicit_attachment_in_owning_conversation',
            'http_status': response.status_code, 'observable_state': result.get('attachment_state'),
            'actual_request': sent, 'final_response': answer, 'latency_ms': elapsed,
            'model_answer_checks': {name: bool(check(answer)) for name, check in expected.items()},
            'failure_reason': None}
        if response.status_code != 200 or result.get('engine') in ('offline-error', 'vision-unavailable'):
            row['failure_reason'] = result.get('answer', result.get('detail', 'API failed'))
        elif not sent:
            row['failure_reason'] = 'No outgoing real Ollama chat request observed'
        elif not all(row['model_answer_checks'].values()):
            row['failure_reason'] = 'Model answer did not identify all fixture facts'
        rows.append(row)
        return row

    try:
        httpx.Client.send = observe
        key = conversation()
        image = upload(key, 'red-triangle.png', image_fixture())
        turn(key, 'Что на картинке? Назови фигуру, цвет и точную надпись.', [image['id']], 'image_object_and_text', {
            'object': lambda answer: 'треуголь' in answer.casefold() or 'triangle' in answer.casefold(),
            'color': lambda answer: 'красн' in answer.casefold() or 'red' in answer.casefold(),
            'text': lambda answer: IMAGE_MARKER in answer})
        turn(key, '', [image['id']], 'image_only', {'text': lambda answer: IMAGE_MARKER in answer})
        document_key = conversation()
        document = upload(document_key, 'later-page.pdf', pdf_fixture())
        turn(document_key, 'Какой код проекта и бюджет на странице 22? Назови страницу.', [document['id']],
            'document_later_page_same_turn', {'code': lambda answer: DOCUMENT_MARKER in answer,
             'budget': lambda answer: '731' in answer, 'page': lambda answer: '22' in answer})
        turn(document_key, 'Повтори код проекта и бюджет на странице 22.', [], 'document_followup', {
            'code': lambda answer: DOCUMENT_MARKER in answer, 'budget': lambda answer: '731' in answer})
    except Exception as exc:
        rows.append({'scenario': 'probe_setup_or_transport', 'failure_reason': type(exc).__name__ + ': ' + str(exc)})
    finally:
        httpx.Client.send = original_send
        server.store.close()
    report = {'generated_utc': datetime.now(timezone.utc).isoformat(), 'model': args.model,
        'kind': 'real production API and real Ollama; fixture uploads; not browser visual or microphone evidence',
        'model_downloaded': False, 'rows': rows,
        'all_passed': len(rows) == 4 and all(row.get('failure_reason') is None for row in rows)}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'output': str(args.output), 'all_passed': report['all_passed'],
                      'rows': [{'scenario': row['scenario'], 'failure_reason': row.get('failure_reason')} for row in rows]}))
    return 0 if report['all_passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
