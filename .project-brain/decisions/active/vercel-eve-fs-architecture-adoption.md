---
type: synthesis
status: active
title: "Vercel Eve filesystem-centric architecture — adoption analysis for the Hermes orchestrator layer"
description: "Whether to adopt Vercel Eve's filesystem-as-registry pattern into the planned Hermes orchestrator layer. Recommendation: adopt the PATTERN (convention-over-config folder registry + evals-as-deploy-gate), not the Eve runtime; keep it framework-agnostic and VPS-friendly."
tags: [architecture, agents, orchestrator, hermes, eve, filesystem-registry, adoption, deferred]
timestamp: 2026-07-16
authority: synthesis
sources: [https://github.com/vercel/eve, https://eve.dev/docs/introduction, https://github.com/coleam00/eve-analyst, Session analysis 2026-07-16 (Claude Opus 4.8); web sources fetched + summarized — verify beta API details before building]
promoted_at: 2026-10-05
originally_promoted_at: 2026-07-16
---

# Vercel Eve filesystem-centric architecture — adoption analysis

> **Status: candidate** (synthesis authority — not a decision). Promote via `brain-promote --approve`
> only after the reference-repo audit (below) is run. Raw Eve source material still needs to land in
> `support/sources/` at raw-source authority per the Second Brain protocol.

## Context / decision framed

- **Objective:** adopt Vercel Eve's filesystem-centric architecture so the **directory layout acts as
  the agent/tool registry**, enabling team scaling without fragile runtime configuration.
- **Confirmed scope (2026-07-16):**
  - **Hermes Agent** = a *future* orchestrator layer of THIS project (persistent background process on a
    Hostinger VPS, Ubuntu/Docker). Not yet implemented.
  - **Adoption scope = the PATTERN only** (filesystem-as-registry convention), NOT the Eve TS runtime.
  - Deliverable = this synthesis candidate first; governance pipeline (register + audit) deferred until
    approved.

## What Eve is (verified, beta)

Vercel open-source, **filesystem-first** agent framework. Governing principle: *"a file's location says
what it does… adding a file automatically registers it"* — the directory layout **is** the registry, no
separate config. TypeScript/Node, Claude-configurable. Standard layout:

```
agent/
├── agent.ts          # model + runtime config
├── instructions.md   # always-on system prompt
├── tools/            # typed functions (TS + Zod); file path → tool name
├── skills/           # on-demand markdown procedures
├── subagents/        # delegated specialist agents (teams)
├── channels/         # HTTP / Slack / Discord
├── hooks/            # lifecycle handlers
├── sandbox/          # controlled code execution
├── schedules/        # cron jobs
└── connections/      # external MCP / OpenAPI services
```

Built-ins: **durable sessions** (pause/resume, via the open-source Workflow SDK), **human-in-the-loop**
(pause-for-approval-then-resume), **sandboxed execution** (Vercel Sandbox, `networkPolicy: deny-all`),
**subagents**. `eve-analyst` confirms the production shape: `evals/` as a **deploy gate**, a read-only
SQL guard, HITL approval on expensive ops, deny-all sandbox.

## The decision that determines everything: pattern vs. framework

| | **Pattern** (adopt) | **Framework runtime** (reject for now) |
|---|---|---|
| Take | Standard folders + a discovery loader (directory traversal → registry); convention over config | Eve's TS runtime, Workflow SDK, Vercel Sandbox, channels |
| Lock-in | None — framework-agnostic, any host | Vercel ecosystem (Sandbox + managed durability are hosted) |
| Hostinger VPS fit | Excellent (pure convention + filesystem) | Partial — self-host substitutes for Sandbox/durability anyway |
| Effort / risk | Low–moderate | High; Eve is **beta** (bad footing for a long-lived orchestrator) |

**Chosen:** pattern only. On a self-hosted VPS, Eve's differentiated pieces are Vercel-hosted; rebuilding
them in Docker means keeping the lock-in surface without the managed benefit.

## Why the fit is strong: this project already lives the pattern

`claude_code` implements Eve's pattern almost point-for-point — evidence it works at production scale in
this exact governance style, and the base Hermes will build on:

| Eve concept | Already here |
|---|---|
| `instructions.md` | `CLAUDE.md` |
| `tools/` + `skills/` as registry | `skills/<name>/SKILL.md`, discovered dynamically (`find skills/ -mindepth 1 -maxdepth 1 -type d`); rule: never hardcode skill names |
| `subagents/` | `.claude/agents/*.md` |
| `hooks/` | `hooks/brain/*` (SessionStart, PreToolUse, …) |
| `evals/` as deploy gate | `evals/` + `SKILL-EVAL.md` + run-manifest integrity gates |
| filesystem-native memory | the `.project-brain/` Second Brain capsule |

**Implication:** for Hermes, this is *formalize + extend an existing, proven pattern*, not adopt-from-scratch.

## Long-run benefits (of the pattern)

- **Zero-config scaling** — new agent/tool = new folder/file, auto-registered; kills the "fragile runtime
  config" named as the problem.
- **Git-native reviewability** — capability changes are diffs; PR-review a new agent like code.
- **Composability / teams** — `subagents/` gives team hierarchies without an orchestration DSL.
- **Self-documenting** — the tree *is* the architecture doc; faster onboarding.
- **Testability gate** — `evals/` before deploy (the discipline this repo already runs).
- **Channel portability** — one agent behavior across HTTP / Slack / terminal.

## Recommended implementation strategy (pattern-only, Hermes as future orchestrator)

1. **Governance first (deferred until this candidate is approved):** `reference-repo-add` for
   `vercel/eve` + `coleam00/eve-analyst`; `reference-repo-audit` (record beta + Vercel-ecosystem risk,
   `install_policy: do-not-install-directly`). Then `reference-repo-pattern-extract` → refine this doc.
2. **Define the Hermes standard layout** — adopt Eve's folder vocabulary for the orchestrator:
   `hermes/agent/{instructions.md, tools/, skills/, subagents/, hooks/, schedules/}` (+ `channels/` if/when
   multi-surface). Reuse this repo's existing `skills/` and `.claude/agents/` conventions rather than
   inventing new ones.
3. **Build a thin discovery loader** — a filesystem walker that turns those folders into Hermes'
   in-memory registry at boot (and on change). ~80% of the value at ~10% of the cost; no Eve dependency.
4. **Pilot with one agent** — restructure a single agent into the standard layout, prove the loader,
   template it, then scale teams by adding folders.
5. **Add an `evals/` deploy gate for Hermes** — mirror the SKILL-EVAL discipline: an agent can't deploy
   on a red gate.
6. **Self-hosted sandbox + HITL on the VPS** — Docker (optionally gVisor/Firecracker) with deny-all
   networking as the Vercel-Sandbox substitute; a durable pause/resume queue (Redis/SQLite-backed) for
   human-in-the-loop, since there's no Vercel managed durability. **This is the real engineering** — the
   folder pattern is easy; secure self-hosted code execution is the hard part.
7. **Capture in the brain** — promote this candidate once audited; log the Hermes layout decision.

## Risks / caveats

- **Eve is beta** — API churn; if the runtime is ever revisited, pin/vendor.
- **Sandboxing self-hosted is the hard problem**, not the filesystem convention.
- **Vercel-ecosystem gravity** — only relevant if the framework decision is ever reopened.
- **Source fidelity** — Eve facts here came via a page summarizer; verify specifics against the live docs
  before building the loader.

## Open questions (for the eventual Hermes phase)

- Loader language/runtime for Hermes (Node, to match this repo? or other)?
- Does Hermes reuse this repo's `.claude/agents/` verbatim, or a parallel `hermes/…/subagents/` tree?
- Durable-session backing store on the VPS (Redis vs SQLite vs Postgres — note `gbrain` Postgres is
  already a registered retrieval option).
- Where the security guard for tool execution lives (extend the existing PreToolUse hook pattern?).

## Next step

On approval: run step 1 (register + audit Eve via the reference-repo pipeline), drop the raw Eve docs
into `support/sources/`, then `brain-promote` this synthesis.
