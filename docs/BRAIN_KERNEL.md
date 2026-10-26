# Brain Kernel — Operator Reference

Every script, hook, and skill in the Second Brain. All scripts are Node ≥ 18,
CommonJS, zero-dependency, deterministic, offline.

## Exit-code convention

| Code | Meaning |
|---|---|
| 0 | ok (including "nothing to do" on fail-open tasks) |
| 1 | usage / structure / overwrite-or-duplicate refusal |
| 2 | missing `--approve` (brain-promote only) |
| 3 | sensitive-content or security refusal |

## Scripts (`scripts/brain/`)

| Script | Usage | Notes |
|---|---|---|
| `brain-verify.js` | `--target <dir>` | structural integrity; exit 1 on any violation |
| `brain-capture.js` | `--message "…" [--type note\|decision\|lesson] [--title "…"] [--target <dir>]` | append-only to `sessions/daily/YYYY-MM-DD.md`; exit 3 on sensitive content |
| `brain-compile.js` | `[--date YYYY-MM-DD \| --all] [--force] [--target <dir>]` | extracts `[decision]`/`[lesson]` entries → candidates; skips entries already promoted (same file name in active/canon), even with `--force`; **never** writes active/canon |
| `brain-lint.js` | `[--target <dir>]` | frontmatter/staleness/orphan warnings (exit 0); sensitive content → exit 3. Stale = not `superseded` or `retired`, and neither `timestamp` nor `reviewed_at` within 90 days |
| `brain-promote.js` | `<capsule-rel-file> --approve [--to active\|canon\|superseded] [--force] [--target <dir>]` | the ONLY writer to `canon/` and `decisions/active/`; exit 2 without `--approve`; `--to superseded` moves a `decisions/active/` file to `decisions/superseded/`; a self-promotion exits 1 |
| `brain-search.js` | `--query "…" [--limit N] [--json] [--dir sub] [--target <dir>]` | authority × keyword × recency ranking; exports `search()` |
| `brain-context-pack.js` | `--intent "…" [--per-bucket N] [--target <dir>]` | §7.3 context object; fail-open on missing profile |
| `brain-self-install.sh` | `[target-dir]` | capsule + hook merge + `.gitignore` + verify; idempotent. The security guard goes into `.claude/settings.json` (exec form, `timeout` 30, `onFailure` block) and its old shell-form copy leaves `.claude/settings.local.json`; the five other hooks stay in `settings.local.json`. Stops, changing neither file, on a settings file it cannot read (invalid JSON, a byte-order mark, not an object, `hooks` or one of its event lists of the wrong type); an empty file counts as `{}`; a file is written only if it changed |
| `reference-lib.js` | (library) | registry load/save/render |
| `brain-reference-repo-{add,audit,map,refresh}.js` | see `REFERENCE_REPOSITORY_LIBRARY.md` | registry management; audit exit 3 on executables/secrets |
| `secondbrainbench-{generate,run,report}.js`, `bench-brain-kernel-adapter.js` | `run.js --adapter brain-kernel --mode smoke\|standard --workspace <dir>` | sealed-answer benchmark; exit 1 if any gate fails |

Frontmatter schema (required set): `type, title, description, tags, timestamp, sources`.

## Hooks (`hooks/brain/`) — resolve capsule via `$CLAUDE_PROJECT_DIR`; no capsule ⇒ silent no-op

| Hook | Event(s) | Behavior | Blocks? |
|---|---|---|---|
| `brain-pre-compact.sh` | PreCompact | snapshot note into today's log before compaction | no |
| `brain-session-end.sh` | SessionEnd + Stop | SessionEnd: run compile. Stop: suggest compile once/day if uncompiled entries | no |
| `brain-security-guard.sh` | PreToolUse (`Write\|Edit\|NotebookEdit\|Bash`) | denies writes to `canon/` and `decisions/active/` (a Bash command that reaches them passes only as one `brain-promote --approve` call or a read-only form), capsule deletes (`rm`/`find -delete`, also after `cd`), direct installs from `sources/` | **yes (only blocking hook)** |
| `brain-post-lint.sh` | PostToolUse (`Write\|Edit`) | lint capsule edits; warn on sensitive content | no |
| `brain-load.sh` | SessionStart | inject protocol + top-authority titles (≤ 8000 chars / < 2k tokens) | no |

Every hook exits 0, except the guard on failure; the guard expresses denial via `hookSpecificOutput.permissionDecision: "deny"`. The guard fails closed (P0-09): bad input is denied; if node cannot run, crashes or passes the guard's 20 s deadline, it writes a line to `.project-brain/reports/guard-failures.log` and exits 2, which blocks the call. It is registered in the committed `.claude/settings.json` with `"timeout": 30` and `"onFailure": "block"`, so a guard that cannot start or times out blocks too. If node breaks, use the break-glass procedure in `docs/SECOND_BRAIN_SECURITY.md`, "Hook gate".

## Skills

| Skill | Trigger phrases |
|---|---|
| `brain-capture` | "log this decision", "remember that X", "capture this lesson" |
| `brain-compile` | "compile the brain", "extract decisions from this week" |
| `brain-promote` | `/brain-promote` (invoke-only: `disable-model-invocation: true`, critical tier) |
| `project-brain-bootstrap` | "set up a project brain here", "bootstrap the second brain" |
| `capture-learning` | "learn from this", "/aprende", "don't do that again" |
| `brain-weekly-review` | "weekly review", "brain review", "refresh the brain" |
| `brain-search` | "search the brain for X", "did we decide anything about Y" |
| `brain-context-pack` | "pack context for X", "what should I know before doing Y" |
| `second-brain-setup` | "set up the second brain", "configure the brain" (5-round interview) |
| `brain-kernel` | "brain status", "how is the brain" (diagnoses + routes) |
| `reference-repo-{add,audit}`, `gstack-pattern-audit`, `reference-repo-pattern-extract` | reference-library operations |

## Install recipe

1. Copy `project-brain/` → `<target>/.project-brain/`
2. Copy `BRAIN.md`, `MEMORY.md`, `README.md` → `<target>/.project-brain/`
3. Copy `brain-profile.json` → `<target>/.project-brain/context/brain-profile.json`
4. Fill `{{PROJECT_NAME}}`/`{{CREATED_AT}}` + profile identity fields
5. `node scripts/brain/brain-verify.js --target <target>/.project-brain`

`brain-self-install.sh` and `install.sh --with-second-brain` automate all five.

## Troubleshooting

- **verify exit 1** — read the listed violations; a missing dir/file or `canon_requires_approval: false` fails it.
- **lint exit 3** — sensitive content; see the report in `.project-brain/reports/lint/`, redact, re-lint. See `SECOND_BRAIN_SECURITY.md`.
- **guard denial** — a command reached `canon/` or `decisions/active/` and was neither one plain `brain-promote --approve` call nor a read-only form, or tried a direct install from `reference-repositories/sources/`. Route canon and active-decision changes through `brain-promote --approve` (the weekly review stages a candidate and runs it); route source adoption through scout → audit → adapt → eval. A read command that shares a line with a writer, a redirect or `$(…)` is denied as a whole — split the command.
- **every call blocked, "the guard fails closed"** — node is broken or missing: break-glass in `docs/SECOND_BRAIN_SECURITY.md`.
- **promote exit 2** — you omitted `--approve`; promotion is never autonomous.
