"""Tests for Rectangular core.

Each test runs in its own tmp dir so .rect/rect.db is isolated.

Model: a ticket IS a chat. Messages have role (user/assistant/system),
optional name, body (text), created_at (time). The only real state is
tickets.state = 'active' | 'done'. 'needs_review' is derived from the last
message being from a worker.
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
    assert t["state"] == "active"
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


def test_message_never_touches_state():
    core.add_ticket("one")
    t = core.message(1, core.ROLE_ASSISTANT, "just chatting")
    assert t["state"] == "active"


# ---------------------------------------------------------------------------
# State: active | done (user-only flips by default)
# ---------------------------------------------------------------------------


def test_user_close_moves_to_done():
    core.add_ticket("one")
    t = core.close(1, role="user")
    assert t["state"] == "done"
    assert [x["id"] for x in core.list_tickets(done=False)] == []
    assert [x["id"] for x in core.list_tickets(done=True)] == [1]


def test_reopen_moves_back_to_active():
    core.add_ticket("one")
    core.close(1, role="user")
    t = core.reopen(1, role="user")
    assert t["state"] == "active"
    assert [x["id"] for x in core.list_tickets(done=False)] == [1]


def test_worker_cannot_close_without_full_access():
    core.add_ticket("one")
    with pytest.raises(PermissionError):
        core.close(1, role="assistant")


def test_worker_cannot_reopen_without_full_access():
    core.add_ticket("one")
    core.close(1, role="user")
    with pytest.raises(PermissionError):
        core.reopen(1, role="assistant")


def test_worker_can_close_with_full_access():
    core.add_ticket("one")
    conn = db.connect()
    db.set_setting(conn, "full_access", "1")
    conn.close()
    t = core.close(1, role="assistant")
    assert t["state"] == "done"


def test_full_access_off_again():
    core.add_ticket("one")
    conn = db.connect()
    db.set_setting(conn, "full_access", "1")
    db.set_setting(conn, "full_access", "0")
    conn.close()
    with pytest.raises(PermissionError):
        core.close(1, role="assistant")


def test_close_leaves_trace():
    core.add_ticket("one")
    core.close(1, role="user")
    t = core.get_ticket(1)
    assert t["messages"][-1]["action"] == "close"


def test_reopen_leaves_trace():
    core.add_ticket("one")
    core.close(1, role="user")
    core.reopen(1, role="user")
    t = core.get_ticket(1)
    assert t["messages"][-1]["action"] == "reopen"


# ---------------------------------------------------------------------------
# Derived needs_review: last message from a worker
# ---------------------------------------------------------------------------


def test_needs_review_when_worker_last():
    core.add_ticket("one")
    core.message(1, core.ROLE_ASSISTANT, "please check")
    t = core.get_ticket(1)
    assert t["needs_review"] is True


def test_not_needs_review_when_user_last():
    core.add_ticket("one")
    core.message(1, core.ROLE_ASSISTANT, "please check")
    core.message(1, core.ROLE_USER, "looks wrong, fix it")
    t = core.get_ticket(1)
    assert t["needs_review"] is False


def test_empty_ticket_not_needs_review():
    core.add_ticket("one")
    t = core.get_ticket(1)
    assert t["needs_review"] is False


def test_status_summary_counts_needs_review():
    core.add_ticket("one")
    core.message(1, core.ROLE_ASSISTANT, "check me")
    core.add_ticket("two")
    s = core.status_summary()
    assert s["active_count"] == 2
    assert len(s["needs_review"]) == 1


def test_group_by_day_puts_needs_review_first():
    core.add_ticket("a")
    core.add_ticket("b")
    core.message(2, core.ROLE_ASSISTANT, "check me")  # T-0002 needs review
    groups = core.group_by_day(core.list_tickets())
    day = groups[0]["tickets"]
    assert day[0]["id"] == 2
    assert day[0]["needs_review"] is True


def test_status_summary_peek_capped_at_ten():
    for i in range(15):
        core.add_ticket(f"task {i}")
    s = core.status_summary()
    assert len(s["peek"]) == 10


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
# Migration: legacy v1 (comments+author) and v2 (approved flag) → v3
# ---------------------------------------------------------------------------


def test_migrate_legacy_comments_and_approved_to_state(tmp_path, monkeypatch):
    import sqlite3

    monkeypatch.chdir(tmp_path)
    # Build a legacy v2 DB by hand: comments table with author, tickets with approved
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
        "INSERT INTO tickets (id, title, status, approved, pending_approval, created_at, updated_at) "
        "VALUES (1, 'done one', '', 1, 0, 'x', 'x'), (2, 'active one', '', 0, 1, 'x', 'x')"
    )
    conn.execute(
        "INSERT INTO comments (ticket_id, author, body, approval_action, created_at) "
        "VALUES (1, 'agent', 'legacy msg', 'approve', 'x')"
    )
    conn.commit()
    conn.close()

    done_t = core.get_ticket(1)
    assert done_t["state"] == "done"
    assert done_t["messages"][0]["role"] == "system"
    assert done_t["messages"][0]["action"] == "close"  # 'approve' → 'close'

    active_t = core.get_ticket(2)
    assert active_t["state"] == "active"  # pending_approval no longer exists
    assert "approved" not in active_t
    assert "pending_approval" not in active_t


def test_schema_version_stamped_on_fresh_db(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    core.add_ticket("one")
    conn = db.connect()
    try:
        assert db.schema_version(conn) == db.SCHEMA_VERSION
        assert db.SCHEMA_VERSION == 3
    finally:
        conn.close()


def test_legacy_db_stamped_with_current_version(tmp_path, monkeypatch):
    import sqlite3

    monkeypatch.chdir(tmp_path)
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
        "INSERT INTO tickets (id, title, status, approved, created_at, updated_at) "
        "VALUES (1, 'old', '', 0, 'x', 'x')"
    )
    conn.commit()
    conn.close()

    core.add_ticket("new")  # triggers migration
    conn = db.connect()
    try:
        assert db.schema_version(conn) == db.SCHEMA_VERSION == 3
    finally:
        conn.close()

# ---------------------------------------------------------------------------
# RECTANGULAR LAW: no curves. border-radius is forbidden.
# ---------------------------------------------------------------------------


def test_no_border_radius_in_ui():
    """The app is named RECTANGULAR. The UI must be all angles, forever."""
    from pathlib import Path

    html = (Path(__file__).parent.parent / "src" / "rectangular" / "web" / "index.html").read_text(encoding="utf-8")
    assert "border-radius" not in html, "border-radius is FORBIDDEN in Rectangular. Angles only."
    assert "borderRadius" not in html, "borderRadius (inline style) is FORBIDDEN in Rectangular."
