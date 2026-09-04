# claude_code — Skill & Agent Pipeline Toolkit

A self-contained pipeline for sourcing, vetting, adapting, measuring, and auto-improving Claude Code skills and agents. Install it into any target project with `./install.sh`.

## Quick Facts

- **Stack**: Node.js ≥ 18 (scripts only — no runtime framework)
- **Test (all suites)**: `node scripts/run-all-tests.js` — run after any change under `skills/*/scripts/`, `scripts/codex/`, `scripts/telemetry/`, or the calibration scripts
- **Test (Hermes `bin/`)**: `infra/hermes-agent/bin/run-bin-tests.sh` — the stdlib-only Python suites, which `run-all-tests.js` does not discover (it is node-only by design). Run after any change under `infra/hermes-agent/bin/`. Discovers suites dynamically; exits non-zero if any fail.
- **Grader calibration**: `node scripts/run-grader-calibration.js generate|check` — blind re-judging of the golden transcript; run after any grading-rubric or judge-methodology change
- **Test**: `node skills/skill-eval/scripts/generate-seed-evals.js skills/<name>/SKILL.md --context evals/project-context.json`
- **Lint**: `node --check skills/skill-eval/scripts/extract-project-context.js` (syntax check)
- **Install**: `./install.sh /path/to/target-project`
- **Uninstall**: `./uninstall.sh /path/to/target-project`

## Key Directories

- `skills/` — source of truth for all pipeline skills; installed to target projects and `~/.claude/skills/`
- `.claude/agents/` — runtime sub-agents; installed to target projects only (project-scoped)
- `evals/` — generated artifacts (gitignored): `project-context.json`, eval runs, refine logs
- `docs/superpowers/specs/` — design specs for features under development

## Pipeline

```
project-setup → project-audit → skill-scout → skill-audit → skill-adapt → skill-eval → skill-refine
                                                               ↕
                                              agent-scout → agent-audit → agent-adapt → agent-eval → agent-refine
```

- `project-setup` — generates `CLAUDE.md` + `evals/project-context.json` for the target project
- `project-audit` — wraps `npx ecc-agentshield` to scan `.claude/` config for security issues
- `skill-scout` / `agent-scout` — searches GitHub registries; scores candidates on 7 dimensions
- `skill-audit` / `agent-audit` — static scanner (47-pattern set across 5 categories: prompt injection, bash, secrets, permissions, scripts); accepts skill dirs, agent .md files, or settings.json
- `skill-adapt` / `agent-adapt` — rewrites sourced skill/agent to match target project context
- `skill-eval` — 9-scenario test suite; 5 metrics (pass rate, trigger accuracy, footprint, fit, resilience)
- `skill-refine` — Karpathy autoresearch loop; max 10 iterations; routes by failing metric to lever A–E
- `agent-eval` — 9-scenario dispatch test suite; 5 metrics (pass rate, dispatch accuracy, footprint, fit, resilience)
- `agent-refine` — Karpathy autoresearch loop for agents; max 10 iterations; Lever E triggers agent-audit re-run

## Domain Terms

- **SKILL.md** — the skill definition file every skill must have; carries frontmatter + workflow
- **project-context.json** — 9-field shared data contract: `project_name`, `stack`, `workflow_terms`, `installed_skills`, `key_phrases`, `artifact_paths`, `hooks`, `mcp_servers`, `plugins`
- **evals.json** — structured test scenarios for a skill; 9 types when `--context` is provided
- **refine-input.json** — handoff from skill-eval to skill-refine; lists failing scenarios + root causes
- **SKILL-EVAL.md** — per-skill eval report with 5-metric table and analyst observations
- **SKILL-REFINE-LOG.md** — append-only iteration log produced by skill-refine / skill-refine-agent
- **AGENT-EVAL.md** — per-agent eval report at `.claude/agents/<name>-EVAL.md`; uses Dispatch Accuracy instead of Trigger Accuracy
- **AGENT-REFINE-LOG.md** — append-only iteration log at `.claude/agents/<name>-REFINE-LOG.md`
- **Lever A–E** — mutation targets in the autoresearch loop (A=description, B=checklist/workflow, C=examples, D=reference/what-not-to-do, E=scripts for skills / frontmatter config for agents)
- **Dispatch Accuracy** — agent-eval metric equivalent to Trigger Accuracy; measures correct dispatch decisions on positive-expected scenarios only; ≥ 85% required (standard), ≥ 95% (critical)
- **Resilience Score** — metric measuring adversarial non-trigger rate; ≥ 8/10 required (standard), ≥ 9/10 (critical); separate from Trigger Accuracy — adversarial scenarios do not count toward accuracy
- **Project Fit Score** — metric averaging project-native + project-workflow + multi-turn scenario scores; ≥ 7/10 required (standard), ≥ 8/10 (critical)
- **risk_tier** — SKILL.md frontmatter field (`standard` | `critical`); critical applies to security-gate skills (skill-audit, project-audit); raises all thresholds and tightens recommendation logic
- **codex-baseline.json** — written to `evals/<skill>/` or `evals/agents/<agent>/` after a HEALTHY Codex eval; used by aggregator for regression detection on subsequent runs
- **events-YYYY-MM.jsonl** — Level 4 real-usage telemetry, one JSONL line per invocation/outcome/session_end event at `evals/telemetry/`; written by `scripts/telemetry/log-invocation.js` (PostToolUse) and `scripts/telemetry/log-outcome.js` (UserPromptSubmit / Stop / SessionEnd); schema at `schemas/telemetry/invocation-event.schema.json`; never contains raw prompt or transcript text — see `docs/telemetry-privacy.md`
- **usage-summary.json** — written by `scripts/telemetry/aggregate-usage.js` to `evals/telemetry/`; per skill/agent invocation_count, correction_rate, rejection_rate, artifact_production_rate, overall + trailing-30-day stats
- **team.json** — team-eval's input manifest: `team_name`, `orchestrator` (skill|agent), `members[]` (each must exist in `.claude/agents/`), `handoff_contract`, `expected_artifacts`, `example_target`; reference at `fixtures/teams/repo-audit-ensemble/team.json`
- **TEAM-EVAL.md** — per-team eval report at `evals/teams/<team>/`; metrics: team pass rate, Dispatch-Chain Accuracy, Handoff Integrity, aggregate footprint, team resilience; failures route to the orchestrator's refine track (no team-refine)
- **Dispatch-Chain Accuracy** — team-eval metric: correct member dispatch decisions / total member-checks across all scenarios, read from the FULL `transcript_markers` evidence (never the single `agent_dispatched` boolean); ≥ 85% required
- **Handoff Integrity** — team-eval metric: verifiably consumed member outputs / expected handoffs; ≥ 90% required
- **REFINE_RECOMMENDED** — advisory-only telemetry flag: ≥10 invocations in the trailing 30 days AND (correction_rate > 0.3 OR rejection_rate > 0.2); the aggregator merges a `real_usage` block (`source: "telemetry"`, stats, `flagged_at`) into the target's `refine-input.json`, never invokes `skill-refine`/`agent-refine` itself

## Claude's Rules

### Always

- Run `extract-project-context.js` before evaluating any skill — stale context degrades adapt and eval quality
- Pass `--context evals/project-context.json` to `generate-seed-evals.js` — without it you get 6 scenarios instead of 9 and miss resilience and fit metrics
- Pass `--context evals/project-context.json` to `generate-agent-evals.js` — same rule applies for agent-eval; agent artifacts go to `evals/agents/<name>/`
- Discover skills and agents dynamically (`find skills/ -mindepth 1 -maxdepth 1 -type d`) — never hardcode skill names in scripts
- Keep `install.sh` and `uninstall.sh` in sync — every step in install must have a mirror in uninstall
- Deploy to `~/.claude/skills/` after editing any skill so changes take effect immediately in Claude Code

### Never

- Hardcode a skill count anywhere — the number of skills changes as the pipeline evolves
- Commit anything under `evals/` — it is gitignored; all eval artifacts are generated, not versioned
- Run `npx ecc-agentshield --opus` automatically — it makes API calls and may incur cost; only on explicit user request
- Edit `SKILL.md.baseline` once created — it is the immutable reference point for a refine session
- Skip the analyst pass in skill-eval — non-discriminating and flaky scenarios are silent failures without it
- Store raw prompt or transcript text in telemetry — `scripts/telemetry/` only ever writes `context_hash` (sha256), booleans, enums, counts, and repo-relative artifact paths; see `docs/telemetry-privacy.md`

## Codex External Eval Layer

Codex CLI is the independent second-model evaluator — it executes eval scenarios outside the
Claude Code session. Claude Code owns methodology, scenarios, lifecycle, and the final call.

**Commands, native audit mode, the disagreement matrix, and the boundary table live in the
`codex-eval` skill** (`.claude/skills/codex-eval/SKILL.md`) — invoke it before running any
Codex eval. The prohibitions below stay here because they are always-loaded safety rules.

### Never

- Add `--live` to any automated script — always require explicit human invocation
- Enable the Codex plugin review gate
- Parse `trace.jsonl` for scores — `result.json` (written by `-o`) is the only source of truth
- Use `--sandbox workspace-write` or `danger-full-access` for read-only evals
- Commit `evals/codex-runs/` artifacts — gitignored
- Add CI until local results are stable and explicitly approved
- Auto-trigger `run-native-audit.js` after a native eval completes — on-demand only
- Let `run-native-audit.js` write anywhere except `evals/codex-runs/native-audits/` — read-only against native run trees

# >>> second-brain >>>
## Second Brain
@.project-brain/BRAIN.md
# <<< second-brain <<<
