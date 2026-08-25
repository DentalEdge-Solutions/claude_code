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
3. Apply updates:
   - Changed decision → update its body and `timestamp` in `decisions/active/` (status-level edit — never restructure the file).
   - Superseded → move to `decisions/superseded/`, set `status: superseded`.
   - Pending candidates the user wants promoted → hand off to /brain-promote (do NOT promote here).
4. Stamp `BRAIN.md` with a `> Last reviewed: YYYY-MM-DD` line (add or update, nothing else in that file).
5. Capture a review summary entry via brain-capture.js (`--type note --title "weekly review"`).

## Hard rules
- Update status/timestamps/bodies of existing items only — never rewrite structure, never touch canon/, never promote.

## Files it may edit
- `.project-brain/decisions/active/*` (content updates), `decisions/superseded/*`, `BRAIN.md` (review stamp only), `sessions/daily/*` (via script)

## Success criteria
- Every stale-flagged item reviewed or consciously deferred; lint stale-warnings reduced; zero structural rewrites.
