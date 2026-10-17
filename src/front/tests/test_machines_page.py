"""The fleet view against a live server.

The devices page is the product's main screen and the only one whose data now comes
over the network on every repaint, so it gets its own tests: it must show current
state, and it must survive a server that is not there.
"""

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PySide6.QtWidgets import QApplication, QLabel
except ImportError as unavailable:  # pragma: no cover - environment dependent
    pytest.skip(
        f"the desktop app needs PySide6, unusable here: {unavailable}",
        allow_module_level=True,
    )

from nixync_front.api import NixyncClient  # noqa: E402
from nixync_front.config import Config  # noqa: E402
from nixync_front.pages.machines import MachinesPage  # noqa: E402


@pytest.fixture(scope="module")
def qt_app():
    yield QApplication.instance() or QApplication([])


@pytest.fixture
def client(live_server) -> NixyncClient:
    return NixyncClient(Config(server_url=live_server, request_timeout=5))


def names_on(page: MachinesPage) -> set[str]:
    return {m.name for m in page.machines}


def test_the_page_lists_machines_the_server_already_knows(qt_app, client):
    client.add_machine("page-existing")

    page = MachinesPage(client)

    assert "page-existing" in names_on(page)


def test_refreshing_picks_up_a_machine_added_after_the_page_was_built(qt_app, client):
    """The fleet view must show current state, not a snapshot from app start.

    Without a re-fetch the page renders whatever it read in __init__ forever: a newly
    registered device never appears, and live telemetry never moves.
    """
    page = MachinesPage(client)
    assert "page-added-later" not in names_on(page)

    client.add_machine("page-added-later")
    page.refresh()

    assert "page-added-later" in names_on(page)


def test_refreshing_drops_a_machine_that_was_removed(qt_app, client):
    client.add_machine("page-removed")
    page = MachinesPage(client)
    assert "page-removed" in names_on(page)

    client.remove_machine("page-removed")
    page.refresh()

    assert "page-removed" not in names_on(page)


def test_refreshing_shows_updated_details_for_a_machine_that_changed(qt_app, client):
    """Telemetry and deployment state move while the app is open."""
    client.add_machine("page-changed")
    page = MachinesPage(client)

    client.add_apps(["page-changed"], ["htop"])
    page.refresh()

    changed = next(m for m in page.machines if m.name == "page-changed")
    assert changed.extra_apps == ["htop"]


def test_the_page_still_builds_when_the_server_is_unreachable(qt_app):
    """A dead server must not stop the app from starting.

    list_machines() used to return sample data and could not fail; now it is a network
    call in __init__, so an unreachable server would otherwise crash the launch.
    """
    offline = NixyncClient(Config(server_url="http://127.0.0.1:1", request_timeout=0.5))

    page = MachinesPage(offline)

    assert page.machines == []


def test_refreshing_against_a_dead_server_keeps_the_page_alive(qt_app):
    offline = NixyncClient(Config(server_url="http://127.0.0.1:1", request_timeout=0.5))
    page = MachinesPage(offline)

    page.refresh()

    assert page.machines == []


def test_the_page_reports_why_the_fleet_is_empty(qt_app):
    """Silently showing "no devices" for a network failure would be a lie."""
    offline = NixyncClient(Config(server_url="http://127.0.0.1:1", request_timeout=0.5))

    page = MachinesPage(offline)

    assert page.load_error, "the page records what went wrong"


def test_the_empty_state_does_not_blame_the_filters_for_a_dead_server(qt_app):
    """"No devices match these filters" would send the operator hunting the wrong thing."""
    offline = NixyncClient(Config(server_url="http://127.0.0.1:1", request_timeout=0.5))
    page = MachinesPage(offline)

    page.refresh()

    labels = page.table.cellWidget(0, 0).findChildren(QLabel)
    assert labels, "an empty-state label is rendered"
    assert "Can't reach the server" in labels[0].text()
