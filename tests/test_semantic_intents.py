"""End-to-end routing with fixture app adapters and real scoped file adapters."""
from dataclasses import replace
import json
from unittest.mock import Mock

import pytest

from localmind import agent, file_access, file_mutations, llm_planner
from localmind.action_journal import ActionJournal
from localmind.capabilities import registry
from localmind.conversations import Conversation
from localmind.results import ActionResult, refused


ALIASES = {
    'app-steam': ('Steam', 'Стим'), 'app-yandex': ('Яндекс Музыка',),
    'app-obsidian': ('Obsidian', 'Обсидиан'), 'app-modrinth': ('Modrinth App', 'Modrinth', 'Модринт'),
    'app-aurora': ('Аврора',), 'app-lunaris': ('Lunaris',), 'app-atlas': ('Атлас',),
    'app-editor': ('Редактор Спектр',), 'app-visual': ('Visual Studio Code',),
    'app-code1': ('Code', 'Код'), 'app-code2': ('Code', 'Код'),
}

COMMANDS = (
    'Открой {}.', 'открывайте {}!', 'Запусти мне {}', 'Пожалуйста, запустите {}?',
    'Можешь включить {}?', 'Открыть {}', 'Можешь мне {} запустить?', 'А можешь открыть {}?',
    'Открой, пожалуйста, {}', 'Вруби {}', 'Покажи приложение {}', 'Запускать {}',
    'Открой {} пожалуйста', 'Будьте добры, запустите {}', 'Прошу открыть {}.',
)
NO_ACTION = (
    'Не открывай {}.', 'Как открыть {}?', 'Что такое {}?', 'Можно ли открыть {}?',
    'Если бы я попросил открыть {}, что произошло бы?', 'Не врубай {}', 'Никогда не запускай {}',
    'Объясни как запустить {}', 'Он сказал «открой {}»', 'Повтори за мной: открой {}',
    'Открыть {}?', 'Открой {} --silent', 'Покажи как открыть {}',
)
NAMES = (
    ('english', 'Steam', 'app-steam'), ('transliteration', 'Стим', 'app-steam'),
    ('exact', 'Яндекс Музыка', 'app-yandex'), ('morphology', 'Яндекс музыку', 'app-yandex'),
    ('morphology', 'Яндекс музыке', 'app-yandex'), ('transliteration', 'Yandex Music', 'app-yandex'),
    ('english', 'Obsidian', 'app-obsidian'), ('transliteration', 'обсидиан', 'app-obsidian'),
    ('transliteration', 'модринт', 'app-modrinth'), ('morphology', 'Аврору', 'app-aurora'),
    ('transliteration', 'Лунарис', 'app-lunaris'), ('exact', 'Атлас', 'app-atlas'),
)
CORPUS = [(category, command.format(name), app_id) for category, name, app_id in NAMES for command in COMMANDS]
CORPUS += [('no_action', command.format(name), None) for command in NO_ACTION
           for name in ('Steam', 'Яндекс Музыку', 'Obsidian', 'Аврору')]
CORPUS += [('ambiguous', command.format(name), None) for command in COMMANDS[:5] for name in ('Code', 'Код')]
CORPUS += [('semantic', command.format(name), app_id) for command in COMMANDS[:3] for name, app_id in
           (('Obisidian', 'app-obsidian'), ('Лунарисс', 'app-lunaris'))]
CORPUS += [('morphology', 'Вруби музыку в Яндексе.', 'app-yandex'),
           ('no_action', 'Можно ли удалить файл?', None),
           ('no_action', 'Если бы я попросил удалить файл test.txt, что произошло бы?', None),
           ('no_action', 'Открой https://steam.com', None),
           ('no_action', r'Открой C:\Apps\Steam\steam.exe', None),
           ('no_action', 'Открой Steam | powershell', None)]


@pytest.fixture
def route(monkeypatch):
    monkeypatch.setattr(agent, '_all_app_aliases', lambda: ALIASES)
    monkeypatch.setattr('localmind.apps.catalog.is_allowed', lambda *a: True)
    monkeypatch.setattr('localmind.model_manager.manager.native_tools_supported', lambda *a: False)
    monkeypatch.setattr(llm_planner, 'journal', ActionJournal())
    adapter = Mock(side_effect=lambda args, owner: ActionResult(
        True, 'apps.open', args['app_id'], 'observed', 'foreground_window', status_text='Проверенное окно на переднем плане.'))
    monkeypatch.setitem(registry.tools, 'apps.open', replace(registry.tools['apps.open'], adapter=adapter))
    def chat(messages, tools, **kwargs):
        schema = kwargs.get('response_format', {})
        if 'calls' in schema.get('properties', {}):
            allowed = json.loads(messages[-1]['content'])['available']
            if allowed.keys() == {'apps.open'}:
                candidates = allowed['apps.open']['properties']['app_id']['enum']
                assert len(candidates) == 1
                return {'content': json.dumps({'calls': [{'tool': 'apps.open', 'arguments': {'app_id': candidates[0]}}]})}
            return {'content': '{"calls":[]}'}
        return {'content': 'Ответ на обычный вопрос.'}
    model = Mock(side_effect=chat)
    monkeypatch.setattr(agent, 'ollama_chat', model)
    return adapter, model


def reply(text, authorized=True):
    return agent.complete_reply(agent.prepare_reply(text, conversation=Conversation('semantic-qa', 0),
        actions_authorized=authorized, llm_first=True, compose_actions=False))


@pytest.mark.parametrize('category,text,expected', CORPUS)
def test_russian_and_mixed_corpus(route, category, text, expected):
    adapter, model = route
    result = reply(text)
    if expected:
        adapter.assert_called_once_with({'app_id': expected}, 'semantic-qa')
        action, = result['action_results']
        assert action['action'] == 'apps.open' and action['observed_state'] == 'foreground_window'
        assert action['resolved_target'] == expected and 'Проверенное окно' in result['answer']
        if category == 'semantic':
            model.assert_called_once()
        else:
            model.assert_not_called()
    else:
        adapter.assert_not_called()
        assert not any(row['success'] or row['execution_status'] == 'confirmation_required' for row in result['action_results'])
        if category == 'ambiguous':
            model.assert_not_called()
            assert result['intent_resolution']['stage'] == 'ambiguous' and 'Варианты' in result['answer']


@pytest.mark.parametrize('answer', ['{"calls":[]}', '{broken',
    '{"calls":[{"tool":"apps.open","arguments":{"app_id":"app-steam"}}]}',
    '{"calls":[{"tool":"apps.open","arguments":{"app_id":"app-obsidian","command":"cmd"}}]}'])
def test_invalid_semantic_plan_clarifies_without_launch(route, answer):
    adapter, model = route
    model.side_effect = None; model.return_value = {'content': answer}
    result = reply('Открой Obsidiann')
    adapter.assert_not_called()
    assert result['action_results'][0]['execution_status'] == 'clarification_required'
    assert 'obsidian' in result['answer'].casefold()


def test_disallowed_app_keeps_adapter_denial_and_voice_review(route):
    adapter, model = route
    adapter.side_effect = None
    adapter.return_value = refused('apps.open', 'app-steam', 'Доступ запрещён.', status='permission_required')
    assert reply('Запусти Стим', authorized=False)['engine'] == 'action-review'
    adapter.assert_not_called()
    result = reply('Запусти Стим')
    assert result['action_results'][0]['execution_status'] == 'permission_required'
    model.assert_not_called()


def test_native_wrong_id_recovers_once_using_the_original_enum(route, monkeypatch):
    adapter, model = route
    monkeypatch.setattr('localmind.model_manager.manager.native_tools_supported', lambda *a: True)
    strict_reply = model.side_effect
    def chat(messages, tools, **kwargs):
        if tools:
            return {'tool_calls': [{'function': {'name': 'apps.open', 'arguments': {'app_id': 'app-steam'}}}]}
        return strict_reply(messages, tools, **kwargs)
    model.side_effect = chat
    result = reply('Открой Obsidiann')
    assert result['planner_mode'] == 'schema_fallback' and model.call_count == 2
    adapter.assert_called_once_with({'app_id': 'app-obsidian'}, 'semantic-qa')


def test_exact_app_does_not_launch_when_audit_cannot_be_saved(route, monkeypatch):
    adapter, model = route
    monkeypatch.setattr(llm_planner.journal, 'record', Mock(side_effect=OSError))
    result = reply('Открой Steam')
    assert result['action_results'][0]['execution_status'] == 'audit_unavailable'
    adapter.assert_not_called()
    model.assert_not_called()


@pytest.mark.parametrize('named', [True, False])
def test_scoped_delete_and_test_folder_never_expand_grants(tmp_path, monkeypatch, named):
    root = tmp_path/'LocalMind_QA'; root.mkdir()
    demo = root/'DEMO'; demo.mkdir()
    target = demo/'test.txt'; target.write_text('disposable')
    access = file_access.FileAccess(lambda: root, persistence=tmp_path/'policy.json')
    access.personal_mode.configure('restricted', [str(root)], ['search', 'read', 'delete'])
    monkeypatch.setattr(file_access, 'file_access', access)
    monkeypatch.setattr(file_mutations, 'file_mutations', file_mutations.FileMutations(access))
    monkeypatch.setattr(llm_planner, 'journal', ActionJournal())
    monkeypatch.setattr(llm_planner, 'choose', lambda *a, **kw: ([], 'schema'))
    listed = reply('Покажи файлы в моей тестовой папке.')
    assert listed['engine'] == 'file-listing' and 'DEMO' in listed['answer']
    denied = reply(f'Удали файл test.txt из папки {tmp_path}')
    assert not denied.get('confirmation_required')
    phrase = 'Удали файл test.txt из папки DEMO' if named else f'Удали файл test.txt в папке «{demo}»'
    result = reply(phrase)
    assert result['action_results'][0]['execution_status'] == 'confirmation_required'
    assert result['pending_operation']['path'] == str(target) and target.exists()
