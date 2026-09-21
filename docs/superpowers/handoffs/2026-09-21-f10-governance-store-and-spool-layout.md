# Session prompt — F10: design the governance store and spool layout for a fresh Linux host

Open a new session and point it here instead of pasting the body:

> Read `docs/superpowers/handoffs/2026-09-21-f10-governance-store-and-spool-layout.md`,
> then confirm your understanding and flag any drift before starting.

Pointing at the file keeps corrections versioned.

---

**This is design work on the laptop. The VPS is not touched in this session.** The product is a
landed PR: a layout for the governance store and `data/spool/`, created by something
reproducible, with tests that show each check reporting failure when it should. After it lands,
Phase 6 (the systemd units, `README.md:957` steps 2–5) can resume on the box in a later
session.

**Mutation stays disabled throughout.** The kill switch is not created. Nothing here enables it.

## Why this exists

The first real bring-up (2026-09-21, PR #33) reached Phase 6 and stopped. It stopped on
purpose: the stack could have run, but the layout below has never been designed. Read the
**F10** section of `docs/superpowers/specs/2026-09-21-vps-first-bring-up-findings.md` first.
In short:

- On a fresh host, **nothing creates the store's contents.** Only `migrate()` creates any of
  `approvals/`, `control/`, `registry/`, `log/`, `seen/` and `registry/clients.json`, and only
  by copying from existing local vaults. The VPS has none. `--bootstrap-logs` refuses a missing
  `log/` **by design** (`bin/migrate_governance_shim.py:153`).
- The **store owner** is unspecified. README:894 says "deploy/broker user" and nothing more.
- **`data/spool/`** must exist before the broker unit can start. Its Linux permissions are
  undocumented. `data/` is currently `700`, owned by uid 10000, so `hermes-broker` cannot even
  traverse it.

The spool is **the only channel between the agent and the broker**. Its permissions decide who
can plant, delete, read or overwrite a request, a result, or a quarantined file. That makes this
a security design decision. It is not a `chmod` to be settled at a prompt.

## Measured inputs — facts, re-verify before relying on them

Re-read each cited line. Line numbers drift.

**Who touches the store, and how**

| Path | Broker (`hermes-broker`, host) | Executor (`ads-mutator`, uid 10000) | Gateway (uid 10000) |
|---|---|---|---|
| `approvals/` | writes: `reserve_approval` (`hermes-broker.py:495`), `record_outcome` (`:520`) | `:ro` mount | not mounted |
| `control/` | creates `control/.locks/` and takes per-client `flock`s (`hermes-broker.py:60-77`, `governance_lib.py:94`) | `:ro` mount | not mounted — `governance_lib.py:95-97` depends on that |
| `registry/clients.json` | reads (pre-flight in `ExecStartPre`) | `:ro` mount | not mounted |
| `log/<slug>.jsonl` | reads? **verify** | appends to a pre-created file (`log/` is `2750`, the file `0660`, group 10000) | not mounted |
| `seen/<slug>.jsonl` | `makedirs` + append + fsync (`changeset_lib.py:626-632`, called at `hermes-broker.py:403`) | **not mounted**, deliberately (`docker-compose.yml` comment near the `log` mount) | not mounted |

**Who touches the spool** (`HERMES_SPOOL_ROOT=/opt/hermes-agent/data/spool` on the host,
`/opt/data/spool` in the container):

| Path | Writer | Reader / remover |
|---|---|---|
| `requests/` | gateway: `hermes-syscall.py:52-53` **creates the directory itself** and writes requests | broker reads, `unlink`s, or moves to `requests/.quarantine/` (`hermes-broker.py:192-204`) |
| `requests/.quarantine/` | broker `makedirs`, inside a directory the gateway can write | — |
| `results/` | broker `makedirs` + `mkstemp` + `os.replace` (`spool_lib.py:187-206`) | gateway reads |

**The broker unit** (`deploy/hermes-broker.service`): `User=hermes-broker`,
`Group=hermes-broker`, `SupplementaryGroups=hermes-rail hermes`, `ProtectSystem=strict`,
`ReadWritePaths=/var/lib/hermes/governance /opt/hermes-agent/data/spool`. `ReadWritePaths` needs
both paths to exist at unit start.

**Host facts, measured on the VPS on 2026-09-21:** `hermes:x:10000:hermes-broker`,
`hermes-rail:x:1001:hermes-broker`, `hermes-broker` uid 997, `hermes-docker-proxy` uid 999 (in
`docker`). The store is `/var/lib/hermes/governance`: empty, `700 root:root`. `data/` is `700`,
owned by uid 10000, group `hermes`. `data/skills` is `755 root:root`.

**The pre-flight** (`bin/preflight-governance-access.py`) requires `READ_ONLY_DIRS =
approvals, control, registry` (`:30`), `READ_WRITE_DIRS = log` (`:53`), and
`registry/clients.json` (`:58`), which may be `{}` for zero clients (`:361-368`). It checks only
from the **executor's** point of view, uid 10000. Run as `hermes-broker` against the empty
store, it printed `Permission denied` for every subdirectory. It **cannot tell "missing" from
"unreadable"** when the root cannot be entered.

## Questions to settle — by reading the code, not by assuming

1. **Store owner.** In the bring-up session the assistant sketched "owned by `hermes-broker`,
   group `hermes` (10000), dirs `750`, `log/` `root:hermes 2750`". **That sketch was never
   checked. Question it; do not inherit it.** In particular: can the broker write `log/`? Should
   it? And what does "owner is not the executor" buy against the POSIX owner-class rule
   described in README:928?
2. **Spool ownership and modes.** The gateway, uid 10000, must create requests. The broker must
   delete and quarantine them, and write results. How does `requests/` grant the broker `unlink`
   without granting the gateway anything over `results/` or `.quarantine/`? Look at: a setgid
   shared group, the sticky bit (does it block the broker's `unlink` of the gateway's files?), and
   whether `.quarantine/` can sit inside a gateway-writable directory at all. Also:
   `hermes-syscall.py` creates `requests/` itself, so a pre-created directory's mode is only kept
   if nothing re-creates it.
3. **Who creates the skeleton.** Options: a new `migrate-governance.py` mode (for example
   `--init-store`, dry-run by default, same pattern as `--bootstrap-logs`), or runbook steps, or
   `provision.sh`. Precedent favours a governed operator CLI, with the reasoning in the
   `bootstrap_logs` docstring (ruling R23). **It must refuse** to "fix" an existing store with
   the wrong ownership, for the same reason `bootstrap_logs` refuses to create `log/`.
4. **Should the pre-flight tell "missing" from "unreadable"?** Today both look the same. A
   clearer refusal is cheap. But the pre-flight is a gate, and any change to it needs its own
   firing control.
5. **`data/` as a whole.** The spool lives under `data/`, which the bring-up made `700` uid
   10000. Either `data/` gains group traverse, or the spool moves out from under it. **Moving it
   changes `ReadWritePaths` and the compose mount.** Check what else assumes `data/spool`.

## Constraints

- **Mutation stays disabled.** No kill switch.
- **Do not widen anything to make something pass.** That includes the proxy allow-list, and
  modes beyond what the table above justifies.
- **F9** (resolved bind paths vs. the proxy allow-list for `bin` and `registry`) is a separate
  item. It comes **after** F10. Do not fold it in. If F10's design constrains F9, write that
  down.
- **Every new check needs a firing control.** That means a test that runs the check against a
  bad layout and shows it fails. The history here is that defects live in code that
  *verifies*: 13 in the build, and F3 on the real box ("in the sudo group" passed while sudo was
  unusable).
- **Linux ownership cannot be proven on darwin.** Docker Desktop remaps ownership, and
  platform-gated tests pass vacuously off Linux. Where a test needs real uids, gids and modes,
  either run it on the Linux CI runner and **check it actually ran there**, or state plainly
  that it is unproven until the VPS.
- **The VPS is a deploy target, not the dev workshop** (canon 2026-07-17). Design, build and
  test here; land by PR; apply on the box in a later session.

## The process

Use `superpowers:brainstorming` to settle the five questions, then write a spec at
`docs/superpowers/specs/2026-09-2x-f10-governance-store-and-spool-layout-design.md`, then
`superpowers:writing-plans`, then TDD. The PR should include:

- the skeleton creator (whatever form question 3 settles on) and its tests, including a firing
  control
- `README.md` "Ownership on a Linux host" and "VPS deploy sequence" step 2, corrected so a fresh
  host has a documented path
- `deploy/BRING-UP.md` Phase 6: remove the **Blocked** banner **only if** the PR really unblocks it
- the F10 entry in the findings record, marked fixed and pointing to the PR

## STATE — measured 2026-09-21, re-measure before trusting it

| | |
|---|---|
| `main` | `7e0fee8` (Merge PR #33). CI green **on the merge commit** (run 35645902405). |
| Suites | provision OK · hermes bin 27/27 · node 22/22 — on darwin |
| VPS | Stack running, dashboard enabled behind basic auth (tunnel only), public `:22` only. README step 1 users and groups exist. **No units installed.** Store empty, `700 root:root`. Ads repo is a placeholder. |
| Kill switch | **ABSENT** |
| Open PRs | #31 Tailscale (proposal only; do not act on it) · #4 (stale) |

Run `git log`, `git status` and the suites before trusting any of this.

## HARD RULES

- **NEVER run `docker compose config`.** It prints the `env_file` secrets in cleartext.
- Never print a credential value, or write one into a tracked file.
- No client names, customer ids, campaign ids, metrics or drafts anywhere in git. Re-run the
  redaction scan **over added lines only**, with a **live control** that must fire.
- **Stage by explicit path only.** Never `git add -A`, `.project-brain/`, or `evals/`.
- `main` is protected. Land via PR. **Check CI on the merge commit**, not only on the PR.
- Only `brain-promote.js --approve` may modify the canon directory. A PreToolUse hook fires on any
  Bash command that merely *mentions* that path, so use a non-Bash tool to read it.

## MEASUREMENT TRAPS — earned

- **An instrument that reports "safe" must be shown reporting "unsafe" too.** A check nobody has
  seen fail proves nothing.
- **`cmd | tail` takes its exit status from `tail`.** Use `PIPESTATUS`, or capture into a variable.
- **A guard that prints a warning and carries on is not a guard.** In the bring-up, a length check
  printed `TOO SHORT` and the next line wrote the bad value anyway.
- **A mock is only as good as its fidelity.** On darwin, file ownership is not what Linux will do.
- **Plan text is the least reliable input.** That includes this document. If it disagrees with
  the code, the code wins and this document gets a PR.

## Confirm your understanding and flag any drift before starting.
