"""Directory commands must run on the live policy and never reach the LLM."""
import os
from unittest.mock import Mock

import pytest

from localmind import agent, file_access as files, llm_planner
from localmind.conversations import Conversation
from localmind.file_requests import directory_request


@pytest.fixture
def listing(tmp_path, monkeypatch):
    root = tmp_path/'Folder with spaces'
    root.mkdir()
    service = files.FileAccess(lambda: root, persistence=tmp_path/'policy.json')
    service.personal_mode.configure('restricted', [str(root)], ['read', 'search'])
    service = files.FileAccess(lambda: root, persistence=tmp_path/'policy.json')
    monkeypatch.setattr(files, 'file_access', service)
    planner = Mock(side_effect=AssertionError('A directory request must bypass the planner'))
    model = Mock(side_effect=AssertionError('A directory result must bypass the model'))
    monkeypatch.setattr(llm_planner, 'prepare', planner)
    monkeypatch.setattr(agent, 'ollama_chat', model)
    yield service, root
    planner.assert_not_called()
    model.assert_not_called()


def reply(text, *, authorized=True):
    prepared = agent.prepare_reply(text, actions_authorized=authorized, llm_first=True,
                                   conversation=Conversation('listing-owner', 0))
    return agent.complete_reply(prepared)


@pytest.mark.parametrize('template', [
    'Какие файлы есть в папке {}?', 'Покажи содержимое папки "{}".',
    'Что лежит в «{}»?', 'Перечисли файлы в\n{}.', 'Какие папки находятся в “{}”?',
    'Список файлов в {}', 'Покажи, что находится в папке\n  "{}"?',
])
def test_language_and_observed_items(listing, template):
    service, root = listing
    (root/'subfolder').mkdir()
    (root/'subfolder/nested.txt').write_text('not listed')
    (root/'z.txt').write_bytes(b'z')
    (root/'A.bin').write_bytes(b'data')
    result = reply(template.format(root))
    assert result['engine'] == 'file-listing' and result['actual_model'] is None
    outcome, = result['action_results']
    assert outcome['action'] == 'files.list_directory' and outcome['execution_status'] == 'observed'
    assert outcome['observed_state'] == 'directory_entries'
    data = outcome['data']
    assert [row['name'] for row in data['entries']] == ['subfolder', 'A.bin', 'z.txt']
    assert (data['files_count'], data['directories_count']) == (2, 1)
    assert data['entries'][1]['size_bytes'] == 4 and data['entries'][1]['modified_utc'].endswith('+00:00')
    assert all(row['name'] in result['answer'] for row in data['entries'])
    assert 'nested.txt' not in result['answer']
    assert result['steps'][0]['actual_result'] == 'observed'
    assert any(row['operation'] == 'search' and row['decision'] == 'observed'
               for row in service.personal_info()['access_log'])


def test_missing_empty_and_existing_file_are_distinct(listing):
    _, root = listing
    assert 'пусто' in reply(f'Что лежит в {root}?')['answer']
    absent = reply(f'Какие файлы есть в папке {root / "missing"}?')
    assert absent['action_results'][0]['execution_status'] == 'not_found'
    target = root/'regular.txt'
    target.touch()
    assert reply(f'Список файлов в {target}')['action_results'][0]['execution_status'] == 'invalid_target'


def test_read_only_grant_does_not_enumerate_and_unapproved_path_is_denied(listing, monkeypatch):
    service, root = listing
    service.personal_mode.configure('restricted', [str(root)], ['read'])
    scan = Mock(side_effect=AssertionError('Denied paths cannot be enumerated'))
    with monkeypatch.context() as patch:
        patch.setattr(files.os, 'scandir', scan)
        for path in (root, root.parent/'unapproved'):
            result = reply(f'Какие файлы есть в папке {path}?')
            assert result['action_results'][0]['execution_status'] == 'permission_required'
            assert '«Поиск»' in result['answer']
        scan.assert_not_called()


def test_rejected_links_cannot_list_external_targets(listing):
    _, root = listing
    other = root.parent/'outside'
    other.mkdir()
    (other/'private.txt').touch()
    try:
        os.symlink(other, root/'link', target_is_directory=True)
    except OSError as exc:
        pytest.skip(f'Directory symlinks unavailable: {exc.winerror if os.name == "nt" else exc.errno}')
    denied = reply(f'Какие файлы есть в папке {root / "link"}?')
    assert not denied['action_results'][0]['success']
    assert 'reparse' in denied['answer']
    result = reply(f'Какие файлы есть в папке {root}?')
    assert not result['action_results'][0]['data']['entries']
    assert 'private.txt' not in result['answer']
    assert not result['action_results'][0]['data']['empty']


def test_explicit_child_deny_takes_priority_over_parent_search_grant(listing):
    service, root = listing
    blocked = root/'Закрытая'
    blocked.mkdir()
    (root/'visible.txt').touch()
    draft = service.personal_mode.preview('Не трогай папку Закрытая', folders={'Закрытая': str(blocked)})
    service.personal_mode.apply(draft['draft_id'])

    result = reply(f'Список файлов в {root}')
    assert [row['name'] for row in result['action_results'][0]['data']['entries']] == ['visible.txt']
    assert blocked.name not in result['answer']
    denied = reply(f'Список файлов в {blocked}')
    assert denied['action_results'][0]['execution_status'] == 'permission_required'
    assert 'запрещено правилом' in denied['answer']


def test_listing_limit_preserves_real_count_and_review_guard(listing):
    _, root = listing
    for index in range(115):
        (root/f'{index:03d}.txt').touch()
    text = f'Какие файлы есть в папке {root}?'
    review = reply(text, authorized=False)
    assert review['engine'] == 'action-review' and review['action_results'] == []
    result = reply(text)
    data = result['action_results'][0]['data']
    assert data['truncated'] and data['files_count'] == 115 and len(data['entries']) == 50
    assert data['entries'][-1]['name'] == '049.txt'
    assert 'Показаны первые 50' in result['answer']


@pytest.mark.parametrize('text', ['Что лежит в основе теории?', 'Не показывай содержимое папки C:\\Demo',
                                  'Как сказать «Какие файлы есть в папке C:\\Demo»?'])
def test_non_commands_do_not_list(text):
    assert directory_request(text) is None
