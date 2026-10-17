"""Shared fixtures for the client suite.

The live server is session-scoped: starting uvicorn is the slow part, and every test
isolates itself by registering its own machines rather than by getting a fresh database.
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

SERVER_DIR = Path(__file__).resolve().parents[2] / "server"
STARTUP_TIMEOUT_SECONDS = 30


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


@pytest.fixture(scope="session")
def live_server(tmp_path_factory):
    """A real `uvicorn server:app` process backed by a throwaway database."""
    port = _free_port()
    db_path = tmp_path_factory.mktemp("client-e2e") / "e2e.db"
    log_path = tmp_path_factory.mktemp("client-e2e-logs") / "uvicorn.log"

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
