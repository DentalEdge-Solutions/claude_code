# Design — Proposals as draft PRs (Increment 2 · P5 Track A.2 · first write capability)

> **Status:** design (brainstormed 2026-07-24, Claude Opus 4.8). Terminal step is an
> implementation plan via `writing-plans`.
> **Depends on:** the P0–P3 Hermes control plane (`infra/hermes-agent/`), the read-only
> proposer + persistence layer (`save-proposal.py`, `proposals-index.py`), and the
> Increment-1 Kanban review pipeline that produces proposals in
> `/opt/data/proposals/claude_code/<ts>.md`.

## Context & purpose

Increment 1 produces improvement proposals as files in Hermes state. Increment 2 is the
**first write capability**: deliver a persisted proposal to GitHub as a **draft pull
request**, re-activating the write-guardrail stack that Track A Increment 1 deliberately
shelved (`2026-07-23-hermes-improvement-proposals-design.md`: scoped PAT, isolated
workspace, git hooks, branch protection).

It is scoped to the **lowest-risk possible write**, on purpose — the write-plumbing analog
of Increment 1's confinement-first philosophy: prove the dangerous machinery (clone,
branch, push, PAT, PR) on a **zero-code-risk payload** before anything ever writes code.

- **Payload = the proposal document itself** (a markdown file). **No code changes.** Track A
  stays "Hermes proposes; the human + Claude Code develop." Code-writing PRs are Track B.
- **Target = `DentalEdge-Solutions/claude_code`** (our own repo; the Inc-1 proposals are
  *about* it). A draft, doc-only PR is fully reversible (close PR + delete branch) and
  human-gated, so no throwaway sandbox is needed. `claude-google-ads` (the client repo) is
  the **second** target, reached in a later increment once this flow is proven.
- **Landing path = `.project-brain/decisions/candidates/`** — so the PR feeds the brain's
  promote-to-canon governance flow, not just a docs folder.

## Goal (this increment)

`open-proposal-pr.py --project claude_code [--proposal latest]` takes a persisted proposal,
opens a **draft** PR on `DentalEdge-Solutions/claude_code` that adds exactly one
brain-candidate markdown file — with the production `:ro` mount provably untouched, `main`
protected, and the PAT never exposed.

## Design decisions (from brainstorming)

| Decision | Choice |
|---|---|
| PR payload | The **proposal document** (doc-only add). No code changes. |
| Target repo | `DentalEdge-Solutions/claude_code` (ours). Client repo = later. |
| **Bot identity** | A **dedicated machine account**, added as a **collaborator** (write, not admin) on the user-owned repo. The PAT is generated from the bot account — it is NOT the owner's token. |
| Landing path | `.project-brain/decisions/candidates/YYYY-MM-DD-<slug>.md` (existing candidate convention; feeds brain governance) |
| Write mechanism | **Trusted deterministic script** — no LLM in the write path |
| Trigger | Operator-invoked (manual) now; auto-open-after-proposal deferred |
| PR state | **Draft only** — a human marks ready + merges |

### Identity model (why a machine account is required — change from the first draft)

The original owner (`dentaledgesolutions`) is a **User** account with the owner as sole admin.
A fine-grained PAT minted from the owner's account **acts as the owner** — so a `main` ruleset
either bypasses for the owner (and therefore the token) or blocks the owner (a PR gate on ~5
owner pushes/day — a non-starter). **There is no branch-protection setting that separates the
owner's token from the owner.** So server-side rejection of the bot's direct `main` pushes is
only real if the bot is a **different actor**:

- A **dedicated machine account** (`dentaledge-bot`) with **write** on the repo (not admin).
- A **ruleset on `main`** requires a pull request, with **bypass = repo admin** (the owner).
  The owner keeps pushing to `main` directly; the **bot cannot bypass** (not an admin).
- The PAT is minted **from the bot account**, scoped to this one repo.

**Org requirement (finding, 2026-07-25):** the bot's write is exercised via a fine-grained PAT
— but fine-grained PATs do **not** grant write to a repo owned by a *different USER account*
where the token creator is only a collaborator (verified live: even with Contents Read/Write
set, both a `git push` and the `git/refs` API returned `403 "Resource not accessible by
personal access token"`). GitHub honors fine-grained-PAT write only for repos owned by the
token creator or by **organizations** they belong to. So `claude_code` was **moved to the
`DentalEdge-Solutions` org**; `dentaledge-bot` is an org collaborator with write, and an
org-scoped fine-grained single-repo PAT now grants real write — verified (positive control
passes; a `main` push is rejected by the ruleset with *"Changes must be made through a pull
request"*, not a 403). This also positions the repo correctly for the multi-project client fleet.

This is verified empirically before any script is built (see Verification / plan Task 1):
push a throwaway branch to `main` **using the bot PAT** and confirm GitHub rejects it. All
guardrail tests run **as the bot** — testing as the owner proves nothing.

**Rejected approaches:** a skill/agent driving the PR flow (puts an LLM in the write path =
larger attack surface); extending the `claude -p` executor with write + `gh` (bloats the
executor's capability surface for a doc-only PR).

## The key safety property

**The write path never touches the `:ro` production mount.** It operates on a *fresh
ephemeral clone* pulled from GitHub via the PAT. So Increment 1's "mounted project untouched
on disk" guarantee **fully carries over** — the only change that exists anywhere reaches
GitHub as a branch, never the filesystem Hermes reads. `/projects/claude_code` stays `:ro`
and byte-identical.

## Write-guardrail stack (seven layers)

1. **`:ro` mount never written** — writes happen in an ephemeral clone, not `/projects/claude_code`.
2. **Draft PR only** — opens as *draft*; a human marks it ready + merges. Nothing auto-merges.
3. **`main` ruleset with admin-only bypass** (server-side GitHub) — requires a PR to land on
   `main`, with **bypass = repo admin (the owner)**. The bot is a collaborator (write, not
   admin), so its direct pushes to `main` are rejected by an actor it **cannot** bypass —
   **verified empirically as the bot** (plan Task 1), not assumed. The owner keeps pushing to
   `main` directly. One-time setup, part of this increment.
4. **Client-side pre-push hook** (installed into the ephemeral clone) — refuses any push
   whose target is `main`; defense-in-depth before a push even reaches GitHub.
5. **Scoped fine-grained PAT minted from the bot account** (not the owner) — single repo
   (`DentalEdge-Solutions/claude_code`), **Contents + Pull-requests: write** only (no
   admin/delete/workflow/actions), **90-day expiry** (rotation in the README). **The PAT is
   NOT in the gateway's environment.** It lives in a separate gitignored
   `infra/hermes-agent/.env.pr` that `docker-compose`'s `env_file` does **not** load, and is
   supplied to the **operator-invoked** write step per-invocation via
   `docker compose exec -e CLAUDE_CODE_PR_PAT` (a thin `open-proposal-pr.sh` wrapper sources
   `.env.pr` and adds the flag; `-e NAME` with no `=value`, so the token isn't in the host
   argv either). Because the gateway starts from `env_file` and the token isn't there, **no
   agent-launched process can ever inherit it — by construction, independent of Hermes's scrub
   list.** This is empirically necessary: Task 1 Step 1 proved Hermes does **not** scrub
   `CLAUDE_CODE_PR_PAT` when it is in the gateway env (it only scrubs known-provider names like
   `ANTHROPIC_API_KEY`/`GH_TOKEN`), so keeping the token out of the gateway env is the only
   robust fix — and it survives `hermes update`/VPS moves unchanged. Never in git or logs.
   (A future auto-trigger runs *through* Hermes and so must get its own deliberate, scoped
   projection — deferred with the auto-trigger.)
6. **Doc-only payload** — adds one markdown file under `.project-brain/decisions/candidates/`;
   no code, no executables. The script writes the file itself (proposal content is data).
7. **Ephemeral workspace** — the clone is deleted after the PR is opened (success or failure).

**Residual (stated honestly, and verified — not assumed — by plan Task 1):** the **bot
account** can push non-`main` branches and open PRs on **this one repo**, nothing more.
Layers 2–4 ensure nothing merges to `main` without the owner; the PAT scope (5) caps blast
radius to this repo's contents + PRs; the bot cannot reach `main`, admin settings, or any
other repo. No path to a code change or a merge without human action.

## Components

1. **`open-proposal-pr.py`** (`infra/hermes-agent/bin/`, new, trusted, deterministic):
   resolves the proposal file (`--proposal latest` → newest under
   `/opt/data/proposals/claude_code/`, or an explicit timestamp) → creates an ephemeral
   workspace → `git clone` (shallow) via `https://<PAT>@github.com/<repo>` → installs the
   pre-push hook → `git checkout -b proposal/<ts>` → writes the candidate file → `git add` +
   `commit` → `git push origin proposal/<ts>` → opens a **draft** PR (`gh pr create --draft`
   or the GitHub REST API via `curl` if `gh` is absent) → prints the PR URL → `rm -rf` the
   workspace. Exits non-zero without side effects if the PAT/proposal is missing.
2. **PAT config** in `infra/hermes-agent/.env.pr` (`CLAUDE_CODE_PR_PAT`), gitignored and **NOT**
   loaded by `docker-compose`'s `env_file` — documented via `.env.pr.example`. Supplied to the
   operator-invoked step per-invocation; never in the gateway env.
2a. **`open-proposal-pr.sh` wrapper** (host-side, sibling of `docker-compose.yml`, NOT under the
   container-mounted `bin/`): sources `.env.pr` and runs
   `docker compose exec -e CLAUDE_CODE_PR_PAT -T hermes-agent python3 /opt/cc-bin/open-proposal-pr.py "$@"`.
   The day-to-day entry point; keeps the token off the host argv (`-e NAME` passthrough).
3. **`main` branch protection** on `DentalEdge-Solutions/claude_code` — a one-time setup step
   (via `gh api` or the GitHub UI), documented in the README.
4. **Registry** (`registry/projects.yaml`): `claude_code` gains a **structured** `pr_target`
   (not a bare slug — generalized now so `claude-google-ads` needs no schema migration):
   ```yaml
   pr_target:
     repo: DentalEdge-Solutions/claude_code
     base: main
     path: .project-brain/decisions/candidates   # where the proposal file lands (repo-specific)
   ```
   The mount stays `scope: read`. (The client repo will land files elsewhere — e.g. `docs/` —
   which the `path` field already accommodates.)
5. **Reuse:** `proposals-index.py` (select which proposal); `save-proposal.py` unchanged; the
   Inc-1 pipeline unchanged.

## Candidate file format & provenance

The file the PR adds must match the **existing candidate convention** (verified against
`.project-brain/decisions/candidates/`), and must be **unambiguously machine-authored** —
under the brain's authority ranking a bot proposal is a lower class of input than a human
decision, and that provenance must be legible to whoever reviews the promote-to-canon flow.

- **Filename:** `YYYY-MM-DD-<slug>.md` (the existing convention — NOT the first draft's
  `<ts>-hermes-proposal.md`). `<slug>` is derived from the proposal title.
- **Frontmatter (matches existing candidates, plus provenance):**
  ```yaml
  ---
  type: decision
  title: <proposal title>
  description: <one-line summary from the proposal>
  tags: [hermes-generated]          # machine-authored marker (also legible in listings)
  author: hermes                    # explicit provenance field
  timestamp: <ISO-8601>
  sources:
    - <originating proposal path, e.g. /opt/data/proposals/claude_code/<ts>.md>
    - <Hermes run/session id that produced it>
  status: candidate
  ---
  ```
  Both the `hermes-generated` tag AND the `author: hermes` field are set (belt-and-suspenders
  legibility). `sources` MUST include the originating Hermes proposal path and the run/session
  id, so a reviewer can trace the candidate back to the run that produced it.
- **Body:** the proposal markdown (Summary + prioritized Items + Sources consulted), treated
  as data and written verbatim by the script.

## Flow

```
open-proposal-pr.py --project claude_code --proposal latest
  read /opt/data/proposals/claude_code/<ts>.md
  resolve pr_target from registry -> {repo, base, path}
  ws=$(mktemp -d); write $ws/.askpass  (0700; prints $CLAUDE_CODE_PR_PAT — no token on disk)
  GIT_ASKPASS=$ws/.askpass GIT_TERMINAL_PROMPT=0 \
    git clone --depth 1 https://x-access-token@github.com/<pr_target.repo> $ws/repo
      # username only — NO token in the URL/argv/.git/config; askpass supplies it at runtime
  install $ws/repo/.git/hooks/pre-push  (refuse pushing to <pr_target.base>)
  ls-remote --heads origin proposal/<ts>  → abort if it already exists (re-run guard)
  git -C $ws/repo checkout -b proposal/<ts>
  write $ws/repo/<pr_target.path>/YYYY-MM-DD-<slug>.md   (candidate format + provenance)
  git -C $ws/repo add + commit -m "proposal: <summary> (Hermes AIOS, machine-generated)"
  PREPUSH_BASE=<base> git -C $ws/repo push origin proposal/<ts>   # hook allows non-base branches
  gh pr create --draft --base <pr_target.base> --head proposal/<ts>   # or REST API
  print PR URL; rm -rf $ws   # cleanup on success AND failure
```

## Boundaries (Track A stays proposals, not development)

- The PR adds a **proposal document**, never code. Implementing a proposal item is Track B.
- Hermes never merges, never marks a PR ready-for-review, never pushes to `main`.
- The `:ro` mount and the Increment-1 read-only pipeline are unchanged.

## Alignment with AIOS objectives

- **C4 (execute writes) — entry point:** the first, smallest, most reversible write, proving
  the write-guardrail stack that every later write capability (Track B, the client pilot)
  inherits — exactly as Increment 1 proved the read-only confinement pattern.
- **Continuous-improvement function:** proposals now enter the repo's review flow (and the
  brain's promote-to-canon governance) instead of sitting in Hermes state.
- **Commercial objective:** the reusable write-delivery template for `claude-google-ads` and
  future client repos (second target).

## Verification

- **Identity model FIRST (plan Task 1, before any script exists):** using the **bot PAT**
  (never the owner's credentials), push a throwaway branch to `main` on
  `DentalEdge-Solutions/claude_code` and confirm GitHub **rejects it server-side**. If it is
  not rejected, the identity model is wrong — stop and fix before building. **Every guardrail
  test runs as the bot; testing as the owner proves nothing.**
- A **draft** PR appears on `DentalEdge-Solutions/claude_code` whose diff is **only** the new
  `.project-brain/decisions/candidates/YYYY-MM-DD-<slug>.md` file, carrying `author: hermes` +
  the `hermes-generated` tag, with `sources` naming the originating proposal path + run id.
- **`main` is unwritable by the bot:** the pre-push hook refuses a push targeting the base
  branch (client-side) AND the `main` ruleset rejects the bot's direct push server-side
  (admin-only bypass) — both verified **as the bot**.
- **`:ro` mount untouched:** `/projects/claude_code` git tree byte-identical before AND after
  (writes went to the ephemeral clone, never the mount).
- **PAT never exposed + not in the gateway env:** `grep` of container logs, the proposal, and
  the repo turns up no token; the PAT lives only in gitignored `.env.pr` (host-side) and the
  process env of the operator-invoked step. An **agent-launched** subprocess (Hermes terminal
  tool) sees it **empty** — `printenv CLAUDE_CODE_PR_PAT` returns nothing — because the token
  is not in the gateway's `env_file`, so no agent inherits it (by construction). (Corrected
  model: Hermes does NOT scrub `CLAUDE_CODE_PR_PAT` when it IS in the gateway env — proven in
  Task 1 Step 1 — so keeping it out of that env is what makes the boundary real.)
- **PAT expiry:** the token carries a 90-day expiry; the README documents the rotation step.
- **Cleanup:** the ephemeral workspace no longer exists after the run — on success AND failure.

## Deferred / open

- **One-time human setup (prerequisite; OWNER-performed, never by Hermes):** create the
  machine account, add it as a collaborator on `DentalEdge-Solutions/claude_code`, mint the
  90-day fine-grained **bot** PAT (Contents + Pull-requests write, single repo), and add the
  `main` ruleset (PR required, bypass = repo admin). The plan sequences these as explicit
  human steps; **plan Task 1 verifies them as the bot before any script is written.**
- **`gh` availability in the container** — confirm; fall back to the GitHub REST API via
  `curl` if absent (pinned in the plan).
- Auto-open-after-proposal (a gateway/cron hook vs. the manual step — auto-invocation would
  need the PAT bootstrap-projection since Hermes scrubs agent-launched env); code-writing PRs
  (Track B); `claude-google-ads` as the second target; a PR-status monitor alongside
  `proposals-index.py`.
