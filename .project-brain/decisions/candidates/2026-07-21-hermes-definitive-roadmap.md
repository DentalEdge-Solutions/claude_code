---
type: decision
status: superseded
superseded_by: canon/2026-07-23-hermes-memory-corrections-d1-d5.md
superseded_reason: "Custom-kernel framing (D-3). 'Hermes' is Nous Research's adopted Hermes Agent, not a custom-built kernel. Replaced by the adoption candidate + the D-1…D-5 correction (now canon)."
title: "Hermes definitive roadmap — credential-free kernel now, multi-tenant Operate track deferred, LLM-agnostic engine"
description: "The definitive plan for implementing Hermes: build a credential-free runtime KERNEL (run agents/teams + serve pack knowledge) now, and defer the credential-bearing execution services (vault, HITL, budget, pack-execution adapter, money/write) to a shared, multi-tenant, just-in-time Operate track initiated with the first spawned operator project. The engine is a pluggable adapter (claude -p default) with capability-tiered, eval-gated model routing."
tags: [hermes, roadmap, architecture, kernel, operate-track, multi-tenant, llm-agnostic, model-routing, governance, deferred]
timestamp: 2026-07-21
sources:
  - .project-brain/canon/2026-07-17-ai-os-charter.md
  - .project-brain/decisions/active/vercel-eve-fs-architecture-adoption.md
  - .project-brain/decisions/candidates/2026-07-17-hermes-local-first-deploy.md
  - docs/superpowers/specs/2026-07-20-hermes-master-architecture.md
  - "Session review 2026-07-20/21 (Claude Opus 4.8): two-agent audit (18 findings A–R), kernel/operate layering, multi-tenancy, LLM-agnostic engine"
---

# Hermes — definitive roadmap (decision candidate)

> **Status: candidate** (awaiting `brain-promote --approve`). Not law until promoted. Full step-by-step
> roadmap of record: `~/.claude/plans/iterative-squishing-church.md` (session plan file); the corrected
> per-phase specs/plans live under `docs/superpowers/{specs,plans}/`.

## Decision

Implement Hermes in two clearly separated scopes:

1. **Hermes KERNEL (build now)** — the persistent runtime that *runs* agents/teams/packs and *serves
   governed domain knowledge*, and **never touches a credential, live write, or money** (its security
   boundary). Phases: **K0** walking skeleton · **K1** daemon + scheduler + SQLite `runs` queue ·
   **K2** pack knowledge/skills mounting + retrieval · **K3** VPS deploy (needs only
   `ANTHROPIC_API_KEY`).
2. **Hermes OPERATE track (deferred, client-driven)** — the credential-bearing execution services
   (credential vault, per-client bindings, pack-execution adapter, HITL approval, budget caps,
   staging/money/client-write, real credentials). Built **just-in-time with the first spawned
   operator project** (e.g. Google Ads Management), living in the **shared kernel** so every later
   product and client reuses it (multi-tenant by client). A further-deferred human-user
   identity/RBAC layer sits above it.

## Why (rationale)

- **Layering:** autonomous operation of live platforms is a *spawned-project* goal, not a base-substrate
  goal; this repo (`claude_code`) is the factory + kernel, not an operator of client systems.
- **Charter principle #6 (measure before scaling):** there is no operator project yet, so the
  vault/HITL/budget/adapter runtime must not be built speculatively.
- **Shared kernel, not per-project:** security-critical services (vault, HITL, budget) built once,
  correctly, and reused — avoids duplicating tenant isolation across projects. Multi-client reuse is a
  core payoff; multi-*human-user* access is a separate later identity layer.
- **Packs were fine, but forward-committed:** packs are docs-only by contract (no executor); their
  `tools/`/`guardrails/` declarations are valid *forward contracts* for the Operate track, not
  functionality that exists today. ~90% of Hermes complexity serves the Operate (action) goal, not the
  knowledge-consultation goal — so the split is honest and cost-aligned.

## Cross-cutting decisions (D1–D15)

- **D1** default engine = Claude Code headless `claude -p` (not the only engine — see D14).
- **D2** `node:sqlite`, Docker base `node:24-slim`; keep toolkit Node ≥18 by skipping Hermes DB suites
  on Node <22.
- **D3** SQLite `hermes/state/hermes.db` via shared `lib/db.js`; kernel uses only the `runs` table.
- **D7** daemon = thin supervisor over the run core; thread the claimed `runId` end-to-end.
- **D8** deploy = git pull + `docker compose build`; kernel needs only `ANTHROPIC_API_KEY`.
- **D9** no LangChain/CrewAI in the v1 build; reconsidered only as the harness for the deferred
  agnostic-runtime track, or on a measured retrieval need.
- **D12 (security boundary)** the kernel never handles a credential, live write, or money.
- **D13** multi-tenant execution services live in the shared kernel, built JIT with the first operator
  project; human-user identity/RBAC is further-deferred.
- **D4** encrypted-file vault (AES-256-GCM, key from `HERMES_VAULT_KEY`) — **Operate**.
- **D5** adapter-primary enforcement; built-in write tools disabled for enforced tiers; PreToolUse hook
  = defense-in-depth (corrected contract, fail-closed) — **Operate**.
- **D6** HITL = approved-replay (`running→awaiting_approval→resumed→done`) — **Operate**.
- **D10** client identity first-class (client on runs/approvals/budget/vault + `clients/<client>/binding.json`
  schema) — **Operate**.
- **D11** headless-capability spike + pack-execution adapter — **Operate**.
- **D14** the engine is a pluggable adapter behind the `runner` seam — `claude -p` default; `codex`
  (already precedented) and open-model CLIs (Kimi/GLM/DeepSeek via OpenAI-compatible endpoints) as
  future adapters. The lock-in that matters is the *harness*, not the *model*.
- **D15** model routing is capability-tiered, cost-aware, **eval-gated**, per-project/per-client
  configurable (orchestration/planning → frontier; routine/high-volume → cheapest-that-passes;
  evaluation → an *independent* model), defaulting to Claude, overridable to all-open-model for
  enterprise clients.

## Review basis

An independent two-agent audit of the first planning set found the H0 core sound but 18 defects
concentrated at the phase seams (lost re-executable approval payload, duplicate run rows, unthreaded
pack/client context, uninjected vault key on the VPS, unspecified pack execution) plus that headless
PreToolUse-hook support is unverified. All are tracked in the roadmap and assigned to the phase that
owns them (kernel corrections applied now; Operate corrections folded when that track is built).

## Consequences

- Near-term build = the kernel (K0→K3), credential-free, deployable safely.
- The first operator project drives the Operate services' design; they land in the shared kernel.
- Real credentials, money, and client writes remain gated behind the Operate track's security review.

## Governance

Candidate only. Promotion to `active`/`canon` is a human-gated `brain-promote --approve` call. No
secrets recorded here (Hard Rule).
