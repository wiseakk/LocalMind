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
def supported_fixtures(monkeypatch):
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
