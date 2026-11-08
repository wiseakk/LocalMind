"""Permission-bound Windows window capabilities.

Titles are display metadata. Selection uses opaque expiring IDs, image grants,
PID creation time, session/SID, HWND/thread and an instance-specific native
window property. Windows destroys that property with the window, so a recycled
HWND in the same process cannot inherit an old selection.
"""
from __future__ import annotations

from contextlib import contextmanager, ExitStack, nullcontext
import ctypes
from ctypes import wintypes as w
from dataclasses import dataclass, replace
import os
from pathlib import Path
import secrets
import threading
import time
import uuid

from .apps import AppError, _launch_guard, _safe_local_path, catalog, KNOWN_ALIASES, executable_identity
from .results import ActionResult, refused
from .generation import check_cancelled, cancellation
from .windows_state import VerifiedWindow, _inspect_windows, inspect_application, inspect_applications


@dataclass(frozen=True)
class AppTarget:
    id: str
    name: str
    path: Path
    fingerprint: str
    safe_close: bool = False
    companions: tuple[tuple[Path, tuple], ...] = ()


@dataclass
class WindowSelection:
    id: str
    app: AppTarget
    native: VerifiedWindow
    marker: int
    expires: float
    close_requested: bool = False
    policy_generation: str | None = None
    image: Path | None = None


class NativeWindowBackend:
    def inspect(self, target):
        return inspect_application(target)

    def inspect_many(self, targets):
        return inspect_applications(targets)

    def child_of(self, pid, parents):
        import psutil
        try:
            parent = psutil.Process(pid).parent()
            # Compare creation time as well: the sampled client PID may have
            # exited before the parent query. psutil returns Unix seconds.
            return parent is not None and any(parent.pid == owner and
                abs(parent.create_time() - (created / 10_000_000 - 11_644_473_600)) < .001
                for owner, created in parents)
        except psutil.Error:
            return False

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
            def same_window():
                pid = w.DWORD()
                return (bool(user.IsWindow(hwnd))
                        and user.GetPropW(hwnd, property_name) == marker
                        and user.GetWindowThreadProcessId(hwnd, ctypes.byref(pid)) == expected.thread_id
                        and pid.value == expected.pid)

            if not same_window():
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
                user.IsIconic.restype = w.BOOL
                user.ShowWindowAsync.argtypes = [w.HWND, ctypes.c_int]
                user.ShowWindowAsync.restype = w.BOOL
                check_cancelled()
                if user.IsIconic(hwnd):
                    user.ShowWindowAsync(hwnd, 9)  # SW_RESTORE, no input simulation
                    # ShowWindowAsync posts to another thread. Give the restore
                    # a bounded interval before observing foreground state.
                    until = time.monotonic() + .3
                    while user.IsIconic(hwnd) and time.monotonic() < until:
                        check_cancelled()
                        if not same_window():
                            return
                        time.sleep(.02)
                # Restore is asynchronous. The original HWND may have been
                # destroyed/reused while waiting; its marker cannot survive.
                check_cancelled()
                if not same_window():
                    return
                if user.IsIconic(hwnd):
                    outcome['state'] = 'restore_pending'
                    return
                user.SetForegroundWindow(hwnd)
                until = time.monotonic() + .3
                while user.GetForegroundWindow() != hwnd and time.monotonic() < until:
                    check_cancelled()
                    if not same_window():
                        return
                    time.sleep(.02)
                if not same_window():
                    return
                observed = user.GetForegroundWindow() == hwnd and not user.IsIconic(hwnd)
                outcome['state'] = 'focused' if observed else 'foreground_denied'
            elif operation in ('minimize', 'restore'):
                user.ShowWindowAsync.argtypes = [w.HWND, ctypes.c_int]
                user.ShowWindowAsync.restype = w.BOOL
                user.IsIconic.argtypes = [w.HWND]
                user.IsIconic.restype = w.BOOL
                desired = operation == 'minimize'
                user.ShowWindowAsync(hwnd, 6 if desired else 9)
                until = time.monotonic() + .4
                while bool(user.IsIconic(hwnd)) != desired and time.monotonic() < until:
                    check_cancelled()
                    if not same_window():
                        return
                    time.sleep(.02)
                if not same_window():
                    return
                outcome['state'] = ('minimized' if desired else 'restored') if bool(user.IsIconic(hwnd)) == desired else 'state_pending'
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
                 clock=time.monotonic, capacity=128, ttl=900, policy=None):
        self.backend = backend or NativeWindowBackend()
        self.target_provider = target_provider or self._catalog_target
        self.app_ids = app_ids or self._catalog_ids
        self.clock, self.capacity, self.ttl = clock, capacity, ttl
        self._selections: dict[str, WindowSelection] = {}
        self._lock = threading.RLock()
        self._property = 'LocalMind.Window.' + uuid.uuid4().hex
        self._builtin_resolver = None
        # Explicit test providers remain isolated from the production singleton.
        self._policy = policy if policy is not None else (lambda: catalog.policy) if target_provider is None else None

    @property
    def policy(self):
        return self._policy() if callable(self._policy) else self._policy

    def _check_policy(self, app, operation):
        if self.policy is None:
            return
        try:
            if app.id in catalog._entries:
                catalog.check_permission(app.id, operation)
            else:
                identifiers = (app.id, str(app.path).casefold(), app.path.stem.casefold(),
                               *KNOWN_ALIASES.get(app.path.stem.casefold(), ()), *executable_identity(app.path))
                if app.id in ('calculator', 'notepad'):
                    identifiers += ('builtin:' + app.id,)
                self.policy.check_app(identifiers, operation)
        except ValueError as exc:
            raise AppError(str(exc)) from exc

    def configure_builtin_resolver(self, resolver):
        self._builtin_resolver = resolver

    def _catalog_ids(self):
        catalog.aliases()  # Discover once; launch permission is not inferred.
        return [item['id'] for item in catalog.entries() if any(item['permissions'].values())] + ['calculator', 'notepad']

    @contextmanager
    def _catalog_target(self, app_id):
        if app_id in ('calculator', 'notepad'):
            path = self._builtin_resolver(app_id) if self._builtin_resolver else None
            if path is None:
                raise AppError('Не удалось проверить системное приложение.')
            with _launch_guard(path):
                if self._builtin_resolver(app_id) != path:
                    raise AppError('Цель системного приложения изменилась.')
                yield AppTarget(app_id, app_id, path, str(path.stat().st_mtime_ns), safe_close=app_id == 'calculator')
            return
        with catalog.policy._lock, catalog._lock:
            entry = catalog._entries.get(app_id)
            if entry is None:
                raise AppError('Приложение отсутствует в каталоге.')
            if entry.launch_type == 'steam':
                raise AppError('Окно игры Steam ещё не связано с проверенным исполняемым файлом.')
            with _launch_guard(entry.target), ExitStack() as companions_guard:
                current = catalog._revalidate(app_id)
                # A basename such as calc.exe is user-controlled. Only the
                # exact OS-resolved calculator image has the safe-close status.
                calculator = self._builtin_resolver('calculator') if self._builtin_resolver else None
                companions = self._steam_companions(current.target, companions_guard)
                yield AppTarget(current.id, current.name, current.target, current.fingerprint,
                                safe_close=calculator is not None and current.target == calculator,
                                companions=companions)

    @staticmethod
    def _steam_companions(client, guards):
        if os.name != 'nt' or client.name.casefold() != 'steam.exe':
            return ()
        import winreg
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r'Software\Valve\Steam') as key:
                root, kind = winreg.QueryValueEx(key, 'SteamPath')
            if kind != winreg.REG_SZ or _safe_local_path(Path(root) / 'steam.exe') != client:
                return ()
        except (AppError, OSError, ValueError):
            return ()
        helpers = []
        for folder in ('cef.win64', 'cef.win32', 'cef.win7x64', 'cef.win7'):
            try:
                path = _safe_local_path(client.parent / 'bin' / 'cef' / folder / 'steamwebhelper.exe')
                guards.enter_context(_launch_guard(path))
                stamp = path.stat()
                helpers.append((path, (stamp.st_dev, stamp.st_ino, stamp.st_size, stamp.st_mtime_ns)))
            except (AppError, OSError, ValueError):
                continue
        return tuple(helpers)

    def _check_companion(self, app, image):
        if self.policy is not None:
            with catalog._lock:
                entry = catalog._entries.get(app.id)
                if entry is None:
                    raise AppError('Установка Steam изменилась.')
                self.policy.check_app((*catalog.identifiers(entry), str(image).casefold(), image.stem.casefold(),
                                       *executable_identity(image)), 'focus')

    def _prune(self):
        for key, selection in list(self._selections.items()):
            if selection.expires <= self.clock():
                # Marker removal is best effort and never targets a new window.
                try:
                    with self.target_provider(selection.app.id) as current:
                        if current == selection.app:
                            self.backend.operate(selection.image or current.path, selection.native, self._property, selection.marker, 'release')
                except (AppError, OSError, ValueError, AttributeError):
                    pass
                self._selections.pop(key, None)

    def _record(self, app, native, image=None):
        generation = self.policy.generation if self.policy is not None else None
        for record in self._selections.values():
            if record.app == app and record.image == image and record.policy_generation == generation and (
                record.native.hwnd, record.native.pid, record.native.created, record.native.thread_id
            ) == (native.hwnd, native.pid, native.created, native.thread_id):
                # Confirm marker too: a recycled HWND must not refresh an ID.
                if self.backend.operate(image or app.path, native, self._property, record.marker, 'verify') == 'verified':
                    return record
        if len(self._selections) >= self.capacity:
            return None
        marker = secrets.randbits(ctypes.sizeof(ctypes.c_void_p) * 8 - 1) or 1
        if self.backend.operate(image or app.path, native, self._property, marker, 'stamp') != 'stamped':
            return None
        record = WindowSelection('win-' + uuid.uuid4().hex, app, native, marker, self.clock() + self.ttl)
        record.policy_generation = generation
        record.image = image
        self._selections[record.id] = record
        return record

    @staticmethod
    def _public(record):
        return {'window_id': record.id, 'app_id': record.app.id, 'application': record.app.name,
                'title': record.native.title, 'close_supported': record.app.safe_close}

    def list_running(self, app_id=None):
        with (self.policy._lock if self.policy is not None else nullcontext()), self._lock:
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
                        # Read-only window selection needs at least one declared
                        # operation, but never upgrades launch into close.
                        if self.policy is not None:
                            permitted = False
                            for operation in ('launch', 'focus', 'close'):
                                try:
                                    self._check_policy(app, operation)
                                    permitted = True
                                    break
                                except AppError:
                                    pass
                            if not permitted:
                                raise AppError('Приложение запрещено политикой доступа.')
                        image_key = os.path.normcase(str(app.path))
                        if image_key in seen_paths:
                            continue
                        seen_paths.add(image_key)
                        candidates.append((key, app))
                    except (AppError, OSError, ValueError, AttributeError):
                        unknown.append(key)
                snapshots = (self.backend.inspect_many([path for _, item in candidates
                             for path in (item.path, *(image for image, _ in item.companions))])
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
                        observed = [(native, None) for native in state.windows]
                        for image, _ in app.companions if state.processes else ():
                            helper = snapshots[image] if snapshots is not None else self.backend.inspect(image)
                            owned = [native for native in helper.windows if self.backend.child_of(native.pid, state.processes)]
                            if owned:
                                try:
                                    self._check_policy(app, 'focus')
                                    self._check_companion(app, image)
                                except (AppError, ValueError):
                                    continue
                                observed.extend((native, image) for native in owned)
                        truncated = truncated or len(observed) > 32
                        for native, image in observed[:32]:
                            if len(windows) >= 64:
                                truncated = True
                                break
                            record = self._record(app, native, image)
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

    def open_app(self, app_id, launcher):
        """Launch once, then observe a permission-bound window and focus it.

        Snapshot the grant before launch so a changed executable cannot silently
        become the focus target. Electron may hand off to a different PID; the
        normal image/session/HWND checks discover that window independently.
        """
        check_cancelled()
        try:
            with self.target_provider(app_id) as target:
                self._check_policy(target, 'launch')
                original = target
        except (AppError, OSError, ValueError):
            # Some launch types (Steam) have no verifiable window image. Their
            # launcher still enforces its own grants; never infer focus there.
            return launcher(app_id)
        window_id, error = self.select_app_window(app_id)
        if window_id:
            focused = self.focus_window(window_id)
            if focused.execution_status not in ('observed', 'activation_denied', 'restore_pending'):
                return focused
            return replace(focused, success=True, action='apps.open', execution_status='already_running',
                observed_state='foreground_window' if focused.success else 'visible_window', error=None,
                status_text=focused.status_text if focused.success else 'Приложение уже открыто. ' + focused.status_text,
                data={**(focused.data or {}), 'process_created': False, 'process_running': True,
                      'window_found': True, 'window_activated': focused.success,
                      'activation_status': focused.execution_status, 'activation_error': focused.error})
        if error.execution_status != 'window_pending':
            return error
        check_cancelled()
        launched = launcher(app_id)
        if not launched.success:
            return launched
        check_cancelled()
        focused = self.focus_app(app_id, timeout=10.0, expected_target=original)
        # Launch and foreground activation are independent outcomes. A denied
        # SetForegroundWindow must never erase a successful CreateProcess or
        # suggest a retry that starts another instance. Revalidation failures
        # still prevent focus and remain visible in the activation diagnostics.
        found = True if focused.data and focused.data.get('window_id') else None
        if focused.execution_status == 'window_timeout':
            found = False
        return replace(launched, action='apps.open',
            observed_state='foreground_window' if focused.success else 'visible_window' if found else launched.observed_state,
            status_text=focused.status_text if focused.success else launched.status_text + ' ' + focused.status_text,
            data={**(launched.data or {}), **(focused.data or {}), 'launch_status': launched.execution_status,
                  'process_created': launched.execution_status == 'process_created',
                  'process_running': True if focused.success or found or launched.observed_state in ('visible_window', 'background') else
                                     (focused.data or {}).get('process_running'),
                  'window_found': True if focused.success else found, 'window_activated': focused.success,
                  'activation_status': focused.execution_status, 'activation_error': focused.error})

    def focus_app(self, app_id, timeout=4.0, *, expected_target=None):
        """Discover after authorization; support delayed and existing-instance windows.

        Every poll and final native operation revalidates the image grant. Never
        select by title or just the PID returned by a launcher (Electron handoff).
        """
        try:
            with self.target_provider(app_id) as target:
                self._check_policy(target, 'focus')
                original = target
                if expected_target is not None and original != expected_target:
                    return refused('apps.focus', app_id, 'Цель приложения изменилась после запуска.', status='stale_target')
        except AppError as exc:
            return refused('apps.focus', app_id, str(exc), status='permission_required')
        except (OSError, ValueError):
            return refused('apps.focus', app_id, 'Проверь разрешение приложения и его исполняемый файл в каталоге.', status='permission_required')
        deadline = self.clock() + min(max(timeout, 0), 10)
        while True:
            check_cancelled()
            try:
                with self.target_provider(app_id) as current:
                    self._check_policy(current, 'focus')
                    if current != original:
                        return refused('apps.focus', app_id, 'Цель приложения изменилась. Выбери приложение повторно.', status='stale_target')
                    window_id, error = self.select_app_window(app_id)
            except AppError as exc:
                return refused('apps.focus', app_id, str(exc), status='stale_target')
            except (OSError, ValueError):
                return refused('apps.focus', app_id, 'Разрешение или цель приложения изменились.', status='stale_target')
            if window_id:
                return self.focus_window(window_id)
            if error.execution_status != 'window_pending':
                return error
            if self.clock() >= deadline:
                outcome = refused('apps.focus', app_id, 'Проверенное окно не появилось за отведённое время. Повтори после загрузки приложения.', status='window_timeout')
                if app_id in (error.data or {}).get('background_apps', ()):
                    return replace(outcome, data={'process_running': True})
                return outcome
            event = cancellation.get()
            if event is not None:
                event.wait(.1)
            else:
                time.sleep(.1)

    def _operate(self, window_id, operation):
        result = self._operate_checked(window_id, operation)
        if self.policy is not None:
            self.policy.record(operation, result.resolved_target or 'window', result.execution_status, reason=result.error)
        return result

    def _operate_checked(self, window_id, operation):
        action = {'focus': 'apps.focus_window', 'close': 'apps.close_window_safely',
                  'minimize': 'apps.minimize_window', 'restore': 'apps.restore_window',
                  'verify': 'apps.verify_selection'}[operation]
        if not isinstance(window_id, str) or len(window_id) > 80:
            return refused(action, None, 'Нужен проверенный идентификатор окна.', status='stale_target')
        with (self.policy._lock if self.policy is not None else nullcontext()), self._lock:
            self._prune()
            selection = self._selections.get(window_id)
            if selection is None:
                return refused(action, None, 'Выбор окна устарел. Найди окно повторно.', status='stale_target')
            try:
                if self.policy is not None and selection.policy_generation != self.policy.generation:
                    self._selections.pop(window_id, None)
                    return refused(action, selection.app.id, 'Политика доступа изменилась. Выбери окно повторно.', status='stale_target')
                with self.target_provider(selection.app.id) as app:
                    self._check_policy(app, 'close' if operation == 'close' else 'focus')
                    if app != selection.app:
                        return refused(action, app.id, 'Приложение или разрешение изменилось. Выбери окно повторно.', status='stale_target')
                    if operation == 'close':
                        if not self._public(selection)['close_supported']:
                            return refused(action, app.id,
                                'Не могу гарантировать сохранность данных при автоматическом закрытии этого приложения. '
                                'Закрой его вручную; диалоги сохранения останутся под твоим контролем.', status='unsupported_safe_close')
                        if selection.close_requested:
                            return refused(action, app.id, 'Запрос закрытия уже отправлен. Проверь окно; повторять его не буду.', status='close_pending')
                    with self.policy._lock if self.policy is not None else nullcontext():
                        if self.policy is not None and selection.policy_generation != self.policy.generation:
                            return refused(action, app.id, 'Политика доступа изменилась. Выбери окно повторно.', status='stale_target')
                        self._check_policy(app, 'close' if operation == 'close' else 'focus')
                        image = selection.image or app.path
                        if selection.image:
                            self._check_companion(app, image)
                            if not self.backend.child_of(selection.native.pid, self.backend.inspect(app.path).processes):
                                return refused(action, app.id, 'Связь окна с процессом Steam изменилась.', status='stale_target')
                        state = self.backend.operate(image, selection.native, self._property, selection.marker, operation)
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
                    if state in ('minimized', 'restored'):
                        return ActionResult(True, action, app.id, 'observed', state,
                                            status_text=f'{app.name}: окно ' + ('свёрнуто.' if state == 'minimized' else 'восстановлено.'), data=facts)
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
                               if state == 'foreground_denied' else
                               'Окно осталось свёрнутым после запроса восстановления. Открой его через панель задач.'
                               if state == 'restore_pending' else 'Windows отклонила запрос к выбранному окну.')
                    return replace(refused(action, app.id, message,
                                   status='activation_denied' if state == 'foreground_denied' else
                                   'restore_pending' if state == 'restore_pending' else 'inspection_unavailable'),
                                   data=facts)
            except AppError as exc:
                return refused(action, selection.app.id, str(exc), status='denied')
            except (OSError, ValueError, AttributeError):
                return refused(action, selection.app.id, 'Не удалось повторно проверить окно и разрешение. Действие отменено.', status='unavailable')

    def focus_window(self, window_id):
        return self._operate(window_id, 'focus')

    def minimize_window(self, window_id):
        return self._operate(window_id, 'minimize')

    def restore_window(self, window_id):
        return self._operate(window_id, 'restore')

    def close_window_safely(self, window_id):
        return self._operate(window_id, 'close')

    def verify_selection(self, window_id):
        """Validate a UI-selected opaque ID without focusing/closing the window."""
        return self._operate(window_id, 'verify')

    def close(self):
        """Release only this instance's markers during orderly API shutdown."""
        with (self.policy._lock if self.policy is not None else nullcontext()), self._lock:
            for selection in self._selections.values():
                try:
                    with self.target_provider(selection.app.id) as current:
                        if current == selection.app:
                            self.backend.operate(selection.image or current.path, selection.native, self._property, selection.marker, 'release')
                except (AppError, OSError, ValueError, AttributeError):
                    pass
            self._selections.clear()


window_tools = WindowTools()
