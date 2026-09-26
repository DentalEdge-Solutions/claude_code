---
type: decision
title: F21 resolved by policy — client slugs may be in the box's journal, never off the box
description: Client slugs reach the box's systemd journal by three routes: the broker logs 'client <slug>' on every request, the exec
tags: []
timestamp: 2026-09-25T16:49:00
sources: [sessions/daily/2026-09-25.md]
status: canon
promoted_at: 2026-09-26
---

Client slugs reach the box's systemd journal by three routes: the broker logs 'client <slug>' on every request, the executor output it copies can carry the slug, and the pre-flight's file-level faults name log/<slug>.jsonl and approvals/<slug>/. The operator decided (2026-09-25, option A) that the journal is trusted host storage — root-readable only on a single-tenant box, and naming the client is what makes a failed apply debuggable — so the rule governs what leaves the box: replace every real slug with <client> before pasting journal, broker or pre-flight output into a chat, PR, doc or handoff, and RESULT blocks use scratch slugs only. Pseudonymising slugs everywhere the host writes to the journal was considered and not chosen (touches the broker and the executor's output contract, and makes failed applies harder to trace). Recorded in README 'Client names and the journal', the head of BRING-UP, and findings F21 (PR #60).
