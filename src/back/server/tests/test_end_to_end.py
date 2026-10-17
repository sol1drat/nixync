"""End-to-end tests driving a real uvicorn process over real HTTP and real WebSockets.

Everything else in this suite uses Starlette's TestClient, which speaks ASGI directly.
That is fast, but it once hid a real defect: the WebSocket tests passed while uvicorn had
no WebSocket implementation installed and would have rejected every agent at the HTTP
upgrade. These tests spawn an actual server process and talk to it the way the desktop
client and the machine agents will, so that class of bug cannot hide again.
"""

import asyncio
import contextlib
import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest
from websockets.asyncio.client import connect
from websockets.exceptions import ConnectionClosed

SERVER_DIR = Path(__file__).resolve().parent.parent
STARTUP_TIMEOUT_SECONDS = 30
RECEIVE_TIMEOUT_SECONDS = 5
SILENCE_TIMEOUT_SECONDS = 1.5


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


@pytest.fixture(scope="module")
def live_server(tmp_path_factory):
    """A real `uvicorn server:app` process backed by a throwaway database."""
    port = _free_port()
    db_path = tmp_path_factory.mktemp("e2e") / "e2e.db"
    log_path = tmp_path_factory.mktemp("e2e-logs") / "uvicorn.log"

    with open(log_path, "w", encoding="utf-8") as log:
        process = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "server:app", "--port", str(port)],
            cwd=SERVER_DIR,
            env={**os.environ, "NIXYNC_DB": str(db_path)},
            stdout=log,
            stderr=subprocess.STDOUT,
        )

    base_url = f"http://127.0.0.1:{port}"
    try:
        _wait_for_server(process, base_url, log_path)
        yield base_url
    finally:
        process.terminate()
        with contextlib.suppress(subprocess.TimeoutExpired):
            process.wait(timeout=10)


def _wait_for_server(process, base_url: str, log_path: Path) -> None:
    deadline = time.monotonic() + STARTUP_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        if process.poll() is not None:
            pytest.fail(f"server exited early:\n{log_path.read_text()}")
        try:
            if httpx.get(f"{base_url}/machines", timeout=1).status_code == 200:
                return
        except httpx.HTTPError:
            time.sleep(0.1)
    pytest.fail(f"server did not start within {STARTUP_TIMEOUT_SECONDS}s:\n{log_path.read_text()}")


class Fleet:
    """The admin side of the product: plain REST, exactly what the desktop client uses."""

    def __init__(self, base_url: str):
        self.base_url = base_url

    def register(self, name: str) -> str:
        response = httpx.post(f"{self.base_url}/machines", json={"name": name}, timeout=5)
        assert response.status_code == 201, response.text
        return response.json()["id"]

    def machine(self, machine_id: str) -> dict:
        response = httpx.get(f"{self.base_url}/machines/{machine_id}", timeout=5)
        assert response.status_code == 200, response.text
        return response.json()

    def all_machines(self) -> list[dict]:
        return httpx.get(f"{self.base_url}/machines", timeout=5).json()

    def change_packages(self, action: str, packages: list[str], machine_ids=None) -> dict:
        body = {"action": action, "packages": packages, "machine_ids": machine_ids}
        response = httpx.post(f"{self.base_url}/machines/packages", json=body, timeout=5)
        assert response.status_code == 200, response.text
        return {r["machine_id"]: r for r in response.json()["results"]}

    def decommission(self, machine_id: str) -> int:
        return httpx.delete(f"{self.base_url}/machines/{machine_id}", timeout=5).status_code

    def wait_until(self, machine_id: str, predicate, what: str) -> dict:
        """Poll a machine until it reaches an expected state — no arbitrary sleeps."""
        deadline = time.monotonic() + RECEIVE_TIMEOUT_SECONDS
        while time.monotonic() < deadline:
            machine = self.machine(machine_id)
            if predicate(machine):
                return machine
            time.sleep(0.05)
        pytest.fail(f"machine never reached: {what}\nlast seen: {json.dumps(machine, indent=2)}")


class Agent:
    """The machine side of the product: one persistent socket, JSON frames both ways."""

    def __init__(self, websocket):
        self._websocket = websocket

    async def send(self, message: dict) -> None:
        await self._websocket.send(json.dumps(message))

    async def receive(self) -> dict:
        raw = await asyncio.wait_for(self._websocket.recv(), timeout=RECEIVE_TIMEOUT_SECONDS)
        return json.loads(raw)

    async def expect_silence(self) -> None:
        """Assert the server pushes nothing — used to prove acked work is not resent."""
        with pytest.raises(TimeoutError):
            await asyncio.wait_for(self._websocket.recv(), timeout=SILENCE_TIMEOUT_SECONDS)

    async def report_telemetry(self, **metrics) -> None:
        await self.send({"type": "telemetry", **metrics})

    async def report_config(self, **config) -> None:
        await self.send({"type": "config_report", "config": _full_config(**config)})

    async def acknowledge(self, apply_id: str, status: str, message: str | None = None) -> None:
        await self.send(
            {"type": "apply_result", "apply_id": apply_id, "status": status, "message": message}
        )


def _full_config(packages=None, users=None, groups=None, services=None) -> dict:
    return {
        "packages": packages or [],
        "users": users or [],
        "groups": groups or [],
        "services": services or [],
    }


@contextlib.asynccontextmanager
async def connected_agent(base_url: str, machine_id: str):
    ws_url = base_url.replace("http://", "ws://")
    async with connect(f"{ws_url}/ws/machines/{machine_id}") as websocket:
        yield Agent(websocket)


@pytest.fixture
def fleet(live_server) -> Fleet:
    return Fleet(live_server)


# ---------------------------------------------------------------------------
# The headline scenario from CLAUDE.md: a university lab, staged rollout.
# ---------------------------------------------------------------------------


def test_university_lab_staged_rollout_from_registration_to_recovery(fleet, live_server):
    """Walk the whole product story end to end, one documented step at a time."""

    async def scenario():
        # STEP 1 — The admin registers three lab machines. The server owns identity:
        # it mints a UUID for each, which the admin hands to that machine's agent.
        test_box = fleet.register("lab-test-bench")
        desk_01 = fleet.register("lab-desk-01")
        desk_02 = fleet.register("lab-desk-02")
        assert len({test_box, desk_01, desk_02}) == 3, "each machine gets a distinct id"

        # STEP 2 — Before any agent dials in, every machine reads as offline with no
        # metrics and an empty configuration. The dashboard shows an honest "unknown".
        fresh = fleet.machine(test_box)
        assert fresh["online"] is False
        assert fresh["cpu_percent"] is None
        assert fresh["config"]["packages"] == []

        async with connected_agent(live_server, test_box) as bench_agent:
            # STEP 3 — The agent connects and immediately reports the real state of
            # its configuration.nix, so the server reflects the machine as it is.
            await bench_agent.report_config(packages=["git"], users=["student"], services=["sshd"])
            fleet.wait_until(
                test_box,
                lambda m: m["config"]["packages"] == ["git"],
                "config_report is stored",
            )

            # STEP 4 — A live socket is what "online" means. No heartbeat guessing.
            assert fleet.machine(test_box)["online"] is True

            # STEP 5 — The agent reports resource usage (every 2 min in production).
            await bench_agent.report_telemetry(
                cpu_percent=18.5,
                ram_used_mb=2048,
                ram_total_mb=16384,
                disk_used_gb=95.5,
                disk_total_gb=512.0,
            )
            metrics = fleet.wait_until(
                test_box, lambda m: m["cpu_percent"] == 18.5, "telemetry is stored"
            )
            assert metrics["ram_used_mb"] == 2048
            assert metrics["disk_used_gb"] == 95.5
            assert metrics["metrics_reported_at"] is not None, "reported_at is stamped"

            # STEP 6 — Staged rollout, stage one: the admin applies the dev-tools
            # preset to the single test bench before touching the lab.
            results = fleet.change_packages("add", ["neovim", "gcc"], machine_ids=[test_box])
            assert results[test_box]["delivery"] == "pushed", "a live agent gets it immediately"
            apply_id = results[test_box]["apply_id"]

            # STEP 7 — The push carries the FULL desired config, not a diff. The agent
            # reconciles whole state, so a machine cannot silently drift.
            pushed = await bench_agent.receive()
            assert pushed["type"] == "apply_config"
            assert pushed["apply_id"] == apply_id
            assert pushed["config"]["packages"] == ["gcc", "git", "neovim"]
            assert pushed["config"]["services"] == ["sshd"], "unrelated config is preserved"

            # STEP 8 — Until the agent reports back, the admin sees work in flight
            # rather than a false success.
            assert fleet.machine(test_box)["last_apply_status"] == "pending"

            # STEP 9 — The agent builds and activates, then acks. Only now is it "applied".
            await bench_agent.acknowledge(apply_id, "applied")
            fleet.wait_until(
                test_box,
                lambda m: m["last_apply_status"] == "applied",
                "the successful activation is recorded",
            )

        # STEP 10 — Stage two: the test bench proved the change, so roll it out to the
        # whole lab. Omitting machine_ids targets every registered machine at once.
        async with connected_agent(live_server, desk_01) as desk_01_agent:
            # desk-02 is deliberately left powered off to prove the queue works.
            rollout = fleet.change_packages("add", ["neovim", "gcc"])
            assert len(rollout) == 3, "a fleet-wide change reaches every machine"
            assert rollout[desk_01]["delivery"] == "pushed", "online machines get it now"
            assert rollout[desk_02]["delivery"] == "queued", "offline machines are not lost"
            # The test bench already proved this exact config, so it is left alone
            # instead of being dragged back to 'pending' for a no-op deployment.
            assert rollout[test_box]["delivery"] == "unchanged"

            # STEP 11 — This lab machine fails to build. The admin needs the reason,
            # not just a red dot.
            failed_push = await desk_01_agent.receive()
            await desk_01_agent.acknowledge(
                failed_push["apply_id"], "failed", "error: gcc collision in /nix/store"
            )
            broken = fleet.wait_until(
                desk_01,
                lambda m: m["last_apply_status"] == "failed",
                "the failure is recorded",
            )
            assert broken["last_apply_message"] == "error: gcc collision in /nix/store"

        # STEP 12 — Per-machine results: one fleet-wide request, three different
        # outcomes, each attributable to its own machine.
        by_id = {m["id"]: m for m in fleet.all_machines()}
        assert by_id[test_box]["last_apply_status"] == "applied", "untouched, so still green"
        assert by_id[desk_01]["last_apply_status"] == "failed"
        assert by_id[desk_02]["last_apply_status"] == "pending", "still waiting to be delivered"

        # STEP 13 — Recovery for the machine that was switched off: it boots, connects,
        # and the server delivers the change it missed. The admin re-requests nothing.
        async with connected_agent(live_server, desk_02) as desk_02_agent:
            redelivered = await desk_02_agent.receive()
            assert redelivered["type"] == "apply_config"
            assert redelivered["config"]["packages"] == ["gcc", "neovim"]
            await desk_02_agent.acknowledge(redelivered["apply_id"], "applied")
            fleet.wait_until(
                desk_02,
                lambda m: m["last_apply_status"] == "applied",
                "the late machine catches up",
            )

            # STEP 14 — Acked work is not resent. Reconnecting does not re-deploy.
            await desk_02_agent.expect_silence()

        # STEP 15 — The admin rolls the lab back by removing a package fleet-wide.
        fleet.change_packages("remove", ["gcc"])
        assert fleet.machine(test_box)["config"]["packages"] == ["git", "neovim"]
        assert fleet.machine(desk_02)["config"]["packages"] == ["neovim"]

        # STEP 16 — A decommissioned machine leaves the fleet entirely.
        assert fleet.decommission(desk_02) == 204
        assert httpx.get(f"{live_server}/machines/{desk_02}", timeout=5).status_code == 404
        assert desk_02 not in {m["id"] for m in fleet.all_machines()}

    asyncio.run(scenario())


# ---------------------------------------------------------------------------
# Focused end-to-end checks for behaviour that only a real socket can prove.
# ---------------------------------------------------------------------------


def test_an_unregistered_machine_cannot_open_a_socket(fleet, live_server):
    """An agent with an unknown id is closed with 4404 — registration comes first."""

    async def scenario():
        ws_url = live_server.replace("http://", "ws://")
        with pytest.raises(ConnectionClosed) as rejection:
            async with connect(f"{ws_url}/ws/machines/not-a-real-machine") as websocket:
                await asyncio.wait_for(websocket.recv(), timeout=RECEIVE_TIMEOUT_SECONDS)

        assert rejection.value.rcvd.code == 4404

    asyncio.run(scenario())


def test_a_machine_goes_offline_the_moment_its_agent_disconnects(fleet, live_server):
    machine_id = fleet.register("flaky-laptop")

    async def scenario():
        async with connected_agent(live_server, machine_id):
            assert fleet.machine(machine_id)["online"] is True

        fleet.wait_until(machine_id, lambda m: m["online"] is False, "machine reads offline")

    asyncio.run(scenario())


def test_a_stale_acknowledgement_cannot_overwrite_a_newer_deployment(fleet, live_server):
    """A slow agent acking a superseded push must not mark newer work as done."""
    machine_id = fleet.register("slow-acker")

    async def scenario():
        async with connected_agent(live_server, machine_id) as agent:
            first = fleet.change_packages("add", ["htop"], machine_ids=[machine_id])
            superseded_apply_id = first[machine_id]["apply_id"]
            await agent.receive()

            # A second change supersedes the first before the agent gets around to it.
            fleet.change_packages("add", ["vim"], machine_ids=[machine_id])
            await agent.receive()

            await agent.acknowledge(superseded_apply_id, "applied")
            await asyncio.sleep(0.3)

            assert fleet.machine(machine_id)["last_apply_status"] == "pending"

    asyncio.run(scenario())


def test_decommissioning_a_machine_disconnects_its_live_agent(fleet, live_server):
    machine_id = fleet.register("retired-desktop")

    async def scenario():
        async with connected_agent(live_server, machine_id) as agent:
            assert fleet.decommission(machine_id) == 204

            with pytest.raises(ConnectionClosed):
                await asyncio.wait_for(agent._websocket.recv(), timeout=RECEIVE_TIMEOUT_SECONDS)

    asyncio.run(scenario())


def test_repeating_a_package_add_does_not_duplicate_it(fleet, live_server):
    machine_id = fleet.register("idempotency-host")

    fleet.change_packages("add", ["git"], machine_ids=[machine_id])
    fleet.change_packages("add", ["git"], machine_ids=[machine_id])

    assert fleet.machine(machine_id)["config"]["packages"] == ["git"]


def test_a_change_targeting_an_unknown_machine_is_rejected_outright(fleet, live_server):
    """A typo in one id fails the request rather than half-applying the change."""
    real_machine = fleet.register("real-host")
    before = fleet.machine(real_machine)["config"]["packages"]

    response = httpx.post(
        f"{live_server}/machines/packages",
        json={"action": "add", "packages": ["htop"], "machine_ids": [real_machine, "ghost-host"]},
        timeout=5,
    )

    assert response.status_code == 404
    assert fleet.machine(real_machine)["config"]["packages"] == before, "no partial application"


def test_the_interactive_docs_and_schema_are_served(live_server):
    """The desktop client team gets a live contract, not a stale copy."""
    assert httpx.get(f"{live_server}/docs", timeout=5).status_code == 200

    schema = httpx.get(f"{live_server}/openapi.json", timeout=5).json()
    assert schema["openapi"].startswith("3.")
    assert "/machines/packages" in schema["paths"]
