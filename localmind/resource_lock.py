"""Cross-process setup admission; lock handles are released on process exit.

The tiny lock file stays in the model directory. Removing a live lock file would
allow a second process to lock another inode and write the same model files.
"""
from contextlib import contextmanager
import os

from .paths import ordinary_tree


class ResourceBusyError(ValueError):
    pass


@contextmanager
def model_download_lock(root, model):
    if model not in ('small', 'medium', 'large-v3-turbo', 'large-v3'):
        raise ValueError('Неизвестная модель распознавания.')
    with resource_download_lock(root, 'whisper:' + model):
        yield


@contextmanager
def resource_download_lock(root, resource):
    """Silero voices share one file, so they also share one OS lock."""
    if resource == 'silero:ru':
        path = ordinary_tree(root / 'silero' / '.ru.setup.lock')
    elif resource in ('whisper:small', 'whisper:medium', 'whisper:large-v3-turbo', 'whisper:large-v3'):
        path = ordinary_tree(root / 'whisper' / ('.' + resource.split(':')[1] + '.setup.lock'))
    else:
        raise ValueError('Неизвестный ресурс загрузки.')
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a+b') as handle:
        handle.seek(0, os.SEEK_END)
        if handle.tell() == 0:
            handle.write(b'0')
            handle.flush()
        handle.seek(0)
        try:
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            raise ResourceBusyError('Подготовка этой модели уже выполняется в другом процессе. Дождитесь завершения и повторите.') from None
        try:
            yield
        finally:
            handle.seek(0)
            if os.name == 'nt':
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
