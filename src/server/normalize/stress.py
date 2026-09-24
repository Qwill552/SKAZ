import re

from .spans import sub


_DECOMPOSED_YO_WITH_ACUTE = re.compile(r"\+?([Ее])(?:\u0308[\u0301\u0341]|[\u0301\u0341]\u0308)")
_VOWEL_WITH_ACUTE = re.compile(r"\+?([АЕЁИОУЫЭЮЯаеёиоуыэюя])[\u0301\u0341]")


def _stress_yo(match: re.Match) -> str:
    return "+Ё" if match.group(1).isupper() else "+ё"


def _stress_vowel(match: re.Match) -> str:
    return "+" + match.group(1)


def apply_user_marks(text: str) -> str:
    text = sub(_DECOMPOSED_YO_WITH_ACUTE, _stress_yo, text)
    text = sub(_VOWEL_WITH_ACUTE, _stress_vowel, text)
    return text
