---
type: decision
title: Credential access levels are measured, never asserted
description: Every access-level guarantee in this capsule used to be a sentence in prose ('this credential is read-only'). Twice thos
tags: []
timestamp: 2026-08-18T19:31:00
sources: [sessions/daily/2026-08-18.md]
status: candidate
---

Every access-level guarantee in this capsule used to be a sentence in prose ('this credential is read-only'). Twice those sentences were wrong and the discrepancy surfaced only by luck. A credential-scoped audit tool now asks the platform what a given credential can actually do — read, blast radius, mutate, manager-level admin — and exits non-zero when the measured level disagrees with the declared one. It is credential-scoped rather than project-scoped deliberately, so it carries to whatever project replaces the current one and to every project registered after it. Rule for any future integration: a credential's access level is a measurement with an expiry, not a documented fact.
