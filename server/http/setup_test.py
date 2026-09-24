"""Сквозная проверка маршрутов TTS-8: python -m server.http.setup_test."""
import http.client
import json
import tempfile
import threading
import time
from pathlib import Path
from unittest.mock import patch

from server import main
from server.backends.stub import StubBackend
from server.normalize import normalize
from server.normalize.user_dict import UserDictWatcher


def run():
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "user_dict.json"
        main.USER_DICT_PATH = path
        server = main.SkazServer(("127.0.0.1", 0), main.Handler,
                                 {"token": "test-secret", "default_voice": "baya"},
                                 StubBackend(), UserDictWatcher(path))
        port = server.server_address[1]
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()

        def request(method, route, body=None, auth=False, origin=None, host=None):
            conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
            headers = {"Host": host or f"127.0.0.1:{port}"}
            if auth:
                headers["Authorization"] = "Bearer test-secret"
            if origin is not None:
                headers["Origin"] = origin
            if body is not None:
                headers["Content-Type"] = "application/json"
            conn.request(method, route, body=body, headers=headers)
            response = conn.getresponse()
            result = response.status, response.read(), response.getheader("Cache-Control")
            conn.close()
            return result

        try:
            code, html, cache = request("GET", "/setup")
            assert code == 200 and b"test-secret" in html and b"data:image/svg+xml;base64," in html
            assert b'href="/userscript/skaz.user.js"' in html and b"skaz.user.js</strong>" in html
            assert cache == "no-store"
            assert request("GET", "/setup", origin="https://bad.example")[0] == 403
            assert request("GET", "/setup", host="bad.example")[0] == 403
            assert request("GET", "/pair")[0] == 401
            assert request("POST", "/pair/open", origin="https://bad.example")[0] == 403
            assert request("POST", "/pair/open")[0] == 200
            assert request("GET", "/pair", origin="https://bad.example")[0] == 403
            code, body, _ = request("GET", "/pair")
            assert code == 200 and json.loads(body)["token"] == "test-secret"
            assert request("GET", "/pair")[0] == 401
            assert request("POST", "/pair/open")[0] == 200
            server.pair_until = time.monotonic() - 1
            assert request("GET", "/pair")[0] == 401

            assert request("GET", "/dict")[0] == 401
            assert request("PUT", "/dict", b'{}')[0] == 401
            dictionary = {"Цунаде": "Цун+адэ", "— Я": "— -Я"}
            code, body, _ = request("PUT", "/dict", json.dumps(dictionary, ensure_ascii=False).encode(), auth=True)
            assert code == 200 and json.loads(body)["entries"] == dictionary
            assert json.loads(path.read_text(encoding="utf-8")) == dictionary
            assert json.loads(request("GET", "/dict", auth=True)[1])["entries"] == dictionary
            assert "Цун+адэ" in normalize("Цунаде пришла.", server.user_dict.get())
            assert request("PUT", "/dict", b'[]', auth=True)[0] == 400
            assert request("GET", "/health", auth=True)[0] == 200
            assert request("POST", "/update")[0] == 401
            with patch.object(main, "start_update") as update:
                assert request("POST", "/update", auth=True)[0] == 202
                update.assert_called_once_with()
            with patch.object(main, "start_update", side_effect=RuntimeError("failed")):
                assert request("POST", "/update", auth=True)[0] == 503
            code, script, _ = request("GET", "/userscript/skaz.user.js")
            assert code == 200 and script.startswith(b"// ==UserScript==")
            print("TTS-8 HTTP: setup, origin, pair, expiry, dict, health, userscript — OK")
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)


if __name__ == "__main__":
    run()
