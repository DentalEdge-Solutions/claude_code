# Evaluator pin in the run manifest (P0-11)

> Date: 2026-10-24 · Item: P0-11 (S5 roadmap), batch B1 PR-2 · Trace: OPP-14 · GAP-05 (refine part), GAP-11 ·
> Review round 1: PR2-R-1…R-10 applied · Review round 2: PR2-R-11, R-12, R-14 applied (R-13 kept as a note) · Review round 3: PR2-R-15 applied, R-16 recorded

## What is pinned and why

Before this change, `skills/skill-eval/scripts/run-manifest.js` pinned only the subject: the sha256 of the measured
SKILL.md or agent .md at `init`, plus a warning at `status` if it changed. Nothing pinned the evaluator. A refine loop
could therefore edit the harvester or the rubric (Lever E edits "the script", Lever D edits `REFERENCE.md`), and the
next eval would grade with the edited judge. Its scores would look comparable to the baseline, but they would not be.

`run-manifest.js` now pins five evaluator files. They are listed once, in `EVALUATOR_FILES`, relative to the skills
root and resolved from the script's own location, so the pin works in this repo's `skills/`, in a target project's
`skills/`, and in `~/.claude/skills/`:

- `skill-eval/scripts/harvest-evidence.js` derives trigger, dispatch and workflow evidence.
- `skill-eval/scripts/run-manifest.js` is the integrity gate itself.
- `skill-eval/scripts/generate-seed-evals.js` and `agent-eval/scripts/generate-agent-evals.js` generate the scenarios.
- `skill-eval/REFERENCE.md` is the grading rubric.

Each file must be a regular file: it is checked with `lstat`, so a symlink is refused. Otherwise an evaluator file
could be swapped for a link to a copy kept somewhere else.

| Command | Behaviour | Exit |
|---|---|---|
| `init` | Records an `evaluator` block (label → sha256) in `run-manifest.json`. Refuses, and writes no manifest, if a listed file is missing or not a regular file (fail closed) | 2 |
| `init --evaluator-ref <earlier run-manifest.json>` | Refuses, and writes no manifest, unless that manifest's `evaluator` record matches the files now. Records `evaluator_ref: { path, sha256 }`: the reference's absolute path and the sha256 of the file that was compared | 2 for every reference problem: missing, unreadable, empty, a directory, not JSON, no or malformed record, differs, no value, given twice |
| `check-ref <run-manifest.json>` | The same comparison, without writing anything. A refine runs it before its first edit | 0 match; 2 otherwise, including any unusable reference or a missing argument |
| `status` | Re-hashes the five files. If any changed, is missing or is not a regular file, or the manifest has no `evaluator` record (made before P0-11), it names each file with short hashes, ends with "Do not resume this iteration: start a new iteration", and exits 2. It does this even when every scenario is graded, and also when no scenario is recorded yet | 2 |
| `evaluator` | Prints `<sha256>  <label>` for each file, or `MISSING` / `NOT-A-FILE` in place of the hash | 0; 1 if any file is absent or not regular |

A record is always compared against the script's own list, never against the labels the record happens to contain.
So an empty `{}` record is refused, and so are a record missing a label and a record with a label that is no longer
on the list.

Exit 1 keeps its meaning: a usage error, or a resumable gap such as an ungraded scenario. Exit 2 is reserved for the
evaluator refusal. The subject warning works as before (a warning only).

## How a refine uses it

The `--evaluator-ref` flag closes the gap between two iterations. Without it, a refine could edit the harvester after
one iteration, and the next `init` would simply record the edited files. The refine definitions now work as follows:

1. **Reference.** The reference `<REF>` is the eval iteration's manifest. skill-eval and agent-eval now write its path
   into `refine-input.json` as `eval_manifest`. The refine reads it from there. If the field is absent, the refine
   stops and asks for a fresh eval; it never guesses from folder names (PR2-R-3).
2. **Check before any edit.** Before any backup or edit, the refine runs `run-manifest.js check-ref <REF>`. On any
   non-zero exit it stops, having changed nothing, and tells the user that a fresh eval made after P0-11 is needed
   first (PR2-R-2).
3. **Pinned scenario set.** In the same start step, the refine copies `evals/<x>/evals.json` to
   `evals/<x>/refine/evals.json` and checks `shasum -a 256` of the copy against `refine-input.json`'s
   `eval_scenarios_sha256`, which skill-eval and agent-eval now write next to `eval_manifest`. If the field is absent
   or the hash differs, the refine stops and asks for a fresh eval; the subject is unchanged. Every re-eval is told:
   do not regenerate `evals.json`, and dispatch only the scenarios in `refine/evals.json` (the training set, as
   before). So what a re-eval dispatches and what the harvester scores against are the same file, and it is the file
   the baseline eval used (PR2-R-11). The eval definitions back this up: their generation step and their
   caller clause say to skip generation in a mid-loop re-eval and to dispatch only the caller's
   `refine/evals.json`. After each 7c re-eval, the refine agents check that `shasum -a 256 evals/<x>/evals.json`
   still equals `eval_scenarios_sha256`. If it changed, they revert the pending edit and stop (PR2-R-15). The skill
   flows run their re-evals themselves, without generating scenarios, so they have no such check. The harvester looks for the scenarios two levels above each scenario folder,
   which is why the copy sits in `refine/` (`harvest-evidence.js` is pinned, so it is not changed).
4. **Its own folder.** Each mid-loop re-eval runs in `evals/<x>/refine/re-eval-N`. That folder is cleared at the start
   of each session, like the `pre-iter-N` copies, and is never an eval `iteration-<N>` folder (PR2-R-1). Every `init`
   passes `--evaluator-ref <REF>`, and so does the final validation, which is a normal eval iteration (it regenerates
   its scenarios as any eval does).
5. **Refusal mid-loop.** If `init` or `status` exits non-zero mid-loop, the refine first reverts the pending edit from
   `pre-iter-N`, exactly as its REVERT branch does, and then stops and reports. The staleness re-run `re-eval-0` has no
   pending edit ("none for re-eval-0", PR2-R-14). It never works around a refusal and never runs `init` without the
   flag (PR2-R-2, R-3).
6. **What it may not edit.** No lever (A–E) may edit the five files. No step may edit:
   - an eval `run-manifest.json` or the `eval_manifest` file (they anchor `--evaluator-ref`);
   - the `eval_manifest` and `eval_scenarios_sha256` fields;
   - the `refine/evals.json` copy (the scenario set checked against `eval_scenarios_sha256`). `--evaluator-ref` does
     not compare this file; round 1's wording said it did, and that is corrected (PR2-R-7, R-11).
7. **Evaluator subjects.** The refine refuses a subject that is part of the evaluator.

The eval definitions mirror this (PR2-R-4). When a caller gives an evaluator reference, the eval adds
`--evaluator-ref` to every `init`, including a restarted iteration. If the caller also names the iteration folder (a
mid-loop re-eval), the eval uses it, skips the resume check and writes no `refine-input.json`. Under a reference, any
exit 2 means: stop and report EVALUATOR_REFUSED, and never start another iteration. Only a stand-alone eval starts a
new iteration after a `status` refusal. They also say what an `init` exit 2 means.

## Definitions changed

- **Refine definitions:** `skills/skill-refine/SKILL.md`, `skills/agent-refine/SKILL.md`,
  `.claude/agents/skill-refine-agent.md` and `.claude/agents/agent-refine-agent.md`, as described above.
- **Eval definitions:** `skills/skill-eval/SKILL.md`, `skills/agent-eval/SKILL.md`,
  `.claude/agents/skill-eval-agent.md` and `.claude/agents/agent-eval-agent.md` changed in three places:
  - the resume check;
  - the `init` step (a caller's reference and the meaning of `init` exit 2);
  - the integrity step (exit 2 means a new iteration when the eval runs alone, and a stop under a reference);
  - the scenario-generation step: skip it in a mid-loop re-eval (PR2-R-15).
- **`refine-input.json` writers:** they add `eval_manifest` and `eval_scenarios_sha256` (`shasum -a 256` of the
  `evals.json` that iteration used). These are the four eval definitions above and the
  handoff format in `skills/agent-eval/REFERENCE.md`. No schema or writer script exists for `refine-input.json`;
  `scripts/telemetry/aggregate-usage.js` merges into it and keeps existing fields. The handoff example in
  `skills/skill-eval/REFERENCE.md` is **not** updated, because it is the pinned rubric file. `skills/skill-eval/SKILL.md`
  step 13 and `skill-eval-agent.md` state both fields (PR2-R-13, a note: a writer that copies the pinned example
  leaves the fields out, and the refine then fails closed).
- **Calibration runbook:** `fixtures/GATE-RUNBOOK.md` step 2 and the help text in `scripts/run-calibration.js` now
  use the next free `iteration-<N>`, never a resumed pre-P0-11 `iteration-1` (PR2-R-8). No test or calibration
  script hashes or reads the runbook. `run-native-audit.js` already takes the highest iteration.
- **skill-guardian** (`.claude/agents/skill-guardian.md` Phase 4, its own refine loop; PR2-R-12): this is a minimal
  change, because the agent is due for retirement (OPP-30).
  - It refuses the four evaluator subjects.
  - No lever may edit the five files.
  - One line says its loop has no evaluator-reference check, so use skill-refine-agent for any refine whose numbers
    will be relied on.
  - Its loop is otherwise unchanged.
- **Frontmatter:** `description:` is unchanged in every changed definition.

**A stricter choice than the roadmap.** S5 P0-11 says to "require a frozen copy when the subject is the evaluator".
The coordinator chose to refuse instead. When the subject is `skill-eval`, `agent-eval`, `skill-eval-agent` or
`agent-eval-agent`, skill-refine and agent-refine refuse to run and tell the user that refining the evaluator needs a
frozen-copy procedure, which does not exist yet. The owner is told of this choice.

## Hashes: B0 reference vs this PR

B0 recorded the hashes at `cbb6d4e` (`2026-10-23-factory-outcome-baseline/README.md` §4). This PR's hashes were taken
at its final head with `run-manifest.js evaluator`:

| File (under `skills/`) | B0 at `cbb6d4e` | After this PR | |
|---|---|---|---|
| `skill-eval/scripts/harvest-evidence.js` | `1ce61bc59a98e0f686575b6dfb735efc1220bc57043b900cd4960a7bda6b2646` | `1ce61bc59a98e0f686575b6dfb735efc1220bc57043b900cd4960a7bda6b2646` | unchanged |
| `skill-eval/scripts/run-manifest.js` | `4bd2551cbd803ac35ac804357b2318f12fabe0eaf4fd2f56e11567ecba62f340` | `ffe55e7e5a8b8f1e8e4d45d3b972e3c23dfea87f21fb13b13953305eefd988ba` | **changed by design** |
| `skill-eval/scripts/generate-seed-evals.js` | `3d09efd21d4cc9eef86dff78d80d35d2fb5fd8fba5a88e28e00da935b14ce4dc` | `3d09efd21d4cc9eef86dff78d80d35d2fb5fd8fba5a88e28e00da935b14ce4dc` | unchanged |
| `agent-eval/scripts/generate-agent-evals.js` | `7325c25cd05be19940a827e7d1bb9a561813f926603b4ef85f7c6b583e9f1100` | `7325c25cd05be19940a827e7d1bb9a561813f926603b4ef85f7c6b583e9f1100` | unchanged |
| `skill-eval/REFERENCE.md` | `3e461df6290a7607e661efe5bdc304315129f8fd99f51b6f2cf3b159c6114c76` | `3e461df6290a7607e661efe5bdc304315129f8fd99f51b6f2cf3b159c6114c76` | unchanged (not touched) |

**Consequence.** The evaluator recorded by any post-P0-11 run differs from B0 in one file, `run-manifest.js`. Under the
V-S5-5 rule ("a delta is reported only if P0-11's recorded hashes match"), no run before this PR can serve as a
same-evaluator baseline. No comparison is lost: B0 skipped the pre-edit eval runs by owner decision (B0 README §4), so
there is no pre-edit run to compare with. The first post-P0-11 runs (P1-10) become the baselines. The four unchanged
hashes show that harvesting, scenario generation and the rubric are the same evaluator that B0 recorded.

Any manifest written before this PR has no `evaluator` record, and `status` refuses it (exit 2). Such an iteration is
restarted, not resumed.

## Tests

The tests are in `scripts/run-manifest.test.js`. Every test that edits an evaluator file copies `skill-eval/` and
`agent-eval/` into a fresh `fs.mkdtempSync` directory and runs the copied script there. The repo's own files are never
modified, and each new test removes its temp dirs when it ends (PR2-R-9).

- **Acceptance.** The copied `harvest-evidence.js` is edited between `init` and `status`. `status` exits 2, names the
  file and prints "start a new iteration", even with every scenario graded.
- `status` also exits 2 for each of these:
  - the rubric `REFERENCE.md` edited;
  - a file deleted, or replaced by a symlink to an identical copy;
  - an ungraded scenario as well (exit 2 wins over 1);
  - zero scenarios;
  - no record;
  - an empty, partial, extra-label or array record.

  An unchanged evaluator with every scenario graded exits 0.
- **Acceptance (drift).** The list is read from `run-manifest.js evaluator`, and each listed file must be a regular
  file under the repo's `skills/`. The test also pins the exact list, so a rename or a removal fails until the list
  and this record are updated together. With a file deleted or symlinked, `evaluator` prints `MISSING` or
  `NOT-A-FILE` and exits 1.
- `init` refuses, and writes no manifest, when a listed file is missing, is a directory, or is a symlink.
- `init --evaluator-ref` succeeds on a match and records `{ path, sha256 }`. These references all exit 2 and write no
  manifest; `check-ref` exits 2 for the same list:
  - a missing file, an empty file, a directory;
  - garbage JSON, `null`;
  - no record, an array record, an empty record, a partial record, an extra label;
  - a changed evaluator;
  - no value, a flag given as the value, the flag given twice.

  `check-ref` exits 0 on a match, and 2 for a symlinked evaluator file or no argument.
- **Definition checks.** Each of the four refine definitions must:
  - name every listed file;
  - pass `--evaluator-ref`;
  - refuse the four evaluator subjects;
  - run re-evals in `refine/re-eval-N`, with no `init` of an `iteration-` folder;
  - copy `evals.json` for the harvester;
  - read `eval_manifest`;
  - run `check-ref` before the first `pre-iter-N` step;
  - revert from `pre-iter-N`, then stop on any non-zero exit;
  - forbid editing run manifests;
  - copy `evals.json` to `refine/` and check its `shasum -a 256` against `eval_scenarios_sha256`, both before the
    first `pre-iter-N` step;
  - tell every re-eval not to regenerate `evals.json` and to dispatch from `refine/evals.json`;
  - (refine agents only) re-check the `evals.json` hash after each 7c re-eval, between 7c and 7d, then revert from
    `pre-iter-N` and stop on a change, and state that the final validation regenerates its scenarios by design;
  - not claim that `--evaluator-ref` compares `refine/evals.json`;
  - say "(none for re-eval-0)" wherever `re-eval-0` appears.

  skill-guardian must name every listed file and refuse the four evaluator subjects. It must also say that its loop
  has no evaluator-reference check and point to skill-refine-agent.

  Each of the four eval definitions must state the stand-alone and the under-reference meaning of exit 2, the meaning
  of `init` exit 2, `eval_manifest` and `eval_scenarios_sha256` (with the `evals.json` it hashes). Each must also skip
  scenario generation in a mid-loop re-eval, both in its generation step and in its caller clause. The agent-eval
  handoff format must carry both fields. The round-1 checks
  failed 8 times on main's definitions.
- `scripts/refine-copy-paths.test.js` counted every `cp` from `evals/` as a restore, so the new `evals.json` copy
  into `refine/` failed it. A restore is now a copy that writes back outside `evals/`. A copy within `evals/` is
  still checked like the other copies into `evals/`: it must be gitignored, and a `mkdir -p` must come first.
- **Mutation testing.** 31 hand-made mutants of `run-manifest.js` were tested. They cover the 22 categories in the
  review, re-expressed for the new code, plus lstat, the duplicate flag, `check-ref`, the `evaluator_ref` path and
  hash, `NOT-A-FILE`, and exit 1 vs 2. The suite kills all 31.

## Remaining limits

- **The pin detects a change; it does not prevent one.** The refine agents hold Edit, Write and Bash and can still
  write the files. The pin turns a silent edit into a refused iteration. It does not make the files read-only.
  Hashing, then using, the files leaves a time-of-check gap, which is acceptable for detection.
- **Two layers, and the code layer depends on the caller.** The "no lever may edit the evaluator" and "never edit a
  run manifest" rules are an instruction layer: they work only if the model follows them. `--evaluator-ref` and
  `check-ref` are the code layer, and they act only when the refine runs them. The eval definitions' own `init` lines
  carry the flag only when a caller supplies a reference. A refine that omits the flag gets a fresh pin of whatever
  evaluator is on disk.
- **The anchor is writable (PR2-R-7).** The reference is a `run-manifest.json` under `evals/`. That folder is
  gitignored, and the refine can write to it. A refine that edits `harvest-evidence.js` and also rewrites the
  reference's `evaluator` block would pass `check-ref` and `--evaluator-ref`. Two things make such an edit detectable
  afterwards, but not preventable:
  - the new manifest records the reference's absolute path and the sha256 of the file it compared;
  - the "never edit a run manifest" rule.
- **The first refine after merge needs a fresh eval (PR2-R-2, R-3).** Every existing `refine-input.json` lacks
  `eval_manifest`, and every existing eval manifest lacks an `evaluator` record. So each refine stops at its start,
  having changed nothing, until skill-eval or agent-eval has been run again on that subject.
- **The reference is the session's baseline, not B0.** `--evaluator-ref` proves that the evaluator stayed the same
  within a refine session. If the evaluator was edited before the baseline iteration ran, that iteration pinned the
  edited files. To check against a fixed reference, compare a manifest's `evaluator` block with the table above
  (P1-10, V-S5-5).
- **`run-manifest.js` checks itself.** An edited `run-manifest.js` could skip its own check. The pin of
  `run-manifest.js` holds only while an unedited copy reads the manifest, for example the deployed copy in
  `~/.claude/skills/` or a reviewer re-running `status` from `main`.
- **Not pinned.** These are outside the list:
  - `skills/agent-eval/REFERENCE.md`, which is **agent-eval's judge rubric** (its "LLM Judge Rubric"). An agent-refine
    lever cannot edit it, because its levers edit only the agent file, but a change to it between iterations goes
    undetected. Pinning it is the first follow-up.
  - The skill-eval and agent-eval `SKILL.md` files and the two eval agent definitions, which hold the methodology
    prose.
  - The judge model.
  - The Codex runners under `scripts/codex/`.
- **Large files.** Files are read whole to hash them. An evaluator file of several GiB would fail with a stack trace
  and exit 1 instead of a refusal. This is noted, not changed: a regular file of that size in a skills tree is already
  abnormal, and symlinks to large files are now refused.
- **Installs are compared file by file.** A manifest made by one install (the repo's `skills/`) and checked by
  another (`~/.claude/skills/`) is refused if the two copies differ. This is intended: run
  `node scripts/check-skill-deploy.js` before an eval campaign.
- **The scenario hash is taken at handoff, not at init (PR2-R-16).** An eval writes `eval_scenarios_sha256` in
  step 13. Suppose `project-context.json` changed between the first run and the resume of an interrupted
  iteration, and the resume regenerated the scenarios. That iteration can then hold scenarios from two prompt sets,
  and the recorded hash describes only the later one. This predates P0-11. A follow-up could record the `evals.json`
  hash at `init` and re-check it at `status`. That changes `run-manifest.js`, and with it its pinned hash.
- **The final validation regenerates its scenarios by design.** It is a full eval. When it still fails, it writes a
  new `refine-input.json` whose `eval_manifest` and `eval_scenarios_sha256` agree with each other. When it passes,
  the old `refine-input.json` stays behind, and a later refine fails closed on the hash.
- **skill-guardian (PR2-R-12).** Its Phase 4 loop has the instruction-layer rules only: the never-edit list and the
  evaluator-subject refusal. It has no code check: no `check-ref`, no `--evaluator-ref`, and no manifest for its
  re-scores. Its re-scores are therefore not comparable under V-S5-5. This closes when skill-guardian is retired
  (OPP-30). Until then, use skill-refine-agent for any refine whose numbers will be relied on.
- **Deploy.** The changed skills (skill-eval, agent-eval, skill-refine, agent-refine) take effect in Claude Code only
  after they are deployed to `~/.claude/skills/` and `check-skill-deploy.js` passes. The owner does this after merge.
