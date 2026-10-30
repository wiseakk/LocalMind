"""Permission-bound Windows window capabilities.

Titles are display metadata. Selection uses opaque expiring IDs, image grants,
PID creation time, session/SID, HWND/thread and an instance-specific native
window property. Windows destroys that property with the window, so a recycled
HWND in the same process cannot inherit an old selection.
"""
from __future__ import annotations

from contextlib import contextmanager, ExitStack
import ctypes
from ctypes import wintypes as w
from dataclasses import dataclass
import os
from pathlib import Path
import secrets
import threading
import time
import uuid

from .apps import AppError, _launch_guard, catalog
from .results import ActionResult, refused
from .generation import check_cancelled, cancellation
from .windows_state import VerifiedWindow, _inspect_windows, inspect_application, inspect_applications


@dataclass(frozen=True)
class AppTarget:
    id: str
    name: str
    path: Path
    fingerprint: str


@dataclass
class WindowSelection:
    id: str
    app: AppTarget
    native: VerifiedWindow
    marker: int
    expires: float
    close_requested: bool = False


class NativeWindowBackend:
    def inspect(self, target):
        return inspect_application(target)

    def inspect_many(self, targets):
        return inspect_applications(targets)

    def operate(self, target, expected, property_name, marker, operation):
        if os.name != 'nt':
            raise OSError('Windows is required')
        outcome = {'state': 'stale'}

        def verified(user, windows):
            # Title changes are harmless; native identity must still match.
            matched = next((item for item in windows if (
                item.hwnd, item.pid, item.created, item.thread_id
            ) == (expected.hwnd, expected.pid, expected.created, expected.thread_id)), None)
            if matched is None:
                return
            user.SetPropW.argtypes = [w.HWND, w.LPCWSTR, w.HANDLE]
            user.SetPropW.restype = w.BOOL
            user.GetPropW.argtypes = [w.HWND, w.LPCWSTR]
            user.GetPropW.restype = w.HANDLE
            user.RemovePropW.argtypes = [w.HWND, w.LPCWSTR]
            user.RemovePropW.restype = w.HANDLE
            user.IsWindow.argtypes = [w.HWND]
            hwnd = expected.hwnd
            if operation == 'stamp':
                outcome['state'] = 'stamped' if user.SetPropW(hwnd, property_name, marker) else 'unavailable'
                return
            if user.GetPropW(hwnd, property_name) != marker:
                return
            # Check window ownership again at the last point before dispatch.
            pid = w.DWORD()
            if (user.GetWindowThreadProcessId(hwnd, ctypes.byref(pid)) != expected.thread_id
                    or pid.value != expected.pid or not user.IsWindow(hwnd)):
                return
            if operation == 'release':
                user.RemovePropW(hwnd, property_name)
                outcome['state'] = 'released'
            elif operation == 'verify':
                outcome['state'] = 'verified'
            elif operation == 'focus':
                user.SetForegroundWindow.argtypes = [w.HWND]
                user.SetForegroundWindow.restype = w.BOOL
                user.GetForegroundWindow.restype = w.HWND
                user.IsIconic.argtypes = [w.HWND]
                user.ShowWindowAsync.argtypes = [w.HWND, ctypes.c_int]
                if user.IsIconic(hwnd):
                    user.ShowWindowAsync(hwnd, 9)  # SW_RESTORE, no input simulation
                    # ShowWindowAsync posts to another thread. Give the restore
                    # a bounded interval before observing foreground state.
                    until = time.monotonic() + .3
                    while user.IsIconic(hwnd) and time.monotonic() < until:
                        time.sleep(.02)
                user.SetForegroundWindow(hwnd)
                until = time.monotonic() + .3
                while user.GetForegroundWindow() != hwnd and time.monotonic() < until:
                    time.sleep(.02)
                observed = user.GetForegroundWindow() == hwnd and not user.IsIconic(hwnd)
                outcome['state'] = 'focused' if observed else 'foreground_denied'
            elif operation == 'close':
                user.PostMessageW.argtypes = [w.HWND, w.UINT, w.WPARAM, w.LPARAM]
                user.PostMessageW.restype = w.BOOL
                # No WM_QUIT, clicks, Enter, forced termination or save-dialog
                # automation. A successful post is only an accepted request.
                outcome['state'] = 'close_requested' if user.PostMessageW(hwnd, 0x10, 0, 0) else 'close_failed'

        _inspect_windows(target, on_verified=verified)
        return outcome['state']


class WindowTools:
    def __init__(self, *, backend=None, target_provider=None, app_ids=None,
                 clock=time.monotonic, capacity=128, ttl=900):
        self.backend = backend or NativeWindowBackend()
        self.target_provider = target_provider or self._catalog_target
        self.app_ids = app_ids or self._catalog_ids
        self.clock, self.capacity, self.ttl = clock, capacity, ttl
        self._selections: dict[str, WindowSelection] = {}
        self._lock = threading.RLock()
        self._property = 'LocalMind.Window.' + uuid.uuid4().hex
        self._builtin_resolver = None

    def configure_builtin_resolver(self, resolver):
        self._builtin_resolver = resolver

    def _catalog_ids(self):
        catalog.aliases()  # Discover once; launch permission is not inferred.
        return [item['id'] for item in catalog.entries() if item['allowed']] + ['calculator', 'notepad']

    @contextmanager
    def _catalog_target(self, app_id):
        if app_id in ('calculator', 'notepad'):
            path = self._builtin_resolver(app_id) if self._builtin_resolver else None
            if path is None:
                raise AppError('Не удалось проверить системное приложение.')
            with _launch_guard(path):
                if self._builtin_resolver(app_id) != path:
                    raise AppError('Цель системного приложения изменилась.')
                yield AppTarget(app_id, app_id, path, str(path.stat().st_mtime_ns))
            return
        with catalog._lock:
            entry = catalog._entries.get(app_id)
            if entry is None:
                raise AppError('Приложение отсутствует в каталоге.')
            if not catalog.is_allowed(app_id):
                raise AppError('Сначала разреши приложение в настройках.')
            if entry.launch_type == 'steam':
                raise AppError('Окно игры Steam ещё не связано с проверенным исполняемым файлом.')
            with _launch_guard(entry.target):
                current = catalog._revalidate(app_id)
                yield AppTarget(current.id, current.name, current.target, current.fingerprint)

    def _prune(self):
        for key, selection in list(self._selections.items()):
            if selection.expires <= self.clock():
                # Marker removal is best effort and never targets a new window.
                try:
                    with self.target_provider(selection.app.id) as current:
                        if current == selection.app:
                            self.backend.operate(current.path, selection.native, self._property, selection.marker, 'release')
                except (AppError, OSError, ValueError, AttributeError):
                    pass
                self._selections.pop(key, None)

    def _record(self, app, native):
        for record in self._selections.values():
            if record.app == app and (
                record.native.hwnd, record.native.pid, record.native.created, record.native.thread_id
            ) == (native.hwnd, native.pid, native.created, native.thread_id):
                # Confirm marker too: a recycled HWND must not refresh an ID.
                if self.backend.operate(app.path, native, self._property, record.marker, 'verify') == 'verified':
                    return record
        if len(self._selections) >= self.capacity:
            return None
        marker = secrets.randbits(ctypes.sizeof(ctypes.c_void_p) * 8 - 1) or 1
        if self.backend.operate(app.path, native, self._property, marker, 'stamp') != 'stamped':
            return None
        record = WindowSelection('win-' + uuid.uuid4().hex, app, native, marker, self.clock() + self.ttl)
        self._selections[record.id] = record
        return record

    @staticmethod
    def _public(record):
        return {'window_id': record.id, 'app_id': record.app.id, 'application': record.app.name,
                'title': record.native.title, 'close_supported': record.app.path.name.casefold() in ('calc.exe', 'calculator.exe', 'calculatorapp.exe')}

    def list_running(self, app_id=None):
        with self._lock:
            self._prune()
            windows, unknown, background = [], [], []
            all_ids = [app_id] if app_id else self.app_ids()
            ids = all_ids[:4096]
            truncated = len(all_ids) > len(ids)
            seen_paths = set()
            # Keep validated image guards through the snapshot, then stamp only
            # observed windows. Each actual mutation still checks native identity.
            with ExitStack() as guards:
                candidates = []
                for key in ids:
                    try:
                        app = guards.enter_context(self.target_provider(key))
                        image_key = os.path.normcase(str(app.path))
                        if image_key in seen_paths:
                            continue
                        seen_paths.add(image_key)
                        candidates.append((key, app))
                    except (AppError, OSError, ValueError, AttributeError):
                        unknown.append(key)
                snapshots = (self.backend.inspect_many([item.path for _, item in candidates])
                             if hasattr(self.backend, 'inspect_many') else None)
                for key, app in candidates:
                    if len(windows) >= 64:
                        truncated = True
                        break
                    try:
                        state = snapshots[app.path] if snapshots is not None else self.backend.inspect(app.path)
                        if state.state == 'unavailable':
                            unknown.append(key)
                        if state.state == 'background':
                            background.append(key)
                        truncated = truncated or len(state.windows) > 32
                        for native in state.windows[:32]:
                            if len(windows) >= 64:
                                truncated = True
                                break
                            record = self._record(app, native)
                            if record:
                                windows.append(self._public(record))
                            else:
                                unknown.append(key)
                    except (AppError, OSError, ValueError, AttributeError):
                        unknown.append(key)
            names = list(dict.fromkeys(item['application'] for item in windows))
            found_text = ('Проверенные окна: ' + ', '.join(names[:12]) + '.' if names else 'Проверенных окон не найдено.')
            return ActionResult(not unknown, 'apps.list_running', app_id,
                'observed' if not unknown else 'inspection_unavailable',
                'verified_windows' if windows else None,
                status_text=((found_text if not unknown else found_text + ' Часть приложений не удалось проверить.')
                             + (' Список ограничен; показана только часть окон.' if truncated else '')),
                data={'windows': windows, 'background_apps': background, 'unavailable_apps': sorted(set(unknown)),
                      'truncated': truncated})

    def select_app_window(self, app_id):
        result = self.list_running(app_id)
        windows = result.data['windows']
        if len(windows) != 1 or not result.success or result.data.get('truncated'):
            reason = ('У приложения несколько окон. Выбери нужное окно.' if len(windows) > 1 else
                      'Не удалось найти проверенное окно приложения. Проверь его вручную.')
            status = ('inspection_unavailable' if not result.success else 'ambiguous' if windows else 'window_pending')
            return None, ActionResult(False, 'apps.focus_window', app_id, status, error=reason,
                                      status_text=reason, data=result.data)
        return windows[0]['window_id'], None

    def focus_app(self, app_id, timeout=4.0):
        """Discover after authorization; support delayed and existing-instance windows.

        Every poll and final native operation revalidates the image grant. Never
        select by title or just the PID returned by a launcher (Electron handoff).
        """
        try:
            with self.target_provider(app_id) as target:
                original = target
        except (AppError, OSError, ValueError):
            return refused('apps.focus', app_id, 'Проверь разрешение приложения и его исполняемый файл в каталоге.', status='permission_required')
        deadline = self.clock() + min(max(timeout, 0), 5)
        while True:
            check_cancelled()
            try:
                with self.target_provider(app_id) as current:
                    if current != original:
                        return refused('apps.focus', app_id, 'Цель приложения изменилась. Выбери приложение повторно.', status='stale_target')
                    window_id, error = self.select_app_window(app_id)
            except (AppError, OSError, ValueError):
                return refused('apps.focus', app_id, 'Разрешение или цель приложения изменились.', status='stale_target')
            if window_id:
                return self.focus_window(window_id)
            if error.execution_status != 'window_pending':
                return error
            if self.clock() >= deadline:
                return refused('apps.focus', app_id, 'Проверенное окно не появилось за отведённое время. Повтори после загрузки приложения.', status='window_timeout')
            event = cancellation.get()
            if event is not None:
                event.wait(.1)
            else:
                time.sleep(.1)

    def _operate(self, window_id, operation):
        action = {'focus': 'apps.focus_window', 'close': 'apps.close_window_safely',
                  'verify': 'apps.verify_selection'}[operation]
        if not isinstance(window_id, str) or len(window_id) > 80:
            return refused(action, None, 'Нужен проверенный идентификатор окна.', status='stale_target')
        with self._lock:
            self._prune()
            selection = self._selections.get(window_id)
            if selection is None:
                return refused(action, None, 'Выбор окна устарел. Найди окно повторно.', status='stale_target')
            try:
                with self.target_provider(selection.app.id) as app:
                    if app != selection.app:
                        return refused(action, app.id, 'Приложение или разрешение изменилось. Выбери окно повторно.', status='stale_target')
                    if operation == 'close':
                        if not self._public(selection)['close_supported']:
                            return refused(action, app.id,
                                'Не могу гарантировать сохранность данных при автоматическом закрытии этого приложения. '
                                'Закрой его вручную; диалоги сохранения останутся под твоим контролем.', status='unsupported_safe_close')
                        if selection.close_requested:
                            return refused(action, app.id, 'Запрос закрытия уже отправлен. Проверь окно; повторять его не буду.', status='close_pending')
                    state = self.backend.operate(app.path, selection.native, self._property, selection.marker, operation)
                    if state == 'stale':
                        self._selections.pop(window_id, None)
                        return refused(action, app.id, 'Окно изменилось. Выбери его повторно.', status='stale_target')
                    facts = self._public(selection)
                    if state == 'verified' and operation == 'verify':
                        return ActionResult(True, action, app.id, 'observed', 'verified_window',
                                            status_text=f'{app.name}: окно проверено.', data=facts)
                    if state == 'focused':
                        return ActionResult(True, action, app.id, 'observed', 'foreground_window',
                                            status_text=f'{app.name}: окно на переднем плане.', data=facts)
                    if state == 'close_requested':
                        selection.close_requested = True
                        # Do not infer window closure from PostMessage success.
                        after = self.backend.inspect(app.path)
                        remaining = any(item.hwnd == selection.native.hwnd for item in after.windows)
                        if after.state in ('absent', 'background', 'visible_window') and not remaining:
                            self._selections.pop(window_id, None)
                            return ActionResult(True, action, app.id, 'observed', 'window_closed',
                                                status_text=f'{app.name}: выбранное окно закрыто.', data=facts)
                        return ActionResult(True, action, app.id, 'request_accepted', None,
                            status_text=f'{app.name}: запрос закрытия отправлен; исчезновение окна пока не подтверждено.', data=facts)
                    message = ('Windows не разрешила вывести окно на передний план. Выбери его через панель задач.'
                               if state == 'foreground_denied' else 'Windows отклонила запрос к выбранному окну.')
                    return refused(action, app.id, message, status='activation_denied' if state == 'foreground_denied' else 'inspection_unavailable')
            except (AppError, OSError, ValueError, AttributeError):
                return refused(action, selection.app.id, 'Не удалось повторно проверить окно и разрешение. Действие отменено.', status='unavailable')

    def focus_window(self, window_id):
        return self._operate(window_id, 'focus')

    def close_window_safely(self, window_id):
        return self._operate(window_id, 'close')

    def verify_selection(self, window_id):
        """Validate a UI-selected opaque ID without focusing/closing the window."""
        return self._operate(window_id, 'verify')

    def close(self):
        """Release only this instance's markers during orderly API shutdown."""
        with self._lock:
            for selection in self._selections.values():
                try:
                    with self.target_provider(selection.app.id) as current:
                        if current == selection.app:
                            self.backend.operate(current.path, selection.native, self._property, selection.marker, 'release')
                except (AppError, OSError, ValueError, AttributeError):
                    pass
            self._selections.clear()


window_tools = WindowTools()
