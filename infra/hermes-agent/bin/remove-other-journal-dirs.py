#!/usr/bin/env python3
"""Remove the journal directories under /var/log/journal that are not this machine's own. Once.

  sudo python3 bin/remove-other-journal-dirs.py --expect-dirs 1 --expect-files 1 --expect-bytes 8388608 [--apply]

A server image can leave the journal of the machine it was built on: the journal service never
trims it and journalctl never reads it. Search it first (collect-review-evidence.py
--other-journals), then remove it with this.

All or nothing. /var, /var/log and /var/log/journal must be real directories (not links). Every
entry under /var/log/journal other than the machine's own must be NAMED exactly 32 lowercase hex
characters (so `remote` and `<id>.<namespace>` are refused) and be a real directory holding regular
files only; no file in it may be newer than the newest regular file of the machine's own directory
(a stale /etc/machine-id must not point this at the live journal); and their numbers and total
size must equal the three expected values. Otherwise nothing is removed. Without --apply it only
says what it would do. Removal goes through a directory descriptor, checked against the directory
counted. If it stops part-way (an error, or Ctrl-C) it prints one line, `STOPPED PART-WAY: files
removed x of y | directories removed a of b (<exception type>)`, and returns 1. Prints counts only:
never a directory's name (a machine id) or a path. Stdlib only."""
import argparse, os, re, stat, sys


class _Refuse(Exception):
    """One of this tool's own refusals: its text is a fixed message and is the only text ever printed."""


def _is_dir(path):
    return stat.S_ISDIR(os.lstat(path).st_mode)


def _plan(root):
    """[(directory, (device, inode), [file name, ...])], total bytes; _Refuse when anything is not as described."""
    base = os.path.join(root, "var/log/journal")
    for part in ("var", "var/log", "var/log/journal"):
        if not _is_dir(os.path.join(root, part)):
            raise _Refuse("journal directory")
    with open(os.path.join(root, "etc/machine-id")) as f:
        mid = f.read(64).strip()
    if not re.fullmatch(r"[0-9a-f]{32}", mid):
        raise _Refuse("machine id")
    own = os.path.join(base, mid)
    if not _is_dir(own):
        raise _Refuse("journal directory")
    own_files = [os.lstat(os.path.join(own, n)) for n in os.listdir(own)]
    own_newest = max([st.st_mtime_ns for st in own_files if stat.S_ISREG(st.st_mode)] or [0])
    plan, size = [], 0
    for n in sorted(os.listdir(base)):
        if n == mid:
            continue
        if not re.fullmatch(r"[0-9a-f]{32}", n):
            raise _Refuse("an entry that is not a machine's journal directory")
        d = os.path.join(base, n)
        st = os.lstat(d)
        if not stat.S_ISDIR(st.st_mode):
            raise _Refuse("an entry that is not a real directory")
        names = []
        for name in sorted(os.listdir(d)):
            fst = os.lstat(os.path.join(d, name))
            if not stat.S_ISREG(fst.st_mode):
                raise _Refuse("an entry that is not a regular file")
            if fst.st_mtime_ns > own_newest:
                raise _Refuse("another directory is newer than this machine's own")
            names.append(name)
            size += fst.st_size
        plan.append((d, (st.st_dev, st.st_ino), names))
    return plan, size


def _remove(plan, done):
    """Remove through a directory descriptor, so a directory swapped for a link after the count is
    never followed. done = [files removed, directories removed], kept up to date; raises OSError part-way."""
    for d, (dev, ino), names in plan:
        fd = os.open(d, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            st = os.fstat(fd)
            if (st.st_dev, st.st_ino) != (dev, ino):
                raise OSError("directory changed")
            for name in names:
                if not stat.S_ISREG(os.stat(name, dir_fd=fd, follow_symlinks=False).st_mode):
                    raise OSError("not a regular file")
                os.unlink(name, dir_fd=fd)
                done[0] += 1
        finally:
            os.close(fd)
        os.rmdir(d)
        done[1] += 1


def main(argv=None):
    try:
        return _main(argv)
    except Exception as e:                     # never a traceback: it would carry a path
        print(f"STOPPED: an unexpected error ({type(e).__name__})")
        return 1


def _main(argv):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0], allow_abbrev=False)
    ap.add_argument("--expect-dirs", type=int, required=True)
    ap.add_argument("--expect-files", type=int, required=True)
    ap.add_argument("--expect-bytes", type=int, required=True)
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--root", default="/")
    a = ap.parse_args(argv)
    try:
        plan, size = _plan(a.root)
    except (OSError, ValueError, _Refuse) as e:
        print(f"STOPPED: nothing was removed ({e if isinstance(e, _Refuse) else type(e).__name__})")
        return 1
    dirs, files = len(plan), sum(len(n) for _, _, n in plan)
    print(f"found: directories {dirs} | files {files} | bytes {size} | "
          f"expected: {a.expect_dirs} | {a.expect_files} | {a.expect_bytes}")
    if (dirs, files, size) != (a.expect_dirs, a.expect_files, a.expect_bytes):
        print("STOPPED: nothing was removed")
        return 1
    if not a.apply:
        print(f"would remove: directories {dirs} | files {files} | bytes {size}")
        return 0
    done = [0, 0]
    try:
        _remove(plan, done)
    except (OSError, KeyboardInterrupt) as e:
        print(f"STOPPED PART-WAY: files removed {done[0]} of {files} | directories removed {done[1]} of {dirs} "
              f"({type(e).__name__})")
        return 1
    print(f"removed: directories {dirs} | files {files} | still there: 0")
    return 0


if __name__ == "__main__":
    sys.exit(main())
