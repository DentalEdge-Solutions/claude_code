---
type: charter
status: canon
title: "Charter — claude_code as the foundational substrate for a self-evolving AI operating system"
description: "The north-star: this project is the base layer of an AI OS that evolves by generating specialized, coordinating agent teams. Maps the existing layers to that goal, names the reality/target gap honestly, and records the load-bearing and deferred decisions and operating principles."
tags: [charter, vision, ai-os, agent-teams, governance, north-star]
timestamp: 2026-07-17
reviewed_at: 2026-10-27
sources: 
promoted_at: 2026-10-27
originally_promoted_at: 2026-07-17
---

# Charter — `claude_code` as an AI-OS substrate

> **Status: canon** (promoted 2026-07-17). **Revised 2026-10-27 for facts only**, on the owner's weekly-review
> verdict: the retired skill-guardian is replaced in the layer table (S6 D-07), the stale "candidate" status line
> is corrected (S6 D-26), and the Hermes framing follows the canon memory corrections D-1 (Hermes = the adopted Nous
> Hermes Agent) and D-2 (the Eve pattern is a design influence, not a loader). The direction is unchanged: whether
> to widen it to a general app-building factory is the owner's open decision (S6 D-28), and the commercial
> objective stays recorded in the memory-corrections record (D-5), to be weighed there.

## North-star

`claude_code` is the **foundational structure for a self-evolving AI operating system**. The system
grows by **generating teams of agents specialized in different areas** (marketing, analytics, web,
ads, …) that operate independently and **coordinate when a task spans areas**. The substrate's job is
to make new specialized capability **cheap to add, safe to run, and governed** — so scaling teams is a
matter of dropping in governed folders, not writing fragile runtime configuration.

## The layers already built toward it

The vision is the implicit telos of machinery that already exists (verified 2026-07-17; rows for the quality
ratchet and the substrate updated 2026-10-27):

| Layer of the OS | Implemented as |
|---|---|
| Generate specialized agents | agent pipeline: `agent-scout → agent-audit → agent-adapt → agent-eval → agent-refine` |
| Teams that coordinate | `team-eval` + `team.json` + the `repo-audit-ensemble` fixture (Dispatch-Chain Accuracy, Handoff Integrity) |
| Self-improvement / quality ratchet | `skill-eval` / `agent-eval`, Karpathy autoresearch refine loops (`skill-refine`, `agent-refine`), telemetry `REFINE_RECOMMENDED`; the health check is a manual recipe (refresh the project context, run the evals, refine only what fails) since the always-on health-check agent was retired on 2026-10-24 (P0-04) |
| OS-level persistent memory | the Second Brain capsule (`.project-brain/`) |
| Substrate to scale teams without fragile config | the Eve filesystem-as-registry pattern (a design influence, D-2) + the adopted Nous Hermes Agent control plane, which operates Claude Code projects via `claude -p` from its project registry (`infra/hermes-agent/registry/projects.yaml`) |
| Governed adoption of outside capability | the reference-repository library + `scout → audit → adapt → eval` |
| Mountable domain expertise for teams | the **domain-packs** subsystem (`packs/`) + the Google Analytics pilot |

## Reality vs. target (stated honestly)

**Today** this is a working **skill/agent quality pipeline + governed memory + one read-only domain
pack**, operated by an adopted, read-only Hermes control plane — a strong foundation, not a running OS.
**The target** is the self-evolving, team-spawning OS above. The named gaps between them are the deferred
decisions below. This charter is a *direction to build toward*, not a claim of what already runs.

## Load-bearing decisions already made

- **Filesystem-as-registry (Eve pattern), pattern-only** — informs the adopted Hermes's project registry
  and the toolkit itself (`skills/`, `.claude/agents/`, `hooks/`, `evals/`); the Eve adoption decision is
  superseded and kept as a design influence (memory corrections D-2).
- **Hermes = the adopted Nous Hermes Agent**, a runtime dependency governed by an adoption decision and a
  security-audit gate, not a custom-built orchestrator *(canon, 2026-07-21; memory corrections D-1, D-4)*.
- **Domain packs, contract-first** — knowledge + tools + guardrails, hybrid ownership (shared registry →
  per-project vendor), per-pack execution-mode tiers (read-only / HITL / staging-autonomous), multi-client
  pack/client split. Runtime deferred to Hermes. *(shipped Phase 1)*
- **Acquisition: official APIs first** — scrapers are a governed follow-on; stealth/ToS-evasion tools and
  OSINT/attack-surface tooling are excluded/out-of-scope. *(decided)*

## Deferred / open (the roadmap the gap implies)

- **Hermes, write path** — Hermes itself is adopted and runs on the Hostinger box (canon: Phase 6 passed on
  the box, 2026-09-22). It is read-only with no write credential (canon: D3.2, 2026-09-29), and under Track A
  it proposes improvements while the owner and Claude Code build them (active decision of 2026-10-22). Still
  deferred: the credential vault, HITL pause/resume, budget caps and staging enforcement needed before any
  write to a paid or client-facing system, built with the first monetizable product that needs writes.
- **Retrieval upgrade** — graph/FTS over a growing multi-domain KB; selection among Graphify /
  Understand-Anything / PixelRAG, deferred until *measurably* needed.
- **Central Operator Brain** — the cross-project/shared layer (domain packs and cross-project knowledge
  live here); currently the per-project capsule only. *Backlog.*
- **Next packs** — Google Ads (first HITL pack; its read-only audits already run through Hermes since the P6
  pilot, and writes are parked by D3.2), Meta, WordPress/Bricks (staging), GTM, GoHighLevel.

## Operating principles (how the system is allowed to evolve)

1. **Governance-first:** external capability enters only through `scout → audit → adapt → eval`; never
   install directly from reference sources.
2. **Human-gated durability:** nothing reaches `canon/` or `decisions/active/` except via
   `brain-promote --approve`. Promotion is never autonomous.
3. **Filesystem-as-registry:** capability is added by dropping governed folders/files; discovery is
   dynamic; nothing is hardcoded.
4. **Memory authority ranking governs conflict:** `canon > active decision > validated lesson >
   synthesis > session note > raw source`; state conflicts before proceeding.
5. **Safety boundaries are non-negotiable:** no secrets in memory or packs; no stealth/ToS-evasion
   tooling; tiered guardrails on anything that touches live, money-spending, or client-facing systems.
6. **Measure before scaling infrastructure:** add heavier machinery (graph retrieval, new runtimes)
   only when a measurable need appears, not speculatively.

## Why record this

Every future decision should be judgeable against this north-star. Absent it, the layers read as
independent tools; with it, they are one coherent, self-evolving, governed agent OS.
