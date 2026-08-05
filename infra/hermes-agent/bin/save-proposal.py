#!/usr/bin/env python3
"""Persist an improvement proposal to Hermes state (proposal read from stdin).

Deterministic persistence so the proposer skill never relies on the LLM to
write files. Reads proposal markdown from stdin, writes it to
$PROPOSALS_DIR/<project>/<UTC-timestamp>.md, and prints the written path.

Usage:  echo "<proposal md>" | save-proposal.py --project claude_google_ads
Env:    PROPOSALS_DIR  base dir (default /opt/data/proposals)
"""
import argparse
import os
import re
import sys
from datetime import datetime, timezone


def slug(s):
    return re.sub(r"[^a-z0-9_-]+", "-", s.strip().lower()).strip("-") or "unknown"


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", required=True)
    ap.add_argument("--now", help="override UTC timestamp (ISO-ish) for tests")
    args = ap.parse_args(argv)

    content = sys.stdin.read()
    if not content.strip():
        print("save-proposal: empty proposal on stdin; nothing written", file=sys.stderr)
        return 1

    base = os.environ.get("PROPOSALS_DIR", "/opt/data/proposals")
    # --now is a test hook; slug it so a path-like value can't escape dest_dir.
    ts = slug(args.now) if args.now else datetime.now(timezone.utc).strftime("%Y-%m-%d_%H-%M-%S")
    dest_dir = os.path.join(base, slug(args.project))
    os.makedirs(dest_dir, exist_ok=True)
    dest = os.path.join(dest_dir, f"{ts}.md")
    with open(dest, "w") as f:
        f.write(content)
    print(dest)
    return 0


if __name__ == "__main__":
    sys.exit(main())
