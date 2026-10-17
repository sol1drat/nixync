"""AdminClient driven against a real server — this is what the desktop GUI will call."""

import pytest

from nixync_client.admin import AdminClient, Machine, NixyncApiError
from nixync_client.protocol import MachineConfig, SystemSettings


@pytest.fixture
def admin(live_server) -> AdminClient:
    return AdminClient(live_server)


# -- registration and lookup ------------------------------------------------


def test_registering_a_machine_returns_it_with_a_server_generated_id(admin):
    machine = admin.register_machine("lab-register")

    assert isinstance(machine, Machine)
    assert machine.id, "the server mints the id"
    assert machine.name == "lab-register"
    assert machine.online is False
    assert machine.config == MachineConfig()


def test_a_newly_registered_machine_has_no_metrics_yet(admin):
    machine = admin.register_machine("lab-no-metrics")

    assert machine.cpu_percent is None
    assert machine.ram_total_mb is None
    assert machine.metrics_reported_at is None


def test_list_machines_includes_everything_registered(admin):
    machine = admin.register_machine("lab-listed")

    assert machine.id in {m.id for m in admin.list_machines()}


def test_get_machine_fetches_a_single_machine_by_id(admin):
    registered = admin.register_machine("lab-fetch")

    fetched = admin.get_machine(registered.id)

    assert fetched.id == registered.id
    assert fetched.name == "lab-fetch"


def test_get_machine_raises_a_typed_error_for_an_unknown_id(admin):
    with pytest.raises(NixyncApiError) as error:
        admin.get_machine("does-not-exist")

    assert error.value.status_code == 404
    assert "not found" in str(error.value).lower()


def test_find_machine_by_name_bridges_the_gui_which_thinks_in_names(admin):
    """The desktop UI identifies devices by name; the server keys on id."""
    registered = admin.register_machine("lab-by-name")

    found = admin.find_machine_by_name("lab-by-name")

    assert found is not None
    assert found.id == registered.id


def test_find_machine_by_name_returns_none_when_there_is_no_match(admin):
    assert admin.find_machine_by_name("no-such-device") is None


def test_find_machine_by_name_refuses_to_guess_between_duplicates(admin):
    """The server does not enforce unique names, so ambiguity must not pick one silently."""
    admin.register_machine("lab-duplicate")
    admin.register_machine("lab-duplicate")

    with pytest.raises(NixyncApiError, match="more than one"):
        admin.find_machine_by_name("lab-duplicate")


def test_removing_a_machine_takes_it_out_of_the_fleet(admin):
    machine = admin.register_machine("lab-remove")

    admin.remove_machine(machine.id)

    assert machine.id not in {m.id for m in admin.list_machines()}


def test_removing_an_unknown_machine_raises_a_typed_error(admin):
    with pytest.raises(NixyncApiError) as error:
        admin.remove_machine("does-not-exist")

    assert error.value.status_code == 404


# -- package changes --------------------------------------------------------


def test_adding_packages_to_a_targeted_machine(admin):
    machine = admin.register_machine("lab-add")

    results = admin.add_packages(["htop"], machine_ids=[machine.id])

    assert len(results) == 1
    assert results[0].machine_id == machine.id
    assert results[0].delivery == "queued", "nothing is connected, so it waits"
    assert admin.get_machine(machine.id).config.packages == ["htop"]


def test_removing_packages_from_a_targeted_machine(admin):
    machine = admin.register_machine("lab-remove-pkg")
    admin.add_packages(["htop", "git"], machine_ids=[machine.id])

    admin.remove_packages(["htop"], machine_ids=[machine.id])

    assert admin.get_machine(machine.id).config.packages == ["git"]


def test_a_fleet_wide_change_needs_no_machine_ids(admin):
    first = admin.register_machine("lab-fleet-a")
    second = admin.register_machine("lab-fleet-b")

    results = admin.add_packages(["curl"])

    touched = {r.machine_id for r in results}
    assert {first.id, second.id} <= touched
    assert "curl" in admin.get_machine(first.id).config.packages
    assert "curl" in admin.get_machine(second.id).config.packages


def test_a_package_change_reports_an_apply_id_per_machine(admin):
    machine = admin.register_machine("lab-apply-id")

    results = admin.add_packages(["vim"], machine_ids=[machine.id])

    assert results[0].apply_id
    assert admin.get_machine(machine.id).last_apply_status == "pending"


def test_targeting_an_unknown_machine_raises_rather_than_half_applying(admin):
    machine = admin.register_machine("lab-partial")

    with pytest.raises(NixyncApiError) as error:
        admin.add_packages(["htop"], machine_ids=[machine.id, "ghost"])

    assert error.value.status_code == 404
    assert admin.get_machine(machine.id).config.packages == [], "nothing was applied"


def test_an_unsupported_action_is_rejected_by_the_server(admin):
    machine = admin.register_machine("lab-bad-action")

    with pytest.raises(NixyncApiError) as error:
        admin.change_packages("upgrade", ["htop"], machine_ids=[machine.id])

    assert error.value.status_code == 422


# -- status and transport errors -------------------------------------------


def test_get_status_reports_the_server_is_reachable(admin):
    status = admin.get_status()

    assert status["status"] == "online"
    assert status["hostname"]


def test_an_unreachable_server_raises_a_typed_error_not_a_requests_error():
    """The GUI should only ever have to catch NixyncApiError."""
    admin = AdminClient("http://127.0.0.1:1", timeout=0.5)

    with pytest.raises(NixyncApiError) as error:
        admin.list_machines()

    assert error.value.status_code is None, "no HTTP response was ever received"


def test_the_base_url_tolerates_a_trailing_slash(live_server):
    """The login screen's URL field will collect both forms."""
    admin = AdminClient(live_server + "/")

    assert admin.get_status()["status"] == "online"


def test_machines_expose_telemetry_once_an_agent_has_reported(live_server, admin):
    """The dashboard's device table reads these fields straight off the Machine."""
    import asyncio

    from nixync_client.agent import NixyncAgent

    machine = admin.register_machine("lab-telemetry-view")

    async def connect_briefly():
        agent = NixyncAgent(
            server_url=live_server, machine_id=machine.id, telemetry_interval=60
        )
        task = asyncio.create_task(agent.run())
        for _ in range(100):
            await asyncio.sleep(0.05)
            if admin.get_machine(machine.id).cpu_percent is not None:
                break
        agent.stop()
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):
            pass

    asyncio.run(connect_briefly())

    live = admin.get_machine(machine.id)
    assert 0.0 <= live.cpu_percent <= 100.0
    assert live.ram_total_mb > 0
    assert live.disk_total_gb > 0


# -- sign-in ----------------------------------------------------------------


def test_signing_in_with_the_configured_credentials_returns_the_user(admin):
    assert admin.login("admin", "password") == {"username": "admin"}


def test_a_wrong_password_raises_a_typed_error_with_401(admin):
    with pytest.raises(NixyncApiError) as error:
        admin.login("admin", "wrong")

    assert error.value.status_code == 401


def test_signing_in_against_an_unreachable_server_is_distinguishable_from_a_bad_password():
    """The login screen must tell these two apart to say anything useful."""
    offline = AdminClient("http://127.0.0.1:1", timeout=0.5)

    with pytest.raises(NixyncApiError) as error:
        offline.login("admin", "password")

    assert error.value.status_code is None


# -- system settings --------------------------------------------------------


def test_setting_a_machines_system_settings_persists_them(admin):
    machine = admin.register_machine("settings-box")

    admin.set_settings(machine.id, SystemSettings(hostname="lab-05", firewall=True))

    stored = admin.get_machine(machine.id).config.settings
    assert stored.hostname == "lab-05"
    assert stored.firewall is True


def test_saving_settings_leaves_the_package_list_alone(admin):
    machine = admin.register_machine("settings-and-apps")
    admin.add_packages(["git"], machine_ids=[machine.id])

    admin.set_settings(machine.id, SystemSettings(hostname="lab-06"))

    fetched = admin.get_machine(machine.id)
    assert fetched.config.packages == ["git"]
    assert fetched.config.settings.hostname == "lab-06"


def test_saving_settings_queues_a_deployment_so_the_machine_picks_them_up(admin):
    machine = admin.register_machine("settings-deploy")

    result = admin.set_settings(machine.id, {"hostname": "lab-07"})

    assert result.delivery in {"pushed", "queued"}
    assert admin.get_machine(machine.id).last_apply_status == "pending"
