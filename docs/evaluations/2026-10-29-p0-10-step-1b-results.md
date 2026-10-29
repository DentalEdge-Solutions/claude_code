# P0-10 step 1b — owner-run GitHub tests: results

> **Date:** 2026-10-29 (tests run 2026-10-28 and 2026-10-29) · **Branch:** `docs/p0-10-step-1b-results`
> (base `b3d3d58`) · **Roadmap:** `docs/evaluations/2026-10-22-optimization-strategy/S5-prioritized-roadmap.md`
> P0-10 step 1b (lines 324-444), batch B5 (line 812), owner-only actions §2.3 (lines 820-826) · **Test plan:**
> `docs/evaluations/2026-10-27-p0-10-step-1a-github-docs-check.md` §4 ("1a §4" below).
> Results record for the owner, returned **before** any production account, token or ruleset step on `main`
> (R-B-9). An independent reviewer checks it (`docs/REVIEW_PROTOCOL.md`). Writing this record made no GitHub
> change.

Tags: **[Ver]** measured during step 1b, either an owner-run command whose output was brought back to the session,
or a read-only call by the coordinator (the Claude session that wrote the runbooks; marked "by the coordinator")
or by this record's reviewer (marked "by the reviewer")
· **[Owner-rep]** owner-reported from a settings screen or an action without captured output · **[Docs]** an
official GitHub source, as the step-1a record or the 2026-10-28 review round read it; **[Docs, fetched by the
reviewer]** marks the two pages the record's reviewer fetched on 2026-10-29 · **[Comm]** community source,
corroboration only (as in 1a) · **[Inf]** inference from the measurements · **untested** not measured, with the
reason.

Times are local (EDT) as recorded in the session notes. "The notes" means the coordinator's step-1b results notes,
the single source of every result below.

## 1. Plain-language summary

**What we tested.** We wanted to know if a separate GitHub account for the agent (`dentaledge-bot`) can do its
work, and if GitHub can stop that account from merging. All tests ran on a throwaway branch
(`p0-10-probe/base`), never on `main`. The owner ran every test. The test tokens were short-lived. The three
named test tokens are deleted, and two of them were proved dead by a refused use. One more value, loaded during a
setup attempt and refused by GitHub, is unexplained; the owner should confirm what it was (§3.8).

**Main results.**
- **The bot works with a classic token.** A classic token with only the `public_repo` scope could push, open a
  pull request, update a branch, approve and merge. A fine-grained token could not even be created for the
  organisation: GitHub did not offer the organisation as an option.
- **Workflow files are refused.** Without the `workflow` scope, GitHub refused the bot's push of a workflow file.
  An ordinary file pushed fine.
- **The bot cannot approve or merge its own PR.** GitHub refused the bot's approval of its own PR. It also refused
  the bot's merge, because the owner's code-owner review was missing.
- **Main finding: the bot can approve and merge the owner's own PRs.** When the person who opens a PR is the only
  code owner, GitHub does not apply the code-owner rule. So one approval from the bot was enough. The bot then
  merged that owner PR, and GitHub's own rule check said every rule passed (sitting 3b, step 3.4). The roadmap's
  safeguard (d) expected the opposite. **Safeguard (d) therefore fails as written.** This was measured on the test
  branch with the planned review rules. It is expected to be the same on `main` once step 5 adds those rules [Inf].
  Today `main` requires no approvals at all.
- **Candidate B stops every bot merge.** Candidate B is the classic branch setting "Restrict who can push", with
  nobody listed and admins not enforced. With B on, GitHub refused every merge by the bot. That includes owner PRs
  that the bot had approved. The owner's normal merges and bypass merges kept working.
- **Without B, the bot merged.** When B was removed, the bot merged a PR the owner had approved, and an owner PR
  the bot had approved. This confirms the "residual" risk the roadmap describes.
- **The bypass does not skip checks.** The owner's bypass merge was refused while the test check failed, and
  worked when it passed.
- **Cleanup is done and checked.** The test rulesets, the classic rule and the test branches are gone. `main` is
  as it was.

**What the owner now decides** (§8): which token type to adopt, and whether to put candidate B on `main`. B stops
the bot merging owner PRs, but safeguard (d) needs rewording either way. Even with B, the bot's approval still
counts on the owner's own PRs, so the owner could merge such a PR normally and it would look reviewed [Inf,
untested]. These results come from the test branch with the planned rules; `main` should behave the same once
step 5 adds them [Inf].

## 2. Repository state, before and after

| What | Before (2026-10-28) | After cleanup (2026-10-29) |
|---|---|---|
| Rulesets | `main-protection` 19737624 only (1a §2) | only `main-protection` 19737624: active, `~DEFAULT_BRANCH`, no bypass, rules deletion, non_fast_forward, pull_request, required_status_checks; unchanged [Ver by the coordinator] |
| Classic branch protection | none on the repository [Owner-rep]; `GET branches/main/protection` → 404 "Branch not protected" [Ver] | `branchProtectionRules` [] [Ver by the coordinator] |
| `main` | `b3d3d58` | `b3d3d58` [Ver by the coordinator] |
| Open PRs | none into `main` (phase A read) [Ver] | none [Ver by the coordinator] |
| `allow_auto_merge` | false (1a §2); still false at step 4.14 [Ver] | false (the record reviewer's live read after cleanup, 2026-10-29) [Ver] |
| `main-protection` bypass list | empty [Owner-rep] | none [Ver by the coordinator] |
| Probe refs | none | none on GitHub; none locally after `fetch --prune` [Ver by the coordinator] |

Other state read on 2026-10-28 [Ver by the coordinator]:
- `security_and_analysis`: secret scanning, non-provider patterns, push protection, validity checks and
  Dependabot security updates are all disabled.
- Forks 0, stars 1, no Pages, no license file.

The owner decided on 2026-10-28 that the repository **stays public**. This weighed the bot's seat cost on a
private repository, the Hermes box's anonymous clone, and the loss of free secret scanning [Owner-rep].

## 3. Results per test (against 1a §4)

Probe PRs, all into `p0-10-probe/base`: **#188** = X, bot PR (`p0-10-probe/t1-head`); **#189** = A, **#190** = B,
**#191** = C, **#192** = D, owner PRs (`owner-a` to `owner-d`); **#193** = Y, second bot PR (`t4-bot`). The
required check was the commit status `p0-10-probe/ci`, set by the owner (CI does not run on probe PRs).

### 3.1 T0 setup — PASS

- `p0-10-probe/base` was created from `main` `b3d3d58`. `/.github/CODEOWNERS` with `* @dentaledgesolutions` was
  committed on it (`309a298`, 23 bytes) [Ver].
- `GET codeowners/errors?ref=p0-10-probe/base` → `{"errors":[]}` [Ver]. As 1a said, this rules out syntax errors
  only. Recognition of the owner as code owner is settled in T3 (§3.4).

### 3.2 T1 token type

**Fine-grained (sitting 1, 2026-10-28) — FAILS AT MINTING** [Owner-rep].

| 1a §4 check | Result |
|---|---|
| Org listed as resource owner | **no**: `DentalEdge-Solutions` was not offered as resource owner for `dentaledge-bot` |
| Token state; push; PR; view; update-branch | not reached: no token was created |

This matches the docs' outside-collaborator gap (1a Q2 [Docs]). It contradicts the 2026-07-25 record (§5).

**Classic `public_repo` (sitting 2, 2026-10-28) — PASS** [Ver]. Token `p0-10-t1-classic`, scope `public_repo`
only, expiry the next day, used through `GH_TOKEN`.

| 1a §4 check | Result |
|---|---|
| Identity | `gh api user` → `dentaledge-bot`; `X-Oauth-Scopes: public_repo` |
| Refusal control (`GH_TOKEN` unset) | exit 128, "Invalid username or token. Password authentication is not supported for Git operations."; trace shows only the inline helper (`get`, `erase`), no `credential-osxkeychain` |
| `git push` of `p0-10-probe/t1-head` | exit 0; trace shows only the inline helper (`get`, `store`) |
| `gh pr create --base p0-10-probe/base` | PR #188, author `dentaledge-bot`, `author_association` `COLLABORATOR`; no scope complaint |
| `gh pr view --json author,reviewDecision,statusCheckRollup` | works (`reviewDecision` "", rollup []) |
| `gh pr checks` | "no checks reported", exit 1 (no CI on probe PRs, so not a token failure [Inf]) |
| `PUT …/pulls/188/update-branch` | "Updating pull request branch.", exit 0 → merge commit `1dbe272`, author `dentaledge-bot`, committer `web-flow` [Ver by the coordinator] |
| Pusher in repository activity | `branch_creation` and `push` on `t1-head`, creation and deletion of `t2-head`, all actor `dentaledge-bot` [Ver by the coordinator] |
| `gh auth login --with-token` message (1a §4 asked to note it) | untested: the notes record only `GH_TOKEN` use |

The later sittings used the same token type (`p0-10-s3`, `p0-10-s3b`). With it the bot also approved PRs, merged
through `PUT …/merge` and `merge-async`, and read rulesets (§3.4, §3.5) [Ver]. `repo` scope was not needed and was
not tried.

### 3.3 T2 workflow refusal (sitting 2) — PASS [Ver]

- The bot pushed `.github/workflows/p0-10-probe-c9bb5ac6.yml` (inert, `workflow_dispatch` only) to
  `p0-10-probe/t2-head`. GitHub refused it, exit 1:

  ```text
  ! [remote rejected] HEAD -> p0-10-probe/t2-head (refusing to allow a Personal Access Token to create or update
  workflow `.github/workflows/p0-10-probe-c9bb5ac6.yml` without `workflow` scope)
  ```

  This is the wording 1a quoted from community reports [Comm]; it is now measured.
- Control: an ordinary file on the same branch, exit 0. The bot then deleted the branch, exit 0.

### 3.4 T3 two rulesets and review rules

**Setup (phase A, 2026-10-28)** [Ver by the coordinator]:
- `probe-checks` 26068761 and `probe-review` 26068762 were created **disabled**. Read back, both include exactly
  `refs/heads/p0-10-probe/base`, exclude [].
- `probe-review` parameters: `require_code_owner_review` true, `dismiss_stale_reviews_on_push` true,
  `require_last_push_approval` true, `required_approving_review_count` 1.
- `probe-review` bypass: `RepositoryRole` id 5, which GraphQL `repositoryRoleName` reports as `admin`, mode
  `PULL_REQUEST`. `probe-checks`: no bypass.
- After the guarded activation: `rules/branches/main` → only `main-protection`'s 4 rules;
  `rules/branches/p0-10-probe/base` → only the probe rulesets' rules; `main` has no classic protection (404).

**Results** (step numbers: 3.1-3.4 from the first attempt of sitting 3, `sitting-3-runbook.txt`; the rest from
sitting 3b, `sitting-3b-ordered.txt`):

| 1a §4 probe | Expected (1a) | Observed | Verdict |
|---|---|---|---|
| bot approves its own PR (3.1, #188) | refused | "GraphQL: Review Can not approve your own pull request (addPullRequestReview)" [Ver] | PASS |
| bot merges its own PR before any approval, check green (3.2, #188) | refused | `gh pr merge`: client-side "not mergeable: the base branch policy prohibits the merge". `PUT …/merge`: HTTP 405 "Repository rule violations found — Waiting on code owner review from dentaledgesolutions." [Ver]. Rule suite id 4779055958 (2026-10-28 16:15:42 -04:00) [Ver by the reviewer] | PASS: the server names the code-owner review as the only violation |
| bot PR, owner approves, check green, bot merge, no candidate | merges (the OC-2 residual) | not run in T3, on purpose (3.12: do not merge before T4). Run in T4 step 4.13: **MERGED** (§3.5) [Ver] | residual confirmed |
| bot pushes after the owner's approval (3.9, 3.11, #188) | approval dismissed | owner view `REVIEW_REQUIRED` after each bot push (`2e45f77`, `112abd5`); after re-approval both views `APPROVED`/`CLEAN` (3.10, 3.12) [Ver] | PASS |
| owner clicks Update branch on a bot PR, then approves (3.8, #188) | approval likely cannot satisfy last-push [UNVERIFIED in 1a] | after the owner's update-branch (`cd9d826`) and approval, owner and bot views both `APPROVED`/`CLEAN` [Ver]. No merge was attempted at that head, and no other step decides whether update-branch counts as a push for last-push approval (§6) | **untested** |
| bot updates the branch, then owner approves (4.8-4.9, #193) | mergeable | bot update-branch (`60ef666`) did **not** dismiss the owner's approval (owner view `APPROVED`/`BLOCKED`); after the owner's re-approval, owner view `CLEAN` [Ver] | mergeable (owner view) |
| owner-authored PR approved by the bot (3.3-3.4, #189) | `REVIEW_REQUIRED`; bot merge refused | bot approval allowed ("✓ Approved"). First attempt: `APPROVED` in both views, merge `BLOCKED` (check missing), so the STOP rule ended the sitting. Sitting 3b, check green: both views `APPROVED`/`CLEAN`; bot `PUT pulls/189/merge` → **MERGED** (`5d5b42b`, `merged_by` `dentaledge-bot`). Rule suite 08:46, `309a298`→`5d5b42b`: every rule pass, including `probe-review`/`pull_request` [Ver] | **FAIL** against the expectation; main finding |
| owner PR, check `failure`, bypass merge (3.5, #190; also 4.6, #191) | refused (probe (e)) | "Repository rule violations found / Required status check "p0-10-probe/ci" is failing." Rule suite 08:50: `required_status_checks` fail; `probe-review` fail ("New changes require approval from someone other than the last pusher"), as expected on an owner PR with no reviews [Ver] | PASS: the bypass does not skip checks |
| owner PR, check `success`, bypass merge (3.6, #190; also 4.6, #191) | merges without review | MERGED; rule suite 08:51 result `bypass` (only `probe-review` failed, and was bypassed); 4.6 merged at 09:14:59, `bypass` [Ver] | PASS |
| `GET rulesets/26068762` as bot / as owner (3.7) | `never` / `pull_requests_only`; no `bypass_actors` for the bot | bot: `never`, `bypass_actors` null. Owner: `pull_requests_only`, `bypass_actors` [{`actor_id` 5, `RepositoryRole`, `pull_request`}] [Ver] | PASS |

**Why the owner PR merged** [Ver by the coordinator, GraphQL, 2026-10-28]:
- #189 had `reviewRequests` [] (no code-owner request) and one `APPROVED` review, from the bot.
- #188 had a review request for `dentaledgesolutions` with `asCodeOwner` true.
- So the owner **is** recognised as code owner. On a PR the owner authored, no code-owner review was required,
  because the author is the only code owner. One approval by anyone else, the bot included, satisfies
  `probe-review`.
- No docs page read for this record names the case of a PR author who is the sole code owner (runbook review
  round 3, accessed 2026-10-28; about-code-owners re-checked by the record's reviewer, 2026-10-29: silent).
- The measurement **contradicts the general documented rule**. About protected branches states that "any pull
  request that affects code with a code owner must be approved by that code owner" [Docs, fetched by the reviewer,
  2026-10-29]. #189 affected code owned by `* @dentaledgesolutions` and merged without that approval. This result
  is measured [Ver]; GitHub's behaviour differs from that sentence for the author's own PR.
- Consequence: S5 acceptance (d) (`S5-prioritized-roadmap.md:415-417`) **fails as written**. It has three parts:
  (1) `reviewDecision: REVIEW_REQUIRED`, (2) the bot's merge is refused, (3) only the owner's PR-only bypass can
  merge it. Part (1) fails whether or not B is on: #189 and #192 both showed `APPROVED` [Ver]. B restores part (2)
  (§3.5, step 4.11). Part (3) is not shown: the owner merging a bot-approved owner PR normally, without the bypass,
  was never tried, and would probably succeed [Inf, untested]. So (d) needs rewording in either case.

### 3.5 T4 candidate B — PASS

Candidate B (`probe-classic-b.json`): classic protection on pattern `p0-10-probe/base`, `restrictions` users,
teams and apps [], `enforce_admins` false, no required checks or reviews in the classic rule. Step 4.1 read back
`{"enforce_admins":false,"restrictions":[]}`, exactly one rule (`p0-10-probe/base`, `restrictsPushes` true,
`isAdminEnforced` false), and `main` still 404 [Ver]. In the rule suites, B's classic rule contributed
`deletion` and `non_fast_forward` evaluations as well as `authorization` [Ver by the reviewer, 2026-10-29].

| 1a §4 probe | Observed | Verdict |
|---|---|---|
| bot merges an owner-approved, green PR (4.2, #188) | `PUT …/merge`: HTTP 405 "You're not authorized to push to this branch. Visit https://docs.github.com/…/about-protected-branches for more information." `merge-async`: `pending` ("Merge request enqueued."), then `failed` with the same message; #188 stayed OPEN. Rule suites 09:00/09:01: the classic `authorization` rule fail, every ruleset rule pass [Ver] | PASS |
| same, UI merge button | untested: the 3b runbook dropped the UI and `gh pr merge` routes for the bot; the optional screenshot is not recorded | — |
| owner merges the same PR normally, no `--admin` (4.3) | MERGED; rule suite 09:07 `pass` [Ver]. No bypass was used | PASS |
| bot merges a second owner-approved bot PR (4.10, #193) | 405 "You're not authorized to push to this branch"; rule suite 09:17: `authorization` fail, ruleset rules pass [Ver] | PASS |
| **bot merges an owner PR that only the bot approved (4.11, #192)** | bot approval allowed; bot merge → 405, the same message as 4.10. Rule suite 09:26: `authorization` fail, `probe-review`/`pull_request` **pass** [Ver] | PASS: B closes the 3.4 gap |
| owner PR, check `failure`, bypass merge under B (4.6, #191) | refused, "Required status check "p0-10-probe/ci" is failing." [Ver] | PASS |
| owner PR, check `success`, bypass merge under B (4.6, #191) | MERGED, 09:14:59 `bypass` [Ver] | PASS |
| org audit log after both | not checked: optional owner check, pending (§9) | untested |
| rule insights | not available on this plan (§5). The rule-suites API was used instead (above) | — |

**Without B** (4.12-4.13b) [Ver]:
- 4.12: B deleted, exit 0; GraphQL `branchProtectionRules` `nodes` [].
- 4.13: the bot merged the owner-approved, green #193 → **MERGED** (`9e62dd5`). The residual is confirmed. The
  bot's single read just before the merge showed `CLEAN`. (The two `BLOCKED` bot reads of #193 just before it came
  from 4.11's conditional lines, run while B was still on, where a viewer-specific `BLOCKED` is expected, as in
  4.5.)
- 4.13b: the owner updated #192 (`11b21a8`; the bot's approval was not dismissed). The bot re-approved and merged
  it → **MERGED** (`9c027d9`). So it was B that refused 4.11.

Since 3.4 merged, 4.11 is unambiguous: B's refusal, not the review rule, stopped the bot on an owner PR. The
differential 4.10 → 4.13 (same PR and head; the owner re-approved in between, in 4.11's conditional lines at
13:27:14Z; B on, then off) proves B's effect on bot PRs.

### 3.6 T5 candidate A — not run

1a §4 says T5 runs "only if B fails". B worked in every case (§3.5), so T5 was not needed and no "Restrict
updates" ruleset was created. The open questions about A (whether a merge counts as an "update", the bypass
checkbox, the logging of exempt bypasses) stay as 1a left them.

### 3.7 T6 — nothing else

`allow_auto_merge` stayed false (4.14) [Ver]. No merge queue was enabled.

### 3.8 Token deaths

| Token | Used in | Death |
|---|---|---|
| `p0-10-t1-classic` | sitting 2 | **proved**: after deletion in the bot's settings, `gh api user` → "Bad credentials", HTTP 401, exit 1 [Ver] |
| `p0-10-s3` | sitting 3, first attempt | **by deletion only**, an explicit exception (S3-R-25) to "prove death, never infer it"; see below |
| `p0-10-s3b` | sitting 3b | **proved** (F1): deleted, then `gh api user` → "Bad credentials", HTTP 401, exit 1 [Ver] |

`p0-10-s3` (S3-R-25):
- It could not be proved dead by use, because its value had been discarded.
- The substitute evidence planned in review round 3 was: its absence from the bot's Tokens (classic) list at
  sitting 3b step S3; the time of the deletion entry in the bot's security log; and no process holding the value
  after the shell exited.
- What was obtained: the owner reported it deleted about two hours before the report on 2026-10-29 (the notes put
  it at about 10:00 EDT). No security-log time was given [Owner-rep].
- Not recorded: whether it was still listed at step S3 (before 08:45). The notes' approximate time falls after S3,
  which told the owner to delete any old p0-10 token. The security-log entry would settle it (§9).

**An unexplained value.** In the first attempt's setup, one attempt loaded a value that GitHub refused (401),
before the third attempt showed `dentaledge-bot` [Owner-rep]. What that value was is **unknown**. It could have
been a bad paste of `p0-10-s3`, or a separately minted token, and the notes do not say which. If it was a separate
token, it is not in the table above, and its deletion is unconfirmed (§9).

### 3.9 Rule-suites API on Team

- `GET /repos/{o}/{r}/rulesets/rule-suites` works on this Team org [Ver by the coordinator, 2026-10-28]. HTTP 200,
  with entries for the last three merges to `main`, actor `dentaledgesolutions`, result `pass`.
- It gave per-rule evaluations for every step above. That includes the classic `authorization` rule from candidate
  B. The classic rules show `rule_source` `{"type":"protected_branch"}`, with no id or name [Ver by the reviewer,
  2026-10-29]. (The notes first read this as `rule_source` null.)
- So B's refusals and the owner's merges under B are visible in the rule-suites API, not only in the org audit log.
  This corrects 1a's inference (§5).

## 4. Owner checks (1a §5), 2026-10-28

| # | Check | Result |
|---|---|---|
| 1 | Org PAT settings | Fine-grained: allowed, administrator approval required, maximum lifetime 366 days. Classic: allowed, **not** restricted, no expiry required [Owner-rep] |
| 2 | Active tokens / pending requests | no active fine-grained tokens, no pending requests. The expired July bot token appears nowhere (neither the bot's own list nor the org list); whether GitHub hides expired tokens or it was deleted cannot be told [Owner-rep] |
| 3 | Org plan | GitHub Team (owner screen: $4.00 per month) [Owner-rep]. The org owners list was not recorded separately; `dentaledgesolutions` is admin through org ownership (check 5) |
| 4 | Classic rules | none on `claude_code` [Owner-rep] |
| 5 | Collaborators, roles | `dentaledge-bot` outside collaborator, write; `dentaledgesolutions` admin through org ownership. Org repository roles: predefined only, so no custom role with "bypass branch protections" [Owner-rep] |
| 6 | Rules | `main-protection` bypass list empty. Rule insights: "only available for enterprise accounts" (§5) [Owner-rep]. The rule-suites API works (§3.9) |
| 7 | Webhooks, deploy keys | none, none [Owner-rep] |
| 8 | Org audit log | not done (optional, pending; §9) |
| 9 | As `dentaledge-bot` | no fine-grained or classic tokens, no SSH or GPG keys, member of no other org. 2FA was **off**; the owner enabled it on 2026-10-28 [Owner-rep] |
| 10 | Laptop (step 3) | partly: git credential config has only `credential.helper osxkeychain` from `/opt/homebrew/etc/gitconfig`, no URL-specific helpers [Ver by the coordinator]. The coordinator's own `gh` session on the laptop is the **owner** account, scopes `gist`, `read:org`, `repo`, `workflow` [Ver by the coordinator]. The other items are step-3 work |

## 5. Corrections to the step-1a record

1. **Rule insights is Enterprise-only.** 1a §5 check 6 said the dashboard needs Team or Enterprise Cloud. The owner's
   screen says "only available for enterprise accounts" [Owner-rep]. The rule-suites REST API does work on Team
   (§3.9) [Ver]. So the A-PR logging plan in 1a Q1 ("rule insights and the rule-suites API") is the API only on
   this plan.
2. **"APPROVED = no code owner assigned" is wrong.** 1a §4 (T0 and the T3 row "owner-authored PR approved by the
   bot") read `APPROVED` as "GitHub did not recognise the owner". In fact #188 had a code-owner request with
   `asCodeOwner` true, and #189 had none because its author is the sole code owner (§3.4) [Ver]. `APPROVED` on an
   owner PR means the code-owner requirement does not apply to the author's own PR. It does not mean the owner is
   unrecognised. 1a §7's fallback "CODEOWNERS does not recognise the owner" is therefore not triggered.
3. **Fine-grained result contradicts the 2026-07-25 record.** The org was not offered as resource owner (§3.2).
   The July record says an org-scoped fine-grained token minted by this bot pushed here. The cause is unknown.
   1a Q8 already listed the unknowns: the repository's visibility on 2026-07-25, whether the org approval flow
   applied, and a possible change in GitHub's behaviour since. Nothing here settles it.
4. **B's refusals are in the rule-suites API.** 1a Q1 (candidate B, logging) inferred that B's refusals "appear in
   the audit log, not in rule insights". The rule-suites API does show them, as the classic `authorization` rule
   with `rule_source` `{"type":"protected_branch"}` (§3.9) [Ver by the reviewer]. Whether the audit log also has
   them is unchecked.
5. **Owner-authored PRs do not need the owner's approval or the bypass.** Step 3.4 contradicts three 1a statements
   on owner-authored PRs:
   - 1a:25-26 (§1): "A code-owner rule with `* @<owner>` therefore means only the owner's approval can satisfy it,
     and an approval by `dentaledge-bot` cannot." This holds for others' PRs (#188). On the owner's own PRs the
     bot's approval satisfied the rule (#189, and #192 in the 09:26 rule suite) [Ver].
   - 1a:180-181 (Q1, candidate B): "The owner's own PRs still need the review ruleset's PR-only bypass". They do
     not, once the bot has approved them: `probe-review` passes (§3.4, §3.5 step 4.11) [Ver].
   - 1a:586 (the T4 row "owner-authored PR, status `success`, merged through the review ruleset's PR-only bypass"):
     the result held (4.6) [Ver], but the row assumed the bypass is the owner's only route. After a bot approval,
     a normal owner merge would probably pass as well [Inf, untested].

## 6. Other observations

- **`mergeStateStatus` is viewer-specific** [Ver]. Under B, #193 and #192 showed `CLEAN` to the owner and `BLOCKED`
  to the bot (4.5, 4.11). After a base move, the owner saw `UNKNOWN` and the bot `BEHIND` (4.7). Read the merge
  state from the account that will merge.
- **Right after a base move** the owner's view showed `UNKNOWN` (4.7) [Ver]. The runbooks waited `sleep 10` after
  each update-branch. A single read right after a change may not be settled [Inf].
- **Update-branch and approvals** [Ver]:
  - With the PR's diff unchanged, it did not dismiss approvals. The bot's update of #193 (4.8) kept the owner's
    approval, and the owner's update of #192 (4.13b) kept the bot's. This fits About protected branches, which
    dismisses approvals as stale on Update branch only "if the diff changes" [Docs, fetched by the reviewer,
    2026-10-29]. A PR whose diff changes on update was not tested.
  - **An approval kept this way moves to the new head** [Ver by the coordinator, re-read of
    `pulls/{n}/reviews`, 2026-10-29]:
    - #193: the owner's approval was submitted at 13:13:35Z while the head was `e7c641a`. It now reports
      `commit_id` `60ef666`, the head after the bot's update-branch.
    - #192: the bot's approval was submitted at 13:25:55Z on `b823bb3`. It now reports `11b21a8`.
    - Dismissed reviews keep their commit (#188: `cd9d826`, `2e45f77`).
    - So a check "approved `commit_id` = merged head" cannot tell an approval carried over by update-branch from one
      given on the merged head. Probe (a) as written would pass in both cases (§8).
  - **Whether update-branch counts as a push for last-push approval is untested.** An earlier reading of the
    rule suites at 08:50 and 09:14 (`probe-review` failing with "New changes require approval from someone other
    than the last pusher") is withdrawn. Those suites are owner-authored PRs (#190, #191) with no reviews at all,
    so the owner was the last pusher regardless of the update, and the rule would have failed either way. Step 3.8
    was the test that could decide it, and it stopped short of a merge.
- **3.8 is untested.** After the owner's update-branch and approval, both views showed `APPROVED`/`CLEAN`, against
  the expectation "NOT CLEAN". No merge was tried at that head, so whether the last-push rule would have refused is
  not known. [Inf] Either update-branch does not count as the owner's push, or `mergeStateStatus` does not reflect
  the last-push rule; nothing measured here tells the two apart.
- **A misleading `gh` hint.** A mistyped call with a literal "N" as the PR number returned 404, and `gh` suggested
  `gh auth refresh -s repo`. The 404 came from the bad PR number, not from the scope [Ver]. Following the hint
  would widen the token for no reason [Inf].
- **Commit identity.** The sitting-2 probe commit `1c83681` shows author `dentaledgesolutions`, from the laptop's
  git `user.name`/`user.email`, although the bot pushed it [Ver]. Later sittings committed with the bot's identity
  (`bc`). Step 3 and the runbook: agent sessions should commit as the bot.
- **`actor_id` 5.** The REST docs do not list 5 as the Repository admin role; Terraform provider docs only
  corroborate it. Phase A confirmed it through GraphQL `repositoryRoleName` `admin` before activation [Ver by the
  coordinator]. In the UI, the bypass list shows "Repository admin". The Add-bypass dialog offers the owner as a
  person, so users are eligible in the UI (R-A-14 answered) [Owner-rep].
- **GitHub-added default.** GitHub added `require_extra_approval_for_unattributed_changes: true` by default to both
  probe rulesets. They therefore mirror `main` on that flag, and S3-R-16's planned omission did not happen (moot)
  [Ver by the coordinator].

## 7. Deviations from the runbooks

- **S3-R-15, the token shell.** The token lived in a bare `zsh -f` child shell, not in the 1a §4 `( … )`
  subshell. That shell had no history file, read the value silently, and lost it on exit, so the effect is the
  same. The clipboard was cleared with `pbcopy < /dev/null`, and clipboard-history apps were paused.
- **Pasting after `zsh -f`.** Pasting a block that begins with `zsh -f` loses the rest: the child shell drops the
  typed-ahead lines. This was a setup slip in the first attempt of sitting 3, with no effect. Sitting 3b typed
  `zsh -f` alone, then sourced a pre-rendered env file.
- **The backtick defect (sitting 2).** A "Check it" line wrapped `cat …` in backticks. The owner typed them, and
  zsh ran the file's contents as a command (`command not found: name:`). Harmless. Later runbooks put commands on
  their own lines, without backticks.
- **PROCESS DEVIATION (sitting 3, first attempt).** The owner reopened Claude while the BOT shell still held a live
  test token, after step 3.4. This broke 1a §4's rule that no agent session runs while a test token is in use
  (DC-R-17). The owner was told to unset it, delete token `p0-10-s3`, and mint a fresh one for the rest. That token
  was therefore deleted and **not proven dead by use** (§3.8, S3-R-25). Sitting 3b moved the point where Claude
  closes to step S2b, before minting (S3-R-22). It also added a "stuck after S3" path that deletes the token and
  proves it dead before Claude reopens (S3-R-21).
- **4.11's conditional lines (sitting 3b).** The "if it MERGED" lines of 4.11 were run although D's merge was
  refused. They were harmless. The bot's update-branch of #193 returned 422 "There are no new commits on the base
  branch." (no change), and the owner re-approved #193, which was already approved.
- **S3-R-16** (planned omission of `require_extra_approval_for_unattributed_changes` from `probe-checks`) did not
  take effect: GitHub added the flag by default (§6).

## 8. What each later step can rely on now

| S5 item | Can rely on now (evidence) | Still needs |
|---|---|---|
| Step 2, token | Classic `public_repo`, no `workflow`, works for push, PR create/view, update-branch, approve, merge and ruleset reads; workflow pushes refused (§3.2, §3.3) [Ver]. Fine-grained cannot be minted for this org by this bot [Owner-rep]. Classic tokens are not restricted by the org (§4) | **Owner decision (1)** below. Step 2's proof that the expired `dentaledge-bot-pat` is refused is still to do; it is listed nowhere (§4 check 2) |
| Step 3, paths | git uses only `osxkeychain` here; the coordinator's `gh` session is the owner's, with `repo` and `workflow` [Ver by the coordinator]. The bot has 2FA on, no keys, no other org [Owner-rep]. Agent sessions should commit as the bot (§6) | the step-3 measurement and probe (h) |
| Step 4, CODEOWNERS | `* @dentaledgesolutions` parses with no errors, and GitHub treats the owner as code owner on others' PRs (§3.1, §3.4) [Ver] | the sole-code-owner gap: no code-owner review on the owner's own PRs |
| Step 5, review ruleset | On bot PRs, as designed: self-approval refused, no merge without the code-owner approval, stale dismissal on bot pushes, admin-role (`actor_id` 5) PR-only bypass, checks not bypassable, `current_user_can_bypass` `never`/`pull_requests_only` (§3.4) [Ver] | owner PRs: one bot approval satisfies it (§3.4), with or without B (09:26 rule suite). The owner could then merge an owner PR normally after a bot approval. It would look reviewed, would not be counted as a bypass merge (S5:439 and the §3 measures at S5:862, 874), and would probably show as rule suite `pass` [Inf, untested] |
| Step 5a, merge restriction | Candidate B refused every bot merge (`merge`, `merge-async`, bot PRs and bot-approved owner PRs); owner normal and bypass merges worked; rule suites show the refusals (§3.5) [Ver] | **Owner decision (2)** below. Measured on `p0-10-probe/base`, not on `main` |
| Step 6, runbook | Update-branch with an unchanged diff does not dismiss approvals, and a kept approval moves to the new head (§6) [Ver]; commit as the bot; read merge state as the merging account | whether update-branch counts as a push for last-push approval, and 3.8 (owner update-branch, then approve, then merge): both untested. The owner-authored CI-change PRs that step 6 routes through the PR-only bypass (S5:397-400) could instead be merged normally after a bot approval, even with B [Inf, untested]; see decision (2) |
| (a) | — | after step 5. As written ("approved commit = merged head", S5:409-410) it cannot detect an approval given on an earlier head, because a kept approval reports the new head (§6) [Ver]. Decision (4) |
| (b) | refused on the probe branch (3.1, 3.2) [Ver] | re-run on `main` after step 5 |
| (c) | bot push dismisses the approval (3.9, 3.11) [Ver]; bot update-branch with an unchanged diff does not (4.8) [Ver] | the owner-update half (3.8) untested |
| (d) | **fails as written**, with or without B. Part 1 (`REVIEW_REQUIRED`) fails either way (#189, #192 showed `APPROVED`); part 2 (the bot's merge refused) holds only with B (4.11); part 3 (only the PR-only bypass can merge it) is not shown [Ver; part 3 Inf, untested] (§3.4) | needs rewording in either case; owner decision (2) |
| (e) | PASS on the probe branch (3.5, 4.6) [Ver] | re-run on `main` |
| (f) | the bot is an outside collaborator, write, not admin [Owner-rep] | step 3 |
| (g) | workflow refusal text and control (§3.3); `current_user_can_bypass` `never` for the bot, `pull_requests_only` for the owner; `bypass_actors` null for the bot (3.7) [Ver] | the full probe with the agent token: private-repo 404, hooks/keys 403 or 404 |
| (h) | inputs only (§4 check 10) | step 3 |
| (i) | with B: the bot cannot merge an owner-approved head; the owner's merge succeeds; it was logged as rule suite `pass`, not `bypass` (4.3) [Ver] | the org audit log (decision (3)) |

**Decisions for the owner.** This record does not make them.

1. **Token type.** The recommendation is classic `public_repo` with **no** `workflow` scope. It is the least
   privilege that worked for every operation the agent needs (§3.2), and the fine-grained token could not be
   minted.
   - It depends on the repository staying public (owner decision of 2026-10-28). If the repository were made
     private, the token would stop working (fail closed, 1a Q2).
   - Adopting it needs these texts amended, because they say `repo`: S5 P0-10 step 2, S5 §2.3 item 1, and S6
     D-13/OC-1.
2. **Candidate B on `main` as the step-5a merge restriction.** Settings as tested: "Restrict who can push", users
   [], `enforce_admins` false.
   - Because of 3.4, B is now a precondition for the merge-refusal part of safeguard (d), not only for (i).
     Without B, the bot can approve and merge any owner-authored PR. That includes the owner-authored CI changes
     that step 6 routes through the PR-only bypass [Inf].
   - (d) needs rewording whether or not B is adopted (§3.4). If B is not adopted, the OC-2 exception also covers
     owner PRs, not only bot PRs [Inf].
   - **Even with B on `main`** [Inf, untested]: the bot's approval still satisfies the review rule on owner PRs
     (`probe-review` passed in the 09:26 rule suite for #192). So the owner's own PRs, including step 6's CI-change
     PRs (S5:397-400), could be merged normally after a bot approval, with no bypass.
     - Such a merge would look reviewed.
     - It would not be counted as an owner-bypass merge (S5:439; the §3 measures at S5:862 and 874).
     - It would probably show as rule suite `pass`.
     - The owner merging a bot-approved owner PR normally was never measured (§9).
3. **The audit-log check (optional).** Does the org audit log show `protected_branch` create/destroy events on
   `p0-10-probe/base`, and any per-merge events? It is still pending.
4. **Probe (a)'s signal.** "Approved commit = merged head" cannot tell an approval carried over by update-branch
   from one given on the merged head (§6) [Ver]. Either (a) gets another signal, or the owner accepts the
   residual. Possible signals: the review's `submitted_at` against the time the head was pushed, or the PR's
   timeline events [Inf].

## 9. Open items

- The org audit-log check for `protected_branch` events on `p0-10-probe/base` (optional, owner; decision (3)).
- `p0-10-s3`: the security-log time of its deletion, and whether it was still listed at sitting 3b step S3 (§3.8).
- 3.8: whether a merge is refused after the owner's update-branch and approval, and so whether update-branch
  counts as a push for last-push approval (both untested; §6).
- The owner's normal merge (no bypass) of a bot-approved owner PR: never measured (decision (2)).
- Probe (a): another signal than "approved commit = merged head", or an accepted residual (decision (4)).
- Update-branch on a PR whose diff changes: whether it then dismisses approvals (untested).
- The value refused with 401 in the first attempt's setup: the owner confirms whether it was a separate token and,
  if so, that it is deleted (§3.8).
- The UI merge button and `gh pr merge` by the bot under B (untested; the API routes were refused).
- What `gh auth login --with-token` says for a `public_repo` token (untested; `GH_TOKEN` worked).
- The cause of the fine-grained contradiction with July (unknown).
- Probe (g) in full, after step 2, with the agent token.
- The expired `dentaledge-bot-pat`: step 2's proof of refusal.

## 10. Sources

GitHub docs fetched by this record's reviewer (accessed 2026-10-29) [Docs, fetched by the reviewer]:

| Source | URL | What it verified here |
|---|---|---|
| About protected branches | https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches/about-protected-branches | the general rule "any pull request that affects code with a code owner must be approved by that code owner", which 3.4 contradicts; Update branch dismisses approvals as stale only "if the diff changes" (fits 4.8, 4.13b). It is also the page GitHub's 405 refusal under B links to [Ver] |
| About code owners | https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/customizing-your-repository/about-code-owners | silent on a PR author who is the sole code owner |

GitHub docs consulted in the runbook review round 3 (accessed 2026-10-28). Per the notes, they are silent on a PR
author who is the sole code owner. They are the rulesets docs (the notes do not say which page; 1a §8 S1-S4 are
the rulesets pages), about-code-owners, about-protected-branches (both above), and the GitHub changelog (the notes
do not name the entries).

Docs relied on from the step-1a record (accessed 2026-10-27; see its §8 for the full list):
- S7 REST rules: `bypass_mode`, `current_user_can_bypass`, `bypass_actors` visibility. Per the notes, the
  `RepositoryRole` id for admin is not listed there.
- S8 Managing your personal access tokens: the outside-collaborator gap that T1 matched.
- S12 Scopes for OAuth apps: `public_repo`, `workflow`.
- REST rule suites: https://docs.github.com/en/rest/repos/rule-suites
- [Comm] C2: the workflow-refusal wording, now measured (§3.3).

Repository and session sources:
- the step-1a record;
- S5 P0-10 (`S5-prioritized-roadmap.md:324-444`), B5 (`:812`) and §2.3 (`:820-826`);
- the coordinator's results notes and runbooks (`sitting-3-runbook.txt`, `sitting-3b-ordered.txt`,
  `phase-a-steps.txt`, `probe-checks.json`, `probe-review.json`, `probe-classic-b.json`), kept in the session
  scratchpad and not committed.

## 11. Method and limits

- **Who ran what.** The owner ran every GitHub write, either with the `!` prefix inside the Claude session (phase
  A, phase A', cleanup; no bot token existed then) or outside Claude (sittings 1, 2, 3 and 3b). The coordinator
  only read: REST and GraphQL GETs, rule suites, and re-reads between steps.
- **Claude closed during sittings 1 and 2.** The runbooks required Claude closed while a token was loaded, and no
  deviation was reported for those sittings [Owner-rep; runbook-required]. The only reported deviation is the
  first attempt of sitting 3 (§7).
- **Tokens.** Each test token was minted from the `dentaledge-bot` account in the browser (a private window, per
  the sitting-3 runbooks). Each was used only in a separate shell outside agent sessions, with one exception (§7,
  process deviation). None was printed: in sittings 3 and 3b it was read with `read -rs`, and git received it
  through the inline helper. The traces show the helper's text, not the value. Each token was deleted after use
  (§3.8).
- **Guards.** Every merge, approval and update was guarded by a check that the PR's base is `p0-10-probe/base`.
  Probe rulesets were created disabled, read back, then activated by a guarded script. Cleanup (`c1-cleanup.sh`)
  deleted rulesets only after checking their names and targets, before the branches (1a §4 order).
- **Independent review of the runbooks.** Findings S3-R-1 to S3-R-30 over 4 rounds, ending APPROVED:
  - rounds 1-2 (S3-R-1 to S3-R-20) approved the sitting-3 runbook;
  - round 3 (S3-R-21 to S3-R-27) approved sitting 3b;
  - round 4 closed those findings and added optional notes S3-R-28 to S3-R-30, all applied before the sitting
    (the never-loaded stuck path, the phase A' precondition in the 3b header, and 4.13b's possible 422).
- **Limits.**
  - One repository, on the GitHub Team plan, measured over one day (2026-10-28 to 2026-10-29).
  - B was measured on a probe branch, not on `main`.
  - Settings-screen results are owner-reported.
  - GitHub's behaviour and docs may change. The fine-grained result already differs from July 2026.

## 12. Review round 1 (2026-10-29): the author's answers

The reviewer's findings P1B-R-1 to P1B-R-12 on `16a65c9`. Each line says what changed; **only the reviewer closes a
finding** (`docs/REVIEW_PROTOCOL.md`).

| ID | Change made |
|---|---|
| P1B-R-1 | §6: "update-branch counts as a push for last-push approval" withdrawn and marked untested, with the reason (the 08:50 and 09:14 suites are owner PRs #190 and #191 with no reviews, so the owner was the last pusher anyway). The 3.8 [Inf] is reworded. §3.4's 3.8 row and 3.5 row adjusted. §8 step-6 row moves it to "Still needs". §9 lists it with 3.8 |
| P1B-R-2 | §6: the "probe (a) catches that" claim withdrawn. The coordinator's re-read is recorded: kept approvals report the new head as `commit_id` (#193, #192), and dismissed reviews keep theirs (#188). §8 (a) row, new decision (4) (another signal such as `submitted_at` against the push time or timeline events, or an accepted residual), and a §9 item |
| P1B-R-3 | §3.4 and the §8 (d) row split S5 (d) (`S5:415-417`) into its three parts. Part 1 fails either way, part 2 holds only with B, and part 3 is [Inf, untested]. (d) needs rewording in either case (§1, §3.4, §8, decision (2)). The finding cited S5:424-426; on this branch (d) is at 415-417 |
| P1B-R-4 | Decision (2) and the §8 step-5 and step-6 rows add the consequence that holds even with B [Inf, untested]: a bot approval satisfies `probe-review` on owner PRs (09:26 suite), so owner PRs, including step 6's CI-change PRs (`S5:397-400`; the finding cited 415-417), could merge normally, look reviewed, escape the bypass count (S5:439, 862, 874) and probably show `pass`. §9 adds "owner merge of a bot-approved owner PR: never measured". §1 mentions it |
| P1B-R-5 | §3.5 (4.13) and §6: the "propagation lag after B's removal" claim removed. The two `BLOCKED` reads are explained as 4.11's conditional lines under B, and 4.13's single read was `CLEAN`. The owner's `UNKNOWN` after a base move (4.7) is kept |
| P1B-R-6 | §5 correction 5 quotes 1a:25-26, 1a:180-181 and the 1a:586 T4 row (wording checked against the 1a file), and states how 3.4 contradicts each on owner-authored PRs |
| P1B-R-7 | §3.4: the docs are not just silent; the measurement contradicts About protected branches' general code-owner rule. §6: "does not dismiss approvals" is limited to an unchanged diff, matching that page's "if the diff changes". About code owners: silent. Both pages are in §10 as [Docs, fetched by the reviewer], accessed 2026-10-29, and the tag is in the legend |
| P1B-R-8 | §3.5: the 4.10 → 4.13 differential reads "same PR and head; the owner re-approved in between (4.11's conditional lines, 13:27:14Z)" |
| P1B-R-9 | §3.9 and §5 correction 4: `rule_source` is `{"type":"protected_branch"}` with no id or name. §3.5: B also added `deletion` and `non_fast_forward` evaluations |
| P1B-R-10 | [Comm] added to the tag legend, along with "by the reviewer" for [Ver]. §2: after-cleanup `allow_auto_merge` cites the reviewer's live read, and the bypass row reads "none [Ver by the coordinator]". §11: Claude closed in sittings 1 and 2 is [Owner-rep; runbook-required]. §3.4 row 3.2 cites rule suite 4779055958 (2026-10-28 16:15:42 -04:00) |
| P1B-R-11 | §3.8: the 401 value in the first attempt's setup is stated as unknown (a bad paste or a separate token). §9 asks the owner to confirm whether it was a separate token and, if so, that it is deleted. §1's token sentence is adjusted |
| P1B-R-12 | §1: the main finding and the decisions paragraph are scoped to the test branch with the planned review rules, expected to be the same on `main` once step 5 adds them [Inf]; today `main` requires no approvals |
