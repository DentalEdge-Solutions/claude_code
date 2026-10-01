#!/usr/bin/env python3
"""Print one client's audit draft to the operator (Option B §2). Stdlib only.

  sudo show-audit <client> [--latest | --ts YYYY-MM-DD_HH-MM-SS | --list]

The vault is uid 10000's, so every name below /var/lib/hermes/vaults is reached with
open_dir_below and opened O_NOFOLLOW: a planted symlink is never followed by root."""
import argparse, os, re, stat, sys
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import client_audit_lib as L
import vault_lib as V

VAULTS = "/var/lib/hermes/vaults"
# The draft is model output steered by attacker-controlled search terms: never let it drive the
# operator's terminal. C0 controls except newline and tab (ESC, BEL, CR, BS, NUL...), DEL, and the
# C1 range (U+0080-U+009F: some terminals take U+009B as CSI) are dropped.
_CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f-\x9f]")


def safe_text(text):
    return _CONTROL.sub("", text)


def main(argv=None, root="/"):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("client")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--latest", action="store_true")
    g.add_argument("--ts")
    g.add_argument("--list", action="store_true")
    a = ap.parse_args(argv)
    root = root.rstrip("/")
    try:
        V.validate_slug(a.client)
        if a.ts is not None and not L.TS_RE.match(a.ts):
            raise ValueError("invalid --ts")
    except ValueError as e:
        print(f"show-audit: refused: {e}", file=sys.stderr); return 2
    try:
        fd = L.open_dir_below(root + VAULTS, (a.client, "audits"))
    except L.UnsafePathError as e:
        print(f"show-audit: refused: {e}", file=sys.stderr); return 2
    except OSError as e:
        print(f"show-audit: {type(e).__name__}", file=sys.stderr); return 1
    if fd is None:
        print("show-audit: no audits for this client", file=sys.stderr); return 1
    try:
        tss = L.list_audit_ts(fd)
        if a.list:
            print("\n".join(tss)); return 0
        ts = a.ts or (tss[-1] if tss else None)
        if ts is None or ts not in tss:
            print("show-audit: no such audit", file=sys.stderr); return 1
        ffd = os.open(f"{ts}-audit.md", os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
    except OSError as e:
        print(f"show-audit: {type(e).__name__}", file=sys.stderr); return 1
    finally:
        os.close(fd)
    with os.fdopen(ffd, encoding="utf-8", errors="replace", newline="") as f:   # keep \r: it is stripped
        if not stat.S_ISREG(os.fstat(ffd).st_mode):
            print("show-audit: not a regular file", file=sys.stderr); return 1
        sys.stdout.write(safe_text(f.read()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
