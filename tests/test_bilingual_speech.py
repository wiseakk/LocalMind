"""Pronunciation preparation and routing tests; these do not assess listening quality."""
import json
import logging
from pathlib import Path
import re
from unittest.mock import Mock

import pytest

from localmind import voice
from localmind.server import SpeechRequest
from localmind.speech_text import SILERO_NAMES, clean_speech, language_spans, normalize_speech, prepare_speech, speech_preparation


PHRASES = [
    ('Расскажи про Arthas Menethil из World of Warcraft', 'Артас Менетил из Ворлд оф Варкрафт'),
    ('Warcraft III: Reign of Chaos', 'Варкрафт три: Рэйн оф Кэйос'),
    ('The Frozen Throne', 'Зэ Фроузен Троун'),
    ('Heroes of the Storm', 'Хироуз оф зэ Сторм'),
    ('Hearthstone', 'Хартстоун'),
    ('Открой Obsidian', 'Открой Обсидиан'),
    ('Найди PDF в Downloads', 'Найди пи ди эф в Даунлоудс'),
    ('Я программирую на Python и C++', 'Я программирую на Пайтон и си плюс плюс'),
    ('Warcraft II', 'Варкрафт два'),
    ('Diablo Immortal', 'Диабло Иммортал'),
    ('Diablo IV', 'Диабло четыре'),
    ('Blizzard Entertainment', 'Близзард Энтертейнмент'),
    ('AI, API, PDF, RSA и C++', 'эй ай, эй пи ай, пи ди эф, эр эс эй и си плюс плюс'),
]


@pytest.mark.parametrize('original,expected', PHRASES)
def test_supplied_names_use_one_russian_speaker(original, expected):
    assert expected in prepare_speech(original, voice.DEFAULT_VOICE)
    assert not re.search('[A-Za-z]', prepare_speech(original, voice.DEFAULT_VOICE))
    assert ''.join(span.text for span in language_spans(original)) == original
    assert clean_speech(original) == original


def test_spans_are_lossless_and_detected_before_adaptation():
    text = 'Про Arthas Menethil: Python и C++, 2026!'
    spans = language_spans(text)
    assert [(span.language, span.text) for span in spans] == [
        ('ru', 'Про'), ('neutral', ' '), ('en', 'Arthas Menethil'), ('neutral', ': '),
        ('en', 'Python'), ('neutral', ' '), ('ru', 'и'), ('neutral', ' '),
        ('en', 'C++'), ('neutral', ', 2026!')]
    assert ''.join(span.text for span in spans) == text


def test_unknown_names_use_word_sounds_and_speakable_acronyms():
    assert prepare_speech('Qzora NASA', voice.DEFAULT_VOICE) == 'кзора НАСА'
    assert prepare_speech('QUANTUM', voice.DEFAULT_VOICE) == 'квантум'
    assert normalize_speech('Qzora NASA') == 'Qzora NASA'
    # A substring of an unknown word must never become a dictionary name.
    assert 'Обсидиан' not in prepare_speech('ObsidianX', voice.DEFAULT_VOICE)


@pytest.mark.parametrize('word,spoken', [('Night', 'найт'), ('Snake', 'снэйк'),
                                       ('Crystal', 'кристал'), ('Zephyr', 'зефир'),
                                       ('BLIZZARD', 'Близзард'), ('API', 'эй пи ай')])
def test_word_sounds_and_initialisms_are_different_policies(word, spoken):
    assert prepare_speech(word, voice.DEFAULT_VOICE) == spoken


@pytest.mark.parametrize('original,expected', PHRASES)
def test_requested_entities_in_complete_russian_sentences(original, expected):
    sentence = f'Сегодня мы обсуждаем {original}. Это интересная тема.'
    spoken = prepare_speech(sentence, voice.DEFAULT_VOICE)
    assert expected in spoken
    assert spoken.startswith('Сегодня мы обсуждаем ')
    assert spoken.endswith('. Это интересная тема.')
    assert not re.search('[A-Za-z]', spoken)


@pytest.mark.parametrize('text,expected', [
    ('warcraft ii, WARCRAFT III; Diablo iv!', 'Варкрафт два, Варкрафт три; Диабло четыре!'),
    ('Blizzard\n  Entertainment', 'Близзард Энтертейнмент'),
    ("Blizzard’s Diablo Immortal", 'Близзардз Диабло Иммортал'),
    ('Diablo  IV. Warcraft II.', 'Диабло четыре. Варкрафт два.'),
    ('I like AI', 'ай лайк эй ай'),
    ('IPv4 v2.1', 'ай пи ви четыре ви два запятая один'),
])
def test_context_case_whitespace_possessives_and_versions(text, expected):
    assert prepare_speech(text, voice.DEFAULT_VOICE) == expected


@pytest.mark.parametrize('text', ['API II', 'I', 'Warcraft I enjoy', 'Warcraft IV.2',
                                'Warcraft IIIx', 'Warcraft IV2', 'Diablo IV+', 'Civil IV'])
def test_numerals_require_conservative_title_context(text):
    # Arabic version digits may still be spoken; Roman IV must not become four.
    forbidden = r'\b(три|четыре)\b' if '2' in text else r'\b(два|три|четыре)\b'
    assert not re.search(forbidden, prepare_speech(text, voice.DEFAULT_VOICE))


def test_preparation_stages_are_distinct_and_display_copy_unchanged():
    original = '**Warcraft II** [Diablo Immortal](https://example.org/private)'
    stages = speech_preparation(original, voice.DEFAULT_VOICE)
    assert stages.original_text == original
    assert stages.cleaned_text == 'Warcraft II Diablo Immortal'
    assert stages.pronunciation_text == 'Варкрафт два Диабло Иммортал'
    assert stages.tts_input == prepare_speech(original, voice.DEFAULT_VOICE)


def test_browser_protects_all_reviewed_multiword_entities():
    source = (Path(__file__).resolve().parents[1] / 'static/assets/speech.js').read_text(encoding='utf-8')
    names = re.search(r'const speechNames=\[([\s\S]*?)\];', source)[1]
    literals = set(re.findall(r"'([^']+)'", names))
    assert {name for name in SILERO_NAMES if ' ' in name} <= literals


def test_diagnostics_are_opt_in_correlated_and_exact(monkeypatch, caplog, capsys):
    monkeypatch.setattr(voice, '_tts_ready', lambda _: True)
    worker = Mock(return_value=b'RIFF')
    monkeypatch.setattr(voice._speech_worker, 'synthesize', worker)
    monkeypatch.delenv('LOCALMIND_TTS_DIAGNOSTICS', raising=False)
    with caplog.at_level(logging.WARNING, logger='localmind.pronunciation'):
        voice.synthesize_speech('Private text')
        assert not caplog.records
        monkeypatch.setenv('LOCALMIND_TTS_DIAGNOSTICS', '1')
        for _ in range(2):
            voice.synthesize_speech('**Warcraft II**', generation_id='a' * 32)
    rows = [json.loads(record.message) for record in caplog.records]
    assert len(rows) == 2 and rows[0]['request_id'] != rows[1]['request_id']
    for row in rows:
        assert row['generation_id'] == 'a' * 32
        assert row['original_text'] == '**Warcraft II**'
        assert row['cleaned_text'] == 'Warcraft II'
        assert row['pronunciation_text'] == 'Варкрафт два'
        assert row['tts_input'] == worker.call_args.args[0]
    assert capsys.readouterr().out == ''


def test_cleanup_keeps_latin_and_does_not_read_code_or_urls():
    text = '**Python** [Obsidian](https://example.org/private) ```C++\nsecret()``` https://example.org/secret'
    cleaned = clean_speech(text)
    assert 'Python' in cleaned and 'Obsidian' in cleaned
    assert 'secret' not in cleaned and 'https' not in cleaned
    assert 'Пайтон' not in cleaned
    assert 'Пайтон' in prepare_speech(text, voice.DEFAULT_VOICE)


def test_default_and_readiness_do_not_depend_on_piper(monkeypatch):
    assert voice.DEFAULT_VOICE == 'silero-v5_6-ru'
    assert SpeechRequest(text='Проверка').voice == voice.DEFAULT_VOICE
    monkeypatch.setattr(voice, '_installed', lambda _: False)
    monkeypatch.setattr(voice, '_tts_ready', lambda selected: selected == voice.DEFAULT_VOICE)
    worker = Mock(return_value=b'RIFF')
    monkeypatch.setattr(voice._speech_worker, 'synthesize', worker)
    original = PHRASES[0][0]
    assert voice.synthesize_speech(original, generation_id='a' * 32) == b'RIFF'
    assert original == PHRASES[0][0]
    assert worker.call_args.args == (prepare_speech(original, voice.DEFAULT_VOICE), voice.DEFAULT_VOICE, 'a' * 32)
    voice.warm_tts()
    assert worker.call_args.args == ('Готов.', voice.DEFAULT_VOICE)
    status = voice.voice_status()
    assert status['tts_installed'] and status['default_voice'] == voice.DEFAULT_VOICE
    assert not next(item for item in status['voices'] if item['id'] == voice.PIPER_VOICE)['ready']


def test_explicit_piper_keeps_its_identity_and_own_readiness(monkeypatch):
    monkeypatch.setattr(voice, '_tts_ready', lambda _: True)
    monkeypatch.setattr(voice, '_installed', lambda _: False)
    worker = Mock()
    monkeypatch.setattr(voice._speech_worker, 'synthesize', worker)
    with pytest.raises(voice.VoiceError, match='Piper'):
        voice.synthesize_speech('Python', voice.PIPER_VOICE)
    worker.assert_not_called()
    monkeypatch.setattr(voice, '_installed', lambda _: True)
    voice.synthesize_speech('Python', voice.PIPER_VOICE)
    assert worker.call_args.args[:2] == ('Пайтон', voice.PIPER_VOICE)


def test_expansion_limit_applies_to_initialisms(monkeypatch):
    monkeypatch.setattr(voice, '_tts_ready', lambda _: True)
    worker = Mock()
    monkeypatch.setattr(voice._speech_worker, 'synthesize', worker)
    with pytest.raises(voice.VoiceError) as error:
        voice.synthesize_speech('HTTP ' * 240)
    assert error.value.status_code == 422
    worker.assert_not_called()
