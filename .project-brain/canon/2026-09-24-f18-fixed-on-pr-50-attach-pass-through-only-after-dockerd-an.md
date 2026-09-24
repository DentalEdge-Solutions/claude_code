---
type: decision
title: F18 fixed on PR #50 — attach pass-through only after dockerd answers 101
description: The Docker proxy used to switch a connection to raw, uninspected pass-through whenever /attach appeared anywhere in an a
tags: []
timestamp: 2026-09-24T12:38:00
sources: [sessions/daily/2026-09-24.md]
status: canon
promoted_at: 2026-09-24
---

The Docker proxy used to switch a connection to raw, uninspected pass-through whenever /attach appeared anywhere in an allowed request's target (query string included), before dockerd had answered. Now attach is defined once (_ATTACH_RE, shared by the allow-list and _is_attach: POST, query stripped, fullmatch), _handle reads dockerd's response head first, and only an attach answered exactly 101 is passed through; any other answer to an attach is relayed and the connection closed. Why: a compromised broker could otherwise smuggle an uninspected privileged create after one allowed request. Measured on Linux CI run 35999764190: real Compose attach is answered 101 (UPGRADE logged), bind-agreement executed 6, skipped 0. F19 recorded: attach may target any container; listed as a kill-switch gate until assessed. After merge, the kill switch is gated by section 6 part B (audit-log truncation) and F19.
