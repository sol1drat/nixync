"""Export the server's OpenAPI schema to openapi.json.

Run from the server directory:
    python scripts/export_openapi.py
"""

import json
import sys
from pathlib import Path

SERVER_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SERVER_DIR))

from server import app  # noqa: E402

OUTPUT_PATH = SERVER_DIR / "openapi.json"


def main() -> None:
    schema = app.openapi()
    OUTPUT_PATH.write_text(json.dumps(schema, indent=2) + "\n", encoding="utf-8")

    paths = schema.get("paths", {})
    print(f"Wrote {OUTPUT_PATH} (OpenAPI {schema.get('openapi')})")
    for path in sorted(paths):
        methods = ", ".join(sorted(m.upper() for m in paths[path]))
        print(f"  {methods:<22} {path}")
    print(
        "\nNote: /ws/machines/{machine_id} is absent by design — OpenAPI 3.1 has no "
        "WebSocket representation.\nThe agent protocol is documented in SPEC.md and in "
        "the API description shown at /docs."
    )


if __name__ == "__main__":
    main()
