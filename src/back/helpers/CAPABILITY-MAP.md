# Capability Map: Nixync agent service

The software that runs **on a managed NixOS machine**. Two faces, one package:
a background daemon that keeps the machine in sync with the server, and a small
desktop app the machine's user opens to ask for software and see how their
machine is doing.

| Module id | Responsibility | Depends on |
|---|---|---|
| `shared-ui` | Theme and widgets that the host app and the device app both import, so they cannot drift apart | — |
| `nix-render` | Turn a `MachineConfig` into NixOS configuration text | — |
| `config-writer` | Write that text to the machine, rebuild, and recover from a failed rebuild | `nix-render` |
| `app-requests` | Server-side requests so a device user's ask reaches the admin | — |
| `agent-daemon` | The long-running service: holds the socket, reports health, applies what the server sends | `config-writer` |
| `device-gui` | The desktop app on the machine: request an app, view this machine | `shared-ui`, `app-requests`, `agent-daemon` |

**Build order:** `shared-ui`, `nix-render` → `config-writer`, `app-requests` →
`agent-daemon` → `device-gui`

`shared-ui`, `nix-render` and `app-requests` have no dependencies on each other and
could be built in parallel. Everything else is sequential: the GUI is last because it
is the only module that needs all the others working.

## Where each module lives

| Module | Location |
|---|---|
| `shared-ui` | `src/shared/nixync_ui/` — new, imported by `src/front` and `src/back/helpers` |
| `nix-render` | `src/back/client/nixync_client/nix.py` — the host app renders the same Nix as a preview, so it cannot live in the device package |
| `config-writer`, `agent-daemon`, `device-gui` | `src/back/helpers/nixync_agent/` |
| `app-requests` | `src/back/server/` + `src/back/client/nixync_client/` + `src/front` |

## Decisions taken before specifying

1. **The daemon owns one file, not the whole configuration.** It writes
   `/etc/nixos/nixync.nix` and adds a single import line to `configuration.nix` if one
   is missing. Hand-written configuration and `hardware-configuration.nix` survive, the
   diff is reviewable, and removing Nixync leaves a working machine.
2. **Requests are a real server feature.** A request made on one machine has to reach
   an admin on another; keeping it in process memory would make the device app's
   headline feature do nothing across two machines.
3. **One theme, two apps.** `style.py` and `widgets.py` move to a shared package rather
   than being copied, because a copy drifts the first time either side is edited — and
   consistency was the point.
4. **Daemon and GUI are separate processes.** The daemon needs root to write `/etc/nixos`
   and run `nixos-rebuild`; the GUI must never need it.
