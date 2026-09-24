import os
from pathlib import Path
import shutil
import subprocess
import sys


ROOT = Path(__file__).resolve().parent.parent


def start_update():
    if not (ROOT / ".skaz-install.json").is_file():
        raise RuntimeError("Обновление доступно только для установленного SKAZ")
    if (ROOT / ".installing").exists() or (ROOT / ".uninstalling").exists():
        raise RuntimeError("Установка или удаление уже выполняется")
    if sys.platform == "win32":
        from .tray import send_command

        result = send_command("update", timeout=10)
        if not result["ok"]:
            raise RuntimeError(result.get("error") or "Не удалось запустить обновление")
        return
    command = ["bash", str(ROOT / "packaging/update.sh"), str(ROOT)]
    if sys.platform == "linux" and shutil.which("systemd-run") and subprocess.run(
        ["systemctl", "--user", "show-environment"], stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL, check=False,
    ).returncode == 0:
        command = ["systemd-run", "--user", "--collect"] + command
    subprocess.Popen(command, cwd=ROOT, stdin=subprocess.DEVNULL,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     start_new_session=True, env={**os.environ, "SKAZ_UNATTENDED_UPDATE": "1"})
