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
import argparse, collections, datetime, fcntl, os, subprocess, sys, time

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
    # the for-loop moves on to the next name. That isolation deliberately does NOT
    # extend to NotImplementedError — Task 5 leaves _execute/_run_subprocess stubbed to
    # raise it on purpose (RULING R12: "not built yet" must propagate loudly, not be
    # laundered into a refusal that looks like a guard decision), so today an accepted
    # request DOES still abort the remainder of this loop when it reaches the stub.
    # That is an accepted, temporary consequence of Task 5's scope, not a design goal.
    # TASK 6: when _execute stops being a stub, whatever exception types a real
    # subprocess invocation and its bookkeeping can actually raise MUST be added to
    # this except clause (or handled inside _execute itself) — otherwise a single
    # unlucky live request (a timeout, a transient I/O error, an unexpected exit
    # shape) reintroduces exactly the batch-starvation failure mode this comment is
    # warning against, just with a real subprocess involved instead of a stub.
    for name, req in parsed:
        rid, slug, cid = req["request_id"], req["client"], req["changeset"]
        path = os.path.join(S.requests_dir(spool), name)
        try:
            with _ClientLock(slug):
                outcome = _process(req, spool, projects, pending[slug], runner, now)
        except (ValueError, KeyError, OSError) as e:
            outcome = {"request_id": rid, "classification": "refused_request",
                       "detail": str(e)}
            _write_result(rid, spool, "refused_request", "refused", 2, str(e), now)
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


def _run_subprocess(argv):
    raise NotImplementedError("Task 6")


def _execute(req, spool, runner, now):
    raise NotImplementedError("Task 6")


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true",
                     help="run a single drain pass and exit (Task 6 adds the loop)")
    ap.parse_args(argv)
    outcomes = drain()
    for o in outcomes:
        print(o.get("classification", "?"), o.get("request_id", ""), file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
