import time

import pytest
from fastapi.testclient import TestClient

import server


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("NIXYNC_DB", str(tmp_path / "nixync_test.db"))
    with TestClient(server.app) as test_client:
        yield test_client


def register(client, name: str) -> dict:
    response = client.post("/machines", json={"name": name})
    assert response.status_code == 201
    return response.json()


def test_register_machine_returns_generated_id_and_empty_config(client):
    machine = register(client, "lab-01")

    assert machine["id"]
    assert machine["name"] == "lab-01"
    assert machine["config"] == {
        "packages": [],
        "users": [],
        "groups": [],
        "services": [],
        "settings": {},
    }


def test_registered_machine_is_offline_until_a_socket_connects(client):
    machine = register(client, "lab-01")

    assert machine["online"] is False


def test_list_machines_returns_every_registered_machine(client):
    register(client, "lab-a")
    register(client, "lab-b")

    names = [m["name"] for m in client.get("/machines").json()]

    assert sorted(names) == ["lab-a", "lab-b"]


def test_get_machine_returns_the_requested_machine(client):
    machine = register(client, "lab-01")

    response = client.get(f"/machines/{machine['id']}")

    assert response.status_code == 200
    assert response.json()["id"] == machine["id"]


def test_get_machine_returns_404_for_unknown_id(client):
    response = client.get("/machines/does-not-exist")

    assert response.status_code == 404


def test_delete_machine_removes_it_from_the_fleet(client):
    machine = register(client, "to-delete")

    assert client.delete(f"/machines/{machine['id']}").status_code == 204
    assert client.get(f"/machines/{machine['id']}").status_code == 404


def test_delete_machine_returns_404_for_unknown_id(client):
    response = client.delete("/machines/does-not-exist")

    assert response.status_code == 404


def packages_of(client, machine_id: str) -> list[str]:
    return client.get(f"/machines/{machine_id}").json()["config"]["packages"]


def _acknowledge(client, machine_id: str, apply_id: str, status="applied", message=None) -> None:
    """Close the deployment loop over a socket — the only way to ack a change."""
    with client.websocket_connect(f"/ws/machines/{machine_id}") as websocket:
        websocket.receive_json()  # the pending push, redelivered on connect
        websocket.send_json(
            {"type": "apply_result", "apply_id": apply_id, "status": status, "message": message}
        )
        for _ in range(200):
            if client.get(f"/machines/{machine_id}").json()["last_apply_status"] == status:
                return
            time.sleep(0.01)
    raise AssertionError(f"the {status} acknowledgement was never processed")


def test_adding_packages_to_a_targeted_machine_leaves_others_untouched(client):
    target = register(client, "target")
    bystander = register(client, "bystander")

    response = client.post(
        "/machines/packages",
        json={"action": "add", "packages": ["htop"], "machine_ids": [target["id"]]},
    )

    assert response.status_code == 200
    assert packages_of(client, target["id"]) == ["htop"]
    assert packages_of(client, bystander["id"]) == []


def test_omitting_machine_ids_targets_every_registered_machine(client):
    first = register(client, "first")
    second = register(client, "second")

    client.post("/machines/packages", json={"action": "add", "packages": ["git"]})

    assert packages_of(client, first["id"]) == ["git"]
    assert packages_of(client, second["id"]) == ["git"]


def test_removing_a_package_drops_it_from_the_config(client):
    machine = register(client, "lab-01")
    client.post(
        "/machines/packages",
        json={"action": "add", "packages": ["git", "htop"], "machine_ids": [machine["id"]]},
    )

    client.post(
        "/machines/packages",
        json={"action": "remove", "packages": ["git"], "machine_ids": [machine["id"]]},
    )

    assert packages_of(client, machine["id"]) == ["htop"]


def test_adding_an_already_installed_package_does_not_duplicate_it(client):
    machine = register(client, "lab-01")
    body = {"action": "add", "packages": ["git"], "machine_ids": [machine["id"]]}
    client.post("/machines/packages", json=body)

    client.post("/machines/packages", json=body)

    assert packages_of(client, machine["id"]) == ["git"]


def test_removing_an_absent_package_is_a_no_op(client):
    machine = register(client, "lab-01")

    response = client.post(
        "/machines/packages",
        json={"action": "remove", "packages": ["not-installed"], "machine_ids": [machine["id"]]},
    )

    assert response.status_code == 200
    assert packages_of(client, machine["id"]) == []


def test_a_change_for_a_disconnected_machine_is_reported_as_queued(client):
    machine = register(client, "offline-host")

    response = client.post(
        "/machines/packages",
        json={"action": "add", "packages": ["htop"], "machine_ids": [machine["id"]]},
    )

    result = response.json()["results"][0]
    assert result["machine_id"] == machine["id"]
    assert result["delivery"] == "queued"
    assert result["apply_id"]


def test_a_queued_change_marks_the_machine_as_pending(client):
    machine = register(client, "offline-host")

    client.post(
        "/machines/packages",
        json={"action": "add", "packages": ["htop"], "machine_ids": [machine["id"]]},
    )

    assert client.get(f"/machines/{machine['id']}").json()["last_apply_status"] == "pending"


def test_a_change_a_machine_already_satisfies_is_reported_as_unchanged(client):
    machine = register(client, "already-compliant")
    body = {"action": "add", "packages": ["git"], "machine_ids": [machine["id"]]}
    first_apply_id = client.post("/machines/packages", json=body).json()["results"][0]["apply_id"]
    _acknowledge(client, machine["id"], first_apply_id)

    result = client.post("/machines/packages", json=body).json()["results"][0]

    assert result["delivery"] == "unchanged"
    assert result["apply_id"] == first_apply_id, "no new deployment is created"


def test_a_machine_that_needs_nothing_stays_applied_rather_than_going_pending(client):
    machine = register(client, "already-compliant")
    body = {"action": "add", "packages": ["git"], "machine_ids": [machine["id"]]}
    apply_id = client.post("/machines/packages", json=body).json()["results"][0]["apply_id"]
    _acknowledge(client, machine["id"], apply_id)

    client.post("/machines/packages", json=body)

    assert client.get(f"/machines/{machine['id']}").json()["last_apply_status"] == "applied"


def test_a_machine_whose_last_apply_failed_is_redeployed_even_if_the_config_matches(client):
    """A failed machine is not in its stored state, so it must not be skipped."""
    machine = register(client, "broken-host")
    body = {"action": "add", "packages": ["git"], "machine_ids": [machine["id"]]}
    apply_id = client.post("/machines/packages", json=body).json()["results"][0]["apply_id"]
    _acknowledge(client, machine["id"], apply_id, status="failed", message="build error")

    result = client.post("/machines/packages", json=body).json()["results"][0]

    assert result["delivery"] == "queued"
    assert result["apply_id"] != apply_id, "a fresh deployment is created"


def test_a_machine_with_a_deployment_still_pending_is_redeployed(client):
    machine = register(client, "never-acked")
    body = {"action": "add", "packages": ["git"], "machine_ids": [machine["id"]]}
    first_apply_id = client.post("/machines/packages", json=body).json()["results"][0]["apply_id"]

    result = client.post("/machines/packages", json=body).json()["results"][0]

    assert result["delivery"] == "queued"
    assert result["apply_id"] != first_apply_id


def test_a_machine_that_never_deployed_anything_is_not_treated_as_compliant(client):
    """An empty remove against a fresh machine must still reach it at least once."""
    machine = register(client, "fresh-host")

    result = client.post(
        "/machines/packages",
        json={"action": "remove", "packages": ["absent"], "machine_ids": [machine["id"]]},
    ).json()["results"][0]

    assert result["delivery"] == "queued"


def test_an_unknown_machine_id_in_the_target_list_is_rejected(client):
    response = client.post(
        "/machines/packages",
        json={"action": "add", "packages": ["htop"], "machine_ids": ["does-not-exist"]},
    )

    assert response.status_code == 404


def test_an_unsupported_action_is_rejected(client):
    machine = register(client, "lab-01")

    response = client.post(
        "/machines/packages",
        json={"action": "upgrade", "packages": ["htop"], "machine_ids": [machine["id"]]},
    )

    assert response.status_code == 422


def test_signing_in_with_the_configured_credentials_succeeds(client):
    response = client.post("/login", json={"username": "admin", "password": "password"})

    assert response.status_code == 200
    assert response.json()["username"] == "admin"


def test_a_wrong_password_is_rejected(client):
    response = client.post("/login", json={"username": "admin", "password": "nope"})

    assert response.status_code == 401


def test_an_unknown_username_is_rejected(client):
    response = client.post("/login", json={"username": "root", "password": "password"})

    assert response.status_code == 401


def test_credentials_can_be_overridden_by_environment(monkeypatch, tmp_path):
    """A demo should not need a code change to use a different password."""
    monkeypatch.setenv("NIXYNC_ADMIN_USER", "lab")
    monkeypatch.setenv("NIXYNC_ADMIN_PASSWORD", "s3cret")
    monkeypatch.setenv("NIXYNC_DB", str(tmp_path / "env.db"))

    with TestClient(server.app) as configured:
        assert configured.post(
            "/login", json={"username": "lab", "password": "s3cret"}
        ).status_code == 200
        assert configured.post(
            "/login", json={"username": "admin", "password": "password"}
        ).status_code == 401


def test_saving_system_settings_stores_them_and_queues_a_deployment(client):
    machine = register(client, "settings-host")

    response = client.put(
        f"/machines/{machine['id']}/settings",
        json={"settings": {"hostname": "lab-05", "firewall": True}},
    )

    assert response.status_code == 200
    stored = client.get(f"/machines/{machine['id']}").json()
    assert stored["config"]["settings"] == {"hostname": "lab-05", "firewall": True}
    assert stored["last_apply_status"] == "pending", "the machine must pick the change up"


def test_saving_settings_replaces_rather_than_merges(client):
    """The GUI sends the whole settings object, so a removed key must disappear."""
    machine = register(client, "settings-replace")
    client.put(
        f"/machines/{machine['id']}/settings",
        json={"settings": {"hostname": "old", "bluetooth": True}},
    )

    client.put(f"/machines/{machine['id']}/settings", json={"settings": {"hostname": "new"}})

    assert client.get(f"/machines/{machine['id']}").json()["config"]["settings"] == {
        "hostname": "new"
    }


def test_saving_settings_does_not_disturb_installed_packages(client):
    machine = register(client, "settings-keeps-apps")
    client.post(
        "/machines/packages",
        json={"action": "add", "packages": ["git"], "machine_ids": [machine["id"]]},
    )

    client.put(f"/machines/{machine['id']}/settings", json={"settings": {"hostname": "x"}})

    assert packages_of(client, machine["id"]) == ["git"]


def test_saving_settings_for_an_unknown_machine_returns_404(client):
    response = client.put("/machines/does-not-exist/settings", json={"settings": {}})

    assert response.status_code == 404
