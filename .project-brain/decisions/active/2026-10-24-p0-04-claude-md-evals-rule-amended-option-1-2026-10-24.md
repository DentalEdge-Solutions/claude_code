---
type: decision
title: P0-04: skill-guardian retired; CLAUDE.md evals rule amended (option 1) (2026-10-24)
description: The skill-guardian agent is retired (PR #179, merge d3184d5; roadmap P0-04), replaced by a manual health-check recipe; the CLAUDE.md evals rule now names exactly which eval files are tracked (owner option 1).
tags: [agents, skill-guardian, evals, claude-md, p0-04, software-factory]
timestamp: 2026-10-24T16:29:00
sources: [sessions/daily/2026-10-24.md]
status: active
promoted_at: 2026-10-27
---

The skill-guardian agent is retired (B2 PR-4, PR #179, merged 2026-10-24 as d3184d5; roadmap S5 P0-04). It was a write-capable reader of untrusted text and had 0 invocations from July to October. Its definition (.claude/agents/skill-guardian.md), the root PROJECT-SKILL-HEALTH.md and its tracked scenarios (evals/agents/skill-guardian/evals.json) were deleted. A test (scripts/retired-skill-guardian.test.js) fails if a tracked file names it again outside excluded history paths; the only allowed live mention is the README's manual cleanup line.

In its place, the health check is a manual recipe, in the README and in the CLAUDE.md text install.sh writes into targets: refresh the project context, run skill-eval / agent-eval per skill and agent, then run skill-refine / agent-refine only for what fails. Do not reintroduce an always-on health-check agent without a measured need.

The owner chose option 1 for the CLAUDE.md amendment (S5 P0-04, R-B-10, R-A-12), made before any evals/ change: the Never rule now reads "never commit generated eval artifacts under evals/ (eval runs, refine logs, reports)"; only the scenario specs evals/**/evals.json, evals/.gitignore and evals/project-context.json (the toolkit's own context snapshot) are tracked. The Key Directories line matches. This resolves S6 CN-13.

Known leftovers: targets installed before the change keep the agent until it is removed by hand (the README gives the command); the AI-OS charter in canon still lists skill-guardian as part of the quality ratchet, left stale on purpose under D-07 (a) and due for update at the weekly review; the Codex judge prompts keep plain "guardian" wording, unchanged because editing them would change the evaluator. Record: docs/evaluations/2026-10-24-p0-04-retire-skill-guardian.md.
