---
name: brain-compile
description: "Use when the user wants session logs distilled into reviewable
  knowledge — 'compile the brain', 'extract decisions from this week', 'turn my
  session logs into candidates'. Runs brain-compile.js to extract [decision] and
  [lesson] entries into candidate files. Not for: capturing new entries (brain-capture),
  approving candidates (brain-promote), or summarizing the current conversation."
compatibility: "Claude Code. Node.js ≥ 18."
risk_tier: standard
---

# Brain Compile

Distill raw session logs into decision/lesson candidate files awaiting human review.

## When to use
- End of a work stretch, or when the Stop-hook suggestion mentions uncompiled entries.
- Before a brain-weekly-review, so candidates are current.

## Inputs
- Optional scope: a date (`--date YYYY-MM-DD`), or everything (`--all`). Default: today.

## Workflow
1. Run: `node scripts/brain/brain-compile.js [--date <date> | --all]`
2. Read the summary; list each new candidate (path + title) to the user.
3. Run `node scripts/brain/brain-lint.js` and surface any warnings on the new candidates.
4. If candidates exist, offer next step: review + promote via brain-promote (requires the user's explicit approval — never invoke promotion yourself).

## Files it may edit
- `.project-brain/decisions/candidates/*`, `.project-brain/lessons/memories/*`, `.project-brain/reports/compile/*` (via the script only)

## Files it must NOT edit
- `.project-brain/canon/`, `.project-brain/decisions/active/`

## Failure modes
- 0 candidates written and 0 skipped: session logs contain only notes — say so; do not invent candidates.

## Success criteria
- Every [decision]/[lesson] entry in scope has a candidate file; nothing promoted.
