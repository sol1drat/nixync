# nixync_client

Client library for the Nixync fleet server. One package, two entry points, one wire
protocol — so neither the desktop app nor a managed machine hand-rolls JSON or sockets.

| | |
|---|---|
| `NixyncAgent` | Runs on a managed NixOS box. Persistent WebSocket, reports CPU/RAM/disk, applies configuration pushes. |
| `AdminClient` | Used by the host GUI. REST calls to register, list and remove machines and change packages. |
| `nixync_client.qt` | Optional PySide6 adapter. Importing the library itself never requires Qt. |

## Machine agent

```python
import asyncio
from nixync_client import MachineConfig, NixyncAgent

def apply_config(config: MachineConfig) -> None:
    """Reconcile to the full desired state. Raise to report failure."""
    render_configuration_nix(config)
    nixos_rebuild_switch()

agent = NixyncAgent(
    server_url="http://127.0.0.1:8000",
    machine_id="<uuid the server returned at registration>",
    on_apply=apply_config,
    current_config=read_configuration_nix,   # what this box actually has
)
asyncio.run(agent.run())        # reconnects on its own until stop()
```

The library never touches `configuration.nix` itself — it validates what the server
sends and calls your handler. Returning normally acks `applied`; raising acks `failed`
with the exception text, which is what the admin sees beside the machine. The handler
runs off the event loop, so a slow `nixos-rebuild` cannot stall telemetry.

Connecting with an id the server does not know raises `UnknownMachineError` instead of
retrying forever. Ordinary disconnects are retried with capped backoff (1s → 30s).

See `example_agent.py` for a runnable version:

```sh
curl -X POST http://127.0.0.1:8000/machines \
     -H 'Content-Type: application/json' -d '{"name":"lab-01"}'
python example_agent.py --server http://127.0.0.1:8000 --machine-id <uuid>
```

## Admin client

```python
from nixync_client import AdminClient

admin = AdminClient("http://127.0.0.1:8000")     # the login screen's server URL

machine = admin.register_machine("lab-01")        # the server mints the id
admin.add_packages(["htop"], machine_ids=[machine.id])
admin.add_packages(["git"])                       # no ids == the whole fleet

for m in admin.list_machines():
    print(m.name, m.online, m.cpu_percent, m.last_apply_status, m.has_drifted)
```

Every failure — HTTP error or unreachable server — raises `NixyncApiError`, so the GUI
never has to catch `requests` exceptions. `status_code` is `None` when no response
arrived at all.

`AdminClient` is **synchronous**: call it from a worker thread, not the Qt UI thread.

### Desired vs reported configuration

`machine.config` is what the admin declared; `machine.reported_config` is what the
machine says it actually has (`None` until it first reports in). `machine.has_drifted`
is true when they differ — someone changed the box outside Nixync.

A machine joining the fleet has its existing setup adopted as the desired config, so
the first package add extends it rather than wiping everything else.

## Qt integration

```python
from nixync_client.qt import QtAgent

self.agent = QtAgent(server_url, machine_id, on_apply=apply_config)
self.agent.connected.connect(self.show_online)
self.agent.disconnected.connect(self.show_offline)
self.agent.telemetry_sent.connect(self.show_metrics)      # dict of the reading
self.agent.config_received.connect(self.show_pending)     # apply_id
self.agent.apply_finished.connect(self.show_result)       # apply_id, ok, message
self.agent.error.connect(self.show_error)
self.agent.start()      # own thread; never blocks the UI
...
self.agent.stop()       # safe from the UI thread, returns promptly
```

Signals emitted from the worker thread arrive as queued connections, so slots run on the
UI thread and may touch widgets. `on_apply` does **not** — it runs on the worker.

## Tests

```sh
.venv/bin/python -m pytest src/back/client -q
```

Most tests run against a real `uvicorn server:app` over real sockets: an in-process
double once hid the fact that uvicorn could not serve WebSockets at all.

The Qt tests skip when PySide6 is missing *or* unusable. On NixOS the pip wheel cannot
find its native libraries, so point it at them:

```sh
export LD_LIBRARY_PATH=/nix/store/<gcc-lib>/lib:/nix/store/<zstd>/lib
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest src/back/client -q
```
