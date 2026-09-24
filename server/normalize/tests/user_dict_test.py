"""Падежные формы словаря и сохранение координат для подсветки."""
import unittest

from server.normalize import normalize, normalize_tracked
from server.normalize.user_dict import apply_user_dict


class UserDictionaryTests(unittest.TestCase):
    def test_ferdinand_all_cases(self):
        dictionary = {"Фердинанд": "Фердин+анд"}
        for word in ("Фердинанд", "Фердинанда", "Фердинанду", "Фердинандом", "Фердинанде"):
            with self.subTest(word=word):
                self.assertEqual(normalize(word, dictionary), word.replace("анд", "+анд"))

    def test_regular_endings(self):
        cases = [
            ("Шарлотта", "Шарл+отта", "Шарлотты Шарлотте Шарлотту Шарлоттой", "Шарл+отты Шарл+отте Шарл+отту Шарл+оттой"),
            ("Флоренсия", "Флор+енсия", "Флоренсии Флоренсию Флоренсией", "Флор+енсии Флор+енсию Флор+енсией"),
            ("Сергей", "Серг+ей", "Сергея Сергею Сергеем Сергее", "Серг+ея Серг+ею Серг+еем Серг+ее"),
            ("Дмитрий", "Дм+итрий", "Дмитрия Дмитрию Дмитрием Дмитрии", "Дм+итрия Дм+итрию Дм+итрием Дм+итрии"),
            ("Игорь", "+Игорь", "Игоря Игорю Игорем Игоре", "+Игоря +Игорю +Игорем +Игоре"),
            ("Наталья", "Нат+алья", "Натальи Наталье Наталью Натальей", "Нат+альи Нат+алье Нат+алью Нат+альей"),
        ]
        for key, value, text, expected in cases:
            with self.subTest(key=key):
                self.assertEqual(normalize(text, {key: value}), expected)

    def test_explicit_form_wins_in_any_order(self):
        entries = [("Фердинанд", "Фердин+анд"), ("Фердинанда", "Ф+ердинанда")]
        for order in (entries, entries[::-1]):
            self.assertEqual(normalize("Фердинанда", dict(order)), "Ф+ердинанда")

    def test_similar_words_and_manual_stress_unchanged(self):
        text = "Фердинандович Фердинандский суперФердинанд Фердин+анда"
        self.assertEqual(normalize(text, {"Фердинанд": "Фердин+анд"}), text)

    def test_exact_phonetic_replacement_and_phrase(self):
        self.assertEqual(normalize("Цунаде. — Я", {"Цунаде": "Цун+адэ", "— Я": "— -Я"}), "Цун+адэ. — -Я")
        self.assertEqual(normalize("Цунадой", {"Цунада": "Цун+адэ"}), "Цунадой")

    def test_do_not_guess_moving_stress_or_irregular_stems(self):
        self.assertEqual(normalize("Анны Льва", {"Анна": "Анн+а", "Лев": "Л+ев"}), "Анны Льва")

    def test_replacement_once(self):
        self.assertEqual(apply_user_dict("имя", {"имя": "другое", "другое": "третье"}), "другое")

    def test_tracked_form_points_to_original_word(self):
        text = "Письмо Фердинанду пришло."
        tracked = normalize_tracked(text, {"Фердинанд": "Фердин+анд"})
        word = "Фердин+анду"
        start, end = tracked.source_span(tracked.text.index(word), len(word))
        self.assertEqual(text[start:end], "Фердинанду")
        self.assertEqual(tracked.text, normalize(text, {"Фердинанд": "Фердин+анд"}))


if __name__ == "__main__":
    unittest.main()
