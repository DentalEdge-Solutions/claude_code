---
type: lesson
title: The laptop collector needs Docker Desktop running (2026-10-14)
description: With Docker Desktop off, the laptop collector exits 0 but writes D3.1 as could-not-check; start Docker first and read D3.1's status before moving on.
tags: [security-review, laptop, docker, d3-1]
timestamp: 2026-10-14T17:59:00
sources: [sessions/daily/2026-10-14.md]
status: active
promoted_at: 2026-10-27
---

The laptop half of a security review runs the credential audit in a Docker container. With Docker Desktop not running, the collector still exits 0 but writes D3.1 as could-not-check ('no audit documents in the output'), and the only sign is in the bundle's contents. Check that Docker Desktop is running before the laptop collection, and read D3.1's status in the laptop bundle before copying anything or moving on.
