# Nixync

Nixync is a control center for managing a fleet of NixOS machines from one app,
instead of configuring and checking every machine by hand.

An administrator registers machines, groups them with reusable **presets**
(roles like "workstation" or "build-server"), and manages their packages and
settings from a dashboard. Each managed machine runs a small agent that applies
the change and reports back — connected, healthy, or failed, with the build log
attached. People working on a managed machine get the same app in a lighter
"device" mode, to request extra software that an admin then approves or
declines.

## How it works

- **Admin app** — sign in and see every machine's status, then manage
  packages, settings and presets from the **Devices**, **Presets** and
  **Updates** pages.
- **Agent** — a small daemon installed on each NixOS machine
  ([`install-agent.sh`](install-agent.sh)). It stays connected to the server,
  applies configuration changes, and reports health and logs back.
- **Server** — what everything talks to. Holds the fleet state: machines,
  presets, and pending app requests.
- **Device mode** — the same desktop app, signed in as a device instead of an
  admin, so the person using that machine can request new software and see
  its status without touching its configuration directly.

Failed deployments show the build log plus an **Ask AI** button that explains
the failure in plain language.

## Features

- **Fleet dashboard** — every registered machine, its health (ok / problem /
  unreachable) and last-seen time, filterable by status, group or preset.
- **Presets (roles)** — label machines without silently changing them;
  rolling a preset's packages out to a machine is a separate, explicit step.
- **Package & settings management** — add or remove packages, and edit
  hostname, nameservers, firewall ports and users, without hand-editing Nix
  config. Advanced users can still see the real config with one toggle.
- **App requests** — someone at a machine can ask for software they can't
  install themselves; an admin approves or declines, and approving deploys it
  the same way any other change would.
- **Per-machine results** — build/activation history, health and full logs
  for every deployment, with AI-assisted help on failures.

## Try it

Download the latest release for your platform from
[Releases (v0.1.0)](https://github.com/sol1drat/nixync/releases/tag/v0.1.0):

- **Linux:** `nixync-linux.zip`
- **Windows:** `nixync-windows.zip`

Unzip it and run `nixync` (Linux) or `nixync.exe` (Windows). The sign-in
screen asks for a server URL and credentials.

## Testing it (for hackathon judges)

A demo server with a virtual NixOS machine is already running, so no setup is
needed.

1. Open the app and on the sign-in screen use:
   - **Server URL:** `http://94.43.175.162:8000`
   - **Username:** `admin`
   - **Password:** `password`
2. After signing in, a virtual NixOS machine is already registered and
   connected. Open it from the **Devices** page to change its packages,
   settings or preset, or check the **Updates** page for deployment results.
3. To watch those changes land on the machine itself, connect to it remotely
   with [RustDesk](https://rustdesk.com):
   - **RustDesk ID:** `<RUSTDESK_ID>`
   - **RustDesk password:** `<RUSTDESK_PASSWORD>`

> On Linux, the app needs a few shared libraries Qt depends on (`libegl1`,
> `libgl1`, `libxkbcommon-x11-0`, ...). See
> [packaging/README.md](packaging/README.md) for the full list if it won't
> start.

## Development

```sh
nix develop                       # sets up the dev shell (.venv, native libs)
pip install -r requirements.txt
./run-demo.sh server              # fleet server on :8000 (admin / password)
./run-demo.sh gui                 # the desktop app
./run-demo.sh agent <machine-id>   # a machine agent (prints instead of installing)
./run-demo.sh tests               # the test suite
```

See [packaging/README.md](packaging/README.md) for building the desktop app
into a standalone binary per platform, and
[install-agent.sh](install-agent.sh) for installing the real agent on a
NixOS machine.

## Status

Nixync is an early prototype built for a hackathon: a working slice of fleet
management (register, configure, deploy, see results, approve requests)
rather than the full product. Git integration and infrastructure provisioning
are intentionally out of scope — see [CLAUDE.md](CLAUDE.md) for the longer-term
idea.
