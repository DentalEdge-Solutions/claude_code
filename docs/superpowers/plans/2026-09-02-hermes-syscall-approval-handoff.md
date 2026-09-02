# Syscall Approval Handoff — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the governed mutation syscall's happy path possible, by teaching the executor to accept the approval reservation the broker made *for this specific run*, without weakening single-use semantics or reopening the TOCTOU the reservation exists to close.

**Architecture:** The broker reserves the approval before spawning the executor (`hermes-broker.py:495`), writing both `reserved_at` and `request_id` into the approval record. The executor then independently re-verifies that same approval (`apply-changeset.py:126`) and `verify_approval` refuses on the presence of `reserved_at` — so the broker's own correctness guarantee makes the legitimate run impossible. The fix threads the request id from broker → wrapper → executor → `verify_approval`, which accepts a reservation **only** when it names this exact request **and** the run has not already completed. Everything else refuses exactly as it does today.

**Tech Stack:** Python 3 stdlib only (no third-party imports anywhere under `infra/hermes-agent/bin/`). POSIX `sh` for the wrapper. Suites are `unittest`, discovered by `infra/hermes-agent/bin/run-bin-tests.sh`.

**Spec:** `docs/superpowers/specs/2026-08-19-hermes-mutation-syscall-design.md` (§7 approval semantics, §13 verification gate). Evidence for the defect: the Task 13 CRITICAL entry in `.superpowers/sdd/2026-08-24-hermes-governed-syscall/progress.md`.

## Global Constraints

- **Stdlib only.** No third-party imports in `infra/hermes-agent/bin/`.
- **Fail closed.** An unreadable, malformed, or type-confused field must refuse, never read as permissive. This is the existing standard throughout `changeset_lib.py`; match it.
- **No client names, customer ids, campaign ids, or credential values** in code, comments, tests, commit messages, or reports. Redact as `<slug-1>` / `<digits>`. Test fixtures use invented slugs only.
- **Zero spend.** No task here may invoke the real `run-ads-mutate.sh` against a live account. Task 4's end-to-end test stubs the ads mutator at the container boundary.
- **Suite discovery is the gate**: `run-bin-tests.sh` must still discover every suite and the test count must **rise**. Exactly one trailing `unittest.main()` per test file — a mid-file one has previously caused six new tests to never run while the suite reported OK.
- **Mutation proofs are green→red on a named test.** Capture the sorted failing-test set before and after and report the difference. After editing any Python to mutate it, run `python3 -c "import ast,io;ast.parse(io.open('F').read())"` before believing a silent result.
- Current baseline: `infra/hermes-agent/bin/run-bin-tests.sh` → **24/24 suites**; `node scripts/run-all-tests.js` → **22/22**.

---

## File Structure

| File | Responsibility | Change |
|---|---|---|
| `infra/hermes-agent/bin/changeset_lib.py` | Approval record semantics — the single place that decides whether an approval may be used | Modify `verify_approval` (`:503`) |
| `infra/hermes-agent/bin/changeset_lib.test.py` | Unit coverage for the above | Add one test class |
| `infra/hermes-agent/bin/apply-changeset.py` | The executor; guard of last resort | Add `--request`, pass it to `verify_approval` (`:126`, argparse at `:390`) |
| `infra/hermes-agent/bin/apply-changeset.test.py` | Executor coverage | Add tests for the new argument |
| `infra/hermes-agent/bin/hermes-broker.py` | Reserves, then spawns | Add `--request` to argv (`:506`) |
| `infra/hermes-agent/bin/hermes-broker.test.py` | Broker coverage | Assert argv carries the request id |
| `infra/hermes-agent/bin/syscall-e2e.test.py` | **New.** The missing seam test: broker → real executor, no mocked executor | Create |

`run-ads-mutate.sh` needs **no change**: line 92 already forwards `"$@"` to the mutator, so a new flag in the broker's argv flows through untouched. Task 3 verifies this rather than assuming it.

---

### Task 1: `verify_approval` accepts the reservation made for this run

**Files:**
- Modify: `infra/hermes-agent/bin/changeset_lib.py:503-541` (`verify_approval`)
- Test: `infra/hermes-agent/bin/changeset_lib.test.py` (append one class above the single trailing `unittest.main()`)

**Interfaces:**
- Consumes: `reserve_approval(slug, cid, request_id, now)` already writes `reserved_at` **and** `request_id` into the record (`changeset_lib.py:677-700`); `record_outcome` later adds `outcome` and `finished_at`.
- Produces: `verify_approval(slug, cid, digest, now, request_id=None)` — the new fifth parameter is **keyword-optional**, so the existing operator path (`--changeset` with no request id) keeps working unchanged.

**The acceptance rule.** Three-way, and the third clause is the one a naive fix forgets:

| Record state | `request_id` argument | Result |
|---|---|---|
| no `reserved_at` | anything | **accept** — the manual operator path, unchanged |
| `reserved_at`, `request_id` matches, no `outcome`/`finished_at` | matching | **accept** — the broker's run, in flight |
| `reserved_at`, run already completed (`outcome` or `finished_at` present) | even a matching one | **refuse** — the run is over; re-use would re-apply |
| `reserved_at`, non-matching or absent argument | anything else | **refuse** — today's behaviour |

- [ ] **Step 1: Write the failing tests**

Append to `changeset_lib.test.py`, above the single trailing `unittest.main()`:

```python
class TestVerifyApprovalReservationHandoff(unittest.TestCase):
    """The broker reserves BEFORE spawning the executor, and the executor then
    re-verifies the same approval. Without this handoff the broker's own
    correctness guarantee makes every legitimate apply impossible — measured
    live on 2026-09-01, every syscall apply refused at refused_preflight.

    The negative cases matter more than the positive one: this parameter is the
    only thing standing between "single-use" and "reusable", so each way it must
    still refuse gets its own test.
    """

    SLUG = "acmedental"
    CID = "20260902-101500-abcdef01"
    DIGEST = "a" * 64
    RID = "11111111-2222-3333-4444-555555555555"

    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.root, True)
        os.environ["HERMES_GOVERNANCE_ROOT"] = self.root
        self.addCleanup(os.environ.pop, "HERMES_GOVERNANCE_ROOT", None)
        self.now = datetime.datetime(2026, 9, 2, 10, 0, 0, tzinfo=datetime.timezone.utc)
        C.write_approval(self.SLUG, self.CID, self.DIGEST, "operator", self.now, 24)

    def test_unreserved_approval_still_verifies_without_a_request_id(self):
        # The manual operator path. Must not regress.
        rec = C.verify_approval(self.SLUG, self.CID, self.DIGEST, self.now)
        self.assertEqual(rec["changeset_id"], self.CID)

    def test_reserved_approval_verifies_for_the_request_that_reserved_it(self):
        # THE POSITIVE CONTROL. Without this the whole feature is dead, and its
        # absence is exactly why the defect survived every prior review.
        C.reserve_approval(self.SLUG, self.CID, self.RID, self.now)
        rec = C.verify_approval(self.SLUG, self.CID, self.DIGEST, self.now,
                                request_id=self.RID)
        self.assertEqual(rec["request_id"], self.RID)

    def test_reserved_approval_refuses_a_different_request_id(self):
        C.reserve_approval(self.SLUG, self.CID, self.RID, self.now)
        with self.assertRaises(ValueError) as cm:
            C.verify_approval(self.SLUG, self.CID, self.DIGEST, self.now,
                              request_id="99999999-9999-9999-9999-999999999999")
        self.assertIn("reserved", str(cm.exception))

    def test_reserved_approval_still_refuses_when_no_request_id_is_supplied(self):
        # The operator path must NOT become a way to consume a broker reservation.
        C.reserve_approval(self.SLUG, self.CID, self.RID, self.now)
        with self.assertRaises(ValueError):
            C.verify_approval(self.SLUG, self.CID, self.DIGEST, self.now)

    def test_a_completed_run_refuses_even_its_own_request_id(self):
        # The clause a naive fix forgets. record_outcome marks the run finished;
        # after that the same request id must not be able to apply again.
        C.reserve_approval(self.SLUG, self.CID, self.RID, self.now)
        C.record_outcome(self.SLUG, self.CID, "accepted_applied", self.now)
        with self.assertRaises(ValueError) as cm:
            C.verify_approval(self.SLUG, self.CID, self.DIGEST, self.now,
                              request_id=self.RID)
        self.assertIn("already completed", str(cm.exception))

    def test_a_type_confused_request_id_in_the_record_refuses(self):
        # Fail closed, matching every other field in this function.
        C.reserve_approval(self.SLUG, self.CID, self.RID, self.now)
        p = C.approval_path(self.SLUG, self.CID)
        rec = json.load(open(p))
        for bad in (None, 123, [], {}, ""):
            rec["request_id"] = bad
            with open(p, "w") as f:
                json.dump(rec, f)
            with self.assertRaises(ValueError):
                C.verify_approval(self.SLUG, self.CID, self.DIGEST, self.now,
                                  request_id=self.RID)

    def test_the_digest_and_expiry_checks_still_run_on_the_reserved_path(self):
        # The new clause must not become a bypass around the other guards.
        C.reserve_approval(self.SLUG, self.CID, self.RID, self.now)
        with self.assertRaises(ValueError) as cm:
            C.verify_approval(self.SLUG, self.CID, "b" * 64, self.now,
                              request_id=self.RID)
        self.assertIn("hash mismatch", str(cm.exception))
        later = self.now + datetime.timedelta(hours=48)
        with self.assertRaises(ValueError) as cm2:
            C.verify_approval(self.SLUG, self.CID, self.DIGEST, later,
                              request_id=self.RID)
        self.assertIn("expired", str(cm2.exception))
```

- [ ] **Step 2: Run them to verify they fail**

```bash
cd infra/hermes-agent && python3 bin/changeset_lib.test.py -k TestVerifyApprovalReservationHandoff -v
```

Expected: `test_reserved_approval_verifies_for_the_request_that_reserved_it` fails with `ValueError: approval ... is already reserved`, and `test_a_completed_run_refuses_even_its_own_request_id` fails on the message assertion. The three "still refuses" tests should already **pass** — they describe today's behaviour and exist to pin it against regression.

- [ ] **Step 3: Implement**

In `changeset_lib.py`, replace the `if "reserved_at" in rec:` block inside `verify_approval` (currently `:518-525`) and change the signature:

```python
def verify_approval(slug, cid, digest, now, request_id=None):
    """...existing docstring...

    RESERVATION HANDOFF (2026-09-02). `request_id` is how the executor proves it is
    the run the broker reserved this approval FOR. The broker reserves before
    spawning (spec §7 — reserving after a successful apply leaves a window in which
    a replay could apply the same change-set twice), and the executor then
    re-verifies the same record as the guard of last resort. Before this parameter
    existed those two correct behaviours contradicted each other and NO apply
    through the syscall could succeed; it was measured live on 2026-09-01, refusing
    at refused_preflight every time.

    Accepting a reservation is narrower than it looks:
      * no reserved_at              -> accept (the manual operator path, unchanged)
      * reserved for THIS request,
        and not yet completed       -> accept
      * reserved and COMPLETED      -> refuse, even for its own request_id. Once
                                       record_outcome has written the outcome the run
                                       is over, and re-running it would re-apply.
      * anything else               -> refuse, exactly as before
    Callers that pass no request_id are unaffected, so single-use is unchanged for
    every path that is not the broker's own in-flight run.
    """
    cid = _require_str(cid, "changeset_id")
    digest = _require_str(digest, "sha256")
    p = approval_path(slug, cid)
    if not os.path.isfile(p):
        raise ValueError(f"no approval record for change-set {cid!r} — run approve-changeset.py first")
    try:                       # unreadable / directory-in-place must REFUSE, not leak an OSError
        with open(p, encoding="utf-8") as f:
            rec = json.load(f)
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as e:
        raise ValueError(f"unreadable approval record for {cid!r}: {e}")
    if not isinstance(rec, dict):
        raise ValueError(f"malformed approval record for {cid!r}: expected a JSON object")
    if "reserved_at" in rec:
        # Presence, not truthiness: "", null, or 0 must refuse exactly like a real
        # timestamp does. Every other field here goes through _require_str — reserved_at
        # is no exception, so a type-confused value refuses loudly instead of reading as
        # unreserved.
        reserved_at = _require_str(rec.get("reserved_at"), "reserved_at")
        # A finished run is dead regardless of who asks. Checked BEFORE the request_id
        # comparison so that a completed run cannot be re-entered by the very request
        # that completed it.
        if "outcome" in rec or "finished_at" in rec:
            raise ValueError(
                "approval for %r was reserved at %s and has already completed — "
                "approvals are single-use; approve again to authorise another apply"
                % (cid, reserved_at))
        if request_id is None:
            raise ValueError(
                "approval for %r is already reserved (reserved_at=%s) — approvals are "
                "single-use; approve again to authorise another apply" % (cid, reserved_at))
        reserved_for = _require_str(rec.get("request_id"), "request_id")
        if reserved_for != _require_str(request_id, "request_id"):
            raise ValueError(
                "approval for %r is reserved for a different request (reserved_at=%s) "
                "— approvals are single-use" % (cid, reserved_at))
    if _require_str(rec.get("changeset_id"), "changeset_id") != cid:
        raise ValueError(f"approval record changeset_id does not match {cid!r}")
    approved_digest = _require_str(rec.get("sha256"), "sha256")
    if approved_digest != digest:
        raise ValueError(f"approval hash mismatch for {cid!r} — the change-set was "
                         "modified after approval; re-approve the reviewed bytes")
    operator = _require_str(rec.get("operator"), "operator")
    if not OPERATOR_RE.fullmatch(operator):
        raise ValueError(f"invalid operator in approval record: {operator!r}")
    _parse_utc_field(rec, "approved_at")
    expires = _parse_utc_field(rec, "expires_at")
    if not isinstance(now, datetime.datetime):
        raise ValueError(f"now must be datetime, got {type(now).__name__}")
    if now > expires:
        raise ValueError(f"approval for {cid!r} expired at {rec['expires_at']} — re-approve")
    return rec
```

Also update the stale comment at `changeset_lib.py:677-679`, which says `verify_approval` "refuses whenever `reserved_at` is present" — that is no longer true. Replace "whenever" with "whenever `reserved_at` is present and the caller is not the run it was reserved for (see verify_approval)".

- [ ] **Step 4: Run the tests to verify they pass**

```bash
cd infra/hermes-agent && python3 bin/changeset_lib.test.py -v 2>&1 | tail -5
```
Expected: `OK`, and the total count for this file is **7 higher** than before.

- [ ] **Step 5: Mutation proof — the completed-run clause**

Capture the sorted failing set, delete the `if "outcome" in rec or "finished_at" in rec:` block, `ast.parse` the file, re-run, and diff.
Expected green→red: `test_a_completed_run_refuses_even_its_own_request_id`.
Then restore and confirm green.

- [ ] **Step 6: Mutation proof — the request-id comparison**

Change `if reserved_for != _require_str(request_id, "request_id"):` to `if False:`. `ast.parse`, re-run, diff.
Expected green→red: `test_reserved_approval_refuses_a_different_request_id`.
Restore and confirm green.

- [ ] **Step 7: Run the whole suite and commit**

```bash
cd infra/hermes-agent && ./bin/run-bin-tests.sh 2>&1 | tail -2   # expect 24/24
git add bin/changeset_lib.py bin/changeset_lib.test.py
git commit -m "fix(hermes): let the executor accept the reservation made for its own run

The broker reserves an approval before spawning the executor (spec §7), and the
executor re-verifies that same approval as the guard of last resort. verify_approval
refused on the mere presence of reserved_at, so the broker's own correctness
guarantee made every legitimate apply impossible — measured live on 2026-09-01,
refusing at refused_preflight with no input that could succeed.

verify_approval gains an optional request_id. A reservation is accepted only when it
names this exact request AND the run has not completed; record_outcome's outcome
closes it permanently, so a finished run cannot be re-entered by the request that
finished it. Callers passing no request_id are unaffected, so single-use is unchanged
for every path that is not the broker's own in-flight run.

7 tests. Mutation proofs, sorted failing sets compared: deleting the completed-run
clause reds test_a_completed_run_refuses_even_its_own_request_id; neutering the
request-id comparison reds test_reserved_approval_refuses_a_different_request_id."
```

---

### Task 2: The executor accepts and forwards `--request`

**Files:**
- Modify: `infra/hermes-agent/bin/apply-changeset.py` (argparse at `:390-396`, `verify_approval` call at `:126`, and `build_plan`'s signature)
- Test: `infra/hermes-agent/bin/apply-changeset.test.py`

**Interfaces:**
- Consumes: `verify_approval(slug, cid, digest, now, request_id=None)` from Task 1.
- Produces: `apply-changeset.py --request <uuid>`, optional. `build_plan(client, changeset_id, now, registry=None, projects=None, undo=None, request_id=None)`.

- [ ] **Step 1: Write the failing test**

```python
class TestRequestIdIsThreadedToTheApproval(unittest.TestCase):
    """--request is how the executor proves it is the broker's in-flight run.
    It must reach verify_approval unchanged, and must stay OPTIONAL so the
    operator's own `--changeset` invocation keeps working."""

    def test_request_id_reaches_verify_approval(self):
        seen = {}
        real = C.verify_approval
        def spy(slug, cid, digest, now, request_id=None):
            seen["request_id"] = request_id
            return real(slug, cid, digest, now, request_id=request_id)
        with mock.patch.object(C, "verify_approval", spy):
            A.build_plan(self.CLIENT, self.CID, self.NOW,
                         registry=self.reg, projects=self.proj,
                         request_id="11111111-2222-3333-4444-555555555555")
        self.assertEqual(seen["request_id"], "11111111-2222-3333-4444-555555555555")

    def test_omitting_request_id_passes_none(self):
        seen = {}
        real = C.verify_approval
        def spy(slug, cid, digest, now, request_id=None):
            seen["request_id"] = request_id
            return real(slug, cid, digest, now, request_id=request_id)
        with mock.patch.object(C, "verify_approval", spy):
            A.build_plan(self.CLIENT, self.CID, self.NOW,
                         registry=self.reg, projects=self.proj)
        self.assertIsNone(seen["request_id"])

    def test_cli_rejects_a_malformed_request_id(self):
        # Fail closed at the boundary rather than letting a junk value reach the
        # approval comparison, where it would merely mismatch and refuse anyway —
        # a clear usage error beats an opaque approval refusal.
        r = subprocess.run([sys.executable, APPLY, "--client", self.CLIENT,
                            "--changeset", self.CID, "--request", "not-a-uuid"],
                           capture_output=True, text=True)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("request", (r.stderr or "").lower())
```

- [ ] **Step 2: Run to verify failure**

```bash
cd infra/hermes-agent && python3 bin/apply-changeset.test.py -k TestRequestIdIsThreadedToTheApproval -v
```
Expected: `TypeError: build_plan() got an unexpected keyword argument 'request_id'`.

- [ ] **Step 3: Implement**

In `apply-changeset.py`:

```python
# argparse, beside the existing arguments (~:396)
ap.add_argument("--request",
                help="the broker's request id. Proves this run is the one the "
                     "approval was reserved for. Omit it for a manual operator "
                     "apply, which uses an unreserved approval.")
```

Validate it at the boundary, next to the other argument checks in `main`:

```python
REQUEST_ID_RE = re.compile(r"^[0-9a-fA-F-]{36}$")   # module level, beside the other regexes

# in main(), before build_plan is called:
if args.request is not None and not REQUEST_ID_RE.fullmatch(args.request):
    print("apply-changeset: invalid --request: %r (expected a 36-character request id)"
          % args.request, file=sys.stderr)
    return 1
```

Thread it through `build_plan`:

```python
def build_plan(client, changeset_id, now, registry=None, projects=None, undo=None,
               request_id=None):
    ...
    approval = C.verify_approval(rec["slug"], changeset_id, C.file_digest(path), now,
                                 request_id=request_id)
```

and at the call site in `main`: `build_plan(..., undo=args.undo, request_id=args.request)`.

- [ ] **Step 4: Run to verify pass**

```bash
cd infra/hermes-agent && python3 bin/apply-changeset.test.py -v 2>&1 | tail -5
```
Expected: `OK`, count 3 higher.

- [ ] **Step 5: Mutation proof**

Change the `build_plan` call in `main` to drop `request_id=args.request`. `ast.parse`, re-run.
Expected green→red: `test_request_id_reaches_verify_approval`. Restore, confirm green.

- [ ] **Step 6: Commit**

```bash
git add bin/apply-changeset.py bin/apply-changeset.test.py
git commit -m "feat(hermes): apply-changeset accepts --request and threads it to the approval

Optional by design: the operator's manual --changeset apply uses an unreserved
approval and passes nothing. Validated at the CLI boundary so a malformed value is
a usage error rather than an opaque approval refusal. 3 tests."
```

---

### Task 3: The broker passes the request id it reserved with

**Files:**
- Modify: `infra/hermes-agent/bin/hermes-broker.py:506`
- Test: `infra/hermes-agent/bin/hermes-broker.test.py`

**Interfaces:**
- Consumes: `apply-changeset.py --request <uuid>` from Task 2.
- Produces: broker argv `[MUTATE_SH, "--client", slug, "--changeset", cid, "--request", rid]`.

`run-ads-mutate.sh` needs no change — line 92 forwards `"$@"` to the mutator. Step 3 verifies that rather than assuming it.

- [ ] **Step 1: Write the failing test**

```python
def test_argv_carries_the_request_id_that_was_reserved(self):
    """The reservation and the executor's proof must be the SAME id. A broker that
    reserved with one id and spawned with another would refuse every apply — the
    2026-09-01 defect in a new disguise."""
    runner = RecordingRunner(rc=0, out=GOOD_RESULT)
    drain(spool=self.spool, projects=self.projects, runner=runner, now=NOW)
    argv = runner.calls[0]
    self.assertIn("--request", argv)
    rid_in_argv = argv[argv.index("--request") + 1]
    self.assertEqual(rid_in_argv, self.request_id)
    rec = json.load(open(C.approval_path(self.SLUG, self.CID)))
    self.assertEqual(rec["request_id"], rid_in_argv,
                     "argv id must match the id written by reserve_approval")
```

- [ ] **Step 2: Run to verify failure**

```bash
cd infra/hermes-agent && python3 bin/hermes-broker.test.py -k test_argv_carries -v
```
Expected: FAIL — `'--request' not found in [...]`.

- [ ] **Step 3: Implement**

```python
# hermes-broker.py:506
argv = [MUTATE_SH, "--client", slug, "--changeset", cid, "--request", rid]
```

- [ ] **Step 4: Run to verify pass, then confirm the wrapper forwards it**

```bash
cd infra/hermes-agent && python3 bin/hermes-broker.test.py -v 2>&1 | tail -3
grep -n '"\$@"' run-ads-mutate.sh    # :92 — confirm the flag reaches the mutator unmodified
```

- [ ] **Step 5: Mutation proof**

Revert argv to the 4-element form. `ast.parse`, re-run.
Expected green→red: `test_argv_carries_the_request_id_that_was_reserved`. Restore, confirm green.

- [ ] **Step 6: Commit**

```bash
git add bin/hermes-broker.py bin/hermes-broker.test.py
git commit -m "fix(hermes): broker passes the request id it reserved the approval with

The test asserts argv's id equals the id reserve_approval wrote, not merely that a
flag is present — a broker that reserved with one id and spawned with another would
reproduce the 2026-09-01 defect in a new disguise."
```

---

### Task 4: The end-to-end test that would have caught this

**Files:**
- Create: `infra/hermes-agent/bin/syscall-e2e.test.py`

**Interfaces:**
- Consumes: everything from Tasks 1–3.
- Produces: nothing; this is the seam net.

**Why this task is the point of the plan.** Broker tests inject a fake runner and never execute the real executor. Executor tests approve directly and never pass through the broker's reservation. Both sides were tested rigorously with the other mocked, and the contradiction lived in the gap. This suite closes that gap by running the **real** `apply-changeset.py` in a subprocess against a **real** temp governance store, stubbing only at the container boundary — the one place that would cost money.

Task 12's seam S4 examined this exact interaction and passed it, because it asked only whether an attacker could get through and never whether the authorised caller could. **Every refusal test here is paired with a positive control asserting the legitimate path still succeeds.**

- [ ] **Step 1: Write the suite**

```python
#!/usr/bin/env python3
"""End-to-end: broker -> real apply-changeset.py, no mocked executor.

ZERO SPEND BY CONSTRUCTION. `docker` is a fake on a temp PATH, so the ads-mutator
container is never created and nothing reaches a Google Ads account. What is real
here is the part that was never tested together: the broker's reservation and the
executor's independent re-verification of the same approval record.

Every refusal below is paired with a positive control. A guard nobody can pass is
indistinguishable from a guard that works, until someone tries the legitimate case —
that is precisely how the 2026-09-01 CRITICAL survived eleven task reviews, a seam
review, a fix wave and a readiness pass.
"""
import json, os, shutil, subprocess, sys, tempfile, unittest, datetime

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import changeset_lib as C
import governance_lib as G

APPLY = os.path.join(HERE, "apply-changeset.py")
SLUG = "acmedental"
NOW = datetime.datetime(2026, 9, 2, 10, 0, 0, tzinfo=datetime.timezone.utc)
RID = "11111111-2222-3333-4444-555555555555"


class Base(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.root, True)
        os.environ["HERMES_GOVERNANCE_ROOT"] = self.root
        self.addCleanup(os.environ.pop, "HERMES_GOVERNANCE_ROOT", None)
        for d in ("approvals", "control", "registry", "log", "seen"):
            os.makedirs(os.path.join(self.root, d), exist_ok=True)
        # Kill switch ON: these tests are about the approval handoff, and a disabled
        # switch would refuse first and hide whatever the handoff did.
        open(os.path.join(self.root, "control", "mutation-enabled"), "w").close()
        self.cid = "20260902-101500-abcdef01"
        self.digest = self._write_changeset()
        C.write_approval(SLUG, self.cid, self.digest, "operator", NOW, 24)

    def _write_changeset(self):
        """Write the change-set the approval binds, and return its digest."""
        raise NotImplementedError("filled in by the implementer against "
                                  "propose-changeset.py's on-disk format")

    def _run_executor(self, request_id=None):
        argv = [sys.executable, APPLY, "--client", SLUG, "--changeset", self.cid,
                "--dry-run"]
        if request_id:
            argv += ["--request", request_id]
        return subprocess.run(argv, capture_output=True, text=True, timeout=120)


class TestReservationHandoffEndToEnd(Base):
    def test_the_happy_path_actually_succeeds(self):
        """THE TEST THAT DID NOT EXIST. Reserve exactly as the broker does, then run
        the REAL executor with that request id. Before the handoff this refused with
        'already reserved' for every possible input."""
        C.reserve_approval(SLUG, self.cid, RID, NOW)
        p = self._run_executor(request_id=RID)
        self.assertEqual(p.returncode, 0,
                         "happy path must succeed; stderr=%s" % p.stderr[:400])
        self.assertNotIn("already reserved", p.stderr)

    def test_a_foreign_request_id_is_refused(self):
        C.reserve_approval(SLUG, self.cid, RID, NOW)
        p = self._run_executor(request_id="99999999-9999-9999-9999-999999999999")
        self.assertNotEqual(p.returncode, 0)

    def test_a_reserved_approval_refuses_an_operator_apply(self):
        C.reserve_approval(SLUG, self.cid, RID, NOW)
        p = self._run_executor()          # no --request: the manual path
        self.assertNotEqual(p.returncode, 0)

    def test_an_unreserved_approval_still_serves_the_operator_path(self):
        # Positive control for the clause above: the manual path must still work.
        p = self._run_executor()
        self.assertEqual(p.returncode, 0,
                         "operator path regressed; stderr=%s" % p.stderr[:400])

    def test_a_completed_run_cannot_be_replayed_by_its_own_request_id(self):
        C.reserve_approval(SLUG, self.cid, RID, NOW)
        C.record_outcome(SLUG, self.cid, "accepted_applied", NOW)
        p = self._run_executor(request_id=RID)
        self.assertNotEqual(p.returncode, 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
```

- [ ] **Step 2: Fill in `_write_changeset` against the real on-disk format**

Read `propose-changeset.py` for the exact change-set JSON it writes and `C.file_digest` for how the digest is computed. Write a change-set with **one** `add_campaign_negative` action using an invented campaign id (`"1"`) and the keyword `"e2e fixture"`. Return `C.file_digest(path)`. Do not invent a format — match what `propose-changeset.py` produces, or the digest check will refuse for the wrong reason and the suite will pass vacuously.

- [ ] **Step 3: Confirm the suite is discovered and the count rises**

```bash
cd infra/hermes-agent && ./bin/run-bin-tests.sh 2>&1 | tail -3
```
Expected: **25/25** suites (24 + this one). If the count did not rise, the suite is not being discovered and none of this is running.

- [ ] **Step 4: The regression proof that matters**

Revert Task 3's one-line argv change so the broker stops passing `--request`. `ast.parse`, then run this suite.
Expected: `test_the_happy_path_actually_succeeds` goes **red**. That is the proof this suite would have caught the original CRITICAL. Restore, confirm green.

- [ ] **Step 5: Commit**

```bash
git add bin/syscall-e2e.test.py
git commit -m "test(hermes): end-to-end broker->executor suite, the seam nothing covered

Broker tests inject a fake runner and never run the real executor; executor tests
approve directly and never pass through the broker's reservation. Both sides were
tested well with the other mocked, and the 2026-09-01 CRITICAL lived in the gap.

Runs the REAL apply-changeset.py against a real temp governance store, stubbing only
at the container boundary. Every refusal is paired with a positive control: seam S4
passed this same interaction by asking only whether an attacker could get through,
never whether the authorised caller could.

Verified by reverting the broker's --request argv: the happy-path test goes red."
```

---

### Task 5: Re-run the live gate's blocked steps

**Files:** none — this is verification, recorded in the ledger.

**Preconditions.** Tasks 1–4 merged. `<slug-1>` marked `mutation_target=dormant_pilot`. Audit log backed up and its sha12 recorded. Kill switch **absent** at start.

- [ ] **Step 1: Fresh change-set and approval**

`propose-changeset.py`, then `approve-changeset.py --expect-sha256 <digest>`. One `add_campaign_negative`, EXACT, an obviously synthetic keyword, on the campaign the rail was verified against on 2026-08-15/16.

- [ ] **Step 2: Step 10 — the apply**

Enable the kill switch. File via `hermes-syscall apply`, drain with `hermes-broker.py --once`.
Expected: `accepted_applied`, `exit_code 0`, syscall `result` exits **0**, audit log grows from 4 to **5** records.

- [ ] **Step 3: S7 check, with its control**

Grep the new `result.json` for the resolved customer id: expect **0**.
Grep `data/vaults/<slug>/changes/20260816-154808-1d5ed98d.result.json` (pre-fix) for the same needle: expect **1**. Without that control, zero is not evidence.

- [ ] **Step 4: Confirm the audit log still parses before undoing**

```bash
python3 -c "import sys;sys.path.insert(0,'bin');import changeset_lib as C;print(len(list(C.iter_log_records('<slug>'))),'records parse')"
```
Undo's only dependency. Check it before relying on it.

- [ ] **Step 5: Undo host-side, and confirm byte-identical**

`run-ads-mutate.sh --undo <changeset>`. Expect audit log at **6** records (applied + undone). Confirm the account is byte-identical to its pre-step-10 state.

- [ ] **Step 6: Step 11 — consumed approval**

Re-request the same change-set. Expect `refused_approval`. This is the live proof that Task 1's completed-run clause holds outside the unit tests.

- [ ] **Step 7: Remove the kill switch and confirm by file test**

```bash
test -e ~/.hermes/governance/control/mutation-enabled && echo "STILL ENABLED — fix" || echo "absent (correct)"
```
A file test, not `ls | grep -c`: `ls` on a missing directory prints an error line that `grep -c` counts as a match.

- [ ] **Step 8: Record every result in the ledger with the control that made it meaningful**

---

## Self-Review

**Spec coverage.** Spec §7's ordering requirement (reserve before spawn) is preserved — Task 1 changes only who may *consume* a reservation, never when it is written. §13's steps 10 and 11 are Task 5. The single-use rule survives: the only new acceptance is the in-flight run that already holds the reservation, and it closes permanently once `record_outcome` writes the outcome.

**Placeholder scan.** One deliberate `NotImplementedError`, in Task 4 Step 1's `_write_changeset`, resolved by Task 4 Step 2 with explicit instructions to read `propose-changeset.py` rather than invent a format. Flagged rather than hidden because inventing that format is the likeliest way to make the suite pass vacuously.

**Type consistency.** `verify_approval(slug, cid, digest, now, request_id=None)` is defined in Task 1 and used with that exact signature in Tasks 2 and 4. `build_plan(..., request_id=None)` is defined in Task 2 and used in Task 4. The argv form in Task 3 matches the `--request` flag Task 2 adds.

**Residual risk.** Task 5 is a live account write; it is unproven against a *hostile* executor because S3-b remains open — the audit log is still executor-deletable, and undo depends on it. That is a separate wave, and its measured blockers are in the Task 12 ledger. Nothing in this plan closes it, and nothing in this plan depends on it.
