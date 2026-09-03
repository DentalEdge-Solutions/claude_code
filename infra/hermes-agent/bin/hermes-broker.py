#!/usr/bin/env python3
"""Host-side broker: drains the request spool and invokes the governed mutation rail.

PRIVILEGED CODE. It runs on the host, it can start containers, and it is the only
component that reads a tree Hermes can write. It is deliberately small, has no network
listener, accepts a closed input schema, and treats every byte of the spool as hostile.

WHAT IT WILL NOT DO, BY CONSTRUCTION:
  * It never interpolates a request field into a command string. The two validated
    identifiers are passed as separate argv elements to a fixed program. There is no
    shell anywhere in this file.
  * It never passes --undo. Undo bypasses the kill switch and the caps and needs no
    approval, so it stays operator-only (spec §17.2).
  * It never trusts the spool for replay state. The seen-set is in the governance
    store, which no container mounts.
  * It never executes before reserving. A crash must cost an unusable approval, never
    a duplicate account change (spec §7).

Concurrency note, corrected after Task 4 changed the locking story: the per-client
_ClientLock below is a serialisation mechanism for the drain and DEFENSE IN DEPTH, not
the thing that makes changeset_lib.reserve_approval/record_outcome safe. Those two
functions take their OWN flock on a per-approval sidecar file
(governance_lib.approval_lock_path) and are self-defending against concurrent callers
regardless of what this module does. An earlier version of this docstring claimed the
single-threaded drain plus this lock was what made that read-modify-write safe; that
was true before Task 4 and is not true now, and is corrected here rather than left to
quietly overclaim a guarantee this file no longer needs to provide. _ClientLock's own
path (control/.locks/<slug>.lock) is a DIFFERENT FILE from Task 4's sidecar
(approvals/<slug>/<cid>.approval.lock) — nesting them cannot deadlock, and they must
not be merged into one lock; see changeset_lib._approval_lock's docstring.
"""
import argparse, collections, datetime, fcntl, json, os, subprocess, sys, time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import changeset_lib as C
import governance_lib
import spool_lib as S
import vault_lib

HERE = os.path.dirname(os.path.abspath(__file__))
MUTATE_SH = os.path.join(os.path.dirname(HERE), "run-ads-mutate.sh")

# A ceiling on how many request files one drain will even look at. Without it, Hermes
# can make the broker's directory scan itself the denial of service — the per-client
# quotas cannot help, because attributing a file to a client requires parsing it.
MAX_SPOOL_FILES = 256

# Subprocess wall-clock ceiling. A hung executor must not wedge a single-threaded
# broker forever.
RUNNER_TIMEOUT_SECONDS = 900

Decision = collections.namedtuple("Decision", "accept classification detail")

ACCEPT = Decision(True, "accepted", "")


def _utcday(now):
    return now.strftime("%Y-%m-%d")


class _ClientLock:
    """flock on a host-only path under control/.locks/. Not in the spool: a lock the
    serialised party can delete is not a lock.

    Serialises one drain's processing of a given client's requests and is defense in
    depth alongside Task 4's own approval-sidecar lock — it is NOT the sole guarantee
    of single-use approval; see the module docstring above.
    """

    def __init__(self, slug):
        self.path = governance_lib.lock_path(slug)
        self.fd = None

    def __enter__(self):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        self.fd = os.open(self.path, os.O_CREAT | os.O_RDWR, 0o600)
        fcntl.flock(self.fd, fcntl.LOCK_EX)
        return self

    def __exit__(self, *exc):
        try:
            fcntl.flock(self.fd, fcntl.LOCK_UN)
        finally:
            os.close(self.fd)
            self.fd = None


def _accepted_today(slug, now):
    """How many request_ids were accepted for this client today, read from the
    governance-store seen-set.

    FIX ROUND 2 (Finding 2): this used to count by substring-matching raw lines for
    '"seen_at": "<day>' and caught only OSError — so a seen-set whose "seen_at" field
    was mangled, missing, or moved by a re-serialization simply failed to match the
    substring and was silently counted as zero, while the docstring claimed "fail
    closed" and `seen_contains` on the exact same file correctly raised on the same
    corruption. Two readers of one file, two failure semantics, on the axis that
    bounds how much work a client can cause. Now reads via
    changeset_lib.iter_seen_records — the SAME parser seen_contains uses — so this
    cannot drift out of sync with it again. FAIL-CLOSED: an unreadable seen-set, or
    any line that is not a well-formed {request_id, seen_at} record, raises
    ValueError (from iter_seen_records) rather than being skipped or undercounted.
    """
    day = _utcday(now)
    n = 0
    for rec in C.iter_seen_records(slug):
        if rec["seen_at"].startswith(day):
            n += 1
    return n


def classify(req, quotas, pending_count, accepted_today, now):
    """Decide whether a SCHEMA-VALID request may proceed. Pure; no side effects.

    Kept pure and separate from drain() so the ordering of the checks is reviewable in
    one screen, and so each refusal reason can be tested without a filesystem.

    NOTE on arity: this takes FIVE arguments (req, quotas, pending_count,
    accepted_today, now). An earlier interfaces listing for this task named only four
    — that listing was wrong; the daily-quota check below needs accepted_today, so this
    signature is the one that ships.

    NOTE on pending_count (RULING R5): pending_count is computed ONCE per drain, over
    every request file present for this client before any of them are processed. A
    client that is already over max_pending_requests is therefore refused WHOLESALE —
    every one of its pending requests, not merely the requests past the limit — because
    there is no ordering among files in one directory listing that would make "the
    first N" a meaningful distinction to enforce. This is the correct fail-closed
    reading: an over-limit client stays refused until its queue drains below the limit
    on a later pass, rather than the broker guessing which of an already-too-large
    batch to let through.
    """
    if pending_count > quotas["max_pending_requests"]:
        return Decision(False, "refused_quota",
                        "client has %d pending requests, over the max_pending_requests "
                        "limit of %d" % (pending_count, quotas["max_pending_requests"]))
    if accepted_today >= quotas["accepted_requests_per_client_day"]:
        return Decision(False, "refused_quota",
                        "client has already had %d requests accepted today, at the "
                        "accepted_requests_per_client_day limit of %d"
                        % (accepted_today, quotas["accepted_requests_per_client_day"]))
    return ACCEPT


def _write_result(rid, spool, classification, status, exit_code, detail, now):
    return S.write_result(rid, {
        "request_id": rid,
        "status": status,
        "classification": classification,
        "exit_code": exit_code,
        "detail": detail,
        "finished_at": now.strftime(C.ISO),
    }, spool)


def _discard(path):
    """Remove a processed spool entry. Must never raise: a single poisoned or
    already-vanished entry must never crash the drain and must never block any other
    request in the same batch.

    FIX ROUND 2 (Finding 1, CRITICAL): Hermes can `mkdir` a UUID-shaped name in
    requests/ — `_scan`'s FILENAME_RE only checks the NAME shape, and `_parse_all`
    correctly refuses it as non-regular, but a bare `os.unlink()` on a directory
    raises (EISDIR on Linux, observed as a bare PermissionError on macOS), and that
    exception used to propagate straight out of drain() uncaught. Because the
    directory was never removed, `_scan` saw it again on the NEXT drain and every
    drain thereafter died the identical way: one `mkdir` from the exact actor this
    module's own docstring names as hostile permanently bricked the governed
    mutation rail, starving every other client's queued requests in the same and
    every subsequent pass.

    Three-step fallback, each step only tried if the previous one failed:
      1. os.unlink — the fast, common case. FileNotFoundError (already gone, e.g. a
         concurrent cleanup or a path replaced out from under us between scan and
         delete) is success, not an error: something else already resolved it.
      2. If unlink fails for any other reason — it is a directory, or a permission
         quirk we cannot otherwise explain — QUARANTINE it: os.replace() it into
         requests/.quarantine/, a location _scan never looks at, under a
         collision-proof name. This is chosen over recursively deleting whatever the
         entry is (which could itself be adversarially deep or surprising — this is
         hostile-input-handling code and should not recurse into untrusted structure)
         and over leaving it in requests/ (which would make _scan find it again on
         every future pass, forever re-triggering the same rejection AND the same
         failing delete attempt — unbounded repeated "new work" and unbounded stderr
         noise on every single drain from here on, which is only a slower-motion
         version of the same permanent stall).
      3. If even the quarantine move fails (e.g. the entry was swapped again, mid-move,
         for something else entirely), log once to stderr and give up on this one
         entry. The drain must survive this by moving on, not by looping.
    """
    try:
        os.unlink(path)
        return
    except FileNotFoundError:
        return                          # already gone — not this function's problem
    except OSError:
        pass                            # not a plain deletable file; fall through

    try:
        qdir = os.path.join(os.path.dirname(path), ".quarantine")
        os.makedirs(qdir, exist_ok=True)
        dest = os.path.join(qdir, "%s.%d.%d" % (os.path.basename(path),
                                                 time.time_ns(), os.getpid()))
        os.replace(path, dest)
    except OSError as e:
        print("hermes-broker: could not remove or quarantine %s (%s) — leaving it in "
              "place; it may be re-scanned and re-rejected on a future drain"
              % (path, e), file=sys.stderr)


def _scan(spool):
    """Return (names, overflow). Only names matching the request-file pattern; a
    dot-prefixed temp file from a half-written request cannot match.

    FIX ROUND 2 (Finding 4): previously did `sorted(os.listdir(d) if FILENAME_RE...)`,
    which materializes and regex-filters the ENTIRE directory before the
    MAX_SPOOL_FILES slice is ever applied — so the stated purpose of the cap ("the
    directory scan itself must not become the denial of service") was only half
    delivered: an extreme flood still paid the full listdir + regex + sort cost every
    single drain, cap or no cap. Uses os.scandir instead, which yields entries
    lazily, and breaks out as soon as MAX_SPOOL_FILES + 1 MATCHING names have been
    seen — at that point we already know this drain will refuse everything on
    overflow (see drain()), so which exact files beyond the cap were present is
    irrelevant and not worth enumerating. Below the cap (the overwhelmingly common
    case), behaviour is identical to before: every matching name, sorted.
    """
    d = S.requests_dir(spool)
    if not os.path.isdir(d):
        return [], False
    names = []
    with os.scandir(d) as it:
        for entry in it:
            if not S.FILENAME_RE.fullmatch(entry.name):
                continue
            names.append(entry.name)
            if len(names) > MAX_SPOOL_FILES:
                return [], True                # already over the cap; stop looking
    return sorted(names), False


def _parse_all(spool, names):
    """Parse every candidate once. Returns (parsed, rejected) where parsed is a list of
    (name, req) and rejected is a list of (name, reason)."""
    parsed, rejected = [], []
    d = S.requests_dir(spool)
    for name in names:
        try:
            parsed.append((name, S.load_request(os.path.join(d, name))))
        except S.SpoolRefused as e:
            rejected.append((name, str(e)))
    return parsed, rejected


def drain(spool=None, projects=None, runner=None, now=None):
    """One pass over the spool. Returns a list of outcome dicts (also written as
    result files). `runner` is a callable (argv) -> (returncode, stdout).

    RULING R6, deliberate departure from "a result on every outcome" (spec §12): on
    spool overflow the WHOLE drain is refused and NO per-request result files are
    written. Overflow is a broker-level event, not a per-request one — attributing any
    of the flood's files to a client requires parsing them, and a flooded spool is
    exactly the situation in which the broker must not spend cycles parsing untrusted
    files one by one. The request files themselves are deliberately NOT discarded on
    this path (contrast with every other refusal path in this function, which does
    discard): they still exist for the next drain to reconsider, or for a human to
    triage, once the flood is understood. This is logged LOUDLY to stderr because it is
    the one refusal path that produces no spool-visible result at all — silence here
    would make a flooded spool indistinguishable from a stalled or dead broker.
    """
    spool = spool or S.spool_root()
    projects = projects or C.registry_projects_path()
    now = now or datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0)
    runner = runner or _run_subprocess
    outcomes = []

    names, overflow = _scan(spool)
    if overflow:
        # Refuse the whole drain rather than servicing an arbitrary prefix. Attributing
        # files to clients requires parsing them, so a flooded spool cannot be triaged
        # per-client — and quietly working through the first 256 would make the flood
        # look like normal operation. Deliberately no per-request result files (R6):
        # said loudly on stderr instead, because that silence is otherwise
        # indistinguishable from a broker that is down.
        detail = ("more than %d request files present; refusing the entire drain "
                  "without writing any per-request result files — the requests are "
                  "NOT discarded" % MAX_SPOOL_FILES)
        print("hermes-broker: SPOOL OVERFLOW — %s" % detail, file=sys.stderr)
        outcomes.append({"classification": "refused_spool_overflow", "detail": detail})
        return outcomes

    parsed, rejected = _parse_all(spool, names)

    for name, reason in rejected:
        rid = name[:-len(".json")]
        if S.REQUEST_ID_RE.fullmatch(rid):
            outcomes.append({"request_id": rid, "classification": "refused_request",
                             "detail": reason})
            _write_result(rid, spool, "refused_request", "refused", 2, reason, now)
        _discard(os.path.join(S.requests_dir(spool), name))

    pending = collections.Counter(req["client"] for _, req in parsed)

    # PER-REQUEST ISOLATION (Finding 3, FIX ROUND 2). This try/except is what stops one
    # bad request from starving every OTHER request already queued in the same batch:
    # an exception here is caught, turned into a refusal for THIS request_id only, and
    # the for-loop moves on to the next name. Through Task 5 that isolation deliberately
    # did NOT extend to NotImplementedError — _execute/_run_subprocess were stubbed to
    # raise it on purpose (RULING R12: "not built yet" must propagate loudly, not be
    # laundered into a refusal that looks like a guard decision).
    #
    # TASK 6 REVISIT, now that _execute is real. Enumerated every exception a genuine
    # call can raise, rather than guessing:
    #   * subprocess.TimeoutExpired — the one exception _run_subprocess's own call can
    #     raise besides OSError — is already caught INSIDE _execute and converted to
    #     rc=3 ("may have mutated, treat as failed"). It never reaches this frame.
    #   * A failure to even launch the executor (missing script, exec permission,
    #     ENOENT/EACCES, ...) surfaces as OSError (FileNotFoundError/PermissionError
    #     are subclasses) — already in the tuple below.
    #   * C.reserve_approval and C.record_outcome raise only ValueError or OSError, and
    #     _execute already catches both around EACH call individually, so neither
    #     propagates here either.
    #   * subprocess.SubprocessError is added explicitly, defensively: it is the base
    #     class for the executor-invocation family (TimeoutExpired included) and, like
    #     OSError from a failed exec, describes the external process misbehaving, not
    #     a bug in this broker — the same category of "operational fault, not a
    #     programming error" that justifies OSError's presence here.
    #   * KeyError is NOT here for _execute's sake — DETAIL_BY_CLASSIFICATION is looked
    #     up with .get(), so it cannot raise KeyError even on a future mapping gap (see
    #     _DETAIL_FALLBACK above). KeyError earns its place in this tuple entirely on
    #     account of vault_lib.resolve(slug), called from _process: an unknown client
    #     slug is a legitimate refusal (RULING R4-adjacent — the slug came from an
    #     untrusted spool file) and vault_lib.resolve raises plain KeyError for it.
    #     Removing KeyError from this tuple would turn that refusal into an uncaught
    #     crash that starves every other client's queued requests in the same batch.
    # Deliberately NOT added: NotImplementedError, or a bare Exception/RuntimeError/
    # TypeError/AttributeError catch-all. Those signal a bug in the broker's own code
    # (a stub still standing, a typo, a wrong argument shape) rather than a guard
    # saying "no" or an external process misbehaving, and R12's point survives Task 6
    # unchanged: a programming error must still fail loudly, never be rendered as a
    # governance refusal.
    for name, req in parsed:
        rid, slug, cid = req["request_id"], req["client"], req["changeset"]
        path = os.path.join(S.requests_dir(spool), name)
        try:
            with _ClientLock(slug):
                outcome = _process(req, spool, projects, pending[slug], runner, now)
        except (ValueError, KeyError, OSError, subprocess.SubprocessError) as e:
            # S6: the FULL exception goes to stderr (host-side, journalled) and the
            # FIXED text goes to the spool. The outcome dict returned from drain() is
            # printed on the broker's own stdout by main(), which is also host-side, so
            # it could keep the raw text — but it carries the same field name as the
            # spool record, and two `detail` values that differ by which side of the
            # boundary you read them on is how the next reader gets this wrong. One
            # value, the safe one; the detail is on stderr right above it.
            print("broker: request %s refused: %s: %s"
                  % (rid, type(e).__name__, e), file=sys.stderr)
            outcome = {"request_id": rid, "classification": "refused_request",
                       "detail": EXCEPTION_DETAIL_REFUSED_REQUEST}
            # FINDING 1, DEFENSE IN DEPTH (post-Task-6 review): _execute already
            # swallows its own final _write_result failure (see its own comment) so
            # this branch should never see a request_id that already has a result on
            # disk. But this is exactly the kind of guarantee that must be structural,
            # not just "the one call site we checked happens to uphold it" — a future
            # refactor of _execute's tail, or any other path that reaches here after
            # already having written a result, must not get to overwrite a possibly
            # TRUE result ("a mutation landed") with a possibly FALSE one
            # ("refused_request" / exit_code=2, which asserts nothing was mutated).
            # spool_lib.write_result performs an unconditional os.replace with no
            # already-written guard of its own, so that check belongs here.
            if os.path.isfile(S.result_path(rid, spool)):
                print("broker: request %s already has a result on disk; NOT "
                      "overwriting it with a refused_request derived from: %s"
                      % (rid, e), file=sys.stderr)
            else:
                _write_result(rid, spool, "refused_request", "refused", 2,
                              EXCEPTION_DETAIL_REFUSED_REQUEST, now)
        outcomes.append(outcome)
        _discard(path)
    return outcomes


def _process(req, spool, projects, pending_count, runner, now):
    """One locked request. Refuses before any side effect that could reach Google."""
    rid, slug, cid = req["request_id"], req["client"], req["changeset"]

    if C.seen_contains(slug, rid):
        detail = "request_id %s has already been accepted — replay refused" % rid
        _write_result(rid, spool, "refused_replay", "refused", 2, detail, now)
        return {"request_id": rid, "classification": "refused_replay", "detail": detail}

    rec = vault_lib.resolve(slug)                       # unknown slug raises -> refusal
    quotas = C.read_spool_quotas(projects, rec["project"])
    decision = classify(req, quotas, pending_count, _accepted_today(slug, now), now)
    if not decision.accept:
        _write_result(rid, spool, decision.classification, "refused", 2,
                      decision.detail, now)
        return {"request_id": rid, "classification": decision.classification,
                "detail": decision.detail}

    # Accepted. Burn the id BEFORE acting: if the process dies here the request is
    # refused as a replay, which costs a re-request. The opposite ordering costs a
    # duplicate account change.
    C.append_seen(slug, rid, now)
    return _execute(req, spool, runner, now)


# Exit semantics are load-bearing and must not be collapsed (spec §12):
#   0 success · 1 usage · 2 pre-flight refusal (NOTHING was mutated) · 3 failure after
#   at least one live mutation landed.
# An unrecognised code is treated as a FAILURE, never as a success: the only safe
# reading of "the executor did something we do not understand" is that it may have
# touched the account.
CLASSIFICATION_BY_RC = {
    0: ("accepted_applied", "applied"),
    1: ("refused_usage", "refused"),
    2: ("refused_preflight", "refused"),
    3: ("failed_after_mutation", "failed"),
}
UNKNOWN_RC = ("failed_unknown_exit", "failed")

# Fixed, non-identifying detail strings. The executor's stdout is DELIBERATELY not
# copied into the spool result: the spool is Hermes-readable, and per-action resource
# names are exactly what §17.3 keeps out of Hermes's reach. The full executor output
# goes to the broker's own stderr, which is host-side and lands in the journal.
DETAIL_BY_CLASSIFICATION = {
    "accepted_applied": "the change-set was applied",
    "refused_usage": "the executor refused with a usage error; nothing was mutated",
    "refused_preflight": "a guard refused before any mutation; nothing was mutated",
    "failed_after_mutation": "the apply failed AFTER at least one live mutation landed "
                             "— an operator must reconcile this run",
    "failed_unknown_exit": "the executor exited with an unrecognised status; treat the "
                           "account as possibly modified",
}

# S6. The same policy, extended to the two sites that were bypassing it.
#
# drain()'s per-request handler wrote `str(e)` into the spool, and _execute's
# reserve_approval failure wrote `"approval unavailable: %s" % e` — both reach
# _write_result, i.e. the Hermes-readable spool, forty lines below the comment above
# declaring that output is deliberately kept out of it. A comment asserting a guarantee
# the adjacent code does not provide is the defect class this capsule has hit repeatedly.
#
# What those exceptions can carry is not hypothetical. OSError renders strerror plus the
# FILENAME it failed on, which on these paths is a host governance-store path; the
# KeyError from vault_lib.resolve carries a client slug; reserve_approval's ValueErrors
# describe approval-store state. Structurally the SAME defect as Task 2's Important #2
# (raw exception text interpolated into model-facing refusal output), which was fixed in
# hermes-syscall.py and never on this side of the same seam.
#
# Same remedy, same shape as that fix: fixed vocabulary to the spool, FULL detail to
# stderr — host-side, lands in the journal. classification, status and exit_code are
# UNCHANGED; only the human-readable text is.
#
# Deliberately NOT folded into DETAIL_BY_CLASSIFICATION above. _parse_all's rejection
# path also writes classification "refused_request", but with a spool_lib SpoolRefused
# message describing the agent's OWN malformed request file ("filename does not match
# request_id") — that is legitimate feedback about data Hermes itself wrote, not host
# state, and keying off the classification would either destroy it or wrongly tell that
# path's reader to go looking in the journal. Two sites, two constants, no conflation.
EXCEPTION_DETAIL_REFUSED_REQUEST = (
    "the request was refused before execution; nothing was mutated. The specific reason "
    "is recorded host-side in the broker's journal, not here")
EXCEPTION_DETAIL_REFUSED_APPROVAL = (
    "the approval for this change-set could not be reserved, so it was not executed; "
    "nothing was mutated. The specific reason is recorded host-side in the broker's "
    "journal, not here")
# FINDING 2 fix (post-Task-6 review): DETAIL_BY_CLASSIFICATION[classification] was a
# raw subscript. It cannot KeyError today because CLASSIFICATION_BY_RC/UNKNOWN_RC only
# ever produce classifications with a matching entry above — but if a future edit adds
# an rc mapping without a matching detail entry, that KeyError would be caught by
# drain()'s per-request except tuple (it includes KeyError — see that tuple's own
# comment for why) and rendered as a governance-looking "refused_request", exactly
# what R12 forbids: a broker defect must fail loudly, never be laundered into what
# looks like a guard's decision. Made total with .get() and a hedged fallback instead,
# so a future mapping gap can never raise here at all.
_DETAIL_FALLBACK = ("no detail text is registered for this classification — treat the "
                    "account as possibly modified and reconcile manually")


def _run_subprocess(argv):
    """Run the mutation wrapper. argv is a LIST — there is no shell here, and no
    request field is ever part of the program name or an option name."""
    p = subprocess.run(argv, capture_output=True, text=True,
                       timeout=RUNNER_TIMEOUT_SECONDS)
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def _execute(req, spool, runner, now):
    rid, slug, cid = req["request_id"], req["client"], req["changeset"]

    # RESERVE FIRST. Not after success — a crash between the mutations landing and the
    # mark being written would otherwise leave the approval live and the same
    # change-set applicable a second time (spec §7).
    try:
        C.reserve_approval(slug, cid, rid, now)
    except (ValueError, OSError) as e:
        # S6: full reason host-side, fixed text to the spool. An OSError here renders
        # the governance-store path it failed on, which the agent must not learn from a
        # refusal it can provoke.
        print("broker: request %s client %s changeset %s — approval unavailable: %s: %s"
              % (rid, slug, cid, type(e).__name__, e), file=sys.stderr)
        detail = EXCEPTION_DETAIL_REFUSED_APPROVAL
        _write_result(rid, spool, "refused_approval", "refused", 2, detail, now)
        return {"request_id": rid, "classification": "refused_approval", "detail": detail}

    argv = [MUTATE_SH, "--client", slug, "--changeset", cid, "--request", rid]
    timed_out = False
    try:
        rc, output = runner(argv)
    except subprocess.TimeoutExpired:
        # A timeout may have left mutations in flight. It is not a refusal.
        rc, output = 3, "executor exceeded %ds" % RUNNER_TIMEOUT_SECONDS
        timed_out = True

    classification, status = CLASSIFICATION_BY_RC.get(rc, UNKNOWN_RC)
    # Host-side only. Never into the spool.
    print("broker: request %s client %s changeset %s rc=%d\n%s"
          % (rid, slug, cid, rc, output), file=sys.stderr)
    try:
        C.record_outcome(slug, cid, classification, now)
    except (ValueError, OSError) as e:
        print("broker: could not record outcome for %s: %s" % (cid, e), file=sys.stderr)

    if timed_out:
        # RIDER fix (post-Task-6 review): rc=3 from a real executor exit and rc=3
        # synthesised here from a timeout both map to classification
        # "failed_after_mutation", but they are not equally certain. The fixed detail
        # text for that classification asserts AS FACT that "the apply failed AFTER
        # at least one live mutation landed" — true for a genuine executor rc=3, but
        # overclaiming for a timeout, where (per the comment two lines above) a
        # mutation only MAY have been left in flight. classification/status/exit_code
        # are UNCHANGED (still failed_after_mutation/failed/3, the correct
        # fail-closed reading) — only the human-readable text is hedged, in the same
        # style as UNKNOWN_RC's "treat the account as possibly modified".
        detail = ("the executor exceeded its %ds timeout; a mutation MAY have been "
                  "left in flight — treat the account as possibly modified and "
                  "reconcile manually" % RUNNER_TIMEOUT_SECONDS)
    else:
        detail = DETAIL_BY_CLASSIFICATION.get(classification, _DETAIL_FALLBACK)

    try:
        _write_result(rid, spool, classification, status, rc, detail, now)
    except OSError as e:
        # FINDING 1 fix (post-Task-6 review): this write is the LAST thing _execute
        # does, after the mutation may already have landed and after record_outcome
        # has already run. If it raises (disk full, transient I/O, ...), letting it
        # propagate hands the exception to drain()'s per-request except tuple, which
        # would write a SECOND result for this request_id: classification
        # "refused_request", status "refused", exit_code 2. Under spec §12, exit_code
        # 2 is a GUARANTEE that nothing was mutated — a false guarantee here, exactly
        # the mirror image of the false-success path this module already guards
        # against, just in the refusal direction instead. Governance state is not at
        # risk either way (the approval is already dead via reserve_approval, so no
        # duplicate mutation is possible) — what is at risk is what an operator or a
        # future agent reconciles the spool against. A MISSING result is honest: the
        # spool client already treats absence as PENDING, which is recoverable. A
        # WRONG result is not. So: log the failure and the payload that could not be
        # written, to stderr, and swallow it here — this exception must never reach
        # drain()'s except tuple.
        print("broker: FAILED to write result for %s (classification=%s status=%s "
              "exit_code=%d detail=%r): %s — the spool result is MISSING, not wrong; "
              "reconcile from the governance store and this stderr line"
              % (rid, classification, status, rc, detail, e), file=sys.stderr)
    return {"request_id": rid, "classification": classification, "exit_code": rc}


def watch(spool, projects, interval):
    """Poll the spool forever. Deliberately a poll rather than inotify: one dependency
    fewer, portable to macOS for local testing, and a few seconds of latency on a path
    whose slowest step is a human approval is not worth a platform-specific watcher.

    A single exception must never kill the broker — a dead broker is a silently
    unprocessed queue, which looks exactly like an idle one.
    """
    while True:
        try:
            drain(spool=spool, projects=projects)
        except Exception as e:                       # noqa: BLE001 — see docstring
            print("broker: drain failed: %s" % e, file=sys.stderr)
        time.sleep(interval)


def _positive_seconds(value):
    """argparse type= for --interval. RULING (post-Task-7 review, Finding 2): a
    non-positive interval must be rejected at PARSE time, before watch()'s loop ever
    starts. --interval 0 would spin drain() back-to-back with no pacing on a
    privileged daemon; --interval -1 would reach time.sleep(-1) on the FIRST
    iteration, which raises ValueError from OUTSIDE watch()'s own try/except (that
    block only guards the drain() call, deliberately, since a stuck drain is the
    failure mode it exists for) — crashing with a raw traceback after one drain pass
    had already run. Raising ArgumentTypeError here instead gives argparse's own
    clean usage-error path: a message on stderr and exit(2), with no drain and no
    traceback, regardless of --once/--watch."""
    try:
        f = float(value)
    except ValueError:
        raise argparse.ArgumentTypeError("%r is not a number" % value)
    if f <= 0:
        raise argparse.ArgumentTypeError(
            "--interval must be positive (got %r): 0 spins the drain loop with no "
            "pacing on a privileged daemon, and a negative value crashes time.sleep "
            "on the first iteration" % value)
    return f


def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="hermes-broker",
        description="Drain the mutation request spool. Host-side; holds the write "
                    "credential's directory but never its value.")
    ap.add_argument("--once", action="store_true", help="one drain pass, then exit")
    ap.add_argument("--watch", action="store_true", help="poll forever")
    ap.add_argument("--interval", type=_positive_seconds, default=5.0)
    ap.add_argument("--spool")
    ap.add_argument("--projects")
    args = ap.parse_args(argv)

    if args.once == args.watch:
        print("hermes-broker: pass exactly one of --once or --watch", file=sys.stderr)
        return 1

    spool = args.spool or S.spool_root()
    projects = args.projects or C.registry_projects_path()
    if args.watch:
        watch(spool, projects, args.interval)
        return 0
    for outcome in drain(spool=spool, projects=projects):
        print(json.dumps(outcome, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
