"""Слой нормализации текста перед синтезом: числа, сокращения, латиница,
ручные пометки пользователя. Зовётся в `/tts` перед `backend.synth`,
бэкенд про нормализацию не знает (skaz/04-text-normalization.md, §1).

Порядок фиксированный, менять только осознанно:
пользовательский словарь → сокращения → междометия → числа → латиница → ударения →
уборка пробелов. Причины порядка — в §2 того же файла: "1,5" должно
стать "полторы" до того, как запятая превратится в разделитель
предложений; "т.д." разложить до того, как точка станет концом
предложения; "г." решить как год/город, пока рядом ещё цифра, а не слово.
"""
import re

from .abbrev import expand_abbreviations
from .interjections import pronounce_interjections
from .latin import transliterate_latin
from .numbers import expand_numbers
from .spans import Tracked, sub
from .stress import apply_user_marks
from .user_dict import apply_user_dict

_WHITESPACE = re.compile(r"[ \t]+")
_SPACED_NEWLINE = re.compile(r" *\n *")


def normalize(text: str, user_dict: dict[str, str] | None = None) -> str:
    return _run(text, user_dict)


def normalize_tracked(text: str, user_dict: dict[str, str] | None = None) -> Tracked:
    """То же самое, но с обратным следом «символ → кусок исходного текста».
    Нужен пословной подсветке (TTS-7A): тайминги считаются по тексту,
    ушедшему в синтез, а подсвечивается исходный текст страницы, и без
    следа смещения слов не переводятся из одного в другой. См. spans.py."""
    return _run(Tracked(text), user_dict)


def _run(text, user_dict: dict[str, str] | None):
    """Один и тот же конвейер для строки и для Tracked — проходы работают
    через spans.sub(), который умеет и то, и другое."""
    text = apply_user_dict(text, user_dict or {})
    text = expand_abbreviations(text)
    text = pronounce_interjections(text)
    text = expand_numbers(text)
    text = transliterate_latin(text)
    text = apply_user_marks(text)
    text = _cleanup_whitespace(text)
    return text


def _cleanup_whitespace(text):
    text = sub(_WHITESPACE, " ", text)
    text = sub(_SPACED_NEWLINE, "\n", text)
    return text.strip()
