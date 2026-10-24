---
name: agent-eval
description: Evaluates a Claude Code agent definition's effectiveness using structured dispatch scenarios and LLM-judge scoring. Produces 5 metrics: eval pass rate, dispatch accuracy, context footprint, project fit, and resilience. Use when evaluating an agent, measuring agent quality, running agent tests, checking agent effectiveness, or before running agent-refine.
compatibility: "Claude Code. Node.js ≥ 18. Requires Agent tool for parallel subagent execution."
---

# Agent Eval

Measure an agent's effectiveness with numbers, not feelings.

## Quick start

```
User: evaluate the skill-eval-agent
User: run agent-eval on agent-adapt
User: check how well skill-refine-agent is working
```

## Workflow

**Resume check (read first):** If the user's prompt indicates work is already in progress — e.g., "I've already generated the scenarios", "the eval is done, score it", "I'm at step N" — skip directly to the appropriate step. Do not re-run scenario generation (step 3) or project context extraction (step 2) if the user has confirmed those artifacts exist. Ask only for what is genuinely missing.

1. **Load the agent** — read `.claude/agents/<agent-name>.md` in full. Extract frontmatter: `name:`, `description:`, `model:`, `tools:`, `color:`. Note every field — all contribute to context footprint. Read the full body including workflow steps and "What NOT to Do" section.

2. **Extract project context** — check first: if `evals/project-context.json` was already confirmed to exist earlier in this session, read it directly and skip the script. Only run the script when the file's existence has not been established:
   ```bash
   node skills/skill-eval/scripts/extract-project-context.js
   ```
   Review the output and add any agent-specific terms the script missed.

3. **Generate dispatch scenarios** — run with project context:
   ```bash
   node skills/agent-eval/scripts/generate-agent-evals.js .claude/agents/<agent-name>.md \
     --context evals/project-context.json
   ```
   This produces 9 scenarios: 6 generic + 3 project-specific. Without `--context` you get 6. Always pass `--context evals/project-context.json` — do not ask the user whether to include it.

   | # | Type | Dispatches? | What it tests |
   |---|------|-------------|---------------|
   | 1 | `direct` | ✓ | Primary orchestration request — cold-start dispatch |
   | 2 | `paraphrased` | ✓ | Same intent, different orchestration phrasing |
   | 3 | `edge_case` | ✓ | Unusual but valid — starts mid-workflow or minimal input |
   | 4 | `negative` | ✗ | Explanation request — should NOT dispatch |
   | 5 | `semantic` | ✓ | Synonym verb variations for the agent's role |
   | 6 | `adversarial` | ✗ | Agent vocabulary in wrong scope — must NOT dispatch |
   | 7 | `project-native` | ✓ | Project terminology injected into orchestration prompt |
   | 8 | `project-workflow` | ✓ | Agent invoked after a sibling in the pipeline |
   | 9 | `multi-turn` | ✓ | Continuation framing from mid-session |

4. **Establish baseline** — the baseline is the same prompt with no agent dispatched (general capabilities only, no Agent tool call), recorded as `baseline_method` `none` for the whole iteration. This holds for a new agent and an existing one alike: a baseline of an earlier version is not run, because a copy taken now would be identical to the agent being measured.

   **Resume check:** if `evals/agents/<agent-name>/iteration-N/run-manifest.json` already exists for the highest N, run `node skills/skill-eval/scripts/run-manifest.js status evals/agents/<agent-name>/iteration-N` first. If it reports incomplete scenarios, resume that iteration using its **recorded** `baseline_method` instead of re-deciding it here. If `status` prints a WARNING that the subject changed or is not found, or the manifest records `baseline_method=snapshot` (written before 2026-10-20), start a new iteration instead of resuming. If `status` exits 2 (`STATUS: REFUSED`: an evaluator file changed since init, or the manifest predates the evaluator pin), the iteration is refused even when every scenario is graded: start a new iteration. Under a caller's evaluator reference (a refine), any exit 2 instead means stop and report EVALUATOR_REFUSED.

5. **Create the iteration dir and initialize the run manifest** (once per iteration — skip on resume):
   ```bash
   mkdir -p evals/agents/<agent-name>/iteration-<N>
   node skills/skill-eval/scripts/run-manifest.js init evals/agents/<agent-name>/iteration-<N> \
     --baseline-method none \
     --subject .claude/agents/<agent-name>.md --commit <short SHA from git rev-parse --short HEAD>
   ```
   `--subject` pins the exact definition measured (sha256); the report's Evidence and Limits section cites it.
   Re-running `init` on an existing manifest is refused by design — that's the guard against re-deciding the baseline method mid-run.
   When the caller gives an evaluator reference `<REF>` (a refine), add `--evaluator-ref <REF>` to every `init`, including a restarted iteration; if it also names the iteration dir (a mid-loop re-eval), use that dir, skip the resume check and write no `refine-input.json`. `init` exits 2 when an evaluator file is missing or not a regular file, or the reference is unusable or differs: stop and report EVALUATOR_REFUSED; never start another iteration and never `init` without the flag.

6. **Run parallel evaluations** — for each not-yet-`graded` scenario, spawn two subagents **in the same turn** via `agent-eval-agent`.
   Canonical scenario-directory naming: `s<id>-<type>-r<rep>` (e.g. `s1-direct-r1`,
   `s4-negative-r2`; single-rep scenarios still get `-r1`) — this is the one naming
   convention going forward; do not use the legacy `<id>_rep<N>` or bare `<id>` forms.
   - Mark each scenario `dispatched`: `node skills/skill-eval/scripts/run-manifest.js mark evals/agents/<agent-name>/iteration-<N> s<id>-<type>-r<rep> dispatched`
   - **With-agent**: dispatch the named agent, execute the prompt, save output to `evals/agents/<agent-name>/iteration-<N>/s<id>-<type>-r<rep>/with_agent/`. Any file the prompt asks the subagent to produce must be written under that scenario's `with_agent/workspace/` subdirectory — never to the repo root or a real skill/agent directory.
   - **Baseline**: no agent dispatched (general capabilities only), same prompt, save to `evals/agents/<agent-name>/iteration-<N>/s<id>-<type>-r<rep>/without_agent/`, with its own `without_agent/workspace/` sandbox.
   - Mark each completed pair `complete`: `node skills/skill-eval/scripts/run-manifest.js mark evals/agents/<agent-name>/iteration-<N> s<id>-<type>-r<rep> complete`

   Run dispatch-type scenarios (direct, paraphrased, semantic, negative, adversarial) 3 times each to measure dispatch consistency. Record `total_tokens` and `duration_ms` from each run — save to `timing.json` in the run directory. A self-reported status header (`did_trigger`, `workflow_steps_executed`) in a transcript is narrative color only — it is never read for scoring.

7. **Harvest evidence** — after each dispatch batch finishes:
   ```bash
   node skills/skill-eval/scripts/harvest-evidence.js evals/agents/<agent-name>/iteration-<N> --type agent --all
   ```
   This writes `evidence.json` next to each `output.md`, deriving `agent_dispatched`, transcript markers, artifact existence/hash, claim verification, and `workflow_steps`/`workflow_executed` from the filesystem and transcript text — never from a self-reported header.

8. **Grade outputs** — dispatch accuracy and workflow-step scoring come **only** from `evidence.json`'s `agent_dispatched` and `workflow_steps[].satisfied` fields. The LLM judge scores only the scenario's `expected.judgment` items plus general output quality — it never re-derives dispatch/workflow results from the transcript, and a subagent's self-reported header is never substituted for evidence.json. Mark each scenario `graded` once scored: `node skills/skill-eval/scripts/run-manifest.js mark evals/agents/<agent-name>/iteration-<N> s<id>-<type>-r<rep> graded`

9. **Confirm integrity before computing metrics**:
   ```bash
   node skills/skill-eval/scripts/run-manifest.js status evals/agents/<agent-name>/iteration-<N>
   ```
   Must exit 0. If it fails, close the gap (harvest, dispatch, or grade what's missing) before proceeding. Exit 2 is an evaluator refusal, not a gap: a stand-alone eval must start a new iteration; under a caller's evaluator reference, stop and report EVALUATOR_REFUSED.

10. **Compute 5 metrics**:
    - **Eval Pass Rate** = (scenarios scoring ≥ 7) / total × 100%. Threshold: ≥ 80%
    - **Dispatch Accuracy** = (correct dispatch decisions across all dispatch-type scenarios, 3 reps each, per evidence.json) / total checks × 100%. Threshold: ≥ 85%
    - **Context Footprint** = total lines in agent file + estimated tokens (lines × 4 avg)
    - **Project Fit Score** = average of project-native + project-workflow + multi-turn ProjectFit dimension scores × 10. Only reported when `--context` was used. Threshold: ≥ 7/10
    - **Resilience Score** = (adversarial scenarios scoring > 0, per evidence.json) / total adversarial × 10. Threshold: ≥ 8/10. An agent that dispatches on adversarial probes has an over-broad description — route to Lever A in agent-refine.

11. **Analyst pass** — before writing the report, review graded results for:
    - Scenarios that pass whether or not the agent is dispatched (non-discriminating)
    - High-variance scenarios (dispatched 1/3 or 2/3 times — unstable description)
    - Large baseline delta (agent significantly outperforms or underperforms general capabilities)
    - Adversarial false positives (agent dispatched when it should not — description too broad; route to Lever A)
    - Tool violations (agent used a tool not listed in its frontmatter `tools:` field → TOOL_VIOLATION flag)
    - Multi-turn redundancy (agent re-asked for context already in the preamble → MULTI_TURN_REDUNDANCY flag)

12. **Write AGENT-EVAL.md** — save to `.claude/agents/<agent-name>-EVAL.md` using the template in REFERENCE.md.

13. **Agent-refine handoff** — if Eval Pass Rate < 80%, Dispatch Accuracy < 85%, Project Fit Score < 7, or Resilience Score < 8, write `evals/agents/<agent-name>/refine-input.json` with failing scenario names, root causes, and analyst observations, plus `eval_manifest`: this iteration's `evals/agents/<agent-name>/iteration-<N>/run-manifest.json`, the refine's evaluator reference, and `eval_scenarios_sha256`: `shasum -a 256 evals/agents/<agent-name>/evals.json` as this iteration used it. Then invoke `agent-refine`.

## Scoring rubric (per scenario, 0–10)

| Score | Meaning |
|-------|---------|
| 10 | Correct dispatch decision + complete workflow + correct output |
| 7–9 | Minor deviation (step skipped, slightly imprecise) |
| 4–6 | Partial execution (dispatched but workflow incomplete) |
| 1–3 | Wrong dispatch decision or substantially wrong output |
| 0 | Failed to dispatch when required, or dispatched when it shouldn't |

**Eval Pass Rate:** ≥ 80% = healthy; 60–79% = refine; < 60% = rewrite  
**Dispatch Accuracy:** ≥ 85% = healthy; < 85% = description needs optimization (Lever A)  
**Project Fit Score:** ≥ 7/10 = well-adapted; < 7 = re-run agent-adapt with richer project context  
**Resilience Score:** ≥ 8/10 = healthy; < 8 = description too broad — tighten trigger language (Lever A)

**Adversarial scoring:** Score 10 = correctly did NOT dispatch + gave a useful redirect. Score 0 = incorrectly dispatched. No partial credit on adversarial scenarios.

**Multi-turn scoring:** Apply composite formula, then deduct 3 points if the agent re-asked for information already in the "[Continuing from earlier]" preamble.

See [REFERENCE.md](REFERENCE.md) for scenario types, eval file format, LLM judge rubric, and report template.
