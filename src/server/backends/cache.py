"""LRU-кэш готового синтеза в памяти. Ключ — sha256(voice + text),
значение — пара (байты WAV, тайминги слов): считать раскладку заново для
уже посчитанного звука незачем, а отдать WAV без таймингов нельзя —
подсветка разъедется ровно на повторах. Переживает выгрузку модели
нарочно: это и есть то, что позволяет мгновенно ответить на повтор, не
поднимая модель обратно."""
import hashlib
from collections import OrderedDict

Entry = tuple[bytes, list[dict]]


class WavCache:
    def __init__(self, max_size: int = 50):
        self._max_size = max_size
        self._data: OrderedDict[str, Entry] = OrderedDict()

    @staticmethod
    def key(text: str, voice: str) -> str:
        return hashlib.sha256(f"{voice}\x00{text}".encode("utf-8")).hexdigest()

    def get(self, key: str) -> Entry | None:
        value = self._data.get(key)
        if value is not None:
            self._data.move_to_end(key)
        return value

    def put(self, key: str, value: Entry) -> None:
        self._data[key] = value
        self._data.move_to_end(key)
        if len(self._data) > self._max_size:
            self._data.popitem(last=False)

    def __len__(self) -> int:
        return len(self._data)
