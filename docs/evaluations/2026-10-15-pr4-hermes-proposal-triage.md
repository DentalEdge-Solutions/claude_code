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
| P2 | No test for `harvest-evidence.js` | Open | `git ls-files \| grep harvest-evidence.*test` → 0 |
| P3 | No test for `static-scan.js` | **Done 2026-10-15** (see "P3 repair") | `scripts/static-scan.test.js`; the tests found 9 scanner gaps, S1–S9, still open |
| P4 | No test for `run-manifest.js` | Done | test added in Phase 3 (PR #131) |
| P5 | No CI | Done | `.github/workflows/ci.yml` and the `main-protection` ruleset (4 required checks) |
| P6 | BSD-only `sed -i ''` | Open | `uninstall.sh:108` |
| P7 | Hand-rolled YAML parsing | Open | `infra/hermes-agent/bin/make-review-board.py:39` |
| P8 | Hermes skills have no evals | **Open, grown** | `infra/hermes-agent/skills/` now has 6 skills and 0 `SKILL-EVAL.md` or `evals.json` files |
| P9 | No guard before `rm -rf` in `uninstall.sh` | Open | `uninstall.sh:19-24`: TARGET is only resolved with `cd`, so `/` or `$HOME` passes. There are 7 `rm -rf` calls. |
| P10 | No architecture map | Open (low) | there is no `ARCHITECTURE.md`; `CLAUDE.md` and `README.md` partly cover it |
| P11 | The brain security guard fails open on a parser error | Open | `hooks/brain/brain-security-guard.sh:52` |
| P12 | Tests missing for 3 scripts | Partly done | `validate-skills` has a test; `score-candidates.js` and `extract-project-context.js` do not |
| P13 | `test-runners.js` writes to real `evals/` paths | **Open, worse than stated** | see below |
| P14 | The superseded architecture spec has no banner | Partly done | `docs/superpowers/specs/archive/2026-07-20-hermes-master-architecture.md` now has a "REVISED" banner, but it points to `~/.claude/plans/…`, a machine-local file and not a repo document |

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

## Open work carried forward, ranked

1. ~~**P13:** isolate the test fixtures and repair the Codex baselines.~~ Done on 2026-10-15 (see "P13 repair").
2. ~~**P1:** one shared secret-pattern module (the superset), with a test per token format.~~ Done on 2026-10-15 (see "P1 repair"). HR1 from `2026-10-14-gsd-global-install-audit.md` §7 (a secret-read guard covering `settings.json`-style key files) is separate and still open.
3. ~~**P3:** tests for the security scanner.~~ Done on 2026-10-15 (see "P3 repair"). Its gaps S1–S3 were fixed the same day (see "S1–S3 repair"); S4–S9 are open.
   **P2:** tests for the eval grader (`harvest-evidence.js`).
4. **P11:** make the brain security guard's fail-open visible (a log) or fail closed.
5. **P9, then P6:** an `rm -rf` target guard and portable `sed` in `uninstall.sh`. Keep `install.sh` in sync.
6. **P8:** an eval path for Hermes skills (a full skill-eval, or a structural check).
7. **P7:** replace the hand-rolled YAML parse with a real parser, with a test.
8. **P12:** tests for `score-candidates.js` and `extract-project-context.js`.
9. **P14:** point the archived spec's banner at a repo document.
10. **P10:** an architecture map (low).

## Method and limits

- Each claim was rechecked by file listing, grep or a probe on `main` @ `4db546d`. The proposal's text was treated as data, not instructions.
- **P1 limit:** the probe used synthetic tokens in the common public formats. A pattern written for a different shape could still match real tokens.

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
