"""Shell policy and lifecycle tests; these do not launch Chromium or record audio."""
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

pytest.importorskip('PySide6')
from PySide6.QtCore import QUrl, Qt
from PySide6.QtWebEngineCore import QWebEnginePage

from localmind import desktop_shell as shell


@pytest.mark.parametrize('address,allowed', [
    ('http://127.0.0.1:8765', True),
    ('http://127.0.0.1:8765/?tab=settings', True),
    ('http://127.0.0.1:8765/assets/app.js', True),
    ('http://127.0.0.1:8766/', False),
    ('https://127.0.0.1:8765/', False),
    ('http://localhost:8765/', False),
    ('http://127.0.0.1.evil.invalid:8765/', False),
    ('http://127.0.0.1:8765@evil.invalid/', False),
    ('http://user:password@127.0.0.1:8765/', False),
    ('file:///C:/Windows/win.ini', False),
    ('javascript:alert(1)', False),
    ('data:text/html,LocalMind', False),
])
def test_shell_navigation_accepts_only_its_fixed_local_origin(address, allowed):
    url = QUrl(address)
    assert shell.local_url(url, 8765) is allowed
    page = SimpleNamespace(port=8765)
    assert shell.LocalPage.acceptNavigationRequest(page, url, None, True) is allowed


def test_popup_creation_never_creates_an_external_browser():
    assert shell.LocalPage.createWindow(None, None) is None


def permission_target(closing=False):
    return SimpleNamespace(origin=QUrl('http://127.0.0.1:8765'), closing=closing,
                           page=SimpleNamespace(setFeaturePermission=Mock()))


@pytest.mark.parametrize('address,feature,closing', [
    ('http://evil.invalid/', QWebEnginePage.Feature.MediaAudioCapture, False),
    ('http://127.0.0.1:8766/', QWebEnginePage.Feature.MediaAudioCapture, False),
    ('http://user@127.0.0.1:8765/', QWebEnginePage.Feature.MediaAudioCapture, False),
    ('http://127.0.0.1:8765/api/', QWebEnginePage.Feature.MediaAudioCapture, False),
    ('http://127.0.0.1:8765/', QWebEnginePage.Feature.MediaVideoCapture, False),
    ('http://127.0.0.1:8765/', QWebEnginePage.Feature.MediaAudioVideoCapture, False),
    ('http://127.0.0.1:8765/', QWebEnginePage.Feature.MediaAudioCapture, True),
])
def test_disallowed_permissions_never_prompt_or_grant(monkeypatch, address, feature, closing):
    question = Mock(side_effect=AssertionError('Unexpected permission prompt'))
    monkeypatch.setattr(shell.QMessageBox, 'question', question)
    target = permission_target(closing)
    url = QUrl(address)
    shell.DesktopWindow.permission(target, url, feature)
    question.assert_not_called()
    target.page.setFeaturePermission.assert_called_once_with(
        url, feature, QWebEnginePage.PermissionPolicy.PermissionDeniedByUser)


@pytest.mark.parametrize('answer,policy', [
    ('Yes', QWebEnginePage.PermissionPolicy.PermissionGrantedByUser),
    ('No', QWebEnginePage.PermissionPolicy.PermissionDeniedByUser),
])
def test_local_microphone_requires_an_explicit_yes_with_no_as_default(monkeypatch, answer, policy):
    question = Mock(return_value=getattr(shell.QMessageBox.StandardButton, answer))
    monkeypatch.setattr(shell.QMessageBox, 'question', question)
    target = permission_target()
    url = QUrl('http://127.0.0.1:8765/')
    shell.DesktopWindow.permission(target, url, QWebEnginePage.Feature.MediaAudioCapture)
    assert question.call_args.args[-1] == shell.QMessageBox.StandardButton.No
    target.page.setFeaturePermission.assert_called_once_with(
        url, QWebEnginePage.Feature.MediaAudioCapture, policy)


def test_tray_restore_preserves_maximized_state():
    target = SimpleNamespace(isMinimized=lambda: True,
        windowState=lambda: Qt.WindowState.WindowMaximized | Qt.WindowState.WindowMinimized,
        setWindowState=Mock(), show=Mock(), raise_=Mock(), activateWindow=Mock())
    shell.DesktopWindow.open_window(target)
    target.setWindowState.assert_called_once_with(Qt.WindowState.WindowMaximized)
    target.show.assert_called_once_with()
    target.raise_.assert_called_once_with()


def test_load_error_uses_native_recovery_without_raw_chromium_error_or_url():
    target = SimpleNamespace(closing=False, load_timeout=SimpleNamespace(stop=Mock()),
        recovery_title=SimpleNamespace(setText=Mock()), recovery_message=SimpleNamespace(setText=Mock()),
        retry=SimpleNamespace(show=Mock()), stack=SimpleNamespace(setCurrentWidget=Mock()), recovery=object())
    shell.DesktopWindow.failed(target)
    target.stack.setCurrentWidget.assert_called_once_with(target.recovery)
    target.retry.show.assert_called_once_with()
    text = target.recovery_message.setText.call_args.args[0]
    assert 'http' not in text and 'chrome' not in text.lower()
    assert 'сохранятся' in text


def test_load_completion_ignores_external_origin_and_uses_recovery():
    target = SimpleNamespace(load_timeout=SimpleNamespace(stop=Mock()),
        page=SimpleNamespace(url=lambda: QUrl('http://evil.invalid/')),
        origin=QUrl('http://127.0.0.1:8765'), failed=Mock(),
        stack=SimpleNamespace(setCurrentWidget=Mock()), view=object(), sync_theme=Mock())
    shell.DesktopWindow.loaded(target, True)
    target.failed.assert_called_once_with()
    target.stack.setCurrentWidget.assert_not_called()
    target.sync_theme.assert_not_called()


def test_theme_sync_only_reads_fixed_enum_and_stops_on_close():
    view = object()
    target = SimpleNamespace(closing=False, stack=SimpleNamespace(currentWidget=lambda: view),
        view=view, page=SimpleNamespace(runJavaScript=Mock()), apply_theme=Mock())
    shell.DesktopWindow.sync_theme(target)
    target.page.runJavaScript.assert_called_once_with('document.documentElement.dataset.theme', target.apply_theme)
    target.closing = True
    target.page.runJavaScript.reset_mock()
    shell.DesktopWindow.sync_theme(target)
    target.page.runJavaScript.assert_not_called()


def test_invalid_theme_cannot_reach_native_calls():
    # No QApplication or Chromium needed: invalid values must short-circuit.
    target = SimpleNamespace(closing=False, theme='dark')
    for value in ('file:///secret', 'light; process.start()', None, {'theme': 'light'}):
        shell.DesktopWindow.apply_theme(target, value)
    assert target.theme == 'dark'


def test_save_preferences_keeps_normal_bounds_while_minimized_and_maximized(monkeypatch, tmp_path):
    from PySide6.QtCore import QRect
    write = Mock()
    monkeypatch.setattr(shell, 'write_state', write)
    target = SimpleNamespace(normalGeometry=lambda: QRect(-1500, 120, 1100, 760),
        windowState=lambda: Qt.WindowState.WindowMaximized | Qt.WindowState.WindowMinimized,
        state_path=tmp_path / 'config/window.json', theme='light')
    shell.DesktopWindow.save_preferences(target)
    write.assert_called_once_with(target.state_path, (-1500, 120, 1100, 760), True, 'light')


@pytest.mark.parametrize('error', [PermissionError('read-only'), ValueError('linked path')])
def test_unwritable_preferences_do_not_prevent_closing(monkeypatch, tmp_path, error):
    from PySide6.QtCore import QRect
    write = Mock(side_effect=error)
    monkeypatch.setattr(shell, 'write_state', write)
    target = SimpleNamespace(normalGeometry=lambda: QRect(40, 40, 1100, 760),
        windowState=lambda: Qt.WindowState.WindowNoState,
        state_path=tmp_path / 'window.json', theme='dark')
    shell.DesktopWindow.save_preferences(target)
    write.assert_called_once()


def test_app_icon_has_small_and_large_windows_sizes():
    from PIL import Image
    with Image.open(shell.ICON_PATH) as icon:
        assert icon.format == 'ICO'
        assert {(16, 16), (20, 20), (24, 24), (32, 32), (40, 40), (48, 48), (256, 256)} <= icon.ico.sizes()


def test_first_window_uses_desktop_default_in_primary_screen_coordinates(monkeypatch):
    from PySide6.QtCore import QRect
    monkeypatch.setattr(shell.QApplication, 'screens', lambda: [
        SimpleNamespace(availableGeometry=lambda: QRect(-1920, 0, 1920, 1040))])
    target = SimpleNamespace(normalGeometry=Mock(side_effect=AssertionError('Uninitialized window bounds')),
        isMaximized=lambda: False, setGeometry=Mock())
    shell.DesktopWindow.fit_to_screens(target, None, initial=True)
    target.setGeometry.assert_called_once_with(-1880, 40, 1280, 900)
    target.normalGeometry.assert_not_called()


def test_disconnected_monitor_refits_live_normal_geometry_and_restores_maximize(monkeypatch):
    from PySide6.QtCore import QRect
    monkeypatch.setattr(shell.QApplication, 'screens', lambda: [
        SimpleNamespace(availableGeometry=lambda: QRect(0, 0, 1920, 1040))])
    calls = []
    target = SimpleNamespace(normalGeometry=lambda: QRect(3000, 80, 1100, 760),
        isMaximized=lambda: True,
        showNormal=lambda: calls.append('normal'),
        setGeometry=lambda *bounds: calls.append(bounds),
        showMaximized=lambda: calls.append('maximized'))
    shell.DesktopWindow.fit_to_screens(target)
    assert calls == ['normal', (808, 80, 1100, 760), 'maximized']
