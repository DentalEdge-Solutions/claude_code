---
type: decision
title: skill-scout-agent is a read-only fetcher; candidates pinned to a full commit sha (P0-05, 2026-10-26)
description: skill-scout-agent is a read-only fetcher dispatched only by the skill-scout skill, and every candidate is pinned to a fu
tags: []
timestamp: 2026-10-27T00:20:00
sources: [sessions/daily/2026-10-27.md]
status: active
promoted_at: 2026-10-27
---

skill-scout-agent is a read-only fetcher dispatched only by the skill-scout skill, and every candidate is pinned to a full commit sha (B2 PR-5, PR #180, merged 2026-10-26 as fce8542; roadmap P0-05).

What holds:
- skill-scout-agent has tools Read, WebFetch and WebSearch only: no writes, no commands, no agent dispatch. It is not a user entry point; users run the skill-scout skill (coordinator decision R-3).
- It returns one fenced JSON array of at most 6 candidates with a closed key set and never returns SKILL.md text. Each candidate is pinned to a full 40-character lowercase commit sha, and its source_url points at that exact commit (https://github.com/org/repo/tree/sha[/path]). A date alone is not a pin; this is stricter than the roadmap's "commit or date" (decision R-20). Candidates it cannot pin, fetch or locate are dropped and counted.
- skills/skill-scout/scripts/score-candidates.js --agent-output validates that output strictly before scoring (regular file only, 4 MiB cap, strict UTF-8 and JSON with duplicate keys refused, hidden characters refused, closed keys, GitHub URL rule, ref equal to commit_hash) and exits 2 on rejection without echoing values. skill-scout shows a shortlist only from validated output and says when candidates were dropped.
- Rankings on the fixed fixtures are unchanged.

Residuals: the main session still sees the agent's raw reply; Read is kept per DECISION-S3-2 (a), so read-then-send is limited by instruction only; targets installed before PR #180 keep the old write-capable agent until install.sh is re-run there. Not measured: agent-eval of skill-scout-agent and skill-eval of skill-scout (P1-10, B6); the tracked scenarios for skill-scout-agent are stale and are regenerated in B6. Record: docs/evaluations/2026-10-25-p0-05-scout-read-only-fetcher.md.
