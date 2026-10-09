---
type: decision
title: Security review #4 PASS (26/26, v1.8): Google Ads audits live on the box
description: Security review #4 (2026-09-30) passed 26/26 against checklist v1.8, signed off by the operator. It is the first review 
tags: []
timestamp: 2026-09-30T14:44:00
sources: [sessions/daily/2026-09-30.md]
status: superseded
---

Security review #4 (2026-09-30) passed 26/26 against checklist v1.8, signed off by the operator. It is the first review with Google Ads audits on the box (PRs #75-#78): 'sudo run-client-audit <client>' runs collectors and readers in one-shot containers, drafts with Opus in the gateway and writes to the client vault. The box holds one READ credential (/etc/hermes/.env.ga, root 0400, fd18a3b7d0f4, same token as the laptop) and a real Anthropic key in the 'hermes-box' workspace ($20/month limit); no write credential (read-only posture unchanged). The first real audit (<client>) took ~3 min, cost $0.51 and was judged deliverable. Incidents fixed along the way: the registry was overwritten by an improvised block (restored; BRING-UP step 5 guarded, PR #76), the compose symlink path (PR #77), data/reports ownership (PR #78). The PASS binds to box fingerprint 1d13661f..., digest 0f0bdb9e.... Next: Option B (Hermes chat triggers audits) needs its own design with per-client isolation and a container egress/credential probe.
