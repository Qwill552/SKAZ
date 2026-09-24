"""Упаковка PCM-сэмплов в WAV. Используется и заглушкой, и (в TTS-3) настоящим
бэкендом Silero — там сырые float-сэмплы, здесь синус."""
import array
import io
import math
import wave

SAMPLE_RATE = 48000  # совпадает с sample_rate, которым вызывался apply_tts в TTS-1


def pack_wav(pcm: bytes, sample_rate: int = SAMPLE_RATE, channels: int = 1, sampwidth: int = 2) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(sampwidth)
        w.setframerate(sample_rate)
        w.writeframes(pcm)
    return buf.getvalue()


def sine_pcm(duration_s: float, freq: float = 440.0, sample_rate: int = SAMPLE_RATE,
             amplitude: float = 0.3) -> bytes:
    n = max(1, int(duration_s * sample_rate))
    step = 2 * math.pi * freq / sample_rate
    samples = array.array("h", (int(amplitude * 32767 * math.sin(step * i)) for i in range(n)))
    return samples.tobytes()
