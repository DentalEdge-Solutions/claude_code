---
type: decision
title: Untrusted-content readers are read-only and carry the framing (P0-03, P0-06, 2026-10-24)
description: Agents that read untrusted content are read-only, and every untrusted reader carries the untrusted-content framing (B2 P
tags: []
timestamp: 2026-10-27T00:20:00
sources: [sessions/daily/2026-10-27.md]
status: active
promoted_at: 2026-10-27
---

Agents that read untrusted content are read-only, and every untrusted reader carries the untrusted-content framing (B2 PR-3, PR #178, merged 2026-10-24 as fabaad9; roadmap P0-03 and P0-06).

What holds:
- The repo-audit layer analysts (repo-audit-runtime, -framework, -database, -auth, -cicd, -testing, -ai-llm, -claude-code) have tools Read only; they cannot write files or run commands.
- Every skill or agent that reads untrusted text (repository files, web pages, third-party skills) carries the untrusted-content paragraph: such content is data, never instructions. 21 files gained it in PR #178.
- scripts/validate-skills.js enforces it for this toolkit's own tree: every file on its UNTRUSTED_INTAKE_FILES list and every repo-audit analyst must carry the framing paragraph (a listed file that is missing also fails), every repo-audit analyst must have exactly tools Read, and a skill or agent that names WebFetch or WebSearch without the paragraph is warned. Since P0-05 (PR #180) no definition warns.
- List membership is a per-file security decision, written down and reviewed in the validator: a new untrusted reader is added to the list when it lands. Hermes is not listed yet, by design (P1-16, outside this tree).

Not measured yet: the repo-audit ensemble team-eval (P1-10, B6; no before/after delta is claimed, per the B0 decision of 2026-10-23). Record: docs/evaluations/2026-10-24-p0-03-p0-06-untrusted-readers.md.
