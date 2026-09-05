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
import argparse, json, os, stat, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import governance_lib                      # SLUG_RE, shared not restated

EXECUTOR_UID = governance_lib.EXECUTOR_UID
EXECUTOR_GID = governance_lib.EXECUTOR_GID

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


def is_client_log_name(entry):
    """S5-M2. The ONLY thing the executor opens in log/ is changeset_lib.log_path(slug),
    i.e. exactly `<slug>.jsonl` for a slug matching governance_lib.SLUG_RE. Everything
    else in that directory belongs to somebody else.

    log/ was walked with NO allowlist, so every regular file in it was required to be
    executor-WRITABLE. A rotated `acme.jsonl.1`, an operator's `acme.jsonl.bak`, a
    tarball left mid-restore, a stray .DS_Store — any of them refused the pre-flight
    and BLOCKED BROKER STARTUP over a file the executor never opens. That is R19b's
    over-checking failure on a path R19 did not cover, and over-checking is as harmful
    as under-checking: it takes the whole rail down, and a gate that cries wolf on a
    healthy store is one operators learn to bypass.

    An allowlist, never a denylist — the same rule and the same reasoning as
    APPROVAL_FILE_SUFFIXES above. A denylist means every future artifact anyone drops
    in log/ becomes a fresh false refusal until someone remembers to add it here.

    Matched against governance_lib.SLUG_RE directly rather than a restated pattern, so
    the two cannot drift about what a slug is.

    HONEST RESIDUAL: a rotation scheme whose output is itself a valid slug name —
    `acme-2026-08-01.jsonl` — is indistinguishable from a real client's log without
    reading the client registry, and is still checked. Excluding it would need this
    pre-flight to depend on clients.json, adding a reader and a failure mode to a gate
    whose failures block startup. Not worth it for a case an operator controls; stated
    rather than papered over.
    """
    suffix = ".jsonl"
    if not entry.endswith(suffix):
        return False
    return bool(governance_lib.SLUG_RE.fullmatch(entry[:-len(suffix)]))


def _check_files_in_dir(dirpath, uid, gid, need_write, suffixes=None, name_filter=None):
    """Stat every existing regular file directly inside dirpath. Missing dirpath is not
    reported here — the directory-level check already covers that path.

    `suffixes` and `name_filter` are both ALLOWLISTS: an entry is checked only if it
    passes whichever is supplied, and is silently ignored otherwise. See
    APPROVAL_FILE_SUFFIXES and is_client_log_name above for why these must stay
    allowlists and must never be inverted into denylists."""
    problems = []
    try:
        entries = sorted(os.listdir(dirpath))
    except OSError:
        return problems
    for entry in entries:
        if suffixes is not None and not entry.endswith(suffixes):
            continue
        if name_filter is not None and not name_filter(entry):
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
        # S5-M1: the slug directory's OWN bits, which nothing checked. Measured: a
        # host-owned 0700 slug dir returned ZERO problems, while a 0600 FILE inside it
        # returned one — so the check saw through a directory the executor cannot even
        # traverse, to files it could never reach. The file-level walk above runs as
        # THIS process (the host user, who can list its own 0700 directory), so it
        # models nothing about the executor's access to the directory itself.
        #
        # read+traverse, never write: apply-changeset opens <cid>.approval.json and
        # <cid>.changeset.json in here and writes neither. This is a tightening, but
        # not the R19b over-checking kind — an executor that cannot traverse this
        # directory fails MID-APPLY on a path this pre-flight exists to predict, so
        # reporting it is the correct answer rather than a wolf cried on a healthy
        # store.
        p = _check_dir(slug_dir, uid, gid, need_write=False)
        if p:
            problems.append(p)
        problems.extend(_check_files_in_dir(slug_dir, uid, gid, need_write=False,
                                             suffixes=APPROVAL_FILE_SUFFIXES))
    return problems


def _check_registered_logs(root):
    """Every REGISTERED client must have a pre-created audit log (S3-b).

    log/ is host-owned 2750, so the executor cannot create log/<slug>.jsonl — append_log
    opens it with mode "a", which creates, and that now fails with EACCES. Catching it
    only in iter_log_records surfaces it MID-APPLY, and R19 exists precisely so a store
    the executor cannot use is refused at startup instead: mid-apply is exit 3 after a
    live account change, while a startup refusal costs one idempotent command.

    This is NOT R19b's over-checking. Every false refusal in that lineage — the
    .approval.lock sidecar, a rotated log, an operator's backup — was this gate demanding
    access to a file the executor never opens, from a requirement list written from
    memory. This requirement is the inverse: log/<slug>.jsonl for a registered slug is
    the one file the executor certainly opens, and it is DERIVED from the same
    clients.json vault_lib.resolve already gates on, never from a listing of log/. Files
    in log/ that no registered slug names stay ignored, exactly as before.

    A MISSING registry is not a fault — _check_file already treats it as the normal
    resting state of a fresh store, and turning that into a refusal is the cry-wolf
    failure. Nor is a registry UNREADABLE BY THE CHECKING PROCESS ITSELF: that fault is
    already reported by the registry/ directory and clients.json file checks above (see
    Ruling 9 below), and reporting it a second time here would double-count one fault as
    two. An UNPARSEABLE one is: no client resolves through it, so "zero registered
    clients" would be a silent pass over a store that cannot work at all.

    The message carries a COUNT, never the slugs. Client slugs are client-private, this
    text goes to stderr, and the systemd journal captures stderr under Phase B —
    vault_lib.resolve_dormant_pilot refuses to name candidates for the same reason.
    """
    reg = governance_lib.clients_registry_path(root)
    try:
        with open(reg, encoding="utf-8") as f:
            data = json.load(f)
    # Ruling 9. Missing OR unreadable-by-this-process, and NEITHER is this check's to
    # report. Absence is the normal resting state of a fresh store — _check_file
    # already treats it that way. Unreadability is ALREADY reported by the registry/
    # directory check and the clients.json file check above, so reporting it again
    # counts one fault twice: measured at 6 problems for a store with 5 faults, which
    # broke test_owner_class_wins_even_when_group_and_other_are_wider's exact count.
    # That is R19b's over-checking failure on a new path.
    #
    # This is also the one place in this module that does REAL I/O rather than
    # simulating access for a hypothetical (uid, gid) via _perm_bits. Every sibling
    # check predicts whether uid 10000 WOULD have access; only this one needs the
    # checking process itself to read a file. Returning [] keeps that asymmetry out of
    # the results.
    #
    # Residual, stated rather than hidden: a registry the EXECUTOR can read but the
    # CHECKER cannot silently skips this check. That is a "cannot verify", not a pass,
    # and Task 4's iter_log_records raise is the backstop that still catches a missing
    # log mid-apply. This check is the early warning, not the only guard.
    except OSError:
        return []
    except ValueError as e:
        return ["%s: malformed client registry (%s) — refusing, because a registry that "
                "will not parse resolves no client, and reading it as 'zero registered "
                "clients' would pass a store that cannot work" % (reg, e)]
    # data.get("clients", {}) — WITH the default, matching vault_lib.load_registry:49
    # exactly. An ABSENT "clients" key means zero registered clients, which is how
    # load_registry already reads it; only a PRESENT but non-object "clients" is a fault.
    # Dropping the default here would return None for a registry of "{}" and refuse it —
    # reding the very controls this check is supposed to leave untouched, since
    # _configure_full_correct_store writes exactly that.
    clients = data.get("clients", {}) if isinstance(data, dict) else None
    if not isinstance(clients, dict):
        return ["%s: registry 'clients' must be a JSON object" % reg]

    missing = 0
    for slug in clients:
        if not isinstance(slug, str) or not governance_lib.SLUG_RE.fullmatch(slug):
            continue        # vault_lib.resolve would refuse it; not this gate's call
        if not os.path.isfile(os.path.join(root, "log", "%s.jsonl" % slug)):
            missing += 1
    if not missing:
        return []
    return ["%s/log: %d registered client(s) have no pre-created audit log. The executor "
            "cannot create one (log/ is host-owned %04o by design), so this surfaces "
            "mid-apply as exit 3 after a live account change. Fix with: "
            "migrate-governance.py --bootstrap-logs --apply"
            % (root, missing, governance_lib.LOG_DIR_MODE)]


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
    # S3-b: read+traverse on the DIRECTORY, never write. Directory write is what grants
    # unlink, so a log/ the executor can write is a log/ it can delete — and both the
    # undo path and the caps path read through iter_log_records, so a deleted log costs
    # REVERSIBILITY, not merely quota. What the executor actually needs here is r-x:
    # append_log opens log/<slug>.jsonl with mode "a" (the FILE-level check below covers
    # that) and then fsyncs the log/ DIRECTORY fd via os.open(dirname, O_RDONLY), which
    # is why read is required and traverse alone would not be enough.
    for name in READ_WRITE_DIRS:
        p = _check_dir(os.path.join(root, name), uid, gid, need_write=False)
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
            _check_files_in_dir(os.path.join(root, name), uid, gid, need_write=True,
                                name_filter=is_client_log_name))

    for rel in (CLIENTS_REGISTRY_REL, KILL_SWITCH_REL):
        p = _check_file(os.path.join(root, *rel), uid, gid, need_write=False)
        if p:
            problems.append(p)

    problems.extend(_check_approvals(root, uid, gid))
    problems.extend(_check_registered_logs(root))

    return problems


REMEDY = """
Fix by OWNERSHIP, not by widening the mode. Either run the store under a group the
executor's UID belongs to:

    sudo chgrp -R %(gid)d %(root)s
    sudo chmod -R g+rX %(root)s
    sudo chmod 2750 %(root)s/log
    sudo find %(root)s/log -type f -name '*.jsonl' -exec chmod 0660 {} +

log/ gets NO group write: write on a directory is what grants unlink, and a deleted
audit log costs reversibility (both --undo and the daily caps read through it), not
merely quota. The executor appends to a PRE-CREATED per-client file instead, and setgid
on log/ is what makes host-created files inherit gid %(gid)d — without it, 0660 grants
the wrong group and uid %(uid)d falls through to `other`. Create missing per-client logs
with:

    migrate-governance.py --bootstrap-logs --apply

or give the store to the executor's UID outright. POSIX selects the owner class before
the group class, so a log/ directory owned by the executor is writable by it no matter
how tight the mode looks, and write on a directory is what grants unlink — so the
sequence must restore log/ to a non-executor owner afterward:

    sudo chown -R %(uid)d:%(gid)d %(root)s && sudo chmod -R 700 %(root)s
    sudo chown root:%(gid)d %(root)s/log && sudo chmod 2750 %(root)s/log

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
