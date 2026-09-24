import os
from pathlib import Path
import shutil
import subprocess
import sys


ROOT = Path(__file__).resolve().parent.parent
DATA_HOME = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local/share")
CONFIG_HOME = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
DESKTOP = DATA_HOME / "applications/skaz.desktop"


def desktop_argument(value):
    escaped = str(value).replace("\\", r"\\\\").replace('"', r'\\"')
    escaped = escaped.replace("$", r"\\$").replace("`", r"\\`").replace("%", "%%")
    return '"' + escaped + '"'


def desktop_content():
    template = (ROOT / "packaging/skaz.desktop").read_text(encoding="utf-8")
    executable = ROOT / ".venv/bin/python"
    handler = ROOT / "packaging/protocol_unix.py"
    command = f"{desktop_argument(executable)} {desktop_argument(handler)} %u"
    return template.replace("@SKAZ_EXEC@", command)


def update_database():
    if shutil.which("update-desktop-database"):
        subprocess.run(["update-desktop-database", str(DESKTOP.parent)], check=True)


def install():
    DESKTOP.parent.mkdir(parents=True, exist_ok=True)
    DESKTOP.write_text(desktop_content(), encoding="utf-8")
    update_database()
    subprocess.run(["xdg-mime", "default", "skaz.desktop", "x-scheme-handler/skaz"], check=True)


def remove_association(path):
    if not path.is_file():
        return
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    updated = []
    for line in lines:
        if line.startswith("x-scheme-handler/skaz="):
            name, values = line.split("=", 1)
            entries = [entry for entry in values.strip().split(";") if entry and entry != "skaz.desktop"]
            if entries:
                updated.append(name + "=" + ";".join(entries) + ";\n")
        else:
            updated.append(line)
    if updated != lines:
        path.write_text("".join(updated), encoding="utf-8")


def uninstall():
    if not DESKTOP.is_file() or DESKTOP.read_text(encoding="utf-8") != desktop_content():
        return
    DESKTOP.unlink()
    for mimeapps in (CONFIG_HOME / "mimeapps.list", DESKTOP.parent / "mimeapps.list"):
        remove_association(mimeapps)
    update_database()


if __name__ == "__main__":
    if sys.argv[1:] == ["install"]:
        install()
    elif sys.argv[1:] == ["uninstall"]:
        uninstall()
