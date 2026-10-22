---
type: decision
title: PR #4 (Hermes improvement proposal) closed; 10 open items carried forward (2026-10-15)
description: Draft PR #4 (a stale Hermes proposal from 2026-07-24) was closed after a recheck on main. 10 of its 14 items were open at the recheck; P13 has since been fixed (PR #135), leaving 9.
tags: [hermes, proposal, triage, codex-eval, testing]
timestamp: 2026-10-15T03:07:00
sources: [sessions/daily/2026-10-15.md]
status: superseded
promoted_at: 2026-10-15
---

Owner closed draft PR #4, Hermes's machine-generated proposal from 2026-07-24, instead of merging its stale candidate. A recheck on main 4db546d found 2 of its 14 items done (CI, run-manifest tests), 2 partly done and 10 still open. Its summary also claimed no CI, which is outdated. The most urgent open item was P13: scripts/codex/test-runners.js overwrote evals/skill-audit/codex-baseline.json and planted a fake evals/skill-eval/codex-baseline.json on every test run, so Codex regression detection compared against fixture data. skill-eval never had a real baseline, because its only HEALTHY run was a smoke run. P13 was fixed the same day (PR #135, merge e36002b): the tests now use a temp workspace, a guard test protects the real baselines, the skill-audit baseline was rebuilt from its 2026-07-01 run, and the fake skill-eval file was removed. Next comes P1: the brain and telemetry secret-pattern lists each miss tokens the other catches. The full ranked list and evidence are in docs/evaluations/2026-10-15-pr4-hermes-proposal-triage.md. Lesson for future Hermes proposals: recheck each item against current main before merging, because a proposal is a dated snapshot.
