---
name: brain-weekly-review
description: "Use when it's time for the periodic brain maintenance ritual —
  'weekly review', 'brain review', 'refresh the brain', or when brain-lint
  reports stale items. Reads current brain state first, interviews the user
  only about deltas ('same' keeps an item), updates status fields only, and
  stamps review dates. Not for: promoting candidates (brain-promote) or
  compiling logs (brain-compile)."
compatibility: "Claude Code. Node.js ≥ 18."
risk_tier: standard
---

# Brain Weekly Review (KJ OS pattern)

Delta-only refresh: detect staleness, ask what changed, update only status fields.

## Workflow
1. Scan first, ask second: run `node scripts/brain/brain-lint.js`; read `.project-brain/BRAIN.md`, `index.md`, and titles in `decisions/active/`. Build the delta list: stale items (lint warnings), active decisions, pending candidates.
2. Interview the user through the delta list, one item at a time: show current state, ask "still accurate, changed, or superseded?" — "same" moves on immediately. Never make the user restate unchanged things.
3. Apply updates. `decisions/active/` is written only by `brain-promote.js` (the security guard denies direct edits there), so each decision change goes through it, on that item's verdict from step 2:
   - Changed decision → write the revised copy (same file name; body and `timestamp` updated, structure unchanged) to `.project-brain/decisions/candidates/<file>.md`, then apply it: `node scripts/brain/brain-promote.js decisions/candidates/<file>.md --approve --to active --force`.
   - Superseded → `node scripts/brain/brain-promote.js decisions/active/<file>.md --approve --to superseded` (moves it to `decisions/superseded/` with `status: superseded` and `superseded_at`, and logs it). A note on what replaced it may then be added to the superseded copy.
   - Pending candidates the user wants promoted → hand off to /brain-promote (do NOT promote them here).
4. Stamp `BRAIN.md` with a `> Last reviewed: YYYY-MM-DD` line (add or update, nothing else in that file).
5. Capture a review summary entry via brain-capture.js (`--type note --title "weekly review"`).

## Hard rules
- Update status/timestamps/bodies of existing items only — never rewrite structure, never touch canon/, never promote a candidate.
- Run `brain-promote.js` only for an item the user answered "changed" or "superseded" in this session, one item per call; never edit `decisions/active/` directly.

## Files it may edit
- `decisions/candidates/*` (staged revisions), `decisions/superseded/*` (a note on a superseded copy), `BRAIN.md` (review stamp only), `sessions/daily/*` (via script); `decisions/active/*` only through `brain-promote.js`

## Success criteria
- Every stale-flagged item reviewed or consciously deferred; lint stale-warnings reduced; zero structural rewrites.
