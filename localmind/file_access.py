"""Bounded local file search with conversation-owned references and exact identity.

Model tools select approved scope IDs; only explicit settings can approve roots.
Personal mode broadens reads/opening, never writes, scripts or OS privileges.
"""
from contextlib import contextmanager, ExitStack
from dataclasses import dataclass, replace
from datetime import datetime, timezone
import ctypes
from ctypes import wintypes as w
import hashlib
import os
from pathlib import Path
import re
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
    if (not path.is_absolute() or str(path).startswith(('\\\\', '//'))
            or '\x00' in str(path) or ':' in str(path)[len(path.drive):]
            or any(part.rstrip(' .') != part for part in path.parts if part != path.anchor)):
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
        if stat.S_ISREG(item.st_mode) and item.st_nlink != 1:
            raise FileAccessError('Файлы с несколькими жёсткими ссылками запрещены.')
    if '..' in path.parts:
        raise FileAccessError('Переходы к родительским папкам запрещены.')
    if path.resolve(strict=True) != path:
        raise FileAccessError('Путь изменился.')
    return path


def _identity(path):
    info = path.stat(follow_symlinks=False)
    return info.st_dev, info.st_ino


def _metadata_stamp(path):
    info = path.stat(follow_symlinks=False)
    if not stat.S_ISREG(info.st_mode) or info.st_size > 64 * 1024 * 1024:
        raise FileAccessError('Нужен обычный документ до 64 МиБ.')
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns,
            info.st_ctime_ns, getattr(info, 'st_birthtime_ns', None))


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
        raise FileAccessError('Документ должен быть обычным файлом размером до 64 МБ.')
    with path.open('rb') as source:
        snapshot = _stream_fingerprint(source, path.suffix.casefold())
        # Bind the checked pathname to the hashed handle. Compare only identity
        # across these APIs: Windows ctime semantics are not interchangeable.
        if (before.st_dev, before.st_ino) != snapshot[0][:2] or _identity(path) != snapshot[0][:2]:
            raise FileAccessError('Файл изменился во время проверки.')
        return snapshot


def _stream_fingerprint(source, suffix):
    """Comparable snapshots from the same handle used to read the bytes.

    Windows Python versions can give stat and fstat different ctime semantics.
    Never compare those APIs or reconstruct nanoseconds from floating seconds.
    Keep birthtime separately where available, as well as the change timestamp.
    Callers hold the checked path against replacement for the whole operation.
    """
    def stamp(info):
        return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns,
                info.st_ctime_ns, getattr(info, 'st_birthtime_ns', None))

    before = os.fstat(source.fileno())
    if not stat.S_ISREG(before.st_mode) or before.st_size > 64 * 1024 * 1024:
        raise FileAccessError('Документ должен быть обычным файлом размером до 64 МБ.')
    if suffix not in READABLE_EXTENSIONS:
        raise FileAccessError('Тип файла не поддерживается для безопасного чтения и открытия.')
    digest = hashlib.sha256()
    total, deadline = 0, time.monotonic() + 5
    source.seek(0)
    if suffix == '.pdf' and source.read(5) != b'%PDF-':
        raise FileAccessError('Файл не имеет заголовка PDF.')
    source.seek(0)
    for chunk in iter(lambda: source.read(65536), b''):
        total += len(chunk)
        if total > 64 * 1024 * 1024 or time.monotonic() > deadline:
            raise FileAccessError('Проверка документа превысила ограничение размера или времени.')
        digest.update(chunk)
    after = os.fstat(source.fileno())
    if stamp(before) != stamp(after):
        raise FileAccessError('Файл изменился во время проверки.')
    return stamp(after), digest.hexdigest()


@dataclass(frozen=True)
class SelectedFile:
    id: str
    owner: str
    path: Path
    stamp: tuple
    digest: str | None
    created_ns: int | None = None

    def public(self):
        return {'file_id': self.id, 'filename': self.path.name, 'path': str(self.path),
                'modified_at': datetime.fromtimestamp(self.stamp[3] / 1e9, timezone.utc).isoformat(),
                'created_at': datetime.fromtimestamp(self.created_ns / 1e9, timezone.utc).isoformat() if self.created_ns else None,
                'size_bytes': self.stamp[2],
                'timestamp_semantics': 'last_modified_not_download_time', 'sha256': self.digest}


READABLE_EXTENSIONS = frozenset(('.pdf', '.txt', '.md', '.markdown', '.docx', '.csv', '.json', '.tsv'))


class FileAccess:
    def __init__(self, folder_provider=downloads_folder, opener=None, *, persistence=None, observer=None):
        from .personal_permissions import PersonalMode
        self.folder_provider = folder_provider
        self.opener = opener or self._open
        self.observer = observer
        self._lock = RLock()
        self._folder_grant = None
        self._selected, self._grants = {}, set()
        self._invalidations = {}  # bounded denial reasons, never retained grants
        self.personal_mode = PersonalMode(persistence)
        self._policy_generation = self.personal_mode.generation

    def _sync_policy(self):
        if self._policy_generation != self.personal_mode.generation:
            self._invalidate('Политика доступа изменилась. Повтори поиск и подтверждение.')
            self._folder_grant = None
            self._policy_generation = self.personal_mode.generation

    def _invalidate(self, reason):
        self._invalidations.update((key, (item.owner, reason)) for key, item in self._selected.items())
        while len(self._invalidations) > 256:
            self._invalidations.pop(next(iter(self._invalidations)))
        self._selected.clear()
        self._grants.clear()

    def personal_info(self):
        return self.personal_mode.public()

    def set_personal_mode(self, enabled, roots=()):
        with self._lock, self.personal_mode._lock:
            self.personal_mode.set(enabled, roots)
            # IDs issued under an old scope cannot become grants for a new scope.
            self._invalidate('Разрешение на область чтения изменилось. Проверь режим личного компьютера и разрешённые папки; повтори поиск.')

    def known_app_launch_allowed(self):
        return self.personal_mode.mode == 'full_user' and self.personal_mode.enabled()

    @staticmethod
    def _open(path):
        if os.name != 'nt':
            raise FileAccessError('Открытие документов поддерживается только в Windows.')
        from .apps import _open_document
        _open_document(path)

    def folder_info(self):
        with self._lock, self.personal_mode._lock:
            self._sync_policy()
            folder = _checked(self.folder_provider())
            if not folder.is_dir():
                raise FileAccessError('Папка Загрузки недоступна.')
            identity = _identity(folder)
            fingerprint = hashlib.sha256(repr((str(folder), identity)).encode()).hexdigest()
            return {'path': str(folder), 'fingerprint': fingerprint,
                    'allowed': self._folder_grant == (folder, identity) or self.personal_mode.allows(folder), 'recursive': False}

    def set_folder_permission(self, allowed, fingerprint):
        with self._lock, self.personal_mode._lock:
            if type(allowed) is not bool:
                raise FileAccessError('Нужно явное разрешение.')
            if not allowed:
                self.personal_mode.set_folder_permission(_checked(self.folder_provider()), False)
                self._folder_grant = None
                self._invalidate('Разрешение на чтение системной папки Загрузки отозвано. Разреши чтение папки в настройках и повтори поиск.')
                return
            folder = _checked(self.folder_provider())
            with _locked_path(folder, True):
                identity = _identity(_checked(folder))
                expected = hashlib.sha256(repr((str(folder), identity)).encode()).hexdigest()
                if fingerprint != expected:
                    raise FileAccessError('Папка изменилась. Проверь разрешение повторно.')
                self.personal_mode.set_folder_permission(folder, True)
                self._folder_grant = folder, identity

    def _folder(self):
        self._sync_policy()
        folder = _checked(self.folder_provider())
        if not self.personal_mode.allows(folder, 'search'):
            self._folder_grant = None
            raise FileAccessError('Сначала разреши чтение системной папки Загрузки.')
        self.personal_mode.check_file(folder, 'search')
        return folder

    def find_latest(self, owner):
        action = 'files.find_latest_pdf_in_downloads'
        try:
            with self._lock, self.personal_mode._lock:
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
                                self.personal_mode.check_file(path, 'search')
                            except (FileAccessError, OSError):
                                continue
                            candidates.append((item.stat(follow_symlinks=False).st_mtime_ns, item.name.casefold(), item.name, path))
                    if not candidates:
                        return refused(action, None, 'PDF в разрешённой папке Загрузки не найден.', status='not_found')
                    # Greatest modified time; ties use smallest casefold/name.
                    path = sorted(candidates, key=lambda x: (-x[0], x[1], x[2]))[0][3]
                    with _locked_path(path):
                        _checked(path)
                        stamp, digest = self._search_snapshot(path)
                    selected = SelectedFile(secrets.token_urlsafe(24), owner, path, stamp, digest)
                    if len(self._selected) >= 128:
                        raise FileAccessError('Список выбранных файлов заполнен. Отзови доступ к папке для сброса.')
                    self._selected[selected.id] = selected
                    return ActionResult(True, action, selected.id, 'observed', 'selected_pdf',
                        status_text=f'Последний по времени изменения PDF: {path.name}. Изменён: {selected.public()["modified_at"]}. Путь: {path}. Это время изменения, а не скачивания.',
                        data=selected.public())
        except (OSError, ValueError, RuntimeError):
            return refused(action, None, 'Не удалось безопасно прочитать PDF. Проверь разрешение на Загрузки и состояние файла.')

    def _search_snapshot(self, path):
        if self.personal_mode.allows(path, 'read'):
            self.personal_mode.check_file(path, 'read')
            return _fingerprint(path)
        self.personal_mode.check_file(path, 'search')
        return _metadata_stamp(path), None

    def _verify_selected(self, selected):
        path = _checked(selected.path)
        if selected.digest is None:
            return _metadata_stamp(path) == selected.stamp
        return _fingerprint(path) == (selected.stamp, selected.digest)

    def _selection(self, owner, file_id, operation='search'):
        from .personal_permissions import ordinary_path
        self._sync_policy()
        selected = self._selected.get(file_id)
        if selected is None or selected.owner != owner:
            invalidated = self._invalidations.get(file_id)
            if invalidated and invalidated[0] == owner:
                raise FileAccessError(invalidated[1])
            raise FileAccessError('Выбери документ в этом разговоре повторно.')
        if not ordinary_path(selected.path):
            raise FileAccessError('Секретные и системные файлы исключены из доступа.')
        self.personal_mode.check_file(selected.path, operation,
            legacy=operation == 'open' and file_id in self._grants and self.personal_mode.allows(selected.path, 'read'))
        return selected

    def selected_info(self, owner, file_id):
        with self._lock, self.personal_mode._lock:
            selected = self._selection(owner, file_id)
            with _locked_path(selected.path):
                if not self._verify_selected(selected):
                    self._grants.discard(file_id)
                    raise FileAccessError('Файл изменился. Найди его повторно.')
                return {**selected.public(), 'open_allowed': file_id in self._grants or self.personal_mode.allows(selected.path, 'open')}

    def set_open_permission(self, owner, file_id, allowed):
        with self._lock, self.personal_mode._lock:
            if not allowed:
                self._grants.discard(file_id)
                return
            selected = self._selection(owner, file_id)
            self.personal_mode.check_file(selected.path, 'open', legacy=True)
            with _locked_path(selected.path):
                if not self._verify_selected(selected):
                    self._grants.discard(file_id)
                    raise FileAccessError('PDF изменился. Найди и разреши файл повторно.')
                self._grants.add(file_id)

    def open_selected(self, owner, file_id):
        action = 'files.open_selected_file'
        try:
            with self._lock, self.personal_mode._lock:
                selected = self._selection(owner, file_id, 'open')
                if file_id not in self._grants and not self.personal_mode.allows(selected.path, 'open'):
                    return refused(action, file_id, 'Разреши открытие этого документа в настройках файлов или включи режим личного компьютера.', status='permission_required')
                with _locked_path(selected.path):
                    self._selection(owner, file_id, 'open')
                    if not self._verify_selected(selected):
                        self._grants.discard(file_id)
                        raise FileAccessError('Файл изменился.')
                    self.opener(selected.path)
                    self.personal_mode.record('open', selected.path, 'request_accepted')
                    observed = self.observer(selected.path) if self.observer else None
                    if observed:
                        return ActionResult(True, action, file_id, 'observed', observed_state='visible_window',
                            status_text=f'Окно документа {selected.path.name} обнаружено.', data=selected.public())
                    return ActionResult(True, action, file_id, 'request_accepted',
                        status_text=f'Команда открытия {selected.path.name} передана Windows; появление окна не проверено.',
                        data=selected.public())
        except (OSError, ValueError, RuntimeError) as exc:
            reason = str(exc) if isinstance(exc, FileAccessError) else 'Не удалось безопасно открыть выбранный документ. Найди и разреши файл повторно.'
            return refused(action, file_id, reason, status='permission_required' if 'разреш' in reason.lower() else 'denied')

    def _scopes(self, scope):
        if scope == 'downloads':
            return [self._folder()]
        roots = self.personal_mode.roots()
        if scope == 'all':
            # Avoid duplicate enumeration of nested grants.
            paths = list(roots.values())
            return [root for root in paths if not any(other in root.parents for other in paths)]
        if scope not in roots:
            raise FileAccessError('Выбери папку из разрешённых областей поиска.')
        return [roots[scope]]

    def search(self, owner, query='', extensions=None, scope='downloads', sort_by='modified', order='desc',
               recursive=False, limit=10, min_size=None, max_size=None):
        """Only declared scope IDs and data filters are accepted; no executable paths.

        A truncated or inaccessible scan never establishes a global oldest/newest.
        Results are references to immutable identities, not model-supplied paths.
        """
        from .personal_permissions import ordinary_path
        action, started = 'files.search', time.monotonic()
        try:
            if (not isinstance(owner, str) or not owner or not isinstance(query, str) or len(query) > 500
                    or sort_by not in ('modified', 'created', 'size', 'name') or order not in ('asc', 'desc')
                    or type(recursive) is not bool or type(limit) is not int or not 1 <= limit <= 20
                    or not isinstance(scope, str)):
                raise FileAccessError('Некорректные параметры поиска.')
            for bound in (min_size, max_size):
                if bound is not None and (type(bound) is not int or bound < 0 or bound > 64 * 1024 * 1024):
                    raise FileAccessError('Предел размера должен быть от 0 до 64 МиБ.')
            if min_size is not None and max_size is not None and min_size > max_size:
                raise FileAccessError('Минимальный размер больше максимального.')
            if extensions is None:
                extensions = READABLE_EXTENSIONS
            if not isinstance(extensions, (tuple, list, set, frozenset)) or not 1 <= len(extensions) <= len(READABLE_EXTENSIONS):
                raise FileAccessError('Укажи поддерживаемые расширения документов.')
            extensions = {'.' + x.lower().lstrip('.') for x in extensions if isinstance(x, str)}
            if not extensions or not extensions <= READABLE_EXTENSIONS:
                raise FileAccessError('Исполняемые и неподдерживаемые файлы исключены.')
            stop = {'найди', 'найти', 'файл', 'файлы', 'документ', 'документы', 'папке', 'самый',
                    'последний', 'старый', 'новый', 'pdf', 'downloads', 'скачал', 'который', 'пожалуйста', 'мне'}
            terms = [x for x in re.findall(r'[\w-]+', query.casefold().replace('ё', 'е')) if x not in stop and len(x) > 1]
            with self._lock, self.personal_mode._lock:
                roots = self._scopes(scope)
                self._sync_policy()
                if recursive and not self.personal_mode.enabled():
                    raise FileAccessError('Вложенные папки требуют режима личного компьютера.')
                deadline, visited, rejected, candidates = started + 10, 0, 0, []
                pending = [(root, 0) for root in roots]
                while pending:
                    folder, depth = pending.pop()
                    if depth > 32 or time.monotonic() > deadline:
                        raise FileAccessError('Поиск неполный: превышен предел времени или глубины. Выбери более узкую папку.')
                    with _locked_path(folder, True):
                        _checked(folder)
                        self.personal_mode.check_file(folder, 'search')
                        with os.scandir(folder) as entries:
                            for item in entries:
                                visited += 1
                                if visited > 20000 or time.monotonic() > deadline:
                                    raise FileAccessError('Поиск неполный: больше 20000 объектов или 10 секунд. Выбери более узкую папку.')
                                path = Path(item.path)
                                if not ordinary_path(path):
                                    rejected += 1
                                    continue
                                if not self.personal_mode.allows(path, 'search'):
                                    rejected += 1
                                    continue
                                if item.is_dir(follow_symlinks=False):
                                    if recursive:
                                        try:
                                            _checked(path)
                                            pending.append((path, depth + 1))
                                        except (OSError, ValueError):
                                            rejected += 1
                                    continue
                                if path.suffix.casefold() not in extensions or not item.is_file(follow_symlinks=False):
                                    continue
                                try:
                                    _checked(path)
                                    info = item.stat(follow_symlinks=False)
                                except (OSError, ValueError):
                                    rejected += 1
                                    continue
                                if info.st_size > 64 * 1024 * 1024 or (min_size is not None and info.st_size < min_size) or (max_size is not None and info.st_size > max_size):
                                    continue
                                name = path.name.casefold().replace('ё', 'е')
                                if terms and not all(term in name for term in terms):
                                    continue
                                created = getattr(info, 'st_birthtime_ns', info.st_ctime_ns if os.name == 'nt' else None)
                                if sort_by == 'created' and created is None:
                                    raise FileAccessError('На этом диске время создания недоступно; выбери время изменения.')
                                value = {'modified': info.st_mtime_ns, 'created': created, 'size': info.st_size, 'name': name}[sort_by]
                                candidates.append((path, value, created))
                # Stable tie order independent of platform directory enumeration.
                candidates.sort(key=lambda row: (row[0].name.casefold(), str(row[0])))
                candidates.sort(key=lambda row: row[1], reverse=order == 'desc')
                if not candidates:
                    self.personal_mode.record('search', scope, 'not_found')
                    return refused(action, None, 'Подходящие документы в выбранной области не найдены.', status='not_found')
                if len(self._selected) + min(limit, len(candidates)) > 256:
                    raise FileAccessError('Слишком много выбранных файлов. Начни новый сеанс доступа.')
                files, selections = [], []
                for path, _, created in candidates[:limit]:
                    if time.monotonic() > started + 20:
                        raise FileAccessError('Проверка результатов превысила 20 секунд. Сузь поиск.')
                    with _locked_path(path):
                        stamp, digest = self._search_snapshot(_checked(path))
                    selected = SelectedFile(secrets.token_urlsafe(24), owner, path, stamp, digest, created)
                    selections.append(selected)
                    files.append(selected.public())
                if time.monotonic() > started + 20:
                    raise FileAccessError('Проверка результатов превысила 20 секунд. Сузь поиск.')
                self._selected.update((selected.id, selected) for selected in selections)
                self.personal_mode.record('search', scope, 'observed')
                label = {'modified': 'времени изменения (не скачивания)', 'created': 'времени создания',
                         'size': 'размеру', 'name': 'названию'}[sort_by]
                first = files[0]
                text = '\n'.join(f'{row["filename"]} — {row["modified_at"]}; {row["size_bytes"]} байт; {row["path"]}' for row in files)
                return ActionResult(True, action, first['file_id'], 'observed', 'files_selected',
                    duration_ms=round((time.monotonic() - started) * 1000),
                    status_text=f'Сортировка по {label}, {"возрастание" if order == "asc" else "убывание"}.\n{text}',
                    data={**first, 'files': files, 'sort_by': sort_by, 'order': order, 'scope': scope,
                          'scan_complete': True, 'visited': visited, 'excluded': rejected, 'total_matches': len(candidates)})
        except (OSError, ValueError, RuntimeError) as exc:
            self.personal_mode.record('search', str(scope), 'denied')
            reason = str(exc) if isinstance(exc, FileAccessError) else 'Не удалось полностью и безопасно прочитать область поиска.'
            return refused(action, None, reason, status='permission_required' if 'разреш' in reason.casefold() or 'выключен' in reason else 'denied')

    def list_directory(self, target):
        from .generation import check_cancelled
        action = 'files.list_directory'
        path = Path(target)
        if (not path.is_absolute() or target.startswith(('\\\\', '//')) or '..' in path.parts
                or ':' in target[len(path.drive):] or any(c in '<>|*?"' or ord(c) < 32 for c in target)
                or any(part.rstrip(' .') != part for part in path.parts if part != path.anchor)):
            return refused(action, None, 'Укажи полный локальный путь к папке.', status='invalid_target')
        limit, scan_limit = 50, 2000
        deadline = time.monotonic() + 5
        entries, seen, complete = [], 0, True
        try:
            with self._lock, self.personal_mode._lock:
                self._sync_policy()
                try:
                    self.personal_mode.check_file(path, 'search')
                except FileAccessError as exc:
                    return refused(action, str(path), str(exc) + ' Для просмотра папки нужно разрешение «Поиск».',
                                   status='permission_required')
                _checked(path)
                if not path.is_dir():
                    return refused(action, str(path), 'Указанный путь ведёт к файлу. Укажи папку.', status='invalid_target')
                with _locked_path(path, directory=True), os.scandir(path) as children:
                    for child in children:
                        check_cancelled()
                        if seen >= scan_limit or time.monotonic() > deadline:
                            complete = False
                            break
                        seen += 1
                        if not self.personal_mode.allows(Path(child.path), 'search'):
                            continue
                        try:
                            # Windows DirEntry.stat may report st_nlink=0.
                            info = os.stat(child.path, follow_symlinks=False)
                        except OSError:
                            continue
                        if getattr(info, 'st_file_attributes', 0) & 0x400:
                            continue
                        is_dir = stat.S_ISDIR(info.st_mode)
                        if not is_dir and (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1):
                            continue
                        entries.append({'name': child.name, 'kind': 'directory' if is_dir else 'file',
                                        'size_bytes': None if is_dir else info.st_size,
                                        'modified_utc': datetime.fromtimestamp(info.st_mtime, timezone.utc).isoformat()})
                entries.sort(key=lambda row: (row['kind'] != 'directory', row['name'].casefold(), row['name']))
                self.personal_mode.record('search', path, 'observed')
                return ActionResult(True, action, str(path), 'observed', 'directory_entries',
                    status_text='Содержимое папки проверено.',
                    data={'directory_name': path.name or path.anchor, 'entries': entries[:limit],
                          'files_count': sum(row['kind'] == 'file' for row in entries) if complete else None,
                          'directories_count': sum(row['kind'] == 'directory' for row in entries) if complete else None,
                          'empty': complete and seen == 0, 'scan_complete': complete,
                          'truncated': not complete or len(entries) > limit})
        except FileNotFoundError:
            reason, status = 'Папка не найдена. Проверь путь.', 'not_found'
        except PermissionError:
            reason, status = 'Windows не разрешила просмотреть папку. Проверь права текущего пользователя.', 'denied'
        except (OSError, FileAccessError) as exc:
            reason = str(exc) if isinstance(exc, FileAccessError) else 'Не удалось безопасно просмотреть папку.'
            status = 'denied'
        self.personal_mode.record('search', path, status, reason)
        return refused(action, str(path), reason, status=status)

    def read_file(self, owner, scope, relative_path):
        """Exact scoped read; scope/relative_path must be grounded by the caller."""
        action = 'files.read_file'
        try:
            if not isinstance(owner, str) or not owner or not isinstance(relative_path, str) or not 1 <= len(relative_path) <= 1024:
                raise FileAccessError('Некорректная цель чтения.')
            relative = Path(relative_path)
            if (relative.is_absolute() or relative.drive or '..' in relative.parts
                    or ':' in relative_path or '\x00' in relative_path):
                raise FileAccessError('Нужен точный относительный путь внутри разрешённой области.')
            with self._lock, self.personal_mode._lock:
                self._sync_policy()
                roots = self.personal_mode.roots()
                if scope not in roots:
                    raise FileAccessError('Область чтения не разрешена. Проверь настройки доступа.')
                path = roots[scope] / relative
                if roots[scope] not in path.parents or path.suffix.casefold() not in READABLE_EXTENSIONS:
                    raise FileAccessError('Нужен поддерживаемый документ внутри разрешённой области.')
                self.personal_mode.check_file(path, 'read')
                _checked(path)  # Report absence after authorization, before Windows handle errors.
                with _locked_path(path):
                    _checked(path)
                    self.personal_mode.check_file(path, 'read')
                    if path.stat().st_size > 10 * 1024 * 1024:
                        raise FileAccessError('Для извлечения текста выбери документ до 10 МиБ.')
                    stamp, digest = _fingerprint(path)
                    if len(self._selected) >= 256:
                        raise FileAccessError('Слишком много выбранных файлов. Начни новый сеанс доступа.')
                    selected = SelectedFile(secrets.token_urlsafe(24), owner, path, stamp, digest)
                    self._selected[selected.id] = selected
                    return replace(self.read_selected(owner, selected.id), action=action)
        except (OSError, ValueError, RuntimeError) as exc:
            missing = isinstance(exc, FileNotFoundError)
            reason = 'Указанный файл не найден.' if missing else str(exc) if isinstance(exc, FileAccessError) else 'Не удалось безопасно прочитать указанный файл.'
            self.personal_mode.record('read', str(scope), 'denied', reason)
            return refused(action, None, reason, status='not_found' if missing else 'permission_required' if 'разреш' in reason.lower() else 'denied')

    def read_selected(self, owner, file_id, query='', budget=12000):
        from .attachments import AttachmentError, extract_document, choose_document_text
        action = 'files.read_selected_file'
        try:
            if not isinstance(query, str) or len(query) > 2000 or type(budget) is not int or not 1000 <= budget <= 32000:
                raise FileAccessError('Некорректный запрос к документу.')
            with self._lock, self.personal_mode._lock:
                selected = self._selection(owner, file_id, 'read')
                with _locked_path(selected.path):
                    self._selection(owner, file_id, 'read')
                    if not self._verify_selected(selected):
                        raise FileAccessError('Файл изменился. Найди его повторно.')
                    if selected.stamp[2] > 10 * 1024 * 1024:
                        raise FileAccessError('Для извлечения текста выбери документ до 10 МиБ.')
                    data = selected.path.read_bytes()
                    name = selected.path.name
                    if selected.path.suffix.casefold() == '.markdown':
                        name += '.md'
                    elif selected.path.suffix.casefold() == '.tsv':
                        name += '.txt'
                    document = extract_document(data, name)
                text = choose_document_text(document.text, query, budget)
                self.personal_mode.record('read', selected.path, 'observed')
                return ActionResult(True, action, file_id, 'observed', 'text_extracted',
                    status_text=f'Прочитан документ {selected.path.name}.',
                    data={**selected.public(), 'text': text, 'untrusted_document': True,
                          'characters': len(text), 'truncated': document.truncated or len(text) < len(document.text),
                          'retained_characters': len(document.text)})
        except (OSError, ValueError, RuntimeError) as exc:
            self.personal_mode.record('read', str(file_id), 'denied')
            reason = str(exc) if isinstance(exc, (FileAccessError, AttachmentError)) else 'Не удалось безопасно прочитать документ.'
            return refused(action, file_id, reason, status='permission_required' if 'разреш' in reason.lower() else 'denied')


from .paths import PRIVATE
from .settings import ROOT
file_access = FileAccess(persistence=PRIVATE / 'personal_mode.json')
