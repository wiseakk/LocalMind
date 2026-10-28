"""Read-only Windows process/window inspection and serialized GUI launches.

Names only select candidates. Positive identity requires the exact image path,
the current user SID and current Windows session. Uninspectable candidates are
unknown, never evidence of absence. No window activation or process termination.
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes as w
from dataclasses import dataclass
import os
from pathlib import Path
import threading
import time

from .results import ActionResult


@dataclass(frozen=True)
class VerifiedWindow:
    """Native identity, never a user/model supplied window title."""
    hwnd: int
    pid: int
    created: int
    thread_id: int
    title: str = ''


@dataclass(frozen=True)
class ApplicationState:
    state: str  # visible_window, background, absent, unavailable
    processes: tuple[tuple[int, int], ...] = ()  # PID, creation FILETIME
    windows: tuple[VerifiedWindow, ...] = ()


class _WTSProcess(ctypes.Structure):
    _fields_ = [('SessionId', w.DWORD), ('ProcessId', w.DWORD),
                ('pProcessName', w.LPWSTR), ('pUserSid', ctypes.c_void_p)]


def inspect_application(target: Path) -> ApplicationState:
    if os.name != 'nt':
        return ApplicationState('unavailable')
    try:
        return _inspect_windows(target)
    except (OSError, ValueError, AttributeError):
        return ApplicationState('unavailable')


def _inspect_windows(target: Path, on_verified=None) -> ApplicationState:
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    security = ctypes.WinDLL('advapi32', use_last_error=True)
    terminal = ctypes.WinDLL('wtsapi32', use_last_error=True)
    user = ctypes.WinDLL('user32', use_last_error=True)
    kernel.GetCurrentProcess.restype = w.HANDLE
    kernel.OpenProcess.argtypes = [w.DWORD, w.BOOL, w.DWORD]
    kernel.OpenProcess.restype = w.HANDLE
    kernel.CloseHandle.argtypes = [w.HANDLE]
    kernel.ProcessIdToSessionId.argtypes = [w.DWORD, ctypes.POINTER(w.DWORD)]
    kernel.QueryFullProcessImageNameW.argtypes = [w.HANDLE, w.DWORD, w.LPWSTR, ctypes.POINTER(w.DWORD)]
    kernel.GetProcessTimes.argtypes = [w.HANDLE] + [ctypes.POINTER(w.FILETIME)] * 4
    kernel.GetExitCodeProcess.argtypes = [w.HANDLE, ctypes.POINTER(w.DWORD)]
    security.OpenProcessToken.argtypes = [w.HANDLE, w.DWORD, ctypes.POINTER(w.HANDLE)]
    security.GetTokenInformation.argtypes = [w.HANDLE, ctypes.c_int, ctypes.c_void_p, w.DWORD, ctypes.POINTER(w.DWORD)]
    security.EqualSid.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    terminal.WTSEnumerateProcessesW.argtypes = [w.HANDLE, w.DWORD, w.DWORD,
                                              ctypes.POINTER(ctypes.POINTER(_WTSProcess)), ctypes.POINTER(w.DWORD)]
    terminal.WTSFreeMemory.argtypes = [ctypes.c_void_p]
    callback_type = ctypes.WINFUNCTYPE(w.BOOL, w.HWND, w.LPARAM)
    user.EnumWindows.argtypes = [callback_type, w.LPARAM]
    user.IsWindowVisible.argtypes = [w.HWND]
    user.GetWindowThreadProcessId.argtypes = [w.HWND, ctypes.POINTER(w.DWORD)]
    user.GetWindowTextW.argtypes = [w.HWND, w.LPWSTR, ctypes.c_int]
    session, token, needed = w.DWORD(), w.HANDLE(), w.DWORD()
    rows, count = ctypes.POINTER(_WTSProcess)(), w.DWORD()
    handles = []
    try:
        if not kernel.ProcessIdToSessionId(os.getpid(), ctypes.byref(session)):
            raise OSError('session unavailable')
        if not security.OpenProcessToken(kernel.GetCurrentProcess(), 8, ctypes.byref(token)):
            raise OSError('token unavailable')
        security.GetTokenInformation(token, 1, None, 0, ctypes.byref(needed))
        if not needed.value or needed.value > 65536:
            raise OSError('invalid token size')
        token_data = ctypes.create_string_buffer(needed.value)
        if not security.GetTokenInformation(token, 1, token_data, needed, ctypes.byref(needed)):
            raise OSError('token unavailable')
        own_sid = ctypes.cast(token_data, ctypes.POINTER(ctypes.c_void_p))[0]
        if not terminal.WTSEnumerateProcessesW(None, 0, 1, ctypes.byref(rows), ctypes.byref(count)):
            raise OSError('enumeration unavailable')
        expected = os.path.normcase(str(target.resolve(strict=True)))
        unknown = False
        identities = []
        identity_handles = {}
        for index in range(count.value):
            row = rows[index]
            if row.SessionId != session.value or not row.pProcessName:
                continue
            if row.pProcessName.casefold() != target.name.casefold():
                continue
            if not row.pUserSid:
                unknown = True
                continue
            if not security.EqualSid(row.pUserSid, own_sid):
                continue
            handle = kernel.OpenProcess(0x1000, False, row.ProcessId)
            if not handle:
                unknown = True
                continue
            handles.append(handle)
            process_session, process_token, token_size = w.DWORD(), w.HANDLE(), w.DWORD()
            try:
                if (not kernel.ProcessIdToSessionId(row.ProcessId, ctypes.byref(process_session))
                        or not security.OpenProcessToken(handle, 8, ctypes.byref(process_token))):
                    unknown = True
                    continue
                security.GetTokenInformation(process_token, 1, None, 0, ctypes.byref(token_size))
                if not token_size.value or token_size.value > 65536:
                    unknown = True
                    continue
                process_user = ctypes.create_string_buffer(token_size.value)
                if not security.GetTokenInformation(process_token, 1, process_user, token_size,
                                                     ctypes.byref(token_size)):
                    unknown = True
                    continue
                process_sid = ctypes.cast(process_user, ctypes.POINTER(ctypes.c_void_p))[0]
                if process_session.value != session.value or not security.EqualSid(process_sid, own_sid):
                    continue
            finally:
                if process_token:
                    kernel.CloseHandle(process_token)
            image, size = ctypes.create_unicode_buffer(32768), w.DWORD(32768)
            created, exited, cpu_kernel, cpu_user = (w.FILETIME() for _ in range(4))
            code = w.DWORD()
            if (not kernel.QueryFullProcessImageNameW(handle, 0, image, ctypes.byref(size))
                    or not kernel.GetProcessTimes(handle, ctypes.byref(created), ctypes.byref(exited),
                                                  ctypes.byref(cpu_kernel), ctypes.byref(cpu_user))
                    or not kernel.GetExitCodeProcess(handle, ctypes.byref(code))):
                unknown = True
                continue
            if code.value != 259:  # process exited during inspection
                continue
            try:
                actual = os.path.normcase(str(Path(image.value).resolve(strict=True)))
            except OSError:
                unknown = True
                continue
            if actual == expected:
                identities.append((row.ProcessId, created.dwLowDateTime | created.dwHighDateTime << 32))
                identity_handles[row.ProcessId] = handle
        matching_pids = {item[0] for item in identities}
        if not matching_pids:
            return ApplicationState('unavailable' if unknown else 'absent')
        visible = set()
        windows = []
        creation_by_pid = dict(identities)

        @callback_type
        def visit(hwnd, _):
            pid = w.DWORD()
            thread_id = user.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            if user.IsWindowVisible(hwnd) and thread_id:
                if pid.value in matching_pids:
                    visible.add(pid.value)
                    if len(windows) < 128:
                        title = ctypes.create_unicode_buffer(512)
                        copied = user.GetWindowTextW(hwnd, title, len(title))
                        display_title = title.value if isinstance(copied, int) and copied > 0 else ''
                        display_title = display_title.encode('utf-8', errors='replace').decode('utf-8')
                        windows.append(VerifiedWindow(int(hwnd), pid.value, creation_by_pid[pid.value],
                                                      int(thread_id), display_title))
            return True

        if not user.EnumWindows(visit, 0):
            return ApplicationState('unavailable', tuple(identities))
        # Handles remain open through EnumWindows, preventing PID recycling.
        live = set()
        for pid, handle in identity_handles.items():
            code = w.DWORD()
            if not kernel.GetExitCodeProcess(handle, ctypes.byref(code)):
                unknown = True
            elif code.value == 259:
                live.add(pid)
        identities = [item for item in identities if item[0] in live]
        visible &= live
        windows = tuple(item for item in windows if item.pid in live)
        # Native process handles remain open through the operation. The caller
        # must additionally validate its per-window marker before any mutation.
        if on_verified is not None:
            on_verified(user, windows)
        if visible:
            return ApplicationState('visible_window', tuple(identities), windows)
        if identities:
            return ApplicationState('background', tuple(identities))
        return ApplicationState('unavailable' if unknown else 'absent')
    finally:
        for handle in handles:
            kernel.CloseHandle(handle)
        if rows:
            terminal.WTSFreeMemory(rows)
        if token:
            kernel.CloseHandle(token)


class LaunchCoordinator:
    """Separate application idempotence, independent of request-id replay.

    Fixed lock stripes bound memory and cover inspection plus CreateProcess.
    Pending entries retain the owned Popen (Windows process handle), not a PID.
    """
    def __init__(self, inspector=None, clock=time.monotonic, handoff_grace=15.0):
        self.inspector = inspector or inspect_application
        self.clock, self.handoff_grace = clock, handoff_grace
        self._locks = tuple(threading.RLock() for _ in range(64))
        self._pending = tuple({} for _ in self._locks)

    def launch(self, target: Path, display_name: str, spawn) -> ActionResult:
        key = os.path.normcase(str(target.resolve(strict=True)))
        stripe = hash(key) % len(self._locks)
        with self._locks[stripe]:
            state = self.inspector(target)
            pending = self._pending[stripe]
            if state.state in ('visible_window', 'background'):
                pending.pop(key, None)
                text = (f'{display_name}: окно уже открыто.' if state.state == 'visible_window'
                        else f'{display_name} уже работает в фоне; видимое окно не обнаружено.')
                return ActionResult(True, 'open_app', display_name, 'already_running', state.state, status_text=text)
            if state.state != 'absent':
                return ActionResult(False, 'open_app', display_name, 'inspection_unavailable',
                                    error='Не удалось проверить состояние приложения; повторный запуск отменён.',
                                    status_text='Не удалось проверить состояние приложения; проверь его вручную.')
            now = self.clock()
            if key in pending:
                process, launched_at = pending[key]
                try:
                    exited = process.poll() is not None
                except OSError:
                    exited = False
                if not exited or now - launched_at < self.handoff_grace:
                    return ActionResult(True, 'open_app', display_name, 'launch_pending',
                                        status_text=f'{display_name} запускается; появление окна пока не подтверждено.')
                pending.pop(key, None)
            # Bound retained process handles. No active/pending entry is evicted.
            for old_key, (old_process, launched_at) in list(pending.items()):
                try:
                    if now - launched_at >= self.handoff_grace and old_process.poll() is not None:
                        pending.pop(old_key, None)
                except OSError:
                    pass
            if len(pending) >= 16:
                return ActionResult(False, 'open_app', display_name, 'inspection_unavailable',
                                    error='Слишком много незавершённых запусков; проверь приложения вручную.',
                                    status_text='Слишком много незавершённых запусков; проверь приложения вручную.')
            process = spawn()
            pending[key] = (process, now)
            return ActionResult(True, 'open_app', display_name, 'process_created',
                                status_text=f'Запуск {display_name} начат; появление окна пока не подтверждено.')


launch_coordinator = LaunchCoordinator()
