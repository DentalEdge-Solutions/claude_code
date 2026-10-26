# Native ask rules and staged self-deploys (P0-07, P0-08)

> Date: 2026-10-26 · Items: P0-07, P0-08 (S5 roadmap, batch B3 / PR-6) · Trace: OPP-07, OPP-09 · GAP-03, GAP-04,
> GAP-11 · breach (c) · DECISION-S2-1 (b), DECISION-S1-5 (b) · R-B-11, R-B-13, V-S5-12, V2-RS-9, OC-4 ·
> Branch `fix/p0-07-p0-08-ask-rules-staged-deploys` from `main` at `fce8542` · Installed Claude Code 2.1.302 ·
> Review: pending (independent reviewer; the author closes no finding)

## What changed and why

Two parts of breach (c), "approval not enforced": consequential commands (pushes, merges, reviews, token use, branch
deletes, promotion to canon, skill deploys, the installer) ran without any prompt, and three definitions deployed a
skill into `~/.claude/skills/` themselves, where Claude Code loads it, with no owner step in between.

| File | Change |
|---|---|
| `.claude/settings.json`, `infra/hermes-agent/.claude/settings.json` | `permissions.ask` added, the same 19 rules in both (below). The 16 deny rules each and the root telemetry hooks are unchanged (diff: +21 lines per file, 0 removed) |
| `scripts/claude-settings.test.js` | 14 new tests (26 in all): the exact ask list in both files, identical lists, deny lists equal to the HR1 set, `permissions` holding only `deny` and `ask`, and a model of the documented Bash matching run over fixed commands (below) |
| `skills/skill-refine/SKILL.md` | KEEP → "**KEEP** (staged: record in SKILL-REFINE-LOG.md; deployment waits for owner approval)"; neutral KEEP → "(staged as above)"; the two copy-location explanations (`:35`, `:55`) no longer say the keep step syncs; step 11 ends by saying the result is staged; new rule "Stage, never deploy" |
| `.claude/agents/skill-refine-agent.md` | The same for KEEP (7d), neutral KEEP, the explanations at step 4 and 7b, step 11 and a What-NOT-to-Do line |
| `skills/skill-adapt/SKILL.md` | Step 10 "Sync to runtime" + `cp -r skills/<skill-name> ~/.claude/skills/` → "**Stage, do not deploy**" (recorded in the step 14 report; deployment waits for owner approval); step 14 states it; new rule. Step 4's sentence about `install.sh` syncing `skills/` is true and stays |
| `CLAUDE.md` | The whole deploy bullet (was `:75`) rewritten to the V2-RS-9 text: the owner deploys and runs the check; "Owner deploys" defined (runs the command or explicitly approves it, for example at the P0-07 ask prompt); skill-adapt, skill-refine and skill-refine-agent stage and never deploy |
| `install.sh` | The CLAUDE.md section it writes into targets gains the same instruction, inside the `skill-builder` markers (below) |
| `scripts/staged-deploys.test.js` (new) | 10 tests: a copy matcher over every definition, the staged wording of the three steps, a never-deploy rule in each, the CLAUDE.md bullet and the install.sh section |
| `scripts/refine-keep-revert.test.js` | The neutral-KEEP assertion reads "KEEP (staged as above)" instead of "KEEP and sync as above" |
| `scripts/refine-copy-paths.test.js` | Header comment only (the keep step's copy is history) |
| `README.md`, `docs/USER-GUIDE.md` | skill-adapt and skill-refine say the result is staged and the owner deploys it |

Not touched: `evals/` (no tracked `evals.json` edited), `.project-brain/`, `skills/skill-eval`, `skills/agent-eval`,
`scripts/codex/`, the pinned evaluator files, `infra/hermes-agent/bin/`, any `settings.local.json`, anything under
`~/.claude`. No `description:` frontmatter changed. `uninstall.sh` needs no change: it removes the whole block between
the `skill-builder` markers (`uninstall.sh:123-`, covered by `scripts/uninstall.test.js`), and the new line sits
inside them (asserted).

## P0-07: the ask list

| # | Rule | Source |
|---|---|---|
| 1-15 | `Bash(git push *)`, `Bash(gh pr merge *)`, `Bash(gh pr review *)`, `Bash(gh api *)`, `Bash(gh auth *)`, `Bash(git push * --delete *)`, `Bash(git branch -D *)`, `Bash(node scripts/brain/brain-promote.js *)`, `Bash(cp * ~/.claude/skills/*)`, `Bash(cp -r * ~/.claude/skills/*)`, `Bash(cp -R * ~/.claude/skills/*)`, `Bash(./install.sh*)`, `Bash(bash install.sh*)`, `Bash(./uninstall.sh*)`, `Bash(bash uninstall.sh*)` | S5 P0-07, verbatim and in order |
| 16 | `Bash(cp * ~/.claude/skills)` | added: `cp -R skills/x ~/.claude/skills` (no trailing slash) is a natural deploy form, and `~/.claude/skills/*` does not match it |
| 17-19 | `Bash(cp * $HOME/.claude/skills*)`, `Bash(cp * "$HOME/.claude/skills*)`, `Bash(cp * "$HOME"/.claude/skills*)` | added: Bash rules match the command text, so `~` and `$HOME` are different text (finding D2) |

No roadmap rule is syntactically wrong per the docs. Two are redundant under the documented matching and are kept as
the roadmap names them: `Bash(git push * --delete *)` is covered by `Bash(git push *)`, and the `cp -r`/`cp -R` rules
by `Bash(cp * ~/.claude/skills/*)` (a `*` matches any text, flags included). Redundant ask rules cost nothing.

### What the docs say (Tier A, accessed 2026-10-26, installed 2.1.302)

Pages fetched as Markdown: <https://code.claude.com/docs/en/permissions.md>, <https://code.claude.com/docs/en/settings.md>,
<https://code.claude.com/docs/en/permission-modes.md>, <https://code.claude.com/docs/en/headless.md>.

| # | Question | Finding | Source (section) |
|---|---|---|---|
| D1 | Wildcard form, word boundary | "A `*` in a Bash rule matches any text, including spaces"; "Claude Code matches everything before the first `*` as written". "A `*` at the end, with a space before it, also matches the bare command" when it is the only wildcard, and "The space before a trailing `*` is part of the rule": `Bash(ls *)` does not match `lsof`, `Bash(ls*)` does. So `Bash(git push *)` covers `git push` alone; `Bash(./install.sh*)` has no space and also covers `./install.sh` with no argument | permissions › Wildcard patterns |
| D2 | Is `~` expanded in a Bash rule? | "Bash rules match the whole command text, with `*` standing in for any text." No expansion of `~` or variables is described for Bash rules (the `~/` anchoring the page describes is for Read/Edit path rules). Read as literal text: `~/.claude/skills/` and `$HOME/.claude/skills/` are different strings. **Inference from the docs, not measured.** Hence rules 17-19; `${HOME}` and absolute home paths remain residuals | permissions › Bash; › Read and Edit |
| D3 | Compound commands | Separators `&&`, `||`, `;`, `|`, `|&`, `&`, newline. "Deny and ask rules apply when any subcommand matches them, including a command nested inside a subshell, a command substitution, or a control-flow body"; "An ask rule like `Bash(git clean *)` still prompts you for `cd /tmp && git clean -f` … even in auto mode" | permissions › Compound commands |
| D4 | Wrappers and assignments | `timeout`, `time`, `nice`, `nohup`, `stdbuf`, `command`, `builtin`, `noglob` are stripped; "A deny or ask rule matches past any leading assignment" | permissions › Wrappers |
| D5 | Not a boundary | A rule "covers the invocation Claude usually produces and isn't a security boundary around the program"; `Bash(git push *)` does not stop `git -C . push origin main`, `git -c push.default=current push origin main` or `git 'push' origin main`. Command-independent enforcement: sandboxing or a PreToolUse hook | permissions › What a Bash rule doesn't match |
| D6 | deny / ask / allow precedence | "Rules are evaluated in order: deny, then ask, then allow. The first match in that order determines the outcome, and rule specificity doesn't change the order"; "a matching ask rule prompts even when a more specific allow rule also matches the same call" | permissions › Manage permissions |
| D7 | Across scopes: does a project `ask` beat a local `allow` such as `Bash(git *)`? | Yes. Lists merge across files ("Claude Code combines the lists instead of picking one"), and "an `allow` rule there [the local file] doesn't outrank an `ask` rule from a project or managed file". Choosing "don't ask again" on an ask prompt saves a local allow that therefore does not stop the next prompt | settings › Lists merge instead of overriding; › Permission rules combine differently than you expected; permissions › Settings precedence |
| D8 | Trust | Project `allow` rules wait for workspace trust; "`deny` and `ask` rules aren't affected, since they only restrict" | permissions › Project allow rules and workspace trust |
| D9 | Auto mode | "Explicit ask rules still force a prompt"; in the classifier's decision order, "Ask rules that match on a command's content, such as `Bash(git push *)`, fall back to a permission prompt". Ask-matched tools are among the "Actions no mode auto-approves", `bypassPermissions` included | permission-modes › Eliminate prompts with auto mode; › How the classifier evaluates actions; › Actions no mode auto-approves |
| D10 | Non-interactive `claude -p` | "In a Manual mode `claude -p` run, a call that needs approval is denied unless something approves it, such as a `PermissionRequest` hook or a `--permission-prompt-tool`". Plan mode "keeps its blocks wherever Claude Code runs without an interactive terminal, including non-interactive runs with `-p`". A `-p` run reads project settings and runs project hooks unless `--setting-sources user` or `--bare` is passed. So an ask rule in a headless run is a denial, not a wait | headless › (permissions paragraph); permission-modes › Tool calls denied in `claude -p` and Agent SDK runs; › Analyze before you edit with plan mode; permissions › What runs before you trust a folder |
| D11 | Which sessions load the file | "Claude Code reads the shared `.claude/settings.json` from the session's primary working directory": sessions started at the repository root, in `infra/hermes-agent/`, or in a worktree of the repository (which checks the tracked file out) get the rules; a session started in another subfolder does not | settings › Where Claude Code keeps the local file in a git repository |
| D12 | Hooks and mods | A PreToolUse hook's `"allow"` does not skip a matching ask rule. A mod handling `tool.check` can approve a call an ask rule would prompt for in a session with neither managed settings nor a Team or Enterprise `/login` | permissions › Precedence among rules, hooks, and mods |

### The test and what it proves

`claude-settings.test.js` holds a small model of D1, D3 and D4: a `*` becomes "any text", a single trailing ` *`
also matches the bare command, a command is split on the D3 separators, and leading assignments and the D4 wrappers
are dropped before matching. The model is pinned on the docs' own table rows (`npm run *`, `git log * main`,
`* --version`, `ls *` vs `ls*`, `* --help *`, the `git -C . push` row, the `git clean` compound example). Over it:

- 31 consequential command texts each match an ask rule in both files (pushes in five forms, a push after `&&` and
  after `;`, behind `timeout` and behind `GIT_TRACE=1`; `gh pr merge`, `gh pr review`, `gh api` write and read,
  `gh auth status|token|login`; `git branch -D`; `brain-promote.js --approve`; seven skill-deploy spellings;
  `./install.sh`, `bash install.sh`, `./uninstall.sh`, `bash uninstall.sh`), and every one of the 19 rules is
  reached by at least one of them;
- 15 routine texts match none (`git status`, a commit whose message says "push", `git branch -d`, `gh pr view|create|list`,
  the test and deploy-check commands, `bash -n install.sh uninstall.sh`, backups and restores under `evals/`, a copy
  *out of* `~/.claude/skills`, `brain-search.js promote`);
- 10 recorded residual forms match none (the list under Residuals). If a later rule catches one, the test fails and
  the residual list must be updated.

It proves the rule strings cover these texts **under the documented matching**. It does not prove Claude Code
prompts: the model is ours, and D2 is an inference. That is the owner probe below.

### Hermes (OC-4): excluded with evidence from the repository

Question: the proposer runs `claude -p` with workdir `/projects/claude_code`, so the root ask rules load in those runs
(D10, D11), and a headless ask is a denial (D10). Does any Hermes run issue a command the new rules match?

Evidence (all read from tracked files; no container, box or server was contacted):

1. `infra/hermes-agent/docker-compose.yml:40` mounts the repository read-only at `/projects/claude_code`;
   `:56-57` puts a read-only tmpfs over `/projects/claude_code/infra/hermes-agent`. So the root `.claude/settings.json`
   is visible to executor runs and the Hermes copy is not.
2. `infra/hermes-agent/registry/projects.yaml`: `claude_code` has `scope: read`, defined there as "`claude -p` runs
   read-only: `--permission-mode plan` and `--allowedTools 'Read,Grep,Glob'`".
3. Every `claude -p` invocation in the tracked Hermes files uses exactly that pair:
   `skills/claude-code-proposer/SKILL.md` step 2 ("Use EXACTLY: … `--allowedTools 'Read,Grep,Glob' --permission-mode plan`",
   workdir from the registry); `skills/claude-code-operator/SKILL.md` (`scope: read` → every call "MUST include" the
   pair; `scope: write` not permitted); `run-ads-audit.sh:24-25`, `run-trend-audit.sh:48-49`,
   `bin/run-client-audit.py:81-82` (Google Ads project, other workdir, same pair). The proposer's analysis
   instruction asks for reading and a Markdown proposal only; its step 3 says "do NOT execute scripts".
4. The draft-PR step (`open-proposal-pr.sh` → `bin/open-proposal-pr.py:157-248`) runs `git` and `gh pr create`
   through Python `subprocess` on a fresh clone. That is not a Claude Code tool call, so permission rules do not
   apply to it (and `gh pr create` is not an ask rule).
5. `infra/hermes-agent/skills/claude-code-reviewer/SKILL.md`: the review worker has no terminal.

Conclusion: no documented Hermes run issues a command the ask rules match. Every ask-ruled command writes or
authenticates, so none is in the read-only command set, and in a `-p` plan-mode run such a call was already denied
(D10). The only case where the outcome changes is a non-read-only call that plan mode would let run because auto mode
is available to the run and its classifier approves it; that call is now denied. The change can only turn an allowed
call into a denied one, never the reverse, and the proposer's contract uses none of these commands. **Hermes runs are
excluded from impact on this evidence.**

What this does not cover (UNVERIFIED): the box's real behaviour. The Dockerfile installs `@anthropic-ai/claude-code`
unpinned (`Dockerfile:17`), so the executor's version is not known from the repository, and the Hermes model could
form a command the skill text does not show. An optional box probe for security review #12, to be run by the owner
only: inside the executor, `ls -l /projects/claude_code/.claude/settings.json` (expected: present, with the ask list)
and `claude --version`; then one proposer run as scheduled, expected to complete with the same output shape as
before and no new `permission_denials`. Impact on the Hermes checklist and review #12: no new checklist item is
needed for this change (it only restricts); review #12 should note that the root project settings now carry ask
rules that load in executor runs and deny the listed commands there. The checklist was not edited here.

The P0-09 part of OC-4 (root *hooks* loading in Hermes runs) is separate and stays open.

### Pending owner probe (acceptance, no-UI evidence row)

Not run: an implementer cannot start a fresh interactive session. To run by the owner, after merge (or in a checkout
of this branch), from the repository root:

1. Start a fresh session: `claude --permission-mode auto` (a fresh process reads the new `.claude/settings.json`).
2. Input: "Run exactly `git push --dry-run origin HEAD:refs/heads/p0-07-probe` and report the result."
   Expected output: a "Bash command" permission prompt naming that command ("This command requires approval"), not a
   classifier decision. Answer **No**. Expected: the command does not run; the tool result says it was rejected.
3. Input: "Run exactly `gh pr merge 999999 --repo DentalEdge-Solutions/claude_code`." (a PR number that does not
   exist). Expected: the same prompt; answer **No**.
4. Optional, same session: `git status && git push --dry-run` (compound, D3) and
   `cp -R skills/skill-refine/. ~/.claude/skills/skill-refine/` (deploy, rule 9/11): a prompt each; answer **No**.
5. `/permissions`: the 19 ask rules listed with `.claude/settings.json` as their source.

Run steps 2-3 once before the settings trim below and once after: per D7 both should prompt, because the local
`Bash(git push *)` / `Bash(git *)` allow does not outrank the project ask. Record each input, the prompt text seen and
the answer in this file or the PR.

### Owner action (not performed here)

In the gitignored `.claude/settings.local.json` at the main checkout's root (not read or edited in this work): remove
`Bash(git push *)`, `Bash(gh pr *)` and `Bash(git *)` from `permissions.allow`, and review `Bash(python3 *)` (S5 cites
`:10,63,68` and `:59`). With D7 the ask rules already win over those allows; the trim removes the silent auto-approval
for the forms the ask rules do not catch (D5), for example `git -C . push`, which `Bash(git *)` approves today.

## P0-08: staged self-deploys

Measured with `scripts/staged-deploys.test.js`'s matcher over every Markdown definition under `skills/`,
`.claude/agents/`, `.claude/skills/`, `packs/` and `infra/hermes-agent/skills/` (90 files, reports and logs
excluded), at `fce8542` (via `git archive`) and at this branch's head:

| Measure | `fce8542` | head |
|---|---|---|
| Model-run copies into the user-level skills folder in definitions | **3** (`skills/skill-adapt/SKILL.md`, `skills/skill-refine/SKILL.md`, `.claude/agents/skill-refine-agent.md`, each `cp -r skills/<skill-name> ~/.claude/skills/`) | **0** |
| Lines in skill-adapt, skill-refine and skill-refine-agent that say a step syncs the skill (a line naming `install.sh` excluded) | 9 | 0 |

The matcher flags `cp`, `rsync`, `install`, `ln`, `mv` and `ditto` commands whose destination is the skills folder
under `~`, `$HOME`, `${HOME}`, `/Users/<u>`, `/home/<u>`, `/root` or `$CLAUDE_CONFIG_DIR`, including quoted and
line-continued forms; it leaves reads from that folder, `diff`, `ls` and copies into the project's `.claude/skills/`
alone (fixtures in the test). Reports (`SKILL-EVAL.md`, `<agent>-EVAL.md`, `*-REFINE-LOG.md`) are dated history and are
excluded: `skills/skill-adapt/SKILL-EVAL.md:47` still quotes the old step 10.

Mid-loop re-evaluation is unaffected: with-skill subagents load `skills/<name>/SKILL.md`, not the deployed copy
(S5 P0-08 risk line, `skill-eval-agent.md`).

### The CLAUDE.md text for targets

`install.sh` writes a `skill-builder` section into a target's `CLAUDE.md`. It now carries: "After a skill change, the
owner deploys it (`cp -R skills/<name>/. ~/.claude/skills/<name>/`) and checks it (`diff -rq skills/<name>
~/.claude/skills/<name>` prints nothing) — Claude Code loads skills from `~/.claude/skills/`, not from this project's
`skills/` … 'Owner deploys' means the owner runs the deploy command or explicitly approves it. skill-adapt,
skill-refine and skill-refine-agent stage their result and never deploy it themselves". Two differences from this
repository's bullet, on purpose: targets do not receive `scripts/check-skill-deploy.js` (`install.sh` copies only the
codex, telemetry and brain scripts), so the check is a `diff -rq`; and targets receive no ask rules, so the text does
not mention the P0-07 prompt.

## Residuals

1. **Rules are not a security boundary (D5, V-S5-12).** Pinned in the test as still escaping: `git -C . push`,
   `git -c push.default=current push`, `git 'push'`, `rsync … ~/.claude/skills/`, `cp … ${HOME}/.claude/skills/`,
   `cp … /Users/<u>/.claude/skills/`, a `node -e` (or `python3`) script calling the GitHub API, `bash ./install.sh`,
   `sh install.sh`, `node ./scripts/brain/brain-promote.js`. Also `/usr/bin/git push`, `sh -c '…'`, `cd ~/.claude/skills
   && cp -R …/skills/x .`, and a `gh` alias. Command-independent enforcement needs a PreToolUse hook or sandboxing; the
   boundary for merges is P0-10 (GitHub rulesets).
2. **`install.sh` is only prompted.** Its step 2 still copies every skill into `~/.claude/skills/` (`install.sh:88-92`);
   P0-07 makes running it prompt, nothing more (V-S3-12, R-B-11).
3. **Prompt count rises (R-B-13).** About 2-4 more prompts per PR, more with `gh api`, whose read-only calls prompt too.
   The B0/P1-03 intervention measures are expected to rise; that is not a regression.
4. **Sessions the rules do not reach (D11).** A session started in a subfolder other than `infra/hermes-agent/` loads
   no project settings, so no ask rules; as for HR1, user-level rules would be needed there.
5. **Mods (D12).** In a session with neither managed settings nor a Team or Enterprise login, an installed mod that
   handles `tool.check` can approve a call an ask rule would prompt for.
6. **D2 is an inference.** If Claude Code expanded `~` before matching, rules 9-11 and 16 would still match the `~`
   form Claude writes; if it did not, rules 17-19 cover the common `$HOME` forms. Either way only the owner probe
   measures it.
7. **Existing targets keep the old CLAUDE.md section.** `install.sh` skips the section when the marker is present, so a
   project installed before this change gets the new line only after the owner removes the block (or runs
   `uninstall.sh`) and reinstalls.
8. **Definitions can still say "deploy" in words.** The P0-08 test reads copy commands and the three steps'
   wording; it cannot read every way a sentence could instruct a deploy. P0-07's `cp` rules are the second layer.
9. **AgentShield grade not measured.** CI's security gate runs the pinned `ecc-agentshield@1.4.0` on `.claude/`;
   `npx` is not run locally (project rule). The local static scanner gives PASS, 0 findings on both settings files.
   The grade on the PR's CI run is the measurement; CI fails only at D or F.

## Checks run (on the branch head before this record)

| Command | Result |
|---|---|
| `node scripts/run-all-tests.js` (alone) | 46/46 suites passed |
| `node scripts/claude-settings.test.js` | 26 PASS (12 before; 14 new) |
| `node scripts/staged-deploys.test.js` | 10 PASS |
| `node scripts/refine-keep-revert.test.js` · `node scripts/refine-copy-paths.test.js` | 47 PASS · 30 PASS |
| `node scripts/validate-skills.js` | exit 0 |
| `node scripts/ci-scan-skills.js` | exit 0; 23 targets, 0 unmatched, 0 stale |
| `node skills/skill-audit/scripts/static-scan.js` on `skills/skill-refine`, `skills/skill-adapt`, `.claude/agents/skill-refine-agent.md` and both settings files | PASS, 0 findings each |
| `bash -n install.sh uninstall.sh` | OK |

Red commits kept: `5e794b3` (P0-07: 7 of the new tests failed on the unchanged settings) and `0ae69bf` (P0-08: the
definition scan found the 3 copies; 9 of 10 new tests and 2 refine-keep-revert tests failed).
`infra/hermes-agent/bin/` was not changed, so `run-bin-tests.sh` was not required.

## Not measured

- The owner probe above (P0-07 acceptance) — pending owner.
- The Hermes box probe — optional, owner-run, for review #12.
- skill-eval of skill-refine and skill-adapt after the step changes — P1-10 (B6).
- Deploys: after merge the owner deploys skill-refine and skill-adapt (`cp -R skills/<name>/. ~/.claude/skills/<name>/`)
  and runs `node scripts/check-skill-deploy.js`; skill-refine-agent is project-scoped and needs no deploy.
