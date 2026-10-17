"""Presets: reusable roles a machine can be assigned to."""

import pytest
from fastapi.testclient import TestClient

import server


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("NIXYNC_DB", str(tmp_path / "presets_test.db"))
    with TestClient(server.app) as test_client:
        yield test_client


def test_a_fresh_server_ships_with_usable_presets(client):
    """An empty preset list would leave the add-device dialog with nothing to pick."""
    names = [p["name"] for p in client.get("/presets").json()]

    assert "Workstation" in names


def test_a_preset_carries_its_bundles_and_apps(client):
    workstation = client.get("/presets/Workstation").json()

    assert [b["name"] for b in workstation["bundles"]]
    assert workstation["extra_apps"]


def test_an_unknown_preset_is_a_404(client):
    assert client.get("/presets/Nonexistent").status_code == 404


def test_creating_a_preset_stores_its_bundles(client):
    body = {
        "name": "Lab kiosk",
        "bundles": [{"name": "Locked desktop", "description": "No shell", "enabled": True}],
        "extra_apps": ["firefox"],
    }

    assert client.put("/presets/Lab kiosk", json=body).status_code == 200

    stored = client.get("/presets/Lab kiosk").json()
    assert stored["extra_apps"] == ["firefox"]
    assert stored["bundles"][0]["name"] == "Locked desktop"


def test_saving_an_existing_preset_replaces_it(client):
    client.put("/presets/Edited", json={"name": "Edited", "extra_apps": ["vim"]})

    client.put("/presets/Edited", json={"name": "Edited", "extra_apps": ["emacs"]})

    assert client.get("/presets/Edited").json()["extra_apps"] == ["emacs"]


def test_the_path_name_wins_over_a_mismatched_body(client):
    """A rename through the body would silently orphan machines pointing at the old name."""
    client.put("/presets/Keep", json={"name": "Renamed", "extra_apps": []})

    assert client.get("/presets/Keep").status_code == 200
    assert client.get("/presets/Renamed").status_code == 404


def test_deleting_an_unused_preset_works(client):
    client.put("/presets/Temporary", json={"name": "Temporary"})

    assert client.delete("/presets/Temporary").status_code == 204
    assert client.get("/presets/Temporary").status_code == 404


def test_a_preset_still_assigned_to_a_machine_cannot_be_deleted(client):
    """Deleting it would leave that machine pointing at a role that does not exist."""
    client.post("/machines", json={"name": "lab-01", "preset": "Workstation"})

    response = client.delete("/presets/Workstation")

    assert response.status_code == 409
    assert "lab-01" in response.json()["detail"]


def test_deleting_an_unknown_preset_is_a_404(client):
    assert client.delete("/presets/Nonexistent").status_code == 404
