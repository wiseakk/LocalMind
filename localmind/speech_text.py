"""Conservative Russian speech rendering, independent of displayed Markdown.

This is pronunciation assistance, not a mathematical evaluator or a translator.
Unknown English words are kept; known technical names use reviewed Russian forms.
"""
import re

TERMS = {
    'World of Warcraft': 'Ворлд оф Варкрафт', 'C++': 'си плюс плюс',
    'C#': 'си шарп', 'Python': 'Пайтон', 'RSA': 'эр эс эй',
    'Obsidian': 'Обсидиан', 'Steam': 'Стим', 'JavaScript': 'Джаваскрипт',
    'GitHub': 'Гитхаб', 'Ollama': 'Оллама', 'LocalMind': 'Локалмайнд',
    'CPU': 'си пи ю', 'GPU': 'джи пи ю', 'VRAM': 'видеопамять', 'PDF': 'пи ди эф',
    'Downloads': 'Даунлоудс', 'Warcraft': 'Варкрафт', 'Windows': 'Виндоус',
}
_ONES = ('ноль', 'один', 'два', 'три', 'четыре', 'пять', 'шесть', 'семь', 'восемь', 'девять')


def pronounce_filename(filename: str, language: str = 'ru') -> str:
    """Pronounce display data only; never rename or reconstruct a disk path."""
    text = re.sub(r'[_\-]+', ' ', filename)
    text = re.sub(r'(?<=[a-z])(?=[A-Z])', ' ', text)
    text = re.sub(r'\.(pdf|txt|docx|md|csv|json|tsv)$', r' · \1', text, flags=re.I)
    if language == 'en':
        for term in ('PDF', 'RSA'):
            text = re.sub(r'(?<!\w)' + term + r'(?!\w)', ' '.join(term), text, flags=re.I)
        return re.sub(r'\s+', ' ', text).strip()
    return normalize_speech(text)


def normalize_speech(text: str) -> str:
    text = re.sub(r'```[\s\S]*?(?:```|$)', ' фрагмент кода. ', text)
    text = re.sub(r'!\[([^\]]*)\]\([^)]*\)', r'\1', text)
    text = re.sub(r'\[([^\]]+)\]\([^)]*\)', r'\1', text)
    text = re.sub(r'(?:https?://|www\.)\S+', ' ссылка ', text, flags=re.I)
    text = re.sub(r'<[^>]*>', ' ', text)
    # Strip layout syntax; never execute LaTeX or model-generated expressions.
    text = re.sub(r'(?m)^\s*(?:#{1,6}\s*|>\s*|[-*+]\s+)', '', text)
    text = re.sub(r'\\(?:\[|\]|\(|\))|\$\$?', ' ', text)
    text = re.sub(r'\\(?:frac|sqrt)\b', lambda m: ' дробь ' if 'frac' in m[0] else ' корень ', text)
    text = re.sub(r'\\(?:times|cdot)\b', ' умножить на ', text)
    text = re.sub(r'\\[a-zA-Z]+', ' ', text)
    # File names often put technical words next to underscores.
    text = text.replace('_', ' ')
    for term, spoken in sorted(TERMS.items(), key=lambda pair: len(pair[0]), reverse=True):
        text = re.sub(r'(?<!\w)' + re.escape(term) + r'(?!\w)', spoken, text, flags=re.I)
    text = re.sub(r'(?<=\d)[.,](?=\d)', ' запятая ', text)
    text = re.sub(r'\^\s*2\b', ' в квадрате ', text)
    text = re.sub(r'\^\s*3\b', ' в кубе ', text)
    text = re.sub(r'\^', ' в степени ', text)
    text = re.sub(r'(?<=\w)\s*=\s*(?=\w)', ' равно ', text)
    text = re.sub(r'(?<=\w)\s*\+\s*(?=\w)', ' плюс ', text)
    text = re.sub(r'(?<=\w)\s*[×*]\s*(?=\w)', ' умножить на ', text)
    text = re.sub(r'(?<=\w)\s*/\s*(?=\w)', ' разделить на ', text)
    text = re.sub(r'(?<=\d)%', ' процентов ', text)
    # Read digits individually: avoids wrong case, oversized integer conversion,
    # dates interpreted as arithmetic, and ambiguous decimal magnitude.
    text = re.sub(r'\d+', lambda m: ' '.join(_ONES[int(d)] for d in m[0] if d in '0123456789'), text, flags=re.ASCII)
    text = re.sub(r'[`*_{}|~]', ' ', text)
    text = ''.join(c for c in text if c in '\n\t' or c.isprintable())
    return re.sub(r'\s+', ' ', text).strip()
