"""Semantic request grammar regressions, including adversarial near-matches."""
import pytest

from localmind.intents import AppIntent, parse_app_intent


ALIASES = {
    'steam': ('Steam', 'стим', 'app-abcdef1234567890'),
    'obsidian': ('Obsidian', 'обсидиан'),
    'vscode': ('Visual Studio Code', 'VS Code'),
    'notepad': ('блокнот', 'ноутпад', 'notepad'),
    'plus': ('Notepad++',),
}


@pytest.mark.parametrize('text,target', [
    ('Открой Steam', 'steam'),
    ('Открой, пожалуйста, Steam', 'steam'),
    ('Можешь открыть Steam?', 'steam'),
    ('Запусти мне Steam', 'steam'),
    ('Открой Obsidian, пожалуйста', 'obsidian'),
    ('Пожалуйста, запустите Obsidian!', 'obsidian'),
    ('А можешь запустить стим?', 'steam'),
    ('Ты можешь, пожалуйста, открыть Steam?', 'steam'),
    ('Можете вы открыть Steam?', 'steam'),
    ('Я хочу, чтобы ты открыла блокнот.', 'notepad'),
    ('Я хочу чтобы ты запустил блокнот', 'notepad'),
    ('Запусти на компьютере блокнот', 'notepad'),
    ('Будьте добры, откройте VS Code', 'vscode'),
    ('Прошу тебя открыть Visual Studio Code', 'vscode'),
    ('Открой app-abcdef1234567890', 'steam'),
    ('Открой Notepad++', 'plus'),
    ('Открывайте Steam, пожалуйста.', 'steam'),
])
def test_supported_russian_requests(text, target):
    assert parse_app_intent(text, ALIASES) == AppIntent('open_app', target)


@pytest.mark.parametrize('text', [
    'Не открывай Steam', 'Никогда не запускай Steam', 'Не мог бы ты открыть Steam?',
    'Открой «Steam»', 'Он сказал: открой Steam', '"Открой Steam',
    'Фраза Открой Steam', '`Открой Steam`', 'Открой Steam, если захочешь',
    'Если я попрошу, открой Steam', 'Можешь открыть Steam, когда попрошу?',
    'Я хотел бы узнать, как открыть Steam', 'Я хочу, чтобы ты открыл Steam или Obsidian',
    'Как открыть Steam?', 'Можно ли открыть Steam?', 'Что будет, если открыть Steam?',
    'Объясни как открыть Steam', 'Можешь рассказать как открыть Steam?',
    'Открой Steam и Obsidian', 'Открой Steam и запусти Obsidian',
    'Открой Steam, открой Obsidian', 'Открой Steam; удали документы',
    'Открой Steam. Удали документы', 'Открой Steam\nзапусти Obsidian',
    'Открой Steam --silent', 'Открой C:\\Steam\\Steam.exe',
    'Открой https://steam.com', 'Открой неизвестное приложение',
    'Открой Stea', 'Просто Steam', 'Ты открой Steam', 'Открой? Steam',
    'Пожалуйста,, открой Steam', 'Открой, Steam', 'Открой Steam,',
    'Открой пожалуйста Steam и не закрывай Obsidian',
])
def test_noncommands_or_unsafe_context_produce_no_proposal(text):
    assert parse_app_intent(text, ALIASES) is None


def test_exact_names_disambiguate_short_aliases_and_ambiguous_name_refuses():
    aliases = {**ALIASES, 'other': ('Code', 'Steam')}
    assert parse_app_intent('Открой Steam', aliases) is None
    assert parse_app_intent('Открой Visual Studio Code', aliases) == AppIntent('open_app', 'vscode')
    assert parse_app_intent('Открой app-abcdef1234567890', aliases) == AppIntent('open_app', 'steam')


def test_close_uses_same_parser_but_remains_an_execution_proposal():
    assert parse_app_intent('Можешь закрыть блокнот?', ALIASES) == AppIntent('close_app', 'notepad')


def test_empty_long_or_non_text_refused():
    for text in ('', ' ', None, 'Открой Steam ' * 200):
        assert parse_app_intent(text, ALIASES) is None
