---
type: decision
title: P6 monetization pilot validated — Hermes produces client-grade Google Ads audits (read-only)
description: The ads-analyst pipeline produced a client-grade audit draft matching the hand-made benchmark; validates the fixed-fee one-off audit as a product. GO.
tags: [hermes, monetization, ads-analyst, read-only, pilot]
timestamp: 2026-08-05T18:00:00
sources: [docs/superpowers/specs/2026-08-05-hermes-ads-analyst-pilot-design.md, docs/superpowers/plans/2026-08-05-hermes-ads-analyst-pilot.md]
status: canon
promoted_at: 2026-08-05
---

## Outcome: GO — the fixed-fee read-only Google Ads audit is a validated product

**Meta-only record. No client business data is stored here (hard rule).**

The P6 pilot proved Hermes can produce a **client-grade Google Ads audit draft** for a
real DentalEdge client account via a repeatable, **read-only** pipeline, at trivial
marginal cost per client.

**Pipeline (all read-only, Hermes never writes the client tree):**
host-side collection (`collect-audit-data.sh` runs the ads project's own SELECT-only
collectors under the read-only credential → refreshes `audit_data/`) → Inc-3 read-execute
readers → the single hand-authored `claude-code-ads-analyst` skill (`claude -p`, plan mode,
opus) → audit DRAFT in `/opt/data/audits/`.

**Quality vs the bar:** benchmarked against the existing hand-made Palmetto exec summary
(different reporting period, so judgments compared, not raw numbers). The draft **matched
the hand-made audit on all four core judgments** (deteriorating account / wrong bid
strategy; ad-to-landing-page language mismatch as the growth lever; duplicate-call
conversion-tracking problem; and the top corrective actions) and **added three insights
the hand-made summary did not surface**. Every quantitative claim traced to a cited report
section — no invented numbers. Human review: operator reviewed the draft, found it sound,
no blocking edits.

**Safety proven live:** read-only credential (mutation refused server-side); allow-list
readers only; collection SELECT-only; analyst is read-only `claude` (no Bash/Write, wrote
via redirect to `/opt/data`, not the `:ro` mount); credential scan clean (0 secrets in
draft + reports + logs); `:ro` target byte-identical (only host-side `audit_data/`
refreshed). A shell-injection defect in the analyst wrapper was caught by task review and
fixed (charset-validate the project arg + `docker exec -e` instead of source-splicing).

**Governance:** the deliverable is a DRAFT behind a mandatory human-review gate — never
auto-sent. Client business data (reports, drafts) stays under gitignored `/opt/data`,
never committed, never in the brain/memory/telemetry.

**Recommendation / next:** proceed to offer the fixed-fee audit; the pipeline is repeatable
per client. Scale-up path (NOT this pilot): the multi-specialist review-team pattern
(Inc-1) for quality decomposition; **P4 (VPS)** for always-on / recurring delivery; a
polished client-facing render; and — separately gated — the managed/mutation tier.
