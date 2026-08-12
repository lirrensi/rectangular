# 📐 Rectangular

**A chat-first, UI-first task system.** One folder, one SQLite DB, zero ceremony.

A ticket is a chat between you and your workers (agents). You read, you reply, you close. That's it.

- Mom I want Linear
- We have Linear at home
- [basically this]

---

## Install

```bash
uv tool install "git+https://github.com/lirrensi/rectangular"
```

That's it. The whole app — CLI + UI — installs as one command. No database setup, no server config, no init.

> Needs [uv](https://github.com/astral-sh/uv). Python 3.10+.

---

## Quick start

```bash
rect ui        # opens the UI. DB is created automatically on first run.
rect status    # quick peek from the terminal: counts + first 10
rect add "Fix login bug"
rect comment T-0001 "root cause found, working on it"
rect close T-0001
```

But generally, you don't touch the command line at all. You're expected to operate in the UI, first and foremost.

Everything lives in `.rect/` in the current folder — including the SQLite database. **Commit `.rect/` to git** and the whole task state travels with the repo. Throw the folder into a VM and keep working.

---

## The philosophy

1. **UI first.** You work with the UI. The CLI exists for agents and quick peeks.
2. **The ticket is a chat.** Worker writes, you write back. Every message has a role (`user` / `assistant` / `system`), a time, and text. Optional `name` for future multi-worker collab.
3. **Two states only:** `active` and `done`. No Kanban columns, no approval flags, no dependency graphs.
4. **Status is just a string.** Free text for navigation. Anyone can set it to anything.
5. **You are the gate.** The CLI can always comment, but only *you* close/reopen. Agents get destructive powers only in Full Access Mode (UI toggle).
6. **No ceremony.** No `init`, no hand-written files, no YAML wrangling. `rect ui` and go.
7. **No curved corners.** The app is called Rectangular. The UI is all angles, forever.

## How it's supposed to work

Inspired by [openai/symphony](https://github.com/openai/symphony)

1. You open the UI, add tickets, and read, modify, or leave comments.
2. You tell your orchestrator to look at the tickets, understand them, then dispatch workers (or the same process) via your scripts, however you like.
3. They finish and post their results. Then you read what they say, manually check whether the job was really done, add a comment if it's wrong so they can continue — or close it entirely.
4. Then you either tell your orchestrator to look again, let your script pick it up, or set it on cron — whatever fits. It's up to you how you orchestrate your agent flow.

The intention is that you're never fully decoupled from the work. Forget charts and harnesses: you operate on the board itself, and nothing else.

---

## CLI reference

```
rect ui                          # serve the UI (any free port; reuses a running instance)
rect status                      # active/done counts + peek at first 10
rect list [--done]               # day-grouped list, needs-review on top
rect read T-0001                 # full chat thread
rect add "Title"                 # create a ticket
rect comment T-0001 "text"       # append a message (role: system by default)
rect comment T-0001 "text" --as user
rect close T-0001                # state → done (user only)
rect reopen T-0001               # state → active (user only)
rect edit T-0001 --status X      # free-string status, anyone
rect full-access on|off          # let agents do destructive things
```

An active ticket whose last message is from a worker = **needs your eyes** — it floats to the top of the list with a 👁 dot. That's the whole review system.

---

## Works offline

The UI is a single page with Alpine vendored locally — no CDN, no internet required.

## Docs

Full behavior spec: [`docs/SPEC.md`](docs/SPEC.md)

## License

MIT.
