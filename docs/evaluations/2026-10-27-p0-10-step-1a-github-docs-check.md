# P0-10 step 1a — GitHub docs check (the R-B-9 gate)

> **Date:** 2026-10-27 · **Branch:** `docs/p0-10-step-1a-docs-check` (base `d7ea01f`) · **Roadmap:**
> `docs/evaluations/2026-10-22-optimization-strategy/S5-prioritized-roadmap.md` P0-10 step 1a (lines 324-444);
> S6 D-12, D-13, OC-1, OC-2; notes R-B-9, R-A-14, R-A-15, V2-ID-3, V2-ID-7, V3-ID-3, V-S2-16.
> **Installed:** `gh` 2.92.0, git 2.54.0. Researcher's record, returned to the owner **before** any production
> account, token or ruleset step (R-B-9). An independent reviewer checks it (`docs/REVIEW_PROTOCOL.md`).
> **No GitHub change was made**: no setting, ruleset, branch, token, review or comment.

Tags: **[Docs]** quoted from an official GitHub source (docs.github.com, the REST reference, the GitHub changelog
or blog, cli.github.com, git-scm.com), all accessed 2026-10-27 · **[Ver]** measured read-only in this session ·
**[Inf]** my inference from the cited sources · **[Comm]** community source, corroboration only ·
**[UNVERIFIED]** the docs are silent or contradict each other; it becomes a step-1b test (§4).

Docs pages were read as markdown through `https://docs.github.com/api/article/body?pathname=<page path>`, which
returns the same article text as the HTML page; the URLs in §8 are the human-readable pages.

## 1. Plain-language summary

**What works, per the docs.**
- Two rulesets on `main` combine: every rule of both applies and the strictest version wins, and a bypass is
  granted per ruleset. So a review ruleset whose only bypass is "For pull requests only" does not let anyone skip
  the checks of `main-protection`, which has no bypass. The docs say this in two places (about-rulesets and the
  rulesets GA blog post); probe (e) confirms it.
- Pull request authors cannot approve their own pull requests. A code-owner rule with `* @<owner>` therefore means
  only the owner's approval can satisfy it, and an approval by `dentaledge-bot` cannot.
- Individual **users** can be bypass actors on repository rulesets since the changelog of 2026-05-07, which
  answers R-A-14. The docs page for creating rulesets still lists only roles, teams, apps and Dependabot, so the
  page lags the changelog. Choice (x), the admin role, still works and does not need to change.
- The required checks of `main-protection` are pinned to GitHub Actions (`integration_id` 15368) [Ver]. A commit
  status posted by the bot cannot satisfy them.
- An outside collaborator on a **public** repository uses no paid seat. The docs say a seat is used only for a
  **private** repository. This settles the "outside-collaborator billing" [Asm] for this repository.

**What does not work, or is not documented.**
- **Token.** The docs say twice that a fine-grained token does not work for an outside collaborator: "Outside
  collaborators can only use personal access tokens (classic) to access organization repositories that they are a
  collaborator on". This repository's own record says the opposite. On 2026-07-25 a fine-grained token minted by
  `dentaledge-bot`, with this organisation as resource owner, pushed to this repository: "an org-scoped
  fine-grained single-repo PAT now grants real write — verified" (draft-PR design spec of 2026-07-24, lines
  64-73; Q8). The docs and the measurement disagree. Only step 1b can settle it.
- **Ruleset "Restrict updates".** The docs do not say whether merging a pull request counts as an "update".
  Community reports say it does, for **everyone**: bypass actors must tick "bypass rules" on every merge, and some
  report no checkbox at all, or that `gh pr merge --auto` is not honoured. On that design every owner merge is a
  bypass event. The newer `exempt` bypass mode (2025-09-10) avoids the prompt, but it is silent: "a bypass audit
  entry will not be created".
- **Workflow files.** A token without `workflow` scope can still commit a workflow file "if the same file (with
  both the same path and contents) exists on another branch in the same repository". Probe (g) must use new,
  unique contents. The agent can also carry a workflow file that already exists on another branch.

**What the owner should choose, and why.**
- **Merge restriction: candidate B first.** Use classic branch protection on `main` with "Restrict who can push
  to matching branches", list nobody (or only the owner), and keep the owner the only admin.
  - The docs say branch protection governs pushes "including merging a pull request into the branch", that "only
    users, teams, or apps that have been given permission can push", and that "People and apps with admin
    permissions to a repository are always able to push". So the owner merges normally, with no bypass prompt.
    The owner-bypass measure (§3 of S5) is not inflated, and the feature exists for this repository whatever the
    org plan.
  - Its weak points: the admin exemption covers every admin (the same condition as (x)); whether an owner merge
    leaves a `protected_branch.*` audit entry is [UNVERIFIED]; and classic protection is the older mechanism (one
    classic rule per branch, layered with the rulesets).
  - **Candidate A** comes second, a "Restrict updates" ruleset in one of two variants. A-exempt: the owner (user)
    or the admin role is exempt, so merges are silent and leave no bypass entry. A-PR: "For pull requests only",
    so every owner merge is a bypass and must be filtered out of the measure by ruleset.
  - Step 1b tests B, then A-exempt, then A-PR, one at a time. If none works without blocking the owner's normal
    merges, the OC-2 exception applies, with `allow_auto_merge` kept false (false today [Ver]).
- **Token: fine-grained first**, as OC-1 already says: Contents read and write, Pull requests read and write,
  Metadata read (always included), the single repository `claude_code`, no Workflows, an expiry of 90 days or
  less.
  - It is the narrowest token, and this bot measured it working on this repository in July 2026. But the docs say
  it should not work, so step 1b must prove that it does.
  - If it fails, use a **classic** token with no `workflow` scope. **`public_repo` is narrower than `repo`** and
    is enough while `claude_code` is public (OC-1 says `repo`; this is the owner's choice). If the repository is
    ever made private, the token stops working (fail closed) instead of reaching private repositories the bot is
    later added to.
  - Before using a classic token, the owner checks the org's "Restrict personal access tokens (classic) from
    accessing your organizations" setting. By default classic tokens are allowed.

**One new finding for step 3** [Ver/Inf].
- On this laptop, git authenticates to `https://github.com/...` through the **`osxkeychain`** helper set in the
  system gitconfig (`/opt/homebrew/etc/gitconfig`). It does not go through `gh`, so `gh auth switch` and
  `gh auth status` say nothing about whose credential `git push` uses.
- An item in the keychain stored by `git-credential-osxkeychain` can be returned to any process that runs that
  helper [Inf]. "Only the agent account on the laptop" (probe (f)) therefore needs the owner's github.com keychain
  item removed, not only the `gh` login. The owner measures this; the agent never reads the keychain.

## 2. Repository state read today [Ver]

| What | Read | Result |
|---|---|---|
| Visibility, owner | `gh repo view --json visibility,owner,isPrivate,isInOrganization,...` | `PUBLIC`, owner `DentalEdge-Solutions` (organization); merge, squash and rebase merges all allowed |
| Auto-merge | `gh api graphql` (call 1) | `autoMergeAllowed: false` |
| Rulesets | `gh api graphql` (call 1) | one ruleset, `main-protection`, `ACTIVE`, target `~DEFAULT_BRANCH`: deletion, non-fast-forward, pull request (`requiredApprovingReviewCount` 0, code-owner review, last-push approval and stale-dismissal all false), required status checks (strict; 4 contexts) |
| Check source pinning | `gh api graphql` (call 2) | all 4 required contexts carry `integrationId: 15368` (the GitHub Actions app) |
| PR #4 | `gh pr view 4 --json ...` | author `dentaledge-bot` (`is_bot: false`, a User account), head `proposal/2026-07-24_22-54-03` in `DentalEdge-Solutions/claude_code` (`isCrossRepository: false`), created 2026-07-25, `CLOSED`, not merged |
| CI triggers | `.github/workflows/ci.yml:3-7` | `push` and `pull_request` on `main` only, so CI does not run for PRs into `p0-10-probe/**` |
| Git credential helper | `git config --show-origin --show-scope --get-regexp '^credential\.'` | `system  file:/opt/homebrew/etc/gitconfig  credential.helper osxkeychain`; no `gh` helper; remote `origin` is HTTPS |
| Token variables | count of `GH_TOKEN`/`GITHUB_TOKEN`/`GH_ENTERPRISE_TOKEN` in this session's environment | 0 (names counted, no values read) |

Not read, on purpose: bypass actors (admin-only data), classic branch protection on `main` (admin-only), hooks,
keys, any credential store, `~/.config/gh/hosts.yml`. Those are owner checks (§5).

## 3. Findings, question by question

### Q1 — Merge-restriction candidates (OC-2, V2-ID-3)

**Candidate A — ruleset "Restrict updates".**
- [Docs] Available rules: "Restrict updates: If selected, only users with bypass permissions can push to branches
  or tags whose name matches the pattern you specify." "Restrict deletions … This rule is selected by default."
- [Docs] The page does **not** say whether a pull request merge is an "update". [UNVERIFIED]
- [Comm] community discussion #113172 (2024-03 to 2026-08, no GitHub staff reply): with "Restrict updates",
  merging is blocked for everyone, including the repository owner and bypass-list members, with "The base branch
  does not allow updates". Bypass actors get a "bypass branch protections" checkbox on each merge. One report
  (2025-08-26) says admins on the bypass list got no checkbox at all. Another (2026-07-23) says an App on the
  bypass list was honoured by the synchronous merge endpoint but not by `gh pr merge --auto`. A workaround
  (2025-10-29) puts "Restrict updates" alone in a ruleset with admins "Exempted from rules".
- [Docs] Bypass modes (REST "Create a repository ruleset"): `bypass_mode` is one of `always`, `pull_request`,
  `exempt` (default `always`): "pull_request means that an actor can only bypass rules on pull requests. …
  pull_request is only applicable to branch rulesets. When bypass_mode is exempt, rules will not be run for that
  actor and a bypass audit entry will not be created."
- [Docs] Changelog 2025-09-10: rulesets "now let you exempt specific actors (roles, teams, or GitHub Apps) from all
  enforced rules with a new `exempt` bypass type"; "an exemption silently skips enforcement", whereas a standard
  bypass "generates prominent audit signals". Migration doc: Always allow, "The ruleset will be evaluated and the
  selected actor(s) will be prompted to bypass"; Exempt, "The ruleset will not be evaluated and no bypass prompt
  will be shown".
- **What the owner can still do** [Inf]: under A-PR (pull_request mode), merge only by bypassing; each owner merge
  is a ruleset bypass (rule insights "Bypass"). Under A-exempt, the owner merges normally, but the exempted ruleset
  is not evaluated for the owner at all, so no audit entry is created. The other rulesets still apply, because the
  exemption is per ruleset.
- **Logging** [Docs]: rule insights list "Actions where someone has bypassed one or more rulesets", filterable "by
  ruleset, branch, actor, and time period", and the rule-suites REST API returns the same data. So the §3 owner-bypass
  measure can be counted per ruleset (count only bypasses of the **review** ruleset) [Inf].

**Candidate B — classic "Restrict who can push to matching branches".**
- [Docs] Availability: "You can enable branch restrictions in public repositories owned by a GitHub Free
  organization and in all repositories owned by an organization using GitHub Team or GitHub Enterprise Cloud."
  `claude_code` is public and org-owned [Ver], so B is available whatever the org's plan.
- [Docs] Scope: "You can enforce certain workflows or requirements before a collaborator can push changes to a
  branch in your repository, including merging a pull request into the branch, by creating a branch protection
  rule." "When you enable branch restrictions, only users, teams, or apps that have been given permission can push
  to the protected branch." The setup step says "search for and select the people, teams, or apps who will have
  permission to push", so **specific users** can be named. "You can only give push access … to users, teams, or
  installed GitHub Apps with write access to a repository."
- [Docs] Admins: "People and apps with admin permissions to a repository are always able to push to a protected
  branch or create a matching branch." Separately, "By default, the restrictions of a branch protection rule do not
  apply to people with admin permissions … You can enable this setting [Do not allow bypassing the above settings]
  to apply the restrictions to admins … too." The two sentences do not say which wins if that setting is on.
  [UNVERIFIED] Keep "Do not allow bypassing" **off** for B.
- [Docs] Required checks still apply to the allowed pushers: "the people, teams, and apps that have permission to
  push to a protected branch will still be prevented from merging into the branch when the required checks fail"
  and "will still need to create a pull request when pull requests are required".
- [Comm/Inf] OpenSSF SCM best practices ("pushes_are_not_restricted") and CIS 1.1.15 treat this setting as the
  control that restricts "pushing or merging". The exact refusal shown to a non-allowed merger is [UNVERIFIED].
- **What the owner can still do** [Inf]: merge normally (an admin is always allowed). The owner's own PRs still
  need the review ruleset's PR-only bypass, and the checks of `main-protection` still apply (layering, Q4).
- **Logging** [Docs]: org audit-log events `protected_branch.policy_override` ("A branch protection requirement was
  overridden by a repository administrator") and `protected_branch.rejected_ref_update` ("A branch update attempt
  was rejected"). Only owners can read the org audit log, and it keeps 180 days. Whether an allowed admin's merge
  counts as an "override" is [UNVERIFIED]. Rule insights cover rulesets only, so B's refusals appear in the audit
  log, not in rule insights [Inf].
- [Docs] "Only a single branch protection rule can apply at a time"; rulesets and branch protection "work
  alongside each other, and all applicable rules are enforced". Whether a classic rule already targets `main` is
  an owner check (§5).

**Auto-merge and merge queue** [Docs]:
- "People with write permissions to a repository can enable auto-merge for a pull request." Keep
  `allow_auto_merge` false (false today [Ver]): otherwise the agent could arm a merge that completes at approval.
- "On a branch that requires a merge queue, the repository setting doesn't apply. **Merge when ready** enables
  auto-merge … even if auto-merge isn't allowed for the repository." "A user with write access … can add the pull
  request to the queue." **Do not enable a merge queue on `main`**: it would reopen the auto-merge path, and the
  queue's own merge is untested against either candidate [Inf].

**Comparison.**

| | A-PR (Restrict updates, PR-only bypass) | A-exempt (Restrict updates, exempt) | B (classic restrict push) |
|---|---|---|---|
| PR merge covered | [UNVERIFIED] docs silent; [Comm] yes | same | [Docs] yes ("including merging a pull request") |
| Owner's normal merge | bypass checkbox on every merge [Comm]; unreliable reports | normal [Docs: not evaluated] | normal [Docs: admins always] |
| Owner merge logged | as a bypass in rule insights [Docs] | no bypass entry [Docs] | audit-log entry [UNVERIFIED] |
| Inflates owner-bypass measure | yes, unless counted per ruleset | no | no |
| Can name the owner as a user | yes since 2026-05-07 [Docs] | user exemption [UNVERIFIED] (changelog names roles, teams, apps) | yes [Docs] |
| Plan | rulesets in use here today [Ver] | same | public repo in any org [Docs] |
| **Order for step 1b** | 3rd | 2nd | **1st** |

### Q2 — Tokens for `dentaledge-bot`

- [Docs] Fine-grained gaps ("Managing your personal access tokens"): "Using fine-grained personal access token to
  contribute to repositories where the user is an outside or repository collaborator." Under classic: "Outside
  collaborators can only use personal access tokens (classic) to access organization repositories that they are a
  collaborator on." Changelog 2025-03-18 (fine-grained PATs GA) lists the same gap: "Contributing to repositories
  where you're an outside collaborator or an unaffiliated open source contributor." No changelog entry closing the
  gap was found (search 2026-10-27).
- [Docs] Resource owner: "The token will only be able to access resources owned by the selected resource owner.
  Organizations that you are a member of will not appear if the organization has blocked the use of fine-grained
  personal access tokens." Whether an org where the user is only an outside collaborator appears is not said.
  [UNVERIFIED] The 2026-07-25 record says it did (Q8).
- [Docs] "Each token is limited to access resources owned by a single user or organization." "Tokens always include
  read-only access to all public repositories on GitHub." "Both … are tied to the user who generated them and will
  become inactive if the user loses access to the resource."
- **Org approval** [Docs] ("Setting a personal access token policy for your organization"): "Require administrator
  approval: An organization owner must approve each fine-grained personal access token that can access the
  organization. Fine-grained personal access tokens created by organization owners will not need approval. This is
  the default value." The other option is worded as "tokens created by organization **members**". "If you selected
  an organization as the resource owner and the organization requires approval … your token will be marked as
  `pending` … [and] will only be able to read public resources until it is approved." Changelog 2025-03-18: "The
  PAT approval flow is also enabled by default". Whether approval applies to an **outside collaborator's** token is
  not said. [UNVERIFIED]
- **Classic-PAT policy** [Docs]: setting name "**Restrict personal access tokens (classic) from accessing your
  organizations**", with the options "Restrict access via personal access tokens" and "Allow access via personal
  access tokens". Path: org **Settings → Personal access tokens → Settings → "Tokens (classic)" tab**. Default: "By
  default, both Personal access tokens (classic) and fine-grained personal access tokens are enabled." "Only
  fine-grained personal access tokens … are subject to approval. Unless the organization has restricted access by
  personal access tokens (classic), any personal access token (classic) can access organization resources without
  prior approval." If restricted, a classic token's "request will fail with a 403 response". "Regardless of the
  chosen policy, Personal access tokens will have access to public resources within the organization."
- **Fine-grained permissions for the agent** [Docs] (permissions table): `PUT /repos/{o}/{r}/pulls/{n}/merge`,
  `POST /repos/{o}/{r}/merges`, `git/refs` and trees are **Contents** write. Reviews and
  `PUT /repos/{o}/{r}/pulls/{n}/update-branch` are **Pull requests** write. `GET /repos/{o}/{r}/rulesets[/{id}]` is
  **Metadata** read, which every token has. **Workflows** write is required *additionally* for
  `PUT/DELETE contents/{path}`, `POST/PATCH git/refs` when workflow files are touched. `POST statuses/{sha}` is
  **Commit statuses** write (not granted). So the set is Contents RW + Pull requests RW (+ Metadata R), no
  Workflows, no Commit statuses, no Administration, no Webhooks. Note: "Using fine-grained personal access token to
  call the Checks API" is another listed gap. `gh pr checks` may fail with a fine-grained token, though check runs
  on a public repository are public [Inf] (step-1b test T1).
- **Classic `repo` without `workflow`** [Docs] (scopes table): `repo` "Grants full access to public and private
  repositories including read and write access to code, commit statuses, repository invitations, collaborators,
  deployment statuses, and repository webhooks … also grants access to manage organization-owned resources
  including projects, invitations, team memberships and webhooks." The real reach is bounded by the bot's role
  (write, so no webhooks or collaborator management here [Docs: role table]), but on **any** repository the bot can
  write to. `public_repo`: "Limits access to public repositories. That includes read/write access to code, commit
  statuses, repository projects, collaborators, and deployment statuses for public repositories and
  organizations." "Your personal access token (classic) can access every repository that you can access." With
  `repo`/`public_repo`, the bot **can** post commit statuses, but they cannot satisfy `main-protection`'s pinned
  checks (`integration_id` 15368 [Ver]; REST: "The optional integration ID that this status check must originate
  from").
- **Workflow scope** [Docs]: "`workflow`: Grants the ability to add and update GitHub Actions workflow files.
  Workflow files can be committed without this scope if the same file (with both the same path and contents) exists
  on another branch in the same repository." The exact refusal text is **not in the docs**. [Comm, many reports]:

  ```text
  ! [remote rejected] <ref> -> <ref> (refusing to allow a Personal Access Token to create or update workflow
  `.github/workflows/<file>.yml` without `workflow` scope)
  ```

  GitHub Apps get "… without `workflows` permission". The fine-grained wording is [UNVERIFIED]; probe (g)
  records it.
- **`gh` and token types** [Docs] (`gh auth login`): with `--with-token` "The minimum required scopes for the token
  are: `repo`, `read:org`, and `gist`", and "Favour setting `GH_TOKEN` for fine-grained personal access token
  usage." A classic `public_repo` token therefore cannot go through `gh auth login --with-token` validation [Inf]:
  use `GH_TOKEN`, or add the scopes `gh` asks for (`read:org` and `gist` are low-risk; `gist` lets the bot write
  gists) [Inf]. Step 1b checks it.
- **Expiry** [Docs]: fine-grained: "Under **Expiration**, select an expiration … Infinite lifetimes are allowed
  but may be blocked by a maximum lifetime policy". The org default maximum for fine-grained tokens is "366 days";
  the creation-link parameter takes "Integer between 1 and 366, or `none`" (default 30). Classic: "choose a default
  option or click **Custom** to enter a date"; "Personal access tokens (classic) do not have an expiration
  requirement". "GitHub automatically removes personal access tokens that haven't been used in a year."
  Recommendation: 90 days or less, recorded with the rotation date (probe (g) re-run).
- **Seat** [Docs] ("Adding outside collaborators"): "Unless you are on a free plan, adding an outside collaborator
  to a private repository will use one of your paid licenses." `claude_code` is public [Ver], so no seat [Inf].
  Also: "Outside collaborators cannot be added to a team", so the bot can never sit in an owner-only bypass team
  (helps choice (y)).

### Q3 — Bypass actors

- [Docs] REST (create/get ruleset): `actor_type` is one of `Integration`, `OrganizationAdmin`, `RepositoryRole`,
  `Team`, `DeployKey`, `User`. `actor_id` is "Required for Integration, RepositoryRole, Team, and User actor
  types … If actor_type is DeployKey, this should be null. OrganizationAdmin is not applicable for personal
  repositories." `pull_request` "is not applicable for the DeployKey actor type".
- [Docs] UI page ("Creating rulesets for a repository", today): "The following are eligible for bypass access:
  Repository admins, organization owners, and enterprise owners; The maintain or write role, or custom repository
  roles based on the write role; Teams, excluding secret teams; GitHub Apps; Dependabot."
- [Docs] **Changelog 2026-05-07**: "You can now add individual users as bypass actors on repository-level rulesets
  through the UI, REST API, and GraphQL." The docs page above has not caught up. **R-A-14 resolved: users are
  eligible** on repository rulesets [Docs]. That the UI offers `dentaledgesolutions` is a step-1b check. Which
  bypass modes a User actor may hold is not stated. [UNVERIFIED]
- [Docs] "For pull requests only": "The selected actor is now required to open a pull request to make changes to a
  repository, creating a clear trail of their changes in the pull request and audit log. The actor can then choose
  to bypass any branch protections and merge that pull request."
- [Docs] `current_user_can_bypass` (response field): enum `always`, `pull_requests_only`, `never`, `exempt`. The
  docs give no prose definition. [Inf] It reports, for the caller, the mode of the matching bypass entry (`never`
  when none). So probe (g) expects `never` for the bot and `pull_requests_only` for the owner on the review
  ruleset. If the owner were made `exempt` anywhere, `exempt`.
- [Docs] Who can read `bypass_actors`: "To prevent leaking sensitive information, the bypass_actors property is only
  returned if the user making the API request has write access to the ruleset." [Inf] that means admins (or a role
  with "edit repository rules"), so the bot's read omits it and the owner does the admin-side read (R-A-16, as
  planned). "Anyone with read access to a repository can view its active rulesets."
- [Docs] The `RepositoryRole` id for "admin" is not listed in the REST page. The owner picks "Repository admin" in
  the UI [Inf].

### Q4 — Two rulesets on `main`

- [Docs] About rulesets, "About rule layering": "A ruleset does not have a priority. Instead, if multiple rulesets
  target the same branch or tag in a repository, the rules in each of these rulesets are aggregated. If the same
  rule is defined in different ways across the aggregated rulesets, the most restrictive version of the rule
  applies. As well as layering with each other, rulesets also layer with protection rules targeting the same branch
  or tag."
- [Docs] Bypass is granted per ruleset ("you can allow certain users to bypass the rules in **the** ruleset").
  The GA blog (2023-07-24) gives the pattern: "you can write a couple of rulesets, one with a bypass list narrowly
  scoped, layered with another ruleset containing an empty bypass list", where "A bot can skip status checks but
  can't delete branches or force push".
- Consequence [Docs + Inf]: an owner PR-only bypass of the **review** ruleset leaves `main-protection`'s required
  checks (strict, pinned) and its own PR rule in force. An owner-bypass merge still needs green, up-to-date checks.
  That is probe (e). The most-restrictive rule also means `required_approving_review_count` resolves to the higher
  value (1) and the flags to `true` for everyone not bypassing the review ruleset [Inf].

### Q5 — Review rules

- [Docs] `required_approving_review_count`: "The number of approving reviews that are required before a pull
  request can be merged" (0-10). Approvals count "from people with write permissions in the repository or from a
  designated code owner".
- [Docs] `require_code_owner_review`: "Require an approving review in pull requests that modify files that have a
  designated code owner." CODEOWNERS: "Users and teams must have explicit `write` access to the repository"; "If you
  specify a user or team that doesn't exist or has insufficient access, a code owner will not be assigned"; "For
  code owners to receive review requests, the CODEOWNERS file must be on the base branch of the pull request";
  location `.github/`, root or `docs/`, first found wins; the docs recommend owning the file itself (e.g.
  `/.github/CODEOWNERS @owner_username`). Whether an **org owner's** access counts as "explicit" write is
  [UNVERIFIED]; the errors endpoint and step 1b T3 settle it.
- [Docs] `GET /repos/{o}/{r}/codeowners/errors`: "List any syntax errors that are detected in the CODEOWNERS file",
  query `ref` ("A branch, tag or commit name used to determine which version of the CODEOWNERS file to use.
  Default: the repository's default branch"), response `errors[]` with `line`, `column`, `kind`, `message`, `path`.
  Contents read for fine-grained tokens. Step 1b can check a CODEOWNERS on `p0-10-probe/base` with
  `?ref=p0-10-probe/base`, without touching `main` [Inf].
- [Docs] `require_last_push_approval`: "Whether the most recent reviewable push must be approved by someone other
  than the person who pushed it." Protected-branches page: "with this option, 'stale' reviews are not dismissed,
  and the pull request remains approved as long as someone other than the person who made the most recent changes
  approves it." "Reviewable push" is **not defined**. [UNVERIFIED]
- [Docs] `dismiss_stale_reviews_on_push`: "New, reviewable commits pushed will dismiss previous pull request review
  approvals." Protected-branches page: "If the diff changes from this state (for example, because a contributor
  pushes new changes to the pull request branch or clicks **Update branch**, or because a related pull request is
  merged into the target branch), the approving review is dismissed as stale"; and with either flag "approving
  reviews will be dismissed as stale if the merge base introduces new changes after the review was submitted."
- [Docs] Self-approval: "Pull request authors cannot approve their own pull requests."
- **R-A-15, "Update branch" by the owner** [Inf, UNVERIFIED]: the button creates a merge (or rebase) commit on the
  head branch, made by whoever clicks it, so the owner very likely becomes the last pusher. With last-push approval,
  the owner's approval then cannot satisfy the rule, and nobody else may (the bot is the author). Together with
  strict checks, which require an up-to-date branch, and stale dismissal, the workable order is: **the agent
  updates the branch** (`PUT …/pulls/{n}/update-branch`, Pull requests write) → CI → the owner approves → merge.
  The runbook (step 6) should say "the owner never clicks Update branch on agent PRs". Step 1b T3 tests both orders.

### Q6 — `gh` multi-account and the laptop's credential paths

- [Docs] `gh auth switch`: "If the specified host has two accounts, the active account will be switched
  automatically"; with more, `--user` or a prompt. `gh auth status` shows the "active account and authentication
  state on each known GitHub host" and marks the active account; `--show-token` prints the token (never use it in a
  session).
- [Docs] Precedence (`gh help environment`): `GH_TOKEN`, `GITHUB_TOKEN` (in order of precedence) "takes precedence
  over previously stored credentials".
- [Docs] Storage (`gh auth login`): the token is stored "in the system credential store"; if none is usable, "gh
  will fallback to writing the token to a plain text file"; `--insecure-storage` forces plain text.
  Multiple-accounts design doc (historical, v2.40.0): tokens live in "the system keyring managed by `gh`"; switching
  "will swap the token used by `gh` for API requests" and for git only when `gh` is the git credential helper;
  `auth logout` will "switch account where possible if the currently active user is the target", so logging out the
  owner while the bot is stored makes the bot active, and the reverse.
- [Docs] `gh auth logout`: "The authentication configuration is only removed locally" and "This command does not
  revoke authentication tokens."
- [Docs] `gh auth setup-git`: "configures `git` to use GitHub CLI as a credential helper … for all authenticated
  hosts".
- [Docs] git (gitcredentials): "If `credential.helper` is configured to the empty string, this resets the helper
  list to empty (so you may override a helper set by a lower-priority config file …)"; "each helper will be tried in
  turn … Once Git has acquired both a username and a non-expired password, no more helpers will be tried."
- [Docs] GitHub: the macOS `osxkeychain` helper stores an "Internet password" entry for `github.com` (Keychain
  Access); it can be erased with `git credential-osxkeychain erase`.
- [Ver] This laptop: `credential.helper osxkeychain` from the system file; no `gh` helper; HTTPS remote. [Inf] So
  today `git push` uses whatever github.com credential is in the login keychain (account unknown to me), and
  `git credential-osxkeychain get` (a trusted binary for that item) would hand it to any process of the user,
  including an agent's Bash. That is a path to the owner's authority if the item is the owner's (credential canon
  rule 2: enumerate every path).
- **To make the laptop use only the agent account** [Inf; owner steps; step 3]:
  - remove the owner's github.com keychain item;
  - `gh auth logout --user <owner>`; the token is not revoked, so the owner revokes the `gh` OAuth grant or that
    token on github.com if it was ever exposed;
  - store only the bot token (`gh auth login --with-token` for a classic token, or `GH_TOKEN` in a file the agent's
    sessions load);
  - make git use `gh` (`gh auth setup-git`, whose URL-scoped empty helper resets the system `osxkeychain` helper for
    github.com) [Inf];
  - check SSH: the remote is HTTPS today, but SSH keys on the owner account would still work through an `ssh` remote
    (owner check).
  - Probe (f) then: `gh auth status` lists only `dentaledge-bot`; `gh api user --jq .login` returns
    `dentaledge-bot`; `GIT_TRACE=1 git push --dry-run` to a probe ref shows only `gh auth git-credential` being run
    (no secret printed); the keychain has no github.com item (the owner checks presence with an output that is a
    byte count, never the value).

### Q7 — Admin-only reads for probe (g)

- [Docs] Repository roles table: "Manage webhooks and deploy keys" is **Admin only** (✗ for Read, Triage, Write,
  Maintain).
- [Docs] REST `GET /repos/{o}/{r}/hooks`: listed status codes **200, 404**. Fine-grained permission "Webhooks"
  read. `GET /repos/{o}/{r}/keys`: listed status code 200 only. Fine-grained "Administration" read.
- [Docs] Errors: "Resource not accessible by personal access token" means insufficient fine-grained permission
  (HTTP 403). "GitHub uses a `404 Not Found` response instead of a `403 Forbidden` response to avoid confirming the
  existence of private repositories."
- **Expected for the bot** [Inf]: fine-grained token without Webhooks/Administration → **403** "Resource not
  accessible by personal access token" on both; classic `repo` token (scope allows hooks, role does not) → **404**
  (or 403). The probe's "403 or 404" is right, and the actual code and message are recorded. A private org
  repository where the bot is not a collaborator (`claude-google-ads`, `claude-marketing-team`) → **404** [Docs].

### Q8 — Counter-evidence on the old token (V2-ID-7)

- `docs/superpowers/specs/2026-07-24-hermes-proposal-draft-pr-design.md:64-73` (finding of 2026-07-25): fine-grained
  PATs "do **not** grant write to a repo owned by a *different USER account* where the token creator is only a
  collaborator (verified live: … `403 "Resource not accessible by personal access token"`)". So the repository was
  moved to the org, "`dentaledge-bot` is an org collaborator with write, and an org-scoped fine-grained single-repo
  PAT now grants real write — verified (positive control passes; a `main` push is rejected by the ruleset with
  *"Changes must be made through a pull request"*, not a 403)".
- `docs/superpowers/plans/2026-07-25-hermes-proposal-draft-pr.md:29`: mint with "resource owner = the
  **`DentalEdge-Solutions` org** …, repository = `claude_code` only, permissions = **Contents: Read/Write** + **Pull
  requests: Read/Write** …, **expiry = 90 days**".
- `infra/hermes-agent/.env.pr.example:2-4` and `infra/hermes-agent/README.md:317-323` describe the same fine-grained
  token. `docs/superpowers/handoffs/2026-10-09-review-9-pass.md:80` and
  `.project-brain/sessions/daily/2026-10-14.md:37` call it "the organisation-scoped GitHub token".
- PR #4 [Ver]: authored by `dentaledge-bot` on 2026-07-25, head branch in the org repository itself (not a fork).
- **Reconciliation** [Inf]:
  - the evidence is strong that, on 2026-07-25, a fine-grained token minted by this bot, with the org as resource
    owner, could push and open a PR here, against the docs' gap;
  - the 2026-10-09/10-14 notes repeat "organisation-scoped", which fits resource owner = org;
  - "outside collaborator" is my reading of the org's 1 of 1 seats (S6, [Ver by the coordinator 2026-10-23]), not
    stated in the 2026-07 records ("org collaborator");
  - the repository's visibility on 2026-07-25 is [Unk];
  - whether the org approval flow applied (and the owner approved it, or it did not apply to an outside
    collaborator) is [Unk].
- **What step 1b must still test**:
  - a fresh fine-grained token minted today: does the org appear as resource owner? does it go `pending`?
  - push, PR creation, update-branch, and the workflow refusal;
  - whether a token approved under the org policy is needed at all.
  - The July result was for a token now expired. GitHub's behaviour may have changed, and the July test used a
    `main` push, not a merge.

## 4. What step 1b must test

Rules for every test: **outside agent sessions**, by the owner; branch pattern **`p0-10-probe/**`** only, never
`main`; test tokens minted from `dentaledge-bot` with the shortest expiry offered (the creation link accepts
`expires_in` from 1 day), used through an environment variable in a terminal that no agent controls, **never
printed**, revoked at the end and **proved dead** by a use that GitHub refuses ("prove death, never infer it",
`credential-governance-lessons.md:136-137`); the test ruleset(s) and classic rule are deleted and the probe
branches removed at the end; results (commands, HTTP codes, refusal texts, screenshots of the merge box) go to a
dated `docs/evaluations/` record. CI does not run on probe PRs (`ci.yml:3-7` [Ver]), so the required check is a
commit status `p0-10-probe/ci` set by the owner (`POST /repos/{o}/{r}/statuses/{sha}`, no `integration_id` in the
probe rule).

**T0 setup (owner).** Create `p0-10-probe/base` from `main` and commit `/.github/CODEOWNERS` with
`* @dentaledgesolutions` on that branch only, **before** any probe ruleset exists. Read
`GET /repos/{o}/{r}/codeowners/errors?ref=p0-10-probe/base`. Expected: `errors: []`. If not, the org-owner
"explicit write" question (Q5) is answered no.

**T1 token type (fine-grained first).** Owner mints, as the bot: resource owner `DentalEdge-Solutions`, only
`claude_code`, Contents RW, Pull requests RW, no Workflows.

| Check | Docs expect | July evidence expects | Record |
|---|---|---|---|
| Org listed as resource owner | not said | yes | yes/no |
| Token state | `pending` if approval applies to outside collaborators | n/a | state; owner approves if pending |
| `git push` of `p0-10-probe/t1-head` | refused (gap) | succeeds | exit code, refusal text |
| `gh pr create --base p0-10-probe/base` | refused | succeeds | PR number or error |
| `gh pr view --json reviewDecision,statusCheckRollup`, `gh pr checks` | Checks API gap | n/a | works/fails |
| `PUT …/pulls/{n}/update-branch` | Pull requests write | n/a | code |

If the fine-grained token fails: repeat with a classic test token, `public_repo` first (`GH_TOKEN`; note what
`gh auth login --with-token` says), then `repo` only if `public_repo` fails. Never `workflow`.

**T2 workflow refusal (preview of probe (g)).** With the token that passed T1, push to `p0-10-probe/t2-head` a
commit adding `.github/workflows/p0-10-probe-<random>.yml` whose contents exist on **no** branch. Expected (classic):
the refusal quoted in Q2 ("refusing to allow a Personal Access Token to create or update workflow … without
`workflow` scope") [Comm].
Fine-grained wording: record it. Control: a non-workflow file to the same branch succeeds. Then delete the
branch.

**T3 two rulesets + review rules** (mirrors `main`, targets `refs/heads/p0-10-probe/base` only):
- `probe-checks`: PR rule (0 approvals), required status check `p0-10-probe/ci` (strict), no bypass;
- `probe-review`: PR rule with `required_approving_review_count: 1`, `require_code_owner_review`,
  `require_last_push_approval`, `dismiss_stale_reviews_on_push`; bypass **For pull requests only**. Note whether
  the UI offers the user `dentaledgesolutions` (R-A-14, changelog 2026-05-07); test with the **Repository admin
  role** (the planned choice (x)).

| Probe | Expected (docs) |
|---|---|
| bot approves its own PR | refused ("authors cannot approve") |
| bot PR, owner approves, status success → mergeable; bot merge (no candidate yet) | merge succeeds: the residual OC-2 describes |
| bot pushes after the owner's approval | approval dismissed; not mergeable until re-approved |
| owner clicks **Update branch** on a bot PR, then approves | [UNVERIFIED]: approval likely cannot satisfy last-push (R-A-15) |
| bot updates the branch (API), then owner approves | mergeable |
| owner-authored PR approved by the bot | `reviewDecision: REVIEW_REQUIRED`; bot merge refused; owner merges via the PR-only bypass |
| owner PR, status `failure`, try bypass merge | refused (`probe-checks` has no bypass) = probe (e) |
| owner PR, status `success` | merges without review via the bypass |
| `GET /rulesets/{probe-review id}` as bot / as owner | `current_user_can_bypass`: `never` / `pull_requests_only`; `bypass_actors` absent for the bot |

**T4 candidate B** (classic rule on pattern `p0-10-probe/base`, only "Restrict who can push to matching branches",
nobody listed (or the owner listed if the UI requires a name); "Do not allow bypassing" off):

| Probe | Expected |
|---|---|
| bot merges an owner-approved, green PR (UI and `PUT …/merge`) | refused [Docs]; record the message |
| owner merges the same kind of PR | succeeds with no bypass prompt [Docs] |
| org audit log after both | `protected_branch.rejected_ref_update` for the bot [Docs]; is the owner merge logged? [UNVERIFIED] |
| rule insights | the owner merge shows "Pass" for `probe-checks`/`probe-review`, not "Bypass" [Inf] |

**T5 candidate A** (only if B fails; delete B's rule first). Ruleset `probe-merge-lock` with "Restrict updates"
only. (i) A-exempt: bypass = owner user, else admin role, mode **Exempt**. (ii) A-PR: same actor, **For pull
requests only**. For each: the bot merge is refused ("The base branch does not allow updates" [Comm]); the
owner's merge succeeds without (i) or with (ii) the bypass checkbox; rule insights show nothing (i) or "Bypass"
(ii). Also try `gh pr merge` from the owner's own terminal.

**T6 nothing else.** Do not enable auto-merge or a merge queue. `allow_auto_merge` stays false.

**Cleanup and record.** Delete the probe rulesets and classic rule, delete `p0-10-probe/*` branches, close probe
PRs, revoke the test token(s) and prove each dead, re-read `main-protection` unchanged, record.

## 5. Owner-only checks (admin or the bot's own settings)

1. **Org settings → Personal access tokens → Settings**:
   - Fine-grained tab: access allowed, and approval required or not;
   - "Tokens (classic)" tab: is "Restrict personal access tokens (classic) from accessing your organizations" set
     to restrict?
   - maximum lifetimes.
2. **Org → Personal access tokens → Active tokens / Pending requests**: is any `dentaledge-bot` token listed (the
   expired one)? That shows whether the approval flow applied to this outside collaborator in July.
3. **Org plan** (Free or Team), and the org owners list (today only `dentaledgesolutions` [Ver by the coordinator,
   2026-10-23]).
4. **Repository → Settings → Branches**: does any classic branch protection rule target `main`? (Only one can
   apply; candidate B adds one.)
5. **Repository → Collaborators**: `dentaledge-bot` = Write, not Admin, not Maintain; the list of admins.
6. **Repository → Rules**: `main-protection` bypass list empty; **Rules → Insights** available (dashboard needs
   Team or Enterprise Cloud).
7. **Repository webhooks and deploy keys** (admin reads): note what exists; a deploy key with write is another push
   path.
8. **Org audit log** (owners only, 180 days): the step-1b events.
9. **As `dentaledge-bot`** (signed in outside agent sessions): its tokens list (expired `dentaledge-bot-pat`; any
   other live token), its SSH keys, its 2FA state, and whether it is a member of any other org.
10. **Laptop** (step 3; the agent never reads these):
    - is there a github.com "Internet password" in Keychain Access, and for which account?
    - which accounts `gh auth status` lists;
    - SSH keys on the owner account;
    - `GH_TOKEN`/`GITHUB_TOKEN` in shell profiles;
    - Claude in Chrome, the desktop built-in browser pane and computer use signed in to github.com.

## 6. What each later step can rely on

| Step | Can rely on (source) | Waits for |
|---|---|---|
| 2 token | classic allowed by default unless the org restricts [Docs]; fine-grained approval on by default for members [Docs]; workflow scope semantics and the same-contents exception [Docs]; seat: none (public) [Docs] | T1 (type), owner check 1-2 |
| 3 paths | `GH_TOKEN` precedence, logout is local and does not revoke, switch semantics [Docs]; git uses `osxkeychain` here [Ver]; keychain item reachable by the trusted helper [Inf] | owner measurement (check 10) |
| 4 CODEOWNERS | location, base-branch rule, write-access rule, errors endpoint with `ref` [Docs] | T0 (org-owner "explicit" access) |
| 5 review ruleset | layering, most-restrictive, per-ruleset bypass, PR-only semantics, self-approval ban [Docs]; users eligible as bypass actors [Docs, changelog] | T3 |
| 5a restriction | B's documented merge coverage and admin rule [Docs] | T4 (then T5) |
| 6 runbook | stale dismissal on Update branch [Docs]; last-push rule [Docs] | T3 Update-branch rows |
| probe (g) | 404 for private repositories [Docs]; hooks/keys admin-only [Docs]; `current_user_can_bypass` enum [Docs]; bypass_actors hidden without ruleset write [Docs] | T1/T2 exact codes and texts |

## 7. Fallbacks if an assumption fails

- **Fine-grained fails (T1)** → classic token, no `workflow`: `public_repo` (narrower) or `repo` (OC-1). If the org
  restricts classic tokens, the owner either allows them (an org-wide change, so record it) or goes to the next
  bullet.
- **Neither token type works, or the classic reach is unacceptable** → a **GitHub App** owned by the org, installed
  on `claude_code` only, with Contents RW + Pull requests RW and no Workflows. It is a separate identity, its
  installation tokens last one hour, and it is never in a bypass list. An App's approval does not satisfy the
  owner code-owner rule (Q5). Cost: an App and private-key custody on the laptop. This is also the identity that
  restoring Hermes delivery would need (S6 §4). Or a **re-decision** of D-13.
- **CODEOWNERS does not recognise the owner (T0)** → add the owner as an explicit admin collaborator, or use a
  visible owner-only team with explicit write (choice (y)); re-run the errors read.
- **No merge restriction works (T4, T5)** → the OC-2 exception to `docs/REVIEW_PROTOCOL.md:22` and the 2026-10-14
  boundary, guarded by the D-09 ask rule, with `allow_auto_merge` false and no merge queue.
- **Owner Update branch breaks approval (T3)** → runbook: the agent updates branches, the owner approves last; or
  drop `require_last_push_approval` and rely on `dismiss_stale_reviews_on_push` (the docs call stale dismissal
  "safer" against hijacking). That is the owner's choice.
- **The laptop cannot be made agent-only (step 3)** → credential option (c): approvals only from a second device.

## 8. Sources (all accessed 2026-10-27)

| # | Source | URL | Verified here |
|---|---|---|---|
| S1 | Available rules for rulesets | https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-rulesets/available-rules-for-rulesets | Restrict updates/deletions text; PR rule; silence on merges |
| S2 | Creating rulesets for a repository | https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-rulesets/creating-rulesets-for-a-repository | eligible bypass actors; "For pull requests only" |
| S3 | About rulesets | https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-rulesets/about-rulesets | layering; read access to rulesets |
| S4 | Managing rulesets for a repository | https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-rulesets/managing-rulesets-for-a-repository | rule insights (Pass/Fail/Bypass, filters) |
| S5 | About protected branches | https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches/about-protected-branches | restrict push; admins; merges; review flags; Update branch |
| S6 | Managing a branch protection rule | https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches/managing-a-branch-protection-rule | naming people/teams/apps |
| S7 | REST: rules | https://docs.github.com/en/rest/repos/rules | actor_type, bypass_mode (incl. exempt), current_user_can_bypass, bypass_actors visibility, PR and status-check params |
| S8 | Managing your personal access tokens | https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/managing-your-personal-access-tokens | fine-grained gaps; classic for outside collaborators; pending; expiry |
| S9 | Setting a PAT policy for your organization | https://docs.github.com/en/organizations/managing-programmatic-access-to-your-organization/setting-a-personal-access-token-policy-for-your-organization | classic policy name, path, default; approval default; lifetimes |
| S10 | Managing requests for PATs in your organization | https://docs.github.com/en/organizations/managing-programmatic-access-to-your-organization/managing-requests-for-personal-access-tokens-in-your-organization | approval applies to "organization members" |
| S11 | Permissions required for fine-grained PATs | https://docs.github.com/en/rest/authentication/permissions-required-for-fine-grained-personal-access-tokens | Contents/PR/Workflows/Webhooks/Administration/Metadata rows |
| S12 | Scopes for OAuth apps | https://docs.github.com/en/apps/oauth-apps/building-oauth-apps/scopes-for-oauth-apps | `repo`, `public_repo`, `workflow` |
| S13 | Repository roles for an organization | https://docs.github.com/en/organizations/managing-user-access-to-your-organizations-repositories/managing-repository-roles/repository-roles-for-an-organization | webhooks/deploy keys admin-only |
| S14 | REST: webhooks; deploy keys; commit statuses; repos (CODEOWNERS errors) | https://docs.github.com/en/rest/repos/webhooks · https://docs.github.com/en/rest/deploy-keys/deploy-keys · https://docs.github.com/en/rest/commits/statuses · https://docs.github.com/en/rest/repos/repos | status codes; "push access" for statuses; errors endpoint and `ref` |
| S15 | Troubleshooting the REST API | https://docs.github.com/en/rest/using-the-rest-api/troubleshooting-the-rest-api | 404 instead of 403; "Resource not accessible" |
| S16 | About code owners | https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/customizing-your-repository/about-code-owners | location, write access, base branch |
| S17 | Approving a PR with required reviews | https://docs.github.com/en/pull-requests/collaborating-with-pull-requests/reviewing-changes-in-pull-requests/approving-a-pull-request-with-required-reviews | authors cannot approve |
| S18 | Automatically merging a PR; Managing a merge queue | https://docs.github.com/en/pull-requests/collaborating-with-pull-requests/incorporating-changes-from-a-pull-request/automatically-merging-a-pull-request · https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/configuring-pull-request-merges/managing-a-merge-queue | who can enable auto-merge; merge queue overrides the setting |
| S19 | Audit log events for your organization; Reviewing the audit log | https://docs.github.com/en/organizations/keeping-your-organization-secure/managing-security-settings-for-your-organization/audit-log-events-for-your-organization · https://docs.github.com/en/organizations/keeping-your-organization-secure/managing-security-settings-for-your-organization/reviewing-the-audit-log-for-your-organization | `protected_branch.*`, `repository_ruleset.*`; owners only, 180 days |
| S20 | Adding outside collaborators | https://docs.github.com/en/organizations/managing-user-access-to-your-organizations-repositories/managing-outside-collaborators/adding-outside-collaborators-to-repositories-in-your-organization | seats only for private repos; no teams |
| S21 | Caching credentials; macOS Keychain | https://docs.github.com/en/get-started/git-basics/caching-your-github-credentials-in-git · https://docs.github.com/en/get-started/git-basics/updating-credentials-from-the-macos-keychain | osxkeychain item; erase |
| S22 | Changelog 2026-05-07, user bypass | https://github.blog/changelog/2026-05-07-repository-rulesets-user-bypass-and-branch-renaming | users as bypass actors (repo rulesets) |
| S23 | Changelog 2025-09-10, exempt bypass | https://github.blog/changelog/2025-09-10-github-ruleset-exemptions-and-repository-insights-updates/ | exempt type, silent |
| S24 | Ruleset bypasses for migrations (GHEC docs) | https://docs.github.com/en/enterprise-cloud@latest/migrations/troubleshooting/setting-ruleset-bypasses-for-repository-migrations | Always allow vs Exempt |
| S25 | Changelog 2025-03-18, fine-grained PATs GA | https://github.blog/changelog/2025-03-18-fine-grained-pats-are-now-generally-available/ | outside-collaborator gap; approval on by default |
| S26 | Blog 2023-07-24, repository rules GA | https://github.blog/news-insights/product-news/github-repository-rules-are-now-generally-available/ | layered rulesets with separate bypass lists |
| S27 | gh manual: auth login, switch, logout, status, setup-git; `gh help environment` | https://cli.github.com/manual/gh_auth_login (and `gh_auth_switch`, `gh_auth_logout`, `gh_auth_status`, `gh_auth_setup-git`, `gh_help_environment`) | scopes, storage, switching, precedence |
| S28 | gh multiple-accounts doc (historical, v2.40.0) | https://github.com/cli/cli/blob/trunk/docs/multiple-accounts.md | keyring; switch affects git only via gh helper; logout switches |
| S29 | git: gitcredentials | https://git-scm.com/docs/gitcredentials | empty helper resets; helper order |
| C1 | [Comm] Community discussion #113172 | https://github.com/orgs/community/discussions/113172 | Restrict updates blocks merges; bypass checkbox reports |
| C2 | [Comm] Workflow-scope refusal reports | https://dev.to/jessehouwing/can-t-push-to-github-refusing-to-allow-an-oauth-app-to-create-or-update-workflow-without-workflow-scope-1imc · https://kb.databricks.com/dev-tools/unable-to-push-github-actions-workflows-from-a-databricks-repository | refusal wording |
| C3 | [Comm] OpenSSF SCM best practices | https://best.openssf.org/SCM-BestPractices/github/repository/pushes_are_not_restricted.html | restrict-push treated as the merge control |

Repository sources: S5 roadmap P0-10 (`S5-prioritized-roadmap.md:324-444`), S6 D-12/D-13/OC-1/OC-2 and Limits;
`docs/superpowers/specs/2026-07-24-hermes-proposal-draft-pr-design.md:64-73`;
`docs/superpowers/plans/2026-07-25-hermes-proposal-draft-pr.md:29`; `infra/hermes-agent/.env.pr.example:1-12`;
`infra/hermes-agent/README.md:317-323`; `docs/superpowers/handoffs/2026-10-09-review-9-pass.md:80`;
`.project-brain/sessions/daily/2026-10-14.md:37` (main checkout, read with the Read tool);
`.project-brain/canon/2026-08-17-credential-governance-lessons.md` and
`.project-brain/canon/2026-08-18-credential-access-levels-are-measured-never-asserted.md`;
`docs/evaluations/2026-10-14-software-factory-architecture-evaluation.md:166,168`; `.github/workflows/ci.yml:3-7`.

## 9. Method and limits

- `gh api` calls made: **2**, both read-only `gh api graphql` queries on `DentalEdge-Solutions/claude_code`:
  - call 1: visibility, `autoMergeAllowed`, rulesets with rule types and PR/status-check parameters;
  - call 2: the required checks' `integrationId`.
- Neither reads `bypassActors`. Other `gh` reads: `gh repo view` (twice; the first failed on an unknown JSON field)
  and `gh pr view 4`. No token was printed or read; no credential store or `hosts.yml` was opened.
- The docs were read as served on 2026-10-27; GitHub changes them often. The user-bypass changelog
  (2026-05-07) is already ahead of the rulesets docs page.
- Community sources corroborate only; none decides a finding.
- Nothing here was tested against GitHub's behaviour; every "expected" in §4 is a prediction from the docs, to be
  measured in step 1b. Machine facts (§2 git helper, environment) describe this laptop on 2026-10-27.
