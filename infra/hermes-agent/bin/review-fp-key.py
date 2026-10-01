#!/usr/bin/env python3
"""The review fingerprint key (Option B §8). Laptop only. Stdlib only.

  review-fp-key.py init     [--path ~/.config/hermes-review/fp.key]   # 32 random bytes, hex, 0600
  review-fp-key.py show-id  [--path ...]                              # 8-hex id, safe to paste

The key never goes to the box's disk: the box collector reads it from the tty for one run.
Copy it for that paste with `pbcopy < ~/.config/hermes-review/fp.key`. Never printed here."""
import argparse, os, secrets, sys
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import review_lib as R

DEFAULT = os.path.expanduser("~/.config/hermes-review/fp.key")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("cmd", choices=("init", "show-id"))
    ap.add_argument("--path", default=DEFAULT)
    a = ap.parse_args(argv)
    if a.cmd == "init":
        os.makedirs(os.path.dirname(a.path), mode=0o700, exist_ok=True)
        try:
            fd = os.open(a.path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        except FileExistsError:
            print(f"review-fp-key: {a.path} exists; refusing to overwrite (it would orphan past fingerprints)",
                  file=sys.stderr)
            return 2
        with os.fdopen(fd, "w") as f:
            f.write(secrets.token_hex(32) + "\n")
        print(f"review-fp-key: created {a.path} (0600)")
        return 0
    with open(a.path) as f:
        print(R.key_id(R.load_fp_key(f.read())))
    return 0


if __name__ == "__main__":
    sys.exit(main())
