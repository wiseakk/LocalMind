"""Ground explicit file requests in saved scope IDs, never in model paths."""
from pathlib import Path
import re

from .capabilities import ToolIntent
from .file_access import FileAccessError


READ_PREFIX = (
    r'(?:прочитай\s+(?:содержимое\s+)?(?:файл|документ)(?:а)?|'
    r'(?:покажи|выведи)\s+содержимое\s+(?:файла|документа)|'
    r'что\s+(?:написано|содержится)\s+в\s+(?:файле|документе)|'
    r'что\s+(?:находится\s+)?внутри\s+(?:файла|документа))'
)


def _target(text, prefix, suffix=''):
    match = re.fullmatch(
        r'(?:пожалуйста[, ]+)?' + prefix + r'\s+(.+?)' + suffix + r'[?!.]?', text.strip(), re.I)
    return match.group(1) if match else None


def _resolve_target(target, operation):
    """Resolve lexically, without enumeration, reading bytes or creating grants."""
    from .file_access import file_access
    from .personal_permissions import known_folder
    try:
        named = re.fullmatch(r'([^/\\:]+)\s+в\s+папке\s+([^/\\:]+)\s+на\s+рабочем\s+столе', target, re.I)
        if named:
            filename, folder = (value.strip() for value in named.groups())
            if any(value in ('.', '..') or value.rstrip(' .') != value for value in (filename, folder)):
                raise FileAccessError('Некорректное имя файла или папки.')
            path = known_folder('desktop') / folder / filename
        else:
            path = Path(target)
        if (not path.is_absolute() or str(path).startswith(('\\\\', '//'))
                or '..' in path.parts or not path.name or len(str(path)) > 1024
                or ':' in str(path)[len(path.drive):]
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
    target = _target(text, READ_PREFIX, r'(?:\s+и\s+скажи\s+код(?:\s+проверки)?)?')
    if target is None:
        return None, None
    resolved, error = _resolve_target(target, 'read')
    return (ToolIntent('files.read_file', {'scope': resolved[0], 'relative_path': resolved[1]})
            if resolved else None), error


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
    return bool(target and re.match(r'(?:[a-z]:[/\\]|/|\\\\)', target, re.I)
                and re.search(r'\.(?:png|jpe?g|webp|gif|bmp|tiff?)$', target, re.I))
