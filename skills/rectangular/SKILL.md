---
name: rectangular
description: >-
  Use this skill whenever you are asked to work on a Rectangular ticket, or told
  "use skill rectangular" / "use the rect skill" together with a ticket number
  (e.g. T-0003), or when the user mentions the `rect` CLI, the task board, or
  wants you to check/comment/close a ticket. This is how you read the board and
  reply as a worker. Load it before touching any `rect` command.
---

# Rectangular — worker quickstart

Rectangular is a chat-first task board. A ticket IS a conversation between the
user and workers. Your job as a worker: read the ticket, do the work, reply on
the ticket. Do NOT flip state unless explicitly told to.

## The commands (the whole toolbox)

```bash
rect list                        # see active tickets, newest first, review-needing on top
rect list --done                 # see closed tickets
rect list --json                 # same, machine-readable
rect status                      # counts + quick peek
rect read T-0001                 # full chat thread of one ticket
rect add "Fix the thing"         # create a new ticket (you usually won't need this)
rect comment T-0001 "my reply" --as assistant --name "your-name"
                                 # reply on a ticket. Default role is 'system' (the machine).
                                 # Use --as assistant to speak as a worker.
rect comment T-0001 "text" --status "in progress"
                                 # reply AND set the free-text status in one shot
rect close T-0001                # state → done. USER-ONLY unless full-access on
rect reopen T-0001               # state → active. USER-ONLY unless full-access on
rect full-access on|off          # enables agents to close/reopen/delete
rect search "fuzzy term"         # full-text search across titles + comments
                                 # (active AND done). Fuzzy: 'quic' finds 'quick'.
                                 # Include a ticket ref (T-XXXX) if you know it.
```

## The one rule that matters

- **Messages (comment) are always allowed.** Reply freely.
- **State flips (close/reopen) and destructive ops (delete) are user-only**
  unless Full Access Mode is on (`rect full-access on`). If you need to move a
  ticket and you lack permission, say so instead of failing silently.

## Typical worker loop

1. `rect list` — find your ticket(s). If given a number like T-0003, use it.
2. `rect read T-0003` — read the full thread. Context is everything.
3. Do the work.
4. `rect comment T-0003 "done — here's what I did" --as assistant --name "<you>"`
   This flags the ticket as needing the user's review.

That's it. Keep it simple, keep it on the board.
