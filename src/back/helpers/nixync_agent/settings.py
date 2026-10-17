"""Where the agent gets its server URL and machine id.

A file rather than flags, because the daemon is started by systemd at boot and
nobody is there to type anything. Flags still win, for running it by hand.
"""

import tomllib
from dataclasses import dataclass
from pathlib import Path

DEFAULT_PATH = Path("/etc/nixync/agent.toml")
DEFAULT_TELEMETRY_INTERVAL = 120.0


class ConfigurationError(RuntimeError):
    """The agent cannot start because it was not told what to connect to."""


@dataclass(frozen=True)
class AgentSettings:
    server_url: str
    machine_id: str
    telemetry_interval: float = DEFAULT_TELEMETRY_INTERVAL
    config_dir: Path = Path("/etc/nixos")
    dry_run: bool = False


def load(
    path: Path = DEFAULT_PATH,
    *,
    server_url: str | None = None,
    machine_id: str | None = None,
    **overrides,
) -> AgentSettings:
    """Read the file, then let explicit arguments win.

    Missing values are an error with a message naming what to do, rather than a
    default that would have the agent connect somewhere unintended.
    """
    values: dict = {}
    if path.is_file():
        values = tomllib.loads(path.read_text())

    if server_url:
        values["server_url"] = server_url
    if machine_id:
        values["machine_id"] = machine_id
    values.update({k: v for k, v in overrides.items() if v is not None})

    # Name the actual flag, not a guess derived from the key: an error message that
    # tells you to pass an option that does not exist is worse than no message.
    flags = {"server_url": "--server", "machine_id": "--machine-id"}
    for required, flag in flags.items():
        if not values.get(required):
            raise ConfigurationError(
                f"No {required} configured. Put it in {path} or pass {flag}."
            )

    known = AgentSettings.__dataclass_fields__
    settings = {k: v for k, v in values.items() if k in known}
    settings["config_dir"] = Path(settings.get("config_dir", "/etc/nixos"))
    settings["telemetry_interval"] = float(
        settings.get("telemetry_interval", DEFAULT_TELEMETRY_INTERVAL)
    )
    return AgentSettings(**settings)
