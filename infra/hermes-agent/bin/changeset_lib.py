#!/usr/bin/env python3
"""Typed change-set validation, canonical serialization, and hashing for the
Hermes mutation tier. Stdlib-only. Holds NO credential and performs no network
I/O — this library is used by propose/approve (uncredentialed) and by apply.

The mutation tier removes the read-only-credential backstop, so validation here
is fail-closed on every field: unknown action types, unknown fields, non-digit
ids, and control characters are all refusals, never coercions.
See docs/superpowers/specs/2026-08-12-hermes-mutation-tier-design.md
"""
import contextlib, datetime, fcntl, hashlib, json, os, re, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import governance_lib
import vault_lib

ACTION_TYPES = ("add_campaign_negative",)
MATCH_TYPES = ("EXACT", "PHRASE", "BROAD")
ISO = "%Y-%m-%dT%H:%M:%SZ"
KEYWORD_MAX = 80                      # Google Ads keyword text limit

ID_RE = re.compile(r"^[0-9]{1,15}$")
CHANGESET_ID_RE = re.compile(r"^[0-9]{8}-[0-9]{6}-[0-9a-f]{8}$")
PROJECT_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
OPERATOR_RE = re.compile(r"^[A-Za-z0-9._@-]{1,64}$")
DAY_RE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")

ACTION_FIELDS = {"type", "campaign_id", "keyword", "match_type"}
CHANGESET_FIELDS = {"changeset_id", "client", "project", "customer_id", "created_at", "actions"}


def _require_str(v, field):
    """Refuse non-string JSON types outright. A validator that silently coerces
    accepts inputs it never specified: `str(22233344455)` would let a JSON NUMBER
    pass a digits-only check and then serialize unquoted, breaking the schema
    contract the approval hash is taken over. Fail closed on type, not just shape."""
    if not isinstance(v, str):
        raise ValueError(f"{field} must be a JSON string, got {type(v).__name__}")
    return v


def validate_keyword(kw):
    if not isinstance(kw, str) or not kw.strip():
        raise ValueError("keyword must be a non-empty string")
    if len(kw) > KEYWORD_MAX:
        raise ValueError(f"keyword exceeds {KEYWORD_MAX} characters (got {len(kw)})")
    if any(ord(c) < 0x20 or ord(c) == 0x7F for c in kw):
        raise ValueError("keyword contains control characters")
    return kw


def validate_action(a):
    """Fail-closed validation of one typed action. Keyword text is free-form (it is
    whatever the public typed into Google), so it travels as JSON to the mutator and
    is never spliced into a shell command."""
    if not isinstance(a, dict):
        raise ValueError("action must be an object")
    extra = set(a) - ACTION_FIELDS
    if extra:
        raise ValueError(f"unknown action fields: {sorted(extra)}")
    if a.get("type") not in ACTION_TYPES:
        raise ValueError(f"unknown action type: {a.get('type')!r} (allowed {list(ACTION_TYPES)})")
    if not ID_RE.fullmatch(_require_str(a.get("campaign_id"), "campaign_id")):
        raise ValueError(f"invalid campaign_id: {a.get('campaign_id')!r} (digits only)")
    if a.get("match_type") not in MATCH_TYPES:
        raise ValueError(f"invalid match_type: {a.get('match_type')!r} (allowed {list(MATCH_TYPES)})")
    validate_keyword(a.get("keyword"))
    return a


def validate_changeset(cs, max_actions):
    if not isinstance(cs, dict):
        raise ValueError("change-set must be an object")
    extra = set(cs) - CHANGESET_FIELDS
    if extra:
        raise ValueError(f"unknown change-set fields: {sorted(extra)}")
    if not CHANGESET_ID_RE.fullmatch(_require_str(cs.get("changeset_id"), "changeset_id")):
        raise ValueError(f"invalid changeset_id: {cs.get('changeset_id')!r}")
    vault_lib.validate_slug(cs.get("client"))
    if not PROJECT_RE.fullmatch(_require_str(cs.get("project"), "project")):
        raise ValueError(f"invalid project: {cs.get('project')!r}")
    vault_lib.validate_customer_id(cs.get("customer_id"))
    datetime.datetime.strptime(_require_str(cs.get("created_at"), "created_at"), ISO)   # raises ValueError
    actions = cs.get("actions")
    if not isinstance(actions, list) or not actions:
        raise ValueError("actions must be a non-empty list")
    if len(actions) > max_actions:
        raise ValueError(f"{len(actions)} actions exceeds cap actions_per_changeset={max_actions}")
    for a in actions:
        validate_action(a)
    return cs


def canonical_bytes(cs):
    """Deterministic serialization: sorted keys, no whitespace. propose writes this
    exact form to disk, so hashing the raw file bytes later is both canonical and
    byte-exact."""
    return json.dumps(cs, sort_keys=True, separators=(",", ":")).encode("utf-8")

CAP_KEYS = ("actions_per_changeset", "actions_per_client_day",
            "applies_per_client_day", "approval_ttl_hours")
_CAP_VALUE_RE = re.compile(r"^[0-9]{1,6}$")


def _strip_inline_comment(stripped):
    """Remove a trailing inline YAML comment (# preceded by whitespace). A '#' flush
    against a value is part of the value, per YAML inline-comment semantics."""
    return re.sub(r"\s+#.*$", "", stripped)


def _iter_project_lines(path, project):
    """Yield (indent, stripped) for each meaningful line inside projects.<project>.

    The single registry walker for this tier. run-ads-report.py has its own copy for
    read_execute and stays frozen (Inc-3 is unchanged by this increment), but nothing
    NEW duplicates it: read_workdir, read_block, read_mutate_execute, and
    read_allow_list are all built on this one generator.
    """
    cur = None
    with open(path, encoding="utf-8") as f:
        for raw in f:
            line = raw.rstrip("\n")
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            indent = len(line) - len(line.lstrip(" "))
            stripped = _strip_inline_comment(line.strip())
            if indent == 2 and stripped.endswith(":"):          # a project name
                cur = stripped[:-1]
                continue
            if cur == project:
                yield indent, stripped


def read_workdir(path, project):
    """The project's workdir. A duplicate refuses, for the same reason read_block's
    duplicates do: workdir is half of the path Hermes executes, so a repeated key
    silently choosing a winner would silently choose which tree runs."""
    found = None
    for indent, stripped in _iter_project_lines(path, project):
        if indent == 4 and stripped.startswith("workdir:"):
            if found is not None:
                raise ValueError(f"duplicate 'workdir' key for project {project!r} — refusing "
                                 "rather than taking the first or last value")
            found = stripped.split(":", 1)[1].strip()
    if found is None:
        raise ValueError(f"no workdir for project {project!r}")
    return found


def read_mask_paths(path, project):
    """Workdir-relative paths masked out of the container view.

    A project with no declaration yields [] — nothing claimed, nothing to enforce.
    A duplicate key refuses, for the same reason read_workdir's does: silently
    choosing a winner would silently choose which paths stay exposed.
    """
    found = None
    collecting = False
    for indent, stripped in _iter_project_lines(path, project):
        if indent == 4 and stripped.startswith("mask_paths:"):
            if found is not None:
                raise ValueError(f"duplicate 'mask_paths' key for project {project!r} — "
                                 "refusing rather than taking the first or last value")
            found, collecting = [], True
            continue
        if collecting:
            if indent == 6 and stripped.startswith("- "):
                found.append(stripped[2:].strip())
                continue
            collecting = False
    return found or []


def read_block(path, project, block):
    """Parse projects.<project>.<block> into scalars plus `allow` and `caps`.

    Scope discipline (from run-ads-report.py's Inc-2 review fix): ANY sibling or
    shallower line closes the block, so a later key cannot bleed into `allow`.
    Returns empty structures when the block is absent — callers decide whether that
    is a refusal (read_mutate_execute) or simply nothing to check (read_allow_list).

    DUPLICATE KEYS REFUSE, at EVERY depth. A repeated `allow:` header would otherwise
    ACCUMULATE, silently admitting a second mutator; a repeated scalar would silently
    take the last value, quietly swapping the interpreter. In a file that decides what
    may mutate a live account, a duplicate key is a mistake — a merge artifact or a bad
    hand-edit — not an intent, so it is loud rather than resolved.

    The depth part is not incidental. Duplicate detection originally covered only the
    indent-6 keys, so a repeated CAP — one level deeper — still took a silent winner.
    That is the worst place to allow it: `applies_per_client_day` is the load-bearing
    cap against a malfunction repeating, and a merge artifact could raise it unnoticed
    while every visible guard still read as correct.
    """
    inside = False
    sub = None
    seen = set()
    seen_deep = set()          # keys inside the current indent-6 sub-block
    got = {"allow": [], "caps": {}}
    for indent, stripped in _iter_project_lines(path, project):
        if indent == 4 and stripped == f"{block}:":
            if inside or seen:
                raise ValueError(f"duplicate {block!r} block for project {project!r} — refusing")
            inside = True; sub = None
        elif indent <= 4:                                        # sibling/shallower closes scope
            inside = False; sub = None
        elif indent == 6 and inside:
            key = stripped[:-1] if stripped in ("allow:", "caps:") else stripped.partition(":")[0].strip()
            if key in seen:
                raise ValueError(f"duplicate {key!r} key in {block} for project {project!r} — "
                                 "refusing rather than merging or taking the last value")
            seen.add(key)
            seen_deep = set()                               # entering a new sub-block
            if stripped in ("allow:", "caps:"):
                sub = key
            else:
                sub = None
                k, _, v = stripped.partition(":")
                got[k.strip()] = v.strip()
        elif indent == 8 and inside:
            if sub == "allow" and stripped.startswith("- "):
                item = stripped[2:].strip()
                if item in seen_deep:
                    raise ValueError(f"duplicate allow entry {item!r} in {block} for project "
                                     f"{project!r} — refusing")
                seen_deep.add(item)
                got["allow"].append(item)
            elif sub == "caps":
                k, _, v = stripped.partition(":")
                k = k.strip()
                if k in seen_deep:
                    raise ValueError(f"duplicate cap {k!r} in {block} for project {project!r} — "
                                     "refusing rather than taking the last value")
                seen_deep.add(k)
                got["caps"][k] = v.strip()
    return got


def read_allow_list(path, project, block):
    """Allow-list for any block. Used for the read_execute side of the disjointness
    check; a project with no such block yields [] — nothing to overlap with."""
    return read_block(path, project, block)["allow"]


def read_mutate_execute(path, project):
    got = read_block(path, project, "mutate_execute")
    if not got.get("runner") or not got.get("script_dir") or not got["allow"]:
        raise ValueError(
            f"no mutate_execute(runner, script_dir, allow) for project {project!r}")
    caps = {}
    for k in CAP_KEYS:
        v = got["caps"].get(k)
        if v is None:
            raise ValueError(f"missing cap {k!r} for project {project!r} — caps are fail-closed; "
                             "an unreadable limit must never become an unlimited one")
        if not _CAP_VALUE_RE.fullmatch(v) or int(v) < 1:
            raise ValueError(f"invalid cap {k}={v!r} — must be a positive integer")
        caps[k] = int(v)
    return {"runner": got["runner"], "script_dir": got["script_dir"],
            "allow": got["allow"], "caps": caps}


# Spool quotas live in the SAME caps: block as the mutation caps — tuning them stays a
# config edit, never a code change (spec §8) — but they are read SEPARATELY. They bound
# the BROKER, not the executor: refused requests never consume applies_per_client_day,
# so without these nothing bounds how many requests Hermes can file. Keeping them out
# of CAP_KEYS is what stops apply-changeset.py refusing over a broker-only setting.
SPOOL_QUOTA_KEYS = ("max_pending_requests", "accepted_requests_per_client_day")


def read_spool_quotas(path, project):
    """Per-client spool quotas, fail-closed exactly like the mutation caps.

    An unreadable limit must never become an unlimited one — the same rule the caps
    already follow, and the reason a missing key raises instead of defaulting.
    """
    got = read_block(path, project, "mutate_execute")
    quotas = {}
    for k in SPOOL_QUOTA_KEYS:
        v = got["caps"].get(k)
        if v is None:
            raise ValueError(
                f"missing spool quota {k!r} for project {project!r} — quotas are "
                "fail-closed; an unreadable limit must never become an unlimited one")
        if not _CAP_VALUE_RE.fullmatch(v) or int(v) < 1:
            raise ValueError(f"invalid spool quota {k}={v!r} — must be a positive integer")
        quotas[k] = int(v)
    return quotas


def assert_allow_lists_disjoint(read_allow, mutate_allow):
    """Inc-3's read allow-list states 'readers only; mutators are never allow-listed'.
    This keeps that sentence literally true rather than merely asserted."""
    both = sorted(set(read_allow) & set(mutate_allow))
    if both:
        raise ValueError(f"allow-list overlap between read_execute and mutate_execute: {both} — "
                         "a script must never be both reader and mutator")


def kill_switch_ok(root=None):
    """Return whether mutation is deliberately enabled.

    Reads the HOST-OWNED governance store, which the gateway container does not
    mount — so this can no longer be enabled from inside the container Hermes runs
    in. Safe state is disabled: absent, unreadable, or not a regular file all return
    False. Never raises; callers turn False into refusal.
    """
    try:
        p = governance_lib.kill_switch_path(root)
        if not os.path.isfile(p):
            return False
        with open(p, "rb") as f:
            f.read(1)
        return True
    except Exception:
        return False


def changes_dir(vault):
    return os.path.join(vault, "changes")


def changeset_path(vault, cid):
    return os.path.join(changes_dir(vault), f"{cid}.json")


def approval_path(slug, cid):
    return governance_lib.approval_path(slug, cid)


def snapshot_path(slug, cid):
    return governance_lib.snapshot_path(slug, cid)


def write_snapshot(slug, cid, src_path):
    """Read the reviewed change-set and snapshot it. Convenience wrapper over
    write_snapshot_bytes for callers that hold a path rather than bytes."""
    with open(src_path, "rb") as src:
        return write_snapshot_bytes(slug, cid, src.read())


def write_snapshot_bytes(slug, cid, data):
    """Write the reviewed change-set BYTES verbatim into the governance store and
    return their sha256.

    apply executes from THIS copy. Hashing the writable original would still leave the
    draft -> review -> swap window open; copying it somewhere Hermes cannot write closes
    it (spec section 7).

    Takes BYTES rather than a path so approve can read the vault file exactly once and
    validate, hash and snapshot the same in-memory bytes. Reading it twice left a
    (small) window in which the two reads could differ — and, more importantly, meant
    the digest the operator is shown was not provably taken over the bytes that were
    validated.
    """
    if not isinstance(data, bytes):
        raise ValueError("snapshot payload must be bytes, got %s" % type(data).__name__)
    os.makedirs(governance_lib.approvals_dir(slug), exist_ok=True)
    dst = governance_lib.snapshot_path(slug, cid)
    tmp = dst + ".tmp"
    with open(tmp, "wb") as out:
        out.write(data)
        out.flush()
        os.fsync(out.fileno())
    os.replace(tmp, dst)
    # fsync the directory too — same reasoning as _atomic_write_json and append_log.
    # write_snapshot is a fourth writer of a newly-named file in this tier; a caller
    # that snapshots without immediately approving (a later increment does exactly
    # this) must not be able to lose the rename on crash just because THIS writer was
    # the one quietly weaker than the others.
    dfd = os.open(os.path.dirname(dst) or ".", os.O_RDONLY)
    try:
        os.fsync(dfd)
    finally:
        os.close(dfd)
    return hashlib.sha256(data).hexdigest()


def result_path(vault, cid):
    return os.path.join(changes_dir(vault), f"{cid}.result.json")


def log_path(slug):
    return governance_lib.log_path(slug)


DEFAULT_PROJECTS_REGISTRY = "/opt/registry/projects.yaml"


def registry_projects_path():
    """Container path when mounted, else the in-repo copy — mirrors
    run-ads-report.py:registry_path()."""
    return os.environ.get("ADS_REGISTRY") or (
        DEFAULT_PROJECTS_REGISTRY if os.path.exists(DEFAULT_PROJECTS_REGISTRY)
        else os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "registry", "projects.yaml"))


def file_digest(path):
    """sha256 over the raw file bytes.

    propose writes canonical JSON, so raw-byte hashing remains canonical and
    also invalidates any later byte edit, including whitespace.
    """
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _atomic_write_json(path, obj):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2, sort_keys=True)
        f.write("\n")
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)
    # fsync the directory so the rename itself is durable — same reasoning as
    # append_log and propose. All three writers of a newly-named file in this tier
    # must be consistent about durability; one quietly weaker writer is how an
    # approval survives review but not a crash.
    dfd = os.open(os.path.dirname(path) or ".", os.O_RDONLY)
    try:
        os.fsync(dfd)
    finally:
        os.close(dfd)


def _parse_utc_field(rec, field):
    raw = _require_str(rec.get(field), field)
    try:
        return datetime.datetime.strptime(raw, ISO).replace(tzinfo=datetime.timezone.utc)
    except ValueError as e:
        raise ValueError(f"invalid {field}: {raw!r}") from e


def write_approval(slug, cid, digest, operator, now, ttl_hours):
    """Write a fresh approval record for (slug, cid).

    FIX ROUND 2: shares the exact same hazard reserve_approval/record_outcome were
    fixed for in FIX ROUND 1 — _atomic_write_json writes to a shared, deterministic
    ``<cid>.approval.json.tmp`` path, so two concurrent write_approval calls for the
    same (slug, cid) can race that tmp path and one thread's os.replace can raise
    FileNotFoundError when it finds the file already consumed by the other. This was
    pre-existing and unproven until Task 4's own mutation proof demonstrated the exact
    failure shape against reserve_approval; the same defect class in the function that
    WRITES approvals, in a plan about approval-record integrity, is not something to
    leave for later just because it predates this branch.

    ORDERING NOTE, checked and corrected during FIX ROUND 2's mutation proof: the
    directory _approval_lock's sidecar file lives in must exist before that sidecar
    can be opened, and the first-ever approval for a brand-new client is exactly the
    case where it doesn't yet. This function keeps the explicit os.makedirs call
    first for that reason and for clarity about who is responsible for the
    directory — but it is NOT the only thing making that case safe: _approval_lock
    itself defensively creates the sidecar's parent directory before opening it (see
    its docstring), so moving this makedirs below the `with _approval_lock(...)`
    line does not reproduce the failure the original version of this docstring
    claimed it would. That claim was tested (mutation: move the lock above this
    makedirs) and did NOT go red — TestFreshApprovalsDirectory passed either way,
    because _approval_lock's own defense covers it regardless of caller ordering.
    Recorded here, not smoothed over, per task-4-report.md FIX ROUND 2: the ordering
    kept below is good practice and matches which function is nominally responsible
    for the directory, not a load-bearing requirement.
    """
    cid = _require_str(cid, "changeset_id")
    digest = _require_str(digest, "sha256")
    operator = _require_str(operator, "operator")
    if not CHANGESET_ID_RE.fullmatch(cid):
        raise ValueError(f"invalid changeset_id: {cid!r}")
    if not SHA256_RE.fullmatch(digest):
        raise ValueError(f"invalid sha256: {digest!r}")
    if not OPERATOR_RE.fullmatch(operator):
        raise ValueError(f"invalid operator: {operator!r} (allowed ^[A-Za-z0-9._@-]{{1,64}}$)")
    if not isinstance(now, datetime.datetime):
        raise ValueError(f"now must be datetime, got {type(now).__name__}")
    if not isinstance(ttl_hours, int) or ttl_hours < 1:
        raise ValueError("ttl_hours must be a positive integer")
    rec = {"changeset_id": cid, "sha256": digest, "operator": operator,
           "approved_at": now.strftime(ISO),
           "expires_at": (now + datetime.timedelta(hours=ttl_hours)).strftime(ISO)}
    # Kept above the lock for clarity about who is nominally responsible for this
    # directory, NOT because the ordering is load-bearing: _approval_lock creates the
    # parent itself, and the mutation that moves this below the lock does not go red.
    # This comment used to read "MUST precede the lock — see docstring", contradicting
    # the docstring above, which had already been corrected to say the opposite. An
    # inline comment that disagrees with the docstring it cites is worse than neither.
    os.makedirs(governance_lib.approvals_dir(slug), exist_ok=True)
    with _approval_lock(slug, cid):
        _atomic_write_json(approval_path(slug, cid), rec)
    return rec


def verify_approval(slug, cid, digest, now):
    cid = _require_str(cid, "changeset_id")
    digest = _require_str(digest, "sha256")
    p = approval_path(slug, cid)
    if not os.path.isfile(p):
        raise ValueError(f"no approval record for change-set {cid!r} — run approve-changeset.py first")
    try:                       # unreadable / directory-in-place must REFUSE, not leak an OSError
        with open(p, encoding="utf-8") as f:
            rec = json.load(f)
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as e:
        raise ValueError(f"unreadable approval record for {cid!r}: {e}")
    if not isinstance(rec, dict):
        raise ValueError(f"malformed approval record for {cid!r}: expected a JSON object")
    if "reserved_at" in rec:
        # Presence, not truthiness: "", null, or 0 must refuse exactly like a real
        # timestamp does. Every other field here goes through _require_str — reserved_at
        # is no exception, so a type-confused value refuses loudly instead of reading as
        # unreserved.
        reserved_at = _require_str(rec.get("reserved_at"), "reserved_at")
        raise ValueError(
            "approval for %r is already reserved (reserved_at=%s) — approvals are "
            "single-use; approve again to authorise another apply" % (cid, reserved_at))
    if _require_str(rec.get("changeset_id"), "changeset_id") != cid:
        raise ValueError(f"approval record changeset_id does not match {cid!r}")
    approved_digest = _require_str(rec.get("sha256"), "sha256")
    if approved_digest != digest:
        raise ValueError(f"approval hash mismatch for {cid!r} — the change-set was "
                         "modified after approval; re-approve the reviewed bytes")
    operator = _require_str(rec.get("operator"), "operator")
    if not OPERATOR_RE.fullmatch(operator):
        raise ValueError(f"invalid operator in approval record: {operator!r}")
    _parse_utc_field(rec, "approved_at")
    expires = _parse_utc_field(rec, "expires_at")
    if not isinstance(now, datetime.datetime):
        raise ValueError(f"now must be datetime, got {type(now).__name__}")
    if now > expires:
        raise ValueError(f"approval for {cid!r} expired at {rec['expires_at']} — re-approve")
    return rec


def append_log(slug, rec):
    """Append one audit-log record and fsync before returning."""
    p = log_path(slug)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, sort_keys=True) + "\n")
        f.flush()
        os.fsync(f.fileno())
    # fsync the DIRECTORY too: on the first append the log file is newly created, and
    # fsyncing its contents does not persist the directory entry that names it. Losing
    # that entry loses the whole reversibility record, which day_counts would then read
    # as a legitimate zero.
    dfd = os.open(os.path.dirname(p), os.O_RDONLY)
    try:
        os.fsync(dfd)
    finally:
        os.close(dfd)


# --- replay protection -------------------------------------------------------------
# The seen-set lives in the GOVERNANCE STORE (governance_lib.seen_path), never in the
# spool. That is the whole point of putting it here rather than beside the request the
# gateway already writes: the spool is the one tree Hermes can write to, and a replay
# record Hermes can delete is not replay protection at all (spec §8).
#
# CORRECTED (S3-a). This comment used to say the executor container mounts seen/
# read-write "alongside log/", and that both are append targets it "cannot repudiate".
# Neither half held. seen/ is now not mounted into the executor at all — nothing under
# its entrypoint ever read or wrote the seen-set; append_log is its only governance
# write. And "cannot repudiate" was never true of either file: write access to a
# DIRECTORY is what grants unlink, so an executor that could write log/ could always
# delete log/<slug>.jsonl outright. It still can — see iter_log_records' docstring for
# what that costs and why closing it is a two-part change parked for its own wave.

def append_seen(slug, request_id, now):
    """Record an accepted request_id, fsynced before returning.

    This is written BEFORE the broker acts on the request (mirrors reserve_approval
    below, and for the identical reason). If the process dies between this append and
    whatever it authorises, the request_id is already burned and a resubmission is
    refused as a replay — which costs the caller a fresh request_id, whereas the
    opposite ordering (append after acting) would let a crashed-and-retried request
    through twice.
    """
    request_id = _require_str(request_id, "request_id")
    p = governance_lib.seen_path(slug)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    rec = {"request_id": request_id, "seen_at": now.strftime(ISO)}
    with open(p, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, sort_keys=True) + "\n")
        f.flush()
        os.fsync(f.fileno())
    # fsync the DIRECTORY too — same reasoning as append_log: on the first append the
    # file is newly created, and fsyncing its contents does not persist the directory
    # entry that names it. Losing that entry loses the whole replay history, which
    # seen_contains below would then read back as a legitimate "never seen".
    dfd = os.open(os.path.dirname(p), os.O_RDONLY)
    try:
        os.fsync(dfd)
    finally:
        os.close(dfd)


def iter_seen_records(slug):
    """Yield each validated {request_id, seen_at} record from the seen-set, in file
    order. THE single reader of seen/<slug>.jsonl.

    Added in Task 5 FIX ROUND 2: seen_contains (below) and hermes-broker.py's
    _accepted_today both need to read this same file, and having each parse it with
    its own rules is exactly how one of them quietly drifts fail-open — which is what
    happened. _accepted_today's original implementation counted lines by a raw
    substring match and caught only OSError, so a seen-set with a mangled or missing
    "seen_at" field silently undercounted instead of raising, while seen_contains's
    JSON parse on the SAME file correctly refused. Two readers, two failure
    semantics, on the axis that bounds how much work a client can cause. Both callers
    now share this one generator instead.

    FAIL-CLOSED on every read error: an unreadable file, a directory sitting where the
    file should be, or a line that is not a JSON object carrying a string
    "request_id" AND a string "seen_at" all RAISE ValueError rather than being
    skipped or silently treated as absent. Returning nothing there would silently admit
    every replay for this client and silently undercount every daily quota — the exact
    same failure shape as an unreadable cap being read as "no usage yet" instead of
    refused (see read_spool_quotas).

    A MISSING FILE IS NOT A READ ERROR AND IS NOT COVERED BY THAT RULE. The `return`
    below is the fail-OPEN case the paragraph above condemns, and this docstring used
    to claim otherwise — it described the corrupt-file path and silently overclaimed
    the missing-file one. Stated plainly rather than left to be discovered: a seen-set
    that has been DELETED reads here as "nothing has ever been recorded", which admits
    every previously-seen request_id as fresh.

    What makes that acceptable TODAY is a property of the deployment, not of this
    function: every caller of the seen-set is host-side in hermes-broker.py, and the
    executor no longer has seen/ mounted at all (S3-a), so the governed party cannot
    reach the file to delete it. That is an argument about who can write the store, and
    it evaporates the moment anything mounts seen/ into a container again. If you are
    about to do that, this `return` is the thing to fix first.
    """
    p = governance_lib.seen_path(slug)
    if not os.path.exists(p):
        return                              # NOT fail-closed — see the docstring above
    try:
        with open(p, encoding="utf-8") as f:
            for lineno, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue
                rec = json.loads(line)
                if (not isinstance(rec, dict)
                        or not isinstance(rec.get("request_id"), str)
                        or not isinstance(rec.get("seen_at"), str)):
                    raise ValueError(f"seen-set {p} line {lineno} is malformed")
                yield rec
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as e:
        raise ValueError(
            f"unreadable seen-set for {slug!r} ({e}) — refusing rather than treating "
            "every request_id as unseen") from e


def seen_contains(slug, request_id):
    """True when this request_id has already been accepted for this client.

    FAIL-CLOSED on every read error — see iter_seen_records, the shared parser this
    now delegates to.
    """
    request_id = _require_str(request_id, "request_id")
    for rec in iter_seen_records(slug):
        if rec["request_id"] == request_id:
            return True
    return False


# --- approval reservation ----------------------------------------------------------
# write_approval/verify_approval (above) predate this task and already enforce the
# single-use rule on the READ side: verify_approval refuses whenever "reserved_at" is
# present on the record, regardless of whether "outcome" was ever written. What was
# missing is the WRITE side — something that sets reserved_at, and does so before the
# executor runs rather than after, per spec §7.

def _load_approval(slug, cid):
    """Shared read for reserve_approval and record_outcome: both need the current
    record before deciding whether to refuse, and both must refuse identically on a
    missing, unreadable, or non-object record rather than each growing its own
    slightly-different check."""
    p = approval_path(slug, cid)
    if not os.path.isfile(p):
        raise ValueError(f"no approval record for change-set {cid!r} — run approve-changeset.py first")
    try:
        with open(p, encoding="utf-8") as f:
            rec = json.load(f)
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as e:
        raise ValueError(f"unreadable approval record for {cid!r}: {e}") from e
    if not isinstance(rec, dict):
        raise ValueError(f"malformed approval record for {cid!r}: expected a JSON object")
    return p, rec


@contextlib.contextmanager
def _approval_lock(slug, cid):
    """Exclusive mutual-exclusion for the read-check-write in reserve_approval and
    record_outcome, added in FIX ROUND 1 after review found the original
    read-modify-write TOCTOU against itself.

    Single-use approval is the property Task 4 exists to deliver, and this project's
    canon says a guardrail secures a path rather than a capability: relying on a
    caller (the broker, Task 5) to remember to take a lock elsewhere would make
    single-use a POLICY someone else has to uphold, not a STRUCTURAL guarantee this
    module makes true by construction. So this function defends itself instead.

    Locks a SIDECAR file (governance_lib.approval_lock_path), never the approval
    record itself. _atomic_write_json writes a .tmp file and os.replace()s it over
    the destination; a lock held on the approval file's own fd would be a lock on the
    OLD inode, and the file that lands after the rename carries no lock at all — the
    mutual exclusion would be silently fictional. The sidecar's path never changes
    across rewrites, so flock-ing it is real serialization.

    This is a DIFFERENT file from the broker's future per-client lock at
    control/.locks/<slug>.lock (Task 5) — do NOT "simplify" the two into one lock.
    They protect different scopes (one approval record here; the whole
    request/reserve/execute/record sequence there) and, because they never name the
    same file, nested acquisition (broker lock held, then this one taken inside it)
    can never deadlock against itself.
    """
    p = governance_lib.approval_lock_path(slug, cid)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    fd = os.open(p, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)


def reserve_approval(slug, cid, request_id, now):
    """Mark an approval consumed BEFORE the executor is invoked. Returns the record.

    THE ORDERING IS LOAD-BEARING (spec §7). If reservation happened AFTER a successful
    apply instead, there is a window — between the mutation landing at Google Ads and
    this record being written — in which the approval is still live and a crash or a
    replayed request in that window applies the same change-set a second time.
    Reserving first closes that window the other direction: a crash between reserving
    and applying costs one unusable approval, which a human clears by approving again.
    That is a strictly cheaper failure than a duplicate account mutation.

    Concurrency: the entire read-check-write runs inside _approval_lock, an exclusive
    flock on a sidecar file scoped to this (slug, cid). That makes single-use
    self-enforcing — a second concurrent caller blocks until the first's lock is
    released, then reads the now-reserved record and correctly refuses, regardless of
    scheduling. (An earlier version of this function relied entirely on the broker's
    future per-client advisory lock for this property; that was reviewed and rejected
    as policy rather than structure — see task-4-report.md FIX ROUND 1.)
    """
    with _approval_lock(slug, cid):
        p, rec = _load_approval(slug, cid)
        if "reserved_at" in rec:
            raise ValueError(
                "approval for %r is already reserved (reserved_at=%s) — approvals are "
                "single-use" % (cid, rec.get("reserved_at")))
        rec["reserved_at"] = now.strftime(ISO)
        rec["request_id"] = _require_str(request_id, "request_id")
        _atomic_write_json(p, rec)
        return rec


def record_outcome(slug, cid, outcome, now):
    """Phase two of the two-phase record: what actually happened. Returns the record.

    Requires a prior reservation — an outcome recorded without one means the ordering
    was inverted somewhere upstream (execution happened, or is about to, without the
    approval ever having been marked consumed), and that is exactly the defect this
    refuses to paper over rather than recording anyway.

    An approval that has reserved_at but never gets an outcome (the crash-mid-apply
    case) stays exactly as dead as one that completed: verify_approval refuses on
    reserved_at alone, never on outcome. So the crash costs an unusable approval, never
    a reusable one — the property spec §7 asks for.

    Concurrency: runs inside the same _approval_lock as reserve_approval, scoped to
    this (slug, cid), for the identical reason — the read-then-write here must not
    race a concurrent reserve_approval or record_outcome on the same approval.
    """
    with _approval_lock(slug, cid):
        p, rec = _load_approval(slug, cid)
        if "reserved_at" not in rec:
            raise ValueError(
                f"approval {cid!r} has no reserved_at — refusing to record an outcome for "
                "an apply that was never reserved; the reservation must precede execution")
        rec["outcome"] = _require_str(outcome, "outcome")
        rec["finished_at"] = now.strftime(ISO)
        _atomic_write_json(p, rec)
        return rec


def iter_log_records(slug):
    """Yield (lineno, record) for every audit-log line, validating the fields all
    readers depend on.

    THE audit log has exactly ONE parser. It feeds two consumers with different
    filters — day_counts (daily caps) and apply-changeset's _undo_targets (the undo
    path) — and two readers with two standards of rigour is precisely how a
    log-borne defect reaches only one of them. (It did: the undo reader originally
    used bare .get() throughout and had no OSError guard, so an unreadable log or a
    record missing a field surfaced as an uncaught exception and exit 1 rather than
    a refusal.)

    Every failure mode BELOW THIS LINE is a refusal, never a skip: an unreadable
    counter must not read as 'under the cap', and an unreadable undo list must not
    read as 'nothing to undo'.

    A MISSING LOG IS THE ONE EXCEPTION, AND IT IS NOT COVERED (S3-b, ruling R22).
    This docstring used to state the rule without that carve-out, and the code
    immediately below it returns nothing when the file is absent — so a missing
    counter reads as exactly the 'under the cap' this text forbids, and a missing
    undo list as exactly the 'nothing to undo'. The text named the precise failure
    the code implements. Measured, not reasoned: deleting log/<slug>.jsonl takes
    day_counts from exhausted back to zero, and destroys the reversibility record
    --undo reads through this same generator.

    It is not merely theoretical for the GOVERNED party either. log/ must stay
    executor-writable — append_log is fsync'd per action — and on Docker Desktop for
    macOS the bind mount remaps ownership so uid 10000 can unlink there. The same
    modes on a Linux VPS would deny uid 10000 even traverse, so the exploit's REACH
    is platform-conditional and the VPS behaviour is UNMEASURED; do not read a darwin
    measurement as covering it either way.

    Why this is still a `return` and not a raise: closing it means an
    append-but-not-unlink layout (host-owned log/ the executor cannot create or
    unlink in, holding a pre-created per-client file it can append to) plus making a
    missing log for a REGISTERED client fail closed. Both halves are needed together,
    and both were measured as out of scope for one fix wave:

      * preflight-governance-access.py demands read+WRITE+traverse on log/, so the
        very layout the fix creates is refused by the pre-flight (measured: 1 problem,
        exit 2) — the mutation rail blocked at startup, which is R19's over-checking
        failure again and worse than the finding.
      * raising here breaks the FIRST apply for any client, not just fixtures:
        day_counts reads this log before any log exists (measured: 30 suite tests,
        including the plain happy path, go red). It is only safe once every registered
        client is guaranteed a pre-created log — and there is no programmatic
        client-registration hook to guarantee it: clients.json is hand-edited, and
        migrate-governance.py only carries logs that ALREADY exist in a vault.

    Until both land together, treat a missing log as UNVERIFIED rather than as zero.
    """
    p = log_path(slug)
    if not os.path.exists(p):
        return                              # NOT fail-closed — see the docstring above
    try:
        f = open(p, encoding="utf-8")
    except OSError as e:
        raise ValueError(f"unreadable audit log at {p} ({e}) — fail-closed") from e
    with f:
        for n, line in enumerate(f, 1):
            if not line.strip():
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError as e:
                raise ValueError(f"corrupt audit log at {p}:{n} ({e}) — fail-closed") from e
            if not isinstance(rec, dict):
                raise ValueError(f"corrupt audit log at {p}:{n} (record must be an object) — fail-closed")
            _require_str(rec.get("status"), "status")
            _require_str(rec.get("ts"), "ts")
            _require_str(rec.get("changeset_id"), "changeset_id")
            yield n, rec


def day_counts(slug, day):
    """Count applied actions and distinct applied change-sets for a UTC day.

    Corrupt log lines refuse rather than being skipped because the log feeds
    daily caps; silent undercount would read as under-cap.
    """
    if not DAY_RE.fullmatch(_require_str(day, "day")):
        raise ValueError(f"invalid day: {day!r}")
    applies, actions = set(), 0
    for _n, rec in iter_log_records(slug):
        if rec["status"] == "applied" and rec["ts"].startswith(day):
            applies.add(rec["changeset_id"])
            actions += 1
    return {"applies": len(applies), "actions": actions}
