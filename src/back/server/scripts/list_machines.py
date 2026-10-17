"""List the rows of the machines table.

Run from the server directory:
    python scripts/list_machines.py [--db PATH] [--json]

The database defaults to $NIXYNC_DB, then nixync.db. It is opened read-only, so this is
safe to run while the server is up.
"""

import argparse
import json
import os
import sqlite3
import sys
from pathlib import Path

DEFAULT_DB_PATH = "nixync.db"
COLUMNS = ("id", "name", "created_at", "cpu_percent", "ram_used_mb", "ram_total_mb", "last_apply_status")


def fetch_rows(path: str) -> list[sqlite3.Row]:
    conn = sqlite3.connect(f"{Path(path).resolve().as_uri()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        return conn.execute("SELECT * FROM machines ORDER BY created_at").fetchall()
    finally:
        conn.close()


def print_table(rows: list[sqlite3.Row]) -> None:
    cells = [[("-" if row[c] is None else str(row[c])) for c in COLUMNS] for row in rows]
    widths = [max(len(c), *(len(r[i]) for r in cells)) for i, c in enumerate(COLUMNS)]
    for line in [COLUMNS, *cells]:
        print("  ".join(v.ljust(w) for v, w in zip(line, widths)).rstrip())
    print(f"\n{len(rows)} machine(s)")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--db", default=os.environ.get("NIXYNC_DB", DEFAULT_DB_PATH))
    parser.add_argument("--json", action="store_true", help="print every column as JSON")
    args = parser.parse_args()

    if not Path(args.db).exists():
        print(f"No database at {args.db}", file=sys.stderr)
        return 1
    try:
        rows = fetch_rows(args.db)
    except sqlite3.OperationalError as error:
        print(f"Cannot read machines from {args.db}: {error}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps([dict(row) for row in rows], indent=2))
    else:
        print_table(rows)
    return 0


if __name__ == "__main__":
    sys.exit(main())
