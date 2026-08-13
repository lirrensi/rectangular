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
    assert s["review_count"] == 1
    assert len(s["needs_review"]) == 1


def test_list_tickets_review_filter_only_needs_review():
    core.add_ticket("one")
    core.message(1, core.ROLE_ASSISTANT, "check me")  # needs review
    core.add_ticket("two")  # empty, no review needed
    core.add_ticket("three")
    core.message(3, core.ROLE_ASSISTANT, "hi")
    core.message(3, core.ROLE_USER, "thanks")  # user last → not needs review
    review = core.list_tickets(review=True)
    assert [t["no"] for t in review] == ["T-0001"]
    assert review[0]["needs_review"] is True


def test_list_tickets_review_never_includes_done():
    core.add_ticket("one")
    core.message(1, core.ROLE_ASSISTANT, "check me")
    core.close(1, role="user")
    assert core.list_tickets(review=True) == []


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
# Claims — soft lock: "I'm on this, don't grab it."
# ---------------------------------------------------------------------------


def test_claim_sets_claimant_and_audits():
    core.add_ticket("one")
    t = core.claim(1, role="assistant", name="arri")
    assert t["claimed_by"] == "arri"
    assert t["claimed_at"] is not None
    assert t["messages"][-1]["action"] == core.ACTION_CLAIM
    assert "arri" in t["messages"][-1]["body"]


def test_claim_requires_distinct_claimant():
    core.add_ticket("one")
    core.claim(1, role="assistant", name="arri")
    with pytest.raises(PermissionError):
        core.claim(1, role="assistant", name="other")


def test_claim_same_claimant_is_idempotent():
    core.add_ticket("one")
    core.claim(1, role="assistant", name="arri")
    t = core.claim(1, role="assistant", name="arri")  # same name → allowed
    assert t["claimed_by"] == "arri"


def test_unclaim_by_claimant():
    core.add_ticket("one")
    core.claim(1, role="assistant", name="arri")
    t = core.unclaim(1, role="assistant", name="arri")
    assert t["claimed_by"] is None
    assert t["messages"][-1]["action"] == core.ACTION_UNCLAIM


def test_unclaim_by_user_force_release():
    core.add_ticket("one")
    core.claim(1, role="assistant", name="arri")
    t = core.unclaim(1, role="user")  # user can always force-release
    assert t["claimed_by"] is None


def test_unclaim_by_other_worker_denied():
    core.add_ticket("one")
    core.claim(1, role="assistant", name="arri")
    with pytest.raises(PermissionError):
        core.unclaim(1, role="assistant", name="intruder")


def test_unclaim_when_not_claimed_is_noop():
    core.add_ticket("one")
    t = core.unclaim(1, role="user")
    assert t["claimed_by"] is None


def test_close_auto_releases_claim():
    core.add_ticket("one")
    core.claim(1, role="assistant", name="arri")
    t = core.close(1, role="user")
    assert t["state"] == "done"
    assert t["claimed_by"] is None


def test_claim_is_soft_lock_comments_still_flow():
    core.add_ticket("one")
    core.claim(1, role="assistant", name="arri")
    # soft lock: another worker may still comment (signal, not a wall)
    core.message(1, role="assistant", name="other", body="just poking")
    msgs = core.get_ticket(1)["messages"]
    assert msgs[-1]["name"] == "other"


# ---------------------------------------------------------------------------
# Search: FTS5 trigram, born in the schema (no migration ladder — baby app).
# ---------------------------------------------------------------------------


def test_search_matches_title():
    core.add_ticket("quick search in the UI")
    core.add_ticket("happy dancing meow")
    hits = core.search("search")
    assert [h["no"] for h in hits] == ["T-0001"]


def test_search_matches_comment_body():
    t = core.add_ticket("some title")
    core.message(t["id"], role="user", body="the header or comment has this word")
    hits = core.search("dragonfruit")
    assert hits == []  # word is in neither title nor comment
    hits = core.search("header")
    assert [h["no"] for h in hits] == ["T-0001"]  # matched via comment body


def test_search_comment_body_and_title():
    t = core.add_ticket("dragonfruit smoothie")
    core.message(t["id"], role="user", body="taste the rainbow")
    hits = core.search("rainbow")
    assert [h["no"] for h in hits] == ["T-0001"]
    hits = core.search("dragonfruit")
    assert [h["no"] for h in hits] == ["T-0001"]


def test_search_is_fuzzy_prefix():
    core.add_ticket("quick search in the UI")
    core.add_ticket("happy dancing meow")
    hits = core.search("quic")
    assert [h["no"] for h in hits] == ["T-0001"]


def test_search_matches_across_done_tickets():
    t = core.add_ticket("archive me later")
    core.close(t["id"])
    hits = core.search("archive")
    assert [h["no"] for h in hits] == ["T-0001"]
    assert hits[0]["state"] == "done"


def test_search_no_match_returns_empty():
    core.add_ticket("alpha beta")
    assert core.search("omega") == []


def test_search_short_query_uses_like_fallback():
    core.add_ticket("meow mix")
    # trigram needs >=3 chars; short terms must fall back to LIKE
    hits = core.search("me")
    assert [h["no"] for h in hits] == ["T-0001"]


def test_search_rebuilds_after_message_delete():
    t = core.add_ticket("privacy")
    core.message(t["id"], role="user", body="sensitive secret word")
    assert core.search("secret")
    # delete the only message → FTS row body becomes empty via trigger
    msgs = core.get_ticket(t["id"])["messages"]
    core.delete_message(msgs[0]["id"], role="user")
    assert core.search("secret") == []


def test_search_reflects_title_rename():
    t = core.add_ticket("old name")
    core.update_ticket(t["id"], title="new title", role="user")
    assert core.search("new")[0]["no"] == "T-0001"
    assert core.search("old") == []


def test_search_returns_rich_ticket_shape():
    t = core.add_ticket("shape check")
    core.message(t["id"], role="assistant", body="agent reply")
    hit = core.search("shape")[0]
    assert hit["no"] == "T-0001"
    assert hit["state"] == "active"
    assert hit["title"] == "shape check"
    assert hit["needs_review"] is True  # last message from a worker


# ---------------------------------------------------------------------------
# RECTANGULAR LAW: no curves. border-radius is forbidden.
# ---------------------------------------------------------------------------


def test_no_border_radius_in_ui():
    """The app is named RECTANGULAR. The UI must be all angles, forever."""
    from pathlib import Path

    html = (Path(__file__).parent.parent / "src" / "rectangular" / "web" / "index.html").read_text(encoding="utf-8")
    assert "border-radius" not in html, "border-radius is FORBIDDEN in Rectangular. Angles only."
    assert "borderRadius" not in html, "borderRadius (inline style) is FORBIDDEN in Rectangular."
