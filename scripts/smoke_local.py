"""Actual loopback smoke. Uses DEMO lamp only, never launches/closes applications."""
import json
import os
import time
import uuid

import httpx


def main():
    headers = {'X-LocalMind-Key': os.getenv('LOCALMIND_KEY', '')}
    with httpx.Client(base_url='http://127.0.0.1:8765', headers=headers,
                      timeout=90, trust_env=False) as client:
        info = client.get('/api/info')
        info.raise_for_status()
        data = info.json()
        if not data['demo']:
            raise SystemExit('Smoke requires DEMO_MODE=true. No real devices were touched.')
        preview = client.post('/api/chat', json={'text': 'Включи лампу', 'actions_authorized': False})
        preview.raise_for_status()
        assert preview.json()['confirmation_required']
        body = {'text': 'Включи лампу', 'request_id': uuid.uuid4().hex,
                'server_instance': data['server_instance'], 'response_length': 'brief'}
        started = time.monotonic()
        events = []
        with client.stream('POST', '/api/chat/stream', json=body) as response:
            response.raise_for_status()
            for line in response.iter_lines():
                event = json.loads(line)
                elapsed = round((time.monotonic() - started) * 1000)
                print(json.dumps({'event': event['type'], 'received_ms': elapsed,
                                  'data': event.get('data')}, ensure_ascii=False))
                events.append(event)
        assert [event['type'] for event in events] == ['status', 'final']
        assert events[0]['data']['action_results'][0]['mode'] == 'DEMO'
        assert events[0]['data']['action_results'][0]['observed_state'] == 'on'
        replay = client.post('/api/chat', json=body)
        replay.raise_for_status()
        assert replay.json() == events[-1]['data']
        print('JSON/stream replay identical; execution count is independently covered by unit tests.')
        refusal = client.post('/api/chat', json={'text': 'Закрой блокнот', 'response_length': 'brief'})
        refusal.raise_for_status()
        assert not refusal.json()['action_results'][0]['success']
        print(json.dumps({'safe_close_refusal': refusal.json()}, ensure_ascii=False))
        question = client.post('/api/chat', json={'text': 'Что такое RSA-шифрование? Объясни роль открытого и закрытого ключей.',
                                                 'response_length': 'normal'})
        question.raise_for_status()
        assert question.json()['actions'] == []
        print(json.dumps({'educational_dialogue': question.json()}, ensure_ascii=False))


if __name__ == '__main__':
    main()
