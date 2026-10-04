---
type: decision
title: Hermes v0.21.5 upgrade evaluated; batch it with the PR 96 pull before review 7
description: Laptop evaluation 2026-10-03 (docs/evaluations/2026-10-03-hermes-v0-21-5-upgrade-evaluation.md): v0.21.5 keeps uid 10000
tags: []
timestamp: 2026-10-03T20:29:00
sources: [sessions/daily/2026-10-03.md]
status: candidate
---

Laptop evaluation 2026-10-03 (docs/evaluations/2026-10-03-hermes-v0-21-5-upgrade-evaluation.md): v0.21.5 keeps uid 10000, HERMES_HOME, printenv, s6 services and our committed mcp_servers block (equals_repo true after the gateway rewrite); our derived image builds; our app MCP server connects with 3 tools. No CVE forces the upgrade; state.db fixes in v0.21.2 and v0.21.3 and the instruction-file write protections motivate it. Box trial still owed: amd64, a real chat audit, review probes, auxiliary routing, and no secrets file in the Hermes data directory.
