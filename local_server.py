"""Detached local Uvicorn runner with an explicit graceful-stop file."""
from __future__ import annotations

import os
from pathlib import Path
import argparse
import threading

import uvicorn


ROOT = Path(__file__).resolve().parent
STATE = ROOT / ".local"
PID_FILE = STATE / "queryvault-server.pid"
STOP_FILE = STATE / "queryvault-server.stop"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("port", nargs="?", type=int, default=8000)
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("port must be between 1 and 65535")

    STATE.mkdir(parents=True, exist_ok=True)
    server = uvicorn.Server(
        uvicorn.Config(
            "app:app",
            host="127.0.0.1",
            port=args.port,
            log_level="info",
            lifespan="on",
        )
    )
    stopping = threading.Event()

    def watch_for_stop() -> None:
        while not stopping.wait(0.2):
            if STOP_FILE.exists():
                server.should_exit = True
                return

    watcher = threading.Thread(target=watch_for_stop, name="queryvault-stop-watcher", daemon=True)
    PID_FILE.write_text(str(os.getpid()), encoding="ascii")
    watcher.start()
    try:
        server.run()
    finally:
        stopping.set()
        watcher.join(timeout=1)
        try:
            if PID_FILE.read_text(encoding="ascii").strip() == str(os.getpid()):
                PID_FILE.unlink(missing_ok=True)
        except OSError:
            pass
        STOP_FILE.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
