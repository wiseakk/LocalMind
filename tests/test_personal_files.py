"""Real fixture I/O: broad consent, sorted search, identity and exact mutations."""
import json
import os
from pathlib import Path
from unittest.mock import Mock

import pytest

from localmind.file_access import FileAccess, FileAccessError, _checked
from localmind.file_mutations import FileMutations
from localmind.personal_permissions import PersonalMode


def personal(tmp_path, **kwargs):
    service = FileAccess(lambda: tmp_path, Mock(), **kwargs)
    service.set_personal_mode(True, [str(tmp_path)])
    return service, service.personal_info()['roots'][0]['id']


def test_sorted_search_names_sizes_and_followup_read(tmp_path):
    (tmp_path / 'old-report.txt').write_text('Actual old fixture content 73281', encoding='utf-8')
    (tmp_path / 'new-report.txt').write_text('New', encoding='utf-8')
    os.utime(tmp_path / 'old-report.txt', ns=(100, 100))
    os.utime(tmp_path / 'new-report.txt', ns=(200, 200))
    service, scope = personal(tmp_path)
    result = service.search('owner', extensions=['txt'], scope=scope, sort_by='modified', order='asc', limit=1)
    assert result.success and result.data['filename'] == 'old-report.txt'
    assert result.data['scan_complete'] and 'не скачивания' in result.status_text
    read = service.read_selected('owner', result.resolved_target)
    assert read.success and '73281' in read.data['text']
    assert not service.read_selected('other', result.resolved_target).success
    assert service.open_selected('owner', result.resolved_target).success
    service.opener.assert_called_once_with(tmp_path / 'old-report.txt')
    largest = service.search('owner', query='report', extensions=['.txt'], scope='all', sort_by='size', min_size=5)
    assert largest.success and largest.data['filename'] == 'old-report.txt'


def test_recursive_is_opt_in_and_revocation_invalidates_refs(tmp_path):
    nested = tmp_path / 'notes'
    nested.mkdir()
    (nested / 'example.md').write_text('nested content', encoding='utf-8')
    service, scope = personal(tmp_path)
    assert not service.search('owner', scope=scope, extensions=['md']).success
    result = service.search('owner', scope=scope, extensions=['md'], recursive=True)
    assert result.success
    service.set_personal_mode(False)
    assert not service.read_selected('owner', result.resolved_target).success
    assert not service.open_selected('owner', result.resolved_target).success
    service.opener.assert_not_called()
    assert service.personal_info()['access_log'][-1]['decision'] == 'denied'


def test_sensitive_stores_never_indexed(tmp_path):
    for relative in ('safe.txt', '.ssh/id_rsa.txt', 'Chrome/User Data/accounts.txt', 'credentials.txt', '.env.txt'):
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('ordinary or confidential fixture', encoding='utf-8')
    service, scope = personal(tmp_path)
    result = service.search('owner', scope=scope, extensions=['txt'], recursive=True)
    assert result.success
    assert [item['filename'] for item in result.data['files']] == ['safe.txt']
    assert not service.search('owner', scope=scope, extensions=['exe']).success
    assert not service.search('owner', scope=str(tmp_path), extensions=['txt']).success


def test_profile_persisted_only_for_current_os_user_and_exact_root(tmp_path):
    state = tmp_path / 'state.json'
    root = tmp_path / 'ordinary'
    root.mkdir()
    mode = PersonalMode(state, lambda: 'current-test-user')
    mode.set(True, [str(root)])
    assert PersonalMode(state, lambda: 'current-test-user').enabled()
    assert not PersonalMode(state, lambda: 'different-user').enabled()
    mode.set(False)
    assert not PersonalMode(state, lambda: 'current-test-user').enabled()


def test_profile_replacement_root_identity_invalidates(tmp_path):
    root = tmp_path / 'ordinary'
    root.mkdir()
    mode = PersonalMode(user_identity=lambda: 'test')
    mode.set(True, [str(root)])
    root.rename(tmp_path / 'old-root')
    root.mkdir()
    with pytest.raises(FileAccessError):
        mode.roots()


@pytest.mark.parametrize('fragment', ['file.txt:stream', 'file.txt.', 'file.txt ', '..\\file.txt'])
def test_invalid_paths_and_ads_rejected(tmp_path, fragment):
    with pytest.raises((FileAccessError, FileNotFoundError)):
        _checked(tmp_path / fragment)


def test_prepare_does_not_write_confirm_once_exact_content(tmp_path):
    service, scope = personal(tmp_path)
    mutations = FileMutations(service)
    pending = mutations.prepare('owner', 'create', scope, 'new.txt', 'Exact approved text 87562')
    assert pending.execution_status == 'confirmation_required'
    assert not (tmp_path / 'new.txt').exists()
    assert pending.data['content'] == 'Exact approved text 87562'
    assert not mutations.confirm('other', pending.resolved_target, True).success
    assert not (tmp_path / 'new.txt').exists()
    assert mutations.confirm('owner', pending.resolved_target, True).success
    assert (tmp_path / 'new.txt').read_text(encoding='utf-8') == 'Exact approved text 87562'
    assert not mutations.confirm('owner', pending.resolved_target, True).success
    overwrite = mutations.prepare('owner', 'overwrite', scope, 'new.txt', 'replacement')
    assert mutations.confirm('owner', overwrite.resolved_target, True).success
    assert (tmp_path / 'new.txt').read_text(encoding='utf-8') == 'replacement'
    delete = mutations.prepare('owner', 'delete', scope, 'new.txt')
    assert (tmp_path / 'new.txt').exists()
    assert mutations.confirm('owner', delete.resolved_target, True).success
    assert not (tmp_path / 'new.txt').exists()


def test_changed_file_expiry_and_cancel_are_not_permission(tmp_path):
    target = tmp_path / 'target.txt'
    target.write_text('original', encoding='utf-8')
    service, scope = personal(tmp_path)
    clock = Mock(return_value=10)
    mutations = FileMutations(service, clock=clock, ttl=30)
    pending = mutations.prepare('owner', 'delete', scope, 'target.txt')
    target.write_text('changed', encoding='utf-8')
    assert not mutations.confirm('owner', pending.resolved_target, True).success
    assert target.exists()
    pending = mutations.prepare('owner', 'delete', scope, 'target.txt')
    clock.return_value = 41
    assert not mutations.confirm('owner', pending.resolved_target, True).success
    assert target.exists()
    pending = mutations.prepare('owner', 'delete', scope, 'target.txt')
    assert mutations.confirm('owner', pending.resolved_target, False).execution_status == 'cancelled'
    assert not mutations.confirm('owner', pending.resolved_target, True).success


def test_reactivation_does_not_resurrect_old_confirmation(tmp_path):
    service, scope = personal(tmp_path)
    mutations = FileMutations(service)
    pending = mutations.prepare('owner', 'create', scope, 'new.txt', 'text')
    service.set_personal_mode(False)
    service.set_personal_mode(True, [str(tmp_path)])
    assert not mutations.confirm('owner', pending.resolved_target, True).success
    assert not (tmp_path / 'new.txt').exists()


def test_move_verified_and_never_overwrites_an_existing_target(tmp_path):
    service, scope = personal(tmp_path)
    (tmp_path / 'source.txt').write_text('move actual bytes', encoding='utf-8')
    mutations = FileMutations(service)
    pending = mutations.prepare('owner', 'move', scope, 'source.txt', destination='destination.txt')
    assert pending.execution_status == 'confirmation_required'
    assert mutations.confirm('owner', pending.resolved_target, True).success
    assert not (tmp_path / 'source.txt').exists()
    assert (tmp_path / 'destination.txt').read_text(encoding='utf-8') == 'move actual bytes'
    (tmp_path / 'source.txt').write_text('second source', encoding='utf-8')
    assert not mutations.prepare('owner', 'move', scope, 'source.txt', destination='destination.txt').success
    assert (tmp_path / 'destination.txt').read_text(encoding='utf-8') == 'move actual bytes'


@pytest.mark.parametrize('target', ['../outside.txt', 'script.ps1', '.ssh/key.txt', 'credentials.json', 'item.txt:stream'])
def test_mutations_cannot_escape_roots_or_write_sensitive_and_executable_targets(tmp_path, target):
    service, scope = personal(tmp_path)
    result = FileMutations(service).prepare('owner', 'create', scope, target, 'text')
    assert result.execution_status != 'confirmation_required'
