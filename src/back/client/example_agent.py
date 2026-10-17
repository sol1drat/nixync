"""Reference agent for a managed NixOS machine.

    python example_agent.py --server http://127.0.0.1:8000 --machine-id <uuid>

Register the machine first (the server mints the id):

    curl -X POST http://127.0.0.1:8000/machines \
         -H 'Content-Type: application/json' -d '{"name":"lab-01"}'

This prints what it would do rather than touching the system. Replace `apply_config`
with the real work — render configuration.nix, run `nixos-rebuild switch` — and raise
on failure so the admin sees the reason next to the machine.
"""

import argparse
import asyncio
import logging
import sys

from nixync_client import MachineConfig, NixyncAgent, UnknownMachineError


# Stands in for the real machine. A real agent reads and writes configuration.nix
# instead; keeping the two functions below backed by the same state is what makes the
# server's drift detection meaningful.
_installed = MachineConfig()


def apply_config(config: MachineConfig) -> None:
    """Reconcile this machine to the full desired state the server sent.

    Return normally to report success; raise to report failure — the exception text
    becomes the message shown beside this machine in the fleet view.
    """
    global _installed
    print(f"  packages: {config.packages}")
    print(f"  services: {config.services}")
    print("  (a real agent would write configuration.nix and run nixos-rebuild switch)")
    _installed = config


def current_config() -> MachineConfig:
    """What this machine actually has right now.

    Sent on connect and after every apply, so the server can tell the difference
    between what was asked for and what is really installed — configuration drift.
    A real agent would parse configuration.nix here.
    """
    return _installed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--server", default="http://127.0.0.1:8000")
    parser.add_argument("--machine-id", required=True)
    parser.add_argument("--telemetry-interval", type=float, default=120.0)
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    agent = NixyncAgent(
        server_url=args.server,
        machine_id=args.machine_id,
        on_apply=apply_config,
        current_config=current_config,
        telemetry_interval=args.telemetry_interval,
        on_event=lambda event, payload: print(f"[{event}] {payload}"),
    )

    print(f"connecting to {args.server} as {args.machine_id} — Ctrl-C to stop")
    try:
        asyncio.run(agent.run())
    except UnknownMachineError as unknown:
        print(f"error: {unknown}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nstopped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
