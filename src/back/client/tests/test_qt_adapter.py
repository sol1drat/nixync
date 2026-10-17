"""QtAgent against a real server, driven by a real Qt event loop.

Run headless with QT_QPA_PLATFORM=offscreen (set automatically below). Skipped entirely
when PySide6 is absent, which is the point of keeping the Qt binding optional.
"""

import os
import time

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

# Not pytest.importorskip: that only skips on ModuleNotFoundError, so a PySide6 that is
# installed but cannot load its native libraries — the usual situation on NixOS, where
# the pip wheel fails to find libstdc++ — would error the whole suite instead of
# skipping an optional extra.
try:
    # QApplication, not QCoreApplication: the desktop-app tests in src/front need a
    # widgets-capable instance, Qt allows only one per process, and mixing the two
    # classes segfaults when both suites run together.
    from PySide6.QtCore import QEventLoop, QTimer
    from PySide6.QtWidgets import QApplication
except ImportError as unavailable:  # pragma: no cover - environment dependent
    pytest.skip(
        f"the Qt adapter is optional and PySide6 is unusable here: {unavailable}",
        allow_module_level=True,
    )

from nixync_client.admin import AdminClient  # noqa: E402
from nixync_client.protocol import MachineConfig  # noqa: E402
from nixync_client.qt import QtAgent  # noqa: E402

SIGNAL_TIMEOUT_MS = 10_000


@pytest.fixture(scope="session")
def qt_app():
    """One QApplication for the session — Qt allows only a single instance."""
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture
def admin(live_server) -> AdminClient:
    return AdminClient(live_server)


class Recorder:
    """Buffers a signal's emissions from the moment it is created.

    Connecting only once you are ready to wait loses any signal that fired in between —
    and the agent is on another thread, so that race is real rather than theoretical.
    Recording from before the triggering action removes it entirely.
    """

    def __init__(self, signal):
        self._signal = signal
        self.events: list[tuple] = []
        signal.connect(self._capture)

    def _capture(self, *args) -> None:
        self.events.append(args)

    def wait(self, count: int = 1, timeout_ms: int = SIGNAL_TIMEOUT_MS) -> tuple:
        """Pump the Qt event loop until the signal has fired `count` times."""
        deadline = time.monotonic() + timeout_ms / 1000
        while len(self.events) < count and time.monotonic() < deadline:
            QApplication.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, 10)
            time.sleep(0.01)
        if len(self.events) < count:
            pytest.fail(
                f"signal fired {len(self.events)} time(s), expected {count}, "
                f"within {timeout_ms}ms"
            )
        return self.events[count - 1]


def wait_for(signal, timeout_ms: int = SIGNAL_TIMEOUT_MS) -> tuple:
    """Wait for a signal that has not been triggered yet."""
    return Recorder(signal).wait(timeout_ms=timeout_ms)


def test_importing_the_adapter_does_not_make_the_core_require_qt():
    """The agent must still run on a NixOS box with no Qt installed."""
    import subprocess
    import sys

    probe = (
        "import sys; sys.modules['PySide6'] = None;"
        "import nixync_client.agent, nixync_client.admin;"
        "print('core imported without PySide6')"
    )
    result = subprocess.run(
        [sys.executable, "-c", probe],
        cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert "core imported without PySide6" in result.stdout


def test_the_connected_signal_fires_once_the_agent_reaches_the_server(
    qt_app, live_server, admin
):
    machine = admin.register_machine("qt-connect")
    agent = QtAgent(live_server, machine.id, telemetry_interval=60)

    try:
        agent.start()
        wait_for(agent.connected)

        assert admin.get_machine(machine.id).online is True
    finally:
        agent.stop()


def test_telemetry_arrives_as_a_signal_the_ui_can_render(qt_app, live_server, admin):
    machine = admin.register_machine("qt-telemetry")
    agent = QtAgent(live_server, machine.id, telemetry_interval=60)

    try:
        agent.start()
        (reading,) = wait_for(agent.telemetry_sent)
    finally:
        agent.stop()

    assert 0.0 <= reading["cpu_percent"] <= 100.0
    assert reading["ram_total_mb"] > 0
    assert reading["disk_total_gb"] > 0


def test_a_package_change_surfaces_as_config_received_then_apply_finished(
    qt_app, live_server, admin
):
    machine = admin.register_machine("qt-apply")
    installed: list[str] = []
    agent = QtAgent(
        live_server,
        machine.id,
        on_apply=lambda config: installed.extend(config.packages),
        telemetry_interval=60,
    )

    try:
        agent.start()
        wait_for(agent.connected)

        # Record before triggering: the apply can finish before we start waiting.
        received = Recorder(agent.config_received)
        finished = Recorder(agent.apply_finished)

        results = admin.add_packages(["htop"], machine_ids=[machine.id])
        apply_id = results[0].apply_id

        assert received.wait() == (apply_id,)
        finished_id, succeeded, message = finished.wait()
    finally:
        agent.stop()

    assert finished_id == apply_id, "the GUI can correlate the result with its request"
    assert succeeded is True
    assert message == ""
    assert installed == ["htop"]


def test_a_failing_handler_reports_the_reason_through_apply_finished(
    qt_app, live_server, admin
):
    machine = admin.register_machine("qt-apply-fails")

    def refuse(config: MachineConfig):
        raise RuntimeError("nixos-rebuild exited 1")

    agent = QtAgent(live_server, machine.id, on_apply=refuse, telemetry_interval=60)

    try:
        agent.start()
        wait_for(agent.connected)
        finished = Recorder(agent.apply_finished)

        admin.add_packages(["gcc"], machine_ids=[machine.id])

        _, succeeded, message = finished.wait()
    finally:
        agent.stop()

    assert succeeded is False
    assert message == "nixos-rebuild exited 1"
    assert admin.get_machine(machine.id).last_apply_status == "failed", (
        "the failure still reached the server, not just the UI"
    )


def test_an_unregistered_machine_reports_through_the_error_signal(qt_app, live_server):
    """A bad machine id must reach the UI, not vanish on the worker thread."""
    agent = QtAgent(live_server, "00000000-0000-0000-0000-000000000000")

    try:
        agent.start()
        (message,) = wait_for(agent.error)
    finally:
        agent.stop()

    assert "machine id" in message.lower()


def test_stop_shuts_the_worker_thread_down(qt_app, live_server, admin):
    """stop() is called from the UI thread while the agent waits on its own loop."""
    machine = admin.register_machine("qt-stop")
    agent = QtAgent(live_server, machine.id, telemetry_interval=60)

    agent.start()
    wait_for(agent.connected)
    # Wait for the first telemetry so the agent's loop has gone quiet — a long sleep
    # with nothing else pending. That is the state a user closes the app in, and the
    # only state where a non-thread-safe stop() fails to wake it.
    wait_for(agent.telemetry_sent)
    assert agent.is_running
    worker = agent._thread

    started = time.monotonic()
    agent.stop()
    took = time.monotonic() - started

    # Assert on the thread itself, not just the adapter's opinion of it: a stop() that
    # gave up waiting could clear its reference and look stopped while the thread ran on.
    assert not worker.is_alive(), "the worker thread actually exited"
    assert not agent.is_running
    # Promptness is the real requirement. `asyncio.Event.set()` called straight from
    # this thread would not wake the agent's loop; it would linger until some unrelated
    # event (a WebSocket keepalive) happened to wake it, and the GUI would freeze on
    # close for seconds. Generous bound so this measures the defect, not the scheduler.
    assert took < 2.0, f"stop() blocked the UI thread for {took:.1f}s"
    assert admin.get_machine(machine.id).online is False


def test_stop_is_safe_to_call_without_starting_and_twice(qt_app, live_server, admin):
    machine = admin.register_machine("qt-stop-twice")
    agent = QtAgent(live_server, machine.id, telemetry_interval=60)

    agent.stop()  # never started

    agent.start()
    wait_for(agent.connected)
    agent.stop()
    agent.stop()  # idempotent

    assert not agent.is_running


def test_starting_twice_does_not_spawn_a_second_agent(qt_app, live_server, admin):
    """A double-click on 'Connect' must not leave a second worker running."""
    machine = admin.register_machine("qt-double-start")
    agent = QtAgent(live_server, machine.id, telemetry_interval=60)

    try:
        agent.start()
        wait_for(agent.connected)
        first_worker = agent._thread

        agent.start()

        assert agent._thread is first_worker, "the same worker, not a second one"
    finally:
        agent.stop()
