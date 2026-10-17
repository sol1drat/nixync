# Spec: Nixync Client Library (`nixync_client`)

## Objective

One importable package in `src/back/client/` that owns the wire protocol to the Nixync
server, so neither the machine agent nor the PySide6 host GUI hand-rolls JSON or
WebSocket plumbing. It replaces the current `src/back/client/client.py`, which polls a
`GET /status` endpoint from an older, inverted architecture and is now dead.

Two consumers, one transport:

- **`NixyncAgent`** — runs on a managed NixOS box. Holds one persistent WebSocket to the
  server, reports that machine's CPU/RAM/disk on an interval, and hands every inbound
  `apply_config` push to a handler the caller registers, acking `applied`/`failed` with
  whatever that handler reports.
- **`AdminClient`** — used by the host GUI (`src/front`). Thin, typed wrapper over the
  server's REST endpoints: register/list/get/remove machines and request package changes.

Success looks like: the GUI picks a server URL on its login screen, constructs one of
these, and never touches `json.dumps` or a socket. The agent runs headless on a NixOS box
with no Qt installed.

Scope is deliberately an MVP first iteration — see Boundaries.

## Design Decisions

Settled before writing code:

1. **One package, two clients.** `NixyncAgent` and `AdminClient` ship together and share
   `protocol.py`, so the message contract lives in exactly one place. Server-side changes
   break one file, not two codebases.
2. **The library never touches `configuration.nix`.** It parses and validates an
   `apply_config` push, then calls a caller-supplied handler. The handler's return (or
   raised exception) decides the ack. Nothing needs root, so the whole library is safe to
   run and test on a dev machine or inside a GUI.
3. **The core has no PySide6 dependency.** `agent.py`/`admin.py` are pure asyncio +
   callbacks. A separate `qt.py` adapter — imported only when wanted — wraps the agent in
   a `QObject` with Qt Signals and runs its event loop off the UI thread. PySide6 is not
   installed in the repo venv, so its tests skip rather than fail.
4. **Telemetry uses the standard library only.** `/proc/stat`, `/proc/meminfo` and
   `shutil.disk_usage`. No `psutil`, keeping the NixOS client package dependency-light.
   Linux-only, which is the only platform the agent targets.

## Tech Stack

- **`websockets` 17.2** — already a repo dependency (uvicorn needs it server-side).
- **`requests`** — already used by `src/front`; backs `AdminClient`.
- **stdlib**: `asyncio`, `shutil`, `dataclasses`, `json`.
- **Dev**: `pytest` (already present). PySide6 is an *optional* extra, never required.

## Project Structure

```
src/back/client/
  nixync_client/
    __init__.py       Public API: NixyncAgent, AdminClient, and the message types
    protocol.py       Message dataclasses + encode/decode; the single wire contract
    telemetry.py      Stdlib CPU/RAM/disk sampling
    transport.py      Async WebSocket connection: connect, send_json, receive loop
    agent.py          NixyncAgent — telemetry loop, apply_config dispatch, acking
    admin.py          AdminClient — REST wrapper for the host GUI
    qt.py             Optional PySide6 adapter (QtAgent, Qt Signals, worker thread)
  tests/
    test_protocol.py
    test_telemetry.py
    test_agent.py
    test_admin.py
    test_qt_adapter.py          skipped when PySide6 is absent
    test_agent_end_to_end.py    against a real uvicorn server
  SPEC.md
  example_agent.py    Runnable reference agent, ~20 lines
```

`src/back/client/client.py` is **deleted** — it targets an architecture that no longer
exists.

## Public API

```python
from nixync_client import AdminClient, ApplyConfig, MachineConfig, NixyncAgent

# --- machine side -------------------------------------------------------
def apply_to_this_machine(config: MachineConfig) -> None:
    """Raise to report failure; return normally to report success."""
    render_configuration_nix(config)   # the caller's job, not the library's

agent = NixyncAgent(
    server_url="http://127.0.0.1:8000",
    machine_id="uuid-from-registration",
    on_apply=apply_to_this_machine,
    telemetry_interval=120.0,
)
asyncio.run(agent.run())     # reconnects on its own until stop() is called

# --- host GUI side ------------------------------------------------------
admin = AdminClient("http://127.0.0.1:8000")
machine = admin.register_machine("lab-01")
admin.change_packages(action="add", packages=["htop"], machine_ids=[machine.id])
fleet = admin.list_machines()
```

Qt usage stays declarative, with no threading code in the GUI:

```python
from nixync_client.qt import QtAgent

self.agent = QtAgent(server_url, machine_id, on_apply=apply_to_this_machine)
self.agent.connected.connect(self.on_connected)
self.agent.disconnected.connect(self.on_disconnected)
self.agent.telemetry_sent.connect(self.show_metrics)
self.agent.config_received.connect(self.show_pending_change)
self.agent.error.connect(self.show_error)
self.agent.start()           # spawns its own thread; never blocks the UI
```

## Behaviour

- **Reconnection.** `run()` reconnects with capped exponential backoff (1s → 30s) until
  `stop()`. A dropped socket is normal for laptops, so it is not an error path. A close
  with code **4404** means the machine is not registered; that is fatal and `run()`
  raises `UnknownMachineError` instead of retrying forever against a server that will
  never accept it.
- **Telemetry.** One sample sent immediately on connect, then every
  `telemetry_interval` seconds (default 120, matching the server's expectation).
- **Config reporting.** The agent sends `config_report` once per connection, from an
  optional `current_config` callable. Omitted means the agent reports an empty config.
- **Acking.** On `apply_config`: call `on_apply(config)`. Returning normally sends
  `applied`; raising sends `failed` with `str(exception)` as the message. The handler
  runs in a thread executor so a slow `nixos-rebuild` cannot stall the socket.
- **Full desired state.** `apply_config` carries the machine's whole desired config, not
  a diff — the handler reconciles everything it is given.

## Commands

```bash
# tests (from the repo root)
.venv/bin/python -m pytest src/back/client -q

# run the reference agent against a local server
.venv/bin/python src/back/client/example_agent.py --server http://127.0.0.1:8000 --machine-id <uuid>
```

## Code Style

Match the server: type hints on every signature, dataclasses for wire messages, plain
functions where a class earns nothing.

```python
@dataclass(frozen=True)
class ApplyConfig:
    apply_id: str
    config: MachineConfig

    @classmethod
    def from_message(cls, message: dict) -> "ApplyConfig":
        return cls(apply_id=message["apply_id"], config=MachineConfig.from_dict(message["config"]))
```

## Testing Strategy

- `pytest`, mirroring the server suite's layering.
- **Unit**: protocol encode/decode, telemetry parsing against fixture `/proc` text, agent
  logic against a fake transport (no sockets).
- **Integration**: `test_agent_end_to_end.py` spawns a real `uvicorn server:app` and
  drives a real `NixyncAgent` against it — registration, telemetry landing in
  `GET /machines`, a package push reaching `on_apply`, and the ack updating the server.
  This layer exists because the server suite already proved that socket bugs hide from
  in-process test doubles.
- **Qt**: `pytest.importorskip("PySide6")`, run with `QT_QPA_PLATFORM=offscreen`.

## Boundaries

- **Always:** keep `protocol.py` the single definition of the wire format; keep the core
  importable without PySide6; run the full server + client suites before calling a task
  done.
- **Ask first:** adding any runtime dependency; changing the wire protocol (it would
  break the server); anything that writes to a real system file or shells out.
- **Never:** modify `src/front/**` (the user owns the GUI) or `src/back/server/**` in
  this phase; render or write `configuration.nix`; run `nixos-rebuild`; add auth.

## Success Criteria

- `src/back/client/client.py` is gone, and nothing references it.
- `NixyncAgent` connects to a real running server, reports telemetry visible via
  `GET /machines/{id}`, receives a package push, and its ack flips `last_apply_status`.
- A handler that raises produces `failed` on the server with the exception text.
- Connecting with an unregistered id raises `UnknownMachineError` rather than looping.
- `AdminClient` round-trips register → list → change packages → remove.
- `import nixync_client` succeeds with PySide6 absent; `nixync_client.qt` raises a clear
  error explaining how to install it.
- Full suite green: `pytest src/back/client` and `pytest src/back/server`.

## Open Questions

1. The host GUI's login screen chooses a server URL; does it also need to *discover* or
   persist machine ids, or does the operator paste the id the server returned at
   registration? Assumed the latter for this iteration.
2. `AdminClient` is synchronous. If the GUI wants live dashboard updates rather than
   polling, a future iteration could add an admin-side WebSocket — the server has no such
   endpoint today, so it is out of scope.
3. Telemetry is Linux-only by design. If the agent ever needs to run on the Windows host
   machine for self-monitoring, `telemetry.py` needs a per-platform branch.
