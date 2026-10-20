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
2. **Skill gate** — the `brain-promote` skill carries `disable-model-invocation: true`,
   so the platform itself prevents model-initiated promotion, and `risk_tier: critical`.
3. **Hook gate** — `brain-security-guard.sh` (the only blocking hook) denies:
   - direct `Write`/`Edit`/`NotebookEdit` into `.project-brain/canon/` (path-normalized;
     NotebookEdit's `notebook_path` is checked too)
   - `Bash` mutations of `canon/` not going through `brain-promote --approve`
     (covers `cd`+relative paths and interpreter writes)
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
       the command (a leading `time` is fine), optionally `-C <dir>`, then `clean`, then only `-[dfnqxX]…`, `--dry-run`,
       `--quiet`, `--force` and plain paths, with an `n` before any `--`, and no quote,
       escape, variable, glob, redirect, comment or `=` in the stage. So `git clean -nd -- <path>`
       passes, while `git clean -n -e foo …`, `env git clean -n …` or
       `git clean -n … 2>/dev/null` are conservatively denied. So is any `git -c …` stage
       containing the word `clean` (`git -c color.ui=never log --grep clean …`): a `-c`
       value can run a program, so the guard does not try to tell them apart.
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
   - direct installs (`cp`/`mv`/`ln`/`rsync`) from `reference-repositories/sources/` into the skills dir

   **When the guard itself fails** (owner decision P11, 2026-10-15):
   - **Bad input fails closed.** Empty input, input that is not JSON, or JSON without a
     `tool_name` string and a `tool_input` object is denied with a reason. Claude Code always
     sends valid input, so this never blocks normal work; it points at a broken hook setup.
   - **node missing or crashing fails open, visibly.** The guard prints a warning to stderr,
     appends a line to `.project-brain/reports/guard-failures.log` (time and exit code only,
     never the command), and exits 1. Claude Code shows exit 1 as a non-blocking hook error
     and lets the call proceed. Denying here would block every Write, Edit and Bash call,
     including the fix. Exit 0 would hide the warning: Claude Code ignores stderr on exit 0
     ([hooks reference](https://code.claude.com/docs/en/hooks), checked 2026-10-15).
   - The hook input reaches node on stdin, not through an environment variable: a large
     Write used to exceed the exec size limit and slip through unchecked.
   - Every pattern is linear-time and tested on 512 KB to 1 MB commands. A PreToolUse hook
     that times out (default 600 s) does not block the call, so a slow regex would be a
     bypass. The 2026-10-16 re-review found one the P11 sweep missed (the `git clean`
     dry-run check, reached only after a `clean` subcommand): a timing input must actually
     reach the pattern it targets.
   - `brain-self-install.sh` registers the guard with `"timeout": 30` (triage F1, owner
     decision 2026-10-20). A stalled guard then costs each call 30 s instead of 10 minutes.
     It still fails open after those 30 s: the timeout bounds the delay, it does not close
     the gap. A normal check takes about 0.07 s on a 1 MB command and stayed under 1 s
     under heavy CPU load. Re-running the installer adds the timeout to an older install,
     and keeps a timeout the owner already set. `"onFailure": "block"` would make a
     timeout deny the call, but it also blocks on a node failure, against P11; it was
     considered and not adopted ([hooks reference](https://code.claude.com/docs/en/hooks),
     checked 2026-10-19 on Claude Code 2.1.302).

   The guard is **defense-in-depth**: `brain-promote --approve` + git history are the
   real boundary. It errs toward denial — a read command mentioning `canon/` alongside a
   redirect/`node -e` can be a conservative false-positive. So can any program not on the
   reader list that carries the word `rm` next to a capsule path (`xargs grep rm …`,
   `sh -c "grep unlink …"`, `git rm --cached …`); split such commands. Known limits: it does
   not follow shell variables (`D=.project-brain; rm -rf "$D"`), commands built at run time
   (`$(printf …)`, a decoded string, a script an executor runs), loops over a capsule glob
   (`for f in .project-brain/*; do rm "$f"; done`), or globs that could expand to the
   capsule (`rm -rf .p*`). It does not treat moving or overwriting as deleting (`mv` of the
   capsule, `rsync --delete`, `cp -r` over it, `truncate`, `: >`). Code that deletes through
   an API the guard doesn't name also gets through.

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
