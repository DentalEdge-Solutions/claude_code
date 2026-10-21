# Skill Refine Reference

## Routing Guide — Which Metric → Which Lever

| Failing metric | Root cause | Action |
|----------------|-----------|--------|
| Project Fit Score < 7 (project-native or project-workflow failed) | Skill wasn't adapted to project context | **Exit: re-run skill-adapt** with richer project-context.json |
| Project Fit Score < 7 (ONLY multi-turn failed) | Skill re-asks established context | **Lever B** — add continuation-awareness note; do NOT exit to skill-adapt |
| Resilience Score < 8/10 | Description too broad — fires on wrong-scope prompts | **Lever A only** — tighten trigger conditions; add negative examples ("not when X") |
| Trigger Accuracy < 85% | Description doesn't match how users phrase requests | **Lever A only** — don't touch B–E until triggers are stable |
| Eval Pass Rate < 80%, triggers and resilience fine | Skill fires but executes incorrectly | **Levers B–E** |
| Multiple metrics failing | Trigger/resilience instability cascades to execution failures | **Lever A first**, then B–E |

---

## Keep / Revert Thresholds

| Outcome | Condition | Decision |
|---------|-----------|----------|
| **KEEP** | score > baseline + 2% | This is the new baseline |
| **REVERT** | score < baseline − 5% | Restore exact prior content |
| **NEUTRAL** | baseline − 5% ≤ score ≤ baseline + 2% | REVERT unless the edit made `SKILL.md` shorter, with fewer bytes (`wc -c`) than before the edit; if it did, KEEP, and the baseline stays as it was. A neutral Lever D or E edit is always reverted. |

`score` is the training-set pass rate from the re-eval, and the bands are in percentage points of it. A neutral edit is kept only when it shortens `SKILL.md`, the definition loaded whenever the skill triggers: at the same score, a shorter definition has a smaller context footprint, while a longer one adds text the score did not pay for. A neutral edit to REFERENCE.md (Lever D) or `scripts/` (Lever E) is reverted: a shorter script can mean a dropped check rather than a smaller footprint. The size is counted in bytes, not lines, so rewrapping text never counts as shorter. A neutral KEEP leaves the baseline where it was, so a run of neutral edits cannot lower the score step by step. For the lever-exhaustion and convergence rules, a neutral KEEP is not an improvement and a neutral revert counts as a revert.

---

## Lever Space

**Lever A — Description wording** (trigger precision)
The `description:` frontmatter. Changes what prompts activate the skill.
- Constraint: keep "Use when [X]" format, ≤ 1024 chars
- High-impact: one word change can shift trigger accuracy by 20%+

**Lever B — Checklist step** (completeness / ordering)
Any numbered step in `## Workflow`. Changes what Claude does when active.
- Constraint: one step at a time, never reorder all steps at once

**Lever C — Examples** (clarity for ambiguous input)
Content under `## Quick start` or inline examples.
- Constraint: examples must reflect real usage, not idealized scenarios

**Lever D — Reference content** (depth for edge cases)
Content in REFERENCE.md. Changes lookup information depth.
- Constraint: don't move core workflow into REFERENCE.md

**Lever E — Script logic** (deterministic behavior)
Code in `scripts/`. Changes deterministic output.
- Constraint: run `static-scan.js` after any script edit

---

## Good vs Bad Mutations

**Good mutations:**
- Add a specific instruction addressing the most common failure pattern
- Reword an ambiguous instruction to be more explicit
- Add an anti-pattern ("Do NOT do X") for a recurring mistake
- Move a buried instruction higher (priority = position in file)
- Add or improve an example showing the correct behavior
- Remove an instruction causing over-optimization for one thing at the expense of others
- Add a trigger synonym the description was missing

**Bad mutations:**
- Rewriting the entire skill from scratch
- Adding multiple rules in one iteration
- Making the skill longer without a specific reason
- Adding vague instructions like "be more careful" or "do better"
- Changing both description and a workflow step in the same iteration

---

## Hypothesis Generation Guide

When a scenario fails, map the failure to a lever:

| Failure mode | Lever | Example hypothesis |
|-------------|-------|--------------------|
| Skill didn't trigger | A | Add "search for skill" to trigger list |
| Triggered on a negative | A | Narrow description: add "installed skill" qualifier |
| **Adversarial false positive** (resilience < 8) | **A** | Add "not when [wrong scope]" to description; example: "does not apply to general code review — only to Claude Code skill files" |
| Step was skipped | B | Add explicit output requirement to step N |
| **Multi-turn re-asks established context** | **B** | Add continuation-awareness note to step N: "If prior context established [X], skip asking for it" |
| Output was incomplete | C | Add example showing complete output format |
| Edge case not handled | D | Add edge case section to REFERENCE.md |
| Script returned wrong format | E | Fix JSON schema in script output |
| Project terminology missing from output | A or B | Add project terms to description or step instructions |

**Coverage tracking** — note which lever type was used each iteration. In early iterations, vary lever types (explore). Once a lever shows consistent improvement, focus on it (exploit).

---

## Convergence Criteria

Stop the loop when ANY of:

1. `eval_pass_rate ≥ 80%` AND `trigger_accuracy ≥ 85%` AND `resilience_score ≥ 8` → **DONE**
2. All three ≥ 95% for 3 consecutive experiments → **DONE** (diminishing returns)
3. Budget exhausted with no improvement in last 2 iterations → **DONE**
4. All generated hypotheses have been tested → **DONE**
5. `eval_pass_rate < 40%` after 5 iterations → **REWRITE** — recommend a rebuild (`superpowers:writing-skills` if installed, otherwise by hand), then `skill-audit` → `skill-eval`
6. Project Fit Score < 7 AND (project-native or project-workflow failed) → **RE-ADAPT** — do not enter refinement loop
   Exception: if ONLY multi-turn failed, this is NOT an exit condition — continue with Lever B

---

## SKILL-REFINE-LOG.md Template

> Standalone file: `skills/skill-refine/assets/SKILL-REFINE-LOG.template.md`

Save to `skills/<skill-name>/SKILL-REFINE-LOG.md`.

```markdown
# Skill Refinement Log: <skill-name>
**Started:** YYYY-MM-DD  
**Baseline:** pass_rate=XX%, trigger_accuracy=XX%, resilience=X.X/10, project_fit=X.X/10  
**Target:** pass_rate ≥ 80%, trigger_accuracy ≥ 85%, resilience_score ≥ 8/10  
**Training set:** <N> failing scenarios from refine-input.json (adversarial always included)  
**Held-out set:** project-native, project-workflow, multi-turn scenarios  

## Iterations

### Iteration 1
- **Hypothesis:** Changing [section] will improve [scenario name] because [reason]
- **Lever:** A/B/C/D/E — [what type of change]
- **Change:** [one-line summary]
- **Before:** pass_rate=XX%, trigger_accuracy=XX%, resilience=X.X/10
- **After:** pass_rate=XX%, trigger_accuracy=XX%, resilience=X.X/10
- **Size:** XXXX → XXXX bytes (`wc -c` of the edited file, before → after)
- **Decision:** KEPT / REVERTED / NEUTRAL-KEPT / NEUTRAL-REVERTED
- **Note:** [why it worked or didn't]

## Final Results

| Metric | Baseline | Final | Delta |
|--------|----------|-------|-------|
| Eval Pass Rate | XX% | XX% | +/-XX% |
| Trigger Accuracy | XX% | XX% | +/-XX% |
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

---

## Cross-Session Persistence

After each refinement session, record a summary. Use claude-mem if installed:

```
Skill: <skill-name>
Date: YYYY-MM-DD
Iterations: N (kept: X, reverted: Y)
Baseline → Final: pass_rate XX%→XX%, trigger_accuracy XX%→XX%
Effective levers: [list]
Failed hypotheses: [list]
Untested hypotheses remaining: [list — pick up here next session]
```

If claude-mem is not installed, `SKILL-REFINE-LOG.md` is the persistent record — future sessions start by reading it.
