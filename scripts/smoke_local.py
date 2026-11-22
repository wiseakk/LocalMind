"""Actual loopback smoke. Uses DEMO lamp only, never launches/closes applications."""
import argparse
import io
import json
import os
import time
import uuid
import wave

import httpx


def smoke_voice(client):
    def speak(text):
        for _ in range(12):
            response = client.post('/api/tts', json={'text': text})
            if response.status_code != 429:
                return response.raise_for_status().content
            time.sleep(.5)  # The worker may still be warming up on startup.
        return response.raise_for_status().content

    prompt = speak('Что такое алгоритм?')
    recognized = client.post('/api/transcribe', files={'audio': ('smoke.wav', prompt, 'audio/wav')},
                             data={'profile': 'balanced'}).raise_for_status().json()
    assert 'алгоритм' in recognized['text'].lower(), recognized['text']
    conversation = client.post('/api/conversations', json={}).raise_for_status().json()['conversation_id']
    answer = client.post('/api/chat', json={'text': recognized['text'], 'conversation_id': conversation,
                         'response_tokens': 160}).raise_for_status().json()
    assert answer['engine'] == 'ollama' and 'алгоритм' in answer['answer'].lower()
    with wave.open(io.BytesIO(speak(answer['answer'])), 'rb') as response:
        seconds = response.getnframes() / response.getframerate()
    assert seconds > 1
    print(json.dumps({'transcript': recognized['text'], 'engine': answer['engine'],
                      'audio_seconds': seconds}, ensure_ascii=False))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--voice', action='store_true', help='Use synthetic WAV and verify the full voice pipeline')
    parser.add_argument('--port', type=int, default=8765)
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error('port must be 1 through 65535')
    headers = {'X-LocalMind-Key': os.getenv('LOCALMIND_KEY', '')}
    with httpx.Client(base_url=f'http://127.0.0.1:{args.port}', headers=headers,
                      timeout=90, trust_env=False) as client:
        info = client.get('/api/info')
        info.raise_for_status()
        data = info.json()
        if not data['demo']:
            raise SystemExit('Smoke requires DEMO_MODE=true. No real devices were touched.')
        if args.voice:
            smoke_voice(client)
            return
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
        assert events[0]['type'] == 'status' and events[-1]['type'] == 'final'
        assert all(event['type'] == 'delta' for event in events[1:-1])
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
