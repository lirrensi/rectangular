"""Core operations for Rectangular.

A ticket IS a chat between the user and workers. Each message has:
  role       user | assistant | system   (UI=user, CLI=system by default)
  name       optional — which worker/agent, for future multi-collab
  body       the text
  time       created_at
Status changes and approval actions live as message events, so the thread
always tells the whole story.
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
APPROVE = "approve"
UNAPPROVE = "unapprove"


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
            "INSERT INTO tickets (title, status, created_by, created_at, updated_at) "
            "VALUES (?, '', ?, ?, ?)",
            (title.strip(), created_by, now, now),
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
        return t
    finally:
        if own:
            conn.close()


def _messages(conn: sqlite3.Connection, ticket_id: int) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT * FROM messages WHERE ticket_id = ? ORDER BY id ASC", (ticket_id,)
    ).fetchall()
    return [dict(r) for r in rows]


def list_tickets(done: bool = False, limit: int | None = None) -> list[dict[str, Any]]:
    """Sequential list. Active by default, Done when done=True.

    Ordered newest first; day-grouped by created_at date.
    """
    conn = db.connect()
    try:
        rows = conn.execute(
            "SELECT * FROM tickets WHERE approved = ? ORDER BY id DESC",
            (1 if done else 0,),
        ).fetchall()
        tickets = [_ticket_row(r) for r in rows]
        if limit is not None:
            tickets = tickets[:limit]
        return tickets
    finally:
        conn.close()


def group_by_day(tickets: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Group a ticket list into [{day, label, tickets:[...]}], newest day first."""
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
        result.append({"day": day, "label": label, "tickets": groups[day]})
    return result


def status_summary() -> dict[str, Any]:
    active = list_tickets(done=False)
    done = list_tickets(done=True)
    return {
        "active_count": len(active),
        "done_count": len(done),
        "pending_approval": [
            t for t in active if t.get("pending_approval")
        ],
        "peek": active[:10],
    }


# ---------------------------------------------------------------------------
# Messages — the chat
# ---------------------------------------------------------------------------


def _insert_message(
    conn: sqlite3.Connection,
    ticket_id: int,
    role: str,
    body: str,
    name: str | None = None,
    status_after: str | None = None,
    approval_action: str | None = None,
) -> None:
    conn.execute(
        "INSERT INTO messages (ticket_id, role, name, body, status_after, approval_action, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (ticket_id, role, name, body, status_after, approval_action, _now()),
    )


def message(
    ticket_id: int,
    role: str,
    body: str,
    name: str | None = None,
    status: str | None = None,
    approve: bool | None = None,
) -> dict[str, Any]:
    """Append a chat message. Optionally set status and/or approval atomically."""
    if role not in VALID_ROLES:
        raise ValueError(f"role must be one of {sorted(VALID_ROLES)}, got {role!r}")
    if body is None or not body.strip():
        raise ValueError("Message body cannot be empty.")
    if approve is True and role != ROLE_USER:
        raise PermissionError("Only the user can approve.")

    conn = db.connect()
    try:
        row = conn.execute("SELECT * FROM tickets WHERE id = ?", (ticket_id,)).fetchone()
        if row is None:
            raise KeyError(f"Ticket not found: {ticket_no(ticket_id)}")

        approval_action = None
        if approve is True:
            approval_action = APPROVE
        elif approve is False:
            approval_action = UNAPPROVE

        _insert_message(
            conn,
            ticket_id,
            role,
            body.strip(),
            name=name,
            status_after=status,
            approval_action=approval_action,
        )

        new_status = status if status is not None else row["status"]
        new_approved = 1 if approve is True else (0 if approve is False else row["approved"])
        # approving clears pending; any user comment also clears pending,
        # because the ball is back in the user's court.
        new_pending = 0 if approve is not None or role == ROLE_USER else row["pending_approval"]

        conn.execute(
            "UPDATE tickets SET status = ?, approved = ?, pending_approval = ?, updated_at = ? "
            "WHERE id = ?",
            (new_status, new_approved, new_pending, _now(), ticket_id),
        )
        conn.commit()
        return get_ticket(ticket_id, conn=conn)
    finally:
        conn.close()


def mark_pending(ticket_id: int, role: str) -> dict[str, Any]:
    """A worker (assistant/system) marks the ticket for user confirmation."""
    if role == ROLE_USER:
        raise PermissionError("Only workers mark tickets as pending approval.")
    conn = db.connect()
    try:
        conn.execute(
            "UPDATE tickets SET pending_approval = 1, updated_at = ? WHERE id = ?",
            (_now(), ticket_id),
        )
        conn.commit()
        return get_ticket(ticket_id, conn=conn)
    finally:
        conn.close()


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
