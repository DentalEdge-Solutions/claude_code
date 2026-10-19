# Skill Eval: <skill-name>
**Date:** YYYY-MM-DD  
**Subject revision:** SKILL.md sha256 <first 12> · commit <short SHA> (from run-manifest.json; "not recorded" when missing, see Evidence and Limits)  
**Scenarios run:** N (trigger-type ×3 reps; non-trigger ×1)
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
| 9 | multi-turn-resumed | multi-turn | 1/1 ✓ | — | — | |

## Analyst Observations

- Non-discriminating: (list any)
- Flaky triggers: (list any)
- Baseline delta summary: (one sentence)
- Project terminology mismatch: (list any)
- Ecosystem conflicts: (list any)
- Adversarial failures: (list any — ADVERSARIAL_FAILURE flag → Lever A)
- Multi-turn redundancy: (list any — MULTI_TURN_REDUNDANCY flag → Lever B)

## Issues Found

(list scenarios scoring < 7, with root cause)

## Evidence and Limits

- **Subject revision:** definition sha256 <first 12> · commit <short SHA> — copied from `run-manifest.json` `subject`. The sha256 identifies the measured text; the commit is HEAD when the run started, so it does not contain an uncommitted definition (a refine loop measures edits before they are committed). Write "not recorded" when `subject` or its `commit` is null
- **Evidence source:** `evidence.json` per scenario (harvest-evidence.js); subagent self-reports are not grading input. `skill_loaded` is the `Skill(<skill-name>)` token the with-skill subagent is instructed to write when it applies the skill — a marker in its own output, not an independent tool-call log, so trigger accuracy assumes the subagent follows that rule
- **Untested:** (every scenario type, rep or check not run, each with its reason — never omitted silently; "none" if complete)
- **Limitations:** (anything that bounds these numbers — e.g. whether the subject's description was in the skill listing during the run, reduced reps, judge model)

## Recommendation

HEALTHY / REFINE / REWRITE / RE-ADAPT

## Next step

(none | invoke skill-refine with evals/<skill-name>/refine-input.json)
