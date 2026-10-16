# Claude Code Skill & Agent Pipeline Toolkit

Infrastructure for finding, vetting, customizing, and evaluating Claude Code skills and agents. Run `/project-setup` once to configure your project, then use the pipeline to source and install capabilities from the ecosystem rather than building from scratch.

## Pipeline Overview

```
project-setup → project-audit
                     │
                     ├── Skill pipeline ──────────────────────────────────────────────────┐
                     │   skill-scout → skill-audit → skill-adapt → skill-eval → skill-refine │
                     │                                    │                                   │
                     │                    (missing agent dependency detected)                 │
                     │                                    ↓                                  │
                     └── Agent pipeline ──────────────────────────────────────────────────── ┘
                         agent-scout → agent-audit → agent-adapt → agent-eval → agent-refine
```

`project-setup` feeds both pipelines via `evals/project-context.json` (9 fields: project name, stack, workflow terms, installed skills, key phrases, artifact paths, hooks, MCP servers, plugins) and optionally seeds them with signals from up to 3 GitHub reference repos.

`project-audit` runs a security scan of the `.claude/` configuration before any skill or agent is sourced or installed.

---

## How Evaluation Works (Plain English)

Before trusting a skill or agent, the pipeline tests it the way you'd test a new employee: give it realistic tasks, compare its work against someone doing the same tasks without its help, and check the evidence of what it actually did — not what it *says* it did.

**1. Write the test questions.** A script reads the skill's definition file and automatically generates 9 test scenarios: some that clearly should trigger it, some phrased indirectly, some that should *not* trigger it, and a few trick questions designed to tempt it into activating when it shouldn't. Three of the nine are tailored to this specific project's stack and vocabulary.

**2. Run each scenario twice — with and without the skill.** For every scenario, one test run has the skill loaded and a twin run doesn't. The "without" run is the baseline: if the skill doesn't beat it, the skill isn't adding value.

**3. Collect hard evidence, not self-reports.** A harvester script inspects what each run actually left behind — did the skill genuinely activate (a specific token that only appears on a real invocation), were the promised files really written to disk, were the workflow steps really completed? The test runs' own claims about what they did are ignored for scoring; only verified evidence counts.

**4. Grade and score five metrics.** Each scenario gets a 0–10 score, rolling up into: pass rate (does it do the job?), trigger accuracy (does it activate at the right times?), resilience (does it resist the trick questions?), project fit (does it speak this project's language?), and context footprint (how much it costs to load). Each metric has a pass threshold, and the result is a one-page report with a recommendation: healthy, refine, or rewrite.

**5. Fix what failed, automatically.** If a metric fails, a refine loop makes one targeted change at a time (to the description, the workflow, the examples, etc.), re-runs the eval, and keeps the change only if the scores improve — up to 10 iterations.

**6. Get a second opinion from a different AI.** Codex — a separate model with no stake in the outcome — can independently judge the scenarios, and in "native audit" mode it reviews a finished eval's real transcripts and report to check whether the evidence actually supports the conclusions. Where the two models disagree, a human decides.

**7. Keep the graders honest.** A deliberately broken skill with 4 known, documented defects lives in `fixtures/`. Periodically the whole pipeline runs against it: if the process catches all 4 defects, the process works (see `fixtures/GATE-RUNBOOK.md`).

**8. Watch real usage over time.** Lightweight, privacy-safe telemetry counts how often each skill gets used and how often users correct or reject its output. A skill that's frequently corrected in real life gets flagged for refinement — the loop feeds itself.

The through-line for all of it: **evidence over claims, comparison over intuition, and a second pair of eyes on the process itself.**

---

## Skills

### `project-idea`

Guided interview that turns a vague idea into a structured `PROJECT-BRIEF.md` — problem, target user, core features, out-of-scope items, tech direction, and success criteria, one question at a time. Run before `project-setup` on any greenfield project; `project-setup` reads the brief to pre-fill its recommendations.

**Triggers:** "I have an idea for a project", "help me figure out what to build", "I want to start a new project"

---

### `project-setup`

Guided interview that produces `CLAUDE.md` and `evals/project-context.json`. Scans existing config files (`.claude/settings.json`, `.mcp.json`, `~/.claude/settings.json`) to auto-detect active hooks, MCP servers, and installed plugins before the interview begins. Optionally fetches conventions, stack, commands, rules, directories, and skill/agent names from up to 3 GitHub reference repos. The output powers the rest of the pipeline.

**Triggers:** "set up my project for Claude Code", "my project-context.json is empty", "help me configure CLAUDE.md"

---

### `project-audit`

Security scan of the Claude Code project configuration using [ecc-agentshield](https://www.npmjs.com/package/ecc-agentshield). Runs 102 rules across 5 categories — Secrets, Permissions, Hooks, MCP Servers, Agents — and returns an A–F grade. Offers auto-fix for the 8 most common safe issues. Advisory by default; surfaces critical findings before any skill installation proceeds.

**Triggers:** "audit my project security", "check my Claude Code setup for secrets", "scan before installing new skills"

---

### `repo-audit`

Deep multi-layer audit of any public GitHub repository, using 8 parallel layer agents (the `repo-audit-*` analysts) backed by Repomix. Produces machine-readable JSON + human-readable Markdown reports at `docs/audits/`, covering runtime, framework, database, testing, CI/CD, auth, AI/LLM, and Claude Code config. `--pipeline` injects findings into `evals/project-context.json`; `--layer` runs a subset; `--estimate` previews token cost first. Also invoked by `project-setup` Phase 0 with `--deep`.

**Triggers:** "audit this repo", "scan this GitHub repo", "extract stack from <url>"

---

### Skill Pipeline

#### `skill-scout`
Searches GitHub and known registries for existing skills that match a capability. Reads `evals/project-context.json` as a pre-flight check — if rich context is present (non-empty `stack` and `key_phrases`), it pre-fills search parameters without asking redundant questions. Returns a ranked shortlist scored on trigger precision, instruction clarity, context footprint, project fit, provenance, and conflict risk.

**Triggers:** "find a skill for X", "is there a skill that can Y", "source a skill"

#### `skill-audit`
Security gate for sourced skill files and agent definitions. Scans SKILL.md content, agent `.md` files, and `settings.json` for prompt injection, hardcoded secrets (Anthropic/GitHub/AWS keys), overly permissive allow rules, and malicious scripts using a 47-pattern static scanner across 5 categories. Returns PASS / FLAG / BLOCK before anything is installed. Complements `project-audit` (which runs AgentShield's 102-rule scan; this is self-contained with no external dependencies).

**Triggers:** "audit this skill", "check skill security", "scan this skill from GitHub"

#### `skill-adapt`
Rewrites a PASS-audited skill to match the project's terminology, workflow gates, and installed skill ecosystem. Reads all 9 fields from `evals/project-context.json`: uses `hooks` to avoid adding redundant workflow steps already covered by PostToolUse automation, `mcp_servers` to add prerequisite notes when a required integration is missing, and `plugins` to catch capability conflicts. Detects agent dependencies in the adapted skill and warns if any are missing from `.claude/agents/`.

**Triggers:** "adapt this skill", "customize this skill for my project", "install this skill"

#### `skill-eval`
Measures an adapted skill's effectiveness using structured test scenarios and LLM-judge scoring. Generates 9 scenario types when project context is available (6 without):

| # | Type | Triggers? | Tests |
|---|------|-----------|-------|
| 1 | `direct` | ✓ | Cold-start primary trigger |
| 2 | `paraphrased` | ✓ | Same intent, different words |
| 3 | `edge_case` | ✓ | Mid-workflow entry |
| 4 | `negative` | ✗ | Explain without invoking |
| 5 | `semantic` | ✓ | Synonym verb variations |
| 6 | `adversarial` | ✗ | Skill vocabulary in wrong scope — must not fire |
| 7 | `project-native` | ✓ | Project terminology injected |
| 8 | `project-workflow` | ✓ | After a sibling skill |
| 9 | `multi-turn` | ✓ | Mid-session continuation framing |

Produces **5 metrics**: eval pass rate (≥ 80%), trigger accuracy (≥ 85%), context footprint, project fit score (≥ 7/10), and resilience score (≥ 8/10 — adversarial correct non-trigger rate).

**Triggers:** "evaluate this skill", "run skill tests", "measure skill effectiveness"

#### `skill-refine`
Applies Karpathy's autoresearch loop to improve a skill that fails eval metrics. Routes by failing metric to one of 5 levers (description, checklist, examples, reference docs, scripts), mutates one lever per iteration, re-scores with `skill-eval-agent`, keeps or reverts. Low resilience score routes to Lever A (tighten trigger conditions). Runs up to 10 iterations autonomously.

**Triggers:** "refine this skill", "improve this skill", "run autoresearch on this skill"

#### `skill-discovery`
Mines the project's logs for tasks done manually often enough to warrant becoming a skill, filters out anything already covered by `installed_skills`, and proposes a prioritized backlog of candidates ready for `skill-scout`. Deliberately *not* a step in the main sourcing pipeline — run it periodically, after friction patterns have had time to accumulate.

**Triggers:** "what skills should we build next?", "what keeps coming up that we don't have a skill for?"

---

### Agent Pipeline

#### `agent-scout`
Searches GitHub for Claude Code agent definitions (`.claude/agents/*.md`) matching a capability. Uses `ref_agents` from `evals/project-context.json` as a warm-start shortlist. Returns a ranked shortlist scored on role clarity, tool minimalism, model appropriateness, project fit, and provenance.

**Triggers:** "find an agent for X", "is there an agent that can Y", "source an agent"

#### `agent-audit`
Security gate for agent definitions. Checks tool escalation (agent requests more tools than its role warrants), unbounded recursion, prompt injection in the description/body, persona override patterns, and model override risks. Returns PASS / FLAG / BLOCK.

**Triggers:** "audit this agent", "check agent security", "scan this agent"

#### `agent-adapt`
Rewrites a PASS-audited agent definition to match the project's model tier preferences, tool scope, domain terminology, and color conventions. Writes the adapted agent to `.claude/agents/<name>.md` with a provenance metadata block.

**Triggers:** "adapt this agent", "customize this agent for my project", "install this agent"

#### `agent-eval`
Mirror of `skill-eval` for agent definitions: 9 dispatch scenarios executed as with-agent/baseline pairs by `agent-eval-agent`, graded from harvested evidence. Produces the same 5 metrics with **Dispatch Accuracy** (≥ 85%) in place of Trigger Accuracy, and writes the report to `.claude/agents/<name>-EVAL.md`. Run after `agent-adapt` and before trusting a new agent.

**Triggers:** "evaluate this agent", "run agent tests", "check agent effectiveness"

#### `agent-refine`
Karpathy autoresearch loop for agents. Requires an `agent-eval` baseline and `refine-input.json`; routes by failing metric, mutates one lever per iteration (Lever E — frontmatter config — triggers an `agent-audit` re-run), re-scores via `agent-eval-agent`, keeps or reverts. Default budget 10 iterations; appends every step to `.claude/agents/<name>-REFINE-LOG.md`.

**Triggers:** "refine this agent", "improve this agent", "run autoresearch on this agent"

---

### `team-eval`

Evaluates an agent **team** — an orchestrator plus the member agents it dispatches — as a single unit, filling the blind spot per-definition evals can't cover: member selection, handoffs, and ensemble degradation. Works from a committed `team.json` manifest (reference: `fixtures/teams/repo-audit-ensemble/team.json`, the 8-analyst repo-audit orchestration). Generates 6 scenario types (full-run, partial-team, member-failure, handoff-integrity, negative, adversarial) with one `Agent(<member>)` dispatch-token marker per member, harvested by the standard evidence harvester. Produces 5 metrics — team pass rate (≥ 80%), **Dispatch-Chain Accuracy** (≥ 85%), **Handoff Integrity** (≥ 90%), aggregate context footprint, and team resilience (≥ 8/10) — reported to `evals/teams/<team>/TEAM-EVAL.md`. Failures route to the *orchestrator's* refine track.

**Triggers:** "evaluate the team", "test the orchestration", "check the ensemble"

---

## Agents

Runtime sub-agents that implement parallelizable or autonomous parts of the pipeline:

| Agent | Model | Role | Invoked by |
|---|---|---|---|
| `skill-scout-agent` | sonnet | Parallel registry + GitHub search | `skill-scout` |
| `skill-eval-agent` | sonnet | Parallel scenario execution with evidence-first grading (up to 42 subagents); resumes interrupted runs from the run manifest | `skill-eval`, `skill-refine` |
| `skill-refine-agent` | sonnet | Autoresearch loop orchestration for skills | user / autoresearch loop |
| `agent-eval-agent` | sonnet | Mirror of `skill-eval-agent` for agent definitions; measures Dispatch Accuracy instead of Trigger Accuracy | `agent-eval`, `agent-refine` |
| `agent-refine-agent` | sonnet | Autoresearch loop for agents; Lever E (frontmatter config) triggers an `agent-audit` re-run | user / autoresearch loop |
| `skill-synthesizer-agent` | opus | Multi-candidate synthesis before adaptation | user (2+ PASS candidates) |
| `skill-needs-analysis-agent` | haiku | Gap analysis: maps stack + workflow_terms + mcp_servers to skill categories | user (after project-setup) |
| `skill-guardian` | sonnet | Full pipeline orchestration: context refresh → project-audit → 5-metric eval cycle → refinement | user (periodic health check) |
| `repo-audit-*` (8 analysts) | inherit | One per codebase layer — runtime, framework, database, auth, testing, CI/CD, AI/LLM, Claude Code config; each reads an XML slice and returns a JSON layer object | `repo-audit` |

---

## Codex External Eval Layer

Codex CLI acts as an independent second-model evaluator: a separate AI with no stake in the outcome that executes eval scenarios outside the Claude Code session and returns structured results. Claude Code remains the methodology and lifecycle owner and makes every final call.

**Three modes** (dry-run is the default everywhere — `--live` must always be typed by a human, never automated):

| Mode | Command | What it does |
|---|---|---|
| Cold prediction | `node scripts/codex/run-external-skill-eval.js <skill> --mode smoke\|standard\|full --live` | Codex reads the definition and judges the scenarios itself (agents: `run-external-agent-eval.js`) |
| Native audit | `node scripts/codex/run-native-audit.js <target> <skill\|agent> --live` | Codex reviews a *completed* native run's real transcripts + report and checks whether the evidence supports the native conclusions |
| Calibration gate | `node scripts/run-calibration.js generate` / `check` `[--fixture <name>]` | Runs the pipeline against a known-defective fixture (two committed: `mutant-brief-writer`, `mutant-notes-summarizer` — 8 defect classes between them) and diffs findings against ground truth (no Codex cost itself; see `fixtures/GATE-RUNBOOK.md`) |

**Disagreement policy:** native PASS + Codex PASS → healthy; any split verdict → refine or manual review; any hard failure → block. A native-audit escalation of `MANUAL_REVIEW_REQUIRED` or `REVIEW_SUGGESTED` always routes to manual review, even when both models otherwise agree. Claude Code reviews only `CODEX-EVAL-SUMMARY.md` / `NATIVE-AUDIT-REPORT.md` — never raw traces.

All Codex run artifacts live under `evals/codex-runs/` (gitignored). Full design and boundary table: `docs/codex-external-eval-architecture.md`.

---

## Second Brain

An optional, governed operating memory for a project: a Git-backed, Markdown-native
`.project-brain/` capsule that captures decisions and lessons, compiles them into
reviewable candidates, and promotes them to canon only through an explicit human
approval gate. Retrieval is authority-ranked (`canon > active decision > lesson >
synthesis > session note`), and lifecycle hooks capture session knowledge automatically.

Install into any project:

```bash
./install.sh <target> --with-second-brain [--brain-mode standard]
```

Docs: [`docs/SECOND_BRAIN.md`](docs/SECOND_BRAIN.md) (architecture + protocol) ·
[`docs/BRAIN_KERNEL.md`](docs/BRAIN_KERNEL.md) (every script/hook/skill) ·
[`docs/SECOND_BRAIN_SECURITY.md`](docs/SECOND_BRAIN_SECURITY.md) (threat model) ·
[`docs/REFERENCE_REPOSITORY_LIBRARY.md`](docs/REFERENCE_REPOSITORY_LIBRARY.md) (external-source governance).

---

## Architecture at a glance

**One governance spine, two lanes, one persistent runtime.** This was decided in the Phase 2 evaluation (`docs/evaluations/2026-10-14-software-factory-architecture-evaluation.md`).

- **Capability lane:** the scout → audit → adapt → eval → refine pipelines above. When no candidate fits, a new skill is built with `superpowers:writing-skills` if the Superpowers plugin is installed, and by hand from the official skills docs otherwise. Either way it goes through the same audit → eval gates. The toolkit does not depend on any plugin.
- **Delivery lane:** spec → plan → worktree tasks with per-task review (Superpowers plus Claude Code's native worktrees and subagents) → PR → required CI → human merge.
- **Hermes** is the only persistent runtime. It is read-only: it runs review teams and delivers proposals as draft PRs.
- **The spine both lanes share:**
  - the Second Brain;
  - the reference library;
  - the Claude Code knowledge protocol ([`docs/CLAUDE_CODE_KNOWLEDGE.md`](docs/CLAUDE_CODE_KNOWLEDGE.md));
  - the review and evidence protocol ([`docs/REVIEW_PROTOCOL.md`](docs/REVIEW_PROTOCOL.md));
  - CI.

---

## `evals/project-context.json`

The shared data contract that connects every pipeline stage. Generated by `project-setup` (interview + auto-detection) or `node skills/skill-eval/scripts/extract-project-context.js` (script only).

| Field | Source | Used by |
|---|---|---|
| `project_name` | package.json / dir name | all stages |
| `stack` | package.json deps, pyproject.toml, manifests | skill-scout, skill-adapt, skill-needs-analysis |
| `workflow_terms` | CLAUDE.md (all-caps tokens) | skill-adapt, skill-eval (scenario 7) |
| `installed_skills` | `skills/` directory listing | skill-scout (conflict check), skill-needs-analysis |
| `key_phrases` | README.md, package.json description | skill-eval (scenario 7) |
| `artifact_paths` | CLAUDE.md, planning docs | skill-adapt |
| `hooks` | `.claude/settings.json` + `~/.claude/settings.json` | skill-adapt (avoid redundant steps) |
| `mcp_servers` | `.mcp.json` | skill-adapt, skill-needs-analysis |
| `plugins` | `~/.claude/settings.json:enabledPlugins` | skill-scout (conflict check), skill-needs-analysis |

---

## Directory Structure

```
skills/
  project-idea/      — greenfield idea interview (PROJECT-BRIEF.md)
  project-setup/     — project initialization (CLAUDE.md + project-context.json)
  project-audit/     — project-level security scan (ecc-agentshield wrapper)
  repo-audit/        — deep multi-layer GitHub repo audit (8 parallel analysts)
  skill-scout/       — skill discovery
  skill-audit/       — skill content security gate
  skill-adapt/       — skill customization
  skill-eval/        — skill measurement (9 scenario types, 5 metrics)
  skill-refine/      — skill autoresearch loop
  skill-discovery/   — periodic log mining for new skill candidates
  agent-scout/       — agent discovery
  agent-audit/       — agent security gate
  agent-adapt/       — agent customization
  agent-eval/        — agent measurement (dispatch accuracy + 4 more metrics)
  agent-refine/      — agent autoresearch loop
  team-eval/         — orchestration measurement (dispatch-chain accuracy, handoff integrity)
  project-brain-bootstrap/, second-brain-setup/   — create and personalize a brain capsule
  brain-capture/, brain-compile/, brain-promote/  — record → distil → promote (promote is invoke-only)
  brain-search/, brain-context-pack/, brain-kernel/, brain-weekly-review/ — query, load, route, maintain
  capture-learning/  — turn a correction into a lesson (per-item confirmation)
  reference-repo-add/, reference-repo-audit/, reference-repo-pattern-extract/, gstack-pattern-audit/
                     — register, audit and mine the reference library
.claude/agents/      — installed runtime sub-agents
.project-brain/      — this repo's own Second Brain capsule (canon changes only via brain-promote)
hooks/brain/         — brain hooks, including the blocking brain-security-guard.sh
templates/           — the second-brain capsule template that install copies
reference-repositories/ — governed source material (docs only, never installed directly)
packs/               — domain packs registry (google-ads, google-analytics, wordpress)
infra/hermes-agent/  — Hermes, the persistent runtime (Docker, stdlib-only bin/, registry)
fixtures/            — committed calibration assets (known-defective mutant + golden target)
schemas/             — JSON schemas (evals.json, telemetry events, Codex results, brain, packs)
scripts/             — calibration, Codex, telemetry, brain, packs and CI-scan scripts; most tests
.github/workflows/   — CI (ci.yml), required on main
evals/               — project context and eval artifacts (generated, mostly gitignored)
docs/                — design specs, evaluations, protocols and implementation plans
```

Security rules for the brain guard: [`docs/SECOND_BRAIN_SECURITY.md`](docs/SECOND_BRAIN_SECURITY.md).
Hermes: [`infra/hermes-agent/README.md`](infra/hermes-agent/README.md).

## Installation

```bash
./install.sh /path/to/target-project
```

## Removal

```bash
./uninstall.sh /path/to/target-project
```
