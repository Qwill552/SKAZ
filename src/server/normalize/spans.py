"""Нормализация со следом: откуда в исходном тексте взялся каждый символ.

Зачем. Пословная подсветка (TTS-7A) рисуется по живому DOM, то есть по
ИСХОДНОМУ тексту страницы, а тайминги считаются по тексту, ушедшему в
синтез, — а это разные строки: «1867 г.» (7 знаков) превращается в
«тысяча восемьсот шестьдесят седьмом году» (40). Смещение слова в
нормализованном тексте на странице не значит ничего, и подсветка без
обратного отображения уехала бы на десятки знаков.

Как. Все проходы нормализации — это `pattern.sub(repl, text)` и ничего
кроме. Поэтому достаточно одной обёртки: `Tracked` носит рядом с текстом
два массива по символам — начало и конец куска ИСХОДНОГО текста, из
которого этот символ произошёл. На замене весь результат наследует span
всего совпадения целиком: слова «тысяча», «восемьсот», …, «году» все
укажут на «1867 г.», и подсветка будет держаться на нём, пока оно
звучит. Это и есть правильное поведение — на странице подсвечивать
нечего, кроме исходных семи знаков.

`sub()` ниже принимает и обычную строку (тогда это просто
`pattern.sub`), и `Tracked`, поэтому модули нормализации не раздваиваются
на две версии: один и тот же код обслуживает и `normalize()`, и
`normalize_tracked()`.
"""
from __future__ import annotations

import re


class Tracked:
    """Строка плюс происхождение каждого символа. Неизменяемая: каждый
    `sub()` возвращает новый объект, как и у обычных строк."""

    __slots__ = ("text", "s0", "s1")

    def __init__(self, text: str, s0: list[int] | None = None, s1: list[int] | None = None):
        self.text = text
        self.s0 = list(range(len(text))) if s0 is None else s0
        self.s1 = list(range(1, len(text) + 1)) if s1 is None else s1

    def __len__(self) -> int:
        return len(self.text)

    def sub(self, pattern: re.Pattern, repl) -> "Tracked":
        out: list[str] = []
        o0: list[int] = []
        o1: list[int] = []
        pos = 0
        hit = False
        for m in pattern.finditer(self.text):
            a, b = m.span()
            if b <= a:
                continue  # пустых совпадений в наших проходах нет, но переносить из них нечего
            hit = True
            out.append(self.text[pos:a])
            o0.extend(self.s0[pos:a])
            o1.extend(self.s1[pos:a])
            piece = repl(m) if callable(repl) else m.expand(repl)
            lo = min(self.s0[a:b])
            hi = max(self.s1[a:b])
            out.append(piece)
            o0.extend([lo] * len(piece))
            o1.extend([hi] * len(piece))
            pos = b
        if not hit:
            return self
        out.append(self.text[pos:])
        o0.extend(self.s0[pos:])
        o1.extend(self.s1[pos:])
        return Tracked("".join(out), o0, o1)

    def strip(self) -> "Tracked":
        text = self.text
        a = len(text) - len(text.lstrip())
        b = len(text.rstrip())
        if a == 0 and b == len(text):
            return self
        return Tracked(text[a:b], self.s0[a:b], self.s1[a:b])

    def source_span(self, off: int, length: int) -> tuple[int, int]:
        """Кусок исходного текста, который породил срез [off, off+length).
        Пустой срез — (0, 0), звать с ним незачем."""
        end = off + length
        if length <= 0 or off < 0 or end > len(self.text):
            return (0, 0)
        return (min(self.s0[off:end]), max(self.s1[off:end]))


def sub(pattern: re.Pattern, repl, text):
    """Единственная точка, через которую нормализация меняет текст.
    Работает одинаково на `str` и на `Tracked` — поэтому проходы написаны
    один раз, а не дважды."""
    if isinstance(text, Tracked):
        return text.sub(pattern, repl)
    return pattern.sub(repl, text)
