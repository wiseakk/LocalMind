"""Exact, expiring, one-shot file confirmations, separate from ordinary tools.

Preparing never writes. Only an authenticated UI confirmation may call confirm;
neither a model plan nor actions_authorized=True is proof of this confirmation.
No scripts, executables, directories or system settings are mutation targets.
"""
from contextlib import contextmanager, ExitStack
from dataclasses import dataclass
import ctypes
from ctypes import wintypes as w
import hashlib
import os
from pathlib import Path
import secrets
import time

from .file_access import FileAccessError, _checked, _fingerprint, _hold, _identity, _stream_fingerprint, file_access
from .personal_permissions import ordinary_path
from .results import ActionResult, refused

MUTABLE = frozenset(('.txt', '.md', '.markdown', '.csv', '.tsv', '.json', '.pdf', '.docx'))
TEXT_MUTABLE = MUTABLE - {'.pdf', '.docx'}
MAX_CONTENT_BYTES = 256 * 1024


@dataclass(frozen=True)
class PendingMutation:
    id: str
    owner: str
    operation: str
    scope: str
    grant_generation: str
    path: Path
    parent_identity: tuple
    expected: tuple | None
    content: bytes
    destination: Path | None
    destination_parent_identity: tuple | None
    deadline: float


@contextmanager
def _parents_held(path):
    with ExitStack() as stack:
        for parent in reversed(path.parents):
            stack.enter_context(_hold(parent, True))
        yield


@contextmanager
def _exact_handle(path, create=False):
    """Windows deny-write/delete handle; ancestors are already held by caller."""
    if os.name != 'nt':
        descriptor = os.open(path, os.O_RDWR | getattr(os, 'O_NOFOLLOW', 0) | (os.O_CREAT | os.O_EXCL if create else 0), 0o600)
        with os.fdopen(descriptor, 'r+b') as stream:
            if _identity(path) != (os.fstat(stream.fileno()).st_dev, os.fstat(stream.fileno()).st_ino):
                raise FileAccessError('Цель изменилась.')
            yield stream, None
        return
    import msvcrt
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.CreateFileW.argtypes = [w.LPCWSTR, w.DWORD, w.DWORD, ctypes.c_void_p, w.DWORD, w.DWORD, w.HANDLE]
    kernel.CreateFileW.restype = w.HANDLE
    kernel.CloseHandle.argtypes = [w.HANDLE]
    # OPEN_REPARSE_POINT plus explicit checked path prevents redirection.
    handle = kernel.CreateFileW(str(path), 0x80000000 | 0x40000000 | 0x10000, 1, None,
                                1 if create else 3, 0x00200000 | 0x80, None)
    if handle in (None, ctypes.c_void_p(-1).value):
        raise FileAccessError('Файл занят, изменился или Windows не разрешает операцию.')
    try:
        _checked(path)
        descriptor = msvcrt.open_osfhandle(handle, os.O_RDWR | os.O_BINARY)
    except Exception:
        kernel.CloseHandle(handle)
        raise
    with os.fdopen(descriptor, 'r+b') as stream:
        if _identity(path) != (os.fstat(stream.fileno()).st_dev, os.fstat(stream.fileno()).st_ino):
            raise FileAccessError('Цель изменилась.')
        yield stream, handle


def _handle_delete(handle):
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.SetFileInformationByHandle.argtypes = [w.HANDLE, ctypes.c_int, ctypes.c_void_p, w.DWORD]
    delete = ctypes.c_ubyte(1)
    if not kernel.SetFileInformationByHandle(handle, 4, ctypes.byref(delete), ctypes.sizeof(delete)):
        raise FileAccessError('Windows отклонила удаление файла.')


def _handle_move(handle, destination):
    class Rename(ctypes.Structure):
        _fields_ = [('replace', w.BOOL), ('root', w.HANDLE), ('length', w.DWORD),
                    ('name', w.WCHAR * (len(str(destination).encode('utf-16-le')) // 2 + 1))]
    rename = Rename()
    rename.replace, rename.root = False, None
    rename.length = len(str(destination).encode('utf-16-le'))
    rename.name = str(destination)
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.SetFileInformationByHandle.argtypes = [w.HANDLE, ctypes.c_int, ctypes.c_void_p, w.DWORD]
    if not kernel.SetFileInformationByHandle(handle, 3, ctypes.byref(rename), ctypes.sizeof(rename)):
        raise FileAccessError('Windows отклонила перемещение. Существующие цели не заменяются.')


class FileMutations:
    def __init__(self, access, *, clock=time.monotonic, ttl=120):
        self.access, self.clock, self.ttl = access, clock, ttl
        self._pending = {}

    def _target(self, scope, relative, operation):
        if not isinstance(relative, str) or not 1 <= len(relative) <= 512:
            raise FileAccessError('Нужно точное относительное имя файла.')
        fragment = Path(relative)
        if fragment.is_absolute() or fragment.drive or any(part in ('..', '.') for part in fragment.parts) or ':' in relative or '\x00' in relative:
            raise FileAccessError('Выбери обычный файл внутри разрешённой папки.')
        roots = self.access.personal_mode.roots()
        if scope not in roots:
            raise FileAccessError('Неизвестная разрешённая область.')
        path = roots[scope] / fragment
        if not ordinary_path(path) or path.suffix.casefold() not in MUTABLE:
            raise FileAccessError('Секретные, системные и исполняемые файлы не изменяются.')
        self.access.personal_mode.check_file(path, operation)
        parent = _checked(path.parent)
        if parent != roots[scope] and roots[scope] not in parent.parents:
            raise FileAccessError('Цель вне разрешённой области.')
        if path.exists() or path.is_symlink():
            _checked(path)
            if not path.is_file():
                raise FileAccessError('Изменять каталоги нельзя.')
        return path

    def prepare(self, owner, operation, scope, relative_path, content='', destination=None):
        action = 'files.prepare_mutation'
        try:
            if not isinstance(owner, str) or not owner or operation not in ('create', 'overwrite', 'delete', 'move'):
                raise FileAccessError('Неизвестная операция изменения файла.')
            if not isinstance(content, str) or len(content) > MAX_CONTENT_BYTES:
                raise FileAccessError('Содержимое должно быть текстом до 256 КиБ.')
            payload = content.encode('utf-8')
            if len(payload) > MAX_CONTENT_BYTES or '\x00' in content:
                raise FileAccessError('Содержимое должно быть обычным текстом до 256 КиБ.')
            if operation in ('delete', 'move') and content:
                raise FileAccessError('Удаление и перемещение не принимают новое содержимое.')
            with self.access._lock, self.access.personal_mode._lock:
                self._pending = {key: value for key, value in self._pending.items() if self.clock() < value.deadline}
                if len(self._pending) >= 128:
                    raise FileAccessError('Слишком много ожидающих подтверждений.')
                path = self._target(scope, relative_path, operation)
                if operation in ('create', 'overwrite') and path.suffix.casefold() not in TEXT_MUTABLE:
                    raise FileAccessError('Создание и перезапись поддерживаются для текстовых документов.')
                with _parents_held(path):
                    if operation == 'create':
                        if path.exists():
                            raise FileAccessError('Файл существует. Для перезаписи нужно отдельное подтверждение.')
                        expected = None
                    else:
                        with _hold(_checked(path)):
                            expected = _fingerprint(path)
                    target = self._target(scope, destination, operation) if operation == 'move' else None
                    if target is not None:
                        if target == path or target.exists():
                            raise FileAccessError('Перемещение не заменяет существующий файл.')
                        if target.suffix.casefold() != path.suffix.casefold():
                            raise FileAccessError('Перемещение не меняет тип файла.')
                    key = secrets.token_urlsafe(32)
                    item = PendingMutation(key, owner, operation, scope, self.access.personal_mode.generation, path, _identity(path.parent), expected,
                        payload, target, _identity(target.parent) if target else None, self.clock() + self.ttl)
                    self._pending[key] = item
                    data = {'confirmation_id': key, 'operation': operation, 'path': str(path),
                            'destination': str(target) if target else None,
                            'content': content if operation in ('create', 'overwrite') else '',
                            'content_sha256': hashlib.sha256(payload).hexdigest(),
                            'expires_in_seconds': self.ttl, 'requires_explicit_confirmation': True}
                    self.access.personal_mode.record('prepare_' + operation, path, 'confirmation_required')
                    return ActionResult(False, action, key, 'confirmation_required',
                        status_text=f'Требуется подтверждение: {operation} — {path}' + (f' → {target}' if target else ''), data=data)
        except (OSError, ValueError, RuntimeError) as exc:
            missing = isinstance(exc, FileNotFoundError)
            reason = 'Указанный файл не найден.' if missing else str(exc) if isinstance(exc, FileAccessError) else 'Не удалось безопасно подготовить операцию.'
            self.access.personal_mode.record('prepare_mutation', str(scope), 'denied', reason, 'mutation_validation')
            return refused(action, None, reason, status='not_found' if missing else 'denied')

    def confirm(self, owner, confirmation_id, approved):
        action = 'files.confirm_mutation'
        try:
            if type(approved) is not bool:
                raise FileAccessError('Нужно явное подтверждение операции.')
            with self.access._lock, self.access.personal_mode._lock:
                pending = self._pending.get(confirmation_id)
                if pending is None or pending.owner != owner:
                    raise FileAccessError('Подтверждение отсутствует или принадлежит другому разговору.')
                # Consume before any side effect, including a failed attempt.
                self._pending.pop(confirmation_id)
                if not approved:
                    self.access.personal_mode.record(pending.operation, pending.path, 'cancelled', 'Операция отменена.', 'exact_confirmation')
                    return refused(action, confirmation_id, 'Операция отменена.', status='cancelled')
                if self.clock() >= pending.deadline:
                    raise FileAccessError('Подтверждение истекло. Подготовь операцию повторно.')
                roots = self.access.personal_mode.roots()
                if self.access.personal_mode.generation != pending.grant_generation:
                    raise FileAccessError('Разрешение изменилось после запроса подтверждения.')
                root = roots.get(pending.scope)
                if root is None or (pending.path != root and root not in pending.path.parents):
                    raise FileAccessError('Разрешение отозвано.')
                path = self._target(pending.scope, str(pending.path.relative_to(root)), pending.operation)
                with ExitStack() as stack:
                    stack.enter_context(_parents_held(path))
                    if _identity(_checked(path.parent)) != pending.parent_identity:
                        raise FileAccessError('Родительская папка изменилась.')
                    if pending.destination:
                        destination = self._target(pending.scope, str(pending.destination.relative_to(root)), pending.operation)
                        stack.enter_context(_parents_held(destination))
                        if destination.exists() or _identity(destination.parent) != pending.destination_parent_identity:
                            raise FileAccessError('Цель перемещения изменилась.')
                    with _exact_handle(path, pending.operation == 'create') as (stream, handle):
                        if pending.expected is not None:
                            # Hash the locked handle, not a pathname reopened after validation.
                            if _stream_fingerprint(stream, path.suffix.casefold()) != pending.expected:
                                raise FileAccessError('Файл изменился после запроса подтверждения.')
                        self.access.personal_mode.check_file(path, pending.operation)
                        if pending.destination:
                            self.access.personal_mode.check_file(pending.destination, pending.operation)
                        if pending.operation in ('create', 'overwrite'):
                            stream.seek(0)
                            stream.write(pending.content)
                            stream.truncate()
                            stream.flush()
                            os.fsync(stream.fileno())
                            stream.seek(0)
                            if hashlib.sha256(stream.read()).digest() != hashlib.sha256(pending.content).digest():
                                raise FileAccessError('Проверка записанного содержимого не пройдена.')
                        elif pending.operation == 'delete':
                            if handle:
                                _handle_delete(handle)
                            else:
                                path.unlink()
                        else:
                            if handle:
                                _handle_move(handle, pending.destination)
                            else:
                                # Hard-link + unlink avoids overwriting an unexpected destination.
                                os.link(path, pending.destination, follow_symlinks=False)
                                path.unlink()
                    if pending.operation == 'delete' and path.exists():
                        raise FileAccessError('Удаление запрошено, но файл всё ещё существует.')
                    if pending.operation == 'move' and (path.exists() or not pending.destination.is_file()):
                        raise FileAccessError('Результат перемещения не подтверждён.')
                self.access.personal_mode.record(pending.operation, path, 'observed')
                return ActionResult(True, action, confirmation_id, 'observed', pending.operation + '_verified',
                    status_text={'create': 'Файл создан.', 'overwrite': 'Файл перезаписан.',
                                 'delete': 'Файл удалён.', 'move': 'Файл перемещён.'}[pending.operation],
                    data={'operation': pending.operation, 'path': str(path),
                          'destination': str(pending.destination) if pending.destination else None})
        except (OSError, ValueError, RuntimeError) as exc:
            reason = str(exc) if isinstance(exc, FileAccessError) else 'Операция не выполнена или её результат не подтверждён.'
            self.access.personal_mode.record('confirm_mutation', confirmation_id, 'denied', reason, 'exact_confirmation')
            return refused(action, confirmation_id, reason)


file_mutations = FileMutations(file_access)
