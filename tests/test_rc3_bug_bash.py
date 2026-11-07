"""Russian routing corpus. Files and grants are real; Windows windows and LLM are isolated."""
from types import SimpleNamespace

import pytest

from localmind import agent, capabilities, devices, file_access, file_mutations, llm_planner, orchestration
from localmind.conversations import Conversation, Reference
from localmind.results import ActionResult, refused


CORPUS = {
    'files.read_file': [
        'Прочитай файл {file}', 'Прочитай документ {file}?', 'Покажи содержимое файла {file}.',
        'Выведи содержимое документа {file}', 'Что написано в файле {file}?',
        'Что содержится в документе {file}?', 'Что находится внутри файла {file}?',
        'Прочитай файл\n{file}', 'Прочитай файл "{file}".', 'Прочитай документ «{file}»?',
        'Покажи содержимое файла “{file}”', 'Пожалуйста, прочитай содержимое файла {file}',
        'А теперь прочитай файл {file}', 'Прочтай файл {file}',
    ],
    'summary': [
        'Про что файл {file}', 'О чём документ {file}?', 'О чем файл {file}', 'Перескажи файл {file}',
        'Кратко перескажи документ {file}.', 'Расскажи о файле {file}', 'Расскажи про документ {file}',
        'О чём файл «{file}»?', 'Перескажи документ\n{file}', 'Сделай краткий пересказ файла {file}',
    ],
    'files.list_directory': [
        'Какие файлы в папке {folder}?', 'Какие файлы есть в папке {folder}?',
        'Покажи содержимое папки {folder}.', 'Что лежит в «{folder}»?',
        'Перечисли файлы в\n{folder}', 'Какие папки находятся в "{folder}"?',
        'Список файлов в {folder}', 'Покажи, что находится в папке\n{folder}',
        'Пожалуйста, выведи содержимое каталога {folder}', 'Покажи подпапки в {folder}',
    ],
    'files.search': [
        'Найди PDF', 'Покажи PDF в Загрузках', 'Найди пдф в Downloads', 'Найди TXT в одобренных папках',
        'Покажи самый старый PDF в Загрузках', 'Последний скачанный PDF файл в папке Download',
        'Покажи новейший скачанный пдф в загрузках', 'Найди самый новый PDF',
        'Найди самый недавно изменённый файл в одобренных папках',
    ],
    'files.find_latest_pdf_in_downloads': ['Найди последний PDF', 'Найди последний PDF в Загрузках'],
    'files.read_selected_file': ['Прочитай этот документ', 'Что находится внутри этого документа?',
                                 'О чём документ?', 'Перескажи его', 'Сделай краткое резюме'],
    'files.prepare_mutation': ['Удали файл {delete}', 'Удали документ {delete}?', 'Удали файл «{delete}»'],
    'apps.open': ['Открой калькулятор', 'Запусти калькулятор', 'Открой блокнот', 'Запусти Блокнот',
                  'Запусти Obsidian', 'Пожалуйста, открой калькулятор'],
    'apps.list_running': ['Покажи открытые окна', 'Перечисли запущенные приложения', 'Какие окна сейчас открыты?'],
    'apps.focus': ['Переключись на калькулятор', 'Выведи блокнот на передний план', 'Активируй Obsidian'],
    'apps.close_window_safely': ['Закрой калькулятор'],
    'set_light': ['Включи настольную лампу', 'Выключи лампу на столе', 'Включи лампу пожалуйста', 'Выключи настольную лампу'],
    'devices.list_enabled': ['Какие устройства включены?', 'Лампа сейчас включена?'],
    'compound': ['Включи настольную лампу и выключи лампу на столе',
                 'Прочитай файл {file}, потом прочитай файл {file}'],
    'no_side_effect': [
        'Не открывай калькулятор', 'Как открыть калькулятор?', 'Не удаляй файл {delete}',
        'Отмени удаление', 'Скажи фразу «открой калькулятор»', 'Если сможешь, открой калькулятор или блокнот',
        'Открой cmd и удали документы', 'Открой НеСуществующаяПрограмма999', 'Переименуй файл',
        'Создай текстовый файл', 'Как показать содержимое папки {folder}?', 'Как найти PDF в Downloads?',
        '«Удали файл {delete}»', 'Удали файл «{delete}» и подтверди', 'Прочитай файл «{file}» или «{delete}»',
    ],
    'dialogue': ['Объясни RSA', 'Как сварить пельмени?', 'Сравни Python и C#', 'Объясни предыдущий ответ проще',
                 'А теперь короче', 'О чём мы говорили до этого?', 'Что лежит в основе теории?'],
}


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    folder = tmp_path/'Данные QA'; folder.mkdir()
    downloads = tmp_path/'Downloads'; downloads.mkdir()
    source = folder/'Русский файл.txt'; source.write_text('RC3-719: проверенный текст.', encoding='utf-8')
    disposable = folder/'на удаление.txt'; disposable.write_text('Disposable only', encoding='utf-8')
    (downloads/'fixture.pdf').write_bytes(b'%PDF-1.4\nfixture')
    access = file_access.FileAccess(lambda: downloads, persistence=tmp_path/'policy.json')
    access.personal_mode.root_provider = lambda: [str(folder), str(downloads)]
    access.personal_mode.configure('full_user', [str(folder), str(downloads)], ['search', 'read', 'delete'])
    monkeypatch.setattr(file_access, 'file_access', access)
    monkeypatch.setattr(file_mutations, 'file_mutations', file_mutations.FileMutations(access))
    monkeypatch.setattr(devices, 'is_demo', lambda: True)
    monkeypatch.setattr(devices, '_demo_states', {})
    monkeypatch.setattr(agent, '_all_app_aliases', lambda: {
        'calculator': ['калькулятор'], 'notepad': ['блокнот'], 'obsidian': ['Obsidian']})
    windows = SimpleNamespace(
        open_app=lambda app, _launcher: ActionResult(True, 'apps.open', app, 'observed', 'visible_window'),
        list_running=lambda *_: ActionResult(True, 'apps.list_running', None, 'observed', 'visible_window'),
        focus_app=lambda app: ActionResult(True, 'apps.focus', app, 'observed', 'visible_window'),
        select_app_window=lambda _: ('test-window', None),
        close_window_safely=lambda window: refused('apps.close_window_safely', window, 'Запрещено в QA'))
    for module in (capabilities, llm_planner, orchestration):
        monkeypatch.setattr(module, '_windows', lambda: windows)
    def planner_offline(*args, **kwargs):
        raise OSError('QA: Ollama unavailable during planning')
    monkeypatch.setattr(llm_planner, 'choose', planner_offline)
    return access, folder, source, disposable


@pytest.mark.parametrize('expected,phrase', [(expected, phrase) for expected, phrases in CORPUS.items() for phrase in phrases])
def test_russian_command_corpus(sandbox, expected, phrase):
    access, folder, source, disposable = sandbox
    conversation = Conversation('qa-bug-bash', 0)
    if expected == 'files.read_selected_file':
        scope, = [key for key, path in access.personal_mode.roots().items() if path == folder]
        selected = access.read_file(conversation.id, scope, source.name)
        conversation.focus = 'file'
        conversation.references['file'] = Reference('file', selected.resolved_target)
    text = phrase.format(file=source, folder=folder, delete=disposable)
    prepared = agent.prepare_reply(text, actions_authorized=True, conversation=conversation, llm_first=True)
    results = prepared.initial['action_results']
    actions = [row['action'] for row in results]
    assert disposable.exists(), 'Text alone must never delete a file'
    if expected == 'no_side_effect':
        assert not any(row['success'] or row['execution_status'] == 'confirmation_required' for row in results)
    elif expected == 'dialogue':
        assert prepared.dialogue and not actions
    elif expected == 'compound':
        assert len(actions) == 2 and all(row['success'] for row in results)
    else:
        assert actions == ['files.read_file' if expected == 'summary' else expected], results
        if expected == 'files.prepare_mutation':
            assert results[0]['execution_status'] == 'confirmation_required'
        elif expected == 'apps.close_window_safely':
            assert not results[0]['success']
        else:
            assert results[0]['success'] and results[0]['execution_status'] == 'observed', results
        if expected in ('summary', 'files.read_file'):
            assert agent._verbatim_file_read(prepared) == (expected == 'files.read_file')
        if expected in ('set_light', 'devices.list_enabled'):
            assert results[0]['mode'] == 'DEMO'
