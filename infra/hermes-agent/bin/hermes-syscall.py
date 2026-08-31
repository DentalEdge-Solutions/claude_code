#!/usr/bin/env python3
"""The in-container mutation syscall client. Stdlib-only.

DELIBERATELY DUMB. It does exactly two things: write a well-formed request into the
spool, and read back a result. It holds no credential, performs no network I/O, and
contains NO POLICY — its power is bounded entirely by what the broker accepts. Anything
it could decide would be a decision a model could influence.

It exposes `apply` only. There is no `undo` subcommand and there must never be one:
undo deliberately bypasses the kill switch and the daily caps so that cleanup is never
blocked by the switch that stopped the damage, and it requires no approval. A
Hermes-callable undo would be an unapproved account change on demand (spec §17.2).

It never re-interprets the broker's classification. In particular a refusal is never
rendered as an error that looks retryable, because a model that retries a refusal is a
model applying pressure to a guard (spec §12).

Invoked in-container as:  python3 /opt/cc-bin/hermes-syscall.py apply --client <slug> --changeset <id>
"""
import argparse, json, os, sys, tempfile, uuid

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import spool_lib as S

# Exit codes. `4` is NOT an error: it means the broker has not written a result yet,
# which is a different event from a refusal and must never collapse into one.
EXIT_OK, EXIT_USAGE, EXIT_REFUSED, EXIT_FAILED_AFTER_MUTATION, EXIT_PENDING = 0, 1, 2, 3, 4

_EXIT_BY_CODE = {0: EXIT_OK, 2: EXIT_REFUSED, 3: EXIT_FAILED_AFTER_MUTATION}


def submit(client, changeset, root=None):
    """Write one request atomically and return its request_id.

    The temp file is excluded from the broker's FILENAME_RE scan by tempfile.mkstemp's
    own naming, not by the dot prefix: mkstemp always inserts its own random 8-character
    infix between prefix and suffix, and keeps the ".tmp" suffix, so the resulting name
    can never fullmatch FILENAME_RE, which demands exactly 36 characters before ".json"
    and nothing else. A broker that picked up a half-written request would be reading
    torn JSON from the one writer it does not trust. The dot prefix is defence in depth
    on top of that guarantee — it keeps the temp file out of shell globs and casual
    directory listings, not out of the broker's regex.
    """
    request_id = str(uuid.uuid4())
    req = {"request_id": request_id, "op": "apply",
           "client": client, "changeset": changeset}
    # Validate our own output against the BROKER's validator before writing. If these
    # two ever disagree about what a request is, the disagreement should surface here
    # and not as an unexplained refusal in a log the operator has to go find.
    S.validate_request(req, "%s.json" % request_id)

    d = S.requests_dir(root)
    os.makedirs(d, exist_ok=True)
    path = os.path.join(d, "%s.json" % request_id)
    fd, tmp = tempfile.mkstemp(dir=d, prefix=".%s." % request_id, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(req, f, sort_keys=True)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    return request_id


def fetch(request_id, root=None):
    """Return (exit_code, text). Absent result => PENDING, never a refusal."""
    path = S.result_path(request_id, root)
    if not os.path.isfile(path):
        return EXIT_PENDING, ("pending: the broker has not written a result for %s yet. "
                              "This is not a refusal — a refusal always writes a result "
                              "file." % request_id)
    try:
        with open(path, encoding="utf-8") as f:
            rec = json.load(f)
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as e:
        # NEVER interpolate the raw exception into model-facing output. An OSError's
        # strerror or a UnicodeDecodeError's repr can carry arbitrary wording or bytes
        # (errno EAGAIN renders as "Resource temporarily unavailable" — exactly the
        # retry-flavoured text this client exists to refuse to say) or embed raw byte
        # values, and results/ lives inside the spool Hermes can write to: a planted
        # unreadable result is an adversarial way to get this client to inject its own
        # retry-inviting wording. The exception detail goes to stderr only, for an
        # operator or journal — mirroring how the broker keeps executor output
        # host-side — never into the exit-2 text a model reads.
        print("hermes-syscall: result %s unreadable: %s" % (request_id, e),
              file=sys.stderr)
        return EXIT_REFUSED, (
            "request %s\n"
            "  status         refused\n"
            "  classification result_unreadable\n"
            "  detail         the result file exists but could not be read as valid "
            "JSON; this is a refusal, not a pending state — an operator must inspect "
            "the result file directly" % request_id)
    if not isinstance(rec, dict):
        return EXIT_REFUSED, "malformed result for %s" % request_id

    # Surfaced VERBATIM. No re-wording, no severity re-grading, no advice about what to
    # do next — the broker's classification is the answer.
    status = rec.get("status", "?")
    classification = rec.get("classification", "?")
    code = rec.get("exit_code")
    lines = ["request %s" % request_id,
             "  status         %s" % status,
             "  classification %s" % classification,
             "  exit_code      %s" % code]
    if rec.get("detail"):
        lines.append("  detail         %s" % rec["detail"])
    # S6-M1: `_EXIT_BY_CODE.get(code, ...)` on a code read straight out of the result
    # FILE. results/ lives inside the spool — the one tree Hermes can write — so an
    # attacker-planted "exit_code": [] or {} made this raise TypeError: unhashable
    # type. main() catches SpoolRefused and OSError, not TypeError, so it escaped as a
    # raw traceback and exit 1: a crash, reported with the code that means "your
    # arguments were wrong", provokable by writing one file.
    #
    # Guarded by TYPE, not by try/except, so the fail-closed reading is stated rather
    # than inferred: the mapping's keys are ints, and anything that is not an int is
    # not a broker exit code. It gets EXIT_REFUSED, the same answer an unrecognised
    # integer already got. bool is an int subclass and needs no special case — True
    # would look up key 1, which is not in the mapping, and land on EXIT_REFUSED too.
    #
    # The rendered line above is left VERBATIM on purpose: this client surfaces the
    # broker's record without re-wording it, and a planted value being visible to the
    # operator exactly as written is the point.
    if not isinstance(code, int):
        return EXIT_REFUSED, "\n".join(lines)
    return _EXIT_BY_CODE.get(code, EXIT_REFUSED), "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="hermes-syscall",
        description="Request application of an OPERATOR-AUTHORED, OPERATOR-APPROVED "
                    "change-set. This client cannot author a change-set, cannot approve "
                    "one, and cannot undo one.")
    sub = ap.add_subparsers(dest="cmd", required=True)

    a = sub.add_parser("apply", help="file a request to apply an approved change-set")
    a.add_argument("--client", required=True)
    a.add_argument("--changeset", required=True)

    r = sub.add_parser("result", help="read the broker's result for a request")
    r.add_argument("--request-id", dest="request_id", required=True)

    try:
        args = ap.parse_args(argv)
    except SystemExit:
        return EXIT_USAGE

    try:
        if args.cmd == "apply":
            print(submit(args.client, args.changeset))
            return EXIT_OK
        code, text = fetch(args.request_id)
        print(text)
        return code
    except S.SpoolRefused as e:
        # A genuine usage error: SpoolRefused off this path means the --client or
        # --changeset the caller supplied is not a well-formed identifier. Re-crafting
        # the arguments is the correct response, and exit 1 is what says so.
        print("hermes-syscall: %s" % e, file=sys.stderr)
        return EXIT_USAGE
    except OSError as e:
        # NOT a usage error, and it used to share exit 1 with one. An OSError here is
        # the spool being absent, read-only, or full — an ENVIRONMENT failure the
        # caller's arguments had nothing to do with. Exit 1 told a model its arguments
        # were wrong, so the only response it invites is to re-craft them and try
        # again: pointless work, and pressure applied to a rail that is simply down.
        #
        # EXIT_REFUSED, because it is TRUE here in the sense spec §12 gives it: exit 2
        # guarantees nothing was mutated, and on this path the request never reached
        # the spool at all, let alone the broker. Deliberately not a new exit code —
        # the 0/1/2/3/4 set is the documented contract this client shares with the
        # broker and the spec, and inventing a sixth value to describe an unreachable
        # spool is a contract change, not a bug fix.
        #
        # The raw exception goes to stderr only, never into the model-facing text,
        # exactly as the unreadable-result path above does: an errno's strerror is
        # arbitrary wording the caller does not control ("Resource temporarily
        # unavailable" is retry-flavoured text this client exists to refuse to say).
        print("hermes-syscall: %s: %s" % (type(e).__name__, e), file=sys.stderr)
        print("  status         refused\n"
              "  classification spool_unavailable\n"
              "  detail         the request spool could not be reached, so nothing was "
              "filed and nothing was mutated. This is not a rejected argument and "
              "re-sending it will not help; an operator must inspect the host.")
        return EXIT_REFUSED


if __name__ == "__main__":
    sys.exit(main())
