"""Discover local freedesktop entries with fixed, argument-free activation."""
from configparser import ConfigParser, Error
import hashlib
import os
from pathlib import Path
import re
import shlex
import stat
import subprocess
from threading import Thread

from .apps import AppError, AppSource, DENIED_EXECUTABLES
from .results import ActionResult

SYSTEM_PATH = (Path('/usr/bin'), Path('/usr/local/bin'))
EXEC_ROOTS = (*SYSTEM_PATH, Path('/opt'))
ACTION_LAUNCHERS = frozenset(('env', 'flatpak', 'snap', 'sudo', 'pkexec', 'fish', 'dash',
                            'busybox', 'xdg-open', 'gio', 'systemctl', 'dbus-send', 'gdbus', 'localmind'))


def data_directories():
    home = Path(os.environ.get('XDG_DATA_HOME', ''))
    if not home.is_absolute():
        home = Path.home() / '.local/share'
    system = os.environ.get('XDG_DATA_DIRS') or '/usr/local/share:/usr/share'
    return tuple(dict.fromkeys([home, *(Path(p) for p in system.split(':') if Path(p).is_absolute())]))


def _default_browser():
    config = Path(os.environ.get('XDG_CONFIG_HOME', ''))
    if not config.is_absolute():
        config = Path.home() / '.config'
    locations = [config, Path('/etc/xdg'), *(base / 'applications' for base in data_directories())]
    for folder in locations:
        parser = ConfigParser(interpolation=None)
        try:
            with (folder / 'mimeapps.list').open(encoding='utf-8') as stream:
                content = stream.read(65537)
            if len(content) > 65536:
                continue
            parser.read_string(content)
            handler = parser.get('Default Applications', 'x-scheme-handler/https', fallback='')
            desktop_id = handler.split(';', 1)[0].strip()
            if re.fullmatch(r'[A-Za-z0-9_.-]+\.desktop', desktop_id):
                return desktop_id
        except (Error, OSError, UnicodeError):
            continue
    return None


def _ordinary(path, owner):
    for item in (path, *path.parents):
        info = item.lstat()
        if stat.S_ISLNK(info.st_mode) or info.st_uid not in owner or info.st_mode & 0o022:
            raise AppError('Недоверенный desktop entry или исполняемый файл.')
    if not stat.S_ISREG(path.stat().st_mode):
        raise AppError('Нужен обычный файл приложения.')


def _executable(command):
    path = Path(command)
    if not path.is_absolute():
        if path.name != command:
            raise AppError('Относительный путь запуска запрещён.')
        path = next((root / command for root in SYSTEM_PATH if (root / command).is_file()), path)
    if not path.is_absolute() or not any(path.is_relative_to(root) for root in EXEC_ROOTS):
        raise AppError('Цель находится вне системных путей приложений.')
    requested_name = path.name
    path = path.resolve(strict=True)
    if not any(path.is_relative_to(root) for root in EXEC_ROOTS) or not os.access(path, os.X_OK):
        raise AppError('Не найден исполняемый файл установленного приложения.')
    for name in (requested_name, path.name):
        if name.casefold() in DENIED_EXECUTABLES | ACTION_LAUNCHERS or re.match(
                r'^(python|perl|ruby|node|php|lua|bash|dash)([0-9.]|$)', name, re.I):
            raise AppError('Исполняемый файл допускает произвольные команды.')
    _ordinary(path, {0})
    return path


def _read(path):
    _ordinary(path, {0, os.getuid()})
    with path.open('rb') as stream:
        raw = stream.read(131073)
    if len(raw) > 131072:
        raise AppError('Desktop entry слишком большой.')
    parser = ConfigParser(interpolation=None, delimiters=('=',))
    parser.optionxform = str
    try:
        parser.read_string(raw.decode('utf-8'))
        section = parser['Desktop Entry']
        if (section.get('Type') != 'Application' or section.get('Hidden', '').lower() == 'true'
                or section.get('NoDisplay', '').lower() == 'true' or section.get('Terminal', '').lower() == 'true'
                or section.get('DBusActivatable', '').lower() == 'true' or section.get('Path')):
            raise AppError('Desktop entry требует неподдерживаемого способа активации.')
        argv = shlex.split(section['Exec'])
        if not argv or any(arg not in ('%f', '%F', '%u', '%U') for arg in argv[1:]):
            raise AppError('Desktop entry требует дополнительных аргументов.')
        if section.get('TryExec'):
            _executable(section['TryExec'])
        target = _executable(argv[0])
        browser = 'WebBrowser' in section.get('Categories', '').split(';')
        return section.get('Name[ru]', section['Name']), target, hashlib.sha256(raw).hexdigest(), browser
    except (Error, ValueError, KeyError) as exc:
        raise AppError('Неверный desktop entry.') from exc


def discover(report):
    seen = set()
    count = 0
    default_browser = _default_browser()
    for base in data_directories():
        root = base / 'applications'
        for directory, children, files in os.walk(root, followlinks=False):
            children[:] = sorted(children) if len(Path(directory).relative_to(root).parts) < 5 else []
            for filename in sorted(files):
                count += 1
                if count > 10000:
                    if report is not None:
                        report['truncated'] = True
                    return
                if not filename.endswith('.desktop'):
                    continue
                path = Path(directory) / filename
                desktop_id = '-'.join(path.relative_to(root).parts)
                if desktop_id in seen:
                    continue
                seen.add(desktop_id)
                try:
                    name, _, _, browser = _read(path)
                except (AppError, OSError):
                    continue

                def read(path=path, relative=path.relative_to(root)):
                    # Recheck XDG precedence at execution, including new masks.
                    for base in data_directories():
                        candidate = base / 'applications' / relative
                        if os.path.lexists(candidate):
                            if candidate != path:
                                raise AppError('Приоритет desktop entry изменился.')
                            break
                    _, target, digest, _ = _read(path)
                    return str(target), '', digest

                aliases = ('браузер', 'browser') if browser and default_browser in (None, desktop_id) else ()
                yield AppSource(desktop_id, name, read, 'xdg', 'linux', desktop_id, aliases=aliases)


def launch(entry):
    process = subprocess.Popen([str(entry.target)], cwd='/', shell=False, close_fds=True,
                               stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        code = process.wait(timeout=.15)
    except subprocess.TimeoutExpired:
        Thread(target=process.wait, daemon=True).start()
        return ActionResult(True, 'open_app', entry.name, 'process_created', 'running_process',
                            status_text=f'{entry.name}: процесс запущен.', data={'process_running': True})
    return ActionResult(code == 0, 'open_app', entry.name, 'request_accepted' if code == 0 else 'failed',
                        status_text=f'{entry.name}: программа запуска завершилась с кодом {code}.')
