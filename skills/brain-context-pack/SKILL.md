---
name: brain-context-pack
description: "Use when starting a substantial task and relevant brain context should
  be loaded up front — 'pack context for X', 'what should I know before doing Y',
  'load the brain for this task'. Runs brain-context-pack.js and folds the result
  into the working context. Not for: one-off lookups (brain-search) or session
  bootstrapping (the SessionStart hook already loads the protocol)."
compatibility: "Claude Code. Node.js ≥ 18."
risk_tier: standard
---

# Brain Context Pack

## Workflow
1. State the task intent in ≤ 6 words.
2. Run: `node scripts/brain/brain-context-pack.js --intent "<intent>"`
3. Read every file listed in relevant_canon and relevant_decisions (they are few by design); skim lesson hits.
4. Summarize to the user: which prior decisions constrain this task, which lessons apply, and what the gaps mean ('no lessons recorded on this topic yet').
5. Surface any warnings verbatim — especially sensitive-content warnings. If memory conflicts with the requested task, state the conflict before proceeding (Second Brain Protocol rule).

## Files it may edit — none (read-only skill).
## Success criteria — constraining decisions surfaced before work starts; conflicts stated; gaps named, not papered over.
