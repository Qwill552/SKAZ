"""Раскрытие сокращений. Идёт до чисел (см. `__init__.py`, порядок шагов),
потому что "г." решает "год" или "город" по контексту, пока рядом ещё
цифры, а не готовое слово, — раскрытые числа сами по себе не несут
признака "рядом было число".

Сокращение раскрывается вместе с точкой — иначе точка остаётся и режет
чанк в TTS-6 (см. skaz/04-text-normalization.md, §3)."""
import re

from .spans import sub

# Обязательный минимум из ТЗ плюс расширение на частые сокращения. "г.",
# "гг." и "вв." — особый случай (год/город, множественное число),
# обрабатываются отдельно в _expand_g/через UNITS ниже.
SIMPLE = {
    "т.д.": "так далее",
    "т.п.": "тому подобное",
    "т.е.": "то есть",
    "т.к.": "так как",
    "т.н.": "так называемый",
    "др.": "другие",
    "пр.": "прочее",
    "в.": "век",
    "вв.": "века",
    "гг.": "годы",
    "см.": "смотри",
    "стр.": "страница",
    "рис.": "рисунок",
    "ок.": "около",
    "напр.": "например",
    "н.э.": "нашей эры",
    "г-н": "господин",
    "г-жа": "госпожа",
    "проф.": "профессор",
    "доц.": "доцент",
    "акад.": "академик",
    "им.": "имени",
    "изд.": "издание",
    "экз.": "экземпляр",
    "гл.": "глава",
    "разд.": "раздел",
    "п.": "пункт",
    "подп.": "подпункт",
    "ст.": "статья",
    "прим.": "примечание",
    "ред.": "редакция",
    "сост.": "составитель",
    "пер.": "перевод",
    "тел.": "телефон",
    "адр.": "адрес",
    "обл.": "область",
    "р-н": "район",
    "пос.": "посёлок",
    "просп.": "проспект",
    "пл.": "площадь",
    "наб.": "набережная",
    "и.о.": "исполняющий обязанности",
    "с.г.": "сего года",
    "т.о.": "таким образом",
}

# Единицы измерения: раскрываются с согласованием по числу перед ними.
# Дробное число ("1,5 млн") всегда берёт родительный единственного —
# общее правило русской грамматики, не частный случай этого проекта.
UNITS = {
    "млн": ("миллион", "миллиона", "миллионов"),
    "млрд": ("миллиард", "миллиарда", "миллиардов"),
    "тыс.": ("тысяча", "тысячи", "тысяч"),
    "руб.": ("рубль", "рубля", "рублей"),
    "кг": ("килограмм", "килограмма", "килограммов"),
    "км": ("километр", "километра", "километров"),
    "мм": ("миллиметр", "миллиметра", "миллиметров"),
    "м": ("метр", "метра", "метров"),
    "долл.": ("доллар", "доллара", "долларов"),
}


def _plural_ru(n: int, forms: tuple[str, str, str]) -> str:
    n = abs(n) % 100
    if 11 <= n <= 14:
        return forms[2]
    tail = n % 10
    if tail == 1:
        return forms[0]
    if 2 <= tail <= 4:
        return forms[1]
    return forms[2]


def _unit_word(forms: tuple[str, str, str], number_text: str | None) -> str:
    if number_text is None:
        # Без числа рядом чаще всего это хвост составного количества,
        # уже раскрытого на этом же проходе ("7,2 млн долл." → число
        # стоит перед "млн", а не перед "долл.") — родительный
        # множественного подходит туда чаще, чем именительный
        # единственного ("миллиона долларов", не "миллиона доллар").
        return forms[2]
    if "," in number_text or "." in number_text:
        return forms[1]
    return _plural_ru(int(number_text), forms)


def _expand_units(text: str) -> str:
    for abbr, forms in UNITS.items():
        number = r"(\d+(?:[.,]\d+)?)\s?" if abbr in {"мм", "м"} else r"(?:(\d+(?:[.,]\d+)?)\s?)?"
        pattern = re.compile(
            number + r"(?<![а-яёa-z‐‑–-])" + re.escape(abbr) + r"(?![а-яёa-z‐‑–-])",
            re.IGNORECASE,
        )

        def repl(m: re.Match, forms=forms) -> str:
            prefix = f"{m.group(1)} " if m.group(1) else ""
            return prefix + _unit_word(forms, m.group(1))

        text = sub(pattern, repl, text)
    return text


def _sub_g(m: re.Match) -> str:
    number = m.group(1)
    if number:
        # Пробел явно, а не то, что было во входе (могло быть "1990 г."
        # с одним пробелом или "1990г." совсем без него) — иначе триггер
        # "число + году" в numbers.py (нужен ровно один пробел) не найдёт
        # склейку и раскрутит "году" как попало через голое число.
        return f"{number} году"
    rest = m.string[m.end():]
    if re.match(r"\s*[А-ЯЁ]", rest):
        return "город"
    return "год"


_ABBR_G = re.compile(r"(?:(\d+)\s*)?(?<![а-яёa-z])г\.")


def _expand_g(text: str) -> str:
    return sub(_ABBR_G, _sub_g, text)


# "20°C" — градус почти всегда лепится вплотную к числу без пробела;
# без явной вставки пробела здесь numbers.py потом приклеит "двадцать"
# прямо к "градусов" одним нечитаемым словом.
_ABBR_CELSIUS = re.compile(r"(?:(\d+(?:[.,]\d+)?)\s*)?°\s*[Cc]\.?")


def _expand_celsius(text: str) -> str:
    def repl(m: re.Match) -> str:
        prefix = f"{m.group(1)} " if m.group(1) else ""
        return f"{prefix}градусов Цельсия"

    return sub(_ABBR_CELSIUS, repl, text)


def _apply_case(original: str, replacement: str) -> str:
    if original[:1].isupper():
        return replacement[:1].upper() + replacement[1:]
    return replacement


def _expand_simple(text: str) -> str:
    for abbr, full in sorted(SIMPLE.items(), key=lambda kv: -len(kv[0])):
        pattern = re.compile(
            r"(?<![а-яёa-z])" + re.escape(abbr), re.IGNORECASE
        )

        def repl(m: re.Match, full=full) -> str:
            return _apply_case(m.group(0), full)

        text = sub(pattern, repl, text)
    return text


def expand_abbreviations(text: str) -> str:
    text = _expand_units(text)
    text = _expand_g(text)
    text = _expand_celsius(text)
    text = _expand_simple(text)
    return text
