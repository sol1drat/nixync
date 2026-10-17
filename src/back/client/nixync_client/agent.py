"""The machine-side agent: one persistent connection, telemetry out, config pushes in.

The agent never touches configuration.nix itself. It validates what the server sends and
hands it to the caller's `on_apply` handler, then reports back whatever that handler did.
That keeps the library safe to run anywhere — including inside a GUI — and leaves the
root-requiring work in code the caller owns.
"""

import asyncio
import logging
from collections.abc import Callable

from nixync_client import telemetry
from nixync_client.protocol import (
    ApplyConfig,
    MachineConfig,
    UnknownMessage,
    apply_result_message,
    config_report_message,
    parse_server_message,
    telemetry_message,
)
from nixync_client.transport import (
    AgentDisconnected,
    UnknownMachineError,
    WebSocketTransport,
)

logger = logging.getLogger(__name__)


async def _cancel_all(tasks) -> None:
    """Cancel tasks and collect their outcomes, so none is left unretrieved."""
    for task in tasks:
        task.cancel()
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)

DEFAULT_TELEMETRY_INTERVAL = 120.0
DEFAULT_BACKOFF_BASE = 1.0
MAX_BACKOFF_SECONDS = 30.0

ApplyHandler = Callable[[MachineConfig], None]


class NixyncAgent:
    """Connects to a Nixync server and keeps this machine in sync with it.

    `on_apply` receives the full desired configuration. Return normally to report
    success; raise to report failure — the exception text becomes the reason the admin
    sees next to the machine.
    """

    def __init__(
        self,
        server_url: str,
        machine_id: str,
        *,
        on_apply: ApplyHandler | None = None,
        current_config: Callable[[], MachineConfig] | None = None,
        telemetry_interval: float = DEFAULT_TELEMETRY_INTERVAL,
        reconnect: bool = True,
        sampler: Callable[[], telemetry.Reading] = telemetry.sample,
        transport_factory: Callable[[], WebSocketTransport] | None = None,
        max_connection_attempts: int | None = None,
        backoff_base: float = DEFAULT_BACKOFF_BASE,
        on_event: Callable[[str, dict], None] | None = None,
    ):
        self.server_url = server_url
        self.machine_id = machine_id
        self.on_apply = on_apply
        self.current_config = current_config
        self.telemetry_interval = telemetry_interval
        self.reconnect = reconnect
        self.sampler = sampler
        self.max_connection_attempts = max_connection_attempts
        self.backoff_base = backoff_base
        self.on_event = on_event
        self._transport_factory = transport_factory or (
            lambda: WebSocketTransport(server_url, machine_id)
        )
        self._stopped = asyncio.Event()
        self._transport: WebSocketTransport | None = None
        self._loop: asyncio.AbstractEventLoop | None = None

    # -- lifecycle ---------------------------------------------------------

    async def run(self) -> None:
        """Stay connected until `stop()` is called.

        Raises `UnknownMachineError` if the server rejects this machine id, since no
        amount of retrying will fix an unregistered machine.
        """
        self._loop = asyncio.get_running_loop()
        self._stopped.clear()
        attempt = 0
        while not self._stopped.is_set():
            attempt += 1
            try:
                await self._run_one_connection()
            except UnknownMachineError:
                # Redundant today (it is not an AgentDisconnected, so it would propagate
                # anyway) but kept deliberately: it is the line a reader looks for, and
                # it survives someone later reparenting the exception.
                raise
            except AgentDisconnected as disconnected:
                self._emit("disconnected", {"reason": str(disconnected)})
                if not self.reconnect or self._stopped.is_set():
                    return
                if self.max_connection_attempts and attempt >= self.max_connection_attempts:
                    return
                await self._sleep_backoff(attempt)
            else:
                return

    def stop(self) -> None:
        """Ask `run()` to shut down. Safe to call from any thread.

        `asyncio.Event.set()` is not thread-safe, so a GUI calling this from its UI
        thread while the agent runs in a worker would set the flag without ever waking
        the coroutine waiting on it. Hopping through the agent's own loop fixes that;
        from inside that loop it behaves like a plain `call_soon`.
        """
        loop = self._loop
        if loop is None:
            self._stopped.set()
            return
        try:
            loop.call_soon_threadsafe(self._stopped.set)
        except RuntimeError:
            # The loop has already closed, so there is nothing left to wake.
            self._stopped.set()

    async def _sleep_backoff(self, attempt: int) -> None:
        delay = min(self.backoff_base * (2 ** (attempt - 1)), MAX_BACKOFF_SECONDS)
        logger.info("reconnecting to %s in %.1fs", self.server_url, delay)
        await asyncio.sleep(delay)

    # -- one connection ----------------------------------------------------

    async def _run_one_connection(self) -> None:
        transport = self._transport_factory()
        self._transport = transport
        await transport.connect()
        self._emit("connected", {"machine_id": self.machine_id})

        tasks: set[asyncio.Task] = set()
        try:
            await transport.send(config_report_message(self._read_current_config()))
            tasks = {
                asyncio.create_task(self._stopped.wait()),
                asyncio.create_task(self._telemetry_loop(transport)),
                asyncio.create_task(self._receive_loop(transport)),
            }
            done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)

            # Settle the losers before closing the socket. Closing first would wake a
            # still-pending read, and its exception would have no one left to retrieve it.
            await _cancel_all(pending)
            for task in done:
                task.result()  # re-raise whatever ended the connection
        finally:
            await _cancel_all(tasks)
            await transport.close()
            self._transport = None
            if self._stopped.is_set():
                raise asyncio.CancelledError("agent stopped")

    async def _telemetry_loop(self, transport) -> None:
        """Report immediately, then on the interval — a dashboard should never wait."""
        while True:
            reading = await asyncio.to_thread(self.sampler)
            await transport.send(telemetry_message(**reading.as_message_fields()))
            self._emit("telemetry_sent", reading.as_message_fields())
            await asyncio.sleep(self.telemetry_interval)

    async def _receive_loop(self, transport) -> None:
        while True:
            message = parse_server_message(await transport.receive())
            if isinstance(message, ApplyConfig):
                await self._handle_apply(transport, message)
            elif isinstance(message, UnknownMessage):
                # A newer server may send things this version predates; stay connected.
                logger.warning("ignoring unsupported message type %r", message.type)

    async def _handle_apply(self, transport, push: ApplyConfig) -> None:
        self._emit("config_received", {"apply_id": push.apply_id})
        applied, reason = await self._apply(push.config)
        await transport.send(
            apply_result_message(push.apply_id, applied=applied, message=reason)
        )
        # Re-report afterwards so the server's view of this machine reflects the work
        # that just happened. Without it the reported state is only ever as fresh as
        # the last connect, and every deployed machine would look like it had drifted.
        # On failure this matters more, not less: it shows what the box actually has
        # after a partial rebuild.
        await transport.send(config_report_message(self._read_current_config()))

    async def _apply(self, config: MachineConfig) -> tuple[bool, str | None]:
        if self.on_apply is None:
            return False, "no handler is registered on this agent to apply configuration"
        try:
            # Off the event loop: a real nixos-rebuild takes minutes and must not
            # stall telemetry or the socket.
            await asyncio.to_thread(self.on_apply, config)
        except Exception as error:  # noqa: BLE001 - any handler failure is a failed apply
            logger.exception("apply handler failed")
            return False, str(error)
        return True, None

    # -- helpers -----------------------------------------------------------

    def _read_current_config(self) -> MachineConfig:
        if self.current_config is None:
            return MachineConfig()
        return self.current_config()

    def _emit(self, event: str, payload: dict) -> None:
        if self.on_event is not None:
            self.on_event(event, payload)
