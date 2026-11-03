"""Finite desktop helpers. No shell, LLM paths, command strings or user URLs."""
import os
from .results import ActionResult, refused

SETTINGS_PAGES = {'display': ('Экран', 'ms-settings:display'), 'sound': ('Звук', 'ms-settings:sound')}
BOOKMARKS = {'localmind_help': ('Справка Ollama', 'https://github.com/ollama/ollama/blob/main/docs/faq.md')}
WORKSPACES = {'study': {'name': 'Учёба', 'aliases': ('учёба', 'учеба', 'учебное'), 'apps': ('notepad', 'calculator')}}


def open_settings(args, owner):
    from .file_access import file_access
    if not file_access.personal_mode.enabled():
        return refused('system.open_settings', None, 'Сначала включите расширенный доступ в настройках.')
    page = SETTINGS_PAGES.get(args['page_id'])
    if not page or os.name != 'nt':
        return refused('system.open_settings', None, 'Эта страница настроек недоступна.')
    os.startfile(page[1])  # Fixed Windows settings URI; does not change a setting.
    return ActionResult(False, 'system.open_settings', args['page_id'], 'request_accepted',
                        status_text=f'Windows получила запрос открыть «{page[0]}». Появление страницы не подтверждено.')


def open_bookmark(args, owner):
    from .file_access import file_access
    if not file_access.personal_mode.enabled():
        return refused('browser.open_bookmark', None, 'Открытие внешних сайтов доступно в расширенном режиме.')
    bookmark = BOOKMARKS.get(args['bookmark_id'])
    if not bookmark or os.name != 'nt':
        return refused('browser.open_bookmark', None, 'Закладка недоступна.')
    os.startfile(bookmark[1])
    return ActionResult(False, 'browser.open_bookmark', args['bookmark_id'], 'request_accepted',
                        status_text='Запрос открытия выбранной закладки передан браузеру. Содержимое вкладки не проверено.')


def open_workspace(args, owner):
    from .capabilities import _open
    from .generation import check_cancelled
    workspace = WORKSPACES.get(args['workspace_id'])
    if workspace is None:
        return refused('workspaces.open', None, 'Рабочее пространство не разрешено.')
    outcomes = []
    for app_id in workspace['apps']:
        check_cancelled()
        result = _open({'app_id': app_id}, owner)
        outcomes.append(result.to_dict())
        if not result.success or result.execution_status != 'observed':
            return ActionResult(False, 'workspaces.open', args['workspace_id'], 'partial',
                                status_text='Рабочее пространство открыто частично. Проверьте журнал действий.', data={'steps': outcomes})
    return ActionResult(True, 'workspaces.open', args['workspace_id'], 'observed', 'workspace_windows',
                        status_text='Окна рабочего пространства «Учёба» обнаружены.', data={'steps': outcomes})


def prepare_mutation(args, owner):
    from .file_mutations import file_mutations
    return file_mutations.prepare(owner, args['operation'], args['scope'], args['filename'],
                                  args['content'], args['destination'] or None)
