# B0 baseline record: measure before any P0 edit (2026-10-23)

> **What this is:** batch B0 of the approved P0 package (S5 §2.2; owner approval of D-01 … D-14 on 2026-10-23,
> recorded in `../2026-10-22-optimization-strategy/S6-strategic-optimization-report.md` §7.1 and in the brain daily
> note of 2026-10-23). B0 is measurement only: nothing in the project was changed. **Measured at:** `cbb6d4e` (main,
> 2026-10-23). **Governing decisions:** D-02 (measure first), D-03 (eval spend tiers; evals stop at
> `refine-input.json`), D-04 (dated tracked record here; raw data local under `evals/`).

## Summary

| B0 part (S5 §2.2) | Result |
|---|---|
| D3 skill-listing check (first, per the active D3 decision) | **Pass.** No over-budget warning at the configured 2%; a 1% control run does warn (155 skills, 40,726 chars > 30,000), so the check can fail. Headroom at 2% about 19,000 chars |
| P1-01 outcome baseline | **Accepted** by an independent reviewer (B0-R-1 … B0-R-16 closed). Detail: [`p1-01-outcome-baseline.md`](p1-01-outcome-baseline.md) |
| P1-02 telemetry validation | **Correction flag: 0 of 20 sampled flags were set by owner input**; all 20 were set by agent reports or background-task notifications. 95% upper bound on precision about 16%. Four coverage gaps (§3) |
| Pre-edit E12 evals (DECISION-S5-2) | **Not run, by owner decision** (§4); for P0-05 this is an owner-approved deviation from S5 and D-03. Evaluator file hashes recorded |
| Breach-inventory snapshot | Recorded (§5); matches the "Today" column of S5 §3 |

## 1. D3 skill-listing check

The active decision `2026-10-15-d3-skill-listing-overflow-…` says "recheck with --debug before skill-eval runs".
Method as in `docs/evaluations/2026-10-14-gsd-global-install-audit.md` §6 (verification table and "Rerun:" line): a
headless session in this repository with a debug log, then a search for the over-budget warning.

| Run | Budget | Debug log |
|---|---|---|
| `claude -p "Reply with the single word OK." --debug-file …` | 2% (user settings) | no over-budget warning |
| same with `--settings '{"skillListingBudgetFraction":0.01}'` | 1% (control) | `[WARN] Skill listing over budget: 155 skills, 40726 chars > 30000 budget — descriptions will be truncated` |

Claude Code 2.1.302. At 2% the budget is about 60,000 chars, so headroom is about 19,000 [Inf from the 1% figure].
The independent reviewer re-ran both checks and got the same result. Recheck before any eval run in P1-10.

## 2. P1-01 outcome baseline

Headline numbers (full method, windows, queries, known errors and the independent review in
[`p1-01-outcome-baseline.md`](p1-01-outcome-baseline.md)):

| Owner's measure | B0 number |
|---|---|
| First-pass acceptance (delivery) | 5 of 16 determinable PRs (31%); 46 of 62 reviewed PRs not determinable |
| Numbered review findings per reviewed PR | median 12 (n = 29); first-round blocking findings median 1 (n = 16) |
| Post-merge fix of the PR's own change | 7 days: 6 of 138 (4.3%), found after merge 4 of 138 (2.9%); 30 days: 1 of 37, known at merge, 0 found after |
| Spec or plan → implementing PR merge | median 0.84 days (n = 62); mostly time on one branch |
| Review rounds per PR | median 2 (n = 61); 108 of 170 PRs record no PR review |
| Files / lines per PR | median 3.5 files, 176 lines |
| Context footprint (skill-eval definition) | `skills/` SKILL.md only: median 61 lines (about 244 tokens); with bundled files median 75.5 |
| Definition count (dynamic) | 56 (30 skills, 16 agents, 1 project skill, 3 pack skills, 6 Hermes skills) |
| Prompts per PR-producing session | not measurable until P1-03 |

## 3. P1-02 telemetry validation

**Run.** `node scripts/telemetry/aggregate-usage.js` once, at 2026-10-23T16:06:15Z (its `generated_at`; writes the
gitignored `evals/telemetry/usage-summary.json`): 23 targets; 2,506 events (1,210 invocations, 519 outcomes, 777
session ends; July to October). It flagged REFINE_RECOMMENDED for `general-purpose` and created
`evals/agents/general-purpose/refine-input.json` with a `real_usage` block (`aggregate-usage.js:234-254`, which has no
filter for project definitions). `general-purpose` is Claude Code's built-in agent, not a project definition, so the
flag is noise. No refine was invoked.

**How the flag works.** `scripts/telemetry/log-outcome.js` (`handleCorrection`, lines 98-151) runs in the
UserPromptSubmit hook. It writes an outcome event, timestamped at that moment, when the submitted prompt matches
`REVISION_RE` (`:38`: fix, fixed, redo, wrong, instead, actually, change, "no,", …) and names a file the session's most
recent invocation produced. Every one of the 519 outcome events carries `followed_by_correction: true`: 509 for
`general-purpose`, 3 skill-eval-agent, 3 Explore, 2 codex-rescue, 2 claude-code-guide. Skills never get an outcome
event: 136 of 136 skill invocations before the cut-off carry no artifacts, and the flag requires artifacts
(`log-outcome.js:107-110`).

**Precision check.**
- **Sample:** 20 events drawn by [`scripts/p1-02-sample.js`](scripts/p1-02-sample.js) (seeded shuffle, seed 20261023,
  cut-off 2026-10-23T16:08:04Z) from the 366 outcome events whose session transcript still exists locally. All 20
  are `general-purpose`.
- **Method:** [`scripts/p1-02-trigger-class.js`](scripts/p1-02-trigger-class.js) finds the input submitted at each
  event's exact timestamp (-1.5 s … +1.8 s; user entries including system-marked ones, queued commands, and queue
  operations) and classifies its source without printing any text.
- **Result:** none of the 20 flags was set by owner input.
  - All 20 were set by an agent's report arriving or a background-task notification, and each of those inputs
    contains a `REVISION_RE` word: 14 agent report plus notification, 4 agent report, 2 notification.
  - No owner-typed input appears at any of the 20 trigger times.
  - So no sampled flag is a human correction: **precision 0 of 20**. The 95% upper bound is about 16% (Wilson, n = 20).
  - The S1 L-06 assumption ("49% flag rate, meaning unknown") is answered for `general-purpose`: on this sample the
    flags are agent traffic, not corrections.
- **Superseded first attempt:** the first method showed the owner the first *visible* message after each flag.
  For 18 of 20 that message came 5 minutes to about 19 hours later and was not the input that set the flag, because
  the method skipped system-marked entries and compared times to the minute. The owner labelled those messages "not a
  correction" (12 rows, 9 distinct owner messages). Those labels are kept in
  [`data/p1-02-sample.csv`](data/p1-02-sample.csv) as superseded columns and are not used for the result.

**Matcher coverage** (PostToolUse matcher `Skill|Task`, `.claude/settings.json`; `log-invocation.js:88-92` logs
only the tools `Skill`, `Task` and `Agent`):

| Invocation path | Recorded? | Evidence |
|---|---|---|
| Agent launched with the Agent tool | yes | caught by the `Task` matcher (observed); 7 invocation events in this session between 13:55 and 16:26 UTC on 2026-10-23, matching the coordinator's own count of 7 launches |
| Agent continued with SendMessage | **no** | not logged by design (the matcher and `log-invocation.js` exclude it); the coordinator counted 14 continuations in the same window, none logged |
| Skill started by the model (Skill tool) | yes | headless control run: one `invocation` event; its debug log shows `PostToolUse:Skill` and `log-invocation.js` |
| Skill typed by the user as a slash command | **no** (headless `-p` only) | headless run of `/superpowers:using-superpowers`: the command expanded, no Skill tool call, no invocation event. Not tested interactively |

So telemetry undercounts agent work (continuations) and skills the owner types, and the outcome flag covers agents
only.

## 4. Pre-edit evals: not run (owner decision, 2026-10-23)

DECISION-S5-2 (D-03) planned pre-edit E12 runs where a delta would be claimed: the repo-audit ensemble team-eval, the
skill-scout-agent agent-eval and the skill-scout skill-eval. The owner chose to skip all three, because each would
deliberately exercise the breaches P0 fixes:
- the repo-audit team-eval targets a live repository (`fixtures/teams/repo-audit-ensemble/team.json`:
  `https://github.com/expressjs/express`), runs unpinned `npx repomix` (and possibly `pip install gitingest`),
  has 8 analysts with Bash read third-party code, and writes into `docs/audits/`;
- the skill-scout runs feed fetched third-party SKILL.md bodies to agents holding Write and Bash. An eval run spawns
  18-42 subagents (S5 P1-10), and each scout run fetches registry pages and candidate SKILL.md bodies
  (`.claude/agents/skill-scout-agent.md:58-75`), so a run would repeat that exposure many times [Inf].

Consequences:
- **P0-03:** allowed by S5 ("If a delta is to be claimed, run team-eval before the edit in B0 … otherwise absolute
  thresholds"). P0-03 is judged on its absolute thresholds.
- **P0-05:** a deviation from S5 (P0-05 Baseline: "measure in B0 (DECISION-S5-2)") and from D-03 as approved, which
  the owner approved on 2026-10-23 (brain daily note 2026-10-23, decision "B0: pre-edit evals skipped by owner
  decision"; local, to be compiled). P0-05 is judged on its absolute agent-eval thresholds (dispatch accuracy ≥ 85%, resilience ≥ 8/10) plus
  its ranking comparison on a fixed fixture set (S5 P0-05 Acceptance).
- No measured before/after delta is claimed for P0-03 or P0-05. The post-edit runs in P1-10 become the first baselines.

Evaluator files at `cbb6d4e` (sha256), recorded so P0-11's pin can be checked against them (V-S5-5):

| File | sha256 |
|---|---|
| `skills/skill-eval/scripts/harvest-evidence.js` | `1ce61bc59a98e0f686575b6dfb735efc1220bc57043b900cd4960a7bda6b2646` |
| `skills/skill-eval/scripts/run-manifest.js` | `4bd2551cbd803ac35ac804357b2318f12fabe0eaf4fd2f56e11567ecba62f340` |
| `skills/skill-eval/scripts/generate-seed-evals.js` | `3d09efd21d4cc9eef86dff78d80d35d2fb5fd8fba5a88e28e00da935b14ce4dc` |
| `skills/agent-eval/scripts/generate-agent-evals.js` | `7325c25cd05be19940a827e7d1bb9a561813f926603b4ef85f7c6b583e9f1100` |
| `skills/skill-eval/REFERENCE.md` | `3e461df6290a7607e661efe5bdc304315129f8fd99f51b6f2cf3b159c6114c76` |

Also found: of the 27 committed SKILL-EVAL reports that state a footprint, only 4 match today's SKILL.md line counts,
so the old reports cannot serve as baselines either (P1-01 metric 5).

## 5. Breach-inventory snapshot (mandatory-criterion indicators, S5 §3)

| Indicator | B0 value at `cbb6d4e` | How measured |
|---|---|---|
| Write-capable agents reading untrusted text directly | **10**: 8 repo-audit analysts (Read, Bash), skill-guardian (Write, Edit, Bash, WebFetch), skill-scout-agent (Write, Bash, Agent, WebFetch) | `tools:` frontmatter in `.claude/agents/`, checked against the S3 §2.4 untrusted-reader inventory |
| Unpinned runtime installs in shipped paths | **3 executed**: `skills/repo-audit/SKILL.md:35,55` (`npx repomix`), `:61` (`pip install gitingest`); plus 1 unpinned instruction to the user, `skills/project-audit/SKILL.md:180`. project-audit's own commands are pinned (`@1.4.0`, `:46,52,58,168`) | grep of `skills/` and `.claude/agents/`; `packs/`, `infra/hermes-agent/skills/` and `.claude/skills/` also searched, 0 hits |
| PRs merged without the owner's code-owner approval of the merged head (last 10) | **10 of 10** (#165-#174: authored and merged by the owner's account, no review decision; no CODEOWNERS file) | `gh pr list --state merged --limit 10` |
| Model-run deploy steps to `~/.claude/skills` in definitions | **3 steps + 1 sanction**: `skills/skill-adapt/SKILL.md:84`, `skills/skill-refine/SKILL.md:60`, `.claude/agents/skill-refine-agent.md:124`; `CLAUDE.md:75` | grep |
| Guard fail-open entries | **50**, all dated 2026-10-15 | `.project-brain/reports/guard-failures.log`, a local gitignored log (`.gitignore:24`), not part of `cbb6d4e`; unchanged since 2026-10-15 |
| Definitions with a post-E12 eval report | **0** (30 committed eval reports: 29 SKILL-EVAL and 1 AGENT-EVAL, `.claude/agents/skill-eval-agent-EVAL.md`; the latest dated 2026-07-16) | `git log` per report |

## 6. Follow-ups found (not decided here)

1. **PR template: state the first-round review outcome.** Since PR #131 the bodies rarely say whether the first
   round found blocking issues (2 of 33 reviewed PRs since #131 determinable), so first-pass acceptance cannot be
   tracked from PR text. Candidate for P1-04 or P1-08.
2. **Telemetry coverage:** SendMessage continuations and slash-typed skills are not logged; skills get no outcome
   events. Relevant to P1-03 (prompt counts).
3. **Correction flag:** on the sample it is set by agent reports and notifications, not by the owner (20 of 20).
   Exclude agent and notification traffic, or retire the flag, before it is used in any measure (P1-02 follow-on).
4. **Aggregator:** it recommends refining Claude Code's built-in `general-purpose` agent; it should skip targets that
   are not project definitions.
5. **Raw-data location:** `evals/baselines/` is not covered by `evals/.gitignore`. The raw B0 data there is untracked
   but not ignored; P0-04's `evals/.gitignore` edit can add it.

## Data and reproduction

- Committed: [`data/`](data/) (hand-coded inputs, derived tables, summaries, the P1-02 sample with trigger classes)
  and [`scripts/`](scripts/).
  - P1-01: `scripts/run.sh <repo-dir> <data-dir> [--refetch]`.
  - P1-02 sample: `node scripts/p1-02-sample.js <repo-dir> 2026-10-23T16:08:04Z [<transcripts-dir>]`.
  - P1-02 trigger classes: `node scripts/p1-02-trigger-class.js data/p1-02-sample.csv [<transcripts-dir>]` (reads the
    owner's local transcripts; prints classes only, never text).
- Local only: `evals/baselines/2026-10-23-b0/` (fetched PR JSON and bodies, review excerpts, pre-review versions).
- No prompt or transcript text is stored in this folder. The P1-02 data holds session IDs, times, source classes and
  labels only.

## Limits

- One coder did the P1-01 hand coding; an independent reviewer re-coded samples (see p1-01).
- The P1-02 frame covers only 2026-09-22 … 2026-10-23 (older transcripts no longer exist locally): 366 events from 17
  sessions. The 20 draws come from 9 sessions (4 from one session, 3 each from two others). All are `general-purpose`,
  so the result is about this flag on that agent.
- The slash-command coverage result is from headless `-p` runs only.
- B0 windows end at `cbb6d4e`; 30-day figures rest on 37 PRs.
- The pre-edit evals were not run, so no before/after delta can be claimed for P0-03 or P0-05.

## Review corrections (2026-10-23)

An independent reviewer checked this record (findings B0-RM-1 … B0-RM-13). Changes made:
- B0-RM-1: the P1-02 result now rests on the input at each flag's exact timestamp (`p1-02-trigger-class.js`); the
  first method (next visible message) is described as superseded and its labels kept only as superseded columns.
- B0-RM-2: the quoted owner message was removed.
- B0-RM-3: the D3 method cites gsd-audit §6.
- B0-RM-4: P0-05's skip is stated as an owner-approved deviation, recorded in the brain daily note; its absolute
  thresholds are named.
- B0-RM-5: the "20-40" figure was replaced by a derivation marked [Inf].
- B0-RM-6: matcher evidence now cites the code and matcher; the 7 and 14 counts are labelled as the coordinator's own;
  the slash result is marked headless-only.
- B0-RM-7: the reproduction commands cover the trigger classifier, which reads the committed CSV and full timestamps.
- B0-RM-8: the sample frame's limits were added (the reviewer's "8 sessions" recounted as 9).
- B0-RM-9: the aggregator time, "created", and why skills get no outcomes were added.
- B0-RM-10: report counts corrected (27 that state a footprint; 30 committed eval reports).
- B0-RM-11: follow-up 1 says "rarely", with the count.
- B0-RM-12: the verification figures were moved to p1-01's review section, where they now trace.
- B0-RM-13: the §5 "How measured" cells were completed.
- B0-RM-14: the trigger classifier now also reads `queue-operation` entries; #18's input is an agent report plus
  notification, so all 20 flags were set by agent traffic (precision 0 of 20, upper bound about 16%). The
  brain-note citation is marked local, to be compiled.
