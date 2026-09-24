"""Бэкенд Silero: диспетчер, который сам ничего не грузит. Синтез идёт в
дочернем процессе (worker.py), запущенном лениво на первый /tts и убитом
по таймеру простоя. См. journal TTS-3 2026-09-21: попытка "выгрузки"
простым обнулением ссылки на модель внутри одного процесса не возвращает
память ОС (torch-аллокатор Windows-кучи её не отдаёт) — private-память
стабилизировалась на ~1.8 ГБ вместо базовых ~30 МБ. Смерть процесса
возвращает всё, поэтому выгрузка теперь — это `Popen.kill()`, не `del`.

`self._lock` защищает переход unloaded/loading/loaded и сериализует доступ
к трубам подпроцесса между обработчиком запроса (main.py, один поток) и
фоновым таймером выгрузки (тоже main.py, отдельный поток)."""
import json
import struct
import subprocess
import sys
import threading
import time
from pathlib import Path

from .. import wavutil
from ..models import ModelError
from . import worker_proto
from .cache import WavCache


class SileroBackend:
    def __init__(self, root: Path, model_key: str, entry: dict, *,
                 idle_unload_minutes: int = 10, cache_size: int = 50):
        self.name = f"silero:{model_key}"
        self.voices = entry["voices"]
        self.ready = True

        self._root = root
        self._model_key = model_key
        self._sample_rate = entry["sample_rate"]

        self._lock = threading.Lock()
        self._proc: subprocess.Popen | None = None
        self._last_used = time.monotonic()
        self._idle_seconds = idle_unload_minutes * 60

        self._cache = WavCache(cache_size)

    @property
    def model_loaded(self) -> bool:
        with self._lock:
            return self._alive_locked()

    def synth(self, text: str, voice: str) -> tuple[bytes, list[dict]]:
        """(WAV, тайминги слов). Тайминги считает воркер вместе с синтезом —
        у него уже есть сырые сэмплы и numpy (TTS-7A). Смещения в них — по
        тому тексту, который сюда передали, то есть по нормализованному;
        переводит их в исходный текст страницы main.py, который один и
        знает про нормализацию."""
        cache_key = self._cache.key(text, voice)
        cached = self._cache.get(cache_key)
        if cached is not None:
            return cached

        with self._lock:
            if not self._alive_locked():
                self._spawn_locked()
            self._last_used = time.monotonic()
            words, pcm = self._request_locked(text, voice)

        wav_bytes = wavutil.pack_wav(pcm, sample_rate=self._sample_rate)
        self._cache.put(cache_key, (wav_bytes, words))
        return wav_bytes, words

    def maybe_unload(self) -> bool:
        """Вызывается периодически фоновым таймером в main.py. Возвращает
        True, если действительно убила процесс (для лога)."""
        with self._lock:
            if not self._alive_locked():
                return False
            if time.monotonic() - self._last_used < self._idle_seconds:
                return False
            self._kill_locked()
            return True

    def close(self) -> None:
        """Вызывается при остановке сервера — не оставлять осиротевший процесс."""
        with self._lock:
            self._kill_locked()

    def _alive_locked(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def _spawn_locked(self) -> None:
        self._proc = subprocess.Popen(
            [sys.executable, "-u", "-m", "server.backends.worker", self._model_key, str(self._root)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            cwd=str(self._root),
        )
        print(f"[silero] подпроцесс воркера запущен (pid={self._proc.pid})")

    def _kill_locked(self) -> None:
        if self._proc is None:
            return
        proc, self._proc = self._proc, None
        proc.kill()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            pass  # уже kill(), дальше ждать нечего — процесс не наш больше

    def _request_locked(self, text: str, voice: str) -> tuple[list[dict], bytes]:
        proc = self._proc
        request = json.dumps({"text": text, "voice": voice}).encode("utf-8")
        try:
            worker_proto.send_frame(proc.stdin, request)
            frame = worker_proto.recv_frame(proc.stdout)
        except (BrokenPipeError, ConnectionError, OSError) as e:
            self._kill_locked()
            raise ModelError(f"Подпроцесс синтеза оборвал связь: {e}") from e

        if frame is None:
            self._kill_locked()
            raise ModelError("Подпроцесс синтеза завершился без ответа — см. лог сервера (stderr воркера)")

        status, payload = frame[0], frame[1:]
        if status == 0:
            message = json.loads(payload.decode("utf-8"))["error"]
            raise ModelError(message)
        # Успех: 4 байта длины JSON с таймингами, JSON, дальше PCM.
        (meta_len,) = struct.unpack(">I", payload[:4])
        meta = json.loads(payload[4:4 + meta_len].decode("utf-8"))
        return meta["words"], payload[4 + meta_len:]
