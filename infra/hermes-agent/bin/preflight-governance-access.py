#!/usr/bin/env python3
"""Pre-flight: can the one-shot executor's UID actually read the governance store?
Stdlib-only. Holds no credential and performs no network I/O.

WHY. `ads-mutator` runs as UID 10000 (`Dockerfile`: `USER hermes`), while the
governance store is documented as mode 700 owned by the deploy/broker user. On a Linux
host those are the same UID namespace, so 700-owned-by-someone-else is simply
unreadable to the executor — and the failure surfaces in the worst possible order:
guard 1 reads the kill switch as ABSENT (a refusal that looks like the safe default),
client resolution raises, and `append_log` fails MID-APPLY, which is exit 3 *after* a
live account change has landed.

On macOS the Docker Desktop file-sharing layer remaps ownership, so every path reads as
accessible whatever the host mode is. That is precisely why this check exists: the local
gate passes and the VPS is where it breaks. It is also why the check DOES NOTHING on
non-Linux — a stat-based prediction there would be false, and a check that cries wolf
locally is a check operators learn to bypass.

The remedy is ownership, never `chmod 777`: making the store world-readable hands it
back to every process on the host and deletes the isolation the store exists for.
"""
import argparse, os, stat, sys

EXECUTOR_UID = 10000            # Dockerfile: USER hermes
EXECUTOR_GID = 10000

READ_ONLY_DIRS = ("approvals", "control", "registry")
READ_WRITE_DIRS = ("log", "seen")


def applies(platform=None):
    """Bind-mount UID semantics are direct only on Linux; elsewhere this predicts
    nothing and must stay silent."""
    return (platform if platform is not None else sys.platform).startswith("linux")


def _perm_bits(st, uid, gid):
    """The POSIX permission-selection algorithm: owner, else group, else other. Exactly
    one class applies — a directory owned by `uid` with mode 077 is NOT accessible to
    it, and a check that OR'd the classes together would wrongly say it is."""
    if st.st_uid == uid:
        return (st.st_mode >> 6) & 0o7
    if st.st_gid == gid:
        return (st.st_mode >> 3) & 0o7
    return st.st_mode & 0o7


def _check_dir(path, uid, gid, need_write):
    try:
        st = os.stat(path)
    except OSError as e:
        return "%s: cannot stat (%s)" % (path, e)
    if not stat.S_ISDIR(st.st_mode):
        return "%s: not a directory" % path
    bits = _perm_bits(st, uid, gid)
    want = "read+traverse"
    ok = (bits & 0o5) == 0o5
    if need_write and ok:
        want, ok = "read+write+traverse", bool(bits & 0o2)
    if ok:
        return None
    return ("%s: mode %04o owner %d:%d gives uid %d only %s — the executor needs %s"
            % (path, stat.S_IMODE(st.st_mode), st.st_uid, st.st_gid, uid,
               "---" if not bits else "%s%s%s" % ("r" if bits & 4 else "-",
                                                  "w" if bits & 2 else "-",
                                                  "x" if bits & 1 else "-"),
               want))


def check(root, uid=EXECUTOR_UID, gid=EXECUTOR_GID, platform=None):
    """Return a list of human-readable problems; empty means the executor can work."""
    if not applies(platform):
        return []
    problems = []
    p = _check_dir(root, uid, gid, need_write=False)
    if p:
        problems.append(p)
    for name in READ_ONLY_DIRS:
        p = _check_dir(os.path.join(root, name), uid, gid, need_write=False)
        if p:
            problems.append(p)
    for name in READ_WRITE_DIRS:
        p = _check_dir(os.path.join(root, name), uid, gid, need_write=True)
        if p:
            problems.append(p)
    return problems


REMEDY = """
Fix by OWNERSHIP, not by widening the mode. Either run the store under a group the
executor's UID belongs to:

    sudo chgrp -R %(gid)d %(root)s
    sudo chmod -R g+rX %(root)s && sudo chmod -R g+w %(root)s/log %(root)s/seen

or give the store to the executor's UID outright:

    sudo chown -R %(uid)d:%(gid)d %(root)s && sudo chmod -R 700 %(root)s

Do NOT `chmod 777`. The store is the one place Hermes cannot reach; making it
world-writable hands it to every process on the host and removes the isolation this
whole tier is built on."""


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True)
    ap.add_argument("--uid", type=int, default=EXECUTOR_UID)
    ap.add_argument("--gid", type=int, default=EXECUTOR_GID)
    args = ap.parse_args(argv)
    if not applies():
        return 0
    problems = check(args.root, args.uid, args.gid)
    if not problems:
        return 0
    print("preflight-governance-access: the ads-mutator executor (uid %d) cannot use the "
          "governance store. Refusing BEFORE any mutation, because this same condition "
          "reached mid-apply is an exit-3 failure after a live account change:"
          % args.uid, file=sys.stderr)
    for p in problems:
        print("  - %s" % p, file=sys.stderr)
    print(REMEDY % {"root": args.root, "uid": args.uid, "gid": args.gid}, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
