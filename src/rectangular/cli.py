"""Rectangular CLI — the rect command.

UI is first; the CLI exists for agents and orchestrator scripts.
CLI messages default to role=system (the machine talking). Pass --as user
to speak as the user. The UI always speaks as user.

Messages are pure (always allowed). State flips (close/reopen) are user-only;
workers need Full Access Mode.
"""

from __future__ import annotations

import json
import os
import socket
import sys
import webbrowser
from typing import Any

import click
from rich.console import Console
from rich.table import Table

from . import __version__, core, db

console = Console()

_UI_STATE_FILE = "ui.json"


def _running_ui() -> str | None:
    """Return the URL of an already-running rect UI for this folder, if any.

    Truth = the socket answers on the recorded port. No psutil required.
    """
    state = db.rect_dir() / _UI_STATE_FILE
    if not state.exists():
        return None
    try:
        data = json.loads(state.read_text(encoding="utf-8"))
        port = int(data.get("port", 0))
    except (ValueError, OSError, KeyError):
        return None
    if port <= 0:
        return None
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.3)
        try:
            s.connect(("127.0.0.1", port))
        except OSError:
            return None
    return f"http://localhost:{port}"


def _write_ui_state(pid: int, port: int) -> None:
    d = db.ensure_rect_dir()
    (d / _UI_STATE_FILE).write_text(
        json.dumps({"pid": pid, "port": port}), encoding="utf-8"
    )


def _clear_ui_state(pid: int) -> None:
    state = db.rect_dir() / _UI_STATE_FILE
    try:
        data = json.loads(state.read_text(encoding="utf-8"))
        if int(data.get("pid", -1)) == pid:
            state.unlink()
    except (OSError, ValueError):
        pass


@click.group()
@click.version_option(__version__, prog_name="rect")
def main() -> None:
    """Chat-first, UI-first task system. Run `rect ui` to open the UI."""


@main.command()
@click.option("--port", type=int, default=0, help="Port to bind (0 = any free port)")
@click.option("--no-browser", is_flag=True, help="Don't open the browser automatically")
def ui(port: int, no_browser: bool) -> None:
    """Serve the UI. Creates the DB on first run. Takes any free port."""
    from .web.app import app

    running = _running_ui()
    if running:
        console.print(f"📋 Rectangular already serving at {running}")
        if not no_browser:
            webbrowser.open(running)
        return

    if port == 0:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("", 0))
            port = s.getsockname()[1]

    url = f"http://localhost:{port}"
    _write_ui_state(os.getpid(), port)
    console.print(f"📋 Rectangular serving at {url}")
    if not no_browser:
        webbrowser.open(url)

    import uvicorn

    try:
        uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")
    finally:
        _clear_ui_state(os.getpid())


def _role_option(f: Any) -> Any:
    return click.option(
        "--as",
        "role",
        type=click.Choice([core.ROLE_USER, core.ROLE_ASSISTANT, core.ROLE_SYSTEM]),
        default=core.ROLE_SYSTEM,
        help="Message role. Default: system (CLI = machine). Use --as user to speak as the user.",
    )(f)


def _name_option(f: Any) -> Any:
    return click.option(
        "--name",
        help="Optional sender name (which worker/agent) — for future multi-collab.",
    )(f)


def _fmt_time(iso: str) -> str:
    return iso[11:19] if len(iso) >= 19 else iso


def _render_peek(tickets: list[dict[str, Any]]) -> None:
    if not tickets:
        console.print("  (no active tickets)")
        return
    for t in tickets:
        review = " 👁" if t["needs_review"] else ""
        console.print(
            f"  [{t['no']}] {t['status'] or '-':<12} {t['title']}{review}"
        )


def _render_day_group(tickets: list[dict[str, Any]]) -> None:
    groups = core.group_by_day(tickets)
    for g in groups:
        console.print(f"\n[bold]{g['label']}[/bold]")
        for t in g["tickets"]:
            review = " 👁" if t["needs_review"] else ""
            console.print(f"  [{t['no']}] {t['status'] or '-':<12} {t['title']}{review}")


def _role_style(role: str) -> str:
    return {
        core.ROLE_USER: "[bold cyan]user[/bold cyan]",
        core.ROLE_ASSISTANT: "[bold magenta]assistant[/bold magenta]",
        core.ROLE_SYSTEM: "[bold yellow]system[/bold yellow]",
    }.get(role, f"[bold]{role}[/bold]")


def _render_thread(t: dict[str, Any]) -> None:
    console.print(f"\n[bold]{t['no']}[/bold] — {t['title']}")
    console.print(f"  state: {t['state']}  status: {t['status'] or '-'}  "
                  f"needs_review: {'yes' if t['needs_review'] else 'no'}")
    console.print("  ---")
    for m in t["messages"]:
        who = _role_style(m["role"])
        sender = f" ({m['name']})" if m.get("name") else ""
        extra = ""
        if m["status_after"]:
            extra += f" → status: {m['status_after']}"
        if m["action"]:
            extra += f" → {m['action']}"
        console.print(f"  {who}{sender} {_fmt_time(m['created_at'])}:{extra}")
        console.print(f"    {m['body']}")
    console.print("")


@main.command()
@click.option("--json", "json_output", is_flag=True, help="Output as JSON")
def status(json_output: bool) -> None:
    """Active count + quick peek at first 10 (headers + statuses)."""
    s = core.status_summary()
    if json_output:
        click.echo(json.dumps(s, indent=2, default=str))
        return
    console.print(f"Active: {s['active_count']}   Done: {s['done_count']}")
    if s["needs_review"]:
        console.print(f"👁 needs your eyes: {len(s['needs_review'])}")
    console.print("\n[bold]LATEST[/bold]")
    _render_peek(s["peek"])


@main.command()
@click.option("--done", is_flag=True, help="List done tickets instead of active")
@click.option("--json", "json_output", is_flag=True, help="Output as JSON")
def list_cmd(done: bool, json_output: bool) -> None:
    """Sequential list, day-grouped, newest first (needs-review on top)."""
    tickets = core.list_tickets(done=done)
    if json_output:
        click.echo(json.dumps(core.group_by_day(tickets), indent=2, default=str))
        return
    if not tickets:
        console.print("(none)")
        return
    _render_day_group(tickets)


@main.command("read")
@click.argument("ref")
@click.option("--json", "json_output", is_flag=True, help="Output as JSON")
def read_cmd(ref: str, json_output: bool) -> None:
    """Full chat thread of one ticket."""
    try:
        t = core.get_ticket(core.parse_ticket_no(ref))
    except (KeyError, ValueError) as e:
        console.print(str(e), style="red")
        sys.exit(1)
    if json_output:
        click.echo(json.dumps(t, indent=2, default=str))
        return
    _render_thread(t)


@main.command("search")
@click.argument("query")
@click.option("--limit", type=int, default=20, help="Max results (default 20)")
@click.option("--json", "json_output", is_flag=True, help="Output as JSON")
def search_cmd(query: str, limit: int, json_output: bool) -> None:
    """Fuzzy full-text search across titles + comments (active and done)."""
    try:
        tickets = core.search(query, limit=limit)
    except ValueError as e:
        console.print(str(e), style="red")
        sys.exit(1)
    if json_output:
        click.echo(json.dumps(tickets, indent=2, default=str))
        return
    if not tickets:
        console.print("(no matches)")
        return
    for t in tickets:
        review = " 👁" if t["needs_review"] else ""
        state = "done" if t["state"] == core.STATE_DONE else "active"
        console.print(
            f"  [{t['no']}] ({state:<6}) {t['status'] or '-':<12} {t['title']}{review}"
        )


@main.command()
@click.argument("title")
@_role_option
@_name_option
def add(title: str, role: str, name: str | None) -> None:
    """Create a ticket."""
    try:
        t = core.add_ticket(title, created_by=role)
    except ValueError as e:
        console.print(str(e), style="red")
        sys.exit(1)
    console.print(f"Created {t['no']}: {t['title']}")


@main.command()
@click.argument("ref")
@click.argument("body")
@click.option("--status", help="Set status atomically with this message")
@_role_option
@_name_option
def comment(ref: str, body: str, status: str | None, role: str, name: str | None) -> None:
    """Append a chat message (pure primitive — always allowed).

    Role defaults to system (the machine talking). --as user to speak as you.
    Never touches state. Close/reopen are separate commands.
    """
    try:
        tid = core.parse_ticket_no(ref)
        t = core.message(tid, role=role, body=body, name=name, status=status)
    except (KeyError, ValueError, PermissionError) as e:
        console.print(str(e), style="red")
        sys.exit(1)
    console.print(f"Message sent on {t['no']}")


@main.command()
@click.argument("ref")
@click.argument("new_status")
@_role_option
def update(ref: str, new_status: str, role: str) -> None:
    """Shorthand: set status (free string) with a log message."""
    try:
        tid = core.parse_ticket_no(ref)
        t = core.message(tid, role=role, body=f"status → {new_status}",
                         status=new_status)
    except (KeyError, ValueError, PermissionError) as e:
        console.print(str(e), style="red")
        sys.exit(1)
    console.print(f"{t['no']} status: {t['status']}")


@main.command()
@click.argument("ref")
@_role_option
def close(ref: str, role: str) -> None:
    """Close a ticket → Done (removes it from your eyes).

    User only; workers need Full Access Mode.
    """
    try:
        tid = core.parse_ticket_no(ref)
        t = core.close(tid, role=role)
    except (KeyError, ValueError, PermissionError) as e:
        console.print(str(e), style="red")
        sys.exit(1)
    console.print(f"{t['no']} closed → Done")


@main.command()
@click.argument("ref")
@_role_option
def reopen(ref: str, role: str) -> None:
    """Reopen a done ticket → Active. User only; workers need Full Access."""
    try:
        tid = core.parse_ticket_no(ref)
        t = core.reopen(tid, role=role)
    except (KeyError, ValueError, PermissionError) as e:
        console.print(str(e), style="red")
        sys.exit(1)
    console.print(f"{t['no']} reopened → Active")


@main.command()
@click.argument("action", type=click.Choice(["on", "off"]))
def full_access(action: str) -> None:
    """Toggle Full Access Mode (workers get state/destructive powers)."""
    conn = db.connect()
    try:
        db.set_setting(conn, "full_access", "1" if action == "on" else "0")
    finally:
        conn.close()
    console.print(f"full_access = {action}")


@main.command()
@click.argument("ref")
@_role_option
def delete(ref: str, role: str) -> None:
    """Delete a ticket (destructive — default user; workers need Full Access)."""
    try:
        core.delete_ticket(core.parse_ticket_no(ref), role=role)
    except (KeyError, ValueError, PermissionError) as e:
        console.print(str(e), style="red")
        sys.exit(1)
    console.print(f"Deleted {ref}")


@main.command()
@click.argument("ref")
@click.option("--title", help="New title (user text — workers need Full Access Mode)")
@click.option("--status", help="New status (free string, anyone may set)")
@_role_option
def edit(ref: str, title: str | None, status: str | None, role: str) -> None:
    """Edit a ticket: title (destructive) and/or status (free)."""
    if title is None and status is None:
        console.print("Nothing to edit — pass --title and/or --status", style="red")
        sys.exit(1)
    try:
        t = core.update_ticket(core.parse_ticket_no(ref), title=title,
                               status=status, role=role)
    except (KeyError, ValueError, PermissionError) as e:
        console.print(str(e), style="red")
        sys.exit(1)
    console.print(f"Updated {t['no']}: {t['title']}")
