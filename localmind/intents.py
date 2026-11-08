"""Recognize a reviewed request and rank observed catalog names independently."""
from dataclasses import dataclass
import re
import unicodedata
from collections.abc import Mapping, Sequence


@dataclass(frozen=True)
class AppIntent:
    action: str
    target: str


@dataclass(frozen=True)
class AppResolution:
    action: str
    candidates: tuple[str, ...]
    stage: str


_TOKEN = re.compile(r'\w+(?:[-+]\w+)*\+*|[^\w\s]', re.UNICODE)
_VERBS = {
    'open_app': {
        'imperative': {'открой', 'откройте', 'открывай', 'открывайте',
                       'запусти', 'запустите', 'запускай', 'запускайте', 'включи', 'включите', 'вруби', 'врубите'},
        'infinitive': {'открыть', 'открывать', 'запустить', 'запускать', 'включить', 'врубить'},
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
_ACTION_WORDS = {word for forms in _VERBS.values() for words in forms.values() for word in words}
_UNSAFE_TARGET = _ACTION_WORDS | {'и', 'или', 'либо', 'затем', 'потом', 'если', 'когда', 'как',
                                 'выключи', 'удали', 'создай', 'скажи', 'покажи', 'показать'}
_TRANSLITERATE = str.maketrans(dict(zip('абвгдежзийклмнопрстуфхцчшщъыьэюя',
    ('a', 'b', 'v', 'g', 'd', 'e', 'zh', 'z', 'i', 'y', 'k', 'l', 'm', 'n', 'o', 'p', 'r',
     's', 't', 'u', 'f', 'kh', 'ts', 'ch', 'sh', 'shch', '', 'y', '', 'e', 'yu', 'ya'))))


def action_clause(text: str) -> str:
    """Normalize discourse, without removing action negation or arbitrary text.

    Only standalone complaint clauses and trailing explanations are discourse.
    A second imperative remains intact for the bounded plan resolver. In
    particular `не открывай` is never rewritten into an affirmative command.
    """
    text = ' '.join(text.strip().split())
    text = re.sub(r'^(?:здорова|привет)[,! ]+', '', text, flags=re.I)
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
    return _TOKEN.findall(unicodedata.normalize('NFKC', text).casefold().replace('ё', 'е'))


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


def _request_body(tokens: list[str], verbs: dict[str, set[str]], *, app=False, bare_infinitive=False) -> list[str] | None:
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
    forms = verbs[mode]
    if app:
        if mode == 'imperative' and bare_infinitive:
            forms = forms | verbs['infinitive']
        if mode == 'infinitive':
            tokens = _target_tokens(tokens)
            if len(tokens) > 1 and tokens[-1] in forms:
                return _target_tokens(tokens[:-1])
        show = {'показать'} if mode == 'infinitive' else {'покажи', 'покажите'} if mode == 'imperative' else set()
        if len(tokens) > 2 and tokens[0] in show and tokens[1] == 'приложение':
            return _target_tokens(tokens[2:])
    return _target_tokens(tokens[1:]) if tokens and tokens[0] in forms else None


def app_request(text: str) -> tuple[str, tuple[str, ...]] | None:
    """Consume one affirmative app clause. The result alone has no authority."""
    if not isinstance(text, str) or not text.strip() or len(text) > 2000:
        return None
    if any(mark in text for mark in _QUOTES) or '\n' in text or '\r' in text:
        return None
    tokens = _tokens(action_clause(text))
    if _NEGATION.intersection(tokens):
        return None
    # Preserve interior punctuation. Only sentence-final punctuation is removed.
    endings = []
    while tokens and tokens[-1] in {'.', '!', '?'}:
        endings.append(tokens.pop())
    if len(endings) > 3:
        return None
    for action, verbs in _VERBS.items():
        target = _request_body(tokens, verbs, app=action == 'open_app', bare_infinitive='?' not in endings)
        if target and not _UNSAFE_TARGET.intersection(target) and all(re.fullmatch(r'[\w+-]+', token) for token in target):
            return action, tuple(target)
    return None


def _name_key(words):
    # Compare complete catalog labels. Any collision remains ambiguous, and
    # derived names are never used as permission identifiers.
    stems = [re.sub(r'(?<=[а-я])[аяуюеыи]$', '', word) if len(word) >= 5 else word for word in words]
    if len(stems) == 3 and stems[1] == 'в':
        stems = [stems[2], stems[0]]
    if len(stems) > 1 and stems[-1] in ('app', 'приложени'):
        stems.pop()
    key = tuple(word.translate(_TRANSLITERATE) for word in stems)
    if key in (('yandeks', 'muzyk'), ('yandex', 'muzyk'), ('yandex', 'music')):
        return ('yandex', 'music')
    return key


def _one_edit(a, b):
    """One substitution, insertion, deletion or adjacent transposition."""
    if min(len(a), len(b)) < 5 or abs(len(a)-len(b)) > 1 or a == b:
        return False
    i = next((index for index, (x, y) in enumerate(zip(a, b)) if x != y), min(len(a), len(b)))
    if len(a) == len(b):
        return a[i+1:] == b[i+1:] or (a[i:i+2] == b[i:i+2][::-1] and a[i+2:] == b[i+2:])
    shorter, longer = sorted((a, b), key=len)
    return shorter[i:] == longer[i+1:]


def _near_label(key, requested):
    if len(key) != len(requested):
        return False
    differences = [(x, y) for x, y in zip(key, requested) if x != y]
    return len(differences) == 1 and _one_edit(*differences[0])


def resolve_app_request(request, aliases: Mapping[str, Sequence[str]]) -> AppResolution | None:
    if request is None:
        return None
    action, words = request
    normalized = _name_key(words)
    matches = {'exact': [], 'normalized': [], 'semantic': []}
    for app_id, names in aliases.items():
        keys = [tuple(_tokens(name)) for name in names]
        if words in keys:
            matches['exact'].append(app_id)
        elif action == 'open_app':
            canonical = [_name_key(key) for key in keys]
            if normalized in canonical:
                matches['normalized'].append(app_id)
            elif not words[0].startswith('app-') and any(_near_label(key, normalized) for key in canonical):
                matches['semantic'].append(app_id)
    for stage, candidates in matches.items():
        if candidates:
            return AppResolution(action, tuple(candidates), stage if len(candidates) == 1 else 'ambiguous')
    return None


def parse_app_intent(text: str, aliases: Mapping[str, Sequence[str]]) -> AppIntent | None:
    resolved = resolve_app_request(app_request(text), aliases)
    if resolved and resolved.stage in ('exact', 'normalized'):
        return AppIntent(resolved.action, resolved.candidates[0])
    return None


def focus_request_target(text: str) -> str | None:
    """Consume an entire one-time foreground request, including modal forms."""
    if not isinstance(text, str) or len(text) > 2000 or any(mark in text for mark in _QUOTES):
        return None
    tokens = _tokens(action_clause(text))
    if _NEGATION.intersection(tokens):
        return None
    for _ in range(3):
        if tokens and tokens[-1] in {'.', '!', '?'}:
            tokens.pop()
    body = _request_body(tokens, {
        'imperative': {'выведи', 'покажи', 'подними'},
        'infinitive': {'вывести', 'показать', 'поднять'},
        'past': {'вывел', 'вывела', 'показал', 'показала', 'поднял', 'подняла'},
    })
    if not body:
        return None
    for ending in (['на', 'передний', 'план'], ['поверх', 'всех', 'окон'], ['поверх', 'окон']):
        if body[-len(ending):] == ending and len(body) > len(ending):
            target = body[:-len(ending)]
            if any(t in {'и', 'или', 'затем', 'потом', ';', ',', '!', '?', '&', '|'} for t in target):
                return None
            return ' '.join(target)
    return None
