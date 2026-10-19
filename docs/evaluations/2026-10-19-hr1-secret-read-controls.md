# HR1: secret-read controls for Claude Code on this laptop (2026-10-19)

HR1 (from `2026-10-14-gsd-global-install-audit.md` §7) says the global GSD secret-read guard protects only `.env`, `.env.<suffix>` and `.secrets` names. The secret actually exposed on this laptop, an Anthropic key in the Hermes container home's `settings.json`, is outside its scope, as are `~/.aws/credentials` and `printenv`.

This record covers:
- what Claude Code's native controls do, from the official docs and from measurement;
- what this repo now enforces (layer A);
- the proposed user-level change (layer B);
- the plan to remove the key from the repo tree (layer C).

Claude Code version: 2.1.302. Default permission mode on this laptop: `auto` (`~/.claude/settings.json`).

## Sources (accessed 2026-10-19)

| Source | What it verified |
|---|---|
| code.claude.com/docs/en/permissions | Path forms:<br>• `//abs`;<br>• `~/` home-relative;<br>• `/path` relative to the settings source, which is the primary working directory for project settings;<br>• a bare name (`Read(.env)` ≡ `Read(**/.env)`), which matches at any depth.<br>A `Read` deny also blocks Edit and Write on the path; NotebookEdit needs an `Edit` rule.<br>Read rules apply to the Bash file commands Claude Code recognizes (`cat`, `head`, `tail`, `sed`, `tee`). They do not apply to `grep -r` from a parent folder, or to scripts that open files themselves.<br>Deny wins over allow at every level. The page says of Bash deny/ask rules that they "isn't a security boundary around the program". Project `.claude/settings.json` keys "load from the current working directory's `.claude/` folder with no parent-directory fallback" (§Working directories). |
| code.claude.com/docs/en/settings | Permission lists from all levels are combined, not overridden. "Claude Code reads the shared `.claude/settings.json` from the session's primary working directory". |
| code.claude.com/docs/en/sandboxing | The sandbox (Seatbelt on macOS) covers Bash only: "A `denyRead` entry doesn't stop the Read tool". It is off by default, and by default reads most of the machine, including `~/.aws/credentials`. |
| code.claude.com/docs/en/env-vars | `CLAUDE_CODE_SUBPROCESS_ENV_SCRUB=1` strips credentials from subprocess environments; Claude Code's own process keeps them. |
| `~/.claude/hooks/gsd-secret-read-guard.js` header (GSD 1.14.0) | Claims that since 2.1.259 any `Read()` deny rule makes `cd DIR && cat …` compounds prompt, "even in `auto`". **Not found in the docs**; measured below. |

The docs research was done by a docs agent quoting the pages; the independent review re-read the permissions and settings pages. The CHANGELOG was not checked.

## Measurements

**Method.** All runs used `claude -p` in scratch git repos under the session scratchpad, with these settings:
- `--setting-sources project`, so no user hooks;
- `claude-haiku-5-5`, with `--max-budget-usd 0.2`;
- an `--allowedTools` list naming the commands under test, such as `Bash(cd *)`, `Bash(cat *)`, `Bash(head *)` and `Read`.

**What the allow list means for the results.** "Runs" cells were measured with those allow rules present. A deny rule wins over them, so "refused" cells hold regardless. `dontAsk` refuses anything that would prompt, so a refusal there with no deny rule means "would prompt" in the default mode.

**Inputs and cost.** Secret files held fake values, except measurement 5, which aimed one refused `cat` at a real private key (see the note there). Total cost of the author's runs: about $0.13; the reviewer's probes added about $0.03.

**1. Does a `Read()` deny rule make harmless `cd … && cat` prompt?** Deny rule `Read(/infra/data/home/**)`; the command reads an unrelated file.

| Command | No rule | Rule, `dontAsk` | Rule, `auto` |
|---|---|---|---|
| `cd sub && cat a.txt` | runs | **refused** | runs (4 of 4) |
| `cat sub/a.txt` | runs | runs | runs |

The GSD claim holds for prompting modes. It did not reproduce in `auto`, this laptop's default.

**2. What a deny rule blocks** (same rule; the fake key file is under the denied folder):

| Read form | Blocked (`dontAsk` and `auto`) |
|---|---|
| Read tool | yes |
| `cat <file>`, `head -c 200 <file>`, `grep FAKE <file>` | yes |
| `cd <dir> && cat <file>` | yes |
| `grep -r FAKE .` | **no**: the key is printed (the documented gap) |

**3. Layer A end to end, sessions started at the repo root.** The branch's exact settings files were copied into a replica of this repo's secret-file layout with fake contents.

| Case | `auto` | `dontAsk` |
|---|---|---|
| Read tool: `data/home/.claude/settings.json`, `data/profiles/architect/.env`, root `.env` | refused | refused |
| `cat .env.ga`, `head data/auth.json`, `cd data/home/.claude && cat settings.json` | refused | refused |
| `cat .env.example`, Read tool on `data/config.yaml` | runs | runs |
| `cd infra/hermes-agent && cat .env.example` | runs | refused (would prompt) |

**4. Sessions started elsewhere** (independent review H1). Project settings load only from the starting folder, and `/` rules are anchored there.
- **Before the fix**, the review showed two leaks:
  - a session started in `infra/hermes-agent/` read the fake `.env.ga` and the container key file;
  - a worktree-like session read the main tree's fake `.env.ga` by absolute path.
- **After the fix**, measured on the replica:
  - **Started in `infra/hermes-agent/`**, with its new settings file: the Read tool on `data/home/.claude/settings.json` and `data/.claude/settings.json`, and `cat .env.ga`, are refused in both modes. `cat .env.example` runs.
  - **Started in an unrelated repo**, reading the replica's `.env.ga` by absolute path:
    - no rule, `auto`: the secret is printed;
    - with an absolute `Read(//…/.env.ga)` rule, the read is refused in both modes.

    Worktree sessions are therefore covered only by the absolute user-level rules in layer B.

**5. `CLAUDE_CODE_SUBPROCESS_ENV_SCRUB=1` set in a settings `env` block.** Bash's environment variable names were compared with and without it.
- **Removed:** a test `*_API_KEY` variable, `CLAUDE_CODE_MESSAGING_TOKEN`, and `SSH_AUTH_SOCK`.
- **Left:** no credential-like names.
- **Cost:** `hermes-box` uses a passphrase-protected key (`~/.ssh/vps-hermes`), so without the agent socket, `ssh hermes-box` from Bash would no longer work.

**The proposed `~/.ssh` rules:**
- `cat ~/.ssh/hermes-box-tunnel` is refused in both modes.
  - **Note (review H3):** this probe pointed at the real private key, not a fake one. The rule held, but had it failed, the key would have landed in a scratch output file. Future probes use fake files only.
- `ssh -G hermes-box` runs in `auto`, with and without the rules (2 of 2 each).
- `ssh -G -i ~/.ssh/vps-hermes …` was refused in `auto` but ran in `dontAsk`. The `auto` refusal therefore came from auto mode's own classifier, not from the deny rule.

**Inventory** (key-shaped strings, compared by sha256 prefix only; no value was printed):
- **The Anthropic key:** one real-looking key sits in both `infra/hermes-agent/.env` and `infra/hermes-agent/data/home/.claude/settings.json`.
- **`.env.ga`:** holds a real-looking Google refresh token.
- **`data/auth.json`:** holds a credential pool (`anthropic`, `openrouter`).
- **Other hits** in tests and plans are fixtures. The `BEGIN … PRIVATE KEY` hits are header text that matches a test fixture.
- **Process note:** the inventory script opened `.env` and `.env.ga` through Python. That is the interpreter gap (HR2); it printed only type and hash prefixes.
- **Found by the review (H6)**, with a key-pattern scan that printed only file names and counts: a second Claude config, `data/.claude/` with `data/.claude.json`, now covered.
- **Not covered:**
  - Hermes `sessions/`, `state.db` and `profiles/*/state.db` (the review's pattern scan found no key-shaped strings there);
  - the `security-reviews/review-*/` screenshots.

## Layer A: project deny rules (this change)

Two committed settings files deny `Read` and `Edit`. Each `/` rule is anchored at its own folder.

**Repo root, `.claude/settings.json`:**
- `**/.env`;
- `/infra/hermes-agent/.env.ga`, `.env.gaw`, `.env.pr`;
- `/infra/hermes-agent/data/auth.json`;
- `/infra/hermes-agent/data/home/**`, the container home with the key file and transcripts;
- `/infra/hermes-agent/data/.claude/**` and `/infra/hermes-agent/data/.claude.json`.

**`infra/hermes-agent/.claude/settings.json`:** the same set, anchored there (`/.env.ga`, `/data/home/**`, and so on).

The tracked `.example` templates stay readable. `scripts/claude-settings.test.js` checks both files:
- every protected path below each file's folder has both rules;
- no rule matches a tracked file;
- no rule matches the listed readable files;
- the root file keeps its telemetry hooks.

Its matcher refuses unanchored patterns with a `/`, because the docs and measured behavior disagree on how those anchor (review H5). `install.sh` never copies these files into target projects; it merges only its own hooks.

On the VPS, `/opt/hermes-agent` is a symlink into the clone (`BRING-UP.md`), so the nested file also lands at `/opt/hermes-agent/.claude/settings.json`. It has no effect there:
- the container mounts a read-only tmpfs over the repo's `infra/hermes-agent`;
- no deploy check lists that folder's files.

A Claude session started in `/opt/hermes-agent` would get the same rules, matching the box layout.

**Scope:** sessions started at the repo root or in `infra/hermes-agent/`. Sessions started anywhere else (a worktree, another subfolder) need layer B.

**Costs:**
- **AgentShield grade.** The grade on the root `.claude/` drops from B (75) to C (71). Once a deny list exists, AgentShield adds five MEDIUM "Missing deny rule" findings: recursive force delete, privilege escalation, world-writable permissions, SSH connections, and device-file writes. This was reproduced with `ecc-agentshield@1.4.0` on copies of `main` and the branch. CI fails only at D or F, so the margin is now one grade. Adding those Bash denies to regain B would block real work, including `ssh hermes-box`.
- **Prompting modes.** In a prompting mode, `cd <dir> && cat <file>` asks for approval while any `Read` rule exists (measurement 1).

**Residual gaps:** `grep -r` from a parent folder, interpreter one-liners, and scripts that open files themselves.

## Layer B: user-level rules (applied 2026-10-19)

The proposal adds `permissions.deny` to `~/.claude/settings.json`, current sha256 `f49cd288f07af1f3…`. It sets `Read` and `Edit` rules (30 entries) for:
- `//**/.env`, `//**/.env.local`, `//**/.env.production`;
- `~/.aws/**`;
- `~/.hermes/.env`;
- `~/.ssh/vps-hermes`, `~/.ssh/hermes-box-tunnel`, `~/.ssh/id_*`;
- this repo's secret paths, absolute: `//Users/ericksicard/Projects/claude_code/infra/hermes-agent/` plus `.env.ga`, `.env.gaw`, `.env.pr`, `data/auth.json`, `data/home/**`, `data/.claude/**`, `data/.claude.json`. These cover worktree sessions (measurement 4).

Nothing else changes.

**Applied 2026-10-19** with the owner's approval:
- the live sha256 matched `f49cd288f07af1f3…`;
- backup at `~/.claude/settings.json.bak-hr1-2026-10-19` (mode 0600); the new file is installed with mode 0600;
- only `permissions.deny` differs, with 30 entries.

Live check: a session ran with `--setting-sources user`, hooks disabled (`disableAllHooks`) so the GSD guard could not interfere. On a fake `.env.production`, the Read tool and `cat` were refused; a plain file still read.
Rollback: restore the backup.

`CLAUDE_CODE_SUBPROCESS_ENV_SCRUB` is **not** proposed as a global default, because it breaks `ssh hermes-box` from Bash (measurement 5). The token it would hide from `printenv`, `CLAUDE_CODE_MESSAGING_TOKEN`, stays visible to Bash; that is an owner decision.

## Layer C: remove the key from the repo tree (done on the laptop 2026-10-19, except rotation)

The VPS already does this (`deploy/BRING-UP.md`, part 1, steps 3 and 5):
- the Anthropic key lives in a root-only `/etc/hermes/.env.anthropic`;
- `ANTHROPIC_API_KEY` is stripped from the gateway `.env`;
- `data/home/.claude/settings.json` (written by the retired `claude-auth-init` sidecar) is shredded;
- the security review checks that it stays absent (`NO_CLAUDE_KEY_FILE`).

The runbook notes the gateway needs no real key for audits. The laptop's local stack never got these steps.

Plan, each step for the owner to approve:
1. Confirm the local stack does not need the key in the gateway. `docker-compose.yml` says the gateway's `.env` is for `OPENROUTER_API_KEY`, and drafts run in `ads-drafter`.
2. Strip `ANTHROPIC_API_KEY` from `infra/hermes-agent/.env` with `bin/install-env-secret.py strip`, as on the box.
3. Check the date of `data/home/.claude/settings.json`; a file dated today means something still writes it, so stop. Otherwise shred it, then recreate the gateway.
4. If a local step needs the key, keep it outside the repo tree: a file like the box's `/etc/hermes/.env.anthropic`, with an owner-only mode.
5. Decide whether to rotate the key. Nothing shows it was read into a conversation:
   - the GSD audit's S05 probe was synthetic;
   - this session compared hash prefixes only.

   However, it has sat in a readable file inside the project tree.

**Done 2026-10-19** with the owner's approval. A script printed only booleans, hash prefixes and dates.
1. **Need:** confirmed the local stack doesn't need the key in the gateway:
   - the compose comment above;
   - `.env.example` has no `ANTHROPIC_API_KEY`;
   - audits read `/etc/hermes/.env.anthropic`, which is box-only.

   No local container was running.
2. **Copy:** the key (sha256 prefix `66504145`, the same value in both repo-tree files) was copied, not deleted, to `~/.config/hermes-local/.env.anthropic`:
   - file mode 0600, folder mode 0700, outside the repo tree;
   - written with `bin/install-env-secret.py set --stdin`, the value passed by pipe;
   - verified equal by hash.
3. **Strip:** `bin/install-env-secret.py strip` removed the one `ANTHROPIC_API_KEY` line from `infra/hermes-agent/.env`. Every other line was kept byte for byte; mode and owner were unchanged.
4. **Container file:** `data/home/.claude/settings.json` held only that key and was last written 2026-09-19, so nothing still writes it. It was overwritten with zeros and deleted. On APFS (SSD), an overwrite does not guarantee the old blocks are erased; treat it as deletion.
5. **Scan:** no file in the repo tree holds the key any more.
6. **README:** `infra/hermes-agent/README.md` "First run" no longer tells a laptop to put `ANTHROPIC_API_KEY` in `.env`, and points to the out-of-tree file.

**Open, owner decision:** rotate the key. Nothing shows it was read into a conversation, but it sat in a readable file in the project tree.

**Still in the repo tree, by design** (they are the local stack's working credentials, read by host scripts):
- the OpenRouter key in `.env`;
- the Google refresh token in `.env.ga`;
- `.env.pr`;
- `data/auth.json`.

Layers A and B deny Claude Code's tools on them. Moving them is a separate change.

## Review

Independent review, round 1: **approve with changes** (H1–H7). The author's answers:
- **H1:** the second settings file and the layer B absolute rules, with measurements.
- **H2:** documented, after reproducing it.
- **H3, H4, H7:** corrections to this record.
- **H5:** the test matcher now refuses unanchored path patterns.
- **H6:** `data/.claude` is now covered.

Round 2 (the reviewer) confirmed H1–H7 closed. It ran 17 test mutants: 15 were killed, and the 2 survivors were equivalent or broadening. It also ran its own probes from `infra/hermes-agent/`. Its verdict was **approve**, with wording fixes I1–I5, which are applied here.
