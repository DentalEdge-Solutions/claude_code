---
name: brain-search
description: "Use when the user asks what the brain knows — 'search the brain for X',
  'did we decide anything about Y', 'what do we know about Z', 'check the project
  brain'. Runs authority-ranked search over .project-brain/ and presents hits with
  their authority level. Not for: searching code (use Grep/Explore), the web, or
  Claude Code native auto-memory."
compatibility: "Claude Code. Node.js ≥ 18."
risk_tier: standard
---

# Brain Search

## Workflow
1. Distill the user's question into 2–5 search terms.
2. Run: `node scripts/brain/brain-search.js --query "<terms>" --json --limit 8`
3. Present hits grouped by authority (canon first), each with title, path, and a one-line gist from reading the file. State the authority level explicitly — a session note is a hint, canon is law.
4. Zero hits: say so plainly and suggest related terms; never invent brain content.
5. If the user acts on a canon/active item, remind that changes go through candidates + brain-promote.

## Files it may edit — none (read-only skill).
## Success criteria — answers cite capsule paths; authority always labeled; no fabricated memory.
