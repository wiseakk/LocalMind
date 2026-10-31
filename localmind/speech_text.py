"""Conservative Russian speech rendering, independent of displayed Markdown.

This is pronunciation assistance, not a mathematical evaluator or a translator.
Cleanup keeps English spelling and numeric separators. The Russian Silero
adapter applies deterministic pronunciation rules because it drops Latin input.
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
    'Reign of Chaos': 'Рэйн оф Кэйос',
    'The Frozen Throne': 'Зэ Фроузен Троун',
    'Heroes of the Storm': 'Хироуз оф зэ Сторм', 'Hearthstone': 'Хартстоун',
    'Diablo Immortal': 'Диабло Иммортал', 'Diablo': 'Диабло',
    'Blizzard Entertainment': 'Близзард Энтертейнмент', 'Blizzard': 'Близзард',
    'Visual Studio Code': 'Вижуал Студио Код', 'Microsoft': 'Майкрософт',
    'Discord': 'Дискорд', 'Chrome': 'Хром', 'Firefox': 'Файрфокс',
    'Linux': 'Линукс', 'Docker': 'Докер', 'ChatGPT': 'Чат джи пи ти',
    'OpenAI': 'Оупен эй ай', 'NVIDIA': 'Энвидиа', 'Wi-Fi': 'вай фай',
    'NASA': 'НАСА', 'NATO': 'НАТО',
}
# Explicit initialisms, never inferred just from uppercase spelling.
INITIALISMS = {
    'AI': 'эй ай', 'API': 'эй пи ай', 'PDF': 'пи ди эф', 'RSA': 'эр эс эй',
    'CPU': 'си пи ю', 'GPU': 'джи пи ю', 'USB': 'ю эс би', 'SSD': 'эс эс ди',
    'HTTP': 'эйч ти ти пи', 'HTTPS': 'эйч ти ти пи эс', 'HTML': 'эйч ти эм эл',
    'DNS': 'ди эн эс', 'IP': 'ай пи', 'IPV': 'ай пи ви', 'V': 'ви',
    'LLM': 'эл эл эм', 'TTS': 'ти ти эс', 'STT': 'эс ти ти',
    'SDK': 'эс ди кей', 'CLI': 'си эл ай', 'URL': 'ю ар эл',
}
# A Latin word followed by a separate canonical numeral is a title-like cue,
# independent of franchise and case. Explicit initialisms and English I opt out.
_TITLE_NUMBER = re.compile(
    r"(?<!\w)([A-Za-z]{2,})\s+([IVXLCDM]{2,15}|[VXLCDM])(?!\w|[+#]|\.[^\s.,!?;:)])", re.I)
_CANONICAL_ROMAN = re.compile(r'M{0,3}(CM|CD|D?C{0,3})(XC|XL|L?X{0,3})(IX|IV|V?I{0,3})')


def _title_numbers(text: str) -> str:
    def render(match):
        title, roman = match[1], match[2].upper()
        if (title.upper() in INITIALISMS or (len(roman) > 1 and roman in INITIALISMS)
                or _CANONICAL_ROMAN.fullmatch(title.upper())
                or not _CANONICAL_ROMAN.fullmatch(roman)):
            return match[0]
        values = {'I': 1, 'V': 5, 'X': 10, 'L': 50, 'C': 100, 'D': 500, 'M': 1000}
        number = sum(-values[c] if i + 1 < len(roman) and values[c] < values[roman[i + 1]]
                     else values[c] for i, c in enumerate(roman))
        return title + ' ' + _cardinal(number)
    return _TITLE_NUMBER.sub(render, text)


def _ampersands(text: str) -> str:
    """Use adjacent original scripts, before any Latin pronunciation replacement."""
    def render(match):
        token = match[0]
        if token == '&':
            left = re.search(r'([A-Za-zА-Яа-яЁё]+)\s*$', text[:match.start()])
            right = re.match(r'\s*([A-Za-zА-Яа-яЁё]+)', text[match.end():])
            english = left and right and left[1].isascii() and right[1].isascii()
            return ' энд ' if english else ' и '
        if len(token) == 1 and token.isascii() and (
                re.search(r'&\s*$', text[:match.start()])
                or re.match(r'\s*&', text[match.end():])):
            return _LETTER_NAMES[token.upper()]
        return token
    return re.sub(r'[A-Za-zА-Яа-яЁё]+|&', render, text)


# Compact English sound approximation, independent of optional lexicons/services.
# Ordered clusters and positional rules beat letter spelling for unseen names;
# English stress and irregular vowels still require listening review.
_SOUNDS = dict(zip('abcdefghijklmnopqrstuvwxyz', (
    'а', 'б', 'к', 'д', 'е', 'ф', 'г', 'х', 'и', 'дж', 'к', 'л', 'м',
    'н', 'о', 'п', 'к', 'р', 'с', 'т', 'у', 'в', 'в', 'кс', 'и', 'з')))
_CLUSTERS = {
    'tion': 'шен', 'sion': 'жен', 'tch': 'ч', 'dge': 'дж', 'igh': 'ай',
    'sch': 'ш', 'sh': 'ш', 'ch': 'ч', 'th': 'т', 'ph': 'ф', 'ck': 'к',
    'qu': 'кв', 'ee': 'и', 'ea': 'и', 'oo': 'у', 'ou': 'ау', 'ow': 'оу',
    'ai': 'эй', 'ay': 'эй', 'oi': 'ой', 'oy': 'ой', 'au': 'о', 'aw': 'о',
    'er': 'ер', 'wh': 'в', 'wr': 'р', 'kn': 'н', 'ng': 'нг',
}


def transliterate_english(word: str) -> str:
    """Bounded, deterministic fallback for words, not an English translator.

    No filesystem, downloads, subprocess or optional dependency in this path.
    Possessives keep their spoken suffix; camel-case components use the same
    sound rules without matching dictionary substrings.
    """
    word = re.sub(r"['’]s$", 'z', word, flags=re.I)
    components = re.split(r'(?<=[a-z])(?=[A-Z])', word)
    rendered = []
    for component in components:
        value = component.lower()
        if value == 'i':
            rendered.append('ай')
            continue
        result, index = [], 0
        while index < len(value):
            rest = value[index:]
            cluster = next((key for key in _CLUSTERS if rest.startswith(key)), None)
            if cluster:
                result.append(_CLUSTERS[cluster])
                index += len(cluster)
                continue
            char = value[index]
            if char == 'e' and index == len(value) - 1 and len(value) > 3 and not value.endswith('le'):
                index += 1
                continue
            if char in 'cg' and value[index + 1:index + 2] in ('e', 'i', 'y'):
                result.append('с' if char == 'c' else 'дж')
            elif index + 2 == len(value) - 1 and value[-1] == 'e' and char in 'aiou' and value[index + 1] not in 'aeiouy':
                result.append({'a': 'эй', 'i': 'ай', 'o': 'оу', 'u': 'ю'}[char])
            else:
                result.append(_SOUNDS.get(char, char))
            index += 1
        rendered.append(''.join(result))
    return ' '.join(rendered)


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
        pattern = r'(?<!\w)' + r'\s+'.join(map(re.escape, term.split())) + r"(['’]s)?(?!\w|[+#])"
        text = re.sub(pattern, lambda m: spoken + ('з' if m[1] else ''), text, flags=re.I)
    return text


@dataclass(frozen=True)
class SpeechPreparation:
    original_text: str
    cleaned_text: str
    pronunciation_text: str
    tts_input: str


def speech_preparation(text: str, voice: str) -> SpeechPreparation:
    """Distinct, inspectable stages; original_text is the incoming speech chunk."""
    cleaned = clean_speech(text)
    if voice != 'silero-v5_6-ru':
        spoken = _pronounce_terms(_numbers(cleaned), TERMS)
    else:
        spoken = _numbers(_ampersands(_title_numbers(cleaned)))
        # Whole phrases precede individual words, across any normalized whitespace.
        spoken = _pronounce_terms(spoken, SILERO_NAMES)
        spoken = re.sub(r"[A-Za-z]+(?:['’][A-Za-z]+)*",
                        lambda m: INITIALISMS.get(m[0].upper())
                        or transliterate_english(m[0]), spoken)
    # No hidden worker-side rewriter: this is the exact text sent to synthesis.
    spoken = re.sub(r'\s+', ' ', spoken).strip()
    return SpeechPreparation(text, cleaned, spoken, spoken)


def prepare_speech(text: str, voice: str) -> str:
    """Adapt only the synthesis copy. One clause still uses one resident voice."""
    return speech_preparation(text, voice).tts_input


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
_TEENS = ('десять', 'одиннадцать', 'двенадцать', 'тринадцать', 'четырнадцать',
          'пятнадцать', 'шестнадцать', 'семнадцать', 'восемнадцать', 'девятнадцать')
_HUNDREDS = ('', 'сто', 'двести', 'триста', 'четыреста', 'пятьсот', 'шестьсот',
             'семьсот', 'восемьсот', 'девятьсот')
_ORDINAL_HUNDREDS = ('', 'сотый', 'двухсотый', 'трёхсотый', 'четырёхсотый',
                     'пятисотый', 'шестисотый', 'семисотый', 'восьмисотый', 'девятисотый')
_THOUSAND_STEMS = ('', '', 'двух', 'трёх', 'четырёх', 'пяти', 'шести', 'семи', 'восьми', 'девяти')


def _plural(number: int, forms: tuple[str, str, str]) -> str:
    if 11 <= number % 100 <= 14:
        return forms[2]
    if number % 10 == 1:
        return forms[0]
    return forms[1] if number % 10 in (2, 3, 4) else forms[2]


def _cardinal(number: int, feminine: bool = False) -> str:
    """Bounded callers supply at most twelve digits (through billions)."""
    if number == 0:
        return _ONES[0]
    if number < 0:
        return 'минус ' + _cardinal(-number, feminine)
    words = []
    for scale, forms in ((10**9, ('миллиард', 'миллиарда', 'миллиардов')),
                         (10**6, ('миллион', 'миллиона', 'миллионов')),
                         (1000, ('тысяча', 'тысячи', 'тысяч'))):
        count, number = divmod(number, scale)
        if count:
            if scale != 1000 or count != 1:
                words.append(_cardinal(count, scale == 1000))
            words.append(_plural(count, forms))
    hundreds, rest = divmod(number, 100)
    if hundreds:
        words.append(_HUNDREDS[hundreds])
    if 10 <= rest < 20:
        words.append(_TEENS[rest - 10])
    else:
        tens, ones = divmod(rest, 10)
        if tens:
            words.append(_TENS[tens])
        if ones:
            words.append({1: 'одна', 2: 'две'}.get(ones, _ONES[ones]) if feminine else _ONES[ones])
    return ' '.join(words)


def _ordinal(number: int, ending: str = 'й') -> str:
    """Explicit masculine ordinals/years, 0–9999; only the last component inflects."""
    if number >= 1000 and number % 1000 == 0:
        word = _THOUSAND_STEMS[number // 1000] + 'тысячный'
        prefix = ''
    else:
        remainder = number % 100
        if remainder == 0 and number:
            last = number % 1000
            word = _ORDINAL_HUNDREDS[last // 100]
        elif remainder < 20:
            last = remainder
            word = _ORDINALS[last] if last else 'нулевой'
        elif remainder % 10 == 0:
            last = remainder
            word = _ORDINAL_TENS[last // 10]
        else:
            last = remainder % 10
            word = _ORDINALS[last]
        prefix = _cardinal(number - last) + ' ' if number != last else ''
    if ending != 'й':
        if word == 'третий':
            word = 'треть' + {'ом': 'ем', 'ым': 'им', 'я': 'я', 'е': 'е', 'ю': 'ю',
                              'ого': 'его', 'ому': 'ему'}[ending]
        else:
            word = word[:-2] + {'я': 'ая', 'е': 'ое', 'ю': 'ую'}.get(ending, ending)
    return prefix + word


def _digits(token: str) -> str:
    return ' '.join(_ONES[int(c)] for c in token)


def _integer(token: str, feminine: bool = False) -> str:
    # Bound before int(), including leading zeros and attacker-sized tokens.
    if len(token) > 12 or (len(token) > 1 and token.startswith('0')):
        return _digits(token)
    return _cardinal(int(token), feminine)


# Order matters: technical identifiers/dates, explicit year/ordinal context,
# decimals, then ordinary integers. A consumed technical token cannot be a year.
_NUMBER = re.compile(
    r'(?P<technical>(?<!\w)(?:IPv\s*[0-9]+|v\s*[0-9]+(?:[.,][0-9]+)*))'
    r'|(?P<date>(?<!\w)[0-9]{4}-[0-9]{2}-[0-9]{2}(?!\w)|(?<!\w)[0-9]{1,2}[./][0-9]{1,2}[./][0-9]{4}(?!\w|\.[0-9]))'
    r'|(?P<dotted>[0-9]+(?:\.[0-9]+){2,})'
    r'|(?P<version>(?<!\w)(?:version|верси[яи])(?:\s+ПО)?\s+[0-9]+(?:[.,][0-9]+)*)'
    r'|(?P<year>(?<![\w.+,−-])[1-9][0-9]{0,3}\s+(?:году|годом|года|год)\b)'
    r'|(?P<ordinal>(?<![\w.,−-])[0-9]{1,4}-(?:ого|ому|ым|ом|й|я|е|ю)\b)'
    r'|(?P<decimal>(?<!\w)[-−]?[0-9]+[.,][0-9]+)'
    r'|(?P<integer>[-−]?[0-9]+)', re.I)


def _numbers(text: str) -> str:
    # Symbols are rendered after title recognition so IV+2 cannot become IV.
    text = re.sub(r'\^\s*2\b', ' в квадрате ', text)
    text = re.sub(r'\^\s*3\b', ' в кубе ', text)
    text = re.sub(r'\^', ' в степени ', text)
    text = re.sub(r'(?<=\w)\s*=\s*(?=\w)', ' равно ', text)
    text = re.sub(r'(?<=\w)\s*\+\s*(?=\w)', ' плюс ', text)
    text = re.sub(r'(?<=\w)\s*[×*]\s*(?=\w)', ' умножить на ', text)
    text = re.sub(r'(?<=\d)%', ' процентов ', text)

    def render(match):
        token, kind = match[0], match.lastgroup
        if kind in ('technical', 'version', 'dotted'):
            # Preserve established version/IP digit speech, including IPv4 v2.1.
            token = re.sub(r'(?i)^(IPv|v)(?=[0-9])', r'\1 ', token)
            return re.sub(r'[0-9]+', lambda m: _digits(m[0]), token.replace('.', ' запятая ').replace(',', ' запятая '))
        if kind == 'date':
            separator = ' дефис ' if '-' in token else ' дробь ' if '/' in token else ' точка '
            return separator.join(_integer(part) for part in re.split(r'[-./]', token))
        if kind == 'year':
            value, noun = token.split()
            ending = {'году': 'ом', 'годом': 'ым', 'года': 'ого', 'год': 'й'}[noun.lower()]
            return _ordinal(int(value), ending) + ' ' + noun
        if kind == 'ordinal':
            value, ending = token.split('-')
            return _ordinal(int(value), ending.lower())
        if kind == 'decimal':
            negative = token.startswith(('-', '−'))
            whole, fraction = re.split(r'[.,]', token.lstrip('-−'))
            if len(whole) > 12 or len(fraction) > 6:
                return ('минус ' if negative else '') + _integer(whole) + ' запятая ' + _digits(fraction)
            count = int(fraction)
            units = ('десятая', 'сотая', 'тысячная', 'десятитысячная', 'стотысячная', 'миллионная')
            singular = count % 10 == 1 and count % 100 != 11
            unit = units[len(fraction) - 1]
            return (('минус ' if negative else '') + _integer(whole, True) + ' '
                    + _plural(int(whole), ('целая', 'целых', 'целых')) + ' '
                    + _cardinal(count, True) + ' ' + (unit if singular else unit[:-2] + 'ых'))
        return ('минус ' if token.startswith(('-', '−')) else '') + _integer(token.lstrip('-−'))
    text = _NUMBER.sub(render, text)
    text = re.sub(r'(?<=\w)\s*/\s*(?=\w)', ' разделить на ', text)
    return re.sub(r'\s+', ' ', text).strip()


def _year(number: int) -> str:
    """Accusative masculine year, for the explicit phrase «за … год»."""
    return _ordinal(number)


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
    text = re.sub(r'(?<=\w)\s*[×*]\s*(?=\w)', ' умножить на ', text)
    text = re.sub(r'[`*_{}|~]', ' ', text)
    text = ''.join(c for c in text if c in '\n\t' or c.isprintable())
    return re.sub(r'\s+', ' ', text).strip()


def normalize_speech(text: str) -> str:
    """Compatibility renderer for Russian filename and legacy speech callers."""
    return _pronounce_terms(_numbers(clean_speech(text)), TERMS)
