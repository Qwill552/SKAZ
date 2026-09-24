"""Заглушка вместо Silero: синус, длительность растёт с длиной текста. Голоса —
те же пять имён, что будут у настоящего бэкенда v5_ru (TTS-3), чтобы проверка
voice в /tts не переписывалась при подключении реального синтеза."""
from .. import wavutil
from . import timings

VOICES = ["aidar", "baya", "kseniya", "eugene", "xenia"]
SECONDS_PER_CHAR = 0.06  # грубо соответствует темпу речи, ~15 знаков в секунду


class StubBackend:
    name = "stub"
    voices = VOICES
    ready = True

    def synth(self, text: str, voice: str) -> tuple[bytes, list[dict]]:
        duration = max(0.2, len(text) * SECONDS_PER_CHAR)
        pcm = wavutil.sine_pcm(duration)
        # В синусе пауз нет, искать их нечем — чистая слоговая раскладка.
        # Для отладки юзерскрипта этого хватает: подсветка едет, а совпадает
        # ли она со звуком, на синусе всё равно не проверить.
        return wavutil.pack_wav(pcm), timings.flat_timings(text, duration)
