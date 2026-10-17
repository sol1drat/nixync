# Spec: Wiring the desktop app to the Nixync server

## Objective

Make the host GUI talk to the real server instead of `sample_data`, using the
`nixync_client` library rather than hand-rolled `requests` calls. After this, two
machines are enough to demonstrate the product: the host app on one, an agent on the
other, with the fleet view, deployments and per-host results all live.

Scope is **core wiring** (agreed before work started):

| Real after this change | Still `sample_data` |
|---|---|
| Login (hardcoded credentials) | Presets and roles |
| Machine list, registration, removal | Machine groups |
| Live telemetry and online state | App requests |
| Add/remove apps on devices | Updates page, build/error history |
| Per-device system settings | nixpkgs search (already a real external API) |

Presets, groups, requests and update history need server data models that do not exist;
they are deliberately out of scope and stay clearly backed by sample data.

## Design Decisions

1. **`NixyncClient` becomes an adapter, not a rewrite.** Its method signatures stay
   exactly as they are and it keeps returning `sample_data.Machine` objects. The GUI
   reads 20+ attributes off that dataclass across a dozen files; changing the view model
   would churn the whole UI for no user-visible gain. Internally it now delegates to
   `nixync_client.AdminClient` and maps the server's `Machine` onto the GUI's.

2. **The server keeps using ids; the GUI keeps using names.** The adapter owns the
   translation and caches the name→id map from the last `list_machines()`. Duplicate
   names raise rather than silently acting on the wrong machine.

3. **System settings travel inside `MachineConfig`.** Hostname, firewall, SSH and users
   are all NixOS configuration, so they belong in the same declarative payload that gets
   pushed to an agent — not in a side-channel. `MachineConfig` gains a free-form
   `settings` dict; the GUI owns its schema (`sample_data.SystemSettings`) and the
   server stores it verbatim.

4. **Login is a real round-trip against hardcoded credentials.** `POST /login` checking
   `admin`/`password` is barely more code than faking it client-side, and it means the
   login screen fails honestly when the server is unreachable or the password is wrong —
   which is what someone will try during a demo. No sessions or tokens: the MVP has no
   authorization, and a token nothing checks would be security theatre.

5. **Fields the server has no concept of keep their sample values** (`preset`, `group`,
   `nixos_version`, `address`, `builds`, `errors`). They are not invented or blanked, so
   the UI still renders, and what is real versus placeholder is documented here.

## Field Mapping

`nixync_client.Machine` → `sample_data.Machine`:

| GUI field | Source |
|---|---|
| `name` | `machine.name` |
| `cpu_percent` | `machine.cpu_percent` |
| `ram_percent` | computed: `ram_used_mb / ram_total_mb * 100` |
| `disk_used_gb`, `disk_total_gb` | direct |
| `last_seen` | `metrics_reported_at`, parsed from ISO 8601 |
| `extra_apps` | `machine.config.packages` |
| `settings` | `machine.config.settings`, decoded to `SystemSettings` |
| `health` | derived — see below |
| `preset`, `group`, `address`, `note`, `nixos_version`, `builds`, `errors` | sample defaults; no server concept yet |

**Health** is derived, since the server models liveness and deployment outcome
separately while the GUI shows one badge:

| Condition | Health |
|---|---|
| `last_apply_status == "failed"` | `PROBLEM` ("Problem after update") |
| not `online` | `UNREACHABLE` ("Can't be reached") |
| otherwise | `OK` ("Online") |

A failed deployment outranks being offline: a machine that broke and then went away is
a problem to show, not an absence. `Health` has no "deploying" state, so a machine with
work still pending reads `OK` — it is online and nothing has gone wrong yet.

## Server Changes

- `POST /login` — body `{username, password}`; 200 `{"username": "admin"}` or 401.
  Credentials are module constants, overridable with `NIXYNC_ADMIN_USER` /
  `NIXYNC_ADMIN_PASSWORD`.
- `MachineConfig.settings: dict` — free-form, defaults `{}`, stored and returned with
  the rest of the config and included in `apply_config` pushes.

Both appear in the regenerated `openapi.json`.

## Commands

```bash
# server, reachable from the other machine
cd src/back/server && NIXYNC_DB=nixync.db ../../../.venv/bin/python -m uvicorn server:app --host 0.0.0.0 --port 8000

# host GUI
cd src/front && NIXYNC_SERVER_URL=http://<server-ip>:8000 python -m nixync_front

# agent on the managed machine
python src/back/client/example_agent.py --server http://<server-ip>:8000 --machine-id <uuid>
```

## Testing Strategy

- `src/front/tests/` — new. `test_api_adapter.py` drives the real `NixyncClient`
  against a real uvicorn process: login, machine list, registration, package changes,
  settings round-trip, and the health/field mapping.
- Mapping logic (health derivation, ram percentage, ISO parsing) is unit-tested
  directly, since those are pure functions over a server payload.
- A headless GUI smoke test (`QT_QPA_PLATFORM=offscreen`) constructs the main window
  against a live server to catch import and wiring errors the adapter tests cannot.
- The existing server and client suites must stay green; this change must not alter
  agent behaviour.

## Boundaries

- **Always:** go through `nixync_client`, never raw `requests`, so the wire format has
  one owner; keep `NixyncClient`'s existing method signatures; keep the GUI responsive
  by leaving blocking calls on worker threads where the pages already do that.
- **Ask first:** adding server data models for presets, groups, requests or build
  history; changing the `sample_data.Machine` shape.
- **Never:** put real authentication or session tokens in this MVP; invent values for
  fields the server does not have.

## Success Criteria

- Signing in with `admin`/`password` succeeds against a running server and fails with a
  clear message on a wrong password or an unreachable server.
- The machines page lists machines from the server, with live CPU, RAM, disk and
  last-seen from a connected agent.
- Adding apps to selected devices deploys them; a connected agent receives the push.
- Device settings saved in the GUI survive a restart of the app.
- Adding a machine in the dialog registers it on the server and shows its id.
- `pytest src/back/server src/back/client src/front` all green.

## Bugs this wiring introduced, and how they were resolved

All three were created by the move from sample data (which could never fail or change)
to a live server, and all three are covered by tests.

1. **The fleet view was frozen at launch.** `MachinesPage` read the machine list once in
   `__init__` and `refresh()` only re-rendered that captured list. Live telemetry would
   never move and a newly registered device would never appear — fatal for a dashboard
   whose entire point is current state. `refresh()` now re-reads from the server.
2. **An unreachable server stopped the app from starting.** That same `__init__` call is
   now a network call, so a dead server raised during window construction. It is caught;
   the page loads empty and keeps the reason in `load_error`, and the empty state says
   the fleet could not be read rather than blaming the filters.
3. **A preset could silently swallow a deployment.** `add_apps` skipped packages the
   machine "already had", counting the preset's apps as installed. Presets are sample
   data the server never deploys, so asking for `htop` on a Workstation device reported
   "already has it" and the package never arrived. Deployment decisions now use only
   what the server actually holds; presets still show in the UI.

## Open Questions

1. The Add-machine dialog collects a preset and group the server cannot store. They are
   accepted and shown but not persisted; revisit when presets become real.
2. The GUI shows one `health` badge per machine, so a machine that is offline *and* has
   a failed deployment reports `PROBLEM`. Confirm that ranking matches what an operator
   expects.
