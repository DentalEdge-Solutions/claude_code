---
type: decision
title: B0: pre-edit evals skipped by owner decision (2026-10-23)
description: Batch B0 of the approved P0 package skips the three pre-edit E12 runs planned by DECISION-S5-2 / D-03 (repo-audit ensemb
tags: []
timestamp: 2026-10-23T18:00:00
sources: [sessions/daily/2026-10-23.md]
status: active
promoted_at: 2026-10-27
---

Batch B0 of the approved P0 package skips the three pre-edit E12 runs planned by DECISION-S5-2 / D-03 (repo-audit ensemble team-eval, skill-scout-agent agent-eval, skill-scout skill-eval), because each would deliberately exercise breaches P0 fixes: unpinned npx repomix and pip install gitingest with shell-holding analysts on a live repository, and third-party SKILL.md bodies fed to agents holding Write and Bash. For P0-03 this is allowed by S5 (absolute thresholds). For P0-05 it is a deviation from S5 (Baseline: measure in B0) and D-03, approved by the owner: P0-05 is judged on its absolute agent-eval thresholds (dispatch at least 85 percent, resilience at least 8/10) plus the ranking comparison on a fixed fixture set; no before/after delta is claimed for P0-03 or P0-05. Record: docs/evaluations/2026-10-23-factory-outcome-baseline/README.md section 4.
