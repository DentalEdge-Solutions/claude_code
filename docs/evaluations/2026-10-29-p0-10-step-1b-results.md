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
· **[Owner-rep]** owner-reported from a settings screen or an action without captured output · **[Docs]** an
official GitHub source, as the step-1a record or the 2026-10-28 review round read it · **[Inf]** inference from the
measurements · **untested** not measured, with the reason.

Times are local (EDT) as recorded in the session notes. "The notes" means the coordinator's step-1b results notes,
the single source of every result below.

## 1. Plain-language summary

**What we tested.** We wanted to know if a separate GitHub account for the agent (`dentaledge-bot`) can do its
work, and if GitHub can stop that account from merging. All tests ran on a throwaway branch
(`p0-10-probe/base`), never on `main`. The owner ran every test. The test tokens were short-lived. All are
deleted, and two of the three were proved dead by a refused use (§3.8).

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
  safeguard (d) expected the opposite. **Safeguard (d) therefore fails as written.**
- **Candidate B stops every bot merge.** Candidate B is the classic branch setting "Restrict who can push", with
  nobody listed and admins not enforced. With B on, GitHub refused every merge by the bot. That includes owner PRs
  that the bot had approved. The owner's normal merges and bypass merges kept working.
- **Without B, the bot merged.** When B was removed, the bot merged a PR the owner had approved, and an owner PR
  the bot had approved. This confirms the "residual" risk the roadmap describes.
- **The bypass does not skip checks.** The owner's bypass merge was refused while the test check failed, and
  worked when it passed.
- **Cleanup is done and checked.** The test rulesets, the classic rule and the test branches are gone. `main` is
  as it was.

**What the owner now decides** (§8): which token type to adopt, and whether to put candidate B on `main`. Without
B, safeguard (d) does not hold.

## 2. Repository state, before and after

| What | Before (2026-10-28) | After cleanup (2026-10-29) |
|---|---|---|
| Rulesets | `main-protection` 19737624 only (1a §2) | only `main-protection` 19737624: active, `~DEFAULT_BRANCH`, no bypass, rules deletion, non_fast_forward, pull_request, required_status_checks; unchanged [Ver by the coordinator] |
| Classic branch protection | none on the repository [Owner-rep]; `GET branches/main/protection` → 404 "Branch not protected" [Ver] | `branchProtectionRules` [] [Ver by the coordinator] |
| `main` | `b3d3d58` | `b3d3d58` [Ver by the coordinator] |
| Open PRs | none into `main` (phase A read) [Ver] | none [Ver by the coordinator] |
| `allow_auto_merge` | false (1a §2) | false (step 4.14) [Ver] |
| `main-protection` bypass list | empty [Owner-rep] | unchanged |
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
| bot merges its own PR before any approval, check green (3.2, #188) | refused | `gh pr merge`: client-side "not mergeable: the base branch policy prohibits the merge". `PUT …/merge`: HTTP 405 "Repository rule violations found — Waiting on code owner review from dentaledgesolutions." [Ver] | PASS: the server names the code-owner review as the only violation |
| bot PR, owner approves, check green, bot merge, no candidate | merges (the OC-2 residual) | not run in T3, on purpose (3.12: do not merge before T4). Run in T4 step 4.13: **MERGED** (§3.5) [Ver] | residual confirmed |
| bot pushes after the owner's approval (3.9, 3.11, #188) | approval dismissed | owner view `REVIEW_REQUIRED` after each bot push (`2e45f77`, `112abd5`); after re-approval both views `APPROVED`/`CLEAN` (3.10, 3.12) [Ver] | PASS |
| owner clicks Update branch on a bot PR, then approves (3.8, #188) | approval likely cannot satisfy last-push [UNVERIFIED in 1a] | after the owner's update-branch (`cd9d826`) and approval, owner and bot views both `APPROVED`/`CLEAN` [Ver]. No merge was attempted at that head | **untested**; see §6 |
| bot updates the branch, then owner approves (4.8-4.9, #193) | mergeable | bot update-branch (`60ef666`) did **not** dismiss the owner's approval (owner view `APPROVED`/`BLOCKED`); after the owner's re-approval, owner view `CLEAN` [Ver] | mergeable (owner view) |
| owner-authored PR approved by the bot (3.3-3.4, #189) | `REVIEW_REQUIRED`; bot merge refused | bot approval allowed ("✓ Approved"). First attempt: `APPROVED` in both views, merge `BLOCKED` (check missing), so the STOP rule ended the sitting. Sitting 3b, check green: both views `APPROVED`/`CLEAN`; bot `PUT pulls/189/merge` → **MERGED** (`5d5b42b`, `merged_by` `dentaledge-bot`). Rule suite 08:46, `309a298`→`5d5b42b`: every rule pass, including `probe-review`/`pull_request` [Ver] | **FAIL** against the expectation; main finding |
| owner PR, check `failure`, bypass merge (3.5, #190; also 4.6, #191) | refused (probe (e)) | "Repository rule violations found / Required status check "p0-10-probe/ci" is failing." Rule suite 08:50: `required_status_checks` fail; `probe-review` fail ("New changes require approval from someone other than the last pusher") [Ver] | PASS: the bypass does not skip checks |
| owner PR, check `success`, bypass merge (3.6, #190; also 4.6, #191) | merges without review | MERGED; rule suite 08:51 result `bypass` (only `probe-review` failed, and was bypassed); 4.6 merged at 09:14:59, `bypass` [Ver] | PASS |
| `GET rulesets/26068762` as bot / as owner (3.7) | `never` / `pull_requests_only`; no `bypass_actors` for the bot | bot: `never`, `bypass_actors` null. Owner: `pull_requests_only`, `bypass_actors` [{`actor_id` 5, `RepositoryRole`, `pull_request`}] [Ver] | PASS |

**Why the owner PR merged** [Ver by the coordinator, GraphQL, 2026-10-28]:
- #189 had `reviewRequests` [] (no code-owner request) and one `APPROVED` review, from the bot.
- #188 had a review request for `dentaledgesolutions` with `asCodeOwner` true.
- So the owner **is** recognised as code owner. On a PR the owner authored, no code-owner review was required,
  because the author is the only code owner. One approval by anyone else, the bot included, satisfies
  `probe-review`.
- The docs read in review round 3 (rulesets, about-code-owners, about-protected-branches, changelog; accessed
  2026-10-28) say nothing about a PR author who is the sole code owner. This result is measured [Ver], not
  documented [Docs].
- Consequence: S5 acceptance (d) **fails as written**, unless a merge restriction blocks the bot (§3.5, step
  4.11).

### 3.5 T4 candidate B — PASS

Candidate B (`probe-classic-b.json`): classic protection on pattern `p0-10-probe/base`, `restrictions` users,
teams and apps [], `enforce_admins` false, no required checks or reviews in the classic rule. Step 4.1 read back
`{"enforce_admins":false,"restrictions":[]}`, exactly one rule (`p0-10-probe/base`, `restrictsPushes` true,
`isAdminEnforced` false), and `main` still 404 [Ver].

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
- 4.13: the bot merged the owner-approved, green #193 → **MERGED** (`9e62dd5`). The residual is confirmed. The bot's
  view showed `BLOCKED` twice, then `CLEAN` (propagation lag after B's removal).
- 4.13b: the owner updated #192 (`11b21a8`; the bot's approval was not dismissed). The bot re-approved and merged
  it → **MERGED** (`9c027d9`). So it was B that refused 4.11.

Since 3.4 merged, 4.11 is unambiguous: B's refusal, not the review rule, stopped the bot on an owner PR. The
differential 4.10 → 4.13 (same PR, same approval, B on then off) proves B's effect on bot PRs.

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

Also in the first attempt's setup, one attempt loaded a value that GitHub refused (401) before the third attempt
showed `dentaledge-bot` [Owner-rep].

### 3.9 Rule-suites API on Team

- `GET /repos/{o}/{r}/rulesets/rule-suites` works on this Team org [Ver by the coordinator, 2026-10-28]. HTTP 200,
  with entries for the last three merges to `main`, actor `dentaledgesolutions`, result `pass`.
- It gave per-rule evaluations for every step above. That includes the classic `authorization` rule from candidate
  B, which shows with `rule_source` null [Ver].
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
   with `rule_source` null (§3.9) [Ver]. Whether the audit log also has them is unchecked.

## 6. Other observations

- **`mergeStateStatus` is viewer-specific** [Ver]. Under B, #193 and #192 showed `CLEAN` to the owner and `BLOCKED`
  to the bot (4.5, 4.11). After a base move, the owner saw `UNKNOWN` and the bot `BEHIND` (4.7). Read the merge
  state from the account that will merge.
- **Propagation lag** [Ver]. After B was removed, the bot's view showed `BLOCKED` twice before `CLEAN` (4.13).
  Right after a base move the owner's view showed `UNKNOWN` (4.7). The runbooks waited `sleep 10` after each
  update-branch. A single read right after a change is not reliable [Inf].
- **Update-branch and approvals** [Ver]:
  - It does not dismiss approvals: the bot's update of #193 (4.8) kept the owner's approval, and the owner's update
    of #192 (4.13b) kept the bot's.
  - It does count as a push for last-push approval. Rule suites 08:50 and 09:14 show `probe-review` failing with
    "New changes require approval from someone other than the last pusher" after the owner's own update-branch.
  - [Inf] An approval can therefore survive while the head changes under it. Probe (a)'s check "approved commit =
    merged head" is what catches that.
- **3.8 is untested.** After the owner's update-branch and approval, both views showed `APPROVED`/`CLEAN`, against
  the expectation "NOT CLEAN". No merge was tried at that head. So whether the last-push rule would have refused is
  not known. [Inf] `mergeStateStatus` may not reflect the last-push rule. The rule suites above show the rule does
  count the owner's update as a push.
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
| Step 5, review ruleset | On bot PRs, as designed: self-approval refused, no merge without the code-owner approval, stale dismissal on bot pushes, admin-role (`actor_id` 5) PR-only bypass, checks not bypassable, `current_user_can_bypass` `never`/`pull_requests_only` (§3.4) [Ver] | owner PRs: one bot approval satisfies it (§3.4) |
| Step 5a, merge restriction | Candidate B refused every bot merge (`merge`, `merge-async`, bot PRs and bot-approved owner PRs); owner normal and bypass merges worked; rule suites show the refusals (§3.5) [Ver] | **Owner decision (2)** below. Measured on `p0-10-probe/base`, not on `main` |
| Step 6, runbook | Update-branch counts as a push for last-push and does not dismiss approvals (§6) [Ver]; commit as the bot; read merge state as the merging account | 3.8 (owner update-branch, then approve, then merge) untested |
| (a) | — | after step 5; (a)'s "approved commit = merged head" check matters because approvals survive update-branch (§6) [Inf] |
| (b) | refused on the probe branch (3.1, 3.2) [Ver] | re-run on `main` after step 5 |
| (c) | bot push dismisses the approval (3.9, 3.11) [Ver]; bot update-branch does not (4.8) [Ver] | the owner-update half (3.8) untested |
| (d) | **fails as written** without B (3.4); holds with B (4.11) [Ver] | owner decision (2); the wording of (d) (expects `REVIEW_REQUIRED`) does not match GitHub's behaviour |
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
   - Because of 3.4, B is now a precondition for safeguard (d), not only for (i). Without B, the bot can approve
     and merge any owner-authored PR. That includes the owner-authored CI changes that step 6 routes through the
     PR-only bypass [Inf].
   - If B is not adopted, (d) needs rewording, and the OC-2 exception covers owner PRs as well as bot PRs [Inf].
3. **The audit-log check (optional).** Does the org audit log show `protected_branch` create/destroy events on
   `p0-10-probe/base`, and any per-merge events? It is still pending.

## 9. Open items

- The org audit-log check for `protected_branch` events on `p0-10-probe/base` (optional, owner; decision (3)).
- `p0-10-s3`: the security-log time of its deletion, and whether it was still listed at sitting 3b step S3 (§3.8).
- 3.8: whether a merge is refused after the owner's update-branch and approval (untested).
- The UI merge button and `gh pr merge` by the bot under B (untested; the API routes were refused).
- What `gh auth login --with-token` says for a `public_repo` token (untested; `GH_TOKEN` worked).
- The cause of the fine-grained contradiction with July (unknown).
- Probe (g) in full, after step 2, with the agent token.
- The expired `dentaledge-bot-pat`: step 2's proof of refusal.

## 10. Sources

GitHub docs consulted in the 2026-10-28 review round (accessed 2026-10-28). Per the notes, they are silent on a PR
author who is the sole code owner:

| Source | URL | What it verified here |
|---|---|---|
| Rulesets docs (the notes do not say which page; 1a S1-S4 are the rulesets pages) | see 1a §8 S1-S4 | silence on the sole-code-owner author |
| About code owners | https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/customizing-your-repository/about-code-owners | same |
| About protected branches | https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches/about-protected-branches | same; it is also the page GitHub's 405 refusal under B links to [Ver] |
| GitHub changelog | (the notes do not name the entries) | same |

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
- **Tokens.** Each test token was minted from the `dentaledge-bot` account in the browser (a private window, per
  the sitting-3 runbooks). Each was used only in a separate shell outside agent sessions, with one exception (§7,
  process deviation). None was printed: in sittings 3 and 3b it was read with `read -rs`, and git received it
  through the inline helper. The traces show the helper's text, not the value. Each token was deleted after use
  (§3.8).
- **Guards.** Every merge, approval and update was guarded by a check that the PR's base is `p0-10-probe/base`.
  Probe rulesets were created disabled, read back, then activated by a guarded script. Cleanup (`c1-cleanup.sh`)
  deleted rulesets only after checking their names and targets, before the branches (1a §4 order).
- **Independent review of the runbooks.** Findings S3-R-1 to S3-R-30 over 4 rounds, ending APPROVED. Rounds 1-2
  (S3-R-1 to S3-R-20) approved the sitting-3 runbook; round 3 (S3-R-21 to S3-R-27) approved sitting 3b.
- **Limits.**
  - One repository, on the GitHub Team plan, measured over one day (2026-10-28 to 2026-10-29).
  - B was measured on a probe branch, not on `main`.
  - Settings-screen results are owner-reported.
  - GitHub's behaviour and docs may change. The fine-grained result already differs from July 2026.
