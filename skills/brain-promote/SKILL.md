---
name: brain-promote
description: "Use when the user explicitly runs /brain-promote to review brain
  candidates for promotion to active decisions or canon. Presents candidates
  one at a time, records the user's verdict, and only on an explicit per-item
  'approve' runs brain-promote.js --approve. Never promotes autonomously; never
  batch-approves. Not for: capturing (brain-capture) or compiling (brain-compile)."
compatibility: "Claude Code. Node.js ≥ 18."
disable-model-invocation: true
risk_tier: critical
---

# Brain Promote — human approval gate

Walk the user through candidate review. The user approves; the script promotes; you never decide.

## When to use
- Only when the user explicitly invokes /brain-promote or unambiguously asks to promote/approve brain candidates.

## Workflow
1. List candidates: `ls .project-brain/decisions/candidates/` (and lesson candidates: files in `.project-brain/lessons/memories/` whose frontmatter says `status: candidate`).
2. For EACH candidate, one at a time: show title, description, body, source. Ask via AskUserQuestion: **Approve to active / Approve to canon / Skip / Retire**. Never present more than one candidate per question; never suggest a default of approval.
3. Only on an explicit approval: `node scripts/brain/brain-promote.js <relative-path> --approve [--to canon]`
4. On Retire: move to `.project-brain/decisions/superseded/` with `status: retired` — use Edit/Bash normally (superseded is not a protected path).
5. Report: promoted / skipped / retired counts and the log.md entries written.

## Hard rules
- NEVER run the script without `--approve`, and NEVER pass `--approve` without a recorded per-item user verdict from this session.
- NEVER edit files in `canon/` or `decisions/active/` directly — the script is the only writer.
- Script exit 2 or 3 is a stop-and-surface, not a retry-with-different-flags.

## Files it may edit
- `.project-brain/decisions/candidates/*` (removal via script), `.project-brain/decisions/superseded/*`
- `canon/` and `decisions/active/` ONLY via the script with per-item approval.

## Success criteria
- Every promotion traceable to an explicit user verdict; log.md reflects each move.
