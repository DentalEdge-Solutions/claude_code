---
type: decision
title: Option B parts 1-2 merged (PRs 85, 86): chat-triggered audits built, not yet on the box
description: Option B (spec 2026-09-30 hermes-chat-triggered-audits) parts 1 and 2 are merged to main via PR #85 (client data out of
tags: []
timestamp: 2026-10-01T13:39:00
sources: [sessions/daily/2026-10-01.md]
status: active
promoted_at: 2026-10-01
---

Option B (spec 2026-09-30 hermes-chat-triggered-audits) parts 1 and 2 are merged to main via PR #85 (client data out of the gateway; per-client ads-drafter behind an Anthropic-only egress proxy; run-client-audit --json/--list) and PR #86 (MCP tools -> unprivileged sandboxed broker -> root path-activated runner; gateway holds only the OpenRouter key; provider_routing.data_collection deny). Key rulings: no git push without the operator; part-2 runner run timeout 7200 s and kill grace 90 s (above run-client-audit's ~6000 s worst case); the pinned Hermes has no zdr key, so Zero Data Retention must be set in the OpenRouter account (spec section 13); refusals beyond 1000/day get no result (pending) to stop results/ flooding. Nothing is on the box yet: part 3 (review tooling, checklist v1.11) and security review #6 come first.
