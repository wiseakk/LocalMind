"""Versioned user preferences and explicit setup completion, independent of models.

Only declared UX choices are stored here. Permissions, audio and credentials
never enter this file. Atomic replacement preserves the previous state on error.
"""
from threading import RLock
import json
from . import paths, storage

_lock = RLock()
STATE_VERSION = 1


def _path():
    return paths.ordinary_tree(paths.CONFIG / 'product-state.json')


def read():
    with _lock:
        path = _path()
        if not path.exists():
            return {'version': STATE_VERSION, 'onboarding': {'completed': False},
                    'tour': {'completed': False, 'skipped': False}, 'preferences': {}}
        try:
            value = json.loads(path.read_text(encoding='utf-8'))
            if (not isinstance(value, dict) or value.get('version') != STATE_VERSION
                    or any(not isinstance(value.get(k), dict) for k in ('onboarding', 'tour', 'preferences'))):
                raise ValueError()
            return value
        except (ValueError, TypeError):
            raise ValueError('Не удалось прочитать сохранённую настройку. Исходный файл сохранён; проверьте каталог данных.') from None


def update(section, values):
    # Route validation is deliberately repeated at the persistence boundary.
    allowed = {
        'onboarding': {'completed', 'step', 'profile', 'skip_asr', 'skip_tts'},
        'tour': {'completed', 'skipped'},
        'preferences': {'theme', 'reduce_motion', 'low_performance', 'voice_profile', 'tts_voice', 'speak'},
    }
    if section not in allowed or set(values) - allowed[section]:
        raise ValueError('Неизвестная настройка.')
    choices = {'theme': {'dark', 'light'}, 'profile': {'cpu-fast', 'balanced', 'gpu-quality'},
               'voice_profile': {'cpu-fast', 'balanced', 'gpu-quality'},
               'tts_voice': {'ru_RU-denis-medium', 'silero-v5_6-ru', 'chatterbox-v3-ru'}}
    for key, value in values.items():
        if key in choices:
            if value not in choices[key]:
                raise ValueError('Недопустимое значение настройки.')
        elif key == 'step':
            if type(value) is not int or not 0 <= value <= 5:
                raise ValueError('Недопустимый шаг настройки.')
        elif type(value) is not bool:
            raise ValueError('Настройка должна быть логическим значением.')
    storage.begin_mutation()
    try:
        with _lock:
            state = read()
            state[section].update(values)
            paths.atomic_json(_path(), state)
            return state
    finally:
        storage.end_mutation()
