"""The device app against a real server, headless."""

import os
import time

import httpx
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PySide6.QtWidgets import QApplication, QLabel, QPushButton
except ImportError as unavailable:  # pragma: no cover - environment dependent
    pytest.skip(f"the device app needs PySide6: {unavailable}", allow_module_level=True)

from nixync_agent.gui.pages import AppsPage, MachinePage, MyRequestsPage  # noqa: E402
from nixync_agent.gui.window import AgentWindow  # noqa: E402
from nixync_client import AdminClient  # noqa: E402

SETTLE_TIMEOUT_SECONDS = 5


@pytest.fixture(scope="session")
def qt_app():
    yield QApplication.instance() or QApplication([])


@pytest.fixture
def admin(live_server) -> AdminClient:
    return AdminClient(live_server)


def pump(window, until, what: str):
    """Spin Qt until a background load lands — the window polls off the UI thread."""
    deadline = time.monotonic() + SETTLE_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        QApplication.processEvents()
        if until():
            return
        time.sleep(0.02)
    pytest.fail(f"never reached: {what}")


def texts(widget) -> str:
    return " | ".join(label.text() for label in widget.findChildren(QLabel))


def test_the_window_builds_and_shows_this_machine(qt_app, live_server, admin):
    machine = admin.register_machine("device-window")

    window = AgentWindow(live_server, machine.id, username="student")
    pump(window, lambda: "device-window" in texts(window.machine), "the machine loaded")

    assert window.PAGES == ["Apps", "My requests", "This machine"]
    assert window.stack.count() == 3
    assert machine.id in texts(window.machine), "the agent id is shown"


def test_an_unreachable_server_is_reported_rather_than_crashing(qt_app):
    # Short timeout so the failure arrives inside the pump window; the default 5s is
    # right for a real poll but longer than this test should wait.
    window = AgentWindow(
        "http://127.0.0.1:1", "whatever", username="student", timeout=0.3
    )

    pump(window, lambda: "Can't reach" in texts(window.machine), "the failure was shown")

    assert window._online is False


def test_requesting_an_app_creates_a_real_request(qt_app, live_server, admin):
    machine = admin.register_machine("device-request")
    window = AgentWindow(live_server, machine.id, username="student")

    window._send_request("blender", "for the 3D assignment")

    requests = admin.list_requests(machine.id)
    assert [r.app for r in requests] == ["blender"]
    assert requests[0].requested_by == "student"
    assert requests[0].reason == "for the 3D assignment"
    assert requests[0].is_pending


def test_my_requests_shows_only_this_users_asks(qt_app, live_server, admin):
    """Two people share a lab machine; neither should see the other's requests."""
    machine = admin.register_machine("device-shared")
    admin.create_request(machine.id, "blender", "student", "mine")
    admin.create_request(machine.id, "vlc", "someone-else", "theirs")

    window = AgentWindow(live_server, machine.id, username="student")
    pump(window, lambda: window._requests, "requests loaded")

    assert [r.app for r in window._requests] == ["blender"]


def test_an_approved_request_shows_the_app_as_installed(qt_app, live_server, admin):
    machine = admin.register_machine("device-approved")
    request = admin.create_request(machine.id, "htop", "student", "")
    admin.approve_request(request.id)

    window = AgentWindow(live_server, machine.id, username="student")
    pump(window, lambda: "htop" in window.apps.installed, "the deployment landed")

    assert "htop" in window.apps.installed


def test_a_failed_deployment_shows_its_reason_to_the_user(qt_app, live_server, admin):
    """Whoever is at the machine should see why their software did not arrive."""
    machine = admin.register_machine("device-broken")
    page = MachinePage()

    class Broken:
        name, preset, online = "device-broken", "", True
        last_apply_status, last_apply_message = "failed", "error: collision in /nix/store"
        metrics_reported_at = cpu_percent = ram_used_mb = ram_total_mb = None
        disk_used_gb = disk_total_gb = None
        config = type("C", (), {"packages": []})()

    page.show_machine(Broken(), "an-id")

    assert "didn't apply" in texts(page)


def test_the_machine_page_handles_a_device_with_no_telemetry(qt_app, live_server, admin):
    machine = admin.register_machine("device-quiet")

    window = AgentWindow(live_server, machine.id, username="student")
    pump(window, lambda: "device-quiet" in texts(window.machine), "loaded")

    assert "Never" in texts(window.machine), "it says so rather than showing a blank"


def test_the_apps_page_starts_with_guidance_not_an_empty_list(qt_app):
    page = AppsPage("latest-51-nixos-26.05")

    assert "Search for an app" in texts(page)


def test_my_requests_says_so_when_there_are_none(qt_app):
    page = MyRequestsPage()
    page.show_requests([])

    assert "haven't asked for anything" in texts(page)


def test_the_window_offers_a_refresh(qt_app, live_server, admin):
    machine = admin.register_machine("device-refresh")
    window = AgentWindow(live_server, machine.id, username="student")

    assert any(b.text() == "Refresh" for b in window.findChildren(QPushButton))


def test_an_unreachable_server_explains_itself_in_plain_words(qt_app):
    """The person at the machine is not an administrator and did nothing wrong."""
    page = MachinePage()

    page.show_machine(None, "an-id", error="HTTPConnectionPool(host='x'): refused")

    shown = texts(page)
    assert "Can't reach the Nixync server." in shown
    assert "machine still works normally" in shown
    assert "HTTPConnectionPool" in shown, "the technical detail is kept, just demoted"
