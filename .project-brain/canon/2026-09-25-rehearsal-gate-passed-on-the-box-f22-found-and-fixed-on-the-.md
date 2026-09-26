---
type: decision
title: Rehearsal gate passed on the box — F22 found and fixed on the way
description: The rehearsal gate passed on the box on 2026-09-25 (attempt 2): a human-approved request for a dedicated fake client 're
tags: []
timestamp: 2026-09-25T19:13:00
sources: [sessions/daily/2026-09-25.md]
status: canon
promoted_at: 2026-09-26
---

The rehearsal gate passed on the box on 2026-09-25 (attempt 2): a human-approved request for a dedicated fake client 'rehearsal' (customer id 0000000000, dummy .env.gaw — operator decisions) went gateway -> broker (reservation) -> wrapper -> proxy -> container and came back refused_preflight / exit 2 with the attested HERMES-EXIT line, every proxy call ALLOW and no DENY, the approval recording the outcome, 0 log lines, no run record; then 'rehearsal' was retired and the dummy credential removed. Attempt 1 found F22: the broker unit's ProtectHome=true made /home unreadable, the Docker client abandons plugin discovery on EACCES, so 'docker compose' was an unknown command (compose rc=125, recorded fail-closed as failed_unverified_exit). Fixed by ProtectHome=tmpfs (PR #62) with a Linux CI test that runs Compose under every directive of the real unit file — nothing had ever run Compose under the broker's actual sandbox. What remains before the kill switch: the real WRITE credential as its own deliberate step, the first real client (merged into the registry beside the retired rehearsal entry), and the operator's decision.
