---
type: lesson
title: Adding a second job on the box: two measurements (2026-10-14)
description: Enabling a second job's units did not change the Docker proxy's ExecStart hash (D4.2 needed no baseline statement); measured once, on this box's systemd.
tags: [hermes-box, systemd, d4-2, ads-report]
timestamp: 2026-10-14T14:08:00
sources: [sessions/daily/2026-10-14.md]
status: retired
retired_at: 2026-10-27
retired_reason: A narrow operational measurement (enabling a second job did not change the Docker proxy's ExecStart hash), measured once on one box; belongs in the Hermes runbook rather than brain guidance (optional follow-up).
---

Adding `ads-report` with `systemctl enable --now` did not change the hash of the Docker proxy's `ExecStart` line, so D4.2 needed no baseline statement; the runbook expected a reload might change it. Measured once, on this box's systemd; check again on another box.
