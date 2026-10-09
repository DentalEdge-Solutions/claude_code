---
type: decision
title: First VPS bring-up done; Phase 6 parked on the F10 store/spool layout
description: First real run of infra/hermes-agent/deploy/ on the Hostinger VPS (Ubuntu 24.04.4, x86_64, Docker 29.8.1) on 2026-09-21.
tags: []
timestamp: 2026-09-21T19:31:00
sources: [sessions/daily/2026-09-21.md]
status: superseded
---

First real run of infra/hermes-agent/deploy/ on the Hostinger VPS (Ubuntu 24.04.4, x86_64, Docker 29.8.1) on 2026-09-21. BRING-UP phases 0-5 and the new phase 7 are done: provision.sh --check 17/17 exit 0, root login shown refused from outside, the gateway is running with only :22 public, and the dashboard is reachable only through an SSH tunnel (laptop port 19119) behind form-based basic auth. Mutation stayed disabled, the kill switch was never created, and the ads repo is a placeholder until after the security review. Phase 6 (the systemd units) is deliberately PARKED rather than improvised on the box: nothing creates the governance store contents or data/spool on a fresh host, and their ownership decides who can delete or plant files in the only agent-to-broker channel. That is a security design decision to be designed, tested and landed from the laptop per the local-first canon (finding F10). F9 is also open: the resolved bind paths for bin and registry miss the proxy allow-list, which was measured and deliberately not widened. The runbook corrections and all 11 findings are in PR #33: docs/superpowers/specs/2026-09-21-vps-first-bring-up-findings.md.
