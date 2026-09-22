# F9 — The executor's bind paths and the proxy allow-list (design)

> **Status:** design approved in brainstorming, 2026-09-22; amended while writing the plan the
> same day (R1 the shell guard, R2 `.env` needs the new keys, R3 the CI job needs a PR — see §8).
> Plan: `docs/superpowers/plans/2026-09-22-f9-bind-paths-and-proxy-allow-list.md`.
> **Handoff:** `docs/superpowers/handoffs/2026-09-22-f9-bind-paths-and-proxy-allow-list.md`
> **Finding:** F9 in `docs/superpowers/specs/2026-09-21-vps-first-bring-up-findings.md`
> **Constraints carried from the handoff:** mutation stays disabled (no kill switch); the
> allow-list is not widened and the proxy is not changed; the spool stays out of `data/` and off
> the allow-list (F10 §8); F12 stays separate; every new check has a firing control; Linux
> behaviour is proven on the Linux CI runner with its executed count read; the VPS is not touched;
> never `docker compose config`.

## 1. Problem

The proxy (`bin/docker-create-proxy.py:231-232`) refuses any container create whose
`HostConfig.Binds` set is not exactly the pinned set from `--allow-bind` in
`deploy/hermes-docker-proxy.service:32-38`. `ads-mutator`'s compose sources
(`docker-compose.yml:98-124`) mix variable-derived absolute paths with **relative** ones
(`./bin`, `./registry`, `../../../claude-google-ads`). `proxy-policy-sync.test.py:41-46` checks
only the count (7) and shape of those volumes, never their paths, which is how F9 shipped.

The handoff also named a second defect on the same path: the broker (`hermes-broker`) cannot
read `.env` (`600 root:root`), which Compose needs for interpolation.

## 2. What was measured (throwaway spike, Linux CI)

Branch `spike/f9-measure`, workflow `F9 spike`, runs 1–2 on 2026-09-22. `ubuntu-latest`, Docker
Engine 28.0.4, Docker Compose v2.38.2, as root. Layout as on the box (BRING-UP Phase 2): the
checkout at `/opt/projects/claude_code`, `/opt/hermes-agent` a symlink to its
`infra/hermes-agent`, a placeholder `/opt/projects/claude-google-ads`, a busybox image tagged
`hermes-agent-claude`, dummy `.env` values. 8 sections executed.

| # | Measurement | Result |
|---|---|---|
| M1 | Relative sources, `-f /opt/hermes-agent/docker-compose.yml` (cwd the symlink, or `/`) | `/opt/hermes-agent/bin`, `/opt/hermes-agent/registry` (**match** the unit); `/claude-google-ads` (**mismatch**: the `..` is applied lexically to `/opt/hermes-agent`) |
| M2 | Absolute sources through the symlink, literal and via `${VAR}` | Sent **verbatim**: no symlink resolution, not even cleaning (`/opt/hermes-agent/../../../claude-google-ads` arrived as written) |
| M3 | The `log` bind's mode (no suffix in compose) | `/var/lib/hermes/governance/log:/opt/governance/log:rw` (matches the unit) |
| M4 | Non-root user, `.env` `600 root:root`, `docker compose run ads-mutator` | `open /opt/hermes-agent/.env: permission denied`, rc 1 — **even with every variable exported**. With `--env-file /dev/null` plus exported variables: passes |
| M5a | Real proxy, flags parsed from the unit's `ExecStart`; compose through it | Create refused (ads-repo bind), `docker compose run` rc **1** |
| M5b | Positive control: proxy pinned to the measured binds | Create **allowed**; the whole create/attach/wait/start sequence passes the proxy. The proxy denied `GET /info` and `GET /networks/<name>` and Compose continued |
| M6 | How the project directory is derived (cwd the symlink) | `PWD` set, no `-f`: short form. `PWD` unset, no `-f` or `-f` relative: **resolved long form**. `sudo docker compose` from the cwd, no `-f`: **resolved long form** (`sudo` drops `PWD`; Go's `os.Getwd` falls back to `getcwd`) |
| M6b | `run-ads-mutate.sh`'s own `$here` invoked as `/opt/hermes-agent/run-ads-mutate.sh` with `PWD` unset | `/opt/hermes-agent` (logical `cd`/`pwd`) |

**What this means for F9.** The bind strings depend on how Compose was started, not on anything
the operator configures. The 2026-09-21 box measurement (long form for `bin`/`registry`, ads
repo matching) is exactly what M6 reproduces for `sudo docker compose` from the working
directory; the broker's real path (`hermes-broker.py:41` → `run-ads-mutate.sh:20,88`) produces
M1's result instead: `bin`/`registry` match and only the ads-repo bind is wrong. No invocation
matches all seven. The root cause is the relative sources.

**What this means for the `.env` defect.** The handoff's first half was wrong:
`hermes-broker.service:21` sets `HERMES_GOVERNANCE_DIR`, and `hostenv.sh:21` only reads `.env`
when it is unset, so the R4 guard does not refuse. The second half stands and is worse than
stated: Compose aborts on the unreadable file even when every variable is already exported.

## 3. Decisions

### 3.1 Q1 — F9 does not block Phase 6

(Numbering in this section is BRING-UP's as of 2026-09-22, where Phase 6 is Hand Off, meaning unit
installation. §3.6 renumbers Hand Off to Phase 5.)

Phase 6 installs and verifies the two units (README "VPS deploy sequence" steps 3–5). None of it
creates a container: the proxy's `serve()` (`docker-create-proxy.py:525-538`) only listens; the
broker's `ExecStartPre`s (`init-host-layout.py --check`, `preflight-governance-access.py`) make
no Docker call; `GET /version` is on the proxy's allow-list (`:93`).

**Correction to the handoff's premise.** A container is not "created only after an accepted
apply, which needs the kill switch". The broker never reads the kill switch. The order is
`_process` → `classify` → `append_seen` → `_execute` → `reserve_approval` → `run-ads-mutate.sh`
→ `docker compose run` → **proxy create** → `apply-changeset.py:94` checks the kill switch and
exits 2. Container creation is gated by a **human approval**, not by the kill switch.

**Decision (operator, 2026-09-22):** Phase 6 is unblocked. A new named gate, **First approved
request (rehearsal)**, is added between Phase 6 and anything touching the kill switch (§3.6).

### 3.2 Q2 — Absolute compose sources from variables (option B)

All seven `ads-mutator` sources become absolute, variable-derived, with the `:?` no-fallback
rule F10 used:

```
${HERMES_GOVERNANCE_DIR:?…}/approvals:/opt/governance/approvals:ro
${HERMES_GOVERNANCE_DIR:?…}/control:/opt/governance/control:ro
${HERMES_GOVERNANCE_DIR:?…}/registry:/opt/governance/registry:ro
${HERMES_GOVERNANCE_DIR:?…}/log:/opt/governance/log
${HERMES_ADS_REPO_DIR:?…}:/projects/claude_google_ads:ro
${HERMES_AGENT_DIR:?…}/registry:/opt/registry:ro
${HERMES_AGENT_DIR:?…}/bin:/opt/cc-bin:ro
```

M2 shows Compose sends absolute sources verbatim, so the strings the proxy sees are exactly the
strings the operator wrote. On the box they come from the broker unit (§3.3) and equal the proxy
unit's `--allow-bind` sources, which do not change. Only `ads-mutator` changes: the gateway
service is not created through the proxy.

Rejected:
- **(A) pin the allow-list to resolved paths.** Wrong for the broker's real path (M1 sends
  `/opt/hermes-agent/bin`, not the long form), ties the unit to the checkout location, and still
  depends on how Compose is invoked.
- **(C) proxy canonicalizes both sides.** Changes a security gate and opens a check-time vs
  mount-time gap; not needed once B works.
- **Real directory at `/opt/hermes-agent`.** Rejected by F5.
- **B for the ads repo only.** Leaves `bin`/`registry` invocation-dependent (M6).

**Locally** (darwin, no proxy): `.env` may hold relative values (`HERMES_AGENT_DIR=.`,
`HERMES_ADS_REPO_DIR=../../../claude-google-ads`); a relative value produced by interpolation is
resolved against the project directory as before. `:?` still refuses an unset or empty value.

### 3.3 The `.env` defect — folded into F9

`run-ads-mutate.sh` always invokes `docker compose --env-file /dev/null -f "$here/docker-compose.yml" …`,
so Compose never opens `.env` (M4). Compose then takes every interpolated variable from the
environment:

- **On the box** the broker unit supplies them. `hermes-broker.service` adds
  `HERMES_AGENT_DIR=/opt/hermes-agent`, `HERMES_ADS_REPO_DIR=/opt/projects/claude-google-ads` and
  `HERMES_SPOOL_DIR=/var/lib/hermes/spool` beside the existing `HERMES_GOVERNANCE_DIR`.
  `HERMES_SPOOL_DIR` is needed only because Compose interpolates the whole file, gateway included
  (`docker-compose.yml:57`), even for `run ads-mutator`; its value equals `HERMES_SPOOL_ROOT` and
  a comment says why it is there. The spool is still not mounted into `ads-mutator` and not on
  the allow-list.
- **Locally** `hostenv.sh` parses the four variables (`HERMES_GOVERNANCE_DIR`,
  `HERMES_AGENT_DIR`, `HERMES_ADS_REPO_DIR`, `HERMES_SPOOL_DIR`) from `.env` as data, exactly as
  it parses `HERMES_GOVERNANCE_DIR` today (never sourced), **per variable and only when that
  variable is unset**. A value already in the environment always wins. When all four are set,
  `.env` is not opened at all — required, because on the box it is unreadable and a failed
  redirect under `set -eu` would abort the wrapper. The R4 guard stays on
  `HERMES_GOVERNANCE_DIR` only (R1, §8): the other three are guarded by compose's `:?`.

`.env` stays `600 root:root`. It is not made group-readable: it holds `ANTHROPIC_API_KEY`, which
the broker has no business seeing.

### 3.4 Q3/Q4 — how it is proven without the box

**Static half (every platform, discovered by `run-bin-tests.sh`).** `proxy-policy-sync.test.py`'s
count-only check is replaced by an agreement test: interpolate each `ads-mutator` compose source
with the **broker unit's** `Environment=` values, apply the mode (`:ro`, or `:rw` for the bare
`log` entry, per M3), and assert the resulting set equals the **proxy unit's** `--allow-bind` set
**as strings**. Firing control: a single altered value, in the unit environment or a compose
source, is reported as a mismatch.

**Linux half.** A new `deploy/bind-agreement-integration.test.py`, run as root under
`HERMES_REQUIRE_LINUX_INTEGRATION=1` (any skip fails), printing
`bind-agreement: executed N, skipped M, failures F`:

1. Build the box layout: checkout under `/opt/projects/claude_code`, `/opt/hermes-agent` a
   symlink, a placeholder ads repo, the governance store via `init-host-layout.py --apply`.
2. Build a stand-in image from a fixture Dockerfile beside the test: an official `python` slim
   image pinned by digest plus a uid-10000 user, tagged `hermes-agent-claude`. The executor and
   its libraries are stdlib-only (`apply-changeset.py:19-23`, `changeset_lib`, `governance_lib`,
   `vault_lib`), so the real executor runs.
3. Start the real proxy with the flags parsed from the proxy unit's `ExecStart` (listen socket
   moved to a test path, socket group granted to the test user).
4. **Positive case.** As a non-root user in the socket's group, with the broker unit's
   environment and `.env` at `600 root:root`, run the wrapper's Compose invocation with valid
   dummy `--client`/`--changeset`/`--request` values. Assert: the proxy log shows
   `ALLOW POST …/containers/create`; the executor exits **2**; its output says mutation is
   disabled.
5. **Firing controls** (each must fail): a proxy with one `--allow-bind` altered refuses the
   create; Compose without `--env-file /dev/null` fails on `.env`; a broker environment with one
   wrong path is refused by the proxy.

The plan decides whether step 4 drives `run-ads-mutate.sh` itself (preferred: it covers
`hostenv.sh` and the `--env-file` flag on the real path) or its exact Compose command, depending
on whether `preflight-governance-access.py` passes against the layout step 1 builds. If it drives
the Compose command, a static test asserts the command equals the wrapper's.

**Q4** is settled by M3: Compose v2.38.2 on Linux sends `:rw`. The integration test re-asserts it
on every run, so a Compose upgrade that changes the spelling fails CI.

### 3.5 CI wiring

A **new job**, "Bind agreement (root, Linux, real proxy)", beside the existing jobs, not a step in
`tests`: F10 Tier 2 also creates users and paths as root, and a separate job keeps them off one
runner. The executed count is read on the PR run **and** on the merge-commit run. Making the job
a required status check on `main` is a GitHub settings change on the operator's account; the
implementer asks rather than doing it.

### 3.6 Q5 — BRING-UP

- **Phase 5 is replaced.** The old instrument (`sudo docker compose --profile tools create
  ads-mutator`) measures the wrong thing (M6: `sudo` from the cwd resolves the symlink; the
  broker's path does not) and, run before README step 2, makes Docker create governance
  directories as root. The new **Confirm the bind agreement** phase runs **after** README
  steps 2–5 (layout and units in place) and confirms what CI proved, on the real path: as
  `hermes-broker`, through the proxy socket, with the broker unit's environment and
  `--env-file /dev/null`, run the wrapper's Compose command with dummy ids. Expected: the proxy
  journal shows `ALLOW POST …/containers/create` and the executor exits 2, "mutation is
  disabled". This also confirms the box's own Compose version and the proxy's endpoint set.
  On any refusal: stop, record, do not widen. Numbering: the old Phase 5 is removed (its
  2026-09-21 result moves to the findings record), Hand Off becomes Phase 5, and Confirm is the
  new Phase 6, followed by the rehearsal gate, then Phase 7 (dashboard) unchanged.
- **Hand Off banner (now Phase 5):** "Not blocked. Installing and verifying the units creates no container",
  citing §3.1.
- **New gate, First approved request (rehearsal):** needs F9 (this work), F12 (a working approval
  writer), `.env.gaw` with the write credential, and Phase 6 (Confirm) passed. Proof: with the kill switch
  **absent**, a human-approved request goes broker → proxy → container and comes back
  `refused_preflight`, "mutation is disabled". Still required before the kill switch is created:
  F12, F14 (§3.7), and the existing §6 hardening gates.

### 3.7 F14 — recorded, not fixed here

`docker compose run` exits 1 on any Compose-level failure (M4, M5a). The broker maps 1 to
`refused_usage`, whose detail says "nothing was mutated" (`hermes-broker.py:489-503`). For a
refusal at create that is true. If Compose loses the proxy connection **after** the container
started, it may also return 1 while the executor is mid-apply, and the broker would promise
"nothing was mutated" about a run that may have changed the account — a side door around
`apply-changeset.py:57`'s exit-2 guarantee. Inferred, unmeasured. Recorded as F14 in the
findings record with the M5 evidence; it gates the kill switch, not the rehearsal (the kill
switch is absent there, so nothing can mutate); designed in its own PR.

## 4. Records

- **Findings record:** F9 marked fixed, pointing to the PR, with a correction: the 2026-09-21
  measurement was an artifact of `sudo docker compose` from the working directory (M6); on the
  broker's path only the ads-repo bind was wrong. The `.env` defect recorded inside F9 as a second
  defect on the same path, fixed, with M4, and the handoff's first half corrected. F14 added. The
  outcome table: Phase 5 "fixed in the repo, box confirmation pending (BRING-UP Phase 6)"; Phase 6
  "not blocked". Open items: item 1 becomes the BRING-UP Phase 6 box confirmation; F14 added.
- **Handoff:** a short correction note (the `.env` premise; the "container only after the kill
  switch" premise) pointing here.
- **Canon:** untouched. A brain session entry records that the canon line "F9 is the only blocker
  for Phase 6" is superseded, as a candidate for `brain-promote --approve`. It is left unstaged.
- **Spike branch** `spike/f9-measure` is deleted once this spec is merged; the integration test
  replaces it.

## 5. What F9's design constrains elsewhere

- **F12:** the broker's environment now carries `HERMES_AGENT_DIR`; a fix for
  `approve-changeset.py` / `persist-run-record.py` should take paths from the same variables
  rather than new relative forms.
- **F14:** any distinct "Compose failed before start" exit code must survive
  `--env-file /dev/null` failures and proxy refusals, the two measured rc-1 cases.
- **Other wrappers** (`run-ads-audit.sh` and friends) run as the operator and still read `.env`;
  they are out of scope.

## 6. Order of work

1. Static agreement test, failing against today's compose (the firing control against real
   drift); it replaces the count-only check.
2. Compose sources, broker unit `Environment=`, `.env.example`, README; `units.test.py` updated.
3. `hostenv.sh` (four variables, per-variable, never open `.env` when all set) and
   `run-ads-mutate.sh` (`--env-file /dev/null`), with tests including an unreadable `.env`.
4. Stand-in image fixture, `bind-agreement-integration.test.py`, the CI job, firing controls.
5. BRING-UP: new Phase 5 and its position, Phase 6 banner, the rehearsal gate.
6. Findings record (F9, `.env`, F14, tables) and the handoff correction.
7. Brain session entry (unstaged).
8. Final whole-branch review; redaction scan over added lines with a live control; local suites;
   PR; CI on the PR with the executed count; merge (operator); CI on the merge commit with the
   executed count; delete the spike branch.

## 7. Accepted risks

- The box's Compose version may behave differently from v2.38.2. Phase 6 on the box catches it
  before the rehearsal.
- The stand-in image is not the real image (Python version, base layers). Phase 6 on the box runs
  the real image.
- The proxy denies `GET /info` and `GET /networks/<name>` and Compose v2.38.2 continues (M5b).
  Recorded as Linux evidence for README's "re-measure the endpoint allow-list" note; nothing is
  widened.

## 8. Amendments (while writing the plan, 2026-09-22)

- **R1 — the shell guard.** `hostenv.sh` is also sourced by `changeset.sh`, which never runs
  Compose. Refusing there on the three Compose-only variables would break a tool that does not
  need them. `hostenv.sh` therefore only *parses* `HERMES_AGENT_DIR`, `HERMES_ADS_REPO_DIR` and
  `HERMES_SPOOL_DIR`; compose's `:?` is their guard (an unset or empty value stops Compose before
  any create). The R4 guard and the absolute-path check stay on `HERMES_GOVERNANCE_DIR`, which
  host-side tools use directly.
- **R2 — `.env` needs the new keys.** Compose interpolates the whole file, inactive profiles
  included, so once `ads-mutator` uses `${HERMES_AGENT_DIR:?…}` and `${HERMES_ADS_REPO_DIR:?…}`,
  every `docker compose` call that reads `.env` (the operator's `up`, `down`, the audit wrappers)
  needs both keys. README step 2 gains non-printing append lines for them, beside the existing
  `HERMES_SPOOL_DIR` line, and the 2026-09-21 box's upgrade list names them. The laptop's `.env`
  needs them too (the operator adds them; nobody reads `.env`).
- **R3 — the CI job needs a PR.** `ci.yml` runs on `pull_request` to `main` and on `push` to
  `main` only, so the new job first runs on a PR. The plan opens a **draft** PR after the
  integration task (outward-facing: ask the operator first) and reads the executed count there
  before the remaining tasks.
