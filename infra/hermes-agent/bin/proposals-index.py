#!/usr/bin/env python3
"""List / open Hermes improvement proposals (read-only).

Usage:
  proposals-index.py                 # list all (newest first)
  proposals-index.py --project NAME  # filter to one project
  proposals-index.py --open PATH     # print one proposal's content
  proposals-index.py --json          # machine-readable list
Env:  PROPOSALS_DIR  base dir (default /opt/data/proposals)
"""
import argparse
import json
import os
import sys


def summary_of(path):
    try:
        lines = open(path).read().splitlines()
    except Exception:
        return ""
    for i, ln in enumerate(lines):
        if ln.strip().lower().startswith("## summary"):
            for nxt in lines[i + 1:]:
                if nxt.strip():
                    return nxt.strip()
    for ln in lines:
        if ln.strip() and not ln.startswith("#"):
            return ln.strip()
    return ""


def collect(base, project=None):
    rows = []
    if not os.path.isdir(base):
        return rows
    projects = [project] if project else sorted(os.listdir(base))
    for proj in projects:
        pdir = os.path.join(base, proj)
        if not os.path.isdir(pdir):
            continue
        for fn in sorted(os.listdir(pdir), reverse=True):
            if fn.endswith(".md"):
                path = os.path.join(pdir, fn)
                rows.append({"project": proj, "timestamp": fn[:-3],
                             "path": path, "summary": summary_of(path)})
    return rows


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--project")
    ap.add_argument("--open")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    base = os.environ.get("PROPOSALS_DIR", "/opt/data/proposals")

    if args.open:
        if not os.path.isfile(args.open):
            print(f"proposals-index: not found: {args.open}", file=sys.stderr)
            return 1
        sys.stdout.write(open(args.open).read())
        return 0

    rows = collect(base, args.project)
    if args.json:
        print(json.dumps(rows, indent=2))
        return 0
    if not rows:
        print("No proposals yet.")
        return 0
    for r in rows:
        print(f"[{r['project']}] {r['timestamp']}")
        print(f"    {r['summary']}")
        print(f"    {r['path']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
