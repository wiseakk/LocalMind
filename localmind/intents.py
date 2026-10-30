"""Small Russian request grammar; proposals never grant execution permission.

The grammar consumes every token, including punctuation. Catalog identity and
permission checks remain the executor's responsibility. No model output, fuzzy
name matching or path interpretation participates in this parser.
"""
from dataclasses import dataclass
import re
from collections.abc import Mapping, Sequence


@dataclass(frozen=True)
class AppIntent:
    action: str
    target: str


_TOKEN = re.compile(r'\w+(?:[-+]\w+)*\+*|[^\w\s]', re.UNICODE)
_VERBS = {
    'open_app': {
        'imperative': {'открой', 'откройте', 'открывай', 'открывайте',
                       'запусти', 'запустите', 'запускай', 'запускайте'},
        'infinitive': {'открыть', 'запустить'},
        'past': {'открыл', 'открыла', 'открыли', 'запустил', 'запустила', 'запустили'},
    },
    'close_app': {
        'imperative': {'закрой', 'закройте', 'закрывай', 'закрывайте',
                       'заверши', 'завершите'},
        'infinitive': {'закрыть', 'завершить'},
        'past': {'закрыл', 'закрыла', 'закрыли', 'завершил', 'завершила', 'завершили'},
    },
}
_NEGATION = {'не', 'нет', 'никогда', 'нельзя', 'запрещаю', 'запрещено'}
_QUOTES = set('«»“”„"‘’\'`‹›')


def action_clause(text: str) -> str:
    """Normalize discourse, without removing action negation or arbitrary text.

    Only standalone complaint clauses and trailing explanations are discourse.
    A second imperative remains intact for the bounded plan resolver. In
    particular `не открывай` is never rewritten into an affirmative command.
    """
    text = ' '.join(text.strip().split())
    text = re.sub(r'^(?:ну[, ]+)?(?:нихуя\s+ты\s+не\s+сделал|ты\s+ничего\s+не\s+сделал)[,!. ]+', '', text, flags=re.I)
    text = re.sub(r'^(?:ну[, ]+|блин[, ]+|ебать[, ]+|по-братски[, ]+)', '', text, flags=re.I)
    text = re.sub(r'(?<=\s)по-братски[, ]+', '', text, flags=re.I)
    # An explanation has no command authority. Do not discard another action.
    parts = re.split(r',\s*(?:он|она|оно)\s+(?:у\s+меня\s+)?', text, maxsplit=1, flags=re.I)
    if len(parts) == 2 and re.fullmatch(r'(?:(?:почему-то|никак|всё|все|ещё|еще)\s+)*(?:не\s+)?(?:открывается|запускается|работает)[.!?]*', parts[1], re.I):
        text = parts[0]
    return text


def command_negated(text: str) -> bool:
    """Negation governs the requested verb, not unrelated words in the turn."""
    clause = action_clause(text)
    return bool(re.search(r'\b(?:не|никогда\s+не|нельзя|запрещаю)\s+(?:(?:ты|мне|пожалуйста)\s+)*(?:откр\w*|запус\w*|закр\w*|включ\w*|выключ\w*|вывед\w*|най\w*|удал\w*|созд\w*)\b', clause, re.I)
                or re.search(r'\bбез\s+(?:запуска|открытия|закрытия|включения|выключения)\b', clause, re.I))


def _tokens(text: str) -> list[str]:
    return _TOKEN.findall(text.casefold().replace('ё', 'е'))


def _polite_start(tokens: list[str]) -> list[str]:
    """Consume one polite clause only at a grammatical boundary."""
    if tokens[:1] == [','] and tokens[1:2] == ['пожалуйста']:
        tokens = tokens[1:]
    if tokens[:1] == ['пожалуйста']:
        tokens = tokens[1:]
        if tokens[:1] == [',']:
            tokens = tokens[1:]
    return tokens


def _target_tokens(tokens: list[str]) -> list[str]:
    tokens = _polite_start(tokens)
    if tokens[:1] == ['мне']:
        tokens = _polite_start(tokens[1:])
    if tokens[:2] == ['на', 'компьютере']:
        tokens = _polite_start(tokens[2:])
    # Trailing politeness belongs outside the exact catalog name.
    if tokens[-1:] == ['пожалуйста']:
        tokens = tokens[:-1]
        if tokens[-1:] == [',']:
            tokens = tokens[:-1]
    return tokens


def _request_body(tokens: list[str], verbs: dict[str, set[str]]) -> list[str] | None:
    tokens = _polite_start(tokens)
    if not tokens:
        return None
    mode = 'imperative'
    if tokens[:1] == ['а']:
        tokens = tokens[1:]
    if tokens[:1] == ['ты'] or tokens[:1] == ['вы']:
        # A leading pronoun is accepted only with an explicit modal request.
        if len(tokens) < 2 or tokens[1] not in {'можешь', 'можете'}:
            return None
        tokens = tokens[1:]
    if tokens[:1] in (['можешь'], ['можете']):
        mode = 'infinitive'
        tokens = tokens[1:]
        if tokens[:1] in (['ты'], ['вы']):
            tokens = tokens[1:]
    elif tokens[:2] == ['я', 'хочу']:
        mode = 'past'
        tokens = tokens[2:]
        if tokens[:1] == [',']:
            tokens = tokens[1:]
        if tokens[:2] != ['чтобы', 'ты']:
            return None
        tokens = tokens[2:]
    elif tokens[:1] == ['прошу']:
        mode = 'infinitive'
        tokens = tokens[1:]
        if tokens[:1] in (['тебя'], ['вас']):
            tokens = tokens[1:]
    elif tokens[:2] in (['будь', 'добр'], ['будь', 'добра'], ['будьте', 'добры']):
        tokens = tokens[2:]
        if tokens[:1] == [',']:
            tokens = tokens[1:]
    tokens = _polite_start(tokens)
    if not tokens or tokens[0] not in verbs[mode]:
        return None
    return _target_tokens(tokens[1:])


def parse_app_intent(text: str, aliases: Mapping[str, Sequence[str]]) -> AppIntent | None:
    """Recognize one explicit request for one exact, unambiguous catalog alias.

    A question mark does not turn "Можешь открыть Steam?" into an information
    query. Conversely "Можно ли открыть Steam?" has no authorized grammar.
    Quotation and negation are inspected before any punctuation normalization.
    The result is a proposal: the caller must still check authorization and
    revalidate the executable and its catalog permission before launching.
    """
    if not isinstance(text, str) or not text.strip() or len(text) > 2000:
        return None
    if any(mark in text for mark in _QUOTES):
        return None
    tokens = _tokens(action_clause(text))
    if _NEGATION.intersection(tokens):
        return None
    # Preserve interior punctuation. Only sentence-final punctuation is removed.
    endings = 0
    while tokens and tokens[-1] in {'.', '!', '?'}:
        endings += 1
        tokens.pop()
    if endings > 3:
        return None
    proposals = []
    for action, verbs in _VERBS.items():
        target = _request_body(tokens, verbs)
        if action == 'open_app' and tokens[:1] in (['включи'], ['включите']):
            target = _target_tokens(tokens[1:])
        if not target:
            continue
        # Catalog names are untrusted metadata. A display alias containing a
        # conjunction/second command cannot turn a compound request into one
        # authorized action; the UI's stable catalog ID remains selectable.
        action_tokens = {word for forms in _VERBS.values() for words in forms.values() for word in words}
        if set(target).intersection(action_tokens | {'и', 'или', 'либо', 'затем', 'потом', 'включи', 'выключи', 'удали', ';', '&', '|'}):
            continue
        matches = [app_id for app_id, names in aliases.items()
                   if any(target == _tokens(name) for name in names)]
        if len(matches) == 1:
            proposals.append(AppIntent(action, matches[0]))
    return proposals[0] if len(proposals) == 1 else None
