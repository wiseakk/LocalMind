"""Read-only Windows app discovery and explicit, fingerprint-bound permissions.

Discovery metadata never becomes a command line. Only a local PE executable with
no arguments can be selected; the source and executable are checked again before
each launch. The owner-bound policy persists exact image grants and independently
controls launch, focus and safe close; model output cannot create a grant.
"""
from __future__ import annotations

from contextlib import contextmanager, ExitStack
import ctypes
from dataclasses import dataclass, replace
import json
import hashlib
import os
from pathlib import Path
import re
import struct
import subprocess
import sys
import threading
import time
import unicodedata
from typing import Callable, Iterable
import uuid
import xml.etree.ElementTree as ET

from .windows_state import launch_coordinator


class AppError(Exception):
    """Safe, user-visible catalog refusal (never contains arbitrary exceptions)."""


def normalize_name(value: str) -> str:
    value = unicodedata.normalize('NFKC', value).casefold().replace('ё', 'е')
    return ' '.join(re.sub(r'[^\w\s-]', ' ', value).split())


# GUI application names are aliases only after an executable was discovered.
KNOWN_ALIASES = {
    'notepad': ('notepad', 'блокнот', 'ноутпад'),
    'calc': ('calculator', 'калькулятор'),
    'calculator': ('calculator', 'калькулятор'),
    'calculatorapp': ('calculator', 'калькулятор'),
    'code': ('Visual Studio Code', 'VS Code', 'vscode', 'вс код'),
    'obsidian': ('Obsidian', 'обсидиан'),
    'discord': ('Discord', 'дискорд'),
    'codex': ('Codex', 'кодекс'),
    'chrome': ('Chrome', 'гугл хром'),
    'firefox': ('Firefox', 'файрфокс'),
    'msedge': ('Microsoft Edge', 'Edge', 'эдж'),
    'steam': ('Steam', 'стим'),
}
# Compatibility aliases for older callers. Admission is based on discovery
# evidence and the PE GUI subsystem, never membership in this set.
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
    'regedit', 'bcdedit', 'diskpart', 'dism', 'sfc', 'net', 'netsh', 'sc',
    'shutdown', 'format', 'systemsettingsadminflows', 'consent', 'runas',
    'taskmgr', 'cmstp', 'fodhelper', 'computerdefaults', 'eventvwr',
    'gcc', 'g++', 'gdb', 'git-bash', 'git-cmd', 'mintty', 'ssh', 'sshd',
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
    if any(part.rstrip(' .') != part for part in path.parts if part != path.anchor):
        raise AppError('Неоднозначный путь приложения запрещён.')
    try:
        for item in (path, *path.parents):
            if _is_reparse(item):
                raise AppError('Ссылки и reparse points приложения запрещены.')
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
    if (re.search(r'(?:^|[-_ ])(?:service|helper|crashpad|crashreporter|reset-settings)(?:$|[-_ ])', stem)
            or stem.endswith(('helper', 'server', 'service'))):
        raise AppError('Фоновый компонент не является запускаемым приложением.')
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


def _installation_roots():
    """Windows-provided installation areas, not model-supplied directories."""
    if os.name != 'nt':
        return ()
    from ctypes import wintypes as w
    shell, ole = ctypes.WinDLL('shell32'), ctypes.WinDLL('ole32')
    shell.SHGetKnownFolderPath.argtypes = [ctypes.c_void_p, w.DWORD, w.HANDLE, ctypes.POINTER(ctypes.c_void_p)]
    ole.CoTaskMemFree.argtypes = [ctypes.c_void_p]
    roots = []
    for value in ('905e63b6-c1bf-494e-b29c-65b732d3d21a',  # ProgramFiles
                  '7c5a40ef-a0fb-4bfc-874a-c0f2e0b9fa8e',  # ProgramFilesX86
                  'f1b32785-6fba-4fcf-9d55-7b8e7f157091'):  # current LocalAppData
        guid, pointer = _GUID(value), ctypes.c_void_p()
        if shell.SHGetKnownFolderPath(ctypes.byref(guid), 0, None, ctypes.byref(pointer)) >= 0:
            try:
                roots.append(Path(ctypes.wstring_at(pointer)).resolve(strict=True))
            finally:
                ole.CoTaskMemFree(pointer)
    return tuple(roots)


def _protected_app_roots():
    from .paths import APP_ROOT, DATA_ROOT
    return APP_ROOT, DATA_ROOT


def executable_identity(path):
    try:
        identity = path.stat()
        return (f'fileidentity:{identity.st_dev}:{identity.st_ino}',)
    except OSError:
        return ()


@dataclass(frozen=True)
class AppSource:
    key: str
    name: str
    read: Callable[[], tuple[str, str, str]]  # target, arguments, source digest
    origin: str = 'other'
    launch_type: str = 'win32'
    launch_id: str = ''
    icon: str = ''
    aliases: tuple[str, ...] = ()


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
    return AppSource('shortcut:' + str(path).casefold(), path.stem, read, 'shortcuts')


def discover_sources(report=None, portable_roots=()) -> Iterable[AppSource]:
    """Bounded read-only scan; never follows directory reparse points."""
    if sys.platform == 'linux':
        from .linux_apps import discover
        yield from discover(report)
        return
    if os.name != 'nt':
        if report is not None:
            report['unavailable_providers'].append('Windows')
        return
    seen = 0
    shortcut_started = time.monotonic()
    for root in _known_roots():
        for directory, dirs, files in os.walk(root, followlinks=False):
            if seen > 10000 or time.monotonic() - shortcut_started > 8:
                if report is not None:
                    report['truncated'] = True
                break
            depth = len(Path(directory).relative_to(root).parts)
            dirs[:] = [d for d in dirs if depth < 6 and not _is_reparse(Path(directory) / d)]
            for filename in sorted(files):
                seen += 1
                if seen > 10000:
                    if report is not None:
                        report['truncated'] = True
                    break
                if filename.casefold().endswith('.lnk'):
                    yield _shortcut_source(Path(directory) / filename)
    for name, provider in (
        ('app_paths', _registry_sources), ('uninstall', lambda: _uninstall_sources(report)),
        ('start_apps', _packaged_sources), ('steam', _steam_sources),
        ('running', _running_sources),
        ('portable', lambda: _portable_sources(portable_roots, report)),
    ):
        try:
            yield from provider()
        except (AppError, OSError, ValueError, ImportError, subprocess.SubprocessError):
            if report is not None:
                report['unavailable_providers'].append(name)


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
                    names = [winreg.EnumKey(key, i) for i in range(min(winreg.QueryInfoKey(key)[0], 4096))]
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
                yield AppSource(f'registry:{hive_name}:{view}:{name.casefold()}', Path(name).stem, read, 'app_paths')


def _file_source(path: Path, name: str, origin: str, *, evidence=None) -> AppSource:
    """A discovered file is still revalidated; a display icon is not evidence."""
    def read():
        actual = _safe_local_path(path)
        if evidence is not None:
            evidence()
        return str(actual), '', hashlib.sha256(str(actual).casefold().encode()).hexdigest()
    return AppSource(origin + ':' + str(path).casefold(), name[:120], read, origin)


def _walk_executables(root: Path, *, depth=2, limit=2000, report=None):
    if not root.is_absolute() or _is_reparse(root) or not root.is_dir():
        return
    scanned = 0
    started = time.monotonic()
    for directory, dirs, files in os.walk(root, followlinks=False):
        if time.monotonic() - started > 5:
            if report is not None:
                report['truncated'] = True
            return
        level = len(Path(directory).relative_to(root).parts)
        dirs[:] = sorted(d for d in dirs if level < depth and not _is_reparse(Path(directory) / d))
        for filename in sorted(files):
            scanned += 1
            if scanned > limit:
                if report is not None:
                    report['truncated'] = True
                return
            if filename.casefold().endswith('.exe'):
                yield Path(directory) / filename


def _portable_sources(roots, report=None):
    for root in roots:
        for path in _walk_executables(Path(root), depth=4, limit=10000, report=report):
            yield _file_source(path, path.stem, 'portable')


def _uninstall_sources(report=None):
    """Use installation directories, never UninstallString/DisplayIcon commands.

    A matching GUI image in the installation root is required. Redistributables,
    services and incidental helper binaries cannot become apps by their label.
    """
    import winreg
    base = r'Software\Microsoft\Windows\CurrentVersion\Uninstall'
    started = time.monotonic()
    for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        for view in (winreg.KEY_WOW64_64KEY, winreg.KEY_WOW64_32KEY):
            try:
                with winreg.OpenKey(hive, base, 0, winreg.KEY_READ | view) as key:
                    names = [winreg.EnumKey(key, i) for i in range(min(winreg.QueryInfoKey(key)[0], 4096))]
            except OSError:
                continue
            for name in names:
                if time.monotonic() - started > 12:
                    if report is not None:
                        report['truncated'] = True
                    return
                try:
                    with winreg.OpenKey(hive, base + '\\' + name, 0, winreg.KEY_READ | view) as key:
                        display, kind = winreg.QueryValueEx(key, 'DisplayName')
                        location, location_kind = winreg.QueryValueEx(key, 'InstallLocation')
                        try:
                            system_component = winreg.QueryValueEx(key, 'SystemComponent')[0]
                        except OSError:
                            system_component = 0
                    if (system_component or kind != winreg.REG_SZ or location_kind != winreg.REG_SZ
                            or not isinstance(display, str) or not isinstance(location, str)):
                        continue
                    root = Path(location.strip().strip('"'))
                    label = normalize_name(display).replace(' ', '')
                    for path in _walk_executables(root, depth=1, limit=512, report=report):
                        stem = normalize_name(path.stem).replace(' ', '')
                        folder = normalize_name(root.name).replace(' ', '')
                        if len(stem) >= 3 and (stem in label or label in stem or stem == folder):
                            yield _file_source(path, display, 'uninstall')
                except (OSError, ValueError):
                    continue


# Fixed, read-only discovery adapters. No registry/LLM/user text is interpolated
# into PowerShell, no profiles or policy changes, and no application is launched.
_PACKAGE_DISCOVERY = r"""
$ErrorActionPreference='Stop'; [Console]::OutputEncoding=[Text.UTF8Encoding]::new($false)
$start=@{}; Get-StartApps | Select-Object -First 4096 | ForEach-Object { $start[$_.AppID]=$_.Name }
$rows=@(Get-AppxPackage | Select-Object -First 1024 | ForEach-Object {
  $p=$_; try { $m=Get-AppxPackageManifest -Package $p.PackageFullName -ErrorAction Stop
    foreach($a in $m.Package.Applications.Application) {
      $id=$p.PackageFamilyName+'!'+$a.Id
      if($start.ContainsKey($id) -and $a.Executable) {
        [PSCustomObject]@{name=$start[$id]; id=$id; root=$p.InstallLocation; executable=[string]$a.Executable}
      }
    }
  } catch { }
}); ConvertTo-Json -InputObject $rows -Compress -Depth 3
"""
_RUNNING_DISCOVERY = r"""
$ErrorActionPreference='Stop'; [Console]::OutputEncoding=[Text.UTF8Encoding]::new($false)
$session=(Get-Process -Id $PID).SessionId
$rows=@(Get-Process | Where-Object { $_.SessionId -eq $session -and $_.MainWindowHandle -ne 0 } |
 Select-Object -First 512 | ForEach-Object { try { if($_.Path) {
 [PSCustomObject]@{name=$_.ProcessName; path=$_.Path} } } catch { } })
ConvertTo-Json -InputObject $rows -Compress -Depth 3
"""


def _powershell_rows(script):
    if os.name != 'nt':
        raise AppError('Требуется Windows.')
    system = Path(os.environ.get('SystemRoot', r'C:\Windows'))
    executable = system / 'System32' / 'WindowsPowerShell' / 'v1.0' / 'powershell.exe'
    # This adapter accepts only constants in this module, never caller code.
    if script not in (_PACKAGE_DISCOVERY, _RUNNING_DISCOVERY):
        raise AppError('Неизвестный адаптер обнаружения.')
    result = subprocess.run([str(executable), '-NoLogo', '-NoProfile', '-NonInteractive', '-Command', script],
                            shell=False, capture_output=True, timeout=12,
                            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    if result.returncode or len(result.stdout) > 8 * 1024 * 1024:
        raise AppError('Провайдер обнаружения Windows недоступен.')
    try:
        rows = json.loads(result.stdout.decode('utf-8-sig'))
        if not isinstance(rows, list) or len(rows) > 4096:
            raise ValueError('invalid rows')
        return rows
    except (UnicodeError, ValueError) as exc:
        raise AppError('Провайдер вернул неверные метаданные.') from exc


def _packaged_source(row):
    if not isinstance(row, dict):
        raise AppError('Неверная запись приложения Store.')
    name, app_id = row.get('name'), row.get('id')
    if (not isinstance(name, str) or not isinstance(app_id, str)
            or not re.fullmatch(r'[A-Za-z0-9_.-]{1,200}![A-Za-z0-9_.-]{1,100}', app_id)):
        raise AppError('Недопустимый идентификатор приложения Store.')
    root, relative = Path(row.get('root', '')), Path(row.get('executable', ''))
    if (not root.is_absolute() or relative.is_absolute() or not relative.parts
            or any(part in ('.', '..') for part in relative.parts)):
        raise AppError('Неверная цель пакета Store.')
    manifest = root / 'AppxManifest.xml'
    application_id = app_id.split('!', 1)[1]
    def read():
        document = _safe_local_path(manifest)
        if document.stat().st_size > 2 * 1024 * 1024:
            raise AppError('Слишком большой манифест Store.')
        raw = document.read_bytes()
        if b'<!DOCTYPE' in raw.upper() or b'<!ENTITY' in raw.upper():
            raise AppError('Неподдерживаемый манифест Store.')
        tree = ET.fromstring(raw)
        application = next((element for element in tree.iter()
                            if element.tag.rsplit('}', 1)[-1] == 'Application'
                            and element.get('Id') == application_id), None)
        if application is None or application.get('Executable') != str(relative):
            raise AppError('Регистрация приложения Store изменилась.')
        target = _safe_local_path(root / relative)
        if not target.is_relative_to(root.resolve(strict=True)):
            raise AppError('Цель Store выходит за каталог пакета.')
        return str(target), '', hashlib.sha256(raw + app_id.encode()).hexdigest()
    return AppSource('package:' + app_id, name[:120], read, 'start_apps', 'packaged', app_id)


def _packaged_sources():
    for row in _powershell_rows(_PACKAGE_DISCOVERY):
        try:
            yield _packaged_source(row)
        except (AppError, TypeError, ValueError):
            continue


def _running_sources():
    from .windows_state import inspect_application
    for row in _powershell_rows(_RUNNING_DISCOVERY):
        if not isinstance(row, dict):
            continue
        try:
            path = validate_executable(row.get('path', ''))
            # Get-Process is a candidate provider, not an ownership authority.
            if inspect_application(path).state == 'visible_window':
                yield _file_source(path, path.stem, 'running')
        except (AppError, AttributeError, TypeError):
            continue


def _steam_sources():
    """Read installed manifests; only a fixed numeric Steam launch is permitted."""
    import winreg
    roots = []
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r'Software\Valve\Steam') as key:
            root, kind = winreg.QueryValueEx(key, 'SteamPath')
        if kind == winreg.REG_SZ:
            roots.append(Path(root))
    except OSError:
        return
    for root in roots[:1]:
        steam = validate_executable(root / 'steam.exe')
        libraries = [root]
        library_file = root / 'steamapps' / 'libraryfolders.vdf'
        try:
            if library_file.stat().st_size < 1024 * 1024:
                text = library_file.read_text(encoding='utf-8')
                for value in re.findall(r'"path"\s+"([^"\r\n]{1,1000})"', text):
                    candidate = Path(value.replace('\\\\', '\\'))
                    if candidate.is_absolute() and not str(candidate).startswith('\\\\'):
                        libraries.append(candidate)
        except OSError:
            pass
        for library in dict.fromkeys(libraries):
            folder = library / 'steamapps'
            if _is_reparse(folder):
                continue
            for manifest in sorted(folder.glob('appmanifest_*.acf'))[:2048]:
                try:
                    raw = manifest.read_bytes()
                    if len(raw) > 1024 * 1024:
                        continue
                    text = raw.decode('utf-8')
                    values = dict(re.findall(r'"(appid|name|installdir)"\s+"([^"\r\n]+)"', text))
                    app_id, name, directory = values['appid'], values['name'], values['installdir']
                    if not re.fullmatch(r'[1-9][0-9]{0,9}', app_id) or manifest.name != f'appmanifest_{app_id}.acf':
                        continue
                    if any(separator in directory for separator in ('/', '\\', ':')) or directory in ('.', '..'):
                        continue
                    game_root = folder / 'common' / directory
                    if not game_root.is_dir() or _is_reparse(game_root):
                        continue
                    expected = hashlib.sha256(raw).hexdigest()
                    def read(manifest=manifest, expected=expected, steam=steam, game_root=game_root):
                        if (not game_root.is_dir() or _is_reparse(game_root)
                                or _digest(_safe_local_path(manifest), 1024 * 1024) != expected):
                            raise AppError('Метаданные установленной игры Steam изменились.')
                        return str(steam), '', expected
                    yield AppSource('steam:' + app_id, name[:120], read, 'steam', 'steam', app_id)
                except (OSError, UnicodeError, KeyError, ValueError):
                    continue


@dataclass(frozen=True)
class AppEntry:
    id: str
    name: str
    target: Path
    aliases: tuple[str, ...]
    fingerprint: str
    source: AppSource
    sources: tuple[str, ...] = ()
    launch_type: str = 'win32'
    launch_id: str = ''
    icon: str = ''


def _entry(source: AppSource, digest_cache=None) -> AppEntry:
    if re.search(r'(?:reset\s+settings|unload\s+kernel|restore\s+defaults|uninstall|redistributable|'
                 r'удалени[ея]\s+программ|сброс\s+настроек)', normalize_name(source.name)):
        raise AppError('Служебный или изменяющий настройки компонент не является приложением.')
    raw, arguments, source_digest = source.read()
    if source.launch_type == 'linux' and sys.platform == 'linux':
        from .linux_apps import _executable
        target = _executable(raw)
    else:
        target = validate_executable(raw, arguments)
    if source.launch_type not in ('win32', 'packaged', 'steam', 'linux'):
        raise AppError('Неподдерживаемый тип запуска.')
    if source.launch_type == 'steam' and not re.fullmatch(r'[1-9][0-9]{0,9}', source.launch_id):
        raise AppError('Неверный идентификатор Steam.')
    if source.launch_type == 'packaged' and not re.fullmatch(r'[A-Za-z0-9_.-]{1,200}![A-Za-z0-9_.-]{1,100}', source.launch_id):
        raise AppError('Неверный идентификатор Store.')
    if digest_cache is None:
        target_digest = _digest(target)
    else:
        stat = target.stat()
        key = (str(target).casefold(), stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns)
        if key not in digest_cache:
            digest_cache[key] = _digest(target)
        target_digest = digest_cache[key]
    fingerprint = hashlib.sha256((source_digest + '\0' + str(target).casefold() + '\0' + target_digest).encode()).hexdigest()
    # Start Menu, App Paths and a running process describe the same launch
    # identity. Its ID must survive changes in provider enumeration order.
    identity = '\0'.join((str(target) if source.launch_type == 'linux' else str(target).casefold(),
                          source.launch_type, source.launch_id))
    app_id = 'app-' + hashlib.sha256(identity.encode()).hexdigest()[:20]
    name = source.name[:120]
    aliases = tuple(dict.fromkeys(normalize_name(item) for item in (
        name, target.stem, *KNOWN_ALIASES.get(target.stem.casefold(), ()), app_id,
        *(('терминал', 'китти') if source.launch_id == 'kitty.desktop' else ()),
        *source.aliases,
    ) if normalize_name(item)))
    return AppEntry(app_id, name, target, aliases, fingerprint, source, (source.origin,),
                    source.launch_type, source.launch_id, source.icon or str(target))


@contextmanager
def _launch_guard(target: Path):
    """Hold image and every ancestor against replacement during CreateProcess."""
    from .file_access import _hold, FileAccessError
    handle = None
    with ExitStack() as ancestors:
        try:
            for parent in reversed(target.parents):
                ancestors.enter_context(_hold(parent, True))
            if os.name == 'nt':
                kernel = ctypes.WinDLL('kernel32', use_last_error=True)
                kernel.CreateFileW.argtypes = [ctypes.c_wchar_p, ctypes.c_ulong, ctypes.c_ulong,
                                              ctypes.c_void_p, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_void_p]
                kernel.CreateFileW.restype = ctypes.c_void_p
                kernel.CloseHandle.argtypes = [ctypes.c_void_p]
                handle = kernel.CreateFileW(str(target), 0x80000000, 1, None, 3, 0x80, None)
                if handle in (None, ctypes.c_void_p(-1).value):
                    handle = None
                    raise AppError('Приложение занято или изменяется; запуск отменён.')
            # OS executables legitimately have WinSxS hardlinks. Image identity
            # and digest are checked by callers; file-document hardlink rules
            # must not prevent launching the OS-resolved Notepad/Calculator.
            _safe_local_path(target)
            yield
        except FileAccessError as exc:
            raise AppError('Папка приложения занята, содержит ссылку или изменяется; запуск отменён.') from exc
        finally:
            if handle is not None:
                kernel.CloseHandle(handle)


class _ActivatedProcess:
    """Own a native handle returned from package activation, never a bare PID."""
    def __init__(self, pid):
        self.kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        self.kernel.OpenProcess.argtypes = [ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong]
        self.kernel.OpenProcess.restype = ctypes.c_void_p
        self.kernel.GetExitCodeProcess.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong)]
        self.kernel.CloseHandle.argtypes = [ctypes.c_void_p]
        self.handle = self.kernel.OpenProcess(0x1000, False, pid)

    def poll(self):
        if not self.handle:
            raise OSError('activated process unavailable')
        code = ctypes.c_ulong()
        if not self.kernel.GetExitCodeProcess(self.handle, ctypes.byref(code)):
            raise OSError('activated process unavailable')
        return None if code.value == 259 else code.value

    def __del__(self):
        if getattr(self, 'handle', None):
            self.kernel.CloseHandle(self.handle)
            self.handle = None


def _activate_packaged(app_id):
    """IApplicationActivationManager, with no app arguments or shell namespace."""
    if os.name != 'nt' or not re.fullmatch(r'[A-Za-z0-9_.-]{1,200}![A-Za-z0-9_.-]{1,100}', app_id):
        raise AppError('Недопустимая активация Store.')
    ole = ctypes.WinDLL('ole32')
    result = ole.CoInitializeEx(None, 2)
    initialized = result in (0, 1)
    if result < 0 and result != -2147417850:
        raise AppError('Активация Store недоступна.')
    pointer = ctypes.c_void_p()
    try:
        clsid = _GUID('45BA127D-10A8-46EA-8AB7-56EA9078943C')
        iid = _GUID('2e941141-7f97-4756-ba1d-9decde894a3d')
        if ole.CoCreateInstance(ctypes.byref(clsid), None, 1, ctypes.byref(iid), ctypes.byref(pointer)) < 0:
            raise AppError('Активация Store недоступна.')
        table = ctypes.cast(pointer, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
        activate = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, ctypes.c_wchar_p,
                                      ctypes.c_wchar_p, ctypes.c_ulong,
                                      ctypes.POINTER(ctypes.c_ulong))(table[3])
        pid = ctypes.c_ulong()
        if activate(pointer, app_id, None, 2, ctypes.byref(pid)) < 0:  # AO_NOERRORUI
            raise AppError('Windows отклонила активацию приложения Store.')
        return _ActivatedProcess(pid.value)
    finally:
        if pointer.value:
            table = ctypes.cast(pointer, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
            ctypes.WINFUNCTYPE(ctypes.c_ulong, ctypes.c_void_p)(table[2])(pointer)
        if initialized:
            ole.CoUninitialize()


class AppCatalog:
    def __init__(self, source_provider: Callable[[], Iterable[AppSource]] = discover_sources,
                 refresh_interval: float = 0, *, policy=None):
        from .personal_permissions import PersonalMode
        self._policy = policy if policy is not None else PersonalMode()
        self._source_provider = source_provider
        self._entries: dict[str, AppEntry] = {}
        self._lock = threading.RLock()
        self._refresh_lock = threading.Lock()
        self._refresh_interval = refresh_interval
        self._last_refresh = 0.0
        self._refreshed = False
        self._stale_ids = set()
        self._portable_roots = ()
        self._statistics = {'sources': {}, 'rejected': 0, 'duplicates': 0, 'truncated': False,
                            'unavailable_providers': [], 'duration_ms': 0, 'applications': 0}
        # Steam can hand off to a process of unknown image identity. Retain the
        # submitted catalog ID until refresh instead of blindly launching twice.
        self._steam_requested = set()

    def configure_portable_roots(self, roots):
        resolved = []
        if not isinstance(roots, (tuple, list)) or len(roots) > 26:
            raise AppError('Нужно выбрать не более 26 локальных каталогов.')
        for raw in roots:
            text = str(raw)
            path = Path(text)
            if (not path.is_absolute() or text.startswith(('\\\\', '//')) or ':' in text[2:]
                    or not path.is_dir() or _is_reparse(path)):
                raise AppError('Нужен существующий локальный каталог без ссылок.')
            actual = path.resolve(strict=True)
            if actual != path.absolute():
                raise AppError('Каталог через ссылку не разрешён.')
            resolved.append(actual)
        with self._lock:
            self._portable_roots = tuple(dict.fromkeys(resolved))

    def set_personal_mode(self, enabled):
        """Compatibility endpoint cannot create broad application permissions."""
        if type(enabled) is not bool:
            raise AppError('Неверный профиль разрешений.')

    @property
    def policy(self):
        return self._policy() if callable(self._policy) else self._policy

    @staticmethod
    def identifiers(entry):
        identifiers = (entry.id, str(entry.target).casefold(), entry.target.stem.casefold(),
                       *entry.aliases, *executable_identity(entry.target),
                       'image:' + str(entry.target).casefold() + '|' + entry.fingerprint)
        if entry.target.stem.casefold() in ('notepad', 'calc'):
            from .agent import resolve_windows_app
            builtin = 'notepad' if entry.target.stem.casefold() == 'notepad' else 'calculator'
            if resolve_windows_app(builtin) == entry.target:
                identifiers += ('builtin:' + builtin,)
        return identifiers

    def check_permission(self, app_id, operation='launch'):
        entry = self._entries.get(app_id)
        if entry is None:
            raise AppError('Приложение отсутствует в каталоге.')
        if not self.is_allowed(app_id, operation):
            try:
                self.policy.check_app(self.identifiers(entry), operation)
            except ValueError as exc:
                raise AppError(str(exc)) from exc
            raise AppError('Эта цель не является проверенным установленным приложением.')
        return entry

    @staticmethod
    def _target_permitted(entry):
        if entry.launch_type == 'linux':
            # Catalog entries are constructed and revalidated by the Linux
            # adapter against root-owned executable roots.
            return sys.platform == 'linux'
        from .personal_permissions import ordinary_path, known_folder, foreign_profile_roots
        try:
            profile = known_folder('profile')
            # Program Files is outside Users; a sibling profile is never an
            # installed-application permission, even after a picker grant.
            if entry.target.is_relative_to(profile.parent) and not entry.target.is_relative_to(profile):
                return False
            if any(entry.target == root or entry.target.is_relative_to(root) for root in foreign_profile_roots()):
                return False
            if any(entry.target == root or entry.target.is_relative_to(root) for root in _protected_app_roots()):
                return False
            parts = {part.casefold() for part in entry.target.parts}
            if parts.intersection({'.ssh', '.aws', '.azure', '.gnupg', '.kube', '.git',
                                   'credentials', 'vault', 'vaults', 'protect', 'crypto'}):
                return False
            if any(entry.target.is_relative_to(root) for root in _installation_roots()):
                return True
            if ordinary_path(entry.target):
                return True
            # The two fixed built-ins are the only system-directory exception.
            if entry.target.stem.casefold() in ('notepad', 'calc'):
                from .agent import resolve_windows_app
                builtin = 'notepad' if entry.target.stem.casefold() == 'notepad' else 'calculator'
                return resolve_windows_app(builtin) == entry.target
        except (OSError, ValueError):
            return False
        return False

    def is_allowed(self, app_id, operation='launch'):
        with self.policy._lock, self._lock:
            entry = self._entries.get(app_id)
            if entry is None or app_id in self._stale_ids or not self._target_permitted(entry):
                return False
            ordinary = True
            # A malicious Start Menu link must not turn a downloaded temporary
            # binary into an automatically approved installed application.
            for name in ('TEMP', 'TMP'):
                raw = os.environ.get(name)
                if raw:
                    try:
                        if entry.target.is_relative_to(Path(raw).resolve()):
                            ordinary = False
                    except (OSError, ValueError):
                        ordinary = False
            installed = any(origin in ('shortcuts', 'app_paths', 'uninstall', 'start_apps', 'steam')
                            for origin in entry.sources)
            installed = installed and any(entry.target.is_relative_to(root) for root in _installation_roots())
            identifiers = self.identifiers(entry)
            installed = installed or any(item.startswith('builtin:') for item in identifiers)
            allowed = self.policy.app_allowed(identifiers, operation)
            if self.policy.mode == 'full_user' and not (ordinary and installed):
                return bool(allowed and self.policy.explicit_app_allowed(self.identifiers(entry), operation))
            return bool(allowed)

    def statistics(self):
        with self._lock:
            return {**self._statistics, 'sources': {key: dict(value) for key, value in self._statistics['sources'].items()},
                    'unavailable_providers': list(self._statistics['unavailable_providers'])}

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
        by_identity = {}
        digest_cache = {}
        report = {'sources': {}, 'rejected': 0, 'duplicates': 0, 'truncated': False,
                  'unavailable_providers': [], 'duration_ms': 0, 'applications': 0}
        started = time.monotonic()
        provider = (discover_sources(report, self._portable_roots) if self._source_provider is discover_sources
                    else self._source_provider())
        for count, source in enumerate(provider):
            if count >= 10000 or time.monotonic() - started > 45:
                report['truncated'] = True
                break
            statistics = report['sources'].setdefault(source.origin, {'candidates': 0, 'accepted': 0, 'rejected': 0})
            statistics['candidates'] += 1
            try:
                entry = _entry(source, digest_cache)
                # Duplicate metadata for one target must not create ambiguity.
                # Multiple package app IDs in the same executable can represent
                # distinct activities; Win32 metadata for that executable is a
                # duplicate, not an additional application.
                image = str(entry.target).casefold()
                identity = (image, entry.launch_id)
                existing = by_identity.get(identity)
                if existing is None and entry.launch_type == 'packaged':
                    old = by_identity.get((image, ''))
                    if old is not None and old.launch_type == 'win32':
                        existing = old
                        by_identity.pop((image, ''), None)
                elif existing is None and entry.launch_type == 'win32':
                    packages = [item for (path, _), item in by_identity.items()
                                if path == image and item.launch_type == 'packaged']
                    if len(packages) == 1:
                        existing = packages[0]
                        identity = (image, existing.launch_id)
                if existing is None:
                    found[entry.id] = entry
                    by_identity[identity] = entry
                else:
                    preferred = entry if entry.launch_type == 'packaged' else existing
                    merged = replace(preferred, id=existing.id,
                                     aliases=tuple(dict.fromkeys((*existing.aliases, *entry.aliases))),
                                     sources=tuple(dict.fromkeys((*existing.sources, *entry.sources))))
                    found[existing.id] = merged
                    by_identity[identity] = merged
                    report['duplicates'] += 1
                statistics['accepted'] += 1
            except (AppError, OSError, ValueError, ET.ParseError):
                report['rejected'] += 1
                statistics['rejected'] += 1
                continue
        with self._lock:
            self._entries = found
            self._stale_ids.clear()
            self._refreshed = True
            self._last_refresh = time.monotonic()
            report['applications'] = len(found)
            report['duration_ms'] = round((self._last_refresh - started) * 1000, 2)
            self._statistics = report
            self._steam_requested.intersection_update(found)
        return self.entries()

    def entries(self) -> list[dict]:
        with self.policy._lock, self._lock:
            return [{'id': item.id, 'name': item.name, 'target': str(item.target),
                     'aliases': list(item.aliases), 'fingerprint': item.fingerprint,
                     'policy_identifiers': list(self.identifiers(item)),
                     'allowed': self.is_allowed(item.id),
                     'permissions': {operation: self.is_allowed(item.id, operation)
                                     for operation in ('launch', 'focus', 'close')},
                     'sources': list(item.sources),
                     'launch_type': item.launch_type, 'launch_id': item.launch_id, 'icon': item.icon}
                    for item in sorted(self._entries.values(), key=lambda item: item.name.casefold())]

    def aliases(self) -> dict[str, tuple[str, ...]]:
        if not self._refreshed:
            self.refresh()
        with self._lock:
            # Steam games use the client executable as a transport. Its aliases
            # must resolve to the client, while games keep their own labels.
            return {key: (normalize_name(item.name), key) if item.launch_type == 'steam' else item.aliases
                    for key, item in self._entries.items()}

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
            self._stale_ids.add(app_id)
            raise AppError('Цель приложения изменилась. Обнови каталог и разрешение.') from exc
        return replace(current, id=entry.id, aliases=entry.aliases, sources=entry.sources)

    def set_permission(self, app_id: str, allowed: bool, fingerprint: str, operation=None) -> list[dict]:
        operations = ('launch', 'focus', 'close') if operation is None else (operation,)
        if type(allowed) is not bool or any(op not in ('launch', 'focus', 'close') for op in operations):
            raise AppError('Неизвестная операция приложения.')
        with self.policy._lock, self._lock:
            if not allowed:
                entry = self._entries.get(app_id)
                if entry is not None:
                    self.policy.set_app_permissions(self.identifiers(entry), operations, False)
                return self.entries()
            entry = self._revalidate(app_id)
            if fingerprint != entry.fingerprint:
                raise AppError('Каталог изменился. Выбери приложение повторно.')
            self.policy.set_app_permissions(self.identifiers(entry), operations, True)
            return self.entries()

    def launch(self, app_id: str) -> dict:
        started = time.perf_counter()
        target = app_id
        try:
            with self.policy._lock, self._lock:
                entry = self._revalidate(app_id)
                target = entry.name
                self.check_permission(app_id)
                with _launch_guard(entry.target):
                    self._revalidate(app_id)
                    self.check_permission(app_id)
                    if entry.launch_type == 'linux':
                        from .linux_apps import launch
                        result = launch(entry)
                    elif entry.launch_type == 'steam':
                        from .results import ActionResult
                        if app_id in self._steam_requested:
                            result = ActionResult(True, 'open_app', target, 'launch_pending',
                                status_text=f'{target}: запрос Steam уже отправлен; окно игры пока не подтверждено.')
                        else:
                            subprocess.Popen([str(entry.target), '-applaunch', entry.launch_id], shell=False,
                                             close_fds=True, cwd=str(entry.target.parent))
                            self._steam_requested.add(app_id)
                            result = ActionResult(True, 'open_app', target, 'request_accepted',
                                status_text=f'{target}: запрос запуска передан Steam; окно игры пока не подтверждено.')
                    else:
                        spawn = (lambda: _activate_packaged(entry.launch_id)) if entry.launch_type == 'packaged' else (
                            lambda: subprocess.Popen([str(entry.target)], shell=False, close_fds=True,
                                                     cwd=str(entry.target.parent)))
                        # Obsidian's single-instance activation can ask an
                        # existing background instance to create/show a window.
                        # Only this reviewed image gets one bounded handoff;
                        # never generalize relaunch to arbitrary background apps.
                        result = launch_coordinator.launch(entry.target, target, spawn,
                            activate_background=entry.launch_type == 'win32' and entry.target.name.casefold() == 'obsidian.exe')
                self.policy.record('launch', app_id, result.execution_status, reason=result.error)
            return {**result.to_dict(), 'duration_ms': round((time.perf_counter() - started) * 1000, 2)}
        except (AppError, OSError) as exc:
            # Exception text is controlled here, OS errors/paths are not reflected.
            error = str(exc) if isinstance(exc, AppError) else 'Система отклонила запуск приложения.'
            self.policy.record('launch', app_id, 'denied', reason=error)
            return {'success': False, 'action': 'open_app', 'resolved_target': target,
                    'execution_status': 'not_executed', 'observed_state': None,
                    'error': error, 'mode': 'REAL', 'duration_ms': round((time.perf_counter() - started) * 1000, 2),
                    'status_text': error}


def _owner_policy():
    from .file_access import file_access
    return file_access.personal_mode


def _associated_executable(suffix):
    """Read only the executable; registry command templates are never executed.

    https://learn.microsoft.com/en-us/windows/win32/api/shlwapi/nf-shlwapi-assocquerystringw
    ASSOCSTR_EXECUTABLE (2), fixed open verb, bounded caller-owned buffer.
    """
    if os.name != 'nt' or not (re.fullmatch(r'\.[a-z0-9]{1,16}', suffix) or suffix == 'https'):
        raise AppError('Ассоциация документа недоступна.')
    from ctypes import wintypes as w
    api = ctypes.WinDLL('shlwapi')
    api.AssocQueryStringW.argtypes = [w.DWORD, ctypes.c_int, w.LPCWSTR, w.LPCWSTR,
                                     w.LPWSTR, ctypes.POINTER(w.DWORD)]
    api.AssocQueryStringW.restype = ctypes.c_long
    buffer, size = ctypes.create_unicode_buffer(32768), w.DWORD(32768)
    if api.AssocQueryStringW(0, 2, suffix, 'open', buffer, ctypes.byref(size)) != 0:
        raise AppError('Не удалось проверить приложение для открытия документа.')
    return validate_executable(buffer.value)


def _open_document(path, *, app_catalog=None, association_resolver=None):
    """Internal adapter: FileAccess must hold the checked document and policy.

    The only argument is that exact local document path. No association command
    string, model arguments, shell verb execution or ShellExecute is accepted.
    """
    from .file_access import FileAccessError, _checked, READABLE_EXTENSIONS
    service = app_catalog if app_catalog is not None else catalog
    resolver = association_resolver or _associated_executable
    path = _checked(path)
    if path.suffix.casefold() not in READABLE_EXTENSIONS:
        raise FileAccessError('Этот тип документа нельзя безопасно открыть.')
    try:
        target = resolver(path.suffix.casefold())
        service.aliases()
        with service.policy._lock, service._lock:
            matches = [entry for entry in service._entries.values() if entry.target == target and entry.launch_type == 'win32']
            if not matches:
                from .agent import resolve_windows_app
                if target == resolve_windows_app('notepad'):
                    with _launch_guard(target):
                        if target != resolve_windows_app('notepad'):
                            raise AppError('Цель Блокнота изменилась.')
                        service.policy.check_app(('builtin:notepad', 'notepad', 'блокнот', str(target).casefold(),
                                                  *executable_identity(target)), 'launch')
                        subprocess.Popen([str(target), str(path)], shell=False, close_fds=True)
                        service.policy.record('launch_document', 'notepad', 'request_accepted')
                    return
                raise AppError('Приложение для этого документа отсутствует в проверенном каталоге. Обнови каталог и разреши его запуск.')
            # Deduplication normally leaves one image. All duplicate identities
            # must permit launch; one alias cannot bypass a policy denial.
            for entry in matches:
                service._revalidate(entry.id)
                service.check_permission(entry.id, 'launch')
            with _launch_guard(target):
                for entry in matches:
                    service._revalidate(entry.id)
                    service.check_permission(entry.id, 'launch')
                subprocess.Popen([str(target), str(path)], shell=False, close_fds=True, cwd=str(target.parent))
                service.policy.record('launch_document', matches[0].id, 'request_accepted')
    except (AppError, OSError) as exc:
        raise FileAccessError(str(exc) if isinstance(exc, AppError) else 'Windows отклонила открытие документа.') from exc


def _open_fixed_bookmark(bookmark_id):
    from .desktop_tools import BOOKMARKS
    bookmark = BOOKMARKS.get(bookmark_id)
    if bookmark is None:
        raise AppError('Закладка не разрешена.')
    target = _associated_executable('https')
    catalog.aliases()
    with catalog.policy._lock, catalog._lock:
        entries = [entry for entry in catalog._entries.values() if entry.target == target and entry.launch_type == 'win32']
        if not entries:
            raise AppError('Разреши браузер для этой закладки в проверенном каталоге приложений.')
        with _launch_guard(target):
            for entry in entries:
                catalog._revalidate(entry.id)
                catalog.check_permission(entry.id, 'launch')
            subprocess.Popen([str(target), bookmark[1]], shell=False, close_fds=True, cwd=str(target.parent))
            catalog.policy.record('launch_bookmark', entries[0].id, 'request_accepted')


catalog = AppCatalog(refresh_interval=2, policy=_owner_policy)
