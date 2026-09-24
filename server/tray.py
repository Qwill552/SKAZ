"""Windows entry point shared by shortcuts, autostart and future protocol handler.

One exclusive file handle per installation; JSON command mailbox (no TCP port,
pickle or elevated service). Only the lifecycle thread touches the child process.
The UI thread never waits for HTTP, model loading, or process termination.
"""
import argparse
import ctypes
import json
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import queue
import subprocess
import sys
import threading
import time
import uuid
import webbrowser

from .windows import FileLock, Job, message
from .release import latest_manifest, newer

ROOT = Path(__file__).resolve().parent.parent
RUNTIME = ROOT / ".runtime"
COMMANDS = {"start", "stop", "restart", "setup", "log", "autostart", "quit", "status", "update"}


def offer_update(controller):
    try:
        release = latest_manifest()
        if newer(release["version"]) and not controller.exiting.is_set():
            choice = ctypes.windll.user32.MessageBoxW(
                None, f"Доступна версия SKAZ {release['version']}. Обновить сейчас?",
                "Обновление SKAZ", 0x24,
            )
            if choice == 6 and not controller.exiting.is_set():
                controller.actions.put(("update", None))
    except (OSError, ValueError, KeyError):
        logging.exception("Update check failed")


def write_json(path, data):
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    temporary.replace(path)


def check_maintenance():
    # Concurrent launchers briefly open this file too. Do not mistake that for
    # a running installer; retry the short collision before reporting maintenance.
    for attempt in range(20):
        try:
            with FileLock(ROOT / ".maintenance.lock"):
                return
        except BlockingIOError:
            if attempt == 19:
                raise RuntimeError("SKAZ обновляется или удаляется; дождитесь завершения") from None
            time.sleep(.05)


def shortcut_path():
    return Path(os.environ["APPDATA"]) / "Microsoft/Windows/Start Menu/Programs/Startup/SKAZ.lnk"


def autostart_enabled():
    # WScript writes the quoted run.vbs argument as a Unicode string in the .lnk.
    # Check ownership too: another checkout's shortcut is not our autostart.
    try:
        return str(ROOT / "run.vbs").encode("utf-16-le") in shortcut_path().read_bytes()
    except FileNotFoundError:
        return False


def set_autostart(enabled):
    subprocess.run(["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass",
                    "-File", str(ROOT / "packaging/shortcuts.ps1"), "-Root", str(ROOT),
                    "-Action", "Enable" if enabled else "Disable"],
                   check=True, creationflags=subprocess.CREATE_NO_WINDOW,
                   stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)


class Controller:
    def __init__(self):
        self.process = self.job = self.output = self.icon = None
        self.state, self.busy, self.port = "Остановлен", False, None
        self.server_pid = None
        self.actions = queue.Queue()
        self.exiting = threading.Event()
        self.exit_requested = threading.Event()
        self.action_lock = threading.Lock()

    def snapshot(self):
        return {"state": self.state, "busy": self.busy, "port": self.port,
                "pid": os.getpid(), "server_pid": self.server_pid,
                "autostart": autostart_enabled()}

    def changed(self, notice=None):
        write_json(RUNTIME / "status.json", self.snapshot())
        if self.icon:
            self.icon.refresh(notice)

    def submit(self, command):
        # Ignore repeated lifecycle clicks while an operation is in progress.
        if command == "log":
            self.actions.put((command, None))
        elif command == "quit":
            self.exit_requested.set()
            self.actions.put((command, None))
        else:
            with self.action_lock:
                if not self.busy:
                    self.busy = True
                    self.actions.put((command, None))

    def start(self):
        if self.process and self.process.poll() is None:
            return
        self.stop()
        self.state = "Запускается"
        self.changed()
        nonce = uuid.uuid4().hex
        ready_path = RUNTIME / "server-ready.json"
        ready_path.unlink(missing_ok=True)
        self.job = Job()
        self.output = (ROOT / "logs/server.log").open("ab", buffering=0)
        python = Path(sys.executable).with_name("python.exe")
        self.process = subprocess.Popen(
            [str(python), "-u", "-m", "server.main", "--managed", nonce],
            cwd=ROOT, stdin=subprocess.PIPE, stdout=self.output, stderr=self.output,
            creationflags=subprocess.CREATE_NO_WINDOW,
            env={**os.environ, "PYTHONIOENCODING": "utf-8"},
        )
        # main waits on stdin before binding or spawning anything. Assign first,
        # then release it: even a crash here cannot leave a worker outside the Job.
        self.job.assign(self.process)
        self.process.stdin.write(b"start\n")
        self.process.stdin.flush()
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            if self.exit_requested.is_set():
                raise RuntimeError("Запуск отменён: выход из SKAZ")
            if self.process.poll() is not None:
                raise RuntimeError(f"Сервер завершился с кодом {self.process.returncode}")
            try:
                ready = json.loads(ready_path.read_text(encoding="utf-8"))
                # Windows venv python.exe is a redirector: Popen.pid can be its
                # wrapper, while ready.pid is the actual interpreter in our Job.
                if ready["nonce"] == nonce:
                    self.server_pid = ready["pid"]
                    self.port, self.state = ready["port"], "Работает"
                    logging.info("Server ready pid=%s port=%s", self.process.pid, self.port)
                    return
            except (OSError, ValueError, KeyError):
                pass
            time.sleep(0.05)
        raise RuntimeError("Сервер не запустился за 30 секунд")

    def stop(self):
        process, self.process = self.process, None
        try:
            if process and process.poll() is None:
                try:
                    process.stdin.write(b"stop\n")
                    process.stdin.flush()
                    process.wait(timeout=3)
                except (OSError, subprocess.TimeoutExpired):
                    pass
        finally:
            if self.job:
                self.job.close()
                self.job = None
            if process:
                # Also handles failure to assign the Job, before startup gate opens.
                if process.poll() is None:
                    process.kill()
                process.wait(timeout=5)
                process.stdin.close()
            if self.output:
                self.output.close()
                self.output = None
            self.state, self.port = "Остановлен", None
            self.server_pid = None

    def perform(self, command):
        if command == "status":
            return
        if command in ("stop", "restart", "quit"):
            self.stop()
        if command in ("start", "restart", "setup"):
            self.start()
        if command == "setup":
            webbrowser.open(f"http://127.0.0.1:{self.port}/setup")
        if command == "autostart":
            set_autostart(not autostart_enabled())
        if command == "log":
            os.startfile(ROOT / "logs/server.log")
            os.startfile(ROOT / "logs/skaz.log")
        if command == "update":
            if not (ROOT / ".skaz-install.json").is_file():
                raise RuntimeError("Обновление доступно только для установленного SKAZ")
            helper = Path(os.environ["TEMP"]) / f"skaz-update-{uuid.uuid4().hex}.ps1"
            helper.write_bytes((ROOT / "packaging/update.ps1").read_bytes())
            subprocess.Popen(["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass",
                              "-File", str(helper), "-InstallDir", str(ROOT.parent)],
                             creationflags=subprocess.CREATE_NO_WINDOW, close_fds=True)
        if command == "quit":
            self.exiting.set()

    def loop(self):
        try:
            while not self.exiting.is_set():
                try:
                    command, reply = self.actions.get(timeout=0.15)
                except queue.Empty:
                    if self.process and self.process.poll() is not None:
                        code = self.process.returncode
                        self.stop()  # also kills any surviving model worker
                        self.state = "Ошибка запуска"
                        logging.error("Server exited unexpectedly: %s", code)
                        self.changed("Сервер завершился. Откройте журнал через меню SKAZ.")
                    continue
                error = None
                self.busy = True
                self.changed()
                try:
                    if self.exit_requested.is_set() and command not in ("quit", "status", "log"):
                        raise RuntimeError("Выполняется выход из SKAZ")
                    self.perform(command)
                except Exception as exc:
                    logging.exception("Command failed: %s", command)
                    error = str(exc)
                    if command in ("start", "restart", "setup"):
                        self.stop()
                        self.state = "Ошибка запуска"
                    self.changed("Не удалось выполнить команду. Откройте журнал SKAZ.")
                finally:
                    self.busy = False
                    self.changed()
                if reply:
                    write_json(reply, {"ok": error is None, "error": error, **self.snapshot()})
        finally:
            self.stop()
            self.exiting.set()
            if self.icon:
                self.icon.stop()

    def mailbox(self):
        while not self.exiting.wait(0.1):
            for path in sorted(RUNTIME.glob("request-*.json")):
                try:
                    data = json.loads(path.read_text(encoding="utf-8"))
                    path.unlink()
                    if data.get("command") not in COMMANDS or time.time() - data["time"] > 60:
                        continue
                    reply = path.with_name(path.name.replace("request-", "reply-"))
                    if data["command"] == "status":
                        write_json(reply, {"ok": True, **self.snapshot()})
                    else:
                        if data["command"] == "quit":
                            self.exit_requested.set()
                        self.actions.put((data["command"], reply))
                except (OSError, ValueError, KeyError):
                    logging.exception("Invalid command file: %s", path.name)


def send_command(command, timeout=45):
    ident = uuid.uuid4().hex
    request = RUNTIME / f"request-{ident}.json"
    reply = RUNTIME / f"reply-{ident}.json"
    write_json(request, {"command": command, "time": time.time()})
    try:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                return json.loads(reply.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                time.sleep(0.05)
        raise RuntimeError("SKAZ не ответил на команду; см. logs/skaz.log")
    finally:
        request.unlink(missing_ok=True)
        reply.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description="SKAZ Windows controller")
    parser.add_argument("command", nargs="?", default="start", choices=sorted(COMMANDS))
    args = parser.parse_args()
    RUNTIME.mkdir(exist_ok=True)
    (ROOT / "logs").mkdir(exist_ok=True)
    handler = RotatingFileHandler(ROOT / "logs/skaz.log", maxBytes=1024 * 1024,
                                  backupCount=2, encoding="utf-8")
    logging.basicConfig(level=logging.INFO, handlers=[handler],
                        format="%(asctime)s %(levelname)s %(message)s")
    if sys.stdout:
        sys.stdout.reconfigure(encoding="utf-8")
    lock = None
    try:
        # Install/uninstall hold this lock while files are being replaced. Stop,
        # quit/status remain available so maintenance can shut down the instance.
        if args.command not in ("stop", "quit", "status"):
            if (ROOT / ".uninstalling").exists():
                raise RuntimeError("Выполняется удаление SKAZ")
            check_maintenance()
        try:
            lock = FileLock(ROOT / ".instance.lock")
        except BlockingIOError:
            result = send_command(args.command)
            if sys.stdout:
                print(json.dumps(result, ensure_ascii=False))
            if not result["ok"]:
                raise RuntimeError(result.get("error"))
            return
        if args.command in ("stop", "quit", "status"):
            if sys.stdout:
                print(json.dumps({"ok": True, "state": "Остановлен"}, ensure_ascii=False))
            return
        # Recheck under the instance lock to close a race with the installer.
        check_maintenance()
        for old in RUNTIME.glob("*-*.json"):
            if time.time() - old.stat().st_mtime > 60:
                old.unlink(missing_ok=True)
        controller = Controller()
        from .tray_icon import TrayIcon
        controller.icon = TrayIcon(ROOT / "packaging/skaz.ico", controller.snapshot, controller.submit)
        lifecycle = threading.Thread(target=controller.loop, name="lifecycle")
        mailbox = threading.Thread(target=controller.mailbox, name="commands", daemon=True)

        def ready():
            lifecycle.start()
            mailbox.start()
            controller.actions.put(("setup" if args.command == "setup" else "start", None))
            threading.Thread(target=offer_update, args=(controller,), daemon=True).start()

        try:
            controller.icon.run(ready)
        finally:
            controller.actions.put(("quit", None))
            if lifecycle.is_alive():
                lifecycle.join(timeout=40)
            controller.stop()
    except Exception as exc:
        logging.exception("SKAZ launcher failed")
        if sys.stderr:
            print(str(exc), file=sys.stderr)
        else:
            message(f"Не удалось запустить SKAZ: {exc}\nЖурнал: {ROOT / 'logs/skaz.log'}")
        raise SystemExit(1)
    finally:
        if lock:
            lock.close()


if __name__ == "__main__":
    main()
