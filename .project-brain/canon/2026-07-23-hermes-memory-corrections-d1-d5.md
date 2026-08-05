---
type: decision
status: canon
title: "Memory corrections D-1…D-5 — 'Hermes' = adopted Nous Hermes Agent (control plane over Claude Code), not a custom-built orchestrator; + record the commercial objective"
description: "Human-gated correction record. Canon (ai-os-charter) and the active Eve synthesis still frame 'Hermes' as a FUTURE, CUSTOM orchestrator layer to be built ('not yet implemented / not yet started'). The confirmed, now-implemented reality: Hermes = Nous Research's Hermes Agent, ADOPTED as the control plane that operates Claude Code projects via `claude -p`, running locally through P2. Specifies the exact canon/active edits, reframes the Eve pattern (D-2), disambiguates the term (D-4), and captures the previously-unrecorded commercial objective (D-5)."
tags: [hermes, nous-hermes-agent, correction, canon-correction, aios, control-plane, commercial-objective, governance, eve-pattern]
timestamp: 2026-07-23
sources: 
promoted_at: 2026-07-23
---

# Memory corrections D-1…D-5 (decision candidate)

> **Status: candidate** — awaiting `brain-promote --approve`. This record does NOT edit `canon/` or
> `decisions/active/` itself (Hard Rule: promotion is human-gated). It specifies the corrections to
> apply on approval. It **builds on** the adoption candidate `2026-07-21-adopt-nous-hermes-agent-runtime.md`
> (the "what we adopt" decision) and adds the precise memory edits + the commercial objective.

## Why now

`canon/2026-07-17-ai-os-charter.md` and `decisions/active/vercel-eve-fs-architecture-adoption.md` were
written when "Hermes" was (mis)understood as a **custom orchestrator to be built** — the charter lists
it under *Deferred/open* as *"the persistent background orchestrator… Not yet started,"* and the Eve
synthesis calls it *"a future orchestrator layer of THIS project… Not yet implemented."* That framing
is now doubly wrong: (1) "Hermes" is **Nous Research's Hermes Agent**, an existing product we **adopt**
(not build), and (2) it is **already running** — P0–P2 shipped this session (local Docker control
plane on OpenRouter/DeepSeek, operating two real Claude Code projects via `claude -p`). Canon must
match reality so future decisions judge against the truth.

## The corrections

### D-1 (major) — canon + active still say "custom-built / to build"
**Wrong:** charter frames Hermes as a future custom orchestrator; the Eve synthesis frames it as "a
future orchestrator layer of THIS project… not yet implemented."
**Correct:** **Hermes = Nous Research's Hermes Agent**, ADOPTED as the persistent, model-agnostic
**control plane** that operates Claude Code projects by invoking `claude -p` in each project's dir
(via the bundled `claude-code` skill). Not custom-built. Governed as a **runtime dependency** (adoption
decision + security-audit gate), not the reference-repo pattern-source model.
**Edit on approval:**
- `ai-os-charter.md` line ~35: "the future Hermes orchestrator" → "the **adopted** Nous Hermes Agent
  control plane (operates Claude Code via `claude -p`)".
- `ai-os-charter.md` lines ~58–59 (Deferred/open): remove Hermes from *"Not yet started"* — move to a
  *"Built / in progress"* status: **adopted; P0–P2 shipped (local); P3–P5 remain** (interaction
  surfaces, VPS, write-guardrails). The credential-vault/HITL/budget items remain deferred to the
  first monetizable product.
- `vercel-eve-fs-architecture-adoption.md` lines ~24–25: "Hermes Agent = a future orchestrator layer
  of THIS project… Not yet implemented" → "Hermes Agent = **Nous Research's** Hermes Agent, adopted as
  the control plane; the Eve **pattern** informs the registry we build for it (see D-2)."

### D-2 — the Eve "filesystem-as-registry loader" premise is superseded; keep the pattern
**Wrong:** Eve pattern framed as the discovery **loader** for a custom Hermes orchestrator.
**Correct:** Nous Hermes has its own skills/registry discovery, so Eve is **not** a loader here. The
**pattern** (convention-over-config folder registry) still validly informs what we actually built:
`infra/hermes-agent/registry/projects.yaml` (the project registry) and the operator skill. **Reframe,
don't delete** the Eve synthesis — downgrade it from "the orchestrator's loader" to "a design
influence on the adopted-Hermes project/agent/workflow registry."

### D-3 — supersede the custom-kernel roadmap
**Supersede:** `decisions/candidates/2026-07-21-hermes-definitive-roadmap.md` and the
`docs/superpowers/…hermes-*` custom-kernel docs (custom-build master + H0–H3 + K2). **Replacement =**
the adoption candidate `2026-07-21-adopt-nous-hermes-agent-runtime.md` **+ this correction record**.
On approval, mark the roadmap candidate obsolete (retire) rather than promote it.

### D-4 — disambiguate the term
Henceforth in memory, **"Hermes" = Nous Research Hermes Agent** (the adopted product). Any earlier use
meaning "a custom orchestrator we would build" is retired. Where ambiguity risk exists, write "Nous
Hermes Agent."

### D-5 — record the commercial objective (currently unrecorded)
**Gap:** the charter's north-star is purely technical ("self-evolving AI OS"). The **commercial
objective is not recorded** anywhere in memory.
**Capture (new, first-class objective):** the purpose of the Claude Code AIOS (Nous Hermes Agent +
Claude Code) is to **manage AI agents and AI workflows across projects and to monetize** — via
client-facing AI products/services. Candidate revenue paths (plan P6, choose one pilot): **client
AI-agent services** (Google Ads / WordPress / analytics management — highest fit), selling the
AIOS/workflow tool itself, or productized AI workflows. **First pilot taking shape:** the
`claude-google-ads` project (DentalEdge Solutions MCC), now registered as the second Hermes-operated
project (read-only until P5 write-guardrails). Future decisions should be judged against **both** the
technical north-star **and** this commercial objective.

## Implemented reality this correction reflects (2026-07-23)

- **Adopted & running (local):** derived image (`nousresearch/hermes-agent` pinned + `claude` CLI);
  `hermes gateway run`; dashboard loopback-only.
- **Two model roles:** control plane on **OpenRouter / `deepseek/deepseek-v3.2`** (cheap OSS, economy);
  executor **`claude -p` direct on Anthropic**, per-task `--model` tiering. (OpenRouter's endpoint is
  OpenAI-compatible only and Claude Code is Claude-native, so the executor stays direct.)
- **Management layer (P2):** `registry/projects.yaml`; `claude-code-operator` skill (read-only,
  registry-aware, model-tiered, delegates to bundled `claude-code`); `hermes cron` scheduling;
  `bin/monitor-runs.py`. Two real projects registered: `claude_code`, `claude_google_ads`.
- **Posture:** read-only project mounts (writes gated to **P5**); no secrets in git; keys only in
  gitignored `.env`, executor key projected into claude's config by an init sidecar.
- **Remaining:** P5 write-guardrails → P3 interaction surfaces → P4 VPS (agreed order 2026-07-23).

## What promotion should do

1. Apply the D-1/D-2/D-4 edits to `canon/2026-07-17-ai-os-charter.md` and
   `decisions/active/vercel-eve-fs-architecture-adoption.md` (correct framing + Hermes status).
2. Promote the **commercial objective (D-5)** into canon alongside the technical north-star.
3. Retire the superseded custom-kernel roadmap candidate + `docs/superpowers/…hermes-*` (D-3).
4. Keep the adoption candidate + this correction record as the decision trail.
