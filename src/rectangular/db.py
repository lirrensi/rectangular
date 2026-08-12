"""SQLite storage for Rectangular.

Everything lives in .rect/rect.db. Created lazily on first use (rect ui / first
insert). No init ceremony. The whole .rect/ folder is committed to git.

State model (v3):
  tickets.state = 'active' | 'done'   (the only real machine state)
  messages.action = 'close' | 'reopen' | NULL   (audit trail of state flips)
  'waiting'/'review' is DERIVED: active ticket whose last message is from a worker.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

RECT_DIR_NAME = ".rect"
DB_FILE_NAME = "rect.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS tickets (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    title      TEXT NOT NULL,
    status     TEXT NOT NULL DEFAULT '',
    state      TEXT NOT NULL DEFAULT 'active',   -- 'active' | 'done'
    created_by TEXT NOT NULL DEFAULT 'user',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

-- The chat. A ticket IS a conversation.
-- role: user | assistant | system   (UI=user, CLI=system by default)
-- name: optional, for future multi-collab (which worker/agent)
CREATE TABLE IF NOT EXISTS messages (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    ticket_id    INTEGER NOT NULL REFERENCES tickets(id) ON DELETE CASCADE,
    role         TEXT NOT NULL DEFAULT 'system',
    name         TEXT,
    body         TEXT NOT NULL,
    status_after TEXT,                       -- status set by this message
    action       TEXT,                       -- 'close' | 'reopen' | NULL
    created_at   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


def rect_dir() -> Path:
    return Path.cwd() / RECT_DIR_NAME


def db_path() -> Path:
    return rect_dir() / DB_FILE_NAME


# Current schema version. Bump + add a migration step when the schema changes.
SCHEMA_VERSION = 3


def connect() -> sqlite3.Connection:
    """Open a connection, creating .rect/ and the schema on first use."""
    d = rect_dir()
    d.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(d / DB_FILE_NAME)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    _migrate(conn)
    conn.executescript(_SCHEMA)
    _seed_settings(conn)
    return conn


def schema_version(conn: sqlite3.Connection) -> int:
    return conn.execute("PRAGMA user_version").fetchone()[0]


def _table_cols(conn: sqlite3.Connection, table: str) -> set[str]:
    return {r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}


def _set_version(conn: sqlite3.Connection, version: int) -> None:
    conn.execute(f"PRAGMA user_version = {int(version)}")
    conn.commit()


def _migrate(conn: sqlite3.Connection) -> None:
    """Bring the DB up to SCHEMA_VERSION.

    Version 0 means either a fresh DB or a legacy DB created before
    versioning existed. The legacy path infers shape (columns/tables);
    from there on, every future change is an explicit `if version < N` step.
    """
    version = schema_version(conn)

    if version == 0:
        _migrate_legacy(conn)
        version = SCHEMA_VERSION

    # Future migrations, e.g.:
    # if version < 4:
    #     _migrate_3_to_4(conn)
    #     version = 4

    _set_version(conn, version)


def _migrate_legacy(conn: sqlite3.Connection) -> None:
    """Shape-inferred catch-all: bring any pre-versioning DB to v3."""
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}

    # ---- v1 → v2: comments(author) → messages(role, name) ----
    if "comments" in tables and "messages" not in tables:
        conn.execute("ALTER TABLE comments RENAME TO messages")
        try:
            conn.execute("ALTER TABLE messages ADD COLUMN name TEXT")
        except sqlite3.OperationalError:
            pass
        try:
            conn.execute("ALTER TABLE messages RENAME COLUMN author TO role")
        except sqlite3.OperationalError:
            pass
        conn.execute("UPDATE messages SET role = 'system' WHERE role = 'agent'")
        conn.commit()

    # ---- messages: approval_action → action (re-check after possible rename) ----
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    if "messages" in tables:
        mcols = _table_cols(conn, "messages")
        if "action" not in mcols and "approval_action" in mcols:
            conn.execute("ALTER TABLE messages RENAME COLUMN approval_action TO action")
            conn.execute("UPDATE messages SET action = 'close' WHERE action = 'approve'")
            conn.execute("UPDATE messages SET action = 'reopen' WHERE action = 'unapprove'")
            conn.commit()

    # ---- v2 → v3: tickets.approved/pending_approval → tickets.state ----
    if "tickets" in tables:
        cols = _table_cols(conn, "tickets")
        if "state" not in cols:
            conn.execute("ALTER TABLE tickets ADD COLUMN state TEXT NOT NULL DEFAULT 'active'")
        if "approved" in cols:
            conn.execute("UPDATE tickets SET state = 'done' WHERE approved = 1")
            conn.execute("ALTER TABLE tickets DROP COLUMN approved")
        if "pending_approval" in cols:
            conn.execute("ALTER TABLE tickets DROP COLUMN pending_approval")
        conn.commit()


def _seed_settings(conn: sqlite3.Connection) -> None:
    conn.execute(
        "INSERT OR IGNORE INTO settings (key, value) VALUES ('full_access', '0')"
    )
    conn.commit()


def get_setting(conn: sqlite3.Connection, key: str, default: str = "") -> str:
    row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else default


def set_setting(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        "INSERT INTO settings (key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )
    conn.commit()


def full_access_enabled(conn: sqlite3.Connection) -> bool:
    return get_setting(conn, "full_access", "0") == "1"


def is_sqlite_db(p: Path) -> bool:
    """Cheap sanity check: sqlite files start with the 'SQLite format 3' header."""
    try:
        with p.open("rb") as f:
            return f.read(16) == b"SQLite format 3\x00"
    except OSError:
        return False
