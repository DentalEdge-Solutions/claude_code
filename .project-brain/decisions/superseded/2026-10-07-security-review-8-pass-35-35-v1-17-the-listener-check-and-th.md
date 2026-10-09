---
type: decision
title: Security review 8 PASS (35/35, v1.17): the listener check and the hashed dashboard password are live
description: Security review #8 passed 35 of 35 on checklist v1.17 and was signed on 2026-10-07. Two findings from review #7 are now 
tags: []
timestamp: 2026-10-07T17:40:00
sources: [sessions/daily/2026-10-07.md]
status: superseded
---

Security review #8 passed 35 of 35 on checklist v1.17 and was signed on 2026-10-07. Two findings from review #7 are now fixed on the box: a timer records the gateway's listening ports every 15 minutes (F50; it records only, by the operator's decision), and the dashboard password is held as a scrypt hash with a session-signing secret (F47). The dashboard change was measured on the laptop first, which found that Docker Compose cuts a bare hash short (F52), so the installer writes it single-quoted. Accepted at sign-off, with follow-ups for the next box change: set a new dashboard password, give the laptop's SSH forward its own restricted key, and have the collector report each service's start time, because automatic security updates restart the Docker proxy and broker unannounced (to be numbered F55). The operator's everyday client is now the Hermes Desktop app over an SSH forward; Tailscale was evaluated and not adopted. Report: docs/security-reviews/2026-10-07-review-8.md. Handoff: docs/superpowers/handoffs/2026-10-07-review-8-pass.md.
