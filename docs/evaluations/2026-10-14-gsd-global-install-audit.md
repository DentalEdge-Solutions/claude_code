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
