"""Trusted adapter outcomes. Acceptance and observation are separate facts."""
from dataclasses import asdict, dataclass
import re


@dataclass(frozen=True)
class ActionResult:
    success: bool
    action: str
    resolved_target: str | None
    execution_status: str
    observed_state: str | None = None
    error: str | None = None
    mode: str = 'REAL'
    duration_ms: int = 0
    status_text: str = ''
    data: dict | None = None

    def to_dict(self) -> dict:
        return asdict(self)

    def __str__(self) -> str:
        return self.status_text

    def __contains__(self, value: str) -> bool:
        """Keep the former adapters' simple status containment API usable."""
        return value in self.status_text


def refused(action: str, target: str | None, reason: str, *, status='denied') -> ActionResult:
    return ActionResult(False, action, target, status, error=reason, status_text=reason)


def output_channels(answer, action_results, speech_text=None):
    """Add channels without altering legacy answer/action_results wire fields.

    The public results already exclude extracted text and image bytes. Never
    construct speech by serializing structured metadata.
    """
    return {'display_text': answer, 'speech_text': answer if speech_text is None else speech_text,
            'structured_result': {'actions': action_results}}


def file_output(result):
    """Return concise display/speech for verified file metadata, or None."""
    if not result.success or not result.data or not result.action.startswith('files.'):
        return None
    if result.action == 'files.list_directory':
        return _directory_output(result.data)
    name = result.data.get('filename')
    if not isinstance(name, str):
        return None
    from .speech_text import filename_description
    if result.action in ('files.search', 'files.find_latest_pdf_in_downloads'):
        timing = (' Сравнение по времени изменения; время скачивания неизвестно.'
                  if result.data.get('sort_by') == 'modified' or result.action == 'files.find_latest_pdf_in_downloads' else '')
        return ('Выбран файл: ' + name + '.' + timing + ' Подробности и другие совпадения — ниже.',
                'Найден ' + filename_description(name) + '.')
    if result.action == 'files.describe_selected_file':
        return name, filename_description(name)
    if result.action == 'files.open_selected_file':
        # Keep the adapter's distinction between accepted and observed opening.
        prefix = 'Окно документа обнаружено: ' if result.observed_state == 'visible_window' else 'Запрос открытия передан Windows: '
        return str(result), prefix + filename_description(name) + '.'
    return None


def _literal_name(name):
    # Names are filesystem data. Keep Markdown syntax and control characters inert.
    name = ''.join(c if c.isprintable() else f'\\u{ord(c):04x}' for c in name)
    fence = '`' * (1 + max((len(run) for run in re.findall(r'`+', name)), default=0))
    return f'{fence} {name} {fence}'


def _directory_output(data):
    folder = 'В папке ' + _literal_name(data['directory_name'])
    entries = data['entries']
    if data['empty']:
        return folder + ' пусто.', 'В папке пусто.'
    if not entries:
        message = ('Доступных элементов не найдено.' if data['scan_complete']
                   else 'Просмотр ограничен. Среди проверенных элементов доступных не найдено.')
        return folder + '. ' + message, message
    counts = (f"Файлов — {data['files_count']}, подпапок — {data['directories_count']}."
              if data['scan_complete'] else 'Просмотр ограничен. Полный размер списка неизвестен.')
    lines = []
    for row in entries:
        kind = 'папка' if row['kind'] == 'directory' else f"{row['size_bytes']} Б"
        date = row['modified_utc'][:16].replace('T', ' ') + ' UTC'
        lines.append(f"- {_literal_name(row['name'])} — {kind}, {date}")
    truncation = f' Показаны первые {len(entries)} доступных элементов из проверенных.' if data['truncated'] else ''
    return folder + '. ' + counts + truncation + '\n\n' + '\n'.join(lines), counts + truncation
