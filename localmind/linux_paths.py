"""Read freedesktop user-directory assignments without executing shell syntax."""
import os
from pathlib import Path
import re


def user_directory(name):
    home = Path.home()
    config = Path(os.environ.get('XDG_CONFIG_HOME', ''))
    if not config.is_absolute():
        config = home / '.config'
    if name == 'profile':
        return home
    key = 'DOWNLOAD' if name == 'downloads' else name.upper()
    try:
        with (config / 'user-dirs.dirs').open(encoding='utf-8') as stream:
            text = stream.read(16385)
        if len(text) <= 16384:
            match = re.search(r'^XDG_' + re.escape(key) + r'_DIR="([^"\n]*)"$', text, re.M)
            if match:
                value = match[1]
                if value.startswith('$HOME/'):
                    value = str(home / value[6:])
                path = Path(value)
                if path.is_absolute() and '..' not in path.parts and not any(c in value for c in '$`\\'):
                    return path
    except (OSError, UnicodeError):
        pass
    return home / name.title()
