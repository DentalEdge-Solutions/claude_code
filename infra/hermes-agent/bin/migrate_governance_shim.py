#!/usr/bin/env python3
"""Move mutation-governance state out of the read-write vault into the host-owned
governance store. Stdlib-only, idempotent, and count-verified.

Count verification is the point. Moving the audit log without carrying its records
resets the daily caps to zero — a guard that reads as green while measuring nothing.

Two properties a naive copy-then-check does NOT give you, and this module must:

1. A failed attempt must not poison a retry. `shutil.copy2` straight to the final
   destination path, followed by a count check, leaves a partial/corrupt destination
   file on disk when the check fails. The obvious operator response — re-run with
   --apply — then sees `os.path.isfile(dst)` as True and takes the idempotency
   `skipped` branch BEFORE any count is recomputed, permanently mistaking the corrupt
   partial copy for a successful migration. Every write here goes to a `.tmp` sibling
   in the destination directory and is `os.replace`d into place only after any
   validation for that write has passed; a failure removes the temp file so a retry
   starts clean.

2. The count check must see the realistic corruption. A copy truncated mid-way through
   the LAST line — far likelier than a whole line vanishing — leaves an identical
   non-blank line count before and after under a splitlines()-based counter, so a
   corrupt trailing record would pass the guard silently. `_count_lines` instead parses
   every non-blank line as JSON, exactly like the production reader
   (changeset_lib.iter_log_records / day_counts), and refuses on the first line that
   doesn't parse rather than silently declining to count it.
"""
import json, os, shutil


def _count_lines(path):
    """Count JSON-record lines the way the production log reader would.

    Blank lines are skipped (changeset_lib.iter_log_records does the same). A line that
    fails to parse as a JSON object is a FAILURE, not simply an uncounted line: the real
    reader fails closed on a corrupt record rather than skipping it, because the log
    feeds daily caps and an unreadable counter must not read as under-cap. Mirroring
    that here means a truncated trailing line — the realistic short-write mode — cannot
    silently produce a before/after count that happens to match.
    """
    if not os.path.isfile(path):
        return 0
    count = 0
    with open(path, encoding="utf-8") as f:
        for n, line in enumerate(f, 1):
            if not line.strip():
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError as e:
                raise RuntimeError(
                    "corrupt log line at %s:%d (%s) — refusing to count, because a "
                    "line that doesn't parse must not silently pass as a match or a "
                    "mismatch" % (path, n, e))
            if not isinstance(rec, dict):
                raise RuntimeError(
                    "corrupt log line at %s:%d (record must be an object)" % (path, n))
            count += 1
    return count


def _ensure_dir(path, mode=0o700):
    """Create `path` (and parents) if it does not already exist, and set its mode if
    this call is the one that created it.

    A pre-existing directory's permissions are left alone. The retry/failure tests in
    this suite pre-create a destination directory with restrictive permissions to force
    a copy failure on purpose; unconditionally chmod-ing to 0o700 on every call would
    silently repair that setup and defeat the test.
    """
    if os.path.isdir(path):
        return
    os.makedirs(path, exist_ok=True)
    os.chmod(path, mode)


def _atomic_copy(src, dst):
    """Copy `src` to a `.tmp` sibling of `dst` and atomically rename it into place.

    Guarantees `dst` never exists in a partial or corrupt state: it either does not
    exist, or it is a complete, successfully-copied file. Any failure during the copy
    removes the temp file before propagating, so a retry finds no destination file and
    genuinely retries instead of being fooled by a partial one.
    """
    tmp = dst + ".tmp"
    try:
        shutil.copy2(src, tmp)
    except Exception:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise
    os.replace(tmp, dst)


def migrate(vault_root, governance_root, dry_run=False):
    result = {"moved": [], "skipped": [], "counts_before": {}, "counts_after": {}}

    src_reg = os.path.join(vault_root, "_registry", "clients.json")
    dst_reg = os.path.join(governance_root, "registry", "clients.json")
    if os.path.isfile(src_reg) and not os.path.isfile(dst_reg):
        if not dry_run:
            _ensure_dir(os.path.dirname(dst_reg))
            _atomic_copy(src_reg, dst_reg)
        result["moved"].append("registry")
    elif os.path.isfile(dst_reg):
        result["skipped"].append("registry")

    src_switch = os.path.join(vault_root, "_governance", "mutation-enabled")
    if os.path.isfile(src_switch):
        # Deliberately NOT copied. The safe state is disabled, and a migration that
        # silently re-enables mutation in a new location is exactly the class of
        # surprise this whole increment exists to remove.
        result["skipped"].append("kill-switch (left disabled by design)")

    for slug in sorted(os.listdir(vault_root)):
        if slug.startswith("_"):
            continue
        src_log = os.path.join(vault_root, slug, "changes", "log.jsonl")
        if not os.path.isfile(src_log):
            continue
        dst_log = os.path.join(governance_root, "log", "%s.jsonl" % slug)
        if os.path.isfile(dst_log):
            result["skipped"].append(slug)
            continue
        before = _count_lines(src_log)
        result["counts_before"][slug] = before
        if dry_run:
            continue

        dst_log_dir = os.path.dirname(dst_log)
        _ensure_dir(dst_log_dir)
        tmp_log = dst_log + ".tmp"
        try:
            shutil.copy2(src_log, tmp_log)
            after = _count_lines(tmp_log)
            result["counts_after"][slug] = after
            if after != before:
                raise RuntimeError(
                    "migration lost records for %r: %d before, %d after — refusing to "
                    "continue, because a short log silently resets the daily caps"
                    % (slug, before, after))
        except Exception:
            try:
                os.remove(tmp_log)
            except OSError:
                pass
            raise
        os.replace(tmp_log, dst_log)
        result["moved"].append(slug)

    return result
