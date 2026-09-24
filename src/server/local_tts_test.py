import base64
import http.client
import json
import tempfile
import threading
import unittest
from pathlib import Path

from . import main
from .backends.stub import StubBackend
from .models import ModelError
from .normalize import normalize_tracked
from .normalize.local import local_text
from .normalize.user_dict import UserDictWatcher


class RecordingLocal(StubBackend):
    def __init__(self):
        self.texts = []

    def synth(self, text, voice):
        self.texts.append(text)
        return super().synth(text, voice)


class FailingOnline:
    name = "edge_tts"
    ready = True
    voices = ["online"]

    def synth(self, text, voice):
        raise ModelError("offline")


class LocalTextTests(unittest.TestCase):
    def test_local_words_and_source_positions(self):
        original = "— А герцогская чета — необходимый шаг."
        tracked = local_text(normalize_tracked(original))
        self.assertEqual(tracked.text, "А герцогская чет+а — необходимый шаг.")
        self.assertEqual(tracked.source_span(0, 1), (2, 3))
        position = tracked.text.index("чет+а")
        self.assertEqual(original[slice(*tracked.source_span(position, 5))], "чета")

    def test_explicit_user_replacements_win(self):
        self.assertEqual(local_text(normalize_tracked("Герцогская чета.", {"чета": "чёта"})).text,
                         "Герцогская чёта.")
        self.assertEqual(local_text(normalize_tracked("Герцогская чета.", {"чета": "ч+ета"})).text,
                         "Герцогская ч+ета.")

    def test_contextual_vse_keeps_other_readings(self):
        original = ("Новостей оказалось действительно много, так что все прекрасно понимали, "
                    "что Эренфест сильно изменится.")
        tracked = local_text(normalize_tracked(original))
        self.assertIn("так что вс+е прекрасно понимали", tracked.text)
        position = tracked.text.index("вс+е")
        self.assertEqual(original[slice(*tracked.source_span(position, 4))], "все")
        self.assertEqual(local_text(normalize_tracked("Все закончилось.")).text, "Все закончилось.")
        self.assertEqual(local_text(normalize_tracked("Они все прекрасно понимали.")).text,
                         "Они все прекрасно понимали.")

    def test_local_request_and_online_fallback(self):
        with tempfile.TemporaryDirectory() as directory:
            local = RecordingLocal()
            server = main.SkazServer(
                ("127.0.0.1", 0), main.Handler,
                {"token": "secret", "model": "silero_v5_ru", "default_voice": "baya"},
                {"silero_v5_ru": local, "edge_tts": FailingOnline()},
                UserDictWatcher(Path(directory) / "user_dict.json"),
            )
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                for model, voice in (("silero_v5_ru", "baya"), ("edge_tts", "online")):
                    connection = http.client.HTTPConnection("127.0.0.1", server.server_address[1])
                    payload = json.dumps({"text": "— А герцогская чета.", "model": model, "voice": voice})
                    connection.request("POST", "/tts", payload, {
                        "Authorization": "Bearer secret", "Content-Type": "application/json"})
                    response = connection.getresponse()
                    self.assertEqual(response.status, 200)
                    self.assertTrue(response.read().startswith(b"RIFF"))
                    words = json.loads(base64.b64decode(response.getheader("X-Skaz-Timings")))["w"]
                    self.assertEqual(words[0][2], 2)
                    connection.close()
                self.assertEqual(local.texts, ["А герцогская чет+а."] * 2)
            finally:
                server.shutdown()
                server.server_close()
                thread.join()


if __name__ == "__main__":
    unittest.main()
