# Skill Eval Reference

## Scenario Types

Generate one of each type. Named evals are easier to track than "eval-0".

| # | Type | Expected trigger | Description | Example |
|---|------|-----------------|-------------|---------|
| 1 | `direct` | ✓ | Exact trigger phrase from description | `"evaluate the skill-adapt skill"` |
| 2 | `paraphrased` | ✓ | Same intent, different words | `"check how well skill-adapt is working"` |
| 3 | `edge_case` | ✓ | Unusual but valid — starts mid-workflow or uses minimal input | `"I already adapted the skill, just run the checklist"` |
| 4 | `negative` | ✗ | Should NOT trigger — explanation request | `"describe how skill-adapt works"` (explain, not invoke) |
| 5 | `semantic` | ✓ | Synonym variation of the action verb | `"measure" / "benchmark" / "test"` for "evaluate" |
| 6 | `adversarial` | ✗ | Skill vocabulary in wrong scope or adjacent pipeline stage — must NOT fire | `"evaluate my React components"` (eval is for skills, not components) |
| 7 | `project-native` | ✓ | Uses project-specific terminology, stack, and artifact paths | `"evaluate skill-adapt for our Next.js/GSD project — outputs go in .planning/"` |
| 8 | `project-workflow` | ✓ | Tests skill within the context of the project's installed skill ecosystem | `"After running skill-audit, now evaluate skill-adapt"` |
| 9 | `multi-turn` | ✓ | Mid-session continuation framing — tests skill outside cold-start conditions | `"[Continuing from earlier] We agreed I'd evaluate skill-adapt. Let's do that now."` |

The first 6 types are always generated. Types 7–9 require `--context evals/project-context.json`.

**Repetitions:** Run trigger-type scenarios (direct, paraphrased, semantic, negative, adversarial) 3 times each — consistency across reps reveals description instability. Run non-trigger scenarios (edge_case, project-native, project-workflow, multi-turn) once per side — they test workflow quality, not trigger reliability.

---

## Eval File Format (`evals.json`)

```json
{
  "skill_name": "<skill-name>",
  "generated_from": "<SKILL.md path>",
  "project_context": "evals/project-context.json",
  "evals": [
    {
      "id": 1,
      "eval_name": "direct-primary-trigger",
      "type": "direct",
      "prompt": "I want to evaluate the skill-adapt skill",
      "expected": {
        "triggers": true,
        "assertions": [
          "Loads skill SKILL.md",
          "Generates at least 6 test scenarios",
          "Reports eval pass rate as a percentage"
        ]
      }
    },
    {
      "id": 4,
      "eval_name": "negative-describe-only",
      "type": "negative",
      "prompt": "Can you explain how to evaluate a skill without actually doing it?",
      "expected": {
        "triggers": false,
        "note": "Should answer conversationally without invoking the eval workflow"
      }
    },
    {
      "id": 6,
      "eval_name": "adversarial-wrong-scope",
      "type": "adversarial",
      "prompt": "Can you evaluate my React components for accessibility issues?",
      "expected": {
        "triggers": false,
        "note": "Adversarial probe — uses 'evaluate' but targets UI components, not a Claude Code skill. Skill must NOT invoke its workflow. A conversational redirect is the correct response. Scored binary: 10 if not triggered, 0 if triggered. No partial credit."
      }
    },
    {
      "id": 9,
      "eval_name": "multi-turn-resumed-context",
      "type": "multi-turn",
      "prompt": "[Continuing from earlier in our session] We discussed claude_code and agreed I'd evaluate skill-adapt. We're using GSD and our hooks include gsd-workflow-guard.js. Let's continue — go ahead and do that now.",
      "expected": {
        "triggers": true,
        "assertions": [
          "Skill triggers correctly despite continuation/resumption framing",
          "Does not ask for information already established in context",
          "Incorporates established context (GSD) without re-asking"
        ]
      },
      "project_context_used": {
        "project_name": "claude_code",
        "workflow_term": "GSD",
        "hooks": ["gsd-workflow-guard.js"]
      }
    }
  ]
}
```

---

## LLM Judge Rubric

Use a faster/cheaper model (e.g., Haiku) as judge. Evaluate each with-skill run on 3 dimensions.

### Dimension 1: Trigger Accuracy (0–10)
- Correct trigger decision (yes/no matches expected) → 10
- Triggered but with hesitation, or failed to trigger confidently → 5
- Triggered on a negative case, or failed on a direct case → 0

Check programmatically first: did the skill tool call appear in the transcript? Use LLM judgment only for borderline cases.

### Dimension 2: Checklist Completion (0–10)
Count numbered workflow steps in SKILL.md.  
Score = (steps completed correctly / total steps) × 10

### Dimension 3: Output Correctness (0–10)
Compare actual output against the `assertions` array in the eval:
- All assertions met → 10
- Minor omissions or imprecisions → 7–9
- Key elements missing → 4–6
- Wrong output → 0–3

### Dimension 4: Project Fit (0–10) — project-native, project-workflow, and multi-turn scenarios only
- Output uses project-specific terminology correctly → 4 pts
- Output references the correct project artifact paths → 3 pts
- Output aligns with the project's installed skill ecosystem (no conflicts, correct handoffs) → 3 pts

**Base scenario score = (Trigger × 0.4) + (Checklist × 0.3) + (Output × 0.3)**  
**Project scenario score = (Trigger × 0.35) + (Checklist × 0.25) + (Output × 0.25) + (ProjectFit × 0.15)**  
**Project Fit Score** = average of Dimension 4 scores across project-native + project-workflow + multi-turn scenarios.

### Special scoring rules

**Adversarial scenarios (type: adversarial, expected triggers: false):**  
Do NOT apply the base composite formula. Score is binary:
- **10** — skill correctly did NOT invoke its workflow AND gave a useful redirect or neutral response
- **0** — skill incorrectly invoked its full workflow on a wrong-scope prompt

No partial credit. A score of 0 on any adversarial scenario is an immediate `ADVERSARIAL_FAILURE` flag.

**Multi-turn scenarios (type: multi-turn, expected triggers: true):**  
Apply the project scenario composite formula, then apply one deduction:
- **−3 pts** if the skill re-asked for any information already present in the "[Continuing from earlier]" preamble (e.g. re-asked for project name, stack, or any detail stated in the simulated prior context)

**Resilience Score** = (adversarial scenarios scoring > 0) / total adversarial × 10. Target ≥ 8/10.

Trigger accuracy is weighted highest — a skill nobody triggers correctly has no value regardless of execution quality. Project Fit Score below 7 means skill-adapt should be re-run with richer project context before proceeding. Resilience Score below 8 means the description is too broad — route to Lever A.

---

## Analyst Pass Checklist

After grading all runs, check for:

- [ ] **Non-discriminating assertions** — scenarios that pass both with-skill and without-skill (skill adds no value here)
- [ ] **Flaky triggers** — scenarios that triggered in 1 or 2 out of 3 reps (description is unstable)
- [ ] **Baseline delta** — is the with-skill output meaningfully better than no-skill? If not, the skill may be redundant
- [ ] **Token cost vs. benefit** — high context footprint skills should show proportionally larger baseline delta
- [ ] **Project terminology mismatch** — project-native scenario triggered but output used generic language instead of project terms
- [ ] **Ecosystem conflict** — project-workflow scenario shows skill duplicating or contradicting output from a sibling skill
- [ ] **Missing artifact references** — output doesn't reference project paths (`.planning/`, `CLAUDE.md`, etc.) that it should know about
- [ ] **Adversarial failure** — adversarial scenario scored 0 (skill over-triggered on wrong-scope prompt; description too broad → Lever A)
- [ ] **Multi-turn redundancy** — multi-turn scenario lost 3 pts for re-asking context already given in the preamble (→ Lever B)

---

## SKILL-EVAL.md Template

> Standalone file: `skills/skill-eval/assets/SKILL-EVAL.template.md`

```markdown
# Skill Eval: <skill-name>
**Date:** YYYY-MM-DD  
**Subject revision:** SKILL.md sha256 <first 12> · commit <short SHA> (from run-manifest.json; "not recorded" when missing, see Evidence and Limits)  
**Scenarios run:** N (×3 reps each)
**Baseline:** no-skill | snapshot of previous version

## Metrics

| Metric | Score | Threshold | Status |
|--------|-------|-----------|--------|
| Eval Pass Rate | XX% | ≥ 80% | PASS / FAIL |
| Trigger Accuracy | XX% | ≥ 85% | PASS / FAIL |
| Context Footprint | XX lines / ~XX tokens | — | OK / HIGH |
| Project Fit Score | X.X/10 | ≥ 7 | PASS / FAIL / N/A |
| Resilience Score | X.X/10 | ≥ 8 | PASS / BROADEN / N/A |

## Scenario Results

| # | Name | Type | Trigger (reps) | Score | Baseline delta | Notes |
|---|------|------|----------------|-------|----------------|-------|
| 1 | direct-primary | direct | 3/3 ✓ | 9/10 | +4 pts | |
| 2 | negative-describe | negative | 0/3 ✓ | 10/10 | n/a | |
| 6 | adversarial-wrong-scope | adversarial | 0/3 ✓ | 10/10 | n/a | Binary score |
| 9 | multi-turn-resumed | multi-turn | 1/1 ✓ | 8/10 | +3 pts | −2 pts: re-asked stack |

## Analyst Observations

- Non-discriminating: (list any)
- Flaky triggers: (list any)
- Baseline delta summary: (one sentence)
- Project terminology mismatch: (list any)
- Ecosystem conflicts: (list any)
- Adversarial failures: (list any — ADVERSARIAL_FAILURE flag)
- Multi-turn redundancy: (list any — MULTI_TURN_REDUNDANCY flag)

## Issues Found

(list scenarios scoring < 7, with root cause)

## Evidence and Limits

- **Subject revision:** definition sha256 <first 12> · commit <short SHA> — copied from `run-manifest.json` `subject`. The sha256 identifies the measured text; the commit is HEAD when the run started, so it does not contain an uncommitted definition (a refine loop measures edits before they are committed). Write "not recorded" when `subject` or its `commit` is null
- **Evidence source:** `evidence.json` per scenario (harvest-evidence.js); subagent self-reports are not grading input. `skill_loaded` is the `Skill(<skill-name>)` token the with-skill subagent is instructed to write when it applies the skill — a marker in its own output, not an independent tool-call log, so trigger accuracy assumes the subagent follows that rule
- **Untested:** (every scenario type, rep or check not run, each with its reason — never omitted silently; "none" if complete)
- **Limitations:** (anything that bounds these numbers — e.g. whether the subject's description was in the skill listing during the run, reduced reps, judge model)

## Recommendation

HEALTHY / REFINE / REWRITE

## Next step

(none | invoke skill-refine with evals/<skill-name>/refine-input.json)
```

---

## Skill-Refine Handoff Format (`refine-input.json`)

Written when any metric falls below threshold: Eval Pass Rate < 80%, Trigger Accuracy < 85%, Project Fit Score < 7, or Resilience Score < 8.

```json
{
  "skill_name": "<skill-name>",
  "eval_date": "YYYY-MM-DD",
  "eval_pass_rate": 0.65,
  "trigger_accuracy": 0.78,
  "resilience_score": 6.7,
  "project_fit_score": 8.2,
  "failing_scenarios": [
    {
      "eval_name": "paraphrased-reword",
      "type": "paraphrased",
      "score": 5,
      "root_cause": "Skill did not trigger on 'check how well' phrasing — description only lists 'evaluate' and 'measure'"
    }
  ],
  "analyst_observations": [
    "Flaky trigger on semantic-synonym (2/3 reps) — description missing synonym 'benchmark'",
    "Non-discriminating: edge_case scenario passes without skill"
  ]
}
```
