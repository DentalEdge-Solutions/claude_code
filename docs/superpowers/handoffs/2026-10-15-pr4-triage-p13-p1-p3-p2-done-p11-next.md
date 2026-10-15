# Handoff 2026-10-15: PR #4 triage items P13, P1, P3, P2 done (plus S1–S3 and E1); P11 next

**Start here in the next session.** Read this file, then `.project-brain/BRAIN.md` and `MEMORY.md`. This file
holds no credential value, customer id, hostname or address. It continues
`2026-10-14-software-factory-phase3-merged.md` and covers the PR #4 triage track.

## Rules that still apply (the owner's, plus CLAUDE.md)

- Do not change anything under `~/.claude`, GitHub settings, or push/open PRs without the owner's explicit
  approval. Ask before deleting remote branches. Never commit `evals/`. Never print credential values.
- Follow `CLAUDE.md`, `docs/REVIEW_PROTOCOL.md` (re-run checks yourself; the author never closes its own
  findings) and `docs/CLAUDE_CODE_KNOWLEDGE.md` (official docs first, cite).
- The owner's uncommitted files stay untouched: the two modified `evals/*.json`, `.obsidian/`,
  `.project-brain/reports/`, `docs/master-prompts/`, `infra/hermes-agent/CLAUDE.md`,
  `infra/hermes-agent/deploy/__pycache__/`, `.project-brain/decisions/candidates/2026-08-05-hermes-post-p6-backlog.md`.
- Canon and active decisions change only through `brain-promote --approve`, an invoke-only skill, with an
  explicit verdict from the owner for each item.
- Run `node scripts/run-all-tests.js` after changes under `scripts/` or `skills/*/scripts/`. After changing a
  skill, its copy in `~/.claude/skills/` must be updated, which needs the owner's approval each time.

## Where things stand

- **`main` is at `37683c3`.** Everything below is merged, and the changed skills are deployed.
- **PR #141 is merged:** it promoted the three static-scan brain entries to `decisions/active/`.
- **This file is uncommitted on purpose:** the owner wants it committed with the P11 PR.

| Item | PR | What it did |
|---|---|---|
| P13 | #135 | `scripts/codex/test-runners.js` no longer overwrites the real Codex baselines |
| P1 | #136 | One shared secret-pattern list (`scripts/telemetry/secret-patterns.js`) for the brain gate and telemetry |
| P3 | #137 | `scripts/static-scan.test.js`: tests for the skill-audit security scanner |
| S1–S3 | #138 | Scanner fixes: injection wording, secrets in code, `child_process`. Also the owner's R2 rule, a simple `rm-rf-root`, and linear-time patterns. It took 5 independent review rounds |
| P2 | #139 | `scripts/harvest-evidence.test.js`: tests for the eval grader's evidence script |
| E1 | #140 | `harvest-evidence.js`: an artifact must resolve inside its own workspace (a symlink can no longer fake one) |

- **Deployed:** the updated skill-audit, agent-eval and skill-eval are in `~/.claude/skills/`. Backups of
  the replaced files are in the old session's scratchpad (`skills-backup-2026-10-15*`).
- **Remote branches:** only `main`.

## Documents (read these instead of re-deriving)

- `docs/evaluations/2026-10-15-pr4-hermes-proposal-triage.md` is the full record. It holds the item table,
  the ranked open list, and these repair sections: "P13 repair", "P1 repair", "P3 repair", "S1–S3 repair"
  with every review table (R, B, F, G, H, V), "P2 repair" and "E1 repair". It also holds the gap tables
  S4–S11 for the scanner and E2–E6 for the harvester.
- Brain, active decisions from 2026-10-15:
  - the D3 skill-listing decision;
  - PR #4 closed with its items carried forward;
  - static-scan severity by location (R2), the simple `rm-rf-root` rule, and the regex-change lesson
    (all three via PR #141).

## Next: P11, the brain security guard (`hooks/brain/brain-security-guard.sh`)

This is a PreToolUse hook, the only blocking brain hook. Existing tests are in
`scripts/brain/brain-hooks.test.js`. Probed read-only on 2026-10-15 against `main` `91ddf28` (the guard is
unchanged at `37683c3`):

| Input | Guard decision | Expected |
|---|---|---|
| Malformed JSON, or empty input | allow, **no stderr warning** | The header promises a warning. JSON parse errors `exit 0` silently inside node, and the shell's `\|\| { … failing open }` only fires when node itself fails |
| `grep "rm" .project-brain/decisions` (read-only) | **deny** | allow. False positive: `\brm\b[^\|;&]*\.project-brain` matches the word `rm` anywhere |
| A `git add` listing a capsule file whose name contains `rm-rf` before another `.project-brain` path | **deny** (it happened live while committing PR #141) | allow. The workaround was a wildcard pathspec and `git commit -F <file>` |
| `cd .project-brain && rm -rf decisions` | **allow** | deny. Real gap: the `rm` rule only sees `.project-brain` after `rm`, not via `cd` |
| `find .project-brain … -delete` | **allow** | deny. Real gap |
| `rm -rf .project-brain`; a Write into `canon/` | deny | deny ✓ |

- **Owner decision needed first:** on a parser error, should the guard **fail closed** (deny and say why),
  or **stay fail-open but visible** (a warning, plus a log line)? `docs/SECOND_BRAIN_SECURITY.md` currently
  documents fail-open as intended ("never bricks a session").
- **Method:**
  - Write the tests first in `scripts/brain/brain-hooks.test.js`.
  - Apply the active lesson on regex changes: compare old and new over many samples (allow/deny), time the
    regexes on long inputs, and give each test a timeout.
  - Keep `install.sh` and `uninstall.sh` in sync if any hook registration changes.
- **Watch out:** this guard inspects the session's own Bash commands. A probe or commit whose command text
  contains `rm` and `.project-brain` gets denied, so put such probes in a script file and run that.

## Other open work, ranked

1. **S4:** a bare `"Bash"` allow rule in settings.json isn't caught. Docs: code.claude.com/docs/en/permissions,
   "Match all uses of a tool". The same section notes the permission patterns also fire on deny rules.
2. **HR1** (`docs/evaluations/2026-10-14-gsd-global-install-audit.md` §7): a secret-read guard that also
   covers settings.json-style key files. This is the precondition for ever uninstalling GSD.
3. **S10:** the scanner has no size or file limits. A file over 536 MB is silently skipped (so it passes),
   and a FIFO named `SKILL.md` hangs the scan.
4. P9, then P6 (`uninstall.sh`: an `rm -rf` target guard and portable `sed`); then P8, P7, P12, P14, P10.
5. Harvester E2–E5 (informational fields) and E6 (a method note on the trigger token); scanner S5–S9 and S11.
6. The deferred R8 re-eval of `skill-scout` and `skill-refine` (18–42 subagents each, in a fresh session).
7. **Owner actions:**
   - rotate the Anthropic API key in `infra/hermes-agent/data/home/.claude/settings.json` (never print it);
   - decide whether to turn on auto-delete of head branches;
   - review the 3 stale canon entries flagged by `brain-lint`;
   - other brain candidates are still waiting: 2 decisions and 7 lessons from August and 2026-10-14.
