"""Bounded local document extraction. No uploaded paths, execution or persistence.

Complex parsers run in a disposable process with a time and OS memory limit.
Only extracted text is kept in the owning, expiring conversation.
"""
from dataclasses import dataclass
import io
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
import sys
import threading
import zipfile
from xml.etree import ElementTree

MAX_FILE_BYTES = 10 * 1024 * 1024
MAX_TOTAL_BYTES = 40 * 1024 * 1024
MAX_FILES = 8
MAX_TEXT = 12000
MAX_CONTEXT = 32000
MAX_XML_BYTES = 2 * 1024 * 1024
PARSER_TIMEOUT = 10
PARSER_MEMORY = 256 * 1024 * 1024
_parser_slots = threading.BoundedSemaphore(2)
ALLOWED = frozenset(('txt', 'md', 'csv', 'pdf', 'docx'))


class AttachmentError(ValueError):
    pass


@dataclass(frozen=True)
class Document:
    id: str
    name: str
    size: int
    text: str
    truncated: bool

    def public(self, preview=False):
        result = {'id': self.id, 'name': self.name, 'size': self.size,
                  'characters': len(self.text), 'truncated': self.truncated, 'state': 'ready'}
        if preview:
            result['preview'] = self.text[:6000]
        return result


def display_name(filename):
    # Metadata only; never interpret a filename as a client or server path.
    name = str(filename or '').replace('\\', '/').rsplit('/', 1)[-1]
    name = ''.join(c for c in name if c.isprintable())[:180].strip()
    if not name or '.' not in name or name.rsplit('.', 1)[-1].lower() not in ALLOWED:
        raise AttachmentError('Поддерживаются TXT, MD, CSV, текстовые PDF и DOCX.')
    return name


def _normalise(text):
    text = text.replace('\x00', '').strip()
    if not text:
        raise AttachmentError('В документе нет доступного текста. Для сканов нужен OCR, он не включён.')
    return text[:MAX_TEXT], len(text) > MAX_TEXT


def _extract(data, suffix):
    if suffix in ('txt', 'md', 'csv'):
        try:
            text = data.decode('utf-8-sig')
        except UnicodeDecodeError:
            try:
                text = data.decode('utf-16') if data.startswith((b'\xff\xfe', b'\xfe\xff')) else data.decode('cp1251')
            except UnicodeError as exc:
                raise AttachmentError('Не удалось прочитать кодировку текста. Сохрани документ в UTF-8.') from exc
        if '\x00' in text or sum(not c.isprintable() and c not in '\r\n\t' for c in text) > max(2, len(text) // 100):
            raise AttachmentError('Файл содержит двоичные данные вместо текста.')
        return _normalise(text)
    if suffix == 'docx':
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            entries = archive.infolist()
            if len(entries) > 256 or sum(i.file_size for i in entries) > 20 * 1024 * 1024:
                raise AttachmentError('DOCX превышает безопасный предел распаковки.')
            if len([i for i in entries if i.filename == 'word/document.xml']) != 1:
                raise AttachmentError('Некорректная структура DOCX.')
            entry = archive.getinfo('word/document.xml')
            if entry.flag_bits & 1 or entry.file_size > MAX_XML_BYTES or entry.file_size > max(4096, entry.compress_size * 200):
                raise AttachmentError('DOCX зашифрован или превышает безопасный предел распаковки.')
            xml = archive.read(entry)
            if b'\x00' in xml or re.search(br'<!\s*(?:DOCTYPE|ENTITY)', xml, re.I):
                raise AttachmentError('XML-сущности в DOCX не поддерживаются.')
            root = ElementTree.fromstring(xml)
            ns = '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'
            # Paragraphs preserve readable text without loading external resources.
            chunks, total = [], 0
            for paragraph in root.iter(ns + 'p'):
                value = ''.join(node.text or '' for node in paragraph.iter(ns + 't'))
                chunks.append(value)
                total += len(value) + 1
                if total > MAX_TEXT:
                    break
            return _normalise('\n'.join(chunks))
    if suffix == 'pdf':
        from pypdf import PdfReader
        if not data.startswith(b'%PDF-'):
            raise AttachmentError('Файл не является PDF.')
        reader = PdfReader(io.BytesIO(data), strict=True, xref_stream_maximum_entries=100000)
        if reader.is_encrypted:
            raise AttachmentError('Зашифрованные PDF не поддерживаются. Добавь незашифрованную копию.')
        if len(reader.pages) > 200:
            raise AttachmentError('PDF содержит больше 200 страниц. Добавь меньший фрагмент.')
        chunks, total = [], 0
        for index, page in enumerate(reader.pages):
            content = page.get_contents()
            if content is not None and len(content.get_data()) > MAX_XML_BYTES:
                raise AttachmentError('Страница PDF превышает безопасный предел обработки.')
            value = page.extract_text() or ''
            chunks.append(f'\n[Страница {index + 1}]\n' + value if value.strip() else '')
            total += len(chunks[-1])
            if total > MAX_TEXT:
                break
        return _normalise(''.join(chunks))
    raise AttachmentError('Формат документа не поддерживается.')


def _limit_worker_memory():
    if os.name != 'nt':
        import resource
        resource.setrlimit(resource.RLIMIT_AS, (PARSER_MEMORY, PARSER_MEMORY))
        return None
    # A per-worker Windows Job object caps committed process memory. Fail closed
    # if the host disallows assigning this disposable parser to its own job.
    import ctypes
    from ctypes import wintypes
    class Basic(ctypes.Structure):
        _fields_ = [('process_time', ctypes.c_longlong), ('job_time', ctypes.c_longlong),
                    ('flags', wintypes.DWORD), ('min_working', ctypes.c_size_t),
                    ('max_working', ctypes.c_size_t), ('active', wintypes.DWORD),
                    ('affinity', ctypes.c_size_t), ('priority', wintypes.DWORD), ('scheduling', wintypes.DWORD)]
    class IO(ctypes.Structure):
        _fields_ = [(name, ctypes.c_ulonglong) for name in ('read_ops', 'write_ops', 'other_ops', 'read_bytes', 'write_bytes', 'other_bytes')]
    class Limits(ctypes.Structure):
        _fields_ = [('basic', Basic), ('io', IO), ('process_memory', ctypes.c_size_t),
                    ('job_memory', ctypes.c_size_t), ('peak_process', ctypes.c_size_t), ('peak_job', ctypes.c_size_t)]
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.CreateJobObjectW.restype = wintypes.HANDLE
    kernel.CreateJobObjectW.argtypes = (ctypes.c_void_p, wintypes.LPCWSTR)
    kernel.GetCurrentProcess.restype = wintypes.HANDLE
    kernel.SetInformationJobObject.argtypes = (wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD)
    kernel.AssignProcessToJobObject.argtypes = (wintypes.HANDLE, wintypes.HANDLE)
    job = kernel.CreateJobObjectW(None, None)
    limits = Limits()
    limits.basic.flags = 0x100  # JOB_OBJECT_LIMIT_PROCESS_MEMORY
    limits.process_memory = PARSER_MEMORY
    if not job or not kernel.SetInformationJobObject(job, 9, ctypes.byref(limits), ctypes.sizeof(limits)) or not kernel.AssignProcessToJobObject(job, kernel.GetCurrentProcess()):
        raise AttachmentError('Системная изоляция парсера недоступна; документ не обработан.')
    return job  # Keep the handle open for the worker's lifetime.


def _worker(data, suffix):
    try:
        job_handle = _limit_worker_memory()
        text, truncated = _extract(data, suffix)
        return {'text': text, 'truncated': truncated}
    except AttachmentError as exc:
        return {'error': str(exc)}
    except Exception:
        return {'error': 'Документ повреждён или превышает безопасный предел обработки.'}


def extract_document(data, filename):
    name = display_name(filename)
    if not data or len(data) > MAX_FILE_BYTES:
        raise AttachmentError('Файл пуст или превышает 10 МиБ.')
    suffix = name.rsplit('.', 1)[-1].lower()
    if suffix in ('txt', 'md', 'csv'):
        text, truncated = _extract(data, suffix)
    else:
        if not _parser_slots.acquire(blocking=False):
            raise AttachmentError('Парсер занят. Повтори добавление документа позже.')
        try:
            # The executable, module and cwd are application-owned constants;
            # the only argument is an allowlisted format. No filename, path or
            # model/user prose can enter a command. Bytes travel on stdin.
            try:
                process = subprocess.run([sys.executable, '-m', 'localmind.document_worker', suffix],
                    input=data, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=PARSER_TIMEOUT, shell=False,
                    cwd=Path(__file__).resolve().parent.parent,
                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
            except subprocess.TimeoutExpired as exc:
                raise AttachmentError('Превышено время обработки документа (10 секунд).') from exc
            except OSError as exc:
                raise AttachmentError('Изолированный парсер недоступен. Документ не обработан.') from exc
            if process.returncode or not process.stdout or len(process.stdout) > 100000:
                raise AttachmentError('Парсер остановлен: превышен безопасный предел ресурсов.')
            try:
                result = json.loads(process.stdout)
            except (ValueError, UnicodeError) as exc:
                raise AttachmentError('Парсер не смог прочитать документ.') from exc
            if not isinstance(result, dict):
                raise AttachmentError('Некорректный ответ парсера.')
            if 'error' in result:
                raise AttachmentError(result['error'])
            if not isinstance(result.get('text'), str) or len(result['text']) > MAX_TEXT or not isinstance(result.get('truncated'), bool):
                raise AttachmentError('Некорректный ответ парсера.')
            text, truncated = result['text'], result['truncated']
        finally:
            _parser_slots.release()
    return Document(secrets.token_urlsafe(24), name, len(data), text, truncated)


def add_document(conversation, document):
    if len(conversation.attachments) >= MAX_FILES or sum(d.size for d in conversation.attachments.values()) + document.size > MAX_TOTAL_BYTES:
        raise AttachmentError('Предел вложений: 8 файлов и 40 МиБ на разговор.')
    conversation.attachments[document.id] = document


def document_context(conversation, ids):
    if len(set(ids)) != len(ids):
        raise AttachmentError('Вложения повторяются.')
    documents, remaining = [], MAX_CONTEXT
    for key in ids:
        document = conversation.attachments.get(key)
        if document is None:
            raise AttachmentError('Вложение удалено, истекло или принадлежит другому разговору.')
        if remaining <= 0:
            raise AttachmentError('Слишком много текста: выбери меньше документов (до 32000 символов).')
        text = document.text[:remaining]
        documents.append({**document.public(), 'text': text,
                          'characters': len(text), 'truncated': document.truncated or len(text) < len(document.text)})
        remaining -= len(text)
    return documents
