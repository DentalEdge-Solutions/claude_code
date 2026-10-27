---
type: decision
status: canon
title: "Adopt Nous Research's Hermes Agent as the AIOS runtime / control plane over Claude Code projects"
description: "Adopt the real Nous Research Hermes Agent (official Docker image) as the persistent, model-agnostic control plane that connects to and operates Claude Code projects (via the bundled claude-code skill running `claude -p`), forming a 'Claude Code AIOS' for managing AI agents/workflows and, ultimately, monetization. Governed as a runtime dependency (adoption decision + security-audit gate), NOT via the reference-repo pattern-source model."
tags: [hermes, nous-hermes-agent, runtime, control-plane, aios, adoption, governance, docker, claude-code, correction]
timestamp: 2026-07-21
reviewed_at: 2026-10-27
sources:
  - .project-brain/canon/2026-07-17-ai-os-charter.md
  - .project-brain/decisions/superseded/vercel-eve-fs-architecture-adoption.md (was in decisions/active/)
  - .project-brain/decisions/superseded/2026-07-21-hermes-definitive-roadmap.md (was in decisions/candidates/)
  - ~/.claude/plans/iterative-squishing-church.md (session plan of record)
  - "Session 2026-07-21 (Claude Opus 4.8): user clarification that 'Hermes' = Nous Research Hermes Agent; recon of NousResearch/hermes-agent"
  - https://hermes-agent.nousresearch.com/docs/
  - https://github.com/nousresearch/hermes-agent
promoted_at: 2026-10-27
originally_promoted_at: 2026-08-05
---

# Adopt Nous Hermes Agent as the AIOS runtime (decision)

> **Status: canon** (first promoted 2026-08-05; re-promoted 2026-10-05 and 2026-10-27). Corrects a prior
> misunderstanding baked into memory (see "Supersedes / corrects").
>
> **Reviewed 2026-10-27 (weekly review):** still the adopted runtime. It runs on the Hostinger box (canon: Phase 6
> passed on the box, 2026-09-22; security review #11, 2026-10-14). It is read-only against the Google Ads accounts,
> with no write credential for them (canon: D3.2, 2026-09-29); its other write path, operator-run draft-PR delivery
> (Track A), is dormant since its bot token lapsed on 2026-10-23. Under Track A (active decision of 2026-10-22) it
> proposes improvements and the owner and Claude Code build them. The items under "Supersedes / corrects" are done:
> the Eve decision and the custom-kernel roadmap are in `decisions/superseded/`, and the charter's correction is
> applied in its 2026-10-27 revision.

## Decision

Adopt **Nous Research's Hermes Agent** (the real open-source product, official Docker image
`nousresearch/hermes-agent`) as the project's **runtime / control plane**. Hermes is the persistent,
model-agnostic, multi-channel front door; it connects to and **operates Claude Code projects** (this
repo + future derived ones) by invoking `claude -p` in each project's directory — using Hermes's
**official bundled `claude-code` skill** and its `terminal.backend: local` execution. Combined,
**Hermes Agent + Claude Code = a "Claude Code AIOS"** for managing AI agents and AI workflows across
projects, and the foundation for monetizable client-facing AI products.

**Not** built as a custom orchestrator; **not** governed via the reference-repo pattern-source model.
It is a **runtime dependency**, governed by: (1) this adoption decision, and (2) a **security-audit
gate** before it holds any real credential or reaches the VPS.

## Why

- The user confirmed "Hermes" always meant Nous Hermes Agent; adopting it obviates building a custom
  runtime and directly delivers model-agnosticism, always-on operation, gateway/channels, scheduler,
  memory, and self-hosting.
- Hermes drives Claude Code as-is (no migration of packs/second-brain/eval-pipeline needed) — Claude
  Code keeps its skills/agents/packs/governance; Hermes is the control plane.
- Official Docker image + official bundled `claude-code` skill mean minimal custom code (a ~5-line
  derived image to add the `claude` CLI; audit/adapt the bundled skill).

## How (summary; full plan in the session plan file)

- Official image + thin **derived image** (`FROM nousresearch/hermes-agent:<pinned>` + add `claude`).
- Persistent backend `hermes gateway run`; API server via `API_SERVER_*`; dashboard on 9119
  (loopback). State volume `/opt/data`. Project dirs mounted; `terminal.backend: local` + `workdir`.
- Local-first → hardened VPS (bind loopback + SSH/Tailscale tunnel; auth required for any public bind).
- Monetization is the next deliverable ON the AIOS (client AI-agent services / the tool itself /
  productized workflows).

## Governance

Runtime-dependency governance (chosen 2026-07-21): adoption decision + **security-audit gate** before
real keys/VPS (review image, `Dockerfile`, `docker-compose.yml`, `install.sh`, docker docs, and the
bundled skill's `--dangerously-skip-permissions`/tmux use; pin image tag/digest; optional
`ecc-agentshield`). Guardrails on which projects Hermes may touch and read-vs-write scope; writes to
real/paid systems require the credential-vault/HITL/budget requirements (kept from the prior plan) —
built with the first monetizable product. No secrets in memory (Hard Rule). Promotion is human-gated.

## Supersedes / corrects

- **Corrects** the custom-build framing of "Hermes" in `canon/2026-07-17-ai-os-charter.md` and
  `decisions/active/vercel-eve-fs-architecture-adoption.md` (they describe building a custom
  orchestrator / thin discovery loader — the accurate objective is **adopt Nous Hermes Agent**). These
  canon/active entries need human-gated correction.
- **Supersedes** the custom-kernel roadmap candidate
  `.project-brain/decisions/candidates/2026-07-21-hermes-definitive-roadmap.md` and the
  `docs/superpowers/…hermes-*` custom-kernel docs (retire/mark obsolete on approval).
