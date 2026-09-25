---
type: decision
title: §6B fixed on PR #57 and applied to the box — the last kill-switch gate is closed
description: Every audit log log/<slug>.jsonl is now sealed append-only (chattr +a, via stdlib fcntl.ioctl) when --bootstrap-logs or
tags: []
timestamp: 2026-09-25T15:41:00
sources: [sessions/daily/2026-09-25.md]
status: canon
promoted_at: 2026-09-25
---

Every audit log log/<slug>.jsonl is now sealed append-only (chattr +a, via stdlib fcntl.ioctl) when --bootstrap-logs or migrate() creates it, and the pre-flight refuses a registered log that is unsealed or cannot be checked (counts only, never slugs), because truncating the log erased the --undo record AND reset the daily caps, and the box measurement showed both the broker (via gid 10000) and the executor could do it. Box proof 2026-09-25 on a scratch store (d4fbb29..2a4e30e, proxy restart only): before, the broker got o_trunc OK / truncate OK / lines 0 with pre-flight rc=0; after, the log carried 'a', broker and executor got EPERM on truncate while append still worked, and the pre-flight went rc=0 -> rc=2 once the flag was cleared; merge-commit CI layout-integration executed 41 / bind-agreement executed 7, skipped 0. Sealing is never applied to an existing log (a person inspects first), and a sealed log refuses chmod/chown even for root (chattr -a first). Deliberately deferred: F20 (whoever can append can forge an 'undone' record — needs a host-side writer or signed records) and F21 (file-level pre-flight messages name per-log paths). Kill switch still absent; the remaining prerequisite is the rehearsal gate (.env.gaw WRITE credential), an operator security decision.
