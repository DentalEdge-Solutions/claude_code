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
       `find … -delete`; `git rm`; `git clean` (but not a `-n` dry run); `fs.rmSync`,
       `unlinkSync`, `rmdirSync`, `shutil.rmtree`, `rimraf`.
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
       so `cd ..` or `cd /tmp` back out of the capsule ends that state.
     - **Splitting follows the shell:** only `;`, `&`, `&&`, `||`, `|` and newlines outside
       quotes separate commands. A leading redirection (`>/dev/null rm …`) is skipped when
       finding the command word.
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
     that times out does not block the call, so a slow regex would be a bypass.

   The guard is **defense-in-depth**: `brain-promote --approve` + git history are the
   real boundary. It errs toward denial — a read command mentioning `canon/` alongside a
   redirect/`node -e` can be a conservative false-positive. So can any program not on the
   reader list that carries the word `rm` next to a capsule path (`xargs grep rm …`,
   `sh -c "grep unlink …"`, `git rm --cached …`); split such commands. Known limits: it does
   not follow shell variables (`D=.project-brain; rm -rf "$D"`), loops over a capsule glob
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
