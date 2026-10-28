"""Actual loopback integration evidence. Never confuses a mock with Windows.

Default: local dialogue, stream/replay, model error, DEMO lamp only.
--steam explicitly exercises the discovered Steam entry with temporary permission;
it may launch Steam if Windows verifies it absent. No app is closed or killed.
"""
from concurrent.futures import ThreadPoolExecutor
import argparse
import json
import os
from pathlib import Path
import time
import uuid

import httpx


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--steam', action='store_true')
    parser.add_argument('--output', type=Path, default=Path('docs/evidence/app-overhaul-2026-10-28.json'))
    args = parser.parse_args()
    report = {'kind': 'actual loopback integration, no microphone or browser claims', 'flows': []}
    with httpx.Client(base_url='http://127.0.0.1:8765', timeout=110, trust_env=False,
                      headers={'X-LocalMind-Key': os.getenv('LOCALMIND_KEY', '')}) as client:
        info = client.get('/api/info').raise_for_status().json()
        report['model'] = info['model']
        report['server_instance'] = info['server_instance']

        def chat(text, **extra):
            body = {'text': text, 'request_id': uuid.uuid4().hex, 'server_instance': info['server_instance'], **extra}
            started = time.perf_counter()
            response = client.post('/api/chat', json=body)
            response.raise_for_status()
            return {'text': text, 'elapsed_ms': (time.perf_counter()-started)*1000, 'response': response.json()}

        report['models'] = client.get('/api/models').raise_for_status().json()
        report['flows'].append(chat('Привет', model='localmind-uninstalled-regression:latest'))
        body = {'text': 'Объясни разницу между списком и кортежем в Python.', 'request_id': uuid.uuid4().hex,
                'server_instance': info['server_instance']}
        events, started = [], time.perf_counter()
        with client.stream('POST', '/api/chat/stream', json=body) as response:
            response.raise_for_status()
            for line in response.iter_lines():
                if line:
                    events.append({'received_ms': (time.perf_counter()-started)*1000, **json.loads(line)})
        final = events[-1]['data']
        replay = client.post('/api/chat', json=body).raise_for_status().json()
        assert replay == final
        report['stream'] = {'events': events, 'replay_identical': True,
                            'first_answer_delta_ms': next((e['received_ms'] for e in events if e['type']=='delta'), None),
                            'browser_visible_ms': None}
        report['flows'].append(chat('А в чём они похожи?', history=[
            {'role': 'user', 'content': body['text']}, {'role': 'assistant', 'content': final['answer']}]))
        if info['demo']:
            report['flows'].append(chat('Включи лампу'))
        if args.steam:
            apps = client.get('/api/apps').raise_for_status().json()['apps']
            steam = [a for a in apps if 'steam' in a.get('aliases', []) or a['name'].casefold() == 'steam']
            report['steam'] = {'catalog_matches': len(steam)}
            if len(steam) == 1:
                item = steam[0]
                permission = {'app_id': item['id'], 'fingerprint': item['fingerprint'], 'allowed': True}
                client.post('/api/apps/permission', json=permission).raise_for_status()
                try:
                    positives = ['Открой Steam', 'Открой, пожалуйста, Steam', 'Можешь открыть Steam?', 'Запусти мне Steam']
                    with ThreadPoolExecutor(max_workers=2) as pool:
                        report['steam']['concurrent'] = list(pool.map(lambda t: chat(t, compose_actions=False), positives[:2]))
                    report['steam']['repeated'] = [chat(t, compose_actions=False) for t in positives[2:]]
                    report['steam']['negative'] = [chat(t, compose_actions=False) for t in [
                        'Не открывай Steam', 'Как открыть Steam?', '«Открой Steam»',
                        'Если я попрошу, открой Steam', 'Открой Steam и Obsidian']]
                    for row in report['steam']['negative']:
                        assert not any(r['success'] for r in row['response']['action_results'])
                finally:
                    if not item['allowed']:
                        client.post('/api/apps/permission', json={**permission, 'allowed': False}).raise_for_status()
        report['diagnostics'] = client.get('/api/diagnostics').raise_for_status().json()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print(str(args.output))
    print('Completed actual HTTP flows. Read responses: HTTP success alone is not quality acceptance.')


if __name__ == '__main__':
    main()
