# Task List: Nixync Client Library

Spec: `../SPEC.md`

Build order is bottom-up: the wire contract and telemetry have no dependencies, the
transport sits on the contract, the agent sits on both, and the Qt adapter wraps the
finished agent. Each phase leaves the package importable and the suite green.

## Phase 1: Foundation

- [x] **C1 — Wire protocol** (`protocol.py`)
  - Acceptance: `MachineConfig`, `ApplyConfig`, and builders for `telemetry`,
    `config_report`, `apply_result`; every message round-trips dict → object → dict;
    an unknown message type is reported, not silently dropped.
  - Verify: `pytest tests/test_protocol.py`
  - Files: `nixync_client/protocol.py`, `tests/test_protocol.py`

- [x] **C2 — Telemetry sampling** (`telemetry.py`)
  - Acceptance: parses fixture `/proc/stat` and `/proc/meminfo` text into CPU percent
    and RAM MB; `shutil.disk_usage` converted to GB; parsing is a pure function fed by
    text, so it is testable without touching the real `/proc`.
  - Verify: `pytest tests/test_telemetry.py`
  - Files: `nixync_client/telemetry.py`, `tests/test_telemetry.py`

### Checkpoint: Foundation
- [x] Both unit suites pass; no sockets involved yet

## Phase 2: The agent

- [x] **C3 — WebSocket transport** (`transport.py`)
  - Acceptance: async connect/send_json/receive/close; close code 4404 surfaces as
    `UnknownMachineError`; a normal drop surfaces as a plain disconnect.
  - Verify: `pytest tests/test_transport.py`
  - Files: `nixync_client/transport.py`, `tests/test_transport.py`

- [x] **C4 — NixyncAgent** (`agent.py`)
  - Acceptance: sends `config_report` then a first telemetry sample on connect; sends
    telemetry every interval; routes `apply_config` to `on_apply` and acks `applied`;
    a raising handler acks `failed` with the exception text; `stop()` ends `run()`;
    reconnects with capped backoff but gives up on 4404.
  - Verify: `pytest tests/test_agent.py` (fake transport, no real sockets)
  - Files: `nixync_client/agent.py`, `tests/test_agent.py`

### Checkpoint: Agent works
- [x] Agent unit suite passes against a fake transport
- [x] `test_agent_end_to_end.py` drives a real agent against a real uvicorn server

## Phase 3: GUI-facing pieces

- [x] **C5 — AdminClient** (`admin.py`)
  - Acceptance: register / list / get / remove machines and change packages; HTTP errors
    raise a typed `NixyncApiError` carrying status and server detail.
  - Verify: `pytest tests/test_admin.py` against a real server
  - Files: `nixync_client/admin.py`, `tests/test_admin.py`,
    `tests/test_fleet_end_to_end.py`, `tests/conftest.py`

- [x] **C8 — Separate desired from reported config** (server `reported_config_json`
  column, enrollment adoption, agent re-reports after each apply, `Machine.has_drifted`)

## FIXED: bug found by the combined end-to-end suite

**The server conflates desired and reported configuration.** `config_json` holds both the
admin's desired state and the agent's reported actual state, so an agent that connects
while a change is pending overwrites that change with its (still unapplied) current
state. The machine then installs the right packages and acks `applied`, while the
dashboard shows an empty package list beside a green badge.

Hit the recovery path — a machine booting into queued work — the headline feature, not
an edge case.

**Fixed in C8.** The server gained a `reported_config_json` column: desired state stays
admin-owned, reported state stays agent-owned. Two consequences fell out of the fix and
are now specified behaviour:

- **Enrollment** — the first report from a never-deployed machine is also adopted as the
  desired config, so an existing machine joins the fleet with its setup intact and the
  admin's first package add extends it rather than reconciling everything else away.
- **Re-reporting** — the agent re-sends `config_report` after every `apply_result`.
  Without it, reported state would only ever be as fresh as the last connect and every
  deployed machine would read as drifted.

The difference between the two configs is now surfaced as `Machine.has_drifted` —
configuration drift detection, which CLAUDE.md implicitly wants.

- [x] **C6 — Qt adapter** (`qt.py`)
  - Acceptance: `QtAgent` exposes `connected`/`disconnected`/`telemetry_sent`/
    `config_received`/`error` signals; `start()` runs the agent off the UI thread;
    `stop()` shuts the thread down cleanly; importing it without PySide6 raises a clear
    install message.
  - Verify: `pytest tests/test_qt_adapter.py` (skips when PySide6 is absent)
  - Files: `nixync_client/qt.py`, `tests/test_qt_adapter.py`

- [x] **C7 — Replace the old client + reference example**
  - Acceptance: `client.py` deleted with no remaining references; `example_agent.py`
    runs a real agent in ~20 lines; `__init__.py` exports the public API; README section
    showing both the agent and the Qt usage.
  - Verify: full `pytest src/back/client` and `pytest src/back/server` green

### Checkpoint: Complete
- [x] Both suites green — 157 with Qt, 148 + 1 skip without
- [x] `import nixync_client` works with PySide6 absent
- [x] Example agent demonstrably drives a real server

## Bugs found while building C6 (the Qt adapter)

Both were in code written earlier in this phase; both are fixed and covered.

1. **`NixyncAgent.stop()` was not thread-safe** despite its docstring saying so. It set
   an `asyncio.Event` directly, which does not wake a loop running on another thread.
   A Qt app calling `stop()` from the UI thread would hang on close until some unrelated
   event (a WebSocket keepalive) happened to wake the agent — several seconds. Now hops
   through `loop.call_soon_threadsafe`.
   *Catching it took three attempts:* asserting the thread died was not enough, because
   it did die — just slowly. The test now asserts `stop()` **returns promptly**, and
   only after waiting for telemetry so the agent's loop is genuinely idle, which is the
   single state where the defect shows.

2. **`QtAgent.stop()` leaked a hung worker thread.** It cleared `self._thread`
   unconditionally after a `join(timeout)`, so a thread that never exited was forgotten
   while `is_running` reported `False` — a hung agent that looked stopped. It now keeps
   the reference and emits `error` instead.

## Environment note

PySide6 is intentionally **not** in the root `requirements.txt`; the Qt binding is
optional and `src/front/requirements.txt` already declares it. On NixOS the pip wheel
cannot find its native libraries, so the Qt tests skip unless `LD_LIBRARY_PATH` points
at a 64-bit `libstdc++`, `libzstd` and `libglib` (see README). The skip is deliberate:
`pytest.importorskip` only catches `ModuleNotFoundError`, so the module catches
`ImportError` instead — otherwise a half-installed PySide6 errors the whole suite.
