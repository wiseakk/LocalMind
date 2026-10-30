"""Deterministic tests, not microphone, speaker or factuality benchmarks."""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from localmind import agent, voice
from localmind.conversations import Conversation
from localmind.generation import GenerationSettings
from localmind.results import ActionResult, file_output
from localmind.speech_text import normalize_speech, pronounce_filename
from scripts.eval_stt import technical_score


def test_file_channels_speak_only_selected_filename_and_keep_exact_metadata():
    metadata = {'filename': 'Warcraft_RSA_2026.pdf', 'path': 'C:/private/Downloads/Warcraft_RSA_2026.pdf',
                'sha256': 'a' * 64, 'modified_at': '2026-10-30T12:00:00+00:00',
                'files': [{'filename': 'Warcraft_RSA_2026.pdf'}, {'filename': 'other-secret.pdf'}]}
    result = ActionResult(True, 'files.search', 'opaque', 'observed', data=metadata)
    display, speech = file_output(result)
    assert metadata['filename'] in display
    assert 'Варкрафт' in speech and 'эр эс эй' in speech and 'PDF-файл' in speech
    assert all(value not in speech for value in ('C:', 'private', metadata['sha256'], 'T12:', 'other-secret'))
    assert metadata['filename'] == 'Warcraft_RSA_2026.pdf'


@pytest.mark.parametrize('written,spoken', [('Downloads', 'Даунлоудс'), ('Obsidian', 'Обсидиан'), ('Warcraft', 'Варкрафт'), ('PDF', 'пи ди эф'), ('RSA', 'эр эс эй')])
def test_requested_pronunciation(written, spoken):
    assert spoken in normalize_speech(written)
    assert spoken.casefold() in pronounce_filename(written + '_notes.pdf').casefold()
    english = written if written not in ('PDF', 'RSA') else ' '.join(written)
    assert english in pronounce_filename(written, 'en')


def test_signal_levels_and_confidence_do_not_rewrite_transcript(monkeypatch):
    assert voice.signal_levels([.002] * 100)['warnings'] == ['quiet_input']
    assert voice.signal_levels([1.] * 100)['warnings'] == ['clipping']
    assert not voice.signal_levels([.1] * 100)['warnings']
    observed = []
    class Model:
        def __init__(self, *a, **k):
            assert k['local_files_only']
        def transcribe(self, signal, **kwargs):
            observed.append(kwargs)
            return [SimpleNamespace(text=' Не открывай Steam ', avg_logprob=-1.5, no_speech_prob=.1)], SimpleNamespace(language='ru')
    monkeypatch.setitem(__import__('sys').modules, 'faster_whisper', SimpleNamespace(WhisperModel=Model))
    monkeypatch.setattr(voice, '_decode_bounded', lambda _: [.1] * 16000)
    result = voice._recognize(Path('unused'), 'balanced', 'technical-auto')
    assert result['text'] == 'Не открывай Steam'
    assert result['quality']['calibrated_confidence'] is None
    assert result['quality']['review_recommended'] and result['final']
    assert observed[0]['language'] is None and 'Downloads' in observed[0]['hotwords']
    assert voice.DECODINGS['baseline']['language'] == 'ru'


def test_technical_scoring_is_evaluation_only():
    assert technical_score('PDF в Downloads', 'PDF в загрузках') == {
        'technical_names': 2, 'technical_names_correct': 1, 'missing_technical_names': ['Downloads']}
    assert technical_score('Warcraft_RSA.pdf', 'Warcraft_RSA.pdf')['technical_names_correct'] == 3
    assert technical_score('PDF', 'PDFake')['technical_names_correct'] == 0


def test_benchmark_comparison_refuses_changed_recordings(tmp_path, monkeypatch, capsys):
    from scripts import eval_stt
    recording = tmp_path / 'voice.wav'; recording.write_bytes(b'a' * 128)
    calls = []
    def recognize(*args):
        calls.append(args)
        return {'text': 'PDF', 'device': 'cpu', 'fallback': False}
    monkeypatch.setattr(eval_stt, 'transcribe_audio', recognize)
    options = SimpleNamespace(profile='balanced', include_transcripts=False)
    rows = [{'id': '1', 'path': 'voice.wav', 'reference': 'PDF'}]
    hashes = {}
    assert eval_stt.evaluate(rows, tmp_path / 'manifest.csv', options, 'baseline', hashes) == 0
    recording.write_bytes(b'b' * 128)
    assert eval_stt.evaluate(rows, tmp_path / 'manifest.csv', options, 'technical-auto', hashes) == 1
    assert len(calls) == 1 and 'Recording changed' in capsys.readouterr().out


def test_budget_preserves_question_and_reranks_later_page_before_old_history(monkeypatch):
    seen = []
    c = Conversation('owner', 0)
    c.history = [{'role': 'user', 'content': 'obsolete ' * 200} for _ in range(8)]
    document = {'id': 'doc', 'name': 'checked.pdf', 'text': '[Страница 1]\n' + 'background ' * 1000 + '\n[Страница 22]\nProject ORBIT-739 budget 731',
                'characters': 12000, 'kind': 'document', 'truncated': False}
    def infer(messages, *a, **k):
        seen.extend(messages)
        return {'content': '{"answer":"ORBIT-739: 731."}'}
    monkeypatch.setattr(agent, 'ollama_chat', infer)
    prepared = agent.prepare_reply('Какой проект и бюджет на странице 22?', conversation=c, document_facts=[document],
        generation=GenerationSettings('qwen3.5:9b', context_tokens=4096, response_tokens=512))
    final = agent.complete_reply(prepared)
    assert final['engine'] == 'ollama'
    assert seen[-1]['content'] == prepared.text
    assert 'ORBIT-739' in json.dumps(seen) and all('_document' not in m for m in seen)
    assert final['context_budget']['dropped_history_messages'] > 0
    assert final['context_budget']['shortened_sources'] == 1
    assert final['speech_text'] == final['answer'] == final['display_text']


def test_small_context_failure_is_explicit_without_inference(monkeypatch):
    monkeypatch.setattr(agent, 'ollama_chat', lambda *a, **k: pytest.fail('must not send oversized context'))
    prepared = agent.prepare_reply('Вопрос ' * 280, generation=GenerationSettings('qwen3.5:9b', context_tokens=1024))
    final = agent.complete_reply(prepared)
    assert final['engine'] == 'context-budget' and 'контекст' in final['answer']


def test_capability_facts_are_compact_and_raw_status_never_enters_system_prompt(monkeypatch):
    c = Conversation('owner', 0)
    c.facts = [{'action': 'files.search', 'success': True, 'execution_status': 'observed',
                'status_text': 'RAW_STATUS_INJECTION ' * 2000, 'data': {'path': 'C:/private'}}]
    seen = []
    monkeypatch.setattr(agent, 'ollama_chat', lambda messages, *a, **k: (seen.extend(messages) or {'content': '{"answer":"Да, после проверки разрешений."}'}))
    final = agent.complete_reply(agent.prepare_reply('Можешь прочитать документ?', conversation=c))
    assert final['engine'] == 'ollama'
    system = seen[0]['content']
    assert 'files.read_selected_file' in system and 'RAW_STATUS_INJECTION' not in system and 'C:/private' not in system
