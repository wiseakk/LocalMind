"""Exact window selection tests; no personal windows are activated/closed."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock

import pytest

from localmind.apps import AppError
from localmind.window_tools import AppTarget, NativeWindowBackend, WindowTools
from localmind.windows_state import ApplicationState, VerifiedWindow
from localmind import window_tools as module


class FakeWindows:
    def __init__(self):
        self.windows = [VerifiedWindow(99, 55, 123, 7, 'display only')]
        self.markers = {}
        self.operations = []
        self.focus_allowed = True
        self.close_disappears = False
        self.inspect_state = None

    def inspect(self, path):
        return ApplicationState(self.inspect_state or ('visible_window' if self.windows else 'absent'),
                                ((55, 123),), tuple(self.windows))

    def operate(self, path, expected, key, marker, operation):
        self.operations.append(operation)
        identity = lambda item: (item.hwnd, item.pid, item.created, item.thread_id)
        current = next((item for item in self.windows if identity(item) == identity(expected)), None)
        if current is None:
            return 'stale'
        if operation == 'stamp':
            self.markers[expected.hwnd] = marker
            return 'stamped'
        if self.markers.get(expected.hwnd) != marker:
            return 'stale'
        if operation == 'verify':
            return 'verified'
        if operation == 'release':
            self.markers.pop(expected.hwnd, None)
            return 'released'
        if operation == 'focus':
            return 'focused' if self.focus_allowed else 'foreground_denied'
        if operation == 'close':
            if self.close_disappears:
                self.windows.remove(current)
            return 'close_requested'
        raise AssertionError(operation)


@pytest.fixture
def tools(tmp_path):
    path = tmp_path / 'calc.exe'
    path.touch()
    backend = FakeWindows()
    permission = {'allowed': True, 'fingerprint': 'first'}

    @contextmanager
    def target_provider(app_id):
        if not permission['allowed'] or app_id != 'calculator':
            raise AppError('permission missing')
        yield AppTarget(app_id, 'Calculator', path, permission['fingerprint'], safe_close=True)

    result = WindowTools(backend=backend, target_provider=target_provider,
                         app_ids=lambda: ['calculator'])
    return result, backend, permission


def selected(tools):
    result = tools.list_running()
    assert result.success
    return result.data['windows'][0]['window_id']


def test_window_ids_are_opaque_and_title_never_selects(tools):
    service, backend, _ = tools
    key = selected(service)
    assert key.startswith('win-') and '99' != key
    assert service.focus_window('display only').execution_status == 'stale_target'
    assert service.focus_window(key).observed_state == 'foreground_window'


def test_policy_change_invalidates_window_and_denies_close_independently(tools):
    from localmind.personal_permissions import PersonalMode
    service, backend, _ = tools
    policy = PersonalMode()
    service._policy = policy
    old_key = selected(service)
    policy.set_app_permission(('calculator',), 'close', False)
    assert service.focus_window(old_key).execution_status == 'stale_target'
    key = selected(service)
    assert service.focus_window(key).success
    assert not service.close_window_safely(key).success
    assert 'close' not in backend.operations


def test_read_only_selection_returns_verified_app_and_window_without_mutation(tools):
    service, backend, _ = tools
    key = selected(service)
    result = service.verify_selection(key)
    assert result.success and result.observed_state == 'verified_window'
    assert result.data['app_id'] == 'calculator' and result.data['window_id'] == key
    assert 'focus' not in backend.operations and 'close' not in backend.operations


@pytest.mark.parametrize('change', ['allowed', 'fingerprint', 'marker'])
def test_read_only_selection_revalidates_grants_and_marker(tools, change):
    service, backend, permission = tools
    key = selected(service)
    if change == 'marker':
        backend.markers.clear()
    else:
        permission[change] = False if change == 'allowed' else 'replacement'
    assert not service.verify_selection(key).success
    assert 'focus' not in backend.operations and 'close' not in backend.operations


def test_list_running_uses_human_application_names(tools):
    service, backend, _ = tools
    result = service.list_running()
    assert 'Calculator' in result.status_text
    assert backend.windows[0].title not in result.status_text


def test_unavailable_verify_does_not_refresh_old_selection(tools):
    service, backend, _ = tools
    old_key = selected(service)
    original = backend.operate
    backend.operate = lambda path, native, key, marker, operation: ('unavailable' if operation == 'verify' else
                                                                original(path, native, key, marker, operation))
    assert selected(service) != old_key


def test_running_results_have_a_global_window_cap(tools):
    service, backend, _ = tools
    original_provider = service.target_provider

    @contextmanager
    def app_target(app_id):
        with original_provider('calculator') as app:
            yield replace(app, id=app_id, path=Path(app_id + '.exe'))

    service.target_provider = app_target
    service.app_ids = lambda: ['first', 'second', 'third']
    backend.windows = [VerifiedWindow(100 + i, 55, 123, 7) for i in range(32)]
    result = service.list_running()
    assert len(result.data['windows']) == 64
    assert result.data['truncated'] is True
    assert 'часть окон' in result.status_text
    assert backend.operations.count('stamp') == 64


def test_duplicate_catalog_and_builtin_images_do_not_invalidate_listed_ids(tools):
    service, backend, _ = tools
    provider = service.target_provider

    @contextmanager
    def same_image(app_id):
        with provider('calculator') as app:
            yield replace(app, id=app_id)

    service.target_provider = same_image
    service.app_ids = lambda: ['catalog-id', 'calculator']
    result = service.list_running()
    assert len(result.data['windows']) == 1
    assert service.verify_selection(result.data['windows'][0]['window_id']).success


@pytest.mark.parametrize('change', ['pid', 'created', 'thread_id', 'hwnd', 'same_process_reuse'])
def test_reused_or_changed_native_identity_never_receives_action(tools, change):
    service, backend, _ = tools
    key = selected(service)
    if change == 'same_process_reuse':
        backend.markers.clear()  # Destroyed HWND loses the native property.
    else:
        backend.windows = [replace(backend.windows[0], **{change: 555})]
    assert service.focus_window(key).execution_status == 'stale_target'
    assert service.close_window_safely(key).success is False
    assert 'close' not in backend.operations


@pytest.mark.parametrize('change', ['allowed', 'fingerprint'])
def test_revocation_and_binary_replacement_cancel_selection(tools, change):
    service, backend, permission = tools
    key = selected(service)
    permission[change] = False if change == 'allowed' else 'changed'
    assert not service.focus_window(key).success
    assert not service.close_window_safely(key).success
    assert not any(item in ('focus', 'close') for item in backend.operations)


def test_title_change_does_not_change_authority(tools):
    service, backend, _ = tools
    key = selected(service)
    backend.windows = [replace(backend.windows[0], title='new untrusted title')]
    assert selected(service) == key
    assert service.focus_window(key).success


def test_ambiguous_windows_require_exact_selection(tools):
    service, backend, _ = tools
    backend.windows.append(VerifiedWindow(100, 55, 123, 7, 'other window'))
    key, error = service.select_app_window('calculator')
    assert key is None and error.execution_status == 'ambiguous'
    assert not any(item in ('focus', 'close') for item in backend.operations)


def test_foreground_failure_is_not_reported_as_focused(tools):
    service, backend, _ = tools
    key = selected(service)
    backend.focus_allowed = False
    result = service.focus_window(key)
    assert not result.success and result.observed_state is None
    assert result.execution_status == 'activation_denied'


def test_app_focus_waits_for_delayed_window_and_handles_existing_instance(tools, monkeypatch):
    service, backend, _ = tools
    window = backend.windows.pop()
    def appear(seconds):
        backend.windows.append(window)
    monkeypatch.setattr(module.time, 'sleep', appear)
    result = service.focus_app('calculator')
    assert result.success and result.observed_state == 'foreground_window'
    assert backend.operations.count('focus') == 1


def test_app_focus_reports_timeout_inspection_failure_and_ambiguity(tools):
    service, backend, _ = tools
    native = backend.windows.pop()
    assert service.focus_app('calculator', timeout=0).execution_status == 'window_timeout'
    backend.inspect_state = 'unavailable'
    assert service.focus_app('calculator').execution_status == 'inspection_unavailable'
    backend.inspect_state = None
    backend.windows = [native, replace(native, hwnd=100)]
    result = service.focus_app('calculator')
    assert result.execution_status == 'ambiguous' and len(result.data['windows']) == 2
    assert 'focus' not in backend.operations


def test_app_focus_revocation_and_cancellation_stop_discovery(tools, monkeypatch):
    from threading import Event
    from localmind.generation import cancellation
    service, backend, permission = tools
    backend.windows.clear()
    monkeypatch.setattr(module.time, 'sleep', lambda _: permission.update(allowed=False))
    assert service.focus_app('calculator').execution_status == 'stale_target'
    permission['allowed'] = True
    event = Event(); event.set(); token = cancellation.set(event)
    try:
        with pytest.raises(ValueError):
            service.focus_app('calculator')
    finally:
        cancellation.reset(token)
    assert 'focus' not in backend.operations


def test_open_cold_launch_waits_for_verified_handoff_window(tools, monkeypatch):
    from localmind.results import ActionResult
    service, backend, _ = tools
    native = replace(backend.windows[0], pid=999, created=5678)
    backend.windows.clear()
    backend.inspect_state = 'background'
    launcher = Mock(return_value=ActionResult(True, 'open_app', 'Calculator', 'process_created'))
    monkeypatch.setattr(module.time, 'sleep', lambda _: backend.windows.append(native))
    result = service.open_app('calculator', launcher)
    launcher.assert_called_once_with('calculator')
    assert result.success and result.observed_state == 'foreground_window'
    assert result.data['launch_status'] == 'process_created'
    assert backend.operations.count('focus') == 1


def test_open_existing_window_focuses_without_launch(tools):
    service, backend, _ = tools
    launcher = Mock()
    assert service.open_app('calculator', launcher).observed_state == 'foreground_window'
    launcher.assert_not_called()


@pytest.mark.parametrize('change', ['allowed', 'fingerprint', 'cancelled'])
def test_open_does_not_focus_changed_target_after_launch(tools, change):
    from localmind.results import ActionResult
    from localmind.generation import cancellation
    from threading import Event
    service, backend, permission = tools
    native = backend.windows.pop()
    event = Event()
    token = cancellation.set(event)

    def launch(app_id):
        backend.windows.append(native)
        if change == 'cancelled':
            event.set()
        else:
            permission[change] = False if change == 'allowed' else 'new-image'
        return ActionResult(True, 'open_app', 'Calculator', 'process_created')

    try:
        if change == 'cancelled':
            with pytest.raises(ValueError):
                service.open_app('calculator', launch)
        else:
            result = service.open_app('calculator', launch)
            assert result.success and result.execution_status == 'process_created'
            assert result.data['activation_status'] in ('permission_required', 'stale_target')
            assert not result.data['window_activated']
    finally:
        cancellation.reset(token)
    assert 'focus' not in backend.operations


def test_open_foreground_denial_preserves_successful_launch(tools):
    from localmind.results import ActionResult
    service, backend, _ = tools
    native = backend.windows.pop()
    backend.focus_allowed = False

    def launch(app_id):
        backend.windows.append(native)
        return ActionResult(True, 'open_app', 'Calculator', 'process_created')

    result = service.open_app('calculator', launch)
    assert result.success and result.execution_status == 'process_created'
    assert result.data['launch_status'] == 'process_created'
    assert result.data['process_created'] and result.data['process_running']
    assert result.data['window_found'] and not result.data['window_activated']
    assert result.data['activation_status'] == 'activation_denied'
    assert result.observed_state == 'visible_window' and 'панель задач' in result.status_text


def test_open_existing_window_activation_denial_does_not_spawn(tools):
    service, backend, _ = tools
    backend.focus_allowed = False
    launcher = Mock()
    result = service.open_app('calculator', launcher)
    launcher.assert_not_called()
    assert result.success and result.execution_status == 'already_running'
    assert result.observed_state == 'visible_window'
    assert result.data['window_found'] and not result.data['window_activated']
    assert result.data['process_created'] is False


def test_open_window_timeout_preserves_launch_and_reports_unknown_process(tools, monkeypatch):
    from localmind.results import ActionResult, refused
    service, backend, _ = tools
    backend.windows.clear()
    monkeypatch.setattr(service, 'focus_app', lambda *a, **k: refused('apps.focus', 'calculator', 'Окно не найдено.', status='window_timeout'))
    result = service.open_app('calculator', lambda app: ActionResult(True, 'open_app', app, 'process_created', status_text='Запуск начат.'))
    assert result.success and result.execution_status == 'process_created'
    assert result.data['process_created'] and result.data['window_found'] is False
    assert result.data['process_running'] is None and not result.data['window_activated']


def test_steam_opens_verified_child_window_without_relaunch(tmp_path):
    client = tmp_path/'steam.exe'
    helper = tmp_path/'steamwebhelper.exe'
    backend = FakeWindows()
    backend.inspect = lambda path: (ApplicationState('background', ((41, 100),)) if path == client else
                                    ApplicationState('visible_window', ((55, 123),), tuple(backend.windows)))
    backend.child_of = Mock(return_value=True)
    operate = Mock(wraps=backend.operate)
    backend.operate = operate
    @contextmanager
    def provider(app_id):
        yield AppTarget(app_id, 'Steam', client, 'client-fingerprint', companions=((helper, (1, 2, 3, 4)),))
    service = WindowTools(backend=backend, target_provider=provider, app_ids=lambda: ['steam'])
    launcher = Mock()
    result = service.open_app('steam', launcher)
    launcher.assert_not_called()
    assert result.observed_state == 'foreground_window' and result.data['window_found'] and result.data['window_activated']
    assert all(call.args[0] == helper for call in operate.call_args_list)
    backend.child_of.return_value = False
    assert service.focus_window(result.data['window_id']).execution_status == 'stale_target'
    assert not service.list_running('steam').data['windows']
    assert operate.call_count == 2  # stamp and focus only


def test_open_ambiguity_and_inspection_failure_never_launch(tools):
    service, backend, _ = tools
    launcher = Mock()
    backend.windows.append(replace(backend.windows[0], hwnd=100))
    assert service.open_app('calculator', launcher).execution_status == 'ambiguous'
    backend.inspect_state = 'unavailable'
    assert not service.open_app('calculator', launcher).success
    launcher.assert_not_called()


def test_accepted_close_is_not_observed_close_and_never_repeated(tools):
    service, backend, _ = tools
    key = selected(service)
    result = service.close_window_safely(key)
    assert result.success and result.execution_status == 'request_accepted'
    assert result.observed_state is None
    assert service.close_window_safely(key).execution_status == 'close_pending'
    assert backend.operations.count('close') == 1


def test_concurrent_close_posts_once_per_selection(tools):
    service, backend, _ = tools
    key = selected(service)
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda _: service.close_window_safely(key), range(12)))
    assert sum(result.execution_status == 'request_accepted' for result in results) == 1
    assert backend.operations.count('close') == 1


def test_disappeared_exact_window_is_observed_closed(tools):
    service, backend, _ = tools
    key = selected(service)
    backend.close_disappears = True
    result = service.close_window_safely(key)
    assert result.success and result.observed_state == 'window_closed'


def test_unknown_post_close_inspection_never_claims_closure(tools):
    service, backend, _ = tools
    key = selected(service)
    backend.close_disappears, backend.inspect_state = True, 'unavailable'
    result = service.close_window_safely(key)
    assert result.success and result.observed_state is None


def test_document_apps_are_not_closed_without_reliable_data_safety(tools):
    service, backend, _ = tools
    provider = service.target_provider

    @contextmanager
    def document_target(app_id):
        with provider(app_id) as target:
            yield replace(target, path=Path('Obsidian.exe'), safe_close=False)

    service.target_provider = document_target
    key = selected(service)
    result = service.close_window_safely(key)
    assert not result.success and result.execution_status == 'unsupported_safe_close'
    assert 'close' not in backend.operations


def test_editor_renamed_calc_does_not_gain_safe_close(tools):
    service, backend, _ = tools
    provider = service.target_provider

    @contextmanager
    def renamed_editor(app_id):
        with provider('calculator') as target:
            yield replace(target, id='editor', name='Editor renamed calc.exe', safe_close=False)

    service.target_provider = renamed_editor
    result = service.list_running()
    assert result.data['windows'][0]['close_supported'] is False
    key = result.data['windows'][0]['window_id']
    assert service.close_window_safely(key).execution_status == 'unsupported_safe_close'
    assert 'close' not in backend.operations


def test_expiry_and_capacity_are_bounded(tools):
    service, backend, _ = tools
    now = [0]
    service.clock, service.ttl, service.capacity = lambda: now[0], 5, 1
    key = selected(service)
    backend.windows.append(VerifiedWindow(100, 55, 123, 7))
    assert len(service.list_running().data['windows']) == 1
    now[0] = 6
    assert service.focus_window(key).execution_status == 'stale_target'
    assert len(service._selections) == 0
    assert backend.operations.count('release') == 1


def test_unknown_inspection_is_not_absence(tools):
    service, backend, _ = tools
    backend.windows, backend.inspect_state = [], 'unavailable'
    result = service.list_running()
    assert not result.success and result.data['unavailable_apps'] == ['calculator']


def test_partial_window_verification_does_not_establish_unique_target(tools):
    service, backend, _ = tools
    service.capacity = 1
    backend.windows.append(VerifiedWindow(100, 55, 123, 7))
    key, error = service.select_app_window('calculator')
    assert key is None and error is not None
    assert 'focus' not in backend.operations


def test_shutdown_releases_only_owned_markers(tools):
    service, backend, _ = tools
    selected(service)
    service.close()
    assert backend.markers == {} and service._selections == {}
    assert backend.operations.count('release') == 1


@pytest.mark.parametrize('invalid', [None, {}, [], 99, 'a' * 81])
def test_invalid_window_arguments_fail_without_native_operation(tools, invalid):
    service, backend, _ = tools
    assert not service.focus_window(invalid).success
    assert not service.close_window_safely(invalid).success
    assert backend.operations == []


@pytest.mark.skipif(module.os.name != 'nt', reason='Windows ABI')
def test_native_operation_requires_marker_before_focus_or_close(monkeypatch):
    user = Mock()
    user.GetPropW.return_value = None
    monkeypatch.setattr(module, '_inspect_windows', lambda target, on_verified:
                        on_verified(user, (VerifiedWindow(99, 55, 123, 7),)))
    backend = NativeWindowBackend()
    for operation in ('focus', 'close'):
        assert backend.operate(Path('test.exe'), VerifiedWindow(99, 55, 123, 7), 'property', 42, operation) == 'stale'
    user.SetForegroundWindow.assert_not_called()
    user.PostMessageW.assert_not_called()


@pytest.fixture
def native_focus(monkeypatch):
    """Exercise the production callback with a fake Win32 ABI, not an OS claim."""
    native = VerifiedWindow(0x100000063, 55, 123, 7)
    user = Mock()
    user.GetPropW.return_value = 42
    user.IsWindow.return_value = True
    user.IsIconic.return_value = False
    user.GetForegroundWindow.return_value = native.hwnd

    def ownership(hwnd, pid):
        pid._obj.value = native.pid
        return native.thread_id

    user.GetWindowThreadProcessId.side_effect = ownership
    monkeypatch.setattr(module, '_inspect_windows', lambda target, on_verified:
                        on_verified(user, (native,)))
    # A fake clock makes denial/restore timeouts deterministic and fast.
    now = [0.0]
    monkeypatch.setattr(module.time, 'monotonic', lambda: now[0])
    monkeypatch.setattr(module.time, 'sleep', lambda seconds: now.__setitem__(0, now[0] + seconds))
    return user, native, lambda: NativeWindowBackend().operate(
        Path('test.exe'), native, 'property', 42, 'focus')


@pytest.mark.skipif(module.os.name != 'nt', reason='Windows ABI')
def test_native_focus_success_requires_observed_exact_64bit_hwnd(native_focus):
    user, native, focus = native_focus
    user.SetForegroundWindow.return_value = False
    assert focus() == 'focused'  # Already foreground is observed success.
    user.SetForegroundWindow.assert_called_once_with(native.hwnd)
    assert user.GetForegroundWindow.restype is module.w.HWND


@pytest.mark.skipif(module.os.name != 'nt', reason='Windows ABI')
def test_native_success_return_without_foreground_equality_is_denied(native_focus):
    user, native, focus = native_focus
    user.SetForegroundWindow.return_value = True
    user.GetForegroundWindow.return_value = native.hwnd + 1
    assert focus() == 'foreground_denied'


@pytest.mark.skipif(module.os.name != 'nt', reason='Windows ABI')
def test_native_focus_restores_before_activation(native_focus):
    user, native, focus = native_focus
    minimized = [True]
    user.IsIconic.side_effect = lambda hwnd: minimized[0]
    user.ShowWindowAsync.side_effect = lambda hwnd, state: minimized.__setitem__(0, False) or True
    assert focus() == 'focused'
    user.ShowWindowAsync.assert_called_once_with(native.hwnd, 9)
    assert user.mock_calls.index(('ShowWindowAsync', (native.hwnd, 9), {})) < user.mock_calls.index(
        ('SetForegroundWindow', (native.hwnd,), {}))


@pytest.mark.skipif(module.os.name != 'nt', reason='Windows ABI')
def test_native_restore_timeout_does_not_report_focus(native_focus):
    user, native, focus = native_focus
    user.IsIconic.return_value = True
    assert focus() == 'restore_pending'
    user.SetForegroundWindow.assert_not_called()


@pytest.mark.skipif(module.os.name != 'nt', reason='Windows ABI')
def test_native_recycled_hwnd_after_restore_never_activated(native_focus):
    user, native, focus = native_focus
    user.IsIconic.return_value = True

    def recycled(hwnd, state):
        user.GetPropW.return_value = None
        user.IsIconic.return_value = False
        return True

    user.ShowWindowAsync.side_effect = recycled
    assert focus() == 'stale'
    user.SetForegroundWindow.assert_not_called()


@pytest.mark.skipif(module.os.name != 'nt', reason='Windows ABI')
def test_native_destroyed_hwnd_cannot_be_observed_success(native_focus):
    user, native, focus = native_focus

    def destroyed(hwnd):
        user.GetPropW.return_value = None
        return True

    user.SetForegroundWindow.side_effect = destroyed
    assert focus() == 'stale'


@pytest.mark.skipif(module.os.name != 'nt', reason='Windows ABI')
def test_native_cancelled_restore_does_not_activate(native_focus):
    from threading import Event
    from localmind.generation import cancellation
    user, native, focus = native_focus
    event = Event()
    user.IsIconic.return_value = True
    user.ShowWindowAsync.side_effect = lambda hwnd, state: event.set() or True
    token = cancellation.set(event)
    try:
        with pytest.raises(ValueError):
            focus()
    finally:
        cancellation.reset(token)
    user.SetForegroundWindow.assert_not_called()


def test_restore_pending_has_honest_manual_fallback(tools):
    service, backend, _ = tools
    key = selected(service)
    original = backend.operate
    backend.operate = lambda path, native, key, marker, operation: (
        'restore_pending' if operation == 'focus' else original(path, native, key, marker, operation))
    result = service.focus_window(key)
    assert not result.success and result.observed_state is None
    assert result.execution_status == 'restore_pending' and 'панель задач' in str(result)
