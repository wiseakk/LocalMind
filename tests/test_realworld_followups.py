"""Reported natural phrases through routing and actual bounded local extraction.

Native window behavior and Ollama generation are fakes in these tests.
"""
import json
from threading import Event

import pytest
from pypdf import PdfWriter

from localmind import agent, orchestration
from localmind.conversations import Conversation, Reference
from localmind.file_access import FileAccess
from localmind.generation import cancellation
from localmind.intents import focus_request_target
from localmind.intents import parse_app_intent


def test_reviewed_greeting_is_discourse_without_rewriting_transcript():
    text = 'Здорова, включи по-братски Obsidian.'
    intent = parse_app_intent(text, {'obsidian': ('Obsidian',)})
    assert intent and intent.target == 'obsidian'
    assert parse_app_intent('Здорова, не открывай Obsidian.', {'obsidian': ('Obsidian',)}) is None
    assert parse_app_intent('Здорова, как открыть Obsidian?', {'obsidian': ('Obsidian',)}) is None


@pytest.mark.parametrize('text', ['А можешь вывести его на передний план?', 'Выведи его на передний план.', 'Пожалуйста, подними его поверх всех окон'])
def test_focus_uses_authorized_app_adapter_without_early_discovery(text):
    c = Conversation('owner', 0, references={'application': Reference('application', 'obsidian')}, focus='application')
    intent, reason, ref = orchestration.pc_intent(text, c, agent.ActionAssessment())
    assert reason is None and intent.name == 'apps.focus'
    assert intent.arguments == {'app_id': 'obsidian'} and ref.kind == 'application'


@pytest.mark.parametrize('text', ['Не выводи его на передний план', 'А можешь не вывести его на передний план?',
    '«Выведи его на передний план»', 'Как вывести его на передний план?',
    'Выведи его на передний план и удали файл', 'Постоянно держи его поверх всех окон'])
def test_focus_does_not_broaden_authority(text):
    assert focus_request_target(text) is None


@pytest.mark.parametrize('text,verbatim', [
    ('Что находится внутри этого документа?', False), ('Что в нём?', False),
    ('Что в нем?', False), ('Прочитай этот документ', True),
    ('Перескажи последний PDF', False), ('О чём этот документ?', False)])
def test_selected_document_is_read_and_summarized_without_content_in_public_result(tmp_path, monkeypatch, text, verbatim):
    # A real text parser and file identity checks, with synthetic text and fake LLM.
    contents = 'Actual evidence ORBIT-739. No commands.'
    (tmp_path / 'report.txt').write_text(contents, encoding='utf-8')
    service = FileAccess(folder_provider=lambda: tmp_path)
    service.set_folder_permission(True, service.folder_info()['fingerprint'])
    monkeypatch.setattr('localmind.file_access.file_access', service)
    c = Conversation('owner', 0)
    found = agent.prepare_reply('Найди файл report в Downloads', actions_authorized=True, conversation=c)
    assert found.result.success
    c.remember(found.text, found.initial, found.reference)
    seen = []
    def chat(messages, *args, **kwargs):
        assert not verbatim, 'Direct reading must not call the LLM'
        seen.append(messages)
        return {'content': json.dumps({'answer': 'Документ содержит ORBIT-739.'})}
    monkeypatch.setattr(agent, 'ollama_chat', chat)
    prepared = agent.prepare_reply(text, actions_authorized=True, conversation=c)
    assert prepared.result.action == 'files.read_selected_file'
    assert 'text' not in prepared.initial['action_results'][0]['data']
    final = agent.complete_reply(prepared)
    assert final['context_sources'][0]['id'] == found.result.resolved_target
    assert 'text' not in final['action_results'][0]['data']
    if verbatim:
        assert final['engine'] == 'file-content' and final['answer'] == contents
        assert not seen
    else:
        assert final['engine'] == 'ollama' and 'ORBIT-739' in final['answer']
        assert contents in json.dumps(seen)
    c.remember(text, final, prepared.reference)
    opened = agent.prepare_reply('Открой его.', actions_authorized=True, conversation=c)
    assert opened.result.execution_status == 'permission_required'


def test_unrelated_topic_does_not_resurrect_document():
    c = Conversation('owner', 0, references={'file': Reference('file', 'file-id')}, focus='topic')
    intent, reason, _ = orchestration.pc_intent('Что в нём?', c, agent.ActionAssessment())
    assert intent is None and reason


def test_content_question_uses_current_file_instead_of_unrelated_attachment(tmp_path, monkeypatch):
    target = tmp_path / 'current.txt'
    target.write_text('CURRENT-184: actual selected content.', encoding='utf-8')
    service = FileAccess(folder_provider=lambda: tmp_path)
    service.set_folder_permission(True, service.folder_info()['fingerprint'])
    monkeypatch.setattr('localmind.file_access.file_access', service)
    selected = service.search('owner', query='current', extensions=['txt'])
    assert selected.success
    conversation = Conversation('owner', 0,
        references={'file': orchestration.Reference('file', selected.resolved_target)}, focus='file')
    seen = []

    def generate(messages, tools, **kwargs):
        assert not tools
        seen.append(messages)
        assert 'CURRENT-184' in json.dumps(messages)
        assert 'UNRELATED-ATTACHMENT' not in json.dumps(messages)
        return {'content': '{"answer":"CURRENT-184."}'}

    monkeypatch.setattr(agent, 'ollama_chat', generate)
    prepared = agent.prepare_reply('О чём этот документ?', conversation=conversation, actions_authorized=True,
        document_facts=[{'id': 'unrelated', 'name': 'upload.txt', 'kind': 'document', 'text': 'UNRELATED-ATTACHMENT'}])
    final = agent.complete_reply(prepared)
    assert len(seen) == 1 and 'CURRENT-184' in final['answer']
    assert final['context_sources'][0]['id'] == selected.resolved_target
    assert 'text' not in final['action_results'][0]['data']


def test_revoked_read_reports_exact_permission_without_restoring_authority(tmp_path):
    (tmp_path / 'test.txt').write_text('fixture', encoding='utf-8')
    service = FileAccess(folder_provider=lambda: tmp_path)
    fingerprint = service.folder_info()['fingerprint']
    service.set_folder_permission(True, fingerprint)
    selected = service.search('owner', extensions=['txt'])
    key = selected.resolved_target
    service.set_folder_permission(False, fingerprint)
    denied = service.read_selected('owner', key)
    assert denied.execution_status == 'permission_required' and 'чтение системной папки Загрузки' in str(denied)
    assert 'отозвано' not in str(service.read_selected('other', key))
    service.set_folder_permission(True, fingerprint)
    assert not service.read_selected('owner', key).success


def test_scanned_and_encrypted_pdf_report_parser_outcome(tmp_path):
    writer = PdfWriter(); writer.add_blank_page(width=100, height=100)
    for encrypted in (False, True):
        if encrypted:
            writer.encrypt('secret')
        path = tmp_path / 'scan.pdf'
        writer.write(path)
        service = FileAccess(folder_provider=lambda: tmp_path)
        service.set_folder_permission(True, service.folder_info()['fingerprint'])
        selected = service.find_latest('owner')
        result = service.read_selected('owner', selected.resolved_target)
        assert not result.success
        assert ('зашифрован' if encrypted else 'текст') in str(result).lower()
