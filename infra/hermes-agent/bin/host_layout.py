#!/usr/bin/env python3
"""The host layout of the governance store and the request spool (F10). Stdlib-only.

ONE TABLE, three operations over it:
  check  — read-only. lstat only: a symlink is always a problem and is never followed.
  plan   — the dry run: per entry, create / ok / mismatch.
  apply  — root only. Creates what is MISSING. Refuses, before creating anything, if any
           entry that EXISTS is wrong, or any ancestor of either root is unsafe. It never
           chowns or chmods an entry it did not create in this call.

Why "never repair": the same reason bootstrap_logs refuses a missing log/ (ruling R23).
A store with the wrong owner is a store someone else laid down, and it is not safe to
"fix" silently. The operator is shown the expected state and sets it by hand.

Spec: docs/superpowers/specs/2026-09-21-f10-governance-store-and-spool-layout-design.md
§3.2 (store), §3.3 (spool), §4.1 (this module).
"""
import collections, grp, os, pwd, stat, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import governance_lib

DEFAULT_STORE_ROOT = "/var/lib/hermes/governance"
DEFAULT_SPOOL_ROOT = "/var/lib/hermes/spool"

DIR, FILE = "dir", "file"

Entry = collections.namedtuple("Entry", "root_key relpath kind owner group mode content")
Step = collections.namedtuple("Step", "action path detail implied entry")

# Parent-first. Rationale per row in the spec's §3.2 / §3.3 tables. The comments say
# only what a reader of THIS file needs in order not to "simplify" a row.
LAYOUT = (
    # Store root: broker and executor traverse via group; only root renames children.
    Entry("store", "", DIR, "root", "hermes", 0o750, None),
    # The broker reserves and records outcomes; setgid keeps group hermes on the slug dirs.
    Entry("store", "approvals", DIR, "hermes-broker", "hermes", 0o2750, None),
    # Root-owned so ONLY root can create the kill switch. The broker cannot enable mutation.
    Entry("store", "control", DIR, "root", "hermes", 0o2750, None),
    Entry("store", "control/.locks", DIR, "hermes-broker", "hermes-broker", 0o700, None),
    Entry("store", "registry", DIR, "root", "hermes", 0o2750, None),
    # Created as {} only if absent. Its content is never checked or rewritten here.
    Entry("store", "registry/clients.json", FILE, "root", "hermes", 0o640, b"{}\n"),
    # S3-b: no group write on the directory, because write on a directory grants unlink.
    Entry("store", "log", DIR, "root", "hermes", governance_lib.LOG_DIR_MODE, None),
    Entry("store", "seen", DIR, "hermes-broker", "hermes-broker", 0o700, None),
    # Spool root: nobody but root can rename requests/ or results/.
    Entry("spool", "", DIR, "root", "hermes", 0o750, None),
    # Sticky: the gateway cannot unlink or rename broker-owned entries, but the broker, as
    # the directory's owner, can unlink the gateway's. Setgid: new files carry group hermes.
    Entry("spool", "requests", DIR, "hermes-broker", "hermes", 0o3770, None),
    # Pre-created, so the gateway can never claim the name first (F10b).
    Entry("spool", "requests/.quarantine", DIR, "hermes-broker", "hermes-broker", 0o700, None),
    # Group read-only: the gateway reads results and can no longer forge one.
    Entry("spool", "results", DIR, "hermes-broker", "hermes", 0o2750, None),
)


class LayoutError(Exception):
    """A refusal. apply() never leaves a partial layout behind one."""


class Resolver:
    """Names to ids. system_resolver() fills it from pwd/grp; tests build one directly."""

    def __init__(self, users, groups):
        self._users = dict(users)
        self._groups = dict(groups)

    def uid(self, name):
        if name not in self._users:
            raise LayoutError("user %r does not exist on this host — create it first "
                              "(README \"VPS deploy sequence\" step 1)" % name)
        return self._users[name]

    def gid(self, name):
        if name not in self._groups:
            raise LayoutError("group %r does not exist on this host — create it first "
                              "(README \"VPS deploy sequence\" step 1)" % name)
        return self._groups[name]


def system_resolver(getpwnam=pwd.getpwnam, getgrnam=grp.getgrnam):
    """Resolve every name the table uses. A name that does not resolve is left out, so the
    refusal comes from Resolver.uid/gid naming it, at the point it is needed."""
    users, groups = {}, {}
    for e in LAYOUT:
        if e.owner not in users:
            try:
                users[e.owner] = getpwnam(e.owner).pw_uid
            except KeyError:
                pass
        if e.group not in groups:
            try:
                groups[e.group] = getgrnam(e.group).gr_gid
            except KeyError:
                pass
    if "hermes" in groups and groups["hermes"] != governance_lib.EXECUTOR_GID:
        raise LayoutError(
            "group 'hermes' is gid %d on this host, but the executor runs as gid %d "
            "(Dockerfile: USER hermes). Reconcile the group before creating the layout "
            "(README \"VPS deploy sequence\" step 1)"
            % (groups["hermes"], governance_lib.EXECUTOR_GID))
    return Resolver(users, groups)


def entry_path(entry, store_root, spool_root):
    root = store_root if entry.root_key == "store" else spool_root
    return os.path.join(root, entry.relpath) if entry.relpath else root


def expected(entry):
    return "%s:%s %04o" % (entry.owner, entry.group, entry.mode)


def _inspect(entry, path, resolver):
    """('ok' | 'missing' | 'mismatch', detail). lstat only — never follows a symlink."""
    try:
        st = os.lstat(path)
    except FileNotFoundError:
        return "missing", "missing, expected %s %s" % (entry.kind, expected(entry))
    except OSError as e:
        return "mismatch", "cannot lstat (%s), expected %s" % (e, expected(entry))
    if stat.S_ISLNK(st.st_mode):
        return "mismatch", ("is a symlink (never followed), expected a real %s %s"
                            % (entry.kind, expected(entry)))
    is_kind = stat.S_ISDIR if entry.kind == DIR else stat.S_ISREG
    if not is_kind(st.st_mode):
        return "mismatch", "is not a %s, expected %s %s" % (entry.kind, entry.kind,
                                                           expected(entry))
    uid, gid = resolver.uid(entry.owner), resolver.gid(entry.group)
    mode = stat.S_IMODE(st.st_mode)
    if (st.st_uid, st.st_gid, mode) != (uid, gid, entry.mode):
        return "mismatch", ("found uid %d gid %d mode %04o, expected %s (uid %d gid %d)"
                            % (st.st_uid, st.st_gid, mode, expected(entry), uid, gid))
    return "ok", ""


def check_ancestors(root, trusted_uids=(0,), top="/"):
    """Every directory above `root`, up to and including `top`, must be a real directory,
    owned by a trusted uid, and neither group- nor world-writable. Whoever can write an
    ancestor can rename the whole layout away and put their own in its place."""
    problems = []
    top = os.path.normpath(top)
    d = os.path.dirname(os.path.normpath(root))
    while True:
        try:
            st = os.lstat(d)
        except OSError as e:
            problems.append((d, "ancestor cannot be checked (%s)" % e))
        else:
            if stat.S_ISLNK(st.st_mode):
                problems.append((d, "ancestor is a symlink — the layout must sit on a "
                                    "real path"))
            elif not stat.S_ISDIR(st.st_mode):
                problems.append((d, "ancestor is not a directory"))
            else:
                if st.st_uid not in trusted_uids:
                    problems.append((d, "ancestor owned by uid %d, expected root"
                                        % st.st_uid))
                if st.st_mode & 0o022:
                    problems.append((d, "ancestor mode %04o is group- or world-writable — "
                                        "whoever can write it can rename the layout away"
                                        % stat.S_IMODE(st.st_mode)))
        if d == top or d == os.path.dirname(d):
            return problems
        d = os.path.dirname(d)


def plan(store_root, spool_root, resolver, ancestor_uids=(0,), ancestor_top="/"):
    for r in (store_root, spool_root):
        if not os.path.isabs(r):
            raise LayoutError("%r is not an absolute path" % r)
    steps, seen = [], set()
    for root in (store_root, spool_root):
        for path, detail in check_ancestors(root, ancestor_uids, ancestor_top):
            if (path, detail) not in seen:          # the two roots share ancestors
                seen.add((path, detail))
                steps.append(Step("mismatch", path, detail, False, None))
    missing = []
    for e in LAYOUT:
        p = entry_path(e, store_root, spool_root)
        if any(p.startswith(m + os.sep) for m in missing):
            steps.append(Step("create", p, "missing, expected %s %s"
                              % (e.kind, expected(e)), True, e))
            continue
        state, detail = _inspect(e, p, resolver)
        if state == "missing":
            steps.append(Step("create", p, detail, False, e))
            if e.kind == DIR:
                missing.append(p)
        else:
            steps.append(Step(state, p, detail, False, e))
    return steps


def check(store_root, spool_root, resolver, ancestor_uids=(0,), ancestor_top="/"):
    """Problems as '<path>: <detail>' lines; empty means the layout is exactly right.
    A missing directory is one line — its children are implied, not repeated."""
    return ["%s: %s" % (s.path, s.detail)
            for s in plan(store_root, spool_root, resolver, ancestor_uids, ancestor_top)
            if s.action == "mismatch" or (s.action == "create" and not s.implied)]


def _remove(path):
    """Best-effort removal used only during rollback. Returns True on success, False if
    the path could not be removed — the caller must surface a False, never swallow it."""
    try:
        st = os.lstat(path)
        if stat.S_ISDIR(st.st_mode):
            os.rmdir(path)
        else:
            os.unlink(path)
        return True
    except OSError:
        return False


def _write_all(fd, data):
    view = memoryview(data)
    while view:
        view = view[os.write(fd, view):]


def apply(store_root, spool_root, resolver, ancestor_uids=(0,), ancestor_top="/",
          geteuid=os.geteuid):
    """Create every MISSING entry, parent-first. Returns the paths created.

    Refuses — before creating anything — when not root, when any ancestor is unsafe, when
    any EXISTING entry mismatches, or when any name does not resolve. Each entry is
    created with mkdir/O_EXCL, then opened with O_NOFOLLOW, and fchown'ed and fchmod'ed
    on that fd, so neither a planted symlink nor the umask can redirect or weaken it.
    Each entry is re-inspected after it is created. On ANY failure, everything created by
    this call is removed, children first, and the exception propagates. Anything that
    could not be removed (for example another process wrote into a directory this call
    created) is named on the re-raised exception — via add_note on 3.11+, or appended to
    its args otherwise — so a failed rollback is never silent; the exception's own type
    is always preserved."""
    if geteuid() != 0:
        raise LayoutError("--apply must run as root: it creates entries owned by users "
                          "other than the caller. Nothing was created.")
    steps = plan(store_root, spool_root, resolver, ancestor_uids, ancestor_top)
    bad = ["%s: %s" % (s.path, s.detail) for s in steps if s.action == "mismatch"]
    if bad:
        raise LayoutError(
            "refusing to create anything: these existing paths do not match the layout, "
            "and this tool never repairs. Set each to the expected state by hand (or, for "
            "an EMPTY directory left by an earlier bring-up, `sudo rmdir` it), then "
            "re-run:\n  - " + "\n  - ".join(bad))
    todo = [s for s in steps if s.action == "create"]
    ids = {s.path: (resolver.uid(s.entry.owner), resolver.gid(s.entry.group))
           for s in todo}                       # every name resolves before any mkdir
    created = []
    try:
        for s in todo:
            e, (uid, gid) = s.entry, ids[s.path]
            if e.kind == DIR:
                os.mkdir(s.path, 0o700)
                created.append(s.path)
                fd = os.open(s.path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            else:
                fd = os.open(s.path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                             0o600)
                created.append(s.path)
            try:
                if e.kind == FILE:
                    _write_all(fd, e.content)
                os.fchown(fd, uid, gid)
                os.fchmod(fd, e.mode)           # after fchown, which can clear setgid
                if e.kind == FILE:
                    os.fsync(fd)
            finally:
                os.close(fd)
            state, detail = _inspect(e, s.path, resolver)
            if state != "ok":
                raise LayoutError("%s did not land as specified: %s" % (s.path, detail))
    except BaseException as exc:
        unremoved = [p for p in reversed(created) if not _remove(p)]
        if unremoved:
            note = ("rollback could not remove: %s; remove by hand"
                    % ", ".join(unremoved))
            if hasattr(exc, "add_note"):
                exc.add_note(note)
            else:
                exc.args = exc.args + (note,)
        raise
    return created
