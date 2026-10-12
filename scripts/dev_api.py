from __future__ import annotations

import logging
import subprocess
import sys
from pathlib import Path

from watchfiles import PythonFilter, watch


PROJECT_ROOT = Path(__file__).resolve().parent.parent


def start_process(command: list[str]) -> subprocess.Popen:
    flags = subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0
    return subprocess.Popen(command, cwd=PROJECT_ROOT, creationflags=flags)


def stop_process(process: subprocess.Popen) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    command = [sys.executable, "-u", "-m", "uvicorn", "atelier_tools.server:create_app", "--factory", "--host", "127.0.0.1", "--port", "47831"]
    process = start_process(command)
    try:
        for changes in watch(PROJECT_ROOT / "atelier_tools", PROJECT_ROOT / "app.py", watch_filter=PythonFilter(), debounce=500):
            logging.info("Restarting API after changes: %s", ", ".join(sorted(path for _, path in changes)))
            stop_process(process)
            process = start_process(command)
    except KeyboardInterrupt:
        pass
    finally:
        stop_process(process)


if __name__ == "__main__":
    main()
