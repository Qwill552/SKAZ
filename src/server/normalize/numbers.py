"""Числа → слова. `num2words(lang='ru')` даёт склонение и падежи, но не
решает, где нужен порядковый номер вместо количественного — это делает
набор регулярок ниже, в порядке от самого конкретного шаблона (диапазон
годов, время, номер, проценты) к голому числу: голый `\\d+` в конце
списка, иначе он перехватил бы цифры раньше специальных случаев.

Разбор предложения не делается (см. skaz/04-text-normalization.md, §2):
"году"/"года"/"веке" и суффиксы -й/-го/-м — дешёвая эвристика по соседнему
слову, ошибки на нетипичных падежах приемлемы (ТЗ явно разрешает).

Числа, склеенные с латиницей (`MP3`), сюда не попадают — их трогает
latin.py, а не этот модуль (см. отрицательный просмотр в _PASSES ниже);
иначе к моменту работы latin.py цифра внутри токена уже исчезла бы,
и словарь исключений вроде `mp3 → эм-пи-три` перестал бы совпадать.
"""
import re

from num2words import num2words

from .spans import sub

# Триггер-слово после числа → порядковое в нужном падеже (skaz/04, §2).
_ORDINAL_TRIGGER = {
    "году": {"case": "p"},
    "года": {"case": "g"},
    "годах": {"case": "p", "plural": True},
    "веке": {"case": "p"},
    "веков": {"case": "g", "plural": True},
    "веках": {"case": "p", "plural": True},
}

# Суффикс, приклеенный к числу через дефис (`5-й`, `20-го`) → падеж/род.
# Приближённо: "-м" не различает дательный/творительный/предложный на
# письме, берём самый частый (предложный, "в 5-м классе").
_ORDINAL_SUFFIX = {
    "й": {"case": "n", "gender": "m"},
    "го": {"case": "g", "gender": "m"},
    "му": {"case": "d", "gender": "m"},
    "м": {"case": "p", "gender": "m"},
    "я": {"case": "n", "gender": "f"},
    "е": {"case": "n", "gender": "n"},
    "ю": {"case": "a", "gender": "f"},
    "х": {"case": "n", "gender": "m", "plural": True},
}

_PERCENT_FORMS = ("процент", "процента", "процентов")
_DOLLAR_FORMS = ("доллар", "доллара", "долларов")


def _plural_ru(n: int, forms: tuple[str, str, str]) -> str:
    """1 процент, 2 процента, 5 процентов — стандартное русское склонение
    счётного существительного по последней цифре/двум цифрам числа."""
    n = abs(n) % 100
    if 11 <= n <= 14:
        return forms[2]
    tail = n % 10
    if tail == 1:
        return forms[0]
    if 2 <= tail <= 4:
        return forms[1]
    return forms[2]


def _cardinal(n: int) -> str:
    words = num2words(n, lang="ru")
    # num2words всегда говорит "одна тысяча ..." (грамматически не
    # ошибка — "тысяча" женского рода, "одна" с ней согласуется), но
    # так по-русски год не читают: "1867" — "тысяча восемьсот...", не
    # "одна тысяча восемьсот...". Только у порядковых (_ordinal) этого
    # нет: там 1 в разряде тысяч особый случай и не проговаривается.
    return re.sub(r"^(минус )?одна тысяча\b", r"\1тысяча", words)


def _ordinal(n: int, **kwargs) -> str:
    return num2words(n, lang="ru", to="ordinal", **kwargs)


def _decimal(int_part: str, frac_part: str) -> str:
    value = float(f"{int_part}.{frac_part}")
    if value == 1.5:
        return "полторы"  # идиома, не "одна целая пять десятых"
    return num2words(value, lang="ru")


def _sub_percent(m: re.Match) -> str:
    whole, frac = m.group(1), m.group(2)
    if frac:
        return f"{_decimal(whole, frac)} {_PERCENT_FORMS[2]}"
    n = int(whole)
    return f"{_cardinal(n)} {_plural_ru(n, _PERCENT_FORMS)}"


def _sub_dollar(m: re.Match) -> str:
    whole, frac = m.group(1), m.group(2)
    if frac:
        return f"{_decimal(whole, frac)} {_DOLLAR_FORMS[2]}"
    n = int(whole)
    return f"{_cardinal(n)} {_plural_ru(n, _DOLLAR_FORMS)}"


def _sub_numero(m: re.Match) -> str:
    return f"номер {_cardinal(int(m.group(1)))}"


def _sub_year_range(m: re.Match) -> str:
    start, end = int(m.group(1)), int(m.group(2))
    return (
        f"с {_ordinal(start, case='g', gender='m')} "
        f"по {_ordinal(end, case='n', gender='m')}"
    )


def _sub_time(m: re.Match) -> str:
    hours, minutes = int(m.group(1)), int(m.group(2))
    return f"{_cardinal(hours)} {_cardinal(minutes)}"


def _sub_ordinal_suffix(m: re.Match) -> str:
    n, suffix = int(m.group(1)), m.group(2)
    return _ordinal(n, **_ORDINAL_SUFFIX[suffix])


def _sub_trigger_word(m: re.Match) -> str:
    n, word = int(m.group(1)), m.group(2)
    return f"{_ordinal(n, **_ORDINAL_TRIGGER[word])} {word}"


def _sub_decimal(m: re.Match) -> str:
    return _decimal(m.group(1), m.group(2))


def _sub_plain(m: re.Match) -> str:
    return _cardinal(int(m.group(0)))


_PASSES = [
    (re.compile(r"(\d+)(?:[.,](\d+))?\s?%"), _sub_percent),
    (re.compile(r"\$\s?(\d+)(?:[.,](\d+))?"), _sub_dollar),
    (re.compile(r"№\s?(\d+)"), _sub_numero),
    (re.compile(r"(?<!\d)(\d{4})\s*-\s*(\d{4})(?!\d)"), _sub_year_range),
    (re.compile(r"(?<!\d)([01]?\d|2[0-3]):([0-5]\d)(?!\d)"), _sub_time),
    (re.compile(r"(\d+)-(" + "|".join(_ORDINAL_SUFFIX) + r")\b"), _sub_ordinal_suffix),
    (re.compile(r"(\d+)\s+(" + "|".join(_ORDINAL_TRIGGER) + r")\b"), _sub_trigger_word),
    (re.compile(r"(\d+),(\d+)"), _sub_decimal),
    # Голое число последним и без латиницы по краям — иначе "MP3" теряет
    # тройку раньше, чем latin.py успевает собрать её словарём исключений.
    (re.compile(r"(?<![A-Za-z])\d+(?![A-Za-z])"), _sub_plain),
]


def expand_numbers(text: str) -> str:
    for pattern, repl in _PASSES:
        text = sub(pattern, repl, text)
    return text
