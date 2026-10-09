---
type: decision
title: Security review 7 PASS (34/34, v1.16) on Hermes v0.21.5; OpenRouter key rotated to a box-only key
description: Security review #7 passed 34 of 34 on checklist v1.16 and was signed on 2026-10-06, so the box may keep running Hermes v
tags: []
timestamp: 2026-10-06T16:28:00
sources: [sessions/daily/2026-10-06.md]
status: superseded
---

Security review #7 passed 34 of 34 on checklist v1.16 and was signed on 2026-10-06, so the box may keep running Hermes v0.21.5 with the API server off (D4.1 listeners [9119]). It took three judgements: the laptop bundle had to be re-collected on the sign-off day, and D10.5 could not be verified until the OpenRouter key was rotated, because the old key had been created for the laptop build and a laptop gateway was still running with it. The new key was created for the box only, typed once into the installer and stored nowhere else; the old key is deleted. The review also found a Data Training toggle (free endpoints that train on request data) that had been on since before review #6, hidden by a cropped screenshot; it is off now. Follow-ups: number the new findings, annotate review #6, add the rotation to BRING-UP, decide a rotation interval. Report: docs/security-reviews/2026-10-06-review-7.md. Handoff: docs/superpowers/handoffs/2026-10-06-review-7-pass-key-rotated.md.
