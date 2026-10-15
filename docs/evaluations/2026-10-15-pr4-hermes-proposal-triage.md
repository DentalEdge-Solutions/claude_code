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
| P1 | The brain and telemetry secret-pattern lists diverge | **Open, broader** | Fake-token probe of `SENSITIVE_CONTENT_PATTERNS` (`scripts/brain/brain-lib.js:7`, 6 patterns) and `SECRET_PATTERNS` (`scripts/telemetry/redact.js:29`, 12 patterns). The brain set misses Slack, Google API key, JWT and Bearer. The telemetry set misses the Google API key and the `BEGIN PRIVATE KEY` header. Both catch Anthropic, AWS and GitHub tokens. |
| P2 | No test for `harvest-evidence.js` | Open | `git ls-files \| grep harvest-evidence.*test` → 0 |
| P3 | No test for `static-scan.js` | Open | `git ls-files \| grep static-scan.*test` → 0 |
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
2. **P1:** one shared secret-pattern module (the superset), with a test per token format. Pair it with HR1 from `2026-10-14-gsd-global-install-audit.md` §7 (a secret guard covering `settings.json`-style key files).
3. **P3, then P2:** tests for the security scanner and the eval grader.
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
