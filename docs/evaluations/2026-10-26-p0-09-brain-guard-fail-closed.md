# P0-09 — brain guard fails closed; registration committed; brain-guard gaps G1 and G3 closed

> **Date:** 2026-10-26 · **Branch:** `fix/p0-09-brain-guard-fail-closed` (base `1bec99e`) · **Roadmap:**
> `docs/evaluations/2026-10-22-optimization-strategy/S5-prioritized-roadmap.md`, P0-09 (with its "Round 2 additions
> (OC-4)"); S6 D-11, RK-14, RK-15. **Installed:** Claude Code 2.1.310, node v26.9.0, `/bin/bash` 3.2 (the only bash on
> `PATH`). Implementer's record; the independent reviewer closes findings (`docs/REVIEW_PROTOCOL.md`).

## Reversal stated

This change **supersedes** two owner decisions recorded in the active decision
`.project-brain/decisions/active/2026-10-21-pr-4-follow-ups-finished-p8-and-the-brain-guard-gaps-stay-op.md`:

- the **P11 failure policy** (node missing or crashing fails open but visibly, exit 1;
  `docs/evaluations/2026-10-15-pr4-hermes-proposal-triage.md`, "P11 repair"): the guard now fails closed (exit 2);
- the **F1 non-adoption of `onFailure: "block"`** ("considered and not adopted, because it conflicts with P11",
  triage F1): the registration now sets it.

The capsule was not edited. After merge, the owner (or the coordinator with the owner's approval) records the
replacement through capture → compile → `brain-promote --approve`, superseding the 2026-10-21 decision (its other
contents, P8 and the remaining guard gaps G2, G4, G5, stay true and should be carried into the replacement). The
weekly review's new `--to superseded` route (below) can retire the old file once the replacement is active.

## What changed

| Area | Change |
|---|---|
| `hooks/brain/brain-security-guard.sh` | **Fails closed**: node missing, crashing, killed, unable to start, or past `BRAIN_GUARD_DEADLINE_S` (default 20 s, under the 30 s hook timeout) → stderr reason, a `guard-failures.log` line ("fails closed"), **exit 2** (blocked). A program cut short (a stray apostrophe ends its bash single-quoted text) exits 3 → blocked. **G1:** the `brain-promote` exemption holds only for a raw command that is exactly one plain `node <script> … --approve …` call, `<script>` being `scripts/brain/brain-promote.js`, `./scripts/…` or the project's absolute path. **canon/ and decisions/active/ are an allowlist** (G3 is a consequence): a Bash command that reaches them passes only as that promote call or as a read-only form; Write/Edit/NotebookEdit into either is denied. **One canonical path form** for every check (kernel-order symlink resolution, Unicode/case folding). Delete rule: cwd-aware, symlink-aware, a second folded pass. Details under "The guard after the security reviews" |
| `.claude/settings.json` | PreToolUse `Write\|Edit\|NotebookEdit\|Bash` → `bash` with `${CLAUDE_PROJECT_DIR}/hooks/brain/brain-security-guard.sh` as its argument (exec form), `timeout` 30, `onFailure` `"block"`. Telemetry hooks unchanged (fail-open) |
| `infra/hermes-agent/.claude/settings.json` | The same registration through a launcher: walks up from `$CLAUDE_PROJECT_DIR` to the first folder holding `hooks/brain/brain-security-guard.sh` and runs it; none found → exit 2 with the break-glass pointer (never exit 0 unchecked). The project folder reaches it as its own argument, not inside the script text |
| `scripts/brain/brain-self-install.sh` | Registers the guard in the target's **shared** `.claude/settings.json` (exec form, timeout 30, onFailure block; an owner-set value is kept); removes the old shell-form guard registration from `.claude/settings.local.json`; the five other brain hooks stay fail-open there. Both files are checked before either is written; a file is written only if it changed |
| `uninstall.sh` | Removes brain hooks from both files **before** deleting files; keeps `hooks/brain/` (with a warning) when `settings.json` cannot be read, since a fail-closed registration naming a deleted script blocks every call |
| `install.sh` | Dry-run text only (where each registration goes). Install/uninstall stay in sync: install step 8 calls `brain-self-install.sh`; uninstall's brain step mirrors both files |
| `scripts/brain/brain-promote.js` | `--to superseded` (a `decisions/active/` file → `decisions/superseded/`, `status: superseded`, `superseded_at`, logged; candidates and canon refused); a self-promotion (source = destination) exits 1 — `--force` used to write the file and then delete it (seen red) |
| `skills/brain-weekly-review/SKILL.md` | Decision changes go through `brain-promote` (below); `description:` unchanged. **Owner deploy after merge** |
| Docs | `docs/SECOND_BRAIN_SECURITY.md` (rule, fail-closed policy, registration, break-glass, limits), `docs/BRAIN_KERNEL.md`, `.gitignore` comment |
| Tests | `scripts/brain/brain-hooks.test.js` (F1 quarantine; fail closed; G1; G3; decisions/active; every security-review class), `scripts/brain-guard-registration.test.js` (new), `brain-self-install.test.js`, `brain-promote.test.js`, `settings-safety.test.js`, `install-hooks-merge.test.js` |
| P0-07 record | Separate docs commit: the owner's 2026-10-26 fresh-session probe (done) and local allow trim |

Not touched: `.project-brain/`, `evals/`, `skills/skill-eval`, `skills/agent-eval`, `scripts/codex/`, pinned evaluator
files, `infra/hermes-agent/bin/`, any `settings.local.json`, the main checkout, `~/.claude`.

## Step 0: the intermittent F1 failure — quarantined, with the reason

Background (triage F1): `brain-hooks.test.js`'s 512 KB timing loop failed four times locally with `spawnSync bash
ETIMEDOUT` (15 s); about 1,930 earlier runs of the suspect `quotes` input gave one hang; root cause not found.

Measured here, before any guard change, on `1bec99e`'s guard (scripts in the session scratchpad `pr7/f1/`):

| Run | Result |
|---|---|
| `brain-hooks.test.js` × 20, sequential | 0 failures; median 15.9 s, max 16.3 s |
| `quotes` input (1,048,677 bytes as JSON) × 1,000, idle, process tree and `sample` captured on any run over 5 s | 0 hangs; median 119 ms, p99 133 ms, max 161 ms |
| same × 500 under 14 busy loops on 12 CPUs | 0 hangs; median 166 ms, p99 193 ms, max 198 ms |

So about 3,430 `quotes` runs now give one hang in total. Not reproducible, so not resolvable here. **Quarantined
with this reason:** a timing run that hits the runner timeout is retried once and the retry must meet the same 3 s
bound; the stall is printed to stderr (`F1 quarantine: …`). A super-linear pattern is deterministic and fails both
runs, so the loop still detects what it exists for. The security impact F1 named ("a timed-out PreToolUse hook lets
the call through") is gone after this PR: a stall now ends at the guard's 20 s deadline with exit 2, and the hook
timeout with `onFailure: "block"` blocks too. Residual: a genuine one-off stall would block one tool call.

## Docs (Tier A, read 2026-10-26; installed 2.1.310)

Fetched as Markdown: <https://code.claude.com/docs/en/hooks.md>, <https://code.claude.com/docs/en/settings.md>,
<https://code.claude.com/docs/en/headless.md>, <https://code.claude.com/docs/en/cli-reference.md>,
<https://code.claude.com/docs/en/permission-modes.md>, <https://code.claude.com/docs/en/permissions.md>,
<https://code.claude.com/docs/en/changelog.md>. `claude --help` checked for `--safe-mode`.

| # | Question | Finding | Source |
|---|---|---|---|
| H1 | `onFailure` | "Whether the action that triggered the hook goes ahead when the hook fails: `"continue"` or `"block"` … Requires Claude Code v2.1.295 or later". Failures: "Can't start", "Exit code other than 0 or 2", "Timeout: the hook reaches its `timeout`", "Invalid output". "With `"block"` set, a failure does what exit code 2 does on that event … a `PreToolUse` failure blocks the tool call". Changelog 2.1.295 (October 8, 2026): "Added `onFailure: "block"` for command and HTTP hooks" | hooks › Command hook fields; › Block the action when a hook fails; changelog |
| H2 | Timeout | "Defaults: 600 for `command`…"; "On `PreToolUse`, a timed-out `command` … hook doesn't block the tool call, except for hooks whose failure blocks the action" | hooks › Common fields; › (timeouts) |
| H3 | Duplicate handlers | "If you define the same handler in more than one settings file, it runs once." Which copy's fields (`onFailure`) win is **not stated**. Hence the new registration uses **exec form**, a different handler from the old shell-form local one: both run ("When an event fires, its matching hooks run in parallel"), and either can block. The old copy runs the same (now fail-closed) script, so it blocks on failure too, except that a timeout of the old copy alone would let the call through — the new copy's own timeout still blocks | hooks › Hook handler fields |
| H4 | Exec form | "`args` … `command` is resolved as an executable and spawned directly … no shell"; placeholders "substituted into `command` and into each `args` element as plain strings"; "Prefer exec form for any hook that references a path placeholder". Changelog 2.1.139 (May 11, 2026): "Added hook `args: string[]` field (exec form)" | hooks › Exec form and shell form; changelog |
| H5 | `$CLAUDE_PROJECT_DIR` | "the project root where the session started"; with a worktree entered mid-session it "stays put". What it is for a session **started in a subdirectory** of a git repository is not stated (owner probe below) | hooks › Reference scripts by path |
| H6 | Which settings load | "Claude Code reads the shared `.claude/settings.json` from the session's primary working directory"; the local file is read at the repository root, "In a worktree, it uses the file at the main checkout's root" | settings › Where Claude Code keeps the local file |
| H7 | Handler cwd | "Handlers run in the current directory with Claude Code's environment"; the hook input's `cwd` "follows Claude … the new directory after Claude runs `cd`" | hooks › Hook handler fields; › Reference scripts by path (note) |
| H8 | `-p` runs | "Without `--bare`, a `-p` session runs the hooks in a project's `.claude/settings.json`" | headless |
| H9 | `--allowedTools` | "Tools that execute without prompting … To restrict which tools are available, use `--tools` instead" — an approval list, not a restriction | cli-reference |
| H10 | Plan mode | "Claude reads files, runs shell commands to explore"; without auto mode, "commands outside the built-in read-only set prompt" (a denial in `-p`) | permission-modes › Analyze before you edit with plan mode |
| H11 | Break-glass | `--safe-mode`: "Start with all customizations disabled …: CLAUDE.md, skills, plugins, hooks, MCP servers …" (`claude --help` on 2.1.310 lists it; added 2.1.169). Settings files "reload … including edits to … `hooks`" | cli-reference; settings |

## The weekly-review route

`brain-promote.js` already supported overwriting with `--force`; it had no way to retire an active decision. The
route chosen adds **no new write path** into a protected folder: `brain-promote.js` stays the only writer to `canon/`
and `decisions/active/` (as its header and `SECOND_BRAIN_SECURITY.md` already claimed), and no guard exemption was
added. The alternative, a narrow guard exemption for `git mv decisions/active/x decisions/superseded/`, would have been
a new exemption in a security pattern, run without the ask prompt.

- Changed decision → the revised copy is written to `decisions/candidates/<same file>.md` (Write, allowed), then
  `node scripts/brain/brain-promote.js decisions/candidates/<file>.md --approve --to active --force`.
- Superseded → `node scripts/brain/brain-promote.js decisions/active/<file>.md --approve --to superseded`.
- Each runs only for an item the user answered in that session; the P0-07 ask rule `Bash(node
  scripts/brain/brain-promote.js *)` prompts for each.

Evidence: `brain-promote.test.js` §10 (both routes, refusals, the self-promotion bug red first);
`brain-hooks.test.js` §6i-d reads every `brain-promote` command in the skill and asserts the guard allows it.

## Subdirectory coverage (D-11, RK-15) — decision and the owner probe

Sessions started in `infra/hermes-agent/` read `infra/hermes-agent/.claude/settings.json`, not the root file (H6).
Options considered:

| Option | Effect | Verdict |
|---|---|---|
| (a) No registration there | Coverage only from the old local registration, which the owner removes → none | rejected: a silent gap (review E) |
| (b) `${CLAUDE_PROJECT_DIR}/../../hooks/brain/…` | Right only if the variable is the subfolder; if it is the repository root, every call is blocked | rejected |
| (c) **Launcher (implemented):** walk up from `$CLAUDE_PROJECT_DIR` to the first folder holding the guard; none → exit 2 | Resolves whether the variable is `infra/hermes-agent`, a folder below it, or the repository root (tested); blocks only if no folder at or above it holds the guard, which cannot happen for a session started inside this repository | **recommended and implemented** |

The first launcher in this branch exited 0 with a notice when it found nothing; background review E called that a
fail-open, and it now blocks. The test (`brain-guard-registration.test.js`) runs the handler exactly as Claude Code
would (exec form, placeholder substituted, variable exported) for the subfolder, a folder under it and the root
(guard reached, a canon write denied, `ls` allowed) and for an empty, a relative, a missing and a quoted/`$(…)` folder
(exit 2). The root registration's path is asserted to resolve in the checkout that holds the file (the shared-file
case: a session at the repository root or a worktree root, V2-RS-11).

**Owner probe (pending; the implementer cannot start sessions).** From a terminal, at the repository root of a
checkout that has this change:

```
cd infra/hermes-agent
claude --debug-file /tmp/p0-09-probe.log -p 'Run the Bash command: ls' --allowedTools 'Bash(ls)'
grep -n 'Hooks: PreToolUse:Bash' /tmp/p0-09-probe.log
claude -p 'Run the Bash command: echo "$CLAUDE_PROJECT_DIR"' --allowedTools 'Bash(echo *)'
```

Expected: the `ls` output is printed (the launcher found the guard and allowed it); the log line ends `finished with
status 0`; the last command prints the folder the session's `CLAUDE_PROJECT_DIR` holds if Claude Code exports it to the
Bash tool (if it prints an empty line, the value is visible only to hooks: then add `echo "$1" >&2;` at the start of the
launcher's script for one probe run and read the `Hooks:` debug line instead, and revert). Record: which folder the
variable names in a session started in `infra/hermes-agent/`.

## Hermes (OC-4, shared with P0-07): from the repository files only

1. **Do the root hooks load?** Yes, by the docs: the proposer runs `claude -p` with workdir `/projects/claude_code`
   (`infra/hermes-agent/registry/projects.yaml`, `workdir`), without `--bare` in any tracked invocation (P0-07 record),
   and "Without `--bare`, a `-p` session runs the hooks in a project's `.claude/settings.json`" (H8). The compose file
   mounts the repository read-only at `/projects/claude_code` and masks only `infra/hermes-agent`
   (`docker-compose.yml`, the `../..:/projects/claude_code:ro` volume and the tmpfs), so `.claude/settings.json` and
   `hooks/brain/` are visible.
2. **Can it fire?** Yes, on Bash calls. `--allowedTools 'Read,Grep,Glob'` approves those tools; it does not remove Bash
   (H9), and plan mode lets Claude run read-only shell commands to explore (H10). Write/Edit/NotebookEdit are blocked
   by plan mode before or regardless of the guard's answer.
3. **What does it decide there?** Exploration commands (`ls`, `cat`, `grep`, `git log`) are read-only forms: allowed.
   It denies only a write to a protected folder or a capsule delete, which the read-only mount would refuse anyway.
   The failure log cannot be written (read-only mount); the write fails silently and does not change the decision.
4. **Can it block every Bash call there?** Only if the guard cannot run: `node` is present (`Dockerfile`: "Node 26 is
   present in the base image", and Claude Code is installed with `npm`); **`bash` is not provable from the repository**
   (the base image's contents are not described). If `bash` were missing, exec form could not start and
   `onFailure: "block"` would block every Bash call in proposer runs; Read, Grep and Glob would still work, so the
   proposal would be degraded, not stopped.
5. **Conclusion:** the guard loads and can fire in Hermes `claude_code` runs; on the repository's evidence it allows
   their read-only exploration and can only block Bash/Write/Edit/NotebookEdit calls. Not excluded; impact accepted as
   low, pending the box probe.

**Owner box probe (security review #12):** inside the gateway container, `docker compose exec hermes-agent sh -c
'command -v bash node; node --version; ls -l /projects/claude_code/.claude/settings.json
/projects/claude_code/hooks/brain/brain-security-guard.sh'` — expected: both paths printed by `command -v`, node 26,
both files present. Then one scheduled proposer run: expected to finish with the same output shape, and no `hook error`
or `blocking because onFailure is "block"` text in its output. **Checklist / review #12 impact:** review #12 should note
that the root project settings now carry a fail-closed PreToolUse hook that loads in executor runs, and the Hermes
checklist should gain "bash and node on `PATH` in the gateway image" (not edited here: the checklist lives under
`infra/hermes-agent/bin/`, out of scope).

## Old local registration (owner action)

From `brain-self-install.sh`, the old entry in the main checkout's gitignored `.claude/settings.local.json` is: in
`hooks.PreToolUse`, an entry with `"matcher": "Write|Edit|NotebookEdit|Bash"` holding `{"type": "command", "command":
"bash \"$CLAUDE_PROJECT_DIR/hooks/brain/brain-security-guard.sh\"", "timeout": 30}`. **After merge, remove that hook**
(and its entry if it holds nothing else); keep the five other brain hooks (`brain-pre-compact`, `brain-session-end` ×2,
`brain-post-lint`, `brain-load`). Either edit by hand, or re-run `bash scripts/brain/brain-self-install.sh` at the
repository root, which removes exactly that hook and writes the guard into `.claude/settings.json` only if it is
missing (it is already there). Until then both copies run; either blocks on failure (H3).

## Break-glass

Written in `docs/SECOND_BRAIN_SECURITY.md`, "Hook gate" → "Break-glass": the owner, outside Claude Code, checks node,
repairs it, or bypasses the guard for one repair session with `claude --safe-mode` or by setting the guard's
`onFailure` to `"continue"` in an editor; then runs `brain-hooks.test.js` and undoes the change. Claude Code must never
edit the registration during a break-glass.

## The guard after the security reviews

Nine background security reviews (summaries only) ran on intermediate commits while this branch was in progress. Each
was investigated with probes, red tests first (kept), then a fix. They moved the protected-path rule from a list of
write verbs to a structural allowlist.

**Final shape (head):**

- *Canonical path form*, one routine for every check: the path is walked segment by segment as the kernel does (each
  existing prefix replaced by its real path, so a symlink is resolved before `..`; `""` and `.` skipped); a path over
  4,096 characters is resolved lexically only; names are compared folded (NFKD, combining marks dropped, upper- then
  lowercased). Words are also read logically (the `cd` builtin's `..`); the union counts.
- *Write/Edit/NotebookEdit*: the canonical target under `canon/` or `decisions/active/` is denied.
- *Bash, canon/ and decisions/active/*: passes only as one plain `brain-promote … --approve` call or a read-only form
  (every stage of every pipeline a pure reader: neither runs its arguments nor writes; no `$(…)`, backticks, heredoc,
  comment or writing redirect). A command reaches them by folded name (ANSI-C decoded, quotes and backslashes
  dropped), by any word resolved on disk from every folder the shell may be in (hook input `cwd` plus every `cd`/
  `pushd` target, kept), by a parent folder given to a non-reader stage, by a glob or brace word that may match (two-
  pointer wildcard, bash's leading-dot rule, brace expansion capped at 64), or by an expansion the guard cannot follow
  next to a protected-looking name. Brain tools that never write protected folders pass as one plain call with at
  most the capsule as `--target`. Over 5,000 words, 5,000 word resolutions or 20,000 disk lookups: read-only forms only.
- *Delete rule*: starts at the cwd's depth inside the capsule; a stage names the capsule by name, by a word or `cd`
  target that resolves into it, by a glob or brace that may match it, or by an expansion in a command showing the
  capsule name; a second pass with capsule words folded; main's floor kept (lowercased).
- *No state between calls* (review J): nothing is cached, stored or read back; environment inputs (`HOME`,
  `CLAUDE_PROJECT_DIR`, `BRAIN_GUARD_DEADLINE_S`, `PATH` for `sleep`) cannot turn a block into an allow.

### Security review (background) — authorization bypass

| ID | Commit reviewed | Class | Confirmed? | Probes (scratchpad `pr7/diff/`) | Resolution | Proof |
|---|---|---|---|---|---|---|
| R0 (first review) | `e8c673e` | authorization bypass | **Yes, 7 regressions** (main denied each): G3's exemption reused "programs that never run their arguments", several of which write: `git restore` (also `--source`), `git switch -f`, `git branch -f`, `touch`, `mkdir`, `find -fprint` on an rm-named canon file | `bypass-probes.js`, 107 probes: e8c673e allowed 44, 7 denied by main | `82a075b`: pure-reader set; then superseded by the allowlist (`bb2524c`) | red `336f6e1`; `brain-hooks.test.js` §6i-e |
| A | after `82a075b` | incomplete denylist | **Yes**, 13/13: `sort -o`, `perl -pi -e`, `ruby -e`, `curl -o`, `wget -O`, `chmod`, `split`, arbitrary node/bash scripts, `xxd -r`, `ed`, `cd …; cd canon; touch` | `batch2-probes.js` | `bb2524c`: allowlist replaces the verb list | red `4474193`; §6i-f |
| B, C | after `82a075b` | case-insensitivity differential; Unicode case folding | **Yes**, 6/9: fullwidth letters, dotted/dotless i (ASCII `/i` did not cover them), also for `rm -rf` and `cd` | `batch2-probes.js` | `bb2524c`: NFKD + mark stripping + upper/lower fold in one routine | red `4474193`; §6i-f |
| D | after `82a075b` | symlink bypass | **Yes**, 4/4 Bash (`cp`/`cd`/`echo`/`rm` through a link), 2 Write | `batch2-probes.js` | `bb2524c`: words resolved on disk; kernel-order canonical form | red `4474193`; §6i-f |
| unnamed (batch 1) | after `82a075b` | — | covered by the probes above; the working-directory gap (a cwd inside the capsule, 4/4 allowed) was found in the same pass | `batch2-probes.js` | `bb2524c`: hook input `cwd` | §6i-f |
| E | settings | fail-open in `infra/hermes-agent/.claude/settings.json` | **Yes**: the first launcher exited 0 when no guard was found | `brain-guard-registration.test.js` | `bb2524c`: walk up, exit 2 when none | red `4474193`; registration test |
| F | after `82a075b` | path-normalization differential | **Yes**, 1/5 Bash + 1 Write: `lnk-deep/../active` (kernel resolves the link before `..`; the lexical resolve landed elsewhere) | `batch2-probes.js` | `bb2524c`: one canonical routine, kernel order | red `4474193`; §6i-f |
| (self) | during F | fail-open on a truncated program | **Yes** (found while fixing F): a comment with two apostrophes ended the bash-quoted program early; node ran only the helpers and allowed every call with exit 0 | §6i-g | `aed9082`: exit 3 unless the last line is reached | red `475e041`; §6i-g; mutant M5 |
| G | after `bb2524c` | incomplete target detection | **Yes**, part of 14/21: globs, braces, a variable or `$(…)` building the name, a parent folder moved/re-permissioned/synced, capsule deletes through glob, brace or variable | `batch3-probes.js` | `f7cc0c3` | red `f2916f1`; §6i-h |
| H | after `bb2524c` | parser differential | **Yes**, part of 14/21: ANSI-C `$'\x2e…'` | `batch3-probes.js` | `f7cc0c3`: decode; quotes/backslashes dropped in the folded text | red `f2916f1`; §6i-h |
| unnamed (batch G/H) | after `bb2524c` | — | the self-review of `f7cc0c3` found the brain-tool exemption applied to canon/active hits with any `--target` (capture/compile/lint write below their target), a lookup budget that quietly stopped checking, and `~user` (5/6 allowed on `f7cc0c3`) | `selfreview-probes.js` | `915e412` | red `b87cc1e`; §6i-i |
| I | after `f7cc0c3` | authorization bypass | **Yes**, the same brain-tool `--target` bypass (e.g. `brain-capture.js --target .project-brain/canon` allowed on `f7cc0c3`) is the confirmed candidate; no other bypass found in the probes | `selfreview-probes.js`, `bypass-probes.js` | `915e412` | §6i-i |
| J | after `915e412` | fail-open state drift | **No state found**: the guard reads only stdin, the filesystem and environment variables, keeps nothing between calls; one input could weaken a check: with `HOME` unset, `~` words were not resolved | `jk-probes.js` | `f92f87b`: `~` with `HOME` unset is an expansion; statement in the code and doc | red `657f962`; §6i-j |
| K | after `915e412` | parser differential | **Yes**: the `cd` builtin reads `link/..` logically; a cd through a link inside `decisions/` into `../active` passed | `jk-probes.js` | `f92f87b`: physical and logical readings | red `657f962`; §6i-j |

| L | after `f92f87b` | control regression (a base denial lost) | **No regression found.** Full differential base `1bec99e` vs head (below): every one of the 7,278 deny → allow flips is a read-only form whose base denial came only from a mutation word used as an argument or file name; the probe differential gives 3 deny → allow, all G3. The G1 exemption is narrower than base (14,334 chained-promote inputs flip to deny, none the other way) | `differential.js`, `classify-d2a.js`, `probe-diff.js`, `vm-check.js` | none needed | Differential section |
| (mutants) | `0da0112` | test gaps | M11 survived alone (the earlier ANSI-C case showed the name in plain text too); the review-G looks-protected test caught `systemctl is-active "$UNIT"` as a false positive | `mutants2.js` | `0da0112`: `active` counts only as a path segment; a fully hex-encoded case added | red `63039e9`; §6i-k |

All probe sets at head: batch 1 0 regressions (5 known limits, below); batch 2 0 of 41 allowed; G/H 0 of 21 allowed
and 10 of 10 allowed as intended; self-review 0 of 6; J/K both denied.

### Deliberate residuals (kept, with reasons)

1. A command built at run time with **no** protected-looking text (`$(printf …)` producing both `canon` and the
   capsule name, a decoded string, a script an executor runs) — static analysis cannot decide; blocking every
   expansion in every command would block ordinary work.
2. Path-less git commands that rewrite protected files (`git reset --hard`, `git stash pop`, `git apply`,
   `git checkout <branch>`) — they name no path; git history is the recovery.
3. A hard link to a protected file made before the guard existed, then written through.
4. A Bash write through a symlink resolved only at run time (a link created in the same command).
5. Moving or overwriting the capsule outside `canon/` and `decisions/active/` is not a "delete" (`cp -r` over it,
   `truncate`, `: >`) — the old G2 class, narrowed: parents of the protected folders are now covered.
6. Conservative denials (no bypass): any command that reaches a protected folder and is not a read-only form or one
   plain brain call, e.g. `cat .project-brain/canon/x.md && npm test`; prose and fixture lines in the real corpus
   (below); `cd .project-brai? && make`.
7. G4 and G5 of the P11 repair stay as recorded (the reader list depends on known program-running options; a
   capsule-leaving `cd` on a line with a group is not honored).

## Differential (regex rule) and timing

Harness: the guard's node program run in-process (scratchpad `pr7/diff/guard-vm.js`, `differential.js`,
`classify-d2a.js`), main (`1bec99e`) against head, on 188,496 synthetic Bash inputs (18 prefixes × 34 verbs ×
22 targets × 14 suffixes, aimed at canon/active/candidates, rm-, cp- and form-named files, chained promotes), 36,296
real inputs (every quoted command in `brain-hooks.test.js`, every fenced line and inline code span with a space in the
tracked Markdown, `evals/` and Hermes data excluded) and 30 Write/Edit/NotebookEdit paths.

| Corpus | Inputs | deny → deny | deny → allow | allow → deny | allow → allow |
|---|---|---|---|---|---|
| synthetic Bash | 188,496 | 74,779 | 7,268 | 39,187 | 67,262 |
| real (tests + tracked Markdown) | 36,306 | 196 | 10 | 171 | 35,929 |
| Write/Edit/NotebookEdit paths | 30 | 3 | 0 | 12 | 15 |
| **total** | **224,832** | **74,978** | **7,278** | **39,370** | **103,206** |

The harness was checked against the real hook (bash + node) on 300 inputs sampled from both flip sets: 0
mismatches (`vm-check.js`). Review L asked for the base guard against head over the test corpus, the adversarial
probes and the real-tree inputs: the test corpus and real tree are the "real" row; the 108 adversarial probes and 7
working-directory cases, run as the hook runs in a scratch project with the probe fixtures (`probe-diff.js`), give
deny → deny 25, **deny → allow 3** (`cat …/canon/rm-notes.md`, `grep rm …/canon/x.md`, `git add …/canon/rm-x.md`:
the G3 class), allow → deny 74, allow → allow 13.

**deny → allow is limited to the intended class.** Every one of the 7,278 flips is a read-only form whose old denial came
only from a mutation word standing as an argument or part of a file name: main allows each with the words `rm`, `cp`,
`mv`, `tee` replaced. 6,091 are the G3 class proper (an `rm` word); 1,187 are the same false positive with `cp`/`mv`/
`tee` in a file name (`cat .project-brain/canon/cp-notes.md`). This is wider than "rm only": the structural allowlist
(review A) cannot keep a verb list for readers without becoming a denylist again; reported as a deliberate deviation
from the roadmap's wording. 0 flips fall outside the class (no shell, `xargs`, substitution, interpreter or writing
redirect; every stage a reader). No Write path flips to allow.

**allow → deny** (stricter, 39,370 in all): chained promotes (G1), decisions/active protection, the folded/symlink/
glob/expansion rules, and conservative denials on non-commands from the real corpus (prose lines that name the capsule
next to a word that is not a reader).

**Timing (1 MB sweep, end to end):** `pr7/diff/timing-1mb.js`, 39 inputs of up to 1 MB (the P11 set scaled to 1 MB
plus every new code path: fold, ANSI-C, globs, braces, many `cd`, 100k+ distinct words, deep paths, `..`, slashes,
`=`/redirect splitting, dollars, `~user`, readers, Write paths of 2,040 segments and 1 MB), bash + node as the hook
runs. **Per-scan timeout: 15 s kill; pass bound 3 s.** 39 inputs × 3 runs at head: worst **1,224 ms**, none over 3 s, none killed (load average 1.5). The first run on `915e412` had two inputs at 3.1–3.3 s
(many `cd`, many deep words); `f92f87b` lowered the lookup budget and stops resolving at it. In the test suite the
512 KB loop (§6j) keeps its 3 s bound and gains 8 inputs for the new checks. In production the guard's own deadline is
20 s and the hook timeout 30 s; both block.

## Mutants

24 mutants on the final code (`mutants2.js`), each run against the test that pins it:

| Mutant | Result |
|---|---|
| M1/M2 wrapper `exit 2` → `exit 1` / `exit 0` (the roadmap's "a mutant reverting exit 2") | killed (node exits 1 must give status 2) |
| M3 deadline never kills; M4 `exec` dropped (the deadline kills a subshell, node keeps the pipe) | killed (runner timeout) |
| M5 truncation sentinel off | killed (§6i-g) |
| M6 G1 character check dropped; M7 G1 any script path | killed |
| M8 fold = identity; M9 canonical without symlinks; M10 hook input cwd ignored | killed |
| M11 ANSI-C not decoded (text pass) | survived alone; the per-stage word decoder catches the same input. Removing both decoders is killed by the fully hex-encoded case (§6i-k). Two independent detections, by design |
| M12 glob hits off; M13 parent folder never a hit; M14 expansions decidable | killed |
| M15 brain tool exemption with any `--target` | survived: equivalent for protection. A `--target` inside canon/ or decisions/active/ is a canon/active hit, which the exemption never covers (the review I fix); the target check only keeps brain tools from writing under other capsule folders. Kept as defence in depth |
| M16 logical reading of plain words dropped | survived: the logical reading of `cd` targets (kept) is what the K case needs; for other words it only adds denials (programs open paths physically). Kept as an over-approximation |
| M17 budget deny off; M18 Write active rule off | killed |
| M19 folded delete pass off | survived: every folded capsule spelling in the tests is also caught by the on-disk resolution (a word whose folded segments name the capsule) or by the parent-folder rule; the second pass is redundant defence. Kept |
| M20 HOME-unset `~` decidable; M21 reader form ignores redirects; M22 reader = never runs its arguments | killed |
| M23 launcher exits 0 when no guard found; M24 root `onFailure` "continue" | killed (registration test) |

Earlier, on `e8c673e`, 13 of 14 mutants were killed; the survivor (a backgrounded reader pipeline) became moot when
read-only forms stopped requiring a single foreground pipeline.

## Checks run (head 0da0112 + this record)

- `node scripts/run-all-tests.js` (alone): **47/47 suites passed** (was 46 at base; new suite
  `scripts/brain-guard-registration.test.js`).
- `node scripts/validate-skills.js`: exit 0. `node scripts/ci-scan-skills.js`: PASS, every finding accounted for by the
  reviewed baseline, no stale entries.
- `bash -n` (through node, see Not measured) on `hooks/brain/brain-security-guard.sh`, `scripts/brain/brain-self-install.sh`,
  `install.sh`, `uninstall.sh`: exit 0.
- `node scripts/security-doc-wrap.test.js`: pass (in the suite).
- `infra/hermes-agent/bin/` not touched, so `run-bin-tests.sh` was not required.
- Probe sets at head (`all-probes.js`, `bypass-probes.js`, `probe-diff.js`): see the review table.

## Owner actions

1. Remove the old local fail-open guard registration (above).
2. Deploy `brain-weekly-review` after merge: `cp -R skills/brain-weekly-review/. ~/.claude/skills/brain-weekly-review/`,
   then `node scripts/check-skill-deploy.js`.
3. The `$CLAUDE_PROJECT_DIR` probe from `infra/hermes-agent/` (above) — pending.
4. The Hermes box probe for review #12 (above) — pending.
5. Over the 14 days after merge: `grep -c 'failing open' .project-brain/reports/guard-failures.log` must not grow (the
   guard no longer writes it); any new "fails closed" line is a real failure to look at.
6. Record the superseding decision through capture → compile → `brain-promote --approve` (Reversal stated).
7. Re-run `bash scripts/brain/brain-self-install.sh` in any target project installed before this change (or
   `install.sh --with-second-brain`), and commit its `hooks/brain/` with the new `settings.json` entry.

## Not measured

- A live session with the new registration (the implementer's own session runs the main checkout's guard and local
  settings); the `onFailure` behaviour itself is documented (H1) and the script's exit codes are tested, but no
  Claude Code process was observed blocking on them here.
- The subdirectory and Hermes probes above.
- `bash -n` was run through `node` (`child_process.spawnSync('bash', ['-n', …])`): the worktree isolation layer refuses
  a direct `bash` call. Same check, different launcher.
- skill-eval of brain-weekly-review after the step change — P1-10 (B6).
