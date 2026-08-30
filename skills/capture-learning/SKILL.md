---
name: capture-learning
description: "Use when a correction or mistake just surfaced that's worth
  learning from — the user fixed your approach, a repeated error surfaced, or
  the user says 'learn from this', '/aprende', 'don't do that again', 'remember
  not to X'. Reviews the conversation, drafts durable learnings (lesson memories
  and anti-patterns), and writes them ONLY after per-item user confirmation.
  Not for: routine decision capture (brain-capture) or conversation summaries."
compatibility: "Claude Code. Node.js ≥ 18."
risk_tier: standard
---

# Capture Learning (aprende pattern)

Turn corrections into confirmed, durable lessons — write nothing without confirmation.

## Workflow
1. Review the recent conversation for learning signals: user corrections, reversals, repeated tool failures, 'stop doing X' feedback.
2. Draft candidate learnings, each with: what happened, why it was wrong, **How to apply** (the behavioral rule going forward). Classify: `lesson` (do this) or `anti-pattern` (never this).
3. Present ALL drafts; let the user confirm/edit/reject each (AskUserQuestion, multiSelect).
4. For each confirmed lesson: `node scripts/brain/brain-capture.js --type lesson --title "<title>" --message "<content incl. How to apply>"`. For anti-patterns, prefix the title with `anti-pattern:` (compile routes on type; the prefix preserves the classification for reviewers).
5. Run brain-compile so the confirmed lessons become candidate files immediately; report paths.

## Hard rules
- Zero writes before confirmation — a rejected draft leaves no trace.
- Lessons must be behavioral ('when X, do Y'), not blame notes.

## Files it may edit
- `.project-brain/sessions/daily/*`, then via compile `.project-brain/lessons/memories/*`

## Success criteria
- Only confirmed learnings written; each has an actionable How-to-apply.
