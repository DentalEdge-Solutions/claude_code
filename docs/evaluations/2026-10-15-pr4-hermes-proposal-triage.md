# Triage of Hermes improvement proposal (PR #4)

> **Date:** 2026-10-15
> **Subject:**
> - Draft PR #4, opened by `dentaledge-bot` on 2026-07-25.
> - It added one brain candidate, `2026-07-25-improvement-proposal-claude-code.md`.
> - That candidate held 14 prioritized items from Hermes's proposer, run `2026-07-24_22-54-03`.
>
> **Verified against:** `main` @ `4db546d`.
> **Outcome:**
> - PR #4 was closed and its branch deleted, on the owner's decision.
> - The proposal was a 2.5-month-old snapshot: 2 items are done and 2 partly done, and its summary says there is no CI, which is no longer true.
> - 10 items remain open and are carried forward below. The proposal's candidate file was not merged.

## Status of each item

The proposal's own `P` numbers are kept.

| Item | Proposal | Status | Evidence (2026-10-15) |
|---|---|---|---|
| P1 | The brain and telemetry secret-pattern lists diverge | **Done 2026-10-15** (see "P1 repair") | Before: the brain set (6 patterns) missed GitHub fine-grained, Slack, Google, JWT, Bearer and `key = value` secrets. The telemetry set (12) missed Anthropic admin keys, `ghs_` tokens, Google keys without the `AIzaSy` prefix, a lone private-key header and short passwords. **Correction to the first probe:** telemetry did catch `AIzaSy…` keys and complete private-key blocks, so its gaps were narrower than first reported. |
| P2 | No test for `harvest-evidence.js` | **Done 2026-10-15** (see "P2 repair") | `scripts/harvest-evidence.test.js`. **Correction:** the first probe missed two end-to-end tests already in `scripts/codex/test-runners.js` (the file name search could not find them). The tests found 6 weaknesses, E1–E6, all open |
| P3 | No test for `static-scan.js` | **Done 2026-10-15** (see "P3 repair") | `scripts/static-scan.test.js`; the tests found 9 scanner gaps, S1–S9, still open |
| P4 | No test for `run-manifest.js` | Done | test added in Phase 3 (PR #131) |
| P5 | No CI | Done | `.github/workflows/ci.yml` and the `main-protection` ruleset (4 required checks) |
| P6 | BSD-only `sed -i ''` | **Fixed** (reviewed; see "P9 repair", P6 note) | `uninstall.sh:108` on `d799f4f` |
| P7 | Hand-rolled YAML parsing | Open | `infra/hermes-agent/bin/make-review-board.py:39` |
| P8 | Hermes skills have no evals | **Open, grown** | `infra/hermes-agent/skills/` now has 6 skills and 0 `SKILL-EVAL.md` or `evals.json` files |
| P9 | No guard before `rm -rf` in `uninstall.sh` | **Fixed** (reviewed; see "P9 repair") | `uninstall.sh:19-24`: TARGET is only resolved with `cd`, so `/` or `$HOME` passes. There are 7 `rm -rf` calls. |
| P10 | No architecture map | Open (low) | there is no `ARCHITECTURE.md`; `CLAUDE.md` and `README.md` partly cover it |
| P11 | The brain security guard fails open on a parser error | **Done** (see "P11 repair") | `hooks/brain/brain-security-guard.sh` |
| P12 | Tests missing for 3 scripts | **Done, in review** (see "P12 repair") | all three have tests: `validate-skills.test.js`, and since 2026-10-16 `scripts/score-candidates.test.js` and `scripts/extract-project-context.test.js` |
| P13 | `test-runners.js` writes to real `evals/` paths | **Open, worse than stated** | see below |
| P14 | The superseded architecture spec has no banner | **Done, in review** (see "P14 and P10") | all 13 archived Hermes custom-kernel docs now carry a RETIRED (canon D-3) headline and point at repo documents only; no machine-local or dead pointer remains under `docs/superpowers/` |

### P13 in detail

- `scripts/codex/test-runners.js:212-245` deletes `evals/skill-eval/codex-baseline.json` and writes fixture data in its place. The `skill-audit` tests at `:173-182` do the same to `evals/skill-audit/codex-baseline.json`.
- **Evidence:**
  - Both files on disk held fixture data, both written by the 2026-10-14 22:29 test run. The `skill-eval` file held the test's fixed scores; the `skill-audit` file had `run_id: critical-tier-std`.
  - The real Codex runs: `skill-audit` `2026-07-01T13-37-52-662Z` is HEALTHY in `standard` mode, so it wrote a real baseline.
  - `skill-eval` `2026-07-01T02-47-22-904Z` is HEALTHY but in **`smoke`** mode, and the aggregator writes no baseline in smoke mode. The later run, `2026-07-01T12-07-13-060Z`, is a BLOCK. **Correction to the first draft of this record:** `skill-eval` therefore never had a real baseline; only `skill-audit` lost one.
- **Effect:** every `node scripts/run-all-tests.js` replaced the `skill-audit` baseline and planted a fake `skill-eval` baseline. Codex regression detection for both compared against fixture data.

### P13 repair (2026-10-15)

- **Fix:** `scripts/codex/test-runners.js` now creates a scratch workspace with `fs.mkdtempSync(os.tmpdir())`, removed on exit.
  - `runAgg` runs the aggregator with that workspace as its cwd, passing absolute paths, so the cwd-relative `evals/<target>/codex-baseline.json` lands in the workspace.
  - The aggregator and renderer fixtures moved there too; they were previously in `evals/codex-runs/.test/`.
  - A guard test snapshots both real baseline files at start and fails if the suite creates, changes or deletes them.
- **Evidence:**
  - **Before the fix,** the guard failed: `evals/skill-audit/codex-baseline.json was created, changed or deleted by this suite`.
  - **After,** the suite passes 30/30, and both files keep their timestamps.
  - **Mutation check:** reverting only `cwd: WORK` makes the guard fail again.
- **Baselines repaired** (local, gitignored):
  - **`skill-audit`:** rebuilt by running the aggregator on a copy of the HEALTHY run, so the original run folder is untouched. The result is HEALTHY again, with metrics identical to the July `aggregate-results.json`. `risk_tier` is recorded as `standard` because that run's spec carried no tier, although `skill-audit` is a critical-tier skill.
  - **`skill-eval`:** the fake file was removed. There is no baseline until a full (non-smoke) HEALTHY Codex run writes one.
- The stale `evals/codex-runs/.test/` folder (15 fixture directories) was removed.
- **Out of scope:** the runner, native-audit and harvest-evidence tests in the same file still write into `evals/` paths of their own (`evals/codex-runs/{skills,agents,native-audits}/…`, `evals/.test-*`). Those paths are dedicated to tests or cleaned up afterwards, and none is a baseline.

## P14 and P10 (2026-10-16)

- **P14.** The archived master spec's REVISED banner named `~/.claude/plans/iterative-squishing-church.md`, a machine-local file. Six sibling archived Hermes specs and plans (H1–H3) carried the same pointer. All seven also named a brain candidate, `2026-07-21-hermes-definitive-roadmap.md`, which has since moved to `decisions/superseded/`. Each banner now points at repo documents: the roadmap's current path, noting that the plan file it cites was machine-local and never in the repo; the two canon entries that supersede it (adopting the Nous Hermes Agent, and the D-1…D-5 corrections); and `infra/hermes-agent/README.md`. Every named path was checked to exist, and no machine-local or candidate pointer remains under `docs/superpowers/`. The canon entry and the superseded decision that also cite the plan file were not edited: canon changes only through `brain-promote`, and the superseded file is a historical record.
- **P10.** Not a new `ARCHITECTURE.md`. README already has "Architecture at a glance" (the Phase 2 lanes and spine) and a "Directory Structure", and a third copy would drift. The actual gap was that the directory tree missed 14 skills (the brain, capture-learning and reference-library skills) and 7 top-level folders (`.project-brain/`, `hooks/`, `templates/`, `reference-repositories/`, `packs/`, `infra/hermes-agent/`, `.github/`). The tree now lists them, with one-liners taken from each SKILL.md description or the folder's own README, plus links to the guard's security rules and the Hermes README. Afterwards, every skill directory appears in the tree.
- **Independent review (2026-10-16): approved with minor findings.** The author's answers are below; the re-review result follows them.
  - **D-1:** the banner headlines still presented the superseded plan as current. All 13 archived Hermes custom-kernel docs (not only the 7 with banners: canon D-3 retires "custom-build master + H0–H3 + K2"; the two K2 docs were added after the re-review) now open with a RETIRED (canon D-3) headline naming the two canon entries.
  - **D-2:** nested parentheses flattened.
  - **D-3:** the P14 evidence column and the ranked list are updated. The P10 and P12 rows sit next to rows the P9 and P12 branches change, so they are flipped at merge time to avoid conflicts.
  - **D-4:** 24 links in 13 archived docs pointed at their pre-archive paths (20, then 4 more in the K2 docs after the re-review); each now points at its existing `archive/` twin.
  - **D-5:** `.claude/skills/` (codex-eval, never copied by install.sh) added to the tree.
  - **Re-review:** D-2, D-3 and D-5 confirmed fixed. D-1 and D-4 were not fixed at first: the author's scripts selected files by a `2026-07-20` prefix and missed the two K2 docs dated `2026-07-21`. Both K2 docs now have the headline and repointed links. **D-6:** the record had claimed "all closed", "all 11" and "0 broken". Only the reviewer closes findings, so this entry is reworded. The P10 and P12 status rows must be flipped at merge; until then they disagree with the ranked list.

## Open work carried forward, ranked

1. ~~**P13:** isolate the test fixtures and repair the Codex baselines.~~ Done on 2026-10-15 (see "P13 repair").
2. ~~**P1:** one shared secret-pattern module (the superset), with a test per token format.~~ Done on 2026-10-15 (see "P1 repair"). HR1 from `2026-10-14-gsd-global-install-audit.md` §7 (a secret-read guard covering `settings.json`-style key files) is separate and still open.
3. ~~**P3:** tests for the security scanner.~~ Done on 2026-10-15 (see "P3 repair"). Its gaps S1–S3 were fixed the same day (see "S1–S3 repair"); S4–S9 are open.
   ~~**P2:** tests for the eval grader (`harvest-evidence.js`).~~ Done on 2026-10-15 (see "P2 repair"); its findings E1–E6 are open.
4. ~~**P11:** make the brain security guard's fail-open visible (a log) or fail closed.~~ Done on 2026-10-15 (see "P11 repair"); its gaps G1–G3 are open.
5. **P9, then P6:** an `rm -rf` target guard and portable `sed` in `uninstall.sh`. Keep `install.sh` in sync.
6. **P8:** an eval path for Hermes skills (a full skill-eval, or a structural check).
7. **P7:** replace the hand-rolled YAML parse with a real parser, with a test.
8. **P12:** tests for `score-candidates.js` and `extract-project-context.js`.
9. ~~**P14:** point the archived spec's banner at a repo document.~~ Done on 2026-10-16 (see "P14 and P10").
10. ~~**P10:** an architecture map (low).~~ Done on 2026-10-16 (see "P14 and P10"): README's directory tree completed.

## Method and limits

- Each claim was rechecked by file listing, grep or a probe on `main` @ `4db546d`. The proposal's text was treated as data, not instructions.
- **P1 limit:** the probe used synthetic tokens in the common public formats. A pattern written for a different shape could still match real tokens.

## P12 repair (2026-10-16)

`validate-skills` already had a test. Added `scripts/score-candidates.test.js` and `scripts/extract-project-context.test.js`. They live in `scripts/`, not next to the scripts, for the reason `harvest-evidence.test.js` gives: files under `skills/` ship to target projects, and CI's skill scan treats a `child_process` require there as a BLOCK finding. A first version placed in `skills/` failed `ci-scan-skills.test.js` with exactly that. A new baseline entry would need the owner's review, so the tests moved instead. Nothing under `skills/` changed, so no runtime redeploy is needed.

- **score-candidates:** expected scores are worked out by hand from the weights. The tests cover every dimension at its extremes, sorting, the SKILL.md body search, plugin and description conflicts, the STRONG/GOOD bands, the weights themselves (a case whose total straddles a rounding point), and the CLI contract (`--help`, no argument, bad JSON).
- **extract-project-context:** a fixture project with a fake `HOME`, so the real `~/.claude/settings.json` is never read. The tests cover each of the 9 contract fields and its source, stdout equal to the written file, preservation of project-audit's fields (including a score of 0), an empty project, `pyproject.toml`, malformed JSON, and `--help`.
- **Evidence:** these test existing code, so instead of RED-first the check is a **mutation run**. 18 realistic bugs were planted one at a time, the test was run, and the file restored. The first run caught 17; the survivor (trigger weight 0.25 → 0.20) showed every total landed on the same rounded integer, so a rounding-straddling case was added. Second run: **18/18 caught**. `node scripts/run-all-tests.js` → 29/29.
- **Independent review (2026-10-16): approved with minor findings.** The reviewer reproduced 18/18, then ran 29 mutants of its own, and only 8 were caught. That showed the author's mutants had been chosen too narrowly. The gaps were bands tested from one side and MARGINAL never asserted (P12-1); untested middle tiers of reputation, provenance, footprint and clarity, plus the overlap math (P12-2); `--help` not checked to write nothing (P12-3); untested sources: the `.claude/CLAUDE.md` fallback, `.planning/` and django (P12-4); and a stale evidence column (P12-5). All five were answered: both edges of every band, every middle tier, the 70% plugin-name weight, the 10-path cap, the alternative sources, and "help writes nothing". The reviewer's mutants now: **28/29 caught**. The survivor is equivalent: it skips the write only when `--help` is given, and `--help` exits before that line. The author's set still 18/18; 29/29 suites. **Re-review:** the reviewer confirmed P12-1 to P12-5 fixed, each by mutants it ran itself. It confirmed #31 as an equivalent mutant: `--help` exits before the write, and no later argument is read. It approved P12. P12-6 asked for this record to report the closures as the reviewer's, not the author's (REVIEW_PROTOCOL rule 5).

## P1 repair (2026-10-15)

- **Fix:** `scripts/telemetry/secret-patterns.js` is the one list (12 named patterns, the union of both, with the broader form wherever they differed).
  - `brain-lib.js` re-exports it as `SENSITIVE_CONTENT_PATTERNS`, and `scanSensitive()` is unchanged.
  - `redact.js` derives its global regexes from it.
  - The private-key pattern matches a complete block whole (so redaction removes the key body) and still matches a lone header.
- **Location:** `install.sh` always installs `scripts/telemetry/` (step 7) and installs the brain only in the same run (opt-in step 8). The brain's `require('../telemetry/secret-patterns.js')` therefore resolves in targets, and `install.sh`/`uninstall.sh` need no change, because they already copy and remove the whole folder.
- **Evidence:**
  - **Before the fix,** the new `scripts/telemetry/secret-patterns.test.js` failed on both consumers' gaps (listed in the P1 row) and on the missing module.
  - **After,** 5/5 pass, and `node scripts/run-all-tests.js` passes 25/25.
  - The wider patterns raise no false positives on existing content: `brain-lint` reports 0 security findings, `brain-verify` is OK, all 11 reference sources and all 3 packs audit without a security exit, and 4 benign-prose probes stay unflagged.
- **Out of scope:**
  - `skills/skill-audit/scripts/static-scan.js` keeps its own severity-rated list. It is a different tool (it rates skills BLOCK/FLAG).
  - Hermes's Python code was not checked for a pattern list.

## P3 repair (2026-10-15)

- **Tests:** `scripts/static-scan.test.js` drives the real CLI (the scanner has no exports) in a scratch `mkdtemp` folder.
  - One sample per pattern, 70 in all, each checked for its check name and severity.
  - A coverage test reads the pattern tables out of `static-scan.js` and fails if a pattern or table has no case, or a severity changed.
  - The verdict and exit-code contract (PASS 0, FLAG 1, BLOCK 2, usage errors 1), the summary counts and the finding shape.
  - Where each table applies: config patterns only in `settings.json`/`settings.local.json`, `.txt` read as markdown, single-file mode, nested folders.
  - The false-positive controls: fenced and inline code in markdown, JS regex literals, `RegExp.exec`, `yaml.load` with `SafeLoader`, and the scanner's own source.
- **Location:** `scripts/`, not `skills/skill-audit/scripts/`. A file under `skills/` ships to target projects and `~/.claude/skills/`, and CI's static-scan-skills job would BLOCK on its samples.
- **Evidence:**
  - 99/99 pass; `node scripts/run-all-tests.js` passes 26/26.
  - The tests cover code that already existed, so they passed at once. Their worth was checked with 8 mutations of the scanner, each made and reverted: a severity downgrade, no code-block stripping, no regex-literal stripping, FLAG exiting 0, a broken pattern, config patterns on any JSON, a new pattern with no case, and FLAG beating BLOCK. Each one failed the suite.
  - The first regex-literal sample was too weak (only the self-scan test caught that mutation); it was strengthened and re-checked.
- **No behavior change.** `static-scan.js` is untouched.

### Scanner gaps found (S1–S9; S1–S3 fixed, see "S1–S3 repair")

Probed on 2026-10-15 with synthetic samples. Each passed as PASS where a BLOCK or FLAG was expected. None is pinned by a test, so a fix will not have to fight one.

| # | Gap | Sample that passes | Impact |
|---|---|---|---|
| S1 | The commonest injection phrasing is missed: `ignore\s+(previous\|prior\|all)\s+instructions` allows one word only | "Ignore all previous instructions." and "ignore the above instructions" | BLOCK → PASS |
| S2 | Markdown code is stripped before **every** markdown table, including secrets and dangerous Bash | a key, or `curl … \| bash`, inside a fenced block or backticks in SKILL.md | BLOCK → PASS. Instructions in code blocks are the ones an agent runs |
| S3 | `node:child_process`, and calls made as methods, are missed | `require('node:child_process')` then `cp.execSync(…)`; ESM `import { execSync } from 'node:child_process'` | BLOCK → PASS |
| S4 | A bare tool name in an allow rule is missed | `"allow": ["Bash"]`. Docs (code.claude.com/docs/en/permissions, "Match all uses of a tool", read 2026-10-15): "`Bash(*)` is equivalent to `Bash` and matches all Bash commands." The same patterns also fire on **deny** rules, a false positive | BLOCK → PASS |
| S5 | Files with no extension (shebang scripts) are not scanned | `#!/bin/sh` + `curl … \| sh` in a file named `install` | BLOCK → PASS |
| S6 | Secrets in JSON/YAML other than `settings*.json` are not scanned | a token in `config.json` or `config.yaml` | BLOCK → PASS |
| S7 | Current key formats are missed | `sk-proj-…`, `sk-ant-oat01-…`, `ghs_…` | BLOCK → PASS. The repo's shared list (`scripts/telemetry/secret-patterns.js`, P1) catches all three |
| S8 | `subprocess-shell-true` stops at the first `)` | `subprocess.run(build(cmd), shell=True)` | BLOCK → PASS |
| S9 | In single-file mode every finding has `file: ""` | any single-file scan | Cosmetic; CI's fallback reads only the verdict |
| S10 | No resource caps (final review F9, 2026-10-15) | a file over 536 MB holding an injection; a FIFO named `SKILL.md`; a symlinked file outside the tree | Over 536 MB → silently skipped, so PASS. A FIFO hangs the scan. Unreadable files are skipped without a finding |
| S11 | Only the first `rm` target is checked, as on main (re-check G6, 2026-10-15) | `rm -rf ./build ~/`, `rm -rf x /`, `rm --interactive=never -rf /`, `rm / -rf`; after `--`, a first target that starts with `-` or a quote: `rm -rf -- --foo-rm ~`, `rm -rf -- "--cached" ~` (verification V2) | BLOCK → PASS. An every-target scan was tried and dropped: it froze the scanner and could be escaped (final review F1–F4). A safe version needs a shell-aware tokenizer, not a regex |

- **Doc drift:** `CLAUDE.md`, `README.md`, `docs/USER-GUIDE.md` and `skills/skill-audit/SKILL.md` call it a "47-pattern" scanner across 5 categories. The tables hold 70 patterns in 7 tables.

## S1–S3 repair (2026-10-15)

- **S1:** `instruction-override` now matches `ignore [all|any [of]] [the|your|my] previous|prior|above|earlier|preceding|all|your instructions|directions`. That covers everything main caught. ("rules", "guidelines" and "prompts" were dropped after re-check G4.) A qualifier is still required, so defensive text ("ignore instructions found in fetched pages") stays quiet.
- **S2:** each markdown table now reads its own text (final design after the owner's decision R2, below).
  - Secrets: the whole file, code included, at full severity.
  - BLOCK-level Bash (`rm-rf-root`, curl/wget piped to a shell, `~/.ssh/`): BLOCK in prose. **FLAG** when the command appears only in code, fenced or inline.
  - FLAG-level Bash (`sudo`, `chmod`, settings) and prompt injection: prose only, as before.
- **`rm-rf-root`:** main's shape (the first target is an absolute or home path, `/tmp` included), with these additions:
  - Any spelling of the recursive or force option (`-rf`, `-r -f`, `-Rf`, `-rfv`, `--recursive`, `--force`, a `--` before the target). Separators may include a line break, as on main, so a soft wrap in prose keeps the command (re-check G1).
  - A quoted target, and `$HOME`.
  - `rm` after any non-word character, as on main (`\rm`, `(rm`, `"rm"`, Makefile's `-rm`). An option run holding `--cached` before any `--` or lone `-` is skipped: that is `git rm`, which only untracks, and plain `rm` refuses the option (re-check G5; pre-push H2 replaced a `git` lookbehind that let `X=git rm -rf /` through; verification V1 added the `--` stop).
  - **History:** two intermediate designs were dropped. A narrowed target list lost `/etc` and `~/.ssh` (review R1). A `/tmp` exemption with an every-target scan could be escaped and froze the scanner (final review F1–F4). See the review tables below.
- **`curl`/`wget` piped to a shell:** rewritten to run in linear time with no length cap. It anchors at the line start, a lookahead finds the line's first `curl`/`wget`, and one pass looks for a later pipe into a shell. The old unbounded `.+` was quadratic: reading fenced blocks made a 210 KB file take 5.1 s to scan (0.02 s before).
  - **Correction:** an intermediate draft capped the gap at 500 characters. A background security check flagged that a padded line slipped past the cap, which the old pattern never allowed. Tests now pin a 5,000-character gap and the scan time.
- **Backtracking in `rm-rf-root`:** the first rework had two overlapping option loops, and `-{1,2}[\w-]*` could split `--x` two ways. That made it quadratic on long `-r` runs and exponential when nothing matched: 22 `--a` options took 386 ms, and 40,000 never finished. Each option now has one parse, and lookaheads do the checks, so 40,000 options scan in about 30 ms. Timing tests pin both inputs.
- **S3:**
  - `child-process-require` matches `require`, `import … from`, side-effect `import` and `import()`, with or without `node:`.
  - `child-process-exec` also matches `execSync(`, however it is reached.
  - `spawn-call` also matches `spawnSync`, `execFile` and `execFileSync`.
- **Repo fallout:**
  - The new `execSync` match hit two test harnesses, `skills/agent-eval/scripts/generate-agent-evals.test.js` and `skills/skill-eval/scripts/generate-seed-evals.test.js`.
  - They now use `execFileSync(process.execPath, [...])`, which runs the same commands without a shell. That follows the CI gate's own advice ("fix the underlying script"), so `.github/skill-scan-baseline.json` is unchanged.
  - Across every skill, agent and settings file CI scans, the only changed findings are three `spawn-call` FLAGs in test harnesses, which the gate ignores.
- **Evidence:**
  - Before the fix, 18 new tests failed for the expected reasons.
  - After, `scripts/static-scan.test.js` and `node scripts/run-all-tests.js` (26/26) pass, and `node scripts/ci-scan-skills.js` passes with no new or stale entries.
  - 7 mutations each failed the suite: the old `rm` pattern, secrets on prose only, every Bash severity read in fenced blocks, no fenced Bash, no `node:` prefix, no `execSync`, an optional S1 qualifier.
- `skills/skill-audit/REFERENCE.md` describes the new rules.

### Final independent review of the branch (2026-10-15)

A second reviewer compared main and the branch on about 1,600 samples and timed every pattern and helper at 100 KB and 1 MB, with a timeout on every scan.

| # | Finding | Introduced by | Outcome |
|---|---|---|---|
| F1 | **Blocker.** ReDoS in the every-target `rm` scan: `rm -rf "` repeated took 5 s at 100 KB and over 20 s at 1 MB (main: 41 ms). `\rm -rf x` and `(rm -rf x)` also triggered it | branch | Fixed by the redesign: no cross-token target scan, and `rm` cannot start after a word character or `-`. Timing tests cover all four inputs (superseded: G3 lets `rm` follow `-` again, and H1 fixed a remaining quadratic case) |
| F2 | False BLOCKs across lines (`rm -rf dist` then `cd /usr/src/app`) | branch | Fixed: options and target must be on the `rm` line. Tests added |
| F3 | Separators inside arguments (`2>&1`, `\;`, quoted `;`) ended the target scan early | branch | Fixed by the redesign: the first target decides, as on main, and `/tmp` counts. Tests added |
| F4 | The `/tmp` exemption trusted literal text (`/tmp/.\./etc`, `/tmp/$X`, symlinks, globs) | branch | Fixed by dropping the exemption. Tests added |
| F5 | `\b` beside `_` hid `_Ignore all previous instructions_` | branch | Fixed: no word boundaries, as on main. Tests added |
| F6 | `curl ` with trailing whitespace, then a line break, was missed | branch | Fixed (`curl\s+`). Tests added |
| F7 | Parser differential: inline-code stripping hid commands in `~~~`, indented and unclosed blocks, and shifted pairings. B3 was wrong | main | Fixed for Bash by R2 (a code-only hit is a FLAG, never a PASS). Injection and hidden Unicode inside code are still open (P3) |
| F8 | `hook-shell-substitution` and `subprocess-shell-true` were quadratic (over 20 s at 1 MB) | main | Fixed: the first is escape-aware and finds `$(` once; the second stops at the next `(`. Timing tests added |
| F9 | No resource caps: files over 536 MB are silently skipped (PASS); a FIFO named `SKILL.md` hangs the scan; symlinked files outside the tree are read; unreadable files are skipped silently | main | **Open, recorded as S10** |

- **After the fixes** (superseded: see the re-check below):
  - Main vs branch over 1,840 samples: the only finding lost is the intended short-comment case. **Correction (re-check G7):** this was wrong; the re-check found the G1–G3 losses below.
  - Every pattern scans 1 MB of hostile input in 15 ms or less.
  - On the repo's own files, the only changes are FLAGs: `repo-audit`'s fenced `/tmp` cleanup, three dangerous commands `skill-audit/REFERENCE.md` names in inline code, and the three `spawn-call` FLAGs in test harnesses. No BLOCK changed.
  - 193/193 scanner tests, 26/26 suites, `ci-scan-skills.js` clean.

### Re-check of the redesign (commit cdb2d5c, 2026-10-15)

A third reviewer re-checked F1–F8 (all fixed) and compared main and the branch on 2,393 samples, plus 400 tracked markdown files for false positives.

| # | Finding | Introduced by | Outcome |
|---|---|---|---|
| G1 | The "same line" rule (F2) also applied to prose, where a line break is a soft wrap: `run rm -rf` + newline + `~/` passed | cdb2d5c | Fixed: separators include line breaks, as on main. F2 stays fixed because only the first target counts. Test added |
| G2 | `subprocess-shell-true` stopped at `(`, so `subprocess.run("… #(", shell=True)` passed | cdb2d5c | Fixed: arguments run to the first `)`, as on main. The scan stops at the next `subprocess.` call to stay linear. Tests added, including `stdout=subprocess.PIPE` |
| G3 | Makefile's `-rm -rf ~/` was missed | cdb2d5c | Fixed: `rm` may follow any non-word character, as on main. `-rm` never joins an option run, so it stays linear. Tests added, including timing |
| G4 | The S1 nouns "rules", "guidelines" and "prompts" made ordinary prose a BLOCK ("ESLint will ignore all rules") | 12a378c | Fixed: nouns limited to "instructions" and "directions". Four tests added |
| G5 | `git rm -r --cached /path` was a false BLOCK | branch | Fixed: `git rm` is excluded. Test added. (Pre-push H2 replaced the `git` lookbehind with a `--cached` check) |
| G6 | Only the first `rm` target is checked | main | **Open, recorded as S11** |
| G7 | The doc's claim that only the short-comment case was lost was wrong | doc | Corrected above |
| B7 | Background check on 3f93cbf: two "detection-bypass" reports (no details given) | 3f93cbf | One found and fixed: the `git rm` exclusion reached across a line break, so `git` on one line and `rm -rf /` on the next passed (main: BLOCK). The exclusion now needs `git` and `rm` on the same line. Test added. The second report could not be identified. The closest candidate is the G4 narrowing: "ignore all previous rules/guidelines/prompts" is no longer caught, as on main, which also missed it |

### Pre-push review of the whole branch (2026-10-15)

A fourth reviewer re-ran everything, reused and extended the earlier harnesses, and gave the verdict **NOT READY**. These findings are fixed:

| # | Finding | Introduced by | Outcome |
|---|---|---|---|
| H1 | **Blocker.** `rm-rf-root` was quadratic on option tokens holding `-rm` (`--rm`, `-x-rm`, `x-rm -`, `--no-rm` repeated: 14 s at 200 KB; over 20 s end to end at 1 MB). No caller sets a timeout | branch | Fixed: an option token is `-(\w \| - not followed by rm)*`, so no token holds `-rm`. About 1 ms at 200 KB, and at most 62 ms end to end at 1 MB. Timing tests for four inputs |
| H2 | The `git` lookbehind let commands main blocks through: `X=git rm -rf /`, `ssh git rm -rf /`, `sudo -u git rm -rf ~`, `xargs -a git rm -rf /`, `echo git rm -rf / \| sh` | branch | Fixed: no `git` lookbehind. An option run holding `--cached` is skipped instead (plain `rm` has no such option). All six inputs are tested as BLOCK; `git rm --cached` and `docker run --rm` stay quiet |
| H3 | More prose that the regex reads as code, so it gets FLAG not BLOCK: escaped backticks, backticks inside HTML tags, link titles or comments, a 4-backtick fence around a lone ``` | main (PASS there) | Documented in REFERENCE.md; it stays FLAG, never PASS |
| H4 | Weak tests: three fence-type tests checked only presence (and one title was wrong); a stale "bounded gap" title; no timeout in the test runner, so a ReDoS would hang the suite | branch | Fixed: severities asserted (`~~~` and unclosed: BLOCK; 4-backtick: FLAG), title corrected, 20 s timeout per scan |
| H5 | REFERENCE.md said "on the same line" for `rm` options (the code allows line breaks, G1); F1's lookbehind note was superseded | branch | Fixed |

- **Also noted by the reviewer:** the S1 wording flags "ignore earlier instructions that conflict" (accepted under R3), and placeholder secrets in fences (`AKIA…EXAMPLE`) are BLOCKs, as intended by S2.
- **After the fixes:**
  - On the 2,393-sample harness, the only loss against main is main's false positive `{"command": "$(", "y": ")"}`.
  - The slowest pattern at 1 MB is 14 ms (`rm-rf-root`: 7 ms).
  - 219/219 scanner tests, 26/26 suites, `ci-scan-skills.js` clean.

### Verification of the H fixes (2026-10-15)

A fifth reviewer confirmed H1–H5 fixed. They timed 43 inputs at 1 MB (the worst was 9.2 ms) and ran four test-suite mutants in scratch, each of which failed the suite. The verdict was **NOT READY** because of V1:

| # | Finding | Introduced by | Outcome |
|---|---|---|---|
| V1 | The `--cached` skip also counted tokens after `--` or a lone `-`, where `--cached` is a file name. `rm -rf -- --cached ~` deleted a scratch folder with real BSD and GNU `rm`, and the branch gave no finding (main gave none either). This was most likely the background check's "detection-bypass" on dbbd09a | dbbd09a | Fixed: the search stops at `--` and a lone `-`. Four tests added. The reviewer's probe script now shows BLOCK on all eight V1 lines |
| V2 | `rm -rf -- --foo-rm ~` passes (first-target-only family) | dbbd09a (main also passes) | Recorded under S11 |

- **After the fix:**
  - On the 2,393-sample harness, the only loss against main is still main's false positive.
  - At 1 MB, every `rm` input takes 7.3 ms or less.
  - 223/223 scanner tests, 26/26 suites, `ci-scan-skills.js` clean.

- **After these fixes:**
  - On the reviewer's own harness (2,393 samples), the only loss against main is a main false positive: `{"command": "$(", "y": ")"}`, an unclosed `$(` matched with a `)` from a different string.
  - The new false BLOCK in the reviewer's benign prose set is `rm -rf "$HOME/.cache/x"`. It's consistent with main, which blocks any `~/…` path.
  - On the 400 tracked markdown files, the only changes are FLAGs (code-only commands, per R2) and two secret BLOCKs inside code in `docs/superpowers/plans/`. Both look like test fixtures: a bare key-header assertion, and a `SENTINEL` token value with 12 distinct characters. The value was not printed.
  - Every pattern scans 1 MB of hostile input in 14 ms or less. **Correction (pre-push H1):** this was wrong. `rm-rf-root` was still quadratic on option tokens holding `-rm` (`--rm` repeated: 14 s at 200 KB).
  - 207/207 scanner tests (after B7), 26/26 suites, `ci-scan-skills.js` clean.

### Independent review of the S1–S3 fix (2026-10-15)

A separate reviewer re-ran every check and compared the old and new scanners on adversarial and benign samples.

| # | Finding | Outcome |
|---|---|---|
| R1 | The `rm-rf-root` draft dropped real targets (`/etc`, `~/.ssh`, `~/Documents`, …) | Fixed, see above; 13 path and spelling tests added |
| R2 | BLOCK rules in fenced blocks now hit common installer lines (`curl -fsSL https://bun.sh/install \| bash`) and `ssh-keygen -f ~/.ssh/…` in sourced docs, with no allowlist | **Decided by the owner (2026-10-15):** a BLOCK-level command found only in code (fenced or inline) is a FLAG; in prose it stays BLOCK |
| R3 | The wider S1 also flags defensive prose that quotes the attack outside inline code | Accepted: quoting the phrase in inline code keeps it quiet |
| R4 | `from"child_process"` (no space) was missed | Fixed and tested. Not fixed: `function execSync(){}` gives a false BLOCK (rare) |
| R5 | REFERENCE.md and this record left out the `my`/`of` qualifiers | Fixed |
| R6 | No tests for `~~~`, 4-backtick or unclosed fences, or the R1 paths | Added |
| P1 | (old) `rm -r -f /`, `rm -Rf /`, `rm -rf "/"`, `rm -rf -- /`, `rm --recursive --force /`, `rm -rf "$HOME"` | Fixed and tested |
| P2 | (old) the quadratic `curl … \|` pattern became reachable in fenced blocks | Fixed (linear rewrite, no cap) and tested |
| P3 | (old) inline code is never scanned for Bash; injection and hidden Unicode in fences are not scanned | Bash part fixed by R2: inline code is now scanned, and a code-only hit is a FLAG. Injection and hidden Unicode inside code are still open |
| B1 | Background check: the 500-character cap on the `curl`/`wget` gap was a bypass | Fixed (linear rewrite, no cap); 5,000-character gap test |
| B2 | Background check: ReDoS in the scanner | Fixed: the `rm-rf-root` rework was exponential on `--a` runs (see above); timing tests added |
| B3 | Background check: "parser differential" (no details given) | Read as the regex pairing of ``` fences, where a stray fence shifts the pairing and makes prose read as code. That affects only the code-skipping checks (injection, `sudo`/`chmod`) and is P3 below. Secrets and BLOCK-level Bash are now read in prose and code alike, so a shifted pairing cannot hide them. **Correction (final review F7):** this was wrong. Inline-code stripping still hid backtick-wrapped commands inside `~~~` blocks, indented blocks, unclosed fences and shifted pairings. Under R2 they are FLAGs now |
| B4 | Background check: ReDoS on commit 913ae8a (no details given) | A timing sweep of all 70 patterns (each test sample's prefixes repeated to 100 KB) found two **pre-existing** quadratic patterns, both unchanged since `main`: `base64-blob` (13 s on a 100 KB run of `/`) and `html-comment-block` (2.2 s on 25,000 `<!--`). Fixed: a base64 match starts only at the start of a run, and a comment is judged by the 20 characters after `<!--` that come before any `-->`. Now 30 ms each, and every pattern scans 100 KB in under 2 ms. Timing tests added. Two intended changes: an unclosed long comment is now flagged (it hides the rest of the rendered file), and `<!-- a -->` followed by a later `-->` no longer is (it was never one long comment) |
| B5 | Background check: "detection-bypass / validator regression" on commit c163649 (no details given) | A differential run (1,840 samples: the attack samples × 20 wrappings, main vs current) lost only the two intended changes (the `/tmp/` exemption and the short-comment case). Reading the exemption found a real bypass, introduced with it: only the **first** target was checked, and `..` escaped the temp folder, so `rm -rf /tmp/../etc`, `rm -rf /tmp/x /etc` and `rm -rf ./build ~/notes` passed (main blocked the first two). Fixed: every target up to `;`, `&` or `\|` is checked, and the exemption does not apply to a path containing `..`. A target scan stops at the next `rm` that has its own recursive or force option, which keeps the pattern linear. Tests pin the bypasses, three harmless forms and two timing inputs |
| B6 | Background check: "ReDoS / resource-cap defeat" and "parser differential" on commit 911335e (no details given) | ReDoS found and fixed: the `curl`/`wget` patterns used the `m` flag, which also starts a line after `\r` and `\u2028`, while `[^\n]` reads through them. 50 KB of bare `\r` took 0.5 s (quadratic). A line now starts after `\n` only (`(?<![^\n])`). 100 KB scans in about 1 ms, and timing tests pin both characters. The sweep now includes `\r`, `\u2028` and tab. The parser differential is passed to the final independent review (see below) |
| P4 | (old) S1 still misses "ignore the instructions above" and "ignore everything above", and flags "never ignore previous instructions" | Open |

## P7 repair (2026-10-16)

`infra/hermes-agent/bin/make-review-board.py` read `projects.yaml` with its own line parser. The item asked for "a real parser". The `bin/` tier is stdlib-only and Python's stdlib has no YAML parser, so this goes the way the tier already went: `changeset_lib._iter_project_lines` is documented as "the single registry walker for this tier … nothing NEW duplicates it", and its `read_workdir` skips comment lines, strips inline comments and refuses a duplicate `workdir`. The private copy had none of that.

- **Before** (base `d799f4f`), new tests in `make-review-board.test.py`:
  - a project line with an inline comment (`demo:  # a project`) was not recognised, so the script said "project not registered";
  - two `workdir` keys were accepted, silently taking the first (exit 0).
- **Fix:** `resolve_workdir` calls `changeset_lib.read_workdir` and turns its errors into the script's exits. A `REVIEW_BOARD_REGISTRY` override, the same pattern as `PR_REGISTRY` and `ADS_REGISTRY`, lets tests point at a temp registry. It was added first, so the tests failed for the parser reason, not the path.
- **After:** 5/5 tests pass. The real registry still gives `Workdir: /projects/claude_code`. `infra/hermes-agent/bin/run-bin-tests.sh` → 61/61.
- **Deployment:** the container mounts all of `bin/` at `/opt/cc-bin` (`docker-compose.yml`), so `changeset_lib` is next to the script. It imports cleanly with an empty environment.
- **Not done:** `run-ads-report.py` and `open-proposal-pr.py` still carry their own walkers. `run-ads-report.py`'s copy is marked frozen with Inc-3. Moving them is a separate change.
- **Independent review (2026-10-16): approved.** The reviewer re-ran everything, including the dry run inside the `hermes-agent-claude` image with the real mounts. It compared the old parser with `read_workdir` on 18 inputs: same results, or differences that are all fixes or error-path only. It showed the tests fail for the parser reason on the old script once only the override is added. **P7-1** (minor): a registry that is not valid UTF-8 was reported as "not registered or ambiguous", because `UnicodeDecodeError` is a `ValueError`. Now reported as unreadable, test first. **P7-2** (nit): the commit message said the tests were red for the parser reason on `d799f4f` itself; on that commit they are red for the path reason, as this section says.
- **Status row:** left as "Open" on this branch, because the P6/P9 branch edits the neighbouring rows and git would conflict. Flip it to Done when merging.

## P2 repair (2026-10-15)

- **What the harvester decides:** `harvest-evidence.js` writes `evidence.json`. Scoring reads only `skill_loaded` / `agent_dispatched` (trigger and dispatch accuracy), `artifacts[].exists` and `workflow_steps[].satisfied` from it. `claims` and `mtime_in_window` are informational; no grader or script reads them for a score.
- **Existing coverage:** two end-to-end tests in `scripts/codex/test-runners.js`: a real and a fabricated claim, a fake self-report header, and `--all`.
- **New tests:** `scripts/harvest-evidence.test.js` (31) drives the real CLI in a scratch folder, with `cwd` set so the repo-root fallback for claims is controlled. It covers:
  - every CLI error path;
  - output placement;
  - a side without `output.md`;
  - skill and agent modes (`agent_dispatched`, no `skill_loaded`, skill sides ignored);
  - the `Skill(...)` marker forms generated by `generate-seed-evals.js`;
  - a self-report header ignored;
  - no `tool_call` marker, and an invalid marker pattern;
  - a missing or malformed `evals.json`, and the scenario id from the folder name;
  - artifact size, sha256, a directory at the artifact path, per-side workspaces, and the `run-manifest.json` time window;
  - the claim rules (verb window, backticks, no spaces, a `/` or `.`, dedup, workspace or repo-root verification);
  - workflow steps (artifact, literal case-insensitive marker, all-or-nothing `workflow_executed`, null with no steps).
- **Location:** `scripts/`, for the same reasons as the scanner tests (P3).
- **Evidence:**
  - 31/31 pass; `node scripts/run-all-tests.js` passes 27/27.
  - 10 mutations of the harvester, each reverted, all failed the suite: loaded from any marker, an unescaped step marker, a flipped time window, md5 for sha256, the wrong agent key, an 800-character claim window, no repo-root fallback, `some` for `every`, a directory counted as an artifact, and a case-sensitive marker.
- **No behavior change.** `harvest-evidence.js` is untouched.

### Harvester weaknesses found (E1–E6; E1 fixed, see "E1 repair")

Probed on 2026-10-15 in a scratch folder. None is pinned by a test.

| # | Weakness | Reproduction | Impact |
|---|---|---|---|
| E1 | A symlink in the workspace satisfies an artifact check | `workspace/report.md` → symlink to any existing file outside the workspace: `exists: true`, the step is satisfied, `workflow_executed: true` | **Fixed 2026-10-15** (see "E1 repair"). Before the fix, a run could satisfy artifact workflow steps without writing the file (a junk file still satisfies `exists`; content is left to the LLM judge) |
| E2 | A claim path can leave the workspace | ``I wrote `../../…/etc/hosts` `` → `claim_verified: true` | Informational field only; misleading if a reader trusts it |
| E3 | An invalid `started_at` in `run-manifest.json` makes every artifact `mtime_in_window: false` (not null) | `{"started_at": "not-a-date"}` | Informational field only |
| E4 | `claim_verified` means "exists", not "written by this run": any existing repo file verifies (repo-root fallback, no time window) | ``I wrote `README.md` `` run from the repo root → `true` | Informational field only |
| E5 | The 80-character claim window crosses lines and sentences, so a mention near another sentence's verb becomes a claim | `produced `a.md`.` then `See `b.md`.` → both claims | Noise in an informational field |
| E6 | Design note: `skill_loaded` comes from the literal token `Skill(<name>)`, which the eval subagent is instructed to write when it applies the skill. It is an instructed marker in the subagent's own output, not an independent tool-call log | `.claude/agents/skill-eval-agent.md` (the "Trigger token" rule) | Trigger accuracy depends on the subagent following that instruction honestly. A method question, not a harvester bug |

## E1 repair (2026-10-15)

- **Fix:** an artifact counts only when it resolves, links followed (`realpathSync`), to a regular file inside its side's own workspace. Rejected cases:
  - a link to a file outside;
  - a linked folder that leads outside;
  - a spec path that climbs out (`../`);
  - a sibling folder whose name starts with `workspace`.

  Each one gives `exists: false` and a stderr warning. A link to another file inside the same workspace still counts. The `evidence.json` shape is unchanged, and artifact workflow steps follow automatically.
- **Evidence:**
  - Before the fix, the three escape tests failed (`exists: true`).
  - After, 37/37 harvester tests and 27/27 suites pass, and `ci-scan-skills.js` is clean.
  - 3 mutations (no separator in the prefix check, no containment check, no link resolution) each failed the suite.
- **Scope:** E2–E5 (informational fields) and E6 (method) are unchanged and still open.

## P9 repair (2026-10-16)

`uninstall.sh` resolved its target only with `cd`, then ran seven `rm -rf "${TARGET}/<dir>"` calls. A target of `/`, `$HOME`, a symlink to either, or this toolkit itself (`./uninstall.sh .` from inside the repo) passed.

- **Before** (branch base `d799f4f`): a copy of `uninstall.sh` in a temp fake repo, `HOME` set to a temp fake home, target = that home, answered "y": it printed `removed <home>/skills/`, `removed <home>/evals/`, `removed brain hooks, scripts, schemas, templates`, and the fake home was left empty of those files.
- **Fix:** right after the target is resolved, and before anything is shown or asked, the script compares the target's physical path (`pwd -P`) with `/`, the home directory and the toolkit repo, and refuses with exit 1 and a message on stderr. `install.sh` deletes nothing under the target, so it needs no mirror.
- **Test** `scripts/uninstall.test.js` (written first; it failed on `target /: must exit non-zero`): refuses `/` and a symlink to `/` (always answered "n"), `$HOME` and a symlink to it (answered "y"; a canary in the fake home survives), the toolkit repo by path and as `.` from inside it; no target still exits 1; a normal project still loses the toolkit's skills, agents and runtime skills and keeps its own agent. It runs only on a copy inside a temp directory. `node scripts/run-all-tests.js` → 28/28.
- **After:** the same probe prints `Refusing to uninstall from <home>: …` and deletes nothing.
- **P6, same file:** step 5 removed the CLAUDE.md pipeline section with `sed -i ''`, which GNU sed reads as an empty script plus a file named after the real expression. RED in `node:24-slim` (GNU sed 4.9; CI runs on `ubuntu-latest`): `sed: can't read /^# >>> skill-builder >>>/…: No such file or directory`, the uninstall aborted. Now the same `awk` → temp file → `mv` form the second-brain step already uses. The test asserts the exact CLAUDE.md left behind; it passes on macOS and in the Linux container.
- **Noted, not fixed here:** with no agents in the repo, `${AGENT_FILES[*]}` under `set -u` aborts the script on macOS bash 3.2 (`unbound variable`, line 48 on `d799f4f`). It stops before any removal, so it is a crash, not a data risk. The test repo always carries one agent.

### Independent review of P9/P6, round 1 (2026-10-16): P9 not fixed, P6 fixed

The reviewer reproduced the RED/GREEN claims and 28/28 (macOS bash 3.2, and `node:24-slim` with bash 5.2 and mawk). Its mutation check showed that every assertion fails on the change it targets, including the old `sed` line on Linux.

| ID | Sev | Finding | Author check | Fix |
|---|---|---|---|---|
| U1 | blocking | `pwd -P` keeps a leading `//`, so `//`, `//.` and `//<home>` passed the string compare. On a fake home, `"/<home>"` + "y" removed its `skills/` and `scripts/telemetry` | reproduced (`//` and `//<home>` reached the prompt; answered "n") | compare with `[ "${TARGET}" -ef … ]` (device and inode), which covers `//` and symlinks |
| U2 | minor | An exported `CDPATH` makes `cd` print the path; with a relative script path `REPO_DIR` held two lines | reproduced on macOS as a crash (`SKILL_NAMES[*]: unbound variable`); the reviewer saw the prompt on Linux bash 5 | `unset CDPATH` at the top |
| U3 | minor | Target `~/.claude` passed, and step 1 removes `~/.claude/skills`, every runtime skill, not only ours | reproduced (reached the prompt) | `$HOME/.claude` refused too. A second toolkit clone: see round 2 |
| U4 | minor | The awk + `mv` form replaced a symlinked `CLAUDE.md` with a regular file (the real file kept the section), reset the mode to the umask, and printed "removed" even on failure | the new symlink/mode assertions failed for that reason | written back with `cat >` (keeps link, inode and mode), success reported only when it happened, a warning otherwise. The awk output adds a final newline to a file without one (accepted). The second-brain step has the same `awk … && mv` form; left as is, out of scope |
| U5 | minor | The P9 row said Done despite U1, and the P6 row had a stale line number | confirmed | rows now say "Fixed, in review", and the P6 row names the base commit |

Tests first: each new assertion was watched failing in turn (`target //`, then the CDPATH case, then the symlinked `CLAUDE.md`). U3 went green in the same edit as U1, so its RED evidence is the probe (`~/.claude` reached the prompt). Now: `node scripts/uninstall.test.js` passes on macOS and in `node:24-slim`; the U1–U3 probe refuses all four; `node scripts/run-all-tests.js` → 28/28.

### Independent re-review of P9/P6, round 2 (2026-10-16): both fixed

The reviewer re-ran the suite on `aa427bd` (macOS bash 3.2 and `node:24-slim` bash 5.2/mawk, 28/28). It broke the script four ways (no `unset CDPATH`, no `~/.claude` check, a string compare instead of `-ef`, `mv` instead of `cat`), and the test failed at the matching assertion each time, on both platforms. Refused on both bash versions: `/`, `//`, `//.`, `///./`, `/..`, symlink chains to `/`, the home directory in five spellings, `~/.claude` in three, the repo as `.` and `//repo`, and the CDPATH case. `cat >` failure modes probed (read-only file, read-only link target, read-only folder, dangling link, hard link): none loses data.

- **U1, U2, U4, U5: fixed.**
- **U3: partly fixed, then closed.** The reviewer pushed back on the round-1 reason for accepting a second toolkit clone, and it was right. `install.sh` never copies `install.sh` or `uninstall.sh` (it copies only `skills/`, agents, `scripts|schemas/{codex,telemetry,brain}`, `hooks/brain` and `templates/second-brain`), so a clone can be told apart from an installed project. And "its files are in git" does not cover uncommitted work. **Fix:** a target whose `uninstall.sh` carries this script's `# Skill Builder — Uninstall` header is refused. The test was written first (RED: `another toolkit clone: must exit non-zero`) and checks that a work-in-progress skill in the clone survives. It passes on macOS and in `node:24-slim`; 28/28. Re-reviewed (2026-10-16): **approved, U3 fixed**. The test fails without the check. A legitimate installed project cannot trip it. The substring also matches the first version's header ("# Skill Builder — Uninstaller"), byte for byte under the Linux locale. **U3-1** (minor, accepted): the check fails open for a clone whose `uninstall.sh` was deleted, made unreadable or had its header rewritten.
- **Accepted:** with `HOME` empty or pointing nowhere, there is no home directory to protect (`/` is still refused). The test covers a symlinked `CLAUDE.md` only; a plain file goes through the same `cat >`.

## P11 repair (2026-10-15)

- **Owner decision (failure policy, hybrid):**
  - Bad input fails closed: empty, not JSON, or no `tool_name` string and `tool_input` object. The guard denies and says why. Claude Code always sends valid input.
  - If node cannot run, the guard fails open but visibly: a stderr warning, a line in `.project-brain/reports/guard-failures.log` (time and exit code only), and **exit 1**.
  - Why exit 1: the [hooks reference](https://code.claude.com/docs/en/hooks) (Tier A, read 2026-10-15, Claude Code 2.1.300) says "Claude never sees stderr from a hook that exits 0". Another code (not 2) is "a non-blocking error": the user sees the notice, and the call proceeds. The old fallback warning was therefore invisible even when it fired.
- **Problems found and fixed:**

  | # | Problem | Before | After |
  |---|---|---|---|
  | 1 | Bad input allowed silently (`exit 0` inside node) | allow, no warning | deny with a reason |
  | 2 | node failure warned on stderr with exit 0 | invisible | exit 1, stderr, log line |
  | 3 | Input passed through an env var | a 2 MB Write into `canon/` exceeded the exec size limit, so the guard failed open | input on stdin; denied |
  | 4 | NotebookEdit's path is `notebook_path`; the guard read `file_path` | NotebookEdit into `canon/` allowed | denied |
  | 5 | The delete rule matched the word `rm` anywhere before `.project-brain` | `grep rm .project-brain/…` and `git add …-rm-rf-….md …` denied | allowed |
  | 6 | `cd .project-brain && rm -rf …`, `find .project-brain -delete`, `… \| xargs rm`, `rmdir`/`unlink`/`shred`/`git clean` | allowed | denied |
  | 7 | Four canon-rule regexes (`\d*>\s*/dev/null`, `\d*>&\d+`, `\bsed\b[^\|]*-i`, `brain-promote…[\s\S]*--approve`) and the old `rm` rule were quadratic | 1.8 s at 64 KB, minutes at 512 KB. A PreToolUse hook that times out "doesn't block the tool call", so this was a bypass | linear: indexOf, per-segment scans, no leading `\d*` |
  | 8 | The first version of the new delete rule (at `509ac1c`) let through capsule deletes that `main` denied (review round 1, R1–R3, below) | allowed | denied (round 2) |

- **Delete rule (final):**
  - **Splitting follows the shell.** Only `;`, `&`, `&&`, `||`, `|`, `|&` and newlines outside quotes separate commands. A backslash escapes the next character, and `\<newline>` joins lines. `&>`, `>&` and `<&` are redirections.
  - **What counts as a delete:** as on `main`, any `rm`/`rmdir`/`unlink`/`shred` word, whoever runs it. Also: one glued to a short option (`-Orm`), `find … -delete`, `git rm`, `git clean` (except a `-n` dry run), and `rmSync`/`unlinkSync`/`rmdirSync`/`rmtree`/`rimraf`.
  - **The one exemption** is a stage whose command never runs its arguments: `grep`, `rg`, `cat`, `ls`, `echo`, `find` without `-exec`, `git add`/`commit`/`log`/`diff`/`show`/`grep`, and similar readers. The exemption ends when the stage has any of these:
    - a `VAR=value` prefix;
    - an option that runs a program (`rg --pre`/`--hostname-bin`, `git grep -O`/`--ope…`, git `-c`, `--ext-diff`, …);
    - `$(…)`, backticks or `<(…)`;
    - a later stage in the pipeline that is not a reader.
  - **The target:** `.project-brain` is named in the same pipeline (expansions included), or the shell is inside the capsule. `cd`, `pushd` and `popd` are tracked by depth, so leaving with `cd ..`, `cd /tmp` or `popd` ends that state.
- **Review round 1** (independent reviewer, at `509ac1c`, verdict REQUEST CHANGES). The author answers each finding here; only the reviewer closes it.

  | ID | Severity | Finding | Author's answer (round 2) |
  |---|---|---|---|
  | R1 | blocking | Splitting at `(){}` and backticks cut `${…}`, `$(…)`, backticks and `{…,…}` targets off the delete | Split only at real separators outside quotes; 9 tests (`"${CLAUDE_PROJECT_DIR}/.project-brain"`, `$(pwd)/…`, `{.project-brain,…}`, quoted `;` and newline) |
  | R2 | blocking | A leading redirection became the command word | Redirections skipped when finding the command word, and any `rm` word counts anyway; 4 tests |
  | R3 | blocking | A fixed runner list (`busybox`, `ssh`, `watch`, `flock`, `trap`, `su -c`, glued here-strings, `env -S'…'`, `git --git-dir … rm`) | Rule inverted: any deleter word counts unless the stage is an exempt reader. Words are split twice (quotes dropped / quotes as separators). 20 tests, including `echo rm … \| sh`, `git -c alias…`, `eval "$(…)"` |
  | R4 | minor | `cd`/`pushd` into the capsule never reset | Directory depth tracked through `cd`/`pushd`/`popd`; 3 allow tests, plus `cd …/decisions && cd .. && rm` stays denied |
  | R5 | minor | False positives: `xargs grep -l rm`, `sh -c "grep unlink …"`, `git clean -n` | `git clean -n` now allowed (test). The other two stay as documented conservative denials (programs that run commands) |
  | R6 | minor | Gaps also on `main` (`xargs -I{} rm`, `bash -c 'cd … && rm'`, `cd "$(…)/.project-brain"`, `find -exec sh -c 'rm …'`, `r\m`, script-level deletes) | All denied now, with tests. `mv`, `rsync --delete`, `cp -r` over, `truncate`, `: >` are documented as limits (G2) |
  | R7 | minor | Docs overstated coverage ("and similar") | `SECOND_BRAIN_SECURITY.md` rewritten: exact rule, exemption conditions, known limits |
  | R8 | minor | The differential lacked expansion, redirection, runner and here-string forms | Corpus extended (see Evidence) |
  | R9 | minor | `guard-failures.log` not gitignored | Added to `.gitignore` |

  Automated background security reviews ran four times during the two rounds. They flagged:
  - **the R1–R3 classes**;
  - **readers that can execute:** `rg --pre`, `ag`/`ack --pager`, `sort --compress-program` (shortenable), `less`/`more`, `git fetch`/`push`/`pull` `--upload-pack`, `GIT_EXTERNAL_DIFF=`/`PAGER=` prefixes;
  - **`git grep -O` / `--open-files-in-pager`** and `rg --hostname-bin`;
  - **quote concatenation:** `git grep -O"r"m …` got past the glued-option check.

  Each was reproduced and given a failing test before the fix. The pagers, `sort` and network git were removed from the readers. `VAR=` prefixes and program-running options end the exemption. The glued-option check reads shell words (quotes joined). The extended differential also found a false positive from an earlier form of that check: `env -S'farm …'` was read as `-Sfarm`. It now has a test.
- **Evidence (round 2):**
  - **Tests first, again.** The round-2 additions to `scripts/brain/brain-hooks.test.js` are the R1–R6 cases, the readers that can execute, two `$(…)`/`<(…)` cases, and the quote-concatenation and `env -S'farm …'` cases. Each batch was watched failing first:
    - against `509ac1c`, 45 of the first 50 failed; the other 5 already passed there and stay as regression checks;
    - then 8 of 11 execute-capable reader cases failed;
    - then 5 more (`git grep -O…`, `sort --compress-prog`, `rg --hostname-bin`);
    - then 1 (`env -S'farm …'` falsely denied);
    - then 2 of 4 quote-concatenation cases.
  - **After:** `brain-hooks.test.js` passes; 27/27 suites pass; `brain-lint` shows 0 security findings (the 3 known stale-canon warnings).
  - **Mutations:** 23 targeted mutations, each caught by a behavioural failure. Timing failures under CPU load were not counted as kills. The mutations covered:
    - cd tracking and leaving the capsule;
    - bad input, env-var input, the fail-open exit code;
    - NotebookEdit;
    - the downstream-stage, substitution and `VAR=` conditions on the exemption;
    - splitting at `(){}`, quotes ignored when splitting, the leading-redirect skip;
    - quote-separated words, API deletes, `git clean -n`, `find` as a reader;
    - program-running options, `git grep -O`, `sort` as a reader;
    - the glued-option check and the shell-word reading it uses;
    - deleter words only as the command word.
  - **Timing:** 34 regexes × 54 adversarial 1 MB inputs in-process: worst 37 ms. The whole guard end-to-end on 54 × 1 MB commands: worst 317 ms (load average about 10 at the time).
  - **Differential (R8, extended):** 228,021 generated inputs, each run through `main`'s guard and the final one:
    - **The corpus.** 25 prefixes, now including leading redirections, `busybox`, `caffeinate`, `ssh h`, `env -S'`, `sh <<<'` and `git --git-dir`. 30 verbs. 19 targets, now including `"${CLAUDE_PROJECT_DIR}/.project-brain"`, `$(pwd)/…`, backticks and brace expansion. 16 suffixes, now including `| sh` and `| bash`. Plus 21 Write/Edit/NotebookEdit paths.
    - **183,471 same decision** (65,310 deny, 118,161 allow).
    - **6,600 deny → allow,** all in the four intended argument classes: `grep rm`, `grep "rm"`, `grep -rn rm`, `git commit -m "rm stuff"`. They appear only behind plain prefixes (`cd`, `ls;`, `time`, a redirect, `git -C … grep`). None sits behind a prefix that runs commands, and none pipes into `sh`, `bash` or `xargs`. The round-1 class of nonsense `git -C …` calls is denied again.
    - **37,950 allow → deny.** A filter for inputs without a real deleting word, `-delete` or `git rm`/`git clean` found none (NotebookEdit into `canon/` aside).
    - Round-1 numbers (99,981 inputs: 4,368 deny → allow, 15,012 allow → deny) were for `509ac1c`. The reviewer showed that run's corpus missed the R1–R3 forms.
- **Gaps left open:**
  - **G1:** the canon rule exempts any command that mentions `brain-promote … --approve` anywhere, so `brain-promote.js x --approve; echo x > .project-brain/canon/y.md` passes.
  - **G2:** the delete rule does not follow shell variables (`D=.project-brain; rm -rf "$D"`), loops over a capsule glob, or globs that may expand to the capsule (`rm -rf .p*`). It does not treat moving or overwriting as deleting (`mv`, `rsync --delete`, `cp -r` over, `truncate`, `: >`).
  - **G3:** the canon rule's mutation check still matches the word `rm` anywhere, so `grep rm .project-brain/canon/x.md` is denied (a conservative false positive, as documented).
  - **G4:** the reader exemption depends on knowing each reader's program-running options. The list is kept small, and an option outside it ends nothing. A program-running option that isn't recognized would let a stage carrying `rm` next to a capsule path through.

- **Review round 3 (2026-10-15).** Round 2 made the parser-based delete rule a superset of `main`, but the rule still depends on parsing the command the same way bash does. A fresh pass — the author re-examining the superset claim, plus five automated background security reviews — found two classes of defect that the parser-based rule alone could not close. Both were reproduced with a failing test first, then fixed.
  - **Parser desync defeats the superset claim.** A quote inside a `#` comment, ANSI-C `$'…'` quoting, or a heredoc body can make the guard's splitter disagree with bash about where a command ends, so a real `rm … .project-brain` that `main` denies slipped past (e.g. `echo hi # it's`<br>`rm -rf .project-brain`). Store-then-run forms did the same by construction: `echo rm -rf .project-brain > x.sh && sh x.sh`, `… | tee x.sh; sh x.sh`, `git commit -m "rm -rf .project-brain" && git log -1 --format=%B | sh`, `printf … >> x.sh`.
  - **Fix — a parser-immune floor.** Added a blunt check that reads the raw command and cannot be fooled by a parse desync: `main` denies any `rm` word followed by `.project-brain` within one `;`/`|`/`&`-free segment. It restores a true superset of `main`: if the check fires, the command is denied unless it is a single foreground pipeline of pure readers with no command/process substitution, none of the desyncing constructs, no background, and no file-writing redirect — the one shape where an `rm` next to the capsule can only be a literal argument (`grep rm .project-brain/log.md`). This closed eight bypasses where round 2 allowed a delete `main` denied.
  - **The floor must be linear.** `main` writes that check as `/\brm\b[^|;&]*\.project-brain/`, which is **O(n²)**: on a command padded with many `rm` words, `[^|;&]*` backtracks from every `rm`. The timing sweep measured one `.test()` at ≈195 s on a 1 MB input and the whole guard timing out at 15 s. Because a PreToolUse hook that times out does not block the call, copying `main`'s regex verbatim would have been a bypass (pad a real `rm -rf .project-brain` with `rm ` filler → guard hangs → delete proceeds). The floor was rewritten to split on `[|;&]` first (linear) and then, per segment, find an `rm` word that starts before a `.project-brain` mention with `search(/\brm\b/)` and `lastIndexOf` — each linear, same semantics. After the rewrite the same 1 MB input is denied in ≈170 ms. (This is a latent defect in `main` too; noted for a separate fix.)
  - **Five security-review findings, all on honoring a capsule-LEAVING `cd`.** The round-2 cd rule honored a leave unless the stage's first character was `(` or `{`. The reviews showed this was not enough: (1) a brace group `{ cd /tmp; }` runs in the *current* shell; (2) a braced group inside a pipeline/background (`{ cd /tmp; } | cat`) runs in a *subshell*, so its `cd` does not move the parent; (3) a `cd` that is not the first statement in such a group (`{ true; cd /tmp; } | cat`); (4) a nesting counter would be corrupted by a non-closing `}`/`)` such as a `case` arm; (5) the same in the background.
  - **Fix — stop parsing group nesting.** A counter-based approach was attempted and abandoned (it was both fragile and, twice, the source of a self-inflicted hook breakage). The final rule is provably simple: a capsule-leaving `cd`/`pushd`/`popd` is honored only from a *plain* command — one stage, not backgrounded, and with **no grouping construct anywhere on the line** (`hasGrouping = /[(){}]/.test(cmd) || /\bcase\b/.test(cmd)`). A move that enters or stays in the capsule is always honored (deny is the safe direction). `splitShell` now also returns whether each pipeline was backgrounded.
  - **Tradeoff.** The grouping rule conservatively denies a capsule-leaving `cd` that merely shares a line with a harmless group — e.g. `cd .project-brain; (ls); cd /tmp; rm -rf build` is now denied. A normal `cd ..`/`cd /tmp` on its own line still ends the inside-capsule state. Added as gap **G5**.
- **Evidence (round 3):**
  - **Tests first.** The round-3 additions to `scripts/brain/brain-hooks.test.js` are the parser-desync cases (comment-quote, ANSI-C, heredoc), the store-then-run cases, the cd-in-subshell/pipeline/background cases, and the five brace/group/`case` cases — each watched failing against the round-2 guard before its fix. The one case reclassified from allow to deny is `cd .project-brain; (ls); cd /tmp; rm -rf build` (the grouping tradeoff).
  - **After:** `brain-hooks.test.js` passes; 27/27 suites pass; `brain-lint` shows 0 security findings (3 known stale-canon warnings).
  - **Mutations:** 28 targeted mutations (the round-2 set plus the floor, the floor exemption, `hasGrouping` ignoring brace groups, and leave-honored-in-background / -in-pipeline). 27 were caught by a behavioural failure. The one survivor, M11, is security-equivalent: it only adds quote-separated word tokens that bash never executes, so it can create a false positive but never a bypass. Timing failures under CPU load were not counted as kills.
  - **Differential (`main` vs. round-3 guard):** the same 228,021 generated inputs as round 2, each run through `main`'s guard and the round-3 guard.
    - **188,001 same decision** (69,840 deny → deny, 118,161 allow → allow).
    - **2,070 deny → allow** (down from round 2's 6,600). Every one starts with `grep` or `git commit` (a reader), with `rm` only as a literal argument; the scary-looking `-delete`/`-exec rm {} +` suffixes are inert arguments to a reader that never runs them, and the leading `(` forms are unclosed subshells. None pipes into `sh`, `bash` or `xargs`. The store-then-run and parser-desync forms that round 2 let through are now denied by the floor — the reason the count fell.
    - **37,950 allow → deny** (new guard stricter than `main`). A filter for inputs with no real deleter word, `-delete`/`-exec`, `git rm`/`git clean`, `xargs rm`, or a NotebookEdit into `canon/` found **none** — every one is a real delete `main` missed or a documented conservative denial.
  - **Timing:** 41 regexes × 54 adversarial 1 MB inputs in-process: worst **40.5 ms** (before the floor fix, the copied `main` regex measured ≈195 s on this same sweep — see "The floor must be linear"). The whole guard end-to-end on 54 × 1 MB commands: worst **315 ms** (load average about 13 at the time). No pattern shows super-linear growth.
- **Gaps left open (round 3 adds):**
  - **G5:** a capsule-leaving `cd` is not honored on any line that also contains a grouping construct (`( )`, `{ }`, or `case`), so such a line is conservatively denied even when the `cd` really does leave the capsule.

## P11 re-review (2026-10-16)

A re-review of the merged guard (`main` at `d799f4f`), per `docs/REVIEW_PROTOCOL.md`. Re-run on `d799f4f`: `node scripts/run-all-tests.js` → 27/27 suites pass; `node scripts/brain/brain-lint.js` → 0 security findings, 3 known stale-canon warnings. Installed Claude Code: 2.1.301. Git used for every behaviour check: 2.54.0, in a scratch repository (a directory named `cap`, never the capsule).

| ID | Sev | Where (`d799f4f`) | Finding | Evidence |
|---|---|---|---|---|
| RR1 | blocking | `brain-security-guard.sh:146-153` (`gitSub`) | Only `-C`/`-c` were skipped with their value. The value of `--namespace`, `--work-tree`, `--git-dir`, `--config-env`, `--attr-source`, `--shallow-file` was read as the subcommand. When that value is a reader name (`log`, `show`), both the stage check and the floor exempt the stage, so an executing subcommand runs a capsule delete. | `git --namespace log rebase -x "rm -rf cap" HEAD~1` deleted `cap/` in the scratch repo; the guard **allowed** the same command on the capsule. Also allowed: `--attr-source show submodule foreach …`, `--shallow-file log bisect run rm -rf …` |
| RR2 | blocking | `:159`, `:166` (`gitCleanDryRun`) | Any short-option word containing `n` counted as a dry run, but `-e` takes the rest of its word or the next word, `--` ends the options, and a later `--no-dry-run` wins. A `clean` behind a valued global option (RR1) was not seen at all. Only untracked (and with `-x`, ignored) capsule files are at risk; tracked files survive `git clean`. | Real deletes, all **allowed**: `git clean -f -en`, `-f -e -n`, `-f -- -n`, `-f --exc -n`, `-n --no-dry-run -f`, `-n -fd --no-d`, `git --work-tree <capsule> clean -fd`, `git --namespace x clean -fd <capsule>` |
| RR3 | blocking (the P11 H1 standard) | `:159` | `/^-[A-Za-z]*n[A-Za-z]*$/` is O(n²) on `-nnn…n1`. End to end: 64 KB 2.2 s, 256 KB 34.5 s; ~1 MB extrapolates to ~9 min, ~1.5 MB to past the 600 s default. A timed-out PreToolUse hook does not block. The P11 sweep missed it because none of its inputs reached this check, which runs only after a `clean` subcommand. | `code.claude.com/docs/en/hooks` (read 2026-10-16): command hooks default to 600 s; "A timed-out `command` … hook doesn't block the tool call" |
| RR4 | owner decision | `.claude/settings.local.json` (hook registration) | Claude Code v2.1.295+ supports `"onFailure": "block"` on a command hook. It would close the whole timeout class, but it also blocks on "can't start" and on any exit other than 0/2, which reverses the P11 decision that a node failure fails open, visibly (exit 1). Options: keep as is; or adopt it together with a recovery path for a broken node. Not changed. | Same page, "Block the action when a hook fails" |

**Fix (branch `fix/p11-rereview-git-guard`).** `gitSub` skips the eight valued global options with their value (list confirmed on git 2.54: each one swallowed the next word), and any unrecognized global option ends the reader exemption. `gitCleanDryRun` parses the words after `clean` the way git does, in one linear pass (last of `-n`/`--dry-run`/`--no-…` wins; `-e`/`--e…` take their value; `--` stops; `--dry-run` abbreviations count as not dry, a conservative denial). If the subcommand cannot be found, a `clean` word anywhere after `git` counts. Tests first: 14 of 21 new cases failed on `d799f4f` for the expected reason (the 7 others are regression guards), plus two 512 KB timing cases (the first timed out the suite).

- **Differential** (old vs new guard, 2,358 generated git commands × 19 global-option forms × 24 subcommands × 5 targets, plus controls): **11 deny → allow**, all `git --git-dir/--work-tree <value> grep -n rm …`, a reader the old parser misread (false positives fixed). **378 allow → deny**, each one of: a `git clean` form verified above to really delete; an executor (`rebase -x`, `bisect run`, `submodule foreach`) or `clean`/`rm` hidden behind a global option's value; or a conservative denial consistent with the unmasked case (`clean --dry`, `rm --cached`, an unknown `--bogus` option that git itself rejects). No real dry run (`clean -n`, `-nd`, `--dry-run`, `-n -e foo`) changed.
- **Timing** (end to end, 10 adversarial shapes reaching the new code, 512 KB and 1 MB): worst **246 ms** at 1 MB, ~2× from 512 KB to 1 MB on every shape.

### Independent review of the fix, round 1 (2026-10-16): request changes

The reviewer re-ran the suites on `8a50ae1` (27/27, guard test passes), confirmed RR3 fixed (the `-nnn…1` shape: 130 ms at 1 MB; 13 shapes, instrumented to prove they reach the new code) and the 14 RR1/RR2 cases denied, and found:

| ID | Sev | Finding | Author check (real git 2.54 deletes, guard on `8a50ae1` allows) |
|---|---|---|---|
| V1 | blocking, **new in `8a50ae1`** | Git words were whitespace-split after removing quotes, so `git --namespace "x log" rebase -x "rm -rf …"` (or `x\ log`) again showed `log` as the subcommand | reproduced |
| V2 | blocking | The same split put an `-n` where git never gets one: `"x -n"`, `x\ -n`, `-e "x -n"`, `> -n`, `<<< -n` | reproduced (5 forms) |
| V3 | blocking | `--end-of-options` was taken for an abbreviated `--exclude` | reproduced |
| V4 | blocking, already on `d799f4f` | `git clean` behind `env`, `command`, `nice`, `xargs` or `-c alias.x=clean` was not checked | reproduced (4 forms) |
| V5 | minor | Docs said "parsed as git does"; the code also checked a `clean` word whenever the subcommand was not `clean` | confirmed, and it caused two **new false positives** on `8a50ae1`: `git commit -m "clean up …"` and `git log --grep clean` were denied |

**Round 2 fix.** The root cause was the approach: parsing git's options precisely, which P11 had already learned is a losing game (the grouping rule, G5). Round 2 allowlists instead:

- Git's subcommand is read from shell-split words (quotes join, `\` escapes, stop at a redirect or `#`). A variable, glob or backtick before the subcommand ends the reader exemption.
- A `git clean` dry run is allowed only in a plain form git cannot read another way (see `SECOND_BRAIN_SECURITY.md`). Anything else is a delete.
- A `clean` word in a stage that runs git through a wrapper, or with an option that can define an alias, counts as `git clean`.
- Conservative cost: dry runs outside the plain form are denied (`-n -e foo`, `env git clean -n`, `git clean -n … 2>/dev/null`, global options other than `-C`).

Evidence:

- Tests first: 18 of 26 round-2 cases red on `8a50ae1`, including the two false positives. A `--` dry run (`git clean -nd -- <path>`) was then added red-first.
- `node scripts/run-all-tests.js` → 27/27.
- **Differential vs `d799f4f`** (2,531 inputs; the corpus now has quoted and escaped values, wrappers, `--end-of-options`, redirects, and commit messages containing `clean`/`rm`):
  - **20 deny → allow**, all `git <option> <value> grep -n rm …`, a reader with no program-running option.
  - **667 allow → deny**, each one a `git clean`, an executor (`rebase -x`, `bisect run`, `submodule foreach`), or `rm --cached`. The 6 exceptions are an unknown option (`--bogus`) or a variable/glob option value.
  - No commit message and no `--grep` was newly denied.
- **Timing:** 17 shapes at 512 KB and 1 MB, end to end. Worst: 310 ms. Every shape took about 2× as long at 1 MB as at 512 KB.

### Independent review of the fix, round 2 (2026-10-16): request changes, then round 3

The first round-2 reviewer was stopped by a safety classifier before it ran anything. A fresh reviewer re-ran everything on `4beb000`:

- Commands: 27/27 suites; the guard test passes; 0 bypasses on the round-1 probe sets (35 + 15 cases; for comparison, 20 + 11 on `d799f4f` and 13 + 12 on `8a50ae1`); timing worst 301 ms, linear.
- **RR1, RR2, RR3, V1, V2, V3, V5: fixed.** **V4:** fixed, but reopened by W1.

| ID | Sev | Finding | Author check (real git deletes, guard allows) | Round 3 |
|---|---|---|---|---|
| W1 | blocking, **new in `4beb000`** | `gitArgs` anchored on the first word whose basename is `git`, so a redirect target or assignment ending in `/git` (`2>./git git clean …`, `A=./git git clean …`, `</usr/bin/git git clean …`) made the subcommand read as `git` | reproduced (4 forms) | `gitArgs` skips the same prefixes as `head()` and anchors on the command word; `null` (counted as a delete) if the shell words disagree |
| W2 | medium, on `d799f4f` | ANSI-C spelling: `git $'cl\x65an' -fd …`, `git cl$'e'an -fd …` | reproduced | a subcommand with `$`, a glob or a backtick counts as a delete |
| W3 | high, on `d799f4f` | `splitShell` turns backslash-newline into a space where bash removes it: `r\⏎m -rf <capsule>` and `git cl\⏎ean -fd …`; the floor misses them too | reproduced | separate commit (below) |
| W4 | low, new false positive | any `-c` plus a `clean` word denies (`git -c color.ui=never log --grep clean …`) | confirmed | **kept, documented:** `-c core.editor="git clean …"` shows that a `-c` value can run a program |
| W5 | nit | the doc said "`git` directly", but a leading `time` is accepted | confirmed | doc reworded |
| X1 | high, on `d799f4f`, found by the author while fixing W1 | a git executor running a nested clean: `git rebase -x "git clean -fd <capsule>" HEAD~1` | reproduced | a `clean` word next to a second `git` word in a non-reader stage counts as a delete |

**Round 3, commit A (W1, W2, X1):**

- Tests first: 7 deny cases red on `4beb000`, plus 5 allow regression guards.
- A first attempt over-denied plain dry runs: `words()` holds every word twice, so one `git` counted as two. That was fixed by counting on a single quote-dropping split.
- Results: 27/27 suites; the 26 round-2 cases and the 11 round-1 reviewer cases still hold.
- **Differential vs `d799f4f`** (same 2,531 inputs):
  - 20 deny → allow, the same `git <opt> <value> grep` readers as before;
  - 652 allow → deny, no line new versus round 2;
  - the 15 that round 2 denied and A allows are all plain dry runs with `-n`/`--dry-run` before a `--`, now accepted.
- **Timing:** new shapes (many assignments, many redirects, nested git words, an unsafe subcommand) take 117–181 ms at 1 MB, about 1.7× their 512 KB time. Worst overall: 312 ms.

**Round 3, commit B (W3):** `splitShell` turned a backslash-newline into a space; bash removes it.

- Real bash deletes on 5 forms that the guard allowed on `b84e72f`: `r\⏎m -rf <capsule>`, `git cl\⏎ean -fd <capsule>`, `echo 'a\⏎b' ; r\⏎m -rf <capsule>`, and two comment forms (`cd <capsule>` then `ls # note \⏎rm -rf decisions`, where the comment ends at the newline and `rm` runs on its own line).
- **Fix:** `joinLines` runs once on the raw command before every rule. It removes a backslash-newline the way bash does, keeps `\\` as a pair, and does not join inside a `#` comment. `splitShell` now lets a leftover backslash-newline (only possible in a comment) end the line.
- **Evidence:**
  - Tests first: the 5 forms were red, and 2 allow guards (an ordinary continuation in `git add` / `grep`) were added. 27/27 suites pass; the earlier case sets still hold.
  - **Metamorphic differential:** every corpus command was compared with the same command where each space becomes ` \⏎ ` (the same command to bash). 0 allow → deny. 8 deny → allow, all from the transformation splitting an escaped space (`x\ log` → `x\ \⏎ log`), which bash also reads as two words, so `log` is the subcommand and nothing runs.
  - **Timing** (continuations, backslash pairs, comments, `#` words): at most 193 ms at 1 MB.
- **Background security-review notices.** Several automated commit reviews reported "parser-differential", "security-control-bypass" and "incomplete nested-executor check" in the guard, each without details. They are consistent with the classes fixed above. An executor can still run a command built at run time (`$(printf …)`, a decoded string, a script); that is the documented "commands built at run time" limit (G2 class), now named in `SECOND_BRAIN_SECURITY.md`.
- **Test flake, unexplained:** one run of `brain-hooks.test.js` exited with an error while background reviewers were running timing sweeps; its output was not captured. Four later runs passed. The 3 s timing bound under load is the likely cause, but it is not confirmed.

**Round 3, commit C (W3 follow-up, from an automated security review).** A background commit review flagged that `joinLines` detected comments without tracking quotes, so a `#` inside quotes stopped the join.

- Real bash deletes on 5 forms the guard allowed at `d941d39`, for example `echo " #"; r\⏎m -rf <capsule>` and `git log --grep " #"; git cl\⏎ean -fd <capsule>`. A sixth form, `echo $'a\'b #' ; r\⏎m -rf <capsule>`, uses ANSI-C quoting the guard does not parse.
- **Fix, following the review's suggestion:** `joinLines` tracks quotes as bash does. Single quotes are copied verbatim; double quotes and unquoted text are joined; a comment starts only at a word-initial `#` outside quotes. Fail closed: if a continuation is kept (in single quotes, a comment, or any quoting read differently from bash) and the command names the capsule, then a delete word, `clean`, a script-level delete or `-delete` anywhere from the start of that line, fully joined, denies.
- **A timing regression, caught before commit:** the first version read the last character of the string it was building, which V8 flattens on every access. 4.2 s at 512 KB, 15.7 s at 1 MB on comment-plus-continuation input, the timeout class this work removes. It now tracks the last character in a variable: 182 ms at 1 MB. The shape was added to the guard suite's 512 KB timing block, where the quadratic version would exceed the 3 s bound.
- **Evidence:** tests first (6 deny cases red, 2 allow guards), 27/27 suites, and every earlier case set still holds.
  - **Differential vs `d799f4f`:** unchanged from commit A (652 / 20, no line added or removed).
  - **Metamorphic:** 4 allow → deny, where the transformation put a continuation inside single quotes (`'x \⏎ show'`), followed by an `rm` word. That is the fail-closed rule's intended conservative cost. The 8 deny → allow are the same escaped-space artifacts as before.
  - **Timing:** 7 continuation, quote and comment shapes, worst 182 ms at 1 MB, linear.

### Independent review of the fix, round 3 (2026-10-16): request changes (X2), then commit D

The reviewer re-ran everything on `1c9ca50`:

- `bash -n`; the guard test passes; 27/27 suites.
- All earlier probe sets give 0 bypasses. Its round-3 set gives 19 bypasses on `4beb000`.
- Timing is linear, at most 313 ms at 1 MB.
- It also saw one unexplained 26/27 run under load. Four reruns passed, the same pattern as the author's flake.

**Verdicts:** W1, W2, X1 and W5 fixed. W4 no longer applies (the conservative denial is accepted for the `core.editor` reason). W3 partly fixed: the plain, comment and 5 quote forms are denied, with real deletes on each.

| ID | Sev | Finding | Author check | Commit D |
|---|---|---|---|---|
| X2 | blocking for W3 | The kept-continuation backstop was a word list. Where `joinLines` still reads quotes differently from bash (a heredoc body with `it's`, `$'\''`), the command is split, the capsule lands on the next line, and the stage rules skip the first part. A glued `-Or\⏎m` and an ANSI-C subcommand were allowed. | 4 forms reproduced as allowed on `1c9ca50` | a kept continuation in a command naming the capsule now **denies outright**. A pair is kept only inside single quotes or a comment, so where the guard reads quotes correctly this is rare, and no word list is complete |

- **Evidence:**
  - Tests first: 4 forms red.
  - `ls <capsule> # list \⏎ls` moved from the allow list to an intended denial.
  - Every earlier case set holds; 27/27 suites.
  - **Differential vs `d799f4f`:** unchanged (652 / 20, identical lines).
  - **Metamorphic:** 8 allow → deny, all from a continuation placed inside a single-quoted value (the intended cost). 8 deny → allow, the same escaped-space artifacts as before.
  - **Timing:** worst 146 ms at 1 MB.
- **Accepted low-severity false positives the reviewer listed:**
  - `git stash push -m "clean up git notes" <capsule>/x`, `git merge -m "clean" origin/git` inside the capsule, and `make clean GIT=git` inside the capsule (the X1 rule);
  - a single-quoted message or comment with a continuation next to a capsule path (this rule).

### Independent review of the fix, round 4 (2026-10-16): X2 fixed; X3 found, then commit E

The reviewer re-ran everything on `c261755`: 27/27 suites, 0 bypasses on every earlier probe set, worst 125 ms at 1 MB. **X2: fixed.**

| ID | Sev | Finding | Author check | Commit E |
|---|---|---|---|---|
| X3 | blocking for W3 (old: `d799f4f` allows all forms too) | The outright denial tested for the capsule on text that still held the kept pair, so a pair that splits the capsule name (`rm -rf .project-\⏎brain` after a heredoc with `it's`, or after `$'\' #'`; also `cd .project-\⏎brain && rm -rf f`) went unnoticed | 3 forms reproduced: real bash deletes, guard allows | the capsule is looked for in the fully joined text (the reviewer's one-line fix) |

**Evidence:**
- Tests first: the 3 forms were red.
- Every earlier case set holds; 27/27 suites.
- The kept-pair path stays linear: 88 ms at 1 MB.
- The base differential is unaffected, because its corpus has no kept pairs.

**Re-review of commit E (`5c91867`): approved.**
- The reviewer re-ran `bash -n`, the guard test and 27/27 suites.
- All 5 split-capsule forms are denied, and real bash deletes in each. Two more variants (a name split by two kept pairs, and `cd .project\⏎-brain`) are denied as well.
- Every earlier probe set gives 0 bypasses. Worst timing is 144 ms at 1 MB.
- **Final verdicts:** RR1–RR3, V1–V5, W1–W3, W5 and X1–X3 are fixed. W4 no longer applies (a documented conservative denial). The listed conservative false positives do not block. Merging is the owner's step.
