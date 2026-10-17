"""App requests: a device user asks, an admin decides."""

import pytest
from fastapi.testclient import TestClient

import server


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("NIXYNC_DB", str(tmp_path / "requests_test.db"))
    with TestClient(server.app) as test_client:
        yield test_client


@pytest.fixture
def machine(client) -> dict:
    return client.post("/machines", json={"name": "lab-01"}).json()


def ask(client, machine, app="blender", by="student14", reason="for coursework") -> dict:
    response = client.post(
        "/requests",
        json={"machine_id": machine["id"], "app": app, "requested_by": by, "reason": reason},
    )
    assert response.status_code == 201, response.text
    return response.json()


def packages_of(client, machine) -> list[str]:
    return client.get(f"/machines/{machine['id']}").json()["config"]["packages"]


def test_a_request_starts_pending_and_deploys_nothing(client, machine):
    request = ask(client, machine)

    assert request["status"] == "pending"
    assert request["app"] == "blender"
    assert packages_of(client, machine) == [], "asking is not installing"


def test_a_request_carries_the_device_name_not_just_its_id(client, machine):
    """The admin's list has to read as devices, not opaque ids."""
    assert ask(client, machine)["machine_name"] == "lab-01"


def test_requests_are_listed_newest_first(client, machine):
    ask(client, machine, app="first")
    ask(client, machine, app="second")

    assert [r["app"] for r in client.get("/requests").json()] == ["second", "first"]


def test_requests_can_be_narrowed_to_one_device(client, machine):
    other = client.post("/machines", json={"name": "lab-02"}).json()
    ask(client, machine, app="blender")
    ask(client, other, app="vlc")

    mine = client.get("/requests", params={"machine_id": machine["id"]}).json()

    assert [r["app"] for r in mine] == ["blender"]


def test_a_request_for_an_unknown_machine_is_refused(client):
    response = client.post(
        "/requests",
        json={"machine_id": "ghost", "app": "blender", "requested_by": "x"},
    )

    assert response.status_code == 404


def test_approving_deploys_the_app_to_that_machine(client, machine):
    request = ask(client, machine)

    approved = client.post(f"/requests/{request['id']}/approve").json()

    assert approved["status"] == "approved"
    assert approved["decided_at"]
    assert packages_of(client, machine) == ["blender"]


def test_approving_for_an_offline_machine_queues_like_any_other_change(client, machine):
    request = ask(client, machine)

    client.post(f"/requests/{request['id']}/approve")

    assert client.get(f"/machines/{machine['id']}").json()["last_apply_status"] == "pending"


def test_declining_deploys_nothing(client, machine):
    request = ask(client, machine)

    declined = client.post(f"/requests/{request['id']}/decline").json()

    assert declined["status"] == "declined"
    assert packages_of(client, machine) == []


def test_deciding_twice_is_refused_rather_than_redeployed(client, machine):
    """A double click must not look like it worked when it did nothing."""
    request = ask(client, machine)
    client.post(f"/requests/{request['id']}/approve")

    second = client.post(f"/requests/{request['id']}/approve")

    assert second.status_code == 409
    assert "already approved" in second.json()["detail"]


def test_a_declined_request_cannot_then_be_approved(client, machine):
    request = ask(client, machine)
    client.post(f"/requests/{request['id']}/decline")

    assert client.post(f"/requests/{request['id']}/approve").status_code == 409


def test_deciding_an_unknown_request_is_a_404(client):
    assert client.post("/requests/999/approve").status_code == 404
    assert client.post("/requests/999/decline").status_code == 404


def test_approving_for_a_machine_that_has_since_been_removed_is_refused(client, machine):
    """The request outlives the device; approving it has nowhere to deploy."""
    request = ask(client, machine)
    client.delete(f"/machines/{machine['id']}")

    response = client.post(f"/requests/{request['id']}/approve")

    assert response.status_code == 409
    assert "no longer in the fleet" in response.json()["detail"]


def test_approving_adds_to_what_the_machine_already_has(client, machine):
    client.post(
        "/machines/packages",
        json={"action": "add", "packages": ["git"], "machine_ids": [machine["id"]]},
    )
    request = ask(client, machine, app="blender")

    client.post(f"/requests/{request['id']}/approve")

    assert sorted(packages_of(client, machine)) == ["blender", "git"]
