"""Общая рамка кадров для протокола родитель↔воркер: 4-байтовая big-endian
длина, потом тело. И запрос (JSON), и ответ (1 байт статуса + тело) едут
через один и тот же примитив — бинарные потоки, никакого текстового
разделителя, который могла бы сломать кириллица или перевод строки внутри
текста."""
import struct


def send_frame(stream, data: bytes) -> None:
    stream.write(struct.pack(">I", len(data)))
    stream.write(data)
    stream.flush()


def recv_frame(stream):
    """None — поток закрыт штатно (EOF на границе кадра). Обрыв внутри кадра
    считается ошибкой протокола (воркер упал не вовремя)."""
    length_bytes = stream.read(4)
    if not length_bytes:
        return None
    if len(length_bytes) < 4:
        length_bytes += _read_exact(stream, 4 - len(length_bytes))
    (length,) = struct.unpack(">I", length_bytes)
    return _read_exact(stream, length)


def _read_exact(stream, n: int) -> bytes:
    buf = bytearray()
    while len(buf) < n:
        chunk = stream.read(n - len(buf))
        if not chunk:
            raise ConnectionError("неожиданный обрыв потока с воркером")
        buf.extend(chunk)
    return bytes(buf)
