#!/usr/bin/env python3
"""Persist an executor run record into the client vault. Stdlib-only.

The executor runs in a one-shot container that deliberately does not mount the vault,
so it emits its result on stdout and the CALLER persists it. The audit log in the
governance store remains the reversibility record and is written by the executor,
fsynced per action; result.json and timeline.md are convenience artifacts for humans
and for Hermes. If this step is lost, the audit log still holds the truth and --undo
still works.

THIS STEP RUNS HOST-SIDE AND WRITES INTO THE ONE TREE HERMES CAN WRITE. That makes
every destination here attacker-shaped, and it is the reason for the containment work
below rather than a plain open(). A symlink planted in the vault turns this step into
a write primitive against anything the host user can reach — demonstrated on
2026-08-19 by symlinking timeline.md at the governance store's `control/mutation-enabled`
(the O_CREAT|O_APPEND open then CREATES it, and kill_switch_ok() only asks whether the
file exists, so mutation becomes globally enabled) and by symlinking the `.tmp` path at
the audit log (the O_TRUNC open then erases the cap consumption the guards count).
Reachable in practice because `--undo` runs with the kill switch off and still emits a
result line, and because HERMES_GOVERNANCE_DIR is in `.env`, the gateway's env_file.

The containment is structural rather than a check: `os.O_NOFOLLOW` means a symlinked
destination cannot be opened at all, and the fstat regular-file test means a directory
or a fifo in that position refuses instead of raising something unrelated. The
resolved-path checks then cover the intermediate components, which O_NOFOLLOW on the
final component does not.
"""
import json, os, stat, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import changeset_lib as C
import vault_lib

MARKER = "HERMES-RESULT-JSON "

# R20: the whole point of the dirfd chain below is that every write happens relative
# to an already-open directory descriptor rather than by re-resolving a path — that is
# what removes the directory-component TOCTOU structurally. If the platform does not
# support dir_fd on the calls we depend on, silently falling back to path-based opens
# would reintroduce exactly that TOCTOU without anyone noticing. Refuse loudly instead.
#
# Measured, not assumed (2026-08-24, darwin): os.open, os.rename, os.unlink and
# os.mkdir are all in os.supports_dir_fd, but os.replace is NOT — so the atomic swap
# below uses os.rename(src_dir_fd=, dst_dir_fd=), never os.replace. On POSIX, rename()
# and the rename half of replace() are the same syscall and both overwrite atomically;
# they differ only on Windows, which this tier does not target.
if os.open not in os.supports_dir_fd or os.rename not in os.supports_dir_fd:
    raise RuntimeError("persist_run_record_shim requires openat/renameat support "
                       "(os.supports_dir_fd); refusing to fall back to path-based "
                       "opens, which reintroduces the directory-component TOCTOU")


class PersistRefused(ValueError):
    """A destination that cannot be proven to stay inside the client vault.

    Subclasses ValueError so persist-run-record.py's existing fail-closed handler
    turns it into exit 2 with the message on stderr — never a silent skip.
    """


def parse_result(text):
    """Return the LAST marker line's payload, or None. The marker must start the line —
    a substring anywhere in prose is not a result."""
    found = None
    for line in text.splitlines():
        if line.startswith(MARKER):
            try:
                found = json.loads(line[len(MARKER):])
            except json.JSONDecodeError:
                continue
    return found


def _contained(path, root):
    """True when `path` is `root` itself or lies beneath it. Both must already be
    resolved — a prefix test on unresolved paths proves nothing."""
    return path == root or path.startswith(root.rstrip(os.sep) + os.sep)


def _resolve_vault(vault, root=None):
    """Resolve the client vault and prove it lies under the configured vault root.

    Refuses a symlinked vault outright even when it resolves back inside the root: the
    guarantee wanted here is "this directory is what it appears to be", and admitting a
    benign-looking symlink today is what makes the next one arguable.

    R20(c): the containment check now precedes the mkdir. The previous order created
    the directory FIRST and refused afterwards — an out-of-root vault path was left on
    disk by a refusal that was supposed to be refusing exactly that side effect.
    """
    root_real = os.path.realpath(root or vault_lib.vault_root())
    if os.path.islink(vault):
        raise PersistRefused("vault path is a symlink, refusing: %s" % vault)
    # Prove containment of the path we are ABOUT to create, using the resolved parent
    # (the vault itself may not exist yet, so it cannot be realpath'd directly).
    candidate = os.path.join(os.path.realpath(os.path.dirname(vault)),
                             os.path.basename(vault))
    if not _contained(candidate, root_real):
        raise PersistRefused(
            "vault %s resolves to %s, which is outside the vault root %s — refusing"
            % (vault, candidate, root_real))
    if not os.path.exists(vault):
        os.makedirs(vault, exist_ok=True)
    if not os.path.isdir(vault):
        raise PersistRefused("vault path is not a directory, refusing: %s" % vault)
    vault_real = os.path.realpath(vault)
    # Re-check after creation: the pre-check proved the intent, this proves the result
    # (belt and suspenders against a race between the two path resolutions).
    if not _contained(vault_real, root_real):
        raise PersistRefused(
            "vault %s resolves to %s, which is outside the vault root %s — refusing"
            % (vault, vault_real, root_real))
    return vault_real


def _resolve_subdir(parent_real, name, vault_real):
    """makedirs(exist_ok=True) happily accepts a symlink-to-directory, so the
    intermediate component needs its own check: O_NOFOLLOW on the final file would
    not notice that `changes/` itself points out of the vault."""
    p = os.path.join(parent_real, name)
    if os.path.islink(p):
        raise PersistRefused("%s is a symlink, refusing" % p)
    os.makedirs(p, exist_ok=True)
    real = os.path.realpath(p)
    if not _contained(real, vault_real):
        raise PersistRefused("%s resolves to %s, outside the vault %s — refusing"
                             % (p, real, vault_real))
    if not os.path.isdir(real):
        raise PersistRefused("%s is not a directory, refusing" % p)
    return real


def _check_dest(path, vault_real):
    """Refuse a destination before opening it. O_NOFOLLOW below is the structural
    guarantee; this exists so the failure is a named refusal naming the path rather
    than an ELOOP the operator has to decode, and so the containment is asserted for
    the rename target too (rename does not follow symlinks, but a reader of this code
    should not have to know that to believe the destination is safe)."""
    if os.path.islink(path):
        raise PersistRefused("%s is a symlink, refusing to follow it out of the vault" % path)
    if os.path.exists(path) and not os.path.isfile(path):
        raise PersistRefused("%s exists and is not a regular file, refusing" % path)
    final = os.path.join(os.path.realpath(os.path.dirname(path)), os.path.basename(path))
    if not _contained(final, vault_real):
        raise PersistRefused("%s resolves to %s, outside the vault %s — refusing"
                             % (path, final, vault_real))


def _open_dir(name, dir_fd=None):
    """Open a directory component with O_NOFOLLOW, relative to an already-open
    directory descriptor when one is supplied.

    R20(b): resolving a path with realpath and then opening it BY PATH leaves a
    window in which any directory component (not just the final one) can be swapped
    out from under the resolved string. Opening each component relative to the
    previous component's already-open descriptor removes that window structurally —
    there is no second path resolution left to race, because nothing after the first
    open ever re-walks the path from the root.
    """
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    try:
        return os.open(name, flags) if dir_fd is None else os.open(name, flags, dir_fd=dir_fd)
    except OSError as e:
        raise PersistRefused("%s cannot be opened as a directory (%s)" % (name, e))


def _open_regular(path, flags, dir_fd=None):
    """os.open with O_NOFOLLOW plus regular-file AND single-link assertions on the fd.

    O_NOFOLLOW refuses a symlink at the final component and the fstat S_ISREG check
    refuses a directory, fifo, device or socket in that position — but NEITHER of
    those sees a HARD LINK (R20(a)). A hard link planted in the vault, pointing at a
    file inside the governance store, passes both existing barriers, and now that
    this step runs as the OWNER of the governance store, writing through that link is
    a write primitive against the store itself. `st_nlink > 1` is the check that
    closes it.

    Everything is asserted on the FD, never the path, so nothing can be swapped
    between the test and the write. `dir_fd`, when given, makes the open relative to
    an already-open directory descriptor rather than a path (R20(b)).
    """
    fd = (os.open(path, flags | os.O_NOFOLLOW, 0o600) if dir_fd is None
          else os.open(path, flags | os.O_NOFOLLOW, 0o600, dir_fd=dir_fd))
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode):
            raise PersistRefused("%s is not a regular file, refusing" % path)
        if st.st_nlink > 1:
            raise PersistRefused(
                "%s has %d hard links, refusing: a hard link to a file outside the "
                "vault passes both O_NOFOLLOW and the regular-file test, and this "
                "step runs as the owner of the governance store" % (path, st.st_nlink))
    except BaseException:
        os.close(fd)
        raise
    return fd


def _refuse_if_hardlinked(name, dir_fd, display_path):
    """If a file already occupies `name` (relative to `dir_fd`) and it is a hard
    link (nlink > 1), refuse before doing anything else to it.

    Two distinct reasons this runs BEFORE the operation rather than relying on
    `_open_regular`'s own nlink check alone:

    - a hard-linked TMP name would otherwise be truncated as a side effect of the
      open() syscall itself when O_TRUNC is requested — the truncation happens
      before any Python code can inspect the resulting fd, so detecting the hard
      link only AFTER that open is already too late to prevent the damage.
    - a hard-linked FINAL name is not corrupted by the rename that would replace it
      (rename(2) swaps the directory entry, it does not write through the old
      inode), but silently replacing a name that is entangled with a file outside
      the vault is exactly the kind of coincidence R20(a) exists to make a named,
      operator-visible refusal rather than best-effort silence.

    Symlinks at `name` are not this function's concern — O_NOFOLLOW here means a
    symlinked name raises OSError (ELOOP) rather than proceeding, and the callers in
    `persist()` already refuse symlinks at the path level via `_check_dest` before
    reaching this check.
    """
    try:
        fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=dir_fd)
    except FileNotFoundError:
        return
    except OSError as e:
        raise PersistRefused("%s cannot be checked before use (%s)" % (display_path, e))
    try:
        st = os.fstat(fd)
        if stat.S_ISREG(st.st_mode) and st.st_nlink > 1:
            raise PersistRefused(
                "%s has %d hard links, refusing: this step runs as the owner of the "
                "governance store and a hard link out of the vault is a write "
                "primitive against it" % (display_path, st.st_nlink))
    finally:
        os.close(fd)


def persist(vault, result, root=None):
    """Write <vault>/changes/<cid>.result.json and append <vault>/timeline.md.

    Every destination is proven to lie inside the vault, then opened RELATIVE TO an
    already-open directory descriptor (R20(b)), with O_NOFOLLOW, a regular-file
    assertion and a single-link assertion (R20(a)). Anything that cannot be proven
    raises PersistRefused (a ValueError) rather than being skipped.
    """
    # Canonical location: changeset_lib.result_path is the single definition of where a
    # result file lives — composing a second, divergent path here (e.g. vault root)
    # would leave the next reader looking in the wrong place.
    vault_real = _resolve_vault(vault, root)
    changes_name = os.path.basename(C.changes_dir(vault_real))
    _resolve_subdir(vault_real, changes_name, vault_real)

    vfd = _open_dir(vault_real)
    try:
        cfd = _open_dir(changes_name, dir_fd=vfd)
        try:
            base = os.path.basename(C.result_path(vault_real, result["changeset_id"]))
            tmp_base = base + ".tmp"
            path = os.path.join(vault_real, changes_name, base)
            _check_dest(path, vault_real)
            _check_dest(path + ".tmp", vault_real)
            # R20(a): checked before either the tmp write (which uses O_TRUNC — a
            # hard link there would be truncated by the open() call itself) or the
            # rename that replaces the final name.
            _refuse_if_hardlinked(tmp_base, cfd, path + ".tmp")
            _refuse_if_hardlinked(base, cfd, path)

            fd = _open_regular(tmp_base, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, dir_fd=cfd)
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(result, f, indent=2, sort_keys=True)
                f.flush()
                os.fsync(f.fileno())
            # os.rename, NOT os.replace: os.replace is NOT in os.supports_dir_fd on
            # darwin (measured 2026-08-24), while os.rename IS. On POSIX the two are
            # the same call — rename(2) already overwrites atomically; replace only
            # differs on Windows, which this tier does not target.
            os.rename(tmp_base, base, src_dir_fd=cfd, dst_dir_fd=cfd)
        finally:
            os.close(cfd)

        timeline = os.path.join(vault_real, "timeline.md")
        _check_dest(timeline, vault_real)
        fd = _open_regular("timeline.md", os.O_WRONLY | os.O_CREAT | os.O_APPEND,
                           dir_fd=vfd)
        with os.fdopen(fd, "a", encoding="utf-8") as f:
            f.write("- %s  change-set `%s`  status=%s  actions=%s\n"
                    % (result.get("finished_at", ""), result["changeset_id"],
                       result.get("status", "?"), result.get("applied", "?")))
    finally:
        os.close(vfd)
    return path
