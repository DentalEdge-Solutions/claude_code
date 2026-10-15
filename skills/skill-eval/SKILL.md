---
name: skill-eval
description: Evaluates a Claude Code skill's effectiveness using structured test scenarios and LLM-judge scoring. Produces three metrics: eval pass rate, trigger accuracy, and context footprint. Use when evaluating a skill, running skill tests, measuring skill effectiveness, checking skill quality, or before running skill-refine.
compatibility: "Claude Code. Node.js ≥ 18. Requires Agent tool for parallel subagent execution."
---

# Skill Eval

Measure a skill's effectiveness with numbers, not feelings.

## Quick start

```
User: evaluate the skill-adapt skill
```

## Workflow

**Resume check (read first):** If the user's prompt indicates work is already in progress — e.g., "I've already generated the scenarios", "the eval is done, score it", "I'm at step N" — skip directly to the appropriate step. Do not re-run scenario generation (step 3) or project context extraction (step 2) if the user has confirmed those artifacts exist. Ask only for what is genuinely missing.

1. **Load the skill** — read `skills/<skill-name>/SKILL.md` and all bundled files (REFERENCE.md, scripts/, references/). Note every file that gets loaded when the skill triggers — these all count toward context footprint.

2. **Extract project context** — check first: if `evals/project-context.json` was already confirmed to exist earlier in this session (e.g., the user mentioned it, or a prior skill step generated it), read it directly and skip the script. Only run the script when the file's existence has not been established:
   ```bash
   node skills/skill-eval/scripts/extract-project-context.js
   ```
   This reads `CLAUDE.md`, `README.md`, `package.json`, `CONTEXT.md`, `.planning/REQUIREMENTS.md`, and the installed skills list, then writes `evals/project-context.json`. Review the output and add any project-specific terms or artifact paths the script missed. Always pass `--context evals/project-context.json` to the scenario generator in step 3 — do not ask the user whether to include it.

3. **Generate seed scenarios** — run with project context:
   ```bash
   node skills/skill-eval/scripts/generate-seed-evals.js skills/<skill-name>/SKILL.md \
     --context evals/project-context.json
   ```
   This produces 9 scenarios: 6 generic + 3 project-specific. Without `--context` you get 6.

   | # | Type | Triggers? | What it tests |
   |---|------|-----------|---------------|
   | 1 | `direct` | ✓ | Primary trigger phrase cold-start |
   | 2 | `paraphrased` | ✓ | Same intent, different words |
   | 3 | `edge_case` | ✓ | Entry mid-workflow |
   | 4 | `negative` | ✗ | "Explain without doing" — should not invoke |
   | 5 | `semantic` | ✓ | Synonym verb variations |
   | 6 | `adversarial` | ✗ | Skill vocabulary in wrong scope/stage — must not fire |
   | 7 | `project-native` | ✓ | Project terminology injected into trigger |
   | 8 | `project-workflow` | ✓ | Skill invoked after a sibling skill |
   | 9 | `multi-turn` | ✓ | Continuation framing from mid-session |

   If the project has a UAT.md or acceptance criteria, add those too:
   ```bash
   node skills/skill-eval/scripts/generate-seed-evals.js <path-to-UAT.md> --context evals/project-context.json
   ```

4. **Establish baseline** — before running with-skill tests, determine what to compare against, and record it as the `baseline_method` for the whole iteration:
   - **New skill**: `none` — run each scenario with no skill loaded
   - **Existing skill being improved**: `snapshot` (`cp -r skills/<skill-name> skills/<skill-name>-eval-snapshot`), then use the snapshot as baseline

   **Resume check:** if `evals/<skill-name>/iteration-N/run-manifest.json` already exists for the highest N, run `node skills/skill-eval/scripts/run-manifest.js status evals/<skill-name>/iteration-N` first. If it reports incomplete scenarios, resume that iteration using its **recorded** `baseline_method` instead of re-deciding it here.

5. **Create the iteration dir and initialize the run manifest** (once per iteration — skip on resume):
   ```bash
   mkdir -p evals/<skill-name>/iteration-<N>
   node skills/skill-eval/scripts/run-manifest.js init evals/<skill-name>/iteration-<N> \
     --baseline-method <none|snapshot> [--snapshot-path skills/<skill-name>-eval-snapshot/SKILL.md] \
     --subject skills/<skill-name>/SKILL.md --commit <short SHA from git rev-parse --short HEAD>
   ```
   `--subject` pins the exact definition measured (sha256); the report's Evidence and Limits section cites it.
   Re-running `init` on an existing manifest is refused by design — that's the guard against re-deciding the baseline method mid-run.

6. **Run parallel evaluations** — for each not-yet-`graded` scenario, spawn two subagents **in the same turn**.
   Canonical scenario-directory naming: `s<id>-<type>-r<rep>` (e.g. `s1-direct-r1`,
   `s4-negative-r2`; single-rep scenarios still get `-r1`) — this is the one naming
   convention going forward; do not use the legacy `<id>_rep<N>`, bare `<id>`, or
   `<eval-name>` forms.
   - Mark each scenario `dispatched`: `node skills/skill-eval/scripts/run-manifest.js mark evals/<skill-name>/iteration-<N> s<id>-<type>-r<rep> dispatched`
   - **With-skill**: load the skill, execute the prompt, save output to `evals/<skill-name>/iteration-<N>/s<id>-<type>-r<rep>/with_skill/`. Any file the prompt asks the subagent to produce must be written under that scenario's `with_skill/workspace/` subdirectory — never to the repo root or a real skill directory.
   - **Baseline**: no skill (or snapshot), same prompt, save to `evals/<skill-name>/iteration-<N>/s<id>-<type>-r<rep>/without_skill/` — with its own `without_skill/workspace/` sandbox.
   - Mark each completed pair `complete`: `node skills/skill-eval/scripts/run-manifest.js mark evals/<skill-name>/iteration-<N> s<id>-<type>-r<rep> complete`

   Run each scenario 3 times to measure trigger consistency. Record `total_tokens` and `duration_ms` from each task notification as it arrives — save to `timing.json` in the run directory. A self-reported status header (`did_trigger`, `workflow_steps_executed`) in a transcript is narrative color only — it is never read for scoring.

7. **Harvest evidence** — after each dispatch batch finishes:
   ```bash
   node skills/skill-eval/scripts/harvest-evidence.js evals/<skill-name>/iteration-<N> --type skill --all
   ```
   This writes `evidence.json` next to each `output.md`, deriving `skill_loaded`, transcript markers, artifact existence/hash, claim verification, and `workflow_steps`/`workflow_executed` from the filesystem and transcript text — never from a self-reported header.

8. **Grade outputs** — trigger accuracy and workflow-step scoring come **only** from `evidence.json`'s `skill_loaded` and `workflow_steps[].satisfied` fields. The LLM judge scores only the scenario's `expected.judgment` items plus general output quality — it never re-derives trigger/workflow results from the transcript, and a subagent's self-reported header is never substituted for evidence.json. Mark each scenario `graded` once scored: `node skills/skill-eval/scripts/run-manifest.js mark evals/<skill-name>/iteration-<N> s<id>-<type>-r<rep> graded`

9. **Confirm integrity before computing metrics**:
   ```bash
   node skills/skill-eval/scripts/run-manifest.js status evals/<skill-name>/iteration-<N>
   ```
   Must exit 0. If it fails, close the gap (harvest, dispatch, or grade what's missing) before proceeding.

10. **Compute 5 metrics**:
    - **Eval Pass Rate** = (scenarios correct) / (total) × 100%. Threshold: ≥ 80%
    - **Trigger Accuracy** = (correct trigger decisions, 3 reps each, per evidence.json) / (total checks) × 100%. Threshold: ≥ 85%
    - **Context Footprint** = total lines across all files loaded on trigger + estimated tokens (lines × 4 avg)
    - **Project Fit Score** = average score of project-native + project-workflow + multi-turn scenarios × 10. Only reported when `--context` was used. Threshold: ≥ 7/10
    - **Resilience Score** = % of adversarial scenarios correctly NOT triggered (per evidence.json) × 10. Threshold: ≥ 8/10. A skill that fires on adversarial probes has an over-broad description — route to Lever A in skill-refine.

11. **Analyst pass** — before writing the report, review graded results for:
    - Scenarios that pass whether or not the skill is loaded (non-discriminating — skill adds no value here)
    - High-variance scenarios (triggered 1/3 or 2/3 times — unstable description)
    - Large baseline delta (skill significantly outperforms or underperforms no-skill)
    - Adversarial false positives (skill triggered when it should not — description is over-broad; route to Lever A)
    - Multi-turn redundancy (skill re-asked for context already given — workflow lacks continuation awareness)

12. **Write SKILL-EVAL.md** — save to `skills/<skill-name>/SKILL-EVAL.md` using the template in REFERENCE.md.

13. **Skill-refine handoff** — if Eval Pass Rate < 80% or Trigger Accuracy < 85%, write `evals/<skill-name>/refine-input.json` with failing scenario names, root causes, and analyst observations. Then invoke `skill-refine`.

## Scoring rubric (per scenario, 0–10)

| Score | Meaning |
|-------|---------|
| 10 | Correct trigger + complete checklist + correct output |
| 7–9 | Minor deviation (step skipped, slightly imprecise) |
| 4–6 | Partial execution (triggered but checklist incomplete) |
| 1–3 | Wrong trigger or substantially wrong output |
| 0 | Failed to trigger when it should, or triggered when it shouldn't |

**Eval Pass Rate:** ≥ 80% = healthy; 60–79% = refine; < 60% = rewrite  
**Trigger Accuracy:** ≥ 85% = healthy; < 85% = description needs optimization  
**Project Fit Score:** ≥ 7/10 = well-adapted; < 7 = re-run skill-adapt with richer project context  
**Resilience Score:** ≥ 8/10 = healthy; < 8 = description too broad — tighten trigger language (Lever A)

**Adversarial scoring note:** For `adversarial` scenarios, score 10 = correctly did NOT trigger + gave a useful redirecting response. Score 0 = incorrectly triggered the full skill workflow. There is no partial credit for wrong trigger decisions on adversarial probes.

**Multi-turn scoring note:** For `multi-turn` scenarios, penalise 3 points if the skill re-asks for information already established in the simulated prior context. Full score requires picking up mid-stream without redundant clarification questions.

See [REFERENCE.md](REFERENCE.md) for scenario types, eval file format, LLM judge rubric, and report template.
