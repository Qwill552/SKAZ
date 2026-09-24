import unittest

from server.normalize import normalize, normalize_tracked


class UnicodeStressTests(unittest.TestCase):
    def test_combining_acute_becomes_model_stress(self):
        cases = {
            "за́мок": "з+амок",
            "замо́к": "зам+ок",
            "Мо́ре, го́ры.": "М+оре, г+оры.",
            "О́н и ё́лка": "+Он и +ёлка",
            "з+а́мок": "з+амок",
            "за́мок": "з+амок",
            "ё́лка": "+ёлка",
            "е́̈лка": "+ёлка",
            "ёлка": "ёлка",
            "замок": "замок",
        }
        for original, expected in cases.items():
            with self.subTest(original=original):
                self.assertEqual(normalize(original), expected)

    def test_highlight_span_includes_accented_source(self):
        original = "Ста́рый за́мок."
        tracked = normalize_tracked(original)
        word = "з+амок"
        start, end = tracked.source_span(tracked.text.index(word), len(word))
        self.assertEqual(original[start:end], "за́мок")


if __name__ == "__main__":
    unittest.main()
