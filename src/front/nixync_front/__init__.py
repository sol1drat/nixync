"""Nixync desktop front end (Qt 6 / PySide6)."""

import sys
from pathlib import Path

# This repository has no packaging, so make the sibling packages importable the same
# way the test suites do, rather than requiring an install step.
#   nixync_ui     (src/shared)      theme and widgets, shared with the device app
#   nixync_client (src/back/client) the wire protocol to the server
_SRC = Path(__file__).resolve().parents[2]
for _sibling in (_SRC / "shared", _SRC / "back" / "client"):
    if _sibling.is_dir() and str(_sibling) not in sys.path:
        sys.path.insert(0, str(_sibling))

__version__ = "0.1.0"
