# Nixync

> [!WARNING]
> **Early alpha disclaimer:** Nixync is experimental software under active development. Expect incomplete workflows and bugs. Test it only on disposable VMs or other non-critical machines; do not use it to manage production systems or hosts containing important data. The client runs with elevated privileges to apply NixOS configuration changes.
>
> **Hackathon jury?** [Jump directly to the testing instructions](#testing-it-for-hackathon-judges).

Nixync is a control center for managing a fleet of NixOS machines. It gives an administrator one place to inspect host health, define package and system settings, deploy configuration changes, and review the result of each deployment.

Instead of installing software imperatively on every host, Nixync represents supported changes in NixOS configuration and applies them through the NixOS rebuild workflow. A host agent communicates with the central server, runs the deployment on the machine, and reports status and logs back to the dashboard.

## Contents

- [Architecture](#architecture)
- [NixOS deployment workflow](#nixos-deployment-workflow)
- [Features](#features)
- [Run the administrator app](#run-the-administrator-app)
- [Testing it (for hackathon judges)](#testing-it-for-hackathon-judges)
- [Development](#development)
- [Future Plans](#future-plans)

## Architecture

Nixync is made up of four separate components:

| Component | Responsibility |
| --- | --- |
| **Nixync** | Native desktop GUI for managing the fleet: host inventory, package and settings changes, presets, app-request approvals, and deployment results. |
| **Server** | Central API and state store for registered machines, presets, requests, and deployment status. The administrator app, clients, and agents communicate through it. |
| **Nixync Client** | A separate (from **Nixync**) binary distributed to end users on managed machines. It lets them request software and check request status. |
| **Nixync Client Service** | A background service on each managed machine. It receives deployment tasks, updates the managed NixOS configuration, invokes the rebuild, and sends the result and logs back to the server. |

### Installing the host agent on NixOS

The [`install-agent.sh`](install-agent.sh) installer configures the agent as a systemd system service. On NixOS, service units are managed declaratively, so the installer writes a NixOS module to `/etc/nixos/nixync-agent.nix`, imports it from `/etc/nixos/configuration.nix`, and runs `nixos-rebuild switch` to activate the service configuration. The service runs as root because deployments need to write system configuration and invoke privileged NixOS rebuilds.

The service is configured to start at boot and restart if the agent process exits. Its logs can be inspected with:

```sh
journalctl -u nixync-agent -f
```

## NixOS deployment workflow

A typical package or settings deployment follows this path:

1. **Define the change.** An administrator edits the host's supported settings or packages in the administrator app. Presets can be assigned to hosts, but applying a preset's package set is an explicit action rather than an automatic side effect of assigning a label.
2. **Send the deployment.** The server records the requested change and passes the task to the relevant connected host agent.
3. **Update declarative configuration.** The agent writes the managed configuration fragment at `/etc/nixos/nixync.nix` rather than asking the user to install packages manually with an imperative package manager.
4. **Evaluate, build, and activate.** The agent runs `nixos-rebuild switch`. Nix evaluates the NixOS configuration and builds the resulting system closure in `/nix/store`; if the rebuild and activation succeed, the machine switches to the new system generation.
5. **Report the result.** The agent sends the outcome and available build/activation output to the server. The administrator can inspect per-host deployment results and logs in the **Updates** view. Failed deployments include their logs and an **Ask AI** action to help explain the error.

This workflow is designed around NixOS's declarative system configuration and generation-based rebuilds—not around remotely running an arbitrary `apt install`-style command for every package change.

## Features

- **Fleet overview:** see registered machines, health (`ok`, `problem`, or `unreachable`), and last-seen time; filter by status, group, or preset.
- **Presets and roles:** organize machines as `workstation`, `web-server`, `build-server`, or other roles. Applying a preset's configuration is a separate, deliberate operation.
- **Package and system settings:** manage packages and supported settings such as hostname, nameservers, firewall ports, and users through the GUI. Advanced users can inspect the generated Nix configuration.
- **Software requests:** end users can submit requests through the separate **Nixync Client**. An administrator can approve or decline a request; approval triggers the normal deployment workflow.
- **Per-host deployment history:** inspect results and logs for each host to see which changes succeeded or failed.
- **Failure assistance:** use the **Ask AI** action to get a plain-language explanation of a failed deployment log.

## Run the app

Download the appropriate administrator-app release asset from [GitHub Releases (v0.1.0)](https://github.com/sol1drat/nixync/releases/tag/v0.1.0):

- **Linux:** `nixync-linux.zip`
- **Windows:** `nixync-windows.zip`

Extract the archive and launch `nixync` on Linux or `nixync.exe` on Windows. On the sign-in screen, enter the server URL and your credentials.

The **Nixync Client** is a separate binary for end users on managed machines. Distribute and launch that client build separately; there is no device/client-mode toggle inside the administrator application. The host agent is also a separate component, installed as a background service on each managed host.

## Testing it (for hackathon judges)

A demo server with a virtual NixOS machine is already running, so you can test the main workflow without setting up a server or installing NixOS yourself.

1. Download and open the administrator app, then sign in with these demo credentials:

   - **Server URL:** `http://94.43.175.162:8000`
   - **Username:** `admin`
   - **Password:** `password`

2. Open **Devices**. A virtual NixOS machine should already be registered and connected. Select it to inspect its configuration, change packages or supported settings, or apply a preset.
3. Open **Updates** to review the deployment status and logs for the change.
4. To observe the virtual machine itself, connect through [RustDesk](https://rustdesk.com):

   - **RustDesk ID:** `<RUSTDESK_ID>`
   - **RustDesk password:** `<RUSTDESK_PASSWORD>`

The demo server and credentials are for evaluation only. Do not enter personal information, production credentials, or other sensitive data.

## Development

Enter the Nix development shell and install the Python dependencies:

```sh
nix develop
pip install -r requirements.txt
```

Common development commands:

```sh
./run-demo.sh server                # start the fleet server on :8000
./run-demo.sh gui                   # launch the administrator desktop app
./run-demo.sh agent <machine-id>    # run the development/mock agent
./run-demo.sh tests                 # run the test suite
```

To install the real host agent on a **test NixOS machine**, register the machine in Nixync first, then use the machine ID supplied by the app:

```sh
sudo ./install-agent.sh --server http://<SERVER-IP>:8000 --machine-id <MACHINE-ID>
```

Review the installer before running it: it modifies the host's NixOS configuration and installs a root-owned system service. Use [`install-agent.sh`](install-agent.sh) for the supported install/uninstall options and [packaging/README.md](packaging/README.md) for instructions on building the desktop application binaries.

## Future Plans

The following are planned improvements; they are not all implemented in the current alpha.

- **Flake- and Git-based configuration management:** connect hosts to version-controlled NixOS configurations, show diffs before deployment, and track pinned inputs and configuration revisions.
- **Safer deployment gates:** add evaluation and dry-build checks before activation, clearer change previews, explicit confirmation for risky changes, and more consistent failure handling.
- **Staged fleet rollouts:** deploy first to a canary host, then to selected groups or the full fleet, with concurrency limits and per-host rollout status.
- **Recovery and rollback tools:** make it easier to select a previous NixOS generation and recover from a bad deployment through the dashboard.
- **Better fleet observability:** show system generations, agent/service health, and richer host diagnostics alongside connection status and deployment history.
- **Security hardening:** improve agent enrollment, transport security, access control, audit trails, and handling of privileged operations before considering production use.
- **Client and administrator UX:** streamline software-request approvals, improve progress reporting, and simplify distributing and updating the separate Nixync Client binary.
