import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

import server


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("NIXYNC_DB", str(tmp_path / "nixync_test.db"))
    with TestClient(server.app) as test_client:
        yield test_client


def register(client, name: str) -> str:
    response = client.post("/machines", json={"name": name})
    assert response.status_code == 201
    return response.json()["id"]


def test_connecting_with_an_unregistered_id_is_rejected(client):
    with pytest.raises(WebSocketDisconnect) as rejection:
        with client.websocket_connect("/ws/machines/does-not-exist") as websocket:
            websocket.receive_json()

    assert rejection.value.code == 4404


def test_a_connected_machine_is_reported_online(client):
    machine_id = register(client, "lab-01")

    with client.websocket_connect(f"/ws/machines/{machine_id}"):
        assert client.get(f"/machines/{machine_id}").json()["online"] is True


def test_a_machine_is_reported_offline_after_disconnecting(client):
    machine_id = register(client, "lab-01")

    with client.websocket_connect(f"/ws/machines/{machine_id}"):
        pass

    assert client.get(f"/machines/{machine_id}").json()["online"] is False


def test_telemetry_message_updates_the_stored_metrics(client):
    machine_id = register(client, "lab-01")

    with client.websocket_connect(f"/ws/machines/{machine_id}") as websocket:
        websocket.send_json(
            {
                "type": "telemetry",
                "cpu_percent": 37.5,
                "ram_used_mb": 4096,
                "ram_total_mb": 16384,
                "disk_used_gb": 210.5,
                "disk_total_gb": 512.0,
            }
        )
        # Round-trip a second message so the first is guaranteed processed.
        websocket.send_json({"type": "ping"})
        machine = client.get(f"/machines/{machine_id}").json()

    assert machine["cpu_percent"] == 37.5
    assert machine["ram_used_mb"] == 4096
    assert machine["ram_total_mb"] == 16384
    assert machine["disk_used_gb"] == 210.5
    assert machine["disk_total_gb"] == 512.0
    assert machine["metrics_reported_at"] is not None


def test_config_report_records_what_the_machine_has_and_enrolls_it(client):
    """A machine joining the fleet brings its existing setup with it.

    The report is always stored as `reported_config`. Because this machine has never
    been deployed to, it is also adopted as the desired config — see
    `test_a_booting_machines_report_does_not_erase_a_change_queued_for_it` for the
    case where the admin has already declared intent.
    """
    machine_id = register(client, "lab-01")

    with client.websocket_connect(f"/ws/machines/{machine_id}") as websocket:
        websocket.send_json(
            {
                "type": "config_report",
                "config": {
                    "packages": ["git", "vim"],
                    "users": ["alice"],
                    "groups": ["wheel"],
                    "services": ["sshd"],
                },
            }
        )
        websocket.send_json({"type": "ping"})
        machine = client.get(f"/machines/{machine_id}").json()

    assert machine["reported_config"]["packages"] == ["git", "vim"]
    assert machine["reported_config"]["users"] == ["alice"]
    assert machine["reported_config"]["groups"] == ["wheel"]
    assert machine["reported_config"]["services"] == ["sshd"]
    assert machine["config"]["packages"] == ["git", "vim"], "adopted on enrollment"


def test_a_booting_machines_report_does_not_erase_a_change_queued_for_it(client):
    """Regression: an honest report of 'I have nothing' must not cancel pending work.

    The machine boots into queued work, reports its real (empty) state, then applies.
    The desired config must survive that report, or the dashboard ends up showing an
    empty package list beside a green 'applied' badge.
    """
    machine_id = register(client, "lab-01")
    queue_package_add(client, machine_id, "gcc")

    with client.websocket_connect(f"/ws/machines/{machine_id}") as websocket:
        pushed = websocket.receive_json()
        websocket.send_json(
            {"type": "config_report", "config": {"packages": [], "users": [], "groups": [], "services": []}}
        )
        websocket.send_json({"type": "ping"})
        machine = client.get(f"/machines/{machine_id}").json()

    assert pushed["config"]["packages"] == ["gcc"], "the queued change was still delivered"
    assert machine["config"]["packages"] == ["gcc"], "and the desired config survived"
    assert machine["reported_config"]["packages"] == []


def test_a_package_change_is_pushed_to_a_connected_machine(client):
    machine_id = register(client, "lab-01")

    with client.websocket_connect(f"/ws/machines/{machine_id}") as websocket:
        response = client.post(
            "/machines/packages",
            json={"action": "add", "packages": ["htop"], "machine_ids": [machine_id]},
        )
        pushed = websocket.receive_json()

    assert response.json()["results"][0]["delivery"] == "pushed"
    assert pushed["type"] == "apply_config"
    assert pushed["apply_id"] == response.json()["results"][0]["apply_id"]
    assert pushed["config"]["packages"] == ["htop"]


def queue_package_add(client, machine_id: str, package: str) -> str:
    response = client.post(
        "/machines/packages",
        json={"action": "add", "packages": [package], "machine_ids": [machine_id]},
    )
    assert response.status_code == 200
    return response.json()["results"][0]["apply_id"]


def test_apply_result_records_a_successful_activation(client):
    machine_id = register(client, "lab-01")

    with client.websocket_connect(f"/ws/machines/{machine_id}") as websocket:
        apply_id = queue_package_add(client, machine_id, "htop")
        websocket.receive_json()

        websocket.send_json({"type": "apply_result", "apply_id": apply_id, "status": "applied"})
        websocket.send_json({"type": "ping"})
        machine = client.get(f"/machines/{machine_id}").json()

    assert machine["last_apply_status"] == "applied"
    assert machine["last_apply_at"] is not None


def test_apply_result_records_a_failure_with_its_reason(client):
    machine_id = register(client, "lab-01")

    with client.websocket_connect(f"/ws/machines/{machine_id}") as websocket:
        apply_id = queue_package_add(client, machine_id, "htop")
        websocket.receive_json()

        websocket.send_json(
            {
                "type": "apply_result",
                "apply_id": apply_id,
                "status": "failed",
                "message": "nixos-rebuild exited 1",
            }
        )
        websocket.send_json({"type": "ping"})
        machine = client.get(f"/machines/{machine_id}").json()

    assert machine["last_apply_status"] == "failed"
    assert machine["last_apply_message"] == "nixos-rebuild exited 1"


def test_a_stale_apply_result_is_ignored(client):
    machine_id = register(client, "lab-01")

    with client.websocket_connect(f"/ws/machines/{machine_id}") as websocket:
        queue_package_add(client, machine_id, "htop")
        websocket.receive_json()

        websocket.send_json(
            {"type": "apply_result", "apply_id": "superseded-apply-id", "status": "applied"}
        )
        websocket.send_json({"type": "ping"})
        machine = client.get(f"/machines/{machine_id}").json()

    assert machine["last_apply_status"] == "pending"


def test_a_change_queued_while_offline_is_delivered_on_reconnect(client):
    machine_id = register(client, "lab-01")

    apply_id = queue_package_add(client, machine_id, "htop")

    with client.websocket_connect(f"/ws/machines/{machine_id}") as websocket:
        pushed = websocket.receive_json()

    assert pushed["type"] == "apply_config"
    assert pushed["apply_id"] == apply_id
    assert pushed["config"]["packages"] == ["htop"]


def test_an_acknowledged_change_is_not_redelivered_on_reconnect(client):
    machine_id = register(client, "lab-01")
    apply_id = queue_package_add(client, machine_id, "htop")

    with client.websocket_connect(f"/ws/machines/{machine_id}") as websocket:
        websocket.receive_json()
        websocket.send_json({"type": "apply_result", "apply_id": apply_id, "status": "applied"})
        websocket.send_json({"type": "ping"})

    with client.websocket_connect(f"/ws/machines/{machine_id}") as websocket:
        websocket.send_json({"type": "ping"})
        # Nothing pending, so the only way out of the socket is the server closing it.
        with pytest.raises(WebSocketDisconnect):
            client.delete(f"/machines/{machine_id}")
            websocket.receive_json()


def test_deleting_a_machine_closes_its_open_socket(client):
    machine_id = register(client, "lab-01")

    with client.websocket_connect(f"/ws/machines/{machine_id}") as websocket:
        assert client.delete(f"/machines/{machine_id}").status_code == 204

        with pytest.raises(WebSocketDisconnect):
            websocket.receive_json()
