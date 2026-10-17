import sqlite3
import uuid
from datetime import datetime, timezone

from models import MachineConfig, MachineOut

SCHEMA = """
CREATE TABLE IF NOT EXISTS machines (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    created_at TEXT NOT NULL,
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


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


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
    _add_missing_columns(conn)
    conn.commit()
    return conn


def _add_missing_columns(conn: sqlite3.Connection) -> None:
    """Bring an existing database up to date without making anyone delete their file."""
    existing = {row["name"] for row in conn.execute("PRAGMA table_info(machines)")}
    if "reported_config_json" not in existing:
        conn.execute("ALTER TABLE machines ADD COLUMN reported_config_json TEXT")


def _row_to_machine(row: sqlite3.Row) -> MachineOut:
    return MachineOut(
        id=row["id"],
        name=row["name"],
        created_at=row["created_at"],
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


def create_machine(conn: sqlite3.Connection, name: str) -> MachineOut:
    machine_id = str(uuid.uuid4())
    conn.execute(
        "INSERT INTO machines (id, name, created_at, config_json) VALUES (?, ?, ?, ?)",
        (machine_id, name, _now(), MachineConfig().model_dump_json()),
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
