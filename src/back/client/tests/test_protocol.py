import pytest

from nixync_client.protocol import (
    ApplyConfig,
    MachineConfig,
    UnknownMessage,
    apply_result_message,
    config_report_message,
    parse_server_message,
    telemetry_message,
)


def test_machine_config_defaults_to_empty_lists():
    config = MachineConfig()

    assert config.packages == []
    assert config.users == []
    assert config.groups == []
    assert config.services == []


def test_machine_config_round_trips_through_a_dict():
    original = MachineConfig(
        packages=["git", "htop"], users=["alice"], groups=["wheel"], services=["sshd"]
    )

    assert MachineConfig.from_dict(original.to_dict()) == original


def test_machine_config_tolerates_missing_keys_from_the_server():
    """An older or trimmed payload must not crash the agent."""
    config = MachineConfig.from_dict({"packages": ["git"]})

    assert config.packages == ["git"]
    assert config.services == []


def test_telemetry_message_has_the_type_the_server_expects():
    message = telemetry_message(
        cpu_percent=12.5,
        ram_used_mb=2048,
        ram_total_mb=8192,
        disk_used_gb=100.0,
        disk_total_gb=512.0,
    )

    assert message == {
        "type": "telemetry",
        "cpu_percent": 12.5,
        "ram_used_mb": 2048,
        "ram_total_mb": 8192,
        "disk_used_gb": 100.0,
        "disk_total_gb": 512.0,
    }


def test_config_report_message_wraps_the_config():
    message = config_report_message(MachineConfig(packages=["git"]))

    assert message["type"] == "config_report"
    assert message["config"]["packages"] == ["git"]


def test_apply_result_message_reports_success_without_a_reason():
    message = apply_result_message("apply-1", applied=True)

    assert message == {
        "type": "apply_result",
        "apply_id": "apply-1",
        "status": "applied",
        "message": None,
    }


def test_apply_result_message_carries_the_failure_reason():
    message = apply_result_message("apply-1", applied=False, message="build failed")

    assert message["status"] == "failed"
    assert message["message"] == "build failed"


def test_parse_server_message_returns_an_apply_config():
    parsed = parse_server_message(
        {"type": "apply_config", "apply_id": "apply-1", "config": {"packages": ["htop"]}}
    )

    assert isinstance(parsed, ApplyConfig)
    assert parsed.apply_id == "apply-1"
    assert parsed.config.packages == ["htop"]


def test_parse_server_message_reports_unknown_types_rather_than_dropping_them():
    """A server that grows a new message type should be visible, not silently ignored."""
    parsed = parse_server_message({"type": "reboot_now"})

    assert isinstance(parsed, UnknownMessage)
    assert parsed.type == "reboot_now"


def test_parse_server_message_rejects_a_malformed_apply_config():
    with pytest.raises(ValueError, match="apply_config"):
        parse_server_message({"type": "apply_config", "config": {}})


def test_the_public_api_is_importable_from_the_package_root():
    """What the GUI and an agent actually write: `from nixync_client import ...`."""
    import nixync_client

    for name in nixync_client.__all__:
        assert hasattr(nixync_client, name), f"{name} is exported but missing"


def test_importing_the_package_neither_needs_nor_pulls_in_pyside6():
    """The agent ships to NixOS boxes with no Qt at all.

    Checked in a subprocess with PySide6 made unimportable, because this process may
    well have it installed — importing it here would prove nothing.
    """
    import subprocess
    import sys
    from pathlib import Path

    probe = (
        "import sys;"
        "sys.modules['PySide6'] = None;"
        "import nixync_client;"
        "assert 'PySide6.QtCore' not in sys.modules;"
        "nixync_client.AdminClient, nixync_client.NixyncAgent;"
        "print('ok')"
    )
    result = subprocess.run(
        [sys.executable, "-c", probe],
        cwd=Path(__file__).resolve().parent.parent,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert "ok" in result.stdout
