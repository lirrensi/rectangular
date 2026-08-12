# Rectangular — Spec

A chat-first, UI-first task system. One folder, one SQLite database, zero ceremony.

---

## 0. Non-negotiable philosophy

- **UI is fucking first.** You work with the UI, you look with the UI. The CLI exists for agents (and quick glances).
- **No status system.** Status is just a free string. Me or an agent sets it to whatever we want, whenever.
- **No dependency graph.** Want to link tickets? Write it in a comment.
- **No hand-written files.** The DB is the DB. Nobody edits YAML/JSON by hand. Agents only use the `rect` CLI.
- **Ticket is a chat.** One sequential thread per ticket. Worker writes their report, I write back. It's exactly this conversation — abstracted for many workers.

---

## 1. Storage

- Everything lives in `.rect/` at the repo root.
- Database: `.rect/rect.db` — SQLite.
- Created immediately on first `rect ui` (or on first insert). No `init` step, no ceremony.
- **The DB is committed to git.** The whole `.rect/` travels with the repo. Throw the folder into a VM and keep working.
- Agents COULD open the SQLite file directly and fuck it up. Nobody asks them to. The access model is enforced at the application layer (CLI/API), not as a security boundary. The UI is expected to surface anything bad happening.

## 2. Data model

### Ticket
| Field | Notes |
|---|---|
| `id` | short stable ID: `T-0001`, `T-0002`, ... auto-increment. Used by CLI to address tickets. |
| `title` | the original name — my text. Always shown. |
| `status` | arbitrary free string. Anyone can set it. |
| `approved` | 0/1. Done = approval passed. |
| `pending_approval` | 0/1. Agent marks this when they want my confirmation. |
| `created_by` | `user` or `agent` |
| `created_at`, `updated_at` | ISO timestamps |

### Message (the chat — a ticket IS a conversation)
| Field | Notes |
|---|---|
| `id` | auto |
| `ticket_id` | FK |
| `role` | **`user` \| `assistant` \| `system` — ALWAYS visible, non-negotiable.** UI writes `user` automatically. CLI writes `system` by default (the machine talking), `--as user` to speak as you, `--as assistant` for a worker. |
| `name` | optional — which worker/agent. Reserved for future multi-collab. |
| `body` | the text |
| `status_after` | optional — the new status this message sets |
| `approval_action` | optional — `approve` / `unapprove` when the message carries an approval action |
| `created_at` | time — every message carries a timestamp |

So every message has at minimum: **time, text, role.**

Status changes and approval are *events that live in the chat*. The message log is the audit trail.

## 3. Approval

- Agent can mark a ticket `pending approval`.
- **Only I clear it.** Click Approve = yes → ticket becomes `approved=1` → moves to Done tab.
- Type back / comment = no → ticket stays in Active.
- **Atomic in the UI:** one action is *write a comment + approve*, or *write a comment and don't approve*. Or just comment and communicate what's wrong.
- Done ticket commented on again → returns to Active.

## 4. Access model — 2 levels

### Level 1 — default (agents are staff)
Agents can:
- ✅ create tickets
- ✅ append comments
- ✅ change status (free string)
- ✅ mark `pending approval`

Agents CANNOT:
- ❌ delete or edit any comment (theirs or mine)
- ❌ edit my text / the title
- ❌ delete a ticket
- ❌ clear the approval gate

### Level 2 — Full Access Mode (toggle in UI)
Everything the UI can do, the CLI/agents can do too — delete tickets, edit comments, rename, mutate. Still gated by me flipping the switch.

## 5. UI

- `rect ui` — starts a server in this folder, takes **any free port**, prints the URL, opens the browser. I start clicking immediately.
- **Not Kanban.** A **sequential list**.
- Two tabs: **Active** / **Done**.
- **Day-grouped:** Today, then Yesterday, then the day before. Newest first within each day.
- Each row: ID + title (header) + status. Click → the chat thread.
- Comment box + Approve button in one atomic action.

## 6. CLI (for agents + quick glances)

```
rect ui                          # serve UI (any port, prints URL; reuses already-running server)
rect status                      # active count + peek at first 10 (headers + statuses)
rect list [--done] [--json]      # list active (default) or done
rect read T-0001                 # full chat thread
rect add "Title"                 # create ticket (role: default system from CLI, user from UI)
rect comment T-0001 "body"       # append chat message. role defaults to system.
rect comment T-0001 "body" --status "in review"   # message + status change, atomic
rect comment T-0001 "body" --as user              # speak as the user
rect comment T-0001 "body" --name worker-42       # optional sender name (multi-collab)
rect update T-0001 --status X    # shorthand status change
rect approve T-0001              # user only (speaks as user)
rect reopen T-0001               # unapprove (back to Active)
rect delete T-0001 [--as assistant]  # destructive — workers need `rect full-access on`
rect edit T-0001 --title Y --status Z [--as assistant]  # title is destructive; status is free for anyone
rect pending T-0001 "msg"        # worker marks pending approval (role: assistant)
rect full-access on|off          # toggle Level 2
```

Roles: **UI → `user` always. CLI → `system` by default**, `--as user` to act as the user, `--as assistant` for workers. `--name` is optional for multi-collab.

## 7. Explicitly NOT doing (from the abandoned agent-sommelier task system)

- 12 statuses / enum columns
- typed dependency graph (`blocks`, `parent`, `child`, ...)
- p0–p4 priority system
- Kanban boards
- `tasks init` ceremony
- YAML hand-editing / migration paths v1→v2
- symmetric actors ("no distinction between user and agent") — the old system's core mistake. Here: **my text is mine, agent text is theirs, always labeled.**
