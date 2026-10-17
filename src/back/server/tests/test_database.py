import pytest

from database import (
    create_machine,
    delete_machine,
    get_machine,
    init_db,
    list_machines,
    save_reported_config,
    set_apply_pending,
    set_apply_result,
    update_telemetry,
)
from models import MachineConfig


@pytest.fixture
def conn(tmp_path):
    db_path = tmp_path / "nixync_test.db"
    connection = init_db(str(db_path))
    yield connection
    connection.close()


def test_create_machine_assigns_id_and_default_config(conn):
    machine = create_machine(conn, name="lab-01")

    assert machine.id
    assert machine.name == "lab-01"
    assert machine.config == MachineConfig()
    assert machine.online is False


def test_get_machine_returns_none_for_unknown_id(conn):
    assert get_machine(conn, "does-not-exist") is None


def test_get_machine_returns_created_machine(conn):
    created = create_machine(conn, name="lab-02")

    fetched = get_machine(conn, created.id)

    assert fetched is not None
    assert fetched.id == created.id
    assert fetched.name == "lab-02"


def test_list_machines_returns_all_created_machines(conn):
    create_machine(conn, name="lab-a")
    create_machine(conn, name="lab-b")

    machines = list_machines(conn)

    assert sorted(m.name for m in machines) == ["lab-a", "lab-b"]


def test_delete_machine_removes_row(conn):
    machine = create_machine(conn, name="to-delete")

    deleted = delete_machine(conn, machine.id)

    assert deleted is True
    assert get_machine(conn, machine.id) is None


def test_delete_machine_returns_false_for_unknown_id(conn):
    assert delete_machine(conn, "does-not-exist") is False


def test_update_telemetry_sets_metrics_and_timestamp(conn):
    machine = create_machine(conn, name="telemetry-host")

    update_telemetry(
        conn,
        machine.id,
        cpu_percent=42.5,
        ram_used_mb=2048,
        ram_total_mb=8192,
        disk_used_gb=120.0,
        disk_total_gb=500.0,
    )

    fetched = get_machine(conn, machine.id)
    assert fetched.cpu_percent == 42.5
    assert fetched.ram_used_mb == 2048
    assert fetched.ram_total_mb == 8192
    assert fetched.disk_used_gb == 120.0
    assert fetched.disk_total_gb == 500.0
    assert fetched.metrics_reported_at is not None


def test_a_new_machine_has_not_reported_its_config_yet(conn):
    machine = create_machine(conn, name="unreported-host")

    assert machine.reported_config is None, "absent is different from empty"


def test_save_reported_config_records_what_the_machine_actually_has(conn):
    machine = create_machine(conn, name="config-host")

    save_reported_config(conn, machine.id, MachineConfig(packages=["git", "htop"]))

    fetched = get_machine(conn, machine.id)
    assert fetched.reported_config.packages == ["git", "htop"]


def test_enrolling_an_existing_machine_adopts_its_setup_as_the_desired_config(conn):
    """A machine joining the fleet brings its configuration with it.

    Without this, the admin's first package add would declare a desired state of just
    that one package, and the agent would reconcile by removing everything else.
    """
    machine = create_machine(conn, name="existing-workstation")

    save_reported_config(conn, machine.id, MachineConfig(packages=["git"], services=["sshd"]))

    fetched = get_machine(conn, machine.id)
    assert fetched.config.packages == ["git"]
    assert fetched.config.services == ["sshd"]


def test_a_machines_report_never_overwrites_the_desired_config(conn):
    """The admin owns desired state; the agent owns reported state. They are separate."""
    machine = create_machine(conn, name="drift-host")
    set_apply_pending(
        conn, machine.id, apply_id="a1", config=MachineConfig(packages=["gcc", "neovim"])
    )

    # The machine boots with nothing installed and says so, before applying anything.
    save_reported_config(conn, machine.id, MachineConfig(packages=[]))

    fetched = get_machine(conn, machine.id)
    assert fetched.config.packages == ["gcc", "neovim"], "the admin's intent survives"
    assert fetched.reported_config.packages == [], "and the machine's truth is kept too"


def test_set_apply_pending_then_set_apply_result_round_trip(conn):
    machine = create_machine(conn, name="apply-host")

    set_apply_pending(conn, machine.id, apply_id="apply-1", config=MachineConfig(packages=["htop"]))
    pending = get_machine(conn, machine.id)
    assert pending.last_apply_id == "apply-1"
    assert pending.last_apply_status == "pending"

    set_apply_result(conn, machine.id, apply_id="apply-1", status="applied", message=None)
    applied = get_machine(conn, machine.id)
    assert applied.last_apply_status == "applied"
    assert applied.last_apply_at is not None


def test_set_apply_result_ignores_stale_apply_id(conn):
    machine = create_machine(conn, name="stale-host")
    set_apply_pending(conn, machine.id, apply_id="apply-current", config=MachineConfig())

    set_apply_result(conn, machine.id, apply_id="apply-old", status="applied", message=None)

    fetched = get_machine(conn, machine.id)
    assert fetched.last_apply_status == "pending"
    assert fetched.last_apply_id == "apply-current"


def test_machine_config_carries_free_form_system_settings(conn):
    """Hostname, firewall and SSH are NixOS config, so they ride with the rest of it."""
    machine = create_machine(conn, name="settings-host")
    config = MachineConfig(packages=["git"], settings={"hostname": "lab-05", "firewall": True})

    set_apply_pending(conn, machine.id, apply_id="a1", config=config)

    fetched = get_machine(conn, machine.id)
    assert fetched.config.settings == {"hostname": "lab-05", "firewall": True}
    assert fetched.config.packages == ["git"], "settings do not disturb packages"


def test_settings_default_to_empty_rather_than_null(conn):
    machine = create_machine(conn, name="plain-host")

    assert machine.config.settings == {}
