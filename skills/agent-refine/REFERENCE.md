# Agent Refine Reference

## Routing Guide — Which Metric → Which Lever

| Failing metric | Root cause | Action |
|----------------|-----------|--------|
| Project Fit Score < 7 (project-native or project-workflow failed) | Agent wasn't adapted to project context | **Exit: re-run agent-adapt** with richer project-context.json |
| Project Fit Score < 7 (ONLY multi-turn failed) | Agent re-asks established context | **Lever B** — add continuation-awareness note; do NOT exit to agent-adapt |
| Resilience Score < 8/10 | Description too broad — dispatches on wrong-scope prompts | **Lever A only** — tighten trigger conditions; add negative examples ("not when X") |
| Dispatch Accuracy < 85% | Description doesn't match how orchestrators phrase requests | **Lever A only** — don't touch B–E until dispatch is stable |
| Eval Pass Rate < 80%, dispatch and resilience fine | Agent dispatches but executes incorrectly | **Levers B–E** |
| Multiple metrics failing | Dispatch/resilience instability cascades to execution failures | **Lever A first**, then B–E |

---

## Keep / Revert Thresholds

| Outcome | Condition | Decision |
|---------|-----------|----------|
| **KEEP** | score > baseline + 2% | This is the new baseline |
| **REVERT** | score < baseline − 5% | Restore exact prior content |
| **NEUTRAL** | baseline − 5% ≤ score ≤ baseline + 2% | REVERT unless the edit made the edited file shorter, with fewer bytes (`wc -c`) than before the edit; if it did, KEEP |

`score` is the training-set pass rate from the re-eval. A neutral edit is kept only when it shortens the agent file: at the same score, a shorter definition has a smaller context footprint, while a longer one adds text the score did not pay for. The size is counted in bytes, not lines, so rewrapping text never counts as shorter.

---

## Lever Space

**Lever A — Description wording** (dispatch precision)
The `description:` frontmatter field. Changes what prompts cause Claude to dispatch this agent.
- Constraint: keep "Use when [X]" format, ≤ 1024 chars
- High-impact: one word change can shift dispatch accuracy by 20%+

**Lever B — Workflow step** (completeness / ordering)
Any numbered step in the agent body. Changes what the agent does when dispatched.
- Constraint: one step at a time, never reorder all steps at once

**Lever C — Examples** (dispatch clarity for ambiguous roles)
`<example>` blocks inside the `description:` field (multi-line YAML block scalar).
- Constraint: examples must reflect real dispatch scenarios, not idealized ones

**Lever D — What NOT to Do** (scope containment)
The `## What NOT to Do` section in the agent body.
- Constraint: don't move core workflow logic here; this section is for constraints, not steps

**Lever E — Frontmatter config** (cost and tool compliance)
The `model:` and `tools:` frontmatter fields.
- Constraint: never expand `tools:` beyond what the role requires; always re-run agent-audit after any Lever E mutation before scoring. A BLOCK verdict = score 0, revert immediately.
- `model:` haiku for lightweight tasks, sonnet for reasoning, opus for complex orchestration
- `tools:` trim to minimum; never add tools not in the source without explicit user approval

---

## Good vs Bad Mutations

**Good mutations:**
- Add a specific "Use when" condition addressing the most common dispatch failure
- Reword an ambiguous "Use when" clause to be more explicit
- Add a negative example ("not when X") for a recurring false dispatch
- Move a buried dispatch condition higher in the description (priority = position)
- Add or improve an `<example>` block showing the correct dispatch trigger
- Remove a workflow step that causes tool scope violations
- Trim `tools:` to remove a tool the agent never uses

**Bad mutations:**
- Rewriting the entire agent definition from scratch
- Adding multiple rules in one iteration
- Making the agent file longer without a specific reason
- Adding vague instructions like "be more careful" or "do better"
- Changing both description and a workflow step in the same iteration
- Expanding `tools:` without re-running agent-audit

---

## Hypothesis Generation Guide

| Failure mode | Lever | Example hypothesis |
|-------------|-------|--------------------|
| Agent doesn't dispatch | A | Add/clarify "Use when" trigger conditions |
| Agent over-dispatches (low dispatch accuracy) | A | Narrow description: add specific role qualifier |
| **Adversarial false dispatch** (resilience < 8) | **A** | Add "not when [wrong scope]" to description; add negative example |
| Step was skipped | B | Add explicit output requirement to step N |
| **Multi-turn re-asks established context** | **B** | Add continuation-awareness note: "If prior context established [X], skip asking for it" |
| Output wrong format | C | Add example showing correct output format |
| Tool scope violation (TOOL_VIOLATION flag) | D or E | Add "Never use [tool]" to What NOT to Do, or remove from tools: list |
| Agent costs too much for lightweight task | E | Downgrade model: sonnet → haiku |
| Agent uses undeclared tools | E | Add missing tool to tools: list; re-run agent-audit |

**Coverage tracking** — note which lever type was used each iteration. Vary lever types in iterations 1–4 (explore). Exploit the best-performing lever in iterations 5+.

---

## Convergence Criteria

Stop the loop when ANY of:

1. `eval_pass_rate ≥ 80%` AND `dispatch_accuracy ≥ 85%` AND `resilience_score ≥ 8` → **DONE**
2. All three ≥ 95% for 3 consecutive experiments → **DONE** (diminishing returns)
3. Budget exhausted with no improvement in last 2 iterations → **DONE**
4. All generated hypotheses have been tested → **DONE**
5. `eval_pass_rate < 40%` after 5 iterations → **REWRITE** — recommend writing a new agent definition
6. Project Fit Score < 7 AND (project-native or project-workflow failed) → **RE-ADAPT** — do not enter refinement loop
   Exception: if ONLY multi-turn failed, this is NOT an exit condition — continue with Lever B

---

## AGENT-REFINE-LOG.md Template

> Standalone file: `skills/agent-refine/assets/AGENT-REFINE-LOG.template.md`

Save to `.claude/agents/<agent-name>-REFINE-LOG.md`.

```markdown
# Agent Refinement Log: <agent-name>
**Started:** YYYY-MM-DD  
**Baseline:** eval_pass_rate=XX%, dispatch_accuracy=XX%, resilience=X.X/10, project_fit=X.X/10  
**Target:** eval_pass_rate ≥ 80%, dispatch_accuracy ≥ 85%, resilience_score ≥ 8/10  
**Training set:** <N> failing scenarios from refine-input.json (adversarial always included)  
**Held-out set:** project-native, project-workflow, multi-turn scenarios  

## Iterations

### Iteration 1
- **Hypothesis:** Changing [section] will improve [scenario name] because [reason]
- **Lever:** A/B/C/D/E — [what type of change]
- **Change:** [one-line summary]
- **Before:** eval_pass_rate=XX%, dispatch_accuracy=XX%, resilience=X.X/10
- **After:** eval_pass_rate=XX%, dispatch_accuracy=XX%, resilience=X.X/10
- **Agent-audit:** PASS / BLOCK (if Lever E — always run)
- **Decision:** KEPT / REVERTED / NEUTRAL-KEPT
- **Note:** [why it worked or didn't]

## Final Results

| Metric | Baseline | Final | Delta |
|--------|----------|-------|-------|
| Eval Pass Rate | XX% | XX% | +/-XX% |
| Dispatch Accuracy | XX% | XX% | +/-XX% |
| Resilience Score | X.X/10 | X.X/10 | +/-X.X |
| Project Fit Score | X.X/10 | X.X/10 | +/-X.X |
| Context Footprint | XXL | XXL | +/-XXL |
| Iterations run | — | N | — |
| Keep rate | — | X/N | — |

**Levers used:** A(N), B(N), C(N), D(N), E(N)  
**Most effective lever:** [letter] — [what worked]  
**Failed hypotheses:** [list — data for future sessions]  

**Recommendation:** DONE / NEEDS-REWRITE / CONTINUE / RE-ADAPT
```
