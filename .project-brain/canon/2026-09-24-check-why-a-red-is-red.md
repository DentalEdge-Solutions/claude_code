---
type: lesson
title: Check why a RED is red
description: A security test's first CI RED failed for the wrong reason: the probe pinned API /v1.55 and CI's dockerd 28.0.4 caps at
tags: []
timestamp: 2026-09-24T17:08:00
sources: [sessions/daily/2026-09-24.md]
status: canon
promoted_at: 2026-09-24
---

A security test's first CI RED failed for the wrong reason: the probe pinned API /v1.55 and CI's dockerd 28.0.4 caps at 1.48, so dockerd answered 400 and the sentinel-not-read assertion passed vacuously while the test still went red on a later status check. Always read the failing assertion and confirm the RED exercises the property named; use unversioned Docker API paths in probes that must run on more than one Engine.
