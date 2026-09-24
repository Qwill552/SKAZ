"""Каталог моделей (models.json), скачивание весов, проверка SHA-256.

Веса не лежат в репозитории — качаются сюда при первом запуске. SHA-256
проверяется всегда после свежей закачки и один раз на файл, найденный уже
на диске (see silero.py: verify=not self._verified), чтобы битая докачка
или ручная порча файла не тонула где-то внутри torch.package непонятным
трейсбеком.
"""
import hashlib
import json
import urllib.request
from pathlib import Path


class ModelError(Exception):
    """Ошибка модели с текстом, который можно показать пользователю как есть."""


def load_catalog(root: Path) -> dict:
    path = root / "models.json"
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise ModelError(f"Не найден каталог моделей: {path}") from None
    except json.JSONDecodeError as e:
        raise ModelError(f"models.json повреждён: {e}") from e


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _download(url: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.name + ".part")
    try:
        with urllib.request.urlopen(url) as resp:
            total = int(resp.headers.get("Content-Length", 0))
            downloaded = 0
            with tmp.open("wb") as out:
                while True:
                    chunk = resp.read(1024 * 1024)
                    if not chunk:
                        break
                    out.write(chunk)
                    downloaded += len(chunk)
                    if total:
                        pct = downloaded * 100 // total
                        print(f"\r  скачивание: {pct:3d}%  "
                              f"({downloaded // (1024 * 1024)} / {total // (1024 * 1024)} МБ)",
                              end="", flush=True)
        print()
    except OSError:
        tmp.unlink(missing_ok=True)
        raise
    tmp.replace(dest)


def ensure_model(root: Path, key: str, entry: dict, *, verify: bool) -> Path:
    """Гарантирует, что файл модели есть на диске и (при verify=True или
    после свежей закачки) прошёл проверку SHA-256. Кидает ModelError с
    понятным текстом вместо трейсбека."""
    filename = entry["url"].rsplit("/", 1)[-1]
    dest = root / "models" / filename

    if not dest.exists():
        print(f"[models] модель {key} не найдена, скачиваю: {entry['url']}")
        try:
            _download(entry["url"], dest)
        except OSError as e:
            raise ModelError(f"Не удалось скачать модель {key}: {e}") from e
        verify = True

    if verify:
        actual = _sha256(dest)
        if actual != entry["sha256"]:
            raise ModelError(
                f"Файл модели {dest.name} повреждён: SHA-256 не совпадает "
                f"(ожидался {entry['sha256'][:12]}…, получен {actual[:12]}…). "
                f"Удалите {dest} и перезапустите сервер — он скачает заново."
            )

    return dest
