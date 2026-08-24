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

    The temp file is DOT-PREFIXED so it cannot match the broker's FILENAME_RE scan: a
    broker that picked up a half-written request would be reading torn JSON from the
    one writer it does not trust.
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
        return EXIT_REFUSED, "unreadable result for %s: %s" % (request_id, e)
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
        print("hermes-syscall: %s" % e, file=sys.stderr)
        return EXIT_USAGE
    except OSError as e:
        print("hermes-syscall: %s" % e, file=sys.stderr)
        return EXIT_USAGE


if __name__ == "__main__":
    sys.exit(main())
