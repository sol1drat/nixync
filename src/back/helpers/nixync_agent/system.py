"""Write Nixync's configuration module to a machine and rebuild it.

The only code in the project that changes a real system, so it is built to be
distrusted: every path and the rebuild command are injected, the module is written
atomically, and a failed rebuild puts the previous file back.

Nixync owns exactly one file — `nixync.nix` — and adds a single import line to the
machine's `configuration.nix`. Hand-written configuration and the hardware module
survive untouched, and removing Nixync leaves a machine that still builds.
"""

import logging
import os
import re
import subprocess
import tempfile
from collections.abc import Callable
from pathlib import Path

from nixync_client.nix import render
from nixync_client.protocol import MachineConfig

logger = logging.getLogger(__name__)

MODULE_NAME = "nixync.nix"
IMPORT_PATH = "./nixync.nix"
REBUILD_COMMAND = ["nixos-rebuild", "switch"]
REBUILD_TIMEOUT_SECONDS = 30 * 60
# A full rebuild log runs to thousands of lines; the failure is at the end of it.
ERROR_TAIL_LINES = 40

_IMPORTS_LIST = re.compile(r"imports\s*=\s*\[(?P<body>.*?)\]", re.DOTALL)


class RebuildFailed(RuntimeError):
    """`nixos-rebuild` returned non-zero. Carries the tail of its output."""


class SystemWriter:
    """Applies a MachineConfig to this machine.

    `config_dir` and `run` are arguments so tests never touch a real /etc and never
    invoke a real rebuild. `dry_run` renders and reports without writing anything,
    so the daemon can be run on a development machine.
    """

    def __init__(
        self,
        config_dir: Path = Path("/etc/nixos"),
        run: Callable[..., subprocess.CompletedProcess] = subprocess.run,
        dry_run: bool = False,
        rebuild_command: list[str] | None = None,
    ):
        self.config_dir = Path(config_dir)
        self.run = run
        self.dry_run = dry_run
        self.rebuild_command = rebuild_command or REBUILD_COMMAND

    @property
    def module_path(self) -> Path:
        return self.config_dir / MODULE_NAME

    @property
    def configuration_path(self) -> Path:
        return self.config_dir / "configuration.nix"

    # -- the one public operation ------------------------------------------

    def apply(self, config: MachineConfig) -> str:
        """Render, write, make sure it is imported, and rebuild.

        Returns the Nix that was written. Raises `InvalidPackageName` for a name that
        cannot be safely rendered, or `RebuildFailed` if the machine would not build —
        in which case the previous configuration is restored first.
        """
        # Render before touching anything: an unsafe name must not leave a partial
        # write behind, and rendering is the step most likely to reject the input.
        text = render(config)

        if self.dry_run:
            logger.info("dry run: would write %s and rebuild", self.module_path)
            return text

        previous = self.module_path.read_text() if self.module_path.exists() else None
        previous_state = self.current_config()
        self._write_atomically(text)
        self._ensure_imported()

        try:
            self._rebuild()
        except RebuildFailed:
            # The machine is still running the old configuration, so the recorded
            # state has to go back too — otherwise the agent would report the config
            # it failed to apply as the one the machine has.
            self._restore(previous)
            self._record_state(previous_state)
            raise
        self._record_state(config)
        return text

    def current_config(self) -> MachineConfig:
        """What Nixync last wrote here.

        Read from a sidecar rather than by parsing Nix back: the file is generated,
        so round-tripping it would be re-implementing a Nix evaluator to recover
        something already known.
        """
        record = self.config_dir / ".nixync-state.json"
        if not record.exists():
            return MachineConfig()
        import json

        try:
            return MachineConfig.from_dict(json.loads(record.read_text()))
        except (ValueError, KeyError):
            # A corrupt record is not worth crashing the agent over; the server will
            # push the desired state again and this gets rewritten.
            logger.warning("ignoring unreadable %s", record)
            return MachineConfig()

    # -- internals ---------------------------------------------------------

    def _write_atomically(self, text: str) -> None:
        """Write via a temp file in the same directory, then rename over the target.

        A rename is atomic on POSIX, so an interrupted write cannot leave a truncated
        module that stops the machine rebuilding — including its next boot.
        """
        self.config_dir.mkdir(parents=True, exist_ok=True)
        handle, temp_name = tempfile.mkstemp(dir=self.config_dir, suffix=".tmp")
        try:
            with os.fdopen(handle, "w", encoding="utf-8") as file:
                file.write(text)
                file.flush()
                os.fsync(file.fileno())
            os.replace(temp_name, self.module_path)
        except BaseException:
            Path(temp_name).unlink(missing_ok=True)
            raise

    def _record_state(self, config: MachineConfig) -> None:
        import json

        state = self.config_dir / ".nixync-state.json"
        state.write_text(json.dumps(config.to_dict(), indent=2))

    def _ensure_imported(self) -> None:
        """Add `./nixync.nix` to configuration.nix, once."""
        path = self.configuration_path
        if not path.exists():
            # Nothing to extend. Writing a configuration.nix from scratch would be
            # claiming ownership of the machine, which this deliberately does not do.
            logger.warning("%s does not exist; not creating one", path)
            return

        text = path.read_text()
        if IMPORT_PATH in text:
            return

        match = _IMPORTS_LIST.search(text)
        if match:
            body = match.group("body").rstrip()
            updated = text[: match.start()] + f"imports = [{body} {IMPORT_PATH} ]" + text[match.end():]
        else:
            # No imports list at all: add one just inside the module's attribute set.
            opening = text.index("{", text.index(":") + 1) if ":" in text else text.index("{")
            updated = (
                text[: opening + 1]
                + f"\n  imports = [ {IMPORT_PATH} ];\n"
                + text[opening + 1 :]
            )
        path.write_text(updated)

    def _rebuild(self) -> None:
        logger.info("running %s", " ".join(self.rebuild_command))
        result = self.run(
            self.rebuild_command,
            capture_output=True,
            text=True,
            timeout=REBUILD_TIMEOUT_SECONDS,
        )
        if result.returncode != 0:
            raise RebuildFailed(_tail(result.stderr or result.stdout or ""))

    def _restore(self, previous: str | None) -> None:
        """Put back what was there, so a failed deployment leaves a buildable machine."""
        if previous is None:
            self.module_path.unlink(missing_ok=True)
        else:
            self._write_atomically(previous)


def _tail(output: str, lines: int = ERROR_TAIL_LINES) -> str:
    return "\n".join(output.strip().splitlines()[-lines:])
