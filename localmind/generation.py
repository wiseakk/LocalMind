"""Immutable per-request local inference controls (never a remote model URL)."""
from contextvars import ContextVar
from dataclasses import asdict, dataclass
import re
import time

@dataclass(frozen=True)
class GenerationSettings:
    model: str
    reasoning: str = 'off'
    context_tokens: int = 4096
    response_tokens: int = 768
    keep_alive_seconds: int = 300

    def __post_init__(self):
        if not isinstance(self.model, str) or not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9._:/-]{0,239}', self.model) or 'cloud' in self.model.casefold():
            raise ValueError('Выберите установленную локальную модель.')
        if self.reasoning not in ('off', 'on', 'auto'):
            raise ValueError('Неизвестный режим рассуждения.')
        if not 1024 <= self.context_tokens <= 8192 or not 64 <= self.response_tokens <= 2048 or not 0 <= self.keep_alive_seconds <= 900:
            raise ValueError('Параметры генерации вне допустимых границ.')

    def to_dict(self):
        return asdict(self)


effective_generation: ContextVar[GenerationSettings | None] = ContextVar('generation', default=None)
text_delta = ContextVar('text_delta', default=None)
cancellation = ContextVar('cancellation', default=None)
turn_deadline = ContextVar('turn_deadline', default=None)


def check_cancelled():
    event = cancellation.get()
    if event is not None and event.is_set():
        raise ValueError('Generation cancelled')
    deadline = turn_deadline.get()
    if deadline is not None and time.monotonic() >= deadline:
        raise ValueError('Turn deadline exceeded')


def defaults():
    from .model_manager import manager
    return GenerationSettings(manager.active)


def json_answer_prefix(content: str) -> str:
    """Decode only complete JSON string characters, withholding partial escapes.

    The schema has one field. Never expose JSON, reasoning fields or tool calls.
    Whole strings and incomplete strings share the same strict decoder.
    """
    match = re.match(r'^\s*\{\s*"answer"\s*:\s*"', content)
    if not match:
        return ''
    result = []
    pos = match.end()
    escapes = {'n': '\n', 'r': '\r', 't': '\t', 'b': '\b', 'f': '\f', '"': '"', '\\': '\\', '/': '/'}
    while pos < len(content):
        char = content[pos]
        if char == '"':
            break
        if char == '\\':
            if pos + 1 >= len(content):
                break
            code = content[pos + 1]
            if code == 'u':
                digits = content[pos + 2:pos + 6]
                if len(digits) < 4:
                    break
                if not re.fullmatch('[0-9a-fA-F]{4}', digits):
                    raise ValueError('Invalid JSON escape')
                point = int(digits, 16)
                if 0xD800 <= point <= 0xDBFF:
                    pair = content[pos + 6:pos + 12]
                    if len(pair) < 6:
                        break
                    if not re.fullmatch(r'\\u[dD][c-fC-F][0-9a-fA-F]{2}', pair):
                        raise ValueError('Invalid surrogate')
                    point = 0x10000 + ((point - 0xD800) << 10) + int(pair[2:], 16) - 0xDC00
                    pos += 6
                elif 0xDC00 <= point <= 0xDFFF:
                    raise ValueError('Invalid surrogate')
                result.append(chr(point))
                pos += 6
                continue
            if code not in escapes:
                raise ValueError('Invalid JSON escape')
            result.append(escapes[code])
            pos += 2
            continue
        if ord(char) < 32:
            raise ValueError('Invalid JSON character')
        if 0xD800 <= ord(char) <= 0xDFFF:
            raise ValueError('Invalid raw surrogate')
        result.append(char)
        pos += 1
    return ''.join(result)
