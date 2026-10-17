# Nixync

Control center for managing multiple machines.

## The idea

Nixync helps a person manage a fleet of NixOS computers from one interface. Instead of configuring and checking every machine separately, an administrator can organize devices, apply shared configurations, deploy changes, check results, and roll back a failed update.

**The goal:** make NixOS fleet management easier to understand and safer to operate—not just add a GUI to one computer.

## Who is it for?

- **Engineering teams** managing workstations, build machines, and servers.
- **Schools and university labs** that need consistent setups across computer rooms.
- **Linux enthusiasts and homelab users** managing several NixOS devices.

Start with a small fleet of existing NixOS machines. Larger organizations could be a future audience once security, permissions, and reliability are mature.

## Core features

- **Fleet dashboard:** See machines, assigned roles, deployment status, and recent failures in one place.
- **Roles and presets:** Apply reusable configurations such as `workstation`, `web-server`, or `build-server` to groups of machines.
- **Simple configuration controls:** Make common changes such as packages, users, groups, and selected services without needing to edit every setting by hand. Advanced users should still be able to use Nix configuration directly.
- **Preview before applying:** Validate a proposed change and show which machines will be affected.
- **Controlled deployment:** Deploy to one test machine first, then roll out to the rest of a selected group.
- **Per-machine results:** Show build, connection, activation, and health-check results separately, with full logs available.
- **Recovery:** Where supported, return a machine to a previous NixOS generation after a failed change.
- **Secure access:** Use authenticated, authorized remote access; machines must not accept arbitrary configurations from any device on the network.

Nixync should manage configuration declaratively rather than silently changing a machine outside its declared setup. Git integration is not part of the planned product.

## Example use case

A university lab has 20 NixOS computers. An administrator applies a standard development-tools preset, tests it on one machine, checks the result, and then deploys it to the remaining lab computers. If some machines fail, Nixync shows which ones failed and provides logs and recovery options.

## Related tools

These projects already solve parts of NixOS deployment or configuration. Nixync should build on proven tools where useful and differentiate itself through the fleet-management experience—not claim that deployment tools do not exist.

| Project | What it does | How Nixync could differ |
|---|---|---|
| **NixOps 2** | Declarative infrastructure and machine deployment; its maintainers describe it as low-maintenance. | Focus on a simpler visual workflow for an existing fleet rather than infrastructure provisioning. |
| **NixOps4** | A newer, in-development approach to infrastructure/resource management. | Monitor it, but avoid depending on an evolving backend for the first prototype. |
| **Morph** | Deploys NixOS configurations across hosts and supports previews and health checks. | Add a centralized dashboard, easy role management, guided rollouts, and readable results. |
| **Colmena** | CLI-based, multi-host deployment with parallel operations and host/tag targeting. | A candidate backend; Nixync would provide the visual fleet workflow. |
| **Clan** | A broader framework for setting up and managing groups of machines, including deployment and other lifecycle tools. | Study it closely; the product needs a clear advantage beyond simply having a GUI. |
| **deploy-rs** | Flake-oriented deployment with rollback-related safeguards. | Potential source of deployment mechanisms or safety ideas, rather than the full product. |
| **nixos-fleet** | CLI-first fleet and installation workflows built around existing NixOS tools. | Competes on fleet scope; Nixync would emphasize visual operation and usability. |
| **Bento / comin** | Tools that can pull configuration updates onto machines, useful when hosts are not always reachable. | Consider whether the target fleet needs a pull-based approach instead of always initiating remote deployments. |
| **Nix-Gui / Nixbit** | Graphical NixOS configuration or update experiences, mainly focused on individual systems. | Make managing and coordinating many machines the central experience. |

**Key differentiator:** one place to organize a fleet, apply configurations to groups, deploy changes in stages, understand failures, and recover safely.

## Technical direction

Prototype with two or three NixOS virtual machines. Evaluate **Colmena** and **Morph** for deployment rather than writing a deployment engine from scratch; study **Clan** because its scope overlaps with the broader idea. Keep Nixync's interface and fleet-management logic separate from whichever backend is selected.

## MVP: build this first

1. A dashboard showing a few machines and their status.
2. Basic machine groups or roles.
3. A small set of configuration actions or presets.
4. Validation/preview before deployment.
5. Deploy to one test host, then to a selected group.
6. Per-host results, logs, a basic health check, and a tested recovery path.

Leave a universal settings editor, custom network protocol, support for every Linux distribution, large app store, and enterprise access-control system for later.

## Risks and open questions

- A GUI alone is not enough; the complete workflow must genuinely be easier than using existing tools directly.
- NixOS configurations are flexible, so the initial set of supported settings must stay limited and well-defined.
- A successful build does not guarantee successful activation or a healthy service.
- Rolling back a NixOS generation does not automatically restore application data or undo every side effect.
- Decide whether the first version assumes machines are reachable over SSH or also needs a pull-based model for laptops and remote devices.

## Next steps

1. Sketch the fleet dashboard, change preview, and deployment-progress screens.
2. Test a real configuration change across NixOS VMs.
3. Compare Colmena and Morph against the specific operations Nixync needs.
4. Ask target users whether this workflow solves a real pain point before expanding the feature list.


# Tracks

**Rules:**

1. No bussines model
2. No sales pitch
3. Only technical presentation

**Tracks:**

1. Make it better
2. Multiplayer agentic experiences
3. Mobile native
4. Desktop native
5. Solana

**Judging:**

1. A clear problem
2. A creative solution
3. It really solves the problem


# Build

## Host

**Windows or Linux machine:** needs a native GUI

# Clients

**NixOS machines:** package