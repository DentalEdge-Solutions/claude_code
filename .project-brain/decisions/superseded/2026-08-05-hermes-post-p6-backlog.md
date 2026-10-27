---
type: decision
title: Hermes post-P6 status + deferred backlog (VPS/P4 deferred by decision)
description: P6 monetization pilot validated and merged to main; VPS/P4 deferred by decision. This records the deferred/next-step backlog durably (the SDD ledger it was in is gitignored scratch).
tags: [hermes, backlog, roadmap, p4, monetization]
timestamp: 2026-08-05T20:00:00
sources: [.superpowers/sdd/progress.md, canon/2026-08-05-p6-ads-audit-pilot-validated.md]
status: retired
retired_at: 2026-10-27
retired_reason: Overtaken by events. The box runs (canon Phase 6 and Option B on the box; security reviews 6-11), D3.2 made Hermes read-only, GitHub hardening is P0-10, and the h0-spec branch is gone. Small items possibly still open (report collection timestamp, filename dedupe, old Inc-2 user-scoped token) are Hermes to-dos to re-check, not brain decisions.
---

## Status (2026-08-05)

Increments 1–3 (Kanban review pipeline · draft-PR write · read-execute) and **P6**
(read-only Google Ads audit pilot, validated GO) are **merged to `main`** and their
foundational decisions are in canon. **VPS / P4 is deferred by decision.** This note
persists the remaining backlog beyond the ephemeral (gitignored) SDD ledger.

## Deferred / next-step backlog

**Operator (UI, not code):**
- Revoke the old Inc-2 **user-scoped** fine-grained PAT (partially exposed in an early
  transcript; keep the org-scoped `dentaledge-bot`).

**P4 — VPS deploy (when resumed):**
- Provision the Hostinger VPS; auto-restart across reboot (systemd unit or compose-managed);
  TLS reverse proxy in front of the loopback dashboard; **pre-cutover security review**;
  dummy credentials first, real client credentials only after hardening.
- Fold in the **§10 `.env`-mask** (Inc-3 residual): mount an empty read-only file over the
  client project's in-tree `.env` so the full-access token is unreadable in-container —
  urgency rises on a shared host.
- Recurring / automated collection + delivery (the piece the always-on host unlocks).

**P6 fast-follow (before any PAID client audit ships):**
- Embed the `audit_data/` collection timestamp into the report tree so the deliverable's
  provenance line is exact, not inferred from report filenames.
- Same-second output-filename dedupe in `run-ads-audit.sh` (cosmetic).

**Scale-up (not warranted until the single-skill audit has real client mileage):**
- Multi-specialist `ads-analyst` team (the Inc-1 review-pipeline pattern) for quality
  decomposition by audit dimension.

**Governance / optional:**
- Team-plan hardening now that the org is on GitHub Team: require fine-grained PAT
  approval + required PR reviews on `main`.
- Prune the merged remote branch `origin/docs/hermes-h0-spec`.

**The payoff (use, not build):**
- Run the validated read-only audit pipeline to produce real DentalEdge client audits.
