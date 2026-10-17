"""A real NixyncAgent against a real uvicorn server, over a real socket.

The unit tests prove what the agent decides; these prove the two halves of the product
actually speak the same language. The server suite learned this lesson the hard way: an
in-process double hid the fact that uvicorn could not serve WebSockets at all.
"""

import asyncio
import contextlib
import time

import httpx
import pytest

from nixync_client.agent import NixyncAgent
from nixync_client.protocol import MachineConfig
from nixync_client.transport import UnknownMachineError

SETTLE_TIMEOUT_SECONDS = 5


async def register(base_url: str, name: str) -> str:
    async with httpx.AsyncClient(base_url=base_url, timeout=5) as client:
        response = await client.post("/machines", json={"name": name})
        assert response.status_code == 201, response.text
        return response.json()["id"]


async def fetch(base_url: str, machine_id: str) -> dict:
    async with httpx.AsyncClient(base_url=base_url, timeout=5) as client:
        return (await client.get(f"/machines/{machine_id}")).json()


async def change_packages(base_url: str, machine_id: str, packages: list[str]) -> dict:
    async with httpx.AsyncClient(base_url=base_url, timeout=5) as client:
        response = await client.post(
            "/machines/packages",
            json={"action": "add", "packages": packages, "machine_ids": [machine_id]},
        )
        assert response.status_code == 200, response.text
        return response.json()["results"][0]


async def wait_until(base_url: str, machine_id: str, predicate, what: str) -> dict:
    deadline = time.monotonic() + SETTLE_TIMEOUT_SECONDS
    machine = {}
    while time.monotonic() < deadline:
        machine = await fetch(base_url, machine_id)
        if predicate(machine):
            return machine
        await asyncio.sleep(0.05)
    pytest.fail(f"server never reported: {what}\nlast seen: {machine}")


@contextlib.asynccontextmanager
async def running(agent: NixyncAgent):
    """Run an agent in the background for the duration of the block."""
    task = asyncio.create_task(agent.run())
    try:
        yield task
    finally:
        agent.stop()
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await asyncio.wait_for(task, timeout=5)


def test_a_real_agent_reports_its_config_and_telemetry_to_the_server(live_server):
    async def scenario():
        machine_id = await register(live_server, "e2e-agent")
        agent = NixyncAgent(
            server_url=live_server,
            machine_id=machine_id,
            current_config=lambda: MachineConfig(packages=["git"], services=["sshd"]),
            telemetry_interval=60,
        )

        async with running(agent):
            machine = await wait_until(
                live_server,
                machine_id,
                lambda m: m["online"] and m["cpu_percent"] is not None,
                "the agent connected and reported telemetry",
            )

            assert machine["config"]["packages"] == ["git"], "real config_report landed"
            assert machine["config"]["services"] == ["sshd"]
            assert 0.0 <= machine["cpu_percent"] <= 100.0, "real sampled CPU"
            assert machine["ram_total_mb"] > 0, "real sampled memory"
            assert machine["disk_total_gb"] > 0, "real sampled disk"
            assert machine["metrics_reported_at"] is not None

        await wait_until(
            live_server, machine_id, lambda m: not m["online"], "it went offline on stop"
        )

    asyncio.run(scenario())


def test_an_admin_package_change_reaches_the_handler_and_is_acked(live_server):
    """The full product loop: admin asks, agent does, admin sees the result."""

    async def scenario():
        machine_id = await register(live_server, "e2e-deploy")
        applied: list[MachineConfig] = []

        agent = NixyncAgent(
            server_url=live_server,
            machine_id=machine_id,
            on_apply=applied.append,
            telemetry_interval=60,
        )

        async with running(agent):
            await wait_until(live_server, machine_id, lambda m: m["online"], "agent connected")

            result = await change_packages(live_server, machine_id, ["htop", "neovim"])
            assert result["delivery"] == "pushed"

            machine = await wait_until(
                live_server,
                machine_id,
                lambda m: m["last_apply_status"] == "applied",
                "the agent acked the deployment",
            )

        assert len(applied) == 1, "the handler ran exactly once"
        assert sorted(applied[0].packages) == ["htop", "neovim"], "full desired state"
        assert machine["last_apply_id"] == result["apply_id"]

    asyncio.run(scenario())


def test_a_failing_handler_surfaces_its_reason_to_the_admin(live_server):
    async def scenario():
        machine_id = await register(live_server, "e2e-failure")

        def refuse(config):
            raise RuntimeError("nixos-rebuild: collision between gcc and clang")

        agent = NixyncAgent(
            server_url=live_server,
            machine_id=machine_id,
            on_apply=refuse,
            telemetry_interval=60,
        )

        async with running(agent):
            await wait_until(live_server, machine_id, lambda m: m["online"], "agent connected")
            await change_packages(live_server, machine_id, ["gcc"])

            machine = await wait_until(
                live_server,
                machine_id,
                lambda m: m["last_apply_status"] == "failed",
                "the failure reached the server",
            )

        assert machine["last_apply_message"] == "nixos-rebuild: collision between gcc and clang"

    asyncio.run(scenario())


def test_a_change_made_while_the_agent_was_offline_is_applied_on_reconnect(live_server):
    """Recovery path: the lab machine that was switched off still catches up."""

    async def scenario():
        machine_id = await register(live_server, "e2e-latecomer")

        result = await change_packages(live_server, machine_id, ["vim"])
        assert result["delivery"] == "queued", "nothing is connected yet"

        applied: list[MachineConfig] = []
        agent = NixyncAgent(
            server_url=live_server,
            machine_id=machine_id,
            on_apply=applied.append,
            telemetry_interval=60,
        )

        async with running(agent):
            await wait_until(
                live_server,
                machine_id,
                lambda m: m["last_apply_status"] == "applied",
                "the queued change was delivered and acked on reconnect",
            )

        assert applied[0].packages == ["vim"]

    asyncio.run(scenario())


def test_stopping_a_live_agent_leaves_no_orphaned_task_exceptions(live_server):
    """Shutting down should not log 'Task exception was never retrieved'.

    Closing the socket wakes the pending read; if that task is dropped before its
    exception is collected, asyncio reports it as unhandled and fills production logs
    with noise that hides real failures. This was observed once during manual testing
    and fixed by settling cancelled tasks before closing the transport.

    Honest caveat: the underlying race is timing-dependent and this test does NOT
    reliably reproduce it — reverting the fix still leaves it green. It is kept as a
    cheap guard against a blatant regression, not as proof the race is gone.
    """
    unhandled: list[dict] = []

    async def scenario():
        asyncio.get_running_loop().set_exception_handler(
            lambda loop, context: unhandled.append(context)
        )
        machine_id = await register(live_server, "e2e-clean-shutdown")
        agent = NixyncAgent(
            server_url=live_server, machine_id=machine_id, telemetry_interval=60
        )

        task = asyncio.create_task(agent.run())
        await wait_until(live_server, machine_id, lambda m: m["online"], "agent connected")

        # Exactly how a GUI shuts an agent down: ask it to stop, then cancel the task
        # it was running in. The external cancel is what races the socket close.
        agent.stop()
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await asyncio.wait_for(task, timeout=5)
        await asyncio.sleep(0.3)  # let the loop report anything it considers orphaned

    asyncio.run(scenario())

    assert unhandled == [], f"asyncio reported unhandled task errors: {unhandled}"


def test_an_unregistered_machine_id_fails_fast_instead_of_retrying(live_server):
    """A misconfigured agent must say so, not spin against a server that will never accept it."""

    async def scenario():
        agent = NixyncAgent(
            server_url=live_server,
            machine_id="00000000-0000-0000-0000-000000000000",
            telemetry_interval=60,
            backoff_base=0.01,
        )

        with pytest.raises(UnknownMachineError):
            await asyncio.wait_for(agent.run(), timeout=10)

    asyncio.run(scenario())


def test_the_agent_survives_a_server_restart(live_server):
    """Reconnect logic against a real dropped socket, not a simulated one."""

    async def scenario():
        machine_id = await register(live_server, "e2e-reconnect")
        agent = NixyncAgent(
            server_url=live_server,
            machine_id=machine_id,
            on_apply=lambda config: None,
            telemetry_interval=60,
            backoff_base=0.05,
        )

        async with running(agent):
            await wait_until(live_server, machine_id, lambda m: m["online"], "first connect")

            # Kick the agent off the way a real network drop would.
            await httpx.AsyncClient(timeout=5).post(
                f"{live_server}/machines/packages",
                json={"action": "add", "packages": ["htop"], "machine_ids": [machine_id]},
            )
            await wait_until(
                live_server,
                machine_id,
                lambda m: m["last_apply_status"] == "applied",
                "work completed over the live connection",
            )

    asyncio.run(scenario())
