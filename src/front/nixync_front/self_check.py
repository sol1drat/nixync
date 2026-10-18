"""Startup check for a packaged build.

PyInstaller works out what to include by reading imports statically, so anything
reached only at runtime can go missing and the app then dies on a traceback the
user cannot act on. This imports every such module, opens the first window
off-screen and exits, which is the part of startup worth gating in CI.
"""

import importlib
import os
import sys
from pathlib import Path

# Imported late in the real app: behind a menu action, a dialog or a search box.
LAZY_MODULES = (
    "nixync_front.ai",
    "nixync_front.dialogs.ask_ai",
    "nixync_front.app_picker",
    "nixync_front.nix_config",
    "nixos_search",
    "nixync_client.admin",
    "nixync_client.nix",
    "anthropic",
    "requests",
    "websockets",
)


def _check_icons() -> list[str]:
    from nixync_ui import style

    missing = [name for name in ("app-icon.png", "logo.png", "logo-white.png")
               if not (Path(style.ICONS) / name).is_file()]
    return [f"missing icon: {style.ICONS / name}" for name in missing]


def _check_imports() -> list[str]:
    problems = []
    for name in LAZY_MODULES:
        try:
            importlib.import_module(name)
        except Exception as e:  # noqa: BLE001 - report every failure, not just the first
            problems.append(f"cannot import {name}: {type(e).__name__}: {e}")
    return problems


def _check_window() -> list[str]:
    from PySide6.QtWidgets import QApplication

    from nixync_front.config import load_config
    from nixync_front.login import LoginWindow
    from nixync_ui import style

    app = QApplication.instance() or QApplication([])
    style.apply(app, "dark")
    window = LoginWindow(load_config())
    window.show()
    app.processEvents()
    ok = window.isVisible()
    window.close()
    return [] if ok else ["the login window did not open"]


def self_check() -> int:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    problems = _check_imports() + _check_icons() + _check_window()
    for problem in problems:
        print(f"FAIL {problem}", file=sys.stderr)
    if problems:
        return 1
    print(f"nixync self-check passed (frozen={getattr(sys, 'frozen', False)})")
    return 0
