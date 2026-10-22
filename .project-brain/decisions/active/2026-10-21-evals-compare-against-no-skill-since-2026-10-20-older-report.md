---
type: decision
title: Evals compare against no skill since 2026-10-20; older reports are not comparable (2026-10-21)
description: Since E12 (2026-10-20), skill and agent evals use a no-skill or no-agent baseline; reports from before then are not comparable with new ones.
tags: [skill-eval, agent-eval, baseline, methodology]
timestamp: 2026-10-21T23:31:00
sources: [sessions/daily/2026-10-21.md]
status: active
promoted_at: 2026-10-22
---

Since E12 (owner decision 2026-10-20, on main 2026-10-21 through PR #163), every skill and agent eval compares the definition against a baseline with no skill loaded or no agent dispatched (baseline_method none), in skill-eval, agent-eval and both eval agents. Before, an existing definition's manifest recorded a snapshot baseline. The snapshot was taken at eval time and was identical to the subject, so the skill flows compared the definition with itself (a delta of about 0), and the eval agents ran no skill at all under a snapshot label; new definitions already recorded none. Consequence: eval reports from before 2026-10-20 stay as written but are not compared with new ones. The delta now measures what the definition adds over no definition, not over an earlier version of it; a true earlier-version baseline is a separate feature for later. Source: docs/evaluations/2026-10-15-pr4-hermes-proposal-triage.md, "E10, E11 and E12 repair".
