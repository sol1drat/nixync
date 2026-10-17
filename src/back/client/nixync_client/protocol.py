"""The wire contract between a Nixync client and the server.

Every message that crosses the socket is defined here and nowhere else, so a change to
the server's protocol touches exactly one file on the client side.
"""

from dataclasses import dataclass, field


@dataclass
class MachineConfig:
    """A machine's declared configuration, as the server stores and pushes it."""

    packages: list[str] = field(default_factory=list)
    users: list[str] = field(default_factory=list)
    groups: list[str] = field(default_factory=list)
    services: list[str] = field(default_factory=list)
    # Hostname, timezone, firewall, SSH, local users — NixOS configuration too, so it
    # rides in the same declarative payload. Free-form: the desktop app owns the schema.
    settings: dict = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict) -> "MachineConfig":
        # Missing keys are tolerated so a trimmed payload cannot crash an agent.
        return cls(
            packages=list(data.get("packages") or []),
            users=list(data.get("users") or []),
            groups=list(data.get("groups") or []),
            services=list(data.get("services") or []),
            settings=dict(data.get("settings") or {}),
        )

    def to_dict(self) -> dict:
        return {
            "packages": list(self.packages),
            "users": list(self.users),
            "groups": list(self.groups),
            "services": list(self.services),
            "settings": dict(self.settings),
        }


@dataclass(frozen=True)
class ApplyConfig:
    """A server push asking the machine to reconcile to this full desired state."""

    apply_id: str
    config: MachineConfig


@dataclass(frozen=True)
class UnknownMessage:
    """A message type this client version does not understand."""

    type: str
    payload: dict


def telemetry_message(
    *,
    cpu_percent: float,
    ram_used_mb: int,
    ram_total_mb: int,
    disk_used_gb: float,
    disk_total_gb: float,
) -> dict:
    return {
        "type": "telemetry",
        "cpu_percent": cpu_percent,
        "ram_used_mb": ram_used_mb,
        "ram_total_mb": ram_total_mb,
        "disk_used_gb": disk_used_gb,
        "disk_total_gb": disk_total_gb,
    }


def config_report_message(config: MachineConfig) -> dict:
    return {"type": "config_report", "config": config.to_dict()}


def apply_result_message(apply_id: str, *, applied: bool, message: str | None = None) -> dict:
    return {
        "type": "apply_result",
        "apply_id": apply_id,
        "status": "applied" if applied else "failed",
        "message": message,
    }


def parse_server_message(message: dict) -> ApplyConfig | UnknownMessage:
    message_type = message.get("type")
    if message_type == "apply_config":
        if "apply_id" not in message:
            raise ValueError("apply_config message is missing apply_id")
        return ApplyConfig(
            apply_id=message["apply_id"],
            config=MachineConfig.from_dict(message.get("config") or {}),
        )
    return UnknownMessage(type=str(message_type), payload=message)
