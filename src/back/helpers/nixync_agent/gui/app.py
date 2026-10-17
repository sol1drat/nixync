"""Entry point for the device app: `python -m nixync_agent.gui`."""

import argparse
import sys
from pathlib import Path

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication

from nixync_agent import settings as agent_settings
from nixync_agent.gui.window import AgentWindow
from nixync_ui import style


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--config", type=Path, default=agent_settings.DEFAULT_PATH)
    parser.add_argument("--server", dest="server_url")
    parser.add_argument("--machine-id")
    args = parser.parse_args(argv)

    try:
        # The same file the daemon reads, so the app on a managed machine needs no
        # separate setup — it already knows which machine it is.
        config = agent_settings.load(
            args.config, server_url=args.server_url, machine_id=args.machine_id
        )
    except agent_settings.ConfigurationError as problem:
        print(f"error: {problem}", file=sys.stderr)
        return 2

    app = QApplication(sys.argv if argv is None else [sys.argv[0], *argv])
    style.apply(app, QSettings("Nixync", "NixyncAgent").value("theme", "light", type=str))
    window = AgentWindow(config.server_url, config.machine_id)
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
