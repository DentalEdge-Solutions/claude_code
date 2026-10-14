---
type: decision
title: Security review #11 PASS 38/38 (v1.22); F62 fixed in the console; both jobs in use
description: Security review #11 PASS 38/38 (checklist v1.22), signed 2026-10-14, merged in PR #126; both jobs (ads-audit, ads-report) in use since the sign-off.
tags: [security-review, hermes-box, ads-report, f62]
timestamp: 2026-10-14T17:59:00
sources: [sessions/daily/2026-10-14.md]
status: active
promoted_at: 2026-10-14
---

Security review #11 passed 38/38 on checklist v1.22, with both bundles collected and the review signed on 2026-10-14 (docs/security-reviews/2026-10-14-review-11.md). It is the first review covering two jobs (ads-audit and ads-report) and the first to search every stored field of the journal (F59's fix). On the sign-off, the ads-report off switch came off, so both jobs are in use. The operator accepted a standing rule: before running a report for a client whose last audit failed, read that audit's step logs first, because a report run clears them. Follow-ups for review #12: a key guardrail limiting OpenRouter to the box's model; the collector reading provider_routing and named-volume options (F61).
