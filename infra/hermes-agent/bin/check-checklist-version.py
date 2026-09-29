#!/usr/bin/env python3
"""Refuse a change to the security-review checklist that does not raise its `version:`.

  python3 bin/check-checklist-version.py --base <ref> [--repo <dir>]

A PASS report cites the checklist by version, so a version must name exactly one text:
two different checklists both called "1.5" would leave a signed report ambiguous about
what the reviewer judged. (The box fingerprint is not the gap. Its `code` component
hashes the git tree of deploy/, which contains the checklist, so ANY edit already
changes the fingerprint. This check keeps the version honest.)

Compares CHECKLIST.md at <base> with HEAD, both as committed. Versions compare
numerically ("1.10" > "1.9"). Exit 0: unchanged, raised, or new at HEAD. Exit 1: changed
without raising the version, or deleted. Exit 2: cannot check (unknown base, no version
line) — fail closed.
"""
import argparse, re, subprocess, sys

REL = "infra/hermes-agent/deploy/security-review/CHECKLIST.md"


class CannotCheck(Exception):
    pass


def show(repo, ref):
    """The checklist at ref, or None when ref exists but the file does not."""
    ok = subprocess.run(["git", "-C", repo, "cat-file", "-e", f"{ref}^{{commit}}"], capture_output=True)
    if ok.returncode != 0:
        raise CannotCheck(f"unknown ref {ref!r}")
    p = subprocess.run(["git", "-C", repo, "show", f"{ref}:{REL}"], capture_output=True, text=True)
    return p.stdout if p.returncode == 0 else None


def version(text, where):
    for line in text.splitlines():
        m = re.match(r"^version:\s*(\d+(?:\.\d+)*)\s*$", line)
        if m:
            return tuple(int(x) for x in m.group(1).split(".")), m.group(1)
    raise CannotCheck(f"no `version: N.N` line in the checklist at {where}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", required=True)
    ap.add_argument("--repo", default=".")
    a = ap.parse_args()
    try:
        old, new = show(a.repo, a.base), show(a.repo, "HEAD")
        if new is None:
            if old is None:
                print("checklist-version: no checklist at base or HEAD — nothing to check")
                return 0
            print(f"checklist-version: {REL} deleted", file=sys.stderr)
            return 1
        new_v, new_s = version(new, "HEAD")
        if old is None:
            print(f"checklist-version: checklist new at HEAD (version {new_s})")
            return 0
        if old == new:
            print(f"checklist-version: unchanged (version {new_s})")
            return 0
        old_v, old_s = version(old, a.base)
        if new_v <= old_v:
            print(f"checklist-version: {REL} changed without raising `version:` "
                  f"(base {old_s}, HEAD {new_s}). Raise it: every signed report cites a version, "
                  f"and a version must name one text.", file=sys.stderr)
            return 1
        print(f"checklist-version: changed, version raised {old_s} -> {new_s}")
        return 0
    except CannotCheck as e:
        print(f"checklist-version: cannot check: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
