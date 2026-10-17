"""A real uvicorn server for the desktop app's tests.

The adapter's whole job is translating between the server's records and the view model
the UI renders, so testing it against a mock would only prove the mock matches the
mapping — not that the mapping matches the server.
"""

import contextlib
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest

SERVER_DIR = Path(__file__).resolve().parents[2] / "back" / "server"
STARTUP_TIMEOUT_SECONDS = 30


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


@pytest.fixture(scope="session")
def live_server(tmp_path_factory):
    port = _free_port()
    db_path = tmp_path_factory.mktemp("front-e2e") / "front.db"
    log_path = tmp_path_factory.mktemp("front-e2e-logs") / "uvicorn.log"

    with open(log_path, "w", encoding="utf-8") as log:
        process = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "server:app", "--port", str(port)],
            cwd=SERVER_DIR,
            env={**os.environ, "NIXYNC_DB": str(db_path)},
            stdout=log,
            stderr=subprocess.STDOUT,
        )

    base_url = f"http://127.0.0.1:{port}"
    deadline = time.monotonic() + STARTUP_TIMEOUT_SECONDS
    try:
        while True:
            if process.poll() is not None:
                pytest.fail(f"server exited early:\n{log_path.read_text()}")
            if time.monotonic() > deadline:
                pytest.fail(f"server never started:\n{log_path.read_text()}")
            try:
                if httpx.get(f"{base_url}/machines", timeout=1).status_code == 200:
                    break
            except httpx.HTTPError:
                time.sleep(0.1)
        yield base_url
    finally:
        process.terminate()
        with contextlib.suppress(subprocess.TimeoutExpired):
            process.wait(timeout=10)
