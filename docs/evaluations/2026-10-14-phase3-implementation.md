# Phase 3: implementation record (software-factory optimization)

> **Date:** 2026-10-14 · **Branch:** `feat/phase3-software-factory-optimization`, from `main` at `caed884`
> **Scope:** the milestones approved for Phase 3: P0-A, P0-B, P0-C (audit only, D3), P0-D (D4: drop the route), P1-A and P1-B, with D1 = `superpowers:writing-skills`.
> **Out of scope:** everything else in the Phase 2 roadmap. The §4 rejections and deferrals were not selected.
> **Plan and decisions:** `docs/evaluations/2026-10-14-software-factory-architecture-evaluation.md`
> **Runtime:** Claude Code 2.1.300.

## 1 · Milestones

| Milestone | What changed | Evidence | Status |
|---|---|---|---|
| **M0** baseline | Branch created; Phase 1 and the Phase 2 report committed | Baseline: node 22/22, Hermes bin 61/61, frontmatter 30/30, `main` = `origin/main` | done |
| **P0-A** generate exit | 6 live `write-a-skill` references now name `superpowers:writing-skills`, followed by skill-audit → skill-eval. agent-scout's inline-agent fallback now goes through agent-audit → agent-eval. `validate-skills.js` gains a skill-reference resolver plus `EXTERNAL_SKILLS` | `scripts/validate-skills.test.js` (14 tests). A dangling fixture makes the CLI exit 1. Repo: 0 unresolved. Skills deployed to `~/.claude/skills/` | done; **one item untested** (§3) |
| **P0-B** merge gate | Ruleset `main-protection` (id 19737624): added the required checks "Validate skill frontmatter" and "Security gate (AgentShield + static fallback)", and set `strict` = true | API read-back diff: exactly those 5 fields changed, nothing else. Both jobs run on every PR to `main` (no path filters, no job-level `if`) | done; **end-to-end PR proof pending** (§3) |
| **P0-C** GSD audit and listing measurement | `2026-10-14-gsd-global-install-audit.md`. Nothing under `~/.claude` changed | Static scan of `~/.claude/hooks`: BLOCK (6). 15 registered scripts classified. About 31 skills listed without descriptions, caused by budget overflow, not overrides | done (D3: the owner decides options A–D) |
| **P0-D** registry and memory route | `--use`/`--risk`: one value per flag, kept verbatim, repeatable; a flag is refused as a value. Three fragmented entries rejoined, with `last_reviewed` unchanged. The capsule BRAIN.md and MEMORY.md drop the auto-memory route; the templates are unchanged | `brain-reference-repo.test.js` (new assertions); brain-verify OK; brain-lint shows 0 security findings | done |
| **P1-A** evidence fields | `run-manifest.js init --subject <file> --commit <sha>` records the definition's sha256 and commit, with strict flag validation. An **Evidence and Limits** section added to the SKILL-EVAL and AGENT-EVAL templates (inline and asset copies) and to the team-eval report instruction | `scripts/run-manifest.test.js` (9 tests) | done, **narrower than planned** (§3) |
| **P1-B** review protocol | `docs/REVIEW_PROTOCOL.md`, `.github/pull_request_template.md`, and a one-line pointer in CLAUDE.md | Codifies the practice in PR #130. Applied to this branch: an independent review found R1–R8 | done; **adoption metric pending** (§3) |
| Review fixes | R2–R7 fixed, each with a test. Also found and fixed: agent eval reports in `.claude/agents/` were scanned and counted as agents | `c417953` | done |

## 2 · Validation (final run, this branch)

| Check | Result |
|---|---|
| `node scripts/run-all-tests.js` | 24/24 (baseline 22/22; adds `validate-skills.test.js` and `run-manifest.test.js`) |
| `infra/hermes-agent/bin/run-bin-tests.sh` | 61/61 (unchanged) |
| `node scripts/validate-skills.js` | 30/30 frontmatter; skill references: 0 unresolved |
| `node scripts/ci-scan-skills.js` | PASS: no unmatched BLOCK, no stale baseline entries, no new baseline exception |
| `brain-verify` / `brain-lint` | OK / 0 security findings (1 pre-existing stale-canon warning) |
| Frontmatter of every edited skill and agent | byte-identical to `main`, so trigger and dispatch inputs are unchanged |
| Independent review (subagent, per the protocol) | re-ran all checks and reproduced them. R1–R8 minor, nothing blocking. R2–R7 fixed; R1 and R8 recorded below |

## 3 · Untested, narrowed, or pending (stated, not hidden)

- **R8, P0-A metrics.**
  - The planned skill-eval re-run of skill-scout and skill-refine was **not run**, because a full run is 18–42 subagents per skill.
  - Mitigation: the frontmatter is byte-identical, and only the no-candidate fallback text changed.
  - **Owner to accept, or to request the re-run.**
- **P0-B end to end.** "A PR with invalid frontmatter is blocked" is not yet observed. This branch's own PR will be the first run under the new required checks.
- **R1, P1-A narrowed.**
  - No JSON evidence schema was added: the reports are model-written Markdown, so a schema would have no producer or validator.
  - Recorded in the Phase 2 report's §8 implementation note.
- **P1-B adoption.** The success metric ("≥ 4 of the next 5 PRs record a rerun command and finding IDs") can only be measured on future PRs.

## 4 · Before and after (against the Phase 2 baselines)

| Metric | Before | After |
|---|---|---|
| Dangling skill references (live guidance) | 7 | **0**, enforced in CI |
| Required checks on `main` / strict | 2 / false | **4 / true** |
| Generated skills and agents routed back through audit → eval | no | **yes** (skill-scout, skill-refine, agent-scout) |
| Eval reports stating the evaluated revision, untested items and limits | no field | **template section plus pinned manifest** |
| Unaudited global hooks | ~18 registrations, no record | **audited (BLOCK, classified)**; the decision is pending (D3) |
| Skill descriptions dropped from the listing | unknown | **measured: about 31** (unresolved; D3 options) |
| Fragmented registry entries | 3 | 0 |
| Contradictory memory routes | 1 | 0 |
| New services, daemons, orchestrators or dependencies | 0 | **0** |

## 5 · Remaining risks and technical debt

1. **The skill-listing overflow is unresolved.** Skill-eval trigger accuracy stays confounded until an option from the GSD audit is chosen. The cheapest is `skillListingBudgetFraction`.
2. **The resolver is precision-first.** Unquoted, single-word and other phrasings are not checked. A future prose false positive gives a clear CI line to fix.
3. **Template drift.** `skills/skill-eval/REFERENCE.md` and `assets/SKILL-EVAL.template.md` already differed before Phase 3: scenario counts and example rows. The Evidence and Limits block was added to both, but the drift remains.
4. **The ruleset requires 0 approvals.** Human merge is a practice, not an enforced rule. "Static scan all skills" runs but is not a required check. Both are owner decisions.
5. **`strict` = true.** PRs must be rebased or merged when `main` moves, so merges are slower.

## 6 · Deferred and rejected (unchanged by Phase 3)

- **Deferred:**
  - improvement-intake dedupe (item 9);
  - the hook-install backup pattern (item 10);
  - dynamic-workflow eval fan-out (item 11);
  - freshness automation (item 12);
  - REA, in a disposable VM, only on a real use case (item 13);
  - agent teams (item 14).
- **Rejected:**
  - the Super-Board runtime and Reviewer self-merge;
  - greploop/Greptile;
  - Rezvani's generators and hooks;
  - before-and-after and unslop;
  - the two-factory subsystem.

## 7 · Maintenance procedures

| When | Do |
|---|---|
| A skill or agent text references another skill | CI resolves it. For a plugin skill, add it to `EXTERNAL_SKILLS` in `scripts/validate-skills.js`, with the reason |
| Starting an eval iteration | `run-manifest.js init … --subject <definition> --commit <short sha>`; fill **Evidence and Limits** in the report |
| Reviewing a PR | `docs/REVIEW_PROTOCOL.md`: re-run the checks at a named SHA, number the findings, and only the reviewer closes them |
| A Claude Code question or upgrade | `docs/CLAUDE_CODE_KNOWLEDGE.md` §4 protocol; re-run the Phase 1 smoke queries after an upgrade |
| Registering a source | `brain-reference-repo-add.js … --use "one item" --use "another"` (one item per flag) |
| Rollback | Each milestone is its own commit, so revert the commit. Ruleset: PUT the pre-change state (required checks "Bind agreement" and "Test suites" only, `strict_required_status_checks_policy: false`) |

## 8 · Recommended next improvements (ranked by value)

1. **Resolve the listing overflow** (GSD audit option D, then B). It unblocks valid trigger metrics. Owner decision; it is a settings change.
2. **Run the deferred R8 re-eval** on skill-scout and skill-refine with the new `--subject` pinning. This doubles as the first real use of the Evidence and Limits section.
3. **Decide the ruleset's approval count and whether to require "Static scan all skills".**
4. **Reconcile the skill-eval template drift** (inline vs asset), with a test that keeps the two copies identical.
5. **Freshness monitoring** (Phase 1 §5) on an existing scheduler, once the owner approves the cost.
