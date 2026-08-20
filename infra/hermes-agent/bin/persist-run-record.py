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
    except (ValueError, KeyError, OSError, TypeError) as e:
        print("persist-run-record: %s" % e, file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
