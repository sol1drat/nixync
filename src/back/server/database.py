import json
import sqlite3
import uuid
from datetime import datetime, timezone

from models import AppRequest, Bundle, MachineConfig, MachineOut, Preset

SCHEMA = """
CREATE TABLE IF NOT EXISTS machines (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    created_at TEXT NOT NULL,
    preset TEXT NOT NULL DEFAULT '',
    "group" TEXT NOT NULL DEFAULT '',
    address TEXT NOT NULL DEFAULT '',
    cpu_percent REAL,
    ram_used_mb INTEGER,
    ram_total_mb INTEGER,
    disk_used_gb REAL,
    disk_total_gb REAL,
    metrics_reported_at TEXT,
    config_json TEXT NOT NULL,
    reported_config_json TEXT,
    last_apply_id TEXT,
    last_apply_status TEXT,
    last_apply_message TEXT,
    last_apply_at TEXT
)
"""


REQUESTS_SCHEMA = """
CREATE TABLE IF NOT EXISTS app_requests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    machine_id TEXT NOT NULL,
    app TEXT NOT NULL,
    requested_by TEXT NOT NULL,
    reason TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'pending',
    created_at TEXT NOT NULL,
    decided_at TEXT
)
"""

PRESETS_SCHEMA = """
CREATE TABLE IF NOT EXISTS presets (
    name TEXT PRIMARY KEY,
    bundles_json TEXT NOT NULL,
    extra_apps_json TEXT NOT NULL
)
"""

# Columns added after the first release. Quoted because "group" is SQL syntax.
_LATER_COLUMNS = {
    "reported_config_json": "TEXT",
    "preset": "TEXT NOT NULL DEFAULT ''",
    '"group"': "TEXT NOT NULL DEFAULT ''",
    "address": "TEXT NOT NULL DEFAULT ''",
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# Shipped so a fresh server is usable immediately: the add-device dialog needs
# something in its preset list, and an empty fleet with no roles looks broken rather
# than new. Seeded only when the table is empty, so edits and deletions stick.
DEFAULT_PRESETS = [
    Preset(
        name="Workstation",
        bundles=[
            Bundle(name="Developer tools", description="Git, a C compiler, Python and Docker"),
            Bundle(name="Secure remote login", description="SSH with keys only, no root login"),
            Bundle(name="Printing", description="Connects to the lab printer", enabled=False),
        ],
        extra_apps=["firefox", "htop"],
    ),
    Preset(
        name="Build server",
        bundles=[
            Bundle(name="Developer tools", description="Git, a C compiler, Python and Docker"),
            Bundle(name="Secure remote login", description="SSH with keys only, no root login"),
        ],
    ),
    Preset(
        name="Web server",
        bundles=[
            Bundle(name="Secure remote login", description="SSH with keys only, no root login"),
        ],
        extra_apps=["nginx"],
    ),
]


def _seed_presets(conn: sqlite3.Connection) -> None:
    if conn.execute("SELECT 1 FROM presets LIMIT 1").fetchone():
        return
    for preset in DEFAULT_PRESETS:
        save_preset(conn, preset)


def init_db(path: str) -> sqlite3.Connection:
    """Open the one connection the app shares for its lifetime.

    Sync routes run in Starlette's threadpool while the WebSocket handler runs on the
    event loop, so this connection is used from several threads. That is safe because
    CPython reports `sqlite3.threadsafety == 3` (serialized): SQLite itself serializes
    access. Revisit if the fleet ever outgrows one writer.
    """
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute(SCHEMA)
    conn.execute(PRESETS_SCHEMA)
    conn.execute(REQUESTS_SCHEMA)
    _add_missing_columns(conn)
    conn.commit()
    _seed_presets(conn)
    return conn


def _add_missing_columns(conn: sqlite3.Connection) -> None:
    """Bring an existing database up to date without making anyone delete their file."""
    existing = {row["name"] for row in conn.execute("PRAGMA table_info(machines)")}
    for column, definition in _LATER_COLUMNS.items():
        if column.strip('"') not in existing:
            conn.execute(f"ALTER TABLE machines ADD COLUMN {column} {definition}")


def _row_to_machine(row: sqlite3.Row) -> MachineOut:
    return MachineOut(
        id=row["id"],
        name=row["name"],
        created_at=row["created_at"],
        preset=row["preset"],
        group=row["group"],
        address=row["address"],
        online=False,
        cpu_percent=row["cpu_percent"],
        ram_used_mb=row["ram_used_mb"],
        ram_total_mb=row["ram_total_mb"],
        disk_used_gb=row["disk_used_gb"],
        disk_total_gb=row["disk_total_gb"],
        metrics_reported_at=row["metrics_reported_at"],
        config=MachineConfig.model_validate_json(row["config_json"]),
        reported_config=(
            MachineConfig.model_validate_json(row["reported_config_json"])
            if row["reported_config_json"]
            else None
        ),
        last_apply_id=row["last_apply_id"],
        last_apply_status=row["last_apply_status"],
        last_apply_message=row["last_apply_message"],
        last_apply_at=row["last_apply_at"],
    )


def create_machine(
    conn: sqlite3.Connection,
    name: str,
    *,
    preset: str = "",
    group: str = "",
    address: str = "",
) -> MachineOut:
    machine_id = str(uuid.uuid4())
    conn.execute(
        'INSERT INTO machines (id, name, created_at, config_json, preset, "group", address)'
        " VALUES (?, ?, ?, ?, ?, ?, ?)",
        (machine_id, name, _now(), MachineConfig().model_dump_json(), preset, group, address),
    )
    conn.commit()
    return get_machine(conn, machine_id)


def get_machine(conn: sqlite3.Connection, machine_id: str) -> MachineOut | None:
    row = conn.execute("SELECT * FROM machines WHERE id = ?", (machine_id,)).fetchone()
    return _row_to_machine(row) if row else None


def list_machines(conn: sqlite3.Connection) -> list[MachineOut]:
    rows = conn.execute("SELECT * FROM machines ORDER BY created_at").fetchall()
    return [_row_to_machine(row) for row in rows]


def delete_machine(conn: sqlite3.Connection, machine_id: str) -> bool:
    cursor = conn.execute("DELETE FROM machines WHERE id = ?", (machine_id,))
    conn.commit()
    return cursor.rowcount > 0


def update_telemetry(
    conn: sqlite3.Connection,
    machine_id: str,
    *,
    cpu_percent: float,
    ram_used_mb: int,
    ram_total_mb: int,
    disk_used_gb: float,
    disk_total_gb: float,
) -> None:
    conn.execute(
        """
        UPDATE machines
        SET cpu_percent = ?, ram_used_mb = ?, ram_total_mb = ?,
            disk_used_gb = ?, disk_total_gb = ?, metrics_reported_at = ?
        WHERE id = ?
        """,
        (cpu_percent, ram_used_mb, ram_total_mb, disk_used_gb, disk_total_gb, _now(), machine_id),
    )
    conn.commit()


def save_reported_config(
    conn: sqlite3.Connection, machine_id: str, config: MachineConfig
) -> None:
    """Record what a machine says it actually has.

    Deliberately separate from `config_json`: that column is the admin's *desired*
    state. Letting a machine's report overwrite it would mean a hand-edited box
    silently rewrote the fleet's intent, and would erase a change still queued for a
    machine that is only now coming online.
    """
    conn.execute(
        "UPDATE machines SET reported_config_json = ? WHERE id = ?",
        (config.model_dump_json(), machine_id),
    )
    # Enrollment: adopt what an existing machine already has as its initial desired
    # state, so the admin's first package add extends that setup instead of wiping it.
    # The `last_apply_id IS NULL` guard limits this to machines that have never been
    # deployed to — once the admin has declared intent, only the admin changes it.
    conn.execute(
        "UPDATE machines SET config_json = ? WHERE id = ? AND last_apply_id IS NULL",
        (config.model_dump_json(), machine_id),
    )
    conn.commit()


def set_apply_pending(
    conn: sqlite3.Connection,
    machine_id: str,
    *,
    apply_id: str,
    config: MachineConfig,
) -> None:
    conn.execute(
        """
        UPDATE machines
        SET config_json = ?, last_apply_id = ?, last_apply_status = 'pending',
            last_apply_message = NULL, last_apply_at = NULL
        WHERE id = ?
        """,
        (config.model_dump_json(), apply_id, machine_id),
    )
    conn.commit()


def set_apply_result(
    conn: sqlite3.Connection,
    machine_id: str,
    *,
    apply_id: str,
    status: str,
    message: str | None,
) -> None:
    conn.execute(
        """
        UPDATE machines
        SET last_apply_status = ?, last_apply_message = ?, last_apply_at = ?
        WHERE id = ? AND last_apply_id = ?
        """,
        (status, message, _now(), machine_id, apply_id),
    )
    conn.commit()


def update_machine(
    conn: sqlite3.Connection,
    machine_id: str,
    *,
    name: str | None = None,
    preset: str | None = None,
    group: str | None = None,
    address: str | None = None,
) -> MachineOut | None:
    """Edit a machine's labels. None means "leave this one alone"."""
    columns = {"name": name, "preset": preset, '"group"': group, "address": address}
    changes = {c: v for c, v in columns.items() if v is not None}
    if changes:
        assignments = ", ".join(f"{c} = ?" for c in changes)
        conn.execute(
            f"UPDATE machines SET {assignments} WHERE id = ?",
            (*changes.values(), machine_id),
        )
        conn.commit()
    return get_machine(conn, machine_id)


# -- presets ---------------------------------------------------------------


def _row_to_preset(row: sqlite3.Row) -> Preset:
    return Preset(
        name=row["name"],
        bundles=[Bundle.model_validate(b) for b in json.loads(row["bundles_json"])],
        extra_apps=json.loads(row["extra_apps_json"]),
    )


def list_presets(conn: sqlite3.Connection) -> list[Preset]:
    rows = conn.execute("SELECT * FROM presets ORDER BY name").fetchall()
    return [_row_to_preset(row) for row in rows]


def get_preset(conn: sqlite3.Connection, name: str) -> Preset | None:
    row = conn.execute("SELECT * FROM presets WHERE name = ?", (name,)).fetchone()
    return _row_to_preset(row) if row else None


def save_preset(conn: sqlite3.Connection, preset: Preset) -> Preset:
    """Create or replace a preset. Named presets are their own identity."""
    conn.execute(
        "INSERT INTO presets (name, bundles_json, extra_apps_json) VALUES (?, ?, ?)"
        " ON CONFLICT(name) DO UPDATE SET bundles_json = excluded.bundles_json,"
        " extra_apps_json = excluded.extra_apps_json",
        (
            preset.name,
            json.dumps([b.model_dump() for b in preset.bundles]),
            json.dumps(preset.extra_apps),
        ),
    )
    conn.commit()
    return get_preset(conn, preset.name)


def delete_preset(conn: sqlite3.Connection, name: str) -> bool:
    cursor = conn.execute("DELETE FROM presets WHERE name = ?", (name,))
    conn.commit()
    return cursor.rowcount > 0


def machines_using_preset(conn: sqlite3.Connection, name: str) -> list[str]:
    """Names of machines assigned this preset — used to refuse an orphaning delete."""
    rows = conn.execute("SELECT name FROM machines WHERE preset = ?", (name,)).fetchall()
    return [row["name"] for row in rows]


# -- app requests ----------------------------------------------------------


def _row_to_request(row: sqlite3.Row) -> AppRequest:
    return AppRequest(
        id=row["id"],
        machine_id=row["machine_id"],
        # Joined in so the admin's list reads as device names, not opaque ids. A
        # request for a since-removed machine keeps its id and shows it.
        machine_name=row["machine_name"] or row["machine_id"],
        app=row["app"],
        requested_by=row["requested_by"],
        reason=row["reason"],
        status=row["status"],
        created_at=row["created_at"],
        decided_at=row["decided_at"],
    )


_REQUEST_QUERY = """
SELECT r.*, m.name AS machine_name
FROM app_requests r LEFT JOIN machines m ON m.id = r.machine_id
"""


def create_request(
    conn: sqlite3.Connection,
    *,
    machine_id: str,
    app: str,
    requested_by: str,
    reason: str = "",
) -> AppRequest:
    cursor = conn.execute(
        "INSERT INTO app_requests (machine_id, app, requested_by, reason, created_at)"
        " VALUES (?, ?, ?, ?, ?)",
        (machine_id, app, requested_by, reason, _now()),
    )
    conn.commit()
    return get_request(conn, cursor.lastrowid)


def get_request(conn: sqlite3.Connection, request_id: int) -> AppRequest | None:
    row = conn.execute(f"{_REQUEST_QUERY} WHERE r.id = ?", (request_id,)).fetchone()
    return _row_to_request(row) if row else None


def list_requests(
    conn: sqlite3.Connection, machine_id: str | None = None
) -> list[AppRequest]:
    """Newest first: an admin reviewing a queue wants the latest asks at the top."""
    if machine_id is None:
        rows = conn.execute(f"{_REQUEST_QUERY} ORDER BY r.id DESC").fetchall()
    else:
        rows = conn.execute(
            f"{_REQUEST_QUERY} WHERE r.machine_id = ? ORDER BY r.id DESC", (machine_id,)
        ).fetchall()
    return [_row_to_request(row) for row in rows]


def set_request_status(
    conn: sqlite3.Connection, request_id: int, status: str
) -> AppRequest | None:
    conn.execute(
        "UPDATE app_requests SET status = ?, decided_at = ? WHERE id = ?",
        (status, _now(), request_id),
    )
    conn.commit()
    return get_request(conn, request_id)
