# Session prompt — post-F12: bring the box up to date, then pick the next blocker

Open a new session and point it here instead of pasting the body:

> Read `docs/superpowers/handoffs/2026-09-23-post-f12-state-and-next-steps.md`,
> then confirm your understanding and flag any drift before starting.

Pointing at the file keeps corrections versioned.

---

**Mutation stays disabled throughout. The kill switch is ABSENT and nothing below creates it.**

Two waves landed on 2026-09-22/23 — **F9** (executor bind paths vs the proxy allow-list) and
**F12** (approvals and run records vs `data/vaults`) — plus **F15/F16** found during the first
real unit installation. The repo is ahead of the box: everything F12 added is on `main` and
proven on Linux CI, but the VPS has not been touched since 2026-09-22 and does not yet have the
`records/` directory the broker now checks for at every start.

## What is true now (re-verify before relying on it)

| | |
|---|---|
| `main` | `8f7b61a` (Merge PR #42, F12). CI green **on the merge commit** (run 35891303120): `layout-integration: executed 30, skipped 0` · `bind-agreement: executed 6, skipped 0` · hermes bin 31/31 |
| Required checks on `main` | **`Bind agreement (root, Linux, real proxy)`** and **`Test suites (node + hermes bin)`** — added 2026-09-22 to the `main-protection` ruleset. They gate by job NAME, so renaming a job in `ci.yml` silently un-gates it |
| Box (`hermesops@srv1997271`) | **At `da2a0ae` — two merges behind** (#41 canon, #42 F12). F10's layout applied; both units installed and **running**; gateway up; F9's bind agreement **confirmed on the box** 2026-09-22 (BRING-UP Phase 6: `rc=2`, `ALLOW POST /v1.55/containers/create`, Docker 29.8.1) |
| Box gaps | No `records/` directory. No approval has ever been written there. The ads repo is still a placeholder (F6) |
| Kill switch | **ABSENT** |
| Laptop | `.env` has all four keys (`HERMES_GOVERNANCE_DIR`, `HERMES_SPOOL_DIR`, `HERMES_AGENT_DIR`, `HERMES_ADS_REPO_DIR`). Docker daemon was NOT running this session — all Linux proof came from CI |
| Brain | `decisions/candidates/2026-09-23-f12-fixed-and-proven-on-linux-ci-pr-42.md` is **compiled and lint-clean, awaiting the operator's `brain-promote --approve`**. Canon already holds the F9 and F10 entries |

Run `git log`, `git status` and the suites before trusting any of this.

## FIRST TASK — the box is one step from a restart loop

**This is time-sensitive in one specific way.** The broker unit's `ExecStartPre` now runs
`init-host-layout.py --check`, which covers the new `records` row. After the operator pulls, the
unit **will not start** until `--apply` creates that directory, and with `Restart=on-failure` /
`RestartSec=5` that is a restart loop. The refusal names `records`, so it is diagnosable — but
pull and apply belong in one sitting.

On the box, from `/opt/hermes-agent` (BRING-UP's "After pulling F12" block has this verbatim):

```bash
sudo git -C /opt/projects/claude_code pull --ff-only
python3 bin/init-host-layout.py                                   # dry run: one line, "create records"
sudo python3 bin/init-host-layout.py --apply
sudo -u hermes-broker python3 bin/init-host-layout.py --check     # must exit 0
systemctl is-active hermes-docker-proxy hermes-broker             # both active
```

No unit files changed, so nothing needs reinstalling and the gateway is untouched. If the pull
refuses on a local modification, check it is only a file mode — the F15 `chmod` was hand-applied
on 2026-09-22 and is now backed by git; `git checkout -- <path>` then re-pull is the fix, and
`git diff` should show `old mode`/`new mode` with no content lines.

## Then choose the next blocker

**The rehearsal gate is one item away.** With F9 and F12 landed, `BRING-UP.md`'s
"Gate: First Approved Request (Rehearsal)" needs only **`.env.gaw` carrying the WRITE Google Ads
credential**. The rehearsal is: with the kill switch **absent**, a human-approved request goes
broker → proxy → container and comes back `refused_preflight` ("mutation is disabled"). It
exercises the broker's own path — reservation, the wrapper, persistence — which Phase 6 does not.
Note `.env.gaw` means real write credentials on the box; that is a security decision, not a
mechanical step, and the 2026-09-17 handoff's §6 gates are where it belongs.

**Open items, in the findings record's order** (`docs/superpowers/specs/2026-09-21-vps-first-bring-up-findings.md`):

1. **F6** — a deploy-key clone of the ads repo, after the security review. The box's is a placeholder.
2. **F3** — a `--check` for usable sudo, with a firing control.
3. **F8** — `data/skills` ownership; the `docker_config_migrate.py` warning.
4. **F14** — a Compose failure exits 1 and the broker reports `refused_usage` — "nothing was
   mutated" — which could be **false** if the connection breaks after the container started.
   **Inferred, never measured.** Gates the kill switch. Laptop work, and the natural next code wave.
5. **F16** — audit the other host-side tools for container-path defaults (`migrate-governance.py`
   defaulted to the container's `/opt/governance`; README's `--bootstrap-logs` commands were
   fixed, but the pattern may repeat elsewhere).

Also outstanding, not in that list: the **§6 hardening including `UMask=0077`** — F12 made every
approval artifact umask-independent specifically so this can land, but it did not land it.

**Recommendation:** F14 next if staying on the laptop — it is the last recorded correctness defect
gating the kill switch, and it is the same shape as F9/F12 (spec → plan → subagent execution with
a firing control on every new check). F6 if the priority is making the box able to do real work.

## What F12 actually changed, for a reader who did not live it

- **Run records** moved out of the gateway-owned vault to `<store>/records/<slug>/`
  (`<cid>.result.json` + `timeline.md`, files `0640`, per-client directory `0o2750`). The writer
  **refuses** if `records/` is missing, naming `init-host-layout.py --apply`.
- **Approval artifacts** get explicit ownership and modes set **on the open fd before the rename**:
  approval `0640`, snapshot `0640`, lock sidecar `0660`, owner `hermes-broker:hermes` when root.
  The per-client `approvals/<slug>/` directory gets the same treatment.
- **`approve-changeset.py` refuses non-root on Linux.** Approving is now
  `sudo ./changeset.sh approve …`.
- **Any change-set approved BEFORE this must be re-approved** — the fix does not repair existing
  artifacts, and the first reserve on one still fails exactly as F12 did.
- **Deliberate loss:** applied changes no longer appear in the vault's `timeline.md`, which
  `run-trend-audit.sh` feeds the analyst as client history. The audit path still writes that file;
  the fsynced governance audit log remains authoritative.
- **Untouched:** the proxy, its `--allow-bind` set, the seven `ads-mutator` binds,
  `docker-compose.yml`, both unit files, `ReadWritePaths=`, and the pre-flight (which deliberately
  does **not** declare `records/` — it describes what the CONTAINER needs, and `records/` has no
  mount; a test pins that absence).

## HARD RULES (unchanged, and earned)

- **NEVER run `docker compose config`.** It prints `env_file` secrets in cleartext.
- Never print a credential value or write one into a tracked file. **Never read or print `.env`** —
  use the non-printing `grep -q … || echo … | sudo tee -a` idiom.
- **Do not widen the proxy allow-list** to make anything pass. A refusal is a refusal.
- **Stage by explicit path only.** Never `git add -A`, `.project-brain/`, `evals/`, `CLAUDE.md`.
  The working tree carries unrelated operator changes.
- `main` is protected: land via PR, and **check CI on the merge commit**, not only on the PR.
- Only `brain-promote.js --approve` may modify the canon directory. A PreToolUse hook fires on any
  Bash command that merely **mentions** that path, including `git add` and `rm`. Read canon with a
  non-Bash tool, and ask the operator to stage canon files with `! git add …`.
- **Never edit a tracked file to run a mutation test.** A background security scanner fires on
  modified security-relevant lines — it did this session, on a legitimately-scoped check. Use a
  scratchpad copy, or a fixture that reproduces the shape.

## MEASUREMENT TRAPS — earned, several of them this session

- **An instrument that reports "safe" must be shown reporting "unsafe" too.** A check nobody has
  seen fail proves nothing.
- **A green CI job can have executed nothing.** Read the executed count. `layout-integration`
  prints `executed N, skipped M` and fails when anything skips while required.
- **A test can pass for the wrong reason.** One F12 Tier 2 test passed on **ENOENT** — the
  directory did not exist — so it would have passed against a `0777` directory too. Pin the cause
  (`assertIn("Permission denied", stderr)`), not just the failure.
- **Darwin proves nothing about Linux ownership or setgid group inheritance** (BSD vs System V).
  Two spec bugs this session were invisible locally: a mode that stripped the setgid bit, and a
  directory root created that blocked the broker anyway.
- **A guard can silently delete coverage on the platform it exists for.** F12's root guard bounced
  13 `approve-changeset` tests at exit 2 on Linux CI; darwin passed 46/46 and hid it. Neutralise
  the guard in the fixture — do **not** `skipIf(linux)`, which preserves the hole.
- **A new exception type must be caught by its callers.** `_apply_owner_mode`'s `RuntimeError`
  escaped both, and a comment enumerating what those functions raise had been silently falsified.
  Task-scoped reviews cannot see this; the whole-branch review can.
- **Never claim a proof you do not have.** A findings record said "Tier 2 on Linux CI reproduces…"
  before any CI run existed. Stage such claims as design intent with a placeholder, and fill them
  only from a real run id and count.
- **Plan text is the least reliable input.** That includes this document. If it disagrees with the
  code, the code wins and this document gets a PR.

## Housekeeping the operator may want

- **Promote the F12 brain candidate** (`brain-promote --approve --to canon`), then a small PR to
  commit it — canon changes need one, and the hook means the operator stages the file.
- A **stale duplicate** F9 candidate sits in `decisions/candidates/` (canon already holds the
  corrected entry). `! rm .project-brain/decisions/candidates/2026-09-22-f9-bind-paths-fixed-and-proven-on-linux-ci-pr-38.md`
- **19 merged-looking branches** remain on the remote if a sweep is wanted.

## Confirm your understanding and flag any drift before starting.
