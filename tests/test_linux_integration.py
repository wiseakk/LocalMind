from pathlib import Path
import sys

import pytest

from localmind import file_access, hyprland_windows, linux_apps, linux_paths, secret_store
from localmind.apps import AppError
from localmind.windows_state import ApplicationState, VerifiedWindow

pytestmark = pytest.mark.skipif(sys.platform != 'linux', reason='Linux platform boundary')


@pytest.mark.parametrize('command', ('sh -c id', 'kitty --hold', 'env kitty', 'kitty %i'))
def test_desktop_entry_cannot_supply_launch_arguments(tmp_path, monkeypatch, command):
    entry = tmp_path / 'fixture.desktop'
    entry.write_text(f'[Desktop Entry]\nName=Fixture\nType=Application\nExec={command}\n')
    monkeypatch.setattr(linux_apps, '_ordinary', lambda *_: None)
    with pytest.raises(AppError, match='дополнительных аргументов'):
        linux_apps._read(entry)


def test_a_new_user_override_invalidates_an_existing_catalog_source(tmp_path, monkeypatch):
    user = tmp_path / 'user'
    system = tmp_path / 'system'
    for root in (user, system):
        (root / 'applications').mkdir(parents=True)
    system_entry = system / 'applications/example.desktop'
    system_entry.touch()
    monkeypatch.setattr(linux_apps, 'data_directories', lambda: (user, system))
    monkeypatch.setattr(linux_apps, '_read', lambda _: ('Fixture', Path('/usr/bin/kitty'), 'digest', False))
    [source] = linux_apps.discover(None)
    assert source.read()[2] == 'digest'
    (user / 'applications/example.desktop').touch()
    with pytest.raises(AppError, match='Приоритет'):
        source.read()


def test_xdg_download_directory_does_not_execute_shell(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, 'home', lambda: tmp_path)
    monkeypatch.setenv('XDG_CONFIG_HOME', str(tmp_path))
    config = tmp_path / 'user-dirs.dirs'
    config.write_text('XDG_DOWNLOAD_DIR="$HOME/Мои загрузки"\n', encoding='utf-8')
    assert linux_paths.user_directory('downloads') == tmp_path / 'Мои загрузки'
    config.write_text('XDG_DOWNLOAD_DIR="$HOME/$(touch unwanted)"\n', encoding='utf-8')
    assert linux_paths.user_directory('downloads') == tmp_path / 'Downloads'


def test_opened_document_rejects_replaced_parent(tmp_path):
    folder = tmp_path / 'approved'
    folder.mkdir()
    document = folder / 'file.txt'
    document.write_text('approved')
    identity = file_access._identity(document)
    moved = folder.rename(tmp_path / 'elsewhere')
    folder.symlink_to(moved, target_is_directory=True)
    with pytest.raises(OSError), file_access._read_handle(document, identity):
        pytest.fail('followed a replaced parent directory')


def test_hyprland_focus_checks_target_and_active_after_dispatch(monkeypatch):
    backend = hyprland_windows.HyprlandWindowBackend()
    target = Path('/usr/bin/kitty')
    window = VerifiedWindow(0xABC, 42, 321, 0)
    calls = []
    monkeypatch.setattr(backend, 'inspect', lambda _: ApplicationState('visible_window', windows=(window,)))
    monkeypatch.setattr(hyprland_windows, '_ipc', lambda *args: calls.append(args)
                        or (b'{"tag":"v0.55.1"}' if args == ('-j', 'version') else b'ok'))
    monkeypatch.setattr(backend, 'is_active', lambda *_: False)
    assert backend.operate(target, window, '', 0, 'focus') == 'foreground_denied'
    assert calls == [('-j', 'version'), ('dispatch', 'hl.dsp.focus({ window = "address:0xabc" })')]
    assert backend.operate(target, VerifiedWindow(0xABC, 42, 322, 0), '', 0, 'focus') == 'stale'
    assert len(calls) == 2


def test_secret_service_never_puts_token_in_command_line(monkeypatch):
    calls = []
    monkeypatch.setattr(secret_store.subprocess, 'run',
                        lambda args, **kwargs: calls.append((args, kwargs)) or type('Result', (), {'stdout': b'my-test-token\n'})())
    reference = secret_store.protect('my-test-token')
    assert secret_store.unprotect(reference) == 'my-test-token'
    assert calls[0][1]['input'] == b'my-test-token'
    assert all('my-test-token' not in arg for args, _ in calls for arg in args)
    with pytest.raises(OSError):
        secret_store.unprotect('arbitrary plaintext')
