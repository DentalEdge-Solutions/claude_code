---
name: reference-repo-audit
description: "Use when the reference library's safety needs checking — 'audit
  the reference library', 'is <source> safe to use', 'check the reference repos'.
  Runs the docs-only audit (no executables, no secrets, correct install policy,
  freshness) and separates security findings from warnings. Not for: registering
  a source (reference-repo-add) or extracting patterns (reference-repo-pattern-extract)."
compatibility: "Claude Code. Node.js ≥ 18."
risk_tier: standard
---

# Reference Repo Audit

Governance gate over the reference library — docs-only, no secrets, no direct-install policy.

## When to use
- Before extracting patterns from a source, or on a periodic library review.

## Workflow
1. Run for one entry: `node scripts/brain/brain-reference-repo-audit.js --name <n>`
   (or loop over every entry in registry.json for a full sweep).
2. Present SECURITY findings (exit 3 — executables under sources/, sensitive content, wrong
   install_policy) SEPARATELY from quality warnings (stale last_reviewed, thin prohibited_uses).
3. For stale entries, offer `reference-repo-refresh` after a human glance at the upstream repo.

## Files it may edit
- none directly (the script writes its own report to `.project-brain/reports/security/`).

## Hard rules
- An exit-3 finding BLOCKS any pattern-extraction work on that source until resolved.
- Never "fix" a security finding by deleting the guard or the report — redact the source and re-audit.

## Success criteria
- Security findings surfaced and blocking; warnings triaged; safe sources cleared for extraction.
