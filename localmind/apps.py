"""Read-only Windows app discovery and explicit, fingerprint-bound permissions.

Discovery metadata never becomes a command line. Only a local PE executable with
no arguments can be selected; the source and executable are checked again before
each launch. Permissions are deliberately session-only and start denied.
"""
from __future__ import annotations

from contextlib import contextmanager
import ctypes
from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import re
import struct
import subprocess
import threading
import time
import unicodedata
from typing import Callable, Iterable
import uuid

from .windows_state import launch_coordinator


class AppError(Exception):
    """Safe, user-visible catalog refusal (never contains arbitrary exceptions)."""


def normalize_name(value: str) -> str:
    value = unicodedata.normalize('NFKC', value).casefold().replace('ё', 'е')
    return ' '.join(re.sub(r'[^\w\s-]', ' ', value).split())


# GUI application names are aliases only after an executable was discovered.
KNOWN_ALIASES = {
    'code': ('Visual Studio Code', 'VS Code', 'vscode', 'вс код'),
    'obsidian': ('Obsidian', 'обсидиан'),
    'discord': ('Discord', 'дискорд'),
    'codex': ('Codex', 'кодекс'),
    'chrome': ('Chrome', 'гугл хром'),
    'firefox': ('Firefox', 'файрфокс'),
    'msedge': ('Microsoft Edge', 'Edge', 'эдж'),
    'steam': ('Steam', 'стим'),
}
# Conservative supported GUI set. A new executable needs an explicit code review,
# rather than letting an arbitrary discovered utility become a launch capability.
SUPPORTED_GUI_EXECUTABLES = {
    'code', 'obsidian', 'discord', 'codex', 'chrome', 'firefox', 'msedge',
    '7zfm', 'winword', 'excel', 'powerpnt', 'mspub', 'msaccess', 'onenote',
    'outlook', 'thunderbird', 'vlc', 'obs64', 'mspaint', 'paintdotnet',
    'gimp', 'gimp-3', 'inkscape', 'blender', 'sumatrapdf', 'acrord32',
    'notepad++', 'pycharm64', 'idea64', 'webstorm64', 'rider64', 'clion64',
    'steam', 'telegram', 'ayugram', 'modrinth app', 'zen', 'notepad', 'calc',
}
DENIED_EXECUTABLES = {
    'cmd', 'powershell', 'pwsh', 'wscript', 'cscript', 'mshta', 'rundll32',
    'regsvr32', 'reg', 'schtasks', 'wmic', 'wsl', 'bash', 'sh', 'zsh',
    'python', 'pythonw', 'py', 'node', 'npm', 'npx', 'java', 'javaw', 'perl',
    'ruby', 'php', 'explorer', 'control', 'mmc', 'msiexec', 'winget', 'curl',
    'wget', 'certutil', 'bitsadmin', 'installutil', 'dotnet', 'conhost',
    'terminal', 'wt', 'update', 'updater', 'setup', 'install', 'uninstall',
}


def _safe_local_path(raw: str | Path) -> Path:
    text = str(raw)
    if not text or len(text) > 32760 or '\x00' in text:
        raise AppError('Недопустимый путь приложения.')
    # Network/device namespace paths and alternate data streams are refused.
    if text.startswith(('\\\\', '//')) or ':' in text[2:]:
        raise AppError('Сетевые пути и потоки файлов не разрешены.')
    path = Path(text)
    if not path.is_absolute():
        raise AppError('Нужен абсолютный локальный путь.')
    try:
        resolved = path.resolve(strict=True)
        if not resolved.is_file():
            raise AppError('Файл приложения не найден.')
    except (OSError, RuntimeError) as exc:
        raise AppError('Файл приложения не найден.') from exc
    if str(resolved).startswith(('\\\\', '//')):
        raise AppError('Сетевой путь не разрешён.')
    return resolved


def _digest(path: Path, maximum: int = 512 * 1024 * 1024) -> str:
    try:
        if path.stat().st_size > maximum:
            raise AppError('Файл слишком велик для безопасной проверки.')
        h = hashlib.sha256()
        consumed = 0
        with path.open('rb') as handle:
            for block in iter(lambda: handle.read(1024 * 1024), b''):
                consumed += len(block)
                if consumed > maximum:
                    raise AppError('Файл вырос во время проверки; операция отменена.')
                h.update(block)
        return h.hexdigest()
    except OSError as exc:
        raise AppError('Не удалось проверить файл приложения.') from exc


def validate_executable(raw: str | Path, arguments: str = '') -> Path:
    if arguments.strip():
        raise AppError('Ярлыки с аргументами не разрешены.')
    path = _safe_local_path(raw)
    stem = path.stem.casefold()
    if path.suffix.casefold() != '.exe' or stem in DENIED_EXECUTABLES:
        raise AppError('Скрипты, оболочки и системные запускатели не разрешены.')
    if re.search(r'(?:unins|uninst|uninstall|installer|setup)', stem):
        raise AppError('Установщики и удаление программ не разрешены.')
    # Never treat Codex CLI as the desktop application.
    if stem == 'codex' and any(p.casefold() in ('bin', 'npm', 'node_modules') for p in path.parts):
        raise AppError('Codex CLI не является настольным приложением.')
    try:
        with path.open('rb') as handle:
            header = handle.read(64)
            if len(header) < 64 or header[:2] != b'MZ':
                raise AppError('Цель не является Windows-приложением.')
            offset = struct.unpack_from('<I', header, 60)[0]
            if offset > 1024 * 1024:
                raise AppError('Некорректный исполняемый файл.')
            handle.seek(offset)
            pe_header = handle.read(24)
            if len(pe_header) < 24 or pe_header[:4] != b'PE\x00\x00':
                raise AppError('Цель не является Windows-приложением.')
            optional_size = struct.unpack_from('<H', pe_header, 20)[0]
            optional = handle.read(70)
            if optional_size < 70 or len(optional) != 70:
                raise AppError('Некорректный заголовок Windows-приложения.')
            magic = struct.unpack_from('<H', optional, 0)[0]
            subsystem = struct.unpack_from('<H', optional, 68)[0]
            if magic not in (0x10B, 0x20B) or subsystem != 2:
                raise AppError('Разрешены только настольные GUI приложения, не CLI.')
    except OSError as exc:
        raise AppError('Не удалось прочитать приложение.') from exc
    return path


class _GUID(ctypes.Structure):
    _fields_ = [('data', ctypes.c_ubyte * 16)]

    def __init__(self, value: str):
        super().__init__()
        self.data[:] = uuid.UUID(value).bytes_le


def _read_shortcut(path: Path) -> tuple[str, str]:
    """Read IShellLinkW without Resolve (no searching, UI or network tracking)."""
    if os.name != 'nt':
        raise AppError('Каталог ярлыков доступен только в Windows.')
    ole = ctypes.WinDLL('ole32')
    result = ole.CoInitializeEx(None, 2)
    initialized = result in (0, 1)
    if result < 0 and result != -2147417850:  # RPC_E_CHANGED_MODE
        raise AppError('Не удалось прочитать ярлык Windows.')
    link, persist = ctypes.c_void_p(), ctypes.c_void_p()

    def method(pointer, index, arguments):
        table = ctypes.cast(pointer, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
        return ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, *arguments)(table[index])

    try:
        clsid = _GUID('00021401-0000-0000-C000-000000000046')
        iid = _GUID('000214F9-0000-0000-C000-000000000046')
        hr = ole.CoCreateInstance(ctypes.byref(clsid), None, 1, ctypes.byref(iid), ctypes.byref(link))
        if hr < 0:
            raise AppError('Не удалось прочитать ярлык Windows.')
        persist_iid = _GUID('0000010b-0000-0000-C000-000000000046')
        hr = method(link, 0, [ctypes.POINTER(_GUID), ctypes.POINTER(ctypes.c_void_p)])(
            link, ctypes.byref(persist_iid), ctypes.byref(persist))
        if hr < 0:
            raise AppError('Не удалось прочитать ярлык Windows.')
        hr = method(persist, 5, [ctypes.c_wchar_p, ctypes.c_ulong])(persist, str(path), 0)
        if hr < 0:
            raise AppError('Не удалось загрузить ярлык Windows.')
        target, arguments = ctypes.create_unicode_buffer(32768), ctypes.create_unicode_buffer(32768)
        hr = method(link, 3, [ctypes.c_wchar_p, ctypes.c_int, ctypes.c_void_p, ctypes.c_ulong])(
            link, target, len(target), None, 4)
        if hr < 0:
            raise AppError('В ярлыке нет безопасной локальной цели.')
        hr = method(link, 10, [ctypes.c_wchar_p, ctypes.c_int])(link, arguments, len(arguments))
        if hr < 0:
            raise AppError('Не удалось проверить аргументы ярлыка.')
        return target.value, arguments.value
    finally:
        for pointer in (persist, link):
            if pointer.value:
                method(pointer, 2, [])(pointer)
        if initialized:
            ole.CoUninitialize()


def _known_roots() -> list[Path]:
    if os.name != 'nt':
        return []
    roots = []
    shell = ctypes.WinDLL('shell32')
    for value in (
        '625B53C3-AB48-4EC1-BA1F-A1EF4146FC19',  # user Start Menu
        'A4115719-D62E-491D-AA7C-E74B8BE3B067',  # common Start Menu
        'B4BFCC3A-DB2C-424C-B029-7FE99A87C641',  # user Desktop
        'C4AA340D-F20F-4863-AFEF-F87EF2E6BA25',  # public Desktop
    ):
        guid, pointer = _GUID(value), ctypes.c_void_p()
        if shell.SHGetKnownFolderPath(ctypes.byref(guid), 0, None, ctypes.byref(pointer)) >= 0:
            try:
                roots.append(Path(ctypes.wstring_at(pointer)))
            finally:
                ctypes.WinDLL('ole32').CoTaskMemFree(pointer)
    return roots


@dataclass(frozen=True)
class AppSource:
    key: str
    name: str
    read: Callable[[], tuple[str, str, str]]  # target, arguments, source digest


def _shortcut_source(path: Path) -> AppSource:
    def read():
        source = _safe_local_path(path)
        if path.is_symlink() or source != path.absolute():
            raise AppError('Подменённый ярлык не разрешён.')
        before = _digest(source, 1024 * 1024)
        target, arguments = _read_shortcut(source)
        if before != _digest(source, 1024 * 1024):
            raise AppError('Ярлык изменился во время проверки.')
        return target, arguments, before
    return AppSource('shortcut:' + str(path).casefold(), path.stem, read)


def discover_sources() -> Iterable[AppSource]:
    """Bounded read-only scan; never follows directory reparse points."""
    if os.name != 'nt':
        return
    seen = 0
    for root in _known_roots():
        for directory, dirs, files in os.walk(root, followlinks=False):
            depth = len(Path(directory).relative_to(root).parts)
            dirs[:] = [d for d in dirs if depth < 6 and not _is_reparse(Path(directory) / d)]
            for filename in sorted(files):
                seen += 1
                if seen > 5000:
                    return
                if filename.casefold().endswith('.lnk'):
                    yield _shortcut_source(Path(directory) / filename)
    yield from _registry_sources()


def _is_reparse(path: Path) -> bool:
    try:
        return bool(getattr(path.lstat(), 'st_file_attributes', 0) & 0x400) or path.is_symlink()
    except OSError:
        return True


def _registry_sources() -> Iterable[AppSource]:
    import winreg
    base = r'Software\Microsoft\Windows\CurrentVersion\App Paths'
    for hive_name, hive in (('HKCU', winreg.HKEY_CURRENT_USER), ('HKLM', winreg.HKEY_LOCAL_MACHINE)):
        for view in (winreg.KEY_WOW64_64KEY, winreg.KEY_WOW64_32KEY):
            try:
                with winreg.OpenKey(hive, base, 0, winreg.KEY_READ | view) as key:
                    names = [winreg.EnumKey(key, i) for i in range(min(winreg.QueryInfoKey(key)[0], 512))]
            except OSError:
                continue
            for name in names:
                def read(hive=hive, view=view, name=name):
                    try:
                        with winreg.OpenKey(hive, base + '\\' + name, 0, winreg.KEY_READ | view) as key:
                            raw, kind = winreg.QueryValueEx(key, None)
                        if kind != winreg.REG_SZ or not isinstance(raw, str):
                            raise AppError('Неподдерживаемая регистрация приложения.')
                        raw = raw.strip()
                        if raw.startswith('"') and raw.endswith('"'):
                            raw = raw[1:-1]
                        return raw, '', hashlib.sha256(raw.encode('utf-8')).hexdigest()
                    except OSError as exc:
                        raise AppError('Регистрация приложения изменилась.') from exc
                yield AppSource(f'registry:{hive_name}:{view}:{name.casefold()}', Path(name).stem, read)


@dataclass(frozen=True)
class AppEntry:
    id: str
    name: str
    target: Path
    aliases: tuple[str, ...]
    fingerprint: str
    source: AppSource


def _entry(source: AppSource) -> AppEntry:
    raw, arguments, source_digest = source.read()
    target = validate_executable(raw, arguments)
    if target.stem.casefold() not in SUPPORTED_GUI_EXECUTABLES:
        raise AppError('Это приложение пока не входит в проверенный каталог GUI.')
    target_digest = _digest(target)
    fingerprint = hashlib.sha256((source_digest + '\0' + str(target).casefold() + '\0' + target_digest).encode()).hexdigest()
    app_id = 'app-' + hashlib.sha256(source.key.encode()).hexdigest()[:20]
    name = source.name[:120]
    aliases = tuple(dict.fromkeys(normalize_name(item) for item in (
        name, target.stem, *KNOWN_ALIASES.get(target.stem.casefold(), ()), app_id,
    ) if normalize_name(item)))
    return AppEntry(app_id, name, target, aliases, fingerprint, source)


@contextmanager
def _launch_guard(target: Path):
    """Hold the Windows image against writes/deletion during CreateProcess."""
    handle = None
    if os.name == 'nt':
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.CreateFileW.argtypes = [ctypes.c_wchar_p, ctypes.c_ulong, ctypes.c_ulong,
                                      ctypes.c_void_p, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_void_p]
        kernel.CreateFileW.restype = ctypes.c_void_p
        kernel.CloseHandle.argtypes = [ctypes.c_void_p]
        handle = kernel.CreateFileW(str(target), 0x80000000, 1, None, 3, 0x80, None)
        if handle == ctypes.c_void_p(-1).value:
            raise AppError('Приложение занято или изменяется; запуск отменён.')
    try:
        yield
    finally:
        if handle is not None:
            kernel.CloseHandle(handle)


class AppCatalog:
    def __init__(self, source_provider: Callable[[], Iterable[AppSource]] = discover_sources,
                 refresh_interval: float = 0):
        self._source_provider = source_provider
        self._entries: dict[str, AppEntry] = {}
        self._permissions: dict[str, str] = {}
        self._lock = threading.RLock()
        self._refresh_lock = threading.Lock()
        self._refresh_interval = refresh_interval
        self._last_refresh = 0.0
        self._refreshed = False

    def refresh(self) -> list[dict]:
        if not self._refresh_lock.acquire(blocking=False):
            return self.entries()
        try:
            if self._refreshed and time.monotonic() - self._last_refresh < self._refresh_interval:
                return self.entries()
            return self._refresh()
        finally:
            self._refresh_lock.release()

    def _refresh(self) -> list[dict]:
        found = {}
        started = time.monotonic()
        for count, source in enumerate(self._source_provider()):
            if count >= 256 or time.monotonic() - started > 20:
                break
            try:
                entry = _entry(source)
                # Duplicate metadata for one target must not create ambiguity.
                existing = next((e for e in found.values() if e.target == entry.target), None)
                if existing is None:
                    found[entry.id] = entry
            except (AppError, OSError, ValueError):
                continue
        with self._lock:
            self._entries = found
            self._permissions = {key: fingerprint for key, fingerprint in self._permissions.items()
                                 if key in found and found[key].fingerprint == fingerprint}
            self._refreshed = True
            self._last_refresh = time.monotonic()
            return self.entries()

    def entries(self) -> list[dict]:
        with self._lock:
            return [{'id': item.id, 'name': item.name, 'target': str(item.target),
                     'aliases': list(item.aliases), 'fingerprint': item.fingerprint,
                     'allowed': self._permissions.get(item.id) == item.fingerprint}
                    for item in sorted(self._entries.values(), key=lambda item: item.name.casefold())]

    def aliases(self) -> dict[str, tuple[str, ...]]:
        with self._lock:
            if not self._refreshed:
                self.refresh()
            return {key: item.aliases for key, item in self._entries.items()}

    def resolve_alias(self, name: str) -> list[str]:
        normalized = normalize_name(name)
        return [key for key, aliases in self.aliases().items() if normalized in aliases]

    def _revalidate(self, app_id: str) -> AppEntry:
        entry = self._entries.get(app_id)
        if entry is None:
            raise AppError('Приложение не найдено в проверенном каталоге.')
        try:
            current = _entry(entry.source)
            if current.fingerprint != entry.fingerprint or current.target != entry.target:
                raise AppError('Цель приложения изменилась. Обнови каталог и разрешение.')
        except (AppError, OSError, ValueError) as exc:
            self._permissions.pop(app_id, None)
            raise AppError('Цель приложения изменилась. Обнови каталог и разрешение.') from exc
        return current

    def set_permission(self, app_id: str, allowed: bool, fingerprint: str) -> list[dict]:
        with self._lock:
            if not allowed:
                self._permissions.pop(app_id, None)
                return self.entries()
            entry = self._revalidate(app_id)
            if fingerprint != entry.fingerprint:
                raise AppError('Каталог изменился. Выбери приложение повторно.')
            self._permissions[app_id] = entry.fingerprint
            return self.entries()

    def launch(self, app_id: str) -> dict:
        started = time.perf_counter()
        target = app_id
        try:
            with self._lock:
                entry = self._revalidate(app_id)
                target = entry.name
                if self._permissions.get(app_id) != entry.fingerprint:
                    raise AppError('Сначала разреши это приложение в настройках.')
                with _launch_guard(entry.target):
                    self._revalidate(app_id)
                    result = launch_coordinator.launch(entry.target, target,
                        lambda: subprocess.Popen([str(entry.target)], shell=False, close_fds=True,
                                                 cwd=str(entry.target.parent)))
            return {**result.to_dict(), 'duration_ms': round((time.perf_counter() - started) * 1000, 2)}
        except (AppError, OSError) as exc:
            # Exception text is controlled here, OS errors/paths are not reflected.
            error = str(exc) if isinstance(exc, AppError) else 'Windows отклонила запуск приложения.'
            return {'success': False, 'action': 'open_app', 'resolved_target': target,
                    'execution_status': 'not_executed', 'observed_state': None,
                    'error': error, 'mode': 'REAL', 'duration_ms': round((time.perf_counter() - started) * 1000, 2),
                    'status_text': error}


catalog = AppCatalog(refresh_interval=2)
