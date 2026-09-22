# Session prompt — F9: reconcile the executor's bind paths with the proxy allow-list

Open a new session and point it here instead of pasting the body:

> Read `docs/superpowers/handoffs/2026-09-22-f9-bind-paths-and-proxy-allow-list.md`,
> then confirm your understanding and flag any drift before starting.

Pointing at the file keeps corrections versioned.

---

**This is design work on the laptop. The VPS is not touched in this session.** The product is a
landed PR: the bind sources Docker Compose sends for `ads-mutator` and the proxy's pinned set
agree by construction. A test fails if they drift, and a Linux measurement shows they agree on a
real host layout.

**Mutation stays disabled throughout.** The kill switch is not created. Nothing here enables it.

## Why this exists

The first bring-up (2026-09-21, PR #33) measured F9: the bind sources Compose produces do not
match the proxy's allow-list, and no single directory layout satisfies both. F10 (PR #35, merged
`6ddef24`) landed the store and spool layout. F9 is now the only item BRING-UP Phase 6 names as a
blocker. Read these first:

- **F9** in `docs/superpowers/specs/2026-09-21-vps-first-bring-up-findings.md`, plus that file's
  "Effect on F9" paragraph under F10.
- §8 of `docs/superpowers/specs/2026-09-21-f10-governance-store-and-spool-layout-design.md`.
- The canon entry `2026-09-22-f10-store-and-spool-layout-landed-pr-35-phase-6-now-waits-on.md`.
  Read it with a non-Bash tool (see HARD RULES).

In short:

- The proxy (`bin/docker-create-proxy.py:231-232`) refuses any create whose `HostConfig.Binds`
  set is not **exactly** the pinned set.
- The pinned set comes from `--allow-bind` flags in `deploy/hermes-docker-proxy.service:32-38`.
  Two of them name `/opt/hermes-agent/{registry,bin}`.
- On the box, `/opt/hermes-agent` is a **symlink** to `/opt/projects/claude_code/infra/hermes-agent`
  (BRING-UP Phase 2; F5 explains why it must not be a real directory). Compose resolves the
  symlink, so `./bin` and `./registry` arrive as the long path, and the proxy would refuse.
- A real directory at `/opt/hermes-agent` would fix those two. But it would send
  `../../../claude-google-ads` to `/claude-google-ads`.

## Measured inputs — facts, re-verify before relying on them

Re-read each cited line. Line numbers drift.

**`ads-mutator`'s seven volumes** (`docker-compose.yml`, the `ads-mutator` service, ~lines 106-124):

| Compose source | Target | Allow-listed source (`hermes-docker-proxy.service`) |
|---|---|---|
| `${HERMES_GOVERNANCE_DIR}/approvals` | `/opt/governance/approvals:ro` | `/var/lib/hermes/governance/approvals` (:32) |
| `${HERMES_GOVERNANCE_DIR}/control` | `/opt/governance/control:ro` | `/var/lib/hermes/governance/control` (:33) |
| `${HERMES_GOVERNANCE_DIR}/registry` | `/opt/governance/registry:ro` | `/var/lib/hermes/governance/registry` (:34) |
| `${HERMES_GOVERNANCE_DIR}/log` (no mode suffix) | `/opt/governance/log` | `/var/lib/hermes/governance/log:…:rw` (:35) |
| `../../../claude-google-ads` | `/projects/claude_google_ads:ro` | `/opt/projects/claude-google-ads` (:36) |
| `./registry` | `/opt/registry:ro` | `/opt/hermes-agent/registry` (:37) |
| `./bin` | `/opt/cc-bin:ro` | `/opt/hermes-agent/bin` (:38) |

- **What was measured, and on what.** On the VPS, the measurement was the **`hermes-agent`
  gateway service's** binds, taken from both `/opt/hermes-agent` and the real path, with identical
  results. `ads-mutator` itself was **never created**, so its binds are an inference from the
  shared relative forms. The `:rw` spelling of the `log` bind (no suffix in compose) was measured
  by the proxy's Task 1 under Docker Desktop on darwin, which R22 says predicts nothing about
  Linux.
- **How the executor is launched.** `hermes-broker.py:41` sets `MUTATE_SH` to `run-ads-mutate.sh`
  next to `bin/`. `run-ads-mutate.sh:20` sets `here` with a logical `pwd` (not `pwd -P`), then
  `:88` runs `docker compose -f "$here/docker-compose.yml" run --rm --no-deps … ads-mutator`, with
  `DOCKER_HOST` pointing at the proxy socket (the broker unit's environment).
- **`proxy-policy-sync.test.py` does not check the paths.** It asserts only the **count (7) and
  shape** of the compose volumes, and that exactly one is writable. Its own docstring says "the
  unit supplies the resolved paths". Nothing compares the paths Compose actually resolves with the
  unit's `--allow-bind` values. That gap is what let F9 through.

## A second defect on the same path — verify it, then decide where it lives

Found while preparing this handoff, by reading only. **Unmeasured.**

- **The broker cannot read `.env`.** On the box `.env` is `600 root:root` (BRING-UP Phase 3,
  `install -m 600`). `run-ads-mutate.sh` runs as **`hermes-broker`** (it is a child of the broker
  unit).
  - `hostenv.sh:21` parses `HERMES_GOVERNANCE_DIR` out of `.env`. As `hermes-broker`, the read
    fails, the variable stays unset, and the R4 guard (`hostenv.sh:36-`) refuses.
  - Even with the variable exported, `docker compose` reads `.env` for interpolation. Since F10,
    the gateway service's volume is `${HERMES_SPOOL_DIR:?…}` (`docker-compose.yml:57`), so Compose
    **aborts the whole file** when it cannot resolve that variable. This happens even for
    `run ads-mutator`, which never mounts the spool.
- **What it means.** As deployed, the broker probably cannot run `docker compose` at all. It is on
  the exact path F9 is about (broker → compose → proxy create). It gates an accepted apply, which
  needs the kill switch, so like F12 it gates the kill switch, not Phase 6.
- **Decide:** fold it into F9's design, or record it as **F13** and design it separately. Do not
  make `.env` group-readable to fix it. It holds `ANTHROPIC_API_KEY`, and the broker has no
  business seeing it (compare the proxy unit's reasoning for not using `Group=hermes-broker`).

## Questions to settle — by reading the code and measuring, not by assuming

1. **Is F9 really a Phase 6 blocker?** Phase 6 installs the two units and verifies them (README
   "VPS deploy sequence" steps 3–5, the `curl …/version` probe). No container is created until an
   **accepted** apply, and that needs the kill switch. By that reading, F9, F12 and the `.env` issue
   all gate the kill switch, not Phase 6. Settle it from the code (what does the proxy do at start?
   does anything create a container before an accepted apply?). If Phase 6 is not blocked, say so
   in BRING-UP. That is an operator decision for the user; recommend, don't decide.
2. **Which path form is canonical: the symlink or the resolved path?** Options, with the costs you
   find:
   - **(A)** Pin the allow-list to the resolved paths
     (`/opt/projects/claude_code/infra/hermes-agent/{bin,registry}`). This ties the unit to where
     the checkout lives. The units already hardcode `/opt/hermes-agent` elsewhere (`ExecStart`,
     `WorkingDirectory`).
   - **(B)** Give compose absolute sources through variables, as `HERMES_GOVERNANCE_DIR` already
     does, for example for the agent directory and the ads repo, with the same `:?` no-fallback
     rule F10 used. Then measure whether Compose realpaths an **absolute** source through a
     symlink. It resolved the relative ones.
   - **(C)** The proxy canonicalizes (`realpath`) both sides before comparing. **This changes a
     security gate.** Check-time resolution against mount-time resolution is a TOCTOU if any path
     component is writable by someone other than root. It needs its own threat analysis and firing
     controls, and "we did it to make the comparison pass" is not a reason.
   - A real directory at `/opt/hermes-agent` is out: F5 already rejected it.
3. **How do you measure without the box?** The F10 Tier 2 suite shows the Linux CI runner can run
   root-level Docker work. A CI job could:
   - lay out `/opt/projects/claude_code` as a symlink or checkout and `/opt/hermes-agent` as a
     symlink;
   - `docker tag` a stand-in image as `hermes-agent-claude`;
   - run `docker compose --profile tools create ads-mutator` and then
     `docker inspect --format '{{json .HostConfig.Binds}}'`;
   - compare the result, **as strings**, with the unit's `--allow-bind` sources.

   That turns F9 into a test that fails on drift, and it makes `proxy-policy-sync.test.py`'s
   coupling real. **Never `docker compose config`** (HARD RULES). It is fine on a secret-less
   runner too, but the rule has no exceptions. Settle what `.env` the CI job needs (dummy values
   only, and `HERMES_SPOOL_DIR` is required since F10), and check that the job really ran (an
   executed count, as in F10 Tier 2).
4. **The `log` bind's mode string.** Does Compose on Linux send `…/log:/opt/governance/log:rw`,
   `…:rw,rprivate`, or no suffix? The proxy compares the whole string. Measure it in the same CI
   job.
5. **BRING-UP Phase 5's instrument.** Phase 5 tells the operator to
   `docker compose --profile tools create ads-mutator` on the box, which makes Docker create any
   missing governance sources as root. Since F10, README step 2 must create the layout **before**
   that happens (recorded as a follow-up on PR #35). Reorder or replace Phase 5 so that the box
   measurement is a confirmation of what CI already proved, taken after the layout exists.

## Constraints

- **Mutation stays disabled.** No kill switch.
- **Do not widen the allow-list** to make the comparison pass. Adding a source, loosening the exact
  match, or turning a `:ro` into `:rw` needs a threat argument in the spec, not convenience.
- **F12 stays separate** (`approve-changeset.py` and `persist-run-record.py` vs `data/vaults`), but
  write down anything F9's design constrains there.
- **F9's design must not move the spool back under `data/`** (F10 §8). The spool is not mounted
  into `ads-mutator` and is not on the allow-list; keep it that way.
- **Every new check needs a firing control:** a test that shows it fails on a mismatched bind set.
- **Linux behaviour is proven on the Linux CI runner, and you check it actually ran,** or you state
  plainly that it is unproven until the VPS. Docker Desktop on darwin remaps paths and ownership.
  Docker was unavailable on the laptop in the F10 session.
- **The VPS is a deploy target, not the dev workshop** (canon 2026-07-17).

## The process

Use `superpowers:brainstorming` to settle the five questions, then write a spec at
`docs/superpowers/specs/2026-09-2x-f9-bind-paths-and-proxy-allow-list-design.md`, then
`superpowers:writing-plans`, then execute. F10 used `superpowers:subagent-driven-development` with
a review per task and a final whole-branch review. That review caught two real defects the task
reviews missed, so keep the final review. The PR should include:

- the fix (whichever form question 2 settles on) and its tests, including a firing control;
- the Linux CI measurement of `ads-mutator`'s real binds against the unit, required to run, with
  its executed count read on the PR and on the merge commit;
- the `.env` readability defect, either fixed or recorded as F13 with its reasoning;
- `deploy/BRING-UP.md` Phase 5 (instrument and order) and Phase 6 (the banner, per question 1);
- the F9 entry in the findings record, marked fixed and pointing to the PR.

## STATE — measured 2026-09-22, re-measure before trusting it

| | |
|---|---|
| `main` | `af17792` (Merge PR #31). It includes F10 (PR #35, `6ddef24`), this handoff plus the F10 canon entry (PR #36, `64cc54e`), and the Tailscale design note (PR #31). CI green **on the merge commit** `af17792` (run 35744754627), with F10 Tier 2 `executed 22, skipped 0`. |
| Suites | hermes bin 29/29 · units 16 · provision 56 · node 22/22 · Tier 2 skips on darwin (runs on CI) |
| VPS | **Unchanged since 2026-09-21. F10 is not applied there yet.** The store is still an empty `700 root:root` directory, and there is no spool. Stack running, dashboard behind basic auth (tunnel only), public `:22` only. README step 1 users and groups exist. No units installed. The ads repo is a placeholder. |
| Kill switch | **ABSENT** |
| Laptop | Local `.env` needs `HERMES_SPOOL_DIR=./data/spool` before the next `docker compose up`. |
| Open PRs | #4 (stale). #31 merged the Tailscale design note **as a proposal only**: nothing is adopted or set up, so do not act on it. |

Run `git log`, `git status` and the suites before trusting any of this.

## HARD RULES

- **NEVER run `docker compose config`.** It prints the `env_file` secrets in cleartext.
- Never print a credential value, or write one into a tracked file. Never read or print `.env`.
- No client names, customer ids, campaign ids, metrics or drafts anywhere in git. Re-run the
  redaction scan **over added lines only**, with a **live control** that must fire.
- **Stage by explicit path only.** Never `git add -A`, `.project-brain/`, or `evals/`. The working
  tree carries unrelated operator changes (CLAUDE.md, `.project-brain/`, `evals/`, untracked files);
  leave them alone.
- `main` is protected. Land via PR. **Check CI on the merge commit**, not only on the PR.
- Only `brain-promote.js --approve` may modify the canon directory. A PreToolUse hook fires on any
  Bash command that merely *mentions* that path, **including `git add`**. Read canon with a non-Bash
  tool, and ask the user to stage a canon file with `! git add …` rather than working around the
  hook.

## MEASUREMENT TRAPS — earned

- **An instrument that reports "safe" must be shown reporting "unsafe" too.** A check nobody has
  seen fail proves nothing.
- **A green CI job can have executed nothing.** Read the executed count in the log. F10's Tier 2
  prints `executed N, skipped M` and fails when anything is skipped while it is required.
- **`cmd | tail` takes its exit status from `tail`.** Use `PIPESTATUS` (`pipestatus` in zsh), or
  capture into a variable.
- **A test that counts the wrong thing passes for the wrong reason.** `proxy-policy-sync.test.py`
  counts seven volumes and says nothing about their paths; that is how F9 shipped.
- **A mock is only as good as its fidelity.** On darwin, paths and ownership are not what Linux
  will do.
- **Plan text is the least reliable input.** That includes this document. If it disagrees with the
  code, the code wins and this document gets a PR.

## Confirm your understanding and flag any drift before starting.
