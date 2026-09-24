---
type: decision
title: Section 6 part A landed on PR #48 — proxy framing hardening + UMask=0077
description: The Docker proxy now parses every request head once, strictly (_parse_head), and refuses anything it cannot parse unambi
tags: []
timestamp: 2026-09-23T21:49:00
sources: [sessions/daily/2026-09-23.md]
status: canon
promoted_at: 2026-09-24
---

The Docker proxy now parses every request head once, strictly (_parse_head), and refuses anything it cannot parse unambiguously: obs-fold, a space before the colon, duplicate Content-Length, a bare CR/LF/NUL, anything but HTTP/1.1, non-printable header values, and a Content-Length over 19 digits. Why: the proxy forwards headers verbatim to dockerd, so any parsing disagreement could let a compromised broker smuggle an uninspected request. Hardened without the VPS framing measurement, as the measurement plan's section 6 allows. Both units now run with UMask=0077; they are copied to /etc/systemd/system, so the box must re-copy them and daemon-reload. Linux CI run 35924147988: bind-agreement executed 6, skipped 0, ALLOW on create. After merge and box rollout, the kill switch is gated only by section 6 part B (audit-log truncation).
