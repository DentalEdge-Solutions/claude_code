#!/usr/bin/env python3
"""Remove the journal directories under /var/log/journal that are not this machine's own. Once.

  sudo python3 bin/remove-other-journal-dirs.py --expect-dirs 1 --expect-files 1 --expect-bytes 8388608 [--apply]

A server image can leave the journal of the machine it was built on: the journal service never
trims it and journalctl never reads it. Search it first (collect-review-evidence.py
--other-journals), then remove it with this.

All or nothing. Every entry under /var/log/journal other than the machine's own must be a real
directory (not a link) holding regular files only, and their numbers and total size must equal
the three expected values; otherwise nothing is removed. Without --apply it only says what it
would do. Prints counts only: never a directory's name (a machine id) or a path. Stdlib only."""
import argparse, os, re, stat, sys


def _plan(root):
    """[(directory, [file, ...])], total bytes; ValueError when anything is not as described."""
    with open(os.path.join(root, "etc/machine-id")) as f:
        mid = f.read(64).strip()
    if not re.fullmatch(r"[0-9a-f]{32}", mid):
        raise ValueError("machine id")
    base = os.path.join(root, "var/log/journal")
    if not stat.S_ISDIR(os.lstat(base).st_mode) or not stat.S_ISDIR(os.lstat(os.path.join(base, mid)).st_mode):
        raise ValueError("journal directory")
    plan, size = [], 0
    for n in sorted(os.listdir(base)):
        if n == mid:
            continue
        d = os.path.join(base, n)
        if not stat.S_ISDIR(os.lstat(d).st_mode):
            raise ValueError("an entry that is not a real directory")
        files = []
        for name in sorted(os.listdir(d)):
            st = os.lstat(os.path.join(d, name))
            if not stat.S_ISREG(st.st_mode):
                raise ValueError("an entry that is not a regular file")
            files.append(os.path.join(d, name))
            size += st.st_size
        plan.append((d, files))
    return plan, size


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--expect-dirs", type=int, required=True)
    ap.add_argument("--expect-files", type=int, required=True)
    ap.add_argument("--expect-bytes", type=int, required=True)
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--root", default="/")
    a = ap.parse_args(argv)
    try:
        plan, size = _plan(a.root)
    except (OSError, ValueError) as e:
        print(f"STOPPED: nothing was removed ({e if isinstance(e, ValueError) else type(e).__name__})")
        return 1
    dirs, files = len(plan), sum(len(f) for _, f in plan)
    print(f"found: directories {dirs} | files {files} | bytes {size} | "
          f"expected: {a.expect_dirs} | {a.expect_files} | {a.expect_bytes}")
    if (dirs, files, size) != (a.expect_dirs, a.expect_files, a.expect_bytes):
        print("STOPPED: nothing was removed")
        return 1
    if not a.apply:
        print(f"would remove: directories {dirs} | files {files} | bytes {size}")
        return 0
    for d, fs in plan:
        for p in fs:
            os.remove(p)
        os.rmdir(d)
    left = sum(1 for d, _ in plan if os.path.lexists(d))
    print(f"removed: directories {dirs} | files {files} | still there: {left}")
    return 0 if left == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
