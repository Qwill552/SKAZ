import hashlib
import io
import json
from pathlib import Path
import runpy
import sys
import tarfile
import zipfile

ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT.parent / "dist"
sys.path.insert(0, str(ROOT))
VERSION = runpy.run_path(str(ROOT / "server/version.py"))["VERSION"]


def server_entries(prefix):
    for path in (ROOT / "server").rglob("*"):
        if path.is_file() and "__pycache__" not in path.parts and "tests" not in path.parts and not path.stem.endswith("_test") and path.suffix in (".py", ".html"):
            yield path, f"{prefix}{path.relative_to(ROOT).as_posix()}"


def windows_entries():
    for name in ("install.bat", "uninstall.bat"):
        yield ROOT / name, name
    for name in ("run.bat", "run.vbs", "handler.vbs", "autostart.bat", "pyproject.toml", "uv.lock", ".python-version", "models.json", "skaz.svg"):
        yield ROOT / name, f"_internal/{name}"
    for name in ("common.ps1", "install.ps1", "shortcuts.ps1", "skaz.ico", "uninstall.ps1", "update.ps1"):
        yield ROOT / "packaging" / name, f"_internal/packaging/{name}"
    yield ROOT / "userscript/skaz.user.js", "userscript/skaz.user.js"
    yield from server_entries("_internal/")


def unix_entries():
    for name in ("install.sh", "uninstall.sh", "run.sh", ".python-version", "models.json", "skaz.svg"):
        yield ROOT / name, name
    for name in ("pyproject-unix.toml", "uv-unix.lock", "unix_runner.py", "protocol_unix.py", "register_protocol.py", "skaz.service", "skaz.desktop", "com.skaz.plist", "update.sh"):
        yield ROOT / "packaging" / name, f"packaging/{name}"
    yield ROOT / "userscript/skaz.user.js", "userscript/skaz.user.js"
    yield from server_entries("")


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_windows(path):
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        for source, name in sorted(windows_entries(), key=lambda entry: entry[1]):
            archive.write(source, name)
        archive.write(ROOT / "README.txt", "README.txt")


def build_unix(path, readme):
    with tarfile.open(path, "w:gz") as archive:
        for source, name in sorted(unix_entries(), key=lambda entry: entry[1]):
            archive.add(source, arcname=name, recursive=False)
        content = readme.read_bytes()
        info = tarfile.TarInfo("README.txt")
        info.size = len(content)
        info.mode = 0o644
        archive.addfile(info, io.BytesIO(content))


def build(destination=DIST):
    if not (ROOT / "packaging/skaz.ico").is_file():
        raise SystemExit("Generate packaging/skaz.ico before building the release")
    destination.mkdir(exist_ok=True)
    archives = {
        "windows": destination / "skaz-windows.zip",
        "linux": destination / "skaz-linux.tar.gz",
        "macos": destination / "skaz-macos.tar.gz",
    }
    build_windows(archives["windows"])
    build_unix(archives["linux"], ROOT / "packaging/README-linux.txt")
    build_unix(archives["macos"], ROOT / "packaging/README-macos.txt")
    script = destination / "skaz.user.js"
    script.write_bytes((ROOT / "userscript/skaz.user.js").read_bytes())
    checksums = {path.name: sha256(path) for path in (*archives.values(), script)}
    (destination / "version.json").write_text(json.dumps({"version": VERSION, "assets": checksums}, indent=2) + "\n", encoding="utf-8")
    notes = (ROOT / "packaging/release-notes.md").read_text(encoding="utf-8").strip()
    if not notes.startswith(f"## v{VERSION}\n"):
        raise SystemExit("Update packaging/release-notes.md for the current version")
    (destination / "release-notes.md").write_text(notes + "\n\nОткройте `README.txt` в скачанном архиве для инструкций по установке и обновлению.\n", encoding="utf-8")
    return archives


if __name__ == "__main__":
    for platform, path in build().items():
        print(f"{platform}: {path} ({path.stat().st_size:,} bytes)")
