---
type: decision
title: Security review #9 PASS 37/37 (v1.18); F58 opened: the box's journal keeps 7 days
description: Security review #9 passed 37 of 37 on checklist v1.18, signed by the operator on 2026-10-09 and merged in PR #108 (docs/
tags: []
timestamp: 2026-10-09T15:39:00
sources: [sessions/daily/2026-10-09.md]
status: active
promoted_at: 2026-10-09
---

Security review #9 passed 37 of 37 on checklist v1.18, signed by the operator on 2026-10-09 and merged in PR #108 (docs/security-reviews/2026-10-09-review-9.md). The first collection, on 2026-10-08, failed D10.7 because the box's journal keeps 7 days (finding F58: the setting came with the server, and the checklist and collector assume 30 days), so the live refusals of 2026-10-02 had aged out; the three checks were repeated and both bundles collected again on 2026-10-09. F56 (new dashboard password) is fixed and F57 (limited key for the laptop's forward) is reduced on the box since 2026-10-08, with F57's three residuals accepted at the sign-off. F58 is accepted for this review and is to be fixed with the next box change (at least 30 days of journal; the collector reports the window it read). Until then the three live refusal checks are repeated within 7 days before every box collection.
