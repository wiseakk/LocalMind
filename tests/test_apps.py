from pathlib import Path
import struct
import threading
from io import BytesIO
from types import SimpleNamespace
from unittest import mock

import pytest

from localmind import apps
from localmind.windows_state import ApplicationState, LaunchCoordinator


@pytest.fixture(autouse=True)
def supported_fixtures(monkeypatch, tmp_path):
    # Synthetic applications are user apps, separate from the assistant's own
    # installation even though restricted Windows test scratch is in the repo.
    monkeypatch.setattr(apps, '_protected_app_roots', lambda: (tmp_path / 'assistant-install',))
    monkeypatch.setattr(apps, 'SUPPORTED_GUI_EXECUTABLES',
                        apps.SUPPORTED_GUI_EXECUTABLES | {'editor', 'first', 'second'})
    monkeypatch.setattr(apps, 'launch_coordinator',
                        LaunchCoordinator(inspector=lambda _: ApplicationState('absent')))


def make_exe(path: Path, extra=b'', subsystem=2) -> Path:
    data = bytearray(256)
    data[:2] = b'MZ'
    struct.pack_into('<I', data, 60, 64)
    data[64:68] = b'PE\0\0'
    struct.pack_into('<H', data, 64 + 20, 168)
    struct.pack_into('<H', data, 64 + 24, 0x20B)
    struct.pack_into('<H', data, 64 + 24 + 68, subsystem)
    path.write_bytes(bytes(data) + extra)
    return path


def source(path, name='Editor', key='test', metadata=None):
    return apps.AppSource(key, name, lambda: (str(path), '', (metadata or ['source'])[0]))


def test_permissions_default_deny_and_bind_current_picker(tmp_path):
    executable = make_exe(tmp_path / 'editor.exe')
    catalog = apps.AppCatalog(lambda: [source(executable)])
    [entry] = catalog.refresh()
    with mock.patch.object(apps.subprocess, 'Popen') as spawn:
        assert not catalog.launch(entry['id'])['success']
        spawn.assert_not_called()
        with pytest.raises(apps.AppError):
            catalog.set_permission(entry['id'], True, 'old-ui-fingerprint')
        catalog.set_permission(entry['id'], True, entry['fingerprint'])
        result = catalog.launch(entry['id'])
        assert result['success']
        assert result['execution_status'] == 'process_created'
        assert result['observed_state'] is None
        assert spawn.call_count == 1
        assert spawn.call_args.args == ([str(executable.resolve())],)
        assert spawn.call_args.kwargs['shell'] is False


@pytest.mark.parametrize('name,activated', [('Obsidian', True), ('Editor', False)])
def test_only_granted_obsidian_opts_into_background_handoff(tmp_path, monkeypatch, name, activated):
    executable = make_exe(tmp_path / (name.lower() + '.exe'))
    catalog = apps.AppCatalog(lambda: [source(executable, name=name)])
    [entry] = catalog.refresh()
    coordinator = mock.Mock()
    from localmind.results import ActionResult
    coordinator.launch.return_value = ActionResult(True, 'open_app', name, 'process_created')
    monkeypatch.setattr(apps, 'launch_coordinator', coordinator)
    assert not catalog.launch(entry['id'])['success']
    coordinator.launch.assert_not_called()
    catalog.set_permission(entry['id'], True, entry['fingerprint'])
    assert catalog.launch(entry['id'])['success']
    assert coordinator.launch.call_args.kwargs == {'activate_background': activated}


from contextlib import contextmanager


@contextmanager
def _null_guard():
    yield


def test_executable_replacement_revokes_permission(tmp_path):
    executable = make_exe(tmp_path / 'editor.exe')
    catalog = apps.AppCatalog(lambda: [source(executable)])
    [entry] = catalog.refresh()
    catalog.set_permission(entry['id'], True, entry['fingerprint'])
    make_exe(executable, b'changed executable')
    with mock.patch.object(apps.subprocess, 'Popen') as spawn:
        assert not catalog.launch(entry['id'])['success']
        spawn.assert_not_called()
    assert not catalog.entries()[0]['allowed']


def test_shortcut_metadata_replacement_revokes_permission(tmp_path):
    executable = make_exe(tmp_path / 'editor.exe')
    metadata = ['original-shortcut-hash']
    catalog = apps.AppCatalog(lambda: [source(executable, metadata=metadata)])
    [entry] = catalog.refresh()
    catalog.set_permission(entry['id'], True, entry['fingerprint'])
    metadata[0] = 'replacement-shortcut-hash'
    with mock.patch.object(apps.subprocess, 'Popen') as spawn:
        assert not catalog.launch(entry['id'])['success']
        spawn.assert_not_called()
    assert not catalog.entries()[0]['allowed']


@pytest.mark.parametrize('filename', ['cmd.exe', 'powershell.exe', 'wscript.exe',
                                     'unins000.exe', 'setup.exe', 'python.exe',
                                     'app.cmd', 'app.lnk', 'app.url'])
def test_unsafe_targets_are_never_catalogued(tmp_path, filename):
    target = make_exe(tmp_path / filename)
    catalog = apps.AppCatalog(lambda: [source(target)])
    assert catalog.refresh() == []


def test_scripts_disguised_as_executable_and_arguments_refused(tmp_path):
    script = tmp_path / 'fake.exe'
    script.write_text('echo malicious')
    assert apps.AppCatalog(lambda: [source(script)]).refresh() == []
    executable = make_exe(tmp_path / 'editor.exe')
    with pytest.raises(apps.AppError):
        apps.validate_executable(executable, '--execute anything')
    for target in ('https://example.com/app.exe', r'\\server\app.exe', 'editor.exe'):
        with pytest.raises(apps.AppError):
            apps.validate_executable(target)


def test_alias_ambiguity_requires_selection_and_ids_are_stable(tmp_path):
    first = make_exe(tmp_path / 'first.exe')
    second = make_exe(tmp_path / 'second.exe')
    catalog = apps.AppCatalog(lambda: [source(first, key='a'), source(second, key='b')])
    rows = catalog.refresh()
    assert len(catalog.resolve_alias('Editor')) == 2
    assert [row['id'] for row in catalog.refresh()] == [row['id'] for row in rows]
    assert catalog.resolve_alias('Unknown') == []


def test_known_alias_only_present_after_discovery_and_cli_excluded(tmp_path):
    code = make_exe(tmp_path / 'Code.exe')
    catalog = apps.AppCatalog(lambda: [source(code, name='Visual Studio Code')])
    [entry] = catalog.refresh()
    assert catalog.resolve_alias('VS Code') == [entry['id']]
    assert catalog.resolve_alias('Codex') == []
    cli = tmp_path / 'bin'
    cli.mkdir()
    make_exe(cli / 'codex.exe')
    assert apps.AppCatalog(lambda: [source(cli / 'codex.exe')]).refresh() == []


def test_codex_cli_outside_bin_is_excluded_by_pe_subsystem(tmp_path):
    cli = make_exe(tmp_path / 'codex.exe', subsystem=3)
    assert apps.AppCatalog(lambda: [source(cli)]).refresh() == []


def test_unique_catalog_id_alias_disambiguates_duplicate_names(tmp_path):
    first = make_exe(tmp_path / 'first.exe')
    second = make_exe(tmp_path / 'second.exe')
    catalog = apps.AppCatalog(lambda: [source(first, key='a'), source(second, key='b')])
    rows = catalog.refresh()
    assert len(catalog.resolve_alias('Editor')) == 2
    assert catalog.resolve_alias(rows[0]['id']) == [rows[0]['id']]


def test_steam_transport_aliases_resolve_to_client_only(tmp_path):
    executable = make_exe(tmp_path / 'steam.exe')
    game = apps.AppSource('steam-game', 'Demo Game', lambda: (str(executable), '', 'fixture'),
                          launch_type='steam', launch_id='42')
    catalog = apps.AppCatalog(lambda: [source(executable, name='Steam'), game])
    ids = {item['name']: item['id'] for item in catalog.refresh()}
    assert catalog.resolve_alias('Стим') == [ids['Steam']]
    assert catalog.resolve_alias('Demo Game') == [ids['Demo Game']]
    assert catalog.resolve_alias(ids['Demo Game']) == [ids['Demo Game']]


def test_duplicate_sources_for_same_target_are_deduplicated(tmp_path):
    executable = make_exe(tmp_path / 'editor.exe')
    catalog = apps.AppCatalog(lambda: [source(executable, key='a'), source(executable, key='b')])
    assert len(catalog.refresh()) == 1


def test_unknown_executable_cannot_become_launch_capability(tmp_path):
    executable = make_exe(tmp_path / 'reset-settings.exe')
    assert apps.AppCatalog(lambda: [source(executable)]).refresh() == []


def test_hashing_bounds_file_growth_after_initial_stat():
    path = mock.Mock()
    path.stat.return_value = SimpleNamespace(st_size=2)
    path.open.return_value = BytesIO(b'growing-file')
    with pytest.raises(apps.AppError, match='вырос'):
        apps._digest(path, maximum=4)


def test_refresh_is_single_flight():
    entered, release = threading.Event(), threading.Event()
    calls = []

    def provider():
        calls.append(True)
        entered.set()
        release.wait(2)
        return []

    catalog = apps.AppCatalog(provider)
    worker = threading.Thread(target=catalog.refresh)
    worker.start()
    assert entered.wait(1)
    try:
        assert catalog.refresh() == []
        assert len(calls) == 1
    finally:
        release.set()
        worker.join(2)
    assert not worker.is_alive()


def test_production_refresh_cooldown():
    provider = mock.Mock(return_value=[])
    catalog = apps.AppCatalog(provider, refresh_interval=2)
    catalog.refresh()
    catalog.refresh()
    assert provider.call_count == 1


def test_removed_target_and_spawn_failure_are_truthful(tmp_path):
    executable = make_exe(tmp_path / 'editor.exe')
    catalog = apps.AppCatalog(lambda: [source(executable)])
    [entry] = catalog.refresh()
    catalog.set_permission(entry['id'], True, entry['fingerprint'])
    with mock.patch.object(apps, '_launch_guard', side_effect=lambda _target: _null_guard()), \
            mock.patch.object(apps.subprocess, 'Popen', side_effect=OSError('secret-path')):
        failure = catalog.launch(entry['id'])
    assert not failure['success']
    assert failure['execution_status'] == 'not_executed'
    assert 'secret-path' not in failure['error']
    executable.unlink()
    assert not catalog.launch(entry['id'])['success']


def test_refresh_preserves_only_unchanged_permissions(tmp_path):
    executable = make_exe(tmp_path / 'editor.exe')
    catalog = apps.AppCatalog(lambda: [source(executable)])
    [entry] = catalog.refresh()
    catalog.set_permission(entry['id'], True, entry['fingerprint'])
    assert catalog.refresh()[0]['allowed']
    make_exe(executable, b'new-version')
    assert not catalog.refresh()[0]['allowed']


def test_stale_source_at_permission_time_is_rejected(tmp_path):
    executable = make_exe(tmp_path / 'editor.exe')
    metadata = ['old']
    catalog = apps.AppCatalog(lambda: [source(executable, metadata=metadata)])
    [entry] = catalog.refresh()
    metadata[0] = 'new'
    with pytest.raises(apps.AppError):
        catalog.set_permission(entry['id'], True, entry['fingerprint'])


def test_policy_app_operations_are_independent_and_persistent(tmp_path):
    from localmind.personal_permissions import PersonalMode
    executable = make_exe(tmp_path / 'editor.exe')
    state = tmp_path / 'permissions.json'
    policy = PersonalMode(state)
    catalog = apps.AppCatalog(lambda: [source(executable)], policy=policy)
    [entry] = catalog.refresh()
    catalog.set_permission(entry['id'], True, entry['fingerprint'], operation='launch')
    assert catalog.entries()[0]['permissions'] == {'launch': True, 'focus': False, 'close': False}
    restarted = apps.AppCatalog(lambda: [source(executable)], policy=PersonalMode(state))
    [row] = restarted.refresh()
    assert row['permissions'] == {'launch': True, 'focus': False, 'close': False}
    make_exe(executable, b'changed image')
    assert not restarted.refresh()[0]['allowed']


def test_catalog_notepad_deny_blocks_builtin_alias(tmp_path, monkeypatch):
    from localmind import agent
    from localmind.file_access import file_access
    from localmind.personal_permissions import PersonalMode
    executable = make_exe(tmp_path / 'notepad.exe')
    policy = PersonalMode()
    catalog = apps.AppCatalog(lambda: [source(executable, name='Notepad')], policy=policy)
    [entry] = catalog.refresh()
    catalog.set_permission(entry['id'], False, entry['fingerprint'], operation='launch')
    monkeypatch.setattr(file_access, 'personal_mode', policy)
    monkeypatch.setattr(agent.platform, 'system', lambda: 'Windows')
    monkeypatch.setattr(agent, 'resolve_windows_app', lambda _: executable)
    with mock.patch.object(agent.subprocess, 'Popen') as spawn:
        assert not agent.open_app('notepad').success
        spawn.assert_not_called()


def test_legacy_personal_flag_never_grants_applications(tmp_path):
    executable = make_exe(tmp_path / 'editor.exe')
    catalog = apps.AppCatalog(lambda: [source(executable)])
    [entry] = catalog.refresh()
    catalog.set_personal_mode(True)
    assert not catalog.is_allowed(entry['id'])


@pytest.mark.parametrize('filename', ['notepad.exe', 'calc.exe', 'calculator.exe'])
def test_builtin_name_cannot_authorize_an_unrelated_executable(tmp_path, filename):
    executable = make_exe(tmp_path / filename)
    catalog = apps.AppCatalog(lambda: [source(executable)])
    [entry] = catalog.refresh()
    assert not catalog.is_allowed(entry['id'])
    with mock.patch.object(apps.subprocess, 'Popen') as spawn:
        assert not catalog.launch(entry['id'])['success']
        spawn.assert_not_called()


def test_reparse_executable_is_not_catalogued(tmp_path):
    executable = make_exe(tmp_path / 'editor.exe')
    linked = tmp_path / 'linked.exe'
    try:
        linked.symlink_to(executable)
    except OSError:
        pytest.skip('Creating symlinks requires Windows Developer Mode or privilege')
    assert apps.AppCatalog(lambda: [source(linked)]).refresh() == []


def test_document_association_cannot_bypass_application_policy(tmp_path):
    from localmind.file_access import FileAccessError
    executable = make_exe(tmp_path / 'editor.exe')
    document = tmp_path / 'document & harmless.txt'
    document.write_text('test fixture')
    catalog = apps.AppCatalog(lambda: [source(executable)])
    [entry] = catalog.refresh()
    resolver = lambda suffix: executable
    with mock.patch.object(apps.subprocess, 'Popen') as spawn:
        with pytest.raises(FileAccessError):
            apps._open_document(document, app_catalog=catalog, association_resolver=resolver)
        spawn.assert_not_called()
        catalog.set_permission(entry['id'], True, entry['fingerprint'], operation='launch')
        apps._open_document(document, app_catalog=catalog, association_resolver=resolver)
        assert spawn.call_args.args == ([str(executable), str(document)],)
        assert spawn.call_args.kwargs['shell'] is False
        catalog.set_permission(entry['id'], False, entry['fingerprint'], operation='launch')
        with pytest.raises(FileAccessError):
            apps._open_document(document, app_catalog=catalog, association_resolver=resolver)
        assert spawn.call_count == 1


def test_full_user_requires_installation_evidence_or_persistent_image_grant(tmp_path, monkeypatch):
    from localmind.personal_permissions import PersonalMode, FILE_OPERATIONS
    install = tmp_path / 'Programs'
    install.mkdir()
    installed = make_exe(install / 'editor.exe')
    downloaded = make_exe(tmp_path / 'downloaded.exe')
    monkeypatch.setattr(apps, '_installation_roots', lambda: (install,))
    providers = lambda: [apps.replace(source(installed, name='Installed'), origin='shortcuts'),
                         apps.replace(source(downloaded, name='Downloaded'), origin='shortcuts')]
    state = tmp_path / 'permissions.json'
    policy = PersonalMode(state, root_provider=lambda: [str(tmp_path)])
    policy.configure('full_user', [], list(FILE_OPERATIONS))
    catalog = apps.AppCatalog(providers, policy=policy)
    rows = {row['name']: row for row in catalog.refresh()}
    assert rows['Installed']['allowed']
    assert not rows['Downloaded']['allowed']
    catalog.set_permission(rows['Downloaded']['id'], True, rows['Downloaded']['fingerprint'], operation='launch')
    restarted = apps.AppCatalog(providers, policy=PersonalMode(state, root_provider=lambda: [str(tmp_path)]))
    rows = {row['name']: row for row in restarted.refresh()}
    assert rows['Downloaded']['allowed']


def test_relocated_foreign_profile_cannot_be_an_installed_app(tmp_path, monkeypatch):
    from localmind import personal_permissions
    relocated = tmp_path / 'RelocatedProfiles' / 'OtherSid'
    relocated.mkdir(parents=True)
    executable = make_exe(relocated / 'editor.exe')
    monkeypatch.setattr(personal_permissions, 'foreign_profile_roots', lambda: (relocated,))
    monkeypatch.setattr(apps, '_installation_roots', lambda: (tmp_path,))
    catalog = apps.AppCatalog(lambda: [apps.replace(source(executable), origin='shortcuts')])
    [entry] = catalog.refresh()
    catalog.set_permission(entry['id'], True, entry['fingerprint'])
    assert not catalog.is_allowed(entry['id'])
    with mock.patch.object(apps.subprocess, 'Popen') as spawn:
        assert not catalog.launch(entry['id'])['success']
        spawn.assert_not_called()


def test_combined_app_grant_is_one_atomic_policy_commit(tmp_path, monkeypatch):
    executable = make_exe(tmp_path / 'editor.exe')
    catalog = apps.AppCatalog(lambda: [source(executable)])
    [entry] = catalog.refresh()
    before = catalog.policy.public()
    saved = []

    def failed_save():
        saved.append(catalog.policy.public()['apps'])
        raise OSError('synthetic full disk')

    monkeypatch.setattr(catalog.policy, '_save', failed_save)
    with pytest.raises(OSError):
        catalog.set_permission(entry['id'], True, entry['fingerprint'])
    assert len(saved) == 1
    assert {grant['operation'] for grant in saved[0]} == {'launch', 'focus', 'close'}
    assert catalog.policy.public()['apps'] == before['apps']
    assert catalog.policy.generation == before['revision']
    assert not catalog.is_allowed(entry['id'])


def test_hardlinked_app_alias_cannot_bypass_explicit_deny(tmp_path):
    import os
    first = make_exe(tmp_path / 'first.exe')
    second = tmp_path / 'second.exe'
    try:
        os.link(first, second)
    except OSError:
        pytest.skip('Hardlinks unavailable on this filesystem')
    catalog = apps.AppCatalog(lambda: [source(first, name='First'), source(second, name='Second')])
    rows = {row['name']: row for row in catalog.refresh()}
    catalog.set_permission(rows['First']['id'], False, rows['First']['fingerprint'], operation='launch')
    catalog.set_permission(rows['Second']['id'], True, rows['Second']['fingerprint'], operation='launch')
    assert not catalog.is_allowed(rows['Second']['id'])


@pytest.mark.skipif(apps.os.name != 'nt', reason='Windows native read-only discovery')
def test_native_shortcuts_can_be_parsed_without_launching():
    paths = []
    for root in apps._known_roots():
        paths.extend(root.glob('*.lnk'))
        paths.extend((root / 'Programs').glob('*.lnk'))
    if not paths:
        pytest.skip('No installed shortcut available')
    # A source may intentionally point at shell metadata: parsing is not approval.
    target, arguments = apps._read_shortcut(paths[0])
    assert isinstance(target, str)
    assert isinstance(arguments, str)
