import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import time
import urllib.request


ROOT = Path(__file__).resolve().parent.parent
RUN = ROOT / "run.sh"
PID_FILE = ROOT / ".server.pid"
UNIT = Path.home() / ".config/systemd/user/skaz.service"
COMMANDS = {
    "skaz://start": "start", "skaz://start/": "start",
    "skaz://setup": "setup", "skaz://setup/": "setup",
    "skaz://stop": "stop", "skaz://stop/": "stop",
}


def owned_service():
    return bool(shutil.which("systemctl")) and UNIT.is_file() and str(RUN) in UNIT.read_text(encoding="utf-8")


def start():
    if owned_service():
        result = subprocess.run(["systemctl", "--user", "start", "skaz.service"],
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if result.returncode == 0:
            return
    output = (ROOT / "server.log").open("ab")
    try:
        subprocess.Popen([str(RUN)], cwd=ROOT, stdin=subprocess.DEVNULL,
                         stdout=output, stderr=output, start_new_session=True)
    finally:
        output.close()


def stop():
    if owned_service():
        subprocess.run(["systemctl", "--user", "stop", "skaz.service"],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        pid = int(PID_FILE.read_text(encoding="ascii"))
        if pid > 1:
            command = subprocess.run(["ps", "-p", str(pid), "-o", "args="],
                                     capture_output=True, text=True, check=True).stdout
            if str(ROOT / "packaging/unix_runner.py") in command:
                os.kill(pid, signal.SIGTERM)
                for attempt in range(50):
                    if not PID_FILE.exists():
                        break
                    time.sleep(0.1)
    except (FileNotFoundError, ValueError, ProcessLookupError, subprocess.CalledProcessError):
        pass


def setup_url():
    config_dir = Path((ROOT / ".config-dir").read_text(encoding="utf-8").strip())
    config = json.loads((config_dir / "config.json").read_text(encoding="utf-8"))
    for port in range(8756, 8761):
        request = urllib.request.Request(f"http://127.0.0.1:{port}/health",
                                         headers={"Authorization": "Bearer " + config["token"]})
        try:
            with urllib.request.urlopen(request, timeout=0.5) as response:
                if response.status == 200:
                    return f"http://127.0.0.1:{port}/setup"
        except (OSError, ValueError):
            continue
    return None


def main():
    if len(sys.argv) != 2:
        return 0
    command = COMMANDS.get(sys.argv[1])
    if command == "stop":
        stop()
        return 0
    if command not in ("start", "setup"):
        return 0
    start()
    if command == "setup":
        for attempt in range(60):
            url = setup_url()
            if url:
                subprocess.Popen(["xdg-open", url], stdin=subprocess.DEVNULL,
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                return 0
            time.sleep(0.5)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
