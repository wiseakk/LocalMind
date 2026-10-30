"""Trusted adapter outcomes. Acceptance and observation are separate facts."""
from dataclasses import asdict, dataclass


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
    name = result.data.get('filename')
    if not isinstance(name, str):
        return None
    from .speech_text import filename_description
    if result.action in ('files.search', 'files.find_latest_pdf_in_downloads'):
        return ('Выбран файл: ' + name + '. Подробности и другие совпадения — ниже.',
                'Найден ' + filename_description(name) + '.')
    if result.action == 'files.describe_selected_file':
        return name, filename_description(name)
    if result.action == 'files.open_selected_file':
        # Keep the adapter's distinction between accepted and observed opening.
        prefix = 'Окно документа обнаружено: ' if result.observed_state == 'visible_window' else 'Запрос открытия передан Windows: '
        return str(result), prefix + filename_description(name) + '.'
    return None
