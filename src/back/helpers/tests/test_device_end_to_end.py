"""The whole device experience against a real server and a real daemon.

Every other GUI test here builds a window for a machine that no agent ever connected
to, so the populated paths — live telemetry, a deployment that landed, an approved
request — were never rendered. That gap let a crash ship: the machine page called
`ago()` with the server's ISO timestamp, which only exists once a daemon has
reported. These tests run the daemon for real so those fields are filled in.
"""

import asyncio
import os
import subprocess
import threading
import time
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PySide6.QtCore import QEvent
    from PySide6.QtWidgets import QApplication, QLabel, QPlainTextEdit
except ImportError as unavailable:  # pragma: no cover - environment dependent
    pytest.skip(f"the device app needs PySide6: {unavailable}", allow_module_level=True)

from nixync_agent.daemon import build_agent  # noqa: E402
from nixync_agent.gui.window import AgentWindow  # noqa: E402
from nixync_agent.settings import AgentSettings  # noqa: E402
from nixync_agent.system import SystemWriter  # noqa: E402
from nixync_client import AdminClient  # noqa: E402

SETTLE_SECONDS = 10


@pytest.fixture(scope="session")
def qt_app():
    yield QApplication.instance() or QApplication([])


@pytest.fixture
def admin(live_server) -> AdminClient:
    return AdminClient(live_server)


@pytest.fixture
def etc(tmp_path) -> Path:
    (tmp_path / "configuration.nix").write_text(
        "{ config, pkgs, ... }:\n\n{\n  imports = [ ./hardware-configuration.nix ];\n}\n"
    )
    return tmp_path


class RunningDaemon:
    """A real agent on its own thread, so Qt can keep its loop in the main one."""

    def __init__(self, live_server: str, machine_id: str, etc: Path):
        writer = SystemWriter(
            config_dir=etc,
            run=lambda cmd, **kw: subprocess.CompletedProcess(cmd, 0, "", ""),
        )
        self.agent = build_agent(
            AgentSettings(live_server, machine_id, telemetry_interval=60, config_dir=etc),
            writer,
        )
        self._thread: threading.Thread | None = None

    def __enter__(self):
        self._thread = threading.Thread(
            target=lambda: asyncio.run(self._run()), daemon=True
        )
        self._thread.start()
        return self

    async def _run(self):
        try:
            await self.agent.run()
        except BaseException:
            pass

    def __exit__(self, *_):
        self.agent.stop()
        if self._thread:
            self._thread.join(timeout=5)


def pump_until(condition, what: str, timeout: float = SETTLE_SECONDS):
    """Spin Qt until something becomes true. Qt work happens on this thread."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        QApplication.processEvents()
        if condition():
            return
        time.sleep(0.02)
    pytest.fail(f"never reached: {what}")


def texts(widget) -> str:
    """Everything the user can read on this widget.

    Flushes deferred deletes first: clear_layout() retires widgets with
    deleteLater(), so without this a rebuilt page still reports its old labels and a
    test can pass against text that is no longer on screen. Includes read-only text
    areas, which is where a build error is shown.
    """
    QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    parts = [label.text() for label in widget.findChildren(QLabel)]
    parts += [box.toPlainText() for box in widget.findChildren(QPlainTextEdit)]
    return " | ".join(parts)


def test_the_machine_page_renders_a_device_that_is_actually_reporting(
    qt_app, live_server, admin, etc
):
    """The regression: with telemetry present, the page used to crash on the timestamp."""
    machine = admin.register_machine("e2e-live")

    with RunningDaemon(live_server, machine.id, etc):
        window = AgentWindow(live_server, machine.id, username="student")
        pump_until(
            lambda: admin.get_machine(machine.id).metrics_reported_at is not None,
            "the daemon reported telemetry",
        )
        window.refresh()
        # Wait for the reported time to appear, not merely for the machine name — the
        # name was already on screen from the first load, so that would pass against
        # a stale render and prove nothing.
        pump_until(
            lambda: "Never" not in texts(window.machine),
            "the page rendered the reported telemetry",
        )

    shown = texts(window.machine)
    assert "Managed by Nixync" in shown, "it knows the agent is connected"
    assert "Last reported" in shown
    assert "unknown" not in shown.lower(), "the timestamp was understood, not fumbled"
    assert "Never" not in shown, "it has reported, so do not claim otherwise"


def test_the_whole_request_journey_from_the_device(qt_app, live_server, admin, etc):
    """Ask for an app, an admin approves, it lands and the device says so."""
    machine = admin.register_machine("e2e-journey")

    with RunningDaemon(live_server, machine.id, etc):
        window = AgentWindow(live_server, machine.id, username="student")
        pump_until(lambda: window._online is True, "the window reached the server")

        window._send_request("htop", "for monitoring")
        pump_until(lambda: window._requests, "the request appears in My requests")
        assert [r.app for r in window._requests] == ["htop"]
        assert window.my_requests is not None
        assert "Pending" in texts(window.my_requests)

        request = admin.list_requests(machine.id)[0]
        admin.approve_request(request.id)

        pump_until(
            lambda: admin.get_machine(machine.id).last_apply_status == "applied",
            "the daemon applied the approved app",
        )
        window.refresh()
        pump_until(lambda: "htop" in window.apps.installed, "the app shows as installed")

    assert "htop" in (etc / "nixync.nix").read_text(), "it reached the machine as Nix"
    assert "Approved" in texts(window.my_requests)
    assert "htop" in texts(window.machine), "the installed list shows it"


def test_a_failed_deployment_is_explained_on_the_device(qt_app, live_server, admin, etc):
    """Whoever is at the machine should learn why their software did not arrive."""
    machine = admin.register_machine("e2e-failed")
    writer = SystemWriter(
        config_dir=etc,
        run=lambda cmd, **kw: subprocess.CompletedProcess(
            cmd, 1, "", "error: undefined variable 'htp'"
        ),
    )
    agent = build_agent(
        AgentSettings(live_server, machine.id, telemetry_interval=60, config_dir=etc),
        writer,
    )
    thread = threading.Thread(target=lambda: asyncio.run(_quiet(agent)), daemon=True)
    thread.start()
    try:
        window = AgentWindow(live_server, machine.id, username="student")
        pump_until(lambda: window._online is True, "connected")
        admin.add_packages(["htp"], machine_ids=[machine.id])
        pump_until(
            lambda: admin.get_machine(machine.id).last_apply_status == "failed",
            "the failure reached the server",
        )
        window.refresh()
        pump_until(lambda: "didn't apply" in texts(window.machine), "the device explains it")
    finally:
        agent.stop()
        thread.join(timeout=5)

    assert "undefined variable" in texts(window.machine)


async def _quiet(agent):
    try:
        await agent.run()
    except BaseException:
        pass


def test_every_page_renders_for_a_fully_populated_machine(
    qt_app, live_server, admin, etc
):
    """A broad sweep: no page may raise once real data is present."""
    machine = admin.register_machine("e2e-pages", preset="Workstation")
    request = admin.create_request(machine.id, "git", "student", "version control")
    admin.approve_request(request.id)

    with RunningDaemon(live_server, machine.id, etc):
        window = AgentWindow(live_server, machine.id, username="student")
        pump_until(
            lambda: admin.get_machine(machine.id).last_apply_status == "applied",
            "the deployment landed",
        )
        window.refresh()
        pump_until(lambda: "e2e-pages" in texts(window.machine), "pages rendered")

        for index in range(window.stack.count()):
            window.stack.setCurrentIndex(index)
            QApplication.processEvents()

    assert "Workstation" in texts(window.machine), "the preset is shown"
    assert "git" in texts(window.machine), "so is what Nixync installed"
