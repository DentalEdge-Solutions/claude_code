---
type: decision
title: Upstream check 2026-08-24: Nous Hermes Agent v0.20.5 (tag v2
description: Upstream check 2026-08-24: Nous Hermes Agent v0.20.5 (tag v2026.8.19) EXISTS and is confirmed, but it is a PATCH ROLLUP,
tags: []
timestamp: 2026-08-24T18:02:00
sources: [sessions/daily/2026-08-24.md]
status: superseded
---

Upstream check 2026-08-24: Nous Hermes Agent v0.20.5 (tag v2026.8.19) EXISTS and is confirmed, but it is a PATCH ROLLUP, not the Quicksilver release — Quicksilver is v0.19.0 (v2026.7.20), which is the version our pinned digest already runs. Upstream provides no spool/broker/host-syscall (code search 0 hits, iron_proxy control 5 hits); the nearest feature, the iron-proxy credential-injection egress firewall (v0.20.0, PR #70848), keeps credentials out of the sandbox but supplies standing unlimited authorisation, so it is a candidate not a substitute for the governed syscall. Fleet management is gateway multiplexing, not project registration — registry/projects.yaml and the read_execute/mutate_execute tiers are ours and untouched. Container identity contract (uid 10000, shared PID namespace) is unchanged at v0.20.5, so F7 and Plan 1 masking/one-shot executors stand. Upstream docker-compose.yml byte-identical across the window; no breaking-change headings. Plan 2 NOT re-scoped. Do not upgrade the gateway; revisit at v0.21.0 when curated notes ship. Full record: docs/evaluations/2026-08-24-upstream-hermes-release-check.md
