"""Optional local text retrieval; configured IDs, explicit exact-source grants.

Neither model prose nor retrieved content can register sources or grant access.
The owner configures a bounded list of UTF-8 .txt/.md sources. Session permission
is separate from catalog listing and invalidates if identity or bytes change.
No recursion, URLs, embeddings, downloads, shell, or file execution exists here.
"""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import stat
from threading import RLock

from .file_access import _checked, _locked_path, _read_handle
from .settings import ROOT

MAX_SOURCES = 16
MAX_SOURCE_BYTES = 256 * 1024
MAX_PASSAGES = 64


class RetrievalError(ValueError):
    pass


def _stamp(path):
    item = path.stat(follow_symlinks=False)
    if not stat.S_ISREG(item.st_mode) or item.st_size > MAX_SOURCE_BYTES:
        raise RetrievalError('Источник должен быть обычным текстовым файлом до 256 КБ.')
    return item.st_dev, item.st_ino, item.st_size, item.st_mtime_ns, item.st_ctime_ns


def _terms(text):
    stop = {'это', 'как', 'что', 'его', 'она', 'оно', 'для', 'или', 'при', 'так', 'the', 'and', 'этот', 'того'}
    return {x for x in re.findall(r'[\w]+', text.casefold().replace('ё', 'е')) if len(x) >= 2 and x not in stop}


class LocalRetrieval:
    def __init__(self, sources=None, *, policy=None):
        self._policy = policy
        if sources is None:
            config = ROOT / 'config' / 'retrieval_sources.json'
            if config.exists():
                if config.stat().st_size > 32768:
                    raise RetrievalError('Слишком большой каталог источников.')
                sources = json.loads(config.read_text(encoding='utf-8'))['sources']
            else:
                sources = []
        if not isinstance(sources, list) or len(sources) > MAX_SOURCES:
            raise RetrievalError('Разрешено до 16 локальных источников.')
        self._sources, self._grants, self._lock = {}, {}, RLock()
        for item in sources:
            if (not isinstance(item, dict) or set(item) != {'id', 'label', 'path'}
                    or not isinstance(item['id'], str) or not re.fullmatch(r'[a-zA-Z0-9_-]{1,64}', item['id'])
                    or item['id'] in self._sources or not isinstance(item['label'], str)
                    or not 1 <= len(item['label']) <= 120 or not isinstance(item['path'], str)
                    or not 1 <= len(item['path']) <= 1024):
                raise RetrievalError('Некорректный каталог источников.')
            path = Path(item['path'])
            if not path.is_absolute():
                path = ROOT / path
            if ':' in str(path)[len(path.drive):]:
                raise RetrievalError('Альтернативные потоки файлов запрещены.')
            if path.suffix.lower() not in ('.txt', '.md'):
                raise RetrievalError('Поддерживаются только UTF-8 .txt и .md.')
            self._sources[item['id']] = {'label': item['label'], 'path': path}

    @property
    def policy(self):
        if self._policy is None:
            from .file_access import file_access
            return file_access.personal_mode
        return self._policy

    def _metadata(self, source_id):
        item = self._sources.get(source_id)
        if item is None:
            raise RetrievalError('Неизвестный источник; путь из модели не принимается.')
        path = _checked(item['path'])
        stamp = _stamp(path)
        fingerprint = hashlib.sha256(repr((str(path), stamp)).encode('utf-8')).hexdigest()
        return path, stamp, fingerprint

    def _read(self, source_id):
        path, stamp, fingerprint = self._metadata(source_id)
        with self.policy._lock, _locked_path(path):
            # Exact configured-source consent may supply the scope, never
            # override mandatory exclusions or a later user prohibition.
            self.policy.check_file(path, 'read', legacy=True)
            if self._metadata(source_id) != (path, stamp, fingerprint):
                raise RetrievalError('Источник изменился во время проверки.')
            with _read_handle(path, stamp[:2]) as stream:
                data = stream.read(MAX_SOURCE_BYTES + 1)
            if len(data) > MAX_SOURCE_BYTES or _stamp(path) != stamp:
                raise RetrievalError('Источник изменился во время чтения.')
        text = data.decode('utf-8-sig', errors='strict')
        if '\x00' in text:
            raise RetrievalError('Двоичные источники запрещены.')
        return path, stamp, fingerprint, hashlib.sha256(data).hexdigest(), text

    def entries(self):
        """Metadata only: no source contents are read without a permission call."""
        entries = []
        with self._lock:
            for source_id, item in self._sources.items():
                try:
                    path, stamp, fingerprint = self._metadata(source_id)
                    grant = self._grants.get(source_id)
                    entries.append({'id': source_id, 'label': item['label'], 'filename': path.name,
                                    'path': str(path), 'fingerprint': fingerprint,
                                    'allowed': bool(grant and grant[0] == fingerprint and grant[2] == self.policy.generation), 'available': True})
                except (OSError, ValueError, RuntimeError):
                    self._grants.pop(source_id, None)
                    entries.append({'id': source_id, 'label': item['label'], 'available': False, 'allowed': False})
        return entries

    def set_permission(self, source_id, allowed, fingerprint=None):
        if not isinstance(source_id, str) or type(allowed) is not bool:
            raise RetrievalError('Разрешение должно быть явным логическим значением.')
        with self._lock, self.policy._lock:
            if source_id not in self._sources:
                raise RetrievalError('Неизвестный источник.')
            if not allowed:
                self._grants.pop(source_id, None)
                return
            try:
                path, stamp, current = self._metadata(source_id)
                if current != fingerprint:
                    raise RetrievalError('Источник изменился; проверь разрешение повторно.')
                _, _, checked, digest, _ = self._read(source_id)
                if checked != current:
                    raise RetrievalError('Источник изменился; проверь разрешение повторно.')
                self._grants[source_id] = current, digest, self.policy.generation
            except (OSError, UnicodeError, ValueError, RuntimeError) as exc:
                self._grants.pop(source_id, None)
                raise RetrievalError('Не удалось безопасно разрешить текстовый источник.') from exc

    def search(self, query, limit=3):
        if not isinstance(query, str) or not 1 <= len(query) <= 2000 or type(limit) is not int or not 1 <= limit <= 5:
            raise RetrievalError('Некорректный локальный поисковый запрос.')
        terms = _terms(query)
        hits, unavailable = [], []
        if not terms:
            return {'hits': [], 'unavailable_source_ids': [], 'authority': 'untrusted_reference_text_only'}
        with self._lock:
            for source_id, grant in list(self._grants.items()):
                try:
                    with self.policy._lock:
                        if grant[2] != self.policy.generation:
                            raise RetrievalError('Политика доступа изменилась. Разрешите источник повторно.')
                        path, stamp, fingerprint, digest, text = self._read(source_id)
                        if grant[:2] != (fingerprint, digest):
                            raise RetrievalError('Источник заменён или изменён.')
                    # Bounded non-overlapping passages with exact line provenance.
                    lines, passage, start = text.splitlines(), [], 1
                    passages = []
                    for index, line in enumerate(lines, 1):
                        if len(line) > 1800:
                            line = line[:1800]
                        if passage and sum(map(len, passage)) + len(line) > 1800:
                            passages.append((start, index - 1, '\n'.join(passage)))
                            passage, start = [], index
                        passage.append(line)
                        if len(passages) >= MAX_PASSAGES:
                            break
                    if passage and len(passages) < MAX_PASSAGES:
                        passages.append((start, min(len(lines), start + len(passage) - 1), '\n'.join(passage)))
                    for first, last, excerpt in passages:
                        score = len(terms & _terms(excerpt))
                        if score:
                            hits.append({'source_id': source_id, 'label': self._sources[source_id]['label'],
                                         'filename': path.name, 'line_start': first, 'line_end': last,
                                         'excerpt': excerpt, 'sha256': digest, 'score': score,
                                         'modified_utc': datetime.fromtimestamp(stamp[3] / 1e9, timezone.utc).isoformat()})
                except (OSError, UnicodeError, ValueError, RuntimeError):
                    self._grants.pop(source_id, None)
                    unavailable.append(source_id)
        hits.sort(key=lambda x: (-x['score'], x['source_id'], x['line_start']))
        return {'hits': hits[:limit], 'unavailable_source_ids': unavailable,
                'authority': 'untrusted_reference_text_only'}


retrieval = LocalRetrieval()
