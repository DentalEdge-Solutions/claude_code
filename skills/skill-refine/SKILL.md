---
name: skill-refine
description: Auto-improves a Claude Code skill using Karpathy's autoresearch loop — baseline eval, targeted mutation, re-measure, keep or revert. Produces a delta report. Use when refining a skill, improving a skill, running autoresearch on a skill, or when skill-eval reports pass rate below threshold.
compatibility: "Claude Code. Node.js ≥ 18. Requires Agent tool for skill-eval-agent invocation."
---

# Skill Refine

Apply Karpathy's autoresearch loop to measurably improve a skill. Diagnose → targeted fix → verified improvement. No guessing, no rewrites.

## Prerequisite

`skill-eval` must have run first. You need a baseline and a `refine-input.json`. If neither exists, run `skill-eval` now.

The subject must not be part of the evaluator. If it is `skill-eval` or `agent-eval` (or the agents `skill-eval-agent` / `agent-eval-agent`), refuse and stop: tell the user that refining the evaluator needs a frozen-copy procedure, which does not exist yet.

## The Loop

```
RULE:    One lever per iteration. Score > baseline + 2 pts → keep. Score < baseline − 5 pts → revert.
         Between → revert unless the definition got shorter. Repeat.
TARGET:  eval_pass_rate ≥ 80%  AND  trigger_accuracy ≥ 85%  AND  resilience_score ≥ 8/10
BUDGET:  default 10 iterations, stop early at 95%+ for 3 consecutive
```

## Workflow

1. **Gather inputs** — load `skills/<skill-name>/SKILL-EVAL.md` and `evals/<skill-name>/refine-input.json` (the structured handoff from skill-eval). Confirm budget and runs-per-experiment with the user (default: 10 iterations, 3 reps each). Take the evaluator reference `<REF>` from `refine-input.json`'s `eval_manifest` (the eval iteration's `run-manifest.json`); if the field is absent, stop and ask the user for a fresh eval — never guess it from folder names. Before any backup or edit, run `node skills/skill-eval/scripts/run-manifest.js check-ref <REF>`: on any non-zero exit, stop and tell the user a fresh eval (made after P0-11) is needed first — nothing has been changed.

2. **Back up and validate baseline** — copy the current skill before touching anything (once per refine session; never overwrite an existing `SKILL.md.baseline`):
   ```bash
   mkdir -p evals/<skill-name>/refine
   [ -e evals/<skill-name>/refine/SKILL.md.baseline ] || cp skills/<skill-name>/SKILL.md evals/<skill-name>/refine/SKILL.md.baseline
   cp evals/<skill-name>/evals.json evals/<skill-name>/refine/evals.json
   ```
   The `evals.json` copy is where the harvester looks for a re-eval's scenarios (two levels above each scenario folder).
   Refine copies live under `evals/<skill-name>/refine/` (gitignored), never in the skill folder: the keep step syncs that folder into `~/.claude/skills/`.
   Then check staleness: if `refine-input.json` was written today **and** `SKILL.md` has not been modified since — trust the baseline scores directly, no re-run needed. If the skill was changed since eval ran, re-run only the failing scenarios (3 reps, same parallel subagent pattern as skill-eval) as a re-eval in `refine/re-eval-0` (step 7) to refresh the baseline before proceeding. If baseline is already ≥ 90%, ask the user whether to continue.

3. **Route by failing metric** — the correct lever depends on *which* metric is failing:
   - **Project Fit Score < 7** → check which scenarios drove it down:
     - If `project-native` or `project-workflow` failed → Exit. Re-run `skill-adapt` with richer `evals/project-context.json`. Refining won't fix a mis-adapted skill.
     - If ONLY `multi-turn` failed (project-native and project-workflow passed) → do NOT exit. Work Lever B this session: add a continuation-awareness note to the step whose output the multi-turn scenario re-asked for.
   - **Resilience Score < 8/10** → work Lever A (description) only this session. The skill is firing on adversarial probes — the trigger language is too broad. Tighten the "Use when" clause and add negative examples (what the skill should NOT handle). Don't touch B–E until resilience passes.
   - **Trigger Accuracy < 85%** → work Lever A (description) only this session. Don't touch B–E until triggers are stable.
   - **Eval Pass Rate < 80%** (triggers and resilience fine) → work Levers B–E.
   - **Multiple failing** → fix Lever A first; pass rate and resilience issues are often downstream of description problems.

4. **Train/test split** — treat the failing scenarios from `refine-input.json` as the *training set* (mutate against these). Hold the `project-native`, `project-workflow`, and `multi-turn` scenarios as the *validation set* (run only on final validation, not during iterations).

   Exception: `adversarial` scenarios belong on the **training set** even when resilience_score is the failing metric — they are the most direct signal for Lever A mutations and must be checked each iteration. Running them only at final validation defeats the purpose of tightening the description.

   This split prevents overfitting the skill to its own eval suite.

5. **Hypothesis** — pick ONE change from the lever space. Consult the failure mode → lever table in REFERENCE.md. Track which levers have been tried this session (coverage) — in early iterations, vary lever types; in later iterations, exploit the best-performing lever.

6. **Mutate** — first copy the whole skill folder, before the edit, into a fresh folder outside it (step 8 syncs the skill folder; fresh, because N, the iteration number, repeats across sessions):
   `rm -rf "evals/<skill-name>/refine/pre-iter-N" && mkdir -p "evals/<skill-name>/refine/pre-iter-N" && cp -R "skills/<skill-name>/." "evals/<skill-name>/refine/pre-iter-N/"`
   Then make exactly the targeted edit, to one file, `<file>`, relative to the skill folder: `SKILL.md` for Levers A–C, `REFERENCE.md` for D, the script for E. No other changes. A symlinked `<file>` is out of scope: a revert can't restore it, so pick another file. `wc -c < evals/<skill-name>/refine/pre-iter-N/SKILL.md` is the size before the edit.

7. **Re-eval (training set only)** — re-run the failing scenarios using skill-eval's exact methodology: parallel subagents (with-skill vs no-skill baseline), 3 reps each, programmatic trigger detection first, then LLM judge scoring using the rubric in skill-eval's REFERENCE.md. Also run 1 rep of each previously-passing scenario as a regression check. Use the same scoring formula: `(Trigger × 0.4) + (Checklist × 0.3) + (Output × 0.3)`.
   Run each re-eval in its own folder under the refine area, fresh per session like step 6's copy — never in an eval `iteration-<N>` folder, which belongs to skill-eval:
   `rm -rf "evals/<skill-name>/refine/re-eval-N" && node skills/skill-eval/scripts/run-manifest.js init "evals/<skill-name>/refine/re-eval-N" --baseline-method none --subject skills/<skill-name>/SKILL.md --commit <short SHA> --evaluator-ref <REF>`
   Its scenario folders, `harvest-evidence.js` and `status` use that folder.
   If `init` or `status` exits non-zero, first revert the pending edit from `pre-iter-N` exactly as step 8's REVERT does, then stop the refine session and report it to the user — never work around it, and never `init` without `--evaluator-ref`.

8. **Keep or revert** (`score` is the training-set pass rate from step 7; the bands are in percentage points of it; see thresholds in REFERENCE.md):
   - score > baseline + 2% → **KEEP**. Sync to runtime: `cp -r skills/<skill-name> ~/.claude/skills/`
   - score < baseline − 5% → **REVERT**: restore the edited file from step 6's copy, or delete it if the edit created it:
     `if [ -e "evals/<skill-name>/refine/pre-iter-N/<file>" ]; then cp "evals/<skill-name>/refine/pre-iter-N/<file>" "skills/<skill-name>/<file>"; else rm "skills/<skill-name>/<file>"; fi`
     Then check that nothing else differs from the copy; this must print nothing:
     `diff -rq -x SKILL-EVAL.md -x SKILL-REFINE-LOG.md "evals/<skill-name>/refine/pre-iter-N" "skills/<skill-name>"`
     If it lists a file, restore it the same way; if it lists a folder the edit created, remove it.
     `SKILL-EVAL.md` and `SKILL-REFINE-LOG.md` are not restored.
   - baseline − 5% ≤ score ≤ baseline + 2% (neutral) → **REVERT unless the edit made `SKILL.md` shorter, with fewer bytes (`wc -c`) than before the edit**; if it did, **KEEP** and sync as above, and the baseline stays as it was. A neutral Lever D or E edit is always reverted.
   - Log the iteration either way — failed hypotheses are data.

9. **Repeat** steps 5–8 until any convergence criterion is met (see REFERENCE.md).

10. **Final validation** — invoke `skill-eval` on the improved skill with `--context evals/project-context.json`. Do not implement a separate eval process — skill-eval IS the final validation. This produces a new `SKILL-EVAL.md` replacing the old one, giving a clean before/after comparison on identical methodology. The held-out `project-native`, `project-workflow`, and `multi-turn` scenarios run here for the first time during this refinement session. All 5 metrics (including resilience_score) must be reported. Its `init` also takes `--evaluator-ref <REF>`; any non-zero `init` or `status` exit stops the session and is reported (every kept edit was measured, so nothing is pending).

11. **Write report** — save `skills/<skill-name>/SKILL-REFINE-LOG.md` using the template in REFERENCE.md. If claude-mem is installed, persist a summary there too.

## Rules

- **One lever per iteration** — never change description AND checklist in the same iteration.
- **Revert faithfully** — restore the exact prior content from the iteration's copy, not a rewrite of it.
- **Never skip the per-iteration copy** — step 6 copies the skill folder before every edit.
- **Log every iteration** — including failed hypotheses. They're data.
- **Don't rewrite** — if pass rate < 40% after 5 iterations, recommend a rebuild instead: `superpowers:writing-skills` if installed, otherwise by hand per skill-scout's no-results step; then `skill-audit` → `skill-eval`.
- **Never skip the baseline backup** — `SKILL.md.baseline` must exist before the first mutation.
- **Never edit the evaluator** — no lever (A–E) may edit `skill-eval/scripts/harvest-evidence.js`, `skill-eval/scripts/run-manifest.js`, `skill-eval/scripts/generate-seed-evals.js`, `agent-eval/scripts/generate-agent-evals.js` or `skill-eval/REFERENCE.md` (under `skills/`; `run-manifest.js evaluator` lists them). The run manifest pins their sha256 and refuses an iteration whose evaluator changed.
- **Never edit a run manifest** — no step may edit an `evals/<skill-name>/iteration-*/run-manifest.json`, the `eval_manifest` that `refine-input.json` names, that field, or the `refine/evals.json` copy: they are what `--evaluator-ref` compares against.

See [REFERENCE.md](REFERENCE.md) for lever definitions, keep/revert thresholds, hypothesis guide, good/bad mutations, convergence criteria, and log template.
