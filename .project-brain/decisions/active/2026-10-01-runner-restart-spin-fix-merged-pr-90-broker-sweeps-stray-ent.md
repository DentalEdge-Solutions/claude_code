---
type: decision
title: Runner restart-spin fix merged (PR 90): broker sweeps stray entries from jobs; checklist v1.12
description: The runner restart-spin fix is merged to main via PR #90 (CI green), so the one item that had to land before the Option
tags: []
timestamp: 2026-10-01T19:35:00
sources: [sessions/daily/2026-10-01.md]
status: active
promoted_at: 2026-10-01
---

The runner restart-spin fix is merged to main via PR #90 (CI green), so the one item that had to land before the Option B box rollout is done. The broker now removes any entry in app-state/<app>/jobs whose name does not fully match the job-file pattern, on every pass and before recover(), by name alone (lstat then unlink or rmdir, never following a link, never recursing); a matching name is a job and is never touched. This was needed because the runner's path unit fires on a non-empty jobs directory while the runner ignores non-matching names, so a stray entry re-started the root runner in a loop. Checklist is now v1.12: D10.7 names the three fixed-text warnings that share the warning count (no pass rule changed), so review 6 runs against v1.12, not v1.11. Still not covered, by decision: an entry the broker cannot remove (a non-empty directory, which only the app user or root can create there) gets one journal line and is left, and the sweep only runs while the broker runs.
