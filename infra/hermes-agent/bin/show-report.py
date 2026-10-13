#!/usr/bin/env python3
"""Print one client's figures report to the operator. Stdlib only.

  sudo show-report <client> [--latest | --ts YYYY-MM-DD_HH-MM-SS | --list]

The report store is root's, but every name below it is still reached with open_dir_below and
opened O_NOFOLLOW: a planted symlink is never followed."""
import argparse, os, stat, sys
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import client_audit_lib as L
import report_lib as RL
import vault_lib as V

ARCHIVE = RL.ARCHIVE


def safe_text(text):
    """What the operator's terminal may receive: report_lib.display_text (controls, format characters
    and line/paragraph separators dropped). A report quotes search terms, which an outsider controls."""
    return RL.display_text(text)


def main(argv=None, root="/"):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0], allow_abbrev=False)
    ap.add_argument("client")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--latest", action="store_true")
    g.add_argument("--ts")
    g.add_argument("--list", action="store_true")
    a = ap.parse_args(argv)
    root = root.rstrip("/")
    try:
        V.validate_slug(a.client)
        if a.ts is not None and not L.TS_RE.fullmatch(a.ts):
            raise ValueError("invalid --ts")
    except ValueError as e:
        print(f"show-report: refused: {e}", file=sys.stderr); return 2
    try:
        fd = L.open_dir_below(root + ARCHIVE, (a.client,))
    except L.UnsafePathError as e:
        print(f"show-report: refused: {e}", file=sys.stderr); return 2
    except OSError as e:
        print(f"show-report: {type(e).__name__}", file=sys.stderr); return 1
    if fd is None:
        print("show-report: no reports for this client", file=sys.stderr); return 1
    try:
        tss = RL.list_report_ts(fd)
        if a.list:
            print("\n".join(tss)); return 0
        ts = a.ts or (tss[-1] if tss else None)
        if ts is None or ts not in tss:
            print("show-report: no such report", file=sys.stderr); return 1
        ffd = os.open(f"{ts}-report.md", os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
    except OSError as e:
        print(f"show-report: {type(e).__name__}", file=sys.stderr); return 1
    finally:
        os.close(fd)
    with os.fdopen(ffd, encoding="utf-8", errors="replace", newline="") as f:   # keep \r: it is stripped
        if not stat.S_ISREG(os.fstat(ffd).st_mode):
            print("show-report: not a regular file", file=sys.stderr); return 1
        sys.stdout.write(safe_text(f.read()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
