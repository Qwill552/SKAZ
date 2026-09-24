import unittest

from .edge import align_words


class EdgeAlignmentTest(unittest.TestCase):
    def test_offsets_follow_normalized_text_with_repeated_words(self):
        text = "Привет, привет — сорок два."
        boundaries = [
            {"text": "Привет", "offset": 0, "duration": 3_000_000},
            {"text": "привет", "offset": 4_000_000, "duration": 3_000_000},
            {"text": "сорок", "offset": 8_000_000, "duration": 3_000_000},
            {"text": "два", "offset": 12_000_000, "duration": 2_000_000},
        ]
        words = align_words(text, boundaries)
        self.assertEqual([word['off'] for word in words], [0, 8, 17, 23])
        self.assertEqual(words[-1]['s'], 1.2)


if __name__ == '__main__':
    unittest.main()
