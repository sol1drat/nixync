from typing import Literal

from pydantic import BaseModel, Field


class LocalUser(BaseModel):
    """A user account on a managed machine.

    No password field, deliberately: passwords are set on the device and hashed
    there, and must never reach a Nix configuration or this server's database.
    """

    name: str
    full_name: str = ""
    admin: bool = False  # member of "wheel", so can use sudo


class SystemSettings(BaseModel):
    """The machine-level NixOS options the desktop app can edit."""

    hostname: str = ""
    timezone: str = "UTC"
    nameservers: list[str] = []
    firewall: bool = True
    open_tcp_ports: list[int] = [22]
    ssh: bool = True
    ssh_password_login: bool = False
    ssh_root_login: Literal["no", "prohibit-password", "yes"] = "no"
    bluetooth: bool = False
    sound: bool = True
    docker: bool = False
    allow_unfree: bool = True
    users: list[LocalUser] = []


class MachineConfig(BaseModel):
    packages: list[str] = []
    users: list[str] = []
    groups: list[str] = []
    services: list[str] = []
    # Hostname, timezone, firewall, SSH and local users are NixOS configuration like
    # the package list, so they travel in the same declarative payload an agent
    # reconciles against. None means no one has configured this machine yet, which is
    # different from having configured it to the defaults.
    settings: SystemSettings | None = None


class Bundle(BaseModel):
    """A named group of configuration a preset can switch on or off."""

    name: str
    description: str = ""
    enabled: bool = True


class Preset(BaseModel):
    """A reusable role — "workstation", "build server" — applied to machines."""

    name: str
    bundles: list[Bundle] = []
    extra_apps: list[str] = []


class MachineOut(BaseModel):
    id: str
    name: str
    created_at: str
    preset: str = ""
    group: str = ""
    address: str = ""
    online: bool
    cpu_percent: float | None = None
    ram_used_mb: int | None = None
    ram_total_mb: int | None = None
    disk_used_gb: float | None = None
    disk_total_gb: float | None = None
    metrics_reported_at: str | None = None
    config: MachineConfig
    reported_config: MachineConfig | None = None
    last_apply_id: str | None = None
    last_apply_status: str | None = None
    last_apply_message: str | None = None
    last_apply_at: str | None = None


class MachineCreate(BaseModel):
    name: str
    preset: str = ""
    group: str = ""
    address: str = ""


class MachineUpdate(BaseModel):
    """Partial edit of a machine's labels. Omitted fields are left alone."""

    name: str | None = None
    preset: str | None = None
    group: str | None = None
    address: str | None = None


class LoginRequest(BaseModel):
    username: str
    password: str


class LoginResponse(BaseModel):
    username: str


class TelemetryIn(BaseModel):
    cpu_percent: float
    ram_used_mb: int
    ram_total_mb: int
    disk_used_gb: float
    disk_total_gb: float


class ConfigReportIn(BaseModel):
    config: MachineConfig


class ApplyResultIn(BaseModel):
    apply_id: str
    status: str
    message: str | None = None


class ApplyConfigOut(BaseModel):
    type: str = "apply_config"
    apply_id: str
    config: MachineConfig


class PackageMutationRequest(BaseModel):
    action: Literal["add", "remove"]
    packages: list[str]
    machine_ids: list[str] | None = None


class PackageMutationResultItem(BaseModel):
    machine_id: str
    delivery: Literal["pushed", "queued", "unchanged"] = Field(
        description=(
            "`pushed`: sent to a connected agent. "
            "`queued`: the agent is offline; it is delivered on reconnect. "
            "`unchanged`: the machine already proved this exact configuration, so no "
            "deployment was created and `apply_id` refers to that earlier one."
        )
    )
    apply_id: str


class PackageMutationResponse(BaseModel):
    results: list[PackageMutationResultItem]


class AppRequest(BaseModel):
    """Someone at a machine asking for software they cannot install themselves."""

    id: int
    machine_id: str
    machine_name: str
    app: str
    requested_by: str
    reason: str = ""
    status: Literal["pending", "approved", "declined"] = "pending"
    created_at: str
    decided_at: str | None = None


class AppRequestCreate(BaseModel):
    machine_id: str
    app: str
    requested_by: str
    reason: str = ""


class SettingsUpdate(BaseModel):
    settings: SystemSettings
