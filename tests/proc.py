"""Starting the real services as subprocesses, for the system and browser tiers."""
from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
from pathlib import Path


def free_port() -> int:
    """An unused port. Chosen by the OS rather than hardcoded so several
    copies of the suite can run at once (a developer's machine and CI on the
    same runner, or pytest-xdist workers)."""
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def wait_healthy(port: int, timeout: float = 45.0) -> None:
    import httpx

    deadline = time.time() + timeout
    last: object = "no attempt made"
    while time.time() < deadline:
        try:
            response = httpx.get(f"http://127.0.0.1:{port}/health", timeout=2.0)
            if response.status_code == 200:
                return
            last = response.status_code
        except Exception as exc:  # noqa: BLE001 - it is simply still starting
            last = exc
        time.sleep(0.25)
    raise RuntimeError(f"service on port {port} never became healthy (last: {last})")


class Service:
    """One uvicorn process, with its output captured to a file so a failure
    can be explained rather than guessed at."""

    def __init__(self, name: str, cwd: Path, port: int, env: dict, log: Path,
                 module: str = "app.main:app"):
        self.name, self.port, self.log = name, port, log
        self.handle = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", module,
             "--host", "127.0.0.1", "--port", str(port), "--log-level", "warning"],
            cwd=str(cwd),
            env={**os.environ, **env, "PYTHONUNBUFFERED": "1"},
            stdout=log.open("w"), stderr=subprocess.STDOUT,
        )

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def log_text(self) -> str:
        return self.log.read_text() if self.log.exists() else ""

    def stop(self) -> None:
        self.handle.terminate()
        try:
            self.handle.wait(timeout=10)
        except subprocess.TimeoutExpired:  # pragma: no cover
            self.handle.kill()
