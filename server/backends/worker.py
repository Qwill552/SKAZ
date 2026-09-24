"""Подпроцесс синтеза. Запускается родителем (silero.py) лениво на первый
/tts и убивается им же по таймеру простоя — не обнуляется ссылка, а именно
kill() процесса. Так torch и веса модели освобождаются ОС целиком: замеры
2026-09-21 показали, что gc.collect() внутри одного процесса не возвращает
эту память системе (private-память стабилизировалась на ~1.8 ГБ вместо
базовых ~30 МБ), а завершение процесса — возвращает всегда.

Протокол — see worker_proto.py. На stdin приходит JSON {"text", "voice"},
на stdout уходит один байт статуса. 1 — успех: дальше 4 байта длины JSON
с таймингами, сам JSON и сырой PCM int16 моно. 0 — ошибка: тело JSON
{"error": "..."}.

Тайминги считаются здесь, а не в диспетчере (хотя файл шага TTS-7A
предполагал `silero.py`), по единственной причине: поиск пауз — это RMS
по сэмплам, то есть numpy, а диспетчер обязан оставаться пустым. Он и так
держит ~15 МБ ровно потому, что не импортирует ни torch, ни numpy; тащить
туда numpy ради 10 мс арифметики — разменять цель TTS-3 на удобство.
Здесь numpy уже импортирован ради конвертации в int16.

Критично: stdout — бинарный канал протокола, и его нельзя пачкать текстом.
Поэтому sys.stdout переопределён на stderr в первую очередь, до всех прочих
импортов (models.py печатает прогресс скачивания через print) — настоящий
файловый объект стандартного вывода сохранён отдельно и используется только
для кадров."""
import json
import struct
import sys
from pathlib import Path

_raw_stdout = sys.stdout.buffer
sys.stderr.reconfigure(encoding="utf-8", line_buffering=True)  # иначе кириллица в логе — кракозябры (см. TTS-2)
sys.stdout = sys.stderr  # см. пояснение выше: любой чужой print() уходит в лог, не в протокол

from . import timings, worker_proto  # noqa: E402  (после переброски stdout, до этого места ничего не печатает)
from ..models import ensure_model, load_catalog  # noqa: E402


def main() -> None:
    model_key = sys.argv[1]
    root = Path(sys.argv[2])

    catalog = load_catalog(root)
    entry = catalog[model_key]
    sample_rate = entry["sample_rate"]

    stdin = sys.stdin.buffer
    model = None  # ленивая загрузка на первый кадр, не на старт процесса
    model_file = None  # держим поток до выгрузки модели / завершения воркера

    while True:
        frame = worker_proto.recv_frame(stdin)
        if frame is None:
            break
        request = json.loads(frame.decode("utf-8"))
        text, voice = request["text"], request["voice"]

        try:
            if model is None:
                # verify=True всегда: воркер — новый процесс каждый раз, что
                # он уже проверял файл в прошлой жизни, ему неизвестно.
                path = ensure_model(root, model_key, entry, verify=True)
                import torch
                from torch.package import PackageImporter

                torch.set_num_threads(4)
                # PyTorchFileReader(path) использует fopen и на Windows теряет
                # кириллицу в пути. Python открывает Unicode-пути корректно;
                # file-like API читает те же веса без копии всего файла в RAM.
                model_file = path.open("rb")
                model = PackageImporter(model_file).load_pickle("tts_models", "model")
                print(f"[worker] {model_key} загружена")

            audio = model.apply_tts(
                text=text,
                speaker=voice,
                sample_rate=sample_rate,
                put_accent=True,
                put_stress_homo=True,
                put_yo=True,
                put_yo_homo=True,
            )
            import numpy as np

            samples = audio.numpy()
            words, info = timings.word_timings(samples, sample_rate, text)
            print(f"[worker] тайминги: {len(words)} слов, {info['dips']} провалов "
                  f"на {info['marks']} знаков, речь {info['head']}–{info['tail']}с")
            pcm = (samples * 32767.0).clip(-32768, 32767).astype(np.int16).tobytes()
            meta = json.dumps({"words": words}, ensure_ascii=False).encode("utf-8")
            worker_proto.send_frame(_raw_stdout, b"\x01" + struct.pack(">I", len(meta)) + meta + pcm)
        except Exception as e:
            if model is None and model_file is not None:
                model_file.close()
                model_file = None
            payload = json.dumps({"error": str(e)}).encode("utf-8")
            worker_proto.send_frame(_raw_stdout, b"\x00" + payload)

    if model_file is not None:
        model_file.close()


if __name__ == "__main__":
    main()
