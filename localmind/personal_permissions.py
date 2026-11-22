"""Versioned local-user policy. Model output can never enable or change it.

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
import sys
import copy
import time
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
    from .paths import APP_ROOT, DATA_ROOT, DEFAULT_ROOT
    from .storage import protected_roots
    candidate = Path(path)
    # An approved parent (even the whole user profile) must never let an LLM
    # rewrite its own grants, HA connection, model manifest, runtime or UI.
    protected = (DATA_ROOT, DEFAULT_ROOT.resolve(), *protected_roots(), *(APP_ROOT / name for name in
        ('localmind', 'config', 'static', 'runtime', 'models', '.voice-envs',
         'offline-assets', 'offline-llm', 'results/private', 'scripts', 'installer', 'tests')),
         *(APP_ROOT / name for name in ('package.json', 'package-lock.json', 'start.py', 'AGENTS.md', 'DEV_CREW_START.txt')))
    if any(candidate == root or root in candidate.parents for root in protected):
        return False
    if sys.platform == 'linux' and any(candidate.is_relative_to(root) for root in (
            '/boot', '/dev', '/etc', '/proc', '/run', '/sys', '/usr', '/var/lib')):
        return False
    # A folder grant never includes another Windows account or shared profiles.
    if os.name == 'nt':
        profile = known_folder('profile')
        for parent in candidate.parents:
            if parent.name.casefold() in {'users', 'documents and settings'}:
                if candidate != profile and profile not in candidate.parents:
                    return False
        system = [Path(os.environ[k]) for k in ('WINDIR', 'ProgramFiles', 'ProgramFiles(x86)', 'ProgramData') if os.environ.get(k)]
        if any(candidate == root or root in candidate.parents for root in system):
            return False
        if any(candidate == root or root in candidate.parents for root in foreign_profile_roots()):
            return False
    parts = {part.casefold() for part in Path(path).parts}
    blocked = {'.ssh', '.aws', '.azure', '.gnupg', '.kube', '.git',
               'credentials', 'credential', 'vault', 'vaults', 'protect', 'crypto',
               'system32', 'syswow64', 'system volume information', '$recycle.bin',
               'windows', '.password-store', 'chrome', 'chromium', 'firefox',
               'edge', 'brave-browser', 'user data', 'keyrings', 'appdata',
               '.config', '.docker', '.terraform', '.npm', '.vscode'}
    # Developer worktrees are ordinary projects, not the host agent's auth,
    # sessions or configuration. The parent .codex itself remains unscannable.
    components = [part.casefold() for part in candidate.parts]
    if '.codex' in components:
        tail = components[components.index('.codex') + 1:]
        if not tail or tail[0] != 'worktrees':
            return False
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


FILE_OPERATIONS = frozenset(('search', 'read', 'open', 'create', 'overwrite', 'move', 'delete'))
APP_OPERATIONS = frozenset(('launch', 'focus', 'close'))
SCHEMA_VERSION = 2
MAX_POLICY_BYTES = 1024 * 1024


def known_folder(name):
    """Current token's Known Folders, including redirected fixed-drive folders."""
    if sys.platform == 'linux':
        from .linux_paths import user_directory
        return user_directory(name)
    if os.name != 'nt':
        return Path.home() if name == 'profile' else Path.home() / name.title()
    import uuid
    ids = {'profile': '5e6c858f-0e22-4760-9afe-ea3317b67173',
           'downloads': '374de290-123f-4565-9164-39c4925e467b',
           'documents': 'fdd39ad0-238f-46af-adb4-6c85480369c7',
           'desktop': 'b4bfcc3a-db2c-424c-b029-7fe99a87c641',
           'pictures': '33e28130-4e1e-4676-835a-98395c3bc3bb',
           'music': '4bd8d571-6d19-48d3-be97-422220080e43',
           'videos': '18989b1d-99b5-455b-841c-ab7c74e4ddfc'}
    guid = (ctypes.c_ubyte * 16).from_buffer_copy(uuid.UUID(ids[name]).bytes_le)
    shell, ole = ctypes.WinDLL('shell32'), ctypes.WinDLL('ole32')
    shell.SHGetKnownFolderPath.argtypes = [ctypes.c_void_p, w.DWORD, w.HANDLE, ctypes.POINTER(ctypes.c_void_p)]
    shell.SHGetKnownFolderPath.restype = ctypes.c_long
    ole.CoTaskMemFree.argtypes = [ctypes.c_void_p]
    pointer = ctypes.c_void_p()
    if shell.SHGetKnownFolderPath(ctypes.byref(guid), 0, None, ctypes.byref(pointer)) != 0:
        raise OSError('Known Folder недоступна.')
    try:
        return Path(ctypes.wstring_at(pointer))
    finally:
        ole.CoTaskMemFree(pointer)


def user_roots():
    roots = []
    for name in ('profile', 'downloads', 'documents', 'desktop', 'pictures', 'music', 'videos'):
        try:
            path = known_folder(name)
            if path.is_dir():
                roots.append(str(path))
        except OSError:
            if name == 'profile':
                raise
    return roots


def foreign_profile_roots():
    """ProfileList includes profiles relocated beyond C:\\Users or other drives.

    Registry metadata only: never enumerate or read another user's files.
    Failure is propagated so adapters fail closed rather than guess ownership.
    """
    if os.name != 'nt':
        return ()
    import winreg
    owner = local_user_identity()
    roots = []
    with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                        r'SOFTWARE\Microsoft\Windows NT\CurrentVersion\ProfileList') as profiles:
        count = winreg.QueryInfoKey(profiles)[0]
        for index in range(count):
            sid = winreg.EnumKey(profiles, index)
            if sid == owner:
                continue
            with winreg.OpenKey(profiles, sid) as profile:
                try:
                    raw, kind = winreg.QueryValueEx(profile, 'ProfileImagePath')
                except FileNotFoundError:
                    continue
            if kind not in (winreg.REG_SZ, winreg.REG_EXPAND_SZ) or not isinstance(raw, str):
                raise OSError('Не удалось проверить границы пользовательских профилей.')
            root = Path(os.path.expandvars(raw))
            if not root.is_absolute():
                raise OSError('Некорректная область пользовательского профиля.')
            roots.append(root.resolve())
    return tuple(roots)


class PersonalMode:
    """Single versioned authority. Session references never survive a revision."""
    def __init__(self, persistence=None, user_identity=local_user_identity, root_provider=user_roots):
        self.persistence = Path(persistence) if persistence else None
        self.user_identity, self.root_provider = user_identity, root_provider
        self._roots, self._rules, self._apps = {}, [], []
        self._root_operations = {}
        self._operations = set(FILE_OPERATIONS)
        self.mode, self.error = 'restricted', None
        self.audit_warning = None
        self._enabled = False
        self.generation = secrets.token_hex(16)
        self._log, self._drafts = deque(maxlen=200), {}
        self._lock = RLock()
        self._load()

    def _checked_roots(self, roots):
        from .file_access import _checked, _identity, FileAccessError
        if not isinstance(roots, (list, tuple)) or len(roots) > 16:
            raise FileAccessError('Выбери до 16 локальных папок.')
        checked = {}
        for raw in roots:
            if not isinstance(raw, str) or not 1 <= len(raw) <= 1024:
                raise FileAccessError('Некорректная папка.')
            root = _checked(Path(raw))
            if not root.is_dir() or not ordinary_path(root):
                raise FileAccessError('Секретные, чужие и системные папки исключены из доступа.')
            checked[hashlib.sha256(str(root).casefold().encode()).hexdigest()[:24]] = root, _identity(root)
        return checked

    def _load(self):
        if self.persistence is None or not self.persistence.exists():
            return
        try:
            from .file_access import _checked, _identity
            path = _checked(self.persistence)
            if path.stat().st_size > MAX_POLICY_BYTES:
                raise ValueError('policy size')
            data = json.loads(path.read_text(encoding='utf-8'))
            if not isinstance(data, dict):
                raise ValueError('policy object')
            if data.get('user') != self.user_identity() or type(data.get('version')) is not int or data.get('version') not in (1, SCHEMA_VERSION):
                raise ValueError('policy owner/version')
            roots = data['roots']
            checked = self._checked_roots([r['path'] for r in roots])
            for r in roots:
                if tuple(r['identity']) != _identity(Path(r['path'])):
                    raise ValueError('root changed')
            if data['version'] == 1:
                if type(data.get('enabled')) is not bool or data['enabled'] and not checked:
                    raise ValueError('legacy enabled/roots')
                # RC3 broad read profile migrates only to reviewed restricted roots.
                self._roots = checked if data.get('enabled') is True else {}
                self._operations = set(FILE_OPERATIONS)
            else:
                if data['mode'] not in ('restricted', 'full_user'):
                    raise ValueError('mode')
                operations = data['operations']
                if not isinstance(operations, list) or not set(operations) <= FILE_OPERATIONS:
                    raise ValueError('operations')
                self._validate_rules(data['rules'])
                for grant in data['apps']:
                    if (set(grant) != {'identifiers', 'operation', 'allowed'} or
                        grant['operation'] not in APP_OPERATIONS or type(grant['allowed']) is not bool or
                        not isinstance(grant['identifiers'], list) or not grant['identifiers'] or
                        any(not isinstance(x, str) or len(x) > 4096 for x in grant['identifiers'])):
                        raise ValueError('apps')
                self.mode, self._roots = data['mode'], checked
                if self.mode == 'full_user':
                    current_roots = self._checked_roots(self.root_provider())
                    if not checked or not current_roots or any(not any(root == base or base in root.parents for base, _ in current_roots.values())
                           for root, _ in checked.values()):
                        raise ValueError('Known Folders changed')
                self._operations, self._rules, self._apps = set(operations), data['rules'], data['apps']
                scoped = data.get('root_operations', {})
                if not isinstance(scoped, dict) or any(k not in checked or not isinstance(v, list) or not set(v) <= FILE_OPERATIONS for k, v in scoped.items()):
                    raise ValueError('root operations')
                self._root_operations = scoped
            self._enabled = bool(self._roots)
        except (OSError, ValueError, TypeError, KeyError):
            self._roots, self._rules, self._apps = {}, [], []
            self._root_operations = {}
            self._enabled, self.mode = False, 'restricted'
            self.error = 'Политика повреждена, принадлежит другому пользователю или имеет неизвестную версию. Доступ закрыт; проверь настройки.'

    def _save(self):
        if self.persistence is None:
            return
        from .paths import atomic_json
        from .file_access import FileAccessError
        data = {'version': SCHEMA_VERSION, 'user': self.user_identity(),
            'mode': self.mode, 'operations': sorted(self._operations), 'root_operations': self._root_operations, 'rules': self._rules, 'apps': self._apps,
            'roots': [{'id': key, 'path': str(path), 'identity': identity} for key, (path, identity) in self._roots.items()]}
        if len(json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False).encode('utf-8')) > MAX_POLICY_BYTES:
            raise FileAccessError('Политика слишком велика. Удалите ненужные правила или разрешения.')
        atomic_json(self.persistence, data)

    def _commit(self, mutate):
        with self._lock:
            previous = copy.deepcopy((self.mode, self._roots, self._operations, self._rules, self._apps, self._root_operations, self._enabled, self.error))
            try:
                mutate()
                self._save()
            except Exception:
                self.mode, self._roots, self._operations, self._rules, self._apps, self._root_operations, self._enabled, self.error = previous
                raise
            self.error = None
            self.generation = secrets.token_hex(16)
            self._drafts.clear()
            self.record('permission', 'policy', 'applied')

    def configure(self, mode, roots, operations):
        from .file_access import FileAccessError
        if mode not in ('restricted', 'full_user') or not isinstance(operations, (list, tuple)) or not set(operations) <= FILE_OPERATIONS:
            raise FileAccessError('Неизвестный режим или операция.')
        if mode == 'full_user':
            known = self._checked_roots(self.root_provider())
            extra = self._checked_roots(roots)
            if any(not any(path == base or base in path.parents for base, _ in known.values()) for path, _ in extra.values()):
                raise FileAccessError('Дополнительная область не принадлежит проверенным папкам текущего пользователя.')
            checked = {**known, **extra}
            if not checked:
                raise FileAccessError('Не удалось определить папки текущего пользователя.')
        else:
            checked = self._checked_roots(roots)
        def mutate():
            self.mode, self._roots, self._operations = mode, checked, set(operations)
            self._root_operations = {}
            self._enabled = bool(checked)
        self._commit(mutate)

    def set(self, enabled, roots=()):
        from .file_access import FileAccessError
        if type(enabled) is not bool:
            raise FileAccessError('Нужен явный выбор режима.')
        # Compatibility endpoint can never turn on full_user.
        self.configure('restricted', list(roots) if enabled else [], sorted(FILE_OPERATIONS))

    def enabled(self):
        return self._enabled and not self.error

    def roots(self):
        from .file_access import _checked, _identity, FileAccessError
        with self._lock:
            if self.error:
                raise FileAccessError(self.error)
            if not self._enabled:
                raise FileAccessError('Режим личного компьютера выключен. Выбери разрешённые папки.')
            for root, identity in self._roots.values():
                if _identity(_checked(root)) != identity:
                    raise FileAccessError('Разрешённая папка была заменена. Проверь доступ повторно.')
            return {key: root for key, (root, _) in self._roots.items()}

    def _path_rule(self, rule, path, operation):
        return (rule['kind'] == 'path' and operation in rule['operations'] and
                (path == Path(rule['target']) or Path(rule['target']) in path.parents))

    def set_folder_permission(self, folder, allowed):
        checked = self._checked_roots([str(folder)])
        def mutate():
            for key, value in checked.items():
                if allowed:
                    if key not in self._roots:
                        self._roots[key] = value
                        self._root_operations[key] = ['search', 'read']
                else:
                    self._roots.pop(key, None)
                    self._root_operations.pop(key, None)
            self._enabled = bool(self._roots)
        self._commit(mutate)

    def check_file(self, path, operation, *, legacy=False, record=True):
        from .file_access import FileAccessError
        path = Path(path)
        with self._lock:
            reason, rule_id = None, 'mode'
            if self.error:
                reason, rule_id = self.error, 'invalid_policy'
            elif operation not in FILE_OPERATIONS:
                reason, rule_id = 'Неизвестная операция запрещена.', 'unknown_operation'
            elif not ordinary_path(path):
                reason, rule_id = 'Секретные, чужие и системные файлы исключены из доступа.', 'mandatory_exclusion'
            else:
                for rule in self._rules:
                    if rule['effect'] == 'deny' and self._path_rule(rule, path, operation):
                        reason, rule_id = 'Действие запрещено правилом: ' + rule['description'], rule['id']
                        break
            if reason is None:
                allow_rule = any(r['effect'] == 'allow' and self._path_rule(r, path, operation) for r in self._rules)
                roots = self.roots() if self.enabled() else {}
                in_scope = any(path == root or root in path.parents for root in roots.values())
                scoped_allow = any((path == root or root in path.parents) and operation in self._root_operations.get(key, self._operations) for key, root in roots.items())
                if not (legacy and operation in self._operations or in_scope and (scoped_allow or allow_rule)):
                    reason = 'Операция или папка не разрешена в настройках доступа.'
            if reason:
                if record:
                    self.record(operation, path, 'denied', reason, rule_id)
                raise FileAccessError(reason)
            return True

    def allows(self, path, operation='read'):
        try:
            return self.check_file(path, operation, record=False)
        except (OSError, ValueError):
            return False

    @staticmethod
    def _identifiers(identifiers):
        return {str(x).casefold() for x in ([identifiers] if isinstance(identifiers, str) else identifiers)}

    def check_app(self, identifiers, operation, *, record=True):
        from .file_access import FileAccessError
        ids = self._identifiers(identifiers)
        with self._lock:
            reason, rule_id = None, 'mode'
            if self.error or operation not in APP_OPERATIONS:
                reason, rule_id = self.error or 'Неизвестная операция приложения.', 'invalid_policy'
            for rule in self._rules:
                if rule['kind'] == 'app' and rule['effect'] == 'deny' and operation in rule['operations'] and ids.intersection(rule['identifiers']):
                    reason, rule_id = 'Действие запрещено правилом: ' + rule['description'], rule['id']
            for grant in self._apps:
                if not grant['allowed'] and grant['operation'] == operation and ids.intersection(grant['identifiers']):
                    reason, rule_id = 'Разрешение приложения отозвано.', 'app_denial'
            grants = [g for g in self._apps if g['allowed'] and g['operation'] == operation]
            def matches(g):
                images = {x for x in g['identifiers'] if x.startswith('image:')}
                return bool(ids.intersection(images or g['identifiers']))
            builtin = bool(ids.intersection({'builtin:calculator', 'builtin:notepad'}))
            allow_rule = any(r['kind'] == 'app' and r['effect'] == 'allow' and operation in r['operations'] and
                             ids.intersection({x for x in r['identifiers'] if x.startswith('image:')} or r['identifiers']) for r in self._rules)
            if reason is None and not (self.mode == 'full_user' or builtin or allow_rule or any(matches(g) for g in grants)):
                reason = 'Приложение и операция не разрешены в настройках доступа.'
            if reason:
                if record:
                    self.record(operation, sorted(ids)[0] if ids else 'app', 'denied', reason, rule_id)
                raise FileAccessError(reason)
            return True

    def app_allowed(self, identifiers, operation):
        try:
            return self.check_app(identifiers, operation, record=False)
        except ValueError:
            return False

    def set_app_permission(self, identifiers, operation, allowed):
        return self.set_app_permissions(identifiers, (operation,), allowed)

    def set_app_permissions(self, identifiers, operations, allowed):
        """Commit a legacy combined picker grant atomically, never in stages."""
        from .file_access import FileAccessError
        ids = sorted(self._identifiers(identifiers))
        if (not isinstance(operations, (tuple, list)) or not operations or
                any(operation not in APP_OPERATIONS for operation in operations) or
                type(allowed) is not bool or not ids):
            raise FileAccessError('Некорректное разрешение приложения.')
        def same_application(grant):
            images = {x.rsplit('|', 1)[0] for x in ids if x.startswith('image:')}
            old_images = {x.rsplit('|', 1)[0] for x in grant['identifiers'] if x.startswith('image:')}
            # An unrelated app sharing a display alias must never revoke a deny.
            return bool(images & old_images) if images or old_images else set(ids) == set(grant['identifiers'])
        def mutate():
            self._apps = [g for g in self._apps if not (g['operation'] in operations and same_application(g))]
            self._apps.extend({'identifiers': ids, 'operation': operation, 'allowed': allowed}
                              for operation in dict.fromkeys(operations))
        self._commit(mutate)

    def explicit_app_allowed(self, identifiers, operation):
        ids = self._identifiers(identifiers)
        if not self.app_allowed(ids, operation):
            return False
        return any(g['allowed'] and g['operation'] == operation and
                   ids.intersection({x for x in g['identifiers'] if x.startswith('image:')} or g['identifiers'])
                   for g in self._apps)

    def check_operation(self, operation):
        from .file_access import FileAccessError
        if self.error or operation not in {'settings', 'bookmark', 'workspace'} or not self.enabled() or 'open' not in self._operations:
            reason = self.error or 'Открытие фиксированной страницы или рабочего пространства не разрешено.'
            self.record(operation, 'fixed_target', 'denied', reason, 'mode')
            raise FileAccessError(reason)
        return True

    def _validate_rules(self, rules):
        if not isinstance(rules, list) or len(rules) > 100:
            raise ValueError('rules')
        for r in rules:
            if (not isinstance(r, dict) or r.get('kind') not in ('path', 'app') or r.get('effect') not in ('allow', 'deny') or
                not isinstance(r.get('id'), str) or not isinstance(r.get('description'), str) or
                not isinstance(r.get('operations'), list) or not r['operations'] or
                not set(r['operations']) <= (FILE_OPERATIONS if r['kind'] == 'path' else APP_OPERATIONS)):
                raise ValueError('rule')
            if r['kind'] == 'path':
                if not isinstance(r.get('target'), str) or not Path(r['target']).is_absolute():
                    raise ValueError('rule path')
            elif not isinstance(r.get('identifiers'), list) or not r['identifiers'] or any(not isinstance(x, str) for x in r['identifiers']):
                raise ValueError('rule app')

    def preview(self, text, *, scope=None, apps=(), folders=None):
        from .access_rules import parse_rules
        with self._lock:
            parsed = parse_rules(text, scope=scope, apps=apps, folders=folders or {})
            if parsed.get('clarification'):
                return {**parsed, 'draft_id': None}
            self._validate_rules(parsed['rules'])
            for new in parsed['rules']:
                for old in self._rules:
                    if (new['kind'] == old['kind'] and new['effect'] != old['effect'] and
                        set(new['operations']).intersection(old['operations']) and
                        ((Path(new['target']) == Path(old['target']) or Path(new['target']) in Path(old['target']).parents or
                          Path(old['target']) in Path(new['target']).parents) if new['kind'] == 'path' else set(new['identifiers']).intersection(old['identifiers']))):
                        return {'draft_id': None, 'rules': [], 'interpretation': '', 'clarification': 'Правило противоречит сохранённому. Сначала удалите противоречащее правило.'}
            if len(self._rules) + len(parsed['rules']) > 100:
                raise ValueError('Разрешено до 100 правил.')
            key = secrets.token_urlsafe(24)
            self._drafts = {k: v for k, v in self._drafts.items() if v[0] > time.monotonic()}
            if len(self._drafts) >= 32:
                self._drafts.clear()
            self._drafts[key] = (time.monotonic() + 300, self.generation, copy.deepcopy(parsed['rules']))
            return {**parsed, 'draft_id': key}

    def apply(self, draft_id):
        from .file_access import FileAccessError
        with self._lock:
            draft = self._drafts.get(draft_id)
            if not draft or draft[0] <= time.monotonic() or draft[1] != self.generation:
                raise FileAccessError('Черновик истёк или политика изменилась. Повтори предварительный просмотр.')
            # Validate targets again; preview never establishes permission.
            for r in draft[2]:
                if r['kind'] == 'path':
                    self._checked_roots([r['target']])
            self._commit(lambda: self._rules.extend(copy.deepcopy(draft[2])))

    def remove_rule(self, rule_id):
        self._commit(lambda: setattr(self, '_rules', [r for r in self._rules if r['id'] != rule_id]))

    def record(self, operation, target, decision, reason=None, rule=None):
        with self._lock:
            row = {'at': datetime.now(timezone.utc).isoformat(), 'operation': operation,
                   'target': str(target), 'decision': decision, 'reason': reason, 'rule': rule,
                   'policy_revision': self.generation}
            self._log.append(row)
            if self.persistence:
                from .action_journal import journal
                try:
                    journal.record(operation, str(target), decision, reason=reason, rule=rule, policy_revision=self.generation)
                    self.audit_warning = None
                except (OSError, ValueError):
                    # Permissions have already committed atomically. Do not
                    # misreport them as rolled back because audit storage failed.
                    self.audit_warning = 'Политика сохранена. Журнал доступен в памяти, но запись журнала на диск не удалась.'

    def public(self):
        with self._lock:
            # A settings save must never silently upgrade a legacy read-only
            # folder to every operation checked in an unrelated default profile.
            effective = [set(self._root_operations.get(key, self._operations)) for key in self._roots]
            displayed_operations = set.intersection(*effective) if effective else self._operations
            return {'schema_version': SCHEMA_VERSION, 'mode': self.mode, 'revision': self.generation,
                    'enabled': self.enabled(), 'error': self.error, 'audit_warning': self.audit_warning,
                    'operations': sorted(displayed_operations), 'app_operations': sorted(APP_OPERATIONS),
                    'apps': copy.deepcopy(self._apps), 'rules': copy.deepcopy(self._rules),
                    'roots': [{'id': key, 'path': str(path), 'operations': sorted(self._root_operations.get(key, self._operations))}
                              for key, (path, _) in self._roots.items()],
                    'summary': 'Контроллер проверяет каждое действие. Все изменения файлов требуют отдельного точного подтверждения. Запуск приложения не создаёт системную песочницу.',
                    'excluded': 'Системные каталоги, другие профили, ключи, секреты, хранилища браузеров и LocalMind; ссылки, сетевые пути и команды. Административные права не выдаются.',
                    'access_log': list(self._log)}
