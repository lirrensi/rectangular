---
summary: "Bootstrap-style unified input group pattern — any adjacent label/input/button combo reads as ONE element with multiple segments"
created: 2026-08-13
updated: 2026-08-13
memory_type: procedural
tags: [ui, design, bootstrap, input-group, rectangular]
status: active
confidence: certain
source: "User had to teach this the hard way over multiple rounds of UI iteration"
---

# Unified Input Group Pattern (Bootstrap `.input-group`)

## The Rule

When a label, input, or button sit next to each other visually, they form **ONE unified block** — not separate boxes glued together. Ship it the way Bootstrap shipped `.input-group` ten thousand years ago.

## Anatomy

```
┌──────┬─────────────────────────────┬────┐
│      │                             │    │   <- one outer border
│  S   │  status text or input       │ ＋ │
│      │                             │    │
└──────┴─────────────────────────────┴────┘
```

- **One outer border** around the entire group — input + label + button all share it.
- **Internal segments** (label, button) have `border: none` and `background: transparent` (or solid color fill — no own border).
- **Internal dividers** are a single `border-left` or `border-right: 1px solid var(--border)` on the right-side segment. NOT a border on BOTH sides.
- Segments are full-height via `align-items: stretch` on the wrapper.
- **Square corners** — RECTANGULAR LAW: no `border-radius`.

## CSS Template

```css
.group {
  display: flex;
  align-items: stretch;
  border: 1px solid var(--border);
  transition: border-color .15s;
}
.group:focus-within { border-color: var(--accent); }

.group .segment-label,
.group .segment-input,
.group .segment-button {
  border: none;
  background: transparent;  /* or solid fill if it's an action button */
  padding: 0 12px;
}

.group .segment-input {
  flex: 1;
  outline: none;
  font: inherit;
  min-width: 0;
}

/* Only the right-side segment carries the divider */
.group .segment-label { border-right: 1px solid var(--border); }
/* or */ .group .segment-button { border-left: 1px solid var(--border); }
```

## State Signals (no extra box)

- Default: dim border, label dim color.
- Focused / has-value: outer border → accent, label → accent (or fills solid).
- **Do NOT** animate individual segment backgrounds separately — that's the "complicated" trap.

## Anti-Patterns (Do Not Do)

- Two separate boxes with `gap: 8px` between them.
- Inner element with its own complete border.
- Border on BOTH sides of the divider (creates double line).
- Outer wrapper with no border + inner element with border (still looks like two boxes).
- Animated background swap on the label segment during focus (overcomplicated, fights the single-block read).

## Applied In Rectangular

- `.status-row` (S label + status input, both list and grid views)
- `.new-ticket` (input + ＋ add button, top of page)

## Prove You Understand

If asked to "add a unified input group" or "make label+input look like one thing" — produce this pattern. Do NOT propose alternative layouts (separate boxes, float labels, icon-only buttons, etc.) unless the user asks.
