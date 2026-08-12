"""FastAPI backend + single-page Alpine UI for Rectangular.

The UI is the first-class interface. UI messages are always role=user.
Messages from workers arrive via CLI/orchestrator with role=assistant/system.

State model: active | done. 'needs_review' is derived (last message from worker).
Close/reopen are user-only state flips.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from .. import core, db

app = FastAPI(title="Rectangular")


class AddTicketBody(BaseModel):
    title: str
    created_by: str = "user"


class CommentBody(BaseModel):
    body: str
    role: str = "user"
    name: str | None = None
    status: str | None = None


class UpdateBody(BaseModel):
    status: str


class EditBody(BaseModel):
    title: str | None = None
    status: str | None = None
    role: str = "user"


class FullAccessBody(BaseModel):
    value: bool


def _get(ref: str) -> int:
    try:
        return core.parse_ticket_no(ref)
    except ValueError:
        raise HTTPException(status_code=404, detail=f"Bad ticket ref: {ref!r}")


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return (Path(__file__).parent / "index.html").read_text(encoding="utf-8")


@app.get("/favicon.ico", response_class=HTMLResponse)
def favicon() -> str:
    """Square purple rectangle — the brand, literally."""
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16">'
        '<rect width="16" height="16" fill="#8b5cf6"/></svg>'
    )


@app.get("/alpine.min.js", response_class=HTMLResponse)
def alpine() -> str:
    """Vendored Alpine build — works with no internet/CDN access."""
    return (Path(__file__).parent / "alpine.min.js").read_text(encoding="utf-8")


@app.get("/api/status")
def api_status() -> dict[str, Any]:
    s = core.status_summary()
    s["cwd"] = str(Path.cwd())
    return s


@app.get("/api/tickets")
def api_list(done: bool = False, review: bool = False) -> list[dict[str, Any]]:
    return core.group_by_day(core.list_tickets(done=done, review=review))


@app.get("/api/tickets/{ref}")
def api_get(ref: str) -> dict[str, Any]:
    return core.get_ticket(_get(ref))


@app.post("/api/tickets", status_code=201)
def api_add(body: AddTicketBody) -> dict[str, Any]:
    try:
        return core.add_ticket(body.title, created_by=body.created_by)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/tickets/{ref}/comments", status_code=201)
def api_comment(ref: str, body: CommentBody) -> dict[str, Any]:
    tid = _get(ref)
    try:
        return core.message(
            tid,
            role=body.role,
            body=body.body,
            name=body.name,
            status=body.status,
        )
    except (KeyError, ValueError, PermissionError) as e:
        raise HTTPException(status_code=400 if isinstance(e, (ValueError, PermissionError)) else 404, detail=str(e))


class CloseBody(BaseModel):
    body: str | None = None
    name: str | None = None


@app.post("/api/tickets/{ref}/close", status_code=200)
def api_close(ref: str, body: CloseBody | None = None) -> dict[str, Any]:
    tid = _get(ref)
    try:
        if body and body.body and body.body.strip():
            core.message(tid, role="user", body=body.body.strip(), name=body.name)
        return core.close(tid, role="user", name=body.name if body else None)
    except (KeyError, ValueError, PermissionError) as e:
        raise HTTPException(status_code=400 if isinstance(e, (ValueError, PermissionError)) else 404, detail=str(e))


@app.post("/api/tickets/{ref}/reopen", status_code=200)
def api_reopen(ref: str) -> dict[str, Any]:
    tid = _get(ref)
    try:
        return core.reopen(tid, role="user")
    except (KeyError, ValueError, PermissionError) as e:
        raise HTTPException(status_code=400 if isinstance(e, (ValueError, PermissionError)) else 404, detail=str(e))


@app.put("/api/tickets/{ref}/status")
def api_status_update(ref: str, body: UpdateBody) -> dict[str, Any]:
    tid = _get(ref)
    try:
        return core.message(tid, role="user", body=f"status → {body.status}", status=body.status)
    except (KeyError, ValueError, PermissionError) as e:
        raise HTTPException(status_code=400 if isinstance(e, (ValueError, PermissionError)) else 404, detail=str(e))


@app.patch("/api/tickets/{ref}")
def api_edit(ref: str, body: EditBody) -> dict[str, Any]:
    tid = _get(ref)
    try:
        return core.update_ticket(tid, title=body.title, status=body.status, role=body.role)
    except (KeyError, ValueError, PermissionError) as e:
        status_code = 404 if isinstance(e, KeyError) else (403 if isinstance(e, PermissionError) else 400)
        raise HTTPException(status_code=status_code, detail=str(e))


@app.delete("/api/tickets/{ref}", status_code=204)
def api_delete(ref: str, role: str = "user") -> None:
    tid = _get(ref)
    try:
        core.delete_ticket(tid, role=role)
    except (KeyError, PermissionError) as e:
        status_code = 404 if isinstance(e, KeyError) else 403
        raise HTTPException(status_code=status_code, detail=str(e))


@app.delete("/api/tickets/{ref}/messages/{message_id}", status_code=204)
def api_delete_message(ref: str, message_id: int, role: str = "user") -> None:
    tid = _get(ref)
    # verify message belongs to the ticket
    conn = db.connect()
    try:
        row = conn.execute(
            "SELECT id FROM messages WHERE id = ? AND ticket_id = ?",
            (message_id, tid),
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        raise HTTPException(status_code=404, detail=f"Message not found: {message_id}")
    try:
        core.delete_message(message_id, role=role)
    except (KeyError, PermissionError) as e:
        status_code = 404 if isinstance(e, KeyError) else 403
        raise HTTPException(status_code=status_code, detail=str(e))


@app.get("/api/settings")
def api_settings() -> dict[str, Any]:
    conn = db.connect()
    try:
        return {"full_access": db.full_access_enabled(conn)}
    finally:
        conn.close()


@app.put("/api/settings/full_access")
def api_full_access(body: FullAccessBody) -> dict[str, Any]:
    conn = db.connect()
    try:
        db.set_setting(conn, "full_access", "1" if body.value else "0")
        return {"full_access": body.value}
    finally:
        conn.close()
