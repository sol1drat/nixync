from typing import Any, Literal

from pydantic import BaseModel, Field


class MachineConfig(BaseModel):
    packages: list[str] = []
    users: list[str] = []
    groups: list[str] = []
    services: list[str] = []
    # Hostname, timezone, firewall, SSH and local users: all NixOS configuration, so it
    # travels in the same declarative payload an agent reconciles against. Free-form
    # because the desktop app owns the schema; the server only stores and forwards it.
    settings: dict[str, Any] = {}


class MachineOut(BaseModel):
    id: str
    name: str
    created_at: str
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


class SettingsUpdate(BaseModel):
    settings: dict[str, Any] = {}
