# Design — Kanban multi-agent read-only review pipeline (first AIOS orchestration use-case)

> **Status:** design (brainstormed 2026-07-24, Claude Opus 4.8). Terminal step is an
> implementation plan via `writing-plans`.
> **Depends on:** the P0–P3 Hermes control plane (`infra/hermes-agent/`), the read-only
> proposer layer (P5 Track A: `save-proposal.py`, `proposals-index.py`, the registry).

## Context & purpose

Hermes Kanban is a durable, multi-agent orchestration system: every task a row in `kanban.db`,
every worker a **named OS-process agent**, with dependencies, structured handoffs, comments (HITL),
crash recovery, and an audit trail. It is the runtime realization of the charter's north-star —
*"teams of agents specialized in different areas that operate independently and coordinate when a task
spans areas"* — whose runtime the charter explicitly **deferred to Hermes** (capability **C2**:
agent/workflow management).

**This spec builds the first, safe instance of that layer.** Purpose:
1. Prove durable multi-agent coordination (named profiles, dependencies, handoffs, a coordinator).
2. Establish the **hardened-worker confinement pattern** every future Kanban workflow inherits —
   locked in on a zero-stakes read-only target *before* anything touches a client system.
3. Produce genuinely useful output (a multi-perspective improvement proposal on real code).
4. Serve as the **template** later re-instantiated with domain specialists (`ads-analyst`, etc.) for
   the monetizable client-services fleet.

Bridges the single-agent proposer (P5 Track A) to true multi-agent teams.

## Goal (this increment)

Given `make-review-board.py --project claude_code`, the Kanban dispatcher runs three **provably
confined** specialist workers in parallel (architecture, tests, risks), then a synthesizer that fuses
their handoffs into one improvement proposal — persisted to Hermes state, with the project provably
untouched.

## Design decisions (from brainstorming)

| Decision | Choice |
|---|---|
| First workflow | Read-only multi-agent **review pipeline** |
| Target project | `claude_code` (rich, non-fixture; respects proposer boundaries) |
| Decomposition | **Fixed template** — deterministic script, no LLM orchestrator |
| Profiles | `architect`, `test-analyst`, `risk-analyst` (specialists) + `synthesizer` (coordinator) |
| Analysis model | Each worker analyzes **directly** (no `claude -p`) on its per-profile OpenRouter model |
| Persistence | Trusted out-of-worker step → `save-proposal.py` |

## Worker confinement (the security core)

A Kanban worker is a full Hermes agent; **its own capabilities are the security surface, not the
analysis it performs.** Every worker is bounded by **five independent layers** so the AIOS objectives
are *provable, not hoped-for*:

1. **`:ro` project mounts** — OS-enforced; a worker cannot modify any project regardless of behavior.
2. **Custom `review-readonly` toolset** — the worker profile's `config.yaml` enables ONLY a custom
   toolset containing `read_file`, `search_files`, `skill_view`, and the **minimal kanban subset**
   (below). It therefore has **no `write_file`/`patch`, no terminal/Bash, no `execute_code`, no
   `delegate_task`, no browser, no web/network.** (Stock `file` bundles read+write, so a custom
   toolset is required; Hermes supports custom toolsets via `platform_toolsets` — the exact
   registration step is pinned in the plan.)
3. **Minimal kanban subset** — `kanban_show, kanban_complete, kanban_comment, kanban_heartbeat,
   kanban_block` only. The **fan-out** tools (`kanban_create`, `kanban_link`, `kanban_unblock`) are
   withheld — workers can't spawn spurious tasks. (Safe because decomposition is deterministic.)
4. **`scratch` workspace** — ephemeral cwd, deleted on completion.
5. **`--max-runtime` + `--failure-limit`** — the dispatcher SIGKILLs overruns and bounds retries.

**Why no `claude -p`:** running it needs the terminal tool, which reopens Bash and breaks confinement.
Workers analyze **directly** (read the project with `read_file`/`search_files`, reason with their
model). Trade-off: analysis runs on the worker's OpenRouter model instead of Sonnet-via-`claude -p` —
a per-profile model choice (a stronger OpenRouter model raises quality; the whole pipeline stays
OpenRouter-only, no Anthropic executor). We accept this to keep confinement provable.

**Prompt-injection containment (matters for the client-fleet future):** a worker ingests project
content, which in a real client repo could be adversarial. With this confinement, the worst case is a
*misleading analysis/handoff* — never a write, command, network exfil, or spawned agent.

## Boundaries with `claude_code` (unchanged from the proposer)

The three never-duplicate rules carry over and become **partly hard-enforced** by the toolset:
1. Never run `skill-refine`/`agent-refine` or mutate skills/agents — *no terminal ⇒ cannot run them.*
2. Never write a project's brain `canon`/`active` — *no write tool ⇒ cannot.*
3. Never reinvent telemetry/`REFINE_RECOMMENDED`/`skill-eval` — read and cite (instruction).

## Components

1. **Custom toolset `review-readonly`** — registered in Hermes (`platform_toolsets`): exactly
   `read_file, search_files, skill_view, kanban_show, kanban_complete, kanban_comment,
   kanban_heartbeat, kanban_block`.
2. **Four confined profiles** — `architect`, `test-analyst`, `risk-analyst`, `synthesizer`, each
   created `--no-skills`, `describe`d for their role, and pinned to `toolsets: [review-readonly]` in
   their per-profile `config.yaml` (+ a capable OpenRouter model).
3. **`claude-code-reviewer` skill** (`infra/hermes-agent/skills/claude-code-reviewer/SKILL.md`) —
   force-loaded per task (`--skill`). Two modes: **analysis** (read the project for your assigned
   dimension; `kanban_complete` with a structured handoff `{dimension, findings[], evidence[]}`) and
   **synthesis** (read the three parent handoffs; produce one combined proposal in the proposer's
   template; `kanban_complete` with the proposal as metadata). Encodes the three boundary rules.
4. **`make-review-board.py`** (`infra/hermes-agent/bin/`, deterministic, trusted) — resolves the
   project from `/opt/registry`, creates the fixed 4-task board: `t1 analyze-architecture→architect`,
   `t2 analyze-tests→test-analyst`, `t3 analyze-risks→risk-analyst` (parallel), `t4 synthesize`
   (`--parent t1 t2 t3`) `→synthesizer` — each `--workspace scratch`, `--max-runtime` set,
   `--skill claude-code-reviewer`.
5. **Persistence step `persist-review-proposal.py`** (trusted, out-of-worker) — reads the completed
   synthesis task's proposal metadata from `kanban.db` and pipes it to the hardened `save-proposal.py`
   (which treats content as data, never executing it) → `/opt/data/proposals/<project>/<ts>.md`.
   For this increment it is a **follow-up call** run after synthesis completes (invoked by the
   operator, or by `make-review-board.py --wait` which polls the board until synthesis is `done`);
   wiring it as an automatic gateway-dispatcher hook is deferred.
6. **Reuse:** `save-proposal.py`, `proposals-index.py`, the registry — unchanged.

## Flow

```
make-review-board.py --project claude_code            → 4 tasks on the board
  dispatcher spawns (confined, --max 2):
     architect | test-analyst | risk-analyst          (parallel; read-only; direct analysis)
     each → kanban_complete(handoff {dimension, findings, evidence})
  all 3 done → synthesizer promoted → reads 3 handoffs → combined proposal → kanban_complete(metadata)
  persist-review-proposal.py → save-proposal.py → /opt/data/proposals/claude_code/<ts>.md
Observe live on the dashboard Kanban board (or `hermes kanban watch`);
read the result via `proposals-index.py`.
```

## Alignment with AIOS objectives

- **C2 orchestration / charter north-star:** three "operate independently" specialists + one
  "coordinate across areas" synthesizer = the charter's team pattern, in miniature, on Hermes's
  durable runtime.
- **Continuous-improvement function:** the output is a multi-perspective improvement proposal (the
  proposer, elevated to a team).
- **C5 safety / governance:** the confinement model *is* the governance for paid work, proven here
  first. **Commercial objective:** indirect — this is the reusable template for domain specialists.

## Verification

- Board created with the exact 4-task shape; parallel specialists complete with structured handoffs;
  synthesizer promoted only after all three; combined proposal persisted + listable.
- **Confinement proof:** a worker's resolved toolset contains none of `write_file`/`patch`/`terminal`/
  `process`/`execute_code`/`delegate_task`/browser/web; the project's git tree is clean before AND
  after; no writes outside `/opt/data`.
- **Fan-out proof:** workers lack `kanban_create`/`kanban_link`.
- Visible on the dashboard Kanban board.

## Deferred / open

- **Custom-toolset registration mechanism** — confirm the exact `platform_toolsets` definition step
  (referenced as supported) during implementation; if unavailable, fall back to group-level
  `[file, kanban, skills]` + document the `write_file`→`/opt/data` residual honestly.
- Dynamic LLM decomposition; write-capable pipelines (dev orchestration); **domain-specialist
  profiles** for client-services (the monetizable re-instantiation); a persistence hook wired into the
  gateway dispatcher (vs. the manual follow-up call).
