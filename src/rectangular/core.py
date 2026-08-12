"""Core operations for Rectangular.

A ticket IS a chat between the user and workers. Each message has:
  role       user | assistant | system   (UI=user, CLI=system by default)
  name       optional — which worker/agent, for future multi-collab
  body       the text
  time       created_at

The ONLY real machine state is `state`: 'active' | 'done'.
'waiting'/'review' is DERIVED: an active ticket whose last message is from a
worker — the ball is in the user's court. The UI sorts those to the top.

Message = primitive (always allowed). State flips (close/reopen) = user-only
by default; workers need Full Access Mode.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, date
from typing import Any

from . import db

ROLE_USER = "user"
ROLE_ASSISTANT = "assistant"
ROLE_SYSTEM = "system"
VALID_ROLES = {ROLE_USER, ROLE_ASSISTANT, ROLE_SYSTEM}

STATE_ACTIVE = "active"
STATE_DONE = "done"
VALID_STATES = {STATE_ACTIVE, STATE_DONE}

ACTION_CLOSE = "close"
ACTION_REOPEN = "reopen"


def ticket_no(ticket_id: int) -> str:
    return f"T-{ticket_id:04d}"


def parse_ticket_no(ref: str) -> int:
    """Accept 'T-0001', 'T-1', or '1'."""
    s = ref.strip().upper()
    if s.startswith("T-"):
        s = s[2:]
    s = s.lstrip("0")
    if not s:
        raise ValueError(f"Bad ticket ref: {ref!r}")
    return int(s)


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _today() -> str:
    return date.today().isoformat()


def _ticket_row(row: sqlite3.Row) -> dict[str, Any]:
    d = dict(row)
    d["no"] = ticket_no(d["id"])
    d["needs_review"] = False
    return d


# ---------------------------------------------------------------------------
# Tickets
# ---------------------------------------------------------------------------


def add_ticket(title: str, created_by: str = ROLE_USER) -> dict[str, Any]:
    if not title or not title.strip():
        raise ValueError("Ticket title cannot be empty.")
    conn = db.connect()
    try:
        now = _now()
        cur = conn.execute(
            "INSERT INTO tickets (title, status, state, created_by, created_at, updated_at) "
            "VALUES (?, '', ?, ?, ?, ?)",
            (title.strip(), STATE_ACTIVE, created_by, now, now),
        )
        conn.commit()
        new_id = cur.lastrowid
        if new_id is None:
            raise RuntimeError("Insert failed: no row id returned.")
        return get_ticket(new_id, conn=conn)
    finally:
        conn.close()


def get_ticket(ticket_id: int, conn: sqlite3.Connection | None = None) -> dict[str, Any]:
    own = conn is None
    conn = conn or db.connect()
    try:
        row = conn.execute("SELECT * FROM tickets WHERE id = ?", (ticket_id,)).fetchone()
        if row is None:
            raise KeyError(f"Ticket not found: {ticket_no(ticket_id)}")
        t = _ticket_row(row)
        t["messages"] = _messages(conn, ticket_id)
        t["needs_review"] = _needs_review(t["messages"])
        return t
    finally:
        if own:
            conn.close()


def _messages(conn: sqlite3.Connection, ticket_id: int) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT * FROM messages WHERE ticket_id = ? ORDER BY id ASC", (ticket_id,)
    ).fetchall()
    return [dict(r) for r in rows]


def _needs_review(messages: list[dict[str, Any]]) -> bool:
    """Ball in the user's court: last message came from a worker (not user)."""
    if not messages:
        return False
    return messages[-1]["role"] != ROLE_USER


def list_tickets(done: bool = False, limit: int | None = None) -> list[dict[str, Any]]:
    """Sequential list. Active by default, Done when done=True.

    Ordered newest first; within a day the needs-review tickets float to top.
    """
    conn = db.connect()
    try:
        state = STATE_DONE if done else STATE_ACTIVE
        rows = conn.execute(
            "SELECT * FROM tickets WHERE state = ? ORDER BY id DESC", (state,)
        ).fetchall()
        tickets = []
        for r in rows:
            t = _ticket_row(r)
            t["messages"] = _messages(conn, r["id"])
            t["needs_review"] = _needs_review(t["messages"])
            tickets.append(t)
        if limit is not None:
            tickets = tickets[:limit]
        return tickets
    finally:
        conn.close()


def group_by_day(tickets: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Group a ticket list into [{day, label, tickets:[...]}], newest day first.

    Within each day, tickets needing review float to the top.
    """
    groups: dict[str, list[dict[str, Any]]] = {}
    for t in tickets:
        day = t["created_at"][:10]
        groups.setdefault(day, []).append(t)
    ordered = sorted(groups.keys(), reverse=True)
    result = []
    for day in ordered:
        label = day
        if day == _today():
            label = "Today"
        elif day == (date.today().fromordinal(date.today().toordinal() - 1).isoformat()):
            label = "Yesterday"
        day_tickets = sorted(groups[day], key=lambda t: (not t["needs_review"],))
        result.append({"day": day, "label": label, "tickets": day_tickets})
    return result


def status_summary() -> dict[str, Any]:
    active = list_tickets(done=False)
    done = list_tickets(done=True)
    return {
        "active_count": len(active),
        "done_count": len(done),
        "needs_review": [t for t in active if t["needs_review"]],
        "peek": active[:10],
    }


# ---------------------------------------------------------------------------
# Messages — the chat (pure primitive, always allowed)
# ---------------------------------------------------------------------------


def _insert_message(
    conn: sqlite3.Connection,
    ticket_id: int,
    role: str,
    body: str,
    name: str | None = None,
    status_after: str | None = None,
    action: str | None = None,
) -> None:
    conn.execute(
        "INSERT INTO messages (ticket_id, role, name, body, status_after, action, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (ticket_id, role, name, body, status_after, action, _now()),
    )


def message(
    ticket_id: int,
    role: str,
    body: str,
    name: str | None = None,
    status: str | None = None,
) -> dict[str, Any]:
    """Append a chat message. Status is free (anyone may set it).

    NEVER touches state — messages are pure. Use close()/reopen() for state.
    """
    if role not in VALID_ROLES:
        raise ValueError(f"role must be one of {sorted(VALID_ROLES)}, got {role!r}")
    if body is None or not body.strip():
        raise ValueError("Message body cannot be empty.")

    conn = db.connect()
    try:
        row = conn.execute("SELECT * FROM tickets WHERE id = ?", (ticket_id,)).fetchone()
        if row is None:
            raise KeyError(f"Ticket not found: {ticket_no(ticket_id)}")

        _insert_message(conn, ticket_id, role, body.strip(), name=name, status_after=status)

        if status is not None and status != row["status"]:
            conn.execute(
                "UPDATE tickets SET status = ?, updated_at = ? WHERE id = ?",
                (status, _now(), ticket_id),
            )
        conn.commit()
        return get_ticket(ticket_id, conn=conn)
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# State flips — the only real machine state (user-only by default)
# ---------------------------------------------------------------------------


def _require_state_power(role: str) -> None:
    """State flips are the user's call. Workers need Full Access Mode."""
    if role == ROLE_USER:
        return
    conn = db.connect()
    try:
        if not db.full_access_enabled(conn):
            raise PermissionError(
                "State changes (close/reopen) are user-only. "
                "Workers may comment and request work, but flipping state "
                "requires `rect full-access on`."
            )
    finally:
        conn.close()


def _flip_state(
    ticket_id: int,
    role: str,
    new_state: str,
    action: str,
    body: str,
) -> dict[str, Any]:
    _require_state_power(role)
    if new_state not in VALID_STATES:
        raise ValueError(f"Invalid state: {new_state!r}")
    conn = db.connect()
    try:
        row = conn.execute("SELECT * FROM tickets WHERE id = ?", (ticket_id,)).fetchone()
        if row is None:
            raise KeyError(f"Ticket not found: {ticket_no(ticket_id)}")
        _insert_message(conn, ticket_id, role, body, action=action)
        conn.execute(
            "UPDATE tickets SET state = ?, updated_at = ? WHERE id = ?",
            (new_state, _now(), ticket_id),
        )
        conn.commit()
        return get_ticket(ticket_id, conn=conn)
    finally:
        conn.close()


def close(ticket_id: int, role: str = ROLE_USER, body: str = "✅ closed") -> dict[str, Any]:
    """Close → Done. Removes the ticket from your eyes."""
    return _flip_state(ticket_id, role, STATE_DONE, ACTION_CLOSE, body)


def reopen(ticket_id: int, role: str = ROLE_USER, body: str = "↩ reopened") -> dict[str, Any]:
    """Reopen a done ticket → Active."""
    return _flip_state(ticket_id, role, STATE_ACTIVE, ACTION_REOPEN, body)


# ---------------------------------------------------------------------------
# Destructive ops (Level 2 / Full Access)
# ---------------------------------------------------------------------------


def _require_destructive(role: str) -> None:
    """Destructive ops: user always allowed; workers need Full Access Mode."""
    if role == ROLE_USER:
        return
    conn = db.connect()
    try:
        if not db.full_access_enabled(conn):
            raise PermissionError(
                "Full Access Mode is off — destructive actions are user-only. "
                "Workers need `rect full-access on`."
            )
    finally:
        conn.close()


def delete_ticket(ticket_id: int, role: str = ROLE_USER) -> None:
    _require_destructive(role)
    conn = db.connect()
    try:
        row = conn.execute("SELECT id FROM tickets WHERE id = ?", (ticket_id,)).fetchone()
        if row is None:
            raise KeyError(f"Ticket not found: {ticket_no(ticket_id)}")
        conn.execute("DELETE FROM tickets WHERE id = ?", (ticket_id,))
        conn.commit()
    finally:
        conn.close()


def delete_message(message_id: int, role: str = ROLE_USER) -> None:
    _require_destructive(role)
    conn = db.connect()
    try:
        cur = conn.execute("DELETE FROM messages WHERE id = ?", (message_id,))
        if cur.rowcount == 0:
            raise KeyError(f"Message not found: {message_id}")
        conn.commit()
    finally:
        conn.close()


def update_ticket(
    ticket_id: int,
    title: str | None = None,
    status: str | None = None,
    role: str = ROLE_USER,
) -> dict[str, Any]:
    """Edit a ticket. Status is free (anyone may set it). Title is user
    text — changing it is destructive, so workers need Full Access Mode."""
    conn = db.connect()
    try:
        row = conn.execute("SELECT * FROM tickets WHERE id = ?", (ticket_id,)).fetchone()
        if row is None:
            raise KeyError(f"Ticket not found: {ticket_no(ticket_id)}")

        if title is not None:
            _require_destructive(role)
            if not title.strip():
                raise ValueError("Title cannot be empty.")
            conn.execute(
                "UPDATE tickets SET title = ?, updated_at = ? WHERE id = ?",
                (title.strip(), _now(), ticket_id),
            )

        if status is not None and status != row["status"]:
            # status is free — anyone can set it; log it as a message event
            _insert_message(conn, ticket_id, role, f"status → {status}", status_after=status)
            conn.execute(
                "UPDATE tickets SET status = ?, updated_at = ? WHERE id = ?",
                (status, _now(), ticket_id),
            )

        conn.commit()
        return get_ticket(ticket_id, conn=conn)
    finally:
        conn.close()
