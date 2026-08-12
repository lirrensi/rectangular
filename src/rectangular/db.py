"""SQLite storage for Rectangular.

Everything lives in .rect/rect.db. Created lazily on first use (rect ui / first
insert). No init ceremony. The whole .rect/ folder is committed to git.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

RECT_DIR_NAME = ".rect"
DB_FILE_NAME = "rect.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS tickets (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    title            TEXT NOT NULL,
    status           TEXT NOT NULL DEFAULT '',
    approved         INTEGER NOT NULL DEFAULT 0,
    pending_approval INTEGER NOT NULL DEFAULT 0,
    created_by       TEXT NOT NULL DEFAULT 'user',
    created_at       TEXT NOT NULL,
    updated_at       TEXT NOT NULL
);

-- The chat. A ticket IS a conversation.
-- role: user | assistant | system   (UI=user, CLI=system by default)
-- name: optional, for future multi-collab (which worker/agent)
CREATE TABLE IF NOT EXISTS messages (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    ticket_id       INTEGER NOT NULL REFERENCES tickets(id) ON DELETE CASCADE,
    role            TEXT NOT NULL DEFAULT 'system',
    name            TEXT,
    body            TEXT NOT NULL,
    status_after    TEXT,                       -- status set by this message
    approval_action TEXT,                       -- 'approve' | 'unapprove' | NULL
    created_at      TEXT NOT NULL
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


def _migrate(conn: sqlite3.Connection) -> None:
    """Migrate legacy `comments` table (author) → `messages` (role, name)."""
    has_comments = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='comments'"
    ).fetchone()
    has_messages = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='messages'"
    ).fetchone()
    if not has_comments or has_messages:
        return

    conn.execute("ALTER TABLE comments RENAME TO messages")
    # add name column (nullable)
    try:
        conn.execute("ALTER TABLE messages ADD COLUMN name TEXT")
    except sqlite3.OperationalError:
        pass
    # rename author → role, then map old values
    try:
        conn.execute("ALTER TABLE messages RENAME COLUMN author TO role")
    except sqlite3.OperationalError:
        pass
    conn.execute("UPDATE messages SET role = 'system' WHERE role = 'agent'")
    conn.execute("UPDATE messages SET role = 'user' WHERE role = 'user'")
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
