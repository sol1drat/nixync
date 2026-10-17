# Spec: Nixync Fleet Server (MVP)

## Objective

Build the FastAPI server that is the hub of the Nixync control center. It is the only
component in scope here — see Boundaries. Two distinct consumers talk to it:

- **Machine agents** — the script running on each managed NixOS box (`src/back/client`,
  out of scope, not modified by this spec). Each agent holds one persistent WebSocket
  connection to the server for its whole lifetime: it pushes telemetry and config-sync
  messages up, and receives package-change commands down the same socket.
- **Admin client** — the desktop GUI (`src/front`). It talks to the server over plain
  REST: register/remove machines, list fleet status, and request package changes.

Success looks like: an admin registers a machine, a (future/stubbed) agent connects and
reports telemetry + its real `configuration.nix` as JSON, the admin asks for a package to
be added to one or more machines, the server pushes that change down the socket, and the
admin can see whether it was applied, failed, or is still queued for a machine that's
currently offline.

No authentication/authorization in this MVP — any request bearing a machine ID that
exists in the database is trusted at face value.

## Tech Stack

- **FastAPI** + **uvicorn** (already in `requirements.txt`) — HTTP + native WebSocket
  support, no separate socket library needed.
- **Pydantic** (already present) — request/response schemas and config validation.
- **`sqlite3`** (stdlib) — no new runtime dependency. A single `nixync.db` file holds one
  `machines` table. No ORM: an MVP with one table doesn't need SQLAlchemy/SQLModel
  weight; a thin repository module wraps the raw SQL.
- **New dev-only dependencies**: `pytest`, `httpx` (required by FastAPI's `TestClient` in
  the Starlette version already pinned). Both added to `requirements.txt`.

## Project Structure

Flat module layout inside the existing `src/back/server/` directory (matches the existing
style — no `__init__.py`, run directly with `uvicorn server:app`):

```
src/back/server/
  server.py              # FastAPI app instance, mounts routers, startup DB init
  database.py            # sqlite3 connection + schema creation + repository functions
  models.py              # Pydantic schemas (MachineConfig, MachineOut, WS message types, ...)
  connection_manager.py  # in-memory registry of live WebSocket connections per machine_id
  machines_router.py     # REST: register/list/get/remove machine, package mutation
  ws_router.py           # WebSocket endpoint: /ws/machines/{machine_id}
  SPEC.md                # this file
  tasks/
    plan.md
    todo.md
  tests/
    test_machines_api.py
    test_ws_protocol.py
nixync.db                # sqlite file, created at runtime — gitignored
```

## Data Model

Single table, `machines`:

| Column | Type | Notes |
|---|---|---|
| `id` | TEXT PK | server-generated UUID4, assigned at registration |
| `name` | TEXT | admin-provided label |
| `created_at` | TEXT (ISO 8601) | registration time |
| `cpu_percent` | REAL, nullable | latest telemetry |
| `ram_used_mb` / `ram_total_mb` | INTEGER, nullable | latest telemetry |
| `disk_used_gb` / `disk_total_gb` | REAL, nullable | latest telemetry |
| `metrics_reported_at` | TEXT, nullable | timestamp of last telemetry message |
| `config_json` | TEXT | **Desired** state — what the admin declared. See `MachineConfig` below |
| `reported_config_json` | TEXT, nullable | **Reported** state — what the machine says it actually has. NULL until it first reports |
| `last_apply_id` | TEXT, nullable | UUID correlating the most recent push with its ack |
| `last_apply_status` | TEXT, nullable | `pending` \| `applied` \| `failed` |
| `last_apply_message` | TEXT, nullable | agent-supplied reason, mainly for `failed` |
| `last_apply_at` | TEXT, nullable | timestamp of the last ack received |

`config_json` deserializes to:

```json
{
  "packages": ["git", "htop"],
  "users": [],
  "groups": [],
  "services": []
}
```

### Desired vs reported state

These are two different things and must never share a column. `config_json` is the
admin's intent; `reported_config_json` is the machine's truth. Conflating them caused a
real bug: a machine booting into queued work reported "I have nothing installed", which
erased the pending change, so the machine installed the right packages while the
dashboard showed an empty list beside a green `applied` badge.

Two rules follow:

- **Enrollment.** The first `config_report` from a machine that has never been deployed
  to (`last_apply_id IS NULL`) is *also* adopted as the desired config. Existing machines
  join the fleet with their current setup intact, so the admin's first package add
  extends it rather than declaring a desired state of one package and having the agent
  reconcile everything else away.
- **After that, only the admin changes desired state.** A later report updates only
  `reported_config_json`. The difference between the two is **configuration drift** —
  someone hand-edited the box — which the fleet view surfaces rather than silently
  adopting.

Agents re-send `config_report` immediately after an `apply_result`, so reported state
stays fresh after every deployment. Without that it would only be as current as the last
connect, and every deployed machine would look drifted.

Only `packages` has a mutation endpoint in this MVP. `users`/`groups`/`services` exist in
the schema now (per CLAUDE.md's planned config surface) but are populated only by what the
agent reports of its real state (see `config_report` below) — there is no admin-facing
endpoint to edit them yet, and that's intentionally out of scope here.

**"Online" is defined as "currently holds an open WebSocket connection"** — tracked only
in `connection_manager`'s in-memory dict, not persisted. This is simpler and more honest
than a staleness timeout given the architecture already keeps the socket open for the
agent's whole lifetime: a closed socket means offline, full stop, no guessing window.

## WebSocket Protocol

Endpoint: `ws://<server>/ws/machines/{machine_id}`

The server closes the connection immediately (code 4404) if `machine_id` is not a
registered machine — an agent must be registered via REST before it can connect.

All messages are JSON objects with a `type` discriminator.

**Agent → server**

| type | Payload | When |
|---|---|---|
| `telemetry` | `cpu_percent: float, ram_used_mb: int, ram_total_mb: int, disk_used_gb: float, disk_total_gb: float` | every 2 minutes |
| `config_report` | `config: MachineConfig` | once, right after the connection opens |
| `apply_result` | `apply_id: str, status: "applied" \| "failed", message: str \| null` | after processing an `apply_config` push |

**Server → agent**

| type | Payload | When |
|---|---|---|
| `apply_config` | `apply_id: str, config: MachineConfig` | right after a package-mutation request targets this machine; also re-sent once immediately on connect if `last_apply_status == "pending"` (so an agent that was offline when the change was requested still gets it without the admin re-requesting) |

Design choice: the server always pushes the **full desired config**, never a diff
("add htop"). Nix configuration is declarative — reconciling the whole desired state each
time is the only representation that can't drift, and it's exactly what
`CLAUDE.md` means by "manage configuration declaratively rather than silently changing a
machine outside its declared setup."

`apply_result` is matched against `last_apply_id` in the database; an ack whose `apply_id`
doesn't match the currently stored one is a stale reply to a superseded push and is
ignored.

## REST API

All under no auth, consumed by `src/front`.

- `POST /machines` — body `{name: str}` → creates row, generates `id`, returns the full
  `MachineOut`. The admin is responsible for handing this `id` to the agent out of band
  (agent provisioning is out of scope).
- `DELETE /machines/{machine_id}` — deletes the row; if currently connected, the server
  closes that WebSocket.
- `GET /machines` — list all machines with `online` (computed), latest telemetry, config,
  and last-apply status.
- `GET /machines/{machine_id}` — single machine, same shape.
- `POST /machines/packages` — body:
  ```json
  {"action": "add" | "remove", "packages": ["htop"], "machine_ids": ["id1", "id2"] | null}
  ```
  `machine_ids: null` (or omitted) means **all currently registered machines** — this is
  the "add to all machines simultaneously" request, folded into one endpoint rather than a
  duplicate one, since the only difference is which rows get selected.
  For each targeted machine: compute the desired `packages` list (add is a dedup'd
  insert, remove is a filter), stamp a fresh `apply_id` + `pending` status, and push
  `apply_config` if connected. Response:
  ```json
  {"results": [{"machine_id": "id1", "delivery": "pushed" | "queued" | "unchanged", "apply_id": "..."}]}
  ```

  **No-op changes are skipped.** If the desired config already equals the stored config
  *and* the machine's `last_apply_status` is `applied`, the machine is left completely
  alone: no new `apply_id`, no push, status stays `applied`, and `delivery` is
  `unchanged` (with `apply_id` referring to the earlier deployment that proved it).
  Without this, a fleet-wide add would drag every already-compliant machine back to
  `pending` — and offline ones would sit there indefinitely — making the dashboard
  overstate outstanding work. A machine whose last apply `failed` or is still `pending`
  is **always** redeployed even when the config matches, because the server cannot prove
  such a machine is actually in its stored state.

OpenAPI schema is FastAPI's generated `/openapi.json` (interactive docs at `/docs`) — no
hand-maintained copy; it's exported to a file as a build step (see Commands) so it can be
committed/diffed if desired.

## Commands

```bash
# install (from repo root)
pip install -r requirements.txt

# run the dev server
cd src/back/server && uvicorn server:app --reload --host 0.0.0.0 --port 8000

# run tests
cd src/back/server && pytest

# export the OpenAPI schema to a file
cd src/back/server && python -c "import json; from server import app; json.dump(app.openapi(), open('openapi.json', 'w'), indent=2)"
```

## Code Style

Match the existing repo: plain functions over classes where a class adds no behavior,
type hints on every signature, Pydantic models for anything crossing an API boundary.
Example (shape, not final code):

```python
class MachineConfig(BaseModel):
    packages: list[str] = []
    users: list[str] = []
    groups: list[str] = []
    services: list[str] = []


def add_packages(conn: sqlite3.Connection, machine_id: str, packages: list[str]) -> MachineConfig:
    config = get_config(conn, machine_id)
    config.packages = sorted(set(config.packages) | set(packages))
    save_config(conn, machine_id, config)
    return config
```

## Testing Strategy

- `pytest` + FastAPI's `TestClient` (sync, backed by `httpx`).
- `tests/test_machines_api.py` — registration, listing, deletion, package mutation
  (targeted subset and `machine_ids: null` → all), using a temp sqlite file per test.
- `tests/test_ws_protocol.py` — `TestClient.websocket_connect` to drive the full
  lifecycle: connect, `config_report`, `telemetry` updates visible via `GET /machines`,
  a package push received after a `POST /machines/packages` call, `apply_result` closing
  the loop, and the "queued while offline, delivered on reconnect" path.
- No coverage threshold enforced for this MVP; every new endpoint and WS message type
  gets at least one test.

## Boundaries

- **Always do:** run `pytest` before considering a task done; keep `config_json` changes
  going through the repository functions in `database.py` (never raw SQL in routers);
  keep the WebSocket protocol's message `type` values and fields exactly as specified
  above since the (out-of-scope) agent script will be written against this contract.
- **Ask first:** adding any new runtime (non-dev) dependency; changing the WS message
  schema once written; anything involving the agent script in `src/back/client`.
- **Never do:** add authentication/authorization (explicitly deferred past MVP), touch
  `src/front` or `src/back/client`, add a roles/presets/updates endpoint (not requested
  yet — `src/front`'s TODOs for those stay TODOs).

## Success Criteria

- `POST /machines` → `DELETE /machines/{id}` round-trips cleanly.
- A simulated WS client can connect, send `config_report` + `telemetry`, and see both
  reflected in `GET /machines/{id}`.
- `POST /machines/packages` with an explicit `machine_ids` list only touches those rows;
  with `machine_ids: null` it touches every registered machine.
- A package push to a connected simulated client arrives as `apply_config` with the full
  merged config; sending back `apply_result` updates `last_apply_status`.
- A package push targeting a machine with no open socket is marked `queued`, and is
  delivered automatically the next time that machine's socket connects.
- `GET /openapi.json` (or the exported file) validates as OpenAPI 3.x.
- All tests in `tests/` pass via `pytest`.

## Open Questions

1. Should `config_report` also be re-sent by the agent whenever its local config drifts
   out of band (manual edit on the box), or only once at connect time? Spec currently
   assumes once-at-connect; revisit once the agent script exists.
2. Metrics are latest-snapshot only, no history — fine for the fleet dashboard's current
   status, but historical graphing (if ever wanted) would need a separate time-series
   table. Not needed for this MVP.
3. `src/front`'s `NixyncClient` still has `list_roles`/`current_update` TODOs backed by
   sample data — intentionally untouched here since roles/presets/updates weren't part of
   this request.
