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


def _open_regular(path, flags):
    """os.open with O_NOFOLLOW plus a regular-file assertion on the resulting fd.

    O_NOFOLLOW refuses a symlink at the final component (ELOOP/EMLINK), and the fstat
    refuses a directory, fifo, device or socket left in that position. Checked on the
    FD, not the path, so nothing can be swapped between the test and the write.
    """
    fd = os.open(path, flags | os.O_NOFOLLOW, 0o600)
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise PersistRefused("%s is not a regular file, refusing" % path)
    except BaseException:
        os.close(fd)
        raise
    return fd


def persist(vault, result, root=None):
    """Write <vault>/changes/<cid>.result.json and append <vault>/timeline.md.

    Every destination is resolved and proven to lie inside the vault first, and opened
    with O_NOFOLLOW; anything that cannot be proven raises PersistRefused (a
    ValueError) rather than being skipped.
    """
    # Canonical location: changeset_lib.result_path is the single definition of where a
    # result file lives — composing a second, divergent path here (e.g. vault root)
    # would leave the next reader looking in the wrong place.
    vault_real = _resolve_vault(vault, root)
    _resolve_subdir(vault_real, os.path.basename(C.changes_dir(vault_real)), vault_real)
    path = C.result_path(vault_real, result["changeset_id"])
    tmp = path + ".tmp"
    _check_dest(path, vault_real)
    _check_dest(tmp, vault_real)
    fd = _open_regular(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, sort_keys=True)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)
    timeline = os.path.join(vault_real, "timeline.md")
    _check_dest(timeline, vault_real)
    fd = _open_regular(timeline, os.O_WRONLY | os.O_CREAT | os.O_APPEND)
    with os.fdopen(fd, "a", encoding="utf-8") as f:
        f.write("- %s  change-set `%s`  status=%s  actions=%s\n"
                % (result.get("finished_at", ""), result["changeset_id"],
                   result.get("status", "?"), result.get("applied", "?")))
    return path
