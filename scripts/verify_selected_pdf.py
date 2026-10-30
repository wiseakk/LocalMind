"""Real selected-file extraction -> production chat -> local Ollama evidence.

Only a generated project-local PDF is read. No desktop actions, personal files,
downloads or inference doubles. Run with --model for an installed local model.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import httpx
from fastapi.testclient import TestClient
from pypdf import PdfWriter
from pypdf.generic import DictionaryObject, NameObject, DecodedStreamObject

from localmind import file_access, server
from localmind.generation import GenerationSettings
from localmind.settings import settings


def fixture(path, code):
    writer = PdfWriter()
    page = writer.add_blank_page(width=600, height=800)
    font = writer._add_object(DictionaryObject({NameObject('/Type'): NameObject('/Font'),
        NameObject('/Subtype'): NameObject('/Type1'), NameObject('/BaseFont'): NameObject('/Helvetica')}))
    page[NameObject('/Resources')] = DictionaryObject({NameObject('/Font'): DictionaryObject({NameObject('/F1'): font})})
    stream = DecodedStreamObject()
    stream.set_data(f'BT /F1 12 Tf 20 700 Td (Project code: {code}. The approved budget is 739 rubles.) Tj ET'.encode('ascii'))
    page[NameObject('/Contents')] = writer._add_object(stream)
    writer.write(path)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--model', default=settings.model)
    args = parser.parse_args()
    GenerationSettings(args.model)  # Use the same local model-name validation.
    folder = ROOT / '.test-artifacts' / ('pdf-evidence-' + uuid.uuid4().hex)
    folder.mkdir(parents=True)
    code = 'LM-' + uuid.uuid4().hex[:10].upper()
    fixture(folder / 'ordinary.pdf', code)
    service = file_access.FileAccess(lambda: folder)
    service.set_folder_permission(True, service.folder_info()['fingerprint'])
    old_service, old_server_service = file_access.file_access, server.file_access
    original_send = httpx.Client.send
    included, rows = [], []
    selected = None

    def observe(client, request, *a, **k):
        # Observer forwards the exact request to the real transport unchanged.
        if request.url.path == '/api/chat' and request.url.port == 11434:
            body = json.loads(request.content)
            for message in body.get('messages', []):
                content = message.get('content', '')
                try:
                    document = json.loads(content[content.index('{'):])
                except (ValueError, TypeError):
                    continue
                if isinstance(document, dict) and document.get('id') == selected:
                    text = document.get('text', '')
                    included.append({'contains_fixture_code': code in text, 'characters': len(text),
                        'source_sha256': hashlib.sha256(text.encode()).hexdigest()})
        return original_send(client, request, *a, **k)

    report = {'model': args.model, 'kind': 'real synthetic PDF / local Ollama; no browser or microphone evidence'}
    try:
        file_access.file_access = server.file_access = service
        httpx.Client.send = observe
        with TestClient(server.app, base_url='http://127.0.0.1', client=('127.0.0.1', 1)) as client:
            def turn(text, conversation=None):
                started = time.monotonic()
                response = client.post('/api/chat', json={'text': text, 'conversation_id': conversation,
                    'actions_authorized': True, 'compose_actions': False, 'model': args.model,
                    'response_tokens': 512, 'context_tokens': 8192})
                response.raise_for_status()
                result = response.json()
                rows.append({'engine': result['engine'], 'latency_ms': round((time.monotonic()-started)*1000),
                    'actions': [{k: a.get(k) for k in ('action', 'success', 'execution_status', 'observed_state')}
                        for a in result['action_results']]})
                return result
            found = turn('Найди последний PDF в Downloads')
            assert found['action_results'][0]['success'], 'Fixture selection failed'
            conversation = found['conversation_id']
            selected = found['action_results'][0]['data']['file_id']
            named = turn('Скажи название последнего PDF-файла', conversation)
            assert named['display_text'] == 'ordinary.pdf'
            summary = turn('Расскажи о содержимом этого PDF', conversation)
            assert summary['engine'] == 'ollama', 'Real generation failed'
            assert summary['action_results'][0]['action'] == 'files.read_selected_file'
            assert summary['action_results'][0]['observed_state'] == 'text_extracted'
            assert any(x['contains_fixture_code'] for x in included), 'Extraction did not reach real Ollama'
            assert code.casefold() in summary['answer'].casefold() and '739' in summary['answer'], 'Summary omitted source-only facts'
            assert summary.get('attachment_state') == 'included_in_inference'
            service.set_folder_permission(False, service.folder_info()['fingerprint'])
            denied = turn('Прочитай этот PDF', conversation)
            assert not denied['action_results'][0]['success'] and denied['engine'] != 'ollama'
            report.update(verified=True, actual_ollama_source=included, rows=rows,
                          summary_sha256=hashlib.sha256(summary['answer'].encode()).hexdigest())
    except Exception as exc:
        report.update(verified=False, error=type(exc).__name__, reason=str(exc) if isinstance(exc, AssertionError) else 'Probe unavailable', rows=rows)
    finally:
        httpx.Client.send = original_send
        file_access.file_access, server.file_access = old_service, old_server_service
        server.store.close()
    (folder / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=True))
    return 0 if report.get('verified') else 1


if __name__ == '__main__':
    raise SystemExit(main())
