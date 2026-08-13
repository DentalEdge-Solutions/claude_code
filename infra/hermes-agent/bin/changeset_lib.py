#!/usr/bin/env python3
"""Typed change-set validation, canonical serialization, and hashing for the
Hermes mutation tier. Stdlib-only. Holds NO credential and performs no network
I/O — this library is used by propose/approve (uncredentialed) and by apply.

The mutation tier removes the read-only-credential backstop, so validation here
is fail-closed on every field: unknown action types, unknown fields, non-digit
ids, and control characters are all refusals, never coercions.
See docs/superpowers/specs/2026-08-12-hermes-mutation-tier-design.md
"""
import datetime, json, os, re, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import vault_lib

ACTION_TYPES = ("add_campaign_negative",)
MATCH_TYPES = ("EXACT", "PHRASE", "BROAD")
ISO = "%Y-%m-%dT%H:%M:%SZ"
KEYWORD_MAX = 80                      # Google Ads keyword text limit

ID_RE = re.compile(r"^[0-9]{1,15}$")
CHANGESET_ID_RE = re.compile(r"^[0-9]{8}-[0-9]{6}-[0-9a-f]{8}$")
PROJECT_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")

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
    """
    inside = False
    sub = None
    got = {"allow": [], "caps": {}}
    for indent, stripped in _iter_project_lines(path, project):
        if indent == 4 and stripped == f"{block}:":
            inside = True; sub = None
        elif indent <= 4:                                        # sibling/shallower closes scope
            inside = False; sub = None
        elif indent == 6 and inside:
            if stripped in ("allow:", "caps:"):
                sub = stripped[:-1]
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
