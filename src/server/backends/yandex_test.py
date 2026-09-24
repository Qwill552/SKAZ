import struct
import unittest

from ..models import ModelError
from .yandex import ogg_duration


def ogg_page(granule: int, payload: bytes) -> bytes:
    header = bytearray(28)
    header[:4] = b"OggS"
    struct.pack_into("<Q", header, 6, granule)
    header[26] = 1
    header[27] = len(payload)
    return bytes(header) + payload


class OggDurationTest(unittest.TestCase):
    def test_final_page_sets_duration(self):
        audio = ogg_page(0, b"head") + ogg_page(48_000, b"data")
        self.assertEqual(ogg_duration(audio), 1.0)

    def test_truncated_page_is_rejected(self):
        with self.assertRaises(ModelError):
            ogg_duration(ogg_page(48_000, b"data")[:-1])


if __name__ == "__main__":
    unittest.main()
