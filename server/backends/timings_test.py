"""Тесты раскладки таймингов (TTS-7A, «Готово когда»). Проверяют арифметику
и поведение якорей, а не звучание: совпало ли на слух, машина сказать не
может — это пункты «Проверки руками».

Без pytest, как и `server/normalize/tests/cases.py`: в проекте нет тестовой
инфраструктуры, и ради двух модулей её не заводили.

Запуск: `uv run python -m server.backends.timings_test`
"""
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")  # см. TTS-2: иначе кириллица в перенаправленном выводе — кракозябры
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from server.backends import timings  # noqa: E402

FAILED = 0


def check(name: str, ok: bool, detail: str = "") -> None:
    global FAILED
    if ok:
        print(f"[ok  ] {name}")
        return
    FAILED += 1
    print(f"[ФЕЙЛ] {name}" + (f"\n       {detail}" if detail else ""))


def near(a: float, b: float, eps: float = 1e-6) -> bool:
    return abs(a - b) <= eps


# --- 1. Разбивка на слова -------------------------------------------------

def test_split():
    words = timings.split_words("Привет, мир! Как дела?")
    check("слова: найдены все четыре", [w[2] for w in words] == ["Привет", "мир", "Как", "дела"])
    check("слова: смещения указывают на себя же",
          all("Привет, мир! Как дела?"[o:o + n] == w for o, n, w in words))

    joined = timings.split_words("эйч-ти-эм-эль дошёл")
    check("слова: дефис не рвёт слово", [w[2] for w in joined] == ["эйч-ти-эм-эль", "дошёл"])

    marked = timings.split_words("прив+ет м+ир")
    check("слова: знак ударения остаётся внутри слова",
          [w[2] for w in marked] == ["прив+ет", "м+ир"])

    pause = timings.split_words("сначала - потом")
    check("слова: одиночный дефис-пауза словом не считается",
          [w[2] for w in pause] == ["сначала", "потом"])


# --- 2. Раскладка без якорей ---------------------------------------------

def test_layout_basics():
    text = "Он шёл по улице и думал о завтрашнем дне."
    words = timings.layout(text, 0.2, 3.4)

    check("раскладка: слов столько же, сколько в тексте",
          len(words) == len(timings.split_words(text)))
    check("раскладка: первое слово начинается там, где началась речь",
          near(words[0]["s"], 0.2, 1e-3))
    check("раскладка: последнее кончается там, где кончилась",
          near(words[-1]["e"], 3.4, 1e-3))
    check("раскладка: ни у одного слова не отрицательная длина",
          all(w["e"] >= w["s"] for w in words),
          str([(w["s"], w["e"]) for w in words if w["e"] < w["s"]]))
    check("раскладка: сумма длительностей равна длительности чанка",
          near(sum(w["e"] - w["s"] for w in words), 3.4 - 0.2, 2e-3),
          f"сумма {sum(w['e'] - w['s'] for w in words):.4f}")
    check("раскладка: покрытие сплошное, дыр между словами нет",
          all(near(words[k]["e"], words[k + 1]["s"], 2e-3) for k in range(len(words) - 1)))
    check("раскладка: смещения попадают в исходный текст",
          all(text[w["off"]:w["off"] + w["n"]].strip() for w in words))

    check("раскладка: пустой текст — пустой список", timings.layout("", 0.0, 1.0) == [])
    check("раскладка: нулевая длительность — пустой список",
          timings.layout("Слово", 1.0, 1.0) == [])


def test_syllables():
    # «встреч» — шесть букв и один слог, «оборона» — семь букв и четыре.
    # По буквам их длительности почти равны, по слогам — вдвое разные.
    words = timings.layout("встреч оборона", 0.0, 2.0)
    short, long_ = words[0]["e"] - words[0]["s"], words[1]["e"] - words[1]["s"]
    check("слоги: многосложное слово длиннее односложного той же длины",
          long_ > short * 1.6, f"встреч {short:.3f}с, оборона {long_:.3f}с")


def test_min_duration():
    # Односложные предлоги в длинной фразе: подсветка должна их показать,
    # а не мигнуть на кадр («Готово когда», пункт 3).
    text = "Я в и к б однажды пошёл в невероятно длинное путешествие по окрестностям."
    words = timings.layout(text, 0.0, 6.0)
    tiny = [w for w in words if w["n"] == 1]
    check("минимум: односложные не короче порога",
          all(w["e"] - w["s"] >= timings.MIN_WORD_S - 1e-3 for w in tiny),
          str([(text[w["off"]], round(w["e"] - w["s"], 3)) for w in tiny]))
    check("минимум: сумма всё равно сходится",
          near(sum(w["e"] - w["s"] for w in words), 6.0, 2e-3))

    # Вырожденный случай: слов больше, чем миллисекунд.
    dense = timings.layout(" ".join(["а"] * 50), 0.0, 0.5)
    check("минимум: не ломается, когда места не хватает никому",
          len(dense) == 50 and all(w["e"] >= w["s"] for w in dense)
          and near(sum(w["e"] - w["s"] for w in dense), 0.5, 2e-3))


# --- 3. Якоря -------------------------------------------------------------

def test_anchors():
    text = "Первое слово, второе слово."
    # Провал ровно на запятой: в раскладке без якоря граница уехала бы.
    words = timings.layout(text, 0.0, 4.0, [(1.5, 2.0)])
    after = next(w for w in words if text[w["off"]:w["off"] + w["n"]] == "второе")
    before = next(w for w in words if w["off"] < after["off"] and w["n"] == 5)
    check("якорь: слово после запятой стартует после провала",
          near(after["s"], 2.0, 1e-3), f"старт {after['s']}")
    check("якорь: слово перед запятой держится всю паузу",
          near(before["e"], 2.0, 1e-3), f"конец {before['e']}")
    check("якорь: сумма по-прежнему сходится",
          near(sum(w["e"] - w["s"] for w in words), 4.0, 2e-3))

    # Знаков три, провал один — он обязан сесть на СВОЙ знак, а не на первый.
    text3 = "раз, два, три, четыре"
    late = timings.layout(text3, 0.0, 4.0, [(2.9, 3.1)])
    четыре = late[3]
    check("якорь: одинокий провал садится на ближний по слогам знак, а не на первый",
          near(четыре["s"], 3.1, 1e-3), f"«четыре» стартует в {четыре['s']}")

    # Провалов больше, чем знаков: лишние (короткие) должны отсеяться,
    # длинный — сесть на запятую.
    noisy = timings.layout("раз, два", 0.0, 2.0, [(0.3, 0.4), (0.9, 1.2), (1.6, 1.7)])
    check("якорь: из лишних провалов берётся самый длинный",
          near(noisy[1]["s"], 1.2, 1e-3), f"«два» стартует в {noisy[1]['s']}")

    # Провал далеко от любого знака — выбросить, а не тянуть якорь силой:
    # раскладка должна получиться ровно такой же, как если бы провала не было.
    wild_text = "одно длинное предложение, потом ещё немного слов совсем"
    wild = timings.layout(wild_text, 0.0, 4.0, [(0.15, 0.30)])
    check("якорь: провал, стоящий не на месте, игнорируется",
          wild == timings.layout(wild_text, 0.0, 4.0, []),
          f"«потом» стартует в {wild[3]['s']}")

    # Без знаков препинания якорей нет вовсе.
    plain = timings.layout("раз два три", 0.0, 3.0, [(1.0, 1.2)])
    check("якорь: без знаков препинания провал не используется",
          plain == timings.layout("раз два три", 0.0, 3.0, []))


# --- 4. Поиск провалов в звуке -------------------------------------------

def test_find_dips():
    try:
        import numpy as np
    except ImportError:
        print("[проп] numpy нет — поиск провалов не проверен")
        return

    sr = 48000

    def tone(seconds):
        t = np.arange(int(sr * seconds)) / sr
        return 0.3 * np.sin(2 * np.pi * 220 * t).astype(np.float32)

    def hush(seconds):
        return np.zeros(int(sr * seconds), dtype=np.float32)

    signal = np.concatenate([hush(0.30), tone(0.50), hush(0.20), tone(0.40), hush(0.25)])
    head, tail, dips = timings.find_dips(signal, sr)
    check("звук: начальная тишина отрезана", near(head, 0.30, 0.02), f"head={head}")
    check("звук: конечная тишина отрезана", near(tail, 1.40, 0.02), f"tail={tail}")
    check("звук: найден ровно один провал", len(dips) == 1, str(dips))
    if dips:
        check("звук: провал там, где тишина",
              near(dips[0][0], 0.80, 0.02) and near(dips[0][1], 1.00, 0.02), str(dips))

    short = np.concatenate([tone(0.30), hush(0.04), tone(0.30)])
    _, _, few = timings.find_dips(short, sr)
    check("звук: провал короче порога не считается паузой", few == [], str(few))

    check("звук: тишина целиком не роняет", timings.find_dips(hush(0.5), sr)[2] == [])
    check("звук: пустой вход не роняет", timings.find_dips(np.zeros(0, dtype=np.float32), sr)[2] == [])

    words, info = timings.word_timings(signal, sr, "Раз, два.")
    check("звук: сквозной путь отдаёт слова и статистику",
          len(words) == 2 and info["dips"] == 1 and info["marks"] == 1, f"{words} {info}")
    check("звук: сквозной путь ставит второе слово после паузы",
          near(words[1]["s"], 1.00, 0.02), str(words))


# --- 5. Заглушка ----------------------------------------------------------

def test_flat():
    words = timings.flat_timings("Раз два три", 3.0)
    check("заглушка: раскладка без звука работает",
          len(words) == 3 and near(words[0]["s"], 0.0) and near(words[-1]["e"], 3.0))


def main():
    test_split()
    test_layout_basics()
    test_syllables()
    test_min_duration()
    test_anchors()
    test_find_dips()
    test_flat()
    print()
    if FAILED:
        print(f"{FAILED} проверок не прошли.")
        sys.exit(1)
    print("Все проверки прошли.")


if __name__ == "__main__":
    main()
