"""Nixync desktop front end (Qt 6 / PySide6)."""

import sys
from pathlib import Path

# The desktop app talks to the server through `nixync_client` (src/back/client), which
# owns the wire protocol. This repository has no packaging, so make the library
# importable the same way the test suites do, rather than requiring an install step.
_CLIENT_LIBRARY = Path(__file__).resolve().parents[2] / "back" / "client"
if _CLIENT_LIBRARY.is_dir() and str(_CLIENT_LIBRARY) not in sys.path:
    sys.path.insert(0, str(_CLIENT_LIBRARY))

__version__ = "0.1.0"
