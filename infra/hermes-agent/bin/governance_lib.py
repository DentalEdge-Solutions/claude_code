#!/usr/bin/env python3
"""Path contract for the host-owned governance store. Stdlib-only.

Everything the mutation guards TRUST lives here, and nothing Hermes can write does.
The gateway container does not mount this tree at all. The one-shot executor mounts
approvals/, control/ and registry/ READ-ONLY and log/ read-write (append, not unlink —
see preflight-governance-access.py). seen/ is NOT mounted into the executor at all
(S3-a) — the broker writes it host-side, and the executor has no business with it.

This module is deliberately the bottom of the dependency graph — it imports nothing
from bin/ — so it can own the shared identifier regexes instead of leaving duplicates
in changeset_lib and vault_lib to drift apart.

Root resolution mirrors vault_lib.vault_root(): a container default that host callers
override with HERMES_GOVERNANCE_ROOT.
"""
import array, errno, fcntl, os, re, stat, sys

DEFAULT_ROOT = "/opt/governance"

SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
CHANGESET_ID_RE = re.compile(r"^[0-9]{8}-[0-9]{6}-[0-9a-f]{8}$")

# The one-shot executor's identity and the audit-log layout it requires. ONE definition,
# shared, so preflight-governance-access.py and migrate_governance_shim.py cannot drift —
# the rule 6645879 applied to REQUEST_ID_RE, for the same reason.
EXECUTOR_UID = 10000            # Dockerfile: USER hermes
EXECUTOR_GID = 10000
# log/ is setgid and NOT group-writable: directory write is what grants unlink, and
# setgid is what makes host-created log files inherit EXECUTOR_GID.
LOG_DIR_MODE = 0o2750
LOG_FILE_MODE = 0o660

# F12: the broker writes run records here. Setgid (like approvals/ and log/) keeps group
# hermes on the per-client directories; no group write, because write on a directory grants
# unlink. NOT mounted into any container — the executor never sees records/, which is why
# preflight-governance-access.py must not list it (spec 2026-09-23 §2.5).
RECORDS_DIR_MODE = 0o2750

# One definition, shared, so the two cannot drift (vault_lib.py's rule, applied here
# too). This is the STRICT lowercase-only class — the pattern spool_lib enforces on
# what a request file's own name and body may claim, and the only one that can
# actually reach the broker. apply-changeset.py's --request flag validates against
# this same object so a CLI-typed uppercase value cannot diverge from what the spool
# already accepted (CORRECTED 2026-09-03 — the two were previously defined twice and
# had already drifted: apply-changeset.py's copy accepted uppercase hex, spool_lib's
# did not).
REQUEST_ID_RE = re.compile(r"^[0-9a-f-]{36}$")


def governance_root():
    return os.environ.get("HERMES_GOVERNANCE_ROOT", DEFAULT_ROOT)


def _slug(s):
    # fullmatch, not match: "acme\n" must not pass as "acme".
    if not isinstance(s, str) or not SLUG_RE.fullmatch(s):
        raise ValueError("invalid client slug: %r" % (s,))
    return s


def _cid(c):
    if not isinstance(c, str) or not CHANGESET_ID_RE.fullmatch(c):
        raise ValueError("invalid changeset id: %r" % (c,))
    return c


def _root(root):
    return root or governance_root()


def kill_switch_path(root=None):
    return os.path.join(_root(root), "control", "mutation-enabled")


def clients_registry_path(root=None):
    return os.path.join(_root(root), "registry", "clients.json")


def approvals_dir(slug, root=None):
    return os.path.join(_root(root), "approvals", _slug(slug))


def approval_path(slug, cid, root=None):
    return os.path.join(approvals_dir(slug, root), "%s.approval.json" % _cid(cid))


def snapshot_path(slug, cid, root=None):
    return os.path.join(approvals_dir(slug, root), "%s.changeset.json" % _cid(cid))


def log_path(slug, root=None):
    return os.path.join(_root(root), "log", "%s.jsonl" % _slug(slug))


# §6B: every log/<slug>.jsonl carries the Linux append-only inode flag (chattr +a), so the
# file admits appends only — for the executor, the broker and root alike. Measured on the
# box 2026-09-24 (spec 2026-09-24-s6b-audit-log-append-only-design.md §2.3).
#
# linux/fs.h: FS_APPEND_FL, and FS_IOC_GETFLAGS / FS_IOC_SETFLAGS = _IOR/_IOW('f', 1|2, long)
# on a 64-bit kernel. The kernel moves an INT through these despite the `long` in the macro,
# so the buffer is 4 bytes. Not assumed: deploy/layout-integration.test.py cross-checks
# these numbers against lsattr on a real ext4 file.
LOG_APPEND_ONLY_FL = 0x00000020
_FS_IOC_GETFLAGS = 0x80086601
_FS_IOC_SETFLAGS = 0x40086602


def _open_regular(path):
    """An fd on path itself — never a symlink's target, never a FIFO we would block on."""
    if not sys.platform.startswith("linux"):
        raise OSError(errno.ENOTSUP,
                      "the append-only flag is Linux-only (platform %s)" % sys.platform, path)
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise OSError(errno.EINVAL, "not a regular file", path)
    except BaseException:
        os.close(fd)
        raise
    return fd


def _get_flags(fd):
    buf = array.array("i", [0])
    fcntl.ioctl(fd, _FS_IOC_GETFLAGS, buf, True)
    return buf[0]


def is_append_only(path):
    """True if path carries the append-only flag. RAISES on every failure — an unsupported
    filesystem, a symlink, a non-regular file, off Linux — and never returns False for one:
    'cannot tell' must not read as 'not sealed', and must never read as 'sealed'.
    Needs no root."""
    fd = _open_regular(path)
    try:
        return bool(_get_flags(fd) & LOG_APPEND_ONLY_FL)
    finally:
        os.close(fd)


def set_append_only(path):
    """Add the append-only flag, keeping every other flag, then read it back. Root only
    (CAP_LINUX_IMMUTABLE). Raises on any failure, and EIO if the flag did not take."""
    fd = _open_regular(path)
    try:
        buf = array.array("i", [_get_flags(fd) | LOG_APPEND_ONLY_FL])
        fcntl.ioctl(fd, _FS_IOC_SETFLAGS, buf, True)
    finally:
        os.close(fd)
    if not is_append_only(path):
        raise OSError(errno.EIO, "the append-only flag did not take", path)


def seen_path(slug, root=None):
    return os.path.join(_root(root), "seen", "%s.jsonl" % _slug(slug))


def records_dir(slug, root=None):
    return os.path.join(_root(root), "records", _slug(slug))


def record_path(slug, cid, root=None):
    return os.path.join(records_dir(slug, root), "%s.result.json" % _cid(cid))


def records_timeline_path(slug, root=None):
    return os.path.join(records_dir(slug, root), "timeline.md")


def lock_path(slug, root=None):
    """Per-client advisory lock for the broker. Lives under control/, which is mounted
    :ro into the executor and not mounted at all into the gateway — so no container can
    take, hold, or delete it. A lock in the spool would be a lock the thing being
    serialised can remove.

    This is DEFENSE IN DEPTH and a drain-serialisation mechanism, not the guarantee of
    single-use approval — Task 4's changeset_lib.reserve_approval/record_outcome take
    their OWN flock on a per-approval sidecar (governance_lib.approval_lock_path),
    which makes single-use self-enforcing regardless of what holds this lock or
    whether it is held at all. This lock and that one are DIFFERENT FILES
    (control/.locks/<slug>.lock here vs. approvals/<slug>/<cid>.approval.lock there),
    so nesting them can never deadlock — but do not conflate what each one proves.
    """
    return os.path.join(_root(root), "control", ".locks", "%s.lock" % _slug(slug))


def approval_lock_path(slug, cid, root=None):
    """Sidecar mutual-exclusion file for reserve_approval/record_outcome.

    Deliberately a SEPARATE file from approval_path(), never the approval record
    itself: changeset_lib._atomic_write_json writes the record to a .tmp path and
    os.replace()s it over the destination, so a lock held on the approval file's own
    fd would be a lock on the OLD inode — the file that lands after the rename is a
    different inode and carries no lock at all. This path's identity never changes
    across rewrites of the approval record, so flock-ing it is real mutual exclusion.

    Lives in approvals_dir(), i.e. inside the governance store the gateway container
    does not mount and the executor mounts read-only — no container can take, hold,
    or delete this lock.
    """
    return os.path.join(approvals_dir(slug, root), "%s.approval.lock" % _cid(cid))
