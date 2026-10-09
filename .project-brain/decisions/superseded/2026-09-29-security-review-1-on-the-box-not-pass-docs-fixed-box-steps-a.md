---
type: decision
title: Security review #1 on the box: NOT PASS — docs fixed, box steps and the D3.2 decision remain
description: The first independent review (2026-09-29, fresh reviewer agent given only the brief, checklist, template, two redacted b
tags: []
timestamp: 2026-09-29T13:24:00
sources: [sessions/daily/2026-09-29.md]
status: superseded
---

The first independent review (2026-09-29, fresh reviewer agent given only the brief, checklist, template, two redacted bundles and the findings doc) returned NOT PASS: 19 PASS, 3 FAIL, 4 manual items open, no sign of compromise. FAILs: D1.6 was a wrong checklist expectation (hermes-docker-proxy is in the docker group by design; fixed in checklist v1.4); D2.1 unexplained unswept in-memory mounts (standard mounts pre-explained in v1.4, the writable ones need an operator sweep); D7.1 vault dirs 0755 under a 0700 parent (chmod 700 pending). It also found the README contradicting canon rule 1 by claiming a separate OAuth client makes revocation surgical; corrected. BRING-UP now has the one-step disable (D8.1) and a revoke-and-prove-death procedure (D8.2). The reviewer recommends moving the write role from the operator's ADMIN account to a dedicated STANDARD-access account (D3.2), an operator decision. Handoff: docs/superpowers/handoffs/2026-09-29-security-review-1-and-next-steps.md (PR #70).
