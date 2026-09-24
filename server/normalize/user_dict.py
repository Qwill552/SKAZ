"""Пользовательский словарь (`user_dict.json`, §6): простые замены по
границам слова, без учёта регистра, применяются первыми — до сокращений
и чисел, — потому что это ручная правка конкретных слов (обычно имён
собственных), а не общее правило текста. Ударение в неизменной основе
переносится на обычные падежные формы; явные записи имеют приоритет.

`UserDictWatcher` перечитывает файл, если его mtime изменился с прошлого
раза — правка должна становиться слышна без перезапуска сервера (§6),
и без этого правка застревала бы до следующего старта процесса."""
import json
import re
from functools import lru_cache
from pathlib import Path

from .spans import sub


def load_user_dict(path: Path) -> dict[str, str]:
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    if not isinstance(data, dict):
        return {}
    return {str(k): str(v) for k, v in data.items()}


class UserDictWatcher:
    def __init__(self, path: Path):
        self._path = path
        self._mtime: float | None = None
        self._data: dict[str, str] = {}

    def get(self) -> dict[str, str]:
        try:
            mtime = self._path.stat().st_mtime
        except FileNotFoundError:
            self._mtime = None
            self._data = {}
            return self._data
        if mtime != self._mtime:
            self._data = load_user_dict(self._path)
            self._mtime = mtime
        return self._data


def stress_forms(key: str, value: str) -> dict[str, str]:
    """Обычные формы с ударением в неизменной основе.

    Только запись, добавляющая один знак + в русское слово: произвольные
    замены, фразы и паузы не склоняем. Если ударение стоит на удаляемом
    окончании, перенести его без знания слова нельзя — нужна явная запись.
    """
    if (not re.fullmatch(r"[а-яё]{3,}", key, re.I) or
            value.count("+") != 1 or value.replace("+", "").casefold() != key.casefold() or
            not re.search(r"\+[аеёиоуыэюя]", value, re.I)):
        return {}
    lower = key.casefold()
    cut = 0
    if lower.endswith("ия"):
        cut, endings = 1, ("и", "ю", "ей", "ею")
    elif lower.endswith("а"):
        instrumental = ("ей", "ею") if lower[-2] in "жчшщц" else ("ой", "ою")
        cut, endings = 1, (("и" if lower[-2] in "гкхжчшщ" else "ы"), "е", "у", *instrumental)
    elif lower.endswith("я"):
        cut, endings = 1, ("и", "е", "ю", "ей", "ею")
    elif lower.endswith("й"):
        cut, endings = 1, ("я", "ю", "ем", "и" if lower.endswith("ий") else "е")
    elif lower.endswith("ь"):
        cut, endings = 1, ("я", "ю", "ем", "е", "и", "ью")
    elif lower[-1] in "бвгджзклмнпрстфхцчшщ":
        endings = ("а", "у", "ем" if lower[-1] in "жчшщц" else "ом", "е")
    else:
        return {}
    stem = key[:-cut] if cut else key
    marked_stem = value[:-cut] if cut else value
    if marked_stem.endswith("+"):
        return {}
    return {stem + ending: marked_stem + ending for ending in endings}


@lru_cache(maxsize=8)
def _compiled_entries(entries: tuple[tuple[str, str], ...]):
    replacements = {}
    for key, value in entries:
        for form, replacement in stress_forms(key, value).items():
            replacements.setdefault(form.casefold(), replacement)
    # Явная запись перекрывает автоматически полученную форму.
    replacements.update({key.casefold(): value for key, value in entries if key})
    if not replacements:
        return None, replacements
    alternatives = "|".join(re.escape(key) for key in sorted(replacements, key=len, reverse=True))
    # Один проход: результат замены не попадает под следующую запись.
    # Не трогаем слова с уже проставленным вручную ударением.
    pattern = re.compile(r"(?<![\w+])(?:" + alternatives + r")(?![\w+])", re.IGNORECASE)
    return pattern, replacements


def apply_user_dict(text: str, user_dict: dict[str, str]) -> str:
    pattern, replacements = _compiled_entries(tuple(user_dict.items()))
    if pattern is None:
        return text
    return sub(pattern, lambda m: replacements[m.group().casefold()], text)
