# Agent Eval Reference

## Scenario Types

Generate one of each type. Named evals are easier to track than "eval-0".

| # | Type | Expected dispatch | Description | Example |
|---|------|------------------|-------------|---------|
| 1 | `direct` | ✓ | Exact orchestration request derived from agent description | `"Dispatch the skill-eval-agent to evaluate skill-adapt"` |
| 2 | `paraphrased` | ✓ | Same intent, different orchestration phrasing | `"I need you to use the skill-eval-agent — specifically to evaluate skill-adapt"` |
| 3 | `edge_case` | ✓ | Unusual but valid — starts mid-workflow or uses minimal input | `"skill-eval-agent already loaded the scenarios. Have it resume from the grading step."` |
| 4 | `negative` | ✗ | Should NOT dispatch — explanation request | `"Can you explain what skill-eval-agent does? I'm not asking you to run it."` |
| 5 | `semantic` | ✓ | Synonym variation of the action verb | `"benchmark" / "assess" / "measure"` for `"evaluate"` |
| 6 | `adversarial` | ✗ | Agent vocabulary in wrong scope — must NOT dispatch | `"Use the eval agent to check my React components"` |
| 7 | `project-native` | ✓ | Uses project-specific terminology, stack, and artifact paths | `"Dispatch skill-eval-agent for our Node.js/GSD project — outputs go in evals/agents/"` |
| 8 | `project-workflow` | ✓ | Agent invoked after a sibling in the pipeline | `"After agent-adapt finished, dispatch skill-eval-agent to evaluate it"` |
| 9 | `multi-turn` | ✓ | Continuation framing from mid-session | `"[Continuing from earlier] We agreed to dispatch skill-eval-agent. Go ahead."` |

Types 1–6 always generated. Types 7–9 require `--context evals/project-context.json`.

**Repetitions:** Run dispatch-type scenarios (direct, paraphrased, semantic, negative, adversarial) 3 times each. Run workflow-type scenarios (edge_case, project-native, project-workflow, multi-turn) once per side — these have dispatches:true but test execution quality, not trigger consistency.

---

## Eval File Format (`evals/agents/<name>/evals.json`)

```json
{
  "agent_name": "skill-eval-agent",
  "agent_file": ".claude/agents/skill-eval-agent.md",
  "project_context": "evals/project-context.json",
  "evals": [
    {
      "id": 1,
      "eval_name": "direct-primary-dispatch",
      "type": "direct",
      "prompt": "Dispatch the skill-eval-agent to evaluate skill-adapt.",
      "expected": {
        "dispatches": true,
        "assertions": [
          "Agent skill-eval-agent is dispatched (Agent tool call appears in transcript)",
          "Executes workflow step: Load the skill",
          "Reports all 5 metrics"
        ]
      }
    },
    {
      "id": 6,
      "eval_name": "adversarial-wrong-scope",
      "type": "adversarial",
      "prompt": "Use the eval agent to check my React components for accessibility issues.",
      "expected": {
        "dispatches": false,
        "note": "Adversarial probe — agent vocabulary used in wrong scope. Agent must NOT be dispatched. Score 10 if not dispatched, 0 if dispatched. No partial credit."
      }
    },
    {
      "id": 9,
      "eval_name": "multi-turn-resumed-context",
      "type": "multi-turn",
      "prompt": "[Continuing from earlier in our session] We discussed claude_code and agreed to dispatch the skill-eval-agent to evaluate skill-adapt. We're using GSD. Let's continue — go ahead and dispatch it now.",
      "expected": {
        "dispatches": true,
        "assertions": [
          "Agent dispatches correctly despite continuation/resumption framing",
          "Does not ask for information already established in context",
          "Incorporates established context (GSD) without re-asking"
        ]
      },
      "project_context_used": {
        "project_name": "claude_code",
        "workflow_term": "GSD",
        "hooks": []
      }
    }
  ]
}
```

---

## LLM Judge Rubric

Use a faster model (e.g., Haiku) as judge. Evaluate each with-agent run on 3 dimensions.

### Dimension 1: Dispatch Accuracy (0–10)
- Correct dispatch decision (dispatches/withholds matches expected) → 10
- Dispatched with hesitation, or failed to dispatch confidently → 5
- Dispatched on a negative case, or failed on a direct case → 0

Check programmatically first: did an `Agent` tool call with this agent's `name` field appear in the transcript? Use LLM judgment only for borderline cases.

### Dimension 2: Workflow Completion (0–10)
Count numbered steps in the agent's body.  
Score = (steps completed correctly / total steps) × 10

### Dimension 3: Output Correctness (0–10)
Compare actual output against the `assertions` array in the eval:
- All assertions met → 10
- Minor omissions or imprecisions → 7–9
- Key elements missing → 4–6
- Wrong output → 0–3

### Dimension 4: Project Fit (0–10) — project-native, project-workflow, and multi-turn only
- Output uses project-specific terminology correctly → 4 pts
- Output references the correct project artifact paths → 3 pts
- Output aligns with the project's installed agent ecosystem (no conflicts, correct handoffs) → 3 pts

**Base composite = (Dispatch × 0.4) + (Workflow × 0.3) + (Output × 0.3)**  
**Project composite = (Dispatch × 0.35) + (Workflow × 0.25) + (Output × 0.25) + (ProjectFit × 0.15)**  
**Project Fit Score** = average of Dimension 4 scores across project-native + project-workflow + multi-turn.

### Special scoring rules

**Adversarial scenarios (type: adversarial, expected dispatches: false):**  
Do NOT apply the base composite formula. Score is binary:
- **10** — agent correctly did NOT dispatch AND gave a useful redirect or neutral response
- **0** — agent incorrectly dispatched on a wrong-scope prompt

No partial credit. A score of 0 on any adversarial scenario is an immediate `ADVERSARIAL_FAILURE` flag.

**Multi-turn scenarios (type: multi-turn, expected dispatches: true):**  
Apply the project composite formula, then apply one deduction:
- **−3 pts** if the agent re-asked for any information already present in the "[Continuing from earlier]" preamble

**Resilience Score** = (adversarial scenarios scoring > 0) / total adversarial × 10. Target ≥ 8/10.

---

## Analyst Pass Checklist

After grading all runs, check for:

- [ ] **Non-discriminating assertions** — scenarios that pass both with-agent and without-agent (agent adds no value here)
- [ ] **Flaky dispatch** — scenarios that dispatched 1 or 2 out of 3 reps (description is unstable)
- [ ] **Baseline delta** — is the with-agent output meaningfully better than general capabilities? If not, the agent may be redundant
- [ ] **Token cost vs. benefit** — high-footprint agents should show proportionally larger baseline delta
- [ ] **Project terminology mismatch** — project-native scenario dispatched but output used generic language instead of project terms
- [ ] **Ecosystem conflict** — project-workflow scenario shows agent duplicating or contradicting output from a sibling agent
- [ ] **Adversarial failure** — adversarial scenario scored 0 (agent over-dispatched; description too broad → Lever A)
- [ ] **Multi-turn redundancy** — multi-turn scenario lost 3 pts for re-asking context already given (→ Lever B)
- [ ] **Tool violation** — agent used a tool not in its frontmatter `tools:` list (→ TOOL_VIOLATION flag; fix via Lever E)

---

## AGENT-EVAL.md Template

> Standalone file: `skills/agent-eval/assets/AGENT-EVAL.template.md`

```markdown
# Agent Eval: <agent-name>
**Date:** YYYY-MM-DD  
**Iteration:** N  
**Evaluator:** agent-eval-agent  
**Model:** <declared model>  
**Tools:** <declared tools list>  
**Subject revision:** agent .md sha256 <first 12> · commit <short SHA> (from run-manifest.json; "not recorded" when missing, see Evidence and Limits)  
**Scenarios run:** N (×3 reps for dispatch-type scenarios)  
**Baseline:** no-agent | snapshot of previous version

## Metrics

| Metric            | Score    | Threshold | Status              |
|-------------------|----------|-----------|---------------------|
| Eval Pass Rate    | XX%      | ≥ 80%     | PASS / FAIL         |
| Dispatch Accuracy | XX%      | ≥ 85%     | PASS / FAIL         |
| Context Footprint | XXL/~XXt | —         | OK / HIGH           |
| Project Fit Score | X.X/10   | ≥ 7       | PASS / FAIL / N/A   |
| Resilience Score  | X.X/10   | ≥ 8       | PASS / BROADEN / N/A|

## Scenario Results

| ID | Name | Type | Dispatched (reps) | Score | Baseline delta | Notes |
|----|------|------|-------------------|-------|----------------|-------|
| 1 | direct-primary-dispatch | direct | 3/3 ✓ | 9/10 | +4 pts | |
| 4 | negative-explain-only | negative | 0/3 ✓ | 10/10 | n/a | |
| 6 | adversarial-wrong-scope | adversarial | 0/3 ✓ | 10/10 | n/a | Binary score |
| 9 | multi-turn-resumed-context | multi-turn | 1/1 ✓ | 8/10 | +3 pts | −2 pts: re-asked stack |

## Analyst Observations

- Non-discriminating: (list any)
- Flaky dispatch: (list any)
- Baseline delta summary: (one sentence)
- Project terminology mismatch: (list any)
- Ecosystem conflicts: (list any)
- Adversarial failures: (list any — ADVERSARIAL_FAILURE flag)
- Multi-turn redundancy: (list any — MULTI_TURN_REDUNDANCY flag)
- Tool violations: (list any — TOOL_VIOLATION flag)

## Issues Found

(list scenarios scoring < 7, with root cause)

## Evidence and Limits

- **Subject revision:** definition sha256 <first 12> · commit <short SHA> — copied from `run-manifest.json` `subject`. The sha256 identifies the measured text; the commit is HEAD when the run started, so it does not contain an uncommitted definition (a refine loop measures edits before they are committed). Write "not recorded" when `subject` or its `commit` is null
- **Evidence source:** `evidence.json` per scenario (harvest-evidence.js); subagent self-reports are not grading input. `agent_dispatched` is the `Agent(<agent-name>)` token the with-agent subagent is instructed to write when it runs the agent — a marker in its own output, not an independent tool-call log, so dispatch accuracy assumes the subagent follows that rule
- **Untested:** (every scenario type, rep or check not run, each with its reason — never omitted silently; "none" if complete)
- **Limitations:** (anything that bounds these numbers — e.g. whether the subject's description was in the skill listing during the run, reduced reps, judge model)

## Recommendation

HEALTHY / REFINE: <metric> / REWRITE / RE-ADAPT

## Next step

(none | invoke agent-refine with evals/agents/<agent-name>/refine-input.json)
```

---

## Agent-Refine Handoff Format (`evals/agents/<name>/refine-input.json`)

Written when any metric falls below threshold.

```json
{
  "agent_name": "skill-eval-agent",
  "agent_file": ".claude/agents/skill-eval-agent.md",
  "eval_date": "YYYY-MM-DD",
  "iteration": 1,
  "failing_metrics": {
    "eval_pass_rate":    { "value": 65, "threshold": 80, "failing": true },
    "dispatch_accuracy": { "value": 78, "threshold": 85, "failing": true },
    "resilience_score":  { "value": 6.7, "threshold": 8, "failing": false },
    "project_fit_score": { "value": 8.2, "threshold": 7, "failing": false }
  },
  "failing_scenarios": [
    {
      "id": 2,
      "eval_name": "paraphrased-reword",
      "type": "paraphrased",
      "score": 5.0,
      "root_cause": "Agent not dispatched on 'I need you to use...' phrasing — description only lists imperative forms"
    }
  ],
  "analyst_observations": [
    "Flaky dispatch on semantic-synonym (2/3 reps) — description missing synonym 'benchmark'",
    "Non-discriminating: edge_case scenario passes without agent"
  ],
  "recommended_lever": "A"
}
```
