---
type: decision
title: Option B part 3 merged (PR 88): review tooling and checklist v1.11 on main; box rollout and review 6 are next
description: Option B part 3 (spec 2026-09-30 hermes-chat-triggered-audits section 8; review tooling) is merged to main via PR #88, C
tags: []
timestamp: 2026-10-01T17:27:00
sources: [sessions/daily/2026-10-01.md]
status: superseded
promoted_at: 2026-10-01
---

Option B part 3 (spec 2026-09-30 hermes-chat-triggered-audits section 8; review tooling) is merged to main via PR #88, CI green including the first real-Docker run of both probes; with PRs #85 and #86 all three Option B parts are now on main and nothing is on the box yet. It adds keyed (HMAC) customer-id fingerprints with a laptop-only review key read from the tty on the box, run-client-audit --probe-env and --probe-egress (sentinel values, throwaway directories, audit lock held, DNS exit measured), the collector's D2.1/D4.1/D4.2/D7.1 edits and D10.1-D10.8, the review-5 follow-ups, and checklist v1.11 with the D10.7 live checks as BRING-UP part 2 step 11. Key rulings, made because the spec is the binding authority and the plan predated parts 1-2: the env probe also reports env names whose value holds the sentinel; D10.7 counts leaks in both the broker and runner journals; D10.6 never prints the gateway-writable MCP config and instead compares its block line-by-line with the committed template (a stated limit, not a YAML parse; the broker stays the boundary); D4.2 keeps its ExecStart hash (false after a proxy restart needs an operator statement plus an unchanged unit and no drop-ins) and gains a restart-stable argv hash as the next review's baseline. Next is the box rollout (BRING-UP chat-triggered audits parts 1 and 2, the manual audit, the first chat audit, the step 11 live checks, shredding the rollback backups) and then security review 6 against checklist v1.11; the runner restart-spin fix must merge before that evidence is collected, or be listed under D9.1, because bin/ is in the box fingerprint.
