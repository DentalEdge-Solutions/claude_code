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
import json, os, shutil, stat, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import governance_lib


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


def _check_log_dir(log_dir, expected_gid):
    """Stat what append_log and bootstrap_logs both rely on before trusting log_dir to
    create anything inside it: it must not be group-writable (write on a directory is
    what grants unlink — the S3-b hazard) and it must carry the executor's group
    (setgid then propagates that group to every file created here; the wrong group
    means a new file inherits something other than EXECUTOR_GID even with setgid set).

    Named after whichever is actually wrong, rather than assuming a single cause —
    "missing setgid" and "wrong directory group" are different faults with different
    remedies, and conflating them sends an operator to fix the wrong thing."""
    st = os.stat(log_dir)
    mode = stat.S_IMODE(st.st_mode)
    if mode & 0o020:
        raise RuntimeError(
            "%s is group-writable (mode %04o) — refusing, because write on a directory "
            "is what grants unlink and this would reinstate the hazard S3-b closed. Fix "
            "with: sudo chmod 2750 %s" % (log_dir, mode, log_dir))
    if st.st_gid != expected_gid:
        raise RuntimeError(
            "%s has group %d, not the executor's group %d — refusing, because a file "
            "created here inherits THIS directory's group under setgid, so the wrong "
            "directory group means every new file lands wrong too. Fix with: "
            "sudo chgrp %d %s" % (log_dir, st.st_gid, expected_gid, expected_gid, log_dir))


def bootstrap_logs(governance_root, dry_run=False, expected_gid=None):
    """Guarantee every REGISTERED client a pre-created audit log.

    S3-b's second half. Under the append-but-not-unlink layout the executor cannot
    CREATE log/<slug>.jsonl — log/ is host-owned 2750 — so a missing log is no longer a
    normal resting state for a registered client, and iter_log_records fails closed on
    it. That is only safe once every registered client is guaranteed a log, and there is
    no programmatic registration hook: clients.json is hand-edited, and migrate() only
    carries logs that ALREADY exist in a vault. Hence this rides the same operator CLI
    (ruling R23), as a separate mode rather than folded into migrate(): migration is a
    one-time vault->store move, registration is continuous, and the pre-flight's refusal
    has to name a command an operator can run right after editing the registry.

    Three properties this must have, each earned:

    1. It REFUSES a missing log/ rather than creating one. _ensure_dir would lay it down
       at 0700, producing exactly the unusable store the pre-flight exists to catch.
    2. Creation is O_CREAT|O_EXCL, never open(p, "w"). Truncation would destroy the
       reversibility record this whole wave protects, and an existence-only idempotency
       check would call that a pass.
    3. It VERIFIES what it created and refuses on a mismatch. log/ without its setgid
       bit gives a new file the creating user's primary group; 0660 then grants the
       wrong group and uid 10000 falls through to `other`, so the executor can neither
       append nor unlink. That layout passes a delete probe and fails an append control
       — it looks like a fix. Creating the file is not evidence; stat'ing it is.
    """
    if expected_gid is None:
        expected_gid = governance_lib.EXECUTOR_GID
    log_dir = os.path.join(governance_root, "log")
    if not os.path.isdir(log_dir):
        raise RuntimeError(
            "no log directory at %s — refusing to create it, because a log/ laid down "
            "here would get the wrong mode and produce a store the executor cannot use. "
            "Create it host-side at mode %04o (see the README's ownership section) and "
            "re-run." % (log_dir, governance_lib.LOG_DIR_MODE))
    # I2(b): stat what we are about to create files under, not just what we are about
    # to create them AS. A log/ that already exists but is group-writable or carries
    # the wrong group is a store this function would otherwise populate with files
    # that pass its own per-file check below by accident (e.g. expected_gid happening
    # to equal the caller's own primary group) while remaining unsafe for the real
    # executor. This mostly subsumes the per-file group check's wrong-gid branch below
    # for the fresh-file case; it does NOT catch a missing setgid bit on an otherwise
    # correctly-owned directory, which only shows up once a file is actually created —
    # that residual is still the per-file check's job.
    _check_log_dir(log_dir, expected_gid)

    reg = governance_lib.clients_registry_path(governance_root)
    try:
        with open(reg, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError) as e:
        raise RuntimeError(
            "cannot read the client registry at %s (%s) — refusing, because a registry "
            "that will not parse resolves no client, and reading it as 'zero registered "
            "clients' would report success over a store that cannot work" % (reg, e))
    # WITH the default, matching vault_lib.load_registry:49 — an absent "clients" key is
    # zero registered clients, not a malformed registry.
    clients = data.get("clients", {}) if isinstance(data, dict) else None
    if not isinstance(clients, dict):
        raise RuntimeError("registry 'clients' must be a JSON object: %s" % reg)

    result = {"created": [], "skipped": []}
    for slug in sorted(clients):
        # NOTE: this RAISES on an invalid slug, unlike preflight-governance-access.py's
        # _check_registered_logs's identical SLUG_RE filter, which silently CONTINUEs.
        # Both are defensible — this is a mutating tool where silently skipping a bad
        # registration would be exactly the ambiguity it exists to remove, while the
        # pre-flight is a read-only refusal gate that must not itself fail loudly on a
        # registry an operator is free to hand-edit incorrectly — but nothing else says
        # they differ, so it is stated here.
        if not isinstance(slug, str) or not governance_lib.SLUG_RE.fullmatch(slug):
            raise RuntimeError(
                "registry contains a slug that is not resolvable (%r) — refusing rather "
                "than skipping it, because a skipped registration is exactly the "
                "ambiguity this function exists to remove" % (slug,))
        dst = governance_lib.log_path(slug, governance_root)
        if os.path.exists(dst):
            result["skipped"].append(slug)
            continue
        if dry_run:
            result["created"].append(slug)
            continue
        fd = os.open(dst, os.O_CREAT | os.O_EXCL | os.O_WRONLY,
                     governance_lib.LOG_FILE_MODE)
        os.close(fd)
        try:
            os.chmod(dst, governance_lib.LOG_FILE_MODE)   # defeat the umask
            st = os.stat(dst)
            mode = stat.S_IMODE(st.st_mode)
            if mode != governance_lib.LOG_FILE_MODE:
                raise RuntimeError(
                    "%s landed at mode %04o, not %04o — refusing"
                    % (dst, mode, governance_lib.LOG_FILE_MODE))
            if st.st_gid != expected_gid:
                # Stat log_dir itself rather than assuming a single cause: "missing
                # setgid" and "setgid present but the directory's own group is wrong"
                # are different faults with different remedies, and a message that
                # always blames setgid sends an operator to run the wrong command when
                # the real problem is the directory's group.
                dir_st = os.stat(log_dir)
                if dir_st.st_mode & stat.S_ISGID:
                    cause = ("%s has group %d, not the executor's group %d — a new "
                              "file inherits THIS directory's group under setgid, so "
                              "the directory's own group is wrong. Run `sudo chgrp %d "
                              "%s`" % (log_dir, dir_st.st_gid, expected_gid,
                                       expected_gid, log_dir))
                else:
                    cause = ("%s is missing its setgid bit, without which a new file "
                              "inherits the creating user's primary group instead of "
                              "the directory's. Run `chmod g+s %s`" % (log_dir, log_dir))
                raise RuntimeError(
                    "%s landed with group %d, not the executor's group %d — refusing: "
                    "%s, then re-run." % (dst, st.st_gid, expected_gid, cause))
        except Exception:
            try:
                os.remove(dst)  # created by THIS call; never remove a pre-existing log
            except OSError:
                pass
            raise
        result["created"].append(slug)
    return result


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
        # I3 / D4: if THIS call is the one laying down log/ (the normal deploy already
        # created it host-side per the README's ownership section before migration
        # ever runs), _ensure_dir's mode= sets the MODE but not the GROUP — a directory
        # made by an unprivileged process inherits that process's own primary group,
        # not EXECUTOR_GID. setgid then propagates that wrong group to every log
        # migrated in, reproducing the exact hazard this wave exists to close. Verify
        # only on first creation (not on a pre-existing log/), and remove what we just
        # made on failure so a retry starts clean instead of silently reusing a
        # directory this call already proved is wrong.
        log_dir_created_here = not os.path.isdir(dst_log_dir)
        _ensure_dir(dst_log_dir, mode=governance_lib.LOG_DIR_MODE)
        if log_dir_created_here:
            try:
                _check_log_dir(dst_log_dir, governance_lib.EXECUTOR_GID)
            except RuntimeError:
                try:
                    os.rmdir(dst_log_dir)
                except OSError:
                    pass
                raise
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
