"""Client library for the Nixync fleet server.

Two entry points sharing one wire protocol:

* `NixyncAgent` — runs on a managed NixOS machine. Holds a persistent WebSocket, reports
  CPU/RAM/disk, and hands each inbound configuration push to your `on_apply` handler.
* `AdminClient` — used by the desktop host app. Register, list and remove machines, and
  request package changes over plain REST.

`nixync_client.qt` adds an optional PySide6 adapter; importing *this* module never
requires Qt, so the agent still runs headless.

    from nixync_client import AdminClient, NixyncAgent

    admin = AdminClient("http://127.0.0.1:8000")
    machine = admin.register_machine("lab-01")

    agent = NixyncAgent(
        server_url="http://127.0.0.1:8000",
        machine_id=machine.id,
        on_apply=lambda config: render_configuration_nix(config),
    )
    asyncio.run(agent.run())
"""

from nixync_client.admin import (
    AdminClient,
    AppRequest,
    Bundle,
    Machine,
    NixyncApiError,
    PackageChangeResult,
    Preset,
)
from nixync_client.agent import NixyncAgent
from nixync_client.protocol import ApplyConfig, LocalUser, MachineConfig, SystemSettings
from nixync_client.telemetry import Reading, sample
from nixync_client.transport import (
    AgentDisconnected,
    NixyncClientError,
    UnknownMachineError,
)

__all__ = [
    "AdminClient",
    "AgentDisconnected",
    "AppRequest",
    "ApplyConfig",
    "Bundle",
    "LocalUser",
    "Machine",
    "MachineConfig",
    "NixyncAgent",
    "NixyncApiError",
    "NixyncClientError",
    "PackageChangeResult",
    "Preset",
    "Reading",
    "SystemSettings",
    "UnknownMachineError",
    "sample",
]
