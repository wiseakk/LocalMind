"""Access policy security regressions: real fixture I/O, no personal data."""
import json
import os
from pathlib import Path
import subprocess
import sys
from unittest.mock import Mock

import pytest

from localmind.access_rules import parse_rules
from localmind.file_access import FileAccess, FileAccessError, _checked, _identity
from localmind.file_mutations import FileMutations
from localmind.personal_permissions import FILE_OPERATIONS, PersonalMode


def configured(tmp_path, operations=FILE_OPERATIONS, persistence=None):
    root = tmp_path / 'documents'
    root.mkdir(exist_ok=True)
    access = FileAccess(lambda: root, opener=Mock(), persistence=persistence)
    access.personal_mode.configure('restricted', [str(root)], list(operations))
    return access, root, access.personal_info()['roots'][0]['id']


def test_legacy_read_only_scope_is_shown_without_permission_upgrade(tmp_path):
    root = tmp_path / 'downloads'
    root.mkdir()
    access = FileAccess(lambda: root)
    access.set_folder_permission(True, access.folder_info()['fingerprint'])
    visible = access.personal_info()
    assert visible['operations'] == ['read', 'search']
    assert visible['roots'][0]['operations'] == ['read', 'search']
    access.personal_mode.configure(visible['mode'], [row['path'] for row in visible['roots']], visible['operations'])
    assert not access.personal_mode.allows(root / 'new.txt', 'create')
    assert not access.personal_mode.allows(root / 'report.pdf', 'open')


def test_full_user_reload_refuses_roots_no_longer_in_current_known_folders(tmp_path):
    original, changed = tmp_path / 'original', tmp_path / 'changed'
    original.mkdir()
    changed.mkdir()
    state = tmp_path / 'policy.json'
    policy = PersonalMode(state, root_provider=lambda: [str(original)])
    policy.configure('full_user', [], ['search', 'read'])
    restored = PersonalMode(state, root_provider=lambda: [str(changed)])
    assert restored.mode == 'restricted' and restored.error
    assert not restored.allows(original / 'document.txt', 'read')


def test_corrupt_full_user_without_roots_cannot_grant_applications(tmp_path):
    root = tmp_path / 'documents'
    root.mkdir()
    state = tmp_path / 'policy.json'
    policy = PersonalMode(state, root_provider=lambda: [str(root)])
    policy.configure('full_user', [], ['read'])
    content = json.loads(state.read_text(encoding='utf-8'))
    content['roots'] = []
    state.write_text(json.dumps(content), encoding='utf-8')
    restored = PersonalMode(state, root_provider=lambda: [str(root)])
    assert restored.error and restored.mode == 'restricted'
    assert not restored.app_allowed(['any-installed-image'], 'launch')


def test_policy_size_limit_rolls_back_instead_of_saving_unloadable_grants(tmp_path, monkeypatch):
    import localmind.personal_permissions as module
    root = tmp_path / 'documents'
    root.mkdir()
    state = tmp_path / 'policy.json'
    policy = PersonalMode(state)
    policy.configure('restricted', [str(root)], ['read'])
    before, revision = state.read_bytes(), policy.generation
    monkeypatch.setattr(module, 'MAX_POLICY_BYTES', len(before) + 20)
    with pytest.raises(FileAccessError):
        policy.set_app_permission(['image:' + 'x' * 1000 + '|hash'], 'launch', True)
    assert policy.generation == revision and state.read_bytes() == before
    assert policy.public()['apps'] == []


def deny_folder(policy, root):
    draft = policy.preview('Не трогай папку Загрузки', folders={'Загрузки': str(root)})
    assert draft['draft_id'] and not draft['clarification']
    policy.apply(draft['draft_id'])


def test_preview_is_inert_apply_is_explicit_and_deny_is_recursive(tmp_path):
    access, root, _ = configured(tmp_path)
    child = root / 'nested' / 'report.txt'
    child.parent.mkdir()
    child.write_text('fixture', encoding='utf-8')
    draft = access.personal_mode.preview('Не трогай папку Загрузки.', folders={'Загрузки': str(root)})
    assert access.personal_mode.allows(child, 'read')
    assert access.personal_info()['rules'] == []
    access.personal_mode.apply(draft['draft_id'])
    for operation in FILE_OPERATIONS:
        assert not access.personal_mode.allows(root, operation)
        assert not access.personal_mode.allows(child, operation)
    with pytest.raises(FileAccessError):
        access.personal_mode.check_file(child, 'read')
    last = access.personal_info()['access_log'][-1]
    assert last['decision'] == 'denied' and last['reason'] and last['rule']
    assert last['policy_revision'] == access.personal_mode.generation


@pytest.mark.parametrize('text', [
    'Не трогай папку неизвестная',
    'Разрешаю редактировать документы, но запрещаю удалять их',
    'Можно открывать MissingApp, но не закрывать его',
    'Разрешаю всё; powershell Remove-Item',
    'Не трогай папку Загрузки. А документы можно удалять',
])
def test_ambiguous_unknown_and_partial_rules_require_clarification(tmp_path, text):
    access, root, _ = configured(tmp_path)
    before = access.personal_mode.generation
    result = access.personal_mode.preview(text, folders={'Загрузки': str(root)})
    assert result['clarification'] and not result['draft_id'] and not result['rules']
    assert not access.personal_info()['rules'] and access.personal_mode.generation == before


def test_edit_rule_needs_scope_and_does_not_authorize_delete(tmp_path):
    access, root, scope = configured(tmp_path, ['search', 'read'])
    target = root / 'report.txt'
    target.write_text('original', encoding='utf-8')
    text = 'Разрешаю редактировать документы, но запрещаю удалять их'
    draft = access.personal_mode.preview(text, scope=str(root), folders={'Документы': str(root)})
    assert draft['draft_id']
    assert not access.personal_mode.allows(target, 'overwrite')
    access.personal_mode.apply(draft['draft_id'])
    assert access.personal_mode.allows(target, 'overwrite')
    assert not access.personal_mode.allows(target, 'delete')
    mutations = FileMutations(access)
    pending = mutations.prepare('owner', 'overwrite', scope, target.name, 'approved')
    assert pending.execution_status == 'confirmation_required'
    assert target.read_text(encoding='utf-8') == 'original'
    assert mutations.confirm('owner', pending.resolved_target, True).success
    assert target.read_text(encoding='utf-8') == 'approved'
    assert mutations.prepare('owner', 'delete', scope, target.name).execution_status != 'confirmation_required'
    assert target.exists()


def test_app_rule_separates_launch_close_and_all_aliases():
    policy = PersonalMode()
    apps = [{'id': 'obsidian-a', 'name': 'Obsidian', 'target': 'fixture-obsidian',
             'aliases': ['обсидиан', 'obsidian'], 'policy_identifiers': ['image:fixture|digest']},
            {'id': 'obsidian-b', 'name': 'Obsidian', 'target': 'fixture-obsidian',
             'aliases': ['другой-алиас']}]
    draft = policy.preview('Можно открывать Obsidian, но не закрывать его', apps=apps)
    assert draft['draft_id'] and not policy.app_allowed(['obsidian-a'], 'launch')
    policy.apply(draft['draft_id'])
    assert policy.app_allowed(['obsidian-a', 'image:fixture|digest'], 'launch')
    assert policy.app_allowed(['obsidian-b', 'image:fixture|digest'], 'launch')
    assert not policy.app_allowed(['obsidian-a', 'image:fixture|changed'], 'launch')
    assert not policy.app_allowed(['другой-алиас'], 'close')
    assert not policy.app_allowed(['obsidian-a'], 'focus')
    # A later broad grant and full-user mode must never override the deny.
    policy.set_app_permission(['obsidian-a', 'обсидиан'], 'close', True)
    assert not policy.app_allowed(['обсидиан'], 'close')


def test_duplicate_app_names_for_different_executables_require_clarification():
    result = parse_rules('Можно открывать Obsidian, но не закрывать его', apps=[
        {'id': 'a', 'name': 'Obsidian', 'target': 'path-a'},
        {'id': 'b', 'name': 'Obsidian', 'target': 'path-b'},
    ])
    assert result['clarification'] and result['rules'] == []


@pytest.mark.parametrize('alias', ['editor', 'notepad'])
def test_grant_for_different_image_with_same_alias_never_removes_deny(tmp_path, alias):
    root = tmp_path / 'documents'
    root.mkdir()
    policy = PersonalMode(root_provider=lambda: [str(root)])
    policy.configure('full_user', [], sorted(FILE_OPERATIONS))
    first = ['app-a', alias, 'image:c:\\fixture\\a.exe|digest-a']
    second = ['app-b', alias, 'image:c:\\fixture\\b.exe|digest-b']
    policy.set_app_permission(first, 'launch', False)
    policy.set_app_permission(second, 'launch', True)
    assert not policy.app_allowed(first, 'launch')
    assert any(not g['allowed'] and 'app-a' in g['identifiers'] for g in policy.public()['apps'])
    assert not policy.app_allowed(first, 'launch')


def test_exact_pdf_open_grant_cannot_override_disabled_open_operation(tmp_path):
    access, root, _ = configured(tmp_path, ['search', 'read'])
    (root / 'report.pdf').write_bytes(b'%PDF-1.7\nfixture')
    selected = access.find_latest('owner')
    assert selected.success
    with pytest.raises(FileAccessError):
        access.set_open_permission('owner', selected.resolved_target, True)
    assert not access.open_selected('owner', selected.resolved_target).success
    access.opener.assert_not_called()


def test_configured_source_consent_cannot_override_disabled_read(tmp_path):
    from localmind.retrieval import LocalRetrieval, RetrievalError
    access, root, _ = configured(tmp_path, ['search'])
    target = root / 'reference.txt'
    target.write_text('uniquefixtureword confidential', encoding='utf-8')
    retrieval = LocalRetrieval([{'id': 'reference', 'label': 'Fixture', 'path': str(target)}], policy=access.personal_mode)
    with pytest.raises(RetrievalError):
        retrieval.set_permission('reference', True, retrieval.entries()[0]['fingerprint'])
    assert not retrieval.search('uniquefixtureword')['hits']


def test_rule_conflict_never_partially_applies(tmp_path):
    access, root, _ = configured(tmp_path)
    deny_folder(access.personal_mode, root)
    before = access.personal_info()['rules']
    draft = access.personal_mode.preview('Разрешаю редактировать документы, но запрещаю удалять их',
        scope=str(root), folders={'Документы': str(root)})
    assert draft['clarification'] and draft['draft_id'] is None
    assert access.personal_info()['rules'] == before


@pytest.mark.parametrize('first_is_parent_deny', [True, False])
def test_parent_child_rule_conflicts_always_require_clarification(tmp_path, first_is_parent_deny):
    access, root, _ = configured(tmp_path)
    child = root / 'nested'
    child.mkdir()
    edit = 'Разрешаю редактировать документы, но запрещаю удалять их'
    if first_is_parent_deny:
        deny_folder(access.personal_mode, root)
        before = access.personal_info()['rules']
        result = access.personal_mode.preview(edit, scope=str(child), folders={'Документы': str(child)})
    else:
        draft = access.personal_mode.preview(edit, scope=str(child), folders={'Документы': str(child)})
        access.personal_mode.apply(draft['draft_id'])
        before = access.personal_info()['rules']
        result = access.personal_mode.preview('Не трогай папку Загрузки', folders={'Загрузки': str(root)})
    assert result['clarification'] and result['draft_id'] is None and not result['rules']
    assert access.personal_info()['rules'] == before


def test_mode_or_rule_change_invalidates_pdf_tokens_and_pending_confirmations(tmp_path):
    access, root, scope = configured(tmp_path)
    (root / 'report.pdf').write_bytes(b'%PDF-1.7\nfixture')
    (root / 'report.txt').write_text('original', encoding='utf-8')
    selected = access.find_latest('owner')
    assert selected.success
    access.set_open_permission('owner', selected.resolved_target, True)
    mutations = FileMutations(access)
    pending = mutations.prepare('owner', 'overwrite', scope, 'report.txt', 'changed')
    assert pending.execution_status == 'confirmation_required'
    deny_folder(access.personal_mode, root)
    assert not access.open_selected('owner', selected.resolved_target).success
    assert not access.read_selected('owner', selected.resolved_target).success
    assert not mutations.confirm('owner', pending.resolved_target, True).success
    assert (root / 'report.txt').read_text(encoding='utf-8') == 'original'
    access.opener.assert_not_called()


def test_deny_cannot_be_overridden_by_new_pdf_open_grant(tmp_path):
    access, root, _ = configured(tmp_path)
    (root / 'report.pdf').write_bytes(b'%PDF-1.7\nfixture')
    selected = access.find_latest('owner')
    deny_folder(access.personal_mode, root)
    with pytest.raises(FileAccessError):
        access.set_open_permission('owner', selected.resolved_target, True)
    assert not access.open_selected('owner', selected.resolved_target).success
    access.opener.assert_not_called()


@pytest.mark.parametrize('blocked_side', ['source', 'destination'])
def test_move_checks_both_source_and_destination(tmp_path, blocked_side):
    access, root, scope = configured(tmp_path)
    blocked = root / 'blocked'
    blocked.mkdir()
    deny_folder(access.personal_mode, blocked)
    source = blocked / 'source.txt' if blocked_side == 'source' else root / 'source.txt'
    destination = blocked / 'destination.txt' if blocked_side == 'destination' else root / 'destination.txt'
    source.write_text('fixture', encoding='utf-8')
    pending = FileMutations(access).prepare('owner', 'move', scope, str(source.relative_to(root)),
        destination=str(destination.relative_to(root)))
    assert pending.execution_status != 'confirmation_required'
    assert source.exists() and not destination.exists()


def test_full_user_roots_are_os_supplied_and_unknown_disk_is_not_owned(tmp_path):
    profile, redirected, unrelated = (tmp_path / name for name in ('profile', 'redirected-documents', 'unrelated-disk'))
    for path in (profile, redirected, unrelated):
        path.mkdir()
    policy = PersonalMode(root_provider=lambda: [str(profile), str(redirected)])
    policy.configure('full_user', [], list(FILE_OPERATIONS))
    assert policy.allows(profile / 'ordinary.txt', 'read')
    assert policy.allows(redirected / 'ordinary.txt', 'read')
    assert not policy.allows(unrelated / 'ordinary.txt', 'read')
    with pytest.raises(FileAccessError):
        policy.configure('full_user', [str(unrelated)], list(FILE_OPERATIONS))
    assert policy.public()['mode'] == 'full_user'
    assert not policy.allows(profile / '.ssh' / 'key.txt', 'read')
    assert not policy.allows(profile / 'Chrome' / 'User Data' / 'safe.txt', 'read')
    assert not policy.allows(profile / 'ordinary.txt', 'execute')


def test_legacy_mode_never_enables_full_user(tmp_path):
    access, root, _ = configured(tmp_path)
    access.personal_mode.root_provider = lambda: [str(root)]
    access.personal_mode.configure('full_user', [], list(FILE_OPERATIONS))
    access.set_personal_mode(True, [str(root)])
    assert access.personal_info()['mode'] == 'restricted'
    assert not access.known_app_launch_allowed()


def test_rules_mode_scopes_and_app_grants_persist_across_process_restart(tmp_path):
    state = tmp_path / 'policy.json'
    root = tmp_path / 'documents'
    root.mkdir()
    policy = PersonalMode(state, user_identity=lambda: 'fixture-sid', root_provider=lambda: [str(root)])
    policy.configure('full_user', [], ['search', 'read', 'open'])
    deny_folder(policy, root)
    policy.set_app_permission(['fixture-app', 'image:fixture|digest'], 'launch', True)
    script = (
        'import json,sys; from localmind.personal_permissions import PersonalMode; '
        'p=PersonalMode(sys.argv[1],user_identity=lambda:"fixture-sid"); '
        'print(json.dumps(p.public(),ensure_ascii=True))'
    )
    process = subprocess.run([sys.executable, '-c', script, str(state)],
        cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True, timeout=20)
    assert process.returncode == 0, process.stderr
    loaded = json.loads(process.stdout)
    assert loaded['mode'] == 'full_user' and loaded['error'] is None
    assert loaded['rules'] == policy.public()['rules']
    assert loaded['roots'] == policy.public()['roots']
    assert loaded['apps'] == policy.public()['apps']
    assert loaded['revision'] != policy.generation


def test_rc3_migration_retains_exact_roots_without_broad_app_permission(tmp_path):
    root = tmp_path / 'documents'
    root.mkdir()
    state = tmp_path / 'policy.json'
    state.write_text(json.dumps({'version': 1, 'user': 'fixture-sid', 'enabled': True,
        'roots': [{'id': 'legacy-root', 'path': str(root), 'identity': _identity(root)}]}), encoding='utf-8')
    policy = PersonalMode(state, user_identity=lambda: 'fixture-sid')
    assert policy.enabled() and policy.public()['mode'] == 'restricted'
    assert list(policy.roots().values()) == [root]
    assert not policy.app_allowed(['random-app'], 'launch')


@pytest.mark.parametrize('corrupt', ['[]', 'null', '"text"', '{',
    '{"version":999,"user":"fixture-sid","roots":[]}',
    '{"version":2,"user":"other-sid","roots":[]}'])
def test_corrupt_unknown_version_or_different_owner_fails_closed(tmp_path, corrupt):
    state = tmp_path / 'policy.json'
    state.write_text(corrupt, encoding='utf-8')
    policy = PersonalMode(state, user_identity=lambda: 'fixture-sid')
    assert not policy.enabled() and policy.public()['error']
    assert not policy.app_allowed(['builtin:notepad'], 'launch')
    assert not policy.allows(tmp_path / 'ordinary.txt', 'read')


def test_atomic_save_failure_rolls_back_and_keeps_old_revision(tmp_path, monkeypatch):
    state = tmp_path / 'policy.json'
    access, root, _ = configured(tmp_path, persistence=state)
    before = access.personal_info()
    saved = state.read_bytes()
    import localmind.paths as paths
    def failure(*_):
        raise OSError('fixture disk full')
    monkeypatch.setattr(paths, 'atomic_json', failure)
    with pytest.raises(OSError):
        access.personal_mode.configure('restricted', [], [])
    assert access.personal_info()['mode'] == before['mode']
    assert access.personal_info()['roots'] == before['roots']
    assert access.personal_mode.generation == before['revision']
    assert state.read_bytes() == saved
    assert access.personal_mode.allows(root / 'ordinary.txt', 'read')


def test_audit_write_failure_reports_persisted_policy_and_visible_warning(tmp_path, monkeypatch):
    from localmind.action_journal import journal
    state = tmp_path / 'policy.json'
    access, root, _ = configured(tmp_path, persistence=state)
    access.personal_mode.root_provider = lambda: [str(root)]
    previous = access.personal_mode.generation
    def audit_failure(*_, **__):
        raise OSError('fixture journal write denied')
    monkeypatch.setattr(journal, 'record', audit_failure)
    access.personal_mode.configure('full_user', [], ['search', 'read'])
    result = access.personal_info()
    assert result['mode'] == 'full_user' and result['audit_warning']
    assert result['revision'] != previous and result['error'] is None
    assert result['access_log'][-1]['decision'] == 'applied'
    loaded = PersonalMode(state)
    assert loaded.public()['mode'] == 'full_user' and loaded.public()['operations'] == ['read', 'search']
    assert loaded.enabled() and loaded.public()['error'] is None


def test_search_only_scope_never_reads_or_hashes_document_contents(tmp_path, monkeypatch):
    import localmind.file_access as file_module
    access, root, scope = configured(tmp_path, ['search'])
    target = root / 'report.txt'
    target.write_text('fixture body must remain unread', encoding='utf-8')
    def fail_hash(*_):
        raise AssertionError('Search-only access must not hash file contents')
    monkeypatch.setattr(file_module, '_fingerprint', fail_hash)
    old_open = Path.open
    def guarded_open(path, *args, **kwargs):
        if path == target:
            raise AssertionError('Search-only access must not open document bytes')
        return old_open(path, *args, **kwargs)
    monkeypatch.setattr(Path, 'open', guarded_open)
    result = access.search('owner', scope=scope, extensions=['txt'])
    assert result.success and result.data['filename'] == target.name
    assert result.data['sha256'] is None
    selected = access.selected_info('owner', result.resolved_target)
    assert selected['sha256'] is None and not selected['open_allowed']
    assert not access.read_selected('owner', result.resolved_target).success
    assert not access.open_selected('owner', result.resolved_target).success
    with pytest.raises(FileAccessError):
        access.set_open_permission('owner', result.resolved_target, True)
    access.opener.assert_not_called()


@pytest.mark.skipif(os.name != 'nt', reason='Windows ProfileList ownership')
def test_registered_foreign_profile_outside_users_is_always_excluded(tmp_path, monkeypatch):
    import localmind.personal_permissions as permissions
    access, root, scope = configured(tmp_path)
    foreign = root / 'RelocatedAccounts' / 'FixtureOtherAccount'
    foreign.mkdir(parents=True)
    target = foreign / 'ordinary.txt'
    target.write_text('foreign-account fixture only', encoding='utf-8')
    (root / 'allowed.txt').write_text('current-account fixture', encoding='utf-8')
    monkeypatch.setattr(permissions, 'foreign_profile_roots', lambda: (foreign,))
    assert not permissions.ordinary_path(target)
    with pytest.raises(FileAccessError):
        access.personal_mode.check_file(target, 'read')
    assert access.personal_info()['access_log'][-1]['rule'] == 'mandatory_exclusion'
    result = access.search('owner', scope=scope, extensions=['txt'], recursive=True)
    assert result.success
    assert [row['filename'] for row in result.data['files']] == ['allowed.txt']
    with pytest.raises(FileAccessError):
        access.personal_mode.configure('restricted', [str(foreign)], ['search', 'read'])
    pending = FileMutations(access).prepare('owner', 'create', scope,
        str((foreign / 'new.txt').relative_to(root)), 'bad')
    assert pending.execution_status != 'confirmation_required'
    assert not (foreign / 'new.txt').exists()


def test_draft_cannot_be_applied_after_another_policy_revision(tmp_path):
    access, root, _ = configured(tmp_path)
    draft = access.personal_mode.preview('Не трогай папку Загрузки', folders={'Загрузки': str(root)})
    access.personal_mode.configure('restricted', [str(root)], ['search', 'read'])
    with pytest.raises(FileAccessError):
        access.personal_mode.apply(draft['draft_id'])
    assert not access.personal_info()['rules']


def test_cancelled_and_expired_direct_confirmations_are_audited_without_content(tmp_path):
    access, _, scope = configured(tmp_path)
    clock = Mock(return_value=0)
    mutations = FileMutations(access, clock=clock, ttl=10)
    content = 'fixture document body must never appear in audit'
    cancelled = mutations.prepare('owner', 'create', scope, 'cancelled.txt', content)
    assert mutations.confirm('owner', cancelled.resolved_target, False).execution_status == 'cancelled'
    last = access.personal_info()['access_log'][-1]
    assert last['decision'] == 'cancelled' and last['reason']
    assert last['policy_revision'] == access.personal_mode.generation
    expired = mutations.prepare('owner', 'create', scope, 'expired.txt', content)
    clock.return_value = 11
    assert not mutations.confirm('owner', expired.resolved_target, True).success
    last = access.personal_info()['access_log'][-1]
    assert last['decision'] == 'denied' and last['reason']
    assert last['policy_revision'] == access.personal_mode.generation
    assert content not in json.dumps(access.personal_info()['access_log'])


def test_hard_link_target_is_never_read_opened_or_modified(tmp_path):
    access, root, scope = configured(tmp_path)
    source = tmp_path / 'outside.txt'
    source.write_text('fixture confidential', encoding='utf-8')
    alias = root / 'ordinary.txt'
    os.link(source, alias)
    with pytest.raises(FileAccessError):
        _checked(alias)
    assert not access.search('owner', scope=scope, extensions=['txt']).success
    assert FileMutations(access).prepare('owner', 'overwrite', scope, alias.name, 'bad').execution_status != 'confirmation_required'
    assert source.read_text(encoding='utf-8') == 'fixture confidential'


@pytest.mark.skipif(os.name != 'nt', reason='Windows case-insensitive path identity')
def test_windows_case_variation_does_not_bypass_folder_deny(tmp_path):
    access, root, _ = configured(tmp_path)
    target = root / 'Report.txt'
    target.write_text('fixture', encoding='utf-8')
    deny_folder(access.personal_mode, root)
    assert not access.personal_mode.allows(Path(str(target).swapcase()), 'read')


@pytest.mark.skipif(os.name != 'nt', reason='Windows short-name aliases')
def test_windows_short_name_alias_is_rejected_before_read_or_write(tmp_path):
    import ctypes
    from ctypes import wintypes
    access, root, scope = configured(tmp_path)
    folder = root / 'Long Folder For Access Alias'
    folder.mkdir()
    target = folder / 'Long Document For Access Alias.txt'
    target.write_text('fixture', encoding='utf-8')
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.GetShortPathNameW.argtypes = [wintypes.LPCWSTR, wintypes.LPWSTR, wintypes.DWORD]
    kernel.GetShortPathNameW.restype = wintypes.DWORD
    buffer = ctypes.create_unicode_buffer(32768)
    length = kernel.GetShortPathNameW(str(target), buffer, len(buffer))
    if not length or '~' not in buffer.value:
        pytest.skip('This volume does not provide an 8.3 alias for the fixture.')
    short = Path(buffer.value)
    with pytest.raises(FileAccessError):
        _checked(short)
    deny_folder(access.personal_mode, folder)
    assert not access.personal_mode.allows(short, 'read')
    # Model/file APIs accept only a scope ID and checked relative target. An
    # alias presented under that root must still fail the canonical parent check.
    relative = str(Path(buffer.value).name)
    assert FileMutations(access).prepare('owner', 'overwrite', scope,
        folder.name + '/' + relative, 'bad').execution_status != 'confirmation_required'
    assert target.read_text(encoding='utf-8') == 'fixture'


def test_symlink_target_is_never_followed(tmp_path):
    access, root, scope = configured(tmp_path)
    outside = tmp_path / 'outside.txt'
    outside.write_text('fixture', encoding='utf-8')
    alias = root / 'ordinary.txt'
    try:
        alias.symlink_to(outside)
    except OSError as exc:
        pytest.skip(f'Token cannot create Windows symlinks: {exc.winerror}')
    with pytest.raises(FileAccessError):
        _checked(alias)
    assert not access.search('owner', scope=scope, extensions=['txt']).success
    assert FileMutations(access).prepare('owner', 'delete', scope, alias.name).execution_status != 'confirmation_required'


def test_configured_retrieval_source_cannot_bypass_folder_deny(tmp_path, monkeypatch):
    import localmind.file_access as file_module
    from localmind.retrieval import LocalRetrieval
    access, root, _ = configured(tmp_path)
    target = root / 'reference.txt'
    target.write_text('uniquefixtureword trusted source', encoding='utf-8')
    monkeypatch.setattr(file_module.file_access, 'personal_mode', access.personal_mode)
    retrieval = LocalRetrieval([{'id': 'reference', 'label': 'Fixture', 'path': str(target)}])
    retrieval.set_permission('reference', True, retrieval.entries()[0]['fingerprint'])
    assert retrieval.search('uniquefixtureword')['hits']
    deny_folder(access.personal_mode, root)
    assert retrieval.search('uniquefixtureword')['hits'] == []
    assert not retrieval.entries()[0]['allowed']


def test_retrieval_grant_is_stale_after_unrelated_policy_change(tmp_path, monkeypatch):
    import localmind.file_access as file_module
    from localmind.retrieval import LocalRetrieval
    access, root, _ = configured(tmp_path)
    target = root / 'reference.txt'
    target.write_text('uniquefixtureword source', encoding='utf-8')
    monkeypatch.setattr(file_module.file_access, 'personal_mode', access.personal_mode)
    retrieval = LocalRetrieval([{'id': 'reference', 'label': 'Fixture', 'path': str(target)}])
    retrieval.set_permission('reference', True, retrieval.entries()[0]['fingerprint'])
    access.personal_mode.configure('restricted', [str(root)], ['search', 'read'])
    assert retrieval.search('uniquefixtureword')['hits'] == []
    assert not retrieval.entries()[0]['allowed']


@pytest.mark.parametrize('relative', [
    '../outside.txt', '..\\outside.txt', 'C:ordinary.txt', 'ordinary.txt:stream',
    'ordinary.txt.', 'ordinary.txt ', '\\\\server\\share\\ordinary.txt', '\\\\?\\C:\\ordinary.txt',
])
def test_mutation_rejects_traversal_device_unc_ads_and_drive_relative(tmp_path, relative):
    access, root, scope = configured(tmp_path)
    result = FileMutations(access).prepare('owner', 'create', scope, relative, 'fixture')
    assert result.execution_status != 'confirmation_required'
    assert list(root.iterdir()) == []
