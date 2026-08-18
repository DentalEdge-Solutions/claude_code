---
type: decision
title: Credential model: one OAuth client per component, one account per role
description: OAuth client and platform account are different axes, and conflating them is what once made a revocation collateral rath
tags: []
timestamp: 2026-08-18T19:32:00
sources: [sessions/daily/2026-08-18.md]
status: candidate
---

OAuth client and platform account are different axes, and conflating them is what once made a revocation collateral rather than surgical — revocation is per (user, client) pair, so a shared client means killing one grant kills them all. The model: each credential-holding component gets its own OAuth client; each ROLE gets its own account. The read role uses a dedicated service account that is read-only at the platform level, and it must NEVER be upgraded — its inability to mutate is the server-side backstop beneath every allow-list, cap and kill switch, and it is what makes a read path safe even when all of those fail. The write role currently reuses the operator's own admin-level account: a deliberate, recorded tradeoff (more privilege than needed, machine actions attributed to a human, and an access level that can change without anyone touching this system) accepted because provisioning per-role service accounts was judged not worth it yet. Revocation stays surgical regardless, because the client was separated even though the account was not.
