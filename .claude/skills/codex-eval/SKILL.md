---
name: codex-eval
description: Use when running, interpreting, or reasoning about a Codex external eval — the independent second-model evaluation layer. Covers run-external-skill-eval.js, run-external-agent-eval.js, run-native-audit.js, their dry-run/--live modes, the native audit mode, the Claude-Code-vs-Codex disagreement matrix, and the ownership boundary. Trigger on "codex eval", "external eval", "second-model eval", "native audit", "CODEX-EVAL-SUMMARY", or before adding --live to anything.
---

# Codex External Eval Layer

> Migrated out of `CLAUDE.md` on 2026-09-04 so it loads on demand instead of every session.
> **The `Never` list for this layer stays in `CLAUDE.md` — safety prohibitions are always-loaded.**

Codex CLI is the independent second-model evaluator. It executes eval scenarios outside the Claude Code session, reducing session token consumption. Claude Code remains the methodology and lifecycle owner; Codex returns structured results and summaries only.

Validated on: `skill-eval` and `skill-eval-agent` (smoke + standard mode, 2026-07-01). See `docs/evaluations/claude-code-codex-architecture-evaluation.md`.

### Commands (DRY-RUN IS DEFAULT — add --live to call Codex)

| Command | What it does |
|---------|-------------|
| `node scripts/codex/run-external-skill-eval.js <skill> --mode smoke` | Dry-run: writes prompts + command preview, no Codex call |
| `node scripts/codex/run-external-skill-eval.js <skill> --mode smoke --live` | Live: 4 scenarios (direct, negative, adversarial, project-native) |
| `node scripts/codex/run-external-skill-eval.js <skill> --mode standard --live` | Live: all 9 scenario types, 1 rep |
| `node scripts/codex/run-external-skill-eval.js <skill> --mode full --live` | Live: all 9 types, 3 reps for trigger-sensitive scenarios |
| `node scripts/codex/run-external-agent-eval.js <agent> --mode smoke` | Same dry-run pattern for agents |
| `node scripts/codex/run-external-agent-eval.js <agent> --mode standard --live` | Live standard eval for agents |

### Native Audit Mode

Additive third mode — Codex audits a *completed* native eval run's real evidence (transcripts + native
`SKILL-EVAL.md`/`<agent>-EVAL.md` report) instead of cold-reading the definition and predicting
triggering. Motivated by a calibration test showing the native pipeline misses internal
self-contradictions and silently-dropped workflow steps (see `docs/evaluations/claude-code-codex-architecture-evaluation.md` Phase 8). Standalone, on-demand only — never wired into `skill-eval`/`agent-eval`'s own workflow.

| Command | What it does |
|---------|-------------|
| `node scripts/codex/run-native-audit.js <target> <skill\|agent>` | Dry-run: packages the latest native run's evidence, writes `audit-spec.json` + `prompt.txt`, no Codex call |
| `node scripts/codex/run-native-audit.js <target> <skill\|agent> --live` | Live: single holistic Codex audit call, writes `NATIVE-AUDIT-REPORT.md` |
| `node scripts/codex/run-native-audit.js <target> <skill\|agent> --iteration N` | Audit a specific `iteration-N` instead of the latest |
| `node scripts/codex/run-native-audit.js <target> <skill\|agent> --all-reps --include-baseline` | Package every rep found + paired baseline transcripts (higher cost) |

Findings go to `evals/codex-runs/native-audits/{skills,agents}/<target>/<run-id>/NATIVE-AUDIT-REPORT.md` — a separate report, not merged into `CODEX-EVAL-SUMMARY.md`. Full design: `docs/codex-external-eval-architecture.md`.

### What Claude Code reviews

`CODEX-EVAL-SUMMARY.md` in `evals/codex-runs/<type>/<target>/<run-id>/` — not the JSONL traces. The summary contains the 5-metric table, recommendation, hard failures, and analyst findings.

### Disagreement policy

| Native eval | Codex eval | Route |
|-------------|-----------|-------|
| PASS | PASS | HEALTHY |
| PASS | FAIL | REFINE or MANUAL REVIEW |
| FAIL | PASS | MANUAL REVIEW |
| FAIL | FAIL | BLOCK / REFINE / REWRITE |
| Any hard failure | Any | BLOCK |

Claude Code makes the final call. A Codex BLOCK that conflicts with a native PASS routes to MANUAL REVIEW, not auto-BLOCK.

**Addendum:** a native-audit `escalation = MANUAL_REVIEW_REQUIRED` or `REVIEW_SUGGESTED` overrides any HEALTHY/PASS agreement in the table above — routes to MANUAL REVIEW regardless of the 2×2 outcome. Evidence, not an auto-BLOCK.

### Boundary

Claude Code = methodology, scenarios, lifecycle, final decision.  
Codex = external second-model execution, per-scenario `result.json`, `CODEX-EVAL-SUMMARY.md`.  
See `docs/codex-external-eval-architecture.md` for the full boundary table and artifact flow.

### What Codex is not

Codex does not replay the Claude Code runtime — it is an independent second model reading skill/agent definitions and judging scenarios. Codex does not own any lifecycle step and does not call skill-refine, agent-refine, or skill-guardian.

