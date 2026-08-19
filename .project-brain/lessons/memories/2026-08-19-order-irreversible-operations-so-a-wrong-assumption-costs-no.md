---
type: lesson
title: Order irreversible operations so a wrong assumption costs nothing
description: A credential was revoked to close a live exposure, on a pre-flight assertion that it could not affect a working credenti
tags: []
timestamp: 2026-08-19T12:50:00
sources: [sessions/daily/2026-08-19.md]
status: candidate
---

A credential was revoked to close a live exposure, on a pre-flight assertion that it could not affect a working credential. The assertion was wrong and the working credential died with it. The outage was recoverable and nothing reached a client account, but it was avoidable for free: minting the replacement BEFORE revoking the old one would have made the wrong assumption cost nothing, because a fresh credential would already have existed. The clue was available and unexamined — both credentials had been provisioned inside the same Cloud project, and that shared boundary was never checked before asserting isolation. Rule: when an operation is irreversible and rests on an assumption you have not measured, sequence it so the assumption being wrong is survivable. Prefer create-then-destroy over destroy-then-create, and treat 'I reasoned it cannot affect X' as a hypothesis requiring a test, not a pre-flight check.
