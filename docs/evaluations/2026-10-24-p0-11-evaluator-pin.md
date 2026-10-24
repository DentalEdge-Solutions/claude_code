# Evaluator pin in the run manifest (P0-11)

> Date: 2026-10-24 · Item: P0-11 (S5 roadmap), batch B1 PR-2 · Trace: OPP-14 · GAP-05 (refine part), GAP-11

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

`node skills/skill-eval/scripts/run-manifest.js evaluator` prints the list with the current sha256 of each file.

| Command | Behaviour | Exit |
|---|---|---|
| `init` | Records an `evaluator` block (label → sha256) in `run-manifest.json`. Refuses, and writes no manifest, if a listed file is missing or not a regular file (fail closed) | 2 |
| `init --evaluator-ref <earlier run-manifest.json>` | Refuses, and writes no manifest, if that manifest has no `evaluator` record or its record differs from the files now. The path is recorded as `evaluator_ref` | 2 (1 if the file cannot be read as JSON) |
| `status` | Re-hashes the five files. If any changed or is missing, or the manifest has no `evaluator` record (made before P0-11), it names each file with short hashes, ends with "Do not resume this iteration: start a new iteration", and exits 2. It does this even when every scenario is graded and every artifact is present | 2 |

Exit 1 keeps its meaning: a usage error, or a resumable gap such as an ungraded scenario. Exit 2 is reserved for the
evaluator refusal. The subject warning works as before (a warning only).

The `--evaluator-ref` flag closes the gap between two iterations. Without it, a refine could edit the harvester after
iteration N, and the `init` for N+1 would simply record the edited files. The refine definitions now pass, to every
re-eval in a session (mid-loop and the final validation), the manifest of the iteration that produced
`refine-input.json`.

## Definitions changed

- `skills/skill-refine/SKILL.md`, `skills/agent-refine/SKILL.md`, `.claude/agents/skill-refine-agent.md` and
  `.claude/agents/agent-refine-agent.md` were changed in three ways:
  - No lever (A–E) may edit the five files, and each definition names them.
  - Every re-eval is initialised with `--evaluator-ref <the baseline iteration's run-manifest.json>`. A refusal stops
    the session and is reported to the user, never worked around.
  - The refine refuses a subject that is part of the evaluator.
- `skills/skill-eval/SKILL.md`, `skills/agent-eval/SKILL.md`, `.claude/agents/skill-eval-agent.md` and
  `.claude/agents/agent-eval-agent.md`: the resume check and the integrity step say that `status` exit 2 means
  "start a new iteration".
- `description:` frontmatter is unchanged in all eight files.

**A stricter choice than the roadmap.** S5 P0-11 says to "require a frozen copy when the subject is the evaluator".
The coordinator chose to refuse instead. When the subject is `skill-eval`, `agent-eval`, `skill-eval-agent` or
`agent-eval-agent`, skill-refine and agent-refine refuse to run and tell the user that refining the evaluator needs a
frozen-copy procedure, which does not exist yet. The owner is told of this choice.

## Hashes: B0 reference vs this PR

B0 recorded the hashes at `cbb6d4e` (`2026-10-23-factory-outcome-baseline/README.md` §4). This PR's hashes are taken
at its head, with `run-manifest.js evaluator`:

| File (under `skills/`) | B0 at `cbb6d4e` | After this PR | |
|---|---|---|---|
| `skill-eval/scripts/harvest-evidence.js` | `1ce61bc59a98e0f686575b6dfb735efc1220bc57043b900cd4960a7bda6b2646` | `1ce61bc59a98e0f686575b6dfb735efc1220bc57043b900cd4960a7bda6b2646` | unchanged |
| `skill-eval/scripts/run-manifest.js` | `4bd2551cbd803ac35ac804357b2318f12fabe0eaf4fd2f56e11567ecba62f340` | `0b9d1958e92cbf7b8a7f0a3d44a126224598f57d68144fa13646e7762c884c37` | **changed by design** |
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
modified.

- **Acceptance.** The copied `harvest-evidence.js` is edited between `init` and `status`. `status` exits 2, names the
  file and prints "start a new iteration", even with every scenario graded.
- The same happens for the rubric `REFERENCE.md`, for a deleted file, and when the iteration also has an ungraded
  scenario: exit 2 wins over 1, and the closing line never says "Resume".
- An unchanged evaluator with every scenario graded exits 0.
- **Acceptance (drift).** The list is read from `run-manifest.js evaluator`, and each listed file must exist under the
  repo's `skills/`. The test also pins the exact list, so a rename or a removal fails until the list and this record
  are updated together.
- `init` refuses, and writes no manifest, when a listed file is missing or is a directory.
- A manifest from before P0-11 (no `evaluator` block) is refused.
- `--evaluator-ref`: init succeeds when the evaluator matches. It refuses, and writes no manifest, when the evaluator
  differs or the referenced manifest has no record. A missing value, a flag given as the value, or an unreadable file
  is an error. The flag's value is not mistaken for the iteration dir.
- Each of the four refine definitions names every listed file, passes `--evaluator-ref`, and refuses the four
  evaluator subjects. Each of the four eval definitions says that exit 2 means a new iteration. These definition
  checks fail on main's definitions (8 failures) and pass on this branch.

## Remaining limits

- **The pin detects a change; it does not prevent one.** The refine agents hold Edit, Write and Bash and can still
  write the files. The pin turns a silent edit into a refused iteration. It does not make the files read-only.
- **Two layers, and the code layer depends on the caller.** The "no lever may edit the evaluator" rule is an
  instruction layer: it works only if the model follows it. `--evaluator-ref` is the code layer, and it acts only when
  the refine passes it. The eval definitions' own `init` lines do not carry the flag. The refine adds it through its
  prompt to the eval run (agents) or its own `init` line (skills). A refine that omits the flag gets a fresh pin of
  whatever evaluator is on disk.
- **The reference is the session's baseline, not B0.** `--evaluator-ref` proves that the evaluator stayed the same
  within a refine session. If the evaluator was edited before the baseline iteration ran, that iteration pinned the
  edited files. To check against a fixed reference, compare a manifest's `evaluator` block with the table above
  (P1-10, V-S5-5).
- **`run-manifest.js` checks itself.** An edited `run-manifest.js` could skip its own check. The pin of
  `run-manifest.js` holds only while an unedited copy reads the manifest, for example the deployed copy in
  `~/.claude/skills/` or a reviewer re-running `status` from `main`.
- **Not pinned.** These files are outside the list:
  - `skills/agent-eval/REFERENCE.md`, which carries agent-eval's own "LLM Judge Rubric".
  - The skill-eval and agent-eval `SKILL.md` files and the two eval agent definitions, which hold the methodology
    prose.
  - The judge model.
  - The Codex runners under `scripts/codex/`.

  The spec fixed the list at five files. Adding `agent-eval/REFERENCE.md` is a candidate follow-up.
- **Installs are compared file by file.** A manifest made by one install (the repo's `skills/`) and checked by
  another (`~/.claude/skills/`) is refused if the two copies differ. This is intended: run
  `node scripts/check-skill-deploy.js` before an eval campaign.
- **Deploy.** The changed skills (skill-eval, agent-eval, skill-refine, agent-refine) take effect in Claude Code only
  after they are deployed to `~/.claude/skills/` and `check-skill-deploy.js` passes. The owner does this after merge.
