import fcntl
import os
from pathlib import Path
import signal
import subprocess
import sys


ROOT = Path(__file__).resolve().parent.parent


def main():
    lock = (ROOT / ".instance.lock").open("a+")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        return 0
    child = subprocess.Popen([sys.executable, "-m", "server.main"], cwd=ROOT)
    pid_file = ROOT / ".server.pid"
    pid_file.write_text(str(os.getpid()), encoding="ascii")

    def terminate(signum, frame):
        if child.poll() is None:
            child.terminate()

    signal.signal(signal.SIGTERM, terminate)
    signal.signal(signal.SIGINT, terminate)
    try:
        return child.wait()
    finally:
        if pid_file.exists() and pid_file.read_text(encoding="ascii") == str(os.getpid()):
            pid_file.unlink()
        lock.close()


if __name__ == "__main__":
    raise SystemExit(main())
