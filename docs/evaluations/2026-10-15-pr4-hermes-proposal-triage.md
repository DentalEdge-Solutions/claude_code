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
| P2 | No test for `harvest-evidence.js` | **Done 2026-10-15** (see "P2 repair") | `scripts/harvest-evidence.test.js`. **Correction:** the first probe missed two end-to-end tests already in `scripts/codex/test-runners.js` (the file name search could not find them). The tests found 6 weaknesses, E1–E6: E1 fixed 2026-10-15, E2–E5 fixed and E6 disclosed 2026-10-19 (see "E2–E6 repair"); E7, found in that review, fixed the same day; E8–E16 are fixed and E6 is kept by owner decision |
| P3 | No test for `static-scan.js` | **Done 2026-10-15** (see "P3 repair") | `scripts/static-scan.test.js`; the tests found 9 scanner gaps, S1–S9, still open |
| P4 | No test for `run-manifest.js` | Done | test added in Phase 3 (PR #131) |
| P5 | No CI | Done | `.github/workflows/ci.yml` and the `main-protection` ruleset (4 required checks) |
| P6 | BSD-only `sed -i ''` | **Done 2026-10-16** (PR #144; see "P9 repair", P6 note) | `uninstall.sh:108` on `d799f4f` |
| P7 | Hand-rolled YAML parsing | **Done 2026-10-16** (PR #145; see "P7 repair") | `infra/hermes-agent/bin/make-review-board.py:39` |
| P8 | Hermes skills have no evals | **Open, grown** | `infra/hermes-agent/skills/` now has 6 skills and 0 `SKILL-EVAL.md` or `evals.json` files |
| P9 | No guard before `rm -rf` in `uninstall.sh` | **Done 2026-10-16** (PR #144; see "P9 repair") | `uninstall.sh:19-24`: TARGET is only resolved with `cd`, so `/` or `$HOME` passes. There are 7 `rm -rf` calls. |
| P10 | No architecture map | **Done 2026-10-16** (PR #147; see "P14 and P10") | no `ARCHITECTURE.md` by design; README's "Architecture at a glance" stands and its directory tree is now complete |
| P11 | The brain security guard fails open on a parser error | **Done** (PR #142; re-review fixes PR #143; see "P11 repair", "P11 re-review") | `hooks/brain/brain-security-guard.sh` |
| P12 | Tests missing for 3 scripts | **Done 2026-10-16** (PR #146; see "P12 repair") | all three have tests: `validate-skills.test.js`, and since 2026-10-16 `scripts/score-candidates.test.js` and `scripts/extract-project-context.test.js` |
| P13 | `test-runners.js` writes to real `evals/` paths | **Open, worse than stated** | see below |
| P14 | The superseded architecture spec has no banner | **Done 2026-10-16** (PR #147; see "P14 and P10") | all 13 archived Hermes custom-kernel docs now carry a RETIRED (canon D-3) headline and point at repo documents only; no machine-local or dead pointer remains under `docs/superpowers/` |

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
3. ~~**P3:** tests for the security scanner.~~ Done on 2026-10-15 (see "P3 repair"). Its gaps S1–S3 were fixed the same day (see "S1–S3 repair"), and S4–S9 on 2026-10-16 (see "S4–S9 repair"); S10, S12 and S13 were fixed on 2026-10-20 (S13's Q5 behavior kept by owner decision); S11 is open.
   ~~**P2:** tests for the eval grader (`harvest-evidence.js`).~~ Done on 2026-10-15 (see "P2 repair"); its findings E1–E5 are fixed (see "E1 repair" and "E2–E6 repair"), and E6, a method question, is disclosed in the eval report instructions and kept by owner decision (2026-10-20). E7 (the eval agents' inline report templates lacked Evidence and Limits) is fixed, as are E8–E16.
4. ~~**P11:** make the brain security guard's fail-open visible (a log) or fail closed.~~ Done on 2026-10-15 (see "P11 repair"); its gaps G1–G3 are open.
5. ~~**P9, then P6:** an `rm -rf` target guard and portable `sed` in `uninstall.sh`.~~ Done on 2026-10-16 (PR #144; see "P9 repair").
6. **P8:** an eval path for Hermes skills (a full skill-eval, or a structural check).
7. ~~**P7:** replace the hand-rolled YAML parse with a real parser, with a test.~~ Done on 2026-10-16 (PR #145; see "P7 repair"): the stdlib-only tier uses the shared registry walker.
8. ~~**P12:** tests for `score-candidates.js` and `extract-project-context.js`.~~ Done on 2026-10-16 (PR #146; see "P12 repair").
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

### Scanner gaps found (S1–S13; S1–S3 fixed, see "S1–S3 repair"; S4–S9 fixed, see "S4–S9 repair"; S10, S12 and S13 fixed 2026-10-20; S11 open)

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
| S12 | Script files are not read for the secrets table (found during the S4–S9 repair, 2026-10-16) | a `ghp_…` token in `install.sh` or `tool.js` | BLOCK → PASS. Python has only its own `hardcoded-secret` FLAG. Turning the table on for scripts adds 12 findings in this repo, all fake tokens in test fixtures outside `skills/` (4 BLOCK, 8 FLAG), and none in `skills/`, so CI's gate would not change. Needs an owner call on fixtures. **Fixed 2026-10-20** (owner decision: turn it on, mark the fixture tokens as known fakes): script files, shebang files included, are read for secrets in their raw text; a check the script table already reported is not repeated. By 2026-10-20 the repo had 14 such findings (4 BLOCK, 10 FLAG), none in `skills/` or `.claude/`, the only trees CI scans. The 4 BLOCK fakes (`brain-lib.test.js`, `test-telemetry.js`, `open-proposal-pr.test.py`, `summarize-review-bundle.test.py`) are now assembled at runtime, the repo's convention, so no token-shaped literal is left in `scripts/` or `infra/`. The generic FLAG fixtures are known fakes, listed below the table |
| S13 | Generic secret forms in data files (independent review T6, 2026-10-16) | `{"password": "hunter2hunter2"}` in a `.json`; `PASSWORD=…` or `API_KEY=…` in `.env`; `_authToken=npm_…` in `.npmrc` | PASS. The generic FLAG patterns need the name right before `:`/`=` and a quoted value; npm tokens have no pattern. **Fixed 2026-10-20:** the name may be quoted (a JSON key); data and config files also match unquoted values (new `DATA_SECRETS` table: only spaces or tabs around the separator, placeholders such as `${VAR}`, `<…>`, `{{ … }}` excluded); markdown keeps the quoted forms. New BLOCK `npm-token`: `npm_` + 36 base62 characters (github.blog, "Announcing npm's new access token format", read 2026-10-20: `npm` prefix, `_` delimiter, GitHub's alphabet, 6-character CRC32 checksum, 178 bits; gitleaks' npm rule, `npm_[a-z0-9]{36}` case-insensitive, corroborates 36). Differential (decision 2026-10-15): 3,000 random samples across 11 file types, 0 main findings missing (the reviewer's 18,000 across 24 file kinds, 0); 48 adversarial 1 MB scans, worst 55 ms; the new regexes on 4 MB inputs, worst 22 ms; on the repo, no new finding in `skills/` or `.claude/`. Review round 1 (P1–P8): every file is read for secrets, files of no known type included (P1: `id_rsa`, `.pem`, `Dockerfile`, `.go`, `.jsx` passed a `ghp_` token and a private key); code uses a stricter quoted form (P3: prompts and format strings were FLAGged); suffixed names, `.netrc`/`.properties` space separators and `_auth=` (P4); `${VAR:-default}` (P5); the per-file check lookup no longer rescans all findings (P2: 40,000 files took 8.6 s, now 1.2 s; main 1.0 s); the report is no longer cut at 64 KiB through a pipe on macOS (P8, also on main). A private-key header inside code stays a BLOCK (P3, the gate errs toward clearance). Review round 2 approved da6ab71 (P1–P8 closed) with follow-ups, done: suffixed names in quoted values too (Q1: `SECRET_KEY = "…"`, `{"secretKey": …}`, `private_key: "…"`); `_auth` only at the start of a name (Q2: `enable_auth` was FLAGged); `.properties` keys anchored at the line start, dotted keys included, comments skipped (Q3); REFERENCE lists the remaining gaps (Q4); tests for four surviving mutants (Q6). **Kept by owner decision (Q5, 2026-10-20):** now that every file is read, a bundled native binary can BLOCK on packed strings (the 200 MB codex binary on a Bearer-like string) and docs that quote a PEM header BLOCK. The owner keeps this: the gate errs toward clearance, and a BLOCK is reviewed by a person. The option not taken was to run only the high-precision token patterns on files containing NUL bytes |
| S10 | No resource caps (final review F9, 2026-10-15) | a file over 536 MB holding an injection; a FIFO named `SKILL.md`; a symlinked file outside the tree | Over 536 MB → silently skipped, so PASS. A FIFO hangs the scan. Unreadable files are skipped without a finding; a single file that can't be read is scanned as empty, so PASS (U7 review Y5, 2026-10-19). **Fixed 2026-10-20:** each is now a finding that only adds to main's. BLOCK where nothing could be read: `unreadable` (file or directory), `special-file` (never opened). Also BLOCK: `symlink-outside-tree` (absolute, or resolving above the tree's top, or dangling or looping; a file target is still scanned under the link's name, unquoted; a directory is not walked), by owner decision 2026-10-20 after review round 2 (K10, K11): install copies the link as is, so what Claude Code loads after install is not what was audited. A third security review (cc700f8) found two parser differentials in that check: it split link targets on `\` too (on POSIX a backslash is part of a name, so `a\b/../../<tree>/x.md` passed), and it folded `..` as text, as node's `fs.realpathSync` also does, while the OS takes `..` after a directory link physically (`docs/l -> ..`, `docs/x.md -> l/../<name>` read a file above the tree). The check now resolves links as the OS does, component by component from the tree's top. A fuzz test of random trees of relative links (an install-like `cp -R` to a new name and depth) finds 0 unflagged links that resolve differently after the copy: 1,000 trees on e069a75, and 3,400 more in the reviewer's extended fuzz (case and NFC/NFD variants, link chains), which also found no flagged link that resolves the same (no false positive). On cc700f8, 400 trees gave 2 violations, both the K16 pattern. Review round 3 (K16, K17) found the same two independently; round 4 approved e069a75 (K21–K23 are notes: case- or normalization-folded names dangle on a case-sensitive copy, which loads nothing; a root given as `dir/link/..` is the operator's input); K18 (a `.` part) and a decoy folder named like the tree are tested, and each test checks the reason, so a check that is switched off cannot hide behind another one. FLAG: `file-too-large` (too large to read whole; scanned in overlapping 64 MB chunks). A first version (3fb556b) skipped in-tree symlinks, capped files at 10 MB and stopped following outside links; the background security review showed it lowered verdicts (`SKILL.md` → `payload.png` with an injection went BLOCK → PASS; an 11 MB file and an outside link went BLOCK → FLAG), and the fix reads every file main read, the same way. A second security review (58a22a7) found that the unreadable and special-file FLAGs failed open: main crashed or hung on an unreadable directory, a FIFO in the tree, a single-file FIFO and an unreadable root (CI's fallback fails on that), so a FLAG let them through; they are BLOCK now. The independent review of 58a22a7 and 1dc3557 (K1–K15) led to: the chunked scan keeps the most severe finding per check (K4: a code-block FLAG had hidden a prose BLOCK); a file over 2 GiB is a `file-over-scan-limit` BLOCK, not read (K7: 2.5 GB took 45 s); an outside link keeps its size or error detail (K6); an unreadable root is reported as `"."` (K8); `--help` and the header list the new checks (K14). CI's `ci-scan-skills.js` reads only BLOCK findings, so `file-too-large` does not show in CI. The stat-then-read race (a file swapped for a FIFO mid-scan) is accepted: it needs local write access during the scan (K13). A differential over 54 trees (symlink names and targets in and outside the tree, loops, `..`, sizes, binary, FIFO, unreadable) found no case where the branch is below main or errors. Tests in `scripts/static-scan.test.js` (S10); the old and new scanner agree on all 57 repo targets |
| S11 | Only the first `rm` target is checked, as on main (re-check G6, 2026-10-15) | `rm -rf ./build ~/`, `rm -rf x /`, `rm --interactive=never -rf /`, `rm / -rf`; after `--`, a first target that starts with `-` or a quote: `rm -rf -- --foo-rm ~`, `rm -rf -- "--cached" ~` (verification V2) | BLOCK → PASS. An every-target scan was tried and dropped: it froze the scanner and could be escaped (final review F1–F4). A safe version needs a shell-aware tokenizer, not a regex |

- **Doc drift:** `CLAUDE.md`, `README.md`, `docs/USER-GUIDE.md` and `skills/skill-audit/SKILL.md` call it a "47-pattern" scanner across 5 categories. The tables hold 70 patterns in 7 tables. **Fixed 2026-10-20 (with S12/S13):** the four docs no longer give a count, since it changes with every pattern (74 in 8 tables after S13); `REFERENCE.md` holds the tables.
- **Known fake secrets in test fixtures (S12, 2026-10-20):** generic FLAG `hardcoded-secret` matches, all fake values in tests outside `skills/`, in `infra/hermes-agent/bin/`: `apply-changeset.test.py`, `review_lib.test.py`, `run-ads-report.test.py`, `run-client-audit.test.py`, `summarize-review-bundle.test.py`, `syscall-e2e.test.py`. Two docs quote a JSON key (`"password": …` in this record, `"token": …` in `docs/security-reviews/2026-09-29-review-3.md`). No CI job scans these trees.

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
| F9 | No resource caps: files over 536 MB are silently skipped (PASS); a FIFO named `SKILL.md` hangs the scan; symlinked files outside the tree are read; unreadable files are skipped silently | main | Recorded as S10; fixed 2026-10-20 |

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

## S4–S9 repair (2026-10-16)

All in `skills/skill-audit/scripts/static-scan.js`; tests in `scripts/static-scan.test.js`; `skills/skill-audit/REFERENCE.md` describes the new rules (which files are read, settings permissions, secrets).

- **S4:** a settings file that parses as JSON is read by a small reader that keeps duplicate keys and positions; it builds only `permissions` and its `allow`, `deny` and `ask` arrays and skips every other value with a loop, so nesting depth does not matter (review round 3, W1). A bare `Bash`, `Write`, `Edit` or `Read`, or a specifier of only `*`, `:` and spaces (`Bash(*)`, `Bash(:*)`), in any `permissions.allow` (every copy of a repeated key, compared decoded) is the wildcard rule. main's text checks still run on the raw text, with only the `permissions.deny` and `permissions.ask` arrays emptied, so deny and ask rules are no longer reported and nothing else is lost. `Edit(//…)` (any absolute path) joins `perm-broad-path`. A file that does not parse keeps main's text checks unchanged. Source: code.claude.com/docs/en/permissions, read 2026-10-16 ("`Bash(*)` is equivalent to `Bash` and matches all Bash commands"; the `:*` suffix "is an equivalent way to write a trailing wildcard"; `//path` is absolute, `/path` is relative to the settings source). The same page says current Claude Code skips an unanchored allow glob such as `"*"` with a warning; it stays a BLOCK for older versions.
- **S5:** a file with no known script extension is read by its shebang: node, deno and bun use the JS table; python and pypy (with any version suffix) the Python table; sh, bash, zsh, dash, ksh and ash the shell table. `env`, its options (`-S`) and `VAR=x` words are skipped. An option that takes an argument (`env -u FOO python3`), `-Spython3`, and other interpreters (`tsx`, `pythonw`, `uv run --script`) are not recognised (review T8, open as on main).
- **S6:** JSON, JSONC, JSON5, YAML, TOML, INI, `.cfg`, `.conf`, `.env`, `.properties`, and the files `.env`, `.env.*`, `.npmrc`, `.pypirc` and `.netrc` are read for secrets. A script extension wins over these names, so `.env.sh` is still a shell script (review T3). The settings permission checks still run on `settings*.json` only. Only the token formats are matched in these files: a JSON `"password": "…"`, an unquoted `.env` value and an npm `_authToken` are not (review T6; recorded as S13).
- **S7:** `anthropic-api-key` and `anthropic-key-in-config` match any `sk-ant-<kind><digits>-` key (api03, admin01, oat01; main's `admin-` matched no real admin key) with no letter or digit before `sk-`, plus main's form anywhere (review T5). `hardcoded-llm-key` adds `sk-proj-`, `sk-svcacct-` and `sk-admin-`, with no letter or digit before `sk-`, so kebab-case prose stays quiet. A new `github-app-token` check (BLOCK) matches `ghs_`, `ghu_` and `ghr_`.
- **S8:** `subprocess-shell-true` adds a reader to main's regex. One linear pass over the file keeps a stack of open brackets and skips strings (single, double and triple quoted, with escapes; a one-line string ends at `\n` or `\r`) and `#` comments (to `\n` or `\r`). `shell=True` counts anywhere inside a `subprocess.run/call/Popen/check_output/check_call(` call, nested calls included. main's regex still runs, so a misread string can only add findings (background review B8-2, review T1/T2). Known limits, as on main: `import subprocess as sp`, `from subprocess import run`, `**{"shell": True}`, `os.popen`, `asyncio.create_subprocess_shell`, `shell=1` and other truthy values, a backslash line break after `shell=`, more than 64 spaces before `(`, and a reader confused by a PEP 701 f-string still misses the S8 forms main's regex cannot see.
- **S9:** a single-file scan names the file (`file: "settings.json"`), relative to its folder.
- **Not done:** S10 (resource caps) and S11 (every `rm` target). New and open: S12 (secrets in scripts) and S13 (generic secret forms in data files). Outside S4's scope and open as on main (review T10): `defaultMode: acceptEdits`, `additionalDirectories: ["/"]`, `Bash(sh *)`, bare `PowerShell`, `Read(//**)`, `Edit(/**)`, `Edit(~)`, and `managed-settings.json` (secrets only). The "47-pattern" doc drift is still open.
- **Evidence (final, after two background reviews and four independent review rounds):**
  - Tests first: run against main's scanner, 52 tests failed for the expected reasons; each review fix also had its test fail first (the B9/U tests fail on c136334, the W1 tests on d2a82b2, the X1 test on 93394ed). After: `scripts/static-scan.test.js` 345/345, `node scripts/run-all-tests.js` → 30/30, `node scripts/ci-scan-skills.js` passes with no new or stale entries.
  - **Differential, repo:** main vs branch over every top-level folder and `.claude/settings*.json`: 0 findings added, 0 removed (195 on the whole repo either way).
  - **Differential, synthetic (924 samples):** Python calls (7 call forms × 11 argument forms × 10 `shell` forms) and settings rules (22 rules × allow/deny/ask × 2 layouts, plus invalid JSON). Added: 100 `subprocess-shell-true` (parentheses or `)` in strings or comments before `shell=True`, `shell = True`, `shell=\nTrue`, nested `wrap(shell=True)`, `subprocess . call`) and 16 permission findings (bare names, `Bash(:*)`, `Bash( * )`, `bash`, `Edit(//etc/**)`). Removed: 15 `subprocess-shell-true` on `shell=True_x` (not `shell=True`) and 28 permission findings on deny and ask rules. Nothing else.
  - **The reviewer's 178 probe samples** (all four rounds), replayed on the final code: 58 are above main, and 8 are below. All 8 are intended: `shell=True_flag`, and 7 settings files whose only matching rule sits in `permissions.deny` or `permissions.ask` (escaped and duplicate `deny` keys, a deny string holding `"],"allow":[…`, `ask` holding `Bash(*)` or `Edit(~/…)`, and deep nesting beside a deny-only rule).
  - **Timing:** 65 hostile inputs of about 1 MB or more (a 10 MB string beside the permissions: 62 ms; 1 MB backslash runs; 150,000 escaped-quote strings; unclosed calls, strings and brackets, CR-only comments, `shell` runs, repeated key prefixes, a 250,000-rule allow list, 100,000 deny rules, 60,000 duplicate `deny` keys, 500,000-deep arrays, 1 MB-deep arrays beside the permissions, 150,000-deep objects inside `allow`, 200,000 bracket-and-quote strings in a skipped value, 80,000 duplicate `permissions` keys at 2.75 MB, 1 MB keys, rules and shebang lines): worst 111 ms end to end, node startup included. The reviewer's sets: worst 66 ms (round 1), 103 ms (round 2, up to 10 MB), 441 ms (round 3, 10.3 MB) and 399 ms (round 4, 10.5 MB), all linear. Four timing tests pin the S8 inputs.
  - **Mutation testing:** 53 mutants of the final code (the author's set), run on a copy, all caught.
  - **Fuzzing:** the reviewer's fuzzer (its own position-keeping reader as the reference) on the final reader: 91,448 valid generated files over three seeds, 0 differences; on a flipped-parity mutant it fails every valid file. On the way, two `sk-` guards, three duplicate-key paths and one shape test were not reached at first, and two shape checks proved equivalent and were removed; each gap was closed with a test.
  - **Hygiene:** two literal U+FEFF characters, which the authoring tool had decoded from `\uFEFF` escapes, were found by a scan for invisible characters and replaced with escapes. The changed files hold no other control or format characters beyond main's own hidden-Unicode pattern.

### Background security review of dc61b2c (2026-10-16)

The review named two issues without details; both were found and reproduced.

| # | Finding | Introduced by | Outcome |
|---|---|---|---|
| B8-1 | Duplicate keys: `JSON.parse` keeps the last copy, so `{"permissions":{"allow":["Bash(*)"]},"permissions":{…}}` and `{"permissions":{"allow":["Bash(*)"],"allow":[]}}` passed (main: BLOCK). Claude Code's choice of copy is not documented | dc61b2c | First fixed in c136334 by renaming later copies with an in-band marker; that fix was itself broken (B9-2, U1). Final fix: the duplicate-keeping reader (see S4). Five tests, including a bare `Bash` hidden in either copy |
| B8-2 | The `shell=True` reader read `'''` inside a PEP 701 f-string (`x = f"{"'''"}"`, valid Python 3.12+, checked on 3.14.6) or an unclosed `"""` as an open string, and skipped the rest of the file (main: BLOCK) | dc61b2c | Fixed: main's regex runs as well, so the reader can only add findings. A quoted `"shell=True"` and `myshell=True` are BLOCKs again, as on main. Three tests |

### Independent review of dc61b2c (2026-10-16)

The reviewer worked from a pinned `git archive` snapshot because the author's mutation runs were editing the shared worktree in place (process fix: mutants now run on a copy). Verdict: **changes needed** (T1–T3).

| # | Sev | Finding | Outcome |
|---|---|---|---|
| T1 | blocker | PEP 701 f-string desync (as B8-2), also on one line: `x = f"{"'"}"; subprocess.run(cmd, shell=True)` | Fixed with B8-2 |
| T2 | blocker | CR-only line ends: a `#` comment with no `\n` after it ended the whole scan | Fixed: comments and one-line strings end at `\n` or `\r` (linear sticky match). Two tests |
| T3 | blocker | `.env.*` was checked before script extensions, so `.env.sh`, `.env.py`, `.env.local.js` got the secrets table only (main: BLOCK) | Fixed: script extensions first. Three tests |
| T4 | minor | Duplicate keys (as B8-1) | Fixed with B8-1 |
| T5 | minor | `sk-ant-[a-z]+…` without a lookbehind matched prose (`task-ant-colony-simulation-…`) | Fixed: the wider form needs no letter or digit before `sk-`; main's api03/admin form still matches anywhere. Three tests |
| T6 | minor | REFERENCE.md overstated S6: JSON keys, unquoted `.env` values and npm tokens are not matched | Docs corrected; recorded as S13 |
| T7 | minor | 7 of the reviewer's 32 mutants survived (BOM strip, newline end of strings, the `myshell` guard, deno, case-insensitive `bash`, `**`, data-before-script order) | Tests added; all 7 now caught |
| T8 | minor | Shebang gaps (`env -u FOO python3`, `-Spython3`, `tsx`, `pythonw`, `uv run`, `busybox sh`; shebang files with data extensions) | Open as on main; documented |
| T9 | minor | S8 known-limits list incomplete | Completed above and in REFERENCE.md |
| T10 | note | Settings gaps outside S4 (see "Not done"); `allow` as a string or a top-level array went BLOCK → PASS | The two shapes now fall back to the text checks (three tests); the rest is open as on main |
| T11 | note | Uncommitted edits in the worktree during review | Process: mutants now run on a copy. These fixes need a re-review |

### Background security review of c136334 (2026-10-16)

Two issues named without details; both found and reproduced.

| # | Finding | Introduced by | Outcome |
|---|---|---|---|
| B9-1 | Detection regression: with a parsable file, the permission checks read `permissions.allow` only, so main's text matches elsewhere were lost: `{"allowedTools":["Bash(*)"]}`, `{"env":{"permissions":{"allow":["Bash(*)"]}}}`, `{"sandbox":{"network":{"allow":["*"]}}}` (main: BLOCK) | dc61b2c | Fixed: main's text checks run on the raw text with only `permissions.deny`/`permissions.ask` emptied. Five tests |
| B9-2 | Parser differential: a key that literally holds the rename marker (`"permissions\u0000dup1"`) was read as a `permissions` copy | c136334 | Fixed: no renaming; the reader keeps duplicate keys as entries. Test added |

### Independent review round 2, of c136334 (2026-10-16)

The reviewer confirmed T1–T3, T5–T10 fixed (its 26 applicable round-1 mutants all killed; the 98 round-1 probes show only the intended deny-only case below main). Verdict: **changes needed** (U1, U2).

| # | Sev | Finding | Outcome |
|---|---|---|---|
| U1 | blocker | The rename marker collided with a key in the file and hid a real copy: `{"permissions":{"allow":[]},"permissions":{"allow":["Bash(*)"]},"permissions\u0000dup1":{"allow":[]}}` (main: BLOCK) | Fixed by the redesign (no marker). Tests for both levels |
| U2 | major | `rules.push(...allow)` threw `RangeError` on an allow list of 150,000+ entries; the scanner exited with no JSON, and CI's fallback prints that as a pass (U7) | Fixed: items are pushed one at a time. Test with 250,000 entries |
| U3 | note | A marker-like key with a non-object value forced the text fallback, which misses a bare `Bash` | Fixed by the redesign. Test added |
| U4 | note | Rules outside `permissions.allow` (as B9-1) | Fixed with B9-1. Test added |
| U5 | minor | 4 of the reviewer's 19 new mutants survived: (a) `COMMENT_REST.lastIndex` without `- 1`; (b) the key check's `\s*:` removed; (c) the T5 lookbehind narrowed to letters; (d) main's form dropped from `anthropic-key-in-config` | (a) equivalent: the skipped character is the line end itself, which the reader ignores outside strings. (b) moot (code removed). (c) test added (a digit before `sk-ant-`). (d) equivalent: `anthropic-api-key` also runs on settings files |
| U6 | note | `shell=True_flag` is below main | Declared exception (`True_flag` is not `True`) |
| U7 | note | CI's static fallback (`.github/workflows/ci.yml`) prints a scanner crash (`ERROR`) as `PASS` | Fixed 2026-10-19: the fallback loop moved to `scripts/ci-static-fallback.js`, which fails on BLOCK and on any scanner error (crash, no or non-JSON output, unknown verdict, exit code that disagrees with the verdict). The same `&&`/`||` chain also printed a BLOCK file as both `BLOCK:` and `FLAG:`; now one line. Evidence: the old loop with a crashing stand-in scanner printed 18 × `PASS` and `Static fallback: PASSED`; the new script gives the same verdicts as the old loop on this repo's 18 targets; 18 tests in `scripts/ci-static-fallback.test.js`. The new script also scans dot-files (`.x.md`) that the old glob skipped. Independent review (2026-10-19) approved with changes; Y1 (a non-string verdict such as `["BLOCK"]` passed), Y2 (no test of the exit code CI reads, or of the FAILED line) and Y3 (the crash reason showed the `Node.js vN` line) were fixed with tests; Y5 was added to S10. Not covered by a test: the one-line CLI call `process.exit(main())`. CI reaches this step only when AgentShield is unavailable (on main it ran, grade B), so CI does not exercise it |

### Independent review round 3, of d2a82b2 (2026-10-16)

Verdict: **approve**. U1–U4 closed; the deny/ask blanking removes only arrays Claude Code reads as deny or ask (34 new settings probes, BOM offsets checked); no disagreement between the reader and `JSON.parse` on valid JSON; timing linear to 10.3 MB (worst 441 ms). Follow-ups, all done in the next commit:

| # | Sev | Finding | Outcome |
|---|---|---|---|
| W1 | minor | The recursive reader gave up at a depth between 3,000 and 8,000, so 16 KB of nesting beside the permissions turned the bare-name check off (PASS; main also PASS) | Fixed: the reader builds only `permissions` and its `allow`/`deny`/`ask` arrays and skips every other value with a bracket-counting loop that steps over strings. Five tests (8,000- and 500,000-deep arrays, 200,000-deep objects, deep items inside `allow`, brackets and escaped quotes in skipped strings) |
| W2 | minor | CRLF and tab whitespace in the reader were untested (mutants survived) | Two tests; both mutants now caught |
| W3 | note | One finding per hit was untested | Test added; mutant caught |
| W4 | note | The record's mutant count is the author's set; 11 of the reviewer's 20 survived (7 equivalent, 1 near-equivalent, W2, W3) | Noted; the W2/W3 survivors are now caught |

### Independent review round 4, of 93394ed (2026-10-16)

Verdict: **approve**. W1–W3 closed. A fuzz run of the settings reader against the reviewer's own position-keeping reader, on 152,391 valid generated files (whitespace, escaped and duplicate keys, strings with brackets, quotes, backslashes, U+2028, lone surrogates), found 0 differences; the fuzzer catches string-jump mutants. Timing linear to 10.5 MB (worst 399 ms). 11 of the reviewer's 12 mutants killed. Follow-ups, done in the next commit:

| # | Sev | Finding | Outcome |
|---|---|---|---|
| X1 | minor | The string regex `/"(?:[^"\\]\|\\.)*"/y` overflowed the stack on a string of about 8 MB, so the reader gave up and a bare `Bash` passed (main also PASS) | Fixed: the string end is found by a loop over `"` positions that counts the backslashes before each, with no regex. Tests: a 9 MB string, and escaped quotes with backslash runs. The reviewer's fuzzer, rerun on the fix over 91,448 valid files, finds 0 differences, and finds the flipped-parity mutant on every file |
| X2 | minor | No test pinned the `JSON.parse` precheck, which keeps a truncated file from aborting the scan (exit 134) | Three truncated-file tests; the mutant is caught |
| X3 | note | The docs left out X1's case | Moot after X1 |

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

### Harvester weaknesses found (E1–E6; E1–E5 fixed, E6 kept as disclosed by owner decision — see "E1 repair" and "E2–E6 repair"; E7 is recorded and fixed there, E8–E16 fixed there)

Probed on 2026-10-15 in a scratch folder. None is pinned by a test.

| # | Weakness | Reproduction | Impact |
|---|---|---|---|
| E1 | A symlink in the workspace satisfies an artifact check | `workspace/report.md` → symlink to any existing file outside the workspace: `exists: true`, the step is satisfied, `workflow_executed: true` | **Fixed 2026-10-15** (see "E1 repair"). Before the fix, a run could satisfy artifact workflow steps without writing the file (a junk file still satisfies `exists`; content is left to the LLM judge) |
| E2 | A claim path can leave the workspace | ``I wrote `../../…/etc/hosts` `` → `claim_verified: true` | **Fixed 2026-10-19** (see "E2–E6 repair"). Informational field only; misleading if a reader trusts it |
| E3 | An invalid `started_at` in `run-manifest.json` makes every artifact `mtime_in_window: false` (not null) | `{"started_at": "not-a-date"}` | **Fixed 2026-10-19.** Informational field only |
| E4 | `claim_verified` means "exists", not "written by this run": any existing repo file verifies (repo-root fallback, no time window) | ``I wrote `README.md` `` run from the repo root → `true` | **Fixed 2026-10-19**: only files in the side's own folder verify, and, when `run-manifest.json` gives `started_at`, only files changed since then. Informational field only |
| E5 | The 80-character claim window crosses lines and sentences, so a mention near another sentence's verb becomes a claim | `produced `a.md`.` then `See `b.md`.` → both claims | **Fixed 2026-10-19.** Noise in an informational field |
| E6 | Design note: `skill_loaded` comes from the literal token `Skill(<name>)`, which the eval subagent is instructed to write when it applies the skill. It is an instructed marker in the subagent's own output, not an independent tool-call log | `.claude/agents/skill-eval-agent.md` (the "Trigger token" rule) | Trigger accuracy depends on the subagent following that instruction honestly. A method question, not a harvester bug. **Disclosed 2026-10-19** in the skill-eval, agent-eval and team-eval report instructions and, since the E7 fix, in the eval agents' inline templates; replacing the marker is an owner decision (see "E2–E6 repair"). **Owner decision 2026-10-20: kept as disclosed**; a stronger signal would need hook-level tool-call logging, a larger project |

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

## E2–E6 repair (2026-10-19)

`skills/skill-eval/scripts/harvest-evidence.js` (shared by skill-eval and agent-eval). The `evidence.json` shape is unchanged.

- **E2:** a claim is verified only when its path resolves, links followed, inside the side's own folder: its workspace, `output.md` and `timing.json`. The path is read against the workspace first, then the repo root (cwd); the usual form is a repo-relative path into the workspace. Rejected cases:
  - `../` paths and absolute paths outside the side's folder;
  - a workspace link to a file outside it;
  - `evals.json`, the other side's workspace, and any other repo file (independent review V3).

  An absolute path inside the workspace now verifies. Before, it was joined onto the workspace path and never matched.
- **E3:** an unparseable `started_at` gives a stderr warning and `mtime_in_window: null`, the same as an unreadable manifest. Before, it gave `false` for every artifact.
- **E4:** when `run-manifest.json` gives `started_at`, a claimed file must also have changed since then, judged by the file's own time (a new link to an old file does not count). An untouched `README.md` is then not "written". Without a start time, existence inside the side's folder is all that can be checked.
  - Artifacts and claims both allow 2 s before `started_at`, for filesystems that keep coarse file times (review V6).
  - `claim_verified: false` therefore means "not found as written in this side's folder", not "fabricated": a file the run really wrote elsewhere, against its instructions (for example `skills/demo/SKILL.md`), is also `false` (review W4).
- **E5:** the 80-character claim window starts after the last `.`, `!` or `?` (plus any closing quote or bracket) that is followed by whitespace and a capital letter. A list number at the start of a line (`1. `, up to 3 digits) is not a sentence end. Formats that keep their claims (review V1, W1):
  - numbered and dashed lists, including items that start with a capital (`1. Main report …`) and lists after a blank line under `…created:`;
  - headings;
  - `e.g.`, `etc.`;
  - list items ending in `.`.

  Known misses (review W2):
  - a sentence is not split when it starts with lower case, a backticked path, a digit, `#`, `**` or a quote;
  - an abbreviation followed by a capitalised word (`e.g. See`) is split;
  - a `./` claim resolves to the workspace folder itself and verifies whenever the run wrote any file there. Folder claims (`out/`) verify from the folder's time; this was already so before.
- **E6:** the marker is still the instructed `Skill(<name>)` / `Agent(<name>)` token. The following now say so:
  - the "Evidence source" line in the skill-eval and agent-eval report templates (`REFERENCE.md` and `assets/*-EVAL.template.md`);
  - team-eval's report step (`skills/team-eval/SKILL.md` step 7), whose Dispatch-Chain Accuracy reads the same kind of `Agent(<member>)` marker.

  An independent signal would need a different method, for example real auto-invocation in a sandbox with the tool calls read from the session log. That is a methodology change, which is the owner's call.
- **E7 (fixed 2026-10-19):** the inline report templates in `.claude/agents/skill-eval-agent.md` and `agent-eval-agent.md` (step 12) have no Evidence and Limits section at all. Reports written through those agents therefore carry neither the E6 disclosure nor the other evidence fields (found by review V4). **Fix:** both step-12 templates now carry the Evidence and Limits section, its four bullets identical to the skill templates (`skills/*-eval/assets/*-EVAL.template.md`), including the E6 marker disclosure. Both agents' `run-manifest.js init` now pass `--subject <definition> --commit <sha>`, as the skills do, so the "Subject revision" line has a pinned value to cite. `scripts/eval-report-sections.test.js` now checks that the section's bullets are identical in the template, the `REFERENCE.md` copy and the agent, for both tracks. Against the pre-fix agents it fails, as it does on a one-word drift or a dropped marker.
  - Independent review: approve with changes (K1–K4).
    - **K1:** a stale "E7" phrase in the E6 row; fixed.
    - **K4:** the sync test above.
    - **Round 2:**
      - **K5:** the same test now requires every `run-manifest.js init` line, in both skills and both agents, to pass `--subject <definition>` and `--commit`; removing either is caught.
      - **K6:** E8 and E9 are listed as open in the status lines.
    - **Round 3:** approve.
      - **K7:** the `--subject` check is anchored at the path's end, so pointing `--subject` at the snapshot file fails the test.
    - **K2:** recorded as E8.
    - **K3:** recorded as E9.
- **E8 (fixed 2026-10-19, from review K2):** `skill-eval-agent` snapshots the baseline to `skills/<name>/SKILL.md.eval-snapshot`, inside the skill folder. The skill-eval skill uses `skills/<name>-eval-snapshot/` instead.
  - `install.sh` gitignores only `skills/*-eval-snapshot/` in target projects, and this repo's own `.gitignore` doesn't cover `skills/*/SKILL.md.eval-snapshot` either. So the agent's snapshot is ignored neither here nor in target projects, and isn't kept out of a skill deploy.
  - agent-eval and its agent agree with each other.
  - **Wider than first recorded:**
    - The skill's own form, `skills/<name>-eval-snapshot/`, was not ignored in this repo either.
    - `install.sh` step 2 copies every folder under `skills/` into `~/.claude/skills/`, so a leftover snapshot folder would have been installed as a second copy of the skill.
    - The agent-eval flows wrote `.claude/agents/<name>.md.eval-snapshot`, also not ignored.
  - **Fix (owner's choice):** all four documents (both eval skills and both eval agents) now take the snapshot in step 5, after the iteration folder exists, so N is not miscounted. The snapshot goes inside that folder:
    - skills: `evals/<skill-name>/iteration-<N>/eval-snapshot/`, the whole skill folder;
    - agents: `evals/agents/<agent-name>/iteration-<N>/eval-snapshot/<agent-name>.md`.

    `--snapshot-path` points there. Each iteration gets its own snapshot, with no cleanup command. The folder is already ignored here (`evals/.gitignore`: `*/iteration-*/`, `agents/*/iteration-*/`) and in target projects (`install.sh` ignores `evals/`).
  - **Checked:**
    - the harvester and `run-native-audit.js` skip the snapshot folder, because it has no `with_*` side;
    - `cp -R` creates the folder rather than nesting it;
    - `scripts/eval-snapshot-paths.test.js` pins the paths, the order (copy after the iteration folder exists) and the ignore rules. It failed before the change.
  - **Independent review:** approve with changes (M1–M5).
    - **M1:** the test now runs each document's step-5 `mkdir -p`/`cp` commands, without a shell, in a temp repo. It asserts that the recorded `--snapshot-path` exists and equals the subject. Three path bugs the first test missed now fail it, checked against a passing control: a wrong copy target, a copy to a file, and a dropped `mkdir`.
    - **M2:** both agents now say "On resume, skip the snapshot copy and this call", because re-running `cp -R` nests a second copy. The test pins it.
    - **M3:** corrects E12; see there.
    - **M4:** extends E13.
    - **M5:** `install.sh` keeps its `skills/*-eval-snapshot/` ignore rule on purpose, for snapshot folders left by earlier runs.
    - **Round 2 (M6–M8):**
      - **M6:** the test refuses absolute and `..` paths, and fails on any unexpected command in step 5 instead of skipping it.
      - **M7:** the test deletes its temp folders.
      - **M8:** E12's first sentence no longer says the baseline was the previous version.
    - **Rounds 3 and 4:** **approve**.
      - **M9:** the test also rejects option-like arguments, such as GNU `cp --target-directory=…`.
      - M1–M9 are closed. Of 19 mutants, 17 fail the test; the 2 survivors are harmless and accepted.
- **E12 (fixed 2026-10-20, owner decision, found while fixing E8):** both eval agents record `baseline_method = snapshot` for an existing skill or agent, but their step-6 baseline prompt always says "Do NOT load any skill" or "Do NOT dispatch the agent". So agent-run evals of an existing definition compare against no skill at all, while the manifest records a snapshot baseline.
  - The eval skills' own text says to use the snapshot as the baseline.
  - **Corrected by review M3:** the step-5 snapshot is taken at eval time, so it is byte-identical to `--subject` (same sha256 in simulation). This was already so before E8. So even a baseline that loaded it would compare the current version with itself, not with an earlier one, in all four flows. `skills/skill-eval/REFERENCE.md` and `skills/agent-eval/REFERENCE.md` call it a "snapshot of previous version", which is not what the steps produce.
  - A real fix needs the pre-change definition, for example refine's `SKILL.md.baseline`, a git ref, or a snapshot taken before an edit, and a rule for grading its trigger marker. That is a methodology decision for the owner.
- **E13 (fixed 2026-10-19, found while fixing E8):** refine copies sit in the definition's own folder and are not ignored. Same class as E8.
  - the refine agents' per-iteration safety copies, `skills/<name>/SKILL.md.pre-iter-N` and `.claude/agents/<name>.md.pre-iter-N`;
  - skill-refine's `skills/<name>/SKILL.md.baseline`. `install.sh`'s `skills/*.baseline` does not match that nested path, and `git check-ignore` misses it here and in a target project (review M4).
  - skill-refine-agent step 7d also runs `cp -r skills/<name> ~/.claude/skills/`, carrying the `pre-iter-N` files into the installed skill.
  - **Also found while fixing it:** `skill-adapt` step 4 backed up to `skills/<name>-backup-<date>/`. `install.sh` step 2 syncs every `skills/` folder into `~/.claude/skills/`, so that backup would become a second copy of the skill. A second backup the same day would also nest inside the first.
  - **Fix:** every refine and adapt copy now lives under the definition's `evals/` folder, next to its `refine-input.json`:
    - `evals/<skill>/refine/SKILL.md.baseline` and `…/SKILL.md.pre-iter-N`, restored from there;
    - `evals/agents/<agent>/refine/<agent>.md.baseline` and `….pre-iter-N`;
    - `evals/<skill>/adapt-backup-<YYYYmmdd-HHMMSS>/`.

    The change covers both refine skills, both refine agents and `skill-adapt`. Each copy is preceded by `mkdir -p`. `evals/.gitignore` gains `*/refine/`, `agents/*/refine/` and `*/adapt-backup-*/`; target projects ignore all of `evals/`. The keep step's sync of the skill folder no longer carries any copy.
  - **Checked:**
    - no leftover copies existed in this checkout, in `~/.claude/skills/` or in `~/.claude/agents/`;
    - `scripts/refine-copy-paths.test.js` pins the paths, the `mkdir` before each copy, the restore-reads-what-was-written link and the ignore rules. It failed before the change, and six mutants fail it against a passing control;
    - two adapt backups a second apart land in separate folders.
  - **Independent review:** approve with changes (N1–N6).
    - **N1:** the test read its ignore samples from a hard-coded list, so 7 of 11 mutants survived. It now reads everything from the documents:
      - every `evals/` copy target, placeholders filled in, must be ignored;
      - the `mkdir -p` must name exactly that folder;
      - both refine agents must restore the definition from its `pre-iter-N` copy;
      - the adapt time stamp is pinned to the second.
    - **N2:** the adapt backup creates its stamped folder and copies the skill's contents into it (`cp -R skills/<n>/. …/`), so it can't nest even within the same second.
    - **N3:** the `.baseline` copy is guarded (`[ -e … ] || cp …`), so it is never overwritten, and the test pins that.
    - **N4:** `install.sh` no longer adds `skills/*.baseline`, which never matched the nested file. It keeps `skills/*-backup-*/` and `skills/*-eval-snapshot/` for folders that earlier versions may have left in target projects.
    - **N5:** `uninstall.sh` says `evals/` also holds the refine and adapt safety copies.
    - **N6:** extends E14.
- **E14 (fixed 2026-10-20, found while fixing E13):** a neutral refine result is handled differently. `skill-refine`/`agent-refine` `SKILL.md` step 8 reverts a neutral result ("Regressed or neutral → REVERT"), while both refine agents' step 7d keep it ("NEUTRAL → KEEP (simpler is better)"). Each skill's own `REFERENCE.md` threshold table ("**NEUTRAL → KEEP** | Within ±2–5%") also contradicts its step 8, which points to that table (review N6).
- **E15 (fixed 2026-10-20, found while fixing E13):** `agent-refine` `SKILL.md` step 8's "Sync to runtime: `cp .claude/agents/<name>.md ~/.claude/ 2>/dev/null || true`" copies the agent into the root of `~/.claude/`, not `~/.claude/agents/`. CLAUDE.md says agents are project-scoped (installed to target projects only), so this leaves a stray file in `~/.claude/`.
- **E14 and E15 repair (2026-10-20):**
  - **Owner decision (E14, 2026-10-20):** a neutral result is reverted unless the edit made the definition shorter.
  - **Fix (E14):** seven documents now state the same three bands, one per line, in the same words. They are both refine `SKILL.md` step 8, both `REFERENCE.md` threshold tables, both refine agents' step 7d and `skill-guardian`'s refine loop (review R4: it kept any gain and reverted any neutral result). The bands:
    - `score > baseline + 2%` → KEEP;
    - `score < baseline − 5%` → REVERT;
    - `baseline − 5% ≤ score ≤ baseline + 2%` (neutral) → REVERT, unless the definition has fewer bytes (`wc -c`) than before the edit; then KEEP, and the baseline stays as it was.

    How the rule reads the decision:
    - **The definition:** for a skill, `SKILL.md`, the file loaded whenever the skill triggers. A neutral Lever D or E edit (`REFERENCE.md`, `scripts/`) is always reverted, since a shorter script can mean a dropped check rather than a smaller footprint (review R2). For an agent, the agent file.
    - **The neutral band:** the old "within ±2–5%" left it undefined. It is now the gap between the two thresholds, which are percentage points of the training-set pass rate (review R6).
    - **The size:** counted in bytes, not lines, so rewrapping text never counts as shorter.
    - **The baseline after a neutral KEEP:** unchanged, so a run of shortening edits can't lower the score step by step (review R5). For lever exhaustion and convergence, a neutral KEEP is not an improvement and a neutral revert counts as a revert.
    - **The summaries and logs (review R7):** both loops' RULE summary states the neutral band. Every log format records the size before and after, and offers KEPT, REVERTED, NEUTRAL-KEPT and NEUTRAL-REVERTED.
  - **Fix (E15):** `agent-refine` step 8 no longer copies the agent anywhere.
    - **Source:** the official sub-agents page (code.claude.com/docs/en/sub-agents, read 2026-10-20, installed Claude Code 2.1.302; the reviewer re-read it and confirmed). Claude Code watches `.claude/agents/` and `~/.claude/agents/`, and an edited file is used on the next delegation with no restart. A restart is needed only for an `agents` folder created after the session started, a folder added with `--add-dir`, or a session started with `--disable-slash-commands`.
    - **Why not `~/.claude/agents/`:** a copy there would make the agent user-scoped in every project, though the project copy wins on a name clash.
    - **Stray file:** none existed in `~/.claude/`.
  - **Checked:** `scripts/refine-keep-revert.test.js`, 52 checks. It reads each band's line in all seven documents: the definition named, the byte measure ending the condition, "if it did, KEEP", the baseline unchanged, Lever D/E reverted for skills, and the sync for the two that sync. It also reads the RULE summaries, the `REFERENCE.md` counting rules and every log format, and fails on any older form of the rule. For E15 it reads every `cp`, `rsync`, `install` or `ln` in every Markdown file under `skills/` and `.claude/agents/`, found at run time. Shell line continuations are joined, and redirections such as `2>/dev/null` dropped, before the destination is read (review R11). It fails when the destination is `~/.claude/agents`, or when a project agent (or an `$…AGENT…` variable) is copied anywhere under the home folder. A separate check fails on any mention of the user-level agents folder (`~/.claude/agents`, `$HOME/…`, `${CLAUDE_…}/agents` but not `$CLAUDE_PROJECT_DIR`), in prose too (review R9, R12). Both matchers are also run on fixed inputs, among them the literal cc5bf74 line, so a rewrite that stops catching the original bug fails (review R11). The percentage-point unit is pinned in all seven documents.
    - **Failures on earlier commits** (the 42 checks of the second commit): on main (cc5bf74), 37 fail. On the first fix (b993f12), 28 fail: every check added after round 1.
    - **On main, with the final test:** 45 of 52 fail, the E15 copy check among them.
    - **Correction (review R11):** the second and third commits (818d6e3, 97b6d33) said the copy check fails on a project agent copied under the home folder. It did not catch the original line, `cp .claude/agents/<name>.md ~/.claude/ 2>/dev/null || true`: the redirection was read as the destination. Only the wording check ("no copy") still failed on main. Fixed in the fourth commit.
    - **Correction (review R8):** this record first said the first test failed on main with "24 rule checks and both E15 checks". It was 20 of 24 rule checks: the two refine agents' keep and revert lines already used these thresholds.
    - **Mutants:** 26 fail it against a passing control. They are the reviewer's round-1 10 (all had survived the first test), 10 of the author's, and 6 of the reviewer's round-2 10. These include a copy split over lines, a prose "sync into ~/.claude/agents/", a `${CLAUDE_HOME:-…}` destination and the unit removed from the guardian or an agent.
  - **Limits:**
    - The test reads the documents, not a refine run.
    - A neutral line that adds an unconditional "KEEP" after the stated rule still passes, as does a contradicting sentence elsewhere in a document, such as "a neutral KEEP counts as an improvement" in a convergence line. These are the 4 surviving round-2 mutants; a text test can't catch every contradiction.
    - So does a copy made with a tool other than `cp`, `rsync`, `install` or `ln`.
    - So does GNU `cp -t DIR SRC`, which names the destination first (review R13; macOS `cp` has no `-t`).
    - Not addressed, and older than this change: whether the one regression rep on scenarios that already passed counts toward `score` (review R6).
  - **Independent review, round 1 (b993f12):** approve with changes, R1–R8, all minor.
  - **Round 2 (818d6e3):** approve; R1–R8 fixed (R3 as a record, the gap staying in E16). R9 (test gaps) and R10 (E16 omitted `skill-guardian`) are new and minor, and are answered in the next commit.
  - **Round 3 (97b6d33):** request changes. R9 and R10 fixed. R11 (blocking): the E15 copy check no longer caught the original line (above). R12 (minor): the user-level folder check matched `$CLAUDE_PROJECT_DIR/.claude/agents`. Both are answered in the fourth commit.
  - **Round 4 (9af4383):** approve; R1–R12 fixed. R13 (minor): `cp -t` isn't read, now listed under Limits as the reviewer accepted.
- **E16 (fixed 2026-10-21, found while fixing E14; widened by review R3):** a refine can't always restore "prior content exactly", or measure the size "before the edit".
  - **`skill-refine-agent`:** step 7b snapshots only `SKILL.md` (`…/SKILL.md.pre-iter-N`), and its revert restores only `SKILL.md`. Lever D edits `REFERENCE.md` and Lever E edits `scripts/`, so a reverted D or E edit stays in the skill.
  - **Both refine skills** (`skill-refine`, `agent-refine`): step 6 makes no per-iteration copy at all; only step 2's once-per-session `.baseline` exists. After the first KEEP, step 8's revert has no stated source, for `SKILL.md` and the agent file as well.
  - **`skill-guardian`** (review R10): step 2 edits `SKILL.md`, or `REFERENCE.md` for Lever D, and step 4 says to revert the edit and compare bytes "before the edit", but the file has no snapshot step at all.
  - **Not affected:** `agent-refine-agent`, which snapshots its single file at every iteration.
  - **Fix (2026-10-21):**
    - **The three skill flows** (`skill-refine` step 6, `skill-refine-agent` step 7b, `skill-guardian` step 2) copy the whole skill folder before each edit, into a fresh `evals/<skill-name>/refine/pre-iter-N/`: `rm -rf` that folder, `mkdir -p` it, `cp -R skills/<skill-name>/. …/pre-iter-N/`. It is outside the folder the keep step syncs into `~/.claude/skills/`, and fresh because N repeats across sessions: a stale copy would turn "delete the file the edit created" into "restore old content".
    - The edit goes to one named file, `<file>`: `SKILL.md` for Levers A–C, `REFERENCE.md` for D, the script for E (`skill-guardian` named only `SKILL.md` or `REFERENCE.md`, though its table routes Lever E to scripts).
    - A revert restores only that file from the copy, or deletes it if the edit created it (`if [ -e …/pre-iter-N/<file> ]; then cp …; else rm …; fi`). `SKILL-EVAL.md` and the append-only `SKILL-REFINE-LOG.md`, both in the skill folder, keep what the iteration wrote. `wc -c` of the copy's `SKILL.md` is the size before the edit for the neutral rule.
    - **`agent-refine`** (the skill) copies the agent file before each edit, as `agent-refine-agent` does, and its revert restores it. Both refine skills' REFERENCE.md tables name the copy.
    - **Tests:** the new `scripts/refine-snapshot.test.js` runs the commands written in the four documents, placeholders filled, in a temp folder: an edit to `SKILL.md`, `REFERENCE.md` or a script, and a new `REFERENCE.md` or script with a stale copy from an earlier session, each reverted; the edited file returns exactly or goes, and the eval report and log keep the iteration's content. On main, all 23 checks fail. Six mutants of the commands, applied to the documents and the test's pinned commands together (no fresh folder, a new file never deleted, the whole folder restored, the copy inside the skill folder, `SKILL.md` only, a nested copy), each fail 6 to 15 checks. `scripts/refine-copy-paths.test.js` now reads a folder copy and a restore from inside it, covers `skill-guardian` and the `agent-refine` skill, and stops a `cp` path at `;`.
    - **Independent review, round 1 (d22461a):** approve with changes, Q1–Q9, none blocking. It reproduced 23/23 failing on main, the six mutants and 41/41 suites; the snapshot, restore and agent copy pass `static-scan.js` and the brain guard. Answered in the next commit:
      - **Q1, Q2, Q5 (test gaps; 7 of the reviewer's document-only mutants survived):** the test now requires the copy before every edit instruction ("Then make exactly …", "Make ONE surgical edit"), fails on any other `cp`, `rsync` or `ditto` from or to the copy (a whole-folder restore in the neutral line had passed), and pins both REFERENCE.md REVERT rows and the two refine skills' rules.
      - **Q3:** the skill flows' paths are quoted. Unquoted, a `<file>` with a space made `[` fail and the `else` branch delete another file (`scripts/my`); the test now runs a `scripts/my tool.sh` edit, existing and new, beside a `scripts/my`.
      - **Q6 and the design note:** after a revert, `diff -rq -x SKILL-EVAL.md -x SKILL-REFINE-LOG.md "<copy>" "skills/<skill-name>"` must print nothing; a listed file is restored the same way, a listed folder the edit created removed. It catches a wrongly named `<file>`, a second stray edit and the empty folder a reverted new file leaves; a test shows it lists both. `diff -x` is in both BSD and GNU diff.
      - **Q4:** a symlinked `<file>` is out of scope (`cp -R` copies the link, so a revert can't restore it), stated in each flow; no skill here has a symlink.
      - **Q7:** `skill-refine-agent` says "use Edit, or Write for a new file".
      - 16 mutants fail the extended test: the reviewer's 7, quoting and the check (docs and test changed together), and the earlier six on the quoted commands.
    - **Q8 (awareness, not changed):** an empty `<skill-name>` would copy all of `skills/` into `evals/refine/pre-iter-N/`, mostly not ignored; an agent filling the placeholder is unlikely to leave it empty. The `rm -rf` of the copy folder may draw a permission prompt in unattended runs; skipping it brings back the stale-copy case, and the post-revert check would then list the stale file.
    - **Untested (review Q9):** no refine run by an LLM was made with the edited flows; the tests run the documented commands, not a loop. The agent flows' unquoted `<name>` paths (as in `agent-refine-agent`) are unchanged.
- **F1 (mitigated 2026-10-20, root cause parked; found 2026-10-19):** `scripts/brain/brain-hooks.test.js` fails intermittently, seen 4 times (plus 1 hang in a timing probe, below). The cause was named on its first run under the new runner (review R1):
  - **The failing check:** `brain-hooks.test.js:24`, runHook's `assert.ok(!r.error)`: "brain-security-guard.sh failed to run or timed out: spawnSync bash ETIMEDOUT".
  - **Where:** it is called from the 512 KB guard-timing loop (`:463`). The hook passed the test's 15 s timeout; this is not the `ms < 3000` check.
  - **Which input** (an inference: the test message names no input):
    - Timing all 12 inputs of that loop 15 times each (`brain-security-guard.sh` alone, fresh capsule) once found exactly one hang: `quotes`, `grep "` plus 512 K `"`, about 1 MB as JSON on stdin. It hung in 1 of 15 runs, to the probe's 30 s limit, against a 72 ms median. Every other input stayed between 51 and 143 ms. The output is saved as the session scratchpad's `guard-timing-run1.txt`.
    - The independent reviewer re-ran the same 15 × 12 timing and saw no hang.
    - 100 more targeted runs did not hang either: 60 async (output not kept) and 40 `spawnSync` with a process watcher (its log records only "0 hang(s)").
    - The input is the same each time, so this looks like a stall in the hook's input or process handling (bash → `node -e` reading fd 0), not a slow pattern.
  - **Root cause:** not found.
  - **Possible security impact (unverified):** the test file states that "a timed-out PreToolUse hook lets the tool call through".
    - `brain-self-install.sh` registered the guard with no `timeout` (before 2026-10-20), so Claude Code's default applied.
    - No probe waited past 30 s, so whether a stall outlasts that default is unknown.
    - If it did, one unusually large command (about 1 MB) could skip the guard. Measuring this and fixing the stall is an owner decision.
  - **Follow-up (2026-10-20):**
    - **The hooks reference** (https://code.claude.com/docs/en/hooks, read 2026-10-19; Claude Code 2.1.302 installed) confirms the impact:
      - "Defaults: 600 for `command`, `http`, and `mcp_tool`".
      - "On `PreToolUse`, a timed-out `command`, `http`, or `mcp_tool` hook doesn't block the tool call … so don't count on a stalled hook to act as a gate."
      - `"onFailure": "block"` (v2.1.295+) makes a timeout block, but it also blocks on any other failure, a missing or crashing node included.
      - So a stalled guard froze each Write/Edit/Bash call for up to 10 minutes, then let it through unchecked.
    - **More repro runs, none hung.** All used the `quotes` input (1,048,677 bytes as JSON), `brain-security-guard.sh` alone and a throwaway capsule:
      - 1,500 runs on an idle machine: none passed 1 s;
      - 300 runs under 24 busy loops on 12 CPUs: none passed 1 s.
      - With the earlier 100 targeted runs, that is 1,900 runs with no hang. Counting the two 15-run `quotes` samples of the timing sweeps, about 1,930 `quotes` runs gave one hang.
      - CI's last 100 runs (2026-10-09 to 2026-10-20) had no failure.
      - All five sightings (4 test failures, 1 probe hang) were local runs made while other work was running.
      - The probe outputs are in the session scratchpad (`guard-hang-1500.txt`; the 300-run load output, whose busy-loop load is not itself recorded in it).
    - **Owner decision (2026-10-20):**
      - Stop looking for the root cause; the new runner report will name the failing check if it comes back.
      - Bound the delay: `brain-self-install.sh` registers the guard with `"timeout": 30` (`brain-self-install.test.js` §2).
      - A re-run gives the timeout to every untimed copy of the guard in PreToolUse, whatever its matcher, and keeps a timeout the owner set (§5, §6). Matching hooks run in parallel, so one untimed copy would still hold a call for 600 s (review G4).
      - A timeout still fails open after 30 s; this bounds the delay and does not close the gap.
      - `"onFailure": "block"` was considered and not adopted, because it conflicts with P11.
      - **Follow-up for the owner:** the change reaches an existing install only when `brain-self-install.sh` is re-run there, this repo's own `.claude/settings.local.json` included (review G10).
    - **G11 and G12 (fixed 2026-10-21; the round-2 review's two non-blocking findings):**
      - **G11:** a `null` entry in a hook list made `brain-self-install.sh` exit 1 with "Cannot read properties of null (reading 'matcher')" before writing anything. It predates F1. `install.sh`'s telemetry step has the same `ensureHookEntry` and crashed the same way, and `extract-project-context.js` caught the same TypeError and dropped every hook in that settings file. All three now skip a `null` entry and keep it in the file as found; the installers already skipped a `null` hook inside an entry, and the extractor now does too (review N5).
      - **Uninstall (review N1):** `uninstall.sh`, the installers' mirror, crashed on the same `null` entries: the telemetry step after it had deleted `scripts/telemetry`, leaving hooks pointing at deleted scripts, and the brain step the same way. Both steps now keep a `null` entry, and the brain step a `null` hook, as found. In the telemetry step, an entry that holds anything besides our hooks is kept whole, as before. `install-hooks-merge.test.js` §3 installs with the second brain over `null` entries in both settings files, then uninstalls; it failed first with the TypeError, and three mutants, each removing one guard, all fail it.
      - **The extractor (review N4):** an event value that is not a list, or an entry whose `hooks` is not a list, also dropped every hook in the file; these are skipped too (`extract-project-context.test.js` §7).
      - **Tests:** `brain-self-install.test.js` §7 and the new `scripts/install-hooks-merge.test.js` (the real `install.sh` on a temp target, HOME pointed at a temp folder) put a `null` entry in every list each installer writes to; both installers finish, add only the missing hooks, find an existing hook past the nulls, and change nothing on a re-run. `extract-project-context.test.js` §7 reads the hooks past a `null` entry. All three failed first, with the TypeError or the dropped hooks.
      - **G12:** `docs/SECOND_BRAIN_SECURITY.md` had lines of 104 to 122 characters where an edit appended a sentence; the prose wraps at about 90. Three lines are reflowed, with the words unchanged. The new `scripts/security-doc-wrap.test.js` fails on any line over 100 characters; it failed first on lines 65, 127 and 154. A short line the reflow left (review N6) is joined, words unchanged.
      - **Q5 in the reference (review N7):** `skills/skill-audit/REFERENCE.md` names the two kept BLOCKs (a token-like string packed in a binary, a quoted private-key header), checked with fake files on 2026-10-21: both BLOCK.
      - **Open (review N2, N3; pre-existing, not changed here; fixed 2026-10-21, see below):** both installers replace a settings file that does not parse (a trailing comma is enough) with only our hooks, against their "merge, never clobber" comments; and when `hooks` or the whole file is a JSON array they report hooks added but write none. Other wrong-typed shapes (an event value that is an object or a string, `hooks` a string, the file `null`) stop the installers with a TypeError before any write.
      - **Open (review N8, N10; pre-existing, not changed here; fixed 2026-10-21, see below):** uninstall's telemetry step keeps a mixed entry whole, so a hook in it can still run `scripts/telemetry/…` after that folder is deleted, with no warning (a `warn` naming each kept entry was suggested). Its brain step removes an entry when **any** hook in it is a brain hook, so an owner's hook in the same entry is deleted with it (probed: `Stop: [{hooks: [echo own, …/hooks/brain/brain-session-end.sh]}]` left `{"hooks":{}}`).
      - **Independent review:** round 1 (22dac1e), approve with changes, N1–N7: N1 (major, uninstall) fixed; N4–N7 fixed; N2, N3 recorded as open. Round 2 (3b8069f), approve: N1 and N4–N7 closed, 8 mutants killed; N9 (the header wording named any key type; the pattern matches untyped, RSA, EC and OPENSSH headers only) and N10's sentence fixed in the next commit; N8 and N10's brain-step behavior recorded as open.
        Round 3 (b05cd67), approve: N9 and N10 closed (the private-key wording checked on fake headers: untyped, RSA, EC and OPENSSH BLOCK, DSA and ENCRYPTED pass); no new finding. N2, N3, N8 and the brain-step removal stay open.
    - **N2, N3, N8 and the brain-step removal (fixed 2026-10-21, PR after #164):**
      - **Settings a script cannot read are never written.** That is a file that does not parse, is not a JSON object, has a `hooks` that is not an object, or (for the installers) has a list for one of their own events that is not a list. `brain-self-install.sh` stops with "… was not changed: <why>. Fix it, then re-run", since the guard hook is its job (`install.sh --with-second-brain` stops with it); `install.sh`'s telemetry step warns and the install goes on; both `uninstall.sh` steps warn and go on. An empty or blank file still counts as `{}`. Before, the installers replaced an unparseable file with only our hooks (N2) and wrote nothing for array-shaped settings while reporting hooks added (N3).
      - **Uninstall removes our hooks one by one.** It keeps the owner's hooks that share an entry with ours and drops an entry only when every hook in it was ours. Before, the telemetry step kept a mixed entry whole, still running a script it had deleted (N8), and the brain step deleted it whole, the owner's hook included. Uninstall now rewrites a file only when it removed something, and its message counts hooks ("removed 4 telemetry hooks").
      - **Tests:** the new `scripts/settings-safety.test.js` runs the real scripts on temp targets (HOME pointed at a temp folder): eight shapes the installers refuse, each with its reason (six of them unreadable for uninstall too, which keeps the other two, a non-list for an event, as found; review P7), empty and blank files for all three scripts, an untouched event of any shape, and mixed entries in both uninstall steps. `install-hooks-merge.test.js` §3 now expects our hook to leave the mixed entry. On main the new test fails at its first check (the brain installer replaced the trailing-comma file and exited 0); 17 mutants, one per guard or rule, all fail it.
      - **Docs:** `README.md` (Removal) and `docs/BRAIN_KERNEL.md` state the rule.
      - **Independent review, round 1 (dc32ac1):** approve with changes, P1–P9, none blocking. It confirmed every section of the new test fails on main, the 17 mutants, and 40/40 suites, and found Claude Code's settings page (code.claude.com/docs/en/settings, read 2026-10-21) saying settings files are strict JSON, a `//` comment or a trailing comma being a Settings Error, so refusing them agrees with Claude Code.
        - **P1–P4 (test gaps; five of the reviewer's mutants survived):** the uninstall steps' empty-file rule, the brain step's empty entry, the count of hooks rather than entries, and the installer's own event-list guard are now tested (an empty string for `Stop` included, which the guard keeps from being overwritten). The five mutants, and two more for P6, now fail the test.
        - **P5:** uninstall's brain step printed "brain hook entries removed" even when it removed nothing; it now counts, as the telemetry step does ("removed 2 brain hooks" or "no brain hook entries found").
        - **P6:** a UTF-8 byte-order mark was reported as an invisible unexpected token; all four steps now say "it starts with a byte-order mark; save it as UTF-8 without one". Whether Claude Code accepts a file with a byte-order mark is not documented and was not tested; refusing is the safe side.
        - **P7, P8:** the test count and the README wording corrected.
        - **P9 (open, pre-existing):** the installers rewrite and reformat the settings file on every run, even when they added nothing; uninstall now writes only when it removed something.
      - **Round 2 (c09630b):** approve; P1–P8 closed, P9 open. Two new nits, fixed in d388129 with tests only and closed in review round 3: P10 (each uninstall step's reason is now matched per file, and a file that is only a byte-order mark is refused, which pins the check before the empty-file rule: `trim()` drops U+FEFF) and P11 (the brain step's `"hooks": null` and singular "1 brain hook" messages). The reviewer's four surviving mutants, and a fifth, now fail the test. Observation O1, not this PR: `scripts/brain/brain-hooks.test.js` timed out once (its 15 s per-hook limit) while the reviewer ran mutants in parallel, and passed on a quiet rerun.
      - **Round 3 (d388129):** approve; P10 and P11 closed, 48 mutants killed (the author's 30 and the reviewer's 18), 40/40 suites. P12 (nit): this record said the author had closed P10 and P11; reworded in the commit that records this round, not re-reviewed (wording only). P9 stays open.
  - **Change:** `run-all-tests.js` now reports a failing suite in full (`scripts/run-all-tests.test.js` pins all of it). The new report named this failure on its first occurrence (review R1):
    - stderr whole up to 200 lines, head and tail beyond that;
    - the last 40 stdout lines;
    - the exit code when there is no output;
    - any spawn error or signal;
    - lines over 2,000 characters cut.
- **E9 (fixed 2026-10-19, from review K3):** `--commit` records HEAD. When a refine loop measures an edited, uncommitted definition, that commit doesn't contain the measured text; only `subject.sha256` pins it. An iteration resumed from a manifest made before `--subject` has `subject: null`.
  - **Fix:** the "Subject revision" bullet now reads "definition sha256 · commit". It is changed in all six copies: the two templates, the two `REFERENCE.md` files and the two eval agents. It says three things:
    - the sha256 identifies the measured text;
    - the commit is HEAD when the run started, so it does not contain an uncommitted definition;
    - write "not recorded" when `subject` is null.
  - `run-manifest.js status` prints `subject=not recorded` in that case; all callers read only its exit code.
  - **Tests:** `scripts/eval-report-sections.test.js` pins the wording, and `scripts/run-manifest.test.js` pins the status line. Both failed first.
  - **Independent review:** approve with changes (L1–L5).
    - **L1:** the report header line in both templates and both `REFERENCE.md` files still put the commit first, with no "not recorded" case. It now matches the bullet, and the test pins it.
    - **L2:** the wording test pinned words, not clauses; a line reversing the meaning passed. It now pins whole clauses, and three meaning-reversing rewrites fail it.
    - **L3:** the status test also requires that a recorded subject never prints `not recorded`.
    - **L4:** split in two. The bullet now also covers a null `commit`; re-hashing on resume is E10.
    - **L5:** recorded as E11.
    - **Round 2:** approve.
      - **L6:** the header test now pins `"not recorded" when missing`.
      - **L7:** the bullet says to write "not recorded" for whichever of `subject` and its `commit` is null, keeping the other.
- **E10 (fixed 2026-10-20, from E9 review L4):** the subject's sha256 is taken once, at `init`. If the definition is edited between an interrupted run and its resume, the recorded hash no longer matches what the resumed scenarios measured, and `status` does not re-check.
  - Fix: `status` re-hashes `subject.path` and warns on a mismatch; the exit code is unchanged.
- **E11 (fixed 2026-10-20, from E9 review L5):** `docs/REVIEW_PROTOCOL.md` says a TEAM-EVAL report's revision is pinned by `run-manifest.js init --subject`. team-eval never calls `run-manifest.js`; `skills/team-eval/SKILL.md` step 7 only says "orchestrator and member revisions".
  - Fix: either give team-eval a manifest with its subjects, or correct the protocol text.
- **E10, E11 and E12 repair (2026-10-20):**
  - **E10:** `run-manifest.js status` re-hashes `subject.path`. It prints "subject unchanged since init", or a WARNING when the subject changed (both sha256 prefixes) or is not found, telling the reader to start a new iteration rather than resume. A relative path resolves against the working directory, as at `init`. The exit code is unchanged: it stays the artifacts-and-grading gate, and a changed subject neither fails a passing status nor passes a failing one. The four eval flows' resume checks say to start a new iteration on that warning. After a warning, a failing status closes with "Do not resume this iteration: start a new iteration" instead of the resume line, and a manifest recording `snapshot` gets its own warning (review R1).
  - **E11:** team-eval writes no run manifest, so the protocol text was wrong, not the flow. `docs/REVIEW_PROTOCOL.md` now says SKILL-EVAL and AGENT-EVAL pin the measured definition with `run-manifest.js init --subject`, and TEAM-EVAL lists the sha256 of the orchestrator and every member. `skills/team-eval/SKILL.md` says how: step 1 records `shasum -a 256 <file>` for each definition plus `git rev-parse --short HEAD` before any run, as `init` does for skills and agents. Step 7 re-hashes them, names any that changed, and carries the commit caveat (review R5).
  - **Owner decision (E12, 2026-10-20):** the report names the baseline that actually runs, no skill (no agent). A true earlier-version baseline is a separate feature for later.
  - **Fix (E12):**
    - All four flows (`skill-eval` and `agent-eval` `SKILL.md` steps 4–6, both eval agents' steps 4–5) record `--baseline-method none` for a new and an existing definition alike, and take no snapshot. The step-5 copy was identical to the subject (review M3), which `subject.sha256` already pins.
    - Old manifests that record `snapshot` start a new iteration instead of resuming.
    - The eval agents' "Unchanged skill/agent with current SKILL-EVAL.md: reuse prior baseline scores" bullet is removed (review R4). The skills never had it, "unchanged" was undefined, and it could carry in scores from a snapshot-era report with no manifest to cite.
    - The report headers say "no skill loaded" / "no agent dispatched" (`baseline_method: none`). The Evidence and Limits section gains a Baseline bullet in all six copies: the delta measures the definition against none, not against an earlier version of it.
    - Both refine skills' re-eval says "with-skill vs no-skill baseline" / "with-agent vs no-agent baseline".
    - `run-manifest.js` still accepts `snapshot`, kept for the later feature; its help says no flow uses it.
    - `scripts/eval-snapshot-paths.test.js` (E8) is replaced by `scripts/eval-baseline.test.js`, which also pins the dispatched baseline instruction in each flow (review R2) and keeps E8's "install.sh ignores evals/" check (review R6). Committed SKILL-EVAL reports from before this change are left as written.
  - **Checked:** on main's documents, the new checks fail: `eval-baseline.test.js` 22 of 22, `eval-report-sections.test.js` 4 (the Baseline bullet in both tracks, E11's two), `run-manifest.test.js` 4 (E10; the fifth, no subject, passes either way). On the branch all pass, and `node scripts/run-all-tests.js` passes 37/37. 12 mutants fail them against a passing control: 4 in `status` (no change check, no missing check, a change that flips the exit code, the recorded hash printed as the current one) and 8 in the documents. After review round 1, 13 more fail them too: the reviewer's surviving A, C and D–G, rebuilt, plus 7 for R1, R4 and R5. static-scan findings for the changed skills and agents are identical to main's.
  - **Independent review, round 1 (7fb6a58):** approve with changes, R1–R7, all minor. It judged removing the snapshot step within the owner's decision, and noted for the owner that an existing skill's session-run baseline really changes: from an identical copy (delta about 0) to no skill (a positive delta). New reports are therefore not comparable with older ones. Answers are above, and in the R3 tests (relative subject path; the not-found advice) and R7 (status lines). The reviewer closes them.
  - **Round 2 (c1f2492):** approve; R1–R7 fixed. New, all minor, answered in the next commit:
    - **R8:** no test of a missing subject with a failing status. Added.
    - **R9:** only the first line of each eval agent's baseline prompt was pinned. The whole prompt is now pinned.
    - **R10:** the `run-manifest.js` help now describes the warnings and the closing line, and says a future snapshot flow must revisit `status` treating every snapshot manifest as stale.

    The reviewer's three surviving mutants for these now fail the tests.
  - **Round 3 (87f1514):** approve; R8–R10 fixed, nothing new. All of R1–R10 are closed.
  - **E6 (owner decision, 2026-10-20):** the instructed `Skill(<name>)` / `Agent(<name>)` marker is kept, as disclosed in every report's Evidence source bullet.
- **Evidence:**
  - **Tests:** 12 new tests in `scripts/harvest-evidence.test.js`, plus 2 existing tests updated for the side-folder rule. Before the fix, 7 of the round-1 tests failed; the rest pin behaviour that review mutants broke. Round 3 added cases for W1 (failed first) and W3 to the E5 tests. All 49 pass, and `node scripts/run-all-tests.js` passes 31/31, including the Codex end-to-end claim test.
  - **Mutants:** 22 were run on a copy, and all were killed. They covered:
    - E2/V3: containment dropped, base instead of side folder, `join` in place of `resolve`.
    - E4: window ignored, flipped or not passed; `lstat`.
    - V6: slack removed, 0.5 s, 5 s.
    - E3: the NaN check dropped.
    - E5: no cut, first end in place of last, no capital-letter check, no closing characters, no `!`, any newline an end, no list-number exemption, no indented list numbers, ASCII-only capitals, any letter in place of a capital.
    - E1: the containment control.
  - **Timing:** linear. 6.3 MB of dense backticks: 169 ms. 150,000 distinct claims, each checked on disk: 680 ms. The sentence-end pattern runs only on slices of 80 characters or less.
  - **Independent review:** round 1 approved with changes (V1–V8). V1–V3, V5, V6 and V7 are addressed here; V4 is addressed for team-eval and recorded as E7 for the agent templates; V8, the skill deploy, follows merge. Round 2 confirmed V2–V6 closed and approved with changes (W1–W5); W1–W5 are addressed here. Round 3 confirmed W1–W5 closed (and V7 with W2) and **approved** with no new findings; open after merge: V8 (deploy) and E7 (E7 since fixed).

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
