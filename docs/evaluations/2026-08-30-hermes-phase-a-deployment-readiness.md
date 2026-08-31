# Hermes Phase A — deployment readiness assessment

**Date:** 2026-08-30 · **Branch:** `feat/hermes-governed-syscall` · **Scope:** Plan 2 Phase A
(the governed mutation syscall). Written before the Task 13 live gate, at the operator's
request, to surface anything that would fail on the Hostinger VPS while it is still cheap.

---

## Bottom line

**Phase A is ready for the Task 13 local dormant pilot. It is NOT ready to deploy to the
VPS, and Task 13 does not make it so** — Task 13 is a local, zero-spend gate, not a
deployment. Two independent things block a VPS go-live, one of them by design.

The most valuable result of this pass is methodological: **this machine could not see the
problems that matter.** macOS is not the deployment platform, and four of the six findings
below were invisible until the same code was run on Linux, in the executor's own image, as
the executor's own uid.

---

## What was verified, and how

Everything below was measured, not reasoned. Where an absence is claimed, a positive control
was run to prove the technique would have detected a presence.

| Property | Result |
|---|---|
| Hermes bin suites, darwin | 24/24 |
| Hermes bin suites, Linux as uid 10000 (executor identity) | 24/24 |
| Hermes bin suites, Linux as a non-10000 uid (CI runner) | 24/24 |
| Node suites, darwin | 22/22 |
| Node suites, clean checkout on node 24 / Linux (real CI condition) | 22/22 |
| CI static scan, run locally | PASS — 0 unmatched, 0 stale |
| Gateway starts on the modified compose | Yes |
| `HERMES_GOVERNANCE_DIR` masked in the running gateway | Empty (control: API key still injected) |
| Governance store reachable from the gateway | Unreachable (control: `/opt/data` present) |
| Spool reachable + writable from the gateway | Yes |
| Client slug / customer id in tracked files or branch diffs | 0 / 0 (both with live controls) |
| Kill switch at rest | Absent, by file test |

---

## Findings

### P1 — the fix wave's own new suite was darwin-only *(fixed, `cb42774`)*

Running the bin suite inside the ads-mutator image gave **23 passed, 1 FAILED** —
`run-ads-mutate.test.py`, 5 of its 7 tests — while darwin reported 24/24.

The wrapper runs the pre-flight first (`run-ads-mutate.sh:34`), and that gate is a deliberate
no-op off Linux. The fixture built a governance store containing `registry/` alone. On darwin
the gate stayed silent and the tests ran; on Linux it correctly refused the incomplete store
at exit 2, so the wrapper never reached the logic under test.

**Consequence:** S1-M2 — the `|| true` that was swallowing **attack detections** — was
unverified on the platform that ships. It is now verified on both.

### P2 — the S3 audit-log deletion is real on Linux *(open, R22 answered)*

Previously unmeasured; the exploit had only been demonstrated on Docker Desktop for macOS,
where bind-mount ownership remapping made it ambiguous. Probed on Linux with a VPS-like
layout and a live control (uid 10000 must be able to append, or the probe is void):

- `log/` group-writable (**current design**) → uid 10000 **deleted** the audit log.
- `log/` not group-writable → append still works, **delete denied**.

So the reversibility record is deletable by the governed party on the VPS as currently
designed, and append-but-not-unlink is sound at the OS level.

*Two earlier attempts at this probe were invalid and the control caught both. Neither was
reported as a result.*

### P3 — the pre-flight enforces the insecure layout and forbids the fix *(open)*

Measured on Linux, same store, only `log/`'s mode differing:

- Secure layout (`log/ 0750`) → pre-flight **refuses**, exit 2, one problem:
  `log: mode 0750 owner 0:10000 gives uid 10000 only r-x — the executor needs read+write+traverse`
- Insecure layout (`log/ 0770`, log deletable) → pre-flight **passes**, exit 0

The gate demands **write on the directory**, and directory write is precisely what grants
`unlink`. What the executor actually needs is traverse+read on the directory and write on the
file. This turns the S3-b blocker from "the pre-flight refuses it" into a precise, actionable
change.

### P4 — CI ran no tests at all *(fixed, `e539edd`)*

Three jobs — skill frontmatter, security gate, static scan — and not one ran a test. All 46
suites, including this branch's entire mutation rail, could go red and a PR would still merge
green. "CI is green" meant the three gates passed, nothing more. A `tests` job now runs both
runners; neither discovers the other, since `run-all-tests.js` is node-only by design.

### P5 — three node tests would have turned that new job red *(fixed, `d78e160`)*

The CI job was proven before shipping. On a clean checkout under node 24 on Linux: 21/22,
exit 1. `evals/` is gitignored **but 41 `evals.json` files are force-added**, so
`evals/agent-eval/` exists in a clean checkout while its generated `iteration-N` directories
never do — the guards checked the parent, passed, then failed inside. Fixed by guarding on
what the tests actually require, verified in both directions.

### P6 — `vault-purge` can fail after an irreversible delete *(open, Phase B hazard)*

`vault-purge.py:42` calls `getpass.getuser()`, which raises when the process has no passwd
entry and no `USER`/`LOGNAME`. It runs *after* the vault has been exported and deleted, so the
failure mode is "irreversible delete succeeded, bookkeeping failed, exit 3". CI is unaffected
(runners have a passwd entry), but **systemd units commonly run `DynamicUser=yes` with a
minimal environment, and Phase B is systemd units.** Out of Plan 2's scope; flagged for
Phase B.

---

## What blocks a VPS deployment

1. **Phase B is not built.** Tasks 10–11 — the body-inspecting Docker socket proxy and the
   systemd units — are deferred by design. On a VPS the broker's Docker access is **host
   root**. Phase A must not be described as "deployed" without them.
2. **S3-b is open** (P2 + P3). The executor can delete its own audit log, which costs
   *reversibility*, not merely quota — `iter_log_records` serves both `--undo` and the daily
   caps. The remediation is now fully characterised: invert the pre-flight's `log/`
   requirement, pre-create per-client log files, set `log/` to `0750` at deploy. The honest
   remaining gap is bootstrap: there is no programmatic client-registration hook, since
   `clients.json` is hand-edited.

**Consequence for Task 13:** its `--undo` step must be read as *unproven against a hostile
executor*. It demonstrates that undo works, not that undo cannot be sabotaged.

---

## Recommendation

Proceed with Task 13 as a local dormant pilot. Land S3-b as its own wave — it is now a
measured, bounded change rather than a design question — and treat Phase B as the real
precondition for any VPS deploy.
