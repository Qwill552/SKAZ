import re

from .spans import Tracked, sub


_CHETA = re.compile(r"(?<![\w+])чета(?![\w+])", re.IGNORECASE)
_VSE_AFTER_TAK_CHTO = re.compile(r"(?<=так что )все(?= прекрасно понимали\b)", re.IGNORECASE)
_LEADING_DIALOGUE_DASH = re.compile(r"^[—–][ \t]+")


def _stress_final(match: re.Match) -> str:
    word = match.group()
    return word[:-1] + "+" + word[-1]


def local_text(tracked: Tracked) -> Tracked:
    tracked = sub(_CHETA, _stress_final, tracked)
    tracked = sub(_VSE_AFTER_TAK_CHTO, _stress_final, tracked)
    return sub(_LEADING_DIALOGUE_DASH, "", tracked)
