import http.client
import json
import tempfile
import threading
import unittest
from pathlib import Path

from . import main
from .backends.stub import StubBackend
from .models import ModelError
from .normalize.user_dict import UserDictWatcher
from .normalize.spans import Tracked


class AlternateStub(StubBackend):
    name = "silero:silero_v5_cis_base"
    voices = ["ru_dmitriy"]


class EdgeStub:
    name = "edge_tts"
    ready = True
    voices = ["ru-RU-SvetlanaNeural"]
    fail = False

    def synth(self, text, voice):
        if self.fail:
            raise ModelError("offline")
        return b"ID3edge", [{"s": 0.0, "e": 0.3, "off": 0, "n": 6}]


class YandexStub:
    name = "yandex_tts"
    ready = True
    voices = ["jane"]
    fail = False

    def synth(self, text, voice):
        if self.fail:
            raise ModelError("empty audio")
        return b"OggSyandex", [{"s": 0.0, "e": 0.3, "off": 0, "n": 6}]


class MultiModelTest(unittest.TestCase):
    def test_edge_text_keeps_source_offsets(self):
        tracked = main.edge_text(Tracked("Прив+ет"))
        self.assertEqual(tracked.text, "Привет")
        self.assertEqual(tracked.source_span(4, 2), (5, 7))

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        path = Path(self.directory.name) / "user_dict.json"
        self.edge = EdgeStub()
        self.yandex = YandexStub()
        backends = {"silero_v5_ru": StubBackend(),
                    "silero_v5_cis_base": AlternateStub(), "edge_tts": self.edge,
                    "yandex_tts": self.yandex}
        config = {"token": "secret", "model": "silero_v5_ru", "default_voice": "baya"}
        self.server = main.SkazServer(("127.0.0.1", 0), main.Handler, config,
                                      backends, UserDictWatcher(path))
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.directory.cleanup()

    def request(self, method, path, data=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.server.server_address[1])
        body = json.dumps(data).encode() if data is not None else None
        connection.request(method, path, body, {"Authorization": "Bearer secret",
                                                "Content-Type": "application/json"})
        response = connection.getresponse()
        result = response.status, dict(response.getheaders()), response.read()
        connection.close()
        return result

    def test_health_and_model_routing(self):
        status, _, body = self.request("GET", "/health")
        self.assertEqual(status, 200)
        self.assertEqual(list(json.loads(body)["models"]),
                         ["silero_v5_ru", "silero_v5_cis_base", "edge_tts", "yandex_tts"])
        status, headers, body = self.request("POST", "/tts", {
            "text": "Привет", "model": "edge_tts", "voice": "ru-RU-SvetlanaNeural"})
        self.assertEqual(status, 200)
        self.assertEqual(headers["Content-Type"], "audio/mpeg")
        self.assertEqual(body, b"ID3edge")
        status, headers, body = self.request("POST", "/tts", {
            "text": "Привет", "model": "silero_v5_cis_base", "voice": "ru_dmitriy"})
        self.assertEqual(status, 200)
        self.assertEqual(headers["Content-Type"], "audio/wav")
        self.assertTrue(body.startswith(b"RIFF"))

        status, headers, body = self.request("POST", "/tts", {
            "text": "Привет", "model": "yandex_tts", "voice": "jane"})
        self.assertEqual(status, 200)
        self.assertEqual(headers["Content-Type"], "audio/ogg")
        self.assertEqual(body, b"OggSyandex")

    def test_edge_failure_falls_back_to_silero(self):
        self.edge.fail = True
        status, headers, body = self.request("POST", "/tts", {
            "text": "Привет", "model": "edge_tts", "voice": "ru-RU-SvetlanaNeural"})
        self.assertEqual(status, 200)
        self.assertEqual(headers["X-Skaz-Fallback"], "silero")
        self.assertTrue(body.startswith(b"RIFF"))

    def test_yandex_failure_falls_back_to_silero(self):
        self.yandex.fail = True
        status, headers, body = self.request("POST", "/tts", {
            "text": "Привет", "model": "yandex_tts", "voice": "jane"})
        self.assertEqual(status, 200)
        self.assertEqual(headers["X-Skaz-Fallback"], "silero")
        self.assertEqual(headers["Content-Type"], "audio/wav")
        self.assertTrue(body.startswith(b"RIFF"))


if __name__ == "__main__":
    unittest.main()
