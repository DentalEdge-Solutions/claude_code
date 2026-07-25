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
| Landing path | `.project-brain/decisions/candidates/<ts>-hermes-proposal.md` (feeds brain governance) |
| Write mechanism | **Trusted deterministic script** — no LLM in the write path |
| Trigger | Operator-invoked (manual) now; auto-open-after-proposal deferred |
| PR state | **Draft only** — a human marks ready + merges |

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
3. **Branch protection on `main`** (server-side GitHub) — no direct pushes; PRs required.
   One-time setup, part of this increment.
4. **Client-side pre-push hook** (installed into the ephemeral clone) — refuses any push
   whose target is `main`; defense-in-depth before a push even reaches GitHub.
5. **Scoped fine-grained PAT** — single repo (`dentaledgesolutions/claude_code`),
   **Contents + Pull-requests: write** only (no admin/delete/workflow/actions). Because the
   write step is **operator-invoked** (`docker compose exec`), the PAT is simply present in
   the container env from `.env` (`env_file`) and read directly by the script; never in git
   or logs. (Hermes scrubs secrets from *agent-launched* subprocess env, so IF this step is
   later auto-invoked **through** Hermes's terminal tool, it would need the executor-key
   bootstrap-projection treatment — deferred with the auto-trigger.)
6. **Doc-only payload** — adds one markdown file under `.project-brain/decisions/candidates/`;
   no code, no executables. The script writes the file itself (proposal content is data).
7. **Ephemeral workspace** — the clone is deleted after the PR is opened (success or failure).

**Residual (stated honestly):** the PAT can push non-`main` branches to `claude_code` and
open PRs. Layers 2–4 ensure nothing merges to `main` without a human; the PAT scope (5)
caps blast radius to this one repo's contents + PRs. There is no path to a code change or a
merge without human action.

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
4. **Registry** (`registry/projects.yaml`): `claude_code` gains a `pr_target`
   (repo slug `dentaledgesolutions/claude_code`); the mount stays `scope: read`.
5. **Reuse:** `proposals-index.py` (select which proposal); `save-proposal.py` unchanged; the
   Inc-1 pipeline unchanged.

## Flow

```
open-proposal-pr.py --project claude_code --proposal latest
  read /opt/data/proposals/claude_code/<ts>.md
  workspace=$(mktemp -d); git clone --depth 1 https://<PAT>@github.com/dentaledgesolutions/claude_code $workspace
  install .git/hooks/pre-push  (refuse pushing to main)
  git -C $workspace checkout -b proposal/<ts>
  write $workspace/.project-brain/decisions/candidates/<ts>-hermes-proposal.md   (brain-candidate format)
  git -C $workspace add + commit -m "proposal: <summary> (Hermes AIOS)"
  git -C $workspace push origin proposal/<ts>            # hook allows non-main
  gh pr create --draft --base main --head proposal/<ts>  # or REST API
  print PR URL; rm -rf $workspace
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

- A **draft** PR appears on `dentaledgesolutions/claude_code` whose diff is **only** the new
  `.project-brain/decisions/candidates/<ts>-hermes-proposal.md` file.
- **`main` is unwritable directly:** a `git push` targeting `main` is refused by the pre-push
  hook, and branch protection rejects it server-side.
- **`:ro` mount untouched:** `/projects/claude_code` git tree byte-identical before AND after
  (writes went to the ephemeral clone, never the mount).
- **PAT never exposed:** `grep` of container logs, the proposal, and the repo turns up no
  token; the PAT lives only in `.env` (gitignored) and the process env of the write step.
- **Cleanup:** the ephemeral workspace no longer exists after the run.

## Deferred / open

- **Brain-candidate format** — pin the exact frontmatter/schema the candidate file needs so
  `brain-compile`/`brain-promote` can consume it (check the candidate template during planning).
- **`gh` availability in the container** — confirm; fall back to the GitHub REST API via
  `curl` if absent (pinned in the plan).
- Auto-open-after-proposal (a gateway/cron hook vs. the manual step); code-writing PRs
  (Track B); `claude-google-ads` as the second target; a PR-status monitor alongside
  `proposals-index.py`.
