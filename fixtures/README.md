# fixtures/

Committed test assets for the Codex native-audit calibration test (Phase 3 of the ground-truth
rebuild plan; see `docs/evaluations/claude-code-codex-architecture-evaluation.md`, Phase 8/F1).

This directory lives at the **repo top level, deliberately not under `skills/`**, so that:

- `find skills/ -mindepth 1 -maxdepth 1 -type d` (dynamic skill discovery, used throughout
  `CLAUDE.md`'s "Always" rules) never enumerates it,
- `install.sh` never installs it into a target project,
- the "deploy to `~/.claude/skills/` after editing" rule never applies to it.

These fixtures are inert reference data. Nothing here is a real, usable skill.

## Contents

- **`mutant-brief-writer/`** — a deliberately defective brief-writing skill recreating the 4
  injected defects from the Phase 8 calibration test that the original mutant (never persisted)
  demonstrated:
  - `SKILL.md` — the mutant definition itself. Carries the header comment
    `<!-- CALIBRATION FIXTURE — intentionally defective. Never install, never refine. -->`.
  - `expected-findings.json` — ground truth: one entry per defect, with `anchor_quote` (exact text
    from `SKILL.md`), which layer is expected to catch it (`native_metric:...` or
    `native_audit:<checklist_item>`), and the Phase 8 native-pipeline result
    (`caught` / `partial` / `missed`).
- **`mutant-notes-summarizer/`** — a second deliberately defective skill (a meeting-notes
  summarizer) with 4 injected defects in classes deliberately distinct from `mutant-brief-writer`'s:
  over-narrow trigger (fires only on one exact phrase), phantom script (a step runs
  `scripts/notes/extract-actions.js`, which doesn't exist), multi-turn redundancy (every step
  re-confirms already-given info), and a dead step (its guard condition can never be true). Same
  file layout (`SKILL.md` + `expected-findings.json`) and the same immutability rules. Run via
  `--fixture mutant-notes-summarizer` on `scripts/run-calibration.js`.
- **`golden-target/`** — a small, clean, benign skill (a changelog-entry formatter) used two ways:
  1. As a concrete `--target` for `generate-seed-evals.js` when generating scenarios for the
     mutant (`--target fixtures/golden-target`), so mutant scenarios name a real sibling instead
     of echoing the mutant's own vague description.
  2. As a grading calibration reference: `golden-transcript.md` is a realistic with-skill
     transcript for one direct scenario, and `expected-scores.json` records the known-correct
     score band (±1 tolerance) per rubric dimension. Re-grading the transcript should land inside
     every band — if it doesn't, the grader (not the fixture) has drifted. Measured via
     `scripts/run-grader-calibration.js`:
     ```bash
     node scripts/run-grader-calibration.js generate --judges 5   # writes N blind judge prompts
     # run each judge-prompt-<i>.md as an independent subagent → scores-<i>.json
     node scripts/run-grader-calibration.js check                 # bands + variance → report
     ```
     Judge prompts are blind by construction (no bands, no notes, fixture preamble stripped);
     `check` writes `GRADER-CALIBRATION-REPORT.md` with per-dimension mean/spread and fails on
     any out-of-band score or spread > 2.
- **`score-candidates/body-candidates.json`** — invented, inert skill candidates with full SKILL.md bodies
  (P0-05). `scripts/score-candidates.test.js` scores them in the legacy body form and in the
  agent-output form derived from them (body removed, `body_keyword_hits` computed by the scorer's
  substring rule) and asserts an identical ranking and identical scores. Record:
  `docs/evaluations/2026-10-25-p0-05-scout-read-only-fetcher.md`.
- **`GATE-RUNBOOK.md`** — the exact human-invoked command sequence for the Phase 3 live gate
  (generate → native eval → native audit `--live` → check). See that file before running the gate.

## Immutability rule

**The defects in `mutant-brief-writer/SKILL.md` are the point of the fixture — never "fix" them.**

- Never edit `mutant-brief-writer/SKILL.md` to resolve the vague trigger, the self-contradiction,
  the dropped step, or the filename mismatch. Doing so breaks the calibration test's ability to
  prove the native-audit layer catches what the native pipeline misses.
- Never run `skill-refine` or `agent-refine` against anything in `fixtures/`.
- Never install `fixtures/mutant-brief-writer/` or `fixtures/golden-target/` into `skills/` or
  `~/.claude/skills/` — not even temporarily. If a workflow (e.g. `skill-eval-agent`) needs to read
  the mutant, invoke it with explicit paths (`--def-path`, `--evals-path` on
  `scripts/codex/run-native-audit.js`; see `GATE-RUNBOOK.md`) rather than copying the fixture into
  `skills/`.
- If a defect stops reproducing (e.g. a generator or grader change accidentally "fixes" the
  mutant's effect), that is a regression in the pipeline, not a reason to update the fixture —
  investigate the pipeline change first.
- `golden-target/` should stay clean and boring on purpose. If it starts triggering interesting
  edge cases, that's a sign it has drifted from "small benign calibration skill" — revert it,
  don't feature-creep it.

## How to run calibration

1. **Generate mutant scenarios** (dry-run-safe, no Codex calls):
   ```bash
   node scripts/run-calibration.js generate
   ```
   Writes `evals/fixtures/mutant-brief-writer/evals.json` and reports the description-echo lint
   result. See `GATE-RUNBOOK.md` for what to do if the lint flags the mutant's own vague
   description (that's signal, not a bug).

2. **Run the native eval** on the mutant via `skill-eval-agent`, using explicit paths (never copy
   the mutant into `skills/`). See `GATE-RUNBOOK.md` step 2 for the exact invocation.

3. **Run the native audit** (human-invoked, spends Codex API credits):
   ```bash
   node scripts/codex/run-native-audit.js mutant-brief-writer skill \
     --def-path fixtures/mutant-brief-writer/SKILL.md \
     --evals-path evals/fixtures/mutant-brief-writer/evals.json \
     --live
   ```

4. **Check the results against ground truth** (dry-run-safe, no Codex calls):
   ```bash
   node scripts/run-calibration.js check
   ```
   Writes `evals/fixtures/CALIBRATION-REPORT.md` — a per-defect caught/missed table diffed against
   `mutant-brief-writer/expected-findings.json`, plus an overall 4/4 verdict.

Full instructions, including the exact skill-eval-agent invocation and pass/fail condition, are in
`GATE-RUNBOOK.md`.
