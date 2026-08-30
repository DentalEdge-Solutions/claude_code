---
name: brain-capture
description: "Use when the user wants to record a decision, lesson, or noteworthy
  fact into the project brain — 'log this decision', 'remember that X', 'capture
  this lesson', 'note this in the brain'. Appends a typed entry to today's session
  log in .project-brain/sessions/daily/. Not for: promoting knowledge to canon
  (use brain-promote), compiling logs into candidates (use brain-compile), or
  Claude Code's native auto-memory — this writes the git-versioned project capsule."
compatibility: "Claude Code. Node.js ≥ 18."
risk_tier: standard
---

# Brain Capture

Record one durable observation into the project brain's session log.

## When to use
- The user states a decision, lesson, correction, or fact worth keeping beyond this session.
- After a notable failure or reversal whose cause is worth remembering.

## Inputs
- The content to capture (from conversation), a type (`decision` | `lesson` | `note` — infer from content, confirm if ambiguous), an optional short title.

## Workflow
1. Draft the entry: 1–5 sentences, self-contained (a reader without this conversation must understand it). Include the *why*, not just the *what*.
2. Confirm type and wording with the user if you inferred either.
3. Run: `node scripts/brain/brain-capture.js --type <type> --title "<title>" --message "<content>"`
4. If the script exits 3 (sensitive content), tell the user what pattern was flagged and ask for a redacted version — never bypass the refusal.
5. Report the file written and remind the user of the next step in the pipeline: **brain-compile** turns captured decisions/lessons into review candidates. (Do not name brain-promote here — promotion to canon is a separate, later, human-approved step; the immediate next step after capture is compile.)

## Files it may edit
- `.project-brain/sessions/daily/*` (via the script only)

## Files it must NOT edit
- `.project-brain/canon/`, `.project-brain/decisions/active/` — promotion is brain-promote's job, behind human approval.

## Failure modes
- Script exits 1 (no capsule): offer `project-brain-bootstrap`.
- Empty/vague content: ask for the missing why rather than capturing filler.

## Success criteria
- Entry appended with correct type; sensitive-content refusals surfaced, never worked around.
