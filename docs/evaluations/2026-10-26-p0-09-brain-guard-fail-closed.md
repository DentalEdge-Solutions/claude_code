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
| `hooks/brain/brain-security-guard.sh` | **Fails closed**: node missing, crashing, killed, unable to start, or past `BRAIN_GUARD_DEADLINE_S` (default 20 s, under the 30 s hook timeout) → stderr reason, a `guard-failures.log` line ("fails closed"), **exit 2** (blocked). A program cut short (a stray apostrophe ends its bash single-quoted text) exits 3 → blocked. **G1:** the `brain-promote` exemption holds only for a raw command that is exactly one plain `node <script> … --approve …` call, `<script>` being `scripts/brain/brain-promote.js`, `./scripts/…` or the project's absolute path. **canon/ and decisions/active/ are an allowlist** (G3 is a consequence, **for read-only forms**: an `rm` word before a capsule path in a writer or brain-tool command is still denied by the kept main floor, as at base — review round 1, N1): a Bash command that reaches them passes only as that promote call or as a read-only form; Write/Edit/NotebookEdit into either is denied. **One canonical path form** for every check (kernel-order symlink resolution, Unicode/case folding). Delete rule: cwd-aware, symlink-aware, a second folded pass. Details under "The guard after the security reviews" |
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
| H11 | Break-glass | `--safe-mode`: "Start with all customizations disabled …: CLAUDE.md, skills, plugins, hooks, MCP servers …" (`claude --help` on 2.1.310 lists it; added 2.1.169). Settings files "reload … including edits to … `hooks`". Round 1: "pass `--settings '{"disableAllHooks": true}'`, which takes precedence over project and local settings" | cli-reference; settings; hooks › Disable or remove hooks |
| H12 | Monitor, PowerShell (round 1) | tools reference: "`Monitor` \| Runs a command in the background …"; "When Monitor runs a command, it uses the same permission rules as Bash"; "`PowerShell` \| Executes PowerShell commands natively"; availability: "Linux, macOS, and WSL: the tool is opt-in" (`CLAUDE_CODE_USE_POWERSHELL_TOOL=1`, "which requires `pwsh` on your `PATH`", env-vars); hooks "receive the tool's command string in `tool_input.command`" | tools-reference › Monitor tool, PowerShell tool; env-vars |

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
(guard reached, a canon write denied, `ls` allowed) and for an empty, a missing and a quoted/`$(…)` folder (exit 2).
**Correction (review round 1, N3):** a relative, quoted or `$(…)` value is walked up from the hook's working
directory, ending at `.`; the test runs those from a scratch folder without the guard, so they give exit 2 there, but
from the repository root they find and run the real guard (no substitution is executed). Claude Code sets an absolute
path, so this is harmless. The root registration's path is asserted to resolve in the checkout that holds the file (the shared-file
case: a session at the repository root or a worktree root, V2-RS-11).

**Owner probe (done 2026-10-27; result below).** From a terminal, at the repository root of a
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

**Result (owner, 2026-10-27, on the laptop, on a checkout with this change; the hook files are identical from
`592d0c2` through `c2a507a`):**

- **Coverage works.** The `ls` output was printed, and the debug log's `Hooks: PreToolUse:Bash [bash -c …
  brain-guard-launcher ${CLAUDE_PROJECT_DIR}]` line ends `finished with status 0`: the launcher walked up, found the
  guard and allowed the call. A fixed `${CLAUDE_PROJECT_DIR}/hooks/brain/…` path would have blocked every call there
  (inferred from the SessionEnd path below); option (c) holds.
- **What the variable names.** In a session started in `infra/hermes-agent/`, a shell-form hook sees the
  **subfolder**, not the repository root: a SessionEnd hook error printed
  `…/claude_code/infra/hermes-agent/hooks/brain/brain-session-end.sh`. The Bash tool's shell does not receive the
  variable (the model reported that the `echo` printed nothing). The launcher's own argument was not printed (the
  edit above was not made): the SessionEnd error shows the variable for a shell-form hook, and the launcher's status 0
  is consistent with either folder, so the exec-form value is inferred, not measured; option (c) covers both.
- **Side finding (pre-existing, not from this change).** The five other brain hook registrations in the owner's local
  settings (four scripts: `brain-load`, `brain-session-end` ×2, `brain-pre-compact`, `brain-post-lint`) use a fixed
  `$CLAUDE_PROJECT_DIR/hooks/brain/` path. Only the `brain-session-end` failure was observed ("No such file or
  directory"); the others are inferred from the same command form (`scripts/brain/brain-self-install.sh`, `H()`). In
  sessions started in `infra/hermes-agent/` they fail open: no brain load at start and no end-of-session compile.
  Nothing is blocked. Follow-up: resolve the repository root by walking up, both in the registration and in the
  scripts' `ROOT`, which also comes from `$CLAUDE_PROJECT_DIR`.

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
   low, pending the box probe. (Box probe 2026-10-27: bash and node present; the box does not yet have this change.
   See the Result below.)

**Owner box probe (security review #12):** inside the gateway container, `docker compose exec hermes-agent sh -c
'command -v bash node; node --version; ls -l /projects/claude_code/.claude/settings.json
/projects/claude_code/hooks/brain/brain-security-guard.sh'` — expected: both paths printed by `command -v`, node 26,
both files present. Then one scheduled proposer run: expected to finish with the same output shape, and no `hook error`
or `blocking because onFailure is "block"` text in its output. **Checklist / review #12 impact:** review #12 should note
that the root project settings now carry a fail-closed PreToolUse hook that loads in executor runs, and the Hermes
checklist should gain "bash and node on `PATH` in the gateway image" (not edited here: the checklist lives under
`infra/hermes-agent/bin/`, out of scope).

**Result (owner, 2026-10-27, on the box).** Run from `/opt/projects/claude_code/infra/hermes-agent` with `sudo docker
compose` (the box's `.env` is root `600`; from the home folder compose finds no configuration file):

- **The guard can start there.** Inside the container, `bash` is `/usr/bin/bash` and `node --version` prints `v26.5.1`
  (the container's `sh` printed only the first `command -v` argument, but `node` ran). The "bash not provable from the
  repository" risk in point 4 is resolved: once the box has this change, exec form can start the guard. The PATH of
  the proposer process itself was not measured.
- **The box does not have this change yet.** Its checkout is at `20a2e7c` (PR #125, merged 2026-10-14), 58 merged PRs
  (#126–#183) behind `main` at `c2a507a`, 8 of which changed 13 files under `infra/hermes-agent/`. Its guard file is
  the July version (3,263 bytes, last changed 2026-07-10 in `b167186`; Sep 21 is the checkout's file time; `main`'s
  guard is 62,139 bytes). Its root settings (969 bytes, the size of `.claude/settings.json` at `20a2e7c`, which
  registers only the telemetry hooks) carry no brain-guard registration and none of the P0-07 ask rules or HR1 deny
  rules, so executor runs on the box run no brain guard at all. The old shell-form registration only ever lived in a
  local, gitignored settings file; whether the box has one was not checked. The risk meanwhile is low: those runs are
  plan mode with Read, Grep and Glob, and the repository mount is read-only.
- **Deferred:** the box update is recommended (by the coordinator) through the Hermes checklist as part of security
  review #12, not ad hoc for this probe; the owner has not yet decided when. The probe's last step, one scheduled
  proposer run with no `hook error` or `blocking because onFailure is "block"` text, follows that update, and the
  checklist gains "bash and node on `PATH` in the gateway image".

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
repairs it, or bypasses the guard for one repair session with `claude --safe-mode`, `claude --settings
'{"disableAllHooks": true}'` (hooks reference, "Disable or remove hooks": "takes precedence over project and local
settings", read 2026-10-26), or by removing the guard's entry from `.claude/settings.json`, any old copy from
`.claude/settings.local.json` and, for that folder, `infra/hermes-agent/.claude/settings.json`, in an editor; then runs
`brain-hooks.test.js` and undoes the change. **Correction (review round 1, PR7-R-5):** the first version also offered
setting `onFailure` to `"continue"`; that does not unblock a broken node, because the script itself exits 2 and exit 2
blocks whatever `onFailure` says. It now says so. Claude Code must never edit the registration during a break-glass.

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

### Deliberate residuals (kept, with reasons; updated in review round 1)

1. An extractor whose input the guard cannot see: an archive extract (`tar -x`, `cpio -i`, `unzip`), `rsync` from a
   source, or a path-less `git checkout`/`restore`/`apply`, run with the working directory outside the capsule, at the
   capsule root or in `decisions/`: the archive, source or patch can hold `canon/…` or `decisions/active/…` members,
   and the command line names no protected path (round 2; widened in round 3, PR7-R-15; base allowed these too). Run
   from inside `canon/` or `decisions/active/`, it is denied (the working directory is protected). Follow-up
   candidate: treat an extractor in a non-reader stage as reaching the protected folders whenever the shell is
   inside the capsule. A command built at run time with **no** protected-looking text (`$(printf …)` producing both `canon` and the
   capsule name, a decoded string, a script an executor runs), and store-then-run across two calls (a message or
   log line written in one Bash call and run by `sh` in a later one) — static analysis cannot decide; blocking every
   expansion in every command would block ordinary work.
2. Path-less git commands that rewrite protected files (`git reset --hard`, `git stash pop`, `git apply`,
   `git checkout <branch>`), `git clean -fdX` (removes the gitignored `sessions/`) — they name no path; git history is
   the recovery. Programs git runs from its configuration (hooks, a `diff.*.textconv` or `diff.external`, filters,
   `core.fsmonitor`) when a reader such as `git log -p`, `git diff` or `git add` runs: setting them needs an earlier
   `git config` or `.gitattributes` write that names no protected path.
3. A hard link to a protected file made with a path built at run time (`ln "$(cat f)" x.md`) is not seen when it is
   made; a later Write, Edit or NotebookEdit through it is denied (PR7-R-11b). A Bash write through such a link is not.
4. A Bash write through a symlink resolved only at run time (a link created in the same command).
5. Moving or overwriting the capsule outside `canon/` and `decisions/active/` is not a "delete" (`cp -r` over it,
   `truncate`, `: >`) — the old G2 class, narrowed: parents of the protected folders are now covered. Deleting a
   folder above the capsule (`rm -rf ../<project>`, `cd .. && rm -rf <project>`, `rm -rf "$CLAUDE_PROJECT_DIR"`) and a
   program pattern with no protected-looking text (`find . -name '*.md' -delete`) name neither the capsule nor a
   protected folder (PR7-R-11c, R-8).
6. Conservative denials (no bypass): any command that reaches a protected folder and is not a read-only form or one
   plain brain call, e.g. `cat .project-brain/canon/x.md && npm test`; `awk`, `sort`, `less`, most `sed`,
   `python3 -c`, `node -e` reading a protected file; a reader with an option outside its allowlist; a loop
   `for f in <active>/*.md; do head "$f"; done`; `( cat <canon file> & )` (N4); a commit, PR or capture message that names a
   protected folder in a heredoc or substitution (round 2: pass it with `git commit -F`, `--body-file` or stdin); prose and fixture lines in the real corpus; `cd .project-brai? && make`. Every PowerShell
   call in a project with a capsule (deliberate, review M: PowerShell is not parsed; this project does not use it).
7. G4 of the P11 repair ("the reader exemption depends on knowing each reader's program-running options") is now
   mostly addressed: each reader passes only with options from its own allowlist, and git readers with a
   per-subcommand allowlist (review O, Q), so an unknown option ends the exemption. What remains: grep, egrep,
   fgrep, rg, test, `[`, true and false take any option (none of their options writes a file; rg `--pre` and
   `--hostname-bin` are caught as program-running), find is checked by its actions, and the delete rule's own reader
   exemption (`NON_EXEC`, kept from P11 as the floor's) still lists programs, not options. G5 stays as recorded (a
   capsule-leaving `cd` on a line with a group is not honored).
8. A reader is trusted by name: a program planted in a `PATH` folder (or `/usr/local/bin`, `/opt/homebrew/bin`) under a
   reader's name runs as that reader.
9. **The guard does not protect itself** (N6): a Write to `hooks/brain/brain-security-guard.sh`, or to the first
   folder the infra/hermes-agent launcher finds, replaces it for the next call. Follow-up: protect `hooks/brain/` and
   the guard's settings entries the same way as canon/.

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

**Correction (review round 1, PR7-R-7):** the "worst 1,224 ms" above did not hold: the reviewer's nested-brace glob
input (1 MB of `{`×2,040 `*N` `}`×2,040 words) took 4,458 ms at 1 MB, 9,021 ms at 2 MB and 18,044 ms at 4 MB on
`0da0112` (reproduced here), because `braces()` rescanned each `{`. "Every pattern is linear-time" was also not
true for it. After the fix it takes 629 ms at 1 MB, 1,369 ms at 2 MB and 2,673 ms at 4 MB. The figures at head are in
the round-1 section below.

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

## Review round 1 (independent review of `e4bf879`) and background reviews M–Q: author's answers

The reviewer closes findings; these are the author's answers, each with its red commit (kept) and the test that pins
it. Findings file: the session scratchpad's `pr7-review/PR7-REVIEW-FINDINGS.md`.

| ID | Answer | Code (head) | Red → fix | Test |
|---|---|---|---|---|
| PR7-R-1 | **Superseded in review round 2 (PR7-R-12): the exemption described in this row was removed; see the round-2 section.** Message text was data when bash passes it literally (single-quoted; double-quoted without `$` or backtick; `$(cat <<'X' … X)` with a quoted delimiter) as the value of `git commit -m/--message/-F/--file`, `gh pr create\|edit --title/-t/--body/-b/--body-file/-F` or `brain-capture.js --message/--title` — and only when every command of the call is git add/commit/push/status/log/diff/show, gh pr create/edit/view, brain-capture or `cd` (review P). Single-quoted text is no expansion and holds no comment, except where a comment or heredoc makes that reading differ from bash (review N). 600 real commit messages in heredoc form: denied **43 → 0** (commit) and **43 → 0** (PR body); base 1 | `hooks/brain/brain-security-guard.sh:283` (`blankData`), `:361`, `:376` (`sqNeutral`) | `e316604` → `19a21ea`; `d9bf0b0` → `722d247`; `e78b74b` → `570268d` | `brain-hooks.test.js:852` §6i-l, `:939`, `:1001` |
| PR7-R-2 | `sed -n '<a>[,<b>]p'` (single-quoted, numbers, `$` or `/re/`, plain file names, no option after) and a stage of plain **lowercase** literal assignments are readers; awk, sort -o, less, other sed, `python3 -c`, `node -e` stay off. `BRAIN_KERNEL.md` "guard denial" says what to use instead, including the `for … head` case | `guard.sh:741` (`SED_PRINT`), `:744` (`LITERAL_ASSIGN`) | `e316604` → `19a21ea`; lowercase: `d9bf0b0` → `722d247` | §6i-l; §6i (review N) |
| PR7-R-3 | Self-promotion refused by file identity: an existing destination with the same dev+ino as the source, or the same real path, exits 1 (a destination that cannot be compared counts as the same file). Case variants `decisions/ACTIVE/…` and `CANON/…` refused on this case-insensitive disk (the test skips with a reason on a case-sensitive one) | `scripts/brain/brain-promote.js:61` | `1f064d1` → `988c3f1` | `brain-promote.test.js:194` §11 |
| PR7-R-4 | Standalone `brain-self-install.sh <target>` copies `hooks/brain/` from the toolkit when the guard script is missing, and refuses (exit 3, both settings files unchanged) if it is still missing | `scripts/brain/brain-self-install.sh:49` | `b808bc0` → `03c217e` | `brain-self-install.test.js:81` §2b |
| PR7-R-5 | Break-glass rewritten: `claude --safe-mode`, `claude --settings '{"disableAllHooks": true}'` (hooks › Disable or remove hooks, read 2026-10-26), or removing the entries from `.claude/settings.json`, `.claude/settings.local.json` and the hermes file; the `onFailure: "continue"` advice removed (it does not unblock a broken node: the script exits 2) | `docs/SECOND_BRAIN_SECURITY.md` "Break-glass"; this record "Break-glass" | docs | — |
| PR7-R-6 | Tool names verified (tools reference, H12): `Monitor` and `PowerShell` added to the matcher in both settings files and in `brain-self-install.sh` (an older entry is widened in place). Monitor's `command` goes through the Bash rules; a WebSocket watch has none. PowerShell (review M): every call is denied in a project with a capsule — it cannot be parsed reliably; opt-in on macOS and Linux; deliberate limit, stated in `BRAIN_KERNEL.md` | `guard.sh:233`, `:244`; `.claude/settings.json:50`; `infra/hermes-agent/.claude/settings.json:50`; `brain-self-install.sh:144` | `e316604` → `19a21ea`; `d9bf0b0` → `722d247` | §6i-l `:914`; registration test; `brain-self-install.test.js:145` §6b |
| PR7-R-7 | Brace expansion: matching braces found in one pass; only groups with a top-level comma or `..` expand; at most 64 results and 200,000 characters of work, past which the word is unresolvable (counted only when the command looks protected). Nested-brace input: 4,458 → 629 ms at 1 MB, linear to 4 MB (2,673 ms). Added to the sweep and to §6j | `guard.sh:121` (`braces`), `:861` (`globHits`) | `e316604` → `19a21ea`; budget test `e78b74b` | §6j nested inputs; §6i-l (O/P) budget case |
| PR7-R-8 | In a stage that is not a reader, a glob or find pattern word (`-path`, `-name`, `-regex`, `-wholename`, `-lname`, and `-i…`) whose folded text looks protected reaches the protected folders and names the capsule for the delete rule. `find . -name '*.md' -delete` stays a stated residual (5) | `guard.sh:800` (`PROT_LOOK`), `:806`, `:912` | `e316604` → `19a21ea` | §6i-l |
| PR7-R-9 | The quarantined 512 KB loop asserts each input's expected decision on the kept run (deny for the 17 base deny inputs and the new writers, allow for the 3 reader forms and the 2 nested-brace inputs) | — | `e316604` | `brain-hooks.test.js:1080` |
| PR7-R-10 | Deny tests: `cat $(cp … canon/y)`, `` cat `cp … canon/y` ``, `` cp … `printf .project-bra`in/canon/y `` (the reviewer's R2 and R12 survivors) | — | `e316604` | §6i-l |
| PR7-R-11 | (a) a reader runs by bare name or from `/bin`, `/usr/bin`, `/usr/local/bin`, `/opt/homebrew/bin` (`./cat`, `sub/git` are not readers); (b) a Write/Edit/NotebookEdit target with nlink > 1 is compared by dev+ino with canon/ and decisions/active/ of the reachable capsules (5,000 entries; past that or on error, denied); `ln` making a hard link from a run-time path stays residual 3; (c) the reviewer's ancestor deletes, `git clean -fdX` and `find . -name '*.md' -delete` added to residuals 2 and 5 | `guard.sh:737`, `:207` | `e316604` → `19a21ea` | §6i-l `:1015` |
| N1 | Stated: G3 is closed for read-only forms; an `rm` word before a capsule path in a writer or brain-tool command is still denied by the main floor, as at base | record "What changed" | — | — |
| N3 | Launcher sentence corrected (relative/quoted values walk up from the hook's cwd) | record "Subdirectory coverage" | — | — |
| N4 | Fixed: a protected name ends at a path boundary, so `decisions/active.md` passes. `( cat <canon file> & )` stays a conservative denial (residual 6) | `guard.sh:870` | `e316604` → `19a21ea` | §6i-l |
| N6 | Listed as residual 9 with a follow-up | record residuals | — | — |
| N2, N5, N7 | Accepted, no change | — | — | — |

**Background reviews after round 1 (summaries only), each checked against head:**

| ID | Class | Finding at the commit reviewed | Resolution | Test |
|---|---|---|---|---|
| M | PowerShell denylist bypass (wildcard, concatenation) | confirmed on `19a21ea`: `Remove-Item -Recurse -Force .proj*`, `("." + "project-" + "brain")`, `-join` allowed | every PowerShell call denied where a capsule exists (`722d247`) | §6i-l `:914` |
| N | parser differential / protected-path bypass | confirmed, new in `19a21ea`: the single-quote reading for R-1 let an apostrophe in a comment or heredoc body hide a later `$(…)`/backtick; and the literal-assignment reader let `PATH=`, `IFS=`, `BASH_ENV=` change the next reader (10/10 allowed; `0da0112` denied the Bash ones) | fall back to the plain text when a comment or heredoc is present; lowercase assignments only (`722d247`) | `:1001` |
| M/N unnamed (2) | — | covered by the same probes (`mn-probes.js`); no further bypass found | — | — |
| O | allowlist semantic escape | confirmed on `722d247`: `git -p`/`--paginate`, `printf -v PATH`, unknown reader options; R-1 heredoc of a program other than `cat`, a delimiter followed by more commands, `--body-file <(…)` already denied | per-program option allowlists; git `-p` no reader (`570268d`) | `:939` |
| P | control regression / fail-open | confirmed: `git commit -m "rm -rf <capsule>" && git log -1 --format=%B \| sh` (and heredoc and `xargs sh -c` forms) allowed on `722d247`; base denied it. Every new round-1 branch checked for an exit-0-on-error path: none (malformed Monitor/PowerShell input is denied; the hard-link scan and the capsule check fail closed; `blankData` leaves the text unchanged on NUL) | blanking only when every command of the call is a message-safe one (`570268d`) | `:939` |
| Q | git reader options | on `570268d` the program-running forms (`git grep -O…`, `--open-files-in-pager`, `-c`, `--config-env`, `--exec-path`, `GIT_PAGER=`, `GIT_EXTERNAL_DIFF=`, `GIT_CONFIG_*`, `--ext-diff`, `--textconv`, `--output`) were already denied; unknown options (`git log --frobnicate`, `blame --contents`, `add --chmod`, `add -e`, `commit -S`) still counted as readers | per-subcommand option allowlists for git readers (`0544c08`) | `:975` |

**Regex-rule evidence at head (`0544c08`):**

- Differential base `1bec99e` vs head, in-process, harness checked against the real hook on 300 sampled inputs (0
  mismatches): 224,979 inputs — synthetic 188,496 (deny→deny 75,332, **deny→allow 6,715**, allow→deny 40,697,
  allow→allow 65,752), real 36,453 (212, **13**, 209, 36,019), file-tool paths 30 (3, 0, 12, 15). **deny→allow 6,728 in
  all:** 6,726 are read-only forms whose base denial came only from a mutation word used as an argument or file name
  (5,641 `rm`, 1,085 `cp`/`mv`/`tee`); the other **2 were the R-1 change, removed in round 2** (heredoc commit and PR bodies whose
  only command is git commit / gh pr edit). None falls outside these two classes. allow→deny 40,918.
- Probe differential (115 adversarial probes and working-directory cases, real hook, fixture project): deny→deny 25,
  **deny→allow 3** (`cat …/canon/rm-notes.md`, `grep rm …/canon/x.md`, `git add …/canon/rm-x.md`: G3), allow→deny 74,
  allow→allow 13.
- 1 MB sweep (52 inputs × 3 runs, the reviewer's nested-brace input and every round-1 path included: heredoc
  messages, heredoc openers, `-m` quotes, single quotes, sed print, assignments, find patterns, Monitor and
  PowerShell at 1 MB): worst **1,617 ms** (many deep words), none over 3 s, none killed at 15 s. Nested braces:
  629 ms (1 MB), 1,369 ms (2 MB), 2,673 ms (4 MB).
- Mutants on the round-1 code: 14 + 6 + 1 run; every one killed except the four of the first round judged
  equivalent (N7). R1d (heredoc of any program) and R7 (no brace budget) survived the first pass and are killed by
  tests added in `e78b74b`.
- All probe sets at head: batch 2 0 of 41 allowed, G/H 0 of 21 (10 of 10 allowed as intended), self-review 0 of 6,
  J/K denied, round 1 0 of 18 wrong, M/N 0 of 10 allowed, O/P 0 of 20 wrong, Q 0 of 35 wrong.

**Round 1 checks (head `0544c08` + docs):** `node scripts/run-all-tests.js` alone: 47/47 suites passed, no F1 retry
printed; `node scripts/validate-skills.js` exit 0; `node scripts/ci-scan-skills.js` PASS, no unmatched or stale
findings; `bash -n` (through node) on the guard, `brain-self-install.sh`, `install.sh`, `uninstall.sh` exit 0; the
record scans clean with `static-scan.js` (0 findings); 3,269 added lines on the branch hold no bidi, zero-width or
control characters; `security-doc-wrap.test.js` passes. Owner deploy is unchanged: `brain-weekly-review` only.

## Review round 2 (independent review of `b33c6d1`): author's answers

The reviewer closes findings. Base of this round: `b33c6d1`.

| ID | Answer | Code (head) | Red → fix | Test |
|---|---|---|---|---|
| PR7-R-12 (blocking) | Confirmed: the six inputs (comment form, comment inside `( … )`, ANSI-C `\'` form, canon overwrite, and the same through `gh pr create --title` and `brain-capture.js --title`) were allowed on `b33c6d1`. Per the coordinator's decision the literal-message exemption is **removed** (`blankData`, the message-safe command set with its `cd`/`gh pr view` additions, and the single-quote reading `sqNeutral`): message text gets the same checks as any other text, as at base, and every rule (the delete rule and the main floor included) reads the joined command. A commit or PR command that is denied gets a reason that says to write the message to a file outside `.project-brain` and use `git commit -F <file>` or `gh pr create\|edit --body-file <file>`; brain-capture has no file option (it takes `--message`, `--title`, `--type`, `--target`), so its reason says not to name the protected paths literally. `-F`/`--body-file` with a file outside the capsule passes; pointing them at a canon file is a read and passes too | `hooks/brain/brain-security-guard.sh:41` (`denyHint`), `:279-286` (`cmd = joined.text`, the hints) | `1c49feb` → `f2a4238` | `brain-hooks.test.js` `:1031` §6i-m |
| PR7-R-13 | `-c` ends the reader exemption only as a git global option (`gitSub`), so `grep -c` is a reader; `sed -n <num>[,<num>]p` is accepted unquoted as well as quoted | `guard.sh:342` (`EXEC_OPT`), `:636` (`SED_PRINT`) | `1c49feb` → `f2a4238` | §6i-l allow list |
| MultiEdit | The permissions page names "legacy `MultiEdit`" (not in the current tools reference), so the tool can exist in older versions: added to the matcher in both settings files and in `brain-self-install.sh` (which widens either earlier matcher in place), and checked like Edit | `guard.sh:194`; `.claude/settings.json:50`; `infra/hermes-agent/.claude/settings.json:50`; `brain-self-install.sh:145` | `1c49feb` → `f2a4238` | §6i-m; `brain-self-install.test.js` §6b |
| cpio | Already a non-reader: `cpio -id` inside canon is denied. From outside the capsule with no protected text it stays allowed: an archive extract (`cpio`, `tar`, `unzip`) whose archive holds capsule paths names none on the command line — added to residual 1 | — | — | §6i-m |
| Record | The record committed at `b33c6d1` was corrupted: inserting the round-1 section with `String.replace` read `$'` and `` $` `` in the inserted text as replacement patterns and pasted two copies of the document into the section (1,158 lines). Rebuilt from its parts (443 lines); no content was lost | — | — | — |

**Measured (head):**

- 600 real commit messages (`commit-replay2.js`): heredoc commit **46 denied**, heredoc PR body 46, `git commit -F <file>` **0**, `gh pr create --body-file <file>` **0** (base: 1, 1, 0, 0; round 1: 0; round 0: 43). Each denial of a commit or PR command carries the `-F`/`--body-file` guidance (§6i-m asserts it).
- Round-2 probes (`r2-probes.js`, 16): 0 wrong (was 12 on `b33c6d1`). Every earlier probe set unchanged, except the round-1 and O/P message allows, which are denials now by design.
- Differential base `1bec99e` vs head, 225,022 inputs: synthetic 188,496 (deny→deny 75,098, **deny→allow 6,949**, allow→deny 40,497, allow→allow 65,952), real 36,496 (221, **11**, 216, 36,048), file-tool paths 30 (3, 0, 12, 15). **deny→allow 6,960**, all read-only forms: 5,641 `rm`-named and 1,085 `cp`/`mv`/`tee`-named files read by readers, and 234 reads with the unquoted `sed -n <num>p` form (R-13). **No message-class flip** (0 commit, PR or capture commands among them). allow→deny 40,725. Harness checked against the real hook on 300 inputs: 0 mismatches.
- Probe differential (115 adversarial probes, real hook): deny→allow 3 (G3), allow→deny 74.
- 1 MB sweep: 52 inputs × 3 runs, worst **1,243 ms**, none over 3 s, none killed. Nested braces: 442 ms (1 MB), 877 ms (2 MB), 1,809 ms (4 MB).
- Mutants on the round-2 code: 5 of 5 killed (guidance text off, `-c` back for every reader, unquoted sed form off, unquoted sed with any script, MultiEdit not checked). A follow-up commit (`b361b3f` red → `0c60e59`) makes the brain-capture reason say that brain-capture reads the message from stdin when `--message` is absent (`brain-capture.js --type <type> < <file>`).

**Round 2 checks:** `node scripts/run-all-tests.js` alone: **47/47 suites passed**, no F1 retry printed; `node scripts/validate-skills.js` exit 0; `node scripts/ci-scan-skills.js` PASS, no unmatched or stale findings; `bash -n` (through node) on the guard, `brain-self-install.sh`, `install.sh`, `uninstall.sh` exit 0; `security-doc-wrap.test.js` passes; the hidden-character and static scans are in the report.

## Review round 3 (independent review of `1d6b3de`): author's answers

The reviewer approves; no blocking finding. No guard code changed in this round.

| ID | Answer | Red → fix | Test |
|---|---|---|---|
| PR7-R-14 | Deny tests for `git -ccore.pager=cat log`, `git -cdiff.external=cat diff` and `git --frobnicate log` on a canon file (path built at run time); they pass on the current code. In scratch copies (discarded afterwards): mutant T3 (unknown global option not treated as config) is **killed** by the `--frobnicate` case. Mutant T2 alone (attached `-cX` not matched as `-c`) **still passes**: every attached `-cX` is also an unknown global option, and that branch denies it, so T2 is equivalent while T3's branch stands. T2 and T3 together are **killed** by the `-ccore.pager` case | tests only, `1d03b76` | `brain-hooks.test.js` review Q block |
| PR7-R-15 | Coordinator decision: recorded, not code (base allowed these too). Residual 1 now covers any extractor whose input the guard cannot see (`tar -x`, `cpio -i`, `unzip`, `rsync`, a path-less `git checkout`/`restore`/`apply`) run outside the capsule, at its root or in `decisions/`; denied from inside `canon/` or `decisions/active/`; a follow-up candidate. Same text in `SECOND_BRAIN_SECURITY.md` | docs | — |
| Residual 7 | G4 is no longer dropped: it is mostly addressed by the per-program and per-git-subcommand option allowlists; what remains is listed | docs | — |

**Round 3 checks:** `node scripts/run-all-tests.js` alone: **47/47 suites passed**, no F1 retry printed; `security-doc-wrap.test.js` passes; the changed files (the test file, this record, `SECOND_BRAIN_SECURITY.md`) hold no bidi, zero-width or control characters in their added lines.

## Owner actions

1. Remove the old local fail-open guard registration (above) — done 2026-10-26 (`brain-self-install.sh` removed one
   old registration from the local settings).
2. Deploy `brain-weekly-review` after merge: `cp -R skills/brain-weekly-review/. ~/.claude/skills/brain-weekly-review/`,
   then `node scripts/check-skill-deploy.js` — done 2026-10-26 (all skills match).
3. The `$CLAUDE_PROJECT_DIR` probe from `infra/hermes-agent/` (above) — done 2026-10-27.
4. The Hermes box probe for review #12 (above) — partly done 2026-10-27: bash and node confirmed; the proposer run waits
   for the box update (recommended with security review #12; not yet scheduled).
5. Over the 14 days after merge: `grep -c 'failing open' .project-brain/reports/guard-failures.log` must not grow (the
   guard no longer writes it); any new "fails closed" line is a real failure to look at.
6. Record the superseding decision through capture → compile → `brain-promote --approve` (Reversal stated) — done
   2026-10-27 on the owner's verdict (PR #183); the 2026-10-21 decision's status is updated at the weekly review.
7. Re-run `bash scripts/brain/brain-self-install.sh` in any target project installed before this change (or
   `install.sh --with-second-brain`), and commit its `hooks/brain/` with the new `settings.json` entry.

## Not measured

- `onFailure: "block"` in a live session: documented (H1) and the script's exit codes are tested, but no Claude Code
  process has been observed blocking because the guard itself failed. Observed since merge (2026-10-26/27): the guard
  denied several commands in the coordinator's live session (reported by the coordinator, not logged here; a promote
  with a chained `echo`, loops building brain paths from a variable, a redirect next to a canon read, a heredoc append
  naming an active decision), all after the owner removed the old local registration on 2026-10-26, so the committed
  registration ran them; and the launcher registration ran in the owner's subfolder probe (status 0, in the debug log).
- The box's proposer run with the new guard (Check B's last step): waits for the box update (recommended with security
  review #12; not yet scheduled).
- `bash -n` was run through `node` (`child_process.spawnSync('bash', ['-n', …])`): the worktree isolation layer refuses
  a direct `bash` call. Same check, different launcher.
- skill-eval of brain-weekly-review after the step change — P1-10 (B6).
