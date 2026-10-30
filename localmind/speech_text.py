"""Conservative Russian speech rendering, independent of displayed Markdown.

This is pronunciation assistance, not a mathematical evaluator or a translator.
Cleanup keeps English spelling. The Russian Silero adapter pronounces reviewed
names and spells unknown Latin words because this model drops Latin input.
"""
from dataclasses import dataclass
import re

TERMS = {
    'World of Warcraft': 'Ворлд оф Варкрафт', 'C++': 'си плюс плюс',
    'C#': 'си шарп', 'Python': 'Пайтон', 'RSA': 'эр эс эй',
    'Obsidian': 'Обсидиан', 'Steam': 'Стим', 'JavaScript': 'Джаваскрипт',
    'GitHub': 'Гитхаб', 'Ollama': 'Оллама', 'LocalMind': 'Локалмайнд',
    'CPU': 'си пи ю', 'GPU': 'джи пи ю', 'VRAM': 'видеопамять', 'PDF': 'пи ди эф',
    'Downloads': 'Даунлоудс', 'Warcraft': 'Варкрафт', 'Windows': 'Виндоус',
    'Word': 'Ворд', 'Markdown': 'Маркдаун', 'CSV': 'си эс ви',
    'TSV': 'ти эс ви', 'JSON': 'джейсон',
}
# Speech-only spellings for the selected Russian speaker. These are reviewed
# vocabulary, not translation, a general transliterator, or Silero phoneme tags.
SILERO_NAMES = {
    **TERMS,
    'Arthas Menethil': 'Артас Менетил', 'Arthas': 'Артас', 'Menethil': 'Менетил',
    'Warcraft III': 'Варкрафт три', 'Reign of Chaos': 'Рэйн оф Кэйос',
    'The Frozen Throne': 'Зэ Фроузен Троун',
    'Heroes of the Storm': 'Хироуз оф зэ Сторм', 'Hearthstone': 'Хартстоун',
}


@dataclass(frozen=True)
class LanguageSpan:
    language: str
    text: str


def language_spans(text: str) -> tuple[LanguageSpan, ...]:
    """Lossless script spans, before pronunciation changes; no language guessing.

    Latin words are English candidates. Unknown words stay intact. Whitespace
    inside a phrase is kept together; punctuation and numbers remain neutral.
    """
    spans = []
    for match in re.finditer(r"[A-Za-z]+(?:['’][A-Za-z]+)*(?:\+\+|#)?|[А-Яа-яЁё]+|[^A-Za-zА-Яа-яЁё]+", text):
        word = match[0]
        language = 'en' if word[0].isascii() and word[0].isalpha() else 'ru' if re.match('[А-Яа-яЁё]', word) else 'neutral'
        if spans and spans[-1].language == language:
            spans[-1] = LanguageSpan(language, spans[-1].text + word)
        elif len(spans) >= 2 and spans[-1].text.isspace() and spans[-2].language == language:
            space = spans.pop().text
            spans[-1] = LanguageSpan(language, spans[-1].text + space + word)
        else:
            spans.append(LanguageSpan(language, word))
    return tuple(spans)


def _pronounce_terms(text, terms):
    for term, spoken in sorted(terms.items(), key=lambda pair: len(pair[0]), reverse=True):
        text = re.sub(r'(?<!\w)' + re.escape(term) + r'(?!\w|[+#])', spoken, text, flags=re.I)
    return text


def prepare_speech(text: str, voice: str) -> str:
    """Adapt only the synthesis copy. One clause still uses one resident voice."""
    cleaned = clean_speech(text)
    if voice != 'silero-v5_6-ru':
        return _pronounce_terms(cleaned, TERMS)

    def russian_span(span):
        spoken = _pronounce_terms(span.text, SILERO_NAMES)
        # This model discards Latin characters. Spell unknown names/acronyms
        # instead of silently omitting them or inventing a pronunciation.
        return re.sub(r'[A-Za-z]+', lambda m: ' '.join(_LETTER_NAMES[c] for c in m[0].upper()), spoken)
    return ''.join(russian_span(span) if span.language == 'en' else span.text
                   for span in language_spans(cleaned))


_ONES = ('ноль', 'один', 'два', 'три', 'четыре', 'пять', 'шесть', 'семь', 'восемь', 'девять')

# Reviewed vocabulary only. Do not transliterate an unknown word into a guessed
# Russian meaning. These words may occur independently in any document title.
_ROMANIZED = {
    'spisok': 'список', 'rabot': 'работ', 'rabota': 'работа',
    'pobeditelej': 'победителей', 'pobediteley': 'победителей',
    'prizjorov': 'призёров', 'prizerov': 'призёров', 'prizyorov': 'призёров',
    'i': 'и', 'za': 'за', 'god': 'год', 'goda': 'года',
    'otchet': 'отчёт', 'otchyot': 'отчёт', 'plan': 'план',
    'proekt': 'проект', 'itogi': 'итоги', 'rezultaty': 'результаты',
    'konferencija': 'конференция', 'konferentsiya': 'конференция',
    'kriterii': 'критерии', 'ocenki': 'оценки', 'trebovanija': 'требования',
    'prezentacija': 'презентация', 'videoprezentacija': 'видеопрезентация',
    'doklad': 'доклад', 'raspisanie': 'расписание', 'uchastnikov': 'участников',
}
_FILE_TYPES = {'pdf': 'PDF-файл', 'txt': 'текстовый файл', 'docx': 'документ Word',
               'md': 'документ Markdown', 'csv': 'файл таблицы CSV', 'tsv': 'файл таблицы TSV',
               'json': 'файл JSON', 'png': 'графический файл', 'jpg': 'графический файл',
               'jpeg': 'графический файл', 'wav': 'аудиофайл', 'mp3': 'аудиофайл'}
_LETTER_NAMES = dict(zip('ABCDEFGHIJKLMNOPQRSTUVWXYZ', (
    'эй', 'би', 'си', 'ди', 'и', 'эф', 'джи', 'эйч', 'ай', 'джей', 'кей',
    'эл', 'эм', 'эн', 'оу', 'пи', 'кью', 'ар', 'эс', 'ти', 'ю', 'ви',
    'дабл ю', 'икс', 'уай', 'зет')))
_ORDINALS = ('', 'первый', 'второй', 'третий', 'четвёртый', 'пятый',
             'шестой', 'седьмой', 'восьмой', 'девятый', 'десятый',
             'одиннадцатый', 'двенадцатый', 'тринадцатый', 'четырнадцатый',
             'пятнадцатый', 'шестнадцатый', 'семнадцатый', 'восемнадцатый', 'девятнадцатый')
_TENS = ('', '', 'двадцать', 'тридцать', 'сорок', 'пятьдесят', 'шестьдесят',
         'семьдесят', 'восемьдесят', 'девяносто')
_ORDINAL_TENS = ('', '', 'двадцатый', 'тридцатый', 'сороковой', 'пятидесятый',
                 'шестидесятый', 'семидесятый', 'восьмидесятый', 'девяностый')


def _year(number: int) -> str:
    """Accusative masculine year, for the explicit phrase «за … год»."""
    if number == 2000:
        return 'двухтысячный'
    if number == 1900:
        return 'тысяча девятисотый'
    century, remainder = divmod(number, 100)
    prefix = 'тысяча девятьсот' if century == 19 else 'две тысячи'
    if remainder < 20:
        ordinal = _ORDINALS[remainder]
    else:
        tens, ones = divmod(remainder, 10)
        ordinal = (_TENS[tens] + ' ' + _ORDINALS[ones]) if ones else _ORDINAL_TENS[tens]
    return prefix + ' ' + ordinal


def _filename_parts(filename):
    # Both Windows and POSIX separators, independent of the host OS. Paths and
    # arbitrarily large metadata never become speech. Never use this for I/O.
    basename = re.split(r'[/\\]', filename)[-1]
    if len(basename) > 512:
        return '', 'файл'
    stem, dot, suffix = basename.rpartition('.')
    return (stem if dot else basename), _FILE_TYPES.get(suffix.casefold(), 'файл')


def filename_description(filename: str, language: str = 'ru') -> str:
    """A short file label and title; the caller owns the surrounding sentence."""
    _, kind = _filename_parts(filename)
    title = pronounce_filename(filename, language)
    if title:
        return kind + ': «' + title + '»'
    return kind + ' с техническим именем'


def pronounce_filename(filename: str, language: str = 'ru') -> str:
    """Pronounce display data only; never rename or reconstruct a disk path."""
    text, _ = _filename_parts(filename)
    # Drop UUID/hash/download identifiers; retain independent human title words.
    text = re.sub(r'(?i)(?<!\w)[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}(?!\w)', ' ', text)
    text = re.sub(r'(?i)(?<![a-z0-9])[0-9a-f]{16,}(?![a-z0-9])', ' ', text)
    text = re.sub(r'(?<!\w)(?=[A-Za-z0-9]{24,}(?!\w))(?=[A-Za-z0-9]*[0-9])[A-Za-z0-9]+', ' ', text)
    text = re.sub(r'[_\-]+', ' ', text)
    text = re.sub(r'(?<=[A-Za-zА-Яа-яЁё])(?=\d)|(?<=\d)(?=[A-Za-zА-Яа-яЁё])', ' ', text)
    if language != 'en':
        for term, spoken in sorted(TERMS.items(), key=lambda pair: len(pair[0]), reverse=True):
            text = re.sub(r'(?<!\w)' + re.escape(term) + r'(?!\w)', spoken, text, flags=re.I)
    text = re.sub(r'(?<=[a-zа-яё])(?=[A-ZА-ЯЁ])', ' ', text)
    tokens = re.findall(r'[\w]+(?:[.,][0-9]+)*|[.,]', text, flags=re.UNICODE)
    tokens = [token for token in tokens if len(token) <= 40 and not (len(token) >= 24 and any(c.isdigit() for c in token))]
    if len(tokens) > 24 or len(text) > 180:
        return ''
    text = ' '.join(tokens)
    if language == 'en':
        for term in ('PDF', 'RSA'):
            text = re.sub(r'(?<!\w)' + term + r'(?!\w)', ' '.join(term), text, flags=re.I)
        return re.sub(r'\s+', ' ', text).strip()
    rendered = []
    for index, token in enumerate(tokens):
        # A v2026 or dotted version is not a year. Adjacent IB2026 is a year.
        if re.fullmatch(r'(?:19\d{2}|20\d{2})', token) and (index == 0 or tokens[index - 1].casefold() not in ('v', 'version')) and (index + 1 == len(tokens) or tokens[index + 1] != '.'):
            phrase = 'за ' + _year(int(token)) + ' год'
            if rendered and rendered[-1] == 'за':
                rendered.pop()
            if rendered:
                rendered[-1] = rendered[-1].rstrip(',') + ','
            rendered.append(phrase)
        elif token.casefold() in ('god', 'год') and index and re.fullmatch(r'(?:19\d{2}|20\d{2})', tokens[index - 1]) and rendered and rendered[-1].endswith(' год'):
            continue
        elif token == 'IB':
            # Letter transliteration only; no claim about what this stands for.
            if rendered:
                rendered[-1] = rendered[-1].rstrip(',') + ','
            rendered.append('ИБ')
        elif token.isascii() and token.isalpha() and token.isupper() and 2 <= len(token) <= 6 and token not in TERMS:
            rendered.append(' '.join(_LETTER_NAMES[c] for c in token))
        else:
            rendered.append(_ROMANIZED.get(token.casefold(), token))
    text = normalize_speech(' '.join(rendered))
    if text and text[0].islower():
        text = text[0].upper() + text[1:]
    return text


def clean_speech(text: str) -> str:
    """Remove display syntax without replacing English names or choosing a voice."""
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


def normalize_speech(text: str) -> str:
    """Compatibility renderer for Russian filename and legacy speech callers."""
    return _pronounce_terms(clean_speech(text), TERMS)
