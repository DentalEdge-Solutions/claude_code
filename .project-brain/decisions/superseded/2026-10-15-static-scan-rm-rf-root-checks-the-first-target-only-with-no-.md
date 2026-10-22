---
type: decision
title: static-scan rm-rf-root checks the first target only, with no /tmp exemption
description: static-scan.js rm-rf-root checks only the first target, as on main; its only skip is git rm --cached.
tags: [static-scan, skill-audit, security, rm-rf-root]
timestamp: 2026-10-15T15:50:00
sources: [sessions/daily/2026-10-15.md]
status: superseded
promoted_at: 2026-10-15
---

rm-rf-root in skills/skill-audit/scripts/static-scan.js keeps main's simple shape: the first target is an absolute or home path, /tmp included. It adds extra option and quote spellings and $HOME. Its only skip is an option run holding --cached before any -- (git rm --cached, which only untracks; plain rm refuses that option). Why: an every-target scan with a /tmp exemption froze the scanner (quadratic regex) and was escapable via .., quotes, variables and redirects (PR #138 final review F1-F4). The owner chose this simpler rule together with R2 on 2026-10-15. Multi-target and other misses are recorded as gap S11 in docs/evaluations/2026-10-15-pr4-hermes-proposal-triage.md.
