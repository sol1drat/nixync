"""A request made on a device must reach the admin panel.

This is the one flow that spans both applications, so it is the one most able to
look fine on each side while being broken between them — which is exactly what
happened: the device app wrote requests to the server while the admin panel read a
local list, so neither could see the other.
"""

import pytest

from nixync_client import AdminClient

from nixync_front import sample_data
from nixync_front.api import ApiError, NixyncClient
from nixync_front.config import Config


@pytest.fixture
def admin_panel(live_server) -> NixyncClient:
    """What the admin's Requests page calls."""
    return NixyncClient(Config(server_url=live_server, request_timeout=5))


@pytest.fixture
def device(live_server) -> AdminClient:
    """Stands in for the device app, which talks to the server directly."""
    return AdminClient(live_server)


def test_a_request_made_on_a_device_appears_in_the_admin_panel(admin_panel, device):
    machine = admin_panel.add_machine("req-e2e-visible")

    device.create_request(admin_panel.machine_id(machine.name), "blender", "student14", "coursework")

    # Scoped to this machine: the server is shared across the session.
    seen = [r for r in admin_panel.list_requests() if r.machine == "req-e2e-visible"]
    assert [r.app for r in seen] == ["blender"]
    assert seen[0].machine == "req-e2e-visible", "named by device, as the page shows it"
    assert seen[0].requested_by == "student14"
    assert seen[0].reason == "coursework"


def test_a_request_shows_as_pending_until_it_is_decided(admin_panel, device):
    machine = admin_panel.add_machine("req-e2e-pending")
    device.create_request(admin_panel.machine_id(machine.name), "vlc", "student", "")

    # Scoped to this machine: the server is shared across the session, so other
    # tests' requests are legitimately pending too.
    pending = admin_panel.pending_requests("req-e2e-pending")

    assert [r.app for r in pending] == ["vlc"]
    assert pending[0].status is sample_data.RequestStatus.PENDING


def test_pending_requests_can_be_narrowed_to_one_device(admin_panel, device):
    first = admin_panel.add_machine("req-e2e-a")
    second = admin_panel.add_machine("req-e2e-b")
    device.create_request(admin_panel.machine_id(first.name), "blender", "s", "")
    device.create_request(admin_panel.machine_id(second.name), "vlc", "s", "")

    assert [r.app for r in admin_panel.pending_requests("req-e2e-a")] == ["blender"]


def test_approving_from_the_admin_panel_deploys_to_the_device(admin_panel, device):
    machine = admin_panel.add_machine("req-e2e-approve")
    request = device.create_request(admin_panel.machine_id(machine.name), "htop", "s", "")

    approved = admin_panel.approve_request(request.id)

    assert approved.status is sample_data.RequestStatus.APPROVED
    assert "htop" in admin_panel.get_machine("req-e2e-approve").extra_apps


def test_declining_from_the_admin_panel_deploys_nothing(admin_panel, device):
    machine = admin_panel.add_machine("req-e2e-decline")
    request = device.create_request(admin_panel.machine_id(machine.name), "doom", "s", "")

    declined = admin_panel.decline_request(request.id)

    assert declined.status is sample_data.RequestStatus.DECLINED
    assert admin_panel.get_machine("req-e2e-decline").extra_apps == []


def test_a_decision_is_visible_to_the_device_afterwards(admin_panel, device):
    """The person who asked has to be able to see the answer."""
    machine = admin_panel.add_machine("req-e2e-answer")
    machine_id = admin_panel.machine_id(machine.name)
    request = device.create_request(machine_id, "git", "student", "")

    admin_panel.approve_request(request.id)

    from_device = device.list_requests(machine_id)
    assert [r.status for r in from_device] == ["approved"]


def test_deciding_a_request_twice_is_reported_rather_than_silently_repeated(
    admin_panel, device
):
    machine = admin_panel.add_machine("req-e2e-twice")
    request = device.create_request(admin_panel.machine_id(machine.name), "htop", "s", "")
    admin_panel.approve_request(request.id)

    with pytest.raises(ApiError):
        admin_panel.approve_request(request.id)


def test_requests_survive_a_restart_of_the_admin_panel(admin_panel, device, live_server):
    """They live on the server, not in whichever process happened to see them."""
    machine = admin_panel.add_machine("req-e2e-restart")
    device.create_request(admin_panel.machine_id(machine.name), "inkscape", "s", "")

    fresh = NixyncClient(Config(server_url=live_server, request_timeout=5))

    assert "inkscape" in [r.app for r in fresh.list_requests()]


# -- the Requests page itself ----------------------------------------------


def test_the_requests_page_offers_a_refresh_that_refetches(live_server, device):
    """Requests arrive from other machines while the page is open."""
    import os

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication, QPushButton

    from nixync_front.pages.requests import RequestsPage

    app = QApplication.instance() or QApplication([])
    panel = NixyncClient(Config(server_url=live_server, request_timeout=5))
    machine = panel.add_machine("req-page-refresh")
    page = RequestsPage(panel)
    page.refresh()
    before = len(page.client.list_requests())

    assert any(b.text() == "Refresh" for b in page.findChildren(QPushButton))

    device.create_request(panel.machine_id(machine.name), "krita", "student", "")
    page.refresh()

    assert len(page.client.list_requests()) == before + 1
    assert "krita" in [r.app for r in page.client.list_requests()]


def test_the_requests_page_survives_an_unreachable_server():
    import os

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication

    from nixync_front.pages.requests import RequestsPage

    QApplication.instance() or QApplication([])
    offline = NixyncClient(Config(server_url="http://127.0.0.1:1", request_timeout=0.3))

    page = RequestsPage(offline)
    page.refresh()

    assert page.load_error, "it records why, rather than crashing"


def test_deciding_a_request_twice_tells_the_operator_instead_of_crashing(
    live_server, device
):
    """Two admins, or one double click. The second attempt is refused by the server."""
    import os

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication

    from nixync_front.pages.requests import RequestsPage

    QApplication.instance() or QApplication([])
    panel = NixyncClient(Config(server_url=live_server, request_timeout=5))
    machine = panel.add_machine("req-page-twice")
    request = device.create_request(panel.machine_id(machine.name), "htop", "s", "")

    page = RequestsPage(panel)
    messages: list[str] = []
    page.message.connect(messages.append)

    view = next(r for r in page.client.list_requests() if r.id == request.id)
    page._decide(view, approve=True)
    page._decide(view, approve=True)

    assert any("Couldn't update that request" in m for m in messages)
