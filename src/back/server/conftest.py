"""Put the server package on sys.path so the suite runs from any working directory."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
