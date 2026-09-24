import unittest

from server.normalize import normalize, normalize_tracked


class InterjectionTests(unittest.TestCase):
    def test_expressive_forms(self):
        cases = {
            "— Мм.": "— Ммм.",
            "— Ммм…": "— Мммм…",
            "— М-м-м?": "— Мммм?",
            "— Эм.": "— Эммм.",
            "Хм-м…": "Хммм…",
            "Хм-м-м…": "Хмммм…",
            "хм-м...": "хммм...",
            "— Эм-м, Розмайн…": "— Эммм, Розмайн…",
            "— Эмм-м?": "— Эмммм?",
            "— А-а?": "— Ааа?",
            "— А-а-а!": "— Аааа!",
            "— О-о-о…": "— Оооо…",
            "— Ну-у, хорошо.": "— Нууу, хорошо.",
            "— Да-а…": "— Дааа…",
            "— Э‑э?": "— Эээ?",
            "— Ю-ю?": "— Ююю?",
            "— Эхе-хе.": "— Эхехе.",
            "— Хе-хе.": "— Хехе.",
            "— Ха-ха-ха!": "— Хахаха!",
            "— А?": "— Ааа?",
            "— О?": "— Ооо?",
            "А ты?": "А ты?",
        }
        for original, expected in cases.items():
            with self.subTest(original=original):
                self.assertEqual(normalize(original), expected)

    def test_compound_words_and_measurements(self):
        cases = {
            "В те дни, когда я была священницей-ученицей": "В те дни, когда я была священницей-ученицей",
            "еле-еле и кое-как": "еле-еле и кое-как",
            "5 м, 2 км и 1 мм": "пять метров, два километра и один миллиметр",
            "5м, 2км и 1мм": "пять метров, два километра и один миллиметр",
            "2 кг, 3 мм": "два килограмма, три миллиметра",
            "— Мм. Длина 5 мм.": "— Ммм. Длина пять миллиметров.",
            "Мама-мама, да-да": "Мама-мама, да-да",
        }
        for original, expected in cases.items():
            with self.subTest(original=original):
                self.assertEqual(normalize(original), expected)

    def test_highlight_span_points_to_original_interjection(self):
        original = "— Эм-м, Розмайн…"
        tracked = normalize_tracked(original)
        pronunciation = "Эммм"
        start, end = tracked.source_span(tracked.text.index(pronunciation), len(pronunciation))
        self.assertEqual(original[start:end], "Эм-м")


if __name__ == "__main__":
    unittest.main()
