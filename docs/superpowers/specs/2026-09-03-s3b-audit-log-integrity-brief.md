# S3-b — audit-log integrity: planning brief

> Written 2026-09-03 as a handoff. **This is a brief, not a plan.** The next session should
> brainstorm/plan from it. Everything below was measured, not assumed; where something is
> unmeasured it says so.

## The finding

**The executor can delete its own audit log.** That costs **reversibility**, not merely quota:
`apply-changeset.py:194` states the undo path and the caps path both read through
`C.iter_log_records`. So a deleted log destroys the record `--undo` needs.

`docker-compose.yml` mounts `${HERMES_GOVERNANCE_DIR}/log` **rw** into the one-shot executor,
which it must, because `append_log` (`apply-changeset.py:301`) is fsync'd per action and is the
reversibility record. Directory write is what grants `unlink`.

## What is already measured

**P2 — the exploit is real on Linux, not a Docker-Desktop artifact.** Probed in the
`ads-mutator` image with a VPS-like layout (host-owned store, executor reaching `log/` by group)
and a live control requiring that uid 10000 can still append:

| `log/` mode | append | delete |
|---|---|---|
| `0770` (current design) | OK | **succeeded — log destroyed** |
| `0750` (proposed) | OK | **denied** |

So append-but-not-unlink works at the OS level on the deployment platform.

**P3 — the pre-flight currently enforces the insecure layout and forbids the secure one.**
Same store, only the mode differing:

- `0750` (secure) → **refuses**, exit 2, one problem:
  `log: mode 0750 owner 0:10000 gives uid 10000 only r-x — the executor needs read+write+traverse`
- `0770` (insecure, log deletable) → **passes**, exit 0

The gate demands **write on the directory**, which is exactly what grants `unlink`. What the
executor actually needs is traverse+read on the directory and write on the **file**.

**The second blocker, measured during the Phase-A fix wave:** making a missing log fail-closed
breaks the **first apply for every client**, not just fixtures — `day_counts` reads the log
before any log exists. Measured at **30 suite tests red, including the plain happy path**.

## Why it is three coupled changes, not one

Land these **together** or the rail breaks:

1. **Pre-flight inversion** — `preflight-governance-access.py`: `log/` requires traverse+read on
   the directory and write on `<slug>.jsonl`, not write on the directory. Note `READ_WRITE_DIRS`
   is now `("log",)` — S3-a already removed `"seen"`.
2. **Registration bootstrap** — every registered client must be guaranteed a pre-created log, or
   "missing log" stays ambiguous between *never used* and *deleted*. **There is no programmatic
   registration hook**: `clients.json` is hand-edited or migrated. So bootstrap has to ride the
   existing `migrate-governance.py` / `migrate_governance_shim.py` (host-side, operator-run,
   dry-run by default).
3. **Deploy permissions** — `log/` `0750` host-owned, per-client files `0660` group-writable.
   Only then can a missing log for a *registered* client become fail-closed.

Applying (3) without (1) reproduces R19's over-checking failure a fourth time: the pre-flight
refuses the correct layout and blocks broker startup.

## How to test it — this is the part that is easy to get wrong

**`preflight-governance-access.py` is a deliberate no-op off Linux** (`applies()` returns False
unless `sys.platform` startswith `linux`). A clean run on macOS **proves nothing** — I reported
a no-op as a pass once in this project and had to correct it.

The `ads-mutator` image *is* Linux, ships Python 3.13, and runs as **uid 10000** — the real
executor identity. Test there:

```
docker run --rm --user 0:0 -v "$PWD":/work:ro --entrypoint sh hermes-agent-claude -c '...'
```

Build the store as root, `chown`/`chgrp` to the target layout, then `su hermes -s /bin/sh -c` to
act as the executor. **Ancestor directories must be traversable** or append fails for an
irrelevant reason — that invalidated two of my three probe attempts, and only the
append-must-succeed control caught it.

Always pair the delete probe with an **append control**. A layout where uid 10000 can neither
append nor delete looks like a fix and is a broken fixture.

## Constraints that bind this work

- Python 3 **stdlib only** under `infra/hermes-agent/bin/`.
- **Fail closed** — an unreadable or missing limit must never read as permissive.
- No client names, customer ids, campaign ids or credential values anywhere. Invented slugs only.
- Exactly one trailing `unittest.main()` per test file.
- Baseline: `run-bin-tests.sh` **25/25**, `node scripts/run-all-tests.js` **22/22**.
- Mutation proofs are **green→red on a named test**, with the sorted failing-set difference
  reported; `ast.parse` the mutant before believing a silent result.
- `main` is protected — land via PR.

## Scope boundaries

- **Not** Phase B. That is the socket proxy and systemd units, is unbuilt, and is the real
  precondition for any VPS deploy (broker's Docker access is host root there). Separate plan.
- **Not** P6 (`vault-purge`'s `getpass.getuser()` after an irreversible delete — a systemd
  `DynamicUser` hazard). Separate, smaller.
- The VPS behaviour of the *deployed* layout remains **unmeasured** until Phase B; per R22,
  nothing measured on darwin may be claimed of the VPS.

## Where the evidence lives

- `docs/evaluations/2026-08-30-hermes-phase-a-deployment-readiness.md` — findings P2, P3
- `.superpowers/sdd/2026-08-24-hermes-governed-syscall/progress.md` — rulings R19–R25, the
  Task 12 seam review, the fix wave's measured blockers
- `.superpowers/sdd/2026-09-02-hermes-syscall-approval-handoff/HANDOFF.md` — the approval-handoff
  branch's rulings and open items
- Spec `docs/superpowers/specs/2026-08-19-hermes-mutation-syscall-design.md` §7, §9 (corrected
  2026-09-03), §6.4 (deviation D1)
