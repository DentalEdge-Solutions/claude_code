# Handoff 2026-10-14: software-factory optimization, Phases 1–3 merged (PR #131); what is open next

**Start here in the next session.** Read this file, then `.project-brain/BRAIN.md`. This file carries no
credential value, customer id, hostname or address. It covers only the software-factory track. The Hermes
box and security-review track is in `2026-10-12-review-10-pass.md` (review #11 has since passed: see the
brain's active decisions).

## The question and the answer so far

**The owner's goal:** improve this project as a "software factory", meaning the way capabilities (skills,
agents) and software are sourced, built, verified and merged.

**The verdict, from evidence (Phase 2):** keep the current architecture and make its gates true. Do not
build a two-factory subsystem. The project already has both "factories":

- **Capability lane:** scout → audit → adapt → eval → refine for skills and agents, plus team-eval,
  telemetry, the reference library and the brain.
- **Delivery lane:** Superpowers brainstorm → spec → plan → subagent tasks with per-task review, then a PR
  gated by CI under the `main-protection` ruleset. Hermes Kanban proposes read-only and opens draft PRs.

The external factories reviewed added patterns, not runtime: Ras Mic `skills`, Super-Board, Rezvani's Skill
Factory and REA, each at a pinned revision. Their runtimes would add a second Kanban, model self-merge or
weaker approval boundaries.

## Documents (read these instead of re-deriving)

| Document | What it holds |
|---|---|
| `docs/CLAUDE_CODE_KNOWLEDGE.md` | Phase 1: source tiers, source registry, research-and-citation protocol, the freshness proposal (§5, not enabled) |
| `docs/evaluations/2026-10-14-claude-code-knowledge-sources.md` | Phase 1 record: the sources checked, access dates, smoke queries |
| `docs/evaluations/2026-10-14-software-factory-architecture-evaluation.md` | Phase 2: repository comparison (§2), adoption matrix of 19 items (§4), roadmap (§8), metrics and baselines (§9), decisions D1–D6 |
| `docs/evaluations/2026-10-14-phase3-implementation.md` | Phase 3: what was built, the evidence, what is untested (§3), before/after (§4), debt (§5), maintenance and rollback (§7), ranked next steps (§8) |
| `docs/evaluations/2026-10-14-gsd-global-install-audit.md` | P0-C: the GSD hooks audit (BLOCK under our scanner), the skill-listing overflow, options A–D |
| `docs/REVIEW_PROTOCOL.md` and `.github/pull_request_template.md` | P1-B: how a PR is reviewed and what evidence it carries |
| `docs/master-prompts/` (uncommitted, the owner's) | The three phase prompts that started this track |

## Where things stand

- **PR #131 is merged** (merge commit `c267c82` on `main`, local `main` in sync). It carried Phase 1, the
  Phase 2 report and the approved Phase 3 milestones P0-A, P0-B (the ruleset half), P0-C (audit only),
  P0-D, P1-A, P1-B and the option B follow-up.
- **Owner decisions taken:** D1 = `superpowers:writing-skills`, made portable by option B ("if installed,
  otherwise by hand per the official skills docs", always followed by skill-audit → skill-eval). D2 =
  approved (done). D3 = audit only, decide later. D4 = drop the auto-memory route (done). D6 = approved.
  **D5 (the rejections and deferrals) was never confirmed, only not selected**, so they stay out of scope
  and are not reopened without the owner.
- **Ruleset `main-protection` (id 19737624):** 4 required checks ("Bind agreement (root, Linux, real
  proxy)", "Test suites (node + hermes bin)", "Validate skill frontmatter", "Security gate (AgentShield +
  static fallback)"), `strict` = true, 0 required approvals, review threads must be resolved,
  `require_extra_approval_for_unattributed_changes` = true. "Static scan all skills" runs but is not
  required. Rollback: PUT the first two checks only with `strict: false`.
- **Checks at merge:** node suites 24/24, Hermes bin 61/61, frontmatter 30/30 with 0 unresolved skill
  references, `ci-scan-skills.js` PASS, brain-verify OK, all 5 PR checks green.
- **Cleanup not yet done:** the merged branch `feat/phase3-software-factory-optimization` still exists
  locally and on `origin`. `git branch -d` is safe; deleting the remote is the owner's call.

## Open work, ranked by value (from the implementation record §8, updated)

1. **Fix the skill-listing overflow (D3, owner decision).** About 31 skills show by name only, including
   `codex-eval` and `superpowers:writing-skills`. GSD supplies 30% of user-level description text. While it
   overflows, skill-eval's trigger accuracy measures the listing budget, not the description. Recommended:
   option D now (`skillListingBudgetFraction`, e.g. `0.02`, or evals with a reduced skill set), then option
   B (trim GSD with `skillOverrides`, keep the 3 protective hooks after a line-level review). Option C,
   uninstall, only once the secret-read guard has a native replacement. **This edits `~/.claude`**: back up
   `settings.json` first, and it affects every project on the laptop.
2. **R8, the deferred re-eval.** skill-eval on `skill-scout` and `skill-refine` was not run (18–42 subagents
   each). Their frontmatter is byte-identical to before; only fallback text changed. The owner accepts this
   or asks for the run. Run it after item 1, or the trigger numbers are confounded. Use
   `run-manifest.js init … --subject <SKILL.md> --commit <sha>` and fill the report's Evidence and Limits
   section: that is also P1-A's first real use.
3. **Prove the merge gate blocks.** P0-B has never been seen blocking a failing PR. Proposed test: a
   throwaway draft PR with broken frontmatter, observe "Validate skill frontmatter" fail and the merge
   button blocked, then close the PR and delete its branch. Outward-facing, so confirm first.
4. **Ruleset policy (owner decision):** whether to require an approval (today 0, so human merge is a
   practice, not a rule) and whether to make "Static scan all skills" required.
5. **Template drift.** `skills/skill-eval/REFERENCE.md` and `skills/skill-eval/assets/SKILL-EVAL.template.md`
   differ (scenario counts, example rows). Reconcile them and add a test that keeps them identical.
6. **Freshness monitoring** (`CLAUDE_CODE_KNOWLEDGE.md` §5) on an existing scheduler, after the owner
   approves the cost.
7. **Measure P1-B adoption.** Target: ≥ 4 of the next 5 PRs record a rerun command and finding IDs. PR #131
   is not counted (it introduced the protocol).
8. **The post-merge-fix baseline** (Phase 2 §9, "to compute in P0") was never computed. Count `fix(...)`
   commits that reference a PR merged in the prior 7 days, over the last 60 days.

Deferred until their trigger appears (Phase 2 §8, P2/P3): improvement-intake dedupe (item 9), hook-install
backup pattern (10), dynamic-workflow eval fan-out (11), REA in a disposable VM (13), agent teams (14).

## Security items for the owner

- **An Anthropic API key in plaintext** in `infra/hermes-agent/data/home/.claude/settings.json` (the
  laptop's local Hermes container home). It is git-ignored, mode 0600, in none of the commits and was not in
  the PR. It was printed into the 2026-10-14 session transcript. **Rotate it.** Never print it again.
- **GSD's hooks** run in every session and rate BLOCK under our own static scanner (6 `child_process`
  findings). One of them, `gsd-validate-commit.sh`, rejects non-conforming commit messages in every repo.

## Known limits of what was built

- **The skill-reference resolver is precision-first.** It checks invocation forms ("invoke `x`", "use the
  `x` skill", `/x`) only. Phrasings like "with …" or unquoted names are not checked; it caught 1 of the 4
  original `writing-skills` mentions. A plugin skill must be listed in `EXTERNAL_SKILLS` in
  `scripts/validate-skills.js`, and a reference to one fails CI without a fallback within two lines.
- **P1-A is narrower than planned (R1):** no JSON evidence schema, because the reports are model-written
  Markdown with no validator. Revisit when a machine-readable eval summary exists.
- **`superpowers:writing-skills`** is enabled only at user level on the laptop. Projects set up with
  `install.sh` get no plugin; the by-hand path covers them. The Hermes box has only `playwright` and never
  runs the pipeline skills.

## What this track taught

1. **Check that a named dependency exists where the guidance runs, not only that it is declared.** P0-A
   first pointed at a plugin skill that was present only on the laptop; CI passed because it checked the
   declaration. Option B and the `no-fallback` rule came from that.
2. **Run a CLI under test from a temp directory.** A red-phase test misparsed arguments as the iteration
   directory and created three directories in the repo root (`3e4c50d` fixed it).
3. **Eval reports were being counted as agents.** `.claude/agents/*-EVAL.md` were scanned as live
   definitions; found while fixing R4. Any scan of `.claude/agents/` must exclude reports.
4. **A draft PR cannot be merged.** PR #131 was blocked only by draft status; `gh pr ready 131` fixed it.
5. **The brain security hook blocks any command naming the canon path**, even a read-only grep. Use
   `node scripts/brain/brain-search.js`.

## Rules that still apply (from CLAUDE.md and this track)

- Never commit `evals/`. The two modified `evals/*.json` files, `.obsidian/` and the `.project-brain/reports/`
  items are the owner's: leave them.
- Keep `install.sh` and `uninstall.sh` in sync; never hardcode skill counts; never edit `SKILL.md.baseline`.
- Deploy edited skills with `cp -R skills/<s> ~/.claude/skills/`.
- Canon changes only through `brain-promote --approve`.
- Codex: no `--live` in automation; never enable the plugin review gate.
- After changes: `node scripts/run-all-tests.js` and `infra/hermes-agent/bin/run-bin-tests.sh`.
- Claude Code behavior questions: follow `docs/CLAUDE_CODE_KNOWLEDGE.md` (official docs first; check the
  installed version, 2.1.300 at this writing).
- Any change under `~/.claude`, to GitHub settings, or a push or PR: confirm with the owner first.

## Suggested first move next session

Ask the owner for D3 (option D, B, or both). If D: back up `~/.claude/settings.json`, set
`skillListingBudgetFraction`, confirm in a fresh session that `codex-eval` and `superpowers:writing-skills`
show their descriptions, record the result in the GSD audit document, then offer the R8 re-eval.
