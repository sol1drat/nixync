"""Make the agent package and its siblings importable from any working directory."""

import sys
from pathlib import Path

_HELPERS = Path(__file__).resolve().parent
_SRC = _HELPERS.parents[1]

for path in (_HELPERS, _SRC / "back" / "client", _SRC / "shared"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))
