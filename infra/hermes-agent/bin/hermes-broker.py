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
import argparse, collections, datetime, errno, fcntl, os, subprocess, sys, time

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
    governance-store seen-set. Fail-closed: an unreadable seen-set raises."""
    p = governance_lib.seen_path(slug)
    if not os.path.exists(p):
        return 0
    day = _utcday(now)
    n = 0
    try:
        with open(p, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and ('"seen_at": "%s' % day) in line:
                    n += 1
    except OSError as e:
        raise ValueError("unreadable seen-set for %r: %s" % (slug, e))
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
    try:
        os.unlink(path)
    except OSError as e:
        if e.errno != errno.ENOENT:
            raise


def _scan(spool):
    """Return (names, overflow). Only names matching the request-file pattern; a
    dot-prefixed temp file from a half-written request cannot match."""
    d = S.requests_dir(spool)
    if not os.path.isdir(d):
        return [], False
    names = sorted(n for n in os.listdir(d) if S.FILENAME_RE.fullmatch(n))
    return names[:MAX_SPOOL_FILES], len(names) > MAX_SPOOL_FILES


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
        except NotImplementedError as e:
            # Task 5 leaves _execute (and _run_subprocess) stubbed; Task 6 fills them
            # in. A request that reaches this point has ALREADY been accepted and
            # burned in the seen-set by _process — C.append_seen runs strictly before
            # _execute is called — so that side effect is real and correct and must
            # stand even though execution itself could not happen yet. This is not a
            # validation refusal, so it gets its own classification rather than being
            # mislabeled "refused_request", and it is logged LOUDLY: once Task 6 lands,
            # this branch should never be reachable again, and silence here would
            # otherwise hide a broker that is quietly unable to execute anything.
            outcome = {"request_id": rid, "classification": "refused_not_implemented",
                       "detail": str(e)}
            print("hermes-broker: %s for request %s (client %s) — Task 6's execution "
                  "path is not installed yet; the request_id was already burned in "
                  "the seen-set before this raised, so no replay of it is possible, "
                  "but nothing was executed and no approval was reserved or consumed"
                  % (e, rid, slug), file=sys.stderr)
            _write_result(rid, spool, "refused_not_implemented", "refused", 2, str(e), now)
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
