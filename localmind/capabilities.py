"""One declaration/validation/adapter boundary for PC capabilities.

Model planning can select a tool, never create a grant. llm_planner validates
operation/target grounding before this boundary; adapters independently recheck
OS identity and permissions before every side effect.
"""
from dataclasses import dataclass
import os

from .results import ActionResult, refused
from .generation import check_cancelled


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
    return _windows().open_app(args['app_id'], open_app)


def _latest(args, owner):
    from .file_access import file_access
    return file_access.find_latest(owner)


def _file(args, owner):
    from .file_access import file_access
    return file_access.open_selected(owner, args['file_id'])


def _search(args, owner):
    from .file_access import file_access
    if (args['sort_by'] not in ('modified', 'created', 'size', 'name') or args['order'] not in ('asc', 'desc')
            or args['extension'] not in ('', 'pdf', 'txt', 'md', 'docx', 'csv', 'json', 'tsv')):
        return refused('files.search', None, 'Недопустимые фильтры поиска.')
    return file_access.search(owner, query=args['query'],
                              extensions=('.' + args['extension'],) if args['extension'] else None,
                              scope='all' if args['scope'] == 'approved' else args['scope'], sort_by=args['sort_by'], order=args['order'])


def _read(args, owner):
    from .file_access import file_access
    return file_access.read_selected(owner, args['file_id'])


def _describe(args, owner):
    from .file_access import file_access
    info = file_access.selected_info(owner, args['file_id'])
    return ActionResult(True, 'files.describe_selected_file', args['file_id'], 'observed', 'file_metadata',
                        status_text=info['filename'] + '\n' + info['path'], data=info)


def _light(args, owner):
    from .devices import set_light
    return set_light(args['device_id'], args['state'])


class CapabilityRegistry:
    def __init__(self):
        from .desktop_tools import open_settings, open_bookmark, open_workspace, prepare_mutation
        from .devices import list_enabled
        definitions = [
            Capability('apps.list_running', (), 'reviewed_request_and_app_grant', 'Список проверенных окон разрешённых приложений.', lambda a, o: _windows().list_running()),
            Capability('apps.open', ('app_id',), 'fingerprint_bound_app_grant', 'Запустить разрешённое приложение или выбрать его проверенное окно.', _open),
            Capability('apps.focus', ('app_id',), 'fingerprint_bound_app_grant', 'Найти окно разрешённого приложения и один раз вывести на передний план; без always-on-top.', lambda a, o: _windows().focus_app(a['app_id'])),
            Capability('apps.focus_window', ('window_id',), 'verified_window_and_app_grant', 'Перевести проверенное окно на передний план, если Windows разрешает.', lambda a, o: _windows().focus_window(a['window_id'])),
            Capability('apps.minimize_window', ('window_id',), 'verified_window_and_app_grant', 'Свернуть проверенное окно.', lambda a, o: _windows().minimize_window(a['window_id'])),
            Capability('apps.restore_window', ('window_id',), 'verified_window_and_app_grant', 'Восстановить проверенное окно.', lambda a, o: _windows().restore_window(a['window_id'])),
            Capability('apps.close_window_safely', ('window_id',), 'verified_window_and_safe_close_policy', 'Мягко закрыть безопасное окно; для документов объяснить ограничение.', lambda a, o: _windows().close_window_safely(a['window_id'])),
            Capability('files.find_latest_pdf_in_downloads', (), 'explicit_downloads_read_grant', 'Найти PDF по времени изменения, без вложенных папок.', _latest),
            Capability('files.open_selected_file', ('file_id',), 'separate_exact_pdf_open_grant', 'Открыть выбранный неизменённый PDF.', _file),
            Capability('files.search', ('query', 'extension', 'scope', 'sort_by', 'order'), 'approved_read_scope', 'Поиск обычных файлов с фильтрами и порядком сортировки.', _search),
            Capability('files.read_selected_file', ('file_id',), 'approved_read_scope', 'Прочитать фактическое содержимое выбранного файла.', _read),
            Capability('files.describe_selected_file', ('file_id',), 'approved_read_scope', 'Показать проверенное имя и путь выбранного файла.', _describe),
            Capability('files.prepare_mutation', ('operation', 'scope', 'filename', 'content', 'destination'), 'extended_and_separate_exact_confirmation', 'Подготовить изменение обычного файла в выбранной папке. Само изменение требует отдельной кнопки подтверждения.', prepare_mutation),
            Capability('system.open_settings', ('page_id',), 'extended_fixed_windows_page', 'Открыть страницу Экран или Звук; не изменяет настройки.', open_settings),
            Capability('browser.open_bookmark', ('bookmark_id',), 'extended_fixed_bookmark', 'Открыть заранее объявленную закладку в браузере.', open_bookmark),
            Capability('workspaces.open', ('workspace_id',), 'each_app_grant', 'Открыть окна рабочего пространства Учёба: Блокнот и Калькулятор.', open_workspace),
            Capability('set_light', ('device_id', 'state'), 'reviewed_request_and_configured_device', 'Включить или выключить разрешённую лампу; DEMO обозначается симуляцией.', _light),
            Capability('devices.list_enabled', (), 'configured_device_allowlist', 'Проверить, какие разрешённые light/switch сейчас включены.', lambda a, o: list_enabled()),
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
                    and all(type(v) is str and (0 < len(v) <= 128 or
                            intent.name == 'files.search' and k in ('query', 'extension') and v == '' or
                            intent.name == 'files.prepare_mutation' and k in ('content', 'destination') and len(v) <= 128)
                            for k, v in intent.arguments.items()))

    def execute(self, intent, authorization, owner):
        from .devices import DeviceError
        if not self.validate(intent) or intent != authorization or not owner:
            return refused('policy', None, 'Инструмент или точная цель не авторизованы проверенным запросом.')
        check_cancelled()
        try:
            result = self.tools[intent.name].adapter(intent.arguments, owner)
        except (ValueError, OSError, DeviceError) as exc:
            # Adapters use ValueError for user-readable policy failures; never
            # reflect arbitrary OS exception strings (which may contain secrets).
            from .file_access import FileAccessError
            result = refused(intent.name, None, str(exc) if isinstance(exc, FileAccessError)
                             else 'Операция недоступна или цель изменилась.', status='failed')
        if not isinstance(result, ActionResult):
            return refused(intent.name, None, 'Результат инструмента не подтверждён.', status='unknown')
        return result

    def snapshot(self):
        return [{'name': t.name, 'arguments': t.schema(), 'permission': t.permission,
                 'available': t.name == 'set_light' or os.name == 'nt', 'description': t.description}
                for t in self.tools.values()]


registry = CapabilityRegistry()
