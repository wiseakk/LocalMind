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
    ('Расскажи про Arthas Menethil из World of Warcraft', 'Расскажи про Артас Менетил из Ворлд оф Варкрафт'),
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
    assert expected == prepare_speech(original, voice.DEFAULT_VOICE)
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
    ('IPv4 v2.1', 'ай пи ви четыре ви два точка один'),
])
def test_context_case_whitespace_possessives_and_versions(text, expected):
    assert prepare_speech(text, voice.DEFAULT_VOICE) == expected


@pytest.mark.parametrize('text', ['API II', 'I', 'Warcraft I enjoy', 'Warcraft IV.2',
                                'Warcraft IIIx', 'Warcraft IV2', 'Diablo IV+'])
def test_numerals_require_conservative_title_context(text):
    # Arabic version digits may still be spoken; Roman IV must not become four.
    forbidden = r'\b(три|четыре)\b' if '2' in text else r'\b(два|три|четыре)\b'
    assert not re.search(forbidden, prepare_speech(text, voice.DEFAULT_VOICE))


NORMALIZATION_CASES = [
    ('StarCraft II', 'стар крафт два'),
    ('StarCraft III', 'стар крафт три'),
    ('Diablo IV', 'Диабло четыре'),
    ('Civil IV', 'сивил четыре'),
    ('Zephyr XLII', 'зефир сорок два'),  # Unseen title; no franchise vocabulary.
    ('Zephyr IIV', 'зефир иив'),  # Noncanonical numeral.
    ('Zephyr IIIx', 'зефир ииикс'),
    ('Zephyr IV2', 'зефир ивдва'),
    ('Zephyr IV.2', 'зефир ив.два'),
    ('Zephyr IV+', 'зефир ив+'),
    ('Zephyr IV+2', 'зефир ив плюс два'),
    ('API II', 'эй пи ай ии'),
    ('CLI IV', 'си эл ай ив'),
    ('Zephyr CLI', 'зефир си эл ай'),
    ('Warcraft V', 'Варкрафт пять'),
    ('I', 'ай'),
    ('Command & Conquer', 'комманд энд конквер'),
    ('Command&Conquer', 'комманд энд конквер'),
    ('C&C', 'си энд си'),
    ('R&D', 'ар энд ди'),
    ('C & C', 'си энд си'),
    ('R & D & C', 'ар энд ди энд си'),
    ('труд & отдых', 'труд и отдых'),
    ('труд&отдых', 'труд и отдых'),
    ('Python & Obsidian', 'Пайтон энд Обсидиан'),
    ('В 1977 году', 'В тысяча девятьсот семьдесят седьмом году'),
    ('В 2014 году', 'В две тысячи четырнадцатом году'),
    ('Выпущена в 2002 году', 'Выпущена в две тысячи втором году'),
    ('1999 году', 'тысяча девятьсот девяносто девятом году'),
    ('2026 году', 'две тысячи двадцать шестом году'),
    ('2000 году', 'двухтысячном году'),
    ('1900 году', 'тысяча девятисотом году'),
    ('2003 году', 'две тысячи третьем году'),
    ('2020 году', 'две тысячи двадцатом году'),
    ('2100 году', 'две тысячи сотом году'),
    ('2026 года', 'две тысячи двадцать шестого года'),
    ('за 2026 год', 'за две тысячи двадцать шестой год'),
    ('за 2000 год', 'за двухтысячный год'),
    ('2014', 'две тысячи четырнадцать'),
    ('42', 'сорок два'),
    ('0', 'ноль'),
    ('-42', 'минус сорок два'),
    ('−11', 'минус одиннадцать'),
    ('10 11 19 20', 'десять одиннадцать девятнадцать двадцать'),
    ('100 200 900', 'сто двести девятьсот'),
    ('1000 1001 2000 21000', 'тысяча тысяча один две тысячи двадцать одна тысяча'),
    ('1000000', 'один миллион'),
    ('42-й', 'сорок второй'),
    ('3-ом', 'третьем'),
    ('100-й 200-й 1000-й', 'сотый двухсотый тысячный'),
    ('21-я 3-я', 'двадцать первая третья'),
    ('192.168.1.1', 'один девять два точка один шесть восемь точка один точка один'),
    ('v2.1', 'ви два точка один'),
    ('v2026.1', 'ви две тысячи двадцать шесть точка один'),
    ('IPv4', 'ай пи ви четыре'),
    ('IPv4 v2.1', 'ай пи ви четыре ви два точка один'),
    ('версия 2026.1', 'версия две тысячи двадцать шесть точка один'),
    ('v2026.1 году', 'ви две тысячи двадцать шесть точка один году'),
    ('31.10.2026', 'тридцать один точка десять точка две тысячи двадцать шесть'),
    ('2026-10-31', 'две тысячи двадцать шесть дефис десять дефис тридцать один'),
    ('31.10.2026 году', 'тридцать один точка десять точка две тысячи двадцать шесть году'),
    ('2026-10-31 году', 'две тысячи двадцать шесть дефис десять дефис тридцать один году'),
    ('31/10/2026 году', 'тридцать один дробь десять дробь две тысячи двадцать шесть году'),
    ('3.14', 'три целых четырнадцать сотых'),
    ('3,14', 'три целых четырнадцать сотых'),
    ('-0.02', 'минус ноль целых две сотых'),
    ('1.1', 'одна целая одна десятая'),
    ('2.001', 'две целых одна тысячная'),
    ('3.11', 'три целых одиннадцать сотых'),
    ('2014.5 году', 'две тысячи четырнадцать целых пять десятых году'),
    ('007', 'ноль ноль семь'),
]


CONTEXTUAL_CASES = [
    ('Apple II', 'Эппл два'),
    ('В 1977 году', 'В тысяча девятьсот семьдесят седьмом году'),
    ('Вышли в 1997 и 2002 годах', 'Вышли в тысяча девятьсот девяносто седьмом и две тысячи втором годах'),
    ('В 2026 году', 'В две тысячи двадцать шестом году'),
    ('Python 3.14', 'Пайтон три точка четырнадцать'),
    ('Версия Node.js 24.19.0', 'Версия Нод джей эс двадцать четыре точка девятнадцать точка ноль'),
    ('Число пи примерно равно 3.14', 'Число пи примерно равно три целых четырнадцать сотых'),
    ('IP-адрес 192.168.1.1', 'ай пи-адрес один девять два точка один шесть восемь точка один точка один'),
    ('Warcraft II', 'Варкрафт два'),
    ('StarCraft II', 'стар крафт два'),
    ('Diablo IV', 'Диабло четыре'),
    ('Command & Conquer', 'комманд энд конквер'),
]


@pytest.mark.parametrize('text,expected', CONTEXTUAL_CASES)
def test_contextual_matrix_reaches_worker_exactly(text, expected, monkeypatch, caplog):
    stages = speech_preparation(text, 'silero-v5_6-ru')
    assert stages.original_text == stages.cleaned_text == text
    assert stages.pronunciation_text == stages.tts_input == expected
    assert prepare_speech(text, 'silero-v5_6-ru') == expected
    assert prepare_speech(expected, 'silero-v5_6-ru') == expected
    monkeypatch.setattr(voice, '_tts_ready', lambda _: True)
    worker = Mock(return_value=b'RIFF')
    monkeypatch.setattr(voice._speech_worker, 'synthesize', worker)
    monkeypatch.setenv('LOCALMIND_TTS_DIAGNOSTICS', '1')
    with caplog.at_level(logging.WARNING, logger='localmind.pronunciation'):
        assert voice.synthesize_speech(text, generation_id='b' * 32) == b'RIFF'
    worker.assert_called_once_with(expected, 'silero-v5_6-ru', 'b' * 32)
    row, = [json.loads(record.message) for record in caplog.records]
    assert row['tts_input'] == expected
    assert row['original_text'] == text


@pytest.mark.parametrize('text,expected', [
    ('apple II, APPLE II', 'Эппл два, Эппл два'),
    ('Node.js', 'Нод джей эс'),
    ('В 1997, 2000 и 2003 годах', 'В тысяча девятьсот девяносто седьмом, двухтысячном и две тысячи третьем годах'),
    ('В 1997, 2000, и 2003 году', 'В тысяча девятьсот девяносто седьмом, двухтысячном, и две тысячи третьем году'),
    ('В 2000 или 2003 годах', 'В двухтысячном или две тысячи третьем годах'),
    ('В 1997, 2000, 2003 годах', 'В тысяча девятьсот девяносто седьмом, двухтысячном, две тысячи третьем годах'),
    ('В 1997  и\n 2002   годах', 'В тысяча девятьсот девяносто седьмом и две тысячи втором годах'),
    ('1997 и продажи в 2002 году', 'тысяча девятьсот девяносто семь и продажи в две тысячи втором году'),
    ('1997; 2002 годах', 'тысяча девятьсот девяносто семь; две тысячи втором годах'),
    ('1997,2002 и 2003 годах', 'тысяча девятьсот девяносто семь целых две тысячи две десятитысячных и две тысячи третьем годах'),
    ('v1997 и 2002 годах', 'ви тысяча девятьсот девяносто семь и две тысячи втором годах'),
    ('x1997 и 2002 годах', 'кстысяча девятьсот девяносто семь и две тысячи втором годах'),
    ('3.1997 и 2002 годах', 'три целых тысяча девятьсот девяносто семь десятитысячных и две тысячи втором годах'),
    ('Python 31.10.2026', 'Пайтон тридцать один точка десять точка две тысячи двадцать шесть'),
    ('Версия Node.js 192.168.1.1', 'Версия Нод джей эс сто девяносто два точка сто шестьдесят восемь точка один точка один'),
    ('Версия ПО 31.10.2026', 'Версия ПО тридцать один точка десять точка две тысячи двадцать шесть'),
    ('Python\n  3.14', 'Пайтон три точка четырнадцать'),
    ('Node.js 24.19.0. Python 3.14.', 'Нод джей эс двадцать четыре точка девятнадцать точка ноль. Пайтон три точка четырнадцать.'),
    ('Версия Python v3.14', 'Версия Пайтон ви три точка четырнадцать'),
    ('Версия 1.2.3', 'Версия один точка два точка три'),
    ('31/10/2026', 'тридцать один дробь десять дробь две тысячи двадцать шесть'),
    ('Python: 3.14, 3,14 и −0.02; 1/2', 'Пайтон: три целых четырнадцать сотых, три целых четырнадцать сотых и минус ноль целых две сотых; один разделить на два'),
    ('Адрес 127.0.0.1', 'Адрес один два семь точка ноль точка ноль точка один'),
    ('Адрес 255.0.10.1', 'Адрес два пять пять точка ноль точка один ноль точка один'),
    ('256.1.1.1', 'двести пятьдесят шесть точка один точка один точка один'),
])
def test_context_boundaries_and_precedence(text, expected):
    stages = speech_preparation(text, 'silero-v5_6-ru')
    assert stages.original_text == text
    assert stages.tts_input == stages.pronunciation_text == expected
    assert prepare_speech(text, 'silero-v5_6-ru') == expected


def test_reviewed_apple_does_not_match_inside_words():
    for text in ('Pineapple', 'AppleX', 'xApple', 'Apple2'):
        assert 'Эппл' not in prepare_speech(text, 'silero-v5_6-ru')


@pytest.mark.parametrize('text,expected', NORMALIZATION_CASES)
def test_exact_normalization_contract(text, expected):
    stages = speech_preparation(text, 'silero-v5_6-ru')
    assert stages.original_text == text
    assert stages.cleaned_text == text
    assert stages.pronunciation_text == stages.tts_input == expected
    assert prepare_speech(text, 'silero-v5_6-ru') == expected


def test_numbers_are_bounded_before_integer_conversion_and_expansion(monkeypatch):
    text = '9' * 5000
    assert prepare_speech(text, voice.DEFAULT_VOICE) == ' '.join(['девять'] * 5000)
    monkeypatch.setattr(voice, '_tts_ready', lambda _: True)
    worker = Mock()
    monkeypatch.setattr(voice._speech_worker, 'synthesize', worker)
    with pytest.raises(voice.VoiceError) as error:
        voice.synthesize_speech('999999999999 ' * 40)
    assert error.value.status_code == 422
    worker.assert_not_called()


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
