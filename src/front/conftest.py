"""Make the desktop app and the client library importable from any working directory."""

import sys
from pathlib import Path

_FRONT = Path(__file__).resolve().parent
_CLIENT_LIBRARY = _FRONT.parent / "back" / "client"
_SHARED_UI = _FRONT.parent / "shared"

for path in (_FRONT, _CLIENT_LIBRARY, _SHARED_UI):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))
