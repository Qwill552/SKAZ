import asyncio

from ..models import ModelError
from .cache import WavCache


DEFAULT_VOICES = ["ru-RU-SvetlanaNeural", "ru-RU-DmitryNeural"]


def align_words(text: str, boundaries: list[dict]) -> list[dict]:
    words = []
    position = 0
    for boundary in boundaries:
        spoken = boundary["text"].strip()
        if not spoken:
            continue
        offset = text.find(spoken, position)
        if offset < 0:
            offset = text.casefold().find(spoken.casefold(), position)
        if offset < 0:
            continue
        position = offset + len(spoken)
        start = boundary["offset"] / 10_000_000
        words.append({"s": start, "e": start + boundary["duration"] / 10_000_000,
                      "off": offset, "n": len(spoken)})
    return words


class EdgeBackend:
    name = "edge_tts"
    ready = True

    def __init__(self, cache_size: int = 50):
        self._voices = None
        self._cache = WavCache(cache_size)

    @property
    def voices(self) -> list[str]:
        if self._voices is None:
            try:
                import edge_tts
                items = asyncio.run(asyncio.wait_for(edge_tts.list_voices(), timeout=3))
                names = [item["ShortName"] for item in items if item.get("Locale") == "ru-RU"]
                self._voices = names or DEFAULT_VOICES.copy()
            except Exception:
                self._voices = DEFAULT_VOICES.copy()
        return self._voices

    async def _synth(self, text: str, voice: str) -> tuple[bytes, list[dict]]:
        import edge_tts
        speech = edge_tts.Communicate(text, voice, boundary="WordBoundary",
                                      connect_timeout=4, receive_timeout=8)
        audio = bytearray()
        boundaries = []
        async for part in speech.stream():
            if part["type"] == "audio":
                audio.extend(part["data"])
            elif part["type"] == "WordBoundary":
                boundaries.append(part)
        if not audio:
            raise ModelError("Сервис Microsoft не вернул звук")
        return bytes(audio), align_words(text, boundaries)

    def synth(self, text: str, voice: str) -> tuple[bytes, list[dict]]:
        key = self._cache.key(text, voice)
        cached = self._cache.get(key)
        if cached is not None:
            return cached
        try:
            result = asyncio.run(asyncio.wait_for(self._synth(text, voice), timeout=10))
        except Exception as exc:
            raise ModelError(f"edge-tts недоступен: {exc}") from exc
        self._cache.put(key, result)
        return result
