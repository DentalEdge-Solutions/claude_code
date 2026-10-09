---
type: decision
title: Security review #5 PASS (26/26, v1.10) after the post-#4 hardening
description: Security review #5 (2026-09-30) passed 26/26 against checklist v1.10, signed off by the operator. It covers PR #80 (cust
tags: []
timestamp: 2026-09-30T16:14:00
sources: [sessions/daily/2026-09-30.md]
status: superseded
---

Security review #5 (2026-09-30) passed 26/26 against checklist v1.10, signed off by the operator. It covers PR #80 (customer-id fingerprints never committed), PR #81 (register-client tool that cannot install a broken registry; D7.1 covers data/reports and audit-logs; pwd -P in host scripts) and PR #82 (checklist v1.10: audit-logs/<client> is root 0711 by design, v1.9 wrongly required 0700). The audit-logs files measured 0600 (19 root, 1 uid 10000). Binds to box fingerprint 2dad4553..., digest 0f0bdb9e.... Follow-ups: the collector reports audit-logs file modes and classifies nsfs handles; evidence files carry the last PASS's proxy ExecStart hash; Option B (Hermes chat) needs its own design with per-client isolation, a credential/egress probe for the audit containers, and keyed hashes for the review tooling's cid: fingerprints.
