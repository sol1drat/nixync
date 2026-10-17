# Task List: Nixync Fleet Server (MVP)

Plan: `plan.md` · Spec: `../SPEC.md`

## Task 1: Persistence layer

**Description:** Create `models.py` (Pydantic schemas: `MachineConfig`, `MachineOut`,
`TelemetryIn`, `PackageMutationRequest`, `PackageMutationResult`, plus the WS message
payload shapes) and `database.py` (sqlite3 schema creation + repository functions:
`create_machine`, `get_machine`, `list_machines`, `delete_machine`, `update_telemetry`,
`save_config`, `set_apply_pending`, `set_apply_result`). No router or app wiring yet.

**Acceptance criteria:**
- [ ] `init_db(path)` creates the `machines` table with all columns from SPEC.md's Data Model
- [ ] Every repository function round-trips correctly against a temp sqlite file
- [ ] `MachineConfig` defaults to empty lists for all four fields

**Verification:**
- [ ] Tests pass: `cd src/back/server && pytest tests/test_database.py`
- [ ] Manual check: `python -c "from database import init_db; init_db('/tmp/t.db')"` creates a readable sqlite file

**Dependencies:** None

**Files likely touched:**
- `src/back/server/models.py`
- `src/back/server/database.py`
- `src/back/server/tests/test_database.py`

**Estimated scope:** Medium: 3 files

---

## Task 2: WebSocket connection manager

**Description:** Create `connection_manager.py` — an in-memory registry mapping
`machine_id -> WebSocket`, with `register`, `unregister`, `is_connected`, and an async
`send_json(machine_id, payload) -> bool` (returns whether a connected socket received it).

**Acceptance criteria:**
- [ ] `is_connected` is `False` for a never-registered id and `False` again after `unregister`
- [ ] `send_json` to an unconnected id returns `False` without raising

**Verification:**
- [ ] Tests pass: `pytest tests/test_connection_manager.py` (use a minimal fake WebSocket object with an async `send_json`/`close`)
- [ ] Manual check: none beyond unit tests — no app wiring yet

**Dependencies:** None

**Files likely touched:**
- `src/back/server/connection_manager.py`
- `src/back/server/tests/test_connection_manager.py`

**Estimated scope:** Small: 1-2 files

---

## Task 3: Machine registry REST endpoints

**Description:** Create `machines_router.py` with `POST /machines`, `DELETE
/machines/{machine_id}`, `GET /machines`, `GET /machines/{machine_id}`, using Task 1's
repository functions. Wire the router into a minimal `server.py` (app instance +
`include_router`, DB init on startup).

**Acceptance criteria:**
- [ ] `POST /machines` with `{"name": "..."}` returns a generated `id` and default empty config
- [ ] `DELETE /machines/{id}` on an unknown id returns 404; on a known id removes the row
- [ ] `GET /machines` reflects an `online` field that is `False` for every machine (no WS yet)

**Verification:**
- [ ] Tests pass: `pytest tests/test_machines_api.py`
- [ ] Manual check: `uvicorn server:app --reload` boots; `/docs` shows the four endpoints

**Dependencies:** Task 1

**Files likely touched:**
- `src/back/server/machines_router.py`
- `src/back/server/server.py`
- `src/back/server/tests/test_machines_api.py`

**Estimated scope:** Medium: 3 files

---

## Task 4: WebSocket protocol — connect, telemetry, config_report

**Description:** Create `ws_router.py` with `/ws/machines/{machine_id}`. Reject unknown
ids (close code 4404) before `accept()`. On accept: register in the connection manager; if
`last_apply_status == "pending"`, immediately send `apply_config`. Handle incoming
`telemetry` (→ `update_telemetry`) and `config_report` (→ `save_config`) messages. On
disconnect: unregister.

**Acceptance criteria:**
- [ ] Connecting with an unregistered `machine_id` closes immediately with code 4404
- [ ] A `telemetry` message updates the row such that `GET /machines/{id}` shows the new values and a fresh `metrics_reported_at`
- [ ] A `config_report` message overwrites `config_json`
- [ ] After disconnect, `GET /machines/{id}` shows `online: false`

**Verification:**
- [ ] Tests pass: `pytest tests/test_ws_protocol.py` (connect/telemetry/config_report/disconnect cases)
- [ ] Manual check: `TestClient(app).websocket_connect(...)` session driven by hand once to sanity-check message shapes match SPEC.md exactly

**Dependencies:** Task 1, Task 2, Task 3

**Files likely touched:**
- `src/back/server/ws_router.py`
- `src/back/server/server.py`
- `src/back/server/tests/test_ws_protocol.py`

**Estimated scope:** Medium: 3 files

---

## Task 5: Package mutation endpoint

**Description:** Add `POST /machines/packages` to `machines_router.py`. Resolves target
machine ids (`machine_ids` list, or all registered machines if omitted/null), mutates each
target's `packages` list (add = dedup'd union, remove = filter), calls
`set_apply_pending` with a fresh `apply_id`, and pushes `apply_config` via the connection
manager if currently connected — otherwise the row stays `pending` for later delivery.

**Acceptance criteria:**
- [ ] `machine_ids: ["a"]` only mutates machine `a`'s config
- [ ] `machine_ids: null` mutates every registered machine
- [ ] Response's `delivery` field is `"pushed"` for a connected target and `"queued"` for a disconnected one
- [ ] Adding an already-present package or removing an absent one is a no-op (idempotent), still returns success

**Verification:**
- [ ] Tests pass: `pytest tests/test_machines_api.py -k packages`
- [ ] Manual check: with a fake WS client connected (via `websocket_connect`), trigger the endpoint and assert the socket receives the `apply_config` frame

**Dependencies:** Task 1, Task 2, Task 3, Task 4

**Files likely touched:**
- `src/back/server/machines_router.py`
- `src/back/server/tests/test_machines_api.py`

**Estimated scope:** Medium: 2 files

---

## Task 6: Apply-result ack + reconnect redelivery

**Description:** In `ws_router.py`, handle incoming `apply_result` messages: if the
message's `apply_id` matches the row's current `last_apply_id`, call `set_apply_result`
(status + message + timestamp); otherwise ignore (stale ack). Confirm the Task 4 connect
handler's "resend `apply_config` if `last_apply_status == pending`" path is exercised by a
real pending-then-reconnect sequence.

**Acceptance criteria:**
- [ ] A matching `apply_result` updates `last_apply_status`/`last_apply_message`/`last_apply_at`, visible via `GET /machines/{id}`
- [ ] An `apply_result` with a stale/mismatched `apply_id` changes nothing
- [ ] Sequence: mutate packages while offline → `delivery: "queued"` → connect → same `apply_config` frame is received without a second mutation request

**Verification:**
- [ ] Tests pass: `pytest tests/test_ws_protocol.py -k apply`
- [ ] Manual check: full scripted scenario in a throwaway test — mutate, disconnect/reconnect, ack — read end state via `GET /machines/{id}`

**Dependencies:** Task 4, Task 5

**Files likely touched:**
- `src/back/server/ws_router.py`
- `src/back/server/tests/test_ws_protocol.py`

**Estimated scope:** Small: 1-2 files

---

## Task 7: App wiring and polish

**Description:** Finalize `server.py` (both routers included, DB path configurable via
env var with a sane default, startup hook calling `init_db`). Add `pytest` and `httpx` to
`requirements.txt`. Add `src/back/server/*.db` to `.gitignore`.

**Acceptance criteria:**
- [ ] Fresh clone + `pip install -r requirements.txt` + `uvicorn server:app` works with no manual steps
- [ ] `nixync.db` never gets committed

**Verification:**
- [ ] Tests pass: full `pytest` suite from `src/back/server/`
- [ ] Manual check: delete `.venv`-cached db file, re-run server, confirm schema is recreated

**Dependencies:** Task 1-6 complete

**Files likely touched:**
- `src/back/server/server.py`
- `requirements.txt`
- `.gitignore`

**Estimated scope:** Small: 1-2 files

---

## Task 8: OpenAPI export

**Description:** Add a small `scripts/export_openapi.py` (or equivalent) that imports the
fully-wired `app` and dumps `app.openapi()` to `openapi.json`, and confirm it validates as
OpenAPI 3.x.

**Acceptance criteria:**
- [ ] Running the script produces `openapi.json` containing all REST paths from SPEC.md (WS endpoints don't appear in OpenAPI — expected, note this in output)
- [ ] The file is valid JSON and has `"openapi": "3.x"` at the top level

**Verification:**
- [ ] Manual check: run the export script, then `python -c "import json; json.load(open('openapi.json'))"` succeeds

**Dependencies:** Task 7

**Files likely touched:**
- `src/back/server/scripts/export_openapi.py`

**Estimated scope:** Small: 1 file
