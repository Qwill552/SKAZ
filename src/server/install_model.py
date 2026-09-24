"""Interactive model installation; never overwrite an existing config/dictionary."""
import argparse
import json
import os
from pathlib import Path
import secrets
import urllib.request

from .models import _sha256, load_catalog

ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = Path(os.environ.get("SKAZ_CONFIG_DIR") or ROOT)


def download_verified(root, entry):
    target = root / "models" / entry["url"].rsplit("/", 1)[-1]
    target.parent.mkdir(exist_ok=True)
    if target.exists() and _sha256(target) == entry["sha256"]:
        print("Модель уже скачана, SHA-256 совпадает.")
        return
    temporary = target.with_suffix(target.suffix + ".part")
    try:
        last_percent = -1
        def progress(block, size, total):
            nonlocal last_percent
            if total > 0:
                percent = min(100, block * size * 100 // total)
                if percent != last_percent:
                    print(f"\rСкачивание: {percent}%", end="", flush=True)
                    last_percent = percent
        urllib.request.urlretrieve(entry["url"], temporary, reporthook=progress)
        print()
        if _sha256(temporary) != entry["sha256"]:
            raise ValueError("SHA-256 не совпадает: скачанный файл повреждён")
        temporary.replace(target)
    finally:
        temporary.unlink(missing_ok=True)


def main():
    import sys
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", action="append")
    parser.add_argument("--unattended", action="store_true")
    args = parser.parse_args()
    catalog = load_catalog(ROOT)
    config_path = CONFIG_DIR / "config.json"
    config = json.loads(config_path.read_text(encoding="utf-8")) if config_path.exists() else None
    if config:
        keys = list(dict.fromkeys(config.get("models") or [config.get("model", "silero_v5_ru")]))
        if args.model:
            keys = list(dict.fromkeys(keys + [part.strip() for value in args.model for part in value.split(",")]))
        elif not args.unattended:
            available = [key for key in [*catalog, "edge_tts", "yandex_tts"] if key not in keys]
            for index, key in enumerate(available, 1):
                print(f"{index}. Добавить {key}")
            choice = input("Добавить модели через запятую [Enter — оставить]: ").strip()
            if choice:
                numbers = [part.strip() for part in choice.split(",")]
                if any(not part.isdigit() or not 1 <= int(part) <= len(available) for part in numbers):
                    raise SystemExit("Неверный номер модели. Запустите установщик снова.")
                keys.extend(available[int(part) - 1] for part in numbers)
                keys = list(dict.fromkeys(keys))
        print(f"Сохраняем настройки и модели: {', '.join(keys)}")
    elif args.model:
        keys = list(dict.fromkeys(part.strip() for value in args.model for part in value.split(",")))
    else:
        available = list(catalog)
        for index, key in enumerate(available, 1):
            item = catalog[key]
            print(f"{index}. {key}: {item['size_mb']} МБ, {item['license']}")
        print(f"{len(available) + 1}. edge_tts: интернет, текст отправляется Microsoft")
        print(f"{len(available) + 2}. yandex_tts: интернет, текст отправляется Яндексу")
        print("v5_ru: только некоммерческое использование (CC-BY-NC 4.0).")
        choice = "" if args.unattended else input("Модели через запятую [1]: ").strip()
        numbers = [part.strip() for part in choice.split(",")] if choice else ["1"]
        if any(not part.isdigit() or not 1 <= int(part) <= len(available) + 2 for part in numbers):
            raise SystemExit("Неверный номер модели. Запустите установщик снова.")
        keys = list(dict.fromkeys((available + ["edge_tts", "yandex_tts"])[int(part) - 1] for part in numbers))
    if not keys or any(key not in catalog and key not in ("edge_tts", "yandex_tts") for key in keys):
        raise SystemExit(f"Неизвестные модели: {', '.join(keys)}")
    if any(key in keys for key in ("edge_tts", "yandex_tts")) and not any(key in catalog for key in keys):
        keys.insert(0, "silero_v5_ru")
    keys = [key for key in keys if key in catalog] + [key for key in keys if key not in catalog]
    for key in keys:
        if key in ("edge_tts", "yandex_tts"):
            continue
        print(f"{key}: {catalog[key]['license']}")
        while True:
            try:
                download_verified(ROOT, catalog[key])
                break
            except (OSError, ValueError) as exc:
                print(f"Не удалось подготовить модель: {exc}")
                if args.unattended or input("Повторить скачивание? [Y/n]: ").lower() in ("n", "н"):
                    raise SystemExit(1)
    if config is None:
        config = {"port": 8756, "token": secrets.token_urlsafe(32), "backend": "silero",
                  "model": keys[0], "models": keys,
                  "default_voice": "baya" if keys[0] == "silero_v5_ru" else "ru_dmitriy",
                  "idle_unload_minutes": 10, "cache_size": 50}
        # Exclusive create also protects data if setup is accidentally run twice.
        with config_path.open("x", encoding="utf-8") as output:
            json.dump(config, output, ensure_ascii=False, indent=2)
    elif keys != (config.get("models") or [config.get("model", "silero_v5_ru")]):
        updated = dict(config, models=keys)
        temporary = config_path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(updated, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(config_path)
    dictionary = CONFIG_DIR / "user_dict.json"
    if not dictionary.exists():
        dictionary.write_text("{}\n", encoding="utf-8")


if __name__ == "__main__":
    main()
