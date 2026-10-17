# Spec: Nixync agent service (`nixync_agent`)

Capability map: `CAPABILITY-MAP.md`. This spec covers the four modules that live in
this package — `nix-render`, `config-writer`, `agent-daemon`, `device-gui` — plus the
two prerequisites they need from elsewhere (`shared-ui`, `app-requests`).

## Objective

Everything that runs **on a managed NixOS machine**:

- A **daemon** that holds one WebSocket to the server for its lifetime, reports CPU /
  RAM / disk, and turns each configuration push into real NixOS configuration: render
  it, write it, rebuild, report back what happened. This is the piece that makes the
  product actually manage a machine rather than describe one.
- A **desktop app** for whoever is sitting at that machine: ask for an application,
  and see this machine's state — what is installed, is it reachable, did the last
  change work, what did it fail with.

Success: an admin adds a package on machine A; machine B installs it and the dashboard
says `applied`. A student on machine B asks for Blender; the admin sees the request,
approves it, and it appears on B.

## Tech Stack

- **Python 3.13**, **PySide6** (GUI only), **`nixync_client`** for the wire protocol.
- No new third-party dependencies. The daemon shells out to `nixos-rebuild` via
  `subprocess`; everything else is standard library plus what the repo already has.

## Project Structure

```
src/shared/nixync_ui/        shared-ui: style.py, widgets.py (moved from src/front)

src/back/helpers/
  nixync_agent/
    __init__.py
    system.py        config-writer:  write, import-line, rebuild, rollback
    daemon.py        agent-daemon:   socket + telemetry + apply, the service loop
    settings.py                      agent config: server URL, machine id, paths
    gui/
      __init__.py
      app.py                         entry point
      window.py      device-gui:     Apps / My requests / This machine
      store.py                       search nixpkgs, request an app
      machine.py                     this machine's details
  tests/
  SPEC.md, CAPABILITY-MAP.md, README.md
  nixync-agent.service               systemd unit, for reference
```

## Behaviour

### nix-render

`render(config: MachineConfig) -> str` produces the full contents of `nixync.nix`:
packages from `config.packages`, everything in `config.settings`, and local users.
A machine with nothing configured renders a valid, empty-but-complete module — never
a syntax error.

Package names are validated against `^[A-Za-z0-9._-]+$` before interpolation. A name
failing that is rejected rather than escaped: anything else is either a typo or an
attempt to inject Nix, and the server is unauthenticated in this MVP.

**It lives in `nixync_client/nix.py`, not in this package.** The spec first placed it
here, but the host app renders the same Nix as a live preview in its settings panel —
so the agent is not the only consumer. Putting it in the agent would point the front at
the device package, backwards. Both already depend on `nixync_client`, and rendering is
the canonical meaning of a `MachineConfig`, so that is where it belongs.

`src/front/nixync_front/nix_config.py` keeps its form validation and diffing, which are
UI concerns, and calls this renderer for the preview.

### config-writer

`apply(config)`:
1. Render to text.
2. Write `/etc/nixos/nixync.nix` atomically — temp file in the same directory, then
   `os.replace`, so an interrupted write cannot leave a half-file that breaks the
   machine's next rebuild.
3. Ensure `configuration.nix` imports it, inserting the path into the existing
   `imports = [ ... ]` list. Already present → left alone.
4. Run `nixos-rebuild switch`. Non-zero exit → restore the previous `nixync.nix` and
   raise with the last ~40 lines of stderr, which becomes the message the admin sees.

Every path and the rebuild command are **constructor arguments**, defaulting to the
real ones. Tests pass a temp directory and a fake runner; no test may touch `/etc` or
invoke a real rebuild.

A `--dry-run` flag renders and writes to a temp directory, logs the diff, and skips the
rebuild — so the daemon can be run safely on a dev machine.

### agent-daemon

Wraps `nixync_client.NixyncAgent`, supplying `on_apply=writer.apply` and
`current_config=` read back from the machine. The agent library already owns
reconnection, telemetry scheduling, acking and the queued-change-on-reconnect path;
this module is the wiring plus process concerns: config file, logging, signal
handling, systemd unit.

Reads its settings from `/etc/nixync/agent.toml` (overridable by flag) — server URL
and machine id. Missing or unregistered id exits with a clear message rather than
retrying forever.

### device-gui

Three pages, built from `shared-ui` so it matches the host app:

- **Apps** — search nixpkgs, see what this machine has, request something it does not.
- **My requests** — what this user asked for and what the admin decided.
- **This machine** — name, agent id, online state, live CPU/RAM/disk, installed
  packages, last deployment result and its error text if it failed.

Runs as the logged-in user. It talks to the **server** for requests and machine detail
(reusing `nixync_client`), not to the daemon — the daemon has no IPC surface, and
inventing one for read-only data the server already has would be a second protocol to
keep in sync. Read-only about configuration: changing the machine is the admin's job.

The existing `src/front/nixync_front/client_window.py` is the closest thing to this and
is the starting point; its sample-data dependencies are replaced with real calls.

### app-requests (prerequisite, server side)

| | |
|---|---|
| `GET /requests` | all requests, newest first; `?machine=` to filter |
| `POST /requests` | body `{machine_id, app, requested_by, reason}` → 201 |
| `POST /requests/{id}/approve` | marks approved **and** deploys the package |
| `POST /requests/{id}/decline` | marks declined, deploys nothing |

A `requests` table: id, machine_id, app, requested_by, reason, status, created_at,
decided_at. Approving reuses the existing deployment path, so a request approved for an
offline machine queues like any other change.

## Commands

```bash
# tests (everything)
./run-demo.sh tests

# the daemon, safe on a dev machine: renders and writes to a temp dir, no rebuild
python -m nixync_agent.daemon --server http://host:8000 --machine-id <uuid> --dry-run

# for real, on a NixOS box
sudo python -m nixync_agent.daemon          # reads /etc/nixync/agent.toml

# the device app
python -m nixync_agent.gui
```

## Code Style

Matches the rest of the repo: type hints on every signature, dependencies injected so
the dangerous parts are testable, comments only where the reason is not obvious.

```python
class SystemWriter:
    """Writes Nixync's configuration module and rebuilds the system.

    Paths and the rebuild command are injected so tests never touch a real /etc.
    """

    def __init__(
        self,
        config_dir: Path = Path("/etc/nixos"),
        run: Callable[[list[str]], CompletedProcess] = subprocess.run,
    ):
        ...
```

## Testing Strategy

`pytest`, alongside the existing suites.

- **nix-render** — unit tests over text output: packages, every setting, users, empty
  config, and the injection rejection. Pure function, no I/O.
- **config-writer** — against a temp directory with a fake rebuild runner: writes the
  file, adds the import exactly once, is idempotent, restores the previous file when
  the rebuild fails, and survives an interrupted write.
- **agent-daemon** — against a real `uvicorn` server, as the client suite already does:
  connects, reports telemetry, applies a push to a temp directory, acks.
- **device-gui** — headless (`QT_QPA_PLATFORM=offscreen`) against a real server: the
  window builds, the pages render, requesting an app creates a real request.

**No test may write outside its temp directory or run `nixos-rebuild`.** A test that
needs either is wrong.

## Boundaries

- **Always:** inject paths and the rebuild command; write config atomically; keep the
  GUI runnable without root; go through `nixync_client` for anything crossing the wire.
- **Ask first:** adding a dependency; changing the agent WebSocket protocol; anything
  that would make the GUI need root.
- **Never:** overwrite `configuration.nix` wholesale; run `nixos-rebuild` from a test;
  interpolate an unvalidated package name into Nix; put a password in rendered Nix.

## Success Criteria

- `render()` output is accepted by `nixos-rebuild` on a real NixOS VM.
- A package added in the host app appears on the device, and the dashboard says
  `applied`.
- A failed rebuild restores the previous configuration, and its error text is what the
  admin sees next to the machine.
- Running the daemon twice over the same machine leaves exactly one import line.
- A request made in the device app appears in the admin's Requests page; approving it
  installs the app on that machine.
- The device app and the host app are visibly the same application.
- `./run-demo.sh tests` green, with nothing written outside temp directories.

## Open Questions

1. **Rollback granularity.** A failed rebuild restores the previous `nixync.nix`, but
   does not roll back to a previous NixOS *generation* — `nixos-rebuild switch` only
   activates on success, so the running system is untouched. Enough for the MVP;
   recovering a machine that booted into a bad generation is a separate problem.
2. **Who the request is from.** The device app has no login, so `requested_by` is the
   OS username. Fine for a lab; worth revisiting with real authentication.
3. **`shared-ui` move.** Relocating `style.py` and `widgets.py` touches every import in
   `src/front`. Mechanical, but it is a wide diff — flagging before doing it.
