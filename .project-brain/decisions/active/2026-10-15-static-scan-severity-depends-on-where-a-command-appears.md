---
type: decision
title: static-scan severity depends on where a command appears
description: static-scan.js rates a BLOCK-level dangerous command FLAG when it appears only in markdown code, and BLOCK in prose.
tags: [static-scan, skill-audit, security, scanner-severity]
timestamp: 2026-10-15T15:50:00
sources: [sessions/daily/2026-10-15.md]
status: active
promoted_at: 2026-10-15
---

In skills/skill-audit/scripts/static-scan.js (the skill-audit security gate), a BLOCK-level dangerous command (rm-rf-root, curl/wget piped to a shell, ~/.ssh access) that appears only in what the scanner reads as markdown code (a ``` fenced block or an inline span; ~~~ and indented blocks are read as prose) is a FLAG; in prose it stays BLOCK. Secret patterns keep their own severity and are now matched in code too. Why: sourced skills often show installer lines in code, which BLOCK would refuse outright, and the scanner's code detection is a regex, so this way a fence trick can only lower BLOCK to FLAG, never hide a command. Owner decision R2, 2026-10-15, merged in PR #138.
