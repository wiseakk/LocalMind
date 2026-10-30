"""Real local Qwen response screening against a checked public source fixture.

Does not execute tools or download assets. Screening is not a general factuality
score. Retains public-source responses for review, never personal content.
"""
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from localmind.agent import prepare_reply, complete_reply
from localmind.generation import GenerationSettings


def main():
    root = Path(__file__).resolve().parents[1]
    fixture = json.loads((root / 'tests/data/warcraft_grounding.json').read_text(encoding='utf-8'))
    rows = []
    for case in fixture['cases']:
        prepared = prepare_reply(case['question'], document_facts=[{
            'id': 'checked-public-source', 'name': fixture['source_title'], 'text': fixture['text'],
            'kind': 'document', 'characters': len(fixture['text']), 'truncated': False}],
            generation=GenerationSettings('qwen3.5:9b', context_tokens=8192, response_tokens=512))
        final = complete_reply(prepared)
        rows.append({'question': case['question'], 'answer': final['answer'], 'engine': final['engine'],
            'screening': all(word.casefold() in final['answer'].casefold() for word in case['required']),
            'actions': final['action_results']})
    report = {'model': 'qwen3.5:9b', 'source': fixture['source_url'], 'rows': rows,
              'limits': 'Two source-bound cases; no claim of general lore accuracy or human review.'}
    output = root / '.test-artifacts' / 'grounding-probe.json'; output.parent.mkdir(exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=True))
    return 0 if all(r['screening'] and r['engine'] == 'ollama' and not r['actions'] for r in rows) else 1


if __name__ == '__main__':
    raise SystemExit(main())
