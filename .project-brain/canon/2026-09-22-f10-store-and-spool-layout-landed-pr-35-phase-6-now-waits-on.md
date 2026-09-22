---
type: decision
title: F10 store and spool layout landed (PR #35); Phase 6 now waits on F9 only
description: F10 landed on main via PR #35 (merge 6ddef24), with CI green on the merge commit, including the new root-on-Linux Tier 2
tags: []
timestamp: 2026-09-22T13:15:00
sources: [sessions/daily/2026-09-22.md]
status: canon
promoted_at: 2026-09-22
---

F10 landed on main via PR #35 (merge 6ddef24), with CI green on the merge commit, including the new root-on-Linux Tier 2 suite (executed 22, skipped 0). A fresh host now gets its governance store and spool from bin/init-host-layout.py (dry run, --apply as root, --check as hermes-broker, never repairs). The spool moved out of the gateway-owned data/ to /var/lib/hermes/spool, spool files are 0640, the broker verifies .quarantine and never overwrites an existing result, and the broker unit runs the layout --check before the pre-flight. Why: on Linux the old layout could not work (0600 spool files between two uids) and let the gateway redirect the broker into the store. Next: F9 (bind paths vs the proxy allow-list) is the only blocker for Phase 6. F12 (approve-changeset and persist-run-record cannot reach data/vaults as hermes-broker) must be fixed before the kill switch is created, and the kill switch stays absent. On the 2026-09-21 box, follow README VPS deploy sequence step 2 (pull, add HERMES_SPOOL_DIR, compose down, rmdir the empty store, apply, check, compose up), and check first for store subdirectories left by BRING-UP Phase 5. Local .env needs HERMES_SPOOL_DIR=./data/spool.
