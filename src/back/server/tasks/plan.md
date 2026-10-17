# Implementation Plan: Nixync Fleet Server (MVP)

Spec: `../SPEC.md`

## Overview

Build the FastAPI server in 8 small tasks, foundation-first: persistence layer, then the
in-memory WebSocket connection registry, then the REST registry endpoints, then the
WebSocket protocol (telemetry/config in, package pushes out), then the package-mutation
endpoint and its ack lifecycle, then wiring/polish. Each phase ends in a working,
pytest-verified state — nothing is left half-wired between phases.

## Architecture Decisions

- **Foundation before protocol:** `database.py` and `models.py` land first since every
  router and the WS handler both import them — building either router first would mean
  guessing at the repository function signatures and rewriting them.
- **Connection manager is its own task** (not folded into the WS router) because the REST
  package-mutation endpoint needs to call into it too (`send_json` to push `apply_config`
  outside of any request currently inside the WS handler itself).
- **Registry (REST) before protocol (WS):** the WS endpoint's first job is rejecting
  unknown `machine_id`s, which requires `GET`-style DB lookups that the registry task
  already builds and tests in isolation — cheaper to verify there first than inside a
  websocket test harness.
- **Package mutation (Task 5) before ack handling (Task 6):** the mutation endpoint is
  what creates `pending` apply state; the ack handler and reconnect-redelivery logic have
  nothing to consume until that state exists.

## Task List

### Phase 1: Foundation
- [x] Task 1: Persistence layer (`database.py` + `models.py`)
- [x] Task 2: WebSocket connection manager (`connection_manager.py`)

### Checkpoint: Foundation
- [x] `pytest` passes for `test_database.py` and `test_connection_manager.py`
- [x] No router or app wiring yet — expected, nothing to run end-to-end

### Phase 2: Machine registry (REST)
- [x] Task 3: Register/list/get/delete endpoints (`machines_router.py`, partial)

### Checkpoint: Registry
- [x] `pytest` passes including `test_machines_api.py`
- [x] `uvicorn server:app` boots; `POST /machines` → `DELETE /machines/{id}` round-trips via curl or `/docs`

### Phase 3: WebSocket protocol
- [x] Task 4: `/ws/machines/{machine_id}` — connect/reject, `telemetry`, `config_report`, disconnect

### Checkpoint: Agent connection lifecycle
- [x] `pytest` passes including `test_ws_protocol.py`'s connect/telemetry/config_report cases
- [x] A simulated agent connecting, reporting telemetry, and disconnecting is visible end-to-end via `GET /machines/{id}`

### Phase 4: Package deployment loop
- [x] Task 5: `POST /machines/packages` (targeted + all-machines, push-if-connected else queue)
- [x] Task 6: `apply_result` ack handling + resend-pending-on-reconnect

### Checkpoint: Full deployment loop (core MVP milestone)
- [x] `pytest` passes including the full package-push → ack → reconnect-redelivery cases
- [x] Manual run-through: register a machine, connect a fake agent, request a package add,
      see it delivered; disconnect, request another package change (queued), reconnect,
      see it delivered automatically
- [ ] **Review with human before proceeding to polish**

### Phase 5: Wiring and polish
- [x] Task 7: `server.py` app wiring, startup DB init, `requirements.txt`/`.gitignore` updates
- [x] Task 8: OpenAPI export script + validation
- [x] Task 9 (added): end-to-end suite against a real uvicorn process

### Checkpoint: Complete
- [x] Full `pytest` suite green — 64 tests
- [x] `uvicorn server:app` runs cleanly from a fresh clone (`pip install -r requirements.txt` only)
- [x] Exported `openapi.json` validates as OpenAPI 3.1.0
- [x] All SPEC.md success criteria met

## Review notes (post-implementation)

Mutation-tested the three load-bearing rules by inverting each and confirming the suite
goes red: the no-op skip guard (4 tests fail), the stale-ack `apply_id` match (3 fail),
and resend-on-reconnect (caught by the E2E suite in 6.6s).

Known and accepted for the MVP:
- `GET /machines` is unpaginated. Fine at the 20-machine target fleet; revisit past ~500.
- `POST /machines/packages` reads then writes each machine's config, so two concurrent
  fleet-wide changes could lose an update. Single-admin MVP; needs a transaction if the
  product ever grows concurrent operators.
- WebSocket tests driven by `TestClient` hang rather than fail when a server-to-agent
  push regresses, because its `receive_json()` takes no timeout. The E2E suite covers
  the same paths with bounded waits, so the regression still surfaces quickly.

## Risks and Mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| `TestClient.websocket_connect` behavior with FastAPI's async handlers is easy to get subtly wrong (sync test driving an async endpoint) | Med | Keep WS handler logic thin and push all real work into plain functions in `database.py`/`connection_manager.py` that can also be unit-tested without a socket at all |
| sqlite + async WS handler: a connection opened in the main thread and used from an async request handler needs `check_same_thread=False` or a fresh connection per call | Med | `database.py` opens a short-lived connection per repository call rather than holding one open across the app's lifetime — simplest safe option for an MVP's traffic level |
| Stale `apply_id` acks arriving after a newer push supersedes them | Low | Already specified: compare against `last_apply_id` before accepting an `apply_result` (Task 6) |
| Scope creep into roles/presets/updates (front-end TODOs reference them) | Low | Explicitly out of boundaries in SPEC.md; not listed in any task above |
| **(Hit in Task 4)** `TestClient` simulates ASGI directly, so WS tests pass even when uvicorn has no WebSocket implementation installed and would reject every real connection | High | `websockets==17.2` added to `requirements.txt`; every WS phase additionally smoke-tested against a real uvicorn process, not just `TestClient` |

## Open Questions

Carried from SPEC.md — none block starting Task 1:
1. Does the (future) agent re-send `config_report` on local drift, or only at connect?
2. Is latest-snapshot telemetry (no history) sufficient long-term?
