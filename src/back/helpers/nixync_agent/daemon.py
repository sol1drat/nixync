"""The agent service: keeps this machine in step with the Nixync server.

Thin by design. `nixync_client.NixyncAgent` already owns the socket, reconnection,
telemetry scheduling, acking and redelivery of a change that arrived while the
machine was off. This module is the wiring — what to apply a push with, where to read
settings from, how to shut down — plus the process concerns a service needs.
"""

import argparse
import asyncio
import logging
import signal
import sys
from pathlib import Path

from nixync_agent import settings as agent_settings
from nixync_agent.system import SystemWriter
from nixync_client import NixyncAgent, UnknownMachineError
from nixync_client.protocol import MachineConfig

logger = logging.getLogger("nixync-agent")


def build_agent(
    config: agent_settings.AgentSettings, writer: SystemWriter | None = None
) -> NixyncAgent:
    """Wire the library agent to this machine's filesystem.

    `writer` is injectable so tests can supply one with a fake rebuild command; the
    default is the real thing pointed at the configured directory.
    """
    writer = writer or SystemWriter(config_dir=config.config_dir, dry_run=config.dry_run)

    def apply(desired: MachineConfig) -> None:
        # Raising is how a failure reaches the admin: the library turns the exception
        # text into the message shown beside this machine.
        logger.info("applying: %d package(s)", len(desired.packages))
        writer.apply(desired)
        logger.info("applied")

    return NixyncAgent(
        server_url=config.server_url,
        machine_id=config.machine_id,
        on_apply=apply,
        current_config=writer.current_config,
        telemetry_interval=config.telemetry_interval,
        on_event=lambda event, payload: logger.info("%s %s", event, payload or ""),
    )


async def run(config: agent_settings.AgentSettings) -> int:
    agent = build_agent(config)

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        # systemd stops the service with SIGTERM; shut the socket down cleanly
        # rather than letting the process die mid-write.
        loop.add_signal_handler(sig, agent.stop)

    logger.info("connecting to %s as %s", config.server_url, config.machine_id)
    if config.dry_run:
        logger.warning("dry run: nothing will be written and no rebuild will run")

    try:
        await agent.run()
    except UnknownMachineError as unknown:
        # Retrying forever against a server that will never accept this id just hides
        # a misconfiguration behind an endless reconnect loop.
        logger.error("%s", unknown)
        return 1
    except asyncio.CancelledError:
        logger.info("stopped")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--config", type=Path, default=agent_settings.DEFAULT_PATH)
    parser.add_argument("--server", dest="server_url")
    parser.add_argument("--machine-id")
    parser.add_argument("--config-dir", type=Path)
    parser.add_argument("--telemetry-interval", type=float)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=None,
        help="render and log, but write nothing and never rebuild",
    )
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    try:
        config = agent_settings.load(
            args.config,
            server_url=args.server_url,
            machine_id=args.machine_id,
            config_dir=args.config_dir,
            telemetry_interval=args.telemetry_interval,
            dry_run=args.dry_run,
        )
    except agent_settings.ConfigurationError as problem:
        print(f"error: {problem}", file=sys.stderr)
        return 2

    return asyncio.run(run(config))


if __name__ == "__main__":
    raise SystemExit(main())
