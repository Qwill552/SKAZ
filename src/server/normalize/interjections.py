import re

from .spans import sub


HYPHEN = r"[-‐‑–]"
EDGE = r"[\w‐‑–-]"

VOWEL_REPEAT = re.compile(
    rf"(?<!{EDGE})([а-яё]*?)([аеёиоуыэюя])\2*(?:{HYPHEN}\2+)+(?!{EDGE})",
    re.IGNORECASE,
)
MURMUR = re.compile(
    rf"(?<!{EDGE})(?:[хэ]м+|м{{2,}}|м+{HYPHEN}м+)(?:{HYPHEN}м+)*(?!{EDGE})",
    re.IGNORECASE,
)
LAUGHTER = re.compile(
    rf"(?<!{EDGE})[аэ]?х([аеиоуыэ])(?:{HYPHEN}х\1)+(?!{EDGE})",
    re.IGNORECASE,
)
SHORT_QUESTION = re.compile(rf"(?<!{EDGE})([аоэу])\?(?!{EDGE})", re.IGNORECASE)


def _preserve_case(original: str, pronunciation: str) -> str:
    letters = "".join(char for char in original if char.isalpha())
    if len(letters) > 1 and letters.isupper():
        return pronunciation.upper()
    if original[0].isupper():
        return pronunciation.capitalize()
    return pronunciation


def _vowel(match: re.Match) -> str:
    original = match.group(0)
    prefix = match.group(1).lower()
    count = sum(char.isalpha() for char in original[len(prefix):])
    pronunciation = prefix + match.group(2).lower() * min(6, max(3, count + 1))
    return _preserve_case(original, pronunciation)


def _murmur(match: re.Match) -> str:
    original = match.group(0)
    prefix = original[0].lower() if original[0].lower() in "хэ" else ""
    count = sum(char.lower() == "м" for char in original)
    pronunciation = prefix + "м" * min(6, max(3, count + 1))
    return _preserve_case(original, pronunciation)


def _laughter(match: re.Match) -> str:
    original = match.group(0)
    pronunciation = "".join(char.lower() for char in original if char.isalpha())
    return _preserve_case(original, pronunciation)


def _short_question(match: re.Match) -> str:
    original = match.group(0)
    return _preserve_case(original, original[0].lower() * 3 + "?")


def pronounce_interjections(text):
    text = sub(VOWEL_REPEAT, _vowel, text)
    text = sub(MURMUR, _murmur, text)
    text = sub(LAUGHTER, _laughter, text)
    return sub(SHORT_QUESTION, _short_question, text)
