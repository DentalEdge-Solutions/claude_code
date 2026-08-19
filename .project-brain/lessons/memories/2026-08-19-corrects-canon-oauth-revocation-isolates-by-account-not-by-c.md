---
type: lesson
title: CORRECTS CANON: OAuth revocation isolates by ACCOUNT, not by client id
description: Canon (credential governance, rule 1) states that revocation is per (user, client) pair and prescribes giving each crede
tags: []
timestamp: 2026-08-19T12:50:00
sources: [sessions/daily/2026-08-19.md]
status: candidate
---

Canon (credential governance, rule 1) states that revocation is per (user, client) pair and prescribes giving each credential-holding component its OWN OAuth client so revocation becomes surgical. An increment was built on that premise. Measured 2026-08-19, it does not hold as written: revoking one refresh token belonging to an account killed that account's grants across TWO DIFFERENT client ids, taking out a working credential as collateral. A third credential sharing the SAME client id as the casualty survived — because it belongs to a different Google ACCOUNT. All the client ids involved were created inside ONE Cloud project — checkable, since the project number is the prefix of every OAuth client id — which is a plausible explanation for the platform treating them as a single app boundary. It is NOT tested: no credential in a different Cloud project existed to try, so whether a separate project would isolate is unknown, and it must not be recommended as a mitigation until someone tests it. Corrected model, stated only as far as the evidence reaches: the isolation axis is the ACCOUNT, and a separate client id is demonstrably insufficient. This does not reduce the value of separate accounts per role — that is precisely what saved the surviving credential — but it means 'own OAuth client' is not sufficient on its own. Canon rule 1 needs amending; this entry is the evidence, and promotion remains a human decision.
