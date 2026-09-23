# F14 — The executor attests its own exit; anything unattested fails closed (design)

**Status:** approved 2026-09-23; implemented in PR #46.
**Finding:** F14 in `docs/superpowers/specs/2026-09-21-vps-first-bring-up-findings.md`
(first recorded in the F9 spec, `2026-09-22-f9-bind-paths-and-proxy-allow-list-design.md` §3.7, §5).
**Gates:** the kill switch. Not the rehearsal (the kill switch is absent there, so nothing can mutate).

**Mutation stays disabled throughout. The kill switch is ABSENT and nothing here creates it.**

## 1. Problem

The broker reads the wrapper's exit status as a promise (`hermes-broker.py:516`,
`CLASSIFICATION_BY_RC`; syscall spec `2026-08-19-hermes-mutation-syscall-design.md` §12):
`0` applied · `1` `refused_usage` "nothing was mutated" · `2` `refused_preflight` "nothing was
mutated" · `3` `failed_after_mutation` · anything else `failed_unknown_exit` "possibly modified".

Status 1 reaches the broker from four places. Only three are safe:

| Source of 1 | Reached Google? |
|---|---|
| The wrapper's own pre-Compose checks (`--client`, `.env.gaw`, role, `hostenv.sh`'s R4 guard) | No |
| The executor's usage paths (`--request` invalid, a crash before `apply()`) | No — `apply()` catches every `Exception` once the live loop can have started (a `BaseException` such as `KeyboardInterrupt` exits 130, already `failed_unknown_exit`) |
| Compose failing to create (proxy refusal M5a, unreadable `.env` M4 — measured, F9 §2) | No |
| Compose losing its connection **after** the container started | **Unknown.** The container runs independently of the Compose client and can keep mutating |

The last row is F14. No marker the executor writes can close it, because when Compose returns
the container may still be running. Only **positive evidence that the executor itself chose the
exit** can.

Three further holes on the same seam, found while designing:

- **2 and 3 are trusted unattested.** Were Compose or Docker ever to return 2 for its own
  reasons, the broker would promise "nothing was mutated". Unmeasured either way.
- **`set -e` after Compose.** `run-ads-mutate.sh` still runs `cat "$tmp_out"` under `set -e`
  after the executor returned. A failing `cat` exits the script with `cat`'s status (1), which
  the broker reads as "nothing was mutated" about a run that may have applied.
- **The Hermes client maps unknown broker codes to "refused".** `hermes-syscall.py:29`,
  `_EXIT_BY_CODE = {0: EXIT_OK, 2: EXIT_REFUSED, 3: EXIT_FAILED_AFTER_MUTATION}`, default
  `EXIT_REFUSED`. A broker `failed_unknown_exit` (e.g. rc 137) already reaches the agent with the
  exit status that means refused, while its detail text says "possibly modified".

## 2. Decisions

- **Fail closed** (operator decision, 2026-09-23). When the executor's own exit cannot be
  verified, the result is "possibly modified; reconcile from the audit log". Pre-start Compose
  failures (proxy refusal, `.env`) are **accepted false alarms**: rare after bring-up, cheap to
  reconcile (the audit log shows nothing), and a duplicate apply is already impossible because the
  approval was reserved before the executor ran.
- **Approach A**: the executor attests its exit on a nonce-bound line; the **wrapper** verifies
  it. Chosen over broker-side verification (leaves manual wrapper runs unprotected and splits the
  contract) and over a blanket "Compose 1 → 4" remap (leaves 2/3 unattested and turns honest
  executor usage errors into false alarms).
- **A new wrapper status, 4 = unverified.** 0/1/2/3 keep their meanings. 1 remains an honest
  "nothing mutated": after this change it can only be a pre-Compose wrapper refusal or an
  executor-attested usage exit.

## 3. Design

### 3.1 Executor — `bin/apply-changeset.py`

**Principle: the executor attests only exits it chose. It never attests a crash.**

- `if __name__ == "__main__":` calls a new `_attested_exit(main)` instead of `sys.exit(main())`.
- `main()` returns an int, or raises `SystemExit` whose `code` is an int or `None` (→ 0): print
  `HERMES-EXIT <nonce> <rc>` as the **last** thing the process writes, then exit with `rc`.
  Covers 0, `main()`'s `return 1`, argparse's `SystemExit(2)`, `_refuse`'s 2, `apply()`'s 3.
  Any int is attested as-is; the wrapper rejects anything outside 0–3.
- `SystemExit` with a non-int, non-`None` code, any other exception, and `KeyboardInterrupt`:
  **no line**, and the process exits as it does today (the exception propagates). Measured on
  darwin, Python 3: an uncaught exception exits **1**, `KeyboardInterrupt` exits **130**. Today an
  uncaught exception can only arise before the live loop (`apply()` catches `Exception` once it
  can have landed), so its 1 is currently true; the rule is defence in depth — a future path
  that crashes after a mutation must not inherit "usage, nothing mutated". Unattested, it becomes
  4 (a false alarm at worst).
- A signal or OOM kill never reaches Python: no line.
- The line is printed only when `HERMES_EXIT_NONCE` fully matches `^[0-9a-f]{32}$`. Absent or
  malformed: nothing is printed (a manual run inside the container behaves as today; through the
  wrapper, that fails closed).
- Order: flush stderr, write the line to stdout, flush stdout.
- `HERMES_EXIT_NONCE` must **never** be in `_RUNTIME_ENV_KEYS` (`apply-changeset.py:50`).
  `_child_env()` is an allow-list, which keeps the nonce out of the mutator subprocess's
  environment so text the mutator echoes (its stderr, via `_scrub(err)` into `_refuse`
  messages) cannot carry it and forge the line. The mutator runs as the same user in the
  same container and could still read the parent's `/proc` environ directly — the
  allow-list does not stop that — but it already holds the write credential, so that would
  not be a new capability. A test pins the allow-list's absence of the nonce.
- `apply()`, `build_plan()` and the meaning of every existing status are unchanged.

### 3.2 Wrapper — `run-ads-mutate.sh`

**Before Compose (every exit here is honest: nothing has run):**

- `nonce=$(od -An -N16 -tx1 /dev/urandom | tr -d ' \n')`; require exactly 32 characters, all
  `[0-9a-f]` (POSIX `case` + `${#nonce}`). On failure: `exit 1`, like the `.env.gaw` checks.
- `export HERMES_EXIT_NONCE="$nonce"`; add `-e HERMES_EXIT_NONCE` to the `docker compose run`
  line.

**After Compose — one exit decision, nothing else may exit:**

- `set +e` immediately after `rc` is captured. No later command (`cat`, `grep`, persist) can
  end the script with its own status.
- `n=$(grep -Fxc "HERMES-EXIT $nonce $rc" "$tmp_out")`. **Verified** iff `rc` is one of
  `0|1|2|3` **and** `n` is exactly `1`. Then `final=$rc`.
- Otherwise `final=4`, and a stderr banner: `EXECUTOR EXIT NOT VERIFIED (compose rc=$rc) — the
  executor may have run; treat the account as possibly modified; reconcile from the governance
  audit log`.
- Every failure of the check itself lands on 4: unreadable output, empty count, wrong nonce, a
  line disagreeing with `rc`, two matching lines.
- The persist step and its banner are unchanged except that they report `$final`; the script
  ends `exit "$final"`.
- The `HERMES-EXIT` line stays in the output (the nonce is single-use and worthless after the
  run; `persist-run-record.py` parses only `HERMES-RESULT-JSON`).
- The header comment documents status 4.

### 3.3 Broker — `bin/hermes-broker.py`

- `CLASSIFICATION_BY_RC[4] = ("failed_unverified_exit", "failed")`.
- `DETAIL_BY_CLASSIFICATION["failed_unverified_exit"]` = "the executor's exit could not be
  verified (e.g. Compose failed, possibly after the container started); treat the account as
  possibly modified and reconcile from the audit log".
- The exit-semantics comment above the map gains the line for 4. `refused_usage` is unchanged.
  `UNKNOWN_RC` stays as a backstop; in practice the wrapper now turns any unrecognised status into 4.

### 3.4 Hermes client — `bin/hermes-syscall.py`

- `_EXIT_BY_CODE[4] = EXIT_FAILED_AFTER_MUTATION`: an unverified exit reaches the agent as
  "possibly modified", never as "refused".
- A comment states that the broker's `exit_code` 4 and the client's own `EXIT_PENDING = 4` are
  different namespaces; the map is the translation.

## 4. Tests

Every new assertion is shown failing first. Controls are built in a **scratchpad copy** or a
fixture, **never by editing a tracked file** (a background scanner fires on modified
security-relevant lines).

**`apply-changeset.test.py`**
1. Each chosen exit — 0, `return 1`, argparse 2, `_refuse` 2, 3 — prints exactly one correct
   line, the last line on stdout. Control: a variant that prints the line before `main()` completes.
2. Uncaught exception and `KeyboardInterrupt` print no line. Control: a bare `finally:` variant.
3. Absent / malformed nonce prints no line.
4. `_child_env()` never contains `HERMES_EXIT_NONCE`, even when set. Control: a scratchpad copy
   with the key added to `_RUNTIME_ENV_KEYS`.

**`run-ads-mutate.test.py`** (fake `docker` on `PATH`; control for each: a scratchpad wrapper
that trusts `rc` as today)
1. rc 0/1/2/3 with a matching line → same status.
2. rc 2, no line → 4.
3. rc 1, no line (Compose's own failure — F14) → 4.
4. Matching shape, **wrong nonce** (forged line) → 4.
5. rc 0 with a line saying 2 → 4.
6. Two matching lines → 4.
7. rc 137, no line → 4.
8. A failing `cat` on `PATH` after Compose → still the verified status, not 1. Control: `set -e`
   left in force.
9. The fake `docker` receives `-e HERMES_EXIT_NONCE`; the value is 32 hex characters and differs
   across two runs.

**`hermes-broker.test.py`**
1. A runner returning 4 → `failed_unverified_exit` / `failed` / exit_code 4 / the new detail.
   The map-pinning test (`:811`) is updated.
2. Wrapper→broker: fake `docker` returns 1 with no line → the broker's result is
   `failed_unverified_exit`. F14 end to end on the laptop.

**`hermes-syscall.test.py`**
1. A result with `exit_code: 4` → `EXIT_FAILED_AFTER_MUTATION`. Control: today's map →
   `EXIT_REFUSED`.

**Linux CI — `deploy/bind-agreement-integration.test.py`** (job `Bind agreement (root, Linux,
real proxy)`, a required check; **no job is renamed**)
- The broker-path test keeps `rc == 2` and "mutation is disabled", and additionally asserts
  exactly one `HERMES-EXIT <32 hex> 2` line: the nonce crossed `docker compose run -e` and the
  real proxy, and the real executor attested.
- Both firing controls (altered allow-bind; wrong ads-repo path) change from
  `assertNotEqual(rc, 2)` to **`assertEqual(rc, 4)`** plus the NOT VERIFIED banner. That is the
  F14 case **measured on real Linux**: proxy refuses at create → Compose 1 → wrapper 4.
- Executed counts are read on the PR and on the merge commit: bind-agreement `executed 6,
  skipped 0`; layout-integration `executed 30, skipped 0`; hermes bin and node suites all pass.

**Runbook sync — no change.** `proxy-policy-sync.test.py::TestRunbookMatchesTheWrapper`
compares only Compose-level flags and deliberately ignores `-e` flags, so `-e
HERMES_EXIT_NONCE` does not drift it, and BRING-UP Phase 6's pasted invocation needs no edit
(without a nonce the executor prints no line; Phase 6 reads the executor's status directly and
still expects `rc=2`).

## 5. Records

- **Findings record:** F14 → fixed, pointing to the PR; the CI run id and executed counts are
  filled **only from a real run**. The mid-run connection-loss case stays marked
  **unmeasured** — the design does not depend on it, since anything unattested fails closed.
- **BRING-UP**, rehearsal gate: "Still required before the kill switch can be created: F14 …"
  loses F14; the §6 hardening gates remain.
- **Syscall spec §12** (`2026-08-19-hermes-mutation-syscall-design.md`): the wrapper's status 4
  and the attestation rule are added.
- **Brain:** a candidate entry via `brain-capture`, left for the operator's
  `brain-promote --approve`.

## 6. Out of scope

- The read-only wrappers (`run-ads-report.sh`, `run-ads-audit.sh`, …): nothing there can mutate.
- A garbage `exit_code` planted in the spool still maps to `EXIT_REFUSED` in the syscall client —
  the agent misleading itself about its own request.
- `UMask=0077` and the rest of the §6 hardening.
- Measuring an actual mid-run connection loss.

## 7. Accepted risks

- **False alarms** on pre-start Compose failures (operator decision, §2).
- **The nonce is visible to same-UID host processes during a run.** It defends against forged
  lines in the executor's output, not against the host, which already holds the credential.

## 8. Order of work

1. Executor attestation + its tests (§3.1).
2. Wrapper verification, `set +e`, status 4 + its tests (§3.2).
3. Broker and syscall mappings + their tests, including wrapper→broker (§3.3, §3.4).
4. Linux CI assertions (§4) — green on the PR with counts read.
5. Records (§5); after merge, CI on the merge commit with counts read.
