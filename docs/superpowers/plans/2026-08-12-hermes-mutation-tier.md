# Hermes Mutation Tier Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a registered project apply an operator-approved, typed, capped, reversible change to a client's external Google Ads account — one action type (campaign-level negative keyword) — proven live on a paused account that ends byte-identical.

**Architecture:** A `mutate-execute` tier parallel to Inc-3's `read-execute`, split across three commands with sharply different privilege: `propose` and `approve` hold no credential and cannot reach Google; `apply` is the only credentialed entry point, running every guard and a `validate_only` dry-run before any live mutate. A shared stdlib-only library (`changeset_lib.py`) owns schema validation, canonical hashing, approval records, caps, and the audit log. The typed mutator itself lives in the `claude-google-ads` repo (the project performs its own function); Hermes owns the entire safety rail.

**Tech Stack:** Python 3 stdlib only for everything in `infra/hermes-agent/bin/` (no third-party imports, matching `vault_lib.py` / `vault-write.py` / `run-ads-report.py`). The mutator in `claude-google-ads/code/` uses the `google-ads` SDK under the pinned `/opt/ads-venv`. POSIX `sh` for host wrappers. `unittest` for tests, run directly (not auto-discovered by `run-all-tests.js`).

**Spec:** `docs/superpowers/specs/2026-08-12-hermes-mutation-tier-design.md`

**Branch:** `feat/hermes-mutation-tier` (already created; spec committed in 3 commits)

## Global Constraints

Every task's requirements implicitly include all of these. Copied from spec §10.

- **`:ro` project mounts** — nothing may write under `/projects/<name>`. All writes go to `/opt/data`.
- **Credentials in gitignored `.env.<x>`**, injected per-invocation via `docker compose exec -e`. Never the gateway env. Never `source`d — parsed as data.
- **Charset-validate every argument** that reaches a path or a subprocess. Use `re.fullmatch`, never `re.match` with `$` (a trailing newline bypasses it — the two-tier Task-1 carry-forward correction).
- **No client names, account IDs, campaign IDs, metrics, or drafts** in git, the brain, specs, plans, tests, or telemetry. Every test fixture uses synthetic placeholders (`acme-dental`, `1234567890`), matching `vault_lib.test.py`.
- **Stdlib only** in `infra/hermes-agent/bin/`.
- **Fail closed.** Missing, malformed, or unreadable configuration is a refusal, never a default.
- **Human gate** on anything reaching a client system.
- **Inc-3's read path is unchanged.** Do not edit `run-ads-report.py`, `run-ads-report.sh`, or the `read_execute` registry block. Its read-only credential must keep working exactly as it does today.

## File Structure

**Create in `infra/hermes-agent/`:**

| File | Responsibility |
|---|---|
| `bin/changeset_lib.py` | Schema validation, canonical serialization + hashing, registry `mutate_execute` parsing, caps, approval records, kill switch, audit-log append + accounting. No credential, no network. |
| `bin/changeset_lib.test.py` | Unit tests for the above. |
| `bin/propose-changeset.py` | Builds a full change-set from an operator-supplied actions file; writes it to the vault. |
| `bin/propose-changeset.test.py` | Unit tests. |
| `bin/approve-changeset.py` | Writes the hash-bound approval record. |
| `bin/approve-changeset.test.py` | Unit tests. |
| `bin/apply-changeset.py` | The credentialed applier and the undo path. |
| `bin/apply-changeset.test.py` | Unit tests, including "mutator never spawned" assertions. |
| `run-ads-mutate.sh` | Host wrapper: parse `.env.gaw`, inject via `docker compose exec -e`. |
| `.env.gaw.example` | Template for the Standard-access write credential. |

**Modify in `infra/hermes-agent/`:** `registry/projects.yaml` (add `mutate_execute` block), `README.md` (add a section), and the repo-root `.gitignore`.

**Create in `claude-google-ads/` (separate repo):** `code/mutate_campaign_negative.py` and `code/mutate_campaign_negative.test.py`.

## Naming note (plan-level refinement of spec §5)

The spec sketches vault filenames as `<ts>-<changeset-id>.json`. Since `changeset_id` is generated as `<YYYYMMDD>-<HHMMSS>-<8 hex>` it already carries the timestamp, so files are named `<changeset_id>.json`, `<changeset_id>.approval.json`, `<changeset_id>.result.json` — no doubled timestamp. This matches the spec's `"changeset_id": "<ts>-<rand>"` schema line.

## Two decisions worth understanding before you start

**The operator's input file contains only `actions`.** `propose` fills in `client`, `project`, `customer_id`, `changeset_id`, and `created_at` from the resolver. An operator therefore cannot typo a customer ID into a change-set, and the apply-time check that `changeset.customer_id` matches the resolved one becomes a genuine tamper check rather than a typo check.

**The approval hashes raw file bytes, and `propose` writes canonical JSON.** Canonical on disk, byte-exact on approval — any later edit, including whitespace, invalidates the approval.

---

### Task 1: Change-set schema and canonical hashing

**Files:**
- Create: `infra/hermes-agent/bin/changeset_lib.py`
- Test: `infra/hermes-agent/bin/changeset_lib.test.py`

**Interfaces:**
- Consumes: `vault_lib.validate_slug`, `vault_lib.validate_customer_id` (existing, in the same directory).
- Produces: `ACTION_TYPES`, `MATCH_TYPES`, `ISO`, `KEYWORD_MAX`, `validate_keyword(kw) -> str`, `validate_action(a) -> dict`, `validate_changeset(cs, max_actions) -> dict`, `canonical_bytes(cs) -> bytes`. All validators raise `ValueError` on rejection.

- [ ] **Step 1: Write the failing test**

Create `infra/hermes-agent/bin/changeset_lib.test.py`:

```python
import json, os, sys, unittest
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import changeset_lib as C

def _action(**kw):
    a = {"type": "add_campaign_negative", "campaign_id": "22233344455",
         "keyword": "free consultation", "match_type": "PHRASE"}
    a.update(kw)
    return a

def _cs(**kw):
    cs = {"changeset_id": "20260812-101500-abcd1234", "client": "acme-dental",
          "project": "claude_google_ads", "customer_id": "1234567890",
          "created_at": "2026-08-12T10:15:00Z", "actions": [_action()]}
    cs.update(kw)
    return cs

class TestAction(unittest.TestCase):
    def test_valid_action_accepted(self):
        self.assertEqual(C.validate_action(_action())["match_type"], "PHRASE")

    def test_unknown_type_rejected(self):
        with self.assertRaises(ValueError):
            C.validate_action(_action(type="set_campaign_budget"))

    def test_bad_match_type_rejected(self):
        with self.assertRaises(ValueError):
            C.validate_action(_action(match_type="EXACTLY"))

    def test_non_digit_campaign_id_rejected(self):
        for bad in ["222-333", "abc", "", "22 33", "1" * 16]:
            with self.assertRaises(ValueError):
                C.validate_action(_action(campaign_id=bad))

    def test_trailing_newline_campaign_id_rejected(self):
        with self.assertRaises(ValueError):
            C.validate_action(_action(campaign_id="22233344455\n"))

    def test_oversize_keyword_rejected(self):
        with self.assertRaises(ValueError):
            C.validate_action(_action(keyword="x" * (C.KEYWORD_MAX + 1)))

    def test_control_characters_in_keyword_rejected(self):
        for bad in ["free\nconsult", "free\tconsult", "free\x00consult", "free\x7fconsult"]:
            with self.assertRaises(ValueError):
                C.validate_action(_action(keyword=bad))

    def test_empty_keyword_rejected(self):
        with self.assertRaises(ValueError):
            C.validate_action(_action(keyword="   "))

    def test_unknown_action_field_rejected(self):
        with self.assertRaises(ValueError):
            C.validate_action(_action(bid_micros=1000))

    def test_numeric_campaign_id_refused(self):
        """A JSON number must not pass a digits-only check via str() coercion — it
        would serialize unquoted and break the schema the approval hash covers."""
        with self.assertRaises(ValueError):
            C.validate_action(_action(campaign_id=22233344455))

    def test_non_string_keyword_refused(self):
        for bad in [12345, None, ["free"], {"t": "free"}]:
            with self.assertRaises(ValueError):
                C.validate_action(_action(keyword=bad))

class TestChangeset(unittest.TestCase):
    def test_valid_changeset_accepted(self):
        self.assertEqual(len(C.validate_changeset(_cs(), 25)["actions"]), 1)

    def test_over_cap_rejected(self):
        with self.assertRaises(ValueError):
            C.validate_changeset(_cs(actions=[_action()] * 4), 3)

    def test_at_cap_accepted(self):
        self.assertEqual(len(C.validate_changeset(_cs(actions=[_action()] * 3), 3)["actions"]), 3)

    def test_empty_actions_rejected(self):
        with self.assertRaises(ValueError):
            C.validate_changeset(_cs(actions=[]), 25)

    def test_bad_slug_rejected(self):
        with self.assertRaises(ValueError):
            C.validate_changeset(_cs(client="../etc"), 25)

    def test_bad_customer_id_rejected(self):
        with self.assertRaises(ValueError):
            C.validate_changeset(_cs(customer_id="123-456"), 25)

    def test_bad_changeset_id_rejected(self):
        for bad in ["", "nope", "20260812-101500-ABCD1234", "20260812-101500-abcd123"]:
            with self.assertRaises(ValueError):
                C.validate_changeset(_cs(changeset_id=bad), 25)

    def test_bad_created_at_rejected(self):
        with self.assertRaises(ValueError):
            C.validate_changeset(_cs(created_at="2026/08/12 10:15"), 25)

    def test_unknown_top_level_field_rejected(self):
        with self.assertRaises(ValueError):
            C.validate_changeset(_cs(approved=True), 25)

    def test_non_string_identity_fields_refused(self):
        """Type is validated, not coerced — every identity field must be a JSON string."""
        for field, bad in [("changeset_id", 20260812), ("client", 123),
                           ("project", 7), ("customer_id", 1234567890),
                           ("created_at", 20260812101500)]:
            with self.assertRaises(ValueError):
                C.validate_changeset(_cs(**{field: bad}), 25)

    def test_null_identity_fields_refused(self):
        for field in ("changeset_id", "client", "project", "customer_id", "created_at"):
            with self.assertRaises(ValueError):
                C.validate_changeset(_cs(**{field: None}), 25)

class TestCanonical(unittest.TestCase):
    def test_canonical_is_key_order_independent(self):
        a = {"b": 1, "a": 2}
        b = {"a": 2, "b": 1}
        self.assertEqual(C.canonical_bytes(a), C.canonical_bytes(b))

    def test_canonical_uses_compact_separators(self):
        """Exact bytes prove compact separators WITHOUT forbidding spaces inside string
        values — a keyword is free text and legitimately contains them."""
        self.assertEqual(C.canonical_bytes({"b": 1, "a": "x y"}), b'{"a":"x y","b":1}')

    def test_canonical_roundtrips(self):
        self.assertEqual(json.loads(C.canonical_bytes(_cs()).decode()), _cs())

    def test_canonical_differs_on_any_value_change(self):
        self.assertNotEqual(C.canonical_bytes(_cs()),
                            C.canonical_bytes(_cs(actions=[_action(keyword="free consult")])))

if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
python3 infra/hermes-agent/bin/changeset_lib.test.py
```

Expected: `ModuleNotFoundError: No module named 'changeset_lib'`.

- [ ] **Step 3: Write the implementation**

Create `infra/hermes-agent/bin/changeset_lib.py`:

```python
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
    vault_lib.validate_slug(cs.get("client"))          # vault_lib already isinstance-checks
    if not PROJECT_RE.fullmatch(_require_str(cs.get("project"), "project")):
        raise ValueError(f"invalid project: {cs.get('project')!r}")
    vault_lib.validate_customer_id(cs.get("customer_id"))            # ditto
    datetime.datetime.strptime(_require_str(cs.get("created_at"), "created_at"), ISO)
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
```

- [ ] **Step 4: Run the test to verify it passes**

```bash
python3 infra/hermes-agent/bin/changeset_lib.test.py
```

Expected: `OK`, no warnings (pristine test output — use context managers for all file I/O).

- [ ] **Step 5: Commit**

```bash
git add infra/hermes-agent/bin/changeset_lib.py infra/hermes-agent/bin/changeset_lib.test.py
git commit -m "feat(hermes): typed change-set schema and canonical hashing"
```

---

### Task 2: Registry `mutate_execute` block, caps, and allow-list disjointness

**Files:**
- Modify: `infra/hermes-agent/bin/changeset_lib.py` (append)
- Modify: `infra/hermes-agent/bin/changeset_lib.test.py` (append)
- Modify: `infra/hermes-agent/registry/projects.yaml`

**Interfaces:**
- Consumes: nothing new.
- Produces: `CAP_KEYS`, `_strip_inline_comment(s)`, `_iter_project_lines(path, project)`, `read_workdir(path, project) -> str`, `read_block(path, project, block) -> dict`, `read_allow_list(path, project, block) -> [str]`, `read_mutate_execute(path, project) -> {"runner": str, "script_dir": str, "allow": [str], "caps": {str: int}}`, `assert_allow_lists_disjoint(read_allow, mutate_allow) -> None`. All raise `ValueError` on rejection.

**Context:** the parsing approach mirrors `read_read_execute()` in `run-ads-report.py:71-105` — same stdlib line-parsing and the same scope discipline (any sibling or shallower line closes the block, so a later key cannot bleed into `allow`). The difference is a second nested sub-block, `caps`. Do not import from `run-ads-report.py`; it is a script, not a module, and Inc-3 is frozen by the Global Constraints.

**One walker, not four.** Everything this tier needs to read from the registry — the workdir, the mutate block, and the read_execute allow-list for the disjointness check — is built on the single `_iter_project_lines` generator, in this file. Task 7's applier calls `C.read_workdir` and `C.read_allow_list`; it must not define parsers of its own. Parsers that change together live together.

- [ ] **Step 1: Write the failing test**

Append to `infra/hermes-agent/bin/changeset_lib.test.py`, before the `if __name__` line:

```python
import tempfile

REG = """version: 1

projects:
  claude_code:
    workdir: /projects/claude_code
    scope: read
  claude_google_ads:
    workdir: /projects/claude_google_ads
    scope: read-execute
    read_execute:
      runner: /opt/ads-venv/bin/python3
      script_dir: code
      allow:
        - account_overview
        - audit_analyze
    mutate_execute:
      runner: /opt/ads-venv/bin/python3   # inline comment must be stripped
      script_dir: code
      allow:
        - mutate_campaign_negative
      caps:
        actions_per_changeset: 25
        actions_per_client_day: 100
        applies_per_client_day: 5
        approval_ttl_hours: 24
"""

def _reg_file(text):
    fd, p = tempfile.mkstemp(suffix=".yaml")
    with os.fdopen(fd, "w") as f:
        f.write(text)
    return p

class TestRegistry(unittest.TestCase):
    def setUp(self):
        self.p = _reg_file(REG)

    def test_reads_mutate_execute(self):
        cfg = C.read_mutate_execute(self.p, "claude_google_ads")
        self.assertEqual(cfg["runner"], "/opt/ads-venv/bin/python3")
        self.assertEqual(cfg["script_dir"], "code")
        self.assertEqual(cfg["allow"], ["mutate_campaign_negative"])

    def test_reads_caps_as_ints(self):
        caps = C.read_mutate_execute(self.p, "claude_google_ads")["caps"]
        self.assertEqual(caps["actions_per_changeset"], 25)
        self.assertEqual(caps["applies_per_client_day"], 5)
        self.assertIsInstance(caps["approval_ttl_hours"], int)

    def test_read_execute_entries_do_not_bleed_into_mutate_allow(self):
        cfg = C.read_mutate_execute(self.p, "claude_google_ads")
        self.assertNotIn("account_overview", cfg["allow"])

    def test_project_without_mutate_execute_refused(self):
        with self.assertRaises(ValueError):
            C.read_mutate_execute(self.p, "claude_code")

    def test_unknown_project_refused(self):
        with self.assertRaises(ValueError):
            C.read_mutate_execute(self.p, "no_such_project")

    def test_missing_cap_refuses_rather_than_defaults(self):
        text = REG.replace("        applies_per_client_day: 5\n", "")
        with self.assertRaises(ValueError) as ctx:
            C.read_mutate_execute(_reg_file(text), "claude_google_ads")
        self.assertIn("applies_per_client_day", str(ctx.exception))

    def test_malformed_cap_refuses(self):
        for bad in ["many", "-1", "0", "2.5", ""]:
            text = REG.replace("actions_per_changeset: 25", f"actions_per_changeset: {bad}")
            with self.assertRaises(ValueError):
                C.read_mutate_execute(_reg_file(text), "claude_google_ads")

    def test_missing_allow_refuses(self):
        text = REG.replace("        - mutate_campaign_negative\n", "")
        with self.assertRaises(ValueError):
            C.read_mutate_execute(_reg_file(text), "claude_google_ads")

    def test_duplicate_allow_header_refused(self):
        """A repeated allow: header must not accumulate — that would silently admit a
        second mutator into the list that decides what may touch a live account."""
        text = REG.replace("        - mutate_campaign_negative\n",
                           "        - mutate_campaign_negative\n      allow:\n        - apply_negatives\n")
        with self.assertRaises(ValueError) as ctx:
            C.read_mutate_execute(_reg_file(text), "claude_google_ads")
        self.assertIn("duplicate", str(ctx.exception))

    def test_duplicate_caps_header_refused(self):
        text = REG.replace("      caps:\n", "      caps:\n        actions_per_changeset: 999\n      caps:\n")
        with self.assertRaises(ValueError):
            C.read_mutate_execute(_reg_file(text), "claude_google_ads")

    def test_duplicate_scalar_key_refused(self):
        """A repeated runner: would otherwise silently swap the interpreter."""
        text = REG.replace("      script_dir: code\n", "      script_dir: code\n      runner: /bin/sh\n")
        with self.assertRaises(ValueError):
            C.read_mutate_execute(_reg_file(text), "claude_google_ads")

    def test_duplicate_block_refused(self):
        text = REG + """    mutate_execute:
      runner: /bin/sh
      script_dir: code
      allow:
        - evil
      caps:
        actions_per_changeset: 1
        actions_per_client_day: 1
        applies_per_client_day: 1
        approval_ttl_hours: 1
"""
        with self.assertRaises(ValueError):
            C.read_mutate_execute(_reg_file(text), "claude_google_ads")

    def test_read_workdir(self):
        self.assertEqual(C.read_workdir(self.p, "claude_google_ads"), "/projects/claude_google_ads")
        self.assertEqual(C.read_workdir(self.p, "claude_code"), "/projects/claude_code")

    def test_read_workdir_unknown_project_refused(self):
        with self.assertRaises(ValueError):
            C.read_workdir(self.p, "no_such_project")

    def test_read_allow_list_reads_each_block_separately(self):
        self.assertEqual(C.read_allow_list(self.p, "claude_google_ads", "read_execute"),
                         ["account_overview", "audit_analyze"])
        self.assertEqual(C.read_allow_list(self.p, "claude_google_ads", "mutate_execute"),
                         ["mutate_campaign_negative"])

    def test_read_allow_list_absent_block_is_empty(self):
        self.assertEqual(C.read_allow_list(self.p, "claude_code", "mutate_execute"), [])

    def test_walker_ignores_other_projects(self):
        """A block belonging to another project must never leak into this one."""
        self.assertEqual(C.read_allow_list(self.p, "claude_code", "read_execute"), [])

class TestDisjointness(unittest.TestCase):
    def test_disjoint_lists_pass(self):
        C.assert_allow_lists_disjoint(["account_overview"], ["mutate_campaign_negative"])

    def test_overlap_refused(self):
        with self.assertRaises(ValueError) as ctx:
            C.assert_allow_lists_disjoint(["account_overview", "shared"], ["shared"])
        self.assertIn("shared", str(ctx.exception))

    def test_real_registry_lists_are_disjoint(self):
        """The shipped registry must never list a script as both reader and mutator."""
        here = os.path.dirname(os.path.abspath(__file__))
        real = os.path.join(here, "..", "registry", "projects.yaml")
        mut = C.read_mutate_execute(real, "claude_google_ads")
        read_allow = C.read_allow_list(real, "claude_google_ads", "read_execute")
        self.assertTrue(read_allow, "read_execute allow-list should not be empty")
        C.assert_allow_lists_disjoint(read_allow, mut["allow"])
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
python3 infra/hermes-agent/bin/changeset_lib.test.py
```

Expected: FAIL with `AttributeError: module 'changeset_lib' has no attribute 'read_mutate_execute'`.

- [ ] **Step 3: Add the `mutate_execute` block to the registry**

In `infra/hermes-agent/registry/projects.yaml`, append to the `claude_google_ads` project, at the same indent as its existing `read_execute:` key:

```yaml
    # MUTATION TIER (Task 2 increment). Separate from read_execute by design: the
    # read allow-list's invariant is "readers only; mutators are never allow-listed",
    # and apply-changeset.py refuses if any name appears in BOTH lists.
    # Runs under a SEPARATE Standard-access write credential (.env.gaw), injected
    # per-invocation. Never the read-only .env.ga, never the gateway env.
    mutate_execute:
      runner: /opt/ads-venv/bin/python3   # pinned build-time venv, NOT base python
      script_dir: code             # relative to workdir
      allow:                       # EXACT basenames; fail-closed; ONE typed mutator
        - mutate_campaign_negative
      caps:                        # fail-closed: missing or malformed => refuse
        actions_per_changeset: 25      # largest batch a human can review in one sitting
        actions_per_client_day: 100
        applies_per_client_day: 5      # load-bearing cap against malfunction
        approval_ttl_hours: 24
```

- [ ] **Step 4: Write the implementation**

Append to `infra/hermes-agent/bin/changeset_lib.py`:

```python
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
```

- [ ] **Step 5: Run the tests to verify they pass**

```bash
python3 infra/hermes-agent/bin/changeset_lib.test.py
```

Expected: `OK`. `test_real_registry_lists_are_disjoint` proves the shipped registry is clean.

- [ ] **Step 6: Verify Inc-3's reader still parses the edited registry**

```bash
python3 infra/hermes-agent/bin/run-ads-report.test.py
```

Expected: `OK`. This is a regression gate — the new block must not disturb `read_read_execute`.

- [ ] **Step 7: Commit**

```bash
git add infra/hermes-agent/bin/changeset_lib.py infra/hermes-agent/bin/changeset_lib.test.py \
        infra/hermes-agent/registry/projects.yaml
git commit -m "feat(hermes): mutate_execute registry block with fail-closed caps"
```

---

### Task 3: Approval records, kill switch, and audit-log accounting

**Files:**
- Modify: `infra/hermes-agent/bin/changeset_lib.py` (append)
- Modify: `infra/hermes-agent/bin/changeset_lib.test.py` (append)

**Interfaces:**
- Consumes: `vault_lib.vault_root()`.
- Produces: `GOVERNANCE_DIR`, `KILL_SWITCH`, `OPERATOR_RE`, `kill_switch_ok(vault_root=None) -> bool`, `changes_dir(vault)`, `changeset_path(vault, cid)`, `approval_path(vault, cid)`, `result_path(vault, cid)`, `log_path(vault)`, `file_digest(path) -> str`, `write_approval(vault, cid, digest, operator, now, ttl_hours) -> dict`, `verify_approval(vault, cid, digest, now) -> dict`, `append_log(vault, rec) -> None`, `day_counts(vault, day) -> {"applies": int, "actions": int}`.

- [ ] **Step 1: Write the failing test**

Append to `infra/hermes-agent/bin/changeset_lib.test.py`, before the `if __name__` line:

```python
import datetime

NOW = datetime.datetime(2026, 8, 12, 10, 15, 0, tzinfo=datetime.timezone.utc)

class TestKillSwitch(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()

    def test_absent_switch_is_not_ok(self):
        self.assertFalse(C.kill_switch_ok(self.root))

    def test_present_switch_is_ok(self):
        d = os.path.join(self.root, C.GOVERNANCE_DIR)
        os.makedirs(d)
        with open(os.path.join(d, C.KILL_SWITCH), "w") as f:
            f.write("enabled\n")
        self.assertTrue(C.kill_switch_ok(self.root))

    def test_directory_in_place_of_switch_is_not_ok(self):
        os.makedirs(os.path.join(self.root, C.GOVERNANCE_DIR, C.KILL_SWITCH))
        self.assertFalse(C.kill_switch_ok(self.root))

class TestApproval(unittest.TestCase):
    def setUp(self):
        self.vault = tempfile.mkdtemp()
        os.makedirs(C.changes_dir(self.vault))
        self.cs = os.path.join(C.changes_dir(self.vault), "20260812-101500-abcd1234.json")
        with open(self.cs, "wb") as f:
            f.write(C.canonical_bytes(_cs()))
        self.digest = C.file_digest(self.cs)

    def test_write_then_verify_roundtrip(self):
        C.write_approval(self.vault, "20260812-101500-abcd1234", self.digest, "erick", NOW, 24)
        rec = C.verify_approval(self.vault, "20260812-101500-abcd1234", self.digest, NOW)
        self.assertEqual(rec["operator"], "erick")

    def test_missing_approval_refused(self):
        with self.assertRaises(ValueError):
            C.verify_approval(self.vault, "20260812-101500-abcd1234", self.digest, NOW)

    def test_hash_mismatch_refused(self):
        C.write_approval(self.vault, "20260812-101500-abcd1234", self.digest, "erick", NOW, 24)
        with open(self.cs, "ab") as f:
            f.write(b" ")                     # a single whitespace byte
        new_digest = C.file_digest(self.cs)
        with self.assertRaises(ValueError) as ctx:
            C.verify_approval(self.vault, "20260812-101500-abcd1234", new_digest, NOW)
        self.assertIn("modified after approval", str(ctx.exception))

    def test_expired_approval_refused(self):
        C.write_approval(self.vault, "20260812-101500-abcd1234", self.digest, "erick", NOW, 24)
        later = NOW + datetime.timedelta(hours=24, seconds=1)
        with self.assertRaises(ValueError) as ctx:
            C.verify_approval(self.vault, "20260812-101500-abcd1234", self.digest, later)
        self.assertIn("expired", str(ctx.exception))

    def test_within_ttl_accepted(self):
        C.write_approval(self.vault, "20260812-101500-abcd1234", self.digest, "erick", NOW, 24)
        later = NOW + datetime.timedelta(hours=23, minutes=59)
        self.assertEqual(
            C.verify_approval(self.vault, "20260812-101500-abcd1234", self.digest, later)["operator"],
            "erick")

    def test_bad_operator_rejected(self):
        for bad in ["", "a b", "rm -rf /", "x" * 65, "erick\n"]:
            with self.assertRaises(ValueError):
                C.write_approval(self.vault, "20260812-101500-abcd1234", self.digest, bad, NOW, 24)

class TestLog(unittest.TestCase):
    def setUp(self):
        self.vault = tempfile.mkdtemp()

    def _line(self, **kw):
        rec = {"ts": "2026-08-12T10:15:00Z", "changeset_id": "20260812-101500-abcd1234",
               "action_index": 0, "type": "add_campaign_negative",
               "resource_name": "customers/1234567890/campaignCriteria/1~2",
               "status": "applied", "operator": "erick"}
        rec.update(kw)
        return rec

    def test_empty_log_counts_zero(self):
        self.assertEqual(C.day_counts(self.vault, "2026-08-12"), {"applies": 0, "actions": 0})

    def test_counts_actions_and_distinct_applies(self):
        C.append_log(self.vault, self._line(action_index=0))
        C.append_log(self.vault, self._line(action_index=1))
        C.append_log(self.vault, self._line(changeset_id="20260812-120000-beef0001"))
        self.assertEqual(C.day_counts(self.vault, "2026-08-12"), {"applies": 2, "actions": 3})

    def test_other_days_not_counted(self):
        C.append_log(self.vault, self._line(ts="2026-08-11T23:59:59Z"))
        self.assertEqual(C.day_counts(self.vault, "2026-08-12"), {"applies": 0, "actions": 0})

    def test_undone_lines_not_counted_as_applies(self):
        C.append_log(self.vault, self._line(status="undone"))
        self.assertEqual(C.day_counts(self.vault, "2026-08-12"), {"applies": 0, "actions": 0})

    def test_corrupt_log_refuses_rather_than_undercounting(self):
        C.append_log(self.vault, self._line())
        with open(C.log_path(self.vault), "a") as f:
            f.write("{not json\n")
        with self.assertRaises(ValueError) as ctx:
            C.day_counts(self.vault, "2026-08-12")
        self.assertIn("corrupt", str(ctx.exception))

    def test_append_is_durable_and_one_line_per_record(self):
        C.append_log(self.vault, self._line())
        C.append_log(self.vault, self._line(action_index=1))
        with open(C.log_path(self.vault)) as f:
            self.assertEqual(len([x for x in f.read().splitlines() if x.strip()]), 2)
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
python3 infra/hermes-agent/bin/changeset_lib.test.py
```

Expected: FAIL with `AttributeError: module 'changeset_lib' has no attribute 'kill_switch_ok'`.

- [ ] **Step 3: Write the implementation**

Append to `infra/hermes-agent/bin/changeset_lib.py`:

```python
import hashlib

GOVERNANCE_DIR = "_governance"
KILL_SWITCH = "mutation-enabled"
OPERATOR_RE = re.compile(r"^[A-Za-z0-9._@-]{1,64}$")


def kill_switch_ok(vault_root=None):
    """The safe state is the default state: absent, unreadable, or not a regular file
    all mean 'mutation disabled'. Never raises — the caller turns False into a refusal."""
    root = vault_root or vault_lib.vault_root()
    p = os.path.join(root, GOVERNANCE_DIR, KILL_SWITCH)
    try:
        with open(p, "rb") as f:
            f.read(1)
    except OSError:
        return False
    return True


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


def file_digest(path):
    """sha256 over the RAW file bytes. propose writes canonical JSON, so this is both
    canonical and byte-exact: any later edit, including whitespace, invalidates it."""
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def _atomic_write_json(path, obj):
    """Write-temp-then-replace (the two-tier final-review correction for the registry
    status flip) so a crash can never leave a half-written approval."""
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2, sort_keys=True)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def write_approval(vault, cid, digest, operator, now, ttl_hours):
    if not OPERATOR_RE.fullmatch(operator or ""):
        raise ValueError(f"invalid operator: {operator!r} (allowed ^[A-Za-z0-9._@-]{{1,64}}$)")
    rec = {"changeset_id": cid, "sha256": digest, "operator": operator,
           "approved_at": now.strftime(ISO),
           "expires_at": (now + datetime.timedelta(hours=ttl_hours)).strftime(ISO)}
    os.makedirs(changes_dir(vault), exist_ok=True)
    _atomic_write_json(approval_path(vault, cid), rec)
    return rec


def verify_approval(vault, cid, digest, now):
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
    if rec.get("sha256") != digest:
        raise ValueError(f"approval hash mismatch for {cid!r} — the change-set was "
                         "modified after approval; re-approve the reviewed bytes")
    expires = datetime.datetime.strptime(str(rec.get("expires_at", "")), ISO).replace(
        tzinfo=datetime.timezone.utc)
    if now > expires:
        raise ValueError(f"approval for {cid!r} expired at {rec['expires_at']} — re-approve")
    return rec


def append_log(vault, rec):
    """Append ONE audit-log line and fsync it. The log is the reversibility record for
    an irreversible action, so it must be durable before the next action starts —
    never let a side effect outrun its record (the vault-purge lesson)."""
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
    """Count applied actions and distinct applied change-sets for a UTC day (YYYY-MM-DD).
    A corrupt line is a refusal, not a skip: an unreadable counter must never read as
    'under the cap'."""
    p = log_path(vault)
    if not os.path.exists(p):
        return {"applies": 0, "actions": 0}
    applies, actions = set(), 0
    with open(p, encoding="utf-8") as f:
        for n, line in enumerate(f, 1):
            if not line.strip():
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError as e:
                raise ValueError(f"corrupt audit log at {p}:{n} ({e}) — caps are fail-closed")
            if rec.get("status") == "applied" and str(rec.get("ts", "")).startswith(day):
                applies.add(rec.get("changeset_id"))
                actions += 1
    return {"applies": len(applies), "actions": actions}
```

Move the `import hashlib` up into the module's existing import line rather than leaving it mid-file.

- [ ] **Step 4: Run the tests to verify they pass**

```bash
python3 infra/hermes-agent/bin/changeset_lib.test.py
```

Expected: `OK`.

- [ ] **Step 5: Commit**

```bash
git add infra/hermes-agent/bin/changeset_lib.py infra/hermes-agent/bin/changeset_lib.test.py
git commit -m "feat(hermes): approval records, kill switch, fsync'd audit log"
```

---

### Task 4: `propose-changeset.py`

**Files:**
- Create: `infra/hermes-agent/bin/propose-changeset.py`
- Test: `infra/hermes-agent/bin/propose-changeset.test.py`

**Interfaces:**
- Consumes: `changeset_lib.validate_changeset`, `canonical_bytes`, `read_mutate_execute`, `changes_dir`, `changeset_path`, `ISO`; `vault_lib.resolve`.
- Produces: `propose(client, actions_file, now, registry=None, projects=None) -> dict` (the written change-set), and a CLI `--client --from [--registry] [--projects]` printing the change-set path, exit 0 / 2.

**Behaviour:** the operator's `--from` file contains **only** `{"actions": [...]}`. `propose` supplies `client`, `project`, `customer_id` (from `vault_lib.resolve`), `changeset_id`, and `created_at`. An operator therefore cannot typo a customer ID into a change-set.

- [ ] **Step 1: Write the failing test**

Create `infra/hermes-agent/bin/propose-changeset.test.py`:

```python
import datetime, importlib.util, json, os, subprocess, sys, tempfile, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

def _load(name, filename):
    spec = importlib.util.spec_from_file_location(name, os.path.join(HERE, filename))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

P = _load("propose_changeset", "propose-changeset.py")
NOW = datetime.datetime(2026, 8, 12, 10, 15, 0, tzinfo=datetime.timezone.utc)

REG = """version: 1

projects:
  claude_google_ads:
    workdir: /projects/claude_google_ads
    mutate_execute:
      runner: /opt/ads-venv/bin/python3
      script_dir: code
      allow:
        - mutate_campaign_negative
      caps:
        actions_per_changeset: 2
        actions_per_client_day: 100
        applies_per_client_day: 5
        approval_ttl_hours: 24
"""

def _action(**kw):
    a = {"type": "add_campaign_negative", "campaign_id": "22233344455",
         "keyword": "free consultation", "match_type": "PHRASE"}
    a.update(kw)
    return a

class T(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        os.environ["VAULT_ROOT"] = self.tmp
        d = os.path.join(self.tmp, "_registry"); os.makedirs(d)
        self.clients = os.path.join(d, "clients.json")
        with open(self.clients, "w") as f:
            json.dump({"clients": {"acme-dental": {
                "project": "claude_google_ads", "customer_id": "1234567890",
                "status": "active"}}}, f)
        self.projects = os.path.join(self.tmp, "projects.yaml")
        with open(self.projects, "w") as f:
            f.write(REG)

    def _actions_file(self, actions):
        p = os.path.join(self.tmp, "in.json")
        with open(p, "w") as f:
            json.dump({"actions": actions}, f)
        return p

    def test_fills_identity_from_resolver(self):
        cs = P.propose("acme-dental", self._actions_file([_action()]), NOW,
                       registry=self.clients, projects=self.projects)
        self.assertEqual(cs["customer_id"], "1234567890")
        self.assertEqual(cs["client"], "acme-dental")
        self.assertEqual(cs["project"], "claude_google_ads")
        self.assertEqual(cs["created_at"], "2026-08-12T10:15:00Z")

    def test_changeset_id_shape_and_uniqueness(self):
        a = P.propose("acme-dental", self._actions_file([_action()]), NOW,
                      registry=self.clients, projects=self.projects)
        b = P.propose("acme-dental", self._actions_file([_action()]), NOW,
                      registry=self.clients, projects=self.projects)
        self.assertRegex(a["changeset_id"], r"^\d{8}-\d{6}-[0-9a-f]{8}$")
        self.assertNotEqual(a["changeset_id"], b["changeset_id"])

    def test_writes_canonical_bytes_to_vault(self):
        import changeset_lib as C
        cs = P.propose("acme-dental", self._actions_file([_action()]), NOW,
                       registry=self.clients, projects=self.projects)
        path = C.changeset_path(os.path.join(self.tmp, "acme-dental"), cs["changeset_id"])
        with open(path, "rb") as f:
            self.assertEqual(f.read(), C.canonical_bytes(cs))

    def test_operator_supplied_identity_fields_refused(self):
        p = os.path.join(self.tmp, "bad.json")
        with open(p, "w") as f:
            json.dump({"actions": [_action()], "customer_id": "9999999999"}, f)
        with self.assertRaises(ValueError):
            P.propose("acme-dental", p, NOW, registry=self.clients, projects=self.projects)

    def test_over_cap_refused(self):
        with self.assertRaises(ValueError):
            P.propose("acme-dental", self._actions_file([_action()] * 3), NOW,
                      registry=self.clients, projects=self.projects)

    def test_bad_action_refused(self):
        with self.assertRaises(ValueError):
            P.propose("acme-dental", self._actions_file([_action(type="set_budget")]), NOW,
                      registry=self.clients, projects=self.projects)

    def test_unknown_client_refused(self):
        with self.assertRaises(KeyError):
            P.propose("nope", self._actions_file([_action()]), NOW,
                      registry=self.clients, projects=self.projects)

    def test_cli_bad_slug_exit2(self):
        out = subprocess.run(
            [sys.executable, os.path.join(HERE, "propose-changeset.py"),
             "--client", "../etc", "--from", self._actions_file([_action()]),
             "--registry", self.clients, "--projects", self.projects],
            capture_output=True, text=True, env={**os.environ})
        self.assertEqual(out.returncode, 2)

    def test_cli_success_prints_path_exit0(self):
        out = subprocess.run(
            [sys.executable, os.path.join(HERE, "propose-changeset.py"),
             "--client", "acme-dental", "--from", self._actions_file([_action()]),
             "--registry", self.clients, "--projects", self.projects],
            capture_output=True, text=True, env={**os.environ})
        self.assertEqual(out.returncode, 0)
        self.assertTrue(os.path.exists(out.stdout.strip()))

if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
python3 infra/hermes-agent/bin/propose-changeset.test.py
```

Expected: FAIL — `propose-changeset.py` does not exist.

- [ ] **Step 3: Write the implementation**

Create `infra/hermes-agent/bin/propose-changeset.py`:

```python
#!/usr/bin/env python3
"""Validate an operator-authored actions file into a typed change-set in the client
vault. Stdlib-only. HOLDS NO CREDENTIAL and performs no network I/O — this command
is structurally incapable of touching the ad account.

The operator supplies ONLY the actions array. Identity fields (client, project,
customer_id) come from the client resolver, so an operator cannot typo a customer id
into a change-set, and the apply-time identity check becomes a tamper check.
"""
import argparse, datetime, json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import changeset_lib as C
import vault_lib

ALLOWED_INPUT_FIELDS = {"actions"}


def propose(client, actions_file, now, registry=None, projects=None):
    rec = vault_lib.resolve(client, registry)          # validates slug + customer_id
    projects_path = projects or C.registry_projects_path()
    caps = C.read_mutate_execute(projects_path, rec["project"])["caps"]
    with open(actions_file, encoding="utf-8") as f:
        payload = json.load(f)
    if not isinstance(payload, dict):
        raise ValueError("actions file must be a JSON object with an 'actions' key")
    extra = set(payload) - ALLOWED_INPUT_FIELDS
    if extra:
        raise ValueError(f"actions file may only contain 'actions'; identity fields are "
                         f"supplied by the resolver, not the operator (got {sorted(extra)})")
    cs = {
        "changeset_id": f"{now.strftime('%Y%m%d-%H%M%S')}-{os.urandom(4).hex()}",
        "client": rec["slug"],
        "project": rec["project"],
        "customer_id": rec["customer_id"],
        "created_at": now.strftime(C.ISO),
        "actions": payload.get("actions"),
    }
    C.validate_changeset(cs, caps["actions_per_changeset"])
    vault = rec["vault_path"]
    os.makedirs(C.changes_dir(vault), exist_ok=True)
    path = C.changeset_path(vault, cs["changeset_id"])
    with open(path, "wb") as f:                        # canonical bytes; hashed later
        f.write(C.canonical_bytes(cs))
        f.flush()
        os.fsync(f.fileno())
    return cs


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--client", required=True)
    ap.add_argument("--from", dest="actions_file", required=True)
    ap.add_argument("--registry", help="clients.json (default: <VAULT_ROOT>/_registry)")
    ap.add_argument("--projects", help="projects.yaml (default: /opt/registry or ../registry)")
    args = ap.parse_args(argv)
    now = datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0)
    try:
        cs = propose(args.client, args.actions_file, now, args.registry, args.projects)
    except (ValueError, KeyError, OSError, TypeError, json.JSONDecodeError) as e:
        print(f"propose-changeset: {e}", file=sys.stderr)
        return 2
    rec = vault_lib.resolve(cs["client"], args.registry)
    print(C.changeset_path(rec["vault_path"], cs["changeset_id"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

Add the shared registry-path helper to `changeset_lib.py` (append):

```python
DEFAULT_PROJECTS_REGISTRY = "/opt/registry/projects.yaml"


def registry_projects_path():
    """Container path when mounted, else the in-repo copy — mirrors
    run-ads-report.py:registry_path()."""
    return os.environ.get("ADS_REGISTRY") or (
        DEFAULT_PROJECTS_REGISTRY if os.path.exists(DEFAULT_PROJECTS_REGISTRY)
        else os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "registry", "projects.yaml"))
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
python3 infra/hermes-agent/bin/propose-changeset.test.py
python3 infra/hermes-agent/bin/changeset_lib.test.py
```

Expected: both `OK`.

- [ ] **Step 5: Commit**

```bash
git add infra/hermes-agent/bin/propose-changeset.py infra/hermes-agent/bin/propose-changeset.test.py \
        infra/hermes-agent/bin/changeset_lib.py
git commit -m "feat(hermes): propose-changeset (uncredentialed, resolver-supplied identity)"
```

---

### Task 5: `approve-changeset.py`

**Files:**
- Create: `infra/hermes-agent/bin/approve-changeset.py`
- Test: `infra/hermes-agent/bin/approve-changeset.test.py`

**Interfaces:**
- Consumes: `changeset_lib.file_digest`, `validate_changeset`, `write_approval`, `read_mutate_execute`, `changeset_path`, `registry_projects_path`; `vault_lib.resolve`.
- Produces: `approve(client, changeset_id, operator, now, registry=None, projects=None) -> dict` (the approval record), and a CLI `--client --changeset --operator [--registry] [--projects]`, exit 0 / 2.

- [ ] **Step 1: Write the failing test**

Create `infra/hermes-agent/bin/approve-changeset.test.py`:

```python
import datetime, importlib.util, json, os, subprocess, sys, tempfile, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import changeset_lib as C

def _load(name, filename):
    spec = importlib.util.spec_from_file_location(name, os.path.join(HERE, filename))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

P = _load("propose_changeset", "propose-changeset.py")
A = _load("approve_changeset", "approve-changeset.py")
NOW = datetime.datetime(2026, 8, 12, 10, 15, 0, tzinfo=datetime.timezone.utc)

REG = """version: 1

projects:
  claude_google_ads:
    workdir: /projects/claude_google_ads
    mutate_execute:
      runner: /opt/ads-venv/bin/python3
      script_dir: code
      allow:
        - mutate_campaign_negative
      caps:
        actions_per_changeset: 25
        actions_per_client_day: 100
        applies_per_client_day: 5
        approval_ttl_hours: 24
"""

class T(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        os.environ["VAULT_ROOT"] = self.tmp
        d = os.path.join(self.tmp, "_registry"); os.makedirs(d)
        self.clients = os.path.join(d, "clients.json")
        with open(self.clients, "w") as f:
            json.dump({"clients": {"acme-dental": {
                "project": "claude_google_ads", "customer_id": "1234567890",
                "status": "active"}}}, f)
        self.projects = os.path.join(self.tmp, "projects.yaml")
        with open(self.projects, "w") as f:
            f.write(REG)
        src = os.path.join(self.tmp, "in.json")
        with open(src, "w") as f:
            json.dump({"actions": [{"type": "add_campaign_negative",
                                    "campaign_id": "22233344455",
                                    "keyword": "free consultation",
                                    "match_type": "PHRASE"}]}, f)
        self.cs = P.propose("acme-dental", src, NOW, registry=self.clients, projects=self.projects)
        self.vault = os.path.join(self.tmp, "acme-dental")

    def test_approval_records_digest_and_expiry(self):
        rec = A.approve("acme-dental", self.cs["changeset_id"], "erick", NOW,
                        registry=self.clients, projects=self.projects)
        self.assertEqual(rec["sha256"],
                         C.file_digest(C.changeset_path(self.vault, self.cs["changeset_id"])))
        self.assertEqual(rec["expires_at"], "2026-08-13T10:15:00Z")

    def test_approval_verifies_after_write(self):
        A.approve("acme-dental", self.cs["changeset_id"], "erick", NOW,
                  registry=self.clients, projects=self.projects)
        digest = C.file_digest(C.changeset_path(self.vault, self.cs["changeset_id"]))
        self.assertEqual(
            C.verify_approval(self.vault, self.cs["changeset_id"], digest, NOW)["operator"], "erick")

    def test_tampered_changeset_refused_at_approve(self):
        p = C.changeset_path(self.vault, self.cs["changeset_id"])
        with open(p, "w") as f:
            json.dump({"changeset_id": self.cs["changeset_id"], "client": "acme-dental",
                       "project": "claude_google_ads", "customer_id": "1234567890",
                       "created_at": "2026-08-12T10:15:00Z",
                       "actions": [{"type": "set_campaign_budget", "campaign_id": "1",
                                    "keyword": "x", "match_type": "PHRASE"}]}, f)
        with self.assertRaises(ValueError):
            A.approve("acme-dental", self.cs["changeset_id"], "erick", NOW,
                      registry=self.clients, projects=self.projects)

    def test_missing_changeset_refused(self):
        with self.assertRaises(ValueError):
            A.approve("acme-dental", "20260812-999999-deadbeef", "erick", NOW,
                      registry=self.clients, projects=self.projects)

    def test_bad_changeset_id_refused(self):
        with self.assertRaises(ValueError):
            A.approve("acme-dental", "../../etc/passwd", "erick", NOW,
                      registry=self.clients, projects=self.projects)

    def test_bad_operator_refused(self):
        with self.assertRaises(ValueError):
            A.approve("acme-dental", self.cs["changeset_id"], "rm -rf /", NOW,
                      registry=self.clients, projects=self.projects)

    def test_cli_success_exit0(self):
        out = subprocess.run(
            [sys.executable, os.path.join(HERE, "approve-changeset.py"),
             "--client", "acme-dental", "--changeset", self.cs["changeset_id"],
             "--operator", "erick", "--registry", self.clients, "--projects", self.projects],
            capture_output=True, text=True, env={**os.environ})
        self.assertEqual(out.returncode, 0)

    def test_cli_bad_operator_exit2(self):
        out = subprocess.run(
            [sys.executable, os.path.join(HERE, "approve-changeset.py"),
             "--client", "acme-dental", "--changeset", self.cs["changeset_id"],
             "--operator", "a b", "--registry", self.clients, "--projects", self.projects],
            capture_output=True, text=True, env={**os.environ})
        self.assertEqual(out.returncode, 2)

if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
python3 infra/hermes-agent/bin/approve-changeset.test.py
```

Expected: FAIL — `approve-changeset.py` does not exist.

- [ ] **Step 3: Write the implementation**

Create `infra/hermes-agent/bin/approve-changeset.py`:

```python
#!/usr/bin/env python3
"""Record a hash-bound approval for a proposed change-set. Stdlib-only.
HOLDS NO CREDENTIAL and performs no network I/O.

The approval binds the sha256 of the exact change-set BYTES that were reviewed, plus
an expiry. Editing the change-set afterwards — even by one whitespace byte —
invalidates the approval, because the hash no longer matches.
"""
import argparse, datetime, json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import changeset_lib as C
import vault_lib


def approve(client, changeset_id, operator, now, registry=None, projects=None):
    if not C.CHANGESET_ID_RE.fullmatch(changeset_id or ""):
        raise ValueError(f"invalid --changeset: {changeset_id!r}")
    rec = vault_lib.resolve(client, registry)
    vault = rec["vault_path"]
    path = C.changeset_path(vault, changeset_id)
    if not os.path.isfile(path):
        raise ValueError(f"no change-set {changeset_id!r} for this client")
    caps = C.read_mutate_execute(projects or C.registry_projects_path(), rec["project"])["caps"]
    with open(path, encoding="utf-8") as f:
        cs = json.load(f)
    # Re-validate at approve time: never approve bytes that would be refused at apply.
    C.validate_changeset(cs, caps["actions_per_changeset"])
    if cs["client"] != rec["slug"] or cs["customer_id"] != rec["customer_id"]:
        raise ValueError("change-set identity does not match the resolved client")
    return C.write_approval(vault, changeset_id, C.file_digest(path), operator, now,
                            caps["approval_ttl_hours"])


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--client", required=True)
    ap.add_argument("--changeset", required=True)
    ap.add_argument("--operator", required=True)
    ap.add_argument("--registry")
    ap.add_argument("--projects")
    args = ap.parse_args(argv)
    now = datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0)
    try:
        rec = approve(args.client, args.changeset, args.operator, now, args.registry, args.projects)
    except (ValueError, KeyError, OSError, TypeError, json.JSONDecodeError) as e:
        print(f"approve-changeset: {e}", file=sys.stderr)
        return 2
    print(f"approved {rec['changeset_id']} by {rec['operator']} (expires {rec['expires_at']})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
python3 infra/hermes-agent/bin/approve-changeset.test.py
```

Expected: `OK`.

- [ ] **Step 5: Commit**

```bash
git add infra/hermes-agent/bin/approve-changeset.py infra/hermes-agent/bin/approve-changeset.test.py
git commit -m "feat(hermes): approve-changeset with byte-exact hash binding and expiry"
```

---

### Task 6: The typed mutator (separate `claude-google-ads` repo)

**Files (in `/Users/ericksicard/projects/claude-google-ads`):**
- Create: `code/mutate_campaign_negative.py`
- Test: `code/mutate_campaign_negative.test.py`

**Interfaces:**
- Consumes: the six `GOOGLE_ADS_*` environment variables, injected per-invocation. Never `load_dotenv`.
- Produces (CLI contract that `apply-changeset.py` in Task 7 depends on):
  - `--action '<json>' [--validate-only]` → stdout is one JSON object. Live: `{"ok": true, "resource_name": "customers/<cid>/campaignCriteria/<cid>~<crit>"}`. Validate-only: `{"ok": true, "validate_only": true}`.
  - `--undo '<resource_name>' [--validate-only]` → `{"ok": true, "removed": "<resource_name>"}` or `{"ok": true, "validate_only": true}`.
  - Exit 0 on success, 2 on refusal or API error, with a message on stderr.
- Produces (importable, pure, testable without network): `parse_action(s) -> dict`, `require_credentials(env) -> dict`, `RESOURCE_RE`.

**Important:** this is a different repository. Commit there separately. It has 2 pre-existing unpushed commits and uncommitted WIP — leave all of that untouched.

- [ ] **Step 1: Write the failing test**

Create `code/mutate_campaign_negative.test.py` in the `claude-google-ads` repo:

```python
import importlib.util, json, os, sys, unittest

HERE = os.path.dirname(os.path.abspath(__file__))

def _load():
    spec = importlib.util.spec_from_file_location(
        "mutate_campaign_negative", os.path.join(HERE, "mutate_campaign_negative.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

M = _load()

GOOD = {"type": "add_campaign_negative", "campaign_id": "22233344455",
        "keyword": "free consultation", "match_type": "PHRASE"}

FULL_ENV = {"GOOGLE_ADS_DEVELOPER_TOKEN": "t", "GOOGLE_ADS_CLIENT_ID": "i",
            "GOOGLE_ADS_CLIENT_SECRET": "s", "GOOGLE_ADS_REFRESH_TOKEN": "r",
            "GOOGLE_ADS_LOGIN_CUSTOMER_ID": "1234567890",
            "GOOGLE_ADS_CUSTOMER_ID": "1234567890"}

class TestParseAction(unittest.TestCase):
    def test_valid_action(self):
        self.assertEqual(M.parse_action(json.dumps(GOOD))["match_type"], "PHRASE")

    def test_unknown_type_refused(self):
        bad = dict(GOOD, type="set_campaign_budget")
        with self.assertRaises(ValueError):
            M.parse_action(json.dumps(bad))

    def test_bad_match_type_refused(self):
        with self.assertRaises(ValueError):
            M.parse_action(json.dumps(dict(GOOD, match_type="NEAR")))

    def test_non_digit_campaign_id_refused(self):
        with self.assertRaises(ValueError):
            M.parse_action(json.dumps(dict(GOOD, campaign_id="22-33")))

    def test_numeric_campaign_id_refused(self):
        """Must match changeset_lib: fail closed on TYPE, not just shape. A JSON
        number must never coerce its way past a digits-only check."""
        with self.assertRaises(ValueError):
            M.parse_action(json.dumps(dict(GOOD, campaign_id=22233344455)))

    def test_malformed_json_refused(self):
        with self.assertRaises(ValueError):
            M.parse_action("{not json")

class TestCredentials(unittest.TestCase):
    def test_full_env_accepted(self):
        self.assertEqual(M.require_credentials(FULL_ENV)["developer_token"], "t")

    def test_any_missing_var_refused(self):
        for k in FULL_ENV:
            env = dict(FULL_ENV)
            del env[k]
            with self.assertRaises(ValueError):
                M.require_credentials(env)

    def test_empty_value_refused(self):
        with self.assertRaises(ValueError):
            M.require_credentials(dict(FULL_ENV, GOOGLE_ADS_REFRESH_TOKEN=""))

class TestResourceName(unittest.TestCase):
    def test_valid_resource_name(self):
        self.assertTrue(M.RESOURCE_RE.fullmatch("customers/1234567890/campaignCriteria/111~222"))

    def test_traversal_and_junk_refused(self):
        for bad in ["../x", "customers/1234567890/campaigns/1",
                    "customers/1234567890/campaignCriteria/111~222\n", "", "customers//campaignCriteria/1~2"]:
            self.assertIsNone(M.RESOURCE_RE.fullmatch(bad))

class TestNoDotenv(unittest.TestCase):
    def test_source_never_calls_load_dotenv(self):
        """Every other mutator in this repo calls load_dotenv() and would pick up the
        in-tree FULL-ACCESS token. This one must not."""
        with open(os.path.join(HERE, "mutate_campaign_negative.py"), encoding="utf-8") as f:
            src = f.read()
        self.assertNotIn("load_dotenv", src)
        self.assertNotIn("dotenv", src)

if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
cd /Users/ericksicard/projects/claude-google-ads
./.venv/bin/python code/mutate_campaign_negative.test.py
```

Expected: FAIL — the module does not exist.

- [ ] **Step 3: Write the implementation**

Create `code/mutate_campaign_negative.py`:

```python
#!/usr/bin/env python3
"""Typed single-action mutator: add or remove ONE campaign-level negative keyword.

Invoked ONLY by Hermes's apply-changeset.py, which owns the safety rail (approval,
caps, kill switch, audit log). This script is deliberately dumb: it performs exactly
one validated operation and reports the result as JSON.

CREDENTIALS COME STRICTLY FROM THE ENVIRONMENT. This script never calls load_dotenv()
— every other mutator in this repo does, and would silently pick up the in-tree
FULL-ACCESS token. Hermes injects a separate Standard-access write credential
per-invocation; an incomplete set is a refusal, never a fallback.

Usage (both modes support --validate-only for a server-side dry run):
  mutate_campaign_negative.py --action '<json>' [--validate-only]
  mutate_campaign_negative.py --undo '<resource_name>' [--validate-only]
"""
import argparse, json, os, re, sys

from google.ads.googleads.client import GoogleAdsClient
from google.ads.googleads.errors import GoogleAdsException

ACTION_TYPES = ("add_campaign_negative",)
MATCH_TYPES = ("EXACT", "PHRASE", "BROAD")
KEYWORD_MAX = 80
ID_RE = re.compile(r"^[0-9]{1,15}$")
RESOURCE_RE = re.compile(r"^customers/[0-9]{1,15}/campaignCriteria/[0-9]{1,20}~[0-9]{1,20}$")

REQUIRED = ("GOOGLE_ADS_DEVELOPER_TOKEN", "GOOGLE_ADS_CLIENT_ID",
            "GOOGLE_ADS_CLIENT_SECRET", "GOOGLE_ADS_REFRESH_TOKEN",
            "GOOGLE_ADS_LOGIN_CUSTOMER_ID", "GOOGLE_ADS_CUSTOMER_ID")


def digits(v):
    return "".join(c for c in str(v) if c.isdigit())


def parse_action(s):
    try:
        a = json.loads(s)
    except json.JSONDecodeError as e:
        raise ValueError(f"--action is not valid JSON: {e}")
    if not isinstance(a, dict):
        raise ValueError("--action must be a JSON object")
    if a.get("type") not in ACTION_TYPES:
        raise ValueError(f"unknown action type: {a.get('type')!r}")
    cid = a.get("campaign_id")
    if not isinstance(cid, str):        # fail closed on TYPE, not just shape — a JSON
        raise ValueError("campaign_id must be a JSON string")   # number must not coerce
    if not ID_RE.fullmatch(cid):
        raise ValueError(f"invalid campaign_id: {cid!r}")
    if a.get("match_type") not in MATCH_TYPES:
        raise ValueError(f"invalid match_type: {a.get('match_type')!r}")
    kw = a.get("keyword")
    if not isinstance(kw, str) or not kw.strip() or len(kw) > KEYWORD_MAX:
        raise ValueError("invalid keyword")
    if any(ord(c) < 0x20 or ord(c) == 0x7F for c in kw):
        raise ValueError("keyword contains control characters")
    return a


def require_credentials(env):
    missing = [k for k in REQUIRED if not env.get(k)]
    if missing:
        raise ValueError(f"missing injected credential vars: {', '.join(missing)} "
                         "(this script never falls back to an in-tree .env)")
    return {"developer_token": env["GOOGLE_ADS_DEVELOPER_TOKEN"],
            "client_id": env["GOOGLE_ADS_CLIENT_ID"],
            "client_secret": env["GOOGLE_ADS_CLIENT_SECRET"],
            "refresh_token": env["GOOGLE_ADS_REFRESH_TOKEN"],
            "login_customer_id": digits(env["GOOGLE_ADS_LOGIN_CUSTOMER_ID"]),
            "use_proto_plus": True}


def _mutate(client, cid, operation, validate_only):
    svc = client.get_service("CampaignCriterionService")
    req = client.get_type("MutateCampaignCriteriaRequest")
    req.customer_id = cid
    req.operations = [operation]
    req.validate_only = validate_only
    return svc.mutate_campaign_criteria(request=req)


def do_add(client, cid, action, validate_only):
    op = client.get_type("CampaignCriterionOperation")
    crit = op.create
    crit.campaign = client.get_service("CampaignService").campaign_path(
        cid, digits(action["campaign_id"]))
    crit.negative = True
    crit.keyword.text = action["keyword"]
    crit.keyword.match_type = client.enums.KeywordMatchTypeEnum[action["match_type"]]
    resp = _mutate(client, cid, op, validate_only)
    if validate_only:
        return {"ok": True, "validate_only": True}
    return {"ok": True, "resource_name": resp.results[0].resource_name}


def do_undo(client, cid, resource_name, validate_only):
    if not RESOURCE_RE.fullmatch(resource_name or ""):
        raise ValueError(f"invalid --undo resource name: {resource_name!r}")
    if not resource_name.startswith(f"customers/{cid}/"):
        raise ValueError("refusing to remove a criterion belonging to another customer")
    op = client.get_type("CampaignCriterionOperation")
    op.remove = resource_name
    _mutate(client, cid, op, validate_only)
    if validate_only:
        return {"ok": True, "validate_only": True}
    return {"ok": True, "removed": resource_name}


def main(argv=None):
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--action", help="one typed action as JSON")
    g.add_argument("--undo", help="resource name of a criterion this rail created")
    ap.add_argument("--validate-only", action="store_true")
    args = ap.parse_args(argv)
    try:
        cfg = require_credentials(os.environ)
        cid = digits(os.environ["GOOGLE_ADS_CUSTOMER_ID"])
        if not cid:
            raise ValueError("GOOGLE_ADS_CUSTOMER_ID has no digits")
        client = GoogleAdsClient.load_from_dict(cfg)
        if args.action:
            out = do_add(client, cid, parse_action(args.action), args.validate_only)
        else:
            out = do_undo(client, cid, args.undo, args.validate_only)
    except ValueError as e:
        print(f"mutate_campaign_negative: {e}", file=sys.stderr)
        return 2
    except GoogleAdsException as e:
        errs = "; ".join(f"{x.error_code}: {x.message}" for x in e.failure.errors)
        print(f"mutate_campaign_negative: Google Ads API refused: {errs}", file=sys.stderr)
        return 2
    print(json.dumps(out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
cd /Users/ericksicard/projects/claude-google-ads
./.venv/bin/python code/mutate_campaign_negative.test.py
```

Expected: `OK`.

- [ ] **Step 5: Verify it is not on any read allow-list**

```bash
grep -n "mutate_campaign_negative" /Users/ericksicard/Projects/claude_code/infra/hermes-agent/registry/projects.yaml
```

Expected: exactly one hit, inside the `mutate_execute` block. If it appears under `read_execute`, stop and fix.

- [ ] **Step 6: Commit (in the ads repo only)**

```bash
cd /Users/ericksicard/projects/claude-google-ads
git add code/mutate_campaign_negative.py code/mutate_campaign_negative.test.py
git commit -m "feat: typed campaign-negative mutator for the Hermes mutation tier

Credentials strictly from the injected environment -- never load_dotenv, so the
in-tree full-access token can never be picked up. Supports --validate-only for a
server-side dry run, and --undo by exact resource name."
```

Do not push yet, and do not touch the pre-existing WIP. Pushing happens in Task 9 after the wrapper exists.

---

### Task 7: `apply-changeset.py` — guards, dry-run, live apply

**Files:**
- Create: `infra/hermes-agent/bin/apply-changeset.py`
- Test: `infra/hermes-agent/bin/apply-changeset.test.py`

**Interfaces:**
- Consumes: everything from `changeset_lib` — including `read_workdir`, `read_allow_list`, and `read_mutate_execute`; this file defines **no registry parser of its own**. Also the Task-6 mutator CLI contract.
- Produces: `PostMutationError`, `build_plan(client, changeset_id, now, ...) -> dict`, `apply(plan, now) -> int`, CLI `--client (--changeset | --undo) [--registry] [--projects] [--dry-run]`, exit 0 / 1 / 2 / 3.

**Guard order (spec §7) — implement exactly this sequence, so every refusal happens before the credential is used:**

1. kill switch → 2. slug resolves, status `active` → 3. change-set loads, schema-validates, within `actions_per_changeset` → 4. `changeset.client` and `changeset.customer_id` match the resolved client → 5. approval hash matches and is unexpired → 6. daily caps → 7. mutator in `mutate_execute.allow`, allow-lists disjoint → 8. all seven credential vars present and `GOOGLE_ADS_CREDENTIAL_ROLE == "write"` → 9. `validate_only` over **every** action → 10. live apply, logging each action immediately → 11. `result.json` + `timeline.md`.

- [ ] **Step 1: Write the failing test**

Create `infra/hermes-agent/bin/apply-changeset.test.py`. The tests use a **stub mutator** — a tiny Python script that records every invocation to a file — so we can assert the strongest property: for a pre-flight refusal, the mutator is never spawned at all.

```python
import datetime, importlib.util, json, os, stat, subprocess, sys, tempfile, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import changeset_lib as C

def _load(name, filename):
    spec = importlib.util.spec_from_file_location(name, os.path.join(HERE, filename))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

P = _load("propose_changeset", "propose-changeset.py")
A = _load("approve_changeset", "approve-changeset.py")
X = _load("apply_changeset", "apply-changeset.py")

NOW = datetime.datetime(2026, 8, 12, 10, 15, 0, tzinfo=datetime.timezone.utc)

FULL_CRED = {"GOOGLE_ADS_DEVELOPER_TOKEN": "t", "GOOGLE_ADS_CLIENT_ID": "i",
             "GOOGLE_ADS_CLIENT_SECRET": "s", "GOOGLE_ADS_REFRESH_TOKEN": "r",
             "GOOGLE_ADS_LOGIN_CUSTOMER_ID": "1234567890",
             "GOOGLE_ADS_CUSTOMER_ID": "1234567890",
             "GOOGLE_ADS_CREDENTIAL_ROLE": "write"}

STUB = '''#!/usr/bin/env python3
# Test double for the ads-repo mutator. Communicates through FILES beside itself, not
# environment variables, so apply-changeset.py's restricted _child_env() needs no
# test-only entries.
import json, os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
CALLS = os.path.join(HERE, "calls.jsonl")
with open(CALLS, "a") as f:
    f.write(json.dumps(sys.argv[1:]) + "\\n")
mode_file = os.path.join(HERE, "mode.txt")
mode = open(mode_file).read().strip() if os.path.exists(mode_file) else "ok"
if mode == "fail_validate" and "--validate-only" in sys.argv:
    sys.stderr.write("stub: validate refused\\n"); sys.exit(2)
if mode == "fail_second_live" and "--validate-only" not in sys.argv:
    n = sum(1 for _ in open(CALLS))
    if n > 3:
        sys.stderr.write("stub: live failure\\n"); sys.exit(2)
if "--validate-only" in sys.argv:
    print(json.dumps({"ok": True, "validate_only": True})); sys.exit(0)
if "--undo" in sys.argv:
    print(json.dumps({"ok": True, "removed": sys.argv[sys.argv.index("--undo") + 1]})); sys.exit(0)
i = sys.argv.index("--action")
a = json.loads(sys.argv[i + 1])
print(json.dumps({"ok": True,
                  "resource_name": "customers/1234567890/campaignCriteria/%s~9" % a["campaign_id"]}))
'''

def _reg_text(tmp, allow="mutate_campaign_negative", caps=None):
    caps = caps or {"actions_per_changeset": 25, "actions_per_client_day": 100,
                    "applies_per_client_day": 5, "approval_ttl_hours": 24}
    return f"""version: 1

projects:
  claude_google_ads:
    workdir: {tmp}
    read_execute:
      runner: /bin/true
      script_dir: code
      allow:
        - account_overview
    mutate_execute:
      runner: {sys.executable}
      script_dir: code
      allow:
        - {allow}
      caps:
        actions_per_changeset: {caps['actions_per_changeset']}
        actions_per_client_day: {caps['actions_per_client_day']}
        applies_per_client_day: {caps['applies_per_client_day']}
        approval_ttl_hours: {caps['approval_ttl_hours']}
"""

class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        os.environ["VAULT_ROOT"] = self.tmp
        for k, v in FULL_CRED.items():
            os.environ[k] = v
        code = os.path.join(self.tmp, "code"); os.makedirs(code)
        self.calls = os.path.join(code, "calls.jsonl")
        self.mode_file = os.path.join(code, "mode.txt")
        self.stub = os.path.join(code, "mutate_campaign_negative.py")
        with open(self.stub, "w") as f:
            f.write(STUB)
        os.chmod(self.stub, os.stat(self.stub).st_mode | stat.S_IEXEC)
        d = os.path.join(self.tmp, "_registry"); os.makedirs(d)
        self.clients = os.path.join(d, "clients.json")
        with open(self.clients, "w") as f:
            json.dump({"clients": {"acme-dental": {
                "project": "claude_google_ads", "customer_id": "1234567890",
                "status": "active"}}}, f)
        self.projects = os.path.join(self.tmp, "projects.yaml")
        with open(self.projects, "w") as f:
            f.write(_reg_text(self.tmp))
        gov = os.path.join(self.tmp, C.GOVERNANCE_DIR); os.makedirs(gov)
        with open(os.path.join(gov, C.KILL_SWITCH), "w") as f:
            f.write("enabled\n")
        self.vault = os.path.join(self.tmp, "acme-dental")

    def _actions(self, n=1):
        return [{"type": "add_campaign_negative", "campaign_id": str(22233344450 + i),
                 "keyword": f"zzz test negative {i}", "match_type": "PHRASE"} for i in range(n)]

    def _proposed(self, n=1):
        src = os.path.join(self.tmp, "in.json")
        with open(src, "w") as f:
            json.dump({"actions": self._actions(n)}, f)
        return P.propose("acme-dental", src, NOW, registry=self.clients, projects=self.projects)

    def _approved(self, n=1):
        cs = self._proposed(n)
        A.approve("acme-dental", cs["changeset_id"], "erick", NOW,
                  registry=self.clients, projects=self.projects)
        return cs

    def _calls(self):
        if not os.path.exists(self.calls):
            return []
        with open(self.calls) as f:
            return [json.loads(x) for x in f if x.strip()]

    def _mode(self, m):
        with open(self.mode_file, "w") as f:
            f.write(m)

    def _run(self, cs_id, now=NOW, undo=None):
        plan = X.build_plan("acme-dental", cs_id, now, registry=self.clients,
                            projects=self.projects, undo=undo)
        return X.apply(plan, now)

class TestHappyPath(Base):
    def test_two_actions_validate_then_apply(self):
        cs = self._approved(2)
        self.assertEqual(self._run(cs["changeset_id"]), 0)
        calls = self._calls()
        self.assertEqual(len(calls), 4)                       # 2 validate + 2 live
        self.assertTrue(all("--validate-only" in c for c in calls[:2]))
        self.assertTrue(all("--validate-only" not in c for c in calls[2:]))

    def test_log_records_resource_names(self):
        cs = self._approved(2)
        self._run(cs["changeset_id"])
        with open(C.log_path(self.vault)) as f:
            recs = [json.loads(x) for x in f if x.strip()]
        self.assertEqual(len(recs), 2)
        self.assertTrue(all(r["status"] == "applied" for r in recs))
        self.assertTrue(all(r["resource_name"].startswith("customers/1234567890/") for r in recs))
        self.assertTrue(all(r["operator"] == "erick" for r in recs))

    def test_result_and_timeline_written(self):
        cs = self._approved(1)
        self._run(cs["changeset_id"])
        self.assertTrue(os.path.exists(C.result_path(self.vault, cs["changeset_id"])))
        with open(os.path.join(self.vault, "timeline.md")) as f:
            self.assertIn("change", f.read())

class TestPreflightRefusals(Base):
    """Every refusal must exit 2 AND never spawn the mutator."""

    def _assert_refused(self, cs_id, now=NOW):
        with self.assertRaises(SystemExit) as ctx:
            self._run(cs_id, now=now)
        self.assertEqual(ctx.exception.code, 2)
        self.assertEqual(self._calls(), [])

    def test_kill_switch_absent(self):
        cs = self._approved()
        os.remove(os.path.join(self.tmp, C.GOVERNANCE_DIR, C.KILL_SWITCH))
        self._assert_refused(cs["changeset_id"])

    def test_no_approval(self):
        cs = self._proposed()
        self._assert_refused(cs["changeset_id"])

    def test_tampered_changeset_after_approval(self):
        cs = self._approved()
        with open(C.changeset_path(self.vault, cs["changeset_id"]), "ab") as f:
            f.write(b" ")
        self._assert_refused(cs["changeset_id"])

    def test_expired_approval(self):
        cs = self._approved()
        self._assert_refused(cs["changeset_id"], now=NOW + datetime.timedelta(hours=25))

    def test_offboarded_client(self):
        cs = self._approved()
        with open(self.clients, "w") as f:
            json.dump({"clients": {"acme-dental": {
                "project": "claude_google_ads", "customer_id": "1234567890",
                "status": "offboarded"}}}, f)
        self._assert_refused(cs["changeset_id"])

    def test_customer_id_mismatch_is_a_tamper_check(self):
        cs = self._approved()
        with open(self.clients, "w") as f:
            json.dump({"clients": {"acme-dental": {
                "project": "claude_google_ads", "customer_id": "9999999999",
                "status": "active"}}}, f)
        self._assert_refused(cs["changeset_id"])

    def test_daily_applies_cap(self):
        with open(self.projects, "w") as f:
            f.write(_reg_text(self.tmp, caps={"actions_per_changeset": 25,
                                              "actions_per_client_day": 100,
                                              "applies_per_client_day": 1,
                                              "approval_ttl_hours": 24}))
        first = self._approved()
        self.assertEqual(self._run(first["changeset_id"]), 0)
        os.remove(self.calls)
        second = self._approved()
        self._assert_refused(second["changeset_id"])

    def test_daily_actions_cap(self):
        with open(self.projects, "w") as f:
            f.write(_reg_text(self.tmp, caps={"actions_per_changeset": 25,
                                              "actions_per_client_day": 2,
                                              "applies_per_client_day": 5,
                                              "approval_ttl_hours": 24}))
        first = self._approved(2)
        self.assertEqual(self._run(first["changeset_id"]), 0)
        os.remove(self.calls)
        second = self._approved(1)
        self._assert_refused(second["changeset_id"])

    def test_missing_credential_var(self):
        cs = self._approved()
        del os.environ["GOOGLE_ADS_REFRESH_TOKEN"]
        self._assert_refused(cs["changeset_id"])

    def test_wrong_credential_role(self):
        cs = self._approved()
        os.environ["GOOGLE_ADS_CREDENTIAL_ROLE"] = "read"
        self._assert_refused(cs["changeset_id"])

    def test_allow_list_overlap(self):
        cs = self._approved()
        with open(self.projects, "w") as f:
            f.write(_reg_text(self.tmp, allow="account_overview"))
        self._assert_refused(cs["changeset_id"])

class TestValidateOnlyGate(Base):
    def test_validate_failure_applies_nothing(self):
        cs = self._approved(2)
        self._mode("fail_validate")
        with self.assertRaises(SystemExit) as ctx:
            self._run(cs["changeset_id"])
        self.assertEqual(ctx.exception.code, 2)
        calls = self._calls()
        self.assertTrue(all("--validate-only" in c for c in calls))   # zero live calls
        self.assertFalse(os.path.exists(C.log_path(self.vault)))

class TestPostMutationFailure(Base):
    def test_partial_apply_exits_3_and_keeps_the_record(self):
        cs = self._approved(2)
        self._mode("fail_second_live")
        with self.assertRaises(SystemExit) as ctx:
            self._run(cs["changeset_id"])
        self.assertEqual(ctx.exception.code, 3)
        with open(C.log_path(self.vault)) as f:
            recs = [json.loads(x) for x in f if x.strip()]
        self.assertEqual(len(recs), 1)                     # the one that landed is recorded
        self.assertEqual(recs[0]["status"], "applied")

if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
python3 infra/hermes-agent/bin/apply-changeset.test.py
```

Expected: FAIL — `apply-changeset.py` does not exist.

- [ ] **Step 3: Write the implementation**

Create `infra/hermes-agent/bin/apply-changeset.py`:

```python
#!/usr/bin/env python3
"""Apply an approved change-set to a client's external Google Ads account.

THE ONLY CREDENTIALED ENTRY POINT in the mutation tier. Runs in-container, invoked by
run-ads-mutate.sh, which injects a SEPARATE Standard-access write credential
per-invocation via `docker compose exec -e`. Stdlib-only; the SDK lives in the
project's pinned venv, reached through the allow-listed mutator subprocess.

Guard order is load-bearing (spec §7): every refusal happens BEFORE the credential is
used, so exit 2 is a promise that nothing was mutated. Exit 3 means at least one live
mutation landed; the audit log holds what did, and --undo can reverse it.

See docs/superpowers/specs/2026-08-12-hermes-mutation-tier-design.md
"""
import argparse, datetime, json, os, shutil, subprocess, sys, tempfile
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import changeset_lib as C
import vault_lib

CRED_VARS = ("GOOGLE_ADS_DEVELOPER_TOKEN", "GOOGLE_ADS_CLIENT_ID",
             "GOOGLE_ADS_CLIENT_SECRET", "GOOGLE_ADS_REFRESH_TOKEN",
             "GOOGLE_ADS_LOGIN_CUSTOMER_ID", "GOOGLE_ADS_CUSTOMER_ID")
SECRET_VARS = ("GOOGLE_ADS_DEVELOPER_TOKEN", "GOOGLE_ADS_CLIENT_ID",
               "GOOGLE_ADS_CLIENT_SECRET", "GOOGLE_ADS_REFRESH_TOKEN")
ROLE_VAR = "GOOGLE_ADS_CREDENTIAL_ROLE"
WRITE_ROLE = "write"

# Mirrors run-ads-report.py: the mutator gets the credentials plus a minimal benign
# runtime whitelist, and nothing else — never ANTHROPIC_API_KEY or the OpenRouter key.
_RUNTIME_ENV_KEYS = ("PATH", "HOME", "LANG", "LC_ALL", "LC_CTYPE", "TMPDIR", "TZ",
                     "SSL_CERT_FILE", "SSL_CERT_DIR", "GRPC_DEFAULT_SSL_ROOTS_FILE_PATH",
                     "REQUESTS_CA_BUNDLE")


class PostMutationError(Exception):
    """Raised for any failure AFTER at least one live mutation landed. Exits 3, never 2 —
    exit 2 must remain a guarantee that the account was not touched."""


def _refuse(msg):
    print(f"apply-changeset: {msg}", file=sys.stderr)
    raise SystemExit(2)


def _scrub(text):
    for v in SECRET_VARS:
        s = os.environ.get(v)
        if s:
            text = text.replace(s, "***")
    return text


def _child_env():
    env = {k: os.environ[k] for k in _RUNTIME_ENV_KEYS if k in os.environ}
    for v in CRED_VARS:
        env[v] = os.environ[v]
    return env


def build_plan(client, changeset_id, now, registry=None, projects=None, undo=None):
    """Guards 1-8. Returns everything apply() needs; raises SystemExit(2) on any refusal."""
    target = undo or changeset_id
    if not C.CHANGESET_ID_RE.fullmatch(target or ""):
        _refuse(f"invalid change-set id: {target!r}")

    # 2. client resolves and is active  (undo skips the kill switch, guard 1, see below)
    try:
        rec = vault_lib.resolve(client, registry)
    except (ValueError, KeyError, OSError) as e:
        _refuse(str(e))
    vault = rec["vault_path"]

    # 1. kill switch — CREATING change only; undo must stay available.
    if not undo and not C.kill_switch_ok(vault_lib.vault_root()):
        _refuse("mutation is disabled (kill switch absent or unreadable) — this is the safe default")
    if rec.get("status") != "active":
        _refuse(f"client status is {rec.get('status')!r}, not 'active'")

    projects_path = projects or C.registry_projects_path()
    try:
        cfg = C.read_mutate_execute(projects_path, rec["project"])
    except (ValueError, OSError) as e:
        _refuse(str(e))

    cs, approval, actions = None, None, []
    if undo:
        actions = _undo_targets(vault, undo)
        if not actions:
            _refuse(f"no applied, un-undone actions recorded for change-set {undo!r}")
        operator = actions[0].get("operator", "unknown")
    else:
        # 3. change-set loads and validates
        path = C.changeset_path(vault, changeset_id)
        if not os.path.isfile(path):
            _refuse(f"no change-set {changeset_id!r} for this client")
        try:
            with open(path, encoding="utf-8") as f:
                cs = json.load(f)
            C.validate_changeset(cs, cfg["caps"]["actions_per_changeset"])
        except (ValueError, json.JSONDecodeError) as e:
            _refuse(str(e))
        # 4. identity match — a tamper check, since propose supplies these fields
        if cs["client"] != rec["slug"] or cs["customer_id"] != rec["customer_id"] \
                or cs["project"] != rec["project"]:
            _refuse("change-set identity does not match the resolved client")
        if cs["customer_id"] != "".join(c for c in os.environ.get("GOOGLE_ADS_CUSTOMER_ID", "")
                                        if c.isdigit()):
            _refuse("injected GOOGLE_ADS_CUSTOMER_ID does not match the change-set's customer_id")
        # 5. approval
        try:
            approval = C.verify_approval(vault, changeset_id, C.file_digest(path), now)
        except (ValueError, OSError, json.JSONDecodeError) as e:
            _refuse(str(e))
        operator = approval["operator"]
        # 6. daily caps
        try:
            counts = C.day_counts(vault, now.strftime("%Y-%m-%d"))
        except ValueError as e:
            _refuse(str(e))
        if counts["applies"] + 1 > cfg["caps"]["applies_per_client_day"]:
            _refuse(f"daily applies cap reached ({counts['applies']}/"
                    f"{cfg['caps']['applies_per_client_day']})")
        if counts["actions"] + len(cs["actions"]) > cfg["caps"]["actions_per_client_day"]:
            _refuse(f"daily actions cap would be exceeded ({counts['actions']}+{len(cs['actions'])}"
                    f" > {cfg['caps']['actions_per_client_day']})")
        actions = cs["actions"]

    # 7. allow-list resolution + disjointness
    if len(cfg["allow"]) != 1:
        _refuse(f"mutate_execute.allow must hold exactly one entry, got {cfg['allow']}")
    name = cfg["allow"][0]
    if os.path.basename(name) != name:
        _refuse(f"mutator name must be a bare basename, got {name!r}")
    try:
        C.assert_allow_lists_disjoint(
            C.read_allow_list(projects_path, rec["project"], "read_execute"), cfg["allow"])
        workdir = C.read_workdir(projects_path, rec["project"])
    except (ValueError, OSError) as e:
        _refuse(str(e))
    script = os.path.join(workdir, cfg["script_dir"], name + ".py")
    if not os.path.isfile(cfg["runner"]):
        _refuse(f"runner interpreter not found: {cfg['runner']}")
    if not os.path.isfile(script):
        _refuse(f"mutator not found: {script}")

    # 8. credentials
    missing = [v for v in CRED_VARS if not os.environ.get(v)]
    if missing:
        _refuse(f"missing injected credential vars: {', '.join(missing)} "
                "(operator-invoked via run-ads-mutate.sh only)")
    if os.environ.get(ROLE_VAR) != WRITE_ROLE:
        _refuse(f"{ROLE_VAR} is {os.environ.get(ROLE_VAR)!r}, expected {WRITE_ROLE!r} — "
                "the mutation tier refuses the read-only credential")

    return {"vault": vault, "changeset_id": target, "runner": cfg["runner"], "script": script,
            "actions": actions, "undo": bool(undo), "operator": operator,
            "customer_id": rec["customer_id"]}


def _undo_targets(vault, changeset_id):
    """Applied actions for this change-set that have not already been undone."""
    p = C.log_path(vault)
    if not os.path.exists(p):
        return []
    applied, undone = [], set()
    with open(p, encoding="utf-8") as f:
        for n, line in enumerate(f, 1):
            if not line.strip():
                continue
            try:
                r = json.loads(line)
            except json.JSONDecodeError as e:
                _refuse(f"corrupt audit log at {p}:{n} ({e})")
            if r.get("changeset_id") != changeset_id:
                continue
            if r.get("status") == "applied":
                applied.append(r)
            elif r.get("status") == "undone":
                undone.add(r.get("resource_name"))
    return [r for r in reversed(applied) if r.get("resource_name") not in undone]


def _invoke(plan, args, scratch):
    proc = subprocess.run([plan["runner"], plan["script"]] + args,
                          cwd=scratch, env=_child_env(), capture_output=True, text=True)
    return proc.returncode, _scrub(proc.stdout), _scrub(proc.stderr)


def apply(plan, now):
    scratch = tempfile.mkdtemp(prefix="ads-mutate-")   # defense in depth: no in-tree .env nearby
    results = []
    try:
        # 9. validate_only over EVERY action, all-or-nothing
        for i, a in enumerate(plan["actions"]):
            args = (["--undo", a["resource_name"]] if plan["undo"]
                    else ["--action", json.dumps(a, sort_keys=True)]) + ["--validate-only"]
            rc, out, err = _invoke(plan, args, scratch)
            if rc != 0:
                _refuse(f"validate_only failed for action {i} — nothing applied:\n{err}")

        # 10. live, one action at a time, each logged before the next begins
        for i, a in enumerate(plan["actions"]):
            args = (["--undo", a["resource_name"]] if plan["undo"]
                    else ["--action", json.dumps(a, sort_keys=True)])
            rc, out, err = _invoke(plan, args, scratch)
            if rc != 0:
                raise PostMutationError(f"action {i} failed after {len(results)} already applied:\n{err}")
            try:
                payload = json.loads(out)
            except json.JSONDecodeError:
                raise PostMutationError(f"action {i} returned unparseable output — the mutation may "
                                        f"have landed; inspect the account:\n{out}")
            resource = payload.get("removed") if plan["undo"] else payload.get("resource_name")
            if not resource:
                raise PostMutationError(f"action {i} returned no resource name — the mutation may "
                                        f"have landed; inspect the account:\n{out}")
            rec = {"ts": now.strftime(C.ISO), "changeset_id": plan["changeset_id"],
                   "action_index": i, "type": a.get("type", "add_campaign_negative"),
                   "resource_name": resource,
                   "status": "undone" if plan["undo"] else "applied",
                   "operator": plan["operator"]}
            C.append_log(plan["vault"], rec)      # fsync'd before the next action starts
            results.append(rec)

        C._atomic_write_json(C.result_path(plan["vault"], plan["changeset_id"]),
                             {"changeset_id": plan["changeset_id"],
                              "undo": plan["undo"], "completed_at": now.strftime(C.ISO),
                              "operator": plan["operator"], "actions": results})
        verb = "undo" if plan["undo"] else "change"
        with open(os.path.join(plan["vault"], "timeline.md"), "a", encoding="utf-8") as f:
            f.write(f"- {now.strftime(C.ISO)} · {verb} · {len(results)} action(s) · "
                    f"changeset {plan['changeset_id']} · by {plan['operator']}\n")
        print(json.dumps({"ok": True, "changeset_id": plan["changeset_id"],
                          "undo": plan["undo"], "applied": len(results)}))
        return 0
    finally:
        shutil.rmtree(scratch, ignore_errors=True)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--client", required=True)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--changeset")
    g.add_argument("--undo")
    ap.add_argument("--registry")
    ap.add_argument("--projects")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)
    now = datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0)
    plan = build_plan(args.client, args.changeset, now, args.registry, args.projects, args.undo)
    if args.dry_run:
        print(f"vault:   {plan['vault']}")
        print(f"runner:  {plan['runner']}")
        print(f"script:  {plan['script']}")
        print(f"mode:    {'undo' if plan['undo'] else 'apply'}")
        print(f"actions: {len(plan['actions'])}")
        return 0
    try:
        return apply(plan, now)
    except PostMutationError as e:
        print(f"apply-changeset: {e}", file=sys.stderr)
        print("apply-changeset: EXIT 3 — at least one mutation LANDED. The audit log records "
              "what applied; reverse it with --undo.", file=sys.stderr)
        return 3


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
python3 infra/hermes-agent/bin/apply-changeset.test.py
```

Expected: `OK`. Every `TestPreflightRefusals` case must show an empty call log — that assertion, not the exit code, is what proves the credential was never used.

- [ ] **Step 5: Run the whole `bin/` suite for regressions**

```bash
cd infra/hermes-agent/bin
for t in *.test.py; do echo "== $t"; python3 "$t" || break; done
```

Expected: every suite `OK`.

- [ ] **Step 6: Commit**

```bash
git add infra/hermes-agent/bin/apply-changeset.py infra/hermes-agent/bin/apply-changeset.test.py
git commit -m "feat(hermes): apply-changeset with fail-closed guards and validate_only gate"
```

---

### Task 8: Undo path end-to-end

**Files:**
- Modify: `infra/hermes-agent/bin/apply-changeset.test.py` (append)
- Modify: `infra/hermes-agent/bin/apply-changeset.py` only if a test exposes a defect

**Interfaces:** no new symbols. Task 7 already implements `--undo`; this task proves the properties the spec claims for it and fixes whatever fails.

- [ ] **Step 1: Write the failing test**

Append to `infra/hermes-agent/bin/apply-changeset.test.py`, before the `if __name__` line:

```python
class TestUndo(Base):
    def _applied(self, n=1):
        cs = self._approved(n)
        self.assertEqual(self._run(cs["changeset_id"]), 0)
        os.remove(self.calls)
        return cs

    def test_undo_removes_each_applied_resource(self):
        cs = self._applied(2)
        self.assertEqual(self._run(cs["changeset_id"], undo=cs["changeset_id"]), 0)
        calls = self._calls()
        self.assertEqual(len(calls), 4)                        # 2 validate + 2 live
        self.assertTrue(all("--undo" in c for c in calls))

    def test_undo_appends_undone_lines(self):
        cs = self._applied(2)
        self._run(cs["changeset_id"], undo=cs["changeset_id"])
        with open(C.log_path(self.vault)) as f:
            recs = [json.loads(x) for x in f if x.strip()]
        self.assertEqual(len([r for r in recs if r["status"] == "applied"]), 2)
        self.assertEqual(len([r for r in recs if r["status"] == "undone"]), 2)

    def test_undo_works_with_kill_switch_absent(self):
        """Guards constrain creating change, never reversing it."""
        cs = self._applied(1)
        os.remove(os.path.join(self.tmp, C.GOVERNANCE_DIR, C.KILL_SWITCH))
        self.assertEqual(self._run(cs["changeset_id"], undo=cs["changeset_id"]), 0)

    def test_undo_works_with_daily_caps_exhausted(self):
        with open(self.projects, "w") as f:
            f.write(_reg_text(self.tmp, caps={"actions_per_changeset": 25,
                                              "actions_per_client_day": 1,
                                              "applies_per_client_day": 1,
                                              "approval_ttl_hours": 24}))
        cs = self._applied(1)
        self.assertEqual(self._run(cs["changeset_id"], undo=cs["changeset_id"]), 0)

    def test_second_undo_is_a_noop_refusal(self):
        cs = self._applied(1)
        self._run(cs["changeset_id"], undo=cs["changeset_id"])
        os.remove(self.calls)
        with self.assertRaises(SystemExit) as ctx:
            self._run(cs["changeset_id"], undo=cs["changeset_id"])
        self.assertEqual(ctx.exception.code, 2)
        self.assertEqual(self._calls(), [])

    def test_undo_of_unknown_changeset_refused(self):
        self._applied(1)
        with self.assertRaises(SystemExit) as ctx:
            self._run("20260812-999999-deadbeef", undo="20260812-999999-deadbeef")
        self.assertEqual(ctx.exception.code, 2)
        self.assertEqual(self._calls(), [])

    def test_undo_still_requires_credentials(self):
        cs = self._applied(1)
        del os.environ["GOOGLE_ADS_CLIENT_SECRET"]
        with self.assertRaises(SystemExit) as ctx:
            self._run(cs["changeset_id"], undo=cs["changeset_id"])
        self.assertEqual(ctx.exception.code, 2)

    def test_undo_still_requires_write_role(self):
        cs = self._applied(1)
        os.environ["GOOGLE_ADS_CREDENTIAL_ROLE"] = "read"
        with self.assertRaises(SystemExit) as ctx:
            self._run(cs["changeset_id"], undo=cs["changeset_id"])
        self.assertEqual(ctx.exception.code, 2)
```

- [ ] **Step 2: Run the tests**

```bash
python3 infra/hermes-agent/bin/apply-changeset.test.py
```

Expected: some undo tests fail on first run — most likely `test_undo_works_with_daily_caps_exhausted` or the `_undo_targets` ordering. Read each failure and fix `apply-changeset.py` so the behaviour matches the spec: undo skips only the kill switch and the daily caps, and keeps every other guard.

- [ ] **Step 3: Fix `apply-changeset.py` until all undo tests pass**

Do not weaken a test to make it pass. If a test looks wrong, re-read spec §7.1 and fix whichever side is actually wrong.

- [ ] **Step 4: Run all suites**

```bash
cd infra/hermes-agent/bin
for t in *.test.py; do echo "== $t"; python3 "$t" || break; done
```

Expected: every suite `OK`.

- [ ] **Step 5: Commit**

```bash
git add infra/hermes-agent/bin/apply-changeset.py infra/hermes-agent/bin/apply-changeset.test.py
git commit -m "test(hermes): prove undo bypasses only the creating-change guards"
```

---

### Task 9: Host wrapper, write credential, gitignore, and docs

**Files:**
- Create: `infra/hermes-agent/run-ads-mutate.sh`, `infra/hermes-agent/.env.gaw.example`
- Modify: `.gitignore` (repo root), `infra/hermes-agent/README.md`

**Interfaces:**
- Consumes: `apply-changeset.py` CLI from Task 7.
- Produces: `./run-ads-mutate.sh --client <slug> (--changeset <id> | --undo <id>) [--dry-run]`.

- [ ] **Step 1: Add `.env.gaw` to `.gitignore` FIRST**

Before creating any credential file. In the repo-root `.gitignore`, next to the existing `infra/hermes-agent/.env.ga` line:

```
infra/hermes-agent/.env.gaw
```

Verify:

```bash
git check-ignore -v infra/hermes-agent/.env.gaw
```

Expected: a line naming `.gitignore` and the pattern. If it prints nothing, stop — the credential would be committable.

- [ ] **Step 2: Create the credential template**

Create `infra/hermes-agent/.env.gaw.example`:

```
# STANDARD-ACCESS (WRITE) Google Ads credential for the Hermes mutation tier.
# Copy to .env.gaw and fill in. GITIGNORED. NOT loaded by docker-compose env_file —
# it is PARSED (not sourced) by run-ads-mutate.sh and injected per-invocation via
# `exec -e`, so it never enters the gateway/agent env and shell metacharacters in a
# value stay inert. Customer IDs WITHOUT dashes.
#
# CRITICAL: this credential CAN mutate the account. It is deliberately SEPARATE from
# the read-only .env.ga, whose refresh token must stay read-only so every other path
# keeps its platform-level backstop. Never copy a token between the two files.
#
# The role marker is required: apply-changeset.py refuses unless it reads exactly
# "write", so invoking the mutation path with the read-only credential fails early
# and legibly instead of failing opaquely at Google.
GOOGLE_ADS_CREDENTIAL_ROLE=write
GOOGLE_ADS_DEVELOPER_TOKEN=
GOOGLE_ADS_CLIENT_ID=
GOOGLE_ADS_CLIENT_SECRET=
GOOGLE_ADS_REFRESH_TOKEN=
GOOGLE_ADS_LOGIN_CUSTOMER_ID=
GOOGLE_ADS_CUSTOMER_ID=
```

- [ ] **Step 3: Create the host wrapper**

Create `infra/hermes-agent/run-ads-mutate.sh` (mirrors `run-ads-report.sh` exactly, with the write credential file and the role variable added):

```sh
#!/bin/sh
# Host-side wrapper: inject the STANDARD-ACCESS (WRITE) Google Ads credential
# per-invocation and run the applier inside the container. The credential lives in
# the gitignored .env.gaw (NOT loaded by docker-compose env_file, NOT in the gateway
# env) — PARSED here (not sourced) and passed via `docker compose exec -e`, so it
# reaches ONLY this exec'd process. Mirrors run-ads-report.sh, which does the same
# for the READ-ONLY credential; the two files are deliberately separate.
set -eu
here="$(cd "$(dirname "$0")" && pwd)"
if [ ! -f "$here/.env.gaw" ]; then
  echo "run-ads-mutate: $here/.env.gaw not found — copy .env.gaw.example and fill in the WRITE credential" >&2
  exit 1
fi
# Parse .env.gaw as DATA (not shell code): read each line raw, split on the first '=',
# assign the value LITERALLY. `export "$k=$v"` performs no command substitution on the
# already-expanded value, so `$(...)`/backticks in a secret stay inert.
while IFS= read -r _line || [ -n "$_line" ]; do
  case "$_line" in
    ''|'#'*) continue ;;
    GOOGLE_ADS_*=*) : ;;
    *) continue ;;
  esac
  _key=${_line%%=*}
  _val=${_line#*=}
  case "$_val" in
    \"*\") _val=${_val#\"}; _val=${_val%\"} ;;
    \'*\') _val=${_val#\'}; _val=${_val%\'} ;;
  esac
  export "$_key=$_val"
done < "$here/.env.gaw"
if [ "${GOOGLE_ADS_CREDENTIAL_ROLE:-}" != "write" ]; then
  echo "run-ads-mutate: .env.gaw must set GOOGLE_ADS_CREDENTIAL_ROLE=write (got '${GOOGLE_ADS_CREDENTIAL_ROLE:-}')" >&2
  exit 1
fi
exec docker compose -f "$here/docker-compose.yml" exec \
  -e GOOGLE_ADS_DEVELOPER_TOKEN -e GOOGLE_ADS_CLIENT_ID -e GOOGLE_ADS_CLIENT_SECRET \
  -e GOOGLE_ADS_REFRESH_TOKEN -e GOOGLE_ADS_LOGIN_CUSTOMER_ID -e GOOGLE_ADS_CUSTOMER_ID \
  -e GOOGLE_ADS_CREDENTIAL_ROLE \
  -T hermes-agent python3 /opt/cc-bin/apply-changeset.py "$@"
```

```bash
chmod +x infra/hermes-agent/run-ads-mutate.sh
sh -n infra/hermes-agent/run-ads-mutate.sh   # syntax check; expect no output
```

- [ ] **Step 4: Verify the wrapper refuses without a credential file**

```bash
cd infra/hermes-agent && ./run-ads-mutate.sh --client acme-dental --changeset x; echo "exit=$?"
```

Expected: the `.env.gaw not found` message and `exit=1`. (Do not create a real `.env.gaw` yet — that happens in Task 10 with the real credential.)

- [ ] **Step 5: Document it in the README**

Append a `## Mutation tier — applying approved changes (Task 2)` section to `infra/hermes-agent/README.md`, after the two-tier section. It must state: the three commands and their privilege split; that this is the first path without the read-only backstop; the guard order; the four caps and where they are configured; exit codes 0/1/2/3 and what exit 2 guarantees; that undo bypasses only the kill switch and daily caps; and the credential separation between `.env.ga` and `.env.gaw`. **Client-agnostic — use `<slug>` placeholders, never a real client name.** Verify before committing:

```bash
cd infra/hermes-agent && python3 - <<'PY'
import json, sys
# Read the roster from the GITIGNORED registry. Never hardcode a client name in a
# tracked file -- not even inside the check that looks for client names.
slugs = list(json.load(open("data/vaults/_registry/clients.json"))["clients"])
src = open("README.md", encoding="utf-8").read().lower()
hits = [s for s in slugs if s.lower() in src]
print("client-name hits:", hits or "none")
sys.exit(1 if hits else 0)
PY
```

Expected: `client-name hits: none`, exit 0.

- [ ] **Step 6: Commit, then push the ads-repo work**

```bash
git add infra/hermes-agent/run-ads-mutate.sh infra/hermes-agent/.env.gaw.example \
        infra/hermes-agent/README.md .gitignore
git commit -m "feat(hermes): run-ads-mutate host wrapper, write-credential template, docs"
```

Then push the separate repo (per the brainstorming decision — the 2 pre-existing commits ride along):

```bash
cd /Users/ericksicard/projects/claude-google-ads
git log --oneline origin/main..HEAD    # expect exactly 3: audit_data untrack, zero-spend guard, mutator
git push origin HEAD
```

---

### Task 10: Live verification gate (CONTROLLER-RUN)

**This task is not for a subagent.** It uses a real write credential against a real account. The controller runs it with the operator present.

**Preconditions the operator must supply:** a Standard-access refresh token for a Google account with write access to the target account, distinct from the read-only one, written into `infra/hermes-agent/.env.gaw`.

- [ ] **Step 1: Rebuild and confirm mounts**

```bash
cd infra/hermes-agent
docker compose up -d --build
docker compose exec -T hermes-agent sh -c 'ls -ld /opt/data/vaults; touch /projects/claude_google_ads/.probe 2>&1 | head -1'
```

Expected: `/opt/data/vaults` exists; the touch fails with a read-only filesystem error. **If the touch succeeds, stop — the `:ro` guarantee is broken.**

- [ ] **Step 2: Re-verify the target campaigns are PAUSED (binding condition 1)**

```bash
./run-ads-report.sh --project claude_google_ads --report account_overview --customer <CID>
```

Read the produced report. **Every campaign must be PAUSED.** If any is enabled, stop and consult the operator — the gate's zero-impact premise no longer holds.

- [ ] **Step 3: Prove the read-only credential still refuses a mutate (positive control)**

```bash
docker compose exec \
  -e GOOGLE_ADS_DEVELOPER_TOKEN -e GOOGLE_ADS_CLIENT_ID -e GOOGLE_ADS_CLIENT_SECRET \
  -e GOOGLE_ADS_REFRESH_TOKEN -e GOOGLE_ADS_LOGIN_CUSTOMER_ID -e GOOGLE_ADS_CUSTOMER_ID \
  -T hermes-agent /opt/ads-venv/bin/python3 \
  /projects/claude_google_ads/code/mutate_campaign_negative.py \
  --action '{"type":"add_campaign_negative","campaign_id":"<CAMPAIGN>","keyword":"zzz hermes gate probe","match_type":"PHRASE"}' \
  --validate-only
```

with the **read-only** values exported from `.env.ga`. Expected: exit 2, `ACTION_NOT_PERMITTED`. Record the exact message. **If this succeeds, stop — `.env.ga` is not read-only and Inc-3's backstop has silently lapsed.**

- [ ] **Step 4: Prove the two refresh tokens differ**

```bash
cd infra/hermes-agent
a=$(grep '^GOOGLE_ADS_REFRESH_TOKEN=' .env.ga  | cut -d= -f2- | shasum | cut -c1-12)
b=$(grep '^GOOGLE_ADS_REFRESH_TOKEN=' .env.gaw | cut -d= -f2- | shasum | cut -c1-12)
[ "$a" != "$b" ] && echo "DISTINCT ok" || echo "IDENTICAL — STOP"
```

Expected: `DISTINCT ok`. Only the truncated hashes are ever printed, never the tokens.

- [ ] **Step 5: Prove the read path cannot reach the mutator**

```bash
./run-ads-report.sh --project claude_google_ads --report mutate_campaign_negative
```

Expected: non-zero exit with `not in read_execute allow-list ... readers only; mutators are never allow-listed`, before any credential use.

- [ ] **Step 6: Enable mutation and propose the synthetic change-set**

```bash
cd infra/hermes-agent
mkdir -p data/vaults/_governance && echo enabled > data/vaults/_governance/mutation-enabled
cat > /tmp/gate-actions.json <<'JSON'
{"actions":[{"type":"add_campaign_negative","campaign_id":"<CAMPAIGN>",
             "keyword":"zzz hermes gate probe","match_type":"PHRASE"}]}
JSON
VAULT_ROOT="$PWD/data/vaults" python3 bin/propose-changeset.py --client <slug> --from /tmp/gate-actions.json
```

Expected: prints the change-set path. The keyword is deliberately synthetic and would never match real traffic.

- [ ] **Step 7: Prove an unapproved change-set is refused**

```bash
./run-ads-mutate.sh --client <slug> --changeset <ID>; echo "exit=$?"
```

Expected: `exit=2`, "no approval record". Nothing reached the account.

- [ ] **Step 8: Approve, then dry-run**

```bash
VAULT_ROOT="$PWD/data/vaults" python3 bin/approve-changeset.py --client <slug> --changeset <ID> --operator <name>
./run-ads-mutate.sh --client <slug> --changeset <ID> --dry-run
```

Expected: approval prints an expiry 24h out; the dry run prints the resolved runner, script, mode `apply`, and 1 action.

- [ ] **Step 9: Prove tamper detection on the real artifact**

```bash
printf ' ' >> data/vaults/<slug>/changes/<ID>.json
./run-ads-mutate.sh --client <slug> --changeset <ID>; echo "exit=$?"
```

Expected: `exit=2`, "modified after approval". Then restore by re-proposing and re-approving a fresh change-set (do not hand-edit the file back).

- [ ] **Step 10: THE MOMENT — apply for real**

```bash
./run-ads-mutate.sh --client <slug> --changeset <ID2>; echo "exit=$?"
```

Expected: `exit=0` and a JSON summary. Internally this ran `validate_only` first — the same call that returned `ACTION_NOT_PERMITTED` in Step 3 now succeeds, because the credential changed and nothing else did.

- [ ] **Step 11: Verify the criterion is present in the account**

```bash
./run-ads-report.sh --project claude_google_ads --report audit_analyze --customer <CID>
```

Confirm the synthetic negative appears. Also confirm the audit log:

```bash
cat data/vaults/<slug>/changes/log.jsonl
```

Expected: one `applied` line carrying the real `resource_name`.

- [ ] **Step 12: UNDO and verify absence (binding condition 3)**

```bash
./run-ads-mutate.sh --client <slug> --undo <ID2>; echo "exit=$?"
./run-ads-report.sh --project claude_google_ads --report audit_analyze --customer <CID>
```

Expected: `exit=0`; the synthetic negative is gone; `log.jsonl` now holds a matching `undone` line. **The account is as found.**

- [ ] **Step 13: Disable mutation again**

```bash
rm infra/hermes-agent/data/vaults/_governance/mutation-enabled
./run-ads-mutate.sh --client <slug> --changeset <ID2>; echo "exit=$?"
```

Expected: `exit=2`, kill-switch message. Leave the switch **off** at rest.

- [ ] **Step 14: Run the §7 assertions**

```bash
cd infra/hermes-agent
# write confinement: only the one client's vault changed
find data/vaults -newermt '-2 hours' -type f | grep -v '^data/vaults/<slug>/' | grep -v _governance; echo "---"
# credential scan: no real secret in vault, reports, or logs
for v in $(grep -h '^GOOGLE_ADS_' .env.ga .env.gaw | cut -d= -f2- | sort -u); do
  [ -n "$v" ] && grep -rlF "$v" data/vaults data/reports 2>/dev/null
done; echo "--- (expect no hits)"
docker compose logs hermes-agent 2>&1 | grep -cF "$(grep '^GOOGLE_ADS_REFRESH_TOKEN=' .env.gaw | cut -d= -f2-)"
# :ro integrity
git -C ../../../claude-google-ads status --short
# no client data in git
cd /Users/ericksicard/Projects/claude_code && git status --short && git grep -il "<slug>" -- . | grep -v '^\.superpowers/'
```

Expected: no stray vault writes; zero credential hits; `0` from the log grep; the ads repo tree unchanged except its own pre-existing WIP; no client slug anywhere in tracked files.

- [ ] **Step 15: Full regression**

```bash
cd /Users/ericksicard/Projects/claude_code
node scripts/run-all-tests.js
cd infra/hermes-agent/bin && for t in *.test.py; do echo "== $t"; python3 "$t" || break; done
```

Expected: the Node suite green and every `bin/` suite `OK`.

- [ ] **Step 16: Record the gate in the SDD ledger and commit**

Write the outcome to `.superpowers/sdd/2026-08-12-hermes-mutation-tier/progress.md` — every step's real result, any bugs the gate surfaced, and the exact `ACTION_NOT_PERMITTED` message from Step 3 next to the Step 10 success. **Meta only: no client name, account id, or campaign id.**

```bash
git add -A infra/hermes-agent docs
git commit -m "feat(hermes): mutation tier verified live — apply and undo on a paused account"
```

---

## Post-plan: whole-branch review

After Task 10, run the whole-branch review per `superpowers:requesting-code-review` across `main..feat/hermes-mutation-tier`, plus a **separate review pass** for the `claude-google-ads` commit (it sits outside this branch's diff). The review must confirm every guarantee in spec §10 still holds, with particular attention to:

- exit 2 genuinely implies no mutation, on every path
- the write credential never appears in `.env`, `.env.ga`, the gateway env, or any log
- no client name, account id, or campaign id in any tracked file in either repo
- the Inc-3 read path is byte-for-byte unchanged in behaviour
