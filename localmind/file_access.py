"""Session-only Downloads access and exact PDF grants, independent of the LLM.

Only a Windows known folder (or an injected test fixture) may be approved. No
path input exists in the chat/tool API. Selection is non-recursive and bounded.
"""
from contextlib import contextmanager, ExitStack
from dataclasses import dataclass
from datetime import datetime, timezone
import ctypes
from ctypes import wintypes as w
import hashlib
import os
from pathlib import Path
import secrets
import stat
import time
from threading import RLock

from .results import ActionResult, refused


class FileAccessError(ValueError):
    pass


def downloads_folder():
    if os.name != 'nt':
        raise FileAccessError('Системная папка Загрузки доступна только в Windows.')
    # FOLDERID_Downloads; do not use a model/environment supplied folder.
    import uuid
    guid = (ctypes.c_ubyte * 16).from_buffer_copy(uuid.UUID('374de290-123f-4565-9164-39c4925e467b').bytes_le)
    shell = ctypes.WinDLL('shell32', use_last_error=True)
    ole = ctypes.WinDLL('ole32')
    shell.SHGetKnownFolderPath.argtypes = [ctypes.c_void_p, w.DWORD, w.HANDLE, ctypes.POINTER(ctypes.c_void_p)]
    shell.SHGetKnownFolderPath.restype = ctypes.c_long
    ole.CoTaskMemFree.argtypes = [ctypes.c_void_p]
    pointer = ctypes.c_void_p()
    if shell.SHGetKnownFolderPath(ctypes.byref(guid), 0, None, ctypes.byref(pointer)) != 0:
        raise FileAccessError('Не удалось определить системную папку Загрузки.')
    try:
        return Path(ctypes.wstring_at(pointer))
    finally:
        ole.CoTaskMemFree(pointer)


def _checked(path):
    path = Path(path)
    if not path.is_absolute() or str(path).startswith(('\\\\', '//')):
        raise FileAccessError('Сетевые и относительные пути запрещены.')
    if os.name == 'nt':
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.GetDriveTypeW.argtypes = [w.LPCWSTR]
        if kernel.GetDriveTypeW(path.anchor) != 3:  # DRIVE_FIXED
            raise FileAccessError('Разрешены только локальные фиксированные диски.')
    for part in (path, *path.parents):
        item = part.lstat()
        if stat.S_ISLNK(item.st_mode) or getattr(item, 'st_file_attributes', 0) & 0x400:
            raise FileAccessError('Ссылки и reparse points запрещены.')
    if path.resolve(strict=True) != path:
        raise FileAccessError('Путь изменился.')
    return path


def _identity(path):
    info = path.stat(follow_symlinks=False)
    return info.st_dev, info.st_ino


@contextmanager
def _hold(path, directory=False):
    """Deny writes/replacement while Windows resolves or opens an exact target."""
    if os.name != 'nt':
        yield
        return
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.CreateFileW.argtypes = [w.LPCWSTR, w.DWORD, w.DWORD, ctypes.c_void_p, w.DWORD, w.DWORD, w.HANDLE]
    kernel.CreateFileW.restype = w.HANDLE
    kernel.CloseHandle.argtypes = [w.HANDLE]
    # Files permit only other readers; directory can change children, not be
    # renamed/replaced. Ancestors are held as well, closing the parent race.
    handle = kernel.CreateFileW(str(path), 0 if directory else 0x80000000,
                                3 if directory else 1, None, 3,
                                0x02000000 if directory else 0x80, None)
    if handle in (None, ctypes.c_void_p(-1).value):
        raise FileAccessError('Файл занят или не удалось безопасно проверить путь.')
    try:
        _checked(path)
        yield
    finally:
        kernel.CloseHandle(handle)


@contextmanager
def _locked_path(path, directory=False):
    with ExitStack() as stack:
        for parent in reversed(path.parents):
            stack.enter_context(_hold(parent, True))
        stack.enter_context(_hold(path, directory))
        yield


def _fingerprint(path):
    before = path.stat(follow_symlinks=False)
    if not stat.S_ISREG(before.st_mode) or before.st_size > 64 * 1024 * 1024:
        raise FileAccessError('PDF должен быть обычным файлом размером до 64 МБ.')
    digest = hashlib.sha256()
    total, deadline = 0, time.monotonic() + 5
    with path.open('rb') as source:
        if source.read(5) != b'%PDF-':
            raise FileAccessError('Файл не имеет заголовка PDF.')
        source.seek(0)
        for chunk in iter(lambda: source.read(65536), b''):
            total += len(chunk)
            if total > 64 * 1024 * 1024 or time.monotonic() > deadline:
                raise FileAccessError('Проверка PDF превысила ограничение размера или времени.')
            digest.update(chunk)
    after = path.stat(follow_symlinks=False)
    stamp = lambda s: (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns)
    if stamp(before) != stamp(after):
        raise FileAccessError('Файл изменился во время проверки.')
    return stamp(after), digest.hexdigest()


@dataclass(frozen=True)
class SelectedFile:
    id: str
    owner: str
    path: Path
    stamp: tuple
    digest: str

    def public(self):
        return {'file_id': self.id, 'filename': self.path.name, 'path': str(self.path),
                'modified_at': datetime.fromtimestamp(self.stamp[3] / 1e9, timezone.utc).isoformat(),
                'timestamp_semantics': 'last_modified_not_download_time', 'sha256': self.digest}


class FileAccess:
    def __init__(self, folder_provider=downloads_folder, opener=None):
        self.folder_provider = folder_provider
        self.opener = opener or self._open
        self._lock = RLock()
        self._folder_grant = None
        self._selected, self._grants = {}, set()

    @staticmethod
    def _open(path):
        if os.name != 'nt':
            raise FileAccessError('Открытие PDF поддерживается только в Windows.')
        os.startfile(str(path), 'open')

    def folder_info(self):
        with self._lock:
            folder = _checked(self.folder_provider())
            if not folder.is_dir():
                raise FileAccessError('Папка Загрузки недоступна.')
            identity = _identity(folder)
            fingerprint = hashlib.sha256(repr((str(folder), identity)).encode()).hexdigest()
            return {'path': str(folder), 'fingerprint': fingerprint,
                    'allowed': self._folder_grant == (folder, identity), 'recursive': False}

    def set_folder_permission(self, allowed, fingerprint):
        with self._lock:
            if not allowed:
                self._folder_grant = None
                self._selected.clear()
                self._grants.clear()
                return
            folder = _checked(self.folder_provider())
            with _locked_path(folder, True):
                identity = _identity(_checked(folder))
                expected = hashlib.sha256(repr((str(folder), identity)).encode()).hexdigest()
                if fingerprint != expected:
                    raise FileAccessError('Папка изменилась. Проверь разрешение повторно.')
                self._folder_grant = folder, identity

    def _folder(self):
        folder = _checked(self.folder_provider())
        if self._folder_grant != (folder, _identity(folder)):
            self._folder_grant = None
            raise FileAccessError('Сначала разреши чтение системной папки Загрузки.')
        return folder

    def find_latest(self, owner):
        action = 'files.find_latest_pdf_in_downloads'
        try:
            with self._lock:
                if not self.folder_info()['allowed']:
                    return refused(action, None, 'Разреши чтение системной папки Загрузки в настройках файлов. Будут просмотрены только файлы в самой папке.', status='permission_required')
                folder = self._folder()
                with _locked_path(folder, True):
                    self._folder()
                    candidates = []
                    with os.scandir(folder) as entries:
                        for index, item in enumerate(entries):
                            if index >= 2048:
                                raise FileAccessError('В папке более 2048 объектов; поиск ограничен. Выбери файл вручную.')
                            if not item.name.casefold().endswith('.pdf') or not item.is_file(follow_symlinks=False):
                                continue
                            path = Path(item.path)
                            try:
                                _checked(path)
                            except (FileAccessError, OSError):
                                continue
                            candidates.append((item.stat(follow_symlinks=False).st_mtime_ns, item.name.casefold(), item.name, path))
                    if not candidates:
                        return refused(action, None, 'PDF в разрешённой папке Загрузки не найден.', status='not_found')
                    # Greatest modified time; ties use smallest casefold/name.
                    path = sorted(candidates, key=lambda x: (-x[0], x[1], x[2]))[0][3]
                    with _locked_path(path):
                        _checked(path)
                        stamp, digest = _fingerprint(path)
                    selected = SelectedFile(secrets.token_urlsafe(24), owner, path, stamp, digest)
                    if len(self._selected) >= 128:
                        raise FileAccessError('Список выбранных файлов заполнен. Отзови доступ к папке для сброса.')
                    self._selected[selected.id] = selected
                    return ActionResult(True, action, selected.id, 'observed', 'selected_pdf',
                        status_text=f'Последний по времени изменения PDF: {path.name}. Изменён: {selected.public()["modified_at"]}. Путь: {path}. Это время изменения, а не скачивания.',
                        data=selected.public())
        except (OSError, ValueError, RuntimeError):
            return refused(action, None, 'Не удалось безопасно прочитать PDF. Проверь разрешение на Загрузки и состояние файла.')

    def _selection(self, owner, file_id):
        selected = self._selected.get(file_id)
        if selected is None or selected.owner != owner:
            raise FileAccessError('Выбери PDF в этом разговоре повторно.')
        if selected.path.parent != self._folder():
            raise FileAccessError('Разрешение на папку изменилось.')
        return selected

    def selected_info(self, owner, file_id):
        with self._lock:
            selected = self._selection(owner, file_id)
            return {**selected.public(), 'open_allowed': file_id in self._grants}

    def set_open_permission(self, owner, file_id, allowed):
        with self._lock:
            if not allowed:
                self._grants.discard(file_id)
                return
            selected = self._selection(owner, file_id)
            with _locked_path(selected.path):
                if _fingerprint(_checked(selected.path)) != (selected.stamp, selected.digest):
                    self._grants.discard(file_id)
                    raise FileAccessError('PDF изменился. Найди и разреши файл повторно.')
                self._grants.add(file_id)

    def open_selected(self, owner, file_id):
        action = 'files.open_selected_file'
        try:
            with self._lock:
                selected = self._selection(owner, file_id)
                if file_id not in self._grants:
                    return refused(action, file_id, 'Разреши открытие именно этого PDF в настройках файлов.', status='permission_required')
                with _locked_path(selected.path):
                    self._selection(owner, file_id)
                    if _fingerprint(_checked(selected.path)) != (selected.stamp, selected.digest):
                        self._grants.discard(file_id)
                        raise FileAccessError('Файл изменился.')
                    self.opener(selected.path)
                    return ActionResult(True, action, file_id, 'request_accepted',
                        status_text=f'Команда открытия {selected.path.name} передана Windows; появление окна не проверено.',
                        data=selected.public())
        except (OSError, ValueError, RuntimeError):
            return refused(action, file_id, 'Не удалось безопасно открыть выбранный PDF. Найди и разреши файл повторно.')


file_access = FileAccess()
