#!/usr/bin/env python3
"""CLI: read executor stdout on stdin, persist the run record into the client vault."""
import argparse, sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import persist_run_record_shim as P
import vault_lib


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--client", required=True)
    args = ap.parse_args(argv)
    text = sys.stdin.read()
    sys.stdout.write(text)          # pass the executor's output through, unchanged
    res = P.parse_result(text)
    if res is None:
        return 0                    # a refusal emits no result line; that is not an error here
    try:
        rec = vault_lib.resolve(args.client)
        P.persist(rec["vault_path"], res)
    # NotImplementedError (S1-M1): this is what Python raises when a dir_fd argument
    # cannot be honoured, and persist() is built entirely out of dir_fd calls. The
    # shim's import-time guard should make it unreachable, but "unreachable" is what
    # this handler exists for — without it the exception escaped as a raw TRACEBACK and
    # exit 1, which reads as a crash rather than the fail-closed refusal it is. Every
    # other failure on this path is exit 2 with one line on stderr; so is this one now.
    except (ValueError, KeyError, OSError, TypeError, NotImplementedError) as e:
        print("persist-run-record: %s: %s" % (type(e).__name__, e), file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
