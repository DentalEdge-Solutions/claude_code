---
name: brain-kernel
description: "Use when a second-brain request names no specific operation — 'do
  something with the brain', 'brain status', 'how is the brain', 'help me with
  project memory'. Diagnoses capsule state and routes to the right brain skill.
  Not for: requests that already name an operation (capture, compile, promote,
  search, review, setup — invoke those skills directly)."
compatibility: "Claude Code. Node.js ≥ 18."
risk_tier: standard
---

# Brain Kernel — orchestrator

## Workflow
1. Diagnose: `node scripts/brain/brain-verify.js` (structure), `node scripts/brain/brain-lint.js`
   (quality/security), count candidates awaiting review, check BRAIN.md's Last-reviewed stamp.
2. Report a one-screen status: structure OK? · security findings? · N candidates pending ·
   days since last review · session-log activity this week.
3. Route by finding:
   | Finding | Route |
   |---|---|
   | No capsule | project-brain-bootstrap |
   | Placeholder BRAIN.md sections | second-brain-setup |
   | Uncompiled session entries | brain-compile |
   | Candidates pending review | suggest /brain-promote (user-invoked; never invoke it yourself) |
   | Stale items / >7 days since review | brain-weekly-review |
   | Security findings from lint | show the report; help redact, then re-lint |
   | "what do we know about X" | brain-search |
4. Never perform a governed write itself — this skill reads, reports, and routes only.

## Files it may edit — none.
