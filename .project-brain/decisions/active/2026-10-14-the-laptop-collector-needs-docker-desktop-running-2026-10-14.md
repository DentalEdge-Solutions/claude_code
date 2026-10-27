---
type: lesson
title: The laptop collector needs Docker Desktop running (2026-10-14)
description: The laptop collector runs the credential audit in Docker. Since PR #185 (2026-10-27) it stops with exit 3 when Docker is down and exits 4 when the bundle is incomplete; read its exit code and D3.1's status before moving on.
tags: [security-review, laptop, docker, d3-1]
timestamp: 2026-10-14T17:59:00
reviewed_at: 2026-10-27
sources: [sessions/daily/2026-10-14.md, sessions/daily/2026-10-27.md]
status: active
promoted_at: 2026-10-27
originally_promoted_at: 2026-10-27
---

The laptop half of a security review runs the credential audit in a Docker container. On 2026-10-14, with Docker Desktop not running, the collector still exited 0 and wrote D3.1 as could-not-check ('no audit documents in the output'); the only sign was in the bundle's contents.

Since PR #185 (merged 2026-10-27, f31f78b) the collector fails loudly: with Docker down it prints "Docker is not running: start Docker Desktop, then re-run", runs no audit and writes nothing (exit 3; --access-digest keeps exit 2 with the same message); with Docker up but D3.1 (or a requested D6.3) could-not-check, it writes the bundle and exits 4 with one fixed-wording line per incomplete item. The owner's probe with Docker Desktop quit passed on 2026-10-27. Rule that remains: start Docker Desktop before the laptop collection, run it as the runbook's step 4 does (python3, with `echo "collector_rc=$?"`), and do not use a bundle unless the collector exited 0 and D3.1 reads observed. Record: docs/evaluations/2026-10-27-laptop-collector-docker-preflight.md.
