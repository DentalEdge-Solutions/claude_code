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
