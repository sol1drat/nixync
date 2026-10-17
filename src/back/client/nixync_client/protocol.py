"""The wire contract between a Nixync client and the server.

Every message that crosses the socket is defined here and nowhere else, so a change to
the server's protocol touches exactly one file on the client side.
"""

from dataclasses import dataclass, field


@dataclass
class LocalUser:
    """A user account on the machine. Never carries a password — see the server model."""

    name: str
    full_name: str = ""
    admin: bool = False

    @classmethod
    def from_dict(cls, data: dict) -> "LocalUser":
        return cls(
            name=data.get("name", ""),
            full_name=data.get("full_name", ""),
            admin=bool(data.get("admin", False)),
        )

    def to_dict(self) -> dict:
        return {"name": self.name, "full_name": self.full_name, "admin": self.admin}


@dataclass
class SystemSettings:
    """Machine-level NixOS options the desktop app edits and an agent applies."""

    hostname: str = ""
    timezone: str = "UTC"
    nameservers: list[str] = field(default_factory=list)
    firewall: bool = True
    open_tcp_ports: list[int] = field(default_factory=lambda: [22])
    ssh: bool = True
    ssh_password_login: bool = False
    ssh_root_login: str = "no"
    bluetooth: bool = False
    sound: bool = True
    docker: bool = False
    allow_unfree: bool = True
    users: list[LocalUser] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict) -> "SystemSettings":
        known = {f for f in cls.__dataclass_fields__ if f != "users"}
        # Unknown keys are dropped: a newer server may send a setting this build does
        # not understand, and losing one toggle beats refusing to read the machine.
        values = {k: v for k, v in (data or {}).items() if k in known}
        settings = cls(**values)
        settings.users = [LocalUser.from_dict(u) for u in (data or {}).get("users", [])]
        return settings

    def to_dict(self) -> dict:
        data = {
            f: getattr(self, f) for f in self.__dataclass_fields__ if f != "users"
        }
        data["users"] = [u.to_dict() for u in self.users]
        return data


@dataclass
class MachineConfig:
    """A machine's declared configuration, as the server stores and pushes it."""

    packages: list[str] = field(default_factory=list)
    users: list[str] = field(default_factory=list)
    groups: list[str] = field(default_factory=list)
    services: list[str] = field(default_factory=list)
    # Hostname, timezone, firewall, SSH, local users — NixOS configuration too, so it
    # rides in the same declarative payload. None means nobody has configured this
    # machine yet, which is not the same as configuring it to the defaults.
    settings: SystemSettings | None = None

    @classmethod
    def from_dict(cls, data: dict) -> "MachineConfig":
        # Missing keys are tolerated so a trimmed payload cannot crash an agent.
        return cls(
            packages=list(data.get("packages") or []),
            users=list(data.get("users") or []),
            groups=list(data.get("groups") or []),
            services=list(data.get("services") or []),
            settings=(
                SystemSettings.from_dict(data["settings"])
                if data.get("settings") is not None
                else None
            ),
        )

    def to_dict(self) -> dict:
        return {
            "packages": list(self.packages),
            "users": list(self.users),
            "groups": list(self.groups),
            "services": list(self.services),
            "settings": self.settings.to_dict() if self.settings else None,
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
