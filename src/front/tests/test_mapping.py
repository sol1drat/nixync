"""Pure mapping helpers: no server needed.

Health, RAM percentage and timestamp parsing are easy to get subtly wrong, and the
adapter tests that hit a live server already have enough moving parts.
"""

from datetime import datetime, timezone

from nixync_client.protocol import MachineConfig
from nixync_client.admin import Machine as ServerMachine

from nixync_front import sample_data
from nixync_front.api import _health_of, _parse_time, _ram_percent, _settings_from, _to_view_model


def _server_machine(**overrides) -> ServerMachine:
    base = dict(
        id="m1",
        name="lab-01",
        created_at="2026-01-01T00:00:00+00:00",
        online=True,
        config=MachineConfig(),
    )
    base.update(overrides)
    return ServerMachine(**base)


def test_a_failed_apply_is_a_problem_even_when_the_device_is_offline():
    machine = _server_machine(online=False, last_apply_status="failed")

    assert _health_of(machine) is sample_data.Health.PROBLEM


def test_an_offline_device_with_no_failed_apply_is_unreachable():
    assert _health_of(_server_machine(online=False)) is sample_data.Health.UNREACHABLE


def test_an_online_device_with_a_pending_apply_reads_as_ok():
    """Health has no deploying state; pending work is not a failure."""
    assert _health_of(_server_machine(last_apply_status="pending")) is sample_data.Health.OK


def test_ram_percent_is_computed_from_megabytes():
    machine = _server_machine(ram_used_mb=512, ram_total_mb=2048)

    assert _ram_percent(machine) == 25.0


def test_ram_percent_is_none_when_totals_are_missing():
    assert _ram_percent(_server_machine()) is None
    assert _ram_percent(_server_machine(ram_used_mb=100, ram_total_mb=0)) is None


def test_iso_timestamps_are_parsed():
    assert _parse_time("2026-03-15T12:30:00+00:00") == datetime(
        2026, 3, 15, 12, 30, tzinfo=timezone.utc
    )


def test_bad_or_missing_timestamps_become_none():
    assert _parse_time(None) is None
    assert _parse_time("") is None
    assert _parse_time("not-a-timestamp") is None


def test_settings_decode_known_keys_and_drop_unknown_ones():
    settings = _settings_from(
        {"hostname": "lab-05", "firewall": False, "future_flag": True},
        hostname="fallback",
    )

    assert settings.hostname == "lab-05"
    assert settings.firewall is False
    assert not hasattr(settings, "future_flag")


def test_settings_fall_back_to_the_machine_name_when_hostname_is_absent():
    assert _settings_from({}, hostname="lab-01").hostname == "lab-01"


def test_view_model_carries_live_fields_and_leaves_unsupported_ones_blank():
    machine = _to_view_model(
        _server_machine(
            cpu_percent=12.5,
            ram_used_mb=100,
            ram_total_mb=400,
            disk_used_gb=10.0,
            disk_total_gb=100.0,
            metrics_reported_at="2026-03-15T12:30:00+00:00",
            last_apply_message="ok",
            config=MachineConfig(packages=["htop"], settings={"hostname": "lab-01"}),
        )
    )

    assert machine.name == "lab-01"
    assert machine.cpu_percent == 12.5
    assert machine.ram_percent == 25.0
    assert machine.extra_apps == ["htop"]
    assert machine.settings.hostname == "lab-01"
    assert machine.note == "ok"
    assert machine.preset == ""
    assert machine.group == ""
    assert machine.builds == []
    assert machine.errors == []
