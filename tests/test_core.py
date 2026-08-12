"""Tests for Rectangular core.

Each test runs in its own tmp dir so .rect/rect.db is isolated.
The chat model: each message has role (user/assistant/system), optional name,
body (text), and created_at (time).
"""

from __future__ import annotations

import pytest

from rectangular import core, db


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)


# ---------------------------------------------------------------------------
# Tickets
# ---------------------------------------------------------------------------


def test_add_and_get_ticket():
    t = core.add_ticket("Fix login bug")
    assert t["no"] == "T-0001"
    assert t["title"] == "Fix login bug"
    assert t["status"] == ""
    assert t["approved"] == 0
    assert t["messages"] == []


def test_add_ticket_requires_title():
    with pytest.raises(ValueError):
        core.add_ticket("   ")


def test_ticket_ids_increment():
    a = core.add_ticket("one")
    b = core.add_ticket("two")
    assert a["no"] == "T-0001"
    assert b["no"] == "T-0002"


def test_get_missing_ticket_raises():
    with pytest.raises(KeyError):
        core.get_ticket(99)


def test_parse_ticket_no():
    assert core.parse_ticket_no("T-0003") == 3
    assert core.parse_ticket_no("t-3") == 3
    assert core.parse_ticket_no("7") == 7
    with pytest.raises(ValueError):
        core.parse_ticket_no("T-")


# ---------------------------------------------------------------------------
# The chat: role + time + text (+ optional name)
# ---------------------------------------------------------------------------


def test_message_has_role_time_text():
    core.add_ticket("one")
    core.message(1, core.ROLE_ASSISTANT, "report")
    t = core.get_ticket(1)
    assert len(t["messages"]) == 1
    m = t["messages"][0]
    assert m["role"] == "assistant"
    assert m["body"] == "report"
    assert m["created_at"]  # time
    assert m["name"] is None


def test_message_with_name():
    core.add_ticket("one")
    core.message(1, core.ROLE_ASSISTANT, "report", name="worker-42")
    m = core.get_ticket(1)["messages"][0]
    assert m["name"] == "worker-42"


def test_message_with_status_sets_status_atomically():
    core.add_ticket("one")
    t = core.message(1, core.ROLE_SYSTEM, "working", status="in-progress")
    assert t["status"] == "in-progress"
    assert t["messages"][-1]["status_after"] == "in-progress"


def test_message_requires_body():
    core.add_ticket("one")
    with pytest.raises(ValueError):
        core.message(1, core.ROLE_SYSTEM, "  ")


def test_invalid_role_rejected():
    core.add_ticket("one")
    with pytest.raises(ValueError):
        core.message(1, "boss", "hi")


def test_status_is_free_string():
    core.add_ticket("one")
    t = core.message(1, core.ROLE_SYSTEM, "who knows", status="🦄 wtf")
    assert t["status"] == "🦄 wtf"


# ---------------------------------------------------------------------------
# Approval
# ---------------------------------------------------------------------------


def test_assistant_cannot_approve():
    core.add_ticket("one")
    with pytest.raises(PermissionError):
        core.message(1, core.ROLE_ASSISTANT, "done", approve=True)


def test_system_cannot_approve():
    core.add_ticket("one")
    with pytest.raises(PermissionError):
        core.message(1, core.ROLE_SYSTEM, "done", approve=True)


def test_user_approve_moves_to_done():
    core.add_ticket("one")
    t = core.message(1, core.ROLE_USER, "approved", approve=True)
    assert t["approved"] == 1
    assert [x["id"] for x in core.list_tickets(done=False)] == []
    assert [x["id"] for x in core.list_tickets(done=True)] == [1]


def test_reopen_moves_back_to_active():
    core.add_ticket("one")
    core.message(1, core.ROLE_USER, "approved", approve=True)
    t = core.message(1, core.ROLE_USER, "oops", approve=False)
    assert t["approved"] == 0
    assert [x["id"] for x in core.list_tickets(done=False)] == [1]


def test_approval_leaves_trace():
    core.add_ticket("one")
    core.message(1, core.ROLE_USER, "approved", approve=True)
    t = core.get_ticket(1)
    assert t["messages"][-1]["approval_action"] == "approve"


def test_pending_approval_flow():
    core.add_ticket("one")
    t = core.mark_pending(1, role=core.ROLE_ASSISTANT)
    assert t["pending_approval"] == 1
    # user commenting clears the pending flag
    t = core.message(1, core.ROLE_USER, "looks bad", approve=False)
    assert t["pending_approval"] == 0
    assert t["approved"] == 0


def test_only_workers_mark_pending():
    core.add_ticket("one")
    with pytest.raises(PermissionError):
        core.mark_pending(1, role=core.ROLE_USER)


# ---------------------------------------------------------------------------
# Destructive ops + Full Access Mode
# ---------------------------------------------------------------------------


def test_user_can_delete():
    core.add_ticket("one")
    core.delete_ticket(1, role="user")
    with pytest.raises(KeyError):
        core.get_ticket(1)


def test_assistant_cannot_delete_without_full_access():
    core.add_ticket("one")
    with pytest.raises(PermissionError):
        core.delete_ticket(1, role="assistant")
    assert core.get_ticket(1)["no"] == "T-0001"


def test_assistant_can_delete_with_full_access():
    core.add_ticket("one")
    conn = db.connect()
    db.set_setting(conn, "full_access", "1")
    conn.close()
    core.delete_ticket(1, role="assistant")
    with pytest.raises(KeyError):
        core.get_ticket(1)


def test_full_access_off_again():
    core.add_ticket("one")
    conn = db.connect()
    db.set_setting(conn, "full_access", "1")
    db.set_setting(conn, "full_access", "0")
    conn.close()
    with pytest.raises(PermissionError):
        core.delete_ticket(1, role="assistant")


def test_assistant_cannot_edit_title_without_full_access():
    core.add_ticket("one")
    with pytest.raises(PermissionError):
        core.update_ticket(1, title="hijacked", role="assistant")


def test_user_can_edit_title():
    core.add_ticket("one")
    t = core.update_ticket(1, title="renamed", role="user")
    assert t["title"] == "renamed"


def test_worker_can_edit_status_without_full_access():
    core.add_ticket("one")
    t = core.update_ticket(1, status="done", role="assistant")
    assert t["status"] == "done"


def test_delete_message_permissions():
    core.add_ticket("one")
    core.message(1, core.ROLE_ASSISTANT, "slop")
    with pytest.raises(PermissionError):
        core.delete_message(1, role="assistant")
    core.delete_message(1, role="user")
    assert core.get_ticket(1)["messages"] == []


# ---------------------------------------------------------------------------
# Views
# ---------------------------------------------------------------------------


def test_list_orders_newest_first():
    core.add_ticket("first")
    core.add_ticket("second")
    tickets = core.list_tickets()
    assert tickets[0]["id"] == 2
    assert tickets[1]["id"] == 1


def test_group_by_day_labels_today():
    core.add_ticket("one")
    groups = core.group_by_day(core.list_tickets())
    assert groups[0]["label"] == "Today"
    assert [t["title"] for t in groups[0]["tickets"]] == ["one"]


def test_status_summary():
    core.add_ticket("one")
    core.add_ticket("two")
    s = core.status_summary()
    assert s["active_count"] == 2
    assert s["done_count"] == 0
    assert len(s["peek"]) == 2


def test_status_summary_peek_capped_at_ten():
    for i in range(15):
        core.add_ticket(f"task {i}")
    s = core.status_summary()
    assert len(s["peek"]) == 10


# ---------------------------------------------------------------------------
# Migration: legacy comments (author) → messages (role)
# ---------------------------------------------------------------------------


def test_migrate_legacy_comments_to_messages(tmp_path, monkeypatch):
    import sqlite3

    monkeypatch.chdir(tmp_path)
    # Build a legacy v1 DB by hand (comments table with author)
    (tmp_path / ".rect").mkdir()
    conn = sqlite3.connect(tmp_path / ".rect" / "rect.db")
    conn.execute(
        "CREATE TABLE tickets ("
        " id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL, status TEXT NOT NULL DEFAULT '',"
        " approved INTEGER NOT NULL DEFAULT 0, pending_approval INTEGER NOT NULL DEFAULT 0,"
        " created_by TEXT NOT NULL DEFAULT 'user', created_at TEXT NOT NULL, updated_at TEXT NOT NULL)"
    )
    conn.execute(
        "CREATE TABLE comments ("
        " id INTEGER PRIMARY KEY AUTOINCREMENT, ticket_id INTEGER NOT NULL,"
        " author TEXT NOT NULL, body TEXT NOT NULL, status_after TEXT,"
        " approval_action TEXT, created_at TEXT NOT NULL)"
    )
    conn.execute(
        "CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
    )
    conn.execute(
        "INSERT INTO tickets (id, title, status, created_at, updated_at) VALUES (1, 'old', '', 'x', 'x')"
    )
    conn.execute(
        "INSERT INTO comments (ticket_id, author, body, created_at) VALUES (1, 'agent', 'legacy msg', 'x')"
    )
    conn.commit()
    conn.close()

    t = core.get_ticket(1)
    assert len(t["messages"]) == 1
    m = t["messages"][0]
    assert m["role"] == "system"  # old 'agent' → system
    assert m["body"] == "legacy msg"
    assert m["name"] is None
