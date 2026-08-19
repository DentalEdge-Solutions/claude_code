---
type: lesson
title: CORRECTS CANON: OAuth revocation isolates by ACCOUNT, not by client id
description: Canon (credential governance, rule 1) states that revocation is per (user, client) pair and prescribes giving each crede
tags: []
timestamp: 2026-08-19T12:50:00
sources: [sessions/daily/2026-08-19.md]
status: candidate
---

Canon (credential governance, rule 1) states that revocation is per (user, client) pair and prescribes giving each credential-holding component its OWN OAuth client so revocation becomes surgical. An increment was built on that premise. Measured 2026-08-19, it does not hold as written: revoking one refresh token belonging to an account killed that account's grants across TWO DIFFERENT client ids, taking out a working credential as collateral. A third credential sharing the SAME client id as the casualty survived — because it belongs to a different Google ACCOUNT. Both client ids had been created inside the same Cloud project, which is the likeliest reason the platform treated them as one app boundary. Corrected model: the isolation axis is the ACCOUNT; for client-level separation to mean anything the clients must live in separate Cloud PROJECTS. A second client id inside the same project buys no revocation isolation at all. This does not reduce the value of separate accounts per role — that is precisely what saved the surviving credential — but it means 'own OAuth client' is not sufficient on its own. Canon rule 1 needs amending; this entry is the evidence, and promotion remains a human decision.
