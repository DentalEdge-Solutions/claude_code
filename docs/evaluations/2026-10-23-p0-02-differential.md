# P0-02 differential (the P0-01 baseline)

> Date: 2026-10-23 · Items: P0-01, P0-02 (S5 roadmap), batch B1 PR-1 · Branch `fix/p0-unpinned-installs`
> Rules: active decision 2026-10-15 "Changing a regex security pattern needs a differential and a timing check";
> S5 P0-02 "the differential count measured in this PR is the baseline for P0-01"

Measured by the author. The independent review of PR-1 is a separate record.

## 1. CI differential over the tree before P0-01 (the P0-01 baseline)

The branch's `scripts/ci-scan-skills.js` was run, with the branch's `static-scan.js`, over main's tree at `0a6cd66`
(before any P0-01 edit), against the migrated baseline.

| Pass | Path | Check | Severity | Lines | Resolution |
|---|---|---|---|---|---|
| general | `skills/repo-audit/SKILL.md` | unpinned-install | FLAG (in code) | 35, 55 (`npx repomix`), 61 (`pip install gitingest`) | P0-01: pinned to `npx -y repomix@1.18.1`; the gitingest fallback removed |
| general | `skills/project-audit/SKILL.md` | unpinned-install | FLAG (in code) in 467086e; BLOCK after review round 1 | 180 (`npx ecc-agentshield scan --fix`); 4, the frontmatter `(npx ecc-agentshield)`, once `(` starts a command (round 1) | P0-01: pinned to `@1.4.0` (both lines) |
| general | `skills/project-audit/SKILL-AUDIT.md` | unpinned-install | FLAG (in code) | 20 (`npx ecc-agentshield`) | pinned to `@1.4.0` (an audit record of the same skill; P0-01's acceptance: every case on the first differential is pinned or baselined) |
| general | `skills/skill-audit/REFERENCE.md` | curl-pipe-shell | FLAG (in code) | 161, 173: the rows that document the pattern | reworded so the documentation does not contain a literal pipeline into a shell |
| general | `skills/skill-audit/REFERENCE.md` | wget-pipe-shell | FLAG (in code) | 161, 173 | as above |
| general | the 3 baseline entries (`child-process-require` in three `*.test.js` harnesses) | | BLOCK | | unchanged, migrated to the pass + repo-relative path key |
| conformance | (none) | | | | the four extra scopes had no finding |

So the baseline count is **5 findings in 4 files, plus the 3 baseline entries**. After this PR the differential is
0 new, 0 stale.

**Correction to the 467086e commit message.** It said "every new finding is unpinned-install". That holds for the
scanner: the only new check in `static-scan.js` is `unpinned-install`, and no finding of main's scanner was lost.
At the CI level it does not hold. 2 of the 5 new CI findings are `curl-pipe-shell` and `wget-pipe-shell` FLAGs that
main's scanner already produced. They are new to CI only because CI now counts the conformance checks at any
severity.

## 2. Severity: S5 says BLOCK, the active decision says FLAG in code (R-11)

S5 P0-02 asks for "a new BLOCK-severity rule". The active decision of 2026-10-15 ("static-scan severity depends on
where a command appears") makes a BLOCK-level command that appears only in markdown code a FLAG.

`unpinned-install` follows the decision: BLOCK in prose and in shell scripts, FLAG in markdown code. The decision
is an active owner decision, and an unpinned install in a sourced skill's code block is common. A BLOCK there would
refuse most sourced skills outright, which is what the decision was made to avoid.

| Context | Effect |
|---|---|
| This repository (CI) | No difference. `ci-scan-skills.js` counts the conformance checks at any severity, so a FLAG in a code block still fails the build |
| skill-audit vetting an external skill | An unpinned install in a fenced block is a FLAG (it needs the user's confirmation), not a BLOCK |

## 3. Scanner differential, main vs branch (round 2, after the review)

Harness: scratch only (`differential-r2.js`). Each file is scanned by main's `static-scan.js` and by the branch's.
Then two checks are made:
- every finding main produces must be produced by the branch, compared on file, check, severity and quoted detail;
- every finding only the branch produces must be `unpinned-install`.

| Corpus | Files | Main findings | Branch findings | Main findings lost | New, of another check |
|---|---|---|---|---|---|
| main's tree (`0a6cd66`) | 832 | 240 | 267 | 0 | 0 |
| branch tree (this commit, records included) | 834 | 238 | 264 | 0 | 0 |
| synthetic variants | 80,157 | 7,346 | 38,192 | 0 | 0 |

**How the synthetic set is built and labelled.** It crosses 77 commands with 26 command-position prefixes and 7
prose-position prefixes, 10 suffixes, and 6 file kinds (markdown prose, fenced markdown, shell, text, JS, JSON).
Each command is labelled before the run:
- unpinned: expect a hit in command position;
- pinned or not a package: expect none;
- `@latest`: expect a hit anywhere;
- another check: expect none.

Every sample in the kinds the rule reads agrees with its label (0 disagreements). The prose-position unpinned
samples are not hits, by design: 7,420 samples, a documented limit.

**The new real-tree hits are outside the CI scopes.** Most are in `docs/` and `CLAUDE.md`: command examples in
evaluation reports and plans.

**Against the 467086e scanner:**
- the only real-tree change is `project-audit/SKILL.md` going from FLAG to BLOCK, through its frontmatter line;
- 1,011 synthetic hits were dropped, all labelled not-a-hit: the `--package=…@x.y.z` and `-t`/`--target` false
  positives (R-3);
- 19,063 synthetic hits were added, all `unpinned-install`.

## 4. Timing (1 MB sweep)

- **Inputs:** 76 hostile inputs of about 1 MB each. They are the reviewer's 40 generators, the reviewer's 6
  prototype extras, and 30 of the author's own for the round-2 forms: continuation runs, prefix runs, pip skip
  kinds and npx `-p` runs.
- **Runs:** 4 patterns (the shipped regex, and its npx, pip and `@latest` parts) × 2 modes (`test` and global
  `matchAll`) = 608 runs.
- **Worst:** 15.8 ms (shipped regex). No run over 50 ms.
- **At 4 MB:** the worst input took 54.3 ms with a global match.
- **In the suite:** `scripts/static-scan.test.js` scans 117 of these inputs through the real CLI, each asserted
  under 2 s with a 20 s per-scan timeout.

An earlier form, without its command-start anchor, took 350 s on 1 MB, so the anchor is what keeps the rule linear.
Round 2 also stops the anchor from matching after a backslash-newline continuation. Without that, every
continuation line would be a new start that scans to the end of the input.

## 5. Mutant

The two `unpinned-install` table entries were deleted from `static-scan.js`. Both suites turned red:
- `ci-scan-skills.test.js`: 31 failures;
- `static-scan.test.js`: 89 failures.

## 6. Known limits

Listed in `skills/skill-audit/REFERENCE.md`, under the Dangerous Bash table: "`unpinned-install`: what it reads"
and "Known limits".
