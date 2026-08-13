#!/usr/bin/env python3
"""Typed change-set validation, canonical serialization, and hashing for the
Hermes mutation tier. Stdlib-only. Holds NO credential and performs no network
I/O — this library is used by propose/approve (uncredentialed) and by apply.

The mutation tier removes the read-only-credential backstop, so validation here
is fail-closed on every field: unknown action types, unknown fields, non-digit
ids, and control characters are all refusals, never coercions.
See docs/superpowers/specs/2026-08-12-hermes-mutation-tier-design.md
"""
import datetime, hashlib, json, os, re, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
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
    for indent, stripped in _iter_project_lines(path, project):
        if indent == 4 and stripped.startswith("workdir:"):
            return stripped.split(":", 1)[1].strip()
    raise ValueError(f"no workdir for project {project!r}")


def read_block(path, project, block):
    """Parse projects.<project>.<block> into scalars plus `allow` and `caps`.

    Scope discipline (from run-ads-report.py's Inc-2 review fix): ANY sibling or
    shallower line closes the block, so a later key cannot bleed into `allow`.
    Returns empty structures when the block is absent — callers decide whether that
    is a refusal (read_mutate_execute) or simply nothing to check (read_allow_list).

    DUPLICATE KEYS REFUSE. A repeated `allow:` header would otherwise ACCUMULATE,
    silently admitting a second mutator; a repeated scalar would silently take the
    last value, quietly swapping the interpreter. In a file that decides what may
    mutate a live account, a duplicate key is a mistake — a merge artifact or a bad
    hand-edit — not an intent, so it is loud rather than resolved.
    """
    inside = False
    sub = None
    seen = set()
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
            if stripped in ("allow:", "caps:"):
                sub = key
            else:
                sub = None
                k, _, v = stripped.partition(":")
                got[k.strip()] = v.strip()
        elif indent == 8 and inside:
            if sub == "allow" and stripped.startswith("- "):
                got["allow"].append(stripped[2:].strip())
            elif sub == "caps":
                k, _, v = stripped.partition(":")
                got["caps"][k.strip()] = v.strip()
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


def assert_allow_lists_disjoint(read_allow, mutate_allow):
    """Inc-3's read allow-list states 'readers only; mutators are never allow-listed'.
    This keeps that sentence literally true rather than merely asserted."""
    both = sorted(set(read_allow) & set(mutate_allow))
    if both:
        raise ValueError(f"allow-list overlap between read_execute and mutate_execute: {both} — "
                         "a script must never be both reader and mutator")


GOVERNANCE_DIR = "_governance"
KILL_SWITCH = "mutation-enabled"


def kill_switch_ok(vault_root=None):
    """Return whether mutation is deliberately enabled.

    Safe state is disabled: absent, unreadable, or not a regular file all return
    False. This function never raises because callers turn False into refusal.
    """
    try:
        root = vault_root or vault_lib.vault_root()
        p = os.path.join(root, GOVERNANCE_DIR, KILL_SWITCH)
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


def approval_path(vault, cid):
    return os.path.join(changes_dir(vault), f"{cid}.approval.json")


def result_path(vault, cid):
    return os.path.join(changes_dir(vault), f"{cid}.result.json")


def log_path(vault):
    return os.path.join(changes_dir(vault), "log.jsonl")


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


def _parse_utc_field(rec, field):
    raw = _require_str(rec.get(field), field)
    try:
        return datetime.datetime.strptime(raw, ISO).replace(tzinfo=datetime.timezone.utc)
    except ValueError as e:
        raise ValueError(f"invalid {field}: {raw!r}") from e


def write_approval(vault, cid, digest, operator, now, ttl_hours):
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
    os.makedirs(changes_dir(vault), exist_ok=True)
    _atomic_write_json(approval_path(vault, cid), rec)
    return rec


def verify_approval(vault, cid, digest, now):
    cid = _require_str(cid, "changeset_id")
    digest = _require_str(digest, "sha256")
    p = approval_path(vault, cid)
    if not os.path.isfile(p):
        raise ValueError(f"no approval record for change-set {cid!r} — run approve-changeset.py first")
    try:                       # unreadable / directory-in-place must REFUSE, not leak an OSError
        with open(p, encoding="utf-8") as f:
            rec = json.load(f)
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as e:
        raise ValueError(f"unreadable approval record for {cid!r}: {e}")
    if not isinstance(rec, dict):
        raise ValueError(f"malformed approval record for {cid!r}: expected a JSON object")
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


def append_log(vault, rec):
    """Append one audit-log record and fsync before returning."""
    d = changes_dir(vault)
    os.makedirs(d, exist_ok=True)
    with open(log_path(vault), "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, sort_keys=True) + "\n")
        f.flush()
        os.fsync(f.fileno())
    # fsync the DIRECTORY too: on the first append the log file is newly created, and
    # fsyncing its contents does not persist the directory entry that names it. Losing
    # that entry loses the whole reversibility record, which day_counts would then read
    # as a legitimate zero.
    dfd = os.open(d, os.O_RDONLY)
    try:
        os.fsync(dfd)
    finally:
        os.close(dfd)


def day_counts(vault, day):
    """Count applied actions and distinct applied change-sets for a UTC day.

    Corrupt log lines refuse rather than being skipped because the log feeds
    daily caps; silent undercount would read as under-cap.
    """
    if not DAY_RE.fullmatch(_require_str(day, "day")):
        raise ValueError(f"invalid day: {day!r}")
    p = log_path(vault)
    if not os.path.exists(p):
        return {"applies": 0, "actions": 0}
    applies, actions = set(), 0
    try:
        f = open(p, encoding="utf-8")
    except OSError as e:
        raise ValueError(f"unreadable audit log at {p} ({e}) — caps are fail-closed") from e
    with f:
        for n, line in enumerate(f, 1):
            if not line.strip():
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError as e:
                raise ValueError(f"corrupt audit log at {p}:{n} ({e}) — caps are fail-closed") from e
            if not isinstance(rec, dict):
                raise ValueError(f"corrupt audit log at {p}:{n} (record must be object) — caps are fail-closed")
            status = _require_str(rec.get("status"), "status")
            ts = _require_str(rec.get("ts"), "ts")
            if status == "applied" and ts.startswith(day):
                applies.add(_require_str(rec.get("changeset_id"), "changeset_id"))
                actions += 1
    return {"applies": len(applies), "actions": actions}
