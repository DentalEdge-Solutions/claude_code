---
type: lesson
title: Changing a regex security pattern needs a differential and a timing check
description: Regex security-pattern changes need an old-vs-new differential, a timing sweep and real-command checks before merge.
tags: [static-scan, regex, redos, review, testing]
timestamp: 2026-10-15T15:50:00
sources: [sessions/daily/2026-10-15.md]
status: active
promoted_at: 2026-10-15
---

On PR #138 five independent reviews and several automated background security checks found new bypasses or ReDoS in the author's own static-scan.js fixes: a narrowed rm pattern that dropped /etc, a length cap defeated by padding, quadratic and exponential patterns, an escapable /tmp exemption, and a --cached skip defeated by --. What caught them: a main-vs-branch harness over thousands of samples, a 1 MB timing sweep of every pattern, and real rm runs in a scratch folder. Before changing a scanner pattern, run those, give the test runner a per-scan timeout so a ReDoS fails instead of hanging, and prefer the simplest pattern that is a superset of main's.
