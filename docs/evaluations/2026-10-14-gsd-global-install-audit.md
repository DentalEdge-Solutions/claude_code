# GSD global install: audit and skill-listing measurement (P0-C)

> **Date:** 2026-10-14
> **Asked:** What does the globally installed GSD framework run in this project's sessions, and does the skill-listing budget distort eval measurements?
> **Answer:**
> - GSD registers **15 hook scripts** (~18 registrations) that fire in every session. The project's own scanner rates them **BLOCK**.
> - Three of the hooks are genuinely protective.
> - The skill listing **is overflowing**: about 31 skills lose their descriptions in a normal session, including the project's own `codex-eval` and the D1 target `superpowers:writing-skills`.
> **Scope:** read-only, per decision D3 ("audit only, decide later"). Nothing under `~/.claude` was changed.
> **Version:** GSD hooks `gsd-hook-version: 1.14.0`, package `@opengsd/gsd-core`, on Claude Code 2.1.300.

## 1 · What is installed (measured)

| Item | Count | Where |
|---|---|---|
| Skills | 72 (`gsd-*`) | `~/.claude/skills/` |
| Agents | 64 (`gsd-*`) | `~/.claude/agents/` |
| Hook scripts present | 29 (8,505 lines; includes Cursor/Windsurf adapters) | `~/.claude/hooks/` |
| Hook scripts registered | 15, on SessionStart, PreToolUse, PostToolUse, SubagentStop, Stop, PreCompact and FileChanged | `~/.claude/settings.json` |
| Use in this project | none: no `.planning/`, and no commit since 2026-09-01 mentions GSD | `git log` |
| Governance record | none in the brain | `brain-search` |

## 2 · Static scan (the project's own gate)

`node skills/skill-audit/scripts/static-scan.js ~/.claude/hooks` returns verdict **BLOCK**, with 19 findings:
- 6 BLOCK `child-process-require`: `gsd-check-update`, `gsd-context-monitor`, `gsd-statusline`, `gsd-windsurf-pre-write`, `gsd-workflow-guard`, `gsd-worktree-path-guard`;
- 11 FLAG `env-access`;
- 2 FLAG `spawn-call`.

`~/.claude/settings.json` itself scans PASS.

A BLOCK here means "needs human review before use", not "malicious". The point is that **these hooks would not pass the gate the project applies to any external skill**, yet they run in every session.

## 3 · Per-hook classification

| Hook | Event | Can block | What it does | Class |
|---|---|---|---|---|
| `gsd-secret-read-guard.js` | PreToolUse Read\|Grep\|Bash | yes | Blocks reads of `.env`, `.env.*` and `.secrets` | **protective (generic)**; no project equivalent |
| `gsd-read-injection-scanner.js` | PostToolUse Read | no (advisory) | Pattern-scans content returned by Read and WebFetch for injection | **protective (generic)**; fired on the Phase 2 spec (a false positive) |
| `gsd-worktree-path-guard.js` | PreToolUse Edit/Write | yes | Blocks edits to absolute paths outside the worktree root | **protective (generic)**; overlaps the native worktree isolation checks |
| `gsd-validate-commit.sh` | PreToolUse Bash | yes | Blocks `git commit` with a non-conforming message | **global side effect**: applies to every repo |
| `gsd-check-update.js` (+ worker) | SessionStart | no | A detached worker runs `npm view` (network) every session, and compiles GSD's TypeScript locally if the build is missing. No auto-install found | **global side effect** |
| `gsd-context-monitor.js` | PostToolUse, SubagentStop, Stop, PreCompact | no | Injects context-usage warnings from a statusline bridge file | workflow |
| `gsd-agent-isolation-guard.js` | PreToolUse Agent | yes | Guards GSD executor dispatch | workflow (GSD-only) |
| `gsd-workflow-guard.js`, `gsd-read-guard.js` | PreToolUse | no | Advisory guidance outside a GSD workflow | workflow |
| `gsd-prompt-guard.js`, `gsd-write-guard.js` | PreToolUse | write-guard: yes | Act on `.planning/` only | inert here |
| `gsd-config-reload.js`, `gsd-phase-boundary.sh`, `gsd-graphify-update.sh`, `gsd-session-state.sh` | various | no | Act on `.planning/` or are opt-in | inert here |

## 4 · Skill-listing budget (measured in this session)

**Fact:** the listing drops descriptions.
- This session's skill list shows about 31 skills by name only.
- The dropped ones include `codex-eval` (project-local), `superpowers:writing-skills`, `superpowers:systematic-debugging`, `security-review` and 22 `anthropic-skills:*` entries.
- Both `codex-eval` and `writing-skills` define descriptions in their SKILL.md.
- `skillOverrides` has 9 entries, all `off` and none `name-only`, and no budget setting is configured. **So the cause is the default budget (1% of context) overflowing**, as documented: "drops descriptions starting with the skills you invoke least" (`code.claude.com/docs/en/skills.md`).

**Volume** (description + `when_to_use`, capped at 1,536 characters each, enabled user-level skills):

| Source | Skills | Description chars | Share |
|---|---|---|---|
| GSD | 72 | 5,469 | 30% |
| Other user skills (this pipeline, brain, gstack, …) | 30 | 12,226 | 67% |
| Project-local | 1 | 468 | 3% |

Plugin and built-in skills come on top. GSD's per-entry name overhead also counts, because every name is always listed.

**Impact on evals (inference):** a skill under evaluation that is rarely invoked can lose its description from the listing, so trigger accuracy then measures the budget, not the description. This affects any skill-eval run in a session with this global set.

**Not measured:** the exact character budget, which depends on the model's context window and isn't stated per model. `/doctor` (interactive) gives the estimate.

## 5 · Options (decision D3 deferred to the owner)

| Option | Effect | Cost / risk |
|---|---|---|
| A. Keep as is | none | the eval confound and global side effects remain |
| B. Trim | disable GSD skills via `skillOverrides` (`off`, or `name-only` to keep names); unregister the workflow and inert hooks; keep the 3 protective hooks (after a line-level review of those three) | moderate; settings edit with backup; reversible |
| C. Uninstall | GSD's own uninstaller | also removes the 3 protective hooks; the secret-read guard would need a project-native replacement first |
| D. Eval-only mitigation | raise `skillListingBudgetFraction` (e.g. `0.02`), or run evals with `--bare` / a reduced skill set | cheapest; fixes the measurement problem without touching GSD; costs context |

**Recommendation:** D now, so eval validity no longer depends on the GSD decision. Then B, after a line-level review of the three protective hooks. Option C only once the secret-read guard has a native replacement.

## 6 · Decision D3 and option D applied (2026-10-14)

**Owner decision D3:** both, in order. Option D now, then option B after a line-level review of the three protective hooks.

**Applied (option D):**
- `~/.claude/settings.json`: added `"skillListingBudgetFraction": 0.02`. It is the only key changed, verified by a key-by-key diff.
- Backup: `~/.claude/settings.json.bak-d3-2026-10-14`, mode 0600. To roll back, restore the backup or delete the key.
- Source: `code.claude.com/docs/en/skills.md`, section "Skill descriptions are cut short", accessed 2026-10-14. It says the budget is 1% of the context window by default, raised by `skillListingBudgetFraction` (e.g. `0.02`) or `SLASH_COMMAND_TOOL_CHAR_BUDGET`. Over-budget listings log a warning visible with `--debug`. `skillOverrides` does not affect plugin skills.

**Verification (fresh headless sessions, Claude Code 2.1.300, this repo, default model):**

| Run | Budget | Debug log |
|---|---|---|
| control (`--settings '{"skillListingBudgetFraction":0.01}'`) | 1% | `[WARN] Skill listing over budget: 154 skills, 45657 chars > 30000 budget — descriptions will be truncated` |
| new (user settings) | 2% | no over-budget warning |

Rerun: `claude -p "<prompt>" --debug-file <log>` with and without the `--settings` override, then `grep -i budget <log>`.

**Limits:**
- Asking the model which descriptions it saw did not discriminate. The 1% control run also showed both `codex-eval` and `superpowers:writing-skills`, because the dropped set depends on recent invocation frequency. The debug-log warning is the evidence.
- Headroom at 2% is about 14,000 characters. Adding skills can overflow the listing again, so recheck with `--debug` before any skill-eval run.
- The change applies to every project on this laptop.

**Next:** option B, after a line-level review of `gsd-secret-read-guard.js`, `gsd-read-injection-scanner.js` and `gsd-worktree-path-guard.js`. Then the R8 re-eval, which is no longer confounded by the listing budget.

## 7 · Line-level review of the three protective hooks (2026-10-14, option B prerequisite)

**Scope:**
- Read in full: `gsd-secret-read-guard.js` (1,105 lines), `gsd-read-injection-scanner.js` (364) and `gsd-worktree-path-guard.js` (336).
- Also read: their helpers `lib/hook-exit.js`, `lib/filename-classification.js` and the exit path of `lib/cli-exit.js`. `lib/git-probe.js` and `lib/injection-patterns.js` were grepped for side effects.
- Version: `gsd-hook-version: 1.14.0`, on Claude Code 2.1.300.
- Read-only: nothing under `~/.claude` was changed.

Finding IDs use the prefix `HR` so they don't collide with this track's existing `R1`…`R8`.

**What they do at runtime (verified by reading):**
- None of the three makes a network call or writes a file. Their only output is stdout and stderr.
- The secret guard and the injection scanner start no processes.
- The worktree guard runs `git rev-parse` through `spawnSync` with a fixed argv, no shell and a 2 s timeout. That is the static scanner's `child-process-require` BLOCK, and its content is benign.
- `terminateNow` always ends the process. Exit 2 means deny, 0 means allow, and an internal error gives 70, which Claude Code treats as a non-blocking error.

**Probes:** synthetic hook payloads piped to each script with no real file read. The secret guard got 21 cases. The worktree guard got 7, in a disposable repo with linked worktrees. The injection scanner got 5.

| Case | Input (tool: target) | Result |
|---|---|---|
| S01–S03 | Read `.env`, `.env.local`, `.env.example` | block, block, allow |
| S04 | Read `.env.prod.example` | allow (documented rename bypass) |
| S05 | Read `infra/hermes-agent/data/home/.claude/settings.json` | allow (not a covered name) |
| S06 | Read `~/.aws/credentials` | allow |
| S07–S10 | Bash `cat .env`, `cd infra && grep KEY .env`, `source .env`, `cat ~/.hermes/.env` | block ×4 |
| S11–S13 | Bash `python3 -c "print(open('.env').read())"`, `cat .e*`, `printenv` | allow ×3 (documented gaps) |
| S14 | Bash `grep -nE "foo\|process\.env" lib/x.js` | **block (false positive)** |
| S15–S17 | commit message mentioning `config/.env`, `ls`/`test -f .env`, heredoc commit message | allow ×3 |
| S18 | Grep pattern over `.`, no glob | allow: relies on Grep skipping gitignored files. All real `.env` files in this repo are gitignored; the 4 tracked ones are `*.example` |
| S19–S20 | Grep glob `.env*`, Grep path `infra/.env` | block ×2 |
| W1–W3 | from a `worktree-agent-*` worktree: write to the main checkout, an unrelated repo, `.git/hooks` | block ×3 |
| W4–W7 | own files, outside any repo, from a non-agent branch, from the main checkout | allow ×4 |
| I1, I5 | Read, WebFetch with injection text | advisory, LOW (2 patterns), never blocks |
| I2–I4 | the same text in `security/…`, `CHECKPOINT-…`, `.planning/…` | silent (excluded) |

**Findings:**

| ID | Severity | Where | Finding |
|---|---|---|---|
| HR1 | minor | `gsd-secret-read-guard.js:163-174` | The guard protects only `.env`, `.env.<suffix>` and `.secrets` names. The secret actually exposed on this laptop (an API key in a container-home `settings.json`) is outside its scope, as are `~/.aws/credentials` and `printenv` (S05, S06, S13). **2026-10-19:** project deny rules cover the repo's secret files for sessions started at the repo root or in `infra/hermes-agent/` (layer A). User-level rules (which also cover worktree sessions) and removing the key from the repo tree are proposed. See `2026-10-19-hr1-secret-read-controls.md` |
| HR2 | minor | `:29-37`, `:79-89` | These bypasses are documented by the hook itself: interpreter one-liners, shell globs, `$VAR` indirection, and renaming a secret to end in `.example`/`.sample`/`.template`/`.dist` (S04, S11, S12). It is a guard against accidents, not a boundary. |
| HR3 | minor | `:181-187`, `lib/filename-classification.js` `lastSegment`; `:125-128` | False positives: tokens are split on `\` as if they were paths, so a grep regex containing `process\.env` is blocked (S14). `find -name '<secret name>'` is blocked because `find` is not in the non-reading set. Both were hit live in this session. |
| HR4 | minor | `:1051`, `:1100-1104` | Fail-open: a parse error, or stdin taking longer than 3 s, allows the call. This is a deliberate, stated policy. |
| HR5 | minor | `~/.claude/settings.json`, the hook commands | All three hooks run under `~/.hermes/node/bin/node` (v26.9.0, the Hermes desktop app's bundled runtime) before the system node. It runs as the same user, so nothing gains privilege, but Hermes's updater controls the interpreter of every hook. |
| HR6 | minor | `gsd-read-injection-scanner.js:17`, `:232` vs the `PostToolUse` matcher `"Read"` | The code scans WebFetch and WebSearch (I5), but the registration fires on Read only. Web content is never scanned. |
| HR7 | minor | `gsd-read-injection-scanner.js:105-117` | Path exclusions silence the scan for any file under a `security/` folder, with `CHECKPOINT` in its basename, named `REVIEW.md`, or under `.planning/` (I2–I4). A file someone else controls can choose such a name. |
| HR8 | minor | `:330`, `:340-349` | Advisory only: blocking needs `.planning/config.json` `security.injection_blocking`, which this repo doesn't have. A 3-sentence injection scored LOW (2 patterns). The value is limited to a warning. |
| HR9 | minor | `gsd-worktree-path-guard.js:203-212` | Mostly redundant. Claude Code natively blocks Edit/Write/NotebookEdit into the main checkout from any isolated session or subagent, and also checks Bash working directories and git redirects (`code.claude.com/docs/en/worktrees.md`, "How Claude Code enforces isolation", accessed 2026-10-14). The guard adds only the unrelated-repo and `.git`-internals blocks (W2, W3), and only on `agent-*` / `worktree-agent-*` / `worktree-wf_*` branches. |

**Not tested:**
- The Kimi payload path. It doesn't apply here.
- Windows behavior.
- The 3 s and 5 s stdin timeouts under load.
- The secret guard header's claim that `Read()` deny rules make compound `cd … && cat` commands prompt since 2.1.259. It is not verified against the official docs.

**Recommendation for option B:**
1. **Keep `gsd-secret-read-guard`.** It is the only secret-read protection on this laptop: there are no `permissions.deny` rules at user or project level. It blocks the plain cases (S01–S10, S19–S20). HR1–HR3 are reasons to plan a project-native replacement, not to drop it.
2. **Keep `gsd-read-injection-scanner`.** It is cheap, starts no process and only warns. Optionally widen its matcher to `Read|WebFetch|WebSearch` (HR6). That is an owner choice, because it adds warnings on web content.
3. **Unregister `gsd-worktree-path-guard`** (HR9). Native isolation covers its main case. Keeping it is also harmless, so this is the owner's call.
4. If B keeps any GSD hook, keep `~/.claude/hooks/lib/` (`hook-exit.js`, `cli-exit.js`, `exit-code-registry.js`, `filename-classification.js`, `injection-patterns.js`, `git-probe.js`).

## 8 · Option B: prepared change (2026-10-14, not applied)

**Inputs measured before preparing:**
- `~/Projects/claude_examples/des-intelligence-platform` has a `.planning/` folder: GSD use, last activity 2026-05-20 (commits) and 2026-06-02 (files).
- 64 of the 72 GSD skills reference other GSD skills. Hiding them from the model (`off` or `user-invocable-only`) would therefore break GSD workflows there. `name-only` keeps them callable by name and in the `/` menu, and drops only their descriptions (`code.claude.com/docs/en/skills.md`, "Override skill visibility from settings").
- `gsd-surface` (GSD's own skill-surface tool) was not used. It runs GSD code to re-stage skill folders, while `skillOverrides` is a single documented native setting.

**Change** (generated by a script from the live file, source sha256 `e887f5e7…8977b`). Only the `hooks` and `skillOverrides` keys change:
- **Hooks:** unregister 16 GSD registrations: `gsd-check-update`, `gsd-session-state`, `gsd-context-monitor` ×4, `gsd-graphify-update`, `gsd-phase-boundary`, `gsd-prompt-guard`, `gsd-read-guard`, `gsd-workflow-guard`, `gsd-worktree-path-guard`, `gsd-agent-isolation-guard`, `gsd-write-guard`, `gsd-validate-commit` and `gsd-config-reload`.
- **Hooks kept:** `gsd-secret-read-guard` and `gsd-read-injection-scanner` (matcher unchanged, `Read`). The non-GSD `context-mode-cache-heal.mjs` is untouched.
- **Skills:** `skillOverrides` sets all 72 `gsd-*` skills (discovered on disk) to `name-only`. The 9 existing `off` entries are kept.
- **Unchanged:** the `statusLine` (`gsd-statusline.js`), the hook script files on disk, `~/.claude/hooks/lib/`, and the 64 GSD agents.

**Apply** (after owner approval):
1. Confirm the live file's sha256 still matches.
2. `cp -p settings.json settings.json.bak-b-2026-10-14`.
3. Install the generated file with mode 0600.

**Verify:**
- In a fresh headless session with `--debug-file`, no removed GSD hook runs and the two kept hooks still do.
- There is no listing over-budget warning.
- Re-run the secret-guard cases S01, S07 and S19 through a real session.

**Rollback:** restore `settings.json.bak-b-2026-10-14`.

**Known effects and risks:**
- The dormant GSD project loses GSD's hook enforcement (phase boundaries, `.planning/` write guards, commit-message validation) until the backup is restored.
- `gsd-validate-commit` no longer checks commit messages in any repo.
- **Unverified:** a GSD reinstall or update may re-register the removed hooks. Recheck after any `/gsd-update`.
- **Out of scope:** the BLOCK-rated `gsd-statusline.js` and the cost of listing 64 GSD agents.

**Applied 2026-10-14 (owner approval):**
- The live sha256 matched the generation source (`e887f5e7…8977b`). The backup is `~/.claude/settings.json.bak-b-2026-10-14`, mode 0600. The generated file was installed with mode 0600.
- A key-by-key diff against the backup shows only `hooks` and `skillOverrides` changed.
- Registered hooks are now `context-mode-cache-heal.mjs`, `gsd-read-injection-scanner.js` and `gsd-secret-read-guard.js`.
- 72 `gsd-*` skills are `name-only`, the 9 prior overrides are kept, `skillListingBudgetFraction` is still 0.02, and `statusLine` is unchanged.

**Verified** in a fresh headless session (`claude -p --allowedTools Read "Bash(cat:*)" --debug-file …`, run in a scratch directory, using a secret-named path that does not exist):

| Call | Result |
|---|---|
| Read of a plain file | succeeded |
| Read of `./does-not-exist/.env` | blocked by the secret read guard (PreToolUse:Read) |
| Bash `cat ./does-not-exist/.env` | blocked by the secret read guard (PreToolUse:Bash) |

- The debug log names only `context-mode-cache-heal.mjs`, `gsd-read-injection-scanner.js` and `gsd-secret-read-guard.js`. None of the 16 removed GSD hooks appears.
- There is no listing over-budget warning.
