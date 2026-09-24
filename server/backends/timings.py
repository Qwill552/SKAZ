"""Пословные тайминги: где в готовом звуке какое слово.

Silero их не отдаёт — проверено прямым вызовом на обеих моделях
(`apply_tts(return_ts=True)` → «This model doesn't support return_ts»),
и forced alignment ради этого шага не берём. Значит оценка, и она
складывается из двух дешёвых приёмов (skaz/07a-word-highlight.md,
«Разведка»):

1. **Реальные паузы видно в самом WAV.** Silero честно останавливается
   на запятых, точках и тире. Окно 10 мс, RMS, провал ниже порога
   дольше 80 мс — это якорь: место, про которое известно точно. Между
   якорями ошибка не копится, что и отличает эту оценку от наивной.
2. **Слоги, а не буквы.** «Встреч» — шесть букв и один слог, «оборона» —
   семь букв и четыре; по буквам раскладка на такой паре ошибается
   заметно, по гласным почти нет. Веса гласных чуть разбавлены длиной
   слова: чистые слоги недооценивают согласные кластеры.

Модуль нарочно делится на «чистую» половину (разбивка на слова,
раскладка) и «звуковую» (`find_dips`). numpy импортируется **внутри**
`find_dips`, а не на уровне модуля: раскладку зовёт и диспетчер (через
StubBackend), а диспетчер обязан оставаться лёгким — цель TTS-3
«простаивающий процесс стоит как пустая вкладка» держится на том, что он
не тянет ни torch, ни numpy.

Все коэффициенты — здесь, в одном месте: их крутят на слух.
"""
from __future__ import annotations

import re

# --- коэффициенты поиска пауз ---
WINDOW_MS = 10          # окно RMS
MIN_PAUSE_MS = 80       # провал короче — это не пауза, а смычка внутри речи
SPEECH_PERCENTILE = 85  # «громкость речи» берём как перцентиль, а не максимум: один щелчок не должен задирать порог
SILENCE_FRACTION = 0.10 # порог тишины — доля от неё. Абсолютный порог развалился бы на тихом голосе

# --- коэффициенты раскладки ---
VOWELS = frozenset("аеёиоуыэюя")
CHAR_WEIGHT = 0.2       # добавка за длину слова: чистые слоги недооценивают «встреч» против «оборона»
MIN_WEIGHT = 0.6        # «в», «к», «б» — без гласных вовсе, но звучат не нулевое время
MIN_WORD_S = 0.05       # и подсвечиваются заметно, а не на один кадр

# Сколько доли чанка может «проехать» якорь, прежде чем выгоднее счесть
# провал случайным и выбросить его. Ошибиться местом хуже, чем не иметь
# якоря вовсе: без якоря раскладка просто равномерная.
MAX_ANCHOR_DRIFT = 0.22

# Слово: буквы, цифры и знак ударения `+` (он часть алфавита модели и
# стоит внутри слова). Дефис склеивает — «эйч-ти-эм-эль» это одно слово,
# оно и в исходном тексте одно («HTML»). Одиночный `-` между пробелами —
# это пауза из пользовательского словаря, а не слово, и сюда не попадает.
WORD_RE = re.compile(r"[\w+]+(?:-[\w+]+)*")

# Знаки, на которых Silero может остановиться. Каждый такой знак между
# двумя словами — кандидат в якоря.
PAUSE_MARKS = frozenset(",.!?…:;—–-")


def split_words(text: str) -> list[tuple[int, int, str]]:
    """[(смещение, длина, слово)] по тексту, который ушёл в синтез."""
    return [(m.start(), m.end() - m.start(), m.group(0)) for m in WORD_RE.finditer(text)]


def _weight(word: str) -> float:
    letters = [c for c in word.lower() if c.isalpha()]
    vowels = sum(1 for c in letters if c in VOWELS)
    return max(MIN_WEIGHT, vowels + CHAR_WEIGHT * len(letters))


def _marks(text: str, words: list[tuple[int, int, str]]) -> list[int]:
    """Номера слов, ПЕРЕД которыми в тексте стоит знак препинания."""
    out = []
    for k in range(1, len(words)):
        gap = text[words[k - 1][0] + words[k - 1][1]:words[k][0]]
        if any(c in PAUSE_MARKS for c in gap):
            out.append(k)
    return out


def find_dips(samples, sample_rate: int) -> tuple[float, float, list[tuple[float, float]]]:
    """(начало речи, конец речи, провалы внутри) — всё в секундах.

    Края нужны отдельно: Silero щедро добавляет тишину в начало и конец,
    и без её отрезания первое слово подсветится заметно раньше, чем
    прозвучит (пункт 1 «Проверки руками»)."""
    import numpy as np

    x = np.asarray(samples, dtype=np.float32)
    total = x.size / sample_rate if x.size else 0.0
    win = max(1, int(sample_rate * WINDOW_MS / 1000))
    n = x.size // win
    if n == 0:
        return 0.0, total, []

    rms = np.sqrt(np.square(x[:n * win].reshape(n, win)).mean(axis=1))
    level = float(np.percentile(rms, SPEECH_PERCENTILE))
    if level <= 0.0:
        return 0.0, total, []

    loud = rms >= level * SILENCE_FRACTION
    idx = np.flatnonzero(loud)
    if idx.size == 0:
        return 0.0, total, []

    first, last = int(idx[0]), int(idx[-1])
    step = win / sample_rate
    head, tail = first * step, (last + 1) * step

    dips: list[tuple[float, float]] = []
    quiet = (~loud).tolist()
    i = first
    while i <= last:
        if not quiet[i]:
            i += 1
            continue
        j = i
        while j <= last and quiet[j]:
            j += 1
        if (j - i) * WINDOW_MS >= MIN_PAUSE_MS:
            dips.append((i * step, j * step))
        i = j
    return head, tail, dips


def _assign(dips: list[tuple[float, float]], marks: list[int],
            frac_at: list[float], head: float, tail: float) -> list[tuple[int, float, float]]:
    """Сопоставить найденные провалы знакам препинания.

    По порядку, «первый провал — первому знаку», сопоставлять нельзя:
    Silero останавливается не на каждой запятой, и один пропуск сдвинул бы
    все якоря до конца фразы. Поэтому выбор monotone-назначения ищется
    динамикой по стоимости «насколько провал стоит не там, где знак».
    Размерность здесь — единицы на единицы, полный перебор дешевле
    объяснения, зачем он не нужен."""
    if not dips or not marks:
        return []
    if len(dips) > len(marks):
        # Провалов больше, чем знаков — значит порог поймал и смычки
        # внутри речи. Берём самые длинные (ТЗ, §2 пункт 3).
        dips = sorted(sorted(dips, key=lambda d: d[0] - d[1])[:len(marks)])

    span = max(1e-6, tail - head)
    dfrac = [((a + b) / 2 - head) / span for a, b in dips]

    d, g = len(dips), len(marks)
    inf = float("inf")
    # f[i][j] — минимальная стоимость, когда первые i провалов разложены
    # по первым j знакам. Из клетки три хода: пропустить знак, пропустить
    # провал (штраф MAX_ANCHOR_DRIFT), поставить якорь.
    f = [[inf] * (g + 1) for _ in range(d + 1)]
    back = [[0] * (g + 1) for _ in range(d + 1)]
    f[0][0] = 0.0
    for i in range(d + 1):
        for j in range(g + 1):
            if f[i][j] == inf:
                continue
            if j < g and f[i][j] < f[i][j + 1]:
                f[i][j + 1], back[i][j + 1] = f[i][j], 1          # знак без провала
            if i < d:
                drop = f[i][j] + MAX_ANCHOR_DRIFT
                if drop < f[i + 1][j]:
                    f[i + 1][j], back[i + 1][j] = drop, 2          # провал мимо кассы
                if j < g:
                    cost = f[i][j] + abs(dfrac[i] - frac_at[marks[j]])
                    if cost < f[i + 1][j + 1]:
                        f[i + 1][j + 1], back[i + 1][j + 1] = cost, 3   # якорь
    i, j = d, g
    out: list[tuple[int, float, float]] = []
    while i > 0 or j > 0:
        move = back[i][j]
        if move == 1:
            j -= 1
        elif move == 2:
            i -= 1
        elif move == 3:
            i -= 1
            j -= 1
            out.append((marks[j], dips[i][0], dips[i][1]))
        else:
            break
    out.reverse()
    return out


def _spread(words: list[tuple[int, int, str]], t0: float, t1: float) -> list[list[float]]:
    """Разложить отрезок [t0, t1] по словам пропорционально весу, но так,
    чтобы ни одно не получило меньше MIN_WORD_S."""
    n = len(words)
    if n == 0:
        return []
    span = max(0.0, t1 - t0)
    if span <= n * MIN_WORD_S:
        step = span / n
        return [[t0 + k * step, t0 + (k + 1) * step] for k in range(n)]

    weights = [_weight(w[2]) for w in words]
    durations = [0.0] * n
    pinned = [False] * n
    for _ in range(n):
        free = [k for k in range(n) if not pinned[k]]
        rest = span - MIN_WORD_S * (n - len(free))
        total = sum(weights[k] for k in free) or 1.0
        short = []
        for k in free:
            durations[k] = rest * weights[k] / total
            if durations[k] < MIN_WORD_S:
                short.append(k)
        if not short:
            break
        for k in short:
            durations[k] = MIN_WORD_S
            pinned[k] = True

    out = []
    t = t0
    for k in range(n):
        out.append([t, t + durations[k]])
        t += durations[k]
    return out


def layout(text: str, head: float, tail: float,
           dips: list[tuple[float, float]] | None = None) -> list[dict]:
    """Слова с временами. Времена сплошные: конец слова — это начало
    следующего, пауза между ними достаётся предыдущему. Подсветка
    переключается по началу слова, поэтому в паузе она не мигает, а
    досиживает на только что прозвучавшем слове."""
    words = split_words(text)
    if not words or tail <= head:
        return []

    marks = _marks(text, words)
    weights = [_weight(w[2]) for w in words]
    total = sum(weights) or 1.0
    cum = [0.0]
    for w in weights:
        cum.append(cum[-1] + w)
    frac_at = [c / total for c in cum]

    anchors = _assign(dips or [], marks, frac_at, head, tail)

    # Речь разбита якорями на куски: [начало, провал), (провал, провал), …
    pieces: list[tuple[int, int, float, float]] = []
    at_word, at_time = 0, head
    for mark, dip_start, dip_end in anchors:
        if mark <= at_word or dip_start <= at_time:
            continue   # якорь не добавляет информации, пропускаем
        pieces.append((at_word, mark, at_time, dip_start))
        at_word, at_time = mark, dip_end
    pieces.append((at_word, len(words), at_time, tail))

    spans: list[list[float]] = []
    for lo, hi, t0, t1 in pieces:
        spans.extend(_spread(words[lo:hi], t0, t1))

    # Сплошное покрытие: паузу отдаём предыдущему слову, хвост — последнему.
    for k in range(len(spans) - 1):
        spans[k][1] = spans[k + 1][0]
    if spans:
        spans[-1][1] = tail

    return [
        {"s": round(spans[k][0], 3), "e": round(spans[k][1], 3),
         "off": words[k][0], "n": words[k][1]}
        for k in range(len(words))
    ]


def word_timings(samples, sample_rate: int, text: str) -> tuple[list[dict], dict]:
    """Полный путь: сэмплы + текст → слова со временами. `info` идёт в лог
    сервера — по нему видно, нашлись якоря или раскладка чисто слоговая
    (пункт 2 «Проверки руками»)."""
    head, tail, dips = find_dips(samples, sample_rate)
    words = layout(text, head, tail, dips)
    return words, {
        "dips": len(dips),
        "marks": len(_marks(text, split_words(text))),
        "head": round(head, 3),
        "tail": round(tail, 3),
    }


def flat_timings(text: str, duration: float) -> list[dict]:
    """Раскладка без звука вовсе — для заглушки (StubBackend) и тестов."""
    return layout(text, 0.0, duration, [])
