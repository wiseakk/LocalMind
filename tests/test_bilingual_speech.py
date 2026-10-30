"""Pronunciation preparation and routing tests; these do not assess listening quality."""
import re
from unittest.mock import Mock

import pytest

from localmind import voice
from localmind.server import SpeechRequest
from localmind.speech_text import clean_speech, language_spans, normalize_speech, prepare_speech


PHRASES = [
    ('Расскажи про Arthas Menethil из World of Warcraft', 'Артас Менетил из Ворлд оф Варкрафт'),
    ('Warcraft III: Reign of Chaos', 'Варкрафт три: Рэйн оф Кэйос'),
    ('The Frozen Throne', 'Зэ Фроузен Троун'),
    ('Heroes of the Storm', 'Хироуз оф зэ Сторм'),
    ('Hearthstone', 'Хартстоун'),
    ('Открой Obsidian', 'Открой Обсидиан'),
    ('Найди PDF в Downloads', 'Найди пи ди эф в Даунлоудс'),
    ('Я программирую на Python и C++', 'Я программирую на Пайтон и си плюс плюс'),
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


def test_unknown_names_are_spelled_instead_of_dropped_or_translated():
    assert prepare_speech('Qzora NASA', voice.DEFAULT_VOICE) == 'кью зет оу ар эй эн эй эс эй'
    assert normalize_speech('Qzora NASA') == 'Qzora NASA'
    # A substring of an unknown word must never become a dictionary name.
    assert 'Обсидиан' not in prepare_speech('ObsidianX', voice.DEFAULT_VOICE)


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


def test_expansion_limit_applies_to_unknown_spelling(monkeypatch):
    monkeypatch.setattr(voice, '_tts_ready', lambda _: True)
    worker = Mock()
    monkeypatch.setattr(voice._speech_worker, 'synthesize', worker)
    with pytest.raises(voice.VoiceError) as error:
        voice.synthesize_speech('W' * 1200)
    assert error.value.status_code == 422
    worker.assert_not_called()
