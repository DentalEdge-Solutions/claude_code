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
- **Target = `dentaledgesolutions/claude_code`** (our own repo; the Inc-1 proposals are
  *about* it). A draft, doc-only PR is fully reversible (close PR + delete branch) and
  human-gated, so no throwaway sandbox is needed. `claude-google-ads` (the client repo) is
  the **second** target, reached in a later increment once this flow is proven.
- **Landing path = `.project-brain/decisions/candidates/`** — so the PR feeds the brain's
  promote-to-canon governance flow, not just a docs folder.

## Goal (this increment)

`open-proposal-pr.py --project claude_code [--proposal latest]` takes a persisted proposal,
opens a **draft** PR on `dentaledgesolutions/claude_code` that adds exactly one
brain-candidate markdown file — with the production `:ro` mount provably untouched, `main`
protected, and the PAT never exposed.

## Design decisions (from brainstorming)

| Decision | Choice |
|---|---|
| PR payload | The **proposal document** (doc-only add). No code changes. |
| Target repo | `dentaledgesolutions/claude_code` (ours). Client repo = later. |
| **Bot identity** | A **dedicated machine account**, added as a **collaborator** (write, not admin) on the user-owned repo. The PAT is generated from the bot account — it is NOT the owner's token. |
| Landing path | `.project-brain/decisions/candidates/YYYY-MM-DD-<slug>.md` (existing candidate convention; feeds brain governance) |
| Write mechanism | **Trusted deterministic script** — no LLM in the write path |
| Trigger | Operator-invoked (manual) now; auto-open-after-proposal deferred |
| PR state | **Draft only** — a human marks ready + merges |

### Identity model (why a machine account is required — change from the first draft)

`dentaledgesolutions` is a **User** account with the owner as sole admin. A fine-grained PAT
minted from the owner's account **acts as the owner** — so a `main` ruleset either bypasses
for the owner (and therefore the token) or blocks the owner (a PR gate on ~5 owner pushes/day
— a non-starter). **There is no branch-protection setting that separates the owner's token
from the owner.** So server-side rejection of the bot's direct `main` pushes is only real if
the bot is a **different actor**:

- Create a **dedicated machine account**; add it as a **collaborator** on
  `dentaledgesolutions/claude_code`. Collaborators on a user-owned repo get **write, not
  admin**.
- A **ruleset on `main`** requires a pull request, with **bypass = repo admin** (the owner).
  The owner keeps pushing to `main` directly as today; the **bot cannot bypass** (it is not
  an admin and genuinely cannot grant itself the bypass).
- The PAT is minted **from the bot account**, scoped to this one repo.

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
   (`dentaledgesolutions/claude_code`), **Contents + Pull-requests: write** only (no
   admin/delete/workflow/actions), **90-day expiry** (rotation step documented in the README).
   Because the write step is **operator-invoked** (`docker compose exec`), the PAT is present
   in the container env from `.env` (`env_file`) and read directly by the script; never in git
   or logs. (Verified: Hermes's *agent-launched* subprocess env scrubbing covers
   `CLAUDE_CODE_PR_PAT` by name/pattern — an agent-launched process cannot read it today, not
   merely won't be asked to; see Verification. IF this step is later auto-invoked **through**
   Hermes's terminal tool, it would need the executor-key bootstrap-projection — deferred with
   the auto-trigger.)
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
2. **PAT config** in `.env` (`CLAUDE_CODE_PR_PAT`), fine-grained, single-repo, documented in
   `.env.example` as write-scoped and gitignored. Present in the container env via `env_file`
   for the operator-invoked `docker compose exec` path.
3. **`main` branch protection** on `dentaledgesolutions/claude_code` — a one-time setup step
   (via `gh api` or the GitHub UI), documented in the README.
4. **Registry** (`registry/projects.yaml`): `claude_code` gains a **structured** `pr_target`
   (not a bare slug — generalized now so `claude-google-ads` needs no schema migration):
   ```yaml
   pr_target:
     repo: dentaledgesolutions/claude_code
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
  workspace=$(mktemp -d)
  git clone --depth 1 https://<BOT_PAT>@github.com/<pr_target.repo> $workspace   # bot account, not owner
  install .git/hooks/pre-push  (refuse pushing to <pr_target.base>)
  git -C $workspace checkout -b proposal/<ts>
  write $workspace/<pr_target.path>/YYYY-MM-DD-<slug>.md   (candidate format + provenance)
  git -C $workspace add + commit -m "proposal: <summary> (Hermes AIOS, machine-generated)"
  git -C $workspace push origin proposal/<ts>              # hook allows non-base branches
  gh pr create --draft --base <pr_target.base> --head proposal/<ts>   # or REST API
  print PR URL; rm -rf $workspace   # cleanup on success AND failure
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
  `dentaledgesolutions/claude_code` and confirm GitHub **rejects it server-side**. If it is
  not rejected, the identity model is wrong — stop and fix before building. **Every guardrail
  test runs as the bot; testing as the owner proves nothing.**
- A **draft** PR appears on `dentaledgesolutions/claude_code` whose diff is **only** the new
  `.project-brain/decisions/candidates/YYYY-MM-DD-<slug>.md` file, carrying `author: hermes` +
  the `hermes-generated` tag, with `sources` naming the originating proposal path + run id.
- **`main` is unwritable by the bot:** the pre-push hook refuses a push targeting the base
  branch (client-side) AND the `main` ruleset rejects the bot's direct push server-side
  (admin-only bypass) — both verified **as the bot**.
- **`:ro` mount untouched:** `/projects/claude_code` git tree byte-identical before AND after
  (writes went to the ephemeral clone, never the mount).
- **PAT never exposed + env-scrub verified:** `grep` of container logs, the proposal, and the
  repo turns up no token; the PAT lives only in `.env` (gitignored) and the process env of the
  operator-invoked step. An **agent-launched** subprocess (Hermes terminal tool) cannot read
  `CLAUDE_CODE_PR_PAT` today — `printenv CLAUDE_CODE_PR_PAT` inside the terminal tool returns
  empty — so the operator-only invocation boundary is real, not merely intended.
- **PAT expiry:** the token carries a 90-day expiry; the README documents the rotation step.
- **Cleanup:** the ephemeral workspace no longer exists after the run — on success AND failure.

## Deferred / open

- **One-time human setup (prerequisite; OWNER-performed, never by Hermes):** create the
  machine account, add it as a collaborator on `dentaledgesolutions/claude_code`, mint the
  90-day fine-grained **bot** PAT (Contents + Pull-requests write, single repo), and add the
  `main` ruleset (PR required, bypass = repo admin). The plan sequences these as explicit
  human steps; **plan Task 1 verifies them as the bot before any script is written.**
- **`gh` availability in the container** — confirm; fall back to the GitHub REST API via
  `curl` if absent (pinned in the plan).
- Auto-open-after-proposal (a gateway/cron hook vs. the manual step — auto-invocation would
  need the PAT bootstrap-projection since Hermes scrubs agent-launched env); code-writing PRs
  (Track B); `claude-google-ads` as the second target; a PR-status monitor alongside
  `proposals-index.py`.
