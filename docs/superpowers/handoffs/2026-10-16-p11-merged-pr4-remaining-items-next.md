# Handoff 2026-10-16: P11 merged (PR #142); next = remaining PR #4 items + follow-on sub-findings

**Start here in the next session.** Read this file, then `.project-brain/BRAIN.md` and `MEMORY.md`. This file
holds no credential value, customer id, hostname or address. It continues
`2026-10-15-pr4-triage-p13-p1-p3-p2-done-p11-next.md` and covers the PR #4 triage track.

## Rules that still apply (the owner's, plus CLAUDE.md)

- Do not change anything under `~/.claude`, GitHub settings, or push/open PRs without the owner's explicit
  approval. Ask before deleting remote branches. Never commit `evals/`. Never print credential values.
- Follow `CLAUDE.md`, `docs/REVIEW_PROTOCOL.md` (re-run checks yourself; the author never closes its own
  findings; approve ≠ merge — merge is the owner's) and `docs/CLAUDE_CODE_KNOWLEDGE.md` (official docs first,
  cite, check the installed Claude Code version).
- The owner's uncommitted files stay untouched: the two modified `evals/*.json`, `.obsidian/`,
  `.project-brain/reports/`, `docs/master-prompts/`, `infra/hermes-agent/CLAUDE.md`,
  `infra/hermes-agent/deploy/__pycache__/`, `.project-brain/decisions/candidates/2026-08-05-hermes-post-p6-backlog.md`.
- Canon and active decisions change only through `brain-promote --approve` (an invoke-only skill) with an
  explicit verdict from the owner for each item. Never write `canon/` directly.
- Run `node scripts/run-all-tests.js` after changes under `scripts/` or `skills/*/scripts/`; run
  `infra/hermes-agent/bin/run-bin-tests.sh` after changes under `infra/hermes-agent/bin/`. After changing a
  skill, its copy in `~/.claude/skills/` must be updated, which needs the owner's approval each time.
- **Editing `hooks/brain/brain-security-guard.sh`:** it is a node program inside a bash single-quoted wrapper.
  NEVER put an apostrophe in a comment or string (use `\x27`) — it closes the wrapper and bricks the hook,
  which then blocks ALL Edit/Write/Bash calls until the file is restored from outside Claude Code. Run
  `bash -n hooks/brain/brain-security-guard.sh` immediately after EVERY edit. Put any probe/command whose text
  contains a deleter word next to `.project-brain` in a SCRIPT FILE (the guard inspects the session's own
  command text and will block it otherwise).

## Where things stand

- **`main` is at `d799f4f`** (merge of PR #142). Everything below is merged.
- **PR #142 merged (P11):** `hooks/brain/brain-security-guard.sh` hardened across 3 rounds — fails closed on
  bad input, visibly open on node failure; delete rule is a superset of main; parser-immune **linear** floor;
  grouping-safe `cd`. This also removed an **O(n²) regex that was a live timeout-bypass on `main`** (a
  PreToolUse hook that times out does not block, so a padded delete could stall the guard and pass).
  Independent review found no bypass. Gaps G1–G5 are documented, accepted defense-in-depth limits.
- **The merged branch `fix/p11-brain-security-guard` was deleted** (local + remote) with owner approval.
- **Remote branches: only `main`.**

### PR #4 item status (full table in the triage doc)

| Done | P1 #136 · P2 #139 · P3 #137 · P4 #131 · P5 (CI) · P11 #142 · P13 #135 |
|---|---|

## Documents (read these instead of re-deriving)

- `docs/evaluations/2026-10-15-pr4-hermes-proposal-triage.md` — the full record: the item table, the ranked
  open list, and the repair sections (P1, P2, P3, S1–S3, E1, and **P11 repair** with its round-3 subsection,
  the floor-linearity finding, differential/mutation/timing evidence, and gaps G1–G5). Also the gap tables
  **S4–S9** (scanner) and **E2–E6** (harvester).
- `docs/SECOND_BRAIN_SECURITY.md` — the guard's exact rules, exemptions, and known limits (updated for P11).
- Brain active decisions from 2026-10-15: PR #4 closed / items carried forward; static-scan severity by
  location (R2); simple `rm-rf-root`; the regex-change lesson (a security regex change needs a differential
  AND a timing check — this is what caught the P11 O(n²) bug).

## Next work (owner's requested order: P9, P8, P7, P6, P12, P14, P10; then E2–E6, S4–S9, HR1)

### Remaining PR #4 items

| Item | Where | What is needed |
|---|---|---|
| **P9** (highest risk) | `uninstall.sh:19-24`, 7 `rm -rf` calls | TARGET is only resolved with `cd`, so `/` or `$HOME` passes. Guard the target before any `rm -rf` (reject root/home/empty). TDD: write the failing test first. |
| **P8** (grown) | `infra/hermes-agent/skills/` (6 skills) | 0 `SKILL-EVAL.md` / `evals.json`. Needs evals per skill. Large; may warrant its own plan. |
| **P7** | `infra/hermes-agent/bin/make-review-board.py:39` | Hand-rolled YAML parsing → use a real parser (stdlib-only constraint: see the bin test rule). |
| **P6** | `uninstall.sh:108` | BSD-only `sed -i ''` breaks on Linux; make portable. |
| **P12** (partly done) | `score-candidates.js`, `extract-project-context.js` | Add the two missing tests (`validate-skills` already has one). |
| **P14** (partly done) | `docs/superpowers/specs/archive/2026-07-20-hermes-master-architecture.md` | Its REVISED banner points to `~/.claude/plans/…` (machine-local); repoint to a repo document. |
| **P10** (low) | — | No `ARCHITECTURE.md`; `CLAUDE.md`/`README.md` partly cover it. |

### Follow-on sub-findings (opened while fixing P2/P3; all informational/scanner-quality)

- **Scanner (static-scan.js), S4–S9:** S4 bare tool name in allow/deny rules missed (`"allow":["Bash"]`);
  S5 extensionless shebang scripts not scanned; S6 secrets in non-`settings*.json` JSON/YAML not scanned;
  S7 current key formats missed (`sk-proj-…`, `sk-ant-oat01-…`, `ghs_…` — the shared list already catches
  these); S8 `subprocess-shell-true` stops at first `)`; S9 single-file mode reports `file: ""` (cosmetic).
- **Harvester (harvest-evidence.js), E2–E6** (all informational-field only, not security): E2 claim path can
  leave the workspace; E3 invalid `started_at` → all `mtime_in_window:false`; E4 `claim_verified` means
  "exists" not "written by this run"; E5 the 80-char claim window crosses sentences; E6 `skill_loaded` is an
  instructed marker in the subagent's output, not an independent log (a method question, not a bug).
- **HR1** (separate, from `2026-10-14-gsd-global-install-audit.md` §7): a secret-read guard covering
  `settings.json`-style key files. Still open.

## Verification quick-reference

- `node scripts/run-all-tests.js` → expect all suites pass (27 as of P11).
- `node scripts/brain/brain-lint.js` → expect 0 security findings (3 known stale-canon warnings).
- For any security-pattern (regex) change: a differential vs the prior version AND a timing sweep on
  512 KB–1 MB inputs are mandatory (brain decision 2026-10-15). The P11 harnesses (differential.js,
  mutate2.js, timing-sweep.js, red-probe*.js) live in the prior session's scratchpad; rebuild as needed.

**This file is uncommitted.** Commit it with the next piece of work, or on the owner's request.
