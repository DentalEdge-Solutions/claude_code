# Second Brain — Security Model

The brain is governed memory. Two properties are load-bearing: **secrets never
enter memory**, and **canon changes only through explicit human approval**. This
document maps the threats to the controls that enforce them.

## Sensitive content — never stored

`brain-lib.js` `scanSensitive()` scans all captured or promoted content against the
repo's one shared secret-pattern list, `scripts/telemetry/secret-patterns.js`. The
same list drives telemetry redaction (`redact.js`). A match refuses the write (exit 3).
The patterns are:

- `anthropic-api-key` — `sk-ant-…` (api, admin and other key types)
- `openai-style-key` — `sk-…` (20+ chars)
- `github-token` — `ghp_/gho_/ghu_/ghs_/ghr_…`
- `github-fine-grained-pat` — `github_pat_…`
- `slack-token` — `xoxb-/xoxa-/xoxp-/xoxr-/xoxs-…`
- `aws-access-key-id` — `AKIA…`
- `google-api-key` — `AIza…`
- `private-key` — `-----BEGIN … PRIVATE KEY-----` (a header alone, or the whole block)
- `jwt` — three base64url segments starting `eyJ`
- `bearer-token` — `Bearer <15+ chars>`
- `secret-assignment` — `api_key/secret/token/password = <12+ chars>`
- `password-assignment` — `password = <4+ chars>`

Tests: `scripts/telemetry/secret-patterns.test.js`. It checks each format against both
consumers, checks benign prose against the brain gate, and checks that both use the
single list.

Enforced at three points: `brain-capture` (before append), `brain-promote` (before
promotion), and `brain-lint` (sweep of the whole capsule, second net). The
`brain-post-lint.sh` hook surfaces any leak that lands via a raw edit.

## Sensitive paths — never read into the brain

`brain-profile.json` `sensitive_paths` (default): `.env`, `.env.*`, `secrets/`,
`credentials/`, `private/`, `legal-sensitive/`, `client-sensitive/`, `patient/`,
`financial/`. Client/patient/financial/legal data must never enter the capsule.

## Canon protection chain (defense in depth)

1. **Script gate** — `brain-promote.js` is the *only* writer to `canon/` and
   `decisions/active/`; without `--approve` it exits 2 and writes nothing. Its
   positional path is normalized and confined to the capsule (no `../` traversal).
   `--to superseded` moves a file from `decisions/active/` to `decisions/superseded/` (the weekly
   review's route, P0-09); a source equal to its destination is refused.
2. **Skill gate** — the `brain-promote` skill carries `disable-model-invocation: true`,
   so the platform itself prevents model-initiated promotion, and `risk_tier: critical`.
3. **Hook gate** — `brain-security-guard.sh` (the only blocking hook) denies:
   - direct `Write`/`Edit`/`NotebookEdit` into `.project-brain/canon/` or
     `.project-brain/decisions/active/` (NotebookEdit's `notebook_path` is checked too). Every
     path check uses one canonical form: segments walked as the kernel does (each existing prefix
     replaced by its real path, so a symlink is resolved before `..`), names folded (NFKD,
     combining marks dropped, upper- then lowercased: `.PROJECT-BRAIN`, fullwidth letters, the
     long s and dotted or dotless i all match, as on a case-insensitive APFS disk or more)
   - **canon/ and decisions/active/ — an allowlist, not a list of write verbs (P0-09).** A `Bash`
     command that reaches them passes only as exactly one plain `brain-promote.js … --approve`
     call (`node scripts/brain/brain-promote.js`, `./scripts/…` or the project's absolute path;
     no separator, redirect, substitution, quote, escape, glob, assignment, comment or control
     character: nothing can be chained to it) or as a **read-only form**: every stage of every
     pipeline is a pure reader (`grep`, `cat`, `ls`, `head`, `wc`, `stat`, `diff`, `jq`, `echo`,
     `find` without `-exec`/`-delete`/`-fprint`/`-fls`, `git status/log/diff/show/grep/blame/
     ls-files/ls-tree/rev-parse/add/commit` …, no `--output`; run by bare name or from `/bin`,
     `/usr/bin`, `/usr/local/bin`, `/opt/homebrew/bin`, never `./cat`), or `sed -n <a>[,<b>]p`
     (`'<a>[,<b>]p'` single-quoted with line numbers, `$` or `/re/`, or unquoted with line
     numbers, then plain file names), or a stage of plain lowercase assignments (`x=1;`), with no
     `$(…)`, backticks, heredoc, comment or writing redirect. Each reader passes only with options
     from its allowlist (an unknown option makes it no reader; `printf` takes none, `git -p` is
     no reader; `-c` ends the exemption only as a git global option). Commit, PR and capture
     messages get the same checks as any other text: a message that names a protected folder in
     a heredoc or a substitution is denied, and the reason says to write it to a file outside the
     capsule and use `git commit -F <file>` or `gh pr create|edit --body-file <file>` (review
     round 2 removed a literal-message exemption that read comments and ANSI-C quoting differently
     from bash). A command reaches them:
     - by name in its text, with ANSI-C `$'…'` escapes decoded, quotes and backslashes dropped,
       folded, `//` and `/./` collapsed; or the word `canon`/`active` in a command that also names
       the capsule or runs inside it;
     - on disk: any word (split also at `=`, `<`, `>`) resolved from every folder the shell may be
       in at that point (the hook input's `cwd` plus each `cd`/`pushd` target, physically and
       logically), symlinks and `~` included;
     - through a parent (the capsule folder or `decisions/`) given to a stage that is not a
       reader (`mv`, `chmod -R`, `rsync --delete` of it);
     - through a glob or brace word (`.project-brai?`, `.pro*/can*`, `.project-{brain,x}`)
       that may match one of them, a parent or a file below; and, in a stage that is not a
       reader, a pattern a program matches itself (`find -path '*canon*'`, `-name`, `-regex` …)
       whose text looks protected;
     - through an expansion the guard cannot follow (a variable, `$(…)`, backticks, `~user`,
       a `cd` it cannot follow) in a command that shows a protected-looking name or runs in the
       capsule: static analysis cannot decide, so it fails closed.
     The brain tools that never write these folders (`brain-verify`, `-lint`, `-search`,
     `-context-pack`, `-compile`, `-capture`) pass as one plain call when they name, at most, the
     capsule folder itself as `--target`. Over 5,000 words or 20,000 disk lookups, a command
     passes only in a read-only form. The guard also runs on `Monitor`, whose command goes
     through these rules, and on `PowerShell`, which it cannot parse: in a project with a capsule
     every PowerShell call is denied (the tool is opt-in on macOS and Linux); and on legacy
     `MultiEdit`, checked like Edit. A Write, Edit, MultiEdit or
     NotebookEdit target with more than one hard link is compared by device and inode with the
     files of canon/ and decisions/active/ (at most 5,000 entries; past that or on error,
     denied). The weekly review stages a changed decision as a candidate
     and applies it with `brain-promote.js … --to active --force`; a superseded one with
     `--to superseded`.
   - deleting the capsule, when the capsule is the target:
     - **What counts as a delete:** any `rm`, `rmdir`, `unlink` or `shred` word, whatever runs
       it (`sudo`, `busybox`, `ssh`, `xargs`, `bash -c`, a here-string, a git alias, `… | sh`).
       That includes one glued to a short option, read as the shell joins quotes (`-Orm`,
       `-O"r"m`);
       `find … -delete`; `git rm`; `git clean`, also behind a wrapper that runs it (`env`,
       `command`, `nice`, `sudo`, `xargs`), nested in a git executor
       (`git rebase -x "git clean …"`), or through `-c` (an alias, or a program such as
       `core.editor`); a git subcommand spelled with `$`, a glob or a backtick
       (`git $'cl\x65an'`); `fs.rmSync`, `unlinkSync`, `rmdirSync`, `shutil.rmtree`, `rimraf`.
     - **A `git clean` dry run** is allowed only in a plain form, not by parsing git's options
       (that was bypassed with quoting, `-e` values, `--` and `--end-of-options`): `git` as
       the command (a leading `time` is fine), optionally `-C <dir>`, then `clean`, then
       only `-[dfnqxX]…`, `--dry-run`, `--quiet`, `--force` and plain paths, with an `n`
       before any `--`, and no quote, escape, variable, glob, redirect, comment or `=` in
       the stage. So `git clean -nd -- <path>` passes, while `git clean -n -e foo …`,
       `env git clean -n …` or `git clean -n … 2>/dev/null` are conservatively denied. So
       is any `git -c …` stage containing the word `clean`
       (`git -c color.ui=never log --grep clean …`): a `-c` value can run a program, so
       the guard does not try to tell them apart.
     - **The git subcommand** is found from shell-split words after skipping git's global
       options together with the value of those that take one (`-C`, `-c`, `--git-dir`,
       `--work-tree`, `--namespace`, `--config-env`, `--attr-source`, `--shallow-file`; git
       2.54), so in `git --namespace "x log" rebase -x …` the subcommand is `rebase`. The
       words are read from the command word itself, never from an earlier `2>./git` or
       `A=./git`. An
       unrecognized global option, or a variable, glob or backtick before the subcommand,
       ends the reader exemption.
     - **The one exemption:** a pipeline stage whose command never runs its arguments:
       `grep`, `cat`, `ls`, `echo`, `head`, `wc`, `find` without `-exec`, `git add` /
       `commit` / `log` / `diff` / `show` / `grep` and similar readers. Pagers (`less`, `more`,
       `ag`/`ack`), `sort` and network git (`fetch`, `push`, `pull`) are not readers. The
       exemption holds only when all of these are true:
       - the stage has no `VAR=value` prefix (`PAGER=`, `GIT_EXTERNAL_DIFF=`);
       - it has no option that runs a program (`rg --pre` / `--hostname-bin`, `git grep -O` /
         `--open-files-in-pager` (also shortened), git `-c`, `--ext-diff` …);
       - it has no `$(…)`, backticks or `<(…)`;
       - it pipes only into other readers.

       So
       `grep rm .project-brain/…` and `git add …-rm-rf-….md` pass, but `echo rm … | sh` doesn't.
     - **When the capsule is the target:** `.project-brain` is named in the same pipeline,
       including inside `"${CLAUDE_PROJECT_DIR}/…"`, `$(pwd)/…` or `{…,…}`. Or the shell is
       inside the capsule after a `cd`/`pushd`. The guard tracks `cd`, `pushd` and `popd`,
       **direction-aware and fail-closed:** a move that *enters or stays in* the capsule is
       always recorded (erring toward a deny is safe), while a move that *leaves* the capsule
       is recorded only from a plain standalone foreground command — one stage, not in the
       background, and with **no grouping construct anywhere on the line**: no `( )`, no `{ }`,
       and no `case`. Rather than parse group nesting (which proved fragile and was repeatedly
       bypassed), the guard treats the presence of any of those as enough to withhold the
       leave, because a `cd` can run in a subshell, or in a brace group that is itself
       piped/backgrounded, without moving the parent shell. So a `cd` hidden in a group can
       never make a later relative delete look safe. The cost is a conservative deny of some
       exotic "leave the capsule on a line that also contains a group" forms (e.g.
       `cd .project-brain; { cd /tmp; }; rm -rf decisions`, which in a real shell targets
       `/tmp`, or `cd .project-brain; (ls); cd /tmp; rm -rf build`). A normal `cd ..` or
       `cd /tmp` on its own still ends the inside-capsule state.
     - **Splitting follows the shell:** only `;`, `&`, `&&`, `||`, `|` and newlines outside
       quotes separate commands. A leading redirection (`>/dev/null rm …`) is skipped when
       finding the command word. Line continuations are joined first, as bash does, so
       `r\⏎m` is `rm` for every rule, the floor included. Quotes are tracked as bash does:
       the pair is kept inside single quotes and inside a `#` comment (where the newline still
       ends the comment). A kept pair in a command that names the capsule is **denied
       outright**, because where the guard reads quotes differently from bash (a heredoc body,
       `$'\''`) it cannot know how the shell splits the command. Put such commands on one line.
     - **Superset-of-`main` floor:** the stage analysis above is parser-dependent, so as a
       floor the guard also keeps `main`'s blunt rule — any `rm` word followed by
       `.project-brain` within one `;`/`|`/`&`-free segment is a delete. This floor runs on the
       raw command and so cannot be fooled by a parser desync (a quote inside a `#` comment,
       ANSI-C `$'…'` quoting, a heredoc body). It never allows a capsule delete that `main`
       blocks. Its one exemption is a single foreground pipeline whose every stage is a pure
       reader, with no command or process substitution, none of those desyncing constructs,
       no background, and no file-writing redirect — there an `rm` can only be a literal
       argument (`grep rm .project-brain/log.md`), so it stays allowed, while store-then-run
       forms (`echo rm -rf .project-brain > x.sh && sh x.sh`) stay denied.
   - direct installs (`cp`/`mv`/`ln`/`rsync`) from `reference-repositories/sources/` into the
     skills dir

   **When the guard itself fails — it fails closed** (P0-09, 2026-10-26; this supersedes the
   P11 fail-open policy of 2026-10-15 and the F1 non-adoption of `onFailure: "block"`):
   - **Bad input fails closed.** Empty input, input that is not JSON, or JSON without a
     `tool_name` string and a `tool_input` object is denied with a reason. Claude Code always
     sends valid input, so this never blocks normal work; it points at a broken hook setup.
   - **node missing, crashing, killed or too slow fails closed.** The guard prints the reason to
     stderr, appends a line to `.project-brain/reports/guard-failures.log` (time, exit code and
     "fails closed" only, never the command), and exits 2: Claude Code blocks the call and shows
     the reason to Claude. The guard stops node at `BRAIN_GUARD_DEADLINE_S` (default 20 s, under
     the 30 s hook timeout), so a stall blocks even under a registration without `onFailure`.
     A program that ends early (a stray apostrophe can end its bash single-quoted text) exits 3
     and is blocked the same way.
   - **The registration sets `"onFailure": "block"` and `"timeout": 30`** (Claude Code
     2.1.295 or later), so a guard that cannot start, exits with another code or reaches the
     hook timeout blocks the call ([hooks reference](https://code.claude.com/docs/en/hooks),
     "Block the action when a hook fails", read 2026-10-26 on Claude Code 2.1.310). It is
     committed in `.claude/settings.json` in exec form (`bash` with the script path as its
     argument). `brain-self-install.sh` writes the same registration into a target's
     `.claude/settings.json` and removes the old shell-form, fail-open copy from its
     `.claude/settings.local.json`; commit `hooks/brain/` with it, since a registration whose
     script is missing blocks every Write, Edit and Bash call. Telemetry hooks stay fail-open.
   - Sessions started in `infra/hermes-agent/` read `infra/hermes-agent/.claude/settings.json`
     instead: it runs the guard from the first folder at or above `$CLAUDE_PROJECT_DIR` that
     holds `hooks/brain/brain-security-guard.sh`, and blocks (exit 2) when none does.
   - The guard keeps no state between calls: every decision comes from the hook input and the
     filesystem at that moment.
   - The hook input reaches node on stdin, not through an environment variable: a large
     Write used to exceed the exec size limit and slip through unchecked.
   - Each check is linear in the command length or bounded by a stated budget (brace expansion
     64 results and 200,000 characters per word; 5,000 word resolutions; 20,000 disk lookups;
     5,000 entries for the hard-link scan). The P0-09 sweep runs 52 inputs of up to 1 MB end to
     end, the reviewer's nested-brace input included: worst 1,617 ms, with a 15 s kill per
     scan; the nested-brace input grows linearly (about 0.65 s per MB, 2.6 s at 4 MB).

   **Break-glass: when node or the guard is broken** (every Write, Edit and Bash call is
   blocked, the fix included). The owner, outside Claude Code:
   1. Read the reason Claude Code shows (or `.project-brain/reports/guard-failures.log`), and
      check node in a terminal: `node --version`.
   2. If node itself is broken, fix or reinstall node in the terminal; nothing else is needed.
   3. If the guard must be bypassed for a repair, start one session with hooks off:
      `claude --safe-mode` ("hooks … do not load", code.claude.com/docs/en/cli-reference), or
      `claude --settings '{"disableAllHooks": true}'` ("To turn hooks off for one run whatever
      the project's settings say, pass `--settings '{"disableAllHooks": true}'`, which takes
      precedence over project and local settings", code.claude.com/docs/en/hooks, "Disable or
      remove hooks"; both read 2026-10-26). Or, in an editor outside Claude Code, remove the
      guard's `PreToolUse` entry from `.claude/settings.json`, any old copy from
      `.claude/settings.local.json`, and, for sessions started there,
      `infra/hermes-agent/.claude/settings.json`. Setting `"onFailure": "continue"` does not
      help: the script itself exits 2 when node fails, and exit 2 blocks whatever `onFailure`
      says; it helps only if `bash` cannot start or the hook times out.
   4. Repair, run `node scripts/brain/brain-hooks.test.js`, then undo step 3 (`git diff
      .claude/settings.json` must show nothing) and start a normal session.
   Never let Claude Code edit the registration during a break-glass: an agent that can turn
   the guard off is the risk the guard exists for.

   The guard is **defense-in-depth**: `brain-promote --approve` + git history are the
   real boundary. It errs toward denial — a read command mentioning `canon/` alongside a
   redirect/`node -e` is denied (split it), and so is any program not on the reader list that
   reaches a protected folder (`awk`, `sort`, `less`, `python3 -c`, `node -e`, most `sed`) or
   carries the word `rm` next to a capsule path (`xargs grep rm …`, `git rm --cached …`). Known
   limits:
   - an extractor whose input the guard cannot see (`tar -x`, `cpio -i`, `unzip`, `rsync`, a
     path-less `git checkout`/`restore`/`apply`) run outside the capsule, at its root or in
     `decisions/`: its archive, source or patch can hold canon/ or decisions/active/ members
     (denied when run from inside canon/ or decisions/active/; a follow-up candidate);
   - commands built at run time without any protected-looking text (a decoded string, a
     script an executor runs); loops whose body holds the only capsule reference after a
     variable; code that writes or deletes through an API the guard does not name;
   - a path-less git command that rewrites protected files (`git reset --hard`, `git stash
     pop`, `git apply`, `git checkout <branch>`), and `git clean -fdX` (it removes the
     gitignored `sessions/`);
   - a hard link to a protected file made with a path built at run time (`ln "$(cat f)"
     x.md`) is not seen when made; a later Write or Edit through it is denied;
   - deleting a folder above the capsule (`rm -rf ../<project>`, `cd .. && rm -rf <project>`,
     `rm -rf "$CLAUDE_PROJECT_DIR"`) and a program pattern with no protected-looking text
     (`find . -name '*.md' -delete`): they name neither the capsule nor a protected folder;
   - a reader found on `PATH` is trusted: a program planted in a `PATH` folder under a
     reader's name runs as that reader;
   - **the guard does not protect itself**: a Write to `hooks/brain/brain-security-guard.sh`
     (or to the first folder the infra/hermes-agent launcher finds) replaces it for the next
     call (follow-up: protect `hooks/brain/` and the settings files the same way);
   - for deletes outside canon/ and decisions/active/, moving or overwriting is still not
     deleting (`cp -r` over the capsule, `truncate`, `: >`).

## Reference sources — documentation only

`reference-repositories/sources/<name>/` holds source cards, never executables.
`brain-reference-repo-audit.js` exits 3 if any `.sh/.js/.py/.rb/.ps1` appears there,
if a card carries sensitive content, or if `install_policy` is not
`do-not-install-directly`. Skill/agent adoption always routes through
scout → audit → adapt → eval.

## Uninstall preserves memory

`uninstall.sh` removes brain tooling (hooks, scripts, schemas, templates, hook
registrations, the CLAUDE.md marker) but **never deletes `.project-brain/`** — it
prints a preservation note. Uninstalling tooling must not erase the team's memory.

## Incident playbook — leaked secret in the capsule

1. `brain-lint.js` exit 3 flags it (or the post-lint hook warns).
2. Locate it via the report in `.project-brain/reports/lint/<date>.md`.
3. Redact the secret from the offending file; re-run `brain-lint.js` (expect exit 0).
4. **Rotate the credential** — it may already be in git history.
5. Check `git log -p` for the file; if the secret was committed, scrub history
   (e.g. `git filter-repo`) and force-rotate. `sessions/` is git-ignored by default,
   which limits but does not eliminate exposure.
