#!/usr/bin/env python3
"""Persist an executor run record into the governance store's records/ tree. Stdlib-only.

The executor runs in a one-shot container that deliberately does not mount the vault
(or records/), so it emits its result on stdout and the CALLER persists it. The audit
log in the governance store remains the reversibility record and is written by the
executor, fsynced per action; result.json and timeline.md are convenience artifacts for
humans and for Hermes. If this step is lost, the audit log still holds the truth and
--undo still works.

THIS STEP RUNS HOST-SIDE, as hermes-broker, and writes into records/<slug>/ in the
governance store: records/ itself is hermes-broker:hermes 0o2750 (host_layout), NOT
mounted into any container, and NOT writable by the gateway.

Until F12 (2026-09-23) this step wrote into data/vaults instead — the one tree the
gateway (and, through it, anything reachable from the mutation path) could read and
write. A symlink planted there turned this step into a write primitive against
anything the host user could reach: demonstrated on 2026-08-19 by symlinking
timeline.md at the governance store's `control/mutation-enabled` (the O_CREAT|O_APPEND
open then CREATES it, and kill_switch_ok() only asks whether the file exists, so
mutation becomes globally enabled) and by symlinking the `.tmp` path at the audit log
(the O_TRUNC open then erases the cap consumption the guards count). That was reachable
in practice because `--undo` runs with the kill switch off and still emits a result
line, and because HERMES_GOVERNANCE_DIR is in `.env`, the gateway's env_file.

Moving the destination to records/ closes that specific vector: nothing that can plant
a symlink can reach records/ any more — it is owned by the same identity that runs this
step, unmounted, unreadable and unwritable by the gateway and the executor alike. The
containment below stays anyway, as defence in depth and because it is structural rather
than a response to one incident: a future writer added to this module, a bind mount
added later, or a mode mis-set on records/ itself must not silently turn this step back
into a write primitive the way the vault did. Refuse loudly and provably, not "it
shouldn't be reachable so the check can go."

The containment is structural rather than a check: `os.O_NOFOLLOW` means a symlinked
destination cannot be opened at all, and the fstat regular-file test means a directory
or a fifo in that position refuses instead of raising something unrelated. The
resolved-path checks then cover the intermediate components, which O_NOFOLLOW on the
final component does not.

OPERATIONAL CONSTRAINT (R20(a)): nothing may hard-link INTO records/. The st_nlink > 1
refusal below is not a false-positive risk to soften — it blocks a proven, demonstrated
write primitive against the host-owned governance store now that this step runs as that
store's owner (see the hardlink docstrings below). But it does mean a backup or rotation
tool that hard-links rather than copies (`cp -al`, rsnapshot-style snapshots, and similar)
would permanently fail every future persist for whichever record file it touches. Document
this as a deployment constraint on whatever backs up the governance store — copy, don't
hard-link — rather than weakening the check to accommodate it.
"""
import json, os, stat, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import governance_lib

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
#
# S1-M1: the guard used to check only os.open and os.rename, while the comment above
# named four calls as measured. os.mkdir and os.unlink became load-bearing dir_fd calls
# in T8 and were never added, so the CHECKED set and the DEPENDED-ON set had drifted
# apart — the same defect class as a requirement list written from memory. Derived from
# one tuple now, so the two cannot drift again: adding a dir_fd call to this module
# without adding it here is the mistake this is shaped to prevent.
#
# Refined by the S1-M1 probe: an unsupported mkdir/unlink was never a silent fallback.
# Python raises NotImplementedError for a dir_fd it cannot honour, and the probe
# confirmed nothing is created and no path-based open happens. The hole was therefore
# documentation plus an ESCAPING exception (see persist-run-record.py's handler), not a
# TOCTOU. This guard still belongs here: refusing at import with a message beats a
# NotImplementedError from somewhere in the middle of a write chain.
_REQUIRED_DIR_FD_CALLS = (os.open, os.rename, os.mkdir, os.unlink)
_missing = [f.__name__ for f in _REQUIRED_DIR_FD_CALLS if f not in os.supports_dir_fd]
if _missing:
    raise RuntimeError("persist_run_record_shim requires dir_fd support for %s "
                       "(os.supports_dir_fd); refusing to fall back to path-based "
                       "operations, which reintroduces the directory-component TOCTOU"
                       % ", ".join(_missing))


class PersistRefused(ValueError):
    """A destination that cannot be proven to stay inside the records directory.

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


def _resolve_records(record_dir, root=None):
    """Resolve the per-client records directory and prove it lies under the records
    root inside the governance store.

    Refuses a symlinked records directory outright even when it resolves back inside
    the root: the guarantee wanted here is "this directory is what it appears to be",
    and admitting a benign-looking symlink today is what makes the next one arguable.

    R20(c): the containment check precedes any creation. Creation itself happens later,
    in persist(), relative to an already-open parent descriptor — this function only
    proves the destination before anything touches disk, so a refusal here can never
    leave an attacker-chosen path behind.
    """
    root_real = os.path.realpath(
        root if root is not None
        else os.path.join(governance_lib.governance_root(), "records"))
    if os.path.islink(record_dir):
        raise PersistRefused("records path is a symlink, refusing: %s" % record_dir)
    # Prove containment of the path we are ABOUT to use, using the resolved parent
    # (the per-client directory may not exist yet, so it cannot be realpath'd
    # directly).
    records_real = os.path.join(os.path.realpath(os.path.dirname(record_dir)),
                                os.path.basename(record_dir))
    if not _contained(records_real, root_real):
        raise PersistRefused(
            "records dir %s resolves to %s, which is outside the records root %s — refusing"
            % (record_dir, records_real, root_real))
    return records_real


def _check_dest(path, records_real):
    """Refuse a destination before opening it. O_NOFOLLOW below is the structural
    guarantee; this exists so the failure is a named refusal naming the path rather
    than an ELOOP the operator has to decode, and so the containment is asserted for
    the rename target too (rename does not follow symlinks, but a reader of this code
    should not have to know that to believe the destination is safe)."""
    if os.path.islink(path):
        raise PersistRefused("%s is a symlink, refusing to follow it out of the "
                             "records directory" % path)
    if os.path.exists(path) and not os.path.isfile(path):
        raise PersistRefused("%s exists and is not a regular file, refusing" % path)
    final = os.path.join(os.path.realpath(os.path.dirname(path)), os.path.basename(path))
    if not _contained(final, records_real):
        raise PersistRefused("%s resolves to %s, outside the records directory %s — "
                             "refusing" % (path, final, records_real))


def _open_dir(name, dir_fd=None):
    """Open a directory component with O_NOFOLLOW, relative to an already-open
    directory descriptor when one is supplied.

    R20(b): resolving a path with realpath and then opening it BY PATH leaves a
    window in which any directory component (not just the final one) can be swapped
    out from under the resolved string. Opening each component relative to the
    previous component's already-open descriptor removes that window structurally.

    Scoped claim, not a blanket one: THIS FUNCTION performs exactly one lookup of
    `name` (relative to `dir_fd`, or the process cwd when `dir_fd` is None) and
    nothing more — it does not itself re-walk a path. The guarantee that NOTHING in
    the whole call chain re-walks a path depends on every caller chaining subsequent
    opens off the descriptor this returns, rather than re-deriving a path string.
    `persist()` does this for `parent_real` -> `pfd` -> the per-client records
    directory (created via `os.mkdir(slug_name, dir_fd=pfd)`, opened via this
    function with `dir_fd=pfd`) -> `rfd`, so no directory component on that chain is
    looked up by path more than once.
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
    those sees a HARD LINK (R20(a)). A hard link planted in the records directory,
    pointing at a file elsewhere inside the governance store, passes both existing
    barriers, and now that this step runs as the OWNER of the governance store,
    writing through that link is a write primitive against the store itself.
    `st_nlink > 1` is the check that closes it.

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
                "records directory passes both O_NOFOLLOW and the regular-file test, "
                "and this step runs as the owner of the governance store"
                % (path, st.st_nlink))
    except BaseException:
        os.close(fd)
        raise
    return fd


def _create_tmp_exclusive(name, dir_fd, display_path):
    """Create the tmp write target with O_CREAT|O_EXCL, never O_TRUNC.

    FINDING 1 (post-implementation review, 2026-08-26): `_refuse_if_hardlinked`'s
    check-then-act sequence has a real window on this specific path. `_open_regular`
    used to open the tmp name with O_TRUNC, and O_TRUNC truncates as a side effect of
    the open() SYSCALL ITSELF — before any Python code runs, before any fd exists to
    fstat. Measured: with the pre-check disabled, a hard link planted between the
    pre-check's close() and this open() is truncated before the nlink check on the
    resulting fd ever gets a chance to fire. A refusal that happens after the
    truncation is not a refusal of the truncation.

    O_EXCL closes this STRUCTURALLY rather than with a tighter check: create and the
    existence test are one syscall, so there is no window between "does a file already
    occupy this name" and "create it" for anything to race into. If ANYTHING already
    occupies `name` — a hard link, a symlink, an ordinary file — this raises
    FileExistsError with zero bytes written and zero bytes truncated.

    The one legitimate reason `name` might already exist is a stale `.tmp` left behind
    by a previous interrupted run. On EEXIST this opens the existing name (by fd,
    O_NOFOLLOW) purely to tell the two cases apart: a hard link (nlink > 1) is refused
    outright, exactly as `_refuse_if_hardlinked` would refuse it, and nothing is
    unlinked or touched. An ordinary single-linked leftover is unlinked and the
    exclusive create is retried EXACTLY ONCE — chosen over a unique-per-attempt temp
    name so the module keeps its one deterministic tmp name per change-set id (the
    invariant the rename step and any future cleanup logic already depend on) instead
    of leaving orphaned uniquely-named tmp files behind on every crash. A second
    EEXIST after the retry (something actively recreating the name faster than we can
    clear it) is treated as a refusal rather than retried further, so a race cannot be
    turned into an unbounded loop.
    """
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
    try:
        return os.open(name, flags, 0o600, dir_fd=dir_fd)
    except FileExistsError:
        pass

    # Reaching here means something already occupies `name` that isn't a symlink at
    # the path level (persist() already refused that earlier, via _check_dest) —
    # most likely the hard link this function exists to catch. Still wrapped: never
    # let a bare OSError escape this module (PersistRefused is the only refusal
    # shape callers are contracted to see).
    try:
        fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=dir_fd)
    except OSError as e:
        raise PersistRefused("%s cannot be checked before creating it (%s)" % (display_path, e))
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode):
            raise PersistRefused("%s exists and is not a regular file, refusing" % display_path)
        if st.st_nlink > 1:
            raise PersistRefused(
                "%s has %d hard links, refusing: this step runs as the owner of the "
                "governance store and a hard link out of the records directory is a "
                "write primitive against it" % (display_path, st.st_nlink))
    finally:
        os.close(fd)

    # Ordinary single-linked leftover from an interrupted run: clear it and retry
    # the exclusive create once.
    try:
        os.unlink(name, dir_fd=dir_fd)
    except FileNotFoundError:
        pass  # raced away between the stat above and here; the retry below covers it
    try:
        return os.open(name, flags, 0o600, dir_fd=dir_fd)
    except FileExistsError:
        raise PersistRefused(
            "%s could not be created exclusively even after clearing a stale "
            "leftover — something is actively recreating it, refusing rather than "
            "retrying indefinitely" % display_path)


def _refuse_if_hardlinked(name, dir_fd, display_path):
    """If a file already occupies `name` (relative to `dir_fd`) and it is a hard
    link (nlink > 1), refuse before doing anything else to it.

    BELT-AND-BRACES, not the sole protection, for either caller:

    - for the tmp name, `_create_tmp_exclusive`'s O_CREAT|O_EXCL is what actually
      closes the truncation window structurally (see its docstring — FINDING 1,
      2026-08-26 review: this function's own check-then-act gap was measured
      exploitable when it was the only thing standing between a hard link and an
      O_TRUNC open). This call now just gives an earlier, friendlier refusal before
      `_create_tmp_exclusive` is even attempted.
    - for the FINAL name, a hard link is not corrupted by the rename that would
      replace it (rename(2) swaps the directory entry, it does not write through the
      old inode), but silently replacing a name that is entangled with a file outside
      the records directory is exactly the kind of coincidence R20(a) exists to make a
      named, operator-visible refusal rather than best-effort silence. This IS the
      only check for that path — there is no structural equivalent needed because
      rename itself is not a destructive operation on the old inode's content.

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
                "governance store and a hard link out of the records directory is a "
                "write primitive against it" % (display_path, st.st_nlink))
    finally:
        os.close(fd)


def persist(record_dir, result, root=None):
    """Write <record_dir>/<cid>.result.json and append <record_dir>/timeline.md into
    the per-client records directory inside the governance store.

    Every destination is proven to lie inside the records directory, then opened
    RELATIVE TO an already-open directory descriptor (R20(b)), with O_NOFOLLOW, a
    regular-file assertion and a single-link assertion (R20(a)). Anything that cannot
    be proven raises PersistRefused (a ValueError) rather than being skipped. Modes are
    set explicitly on open file descriptors — governance_lib.RECORDS_DIR_MODE (0o2750,
    setgid) on the per-client directory, 0640 on both files — so no umask, however
    strict, can make them unreadable later.
    """
    records_real = _resolve_records(record_dir, root)
    parent_real = os.path.dirname(records_real)
    slug_name = os.path.basename(records_real)

    # Validate and derive every destination NAME before anything is created (R20(c)
    # extended to slug/cid validation, spec 2026-09-23 review): governance_lib.record_
    # path and .records_timeline_path validate slug_name and the changeset id via
    # governance_lib's own _slug/_cid, and a refusal on a bad id must not leave an
    # attacker-chosen directory behind either — exactly what _resolve_records's
    # docstring already promises for the containment checks, extended here to cover
    # name validation too.
    base = os.path.basename(governance_lib.record_path(slug_name, result["changeset_id"]))
    tmp_base = base + ".tmp"
    timeline_base = os.path.basename(governance_lib.records_timeline_path(slug_name))

    # The records/ tree itself is a hard prerequisite laid down by host_layout /
    # init-host-layout.py --apply (setgid, hermes-broker:hermes) — NOT something this
    # module may create. Auto-creating it here (as an earlier version of this function
    # did, via a defensive os.makedirs) would build it path-based, with a umask-derived
    # mode and no setgid bit — exactly the wrong-moded tree the row exists to prevent
    # (spec 2026-09-23 §2.4 correction R1) — and init-host-layout.py verifies the row
    # but deliberately never repairs it. Refuse instead of silently building it wrong.
    if not os.path.isdir(parent_real):
        raise PersistRefused(
            "records root %s does not exist — the governance store layout is a hard "
            "prerequisite; run init-host-layout.py --apply before persisting records"
            % parent_real)

    pfd = _open_dir(parent_real)
    try:
        # R20(b): create the per-client directory relative to the already-open
        # parent descriptor — os.mkdir IS in os.supports_dir_fd (see the import-time
        # guard above) — then reopen it the same way. No directory component on this
        # chain is looked up by path more than once.
        try:
            os.mkdir(slug_name, dir_fd=pfd)
        except FileExistsError:
            pass

        rfd = _open_dir(slug_name, dir_fd=pfd)
        try:
            # Explicit, umask-independent (spec 2026-09-23 §2.4, correction R1): MUST
            # be governance_lib.RECORDS_DIR_MODE (0o2750, setgid), never a bare 0750.
            # records/ is setgid, so a freshly created per-client directory already
            # inherits group "hermes" and its OWN setgid bit from the kernel — but that
            # inheritance happens independently of, and BEFORE, this fchmod call, and a
            # plain 0750 here would STRIP the inherited setgid bit right back off.
            # Without it, files this step writes take the writing PROCESS's effective
            # group — hermes-broker (Group=hermes-broker in the unit, hermes only
            # supplementary) — not the inherited "hermes", which is the exact failure
            # the row's setgid bit exists to prevent. Darwin has no such uid/gid
            # separation to expose this, which is why it was missed at first: the
            # spec briefly said plain 0750 too, corrected 2026-09-23 (R1).
            os.fchmod(rfd, governance_lib.RECORDS_DIR_MODE)

            path = os.path.join(records_real, base)
            _check_dest(path, records_real)
            _check_dest(path + ".tmp", records_real)
            # Belt-and-braces early refusal (see _refuse_if_hardlinked's docstring);
            # the STRUCTURAL protection for the tmp name is _create_tmp_exclusive's
            # O_EXCL below, not this check.
            _refuse_if_hardlinked(tmp_base, rfd, path + ".tmp")
            _refuse_if_hardlinked(base, rfd, path)

            fd = _create_tmp_exclusive(tmp_base, rfd, path + ".tmp")
            os.fchmod(fd, 0o640)
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(result, f, indent=2, sort_keys=True)
                f.flush()
                os.fsync(f.fileno())
            # os.rename, NOT os.replace: os.replace is NOT in os.supports_dir_fd on
            # darwin (measured 2026-08-24), while os.rename IS. On POSIX the two are
            # the same call — rename(2) already overwrites atomically; replace only
            # differs on Windows, which this tier does not target.
            os.rename(tmp_base, base, src_dir_fd=rfd, dst_dir_fd=rfd)

            timeline = os.path.join(records_real, timeline_base)
            _check_dest(timeline, records_real)
            tfd = _open_regular(timeline_base, os.O_WRONLY | os.O_CREAT | os.O_APPEND,
                               dir_fd=rfd)
            os.fchmod(tfd, 0o640)
            with os.fdopen(tfd, "a", encoding="utf-8") as f:
                f.write("- %s  change-set `%s`  status=%s  actions=%s\n"
                        % (result.get("finished_at", ""), result["changeset_id"],
                           result.get("status", "?"), result.get("applied", "?")))
        finally:
            os.close(rfd)
    finally:
        os.close(pfd)
    return path
