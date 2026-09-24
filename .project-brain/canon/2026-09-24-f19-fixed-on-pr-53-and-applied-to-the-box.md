---
type: decision
title: F19 fixed on PR #53 and applied to the box
description: The Docker proxy now forwards container-scoped calls (inspect, start, attach, wait, delete) only to ads-mutator runs: a
tags: []
timestamp: 2026-09-24T17:08:00
sources: [sessions/daily/2026-09-24.md]
status: canon
promoted_at: 2026-09-24
---

The Docker proxy now forwards container-scoped calls (inspect, start, attach, wait, delete) only to ads-mutator runs: a full 64-hex id is required and, per request and before any byte goes upstream, the proxy asks dockerd about the target and requires the pinned image AND the pinned entrypoint (the image alone is shared by all three services), failing closed on any lookup error. This closed the path by which a compromised broker could read the gateway's API keys via inspect. Proven: CI RED run 36020681939, merge-commit CI run 36031116861 (bind-agreement executed 7); on the box the gateway probe returned 200 before and 403 after, and Phase 6 stayed clean. The only remaining kill-switch gate is §6 part B (audit-log truncation).
