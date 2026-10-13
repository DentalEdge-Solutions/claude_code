#!/usr/bin/env python3
"""The `store` step of a figures run (run by root; design 2026-10-13, Part 1). Stdlib only.

  report-store.py --client S --ts T --reports-dir D --archive A --registry R --reader N [--reader N ...]

Joins this run's reader reports and stores them as one document. Before anything is written the
document is checked for another client's name: a hit stores nothing and exits ISOLATION_RC.
Exit 0 stored, 1 failed. Human lines on stderr, in fixed words: never a report's text."""
import argparse, os, re, sys
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import report_lib as RL
import vault_lib as V

OWNER_UID = 0          # tests override
_READER_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0], allow_abbrev=False)
    for name in ("--client", "--ts", "--reports-dir", "--archive", "--registry"):
        ap.add_argument(name, required=True)
    ap.add_argument("--reader", action="append", required=True)
    a = ap.parse_args(argv)
    if not all(_READER_RE.fullmatch(x) for x in a.reader):
        ap.error("--reader must be a lower-case name")
    if len(set(a.reader)) != len(a.reader):
        ap.error("--reader given twice for one name")
    try:
        text = RL.read_reports(a.reports_dir, a.client, tuple(a.reader))
        hits = RL.isolation_hits(text, a.client, V.load_registry(a.registry))
        if hits:
            print(f"report-store: ASSERTION FAIL: the reports name {hits} other client(s); nothing stored",
                  file=sys.stderr)
            return RL.ISOLATION_RC
        rel = RL.store(a.archive, a.client, a.ts, text, owner_uid=OWNER_UID)
    except RL.ReportError as e:
        print(f"report-store: refused: {e}", file=sys.stderr)
        return 1
    except (OSError, ValueError) as e:
        print(f"report-store: failed: {type(e).__name__}", file=sys.stderr)
        return 1
    except Exception as e:                 # KeyboardInterrupt and SystemExit still propagate
        print(f"report-store: failed: unexpected {type(e).__name__}", file=sys.stderr)
        return 1
    print(f"report-store: stored {os.path.basename(rel)}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
