# Design — Hermes AIOS improvement-proposal layer (Track A, Increment 1)

> **Status:** design (brainstormed 2026-07-23, Claude Opus 4.8). Terminal step of this
> design is an implementation plan via `writing-plans`.
> **Depends on:** the P0–P2 Hermes control plane (`infra/hermes-agent/`), the read-only
> `claude-code-operator` skill, and the project registry.

## Context & re-scope

The agreed plan order is: brain corrections → **P5 write-access guardrails** → P3 → P4.
Brainstorming P5 surfaced a sharper intent than "let Hermes write code": **Hermes AIOS is an
operations + continuous-improvement layer.** It **executes** already-built Claude Code projects and,
from what execution reveals, **proposes** improvements (enhancements, corrections, new features, even
new projects). It does not develop projects itself — the human + Claude Code do that.

This splits P5 into two tracks, sequenced safest-first:

- **Track A — improvement proposals** (this spec). Low risk; the distinctive AIOS feature.
- **Track B — execution** (deferred). B1 read-execute (run a project's reporting tools; credentials,
  no mutation), B2 live mutation (change live systems, e.g. the Ads account) behind per-action HITL +
  budget caps.

**Re-scope note (plan change):** because Track A Increment 1 is **read-only** (proposals are
documents), it needs **none** of the write-access guardrails P5 originally implied — no PAT, isolated
workspace, git hooks, or branch protection. That write-guardrail design is **shelved, not discarded**;
it returns only if/when proposals are delivered as draft PRs, or for Track B.

## Goal (Increment 1)

Hermes produces, on request or on a schedule, a **structured, read-only improvement proposal** for a
registered project — starting with `claude_google_ads`. The project is never modified.

## Design decisions (from brainstorming)

| Decision | Choice |
|---|---|
| Capability | Improvement **proposals** (not developer-on-demand) |
| Proposal form | **Written proposal only** — fully read-only |
| First project | `claude_google_ads` (read scope, unchanged) |
| Data sources | Project **code + structure** + any existing result artifacts (execution data arrives with Track B) |
| Output | Structured proposal doc → `/opt/data/proposals/<project>/<timestamp>.md`, surfaced to the user |
| Model tier | **Sonnet** (real analysis; Haiku too weak) |
| Trigger | **On-demand** now; **schedulable** via existing `hermes cron` |
| Monitoring | A proposals index (list/open past proposals) |

## Boundaries & integration with `claude_code` (no overlap, real benefit)

Verified 2026-07-23: `claude_google_ads` has **no** `claude_code` pipeline/brain installed (so **zero
overlap for the pilot**); `claude_code` itself has 15 improvement skills, telemetry
(`REFINE_RECOMMENDED`), and the Second Brain. The proposer stays clear of that machinery by **altitude
separation + delegation**, and *benefits* from it by consuming its outputs.

**Altitude:** `claude_code`'s machinery improves **skills/agents** (capability level, telemetry-driven,
self-contained). The proposer works at the **operations/project level** (features, corrections,
strategy, new projects) that the capability pipeline does not cover. Complementary, not redundant.

**Three hard "never duplicate" rules (encoded in the proposer skill):**
1. **Never** run `skill-refine`/`agent-refine` or mutate skills/agents — capability-level improvement
   **delegates** to the project's own pipeline if installed.
2. **Never** write to a project's brain `canon/`/`active` — human-gated via the candidate flow; the
   proposer only **reads** the brain.
3. **Never** reinvent telemetry / `REFINE_RECOMMENDED` / `skill-eval` — **read** and **cite** them.

**Benefit (all read-only) — the proposer consumes `claude_code` outputs when a project has them:**
- **Second Brain** — the proposer reads the brain's **files directly** (`canon/`, `decisions/`,
  `index.md`, `MEMORY.md`) with `Read`/`Grep`/`Glob` — the same content `brain-search`/`context-pack`
  index, but no script execution, preserving the no-Bash read-only posture → ground proposals in the
  project's canon/decisions/lessons; **avoid re-proposing rejected ideas**; align with governance.
- **Telemetry** (`usage-summary.json`, `REFINE_RECOMMENDED`) → real-usage-driven proposals.
- **Eval/audit reports** (`SKILL-EVAL.md`, `project-audit`) → grounded quality signals.
- For pipeline-equipped projects: **delegate** capability improvement and **surface** its
  `REFINE_RECOMMENDED` flags rather than re-deriving them.

**AIOS cross-project learning** (Hermes spotting patterns across projects) maps to the charter's
deferred **Central Operator Brain** — and must **reuse the brain kernel + candidate → human-promote
protocol**, never a parallel memory. Deferred; noted so it's designed right later.

## Components

1. **`claude-code-proposer` skill** (`infra/hermes-agent/skills/claude-code-proposer/SKILL.md`) —
   sibling to `claude-code-operator`. Read-only, registry-aware. Resolves a project → read `workdir`
   (`:ro`), runs `claude -p` (Sonnet, `--permission-mode plan`, `Read,Grep,Glob`) to analyze code +
   artifacts, and — when a `claude_code` brain/telemetry/eval outputs exist — reads them for grounding.
   Encodes the three "never duplicate" rules. Produces the structured proposal.
2. **Proposal template** — a fixed structure so output is consistent and actionable:
   ```
   # Improvement proposal — <project> — <timestamp>
   ## Summary            (2–3 sentences)
   ## Items (prioritized)
   - [P#] type: enhancement | correction | feature | new-project
         title:     …
         rationale: … (grounded)
         evidence:  file refs / observed facts / cited claude_code signals
         impact / effort: rough sizing
   ## Sources consulted   (code paths, brain hits, telemetry/eval reports)
   ```
3. **Storage** — `/opt/data/proposals/<project>/<timestamp>.md` (Hermes state, gitignored). Mirrors the
   cron-output pattern; persistent and reviewable.
4. **Monitor** — `infra/hermes-agent/bin/proposals-index.py`: list proposals per project with
   timestamp + summary; `--open <id>` prints one. Read-only. (Kept separate from `monitor-runs.py`,
   which stays focused on cron runs.)

## Flow

1. User (or `hermes cron`): *"Review `claude_google_ads` and propose improvements."*
2. Proposer resolves the project (read `workdir`, `:ro`).
3. `claude -p` (Sonnet, read-only) analyzes code + artifacts; if a brain/telemetry/eval exist, reads
   their files for grounding (never mutates them) and **returns the structured proposal as its output**
   (plan mode + `Read,Grep,Glob` means it produces content, it does not write).
4. **Hermes** captures that output and writes it to `/opt/data/proposals/<project>/<ts>.md` (its own
   state, never a project dir); surfaces the summary to the user.
5. User reviews → decides → builds chosen items with Claude Code locally.

## Guardrails

Unchanged read-only posture on **all** projects: `--permission-mode plan`, `Read,Grep,Glob`; no
credentials, no writable mount, no PAT, no write surface. The **only** artifact written is the proposal
document, into Hermes's own state — never into any project. The proposer refuses to modify projects and
refuses the three "never duplicate" actions.

## Verification

- Given `claude_google_ads`, Hermes produces a **grounded, structured** proposal (real file refs,
  sensible prioritized items, correct types).
- The project is **provably untouched** (git status clean in the mounted tree; no writes outside
  `/opt/data/proposals`).
- The proposal **persists** and is **listable** via the proposals index.
- Boundary check: when pointed at `claude_code` (which *has* the pipeline), the proposal **cites**
  brain/telemetry/eval signals and proposes operations-level items — it does **not** run refine/eval or
  write the brain.

## Deferred / future increments

- **Track A Increment 2** — proposals delivered as **draft PRs** (re-activates the shelved write-guardrail
  stack: isolated workspace, scoped PAT, pre-push hook, branch protection).
- **Track B** — execution: B1 read-execute (reporting tools; credential delivery), B2 live mutation
  (per-action HITL + budget caps).
- **Install the Second Brain into `claude_google_ads`** so the proposer can ground on governed memory
  (a write into that repo; do via `./install.sh` when ready).
- **Central Operator Brain** — cross-project AIOS learning, reusing the brain kernel.
