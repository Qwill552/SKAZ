import asyncio
import json
import struct
import uuid

import aiohttp

from ..models import ModelError
from .cache import WavCache
from .timings import flat_timings


UNIPROXY_URL = "wss://uniproxy.alice.yandex.net/uni.ws"
TRANSLATE_KEY = "bf4277fc-06c0-405a-b278-b796bbbd3f27"
VOICE_OPTIONS = {
    "oksana": ("oksana.gpu", "neutral"),
    "jane": ("jane.gpu", "neutral"),
    "omazh": ("omazh.gpu", "neutral"),
    "nastya": ("nastya.gpu", "neutral"),
    "sasha": ("sasha.gpu", "neutral"),
    "tatyana": ("tatyana_abramova.gpu", "good"),
    "ermil": ("ermil.gpu", "neutral"),
    "zahar": ("zahar.gpu", "neutral"),
    "kolya": ("kolya.gpu", "neutral"),
    "kostya": ("kostya.gpu", "neutral"),
    "anton": ("anton_samokhvalov.gpu", "neutral"),
}


def ogg_duration(audio: bytes) -> float:
    position = 0
    last_granule = 0
    while position + 27 <= len(audio):
        if audio[position:position + 4] != b"OggS":
            raise ModelError("Яндекс вернул повреждённый аудиопоток")
        segment_count = audio[position + 26]
        table_end = position + 27 + segment_count
        if table_end > len(audio):
            raise ModelError("Яндекс вернул неполный аудиопоток")
        page_end = table_end + sum(audio[position + 27:table_end])
        if page_end > len(audio):
            raise ModelError("Яндекс вернул неполный аудиопоток")
        granule = struct.unpack_from("<Q", audio, position + 6)[0]
        if granule != 0xFFFFFFFFFFFFFFFF:
            last_granule = granule
        position = page_end
    if position != len(audio):
        raise ModelError("Яндекс вернул неполный аудиопоток")
    return last_granule / 48000


class YandexBackend:
    name = "yandex_tts"
    ready = True
    voices = list(VOICE_OPTIONS)

    def __init__(self, cache_size: int = 50):
        self._cache = WavCache(cache_size)

    async def _synth(self, text: str, voice: str) -> tuple[bytes, list[dict]]:
        identity = str(uuid.uuid4())
        request_id = str(uuid.uuid4())
        audio = bytearray()
        stream_id = None
        timeout = aiohttp.ClientTimeout(total=12)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.ws_connect(UNIPROXY_URL, heartbeat=10) as socket:
                await socket.send_json({"event": {
                    "header": {"namespace": "System", "name": "SynchronizeState",
                               "messageId": str(uuid.uuid4()), "seqNumber": 1},
                    "payload": {"uuid": identity, "auth_token": TRANSLATE_KEY,
                                "vins": {"application": {"platform": "windows", "uuid": identity,
                                                         "app_id": "ru.yandex.translate.desktop"}}}}})
                await socket.send_json({"event": {
                    "header": {"namespace": "tts", "name": "Generate",
                               "messageId": request_id, "seqNumber": 2},
                    "payload": {"text": text, "lang": "ru-RU", "voice": VOICE_OPTIONS[voice][0],
                                "speed": 1, "emotion": VOICE_OPTIONS[voice][1],
                                "format": "audio/ogg;codecs=opus"}}})
                async for message in socket:
                    if message.type == aiohttp.WSMsgType.BINARY:
                        if len(message.data) < 4:
                            raise ModelError("Яндекс вернул повреждённый аудиопоток")
                        if stream_id == struct.unpack_from(">I", message.data)[0]:
                            audio.extend(message.data[4:])
                            if len(audio) > 10_000_000:
                                raise ModelError("Аудиопоток Яндекса слишком большой")
                    elif message.type == aiohttp.WSMsgType.TEXT:
                        packet = json.loads(message.data)
                        directive = packet.get("directive") or {}
                        header = directive.get("header") or {}
                        if header.get("refMessageId") == request_id:
                            if header.get("name") == "EventException":
                                raise ModelError("Яндекс отклонил запрос синтеза")
                            if header.get("name") == "Speak":
                                stream_id = header.get("streamId")
                        control = packet.get("streamcontrol") or {}
                        if stream_id is not None and control.get("streamId") == stream_id:
                            if control.get("action") != 0 or control.get("reason") != 0:
                                raise ModelError("Яндекс прервал синтез")
                            break
                    elif message.type in (aiohttp.WSMsgType.ERROR, aiohttp.WSMsgType.CLOSE,
                                          aiohttp.WSMsgType.CLOSED):
                        break
        duration = ogg_duration(bytes(audio))
        if len(audio) < 512 or duration < 0.2:
            raise ModelError("Яндекс вернул пустой звук")
        return bytes(audio), flat_timings(text, duration)

    def synth(self, text: str, voice: str) -> tuple[bytes, list[dict]]:
        key = self._cache.key(text, voice)
        cached = self._cache.get(key)
        if cached is not None:
            return cached
        try:
            result = asyncio.run(asyncio.wait_for(self._synth(text, voice), timeout=12))
        except (aiohttp.ClientError, asyncio.TimeoutError, OSError, json.JSONDecodeError) as exc:
            raise ModelError(f"Сервис Яндекса недоступен: {exc}") from exc
        self._cache.put(key, result)
        return result
