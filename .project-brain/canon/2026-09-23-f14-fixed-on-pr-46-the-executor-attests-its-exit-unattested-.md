---
type: decision
title: F14 fixed on PR #46 — the executor attests its exit; unattested is status 4
description: F14 (a Compose failure reported as 'refused, nothing was mutated') is fixed on PR #46, pending merge. The executor print
tags: []
timestamp: 2026-09-23T18:55:00
sources: [sessions/daily/2026-09-23.md]
status: canon
promoted_at: 2026-09-24
---

F14 (a Compose failure reported as 'refused, nothing was mutated') is fixed on PR #46, pending merge. The executor prints a nonce-bound HERMES-EXIT <nonce> <rc> line for exits it chose, never for a crash; run-ads-mutate.sh trusts 0-3 only on exactly one exact match and otherwise exits 4, which the broker records as failed_unverified_exit ('possibly modified') and hermes-syscall returns as EXIT_FAILED_AFTER_MUTATION. Why: an exit status of 1 could come from Compose losing the connection after the container started, and only positive evidence from the executor can rule that out. Measured on Linux CI run 35905446915 (bind-agreement executed 6, skipped 0): a proxy-refused create now yields 4 with compose rc=1. Pre-start Compose failures are accepted false alarms (operator decision); mid-run connection loss is still unmeasured and the fix does not depend on it. After merge, the kill switch is gated only by the section 6 hardening.
