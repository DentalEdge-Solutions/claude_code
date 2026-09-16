# Phase B — socket proxy and systemd units: planning brief

> Written 2026-09-16, the day S3-b merged (`800135f`). **This is a brief, not a plan.** The
> next session should brainstorm from it. Everything below was measured against the tree at
> `800135f`; where something is unmeasured it says so.

## The finding Phase B closes

On a VPS **the broker's Docker access is host root.** Anything holding the Docker socket can
start a container as any user with any mount, which bypasses every guarantee the mutation rail
provides — by construction, not by defect. S3-b hardened the audit log; it did nothing about
this, and it cannot.

This is canon rule 2 in its sharpest form: *a guardrail secures a path, never a capability…
the measure of a safety model is its weakest reachable path, not its best-designed one.* Until
Phase B lands, the honest description of Phase A is **one well-guarded path beside an
unguarded host**, and nothing may describe it as deployed or deployable.

## The first thing to know: this is NOT unplanned work

`docs/superpowers/plans/2026-08-24-hermes-governed-syscall.md` already contains both tasks in
full, TDD-structured:

- **Task 10** (`:2740`, 288 lines) — `docker-create-proxy.py`, a body-inspecting allow-list.
  Produces `decide(method, path, body) -> (bool, str)` as a pure function plus the socket
  plumbing, and a CLI `--listen PATH --upstream /var/run/docker.sock --image IMAGE`.
- **Task 11** (`:3027`, 254 lines) — the two systemd units and the VPS deploy sequence.

**So the wave's job is re-validation against six weeks of drift, not planning from scratch.**
A session that brainstorms Phase B from nothing will rewrite work that already exists and lose
the reasoning in it. Read those two tasks first, then treat the drift below as the delta.

## What is already measured (D1, spec §6.4)

One real `docker compose run --rm --no-deps ads-mutator` was passed through a logging
pass-through on the socket. It makes **14 calls across 10 distinct endpoints**; `create` and
`start` are **2 of the 14**. The spec's original "restrict to create and start" would break the
rail outright.

Two consequences the plan already absorbs, both load-bearing:

1. **`attach` is requested with `stdin=1`** (`?stderr=1&stdin=1&stdout=1&stream=1`), so the
   proxy grants a **bidirectional stream**, not a read-only tail. That is a wider grant than
   "start one container" and must be reasoned about explicitly rather than inherited from the
   CLI's defaults. `attach` and `wait` are how the wrapper reads the `HERMES-RESULT-JSON` line
   and the exit code — the entire result and classification path.
2. **`POST /containers/create` is the call that carries the bind mounts**, so it is the one
   whose *body* must be inspected. A path-and-verb allow-list would let a compromised broker
   create the permitted image with attacker-chosen mounts.

**Measured on darwin.** The endpoint set is a property of the Compose CLI, not the kernel, so
it should hold on Linux — but per R22 that is **unverified**, and Task 10 Step 1 must re-measure
on the VPS rather than inherit this table.

## What has drifted since those tasks were written (2026-08-24)

### S3-a — `seen/` is no longer mounted into the executor

The replay-protection set is host-side only. Any Phase B work that touches
`docker-compose.yml`'s mounts must not reintroduce it. `changeset_lib.py:682`'s
`iter_seen_records` still fails **open** on a missing file, and that is safe *only* because the
governed party cannot reach the file. **Anything re-mounting `seen/` must fix that `return`
first** — its docstring says so, and this brief repeats it because a Phase B mount change is
exactly the context where it would be reintroduced.

### S3-b — the governance store's layout and the pre-flight both changed

- `log/` is now `2750` host-owned setgid, per-client logs `0660`.
- `migrate-governance.py --bootstrap-logs` must be run for every registered client.
- The pre-flight gained **two** checks: a registered client with no log is refused, and the
  executor must not have **write** on `log/` by owner, group, or other.

### The interaction that matters most, and is new

Task 11's broker unit already runs the pre-flight as `ExecStartPre` (`:67`) — **this was
already planned; it is not a gap**, contrary to what an earlier reading of this project
suggested. But S3-b changed what that gate refuses, so the unit now carries a boot-blocking
condition that did not exist when it was written:

> **The broker will not start until `--bootstrap-logs` has been run for every registered
> client.**

And the unit has `Restart=on-failure` with `RestartSec=5`, so an unbootstrapped store does not
fail once — it **restart-loops every five seconds**. The deploy sequence must run the bootstrap
*before* the units are enabled, and Task 11's ordering must be checked against that.

### An unspecified fact that S3-b made load-bearing — MEASURED

Task 11's unit specifies `User=hermes-broker` / `Group=hermes-broker` and, deliberately, **not**
the docker group. It does **not** specify the governance store's ownership relative to that
user — and S3-b's new check does **real I/O** (it reads `clients.json`), unlike every sibling
check, which only *simulates* access for a hypothetical uid.

Measured in `hermes-agent-claude:latest`, store `root:10000` `0750`, one registered client with
no log, pre-flight run as two different broker identities:

| broker identity | exit | `cannot stat` problems | names `--bootstrap-logs` |
|---|---|---|---|
| **not** in group `hermes`(10000) | 2 | **4** | 1 (only in the remedy text) |
| in group `hermes`(10000) | 2 | 0 | 2 (the real finding) |

**Both refuse, so it fails safe** — the misconfiguration cannot produce a vacuous pass. But only
one names the real problem. The other buries it under four spurious "cannot stat" errors, which
is the diagnosis an operator would act on at 3am. Task 11's deploy sequence should state the
store's ownership and the broker's group membership explicitly, and a test should pin it.

## Corrections to earlier advice about this phase

Two things recommended on 2026-09-07 were wrong, and are corrected here so the next session
does not act on them:

- **"Phase B's Task 11 should wire the pre-flight as `ExecStartPre`."** It already does, at
  `:67`. Nothing to add.
- **"P6 is coupled to Phase B because the units will use `DynamicUser`."** They will not —
  measured: **zero** occurrences of `DynamicUser` in the plan; both units use a static `User=`.
  `vault-purge.py` is operator-run from a shell (README `:489`), which has a passwd entry. P6 is
  therefore a **latent** hazard that would only bite if someone later switches to `DynamicUser`,
  not a Phase B blocker. Its failure path is also better than the backlog implies: it exports
  first, raises `PostPurgeError`, warns loudly naming the tarball, and exits 3 — no data loss.
  **Treat P6 as its own small wave, not as Phase B scope.**

## How to test it — the parts easy to get wrong

- **`--log-only` is a bypass flag and must not survive into the unit.** The plan already says
  it "must be removed, or made refuse-by-default, before Task 11 installs the unit. A proxy
  with a bypass flag is not a proxy." Verify that in the shipped unit, not in the plan.
- **The proxy needs a positive control, not only refusals.** A proxy that refuses everything
  passes every attacker test and breaks the rail. Task 10 Step 6 already asks for "both a
  refusal and a success"; the success half is the one that gets skipped under time pressure.
  This project has a recorded case (Task 12's seam S4) of blessing a seam nobody could pass.
- **Re-measure the endpoint set on Linux (R22).** Do not inherit the darwin table.
- **CI runs Linux; local darwin runs fewer tests.** `applies()` gates real logic off, and
  `main()` returns 0 before `check()` executes, so platform-gated tests pass **vacuously** on
  darwin. This cost ten days of a silently-red PR on S3-b. **Check CI after every push.**
- **Build container probe stores with in-container `mktemp -d` or a named volume, never a bind
  mount.** Measured 2026-09-06: macOS Docker Desktop does not preserve `chown`'d ownership
  across a bind mount, so a bind-mounted probe reports ownership it did not set — and because
  the executor then appears to own everything, an unsafe layout can read as safe. See design
  §6.4's footnote.
- **A systemd unit is hard to test honestly off the target.** Task 11's existing tests assert
  unit *content* (that the broker is not in the docker group, that `ExecStartPre` names the
  pre-flight). That is the right shape for a repo test, but it proves the file says the right
  thing, **not that the system behaves that way**. Decide deliberately what is proven by test,
  what by a VPS probe, and what stays unproven until first deploy — and write that division
  down rather than letting it be assumed.

## Scope boundaries

- **Not P6** (see above — its own wave).
- **Not truncation.** S3-b closed `unlink` on the audit log and left truncation open: `0660`
  grants write, and write includes truncate, at the same cost. Needs append-only semantics
  (`chattr +a`) or a host-side writer. Its own wave, and arguably one to do *before* a VPS
  deploy rather than after — that is a judgement for the brainstorm, not a decision here.
- **Not a VPS deploy.** Phase B is the precondition for one, not the act of one. Deciding to
  deploy is a separate, explicit decision with its own checklist.

## Constraints that bind this work

- Python 3 **stdlib only** under `infra/hermes-agent/bin/` — the proxy included. It terminates
  a Unix socket and speaks HTTP to another Unix socket, which is `http.client` plus `socket`,
  both stdlib. No new dependency may enter on this path.
- **Fail closed** — an unparseable request body must refuse, never pass through.
- **NEVER run `docker compose config`** — it renders `env_file` secrets in cleartext.
- No client names, customer ids, campaign ids or credential values anywhere; invented slugs only.
- `:ro` project mounts; Hermes never writes a project tree.
- Nothing mutates without an explicit per-action approval. The kill switch is the **file**
  `~/.hermes/governance/control/mutation-enabled` and stays absent.
- `main` is protected — land via PR, and check CI after pushing.

## Where the evidence lives

- `docs/superpowers/plans/2026-08-24-hermes-governed-syscall.md` — **Task 10 at `:2740`,
  Task 11 at `:3027`.** Read these before brainstorming.
- `docs/superpowers/specs/2026-08-19-hermes-mutation-syscall-design.md` §6.4 — deviation D1,
  the measured 10-endpoint table, and §6.4's bind-mount footnote.
- `.superpowers/sdd/2026-08-24-hermes-governed-syscall/progress.md` — rulings R19–R25, the
  Task 12 seam review, Task 13's live gate.
- `docs/evaluations/2026-09-04-s3b-layout-probe.md` — the container-probe method, both
  attempts, and the R22 disclaimer.
- The credential-governance canon entry (2026-08-17) — rule 2 (guard every reachable path) is
  the reason this phase exists; rule 1 (the isolation boundary is the ACCOUNT, and a separate
  OAuth client id buys no revocation isolation) should be re-checked against whatever
  credential topology the VPS ends up with.
