"""Headless construction of the main window against a live server.

Runs in a subprocess so a missing Qt platform library cannot abort the rest of
the suite. Catches import and wiring mistakes the adapter tests cannot.
"""

import os
import subprocess
import sys
from pathlib import Path

import pytest

FRONT_ROOT = Path(__file__).resolve().parents[1]
CLIENT_LIBRARY = FRONT_ROOT.parent / "back" / "client"
SHARED_UI = FRONT_ROOT.parent / "shared"

SMOKE_SCRIPT = r"""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PySide6.QtWidgets import QApplication
except ImportError as exc:
    print(f"SKIP: PySide6 unavailable: {exc}")
    raise SystemExit(0)

from nixync_front.config import Config
from nixync_front.main_window import MainWindow

server_url = sys.argv[1]
app = QApplication.instance() or QApplication([])
window = MainWindow(Config(server_url=server_url, request_timeout=5), username="admin")
window.show()
app.processEvents()
# The session-scoped test server may already hold machines from earlier tests;
# what matters is that listing and rendering them does not crash.
assert isinstance(window.client.list_machines(), list)
assert window.stack.count() >= len(MainWindow.PAGES)
window.close()
print("ok")
"""


def test_main_window_builds_against_a_live_server(live_server):
    env = {
        **os.environ,
        "QT_QPA_PLATFORM": "offscreen",
        "PYTHONPATH": os.pathsep.join(
            [str(FRONT_ROOT), str(CLIENT_LIBRARY), str(SHARED_UI), os.environ.get("PYTHONPATH", "")]
        ),
    }
    result = subprocess.run(
        [sys.executable, "-c", SMOKE_SCRIPT, live_server],
        capture_output=True,
        text=True,
        env=env,
        timeout=60,
    )
    if "SKIP:" in result.stdout:
        pytest.skip(result.stdout.strip())
    assert result.returncode == 0, (
        f"GUI smoke failed (exit {result.returncode})\n"
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
    assert "ok" in result.stdout
