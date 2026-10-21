---
name: agent-refine
description: Auto-improves a Claude Code agent definition using Karpathy's autoresearch loop — baseline eval, targeted mutation, re-measure, keep or revert. Produces a delta report. Use when refining an agent, improving an agent definition, running autoresearch on an agent, or when agent-eval reports any metric below threshold.
compatibility: "Claude Code. Node.js ≥ 18. Requires Agent tool for agent-eval-agent invocation."
---

# Agent Refine

Apply Karpathy's autoresearch loop to measurably improve an agent definition. Diagnose → targeted fix → verified improvement. No guessing, no rewrites.

## Prerequisite

`agent-eval` must have run first. You need a baseline and a `refine-input.json` at `evals/agents/<agent-name>/refine-input.json`. If neither exists, run `agent-eval` now.

## The Loop

```
RULE:    One lever per iteration. Score ↑ (>+2%) → keep. Score ↓ (>−5%) → revert. Repeat.
TARGET:  eval_pass_rate ≥ 80%  AND  dispatch_accuracy ≥ 85%  AND  resilience_score ≥ 8/10
BUDGET:  default 10 iterations, stop early at 95%+ for 3 consecutive
```

## Workflow

1. **Gather inputs** — load `.claude/agents/<name>-EVAL.md` and `evals/agents/<name>/refine-input.json`. Confirm budget and runs-per-experiment with the user (default: 10 iterations, 3 reps each).

2. **Back up and validate baseline** — copy the current agent before touching anything (once per refine session; never overwrite an existing `.md.baseline`):
   ```bash
   mkdir -p evals/agents/<name>/refine
   [ -e evals/agents/<name>/refine/<name>.md.baseline ] || cp .claude/agents/<name>.md evals/agents/<name>/refine/<name>.md.baseline
   ```
   Refine copies live under `evals/agents/<name>/refine/` (gitignored), never in `.claude/agents/`.
   Then check staleness: if `refine-input.json` was written today **and** the agent file has not been modified since — trust the baseline scores directly, no re-run needed. If the agent was changed since eval ran, re-run only the failing scenarios (3 reps, same parallel subagent pattern as agent-eval) to refresh the baseline before proceeding. If baseline is already ≥ 90%, ask the user whether to continue.

3. **Route by failing metric** — the correct lever depends on *which* metric is failing:
   - **Project Fit Score < 7** → check which scenarios drove it down:
     - If `project-native` or `project-workflow` failed → Exit. Re-run `agent-adapt` with richer `evals/project-context.json`. Refining won't fix a mis-adapted agent.
     - If ONLY `multi-turn` failed (project-native and project-workflow passed) → do NOT exit. Work Lever B this session: add a continuation-awareness note to the workflow step whose output the multi-turn scenario re-asked for.
   - **Resilience Score < 8/10** → work Lever A (description) only this session. The agent is dispatching on adversarial probes — the trigger language is too broad. Tighten the "Use when" clause and add negative examples. Don't touch B–E until resilience passes.
   - **Dispatch Accuracy < 85%** → work Lever A (description) only this session. Don't touch B–E until dispatch is stable.
   - **Eval Pass Rate < 80%** (dispatch and resilience fine) → work Levers B–E.
   - **Multiple failing** → fix Lever A first; pass rate and resilience issues are often downstream of description problems.

4. **Train/test split** — treat the failing scenarios from `refine-input.json` as the *training set* (mutate against these). Hold the `project-native`, `project-workflow`, and `multi-turn` scenarios as the *validation set* (run only on final validation, not during iterations).

   Exception: `adversarial` scenarios belong on the **training set** even when resilience_score is the failing metric — they are the most direct signal for Lever A mutations and must be checked each iteration. Running them only at final validation defeats the purpose.

5. **Hypothesis** — pick ONE change from the lever space. Consult the failure mode → lever table in REFERENCE.md. Track which levers have been tried this session — vary lever types in early iterations; exploit the best-performing lever in later ones.

6. **Mutate** — make exactly the targeted edit. No other changes.
   - **Lever E only**: after mutating `model:` or `tools:` in the frontmatter, immediately re-run agent-audit:
     ```bash
     node skills/skill-audit/scripts/static-scan.js .claude/agents/<name>.md
     ```
     A BLOCK verdict counts as a score of 0 for this iteration — revert immediately and log.

7. **Re-eval (training set only)** — re-run the failing scenarios using agent-eval's exact methodology: parallel subagents (with-agent vs baseline snapshot), 3 reps each, programmatic dispatch detection first, then LLM judge scoring. Also run 1 rep of each previously-passing scenario as a regression check. Use the same scoring formula: `(Dispatch × 0.4) + (Workflow × 0.3) + (Output × 0.3)`.

8. **Keep or revert** (see thresholds in REFERENCE.md):
   - score > baseline + 2% → **KEEP**. No copy is needed: the agent is project-scoped, and Claude Code watches `.claude/agents/` and uses the edited file on the next delegation.
   - score < baseline − 5% → **REVERT** to prior content exactly.
   - baseline − 5% ≤ score ≤ baseline + 2% (neutral) → **REVERT unless the edit made the edited file shorter, with fewer bytes (`wc -c`) than before the edit**; if it did, **KEEP**.
   - Log the iteration either way — failed hypotheses are data.

9. **Repeat** steps 5–8 until any convergence criterion is met (see REFERENCE.md).

10. **Final validation** — invoke `agent-eval` on the improved agent with `--context evals/project-context.json`. Do not implement a separate eval process — agent-eval IS the final validation. This produces a new `AGENT-EVAL.md` replacing the old one, giving a clean before/after comparison. The held-out `project-native`, `project-workflow`, and `multi-turn` scenarios run here for the first time during this refinement session. All 5 metrics must be reported.

11. **Write report** — save `.claude/agents/<name>-REFINE-LOG.md` using the template in REFERENCE.md.

## Rules

- **One lever per iteration** — never change description AND a workflow step in the same iteration.
- **Re-run agent-audit after Lever E** — any tools/model change must pass the security scanner before scoring.
- **Revert faithfully** — restore the exact prior content, not a rewrite of it.
- **Log every iteration** — including failed hypotheses. They're data.
- **Don't rewrite** — if pass rate < 40% after 5 iterations, recommend writing a new agent definition from scratch.
- **Never skip the baseline backup** — `.md.baseline` must exist before the first mutation.

See [REFERENCE.md](REFERENCE.md) for lever definitions, keep/revert thresholds, hypothesis guide, good/bad mutations, convergence criteria, and log template.
