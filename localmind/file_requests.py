"""Ground explicit file requests in saved scope IDs, never in model paths."""
from pathlib import Path
import re

from .capabilities import ToolIntent
from .file_access import FileAccessError


READ_PREFIX = (
    r'(?:прочи?тай\s+(?:содержимое\s+)?(?:файл|документ)(?:а)?|'
    r'(?:покажи|выведи)\s+содержимое\s+(?:файла|документа)|'
    r'что\s+(?:написано|содержится)\s+в\s+(?:файле|документе)|'
    r'что\s+(?:находится\s+)?внутри\s+(?:файла|документа))'
)

SUMMARY_PREFIX = (
    r'(?:(?:о\s+ч[её]м|про\s+что)\s+(?:этот\s+)?(?:файл|документ)|'
    r'(?:кратко\s+)?перескажи\s+(?:содержимое\s+)?(?:файл|документ)(?:а)?|'
    r'сделай\s+(?:краткий\s+)?пересказ\s+(?:файла|документа)|'
    r'расскажи\s+(?:о\s+(?:файле|документе)|про\s+(?:файл|документ)))'
)

DIRECTORY_PREFIX = (
    r'(?:какие\s+(?:файлы|папки|подпапки)(?:\s+(?:есть|находятся|лежат))?\s+в|'
    r'(?:перечисли|покажи)\s+(?:файлы|папки|подпапки)\s+в|список\s+файлов\s+в|'
    r'покажи,?\s+что\s+(?:находится|лежит|есть)\s+в|что\s+(?:лежит|находится)\s+в)'
    r'\s+(?:(?:папке|каталоге)\s+)?|(?:покажи|выведи)\s+содержимое\s+(?:папки|каталога)\s+'
)
PATH_QUOTES = {'"': '"', '«': '»', '“': '”', "'": "'"}


def _unquote_target(target):
    if len(target) > 1 and PATH_QUOTES.get(target[0]) == target[-1]:
        return target[1:-1]
    return target


def directory_request(text):
    text = text.strip()
    match = re.fullmatch(r'(?:пожалуйста[,\s]+)?(?:' + DIRECTORY_PREFIX + r')(.+)',
                         text, re.I)
    if not match:
        return None
    target = _unquote_target(match[1].rstrip('?.').strip())
    # A generic question such as «Что лежит в основе теории?» stays dialogue.
    if not re.match(r'(?:[a-z]:|[\\/])', target, re.I) and not re.search(
            r'\b(?:папк[еи]|каталог[еа])\s*$', text[:match.start(1)], re.I):
        return None
    return ToolIntent('files.list_directory', {'path': target})


def _target(text, prefix, suffix=''):
    match = re.fullmatch(
        r'(?:пожалуйста[, ]+)?' + prefix + r'\s+(.+?)' + suffix + r'[?!.]?', text.strip(), re.I)
    return match.group(1) if match else None


def _resolve_target(target, operation):
    """Resolve lexically, without enumeration, reading bytes or creating grants."""
    from .file_access import file_access
    from .personal_permissions import known_folder
    unquoted = _unquote_target(target)
    try:
        named = re.fullmatch(r'([^/\\:]+)\s+в\s+папке\s+([^/\\:]+)\s+на\s+рабочем\s+столе', unquoted, re.I)
        scoped = re.fullmatch(r'([^/\\:]+?)\s+(?:в|из)\s+папк[еи]\s+(.+)', target, re.I)
        if named:
            filename, folder = (value.strip() for value in named.groups())
            if any(value in ('.', '..') or value.rstrip(' .') != value for value in (filename, folder)):
                raise FileAccessError('Некорректное имя файла или папки.')
            path = known_folder('desktop') / folder / filename
            target = str(path)
        elif scoped:
            filename, folder = (_unquote_target(value.strip()) for value in scoped.groups())
            if not filename or filename in ('.', '..') or filename.rstrip(' .') != filename:
                raise FileAccessError('Некорректное имя файла.')
            parent = Path(folder)
            if not parent.is_absolute():
                raise FileAccessError('Укажи полный локальный путь к папке.')
            path = parent / filename
            target = str(path)
        else:
            target = unquoted
            path = Path(target)
        if (not path.is_absolute() or str(path).startswith(('\\\\', '//'))
                or '..' in path.parts or not path.name or len(str(path)) > 1024
                or ':' in str(path)[len(path.drive):] or any(c in '<>|*?"«»“”`' or ord(c) < 32 for c in target)
                or any(part.rstrip(' .') != part for part in path.parts if part != path.anchor)):
            raise FileAccessError('Укажи полный локальный путь или имя файла в папке на рабочем столе.')
        roots = file_access.personal_mode.roots()
        matches = [(key, root) for key, root in roots.items() if root in path.parents]
        if not matches:
            file_access.personal_mode.check_file(path, operation)
            raise FileAccessError('Папка файла не разрешена в настройках доступа.')
        key, root = max(matches, key=lambda item: len(item[1].parts))
        return (key, str(path.relative_to(root))), None
    except (OSError, ValueError) as exc:
        return None, str(exc) if isinstance(exc, FileAccessError) else 'Не удалось определить разрешённую папку файла.'


def read_request(text):
    target = _target(text, '(?:' + READ_PREFIX + '|' + SUMMARY_PREFIX + ')',
                     r'(?:\s+и\s+скажи\s+код(?:\s+проверки)?)?')
    if target is None:
        return None, None
    resolved, error = _resolve_target(target, 'read')
    return (ToolIntent('files.read_file', {'scope': resolved[0], 'relative_path': resolved[1]})
            if resolved else None), error


def latest_download_request(text):
    """A bounded retrieval request, never a claim about actual download time."""
    match = re.fullmatch(
        r'(?:пожалуйста[, ]+)?(?:(?:найди|покажи)\s+)?'
        r'(?:последний|новейший|самый\s+новый)\s+(?:скачанный\s+)?'
        r'(?:pdf(?:[- ]файл)?|пдф(?:[- ]файл)?)'
        r'(?:\s+в\s+(?:(?:папке|каталоге)\s+)?(?:downloads?|загрузк(?:и|ах)))?'
        r'(?:[, ]+пожалуйста)?[.!?]?', text.strip(), re.I)
    if not match:
        return None
    if text.strip().casefold().rstrip('.!') in ('найди последний pdf', 'найди последний pdf в загрузках'):
        return ToolIntent('files.find_latest_pdf_in_downloads', {})
    return ToolIntent('files.search', {'query': '', 'extension': 'pdf', 'scope': 'downloads',
                                     'sort_by': 'modified', 'order': 'desc'})


def delete_request(text):
    target = _target(text, r'удали\s+(?:файл|документ)')
    if target is None:
        return None, None
    resolved, error = _resolve_target(target, 'delete')
    return (ToolIntent('files.prepare_mutation', {'operation': 'delete', 'scope': resolved[0],
            'filename': resolved[1], 'content': '', 'destination': ''}) if resolved else None), error


def image_path_request(text):
    """Detect disk image questions without checking the file or reading bytes."""
    prefix = (r'(?:что\s+(?:изображено|нарисовано|показано)\s+на\s+(?:картинке|изображении|фото)|'
              r'опиши\s+(?:картинку|изображение|фото)|' + READ_PREFIX + r')')
    target = _target(text, prefix)
    target = _unquote_target(target) if target else ''
    return bool(target and re.match(r'(?:[a-z]:[/\\]|/|\\\\)', target, re.I)
                and re.search(r'\.(?:png|jpe?g|webp|gif|bmp|tiff?)$', target, re.I))
