"""Optional PySide6 adapter: the agent as a QObject with signals.

Import this only if you are writing a Qt app — `nixync_client` itself has no Qt
dependency, so the agent still runs headless on a NixOS box.

The agent is an asyncio program and Qt has its own event loop, so `QtAgent` runs the
agent's loop on a worker thread and reports back with signals. Qt delivers a signal
emitted from a non-GUI thread as a queued connection, which means your slots run on the
UI thread and may touch widgets directly.
"""

import asyncio
import threading
from collections.abc import Callable

try:
    from PySide6.QtCore import QObject, Signal
except ModuleNotFoundError as missing:  # pragma: no cover - depends on the environment
    raise ModuleNotFoundError(
        "nixync_client.qt needs PySide6. Install it with 'pip install PySide6', or use "
        "nixync_client.agent.NixyncAgent directly if you are not writing a Qt app."
    ) from missing

from nixync_client.agent import DEFAULT_TELEMETRY_INTERVAL, ApplyHandler, NixyncAgent
from nixync_client.protocol import MachineConfig
from nixync_client.transport import UnknownMachineError

SHUTDOWN_TIMEOUT_SECONDS = 5.0


class QtAgent(QObject):
    """A `NixyncAgent` that lives on its own thread and talks to Qt in signals.

        agent = QtAgent(server_url, machine_id, on_apply=apply_to_this_machine)
        agent.connected.connect(self.show_online)
        agent.error.connect(self.show_error)
        agent.start()

    `on_apply` runs on a worker thread, not the UI thread — do not touch widgets from
    it. Report progress by connecting to `config_received` and `apply_finished`.
    """

    connected = Signal()
    disconnected = Signal(str)
    telemetry_sent = Signal(dict)
    config_received = Signal(str)
    apply_finished = Signal(str, bool, str)
    error = Signal(str)
    stopped = Signal()

    def __init__(
        self,
        server_url: str,
        machine_id: str,
        *,
        on_apply: ApplyHandler | None = None,
        current_config: Callable[[], MachineConfig] | None = None,
        telemetry_interval: float = DEFAULT_TELEMETRY_INTERVAL,
        parent: QObject | None = None,
    ):
        super().__init__(parent)
        self._agent = NixyncAgent(
            server_url=server_url,
            machine_id=machine_id,
            on_apply=self._wrap_handler(on_apply),
            current_config=current_config,
            telemetry_interval=telemetry_interval,
            on_event=self._on_event,
        )
        self._thread: threading.Thread | None = None
        # Applies are handled one at a time per connection, so the last apply_id the
        # server pushed is the one the handler is currently working on.
        self._current_apply_id = ""

    # -- lifecycle ---------------------------------------------------------

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        """Connect in the background. Returns immediately; never blocks the UI."""
        if self.is_running:
            return
        self._thread = threading.Thread(
            target=self._run, name="nixync-agent", daemon=True
        )
        self._thread.start()

    def stop(self, timeout: float = SHUTDOWN_TIMEOUT_SECONDS) -> None:
        """Shut the agent down and wait for its thread. Safe to call more than once."""
        if self._thread is None:
            return
        worker = self._thread
        self._agent.stop()
        worker.join(timeout=timeout)

        if worker.is_alive():
            # Clearing the reference here would leak the thread while `is_running`
            # reported False — a hung agent that looks stopped. Say so instead.
            self.error.emit(f"the agent thread did not shut down within {timeout}s")
            return
        self._thread = None

    def _run(self) -> None:
        try:
            asyncio.run(self._agent.run())
        except asyncio.CancelledError:
            pass  # the normal result of stop()
        except UnknownMachineError as unknown:
            self.error.emit(str(unknown))
        except Exception as unexpected:  # noqa: BLE001 - surfaced to the UI, not swallowed
            self.error.emit(str(unexpected))
        finally:
            self.stopped.emit()

    # -- bridging agent callbacks to signals -------------------------------

    def _on_event(self, event: str, payload: dict) -> None:
        match event:
            case "connected":
                self.connected.emit()
            case "disconnected":
                self.disconnected.emit(payload.get("reason", ""))
            case "telemetry_sent":
                self.telemetry_sent.emit(payload)
            case "config_received":
                self._current_apply_id = payload.get("apply_id", "")
                self.config_received.emit(self._current_apply_id)

    def _wrap_handler(self, on_apply: ApplyHandler | None) -> ApplyHandler | None:
        """Report the outcome of each apply without hiding the failure from the agent."""
        if on_apply is None:
            return None

        def handler(config: MachineConfig) -> None:
            apply_id = self._current_apply_id
            try:
                on_apply(config)
            except Exception as failure:  # noqa: BLE001 - re-raised after reporting
                self.apply_finished.emit(apply_id, False, str(failure))
                raise
            self.apply_finished.emit(apply_id, True, "")

        return handler
