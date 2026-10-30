"""Consented real Windows tool-chain probe; no mocks and no model downloads.

python scripts/probe_realworld.py --desktop
Opens Obsidian and the latest PDF in Downloads. Does not close user windows,
change persistent grants, write personal files, record audio or log PDF text.
Browser composer and human microphone/speaker checks are separate.
"""
import argparse
import ctypes
from ctypes import wintypes as w
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import httpx
from fastapi.testclient import TestClient
from localmind import agent, server
from localmind.apps import catalog
from localmind.capabilities import _windows
from localmind.file_access import file_access


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--desktop', action='store_true', help='Consent to launch/focus Obsidian and read/open latest Downloads PDF locally')
    args = parser.parse_args()
    if not args.desktop or sys.platform != 'win32':
        parser.error('Windows and explicit --desktop are required.')
    report = {'utc': datetime.now(timezone.utc).isoformat(), 'model': 'qwen3.5:9b',
              'kind': 'real local API/Win32/Ollama; no browser or microphone evidence', 'rows': []}
    client = TestClient(server.app, base_url='http://127.0.0.1', client=('127.0.0.1', 12))
    send = httpx.Client.send
    expected_text, expected_file_id, included = '', '', []
    def observe(instance, request, *a, **k):
        if request.url.port == 11434 and request.url.path == '/api/chat':
            body = json.loads(request.content)
            for message in body.get('messages', []):
                content = message.get('content', '')
                try:
                    document = json.loads(content[content.index('{'):])
                except (ValueError, TypeError):
                    continue
                if isinstance(document, dict) and document.get('id') == expected_file_id:
                    actual = document.get('text', '')
                    included.append(bool(actual and any(expected_text[i:i+80] in actual
                        for i in range(0, max(1, len(expected_text)-80), 80))))
                    report['sent_source'] = {'characters': len(actual), 'sha256': hashlib.sha256(actual.encode()).hexdigest()}
        return send(instance, request, *a, **k)
    def turn(text, key=None):
        result = client.post('/api/chat', json={'text': text, 'conversation_id': key,
            'model': 'qwen3.5:9b', 'context_tokens': 8192, 'response_tokens': 512,
            'actions_authorized': True, 'compose_actions': False}).json()
        # No personal filenames, paths, document text or summaries in evidence.
        report['rows'].append({'request': text, 'engine': result.get('engine'),
            'actions': [{k: r.get(k) for k in ('action', 'success', 'execution_status', 'observed_state')}
                        for r in result.get('action_results', [])],
            'answer_sha256': hashlib.sha256(result.get('answer', '').encode()).hexdigest()})
        return result
    try:
        catalog.refresh()
        candidates = [x for x in catalog.entries() if x['name'].casefold() == 'obsidian']
        if len(candidates) == 1:
            app = candidates[0]
            catalog.set_permission(app['id'], True, app['fingerprint'])
            first = turn('Открой Obsidian')
            focused = turn('А можешь вывести его на передний план?', first['conversation_id'])
            last = focused.get('action_results', [{}])[0]
            key = (last.get('data') or {}).get('window_id')
            selected = _windows()._selections.get(key)
            user = ctypes.WinDLL('user32'); user.GetForegroundWindow.restype = w.HWND
            report['foreground_hwnd'] = user.GetForegroundWindow()
            report['selected_hwnd'] = selected.native.hwnd if selected else None
            report['foreground_matches'] = bool(selected and user.GetForegroundWindow() == selected.native.hwnd)
        else:
            report['obsidian'] = 'not uniquely present in actual catalog'
        info = file_access.folder_info()
        file_access.set_folder_permission(True, info['fingerprint'])
        found = turn('Найди последний PDF в папке Downloads.')
        key = found.get('conversation_id')
        actions = found.get('action_results') or []
        if actions and actions[0]['success']:
            file_id = actions[0]['data']['file_id']
            expected_file_id = file_id
            extracted = file_access.read_selected(key, file_id)
            if extracted.success:
                expected_text = extracted.data['text']
                httpx.Client.send = observe
                summary = turn('Что в нём?', key)
                httpx.Client.send = send
                report['extraction'] = {'characters': len(expected_text),
                    'sha256': hashlib.sha256(expected_text.encode()).hexdigest(),
                    'actual_ollama_source_inclusion': any(included),
                    'summary_engine': summary.get('engine')}
                file_access.set_open_permission(key, file_id, True)
                turn('Открой его.', key)
                report['pdf_window_observation'] = 'pending independent desktop observation; os.startfile acceptance alone is insufficient'
            else:
                report['extraction'] = {'success': False, 'status': extracted.execution_status}
        else:
            report['downloads'] = 'no verified PDF selected; inspect permission/result locally'
    except Exception as exc:
        report['probe_error'] = type(exc).__name__  # no native exceptions/paths
    finally:
        httpx.Client.send = send
        _windows().close()
        server.store.close()
    target = ROOT / '.test-artifacts' / 'realworld-probe.json'
    target.parent.mkdir(exist_ok=True)
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=True))
    return 0 if report.get('foreground_matches') and report.get('extraction', {}).get('actual_ollama_source_inclusion') else 1


if __name__ == '__main__':
    raise SystemExit(main())
