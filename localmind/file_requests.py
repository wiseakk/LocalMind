"""Ground explicit read requests in saved scope IDs, never in model paths."""
from pathlib import Path
import re

from .capabilities import ToolIntent
from .file_access import FileAccessError


def read_request(text):
    """Resolve lexically, without enumeration, reading bytes or creating grants."""
    match = re.fullmatch(
        r'(?:пожалуйста[, ]+)?прочитай\s+(?:содержимое\s+)?файл(?:а)?\s+'
        r'(.+?)(?:\s+и\s+скажи\s+код(?:\s+проверки)?)?[.!]?', text.strip(), re.I)
    if not match:
        return None, None
    target = match.group(1)
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
            raise FileAccessError('Папка файла не разрешена в настройках доступа.')
        key, root = max(matches, key=lambda item: len(item[1].parts))
        return ToolIntent('files.read_file', {'scope': key, 'relative_path': str(path.relative_to(root))}), None
    except (OSError, ValueError) as exc:
        return None, str(exc) if isinstance(exc, FileAccessError) else 'Не удалось определить разрешённую папку файла.'
