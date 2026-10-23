# Factory outcome baseline (B0, roadmap item P1-01)

- **Status:** accepted on 2026-10-23 by an independent reviewer after three rounds (B0-R-1 … B0-R-16, all closed;
  see "Review corrections"). Part of the B0 record in [`README.md`](README.md).
- **Measured at:** `cbb6d4e04dc22f72c274e7b44c9740a8a2e2f165` (main, commit time 2026-10-23T16:03:32Z).
- **Measured on:** 2026-10-23. PR data was fetched from GitHub the same day with read-only `gh` GET calls.
- **Definitions used:** S5 roadmap §1.2 P1-01 and the §3 "Measurement plan" rows whose Baseline is "B0";
  the 10-14 proxy at `docs/evaluations/2026-10-14-software-factory-architecture-evaluation.md:265`;
  the footprint metric from `skills/skill-eval/SKILL.md:96` and `:21`.
- **Data and scripts:** the hand-coded inputs and derived tables are in [`data/`](data/); the scripts are in
  [`scripts/`](scripts/) (`run.sh <repo-dir> <data-dir> [--refetch]`). The fetched PR JSON and bodies are kept
  locally, not committed, in `evals/baselines/2026-10-23-b0/` (re-fetchable with `--refetch`; bodies may change).
  Pre-review versions are in that local folder's `superseded-v1/`.

## Headline numbers

| # | Metric | B0 number | Window | Main known error |
|---|---|---|---|---|
| 1 | First-pass acceptance (delivery) | **5 of 16** PRs whose body states the first-round outcome (31%). 46 of the 62 reviewed PRs are not determinable. Using the linked review record too: 11 of 25 (44%) | PRs merged 2026-08-01T00:00Z … 2026-10-23T16:03:32Z (170) | since 2026-10-15, bodies rarely state severities (31 of 33 reviewed PRs not determinable); one coder |
| 1 | Numbered review findings per reviewed PR | median **12** (p25 7, p75 15, max 34), n = 29 PRs that name ID ranges; blocking findings in the first round: median **1** (p75 2, max 6), n = 16 | same | ID ranges can span rounds; before #131, findings are rarely numbered (1 PR) |
| 2 | Post-merge fix of the PR's own change, 7 days | **6 of 138** (4.3%), 7 with one unreferenced plausible case (5.1%); of these, **found after merge: 4 of 138** (2.9%) | PRs merged 2026-08-01T00:00Z … 2026-10-16T16:03:32Z (complete 7-day window) | reference-based and hand-confirmed: it misses fixes that do not cite the PR; the path-matched count (79 of 138) overcounts |
| 2 | Post-merge fix of the PR's own change, 30 days | **1 of 37** (2.7%), known at merge; **0 of 37** found after merge | PRs merged 2026-08-01T00:00Z … 2026-09-23T16:03:32Z (#5–#41) | only 37 PRs have a full window |
| 2 | 10-14 proxy, literal | 291 `fix(...)` commits landed in the 60 days. **2** of their messages cite a PR merged in the prior 7 days (1 is a real fix of it). Counting the landing PR's text: 54 commits in 14 PRs; **6 of the 14 pairs** fix the cited PR, **4** of them after merge | 2026-08-24T16:03:32Z … 2026-10-23T16:03:32Z | most `fix(...)` commits are review fix-ups that land with their own PR |
| 3 | Spec or plan first commit → implementing PR merge | median **0.84 days** (p25 0.10, p75 2.85, max 28.87), n = 62 | files at `cbb6d4e`; matched first commits 2026-07-23 … 2026-10-21; merges 2026-08-05 … 2026-10-21 | 60 of the 64 matches are the same PR that added the file, so this mostly measures time on one branch; specs not yet delivered are excluded |
| 4 | Review rounds per PR | median **2** (p25 1, p75 3, max 6), n = 61; before #131: median **1** (n = 29); from #131: median **3** (n = 32). 108 of 170 PRs have no PR review recorded | 170 PRs | the meaning of "round" changed at #131 |
| 4 | Prompts per PR-producing session | **not measurable** until P1-03 | — | — |
| 5 | Files / lines per PR | median **3.5 files, 176 lines**; code-touching PRs: median 8 files, 428 lines | 170 PRs | the docs/code split is by `.md` extension only |
| 5 | Path-matched follow-up `fix` PRs within 30 days | 17 of 37 PRs (46%, PR level; commit level 16); 14 of 37 on a shared non-`.md` path | complete 30-day windows | overcounts: 2 of 20 sampled pairs plausible |
| 5 | Context footprint (skill-eval definition) | `skills/` (30 skills): SKILL.md median **61 lines ≈ 244 tokens**, max 433; with bundled files median 75.5 lines ≈ 302 tokens, max 2,255 ≈ 9,020 tokens | tree at `cbb6d4e` | the definition does not settle which bundled files load on trigger; two variants reported |
| 5 | Definition count | **56** (30 + 16 + 1 + 3 + 6, see metric 5) | tree at `cbb6d4e` | counts entries, not quality or use |

## Method

**Population.** Every PR merged into `main` from 2026-08-01T00:00:00Z up to the commit time of
`cbb6d4e`: 170 PRs, #5 to #174. Each is a two-parent merge commit on `main`'s first-parent line.
Since 2026-08-01 nothing reached `main` except through these merges:
`git log --first-parent --no-merges --since=2026-08-01 cbb6d4e` returns 0 commits. Times are UTC.
89 of the 170 PRs are Hermes work (they touch `infra/hermes-agent/` or say "hermes" in the title),
so one workstream dominates the baseline.

**Sources, read-only.**
- GitHub:
  `gh pr list --state merged --limit 500 --json number,title,mergedAt,createdAt,headRefName,mergeCommit,additions,deletions,changedFiles,author`
  and, for each PR,
  `gh pr view <n> --json number,title,body,mergedAt,createdAt,mergeCommit,additions,deletions,changedFiles,files,reviews,comments,commits,headRefName,baseRefName`
  (`p1-01-scripts/fetch.sh`). The JSON is kept in `p1-01-data/` because a later edit to a PR body
  would change the input.
- git at `cbb6d4e`: `git log`, `git diff`, `git ls-tree`, `git cat-file`, `git show`,
  `git merge-base --is-ancestor`, `git rev-parse`. Nothing under `infra/hermes-agent/data` was read;
  the script asserts that no path set contains it.

**What a PR changed.** `git diff <merge>^1 <merge>`, the change the merge brought to `main`. Sizes
use rename detection (`-M`). They equal GitHub's additions, deletions and changedFiles for all 170
PRs; the script checks all three fields. The path sets used for fix attribution use `--no-renames`,
so the old and the new name of a moved file both count.

**When a commit landed.** The merge time of the PR that brought it to `main`
(`git log --no-merges <merge>^1..<merge>^2`). Each commit lands exactly once.

**Hand-coded inputs.** One coder did all three: the author of this draft. A reviewer re-checked
them (B0-R-1 … B0-R-9).
- `p1-01-data/review-coding-manual.csv` (read by `measure.py`): how each PR body records its
  review, with columns for rounds and numbered findings (metrics 1 and 4). PRs not listed record no
  review. The coder worked from `review-excerpts.txt` and `review-context.txt` (made by
  `extract_review_text.py`), plus the full bodies where an excerpt was unclear (#19, #20, #23).
  `review-missed-check.txt` is a second keyword pass over the other PRs.
- `p1-01-data/spec-plan-match-verification-manual.csv` (read by `verify.py`): a verdict for each
  automatic spec/plan match that is not plainly right (metric 3). Matches not listed were checked
  and judged correct.
- `p1-01-data/fix-attribution-validation-manual.csv` (read by `verify.py`): a verdict for every pair
  matched by reference, every pair in the 60-day proxy, and a seeded random sample of 20 pairs
  matched by path (metric 2).

**Re-run.** `p1-01-scripts/run.sh <repo> <data-dir>` checks that `cbb6d4e` exists, regenerates the
excerpts, then runs `measure.py` (git plus the saved JSON) and `verify.py`. It writes
`summary.json`, `verify-summary.json` and the per-row CSVs. `--refetch` pulls fresh PR JSON first.
The scripts are stdlib Python 3 and bash; run Python with `-I`.

## Metric 1 — First-pass acceptance (delivery)

**How PR bodies record reviews.** No PR has a GitHub review object: `reviews` is empty for all 170.
Reviews are written in the PR body, in four styles:
1. **August to early October, Superpowers subagent-driven development** (16 PRs coded `sdd`).
   Per-task reviews with fix loops, then a whole-branch ("final") review, sometimes followed by a
   fix wave and a re-review. When severities are given, the scale is Critical / Important / minor.
2. **Single independent review, early to mid October** (e.g. #97, #99, #100, #123, #130). One
   reviewer gives a verdict ("Approved", "with fixes", "APPROVE"), sometimes with counts per severity.
3. **From #131 (2026-10-15)**, after `docs/REVIEW_PROTOCOL.md` was added in `4ec1ae6`. Bodies say
   "Independent review, N rounds (ID range), final verdict approve". The protocol asks for a
   blocking / minor severity on each finding, but the bodies give only the number of rounds and
   the ID range. For several PRs the per-round detail is in
   `docs/evaluations/2026-10-15-pr4-hermes-proposal-triage.md`.
4. **Unfilled template:** #132, #133 and #135 contain only the placeholders of the template's
   "Review" section.

Not counted as PR reviews:
- Hermes "security review #N", which audits the server, not the PR.
- The brain "weekly review".
- PR comments: 5 PRs have one. The comment on #30 is a review, see the known errors.

**Definitions.**
- *Review recorded:* the body says someone other than the author reviewed this PR's change: an
  independent reviewer, a subagent reviewer, a whole-branch or final review, or an Opus review.
  Listed apart (B0-R-8, B0-R-10):
  - automated review only: #115;
  - review of the design spec only: #35;
  - template placeholders: #132, #133, #135;
  - a content review whose reviewer is not identified: #134, #136, #141.
  
  #26 is recorded in #27 as merged without independent review.
- *First review round:* the first round of the review of the whole change. For `sdd` PRs that is the
  whole-branch review. Per-task reviews happen during development and are reported in a separate
  column (`any_round_blocking_incl_per_task`).
- *Blocking:* the body calls a finding Critical, Important, blocking or a blocker, or says it must be
  fixed "before publishing", or the round's verdict is "request changes" (or "with fixes" alongside
  Important findings).
- *Not blocking:* minor, nit, cosmetic, "none blocking", or a round stated as approved, clean or
  passed **with no fix reported after it** (B0-R-1 applies this clause to #100 and #145).
- *Not determinable (ND):* everything else. The common cases are "N rounds, findings X1–Xk closed,
  approve" with no severity, and "found and fixed defects" with no severity. ND is never inferred
  from the number of rounds.

**Numbers** (`summary.json` → `metric1_first_pass`; per-PR rows in `review-coding-population.csv`):

| | PRs |
|---|---|
| Population | 170 |
| PR review recorded | 62 |
| No PR review recorded | 108: 100 with none, 3 placeholders, 1 automated-only, 1 spec-review-only, 3 unattributed |
| Reviewed, first round **0 blocking** | **5** (#5, #97, #99, #123, #131) |
| Reviewed, first round **≥ 1 blocking** | **11** (#8, #16, #19, #25, #61, #62, #69, #102, #105, #130, #144) |
| Reviewed, **not determinable** | **46** |

- **First-pass acceptance, determinable PRs only: 5 / 16 = 31%.** Bounds over all 62 reviewed PRs:
  5/62 = 8% if every ND counts as blocking, up to 51/62 = 82% if every ND counts as clean.
- **With the linked review record:** the triage document above, at `cbb6d4e`, used only where the
  body points to it. Result: 11 with 0 blocking, 14 with ≥ 1, 37 ND, so 11 / 25 = 44%.
  - It resolves #142, #143 and #149 as ≥ 1 blocking.
  - It resolves #146, #147, #162, #163, #165 and #166 as 0 blocking in round 1. In #162, a later
    round (round 3) had a blocking finding.
- **By period:**
  - Before #131: 29 of 126 PRs record a review; 4 of the 14 determinable had 0 blocking.
  - From #131: 33 of 44 PRs record a review, but only 2 are determinable (1 with 0, 1 with ≥ 1).
  - Since the review protocol arrived, reviews are recorded far more often, but the body almost
    never states the first-round outcome.
- **By PR type:** code-touching PRs: 53 of 83 reviewed (5 with 0, 9 with ≥ 1, 39 ND). Docs-only
  PRs: 9 of 87 reviewed.
- **Including the per-task reviews of `sdd` PRs:** 4 with 0, 11 with ≥ 1, 47 ND.

**Numbered findings per reviewed PR** (B0-R-3; `summary.json` → `metric1_first_pass.numbered_findings`;
columns `findings_ids`, `findings_count_ids`, `findings_count_stated` and `first_round_blocking_count`
in the coding CSV):
- **From ID ranges in bodies:** 29 PRs, median **12**, p25 7, p75 15, p90 20.4, max 34 (#149),
  mean 12.03. One of these PRs is before #131 (#42, 2 findings); 28 are from #131 (median 12).
  - Counting rule: each named series counts up to its highest index, e.g. K1–K7 = 7,
    "N1 and N4–N7, N9, N10" = 10, "P1–P8 and P10–P12" = 12.
  - Only review-finding series count. Hermes findings-document IDs (F26–F43 …) are not review
    findings, and neither are the research IDs in #172–#174.
- **Counts stated in words, no IDs:** 5 PRs, median 7, max 17 (#61, #62, #102, #123, #130).
  - Combined with the ID counts: 34 PRs, median 10, p75 14.75, max 34.
- **Blocking findings in the first round, where the body states them:** 16 PRs, median **1**, p75 2,
  max 6 (#69). Distribution: 0 → 5 PRs, 1 → 5, 2 → 3, 3 → 2, 6 → 1.
- **Not stated:** 28 of the 62 reviewed PRs give neither IDs nor a count.

**Query.** `fetch.sh`, then `extract_review_text.py`, then the hand coding, then `measure.py`
(section "metrics 1 / 4"). The keyword sets are in `extract_review_text.py`.

**Known error.**
- One coder, unblinded; the reviewer re-checked the coding.
- The 0-blocking code for #5 rests on wording: its final whole-branch review "passed" and no fix
  is reported after it. Coded ND instead, the rate becomes 4/15 = 27%.
- **#30 (B0-R-2):** the body says the final whole-branch review "returned clean". But a PR comment
  posted 2026-09-20, before the 2026-09-21 merge, is a "Claude Code review" with 3 findings: one
  "Normal", two "Nit". #30 is therefore coded ND.
- Other review comments, if any, are not read.
- Severity scales differ by era:
  - Critical / Important / minor;
  - blocking / minor;
  - one "major" in the linked record, coded ND.
- "Important" is treated as blocking because the Superpowers `requesting-code-review` skill says
  "Fix Important issues before proceeding" (`SKILL.md:44` in the installed plugin versions 6.4.1
  and 7.0.0).
- Finding IDs often span several rounds, so an ID count is the number of findings across the
  review, not per round. The highest index can also overcount when IDs are skipped.
- The body is written by the implementing session. That a stated review happened is taken as
  given; it is not verified here.

## Metric 2 — Defect / rework frequency

**Definitions.**
- *Fix commit:* the subject matches `^fix(\([^)]*\))?!?:` (conventional commit).
- *Fix PR:* the title matches `^fix\b`, case-insensitive.
- *Post-merge:* the fix landed on `main` after PR X merged and within W days (W = 7 or 30), and X
  itself did not land it.
- *Attribution to X*, four ways:
  - **path:** the fix touches at least one file X changed;
  - **path-code:** the same, ignoring `.md` files;
  - **commit reference:** the fix commit's message cites `#X`;
  - **landing-PR reference:** the title or body of the PR that landed the fix commit cites `#X`.
- *Hand verdict* (B0-R-5): one rule for every pair. A pair counts as a **fix of X's own change**
  when the later PR fixes something X introduced. This includes issues X merged with and listed as
  open. Such a fix is a **"found after merge"** escape only when the issue was not known at merge.
- *Complete window:* X merged at least W days before the `cbb6d4e` commit time. Only those PRs are
  counted:
  - 7 days: 138 PRs, merged 2026-08-01T00:00Z … 2026-10-16T16:03:32Z;
  - 30 days: 37 PRs, merged 2026-08-01T00:00Z … 2026-09-23T16:03:32Z, #5–#41.
  
  The rest (32 and 133 PRs) are censored.

**Volume.** 320 `fix(...)` commits landed since 2026-08-01, and 48 of the 170 PRs have a "fix"
title. Most `fix(...)` commits are review fix-ups inside a PR's own branch. They land with that PR,
so they are not post-merge fixes.

**Numbers** (`summary.json` → `metric2_rework`; hand counts in `verify-summary.json` →
`hand_validated_fixes`; per PR in `per-pr-size-and-fixes.csv`):

| Attribution | 7 days: PRs with ≥ 1 / complete | 30 days: PRs with ≥ 1 / complete |
|---|---|---|
| Fix commit, any shared path (path-matched, overcounts) | 79 / 138 (57%) | 16 / 37 (43%) |
| Fix commit, shared non-`.md` path (overcounts) | 43 / 138 (31%) | 15 / 37 (41%) |
| Fix PR, any shared path (overcounts) | 79 / 138 (57%) | 17 / 37 (46%) |
| Fix PR, shared non-`.md` path (overcounts) | 35 / 138 (25%) | 14 / 37 (38%) |
| Fix commit message cites `#X` | 2 / 138 (1.4%) | 0 / 37 |
| Fix PR body cites `#X` | 8 / 138 (5.8%) | 1 / 37 (2.7%) |
| Landing-PR text cites `#X` | 12 / 138 (8.7%) | 2 / 37 (5.4%) |
| **Hand-confirmed fix of X's own change** | **6 / 138 (4.3%)** | **1 / 37 (2.7%)** |
| … with the unreferenced plausible case (#86) | 7 / 138 (5.1%) | 1 / 37 |
| **… of which found after merge (escapes)** | **4 / 138 (2.9%)** | **0 / 37** |

The hand-confirmed cases are in `fix-attribution-validation-manual.csv`.
- **Known at merge:**
  - #25, fixed by #26: framing issues #25 listed as open.
  - #85, fixed by #86: items from #85's review "carried from part 1".
- **Found after merge:**
  - #81, fixed by #82;
  - #99, fixed by #100;
  - #114, fixed by #115;
  - #142, fixed by #143.
- **Not fixes of the cited PR:** 7 of the 13 landing-PR-reference pairs in the 7-day set. They cite
  the PR for batching, implement its spec, or fix older code that its tests exposed.

**Hand check of path matching.** 20 pairs were drawn at random (seed 20261023) from the 382
path-matched pairs:
- 2 are plausible fixes of the earlier PR: #86 fixed by #90 and by #92. Neither cites #86, and both
  were found after merge.
- 18 are not. They share a findings document, a checklist or collector files.

So path matching measures how much work touches the same files, not defect escape. The
hand-confirmed figure is a lower bound for fixes that cite the PR; fixes that cite nothing are
missed, as #86 shows.

**The literal 10-14 proxy:** "count `fix(...)` commits that reference a PR merged in the prior
7 days, last 60 days". Window: 2026-08-24T16:03:32Z … 2026-10-23T16:03:32Z (`summary.json` →
`metric2_1014_proxy`).
- 291 `fix(...)` commits landed in the window.
- 2 commit messages cite a PR merged in the 7 days before the commit landed:
  - `52c20a5` cites #81 and is a real fix of #81;
  - `5d0c9d4` cites #110 and is not a fix of #110.
- 54 commits, in 14 landing PRs, sit in a PR whose title or body cites such a PR. All 14 pairs have
  a hand verdict (B0-R-6 added #165 → #164, not a fix). **6 of the 14 fix the cited PR; 4 of those
  were found after merge.**

**Query.** `measure.py`, section "metric 2 / 5"; `verify.py` for the sample and the hand counts.

**Known error.**
- **Path matching overcounts:** only 2 of 20 sampled pairs were plausible. It is also not a strict
  upper bound (B0-R-12): a fix whose commit and PR are both unlabelled `fix` is invisible to every
  rule here.
- **Reference matching undercounts** fixes that do not cite the PR.
- **A "fix" subject or title is the author's own label.** #26 ("F4: …") and #115
  ("docs(hermes): …") are counted only through the landing-PR rule.
- **The 30-day figure rests on 37 PRs** merged by 2026-09-23, almost all Hermes.
- **The split between "known at merge" and "found after merge"** is read from the bodies of the
  fixing PRs.

## Metric 3 — Time from specification to verified delivery

**Recount at `cbb6d4e`** (`git ls-tree`):
- 37 top-level `.md` files in `docs/superpowers/specs/` and 50 in `docs/superpowers/plans/`.
- The `archive/` folders hold 7 more specs and 6 more plans, plus a README in each.
- S1's "38 specs, 51 plans" equals the top-level entries counted together with the `archive/`
  folder (an inference).
- The 13 archived files are the retired Hermes custom-kernel documents (canon D-3). All of them
  landed with #5, 15.2 to 16.1 days after their first commit, and they are excluded below.

**Scope.** 19 of the 87 top-level files were committed straight to `main` in June and July, before
the PR flow, so no PR can match them. 68 files are in scope.

**Matching rule** (`measure.py`, "metric 3").
- *First commit:* the earliest commit that adds the file (`git log --follow --diff-filter=A`).
- *Candidates:* PRs that merge at or after that commit and change at least one file outside
  `docs/superpowers/`.
- *A candidate qualifies if:*
  - (a) its title or body names the file;
  - (b) its branch name contains the file's slug (the name without the date prefix and without a
    trailing `-design`, `-plan` or `-spec`);
  - (c) it is the PR that landed the file's first commit.
- *The match:* the earliest qualifying PR in the best class (a before b before c).
- *Correction by hand:* when delivery spans several PRs, the corrected match is the **last part**.
- *Delivery:* that PR's merge. Nothing marks verification after a merge, so "verified delivery" is
  proxied by the merge.

**Results** (`verify-summary.json`; rows in `spec-plan-matches.csv`):
- **Matched:** 64 of 68 in scope (94%; 74% of all 87).
- **Unmatched in scope (4):** none of them has an implementing PR, by nature.
  - two planning briefs: `2026-09-03-s3b-…-brief` and `2026-09-16-phase-b-brief`;
  - an unapproved proposal: `2026-09-19-tailscale-access-design`;
  - an operational rollout plan: `2026-10-14-review-11-rollout`.
- **Hand verification of the 64:**
  - 59 correct;
  - 3 partial, all multi-PR deliveries corrected to the last part:
    - the mutation-syscall spec → #25 (B0-R-7);
    - the chat-triggered-audits spec → #88;
    - the ads-report-job spec → #121;
  - 1 not a spec: the bring-up findings record kept under `specs/`;
  - 1 delivered as a decision, not code: S11, #168.
  
  **Exact precision of the automatic rule: 59 / 64 = 92.2%.**
- **Lead time, corrected (n = 62): median 0.84 days, p25 0.10, p75 2.85, min 0.01, max 28.87.**
  - Specs (n = 25): median 0.90, p25 0.28, p75 4.90, max 28.87.
  - Plans (n = 37): median 0.66, p25 0.08, p75 2.19, max 23.79.
- **Automatic rule without correction (n = 64):** median 0.71, p25 0.09, p75 2.83, max 23.79.
- Using author time instead of committer time changes no value.

**Known error.**
- **Mostly one branch:** in 60 of the 64 matches, the implementing PR is the PR that added the spec
  or plan, because they are committed on the implementation branch. So the number is "spec commit →
  merge of that branch", not the wait before work starts. Design work before the first commit
  (brainstorming in a session) is not visible in git.
- **Right-censoring (B0-R-11):** specs and plans not yet delivered at `cbb6d4e` are excluded. Long
  waits that have not ended are therefore missing, which biases the lead time short.
- **Matching:** 5 of the 64 automatic matches needed a hand verdict other than "correct".
  Multi-part deliveries depend on whether delivery means the first or the last part; the corrected
  figure uses the last part throughout.
- **Merge is not verification.** Hermes deliveries were often verified later, on the server, and
  recorded in a separate docs PR ("… applied to the box"). That step is not part of this measure.

## Metric 4 — Human interventions per task

**Review rounds per PR, from bodies** (`summary.json` → `metric4_interventions`):
- **Coverage:** 62 PRs record a PR review. 61 of them have a round count; #174 does not.
- **Counting rule (B0-R-9):** one round is one PR-level review pass. A re-review after a fix wave is
  a second round. A whole-branch review with no re-review stated is 1 round. Per-task review loops
  are not counted.
- **Rounds:** median **2**, p25 1, p75 3, p90 4, max 6, mean 2.26. Distribution: 1 round → 20 PRs,
  2 → 20, 3 → 10, 4 → 8, 5 → 2, 6 → 1.
- **Before #131:** n = 29, **median 1**, max 2. Distribution: 1 → 18, 2 → 11.
- **From #131:** n = 32, **median 3**, p75 4, max 6.
- **No review:** 108 PRs have no PR review recorded. They are not counted as 0 rounds above.

**Prompts per PR-producing session: not measurable.** No instrument joins sessions to PRs until
P1-03, and transcripts were not read, by rule.

**Approvals per PR** are not part of this item. GitHub records no review approval on any of the 170
PRs (`reviews` is empty).

**Known error.**
- **What a "round" means changed at #131.** Before, a round is a whole-branch pass by the
  implementing workflow's reviewer. From #131, it is a reviewer pass under `REVIEW_PROTOCOL.md`.
  Part of the rise from median 1 to 3 can come from that change.
- **Uncounted review work before #131.** The per-task review loops that dominated before #131 are
  not counted; the bodies do not give their number.
- **Reviewer's recount was n = 24 before #131; mine is 29.** The difference: I applied the same
  one-pass rule to #5, #20, #23 and #42 (a final review stated, no re-review: 1) and to #19 (seam
  review, then a readiness pass: 2). The median is 1 either way.
- **#5 is a judgment call.** It shipped 4 increments, each with its own whole-branch review, so it
  could be coded 1, 4 or ND. The median before #131 stays 1 in every case.

## Metric 5 — Integration complexity and maintenance burden

**Files and lines per PR** (`git diff -M --numstat <merge>^1 <merge>`; `summary.json` →
`metric5_size`):

| PRs | n | Files: median (p75, p90, max) | Lines added + deleted: median (p75, p90, max) |
|---|---|---|---|
| All | 170 | 3.5 (8, 18.1, 66) | 176 (501.5, 3,188.5, 12,995) |
| Code-touching (any non-`.md` file) | 83 | 8 (16.5, 21.8, 66) | 428 (2,373, 5,071.8, 12,995) |
| Docs-only (`.md` only) | 87 | 2 (3, 5.4, 22) | 80 (178.5, 248.8, 5,961) |

**Path-matched follow-up `fix` within 30 days** (overcounts, see metric 2):
- 17 of 37 complete-window PRs (46%) have a later fix PR on a shared path. That count is at PR
  level; at commit level it is 16.
- 14 of 37 (38%) have one on a shared non-`.md` path (commit level: 15).

These counts measure overlap in the files that work touches. They are not defect counts.

**Context footprint** (B0-R-4; `summary.json` → `metric5_footprint`; per skill in
`footprint-per-skill.csv`).
- **The definition, in skill-eval's own words** at `cbb6d4e`:
  - `skills/skill-eval/SKILL.md:96`: "**Context Footprint** = total lines across all files loaded
    on trigger + estimated tokens (lines × 4 avg)".
  - Step 1 (`:21`) names the files: "`skills/<skill-name>/SKILL.md` and all bundled files
    (REFERENCE.md, scripts/, references/) … these all count toward context footprint".
- **Two variants.** The definition does not settle which bundled files load when a skill triggers,
  so both are reported:
  - **A, step-1 literal:** SKILL.md + REFERENCE.md + `references/**` + `scripts/**`.
  - **B, SKILL.md only:** the file Claude Code loads when the skill triggers.
  - Neither variant counts report files (SKILL-EVAL.md, SKILL-AUDIT.md, *-REFINE-LOG.md) or
    `assets/`.
  - Lines are newline counts of each blob at `cbb6d4e`, and tokens = lines × 4. No binary file was
    met.
- **Skills discovered dynamically:** 30 under `skills/`, 1 under `.claude/skills/`, 3 under
  `packs/*/skills/` and 6 under `infra/hermes-agent/skills/`.

| Skills | n | B: SKILL.md lines, median (p75, max) / total | A: bundled lines, median (p75, max) / total |
|---|---|---|---|
| `skills/` | 30 | **61** (114.75, 433) / 2,693 ≈ 10,772 tokens | **75.5** (249, 2,255) / 8,475 ≈ 33,900 tokens |
| `.claude/skills/` | 1 | 69 | 69 |
| `packs/*/skills/` | 3 | 27 (27, 27) / 80 | the same |
| `infra/hermes-agent/skills/` | 6 | 64.5 (90.75, 104) / 406 | the same |

- **Largest:** the biggest SKILL.md is `project-setup` (433 lines). The largest variant-A footprint
  is `skill-eval` (2,255 lines, of which scripts are the bulk), then `agent-eval` (1,480).
- **Committed SKILL-EVAL reports:** 27 report a footprint in lines. Only 4 equal the line count at
  `cbb6d4e`: agent-adapt, brain-context-pack, brain-kernel and skill-discovery. These are
  single-file skills, so the count is the same in both variants. The reports
  predate later edits and were not computed the same way, so they are not a baseline. The B0 values
  are the ones above.
- **Which variant past reports used:** 18 of the 27 reported footprints are within 1 line of the
  SKILL.md-only count (variant B), so past reports mostly used that variant. Caveat: 17 of the 18
  are single-file skills, where the two variants agree. The one case that tells them apart,
  skill-audit (reported 51; SKILL.md 52; bundled 997), points to variant B. Compare future reports
  on variant B.

**Definition count at `cbb6d4e`** (`git ls-tree`; this equals `find` on the checkout, because those
paths have no uncommitted changes):

| Location | Command | Count |
|---|---|---|
| `skills/*` | `find skills -mindepth 1 -maxdepth 1 -type d` | 30 |
| `.claude/agents/*.md` | `ls .claude/agents/*.md` | 17 files: 16 agents + 1 eval report (`skill-eval-agent-EVAL.md`) |
| `.claude/skills/*` | `ls .claude/skills` | 1 (`codex-eval`) |
| `packs/*/skills/*` | `ls -d packs/*/skills/*` | 3 |
| `infra/hermes-agent/skills/*` | `ls -d infra/hermes-agent/skills/*` | 6 |
| **Total definitions** | | **56** |

The list is in `definition-inventory.json`. The 3 `SKILL.md` files under `fixtures/` (golden-target,
mutant-brief-writer, mutant-notes-summarizer) are test fixtures and are excluded by design.

**Known error.**
- The docs/code split goes by the `.md` extension, so runbooks, the brain capsule and the Hermes
  checklists (`.md`) all count as docs.
- Line counts include generated or moved content.
- The footprint counts lines, not what is actually in context. Variant A includes test scripts that
  ship inside `scripts/`.

## Limitations

1. **One coder.** The review coding, the match verdicts and the fix verdicts are one reading by the
   author of this draft; the independent reviewer re-checked them. Each hand-coded row keeps its
   reason.
2. **PR bodies only, as fetched on 2026-10-23.** A body edited later changes the input, so the
   fetched JSON is kept. Comments are not read, except where the reviewer found one that contradicts
   a body (#30). The bodies are written by the implementing session, and their claims of review are
   not verified.
3. **Censoring.** 32 PRs lack a full 7-day window and 133 a full 30-day window. The 30-day numbers
   rest on 37 PRs (#5–#41), nearly all Hermes, from August to September. Metric 3 leaves out specs
   that are not yet delivered.
4. **Mix.** 89 of the 170 PRs are Hermes work, and the practice changed mid-window: Superpowers
   subagent-driven development before, `REVIEW_PROTOCOL.md` from #131. Later comparisons should use
   the same windows and rules, and report the mix.
5. **Labels.** "Fix" means the author's commit or title label, and "blocking" means the body's
   words. Neither is an independent judgment of defect or severity.
6. **What the bodies do not hold.** Since 2026-10-15, bodies list review rounds and finding IDs but
   not the first-round verdict or severities. Metric 1 cannot be followed over time from bodies
   alone. A PR template line with the first-round verdict and the number of blocking findings (or
   the P1-08 IDs) would make it measurable.
7. **Not measured:**
   - prompts per PR (P1-03);
   - false completions (P1-09);
   - verification after merge;
   - anything before 2026-08-01.
8. **Out of scope (B0-R-15).** The §3 "mandatory-criterion indicators" belong to the B0
   breach-inventory snapshot (S5 §2.2), not to P1-01. The coordinator records them separately.
9. **Privacy.** This record and the data hold PR numbers, titles, repository paths, commit hashes
   and counts. No prompt or transcript text was read or stored. The saved PR JSON holds the PR
   bodies and comments as published on GitHub; the coder saw no client name, customer id or
   credential value in them.

## Independent review (2026-10-23)

An independent reviewer under `docs/REVIEW_PROTOCOL.md` checked this record in three rounds and accepted it in the
third; all findings B0-R-1 … B0-R-16 are closed. What the reviewer did:
- **Scripts.** Read every script before running it: git read commands, `gh` GETs and local files only; no writes
  outside the data directory.
- **Re-runs.** Ran `run.sh` without `--refetch` on fresh copies of the inputs in each round. The outputs were
  byte-identical to this record's data each time: 14 files in round 1, 19 in rounds 2 and 3.
- **Live check.** Compared 7 fields (title, body, mergedAt, additions, deletions, changedFiles, merge oid) for PRs 8,
  61, 99, 142 and 165 with live GitHub: 35 of 35 match.
- **Own commands.** Re-derived the PR count, spec and plan counts, sizes, definition count, fix windows and the
  review-rounds median with its own commands.
- **Re-coding.** Re-coded seeded samples of the hand coding in round 1:
  - `review-coding-manual.csv`: 7 of 10 rows agree on every field (9 of 10 per field);
  - `spec-plan-match-verification-manual.csv`: 9 of 10;
  - `fix-attribution-validation-manual.csv`: 9 of 10.
  - In round 2, 5 of 5 freshly drawn rows agree on the corrected columns.

## Review corrections (2026-10-23)

One line per finding of the independent review. The reviewer closes them; the author does not.

- **B0-R-1:** #100 and #145 recoded from 0 blocking to ND, because both bodies report a fix after
  the approved round.
- **B0-R-2:** #30 recoded to ND. A PR comment posted before the merge is a review with 3 findings,
  contradicting "returned clean". Stated under the known errors. First-pass acceptance becomes
  5/16 = 31%.
- **B0-R-3:** added numbered findings per reviewed PR (from ID ranges and stated counts) and
  blocking findings per first round, with new columns in `review-coding-manual.csv`.
- **B0-R-4:** measured the context footprint with skill-eval's definition (`SKILL.md:96`, `:21`)
  for all 40 discovered skills, in two variants. The reviewer's indication (2,693 lines, median 61,
  max 433) is reproduced.
- **B0-R-5:** one rule for known-at-merge fixes. #85 by #86 now counts like #25 by #26. Reported
  two ways: fixes of the PR's own change, 6/138 (7/138 with #86); found after merge, 4/138. At
  30 days: 1/37 fixes, 0/37 escapes. Proxy: 6 of 14 pairs, 4 found after merge.
- **B0-R-6:** added the verdict for #165 → #164 (not a fix of #164). `verify.py` now checks that
  every proxy pair has a verdict (none missing).
- **B0-R-7:** last-part rule applied to both syscall files, so both map to #25. Precision is
  59/64 = 92.2%; the median, p25 and p75 are unchanged; max 13.07 → 28.87 (specs 28.87, plans 23.79).
- **B0-R-8:** #134, #136 and #141 are listed apart as unattributed reviews. 62 PRs reviewed; 33 of
  44 from #131.
- **B0-R-9:** rounds recoded by the one-pass rule (#5, #7, #20, #23, #42, #85, #86, #96, #114, #120
  → 1; #19, #107 → 2). Overall median stays 2; before #131 the median falls to 1. My n is 29, the
  reviewer's 24; the reason is given under metric 4.
- **B0-R-10:** the headline and the table now agree: 108 PRs have no PR review recorded (100 none,
  3 placeholders, 1 automated-only, 1 spec-review-only, 3 unattributed).
- **B0-R-11:** exact windows given for metrics 2 and 3; right-censoring added to metric 3's known
  errors.
- **B0-R-12:** path matching is called a "path-matched count (overcounts)", not an upper bound. The
  30-day 17 is stated as PR level (16 at commit level).
- **B0-R-13:** the 30-day result now reads "1 of 37, known at merge; 0 found after merge".
- **B0-R-14:**
  - `run.sh` now says three hand-coded inputs;
  - the `measure.py` docstring names which script reads which input;
  - `gh_vs_git_mismatch` also checks changedFiles (0 mismatches of 170).
- **B0-R-15:** added Limitation 8 (mandatory-criterion indicators are out of scope), and noted
  that the 3 `fixtures/` SKILL.md files are excluded from the definition count.
- **B0-R-16:** #149 recounted from 27 to 34 by the stated highest-index rule (the B series counts to 9).
  Numbered findings: max 27 → 34, mean 11.79 → 12.03; median, p25, p75 and p90 unchanged.
  ID-or-stated: max 27 → 34. Also added: the #5 judgment-call note (metric 4) and which footprint
  variant past reports used (metric 5).
