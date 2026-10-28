"""Application idempotence tests; no real application is launched."""
from concurrent.futures import ThreadPoolExecutor
import os
from pathlib import Path
import sys
from unittest.mock import Mock

import pytest

from localmind.windows_state import ApplicationState, LaunchCoordinator, inspect_application
from localmind import windows_state


@pytest.mark.parametrize('state', ['visible_window', 'background', 'unavailable'])
def test_existing_or_uncertain_state_never_spawns(tmp_path, state):
    target = tmp_path / 'steam.exe'
    target.touch()
    spawn = Mock()
    coordinator = LaunchCoordinator(inspector=lambda _: ApplicationState(state))
    result = coordinator.launch(target, 'Steam', spawn)
    spawn.assert_not_called()
    assert result.success == (state != 'unavailable')
    assert result.observed_state == (None if state == 'unavailable' else state)


def test_concurrent_different_requests_share_inspection_spawn_lock(tmp_path):
    target = tmp_path / 'steam.exe'
    target.touch()
    process = Mock()
    process.poll.return_value = None
    spawn = Mock(return_value=process)
    coordinator = LaunchCoordinator(inspector=lambda _: ApplicationState('absent'))
    with ThreadPoolExecutor(max_workers=12) as workers:
        results = list(workers.map(lambda _: coordinator.launch(target, 'Steam', spawn), range(24)))
    assert spawn.call_count == 1
    assert sum(result.execution_status == 'process_created' for result in results) == 1
    assert sum(result.execution_status == 'launch_pending' for result in results) == 23
    assert all(result.observed_state is None for result in results)


def test_pending_owned_process_exit_handoff_grace_and_retry(tmp_path):
    target = tmp_path / 'steam.exe'
    target.touch()
    now = [100.0]
    process = Mock()
    process.poll.return_value = 0
    spawn = Mock(return_value=process)
    coordinator = LaunchCoordinator(inspector=lambda _: ApplicationState('absent'), clock=lambda: now[0])
    assert coordinator.launch(target, 'Steam', spawn).execution_status == 'process_created'
    now[0] += 14
    assert coordinator.launch(target, 'Steam', spawn).execution_status == 'launch_pending'
    now[0] += 2
    assert coordinator.launch(target, 'Steam', spawn).execution_status == 'process_created'
    assert spawn.call_count == 2


def test_failed_poll_is_uncertain_not_permission_to_launch(tmp_path):
    target = tmp_path / 'steam.exe'
    target.touch()
    process = Mock()
    process.poll.side_effect = OSError('access denied')
    spawn = Mock(return_value=process)
    coordinator = LaunchCoordinator(inspector=lambda _: ApplicationState('absent'), handoff_grace=0)
    coordinator.launch(target, 'Steam', spawn)
    assert coordinator.launch(target, 'Steam', spawn).execution_status == 'launch_pending'
    assert spawn.call_count == 1


def test_spawn_failure_does_not_cache_success(tmp_path):
    target = tmp_path / 'steam.exe'
    target.touch()
    spawn = Mock(side_effect=OSError('refused'))
    coordinator = LaunchCoordinator(inspector=lambda _: ApplicationState('absent'))
    for _ in range(2):
        with pytest.raises(OSError):
            coordinator.launch(target, 'Steam', spawn)
    assert spawn.call_count == 2


def test_different_images_are_independent_even_with_same_basename(tmp_path):
    paths = []
    for directory in ('first', 'second'):
        folder = tmp_path / directory
        folder.mkdir()
        target = folder / 'steam.exe'
        target.touch()
        paths.append(target)
    spawn = Mock(return_value=Mock(poll=Mock(return_value=None)))
    coordinator = LaunchCoordinator(inspector=lambda _: ApplicationState('absent'))
    for target in paths:
        assert coordinator.launch(target, 'Steam', spawn).execution_status == 'process_created'
    assert spawn.call_count == 2


@pytest.mark.skipif(os.name != 'nt', reason='Native Windows inspection')
def test_native_current_python_identity_without_launch():
    # Windows venv python.exe is a launcher; the interpreter image is the base.
    state = inspect_application(Path(getattr(sys, '_base_executable', sys.executable)))
    # Restricted desktops may deny EnumWindows. They must never look absent.
    assert state.state in ('visible_window', 'background', 'unavailable')
    assert any(pid == os.getpid() and created > 0 for pid, created in state.processes), (state, os.getpid(), sys.executable)


@pytest.mark.skipif(os.name != 'nt', reason='Native Windows inspection')
def test_native_absent_unique_image(tmp_path):
    target = tmp_path / 'localmind-not-running-probe.exe'
    target.touch()
    assert inspect_application(target).state == 'absent'


@pytest.mark.skipif(os.name != 'nt', reason='Windows ABI simulation')
@pytest.mark.parametrize('case, expected', [
    ('visible', 'visible_window'), ('background', 'background'),
    ('same_name_other_image', 'absent'), ('other_user', 'absent'),
    ('other_session', 'absent'), ('access_denied', 'unavailable'),
    ('exited', 'absent'), ('window_inspection_denied', 'unavailable'),
    ('ownership_changed', 'absent'), ('session_changed', 'absent'),
    ('exit_during_windows', 'absent'),
])
def test_native_identity_and_window_boundaries(monkeypatch, tmp_path, case, expected):
    import ctypes
    from ctypes import wintypes as w

    target = tmp_path / 'steam.exe'
    target.touch()
    other = tmp_path / 'other'
    other.mkdir()
    alternate = other / 'steam.exe'
    alternate.touch()
    libraries = {name: Mock() for name in ('kernel32', 'advapi32', 'wtsapi32', 'user32')}
    monkeypatch.setattr(ctypes, 'WinDLL', lambda name, **_: libraries[name])
    kernel, security, terminal, user = (libraries[name] for name in libraries)
    kernel.GetCurrentProcess.return_value = 1

    def set_session(pid, output):
        ctypes.cast(output, ctypes.POINTER(w.DWORD))[0] = 2 if pid == 55 and case == 'session_changed' else 1
        return 1

    def set_token(process, access, output):
        ctypes.cast(output, ctypes.POINTER(w.HANDLE))[0] = 3 if process == 88 else 2
        return 1

    def token_info(token, kind, buffer, size, length):
        ctypes.cast(length, ctypes.POINTER(w.DWORD))[0] = 16
        if buffer is not None:
            sid = 9 if getattr(token, 'value', token) == 3 and case == 'ownership_changed' else 7
            ctypes.cast(buffer, ctypes.POINTER(ctypes.c_void_p))[0] = sid
        return 1

    kernel.ProcessIdToSessionId.side_effect = set_session
    security.OpenProcessToken.side_effect = set_token
    security.GetTokenInformation.side_effect = token_info
    security.EqualSid.side_effect = lambda left, right: int(left == right)
    rows = (windows_state._WTSProcess * 1)()
    rows[0].SessionId = 2 if case == 'other_session' else 1
    rows[0].ProcessId = 55
    rows[0].pProcessName = 'steam.exe'
    rows[0].pUserSid = 9 if case == 'other_user' else 7

    def enumerate_processes(server, reserved, version, output, count):
        ctypes.cast(output, ctypes.POINTER(ctypes.POINTER(windows_state._WTSProcess)))[0] = rows
        ctypes.cast(count, ctypes.POINTER(w.DWORD))[0] = 1
        return 1

    terminal.WTSEnumerateProcessesW.side_effect = enumerate_processes
    kernel.OpenProcess.return_value = 0 if case == 'access_denied' else 88

    def image_name(process, flags, image, size):
        image.value = str(alternate if case == 'same_name_other_image' else target)
        return 1

    kernel.QueryFullProcessImageNameW.side_effect = image_name

    def process_times(process, created, *rest):
        ctypes.cast(created, ctypes.POINTER(w.FILETIME))[0].dwLowDateTime = 123
        return 1

    kernel.GetProcessTimes.side_effect = process_times

    exited = [False]

    def exit_code(process, output):
        ctypes.cast(output, ctypes.POINTER(w.DWORD))[0] = 0 if case == 'exited' or exited[0] else 259
        return 1

    kernel.GetExitCodeProcess.side_effect = exit_code

    def window_pid(hwnd, output):
        ctypes.cast(output, ctypes.POINTER(w.DWORD))[0] = 55
        return 1

    user.GetWindowThreadProcessId.side_effect = window_pid
    user.IsWindowVisible.return_value = 1

    def enum_windows(callback, parameter):
        if case == 'window_inspection_denied':
            return 0
        if case == 'visible':
            assert callback(99, 0)
        if case == 'exit_during_windows':
            assert callback(99, 0)
            exited[0] = True
        return 1

    user.EnumWindows.side_effect = enum_windows
    state = windows_state._inspect_windows(target)
    assert state.state == expected
    if expected in ('visible_window', 'background'):
        assert state.processes == ((55, 123),)
    if case == 'access_denied':
        kernel.QueryFullProcessImageNameW.assert_not_called()
    if kernel.OpenProcess.return_value:
        # Native handles must close, including on failure/exit paths.
        if case not in ('other_session', 'other_user'):
            assert any(call.args == (88,) for call in kernel.CloseHandle.call_args_list)
