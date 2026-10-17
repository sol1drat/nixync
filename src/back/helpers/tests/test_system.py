"""Writing configuration to a machine and rebuilding it.

This is the only code in the project that modifies a real system, so every path and
the rebuild command are injected and every test runs against a temp directory with a
fake runner. No test here may touch /etc or invoke a real nixos-rebuild.
"""

import subprocess
from pathlib import Path

import pytest

from nixync_agent.system import RebuildFailed, SystemWriter
from nixync_client.protocol import MachineConfig, SystemSettings

EXISTING_CONFIG = """{ config, pkgs, ... }:

{
  imports = [ ./hardware-configuration.nix ];

  boot.loader.systemd-boot.enable = true;
  system.stateVersion = "24.11";
}
"""


class FakeRebuild:
    """Stands in for `nixos-rebuild`. Records calls; fails when told to."""

    def __init__(self, returncode: int = 0, stderr: str = ""):
        self.returncode = returncode
        self.stderr = stderr
        self.calls: list[list[str]] = []

    def __call__(self, command, **kwargs) -> subprocess.CompletedProcess:
        self.calls.append(command)
        return subprocess.CompletedProcess(command, self.returncode, "", self.stderr)


@pytest.fixture
def etc(tmp_path) -> Path:
    """A stand-in /etc/nixos with a configuration the operator already had."""
    (tmp_path / "configuration.nix").write_text(EXISTING_CONFIG)
    (tmp_path / "hardware-configuration.nix").write_text("{ }\n")
    return tmp_path


@pytest.fixture
def rebuild() -> FakeRebuild:
    return FakeRebuild()


def writer(etc: Path, rebuild: FakeRebuild, **kwargs) -> SystemWriter:
    return SystemWriter(config_dir=etc, run=rebuild, **kwargs)


# -- writing the module -----------------------------------------------------


def test_applying_writes_the_rendered_config(etc, rebuild):
    writer(etc, rebuild).apply(MachineConfig(packages=["git"]))

    assert "git" in (etc / "nixync.nix").read_text()


def test_the_operators_own_configuration_is_not_overwritten(etc, rebuild):
    """Nixync owns one file. Everything else on the machine stays as it was."""
    writer(etc, rebuild).apply(MachineConfig(packages=["git"]))

    kept = (etc / "configuration.nix").read_text()
    assert "boot.loader.systemd-boot.enable = true;" in kept
    assert 'system.stateVersion = "24.11";' in kept
    assert (etc / "hardware-configuration.nix").read_text() == "{ }\n"


def test_the_import_line_is_added_to_the_existing_imports_list(etc, rebuild):
    writer(etc, rebuild).apply(MachineConfig())

    imports = (etc / "configuration.nix").read_text()
    assert "./nixync.nix" in imports
    assert "./hardware-configuration.nix" in imports, "the existing import survives"


def test_applying_twice_leaves_exactly_one_import(etc, rebuild):
    """Re-running the agent must not keep appending to configuration.nix."""
    system = writer(etc, rebuild)
    system.apply(MachineConfig())
    system.apply(MachineConfig(packages=["git"]))

    assert (etc / "configuration.nix").read_text().count("./nixync.nix") == 1


def test_an_import_the_operator_already_added_is_respected(etc, rebuild):
    (etc / "configuration.nix").write_text(
        EXISTING_CONFIG.replace("[ ./hardware-configuration.nix ]",
                                "[ ./hardware-configuration.nix ./nixync.nix ]")
    )

    writer(etc, rebuild).apply(MachineConfig())

    assert (etc / "configuration.nix").read_text().count("./nixync.nix") == 1


def test_a_configuration_with_no_imports_list_gains_one(etc, rebuild):
    (etc / "configuration.nix").write_text("{ config, pkgs, ... }:\n\n{\n  x = 1;\n}\n")

    writer(etc, rebuild).apply(MachineConfig())

    text = (etc / "configuration.nix").read_text()
    assert "./nixync.nix" in text
    assert "x = 1;" in text


# -- rebuilding -------------------------------------------------------------


def test_applying_runs_the_rebuild(etc, rebuild):
    writer(etc, rebuild).apply(MachineConfig())

    assert rebuild.calls, "nixos-rebuild was invoked"
    assert "switch" in rebuild.calls[0]


def test_a_failed_rebuild_raises_with_the_error_the_admin_should_see(etc):
    failing = FakeRebuild(returncode=1, stderr="error: undefined variable 'htp'")

    with pytest.raises(RebuildFailed, match="undefined variable"):
        writer(etc, failing).apply(MachineConfig(packages=["htop"]))


def test_a_failed_rebuild_restores_the_previous_configuration(etc):
    """A broken deployment must not leave broken Nix on the machine."""
    system_ok = writer(etc, FakeRebuild())
    system_ok.apply(MachineConfig(packages=["git"]))
    good = (etc / "nixync.nix").read_text()

    with pytest.raises(RebuildFailed):
        writer(etc, FakeRebuild(returncode=1, stderr="boom")).apply(
            MachineConfig(packages=["broken-package"])
        )

    assert (etc / "nixync.nix").read_text() == good


def test_a_first_ever_failed_rebuild_leaves_no_half_written_module(etc):
    """There is no previous file to restore, so the bad one must simply go."""
    with pytest.raises(RebuildFailed):
        writer(etc, FakeRebuild(returncode=1, stderr="boom")).apply(
            MachineConfig(packages=["nope"])
        )

    assert not (etc / "nixync.nix").exists()


def test_only_the_tail_of_a_huge_build_log_is_reported(etc):
    """A full nixos-rebuild log is thousands of lines; the admin needs the end of it."""
    noise = "\n".join(f"line {i}" for i in range(500)) + "\nerror: the real problem"

    with pytest.raises(RebuildFailed) as failure:
        writer(etc, FakeRebuild(returncode=1, stderr=noise)).apply(MachineConfig())

    assert "error: the real problem" in str(failure.value)
    assert "line 0" not in str(failure.value)


# -- dry run ----------------------------------------------------------------


def test_a_dry_run_never_rebuilds_or_touches_the_real_config(etc, rebuild):
    """So the daemon can be run on a dev machine without consequences."""
    writer(etc, rebuild, dry_run=True).apply(MachineConfig(packages=["git"]))

    assert rebuild.calls == []
    assert not (etc / "nixync.nix").exists()
    assert "./nixync.nix" not in (etc / "configuration.nix").read_text()


def test_a_dry_run_still_reports_what_it_would_write(etc, rebuild):
    text = writer(etc, rebuild, dry_run=True).apply(MachineConfig(packages=["git"]))

    assert "git" in text


# -- reading back -----------------------------------------------------------


def test_the_writer_reports_what_it_last_wrote(etc, rebuild):
    system = writer(etc, rebuild)
    system.apply(MachineConfig(packages=["git", "htop"], settings=SystemSettings(hostname="lab-05")))

    current = system.current_config()
    assert current.packages == ["git", "htop"]
    assert current.settings.hostname == "lab-05"


def test_a_machine_nixync_has_never_touched_reports_an_empty_config(etc, rebuild):
    """Nothing has been deployed, so claim nothing rather than guessing."""
    assert writer(etc, rebuild).current_config() == MachineConfig()


# -- safety -----------------------------------------------------------------


def test_an_unsafe_package_name_is_refused_before_anything_is_written(etc, rebuild):
    """Validation happens before the file is touched, not after."""
    with pytest.raises(ValueError):
        writer(etc, rebuild).apply(MachineConfig(packages=["git; rm -rf /"]))

    assert not (etc / "nixync.nix").exists()
    assert rebuild.calls == []


def test_the_module_is_written_atomically(etc, rebuild):
    """An interrupted write must not leave a truncated file the machine cannot parse.

    Checked by watching what the rebuild sees: by the time it runs, the file is
    complete, because the write was a rename over the top of the old one.
    """
    seen = {}

    def capture(command, **kwargs):
        seen["text"] = (etc / "nixync.nix").read_text()
        return subprocess.CompletedProcess(command, 0, "", "")

    SystemWriter(config_dir=etc, run=capture).apply(MachineConfig(packages=["git"]))

    assert seen["text"].rstrip().endswith("}")
    assert not list(etc.glob("*.tmp*")), "no temp file is left behind"


def test_a_failed_rebuild_rolls_back_the_recorded_state_too(etc):
    """Otherwise the agent reports the config it failed to apply as the live one."""
    writer(etc, FakeRebuild()).apply(MachineConfig(packages=["git"]))

    with pytest.raises(RebuildFailed):
        writer(etc, FakeRebuild(returncode=1, stderr="boom")).apply(
            MachineConfig(packages=["git", "broken"])
        )

    assert writer(etc, FakeRebuild()).current_config().packages == ["git"]


def test_a_corrupt_state_record_does_not_crash_the_agent(etc, rebuild):
    """The server will push the desired state again; a bad record is not fatal."""
    (etc / ".nixync-state.json").write_text("{ not json")

    assert writer(etc, rebuild).current_config() == MachineConfig()


def test_a_missing_configuration_nix_is_reported_not_invented(etc, rebuild, caplog):
    """Writing one from scratch would be claiming ownership of the whole machine."""
    (etc / "configuration.nix").unlink()

    writer(etc, rebuild).apply(MachineConfig(packages=["git"]))

    assert (etc / "nixync.nix").exists(), "the module is still written"
    assert not (etc / "configuration.nix").exists(), "but nothing is fabricated"


def test_a_write_that_fails_partway_leaves_the_previous_module_intact(etc, monkeypatch):
    """This is what "atomic" has to mean, and the only way to show it.

    A plain write truncates the target before it has the new contents, so a crash
    leaves Nix that will not parse — and the machine fails its *next* rebuild too,
    including on boot. Writing to a temp file and renaming means a failure anywhere
    before the rename leaves the old file exactly as it was.
    """
    import os

    writer(etc, FakeRebuild()).apply(MachineConfig(packages=["git"]))
    good = (etc / "nixync.nix").read_text()

    def explode(_fd):
        raise OSError("disk full")

    monkeypatch.setattr(os, "fsync", explode)

    with pytest.raises(OSError):
        writer(etc, FakeRebuild()).apply(MachineConfig(packages=["git", "htop"]))

    assert (etc / "nixync.nix").read_text() == good, "the old module survived untouched"
    assert not list(etc.glob("*.tmp*")), "and the partial write was cleaned up"


# -- rollback must leave the machine buildable ------------------------------


def test_a_failed_first_rebuild_removes_the_import_it_added(etc):
    """Found on a real machine: the module was deleted but the import was not.

    configuration.nix was left importing ./nixync.nix with no such file, so every
    later `nixos-rebuild` failed — including one the operator ran themselves, with
    nothing on screen explaining why. Rolling back has to undo both halves.
    """
    before = (etc / "configuration.nix").read_text()

    with pytest.raises(RebuildFailed):
        writer(etc, FakeRebuild(returncode=1, stderr="boom")).apply(
            MachineConfig(packages=["nope"])
        )

    assert not (etc / "nixync.nix").exists()
    assert (etc / "configuration.nix").read_text() == before, (
        "configuration.nix is byte-identical to before the attempt"
    )


def test_a_failed_rebuild_keeps_the_import_when_a_module_already_worked(etc):
    """The opposite case: a working deployment must not lose its import line."""
    writer(etc, FakeRebuild()).apply(MachineConfig(packages=["git"]))
    good_config = (etc / "configuration.nix").read_text()

    with pytest.raises(RebuildFailed):
        writer(etc, FakeRebuild(returncode=1, stderr="boom")).apply(
            MachineConfig(packages=["git", "broken"])
        )

    assert (etc / "configuration.nix").read_text() == good_config
    assert "./nixync.nix" in (etc / "configuration.nix").read_text()
    assert (etc / "nixync.nix").exists(), "the working module is still there"


def test_a_failed_rebuild_leaves_no_state_file_behind_on_a_first_attempt(etc):
    """A state file for a deployment that never landed is a lie about the machine."""
    with pytest.raises(RebuildFailed):
        writer(etc, FakeRebuild(returncode=1, stderr="boom")).apply(
            MachineConfig(packages=["nope"])
        )

    assert not (etc / ".nixync-state.json").exists()


def test_the_machine_still_builds_after_a_failed_deployment(etc):
    """The property all of this protects: nothing dangling, nothing half-applied."""
    with pytest.raises(RebuildFailed):
        writer(etc, FakeRebuild(returncode=1, stderr="boom")).apply(
            MachineConfig(packages=["nope"])
        )

    config = (etc / "configuration.nix").read_text()
    imported = [part for part in config.split() if part.endswith(".nix")]
    for reference in imported:
        name = reference.lstrip("./")
        assert (etc / name).exists(), f"configuration.nix imports missing {reference}"
