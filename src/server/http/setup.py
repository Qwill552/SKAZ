"""Локальное связывание и правка пользовательского словаря."""
import html
import base64
import json
import time
from pathlib import Path


SETUP_HTML = Path(__file__).resolve().parent.parent / "static" / "setup.html"
PAIR_SECONDS = 60
MAX_DICT_BYTES = 65536


def userscript_path(root: Path) -> Path:
    """Prefer the userscript beside the install.bat used for this installation.

    The source is recorded locally by the installer, never accepted from HTTP.
    Keep the installed copy usable after the downloaded archive is moved/deleted.
    """
    try:
        metadata = json.loads((root / ".skaz-install.json").read_text(encoding="utf-8"))
        source = metadata.get("userscript_source")
        if isinstance(source, str):
            path = Path(source)
            if path.is_absolute() and path.is_file():
                return path
    except (OSError, ValueError, AttributeError):
        pass
    local = root / "userscript" / "skaz.user.js"
    return local if local.is_file() else root.parent / "userscript" / "skaz.user.js"


def local_page_request(handler) -> bool:
    """Не отдавать секрет странице с чужим Origin или подменённым Host."""
    host = handler.headers.get("Host", "")
    port = handler.server.server_address[1]
    if host != f"127.0.0.1:{port}":
        return False
    origin = handler.headers.get("Origin")
    return not origin or origin == f"http://{host}"


def render_setup(token: str) -> bytes:
    import qrcode
    from qrcode.image.svg import SvgPathImage

    template = SETUP_HTML.read_text(encoding="utf-8")
    svg = qrcode.make(token, image_factory=SvgPathImage).to_string()
    qr = "data:image/svg+xml;base64," + base64.b64encode(svg).decode("ascii")
    return (template.replace("{{TOKEN}}", html.escape(token, quote=True))
            .replace("{{QR}}", qr)).encode("utf-8")


def open_pair(server) -> None:
    server.pair_until = time.monotonic() + PAIR_SECONDS


def take_pair(server) -> str | None:
    if time.monotonic() >= server.pair_until:
        server.pair_until = 0
        return None
    server.pair_until = 0
    return server.config["token"]


def parse_dict(raw: bytes) -> dict[str, str]:
    if len(raw) > MAX_DICT_BYTES:
        raise ValueError("dictionary_too_large")
    try:
        data = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        raise ValueError("bad_json") from exc
    if not isinstance(data, dict) or any(
        not isinstance(k, str) or not isinstance(v, str) or not k.strip() or
        len(k) > 120 or len(v) > 240 for k, v in data.items()
    ):
        raise ValueError("bad_dictionary")
    return data


def save_dict(path: Path, data: dict[str, str]) -> None:
    # os.replace оставляет читателю либо старый, либо новый целый JSON.
    import os
    import tempfile
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as out:
        name = out.name
        json.dump(data, out, ensure_ascii=False, indent=2)
        out.write("\n")
    os.replace(name, path)
