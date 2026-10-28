"""One declaration/validation/adapter boundary for PC capabilities.

Model planning can select a proposal, never create a grant. A user-text-derived
exact envelope is checked again here before an adapter sees any argument.
"""
from dataclasses import dataclass
import os

from .results import ActionResult, refused


@dataclass(frozen=True)
class ToolIntent:
    name: str
    arguments: dict


@dataclass(frozen=True)
class Capability:
    name: str
    arguments: tuple[str, ...]
    permission: str
    description: str
    adapter: object

    def schema(self):
        return {'type': 'object', 'additionalProperties': False,
                'properties': {k: {'type': 'string', 'minLength': 1, 'maxLength': 128} for k in self.arguments},
                'required': list(self.arguments)}


def _windows():
    from .window_tools import window_tools
    from .agent import resolve_windows_app
    window_tools.configure_builtin_resolver(resolve_windows_app)
    return window_tools


def _open(args, owner):
    from .agent import open_app
    window_id, error = _windows().select_app_window(args['app_id'])
    if window_id:
        return _windows().focus_window(window_id)
    if error and error.execution_status == 'ambiguous':
        return error
    return open_app(args['app_id'])


def _latest(args, owner):
    from .file_access import file_access
    return file_access.find_latest(owner)


def _file(args, owner):
    from .file_access import file_access
    return file_access.open_selected(owner, args['file_id'])


def _light(args, owner):
    from .devices import set_light
    return set_light(args['device_id'], args['state'])


class CapabilityRegistry:
    def __init__(self):
        definitions = [
            Capability('apps.list_running', (), 'reviewed_request_and_app_grant', 'Список проверенных окон разрешённых приложений.', lambda a, o: _windows().list_running()),
            Capability('apps.open', ('app_id',), 'fingerprint_bound_app_grant', 'Запустить разрешённое приложение или выбрать его проверенное окно.', _open),
            Capability('apps.focus_window', ('window_id',), 'verified_window_and_app_grant', 'Перевести проверенное окно на передний план, если Windows разрешает.', lambda a, o: _windows().focus_window(a['window_id'])),
            Capability('apps.close_window_safely', ('window_id',), 'verified_window_and_safe_close_policy', 'Мягко закрыть безопасное окно; для документов объяснить ограничение.', lambda a, o: _windows().close_window_safely(a['window_id'])),
            Capability('files.find_latest_pdf_in_downloads', (), 'explicit_downloads_read_grant', 'Найти PDF по времени изменения, без вложенных папок.', _latest),
            Capability('files.open_selected_file', ('file_id',), 'separate_exact_pdf_open_grant', 'Открыть выбранный неизменённый PDF.', _file),
            Capability('set_light', ('device_id', 'state'), 'reviewed_request_and_configured_device', 'Включить или выключить разрешённую лампу; DEMO обозначается симуляцией.', _light),
        ]
        self.tools = {d.name: d for d in definitions}

    def validate(self, intent):
        if not isinstance(intent, ToolIntent) or not isinstance(intent.name, str):
            return False
        tool = self.tools.get(intent.name)
        if intent.name == 'set_light':
            from .settings import DEVICES
            if (type(intent.arguments) is not dict or type(intent.arguments.get('device_id')) is not str
                    or intent.arguments['device_id'] not in DEVICES or intent.arguments.get('state') not in ('on', 'off')):
                return False
        return bool(tool and type(intent.arguments) is dict and set(intent.arguments) == set(tool.arguments)
                    and all(type(v) is str and 0 < len(v) <= 128 for v in intent.arguments.values()))

    def execute(self, intent, authorization, owner):
        if not self.validate(intent) or intent != authorization or not owner:
            return refused('policy', None, 'Инструмент или точная цель не авторизованы проверенным запросом.')
        result = self.tools[intent.name].adapter(intent.arguments, owner)
        if not isinstance(result, ActionResult):
            return refused(intent.name, None, 'Результат инструмента не подтверждён.', status='unknown')
        return result

    def snapshot(self):
        return [{'name': t.name, 'arguments': t.schema(), 'permission': t.permission,
                 'available': t.name == 'set_light' or os.name == 'nt', 'description': t.description}
                for t in self.tools.values()]


registry = CapabilityRegistry()
