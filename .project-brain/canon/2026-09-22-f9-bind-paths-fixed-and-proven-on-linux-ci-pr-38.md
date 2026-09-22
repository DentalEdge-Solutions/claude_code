---
type: decision
title: F9 bind paths fixed and proven on Linux CI (PR #38)
description: F9 landed on main via PR #38 (merge 89c0746): ads-mutator's seven bind sources are now absolute :?-guarded vari
tags: []
timestamp: 2026-09-22T18:03:00
sources: [sessions/daily/2026-09-22.md]
status: canon
promoted_at: 2026-09-22
---

F9 landed on main via PR #38 (merge 89c0746): ads-mutator's seven bind sources are now absolute :?-guarded variables supplied by hermes-broker.service and equal to the proxy's UNCHANGED --allow-bind pins; run-ads-mutate.sh passes --env-file /dev/null so the broker never needs to read .env (600 root:root, holds ANTHROPIC_API_KEY). Proven on Linux CI, green ON THE MERGE COMMIT (run 35769257423): bind-agreement executed 6, skipped 0 (layout-integration executed 22, skipped 0) — the real proxy allowed the create, the real executor refused at the absent kill switch, and all three firing controls fired. WHY the original finding was partly wrong: the 2026-09-21 box measurement used sudo docker compose from the working directory, which drops PWD so Compose resolves the /opt/hermes-agent symlink; the broker's real path does not, so bin/registry actually matched and only the ads-repo bind was wrong. SUPERSEDES the canon line 'F9 is the only blocker for Phase 6': F9 never blocked unit installation, because nothing creates a container at unit start; the real gate is the new 'first approved request (rehearsal)', which needs F9 + F12 + .env.gaw. F14 recorded (inferred, unmeasured): a Compose failure exits 1 and the broker reports 'refused_usage — nothing was mutated', which could be false if the connection breaks after the container started; it gates the kill switch. The bind-agreement job and Test suites are now REQUIRED status checks on main (ruleset main-protection), so the agreement cannot regress unnoticed; they gate by job NAME, so renaming a job in ci.yml silently un-gates it. Still unproven: nothing has run on the VPS — BRING-UP Phase 6 (Confirm the Bind Agreement) is the box confirmation, and systemd, the box's Compose version and the real image are all untested.
