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

# log/ ONLY. `seen/` used to be listed here, and the failure message below asserted the
# executor "cannot use the governance store" without it — but that requirement was
# written from memory, never measured. Every caller of append_seen / seen_contains /
# iter_seen_records is host-side in hermes-broker.py; nothing the ads-mutator entrypoint
# reaches touches the seen-set. docker-compose.yml no longer mounts seen/ into that
# container, so a seen/ entry here would be a pure false refusal — the pre-flight would
# demand executor access to a path the executor cannot even see, and block startup over
# it. The two are COUPLED: change one only with the other.
#
# Nothing checks seen/ now, and that is correct: this script predicts what the EXECUTOR's
# uid can do, and the executor has no business with seen/. The broker writes it as the
# host user, whose access is not in question here.
READ_WRITE_DIRS = ("log",)

# Fixed-name read-only files directly under the store root's directories. The kill
# switch is normally ABSENT (that is the safe default: no switch => mutation disabled),
# so its absence must never be treated as a problem — see _check_file.
CLIENTS_REGISTRY_REL = ("registry", "clients.json")
KILL_SWITCH_REL = ("control", "mutation-enabled")


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


def _describe(path, st, uid, bits, want):
    return ("%s: mode %04o owner %d:%d gives uid %d only %s — the executor needs %s"
            % (path, stat.S_IMODE(st.st_mode), st.st_uid, st.st_gid, uid,
               "---" if not bits else "%s%s%s" % ("r" if bits & 4 else "-",
                                                  "w" if bits & 2 else "-",
                                                  "x" if bits & 1 else "-"),
               want))


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
    return _describe(path, st, uid, bits, want)


def _check_file(path, uid, gid, need_write):
    """A file that does not exist is not a problem — absence is the normal resting
    state (no kill switch yet, no log yet, no applies yet). Only an EXISTING file with
    inaccessible permissions is a problem."""
    try:
        st = os.stat(path)
    except OSError:
        return None
    if not stat.S_ISREG(st.st_mode):
        return "%s: not a regular file" % path
    bits = _perm_bits(st, uid, gid)
    want = "read"
    ok = bool(bits & 0o4)
    if need_write and ok:
        want, ok = "read+write", bool(bits & 0o2)
    if ok:
        return None
    return _describe(path, st, uid, bits, want)


# approvals/<slug>/ is where apply-changeset.py (the executor) reads a reservation
# from — but it is NOT the only thing that lives there. governance_lib.approval_lock_
# path puts a THIRD file next to those two: <cid>.approval.lock, created 0600 by
# changeset_lib._approval_lock and deliberately NEVER unlinked (deleting it would
# reopen a wrong-inode race — see that function's docstring). That lock is taken
# HOST-SIDE ONLY by hermes-broker.py; apply-changeset.py never references
# approval_lock_path and never opens it. An ALLOWLIST of the suffixes the executor
# actually reads — not a denylist of things to skip — is the only safe way to walk
# this directory: a denylist means every future host-side artifact dropped into
# approvals/ (this is already the second one) becomes a fresh false refusal until
# someone remembers to add it here, and an interrupted _atomic_write_json's leftover
# `<cid>.approval.json.tmp` would need the same treatment. An allowlist fails in the
# safer direction instead — an unrecognized file is ignored rather than blocking the
# broker from starting. Do not "helpfully" invert this into a denylist.
APPROVAL_FILE_SUFFIXES = (".approval.json", ".changeset.json")


def _check_files_in_dir(dirpath, uid, gid, need_write, suffixes=None):
    """Stat every existing regular file directly inside dirpath. Missing dirpath is not
    reported here — the directory-level check already covers that path. A directory we
    cannot even list is itself a problem to REPORT, not an exception to raise (it means
    this process, run ahead of the executor, cannot see what the executor would need
    to).

    suffixes, when given, is an ALLOWLIST: only entries whose name ends with one of
    these exact strings are checked at all, everything else is silently ignored. See
    APPROVAL_FILE_SUFFIXES above for why this must stay an allowlist."""
    problems = []
    try:
        entries = sorted(os.listdir(dirpath))
    except OSError:
        return problems
    for entry in entries:
        if suffixes is not None and not entry.endswith(suffixes):
            continue
        path = os.path.join(dirpath, entry)
        try:
            st = os.lstat(path)
        except OSError:
            continue
        if not stat.S_ISREG(st.st_mode):
            continue
        p = _check_file(path, uid, gid, need_write)
        if p:
            problems.append(p)
    return problems


def _check_approvals(root, uid, gid):
    """approvals/ is nested one level by client slug. Each slug directory holds
    <cid>.approval.json and <cid>.changeset.json — the two files apply-changeset.py
    (the executor) actually opens, and the ONLY two this function verifies — plus a
    third, host-side-only file, <cid>.approval.lock (see APPROVAL_FILE_SUFFIXES),
    which the executor never reads and which this function must NOT demand be
    readable: doing so would false-refuse every store that has ever reserved a
    change-set, which is worse than the gap R19 fixed, because a check that cries wolf
    on a healthy store is one operators learn to disable.

    Walk it defensively regardless: a slug directory this process cannot stat or list
    is REPORTED, never raised — the whole point of a pre-flight is to surface exactly
    this kind of thing before the executor hits it mid-apply."""
    problems = []
    approvals_root = os.path.join(root, "approvals")
    try:
        slugs = sorted(os.listdir(approvals_root))
    except OSError:
        return problems  # the approvals/ directory-level check already covers this
    for slug in slugs:
        slug_dir = os.path.join(approvals_root, slug)
        try:
            st = os.lstat(slug_dir)
        except OSError as e:
            problems.append("%s: cannot stat (%s)" % (slug_dir, e))
            continue
        if not stat.S_ISDIR(st.st_mode):
            continue
        problems.extend(_check_files_in_dir(slug_dir, uid, gid, need_write=False,
                                             suffixes=APPROVAL_FILE_SUFFIXES))
    return problems


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

    # File-level (R19): the directory checks above stop at the directory's own mode
    # and miss files inside with independently wrong permissions — e.g. append_log
    # opening an EXISTING log/<slug>.jsonl with mode "a" against a store whose
    # directories are all correct but whose files were touched by a different writer
    # or a restrictive umask. A file that does not exist yet is never a problem
    # (_check_file returns None for it) — most of these files are normally absent.
    for name in READ_WRITE_DIRS:                        # log/: append_log opens
        problems.extend(                                # log/<slug>.jsonl with mode "a"
            _check_files_in_dir(os.path.join(root, name), uid, gid, need_write=True))

    for rel in (CLIENTS_REGISTRY_REL, KILL_SWITCH_REL):
        p = _check_file(os.path.join(root, *rel), uid, gid, need_write=False)
        if p:
            problems.append(p)

    problems.extend(_check_approvals(root, uid, gid))

    return problems


REMEDY = """
Fix by OWNERSHIP, not by widening the mode. Either run the store under a group the
executor's UID belongs to:

    sudo chgrp -R %(gid)d %(root)s
    sudo chmod -R g+rX %(root)s && sudo chmod -R g+w %(root)s/log

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
