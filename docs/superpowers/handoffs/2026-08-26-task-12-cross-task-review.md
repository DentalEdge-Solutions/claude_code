# Session prompt — Hermes AIOS, Plan 2: Task 12 (cross-task review), then 13 and 14

Paste this whole file as the opening message of a fresh session.

---

We're continuing the Hermes AIOS project (Nous Hermes Agent as a Dockerized control plane
operating registered Claude Code projects). Plan 1 is merged. **Plan 2's Phase A is COMPLETE
and unreviewed as a whole.** This session runs the cross-task review, then the live gate, then
docs and the PR.

## Read these first

- `docs/superpowers/plans/2026-08-24-hermes-governed-syscall.md` — Plan 2. **It has been
  corrected in place several times during execution; the corrections are dated inline. Trust
  the code over the plan where they disagree.**
- `.superpowers/sdd/2026-08-24-hermes-governed-syscall/progress.md` — the execution ledger.
  ~20 numbered rulings, every parked minor, and every measurement. **This is the authoritative
  record. Read it before touching anything.**
- `docs/superpowers/specs/2026-08-19-hermes-mutation-syscall-design.md` — the binding spec.
  §7 was corrected once already; §6.5's claim that the broker persists `result.json` /
  `timeline.md` is FALSE (the wrapper does it) and Task 14 must fix it.
- `docs/evaluations/2026-08-24-upstream-hermes-release-check.md` — why we are not upgrading
  the gateway. Our pinned image already is the release someone will suggest adopting.
- `infra/hermes-agent/README.md` — governance store, mutation tier, credential access levels.

## STATE — measured, not asserted

Branch `feat/hermes-governed-syscall`, tip **`4d61220`**, base `b9cb1e2` (main).
Working tree has pre-existing dirt from before this work (`.project-brain/log.md`, two deleted
candidates, two `evals/*.json`) — **not yours, do not commit it.**

- `infra/hermes-agent/bin/run-bin-tests.sh` → **23/23 suites**
- `node scripts/run-all-tests.js` → 21/21 on this branch
- **CI is GREEN ON `main`** — PR #18 merged as `4e15142`; all three jobs pass on the real
  runner. First green pipeline since at least `c3759b0`. The gate now protects every PR.
- **This branch is BEHIND `main`** by the two CI commits, deliberately — they were dropped from
  here so the Hermes PR reviews as pure Hermes work, and they now arrive via main instead.
  **Merge `origin/main` into this branch before opening the Hermes PR**, so CI runs against the
  restored pipeline. The two sets touch disjoint files (`.github/`, `scripts/`, `skills/` vs
  `infra/hermes-agent/`), so expect no conflicts — verify rather than assume.
- The branch is pushed: `origin/feat/hermes-governed-syscall` at `c937724`. No PR yet, by design
  — the PR belongs after Task 12 and Task 13 so its body can carry their findings.

**Phase A is 9/9 complete**, every task individually reviewed with a fix loop:

| Task | What | Commits |
|---|---|---|
| T1 | `spool_lib.py` — closed schema, hostile-input reads | `a92fc3c..b68f9ee` |
| T2 | `hermes-syscall.py` — identifier-only in-container client | `..4cc3423` |
| T3 | fail-closed per-client spool quotas | `..ad5dace` |
| T4 | governance-store replay seen-set + single-use approval reservation | `..60898d1` |
| T5 | broker refusal core | `..bb86671` |
| T6 | broker execution path | `..bf3671b` |
| T7 | broker CLI `--once`/`--watch` + test-runner timeout hardening | `..7395e82` |
| R19 | pre-flight file-level check (session Task 2, gates any VPS apply) | `..53f612b` |
| T8 | parked residuals (a) hardlinks (b) dirfd chain (c) mkdir ordering | `..f67931c` |
| T9 | `--expect-sha256` required by default | `..4bcf1d0` |
| — | redaction of two pre-existing tracked files | `4d61220` |

**Mutation is DISABLED at rest.** No kill switch at `~/.hermes/governance/control/`. Leave it
that way except where Task 13 demands otherwise, and turn it off again after.

---

## TASK 12 — the cross-task security review (do this first, it is the point of the session)

Plan 1's CRITICAL was invisible to eleven per-task reviews because it lived in a **seam**. Plan 2
has the same shape, and this session has already proven the risk is real twice:

- R19's pre-flight false-refused every store that had ever reserved an approval, because T4 added
  an `.approval.lock` sidecar that R19's requirement list (written from memory) predated.
- My own ruling that a hardlink TOCTOU was "not exploitable" was **wrong** — I verified it on the
  `O_APPEND` path and generalised to the `O_TRUNC` path, where the target is truncated before the
  check fires.

**Dispatch this to a reviewer that implemented none of it, on the most capable model.** Give it
the seam list, not the file list. Require a finding or an explicit "clean" per seam, each backed
by a probe rather than an argument.

| # | Seam | Probe it, don't argue it |
|---|---|---|
| S1 | broker → `persist_run_record_shim` | The broker runs persist as the governance store's OWNER, into `data/vaults` which the agent writes. Plant a hardlink, a symlink, and a fifo at `timeline.md` and at the `.tmp` result path; run a real drain. Kill switch still absent? Audit-log byte count unchanged? |
| S2 | spool → broker | Can the agent make the broker read outside `requests/`? Symlink, `..` in the filename, hardlink to the audit log, 1 GB file, fifo, a file that grows mid-read, a uuid-shaped **directory** (this one bricked the broker before it was fixed). |
| S3 | seen-set → quotas | Delete `governance/seen/<slug>.jsonl` from the host between drains. Does a used `request_id` become replayable? Does the daily quota reset? |
| S4 | reservation → executor guard 5 | Kill the broker between `reserve_approval` and the subprocess. Is the approval dead afterwards? |
| S5 | pre-flight → real store | Build a store that has processed several approvals (locks, logs, seen entries, a stale `.tmp`) and confirm the pre-flight reports **zero** problems. Over-checking blocks the broker from starting; it is as harmful as under-checking. |
| S6 | `hermes-syscall` → broker | Do client and broker agree on the schema in both directions? Boundary-value every field. |
| S7 | result file → agent | Grep a real dry-run result for the resolved customer id and for anything client-identifying. **Pair with a control**: grep for a string you know IS present, so an empty grep is evidence. |
| S8 | compose masks → spool | `data/` is mounted rw and now holds the spool. Re-run the Plan-1 credential probe: **5 → 0 readable, with a normal repo file readable as the control.** |

Then re-run the **Plan 1** guarantees, not only the new ones:
`./audit-credential-access.sh --all --customer <digits>` → exit 0. In-container: every `.env.*`
unreadable **with a known-readable control**; governance store unreachable **with a reachable
control**; spool reachable and writable; seen-set NOT reachable.

Record every finding in the ledger **before** fixing anything.

## TASK 13 — the live verification gate (operator-run, dormant pilot ONLY)

Spec §13. Do not start until Task 12's findings are resolved or parked with rulings. Zero spend.
Resolve the client via `vault_lib.resolve('<slug>')` — **never hardcode**. `.env.ga` pins no
customer id by design, so every read passes `--customer` explicitly.

The full ordered checklist is in the plan's Task 13. The load-bearing ones:

- Credential roles unchanged before and after (`audit-credential-access.sh` measures this — do
  not re-derive credential facts by hand).
- P1 by probe: credential files unreadable in-container, with a readable control.
- F7 closed for the write path: poll `/proc/*/environ` during a live apply, find nothing, **with
  the F7 marker probe re-run as a positive control proving the technique still works**. Compare
  by sha12 only; never print a credential value.
- Forged approval at the OLD vault location → not honoured.
- Kill switch created from inside the container at the old path → no effect.
- Replay refused; then **delete the whole spool from inside the container** and confirm still
  refused.
- Full happy path, then `run-ads-mutate.sh --undo` host-side, then confirm the account is
  byte-identical.
- No syscall path to `--undo`: the client has no such subcommand and a hand-written `"op":"undo"`
  request is `refused_request`.
- Kill switch removed. Confirm absent with a **file test**, not `ls | grep -c`.

## TASK 14 — docs, spec amendment, PR

- README: spool layout, `hermes-syscall apply|result` with **exit 4 = pending, not refused**,
  broker `--once`/`--watch`, the two quotas, and the deploy sequence.
- **Correct spec §6.5** — it says the broker persists `result.json`/`timeline.md`; the wrapper
  does. Grep the README for the same claim.
- Record deviation **D1** in §6.4 (the socket proxy's allow-list is wider than `create`/`start`,
  measured not guessed) the way §7 was corrected — keep the original text, mark the correction.
- Document R6: on spool overflow the broker refuses the whole drain, writes no per-request
  results, and does **not** discard the files — a flooded spool stalls that client until an
  operator clears it.
- Open the PR. **`main` is protected in both repos.** The PR body must carry every parked minor
  from the ledger — Plan 1's parked findings survived only because they reached a PR body.

## Phase B is DEFERRED — do not start it here

Tasks 10–11 (the body-inspecting Docker socket proxy and the systemd units) are the
highest-risk remaining code and are already gated behind VPS deploy. They should be their own
plan against the now-green pipeline. **Phase A must not be described as "deployed" without them**,
because on a VPS the broker's Docker access is host root.

---

## The final fix wave — parked minors, all in the ledger

Batch these into ONE fix dispatch, not one per finding. Highest value first:

1. **`persist_run_record_shim.py` import guard checks only `os.open`/`os.rename`**, but
   `os.mkdir` and `os.unlink` became load-bearing `dir_fd` calls in T8, and the adjacent comment
   claims all four were "measured". Two-line fix. (11th overclaim instance.)
2. **`changeset_lib.py:482`** — `# MUST precede the lock` directly contradicts the corrected
   docstring above it, which says the ordering is not load-bearing.
3. **R8** — `test_quotas_are_not_absurdly_large` is a change-detector with 100/500 ceilings;
   `registry-invariants.test.py`'s own docstring says the suite must not become one. Loosen to an
   unambiguously absurd bound.
4. `governance_lib.approval_lock_path` has **no tests**, unlike every sibling path helper. Its
   behaviour is correct (I probed it) — the gap is coverage.
5. R16 — the hedged timeout detail string has no test. A purpose-built fake runner raising
   `subprocess.TimeoutExpired` would cover it; "RecordingRunner can't" was too strong.
6. `read_spool_quotas`'s validate loop duplicates `read_mutate_execute`'s almost verbatim.
7. `_open_regular_ro` re-raises a raw `OSError` if `os.fstat` fails, contradicting its docstring.
8. `hermes-syscall` maps `OSError` from `submit()` to the **usage** exit code.
9. Quarantined spool entries and `.approval.lock` sidecars are never pruned — unbounded disk on a
   sustained flood. Needs operator tooling, not a code fix.
10. CI's new scan job surfaces only BLOCK; the old one also printed FLAG as non-failing signal.
    Zero skills FLAG today, so it is latent.

---

## HARD RULES

- No client names, account ids, campaign ids, metrics, or drafts in git, the brain, specs, plans,
  tests, reports, or telemetry. Redact as `<slug-1>` / `<digits>`. **A scan on 2026-08-26 found
  and fixed two pre-existing violations; re-run `git grep` before the PR.**
- NEVER print a credential value or write one into a tracked file. Compare by sha12:
  `printf '%s' "$v" | shasum | cut -c1-12`. **A sha12 is a durable identifier of a live
  credential — keep it out of tracked files too.** `.env.*.example` are TRACKED.
- **NEVER run `docker compose config`** — it renders `env_file` secrets in CLEARTEXT.
- `:ro` project mounts; Hermes never writes a project tree.
- Credentials in gitignored `.env.<x>`, parsed as DATA never sourced, injected per-invocation.
- Nothing mutates without an explicit per-action approval. Leave the kill switch OFF.
- `main` is protected in both repos — open a PR.
- Do not install directly from reference repositories; external skills/agents pass
  scout → audit → adapt → eval.
- **Only `brain-promote.js --approve` may modify `.project-brain/canon/`.** A PreToolUse hook
  fires on any Bash command merely *mentioning* that path — use a non-Bash tool to read it, and
  do not defeat the guard. Promote MOVES the candidate and the destination filename is the
  candidate's BASENAME: to amend an existing canon file, give the candidate that exact basename
  and pass `--force`, or you create a rival file on the same topic. (Done successfully on
  2026-08-26 — see commit `4d61220` for the pattern.)

## MEASUREMENT TRAPS

The originals still apply. These were **earned in this plan's execution** and are new:

- **A mutation proof must move a suite test from GREEN to RED.** An already-failing test cannot
  be killed, so a proof run against a red baseline proves nothing. Capture the SORTED failing-test
  set before and after and report the DIFFERENCE. This caught a row reported as "KILLED via
  standalone probe" where the suite in fact caught nothing.
- **"KILLED via standalone probe" is a weaker claim than "a suite test went red."** A probe shows
  the code works now; only green-to-red shows the suite will catch a regression.
- **A broken mutation script prints nothing, which looks exactly like a test that did not fail.**
  Run `python3 -c "import ast,io; ast.parse(io.open(F).read())"` after every mutation before
  believing any result. I fooled myself with a bad regex this way.
- **`git checkout --` is only a safe revert AFTER the implementation is committed.** An
  implementer wiped an entire function reverting a mutation against uncommitted work.
- **Verify each path; never generalise from one to another.** I proved a hardlink check was
  non-load-bearing on the `O_APPEND` path and wrongly concluded the same for `O_TRUNC`, where the
  file is destroyed before the check fires.
- **A Critical is not closed until the ORIGINAL exploit fails.** A new passing test is not
  sufficient evidence; replay the actual attack.
- **Over-checking is as harmful as under-checking** for any gate that blocks startup. An
  allowlist of what must be accessible fails safer than a denylist of what to skip.
- **Source-text assertions are not tests.** `inspect.getsource(...)` containing `"dir_fd"` passed
  through the exact regression it named, because the string was present in a comment.
- **Ten of this plan's defects were in the PLAN, not the implementations** — wrong causal claims
  in mutation rows, stale briefs, a fixture that tripped its own quota, a control whose filename
  the validator rejected. Treat plan text as the least reliable input in the room.
- **SUBAGENTS DIE MID-TASK** — three times in this plan (session limits). Never trust an agent's
  last words. Measure `git log`, `git status`, and the index before resuming, and tell the
  resumed agent exactly what you measured. If it died with uncommitted work, commit it yourself
  under an honest WIP message before resuming, or it cannot safely revert a mutation.
- Under `set -eu`, a bare `rc=$?` is never reached — but `run-bin-tests.sh` uses `set -u` ONLY,
  so its bare `rc=$?` is correct. Check which before "fixing" it.
- `cmd | tail` takes its exit status from `tail`. This reported a failing validator as exit 0
  during the CI diagnosis.
- An empty grep is not evidence of absence until the same search finds a known-present case.
  A digit-scan for account ids returned nothing here **because the pattern was broken**, and only
  the control revealed it.

## Confirm your understanding and flag any drift before starting.
