"""The desktop app's adapter, driven against a real server.

These tests are written from the UI's point of view: they call exactly what the pages
call, and assert on the `sample_data.Machine` the pages render.
"""

import asyncio
import contextlib
import time
from dataclasses import replace

import pytest

from nixync_client.agent import NixyncAgent
from nixync_client.protocol import MachineConfig

from nixync_front import sample_data
from nixync_front.api import ApiError, NixyncClient
from nixync_front.config import Config

SETTLE_TIMEOUT_SECONDS = 5


@pytest.fixture
def client(live_server) -> NixyncClient:
    return NixyncClient(Config(server_url=live_server, request_timeout=5))


async def call(blocking_fn, *args, **kwargs):
    """Run a blocking adapter call off the event loop.

    NixyncClient is synchronous — the GUI runs it on worker threads for exactly this
    reason. Calling it directly here would block the loop the agent under test shares,
    starving the very thing we are waiting for.
    """
    return await asyncio.to_thread(blocking_fn, *args, **kwargs)


async def wait_until(client: NixyncClient, name: str, predicate, what: str):
    deadline = time.monotonic() + SETTLE_TIMEOUT_SECONDS
    machine = None
    while time.monotonic() < deadline:
        machine = await call(client.get_machine, name)
        if predicate(machine):
            return machine
        await asyncio.sleep(0.05)
    pytest.fail(f"never reached: {what}\nlast seen: {machine}")


@contextlib.asynccontextmanager
async def agent_running(agent: NixyncAgent):
    """Keep an agent connected for the duration of the block."""
    task = asyncio.create_task(agent.run())
    try:
        yield agent
    finally:
        agent.stop()
        task.cancel()
        # CancelledError derives from BaseException, so Exception alone misses it.
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await asyncio.wait_for(task, timeout=5)


# -- sign-in ----------------------------------------------------------------


def test_signing_in_with_the_demo_credentials_succeeds(client):
    assert client.login("admin", "password")["username"] == "admin"


def test_a_wrong_password_reports_a_message_fit_for_the_login_screen(client):
    with pytest.raises(ApiError, match="Incorrect username or password"):
        client.login("admin", "wrong")


def test_empty_credentials_are_caught_before_a_round_trip(client):
    with pytest.raises(ApiError, match="Enter your username and password"):
        client.login("", "")


def test_an_unreachable_server_is_reported_differently_from_a_bad_password():
    """The operator needs to know whether to fix the password or the network."""
    offline = NixyncClient(Config(server_url="http://127.0.0.1:1", request_timeout=0.5))

    with pytest.raises(ApiError, match="Can't reach the server"):
        offline.login("admin", "password")


# -- the fleet view ---------------------------------------------------------


def test_a_registered_machine_appears_in_the_machines_list(client):
    client.add_machine("front-listed")

    assert "front-listed" in {m.name for m in client.list_machines()}


def test_a_new_machine_reads_as_unreachable_with_no_metrics(client):
    machine = client.add_machine("front-fresh")

    assert machine.health is sample_data.Health.UNREACHABLE
    assert machine.cpu_percent is None
    assert machine.ram_percent is None
    assert machine.last_seen is None
    assert machine.extra_apps == []


def test_removing_a_machine_takes_it_off_the_list(client):
    client.add_machine("front-removed")

    client.remove_machine("front-removed")

    assert "front-removed" not in {m.name for m in client.list_machines()}


def test_asking_for_an_unknown_machine_reports_it_clearly(client):
    with pytest.raises(ApiError, match="No machine called"):
        client.get_machine("never-registered")


def test_the_agent_id_is_available_so_the_operator_can_provision_the_device(client):
    machine = client.add_machine("front-id")

    assert client.machine_id(machine.name)


def test_add_dialog_labels_are_stored_with_the_machine(client):
    """What the operator typed in the add dialog comes back on the machine."""
    machine = client.add_machine(
        "front-labeled", preset="Workstation", address="10.0.4.15"
    )

    assert machine.preset == "Workstation"
    assert machine.address == "10.0.4.15"
    listed = next(m for m in client.list_machines() if m.name == "front-labeled")
    assert listed.preset == "Workstation"
    assert listed.address == "10.0.4.15"


def test_add_dialog_labels_survive_a_restart_of_the_app(client, live_server):
    """Preset, group and address live on the server now, not in this process."""
    client.add_machine(
        "front-persisted", preset="Workstation", group="Lab A", address="10.0.0.1"
    )

    fresh = NixyncClient(Config(server_url=live_server, request_timeout=5))
    machine = fresh.get_machine("front-persisted")

    assert machine.preset == "Workstation"
    assert machine.group == "Lab A"
    assert machine.address == "10.0.0.1"


# -- live telemetry ---------------------------------------------------------


def test_a_connected_device_reports_live_usage_into_the_view_model(client, live_server):
    machine = client.add_machine("front-live")
    machine_id = client.machine_id(machine.name)

    async def scenario():
        agent = NixyncAgent(
            server_url=live_server, machine_id=machine_id, telemetry_interval=60
        )
        async with agent_running(agent):
            return await wait_until(
                client,
                "front-live",
                lambda m: m.cpu_percent is not None,
                "the device reported its usage",
            )

    live = asyncio.run(scenario())
    assert 0.0 <= live.cpu_percent <= 100.0
    assert 0.0 <= live.ram_percent <= 100.0, "ram is a percentage, not megabytes"
    assert live.disk_total_gb > 0
    assert live.last_seen is not None, "last_seen is parsed from the server's timestamp"
    assert live.disk_percent is not None, "the UI's computed property still works"


def test_a_failed_deployment_shows_as_a_problem_with_its_reason(client, live_server):
    """A build failure must reach the operator as a badge and a message."""
    machine = client.add_machine("front-broken")
    machine_id = client.machine_id(machine.name)

    def refuse(config: MachineConfig):
        raise RuntimeError("nixos-rebuild: collision between gcc and clang")

    async def scenario():
        agent = NixyncAgent(
            server_url=live_server,
            machine_id=machine_id,
            on_apply=refuse,
            telemetry_interval=60,
        )
        async with agent_running(agent):
            await wait_until(
                client,
                "front-broken",
                lambda m: m.health is not sample_data.Health.UNREACHABLE,
                "the device came online",
            )
            await call(client.add_apps, ["front-broken"], ["gcc"])
            return await wait_until(
                client,
                "front-broken",
                lambda m: m.health is sample_data.Health.PROBLEM,
                "the failure reached the fleet view",
            )

    broken = asyncio.run(scenario())
    assert broken.health is sample_data.Health.PROBLEM
    assert "collision" in broken.note, "the build error is visible in the UI"


# -- deploying apps ---------------------------------------------------------


def test_adding_apps_deploys_them_and_reports_what_was_new(client):
    client.add_machine("front-apps")

    added = client.add_apps(["front-apps"], ["htop", "git"])

    assert sorted(added["front-apps"]) == ["git", "htop"]
    assert sorted(client.get_machine("front-apps").extra_apps) == ["git", "htop"]


def test_adding_an_app_a_device_already_has_reports_nothing_new(client):
    """The UI says "nothing to do" rather than claiming a fresh install."""
    client.add_machine("front-dupes")
    client.add_apps(["front-dupes"], ["htop"])

    added = client.add_apps(["front-dupes"], ["htop"])

    assert added["front-dupes"] == []


def test_apps_can_be_deployed_to_several_devices_at_once(client):
    client.add_machine("front-multi-a")
    client.add_machine("front-multi-b")

    added = client.add_apps(["front-multi-a", "front-multi-b"], ["curl"])

    assert added == {"front-multi-a": ["curl"], "front-multi-b": ["curl"]}
    assert "curl" in client.get_machine("front-multi-a").extra_apps
    assert "curl" in client.get_machine("front-multi-b").extra_apps


def test_installed_apps_is_what_the_app_store_checks_against(client):
    client.add_machine("front-installed")
    client.add_apps(["front-installed"], ["vim"])

    assert "vim" in client.installed_apps("front-installed")


def test_set_apps_adds_and_removes_to_match_the_edited_list(client):
    """The machine-config page edits the full list, not just additions."""
    client.add_machine("front-set-apps")
    client.add_apps(["front-set-apps"], ["htop", "git", "curl"])

    added, removed = client.set_apps("front-set-apps", ["htop", "vim"])

    assert added == ["vim"]
    assert removed == ["curl", "git"]
    assert sorted(client.get_machine("front-set-apps").extra_apps) == ["htop", "vim"]


def test_set_apps_with_the_same_list_changes_nothing(client):
    client.add_machine("front-set-noop")
    client.add_apps(["front-set-noop"], ["htop"])

    added, removed = client.set_apps("front-set-noop", ["htop"])

    assert added == []
    assert removed == []


def test_duplicate_machine_names_refuse_to_act_silently(client):
    """Acting on the wrong machine is worse than failing loudly."""
    client._admin.register_machine("front-dup")
    client._admin.register_machine("front-dup")

    # The fleet view can still list them; looking one up by name must not pick either.
    assert "front-dup" in {m.name for m in client.list_machines()}
    with pytest.raises(ApiError, match="more than one"):
        client.get_machine("front-dup")


# -- device settings --------------------------------------------------------


def test_device_settings_survive_a_restart_of_the_app(client, live_server):
    """Settings must live on the server, not in this process."""
    client.add_machine("front-settings")
    settings = sample_data.SystemSettings(
        hostname="lab-05", timezone="Europe/London", firewall=False, bluetooth=True
    )

    client.save_settings("front-settings", settings)

    fresh_app = NixyncClient(Config(server_url=live_server, request_timeout=5))
    stored = fresh_app.get_machine("front-settings").settings
    assert stored.hostname == "lab-05"
    assert stored.timezone == "Europe/London"
    assert stored.firewall is False
    assert stored.bluetooth is True


def test_local_users_round_trip_through_the_server(client):
    client.add_machine("front-users")
    settings = sample_data.SystemSettings(
        hostname="front-users",
        users=[sample_data.LocalUser(name="alice", full_name="Alice", admin=True)],
    )

    client.save_settings("front-users", settings)

    stored = client.get_machine("front-users").settings
    assert [u.name for u in stored.users] == ["alice"]
    assert stored.users[0].admin is True


def test_saving_settings_does_not_disturb_installed_apps(client):
    client.add_machine("front-settings-apps")
    client.add_apps(["front-settings-apps"], ["git"])

    client.save_settings(
        "front-settings-apps", sample_data.SystemSettings(hostname="renamed")
    )

    machine = client.get_machine("front-settings-apps")
    assert machine.extra_apps == ["git"]
    assert machine.settings.hostname == "renamed"


def test_passwords_are_never_sent_to_the_server(client):
    """They belong on the device, hashed there, and never in the Nix configuration."""
    client.add_machine("front-passwords")
    settings = sample_data.SystemSettings(
        hostname="front-passwords",
        users=[sample_data.LocalUser(name="bob")],
    )

    client.save_settings("front-passwords", settings, passwords={"bob": "hunter2"})

    raw = client._admin.get_machine(client.machine_id("front-passwords")).config.settings
    assert "hunter2" not in str(raw)


def test_a_device_with_no_saved_settings_still_renders(client):
    """SystemSettings must never be None; the UI reads attributes off it directly."""
    machine = client.add_machine("front-no-settings")

    assert machine.settings is not None
    assert machine.settings.hostname == "front-no-settings"


def test_unknown_stored_settings_keys_are_ignored_rather_than_crashing(client):
    """A newer build may have written a setting this one does not know about."""
    machine = client.add_machine("front-future-settings")
    client._admin.set_settings(
        client.machine_id(machine.name),
        {"hostname": "known", "some_future_toggle": True},
    )

    stored = client.get_machine("front-future-settings").settings

    assert stored.hostname == "known"


# -- app requests (still local, but approval deploys for real) --------------


def test_approving_a_request_actually_deploys_the_app(client):
    client.add_machine("front-request")
    request = client.create_request("front-request", "htop", "student", "for monitoring")

    # The decision comes back from the server rather than mutating the caller's copy,
    # which is what a request held by another window would otherwise go stale against.
    approved = client.approve_request(request.id)

    assert approved.status is sample_data.RequestStatus.APPROVED
    assert "htop" in client.get_machine("front-request").extra_apps


def test_declining_a_request_deploys_nothing(client):
    client.add_machine("front-declined")
    request = client.create_request("front-declined", "doom", "student", "")

    declined = client.decline_request(request.id)

    assert declined.status is sample_data.RequestStatus.DECLINED
    assert client.get_machine("front-declined").extra_apps == []


def test_a_preset_claiming_an_app_does_not_stop_it_being_deployed(client):
    """Presets are sample data the server never deploys — they must not mask a real gap.

    The "Workstation" preset lists htop. If add_apps treats that as installed, the
    operator asks for htop, the UI reports the device already has it, and the package
    never reaches the machine. A silent no-op is worse than an error.
    """
    machine = client.add_machine("front-preset-gap", preset="Workstation")

    added = client.add_apps([machine.name], ["htop"])

    assert added[machine.name] == ["htop"], "the request was not silently swallowed"
    assert "htop" in client.get_machine(machine.name).extra_apps, "it really deployed"
