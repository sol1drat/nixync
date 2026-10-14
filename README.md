# Nixync

**A control center for managing multiple machines.**

Nixync lets you manage a fleet of NixOS machines from one interface. Configure devices, deploy changes, monitor results, and recover from failed deployments without managing every machine separately.

## Features

- **Fleet dashboard** — View machines, their status, and deployment results.
- **Machine groups** — Organize devices by role, such as workstations or servers.
- **Configuration presets** — Apply shared settings across multiple machines.
- **Deployment preview** — Validate changes before applying them.
- **Staged deployments** — Test changes on one machine before rolling them out to the rest.
- **Logs and recovery** — Inspect failures and roll back to a previous NixOS generation.

## Who is it for?

- Teams managing multiple workstations or servers.
- Schools and computer labs.
- Homelab users running several NixOS machines.

## Example

An administrator manages 20 NixOS computers in a university lab. They apply a development-tools configuration to one machine, verify that it works, then deploy it to the rest. Nixync shows the result for each machine and highlights any failures.

## Development

The initial goal is to build a working prototype with a small fleet of NixOS virtual machines.

Existing deployment tools such as [Colmena](https://github.com/zhaofengli/colmena) and [Morph](https://github.com/DBCDK/morph) will be evaluated before building deployment functionality from scratch.

**The focus:** making fleet-wide NixOS management easier to operate, monitor, and recover.
