"""The agent daemon against a real server and a temp filesystem.

Nothing here touches /etc or runs nixos-rebuild: the writer is pointed at a temp
directory and the rebuild is faked, exactly as in test_system.py.
"""

import asyncio
import contextlib
import subprocess
import time
from pathlib import Path

import httpx
import pytest

from nixync_agent import settings as agent_settings
from nixync_agent.daemon import build_agent, run
from nixync_agent.settings import AgentSettings, ConfigurationError

SETTLE_TIMEOUT_SECONDS = 5


def fake_rebuild(returncode: int = 0, stderr: str = ""):
    """Stands in for nixos-rebuild.

    Passed to SystemWriter explicitly rather than patched onto the subprocess module:
    a patch applied after import does not reach a default argument, and the test
    would quietly run a real rebuild.
    """

    def run(command, **kwargs):
        return subprocess.CompletedProcess(command, returncode, "", stderr)

    return run


def writer_for(etc: Path, returncode: int = 0, stderr: str = "", dry_run: bool = False):
    from nixync_agent.system import SystemWriter

    return SystemWriter(
        config_dir=etc, run=fake_rebuild(returncode, stderr), dry_run=dry_run
    )


@pytest.fixture
def etc(tmp_path) -> Path:
    (tmp_path / "configuration.nix").write_text(
        "{ config, pkgs, ... }:\n\n{\n  imports = [ ./hardware-configuration.nix ];\n}\n"
    )
    return tmp_path


def register(live_server: str, name: str) -> str:
    response = httpx.post(f"{live_server}/machines", json={"name": name}, timeout=5)
    assert response.status_code == 201
    return response.json()["id"]


def machine(live_server: str, machine_id: str) -> dict:
    return httpx.get(f"{live_server}/machines/{machine_id}", timeout=5).json()


async def wait_until(live_server, machine_id, predicate, what):
    deadline = time.monotonic() + SETTLE_TIMEOUT_SECONDS
    seen = None
    while time.monotonic() < deadline:
        seen = await asyncio.to_thread(machine, live_server, machine_id)
        if predicate(seen):
            return seen
        await asyncio.sleep(0.05)
    pytest.fail(f"never reached: {what}\nlast seen: {seen}")


@contextlib.asynccontextmanager
async def running(agent):
    task = asyncio.create_task(agent.run())
    try:
        yield agent
    finally:
        agent.stop()
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await asyncio.wait_for(task, timeout=5)


# -- settings ---------------------------------------------------------------


def test_settings_come_from_the_file(tmp_path):
    path = tmp_path / "agent.toml"
    path.write_text('server_url = "http://host:8000"\nmachine_id = "abc"\n')

    config = agent_settings.load(path)

    assert config.server_url == "http://host:8000"
    assert config.machine_id == "abc"


def test_explicit_arguments_beat_the_file(tmp_path):
    path = tmp_path / "agent.toml"
    path.write_text('server_url = "http://file:8000"\nmachine_id = "from-file"\n')

    config = agent_settings.load(path, server_url="http://flag:9000")

    assert config.server_url == "http://flag:9000"
    assert config.machine_id == "from-file", "untouched keys still come from the file"


def test_a_missing_server_url_names_the_flag_that_would_fix_it(tmp_path):
    """An error telling you to pass an option that does not exist is worse than none."""
    with pytest.raises(ConfigurationError, match=r"--server\b"):
        agent_settings.load(tmp_path / "absent.toml", machine_id="abc")


def test_a_missing_machine_id_is_an_error_not_a_default(tmp_path):
    with pytest.raises(ConfigurationError, match="--machine-id"):
        agent_settings.load(tmp_path / "absent.toml", server_url="http://host:8000")


# -- the daemon against a real server ---------------------------------------


def test_the_daemon_reports_this_machine_to_the_server(live_server, etc):
    machine_id = register(live_server, "daemon-telemetry")
    config = AgentSettings(live_server, machine_id, telemetry_interval=60, config_dir=etc)

    async def scenario():
        async with running(build_agent(config)):
            return await wait_until(
                live_server, machine_id,
                lambda m: m["online"] and m["cpu_percent"] is not None,
                "the daemon connected and reported",
            )

    seen = asyncio.run(scenario())
    assert 0.0 <= seen["cpu_percent"] <= 100.0
    assert seen["ram_total_mb"] > 0


def test_a_deployment_is_written_to_the_machine_as_nix(live_server, etc):
    """The whole point: a package added on the server becomes Nix on the device."""
    machine_id = register(live_server, "daemon-deploy")
    config = AgentSettings(live_server, machine_id, telemetry_interval=60, config_dir=etc)

    async def scenario():
        async with running(build_agent(config, writer_for(etc))):
            await wait_until(live_server, machine_id, lambda m: m["online"], "connected")
            await asyncio.to_thread(
                httpx.post, f"{live_server}/machines/packages",
                json={"action": "add", "packages": ["htop"], "machine_ids": [machine_id]},
                timeout=5,
            )
            return await wait_until(
                live_server, machine_id,
                lambda m: m["last_apply_status"] == "applied",
                "the daemon applied and acked",
            )

    asyncio.run(scenario())

    written = (etc / "nixync.nix").read_text()
    assert "htop" in written
    assert "./nixync.nix" in (etc / "configuration.nix").read_text()


def test_a_failed_rebuild_reaches_the_server_as_the_reason(live_server, etc):
    machine_id = register(live_server, "daemon-failure")
    config = AgentSettings(live_server, machine_id, telemetry_interval=60, config_dir=etc)
    broken = writer_for(etc, returncode=1, stderr="error: undefined variable 'htp'")

    async def scenario():
        async with running(build_agent(config, broken)):
            await wait_until(live_server, machine_id, lambda m: m["online"], "connected")
            await asyncio.to_thread(
                httpx.post, f"{live_server}/machines/packages",
                json={"action": "add", "packages": ["htp"], "machine_ids": [machine_id]},
                timeout=5,
            )
            return await wait_until(
                live_server, machine_id,
                lambda m: m["last_apply_status"] == "failed",
                "the failure reached the server",
            )

    seen = asyncio.run(scenario())
    assert "undefined variable" in seen["last_apply_message"]


def test_a_dry_run_writes_nothing(live_server, etc):
    machine_id = register(live_server, "daemon-dry")
    config = AgentSettings(
        live_server, machine_id, telemetry_interval=60, config_dir=etc, dry_run=True
    )

    async def scenario():
        async with running(build_agent(config)):
            await wait_until(live_server, machine_id, lambda m: m["online"], "connected")
            await asyncio.to_thread(
                httpx.post, f"{live_server}/machines/packages",
                json={"action": "add", "packages": ["htop"], "machine_ids": [machine_id]},
                timeout=5,
            )
            await wait_until(
                live_server, machine_id,
                lambda m: m["last_apply_status"] == "applied",
                "the daemon acked without doing anything",
            )

    asyncio.run(scenario())

    assert not (etc / "nixync.nix").exists()
    assert "./nixync.nix" not in (etc / "configuration.nix").read_text()


def test_an_unregistered_machine_exits_rather_than_retrying_forever(live_server, etc):
    """A misconfigured id must be visible, not hidden behind an endless reconnect."""
    config = AgentSettings(
        live_server, "00000000-0000-0000-0000-000000000000", config_dir=etc
    )

    assert asyncio.run(asyncio.wait_for(run(config), timeout=15)) == 1
