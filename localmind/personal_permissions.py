"""Explicit local-user read/launch profile. Model output can never enable it.

The authenticated settings endpoint is the only activation path. Root identities,
not path prefixes, form the grant. Persistence is private and bound to the OS SID.
"""
from collections import deque
from datetime import datetime, timezone
import ctypes
from ctypes import wintypes as w
import hashlib
import json
import os
from pathlib import Path
import secrets
from threading import RLock


def local_user_identity():
    if os.name != 'nt':
        return f'uid:{os.getuid()}'
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    security = ctypes.WinDLL('advapi32', use_last_error=True)
    kernel.GetCurrentProcess.restype = w.HANDLE
    kernel.CloseHandle.argtypes = [w.HANDLE]
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    security.OpenProcessToken.argtypes = [w.HANDLE, w.DWORD, ctypes.POINTER(w.HANDLE)]
    security.GetTokenInformation.argtypes = [w.HANDLE, ctypes.c_int, ctypes.c_void_p, w.DWORD, ctypes.POINTER(w.DWORD)]
    security.ConvertSidToStringSidW.argtypes = [ctypes.c_void_p, ctypes.POINTER(w.LPWSTR)]
    token, needed, sid_text = w.HANDLE(), w.DWORD(), w.LPWSTR()
    try:
        if not security.OpenProcessToken(kernel.GetCurrentProcess(), 8, ctypes.byref(token)):
            raise OSError('OS user identity unavailable')
        security.GetTokenInformation(token, 1, None, 0, ctypes.byref(needed))
        if not 0 < needed.value < 65536:
            raise OSError('OS user identity unavailable')
        data = ctypes.create_string_buffer(needed.value)
        if not security.GetTokenInformation(token, 1, data, needed, ctypes.byref(needed)):
            raise OSError('OS user identity unavailable')
        sid = ctypes.cast(data, ctypes.POINTER(ctypes.c_void_p))[0]
        if not security.ConvertSidToStringSidW(sid, ctypes.byref(sid_text)):
            raise OSError('OS user identity unavailable')
        return sid_text.value
    finally:
        if sid_text:
            kernel.LocalFree(ctypes.cast(sid_text, ctypes.c_void_p))
        if token:
            kernel.CloseHandle(token)


def ordinary_path(path):
    """Exclude secrets by components even when the owner approves a whole drive."""
    parts = {part.casefold() for part in Path(path).parts}
    blocked = {'.ssh', '.aws', '.azure', '.gnupg', '.kube', '.git',
               'credentials', 'credential', 'vault', 'vaults', 'protect', 'crypto',
               'system32', 'syswow64', 'system volume information', '$recycle.bin',
               'windows', '.password-store', 'chrome', 'chromium', 'firefox',
               'edge', 'brave-browser', 'user data', 'keyrings'}
    name = Path(path).name.casefold()
    if parts & blocked or name in {'login data', 'cookies', 'local state', 'key4.db', 'logins.json',
                                  'credentials.json', 'credentials.ini', 'auth.json', '.env', 'ntuser.dat', 'sam', 'security', 'system'}:
        return False
    if name.startswith(('.env.', 'id_rsa', 'id_ed25519', 'id_ecdsa')):
        return False
    if name in {'.netrc', '.npmrc', '.pypirc', '.git-credentials'} or any(
            token in Path(path).stem.casefold() for token in ('password', 'credential', 'secret', 'token')):
        return False
    return Path(path).suffix.casefold() not in {'.pem', '.key', '.pfx', '.p12', '.kdbx', '.jks', '.keystore'}


class PersonalMode:
    def __init__(self, persistence=None, user_identity=local_user_identity):
        self.persistence = Path(persistence) if persistence else None
        self.user_identity = user_identity
        self._roots = {}
        self._enabled = False
        self.generation = secrets.token_hex(16)
        self._log = deque(maxlen=200)
        self._lock = RLock()
        self._load()

    def _load(self):
        if self.persistence is None or not self.persistence.exists():
            return
        try:
            from .file_access import _checked, _identity
            path = _checked(self.persistence)
            if path.stat().st_size > 32768:
                return
            data = json.loads(path.read_text(encoding='utf-8'))
            if data.get('user') != self.user_identity() or data.get('enabled') is not True:
                return
            roots = data.get('roots', [])
            if not isinstance(roots, list) or not 1 <= len(roots) <= 16:
                return
            for item in roots:
                root = _checked(Path(item['path']))
                if not root.is_dir() or tuple(item['identity']) != _identity(root) or not ordinary_path(root):
                    raise ValueError('root changed')
                self._roots[item['id']] = (root, _identity(root))
            self._enabled = True
        except (OSError, ValueError, TypeError, KeyError):
            self._roots.clear()
            self._enabled = False

    def _save(self):
        if self.persistence is None:
            return
        from .file_access import _checked
        self.persistence.parent.mkdir(parents=True, exist_ok=True)
        _checked(self.persistence.parent)
        data = {'version': 1, 'user': self.user_identity(), 'enabled': self._enabled,
                'roots': [{'id': key, 'path': str(path), 'identity': identity}
                          for key, (path, identity) in self._roots.items()]}
        # Exclusive temporary creation, no following pre-existing target links.
        temporary = self.persistence.with_name(self.persistence.name + '.' + secrets.token_hex(8) + '.tmp')
        try:
            with temporary.open('x', encoding='utf-8') as stream:
                json.dump(data, stream, ensure_ascii=False)
            os.replace(temporary, self.persistence)
        finally:
            temporary.unlink(missing_ok=True)

    def set(self, enabled, roots=()):
        from .file_access import _checked, _identity, FileAccessError
        if type(enabled) is not bool:
            raise FileAccessError('Нужен явный выбор режима.')
        with self._lock:
            if not enabled:
                self._enabled, self._roots = False, {}
                self.generation = secrets.token_hex(16)
                self._save()
                self.record('permission', 'personal_mode', 'revoked')
                return
            if not isinstance(roots, (list, tuple)) or not 1 <= len(roots) <= 16:
                raise FileAccessError('Выбери от 1 до 16 локальных папок или дисков.')
            checked = {}
            for raw in roots:
                if not isinstance(raw, str) or not 1 <= len(raw) <= 1024:
                    raise FileAccessError('Некорректная папка.')
                root = _checked(Path(raw))
                if not root.is_dir() or not ordinary_path(root):
                    raise FileAccessError('Секретные и системные папки исключены из доступа.')
                key = hashlib.sha256(str(root).encode('utf-8')).hexdigest()[:24]
                checked[key] = root, _identity(root)
            previous = self._enabled, self._roots
            self._enabled, self._roots = True, checked
            try:
                self._save()
            except (OSError, ValueError):
                self._enabled, self._roots = previous
                raise
            self.generation = secrets.token_hex(16)
            self.record('permission', 'personal_mode', 'enabled')

    def enabled(self):
        with self._lock:
            return self._enabled

    def roots(self):
        from .file_access import _checked, _identity, FileAccessError
        with self._lock:
            if not self._enabled:
                raise FileAccessError('Режим личного компьютера выключен.')
            for root, identity in self._roots.values():
                if _identity(_checked(root)) != identity:
                    raise FileAccessError('Разрешённая папка была заменена. Включи режим повторно.')
            return {key: root for key, (root, _) in self._roots.items()}

    def allows(self, path):
        if not self.enabled() or not ordinary_path(path):
            return False
        return any(path == root or root in path.parents for root in self.roots().values())

    def record(self, operation, target, decision):
        with self._lock:
            self._log.append({'at': datetime.now(timezone.utc).isoformat(), 'operation': operation,
                              'target': str(target), 'decision': decision})

    def public(self):
        with self._lock:
            return {'enabled': self._enabled,
                    'roots': [{'id': key, 'path': str(path)} for key, (path, _) in self._roots.items()],
                    'summary': 'Чтение и поиск обычных файлов в выбранных папках, открытие документов и запуск обнаруженных приложений. Изменение и удаление требуют отдельного точного подтверждения. Скрипты, установка, настройка ОС и повышение прав не разрешены.',
                    'excluded': 'Ключи, пароли, хранилища браузеров и системные каталоги; ссылки и сетевые пути.',
                    'access_log': list(self._log)}
