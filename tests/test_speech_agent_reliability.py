"""Policy/dependency regressions; desktop adapters and generation are doubles."""
import json

import pytest

from localmind import agent
from localmind.capabilities import Capability, CapabilityRegistry
from localmind.conversations import Conversation, Reference
from localmind.results import ActionResult, refused


def adapters(monkeypatch, fail=False):
    calls = []
    registry = CapabilityRegistry()
    def execute(args, owner):
        calls.append(dict(args))
        if fail:
            return refused('apps.open', args['app_id'], 'Permission missing', status='permission_required')
        return ActionResult(True, 'apps.open', args['app_id'], 'process_created', status_text='Запуск начат.')
    registry.tools['apps.open'] = Capability('apps.open', ('app_id',), 'test', '', execute)
    def focus(args, owner):
        calls.append(dict(args))
        return ActionResult(True, 'apps.focus', args['app_id'], 'observed', 'foreground_window', status_text='Окно проверено.')
    registry.tools['apps.focus'] = Capability('apps.focus', ('app_id',), 'test', '', focus)
    monkeypatch.setattr(agent, 'registry', registry)
    monkeypatch.setattr(agent.catalog, 'aliases', lambda: {'obsidian': ('Obsidian',)})
    return calls


def test_launch_then_focus_resolves_same_app_not_old_reference(monkeypatch):
    calls = adapters(monkeypatch)
    conversation = Conversation('owner', 0, references={'application': Reference('application', 'notepad')}, focus='application')
    reply = agent.prepare_reply('Открой Obsidian, после запуска выведи его на передний план',
                                actions_authorized=True, conversation=conversation)
    assert calls == [{'app_id': 'obsidian'}, {'app_id': 'obsidian'}]
    assert len(reply.initial['action_results']) == 2


@pytest.mark.parametrize('tail', ['удали документы', 'открой неизвестное приложение', 'не открывай блокнот',
                                    'выведи неизвестное на передний план'])
def test_all_clauses_validated_before_any_launch(monkeypatch, tail):
    calls = adapters(monkeypatch)
    reply = agent.prepare_reply('Открой Obsidian, затем ' + tail, actions_authorized=True,
                                conversation=Conversation('owner', 0))
    assert not calls
    assert not any(r['success'] for r in reply.initial['action_results'])


def test_failed_launch_stops_focus(monkeypatch):
    calls = adapters(monkeypatch, fail=True)
    reply = agent.prepare_reply('Открой Obsidian, после запуска выведи его на передний план',
                                actions_authorized=True, conversation=Conversation('owner', 0))
    assert calls == [{'app_id': 'obsidian'}]
    assert len(reply.initial['action_results']) == 1


def test_unreviewed_sequence_has_no_effects(monkeypatch):
    calls = adapters(monkeypatch)
    reply = agent.prepare_reply('Открой Obsidian, затем выведи его на передний план',
                                actions_authorized=False, conversation=Conversation('owner', 0))
    assert not calls and reply.initial['confirmation_required']


@pytest.mark.parametrize('text', ['Расскажи о содержимом этого PDF', 'О чём этот документ?',
    'Кратко опиши этот PDF', 'Сделай краткое резюме этого документа', 'Расскажи про этот документ', 'Сделай краткое резюме'])
def test_summary_executes_read_and_sends_extracted_content(monkeypatch, text):
    registry = CapabilityRegistry()
    registry.tools['files.read_selected_file'] = Capability('files.read_selected_file', ('file_id',), 'test', '',
        lambda a, o: ActionResult(True, 'files.read_selected_file', a['file_id'], 'observed', 'text_extracted',
            status_text='Прочитан', data={'filename': 'ordinary.pdf', 'text': 'The budget is 739 rubles.'}))
    monkeypatch.setattr(agent, 'registry', registry)
    seen = []
    def chat(messages, *args, **kwargs):
        seen.extend(messages)
        return {'content': json.dumps({'answer': 'Бюджет 739 рублей.'})}
    monkeypatch.setattr(agent, 'ollama_chat', chat)
    c = Conversation('owner', 0, references={'file': Reference('file', 'file-safe')}, focus='file')
    prepared = agent.prepare_reply(text, actions_authorized=True, conversation=c)
    result = agent.complete_reply(prepared)
    assert result['action_results'][0]['action'] == 'files.read_selected_file'
    assert 'The budget is 739' in json.dumps(seen)
    assert 'text' not in result['action_results'][0]['data']


@pytest.mark.parametrize('data', [None, {}, {'text': 23}, {'filename': 'claimed-facts.pdf', 'text': '  '}])
@pytest.mark.parametrize('llm_first', [False, True])
def test_empty_extraction_never_generates_summary(monkeypatch, data, llm_first):
    registry = CapabilityRegistry()
    registry.tools['files.read_selected_file'] = Capability('files.read_selected_file', ('file_id',), 'test', '',
        lambda a, o: ActionResult(True, 'files.read_selected_file', a['file_id'], 'observed', 'text_extracted',
            data=data))
    monkeypatch.setattr(agent, 'registry', registry)
    monkeypatch.setattr('localmind.llm_planner.registry', registry)
    from localmind.action_journal import ActionJournal
    from localmind.capabilities import ToolIntent
    monkeypatch.setattr('localmind.llm_planner.journal', ActionJournal())
    monkeypatch.setattr('localmind.llm_planner.choose', lambda *a, **k:
                        ([ToolIntent('files.read_selected_file', {'file_id': 'file-safe'})], 'schema'))
    monkeypatch.setattr('localmind.model_manager.manager.native_tools_supported', lambda *a: False)
    monkeypatch.setattr(agent, 'ollama_chat', lambda *a, **k: pytest.fail('Must not infer content without extraction'))
    c = Conversation('owner', 0, references={'file': Reference('file', 'file-safe')}, focus='file')
    result = agent.complete_reply(agent.prepare_reply('О чём этот документ?', actions_authorized=True, conversation=c,
                                                     llm_first=llm_first, compose_actions=False))
    assert result['action_results'][0]['execution_status'] == 'extraction_failed'


@pytest.mark.parametrize('execution_status,observed_state', [('process_created', 'text_extracted'), ('observed', None)])
def test_unconfirmed_extraction_cannot_claim_read_success(monkeypatch, execution_status, observed_state):
    registry = CapabilityRegistry()
    registry.tools['files.read_selected_file'] = Capability('files.read_selected_file', ('file_id',), 'test', '',
        lambda a, o: ActionResult(True, 'files.read_selected_file', a['file_id'], execution_status, observed_state,
                                 data={'text': 'UNCONFIRMED-CONTENT'}))
    monkeypatch.setattr(agent, 'registry', registry)
    monkeypatch.setattr(agent, 'ollama_chat', lambda *a, **k: pytest.fail('No confirmed text'))
    c = Conversation('owner', 0, references={'file': Reference('file', 'file-safe')}, focus='file')
    result = agent.complete_reply(agent.prepare_reply('Прочитай этот файл', actions_authorized=True, conversation=c))
    assert not result['action_results'][0]['success']
    assert 'UNCONFIRMED-CONTENT' not in json.dumps(result)


def test_verbatim_read_preserves_text_and_discloses_extraction_truncation(monkeypatch):
    contents = 'Строка с проверенным содержимым.\n' * 100
    registry = CapabilityRegistry()
    registry.tools['files.read_selected_file'] = Capability('files.read_selected_file', ('file_id',), 'test', '',
        lambda a, o: ActionResult(True, 'files.read_selected_file', a['file_id'], 'observed', 'text_extracted',
                                 data={'text': contents, 'truncated': True}))
    monkeypatch.setattr(agent, 'registry', registry)
    monkeypatch.setattr(agent, 'ollama_chat', lambda *a, **k: pytest.fail('Plain reading requires no model'))
    c = Conversation('owner', 0, references={'file': Reference('file', 'file-safe')}, focus='file')
    result = agent.complete_reply(agent.prepare_reply('Прочитай этот документ', actions_authorized=True,
                                                     conversation=c, response_length='short'))
    assert contents in result['answer'] and 'неполный' in result['answer']
    assert result['answer'] == result['speech_text'] == result['display_text']
    assert result['context_sources'][0]['truncated']


def test_ordinary_chat_still_streams_without_file_buffering(monkeypatch):
    deltas = []
    def chat(*args, **kwargs):
        callback = agent.text_delta.get()
        assert callback == deltas.append
        callback('Обычный ')
        callback('ответ.')
        return {'content': json.dumps({'answer': 'Обычный ответ.'})}
    monkeypatch.setattr(agent, 'ollama_chat', chat)
    prepared = agent.prepare_reply('Расскажи про RSA')
    prepared.on_delta = deltas.append
    final = agent.complete_reply(prepared)
    assert deltas == ['Обычный ', 'ответ.']
    assert final['answer'] == 'Обычный ответ.'


@pytest.mark.parametrize('text', ['Кратко опиши файл', 'Сделай выводы из этого PDF', 'Расскажи мне о документе'])
def test_unsupported_content_request_cannot_infer_from_filename(monkeypatch, text):
    monkeypatch.setattr(agent, 'ollama_chat', lambda *a, **k: pytest.fail('Unsupported content grammar must clarify'))
    c = Conversation('owner', 0, references={'file': Reference('file', 'file-safe')}, focus='file')
    result = agent.complete_reply(agent.prepare_reply(text, actions_authorized=True, conversation=c))
    assert result['action_results'][0]['execution_status'] == 'clarification_required'


@pytest.mark.parametrize('text', ['Опиши Arthas Menethil', 'О чём World of Warcraft?'])
def test_file_selection_does_not_hijack_unrelated_knowledge(monkeypatch, text):
    monkeypatch.setattr(agent, 'ollama_chat', lambda *a, **k: {'content': '{"answer":"Ответ по теме игры."}'})
    c = Conversation('owner', 0, references={'file': Reference('file', 'file-safe')}, focus='file')
    result = agent.complete_reply(agent.prepare_reply(text, actions_authorized=True, conversation=c))
    assert result['engine'] == 'ollama' and result['action_results'] == []


@pytest.mark.parametrize('tail', ['прочитай его', 'выведи Obsidian на передний план'])
def test_compound_retains_filename_speech_separate_from_display(monkeypatch, tail):
    """Real routing/renderer; search, focus and Ollama are explicit doubles."""
    calls = adapters(monkeypatch)
    filename = 'Spisok_rabot_2026.pdf'
    registry = agent.registry
    registry.tools['files.find_latest_pdf_in_downloads'] = Capability(
        'files.find_latest_pdf_in_downloads', (), 'test', '',
        lambda a, o: ActionResult(True, 'files.find_latest_pdf_in_downloads', 'file-safe',
            'observed', 'file_selected', status_text='Выбран файл.',
            data={'filename': filename, 'file_id': 'file-safe'}))
    registry.tools['files.read_selected_file'] = Capability(
        'files.read_selected_file', ('file_id',), 'test', '',
        lambda a, o: ActionResult(True, 'files.read_selected_file', a['file_id'],
            'observed', 'text_extracted', status_text='Прочитан файл.',
            data={'filename': filename, 'text': 'An extracted fact: budget 739 rubles.'}))
    monkeypatch.setattr(agent, 'ollama_chat', lambda *a, **k:
        {'content': json.dumps({'answer': 'Бюджет составляет 739 рублей.'})})
    prepared = agent.prepare_reply('Найди последний PDF, затем ' + tail,
        actions_authorized=True, conversation=Conversation('owner', 0))
    result = agent.complete_reply(prepared)
    assert len(result['action_results']) == 2
    assert filename in result['display_text']
    assert result['structured_result']['actions'][0]['data']['filename'] == filename
    assert filename not in result['speech_text']
    assert 'Список работ' in result['speech_text']
    assert 'две тысячи двадцать шестой год' in result['speech_text']
    if tail == 'прочитай его':
        assert prepared.initial['speech_deferred'] is True
        assert 'An extracted fact: budget 739 rubles.' in result['speech_text']
    else:
        assert calls == [{'app_id': 'obsidian'}]
