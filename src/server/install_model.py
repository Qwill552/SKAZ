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
    parser.add_argument("--model")
    parser.add_argument("--unattended", action="store_true")
    args = parser.parse_args()
    catalog = load_catalog(ROOT)
    config_path = CONFIG_DIR / "config.json"
    config = json.loads(config_path.read_text(encoding="utf-8")) if config_path.exists() else None
    if config:
        key = config.get("model", "silero_v5_ru")
        print(f"Сохраняем настройки и выбранную модель: {key}")
    elif args.model:
        key = args.model
    else:
        keys = list(catalog)
        for index, key in enumerate(keys, 1):
            item = catalog[key]
            print(f"{index}. {key}: {item['size_mb']} МБ, {item['license']}")
        print("v5_ru: только некоммерческое использование (CC-BY-NC 4.0).")
        choice = "" if args.unattended else input("Модель [1]: ").strip()
        if choice and (not choice.isdigit() or not 1 <= int(choice) <= len(keys)):
            raise SystemExit("Неверный номер модели. Запустите установщик снова.")
        key = keys[int(choice) - 1] if choice else "silero_v5_ru"
    if key not in catalog:
        raise SystemExit(f"Неизвестная модель: {key}")
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
                  "model": key, "default_voice": "baya" if key == "silero_v5_ru" else "ru_dmitriy",
                  "idle_unload_minutes": 10, "cache_size": 50}
        # Exclusive create also protects data if setup is accidentally run twice.
        with config_path.open("x", encoding="utf-8") as output:
            json.dump(config, output, ensure_ascii=False, indent=2)
    dictionary = CONFIG_DIR / "user_dict.json"
    if not dictionary.exists():
        dictionary.write_text("{}\n", encoding="utf-8")


if __name__ == "__main__":
    main()
