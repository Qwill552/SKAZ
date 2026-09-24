"""Запуск сервера: конфиг, выбор порта, HTTP-роутинг на /health и /tts.

Синтез в /tts блокирующий и однопоточный нарочно: пока сервер занят одним
запросом, второй ждёт — реальные чанки (TTS-6) короткие, и это не проблема,
а огромный текст (баг чанкинга) должен встать в очередь, а не срываться
параллельно на нескольких потоках сразу.
"""
import base64
import json
import os
import secrets
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

from .auth import check_auth
from .http.setup import local_page_request, open_pair, parse_dict, render_setup, save_dict, take_pair, userscript_path, MAX_DICT_BYTES
from .backends.silero import SileroBackend
from .backends.stub import StubBackend
from .models import ModelError, load_catalog
from .normalize import normalize_tracked
from .normalize.spans import Tracked
from .normalize.user_dict import UserDictWatcher
from .version import VERSION
from .update import start_update

ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = Path(os.environ.get("SKAZ_CONFIG_DIR") or ROOT)
CONFIG_PATH = CONFIG_DIR / "config.json"
USER_DICT_PATH = CONFIG_DIR / "user_dict.json"
PORT_RANGE = range(8756, 8761)
DEFAULT_VOICE = "baya"
DEFAULT_BACKEND = "silero"
DEFAULT_MODEL = "silero_v5_ru"
UNLOAD_CHECK_SECONDS = 60

# Предохранитель на /tts. Не 5000 (как в исходном ТЗ TTS-2) — по замерам TTS-1
# реальный потолок apply_tts у v5_ru лежит между 900 и 1000 знаками, и падает
# он не всегда мгновенно: около 5000 знаков модель не отказывает сразу, а
# перемалывает вход почти 5 минут. 800 — потолок минус запас на то, что лимит
# считается в знаках уже после акцентуации, а не во входных. См. skaz.md,
# таблицу решений, правка 2026-09-21.
MAX_TEXT_LENGTH = 800

# Тайминги слов едут заголовком, а не multipart-телом (развилка была
# оставлена на месте в skaz/07a-word-highlight.md, §1). Причина простая:
# GM_xmlhttpRequest с responseType:'arraybuffer' отдаёт тело одним
# буфером, и multipart пришлось бы разбирать вручную, байт за байтом,
# на стороне юзерскрипта. Заголовок читается одной строкой, а размер
# смешной: предложение — это меньше килобайта base64.
TIMINGS_HEADER = "X-Skaz-Timings"


def load_or_create_config() -> dict:
    if CONFIG_PATH.exists():
        return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    config = {
        "port": PORT_RANGE.start,
        "token": secrets.token_urlsafe(32),
        "backend": DEFAULT_BACKEND,
        "model": DEFAULT_MODEL,
        "default_voice": DEFAULT_VOICE,
        "idle_unload_minutes": 10,
        "cache_size": 50,
    }
    save_config(config)
    return config


def build_backend(config: dict):
    """stub — для отладки юзерскрипта без модели, доступен через конфиг.
    silero — модель и голос по умолчанию, переключается ключом "model"."""
    backend_name = config.get("backend", DEFAULT_BACKEND)
    if backend_name == "stub":
        return StubBackend()
    if backend_name == "silero":
        model_key = config.get("model", DEFAULT_MODEL)
        catalog = load_catalog(ROOT)
        if model_key not in catalog:
            raise SystemExit(f"Неизвестная модель '{model_key}' в config.json, есть: {', '.join(catalog)}")
        return SileroBackend(
            ROOT, model_key, catalog[model_key],
            idle_unload_minutes=config.get("idle_unload_minutes", 10),
            cache_size=config.get("cache_size", 50),
        )
    raise SystemExit(f"Неизвестный бэкенд '{backend_name}' в config.json (ожидался 'silero' или 'stub').")


def source_timings(words: list[dict], tracked: Tracked) -> list[list]:
    """Перевести тайминги из координат синтеза в координаты исходного
    текста и сжать формат до [начало, конец, смещение, длина].

    Зачем перевод. Подсветка рисуется по живому DOM, то есть по тому
    тексту, который человек видит, а синтез шёл по нормализованному:
    «1867 г.» (7 знаков) звучит как «тысяча восемьсот шестьдесят седьмом
    году» (40). Обратный след ведёт `Tracked` (normalize/spans.py).

    Слова, пришедшие из одного и того же куска исходного текста, здесь же
    склеиваются в одну запись: подсвечивать «1867 г.» пять раз подряд
    незачем — подсветка просто держится на нём, пока оно звучит."""
    out: list[list] = []
    for w in words:
        start, end = tracked.source_span(w["off"], w["n"])
        if end <= start:
            continue
        if out and start < out[-1][3]:
            out[-1][1] = w["e"]
            out[-1][3] = max(out[-1][3], end)
            continue
        out.append([w["s"], w["e"], start, end])
    return [[s, e, a, b - a] for s, e, a, b in out]


def unload_timer(backend, stop_event: threading.Event) -> None:
    while not stop_event.wait(UNLOAD_CHECK_SECONDS):
        maybe_unload = getattr(backend, "maybe_unload", None)
        if maybe_unload and maybe_unload():
            print(f"{time.strftime('%H:%M:%S')}  модель выгружена после простоя")


def save_config(config: dict) -> None:
    # The controller can be terminated while a server is starting. Never truncate
    # the user's token/config in place; publish the complete file atomically.
    temporary = CONFIG_PATH.with_name(f"{CONFIG_PATH.name}.{os.getpid()}.tmp")
    try:
        temporary.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(CONFIG_PATH)
    finally:
        temporary.unlink(missing_ok=True)


class SkazServer(HTTPServer):
    # По умолчанию True (унаследовано от socketserver.TCPServer). На Windows
    # SO_REUSEADDR — не то же самое, что на Linux: он позволяет второму
    # процессу забиндиться на уже занятый порт, а не только переиспользовать
    # TIME_WAIT. С этим включённым второй экземпляр молча слушает тот же
    # порт, что и первый, вместо перехода на следующий. Выключено нарочно.
    allow_reuse_address = False

    # По умолчанию 5 (socketserver.TCPServer). Сервер однопоточный, и холодная
    # загрузка модели блокирует accept() на ~10с — замерено (TTS-3, десять
    # параллельных curl на холодном сервере): при бэклоге 5 ОС молча рвёт
    # соединения сверх очереди, 4 из 10 запросов не доходят до сервера вообще.
    request_queue_size = 16

    def __init__(self, address, handler_cls, config: dict, backend, user_dict: UserDictWatcher):
        self.config = config
        self.backend = backend
        self.user_dict = user_dict
        self.pair_until = 0.0
        super().__init__(address, handler_cls)


class Handler(BaseHTTPRequestHandler):
    server_version = f"skaz/{VERSION}"

    def log_message(self, format, *args):  # свой формат лога ниже, без тела запроса
        pass

    def _send_json(self, code: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _send_wav(self, code: int, wav_bytes: bytes, timings: list | None = None) -> None:
        self.send_response(code)
        self.send_header("Content-Type", "audio/wav")
        self.send_header("Content-Length", str(len(wav_bytes)))
        if timings:
            payload = json.dumps({"w": timings}, ensure_ascii=False, separators=(",", ":"))
            self.send_header(TIMINGS_HEADER, base64.b64encode(payload.encode("utf-8")).decode("ascii"))
        self.end_headers()
        self.wfile.write(wav_bytes)

    def _authorized(self) -> bool:
        return check_auth(self.headers.get("Authorization"), self.server.config["token"])

    def _send_bytes(self, code: int, body: bytes, content_type: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.end_headers()
        self.wfile.write(body)

    def _log(self, code: int, start: float) -> None:
        duration_ms = (time.perf_counter() - start) * 1000
        print(f"{time.strftime('%H:%M:%S')}  {self.command:<4}  {self.path:<10}  {code}  {duration_ms:6.1f}ms")

    def do_GET(self):
        start = time.perf_counter()
        if self.path in ("/userscript/skaz.user.js", "/skaz.user.js"):
            # Public code, unlike /setup's token. Tampermonkey can fetch it with
            # an extension Origin; applying the pairing Origin check rejects it.
            if self.headers.get("Host") != f"127.0.0.1:{self.server.server_address[1]}":
                self._send_json(403, {"error": "bad_host"})
                self._log(403, start)
                return
            try:
                body = userscript_path(ROOT).read_bytes()
            except OSError:
                self._send_json(404, {"error": "userscript_not_found"})
                self._log(404, start)
                return
            self._send_bytes(200, body, "text/javascript; charset=utf-8")
            self._log(200, start)
            return
        if self.path == "/setup":
            if not local_page_request(self):
                self._send_json(403, {"error": "bad_origin"})
                self._log(403, start)
                return
            body = render_setup(self.server.config["token"])
            self._send_bytes(200, body, "text/html; charset=utf-8")
            self._log(200, start)
            return
        if self.path == "/pair":
            if not local_page_request(self):
                self._send_json(403, {"error": "bad_origin"})
                self._log(403, start)
                return
            token = take_pair(self.server)
            print(f"{time.strftime('%H:%M:%S')}  связывание: {'ключ выдан' if token else 'окно закрыто'}")
            self._send_json(200 if token else 401, {"token": token} if token else {"error": "pair_closed"})
            self._log(200 if token else 401, start)
            return
        if self.path == "/dict":
            if not self._authorized():
                self._send_json(401, {"error": "bad_token"})
                self._log(401, start)
                return
            self._send_json(200, {"entries": self.server.user_dict.get()})
            self._log(200, start)
            return
        if self.path != "/health":
            self._send_json(404, {"error": "not_found"})
            self._log(404, start)
            return
        if not self._authorized():
            self._send_json(401, {"error": "bad_token"})
            self._log(401, start)
            return
        backend = self.server.backend
        self._send_json(200, {
            "ok": True,
            "version": VERSION,
            "protocol_version": 1,
            "backend": backend.name,
            "voices": backend.voices,
            "model_loaded": getattr(backend, "model_loaded", False),
        })
        self._log(200, start)

    def do_POST(self):
        start = time.perf_counter()
        if self.path == "/pair/open":
            if not local_page_request(self):
                self._send_json(403, {"error": "bad_origin"})
                self._log(403, start)
                return
            open_pair(self.server)
            self._send_json(200, {"expires_in": 60})
            self._log(200, start)
            return
        if self.path == "/update":
            if not self._authorized():
                self._send_json(401, {"error": "bad_token"})
                self._log(401, start)
                return
            try:
                start_update()
            except (OSError, RuntimeError) as exc:
                self._send_json(503, {"error": "update_failed", "message": str(exc)})
                self._log(503, start)
                return
            self._send_json(202, {"ok": True})
            self._log(202, start)
            return
        if self.path != "/tts":
            self._send_json(404, {"error": "not_found"})
            self._log(404, start)
            return
        if not self._authorized():
            self._send_json(401, {"error": "bad_token"})
            self._log(401, start)
            return

        length = int(self.headers.get("Content-Length", 0) or 0)
        raw = self.rfile.read(length) if length else b""
        try:
            data = json.loads(raw.decode("utf-8")) if raw else {}
        except (json.JSONDecodeError, UnicodeDecodeError):
            self._send_json(400, {"error": "bad_request"})
            self._log(400, start)
            return

        text = str(data.get("text") or "").strip()
        voice = data.get("voice") or self.server.config["default_voice"]
        backend = self.server.backend

        if not text:
            self._send_json(400, {"error": "empty_text"})
            self._log(400, start)
            return

        # Нормализация до проверки длины, не после: числа и сокращения
        # (TTS-4) раздувают текст ("1867" → 33 знака), и лимит защищает
        # реальный потолок модели, а не то, сколько знаков ввёл человек
        # (см. skaz.md, "Лимит длины текста").
        # tracked, а не просто строка: рядом с нормализованным текстом
        # нужен след «символ → кусок исходного», иначе тайминги слов
        # (TTS-7A) некуда положить на странице. См. normalize/spans.py.
        tracked = normalize_tracked(text, self.server.user_dict.get())
        normalized = tracked.text

        if len(normalized) > MAX_TEXT_LENGTH:
            self._send_json(413, {"error": "too_long", "limit": MAX_TEXT_LENGTH})
            self._log(413, start)
            return
        if voice not in backend.voices:
            self._send_json(422, {"error": "bad_voice", "voices": backend.voices})
            self._log(422, start)
            return
        if not backend.ready:
            self._send_json(503, {"error": "backend_unavailable"})
            self._log(503, start)
            return

        try:
            wav_bytes, words = backend.synth(normalized, voice)
        except ModelError as e:
            self._send_json(500, {"error": "model_error", "message": str(e)})
            self._log(500, start)
            return
        self._send_wav(200, wav_bytes, source_timings(words, tracked))
        self._log(200, start)

    def do_PUT(self):
        start = time.perf_counter()
        if self.path != "/dict":
            self._send_json(404, {"error": "not_found"})
            self._log(404, start)
            return
        if not self._authorized():
            self._send_json(401, {"error": "bad_token"})
            self._log(401, start)
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length < 0 or length > MAX_DICT_BYTES:
                raise ValueError("dictionary_too_large")
            entries = parse_dict(self.rfile.read(length))
        except ValueError as e:
            self._send_json(400, {"error": str(e)})
            self._log(400, start)
            return
        save_dict(USER_DICT_PATH, entries)
        self.server.user_dict.get()
        self._send_json(200, {"entries": entries})
        self._log(200, start)


def bind_server(config: dict, backend, user_dict: UserDictWatcher) -> SkazServer:
    last_error: OSError | None = None
    for port in PORT_RANGE:
        try:
            return SkazServer(("127.0.0.1", port), Handler, config, backend, user_dict)
        except OSError as e:
            last_error = e
            continue
    raise SystemExit(
        f"Все порты {PORT_RANGE.start}-{PORT_RANGE.stop - 1} заняты, сервер не запущен ({last_error})."
    )


def main() -> None:
    # line_buffering — видно сразу и в перенаправленном выводе; utf-8 — иначе на
    # Windows с системной кодовой страницей (cp1251/cp866) токен и подсказки
    # в консоли превращаются в кракозябры
    sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)
    managed = len(sys.argv) == 3 and sys.argv[1] == "--managed"
    if managed and sys.stdin.readline().strip() != "start":
        return  # controller died before assigning our Windows Job
    config = load_or_create_config()
    try:
        backend = build_backend(config)
    except ModelError as e:
        raise SystemExit(str(e))
    user_dict = UserDictWatcher(USER_DICT_PATH)
    server = bind_server(config, backend, user_dict)
    config["port"] = server.server_address[1]
    save_config(config)

    print(f"SKAZ сервер: http://127.0.0.1:{config['port']}  (бэкенд: {backend.name})")
    print(f"Голоса: {', '.join(backend.voices)}")
    print()
    if not managed:
        print(f"Токен: {config['token']}")
    print(f"Связать браузер: http://127.0.0.1:{config['port']}/setup")
    print()

    stop_event = threading.Event()
    timer_thread = threading.Thread(target=unload_timer, args=(backend, stop_event), daemon=True)
    timer_thread.start()

    if managed:
        # Readiness is independent of HTTP: /tts intentionally blocks that loop.
        ready = ROOT / ".runtime/server-ready.json"
        temp = ready.with_suffix(".tmp")
        temp.write_text(json.dumps({"pid": os.getpid(), "port": config["port"],
                                    "nonce": sys.argv[2]}), encoding="utf-8")
        temp.replace(ready)

        def control():
            sys.stdin.readline()  # stop command or EOF when the controller exits
            server.shutdown()

        threading.Thread(target=control, daemon=True).start()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nОстановлено.")
    finally:
        stop_event.set()
        close = getattr(backend, "close", None)
        if close:
            close()
        server.server_close()


if __name__ == "__main__":
    main()
