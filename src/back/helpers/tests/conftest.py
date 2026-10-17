"""A real uvicorn server for the agent's integration tests.

The agent's job is to behave correctly against the real server, so the daemon tests
drive one rather than a double — the same reasoning as the client suite.
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
    port = _free_port()
    db_path = tmp_path_factory.mktemp("agent-e2e") / "agent.db"
    log_path = tmp_path_factory.mktemp("agent-e2e-logs") / "uvicorn.log"

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


@pytest.fixture(autouse=True)
def never_rebuild_for_real(monkeypatch):
    """Fail loudly if any test reaches a real nixos-rebuild.

    This is not hypothetical: an earlier version of these tests patched
    `subprocess.run` after `SystemWriter` had already captured it as a default
    argument, so the patch did nothing and a genuine `nixos-rebuild` was invoked. It
    only failed because this machine has no NIX_PATH. The writer now resolves the
    command lazily, and this fixture makes the mistake impossible to miss.
    """
    real_run = subprocess.run

    def guarded(command, *args, **kwargs):
        name = command[0] if isinstance(command, (list, tuple)) and command else command
        if "nixos-rebuild" in str(name):
            raise AssertionError(
                f"a test tried to run {command!r}. Inject a fake runner into "
                "SystemWriter instead of letting the real command through."
            )
        return real_run(command, *args, **kwargs)

    monkeypatch.setattr(subprocess, "run", guarded)
