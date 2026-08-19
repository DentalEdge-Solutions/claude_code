# Hermes Runtime Boundary Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make every credential and every piece of mutation-governance state unreachable from the container Hermes runs in, without changing what the operator's existing mutation rail does.

**Architecture:** Governance state (kill switch, client registry, approvals, byte-exact approved change-set snapshots, audit log) moves out of the read-write `data/` volume into a host-owned governance store that the gateway container does not mount. `apply-changeset.py` stops running in the gateway container and runs in a one-shot `ads-mutator` container that mounts only what it needs. Credential files are masked out of the project mounts, declared per project in the registry and enforced by an invariant test.

**Tech Stack:** Python 3 stdlib only (no third-party imports in `bin/`), POSIX `sh`, Docker Compose. Tests are `unittest` suites named `*.test.py` under `infra/hermes-agent/bin/`, discovered by `bin/run-bin-tests.sh`.

**Spec:** `docs/superpowers/specs/2026-08-19-hermes-mutation-syscall-design.md`

## Global Constraints

- **`python3`, never `python`.** A bare `python` does not exist in this environment and its "command not found" is a shell error that has previously been mistaken for a failing test.
- **Stdlib only** in `infra/hermes-agent/bin/`. The Google Ads SDK is reached only through the allow-listed mutator subprocess, run with the pinned venv at `/opt/ads-venv/bin/python3`.
- **Never print, log, or commit a credential value.** Compare by sha12 using the bare convention: `printf '%s' "$v" | shasum | cut -c1-12`.
- **No client names, account ids, campaign ids, metrics, or drafts** in any tracked file, test, fixture, or commit message. Test fixtures use invented slugs like `acme-dental` and invented digits, matching the existing suites.
- **`main` is protected.** All work lands on a branch via PR. Never push to `main`.
- **Mutation stays DISABLED at rest.** The kill switch file must be absent when you finish. Do not create it except inside a verification step that removes it again.
- **Only `brain-promote.js --approve` may write `.project-brain/canon/`.** Nothing in this plan touches it.
- **Run after every task:** `infra/hermes-agent/bin/run-bin-tests.sh` — and **confirm the suite count changed** when you add a suite, not merely that it reports OK. A stray mid-file `unittest.main()` has previously caused new tests to never run while appearing to pass.
- **`cmd | head` takes its exit status from `head`.** Capture `rc=$?` from an unpiped command.
- **Shell globs skip dotfiles** — `*.bak-*` will not match `.env.gaw.bak-…`.

---

## File Structure

**Created**

| File | Responsibility |
|---|---|
| `infra/hermes-agent/bin/governance_lib.py` | Sole path contract for the governance store. Depends on nothing else in `bin/`, so it can own the shared regexes. |
| `infra/hermes-agent/bin/governance_lib.test.py` | Suite for the above. |
| `infra/hermes-agent/bin/migrate-governance.py` | One-shot, idempotent, count-verified migration of state out of the vault. |
| `infra/hermes-agent/bin/migrate-governance.test.py` | Suite for the above. |
| `infra/hermes-agent/bin/persist-run-record.py` | Host-side: reads the executor's stdout, writes `result.json` + appends `timeline.md` into the vault. Reused by the broker in Plan 2. |
| `infra/hermes-agent/bin/persist-run-record.test.py` | Suite for the above. |
| `infra/hermes-agent/masks/empty` | An empty tracked file, used as a bind source to mask a single secret-bearing file inside a project mount. |

**Modified**

| File | Change |
|---|---|
| `bin/changeset_lib.py` | Kill switch, approvals, snapshots, and audit log addressed by client **slug** against the governance root instead of by vault path; adds `read_mask_paths`. |
| `bin/vault_lib.py` | Client registry read from the governance store; `vault_path` unchanged. |
| `bin/approve-changeset.py` | Writes the approval **and** a byte-exact snapshot of the reviewed change-set. |
| `bin/apply-changeset.py` | Executes from the snapshot; emits a machine-readable result line on stdout; no longer writes into the vault. |
| `bin/audit-credential-access.py` | Unchanged logic; moved onto the isolated service by the compose change. |
| `bin/registry-invariants.test.py` | New invariant: every declared `mask_paths` entry has a matching compose mount, plus a guard that the reader is not blind. |
| `registry/projects.yaml` | New per-project `mask_paths` declaration. |
| `docker-compose.yml` | New `ads-mutator` and `ads-credential-audit` one-shot services; credential masks on the project mounts. |
| `run-ads-mutate.sh` | Targets the one-shot service instead of `exec` into the gateway; pipes the result through `persist-run-record.py`. |
| `audit-credential-access.sh` | Targets the one-shot service. |
| `README.md` | Corrects the credential-isolation claim; documents the governance store. |

---

## Task 1: The governance store path contract

**Files:**
- Create: `infra/hermes-agent/bin/governance_lib.py`
- Test: `infra/hermes-agent/bin/governance_lib.test.py`

**Interfaces:**
- Consumes: nothing. This module is the bottom of the dependency graph deliberately — `changeset_lib` and `vault_lib` will import their shared regexes from here rather than keeping duplicates.
- Produces: `governance_root()`, `kill_switch_path(root=None)`, `clients_registry_path(root=None)`, `approvals_dir(slug, root=None)`, `approval_path(slug, cid, root=None)`, `snapshot_path(slug, cid, root=None)`, `log_path(slug, root=None)`, `seen_path(slug, root=None)`, and the constants `SLUG_RE`, `CHANGESET_ID_RE`, `DEFAULT_ROOT`.

- [ ] **Step 1: Write the failing test**

Create `infra/hermes-agent/bin/governance_lib.test.py`:

```python
import os, sys, unittest
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import governance_lib as G


class TestRoot(unittest.TestCase):
    def setUp(self):
        self._saved = os.environ.pop("HERMES_GOVERNANCE_ROOT", None)

    def tearDown(self):
        os.environ.pop("HERMES_GOVERNANCE_ROOT", None)
        if self._saved is not None:
            os.environ["HERMES_GOVERNANCE_ROOT"] = self._saved

    def test_default_is_the_container_path(self):
        self.assertEqual(G.governance_root(), "/opt/governance")

    def test_env_overrides_for_host_callers(self):
        os.environ["HERMES_GOVERNANCE_ROOT"] = "/tmp/gov"
        self.assertEqual(G.governance_root(), "/tmp/gov")


class TestPaths(unittest.TestCase):
    R = "/tmp/gov"

    def test_kill_switch_path(self):
        self.assertEqual(G.kill_switch_path(self.R),
                         "/tmp/gov/control/mutation-enabled")

    def test_clients_registry_path(self):
        self.assertEqual(G.clients_registry_path(self.R),
                         "/tmp/gov/registry/clients.json")

    def test_approval_and_snapshot_are_siblings(self):
        cid = "20260812-101500-abcd1234"
        self.assertEqual(G.approval_path("acme-dental", cid, self.R),
                         "/tmp/gov/approvals/acme-dental/%s.approval.json" % cid)
        self.assertEqual(G.snapshot_path("acme-dental", cid, self.R),
                         "/tmp/gov/approvals/acme-dental/%s.changeset.json" % cid)

    def test_log_and_seen_paths(self):
        self.assertEqual(G.log_path("acme-dental", self.R),
                         "/tmp/gov/log/acme-dental.jsonl")
        self.assertEqual(G.seen_path("acme-dental", self.R),
                         "/tmp/gov/seen/acme-dental.jsonl")


class TestValidation(unittest.TestCase):
    """A path helper that accepts junk is a path-traversal primitive. These are the
    controls: each must REFUSE, and the valid case above proves the check is not
    simply rejecting everything."""

    def test_bad_slugs_refused(self):
        for bad in ["", "../etc", "Acme", "a/b", "-lead", "x" * 65, None, 7]:
            with self.assertRaises(ValueError):
                G.approvals_dir(bad, self.R if hasattr(self, "R") else "/tmp/gov")

    def test_bad_changeset_ids_refused(self):
        for bad in ["", "../x", "20260812-101500-ABCD1234", "20260812-101500-abcd123",
                    "2026081-101500-abcd1234", None, 7]:
            with self.assertRaises(ValueError):
                G.approval_path("acme-dental", bad, "/tmp/gov")

    def test_slug_with_trailing_newline_refused(self):
        with self.assertRaises(ValueError):
            G.log_path("acme-dental\n", "/tmp/gov")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 infra/hermes-agent/bin/governance_lib.test.py`
Expected: FAIL with `ModuleNotFoundError: No module named 'governance_lib'`

- [ ] **Step 3: Write minimal implementation**

Create `infra/hermes-agent/bin/governance_lib.py`:

```python
#!/usr/bin/env python3
"""Path contract for the host-owned governance store. Stdlib-only.

Everything the mutation guards TRUST lives here, and nothing Hermes can write does.
The gateway container does not mount this tree at all. The one-shot executor mounts
approvals/, control/ and registry/ READ-ONLY and log/ + seen/ read-write.

This module is deliberately the bottom of the dependency graph — it imports nothing
from bin/ — so it can own the shared identifier regexes instead of leaving duplicates
in changeset_lib and vault_lib to drift apart.

Root resolution mirrors vault_lib.vault_root(): a container default that host callers
override with HERMES_GOVERNANCE_ROOT.
"""
import os, re

DEFAULT_ROOT = "/opt/governance"

SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
CHANGESET_ID_RE = re.compile(r"^[0-9]{8}-[0-9]{6}-[0-9a-f]{8}$")


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


def seen_path(slug, root=None):
    return os.path.join(_root(root), "seen", "%s.jsonl" % _slug(slug))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 infra/hermes-agent/bin/governance_lib.test.py`
Expected: PASS, `OK`

- [ ] **Step 5: Confirm the runner discovers the new suite**

Run: `infra/hermes-agent/bin/run-bin-tests.sh`
Expected: the trailing `hermes bin: N/N suites passed` line shows **N one higher than before this task**. If N is unchanged, the suite is not being discovered — fix that before continuing; a suite that never runs is worse than one that fails.

- [ ] **Step 6: Commit**

```bash
git add infra/hermes-agent/bin/governance_lib.py infra/hermes-agent/bin/governance_lib.test.py
git commit -m "feat(hermes): add the governance store path contract"
```

---

## Task 2: Move the kill switch to the governance store

**Files:**
- Modify: `infra/hermes-agent/bin/changeset_lib.py:246-265`
- Modify: `infra/hermes-agent/bin/apply-changeset.py:77`
- Test: `infra/hermes-agent/bin/changeset_lib.test.py`

**Interfaces:**
- Consumes: `governance_lib.kill_switch_path(root=None)` from Task 1.
- Produces: `changeset_lib.kill_switch_ok(root=None)` — signature changes from `kill_switch_ok(vault_root=None)`. The safe-state semantics are unchanged: absent, unreadable, or not a regular file all return `False`, and it never raises.

- [ ] **Step 1: Write the failing test**

Append to `infra/hermes-agent/bin/changeset_lib.test.py`, **above** the trailing `if __name__ == "__main__":` block — never below it, or the file's own `unittest.main()` runs before your class is defined and the tests silently never execute:

```python
class TestKillSwitchInGovernanceStore(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="gov-")
        os.makedirs(os.path.join(self.root, "control"))
        self.addCleanup(shutil.rmtree, self.root, True)

    def _switch(self):
        return os.path.join(self.root, "control", "mutation-enabled")

    def test_absent_means_disabled(self):
        self.assertFalse(C.kill_switch_ok(self.root))

    def test_present_and_readable_means_enabled(self):
        open(self._switch(), "w").close()
        self.assertTrue(C.kill_switch_ok(self.root))

    def test_directory_in_its_place_means_disabled(self):
        os.makedirs(self._switch())
        self.assertFalse(C.kill_switch_ok(self.root))

    def test_unreadable_means_disabled(self):
        open(self._switch(), "w").close()
        os.chmod(self._switch(), 0o000)
        try:
            self.assertFalse(C.kill_switch_ok(self.root))
        finally:
            os.chmod(self._switch(), 0o600)

    def test_it_no_longer_reads_the_vault_location(self):
        """The control that proves the move actually happened: a switch at the OLD
        vault path must NOT enable mutation."""
        vault_root = tempfile.mkdtemp(prefix="vault-")
        self.addCleanup(shutil.rmtree, vault_root, True)
        os.makedirs(os.path.join(vault_root, "_governance"))
        open(os.path.join(vault_root, "_governance", "mutation-enabled"), "w").close()
        self.assertFalse(C.kill_switch_ok(self.root))
```

Ensure `tempfile` and `shutil` are imported at the top of the file; add them to the existing import line if absent.

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 infra/hermes-agent/bin/changeset_lib.test.py -v 2>&1 | tail -20`
Expected: FAIL — `kill_switch_ok` still resolves `<root>/_governance/mutation-enabled`, so `test_present_and_readable_means_enabled` fails.

- [ ] **Step 3: Write minimal implementation**

In `changeset_lib.py`, delete the `GOVERNANCE_DIR` and `KILL_SWITCH` constants and replace `kill_switch_ok` with:

```python
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
```

Add `import governance_lib` to the module's imports. In `apply-changeset.py:77`, change the call to drop the vault argument:

```python
        if not undo and not C.kill_switch_ok():
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `infra/hermes-agent/bin/run-bin-tests.sh`
Expected: all suites pass. `apply-changeset.test.py` must pass unchanged — if it fails, it was asserting the old vault location and its fixture needs the same move, which is a real part of this task rather than a test to weaken.

- [ ] **Step 5: Commit**

```bash
git add infra/hermes-agent/bin/changeset_lib.py infra/hermes-agent/bin/changeset_lib.test.py infra/hermes-agent/bin/apply-changeset.py
git commit -m "feat(hermes): read the kill switch from the governance store"
```

---

## Task 3: Move the client registry to the governance store

**Files:**
- Modify: `infra/hermes-agent/bin/vault_lib.py:14-18`
- Test: `infra/hermes-agent/bin/vault_lib.test.py`

**Interfaces:**
- Consumes: `governance_lib.clients_registry_path(root=None)`, `governance_lib.SLUG_RE`.
- Produces: `vault_lib.registry_path()` now resolves the governance store. `vault_lib.vault_root()` and the `vault_path` field are **unchanged** — reports and results stay in the vault, where Hermes can read them.

- [ ] **Step 1: Write the failing test**

Append to `infra/hermes-agent/bin/vault_lib.test.py`, above the trailing `unittest.main()` block:

```python
class TestRegistryLivesInGovernanceStore(unittest.TestCase):
    def setUp(self):
        self.gov = tempfile.mkdtemp(prefix="gov-")
        self.vault = tempfile.mkdtemp(prefix="vault-")
        self.addCleanup(shutil.rmtree, self.gov, True)
        self.addCleanup(shutil.rmtree, self.vault, True)
        os.makedirs(os.path.join(self.gov, "registry"))
        os.environ["HERMES_GOVERNANCE_ROOT"] = self.gov
        os.environ["VAULT_ROOT"] = self.vault
        self.addCleanup(os.environ.pop, "HERMES_GOVERNANCE_ROOT", None)
        self.addCleanup(os.environ.pop, "VAULT_ROOT", None)
        with open(os.path.join(self.gov, "registry", "clients.json"), "w") as f:
            json.dump({"clients": {"acme-dental": {
                "customer_id": "1234567890", "project": "claude_google_ads",
                "status": "active"}}}, f)

    def test_registry_path_points_at_the_governance_store(self):
        self.assertEqual(vault_lib.registry_path(),
                         os.path.join(self.gov, "registry", "clients.json"))

    def test_resolve_reads_it(self):
        rec = vault_lib.resolve("acme-dental")
        self.assertEqual(rec["customer_id"], "1234567890")

    def test_vault_path_still_points_at_the_vault(self):
        """The vault is NOT being emptied — results and reports stay readable by Hermes."""
        rec = vault_lib.resolve("acme-dental")
        self.assertEqual(rec["vault_path"], os.path.join(self.vault, "acme-dental"))

    def test_a_registry_at_the_old_vault_location_is_not_read(self):
        """Control: writing the old path must NOT satisfy resolve."""
        os.makedirs(os.path.join(self.vault, "_registry"))
        with open(os.path.join(self.vault, "_registry", "clients.json"), "w") as f:
            json.dump({"clients": {"other-clinic": {
                "customer_id": "9999999999", "project": "claude_google_ads",
                "status": "active"}}}, f)
        with self.assertRaises(KeyError):
            vault_lib.resolve("other-clinic")
```

Ensure `json`, `tempfile`, and `shutil` are imported at the top of the file.

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 infra/hermes-agent/bin/vault_lib.test.py -v 2>&1 | tail -20`
Expected: FAIL — `registry_path()` still returns `<VAULT_ROOT>/_registry/clients.json`.

- [ ] **Step 3: Write minimal implementation**

In `vault_lib.py`, add `import governance_lib`, replace the `SLUG_RE` definition with a re-export, and repoint `registry_path`:

```python
SLUG_RE = governance_lib.SLUG_RE      # one definition, shared, so the two cannot drift

def registry_path():
    """The client registry is CLIENT-PRIVATE and moved into the host-owned governance
    store on 2026-08-19. It was previously under VAULT_ROOT, which is the container's
    one read-write mount — meaning Hermes could flip a dormant client to 'active'."""
    return governance_lib.clients_registry_path()
```

Leave `vault_root()` exactly as it is.

- [ ] **Step 4: Run tests to verify they pass**

Run: `infra/hermes-agent/bin/run-bin-tests.sh`
Expected: all suites pass.

- [ ] **Step 5: Commit**

```bash
git add infra/hermes-agent/bin/vault_lib.py infra/hermes-agent/bin/vault_lib.test.py
git commit -m "feat(hermes): read the client registry from the governance store"
```

---

## Task 4: Approvals and byte-exact snapshots

**Files:**
- Modify: `infra/hermes-agent/bin/changeset_lib.py:276-278, 339-390`
- Modify: `infra/hermes-agent/bin/approve-changeset.py:14-31`
- Modify: `infra/hermes-agent/bin/apply-changeset.py:104-124`
- Test: `infra/hermes-agent/bin/changeset_lib.test.py`, `infra/hermes-agent/bin/approve-changeset.test.py`

**Interfaces:**
- Consumes: `governance_lib.approval_path(slug, cid, root=None)`, `governance_lib.snapshot_path(slug, cid, root=None)`, `governance_lib.approvals_dir(slug, root=None)`.
- Produces:
  - `changeset_lib.write_approval(slug, cid, digest, operator, now, ttl_hours)` — takes a **slug**, not a vault path.
  - `changeset_lib.write_snapshot(slug, cid, src_path)` → returns the sha256 of the bytes written.
  - `changeset_lib.verify_approval(slug, cid, digest, now)` — additionally raises `ValueError` if the record carries `reserved_at`.

Rationale (spec §7): `apply` must execute the bytes a human reviewed, not a copy Hermes can still reach. Hashing a writable file leaves a draft→review→swap race; copying the reviewed bytes somewhere Hermes cannot write closes it.

- [ ] **Step 1: Write the failing test**

Append to `infra/hermes-agent/bin/changeset_lib.test.py`, above the trailing `unittest.main()`:

```python
class TestApprovalSnapshot(unittest.TestCase):
    CID = "20260812-101500-abcd1234"

    def setUp(self):
        self.gov = tempfile.mkdtemp(prefix="gov-")
        self.addCleanup(shutil.rmtree, self.gov, True)
        os.environ["HERMES_GOVERNANCE_ROOT"] = self.gov
        self.addCleanup(os.environ.pop, "HERMES_GOVERNANCE_ROOT", None)
        self.src = os.path.join(self.gov, "draft.json")
        with open(self.src, "w") as f:
            f.write('{"actions": []}')

    def test_snapshot_is_byte_identical(self):
        digest = C.write_snapshot("acme-dental", self.CID, self.src)
        with open(G.snapshot_path("acme-dental", self.CID)) as f:
            self.assertEqual(f.read(), '{"actions": []}')
        self.assertEqual(digest, C.file_digest(self.src))

    def test_editing_the_source_afterwards_does_not_change_the_snapshot(self):
        """This is the race the snapshot exists to close."""
        C.write_snapshot("acme-dental", self.CID, self.src)
        with open(self.src, "w") as f:
            f.write('{"actions": [{"type": "add_campaign_negative"}]}')
        with open(G.snapshot_path("acme-dental", self.CID)) as f:
            self.assertEqual(f.read(), '{"actions": []}')

    def test_verify_refuses_a_reserved_approval(self):
        now = datetime.datetime(2026, 8, 12, 10, 0, tzinfo=datetime.timezone.utc)
        digest = C.write_snapshot("acme-dental", self.CID, self.src)
        C.write_approval("acme-dental", self.CID, digest, "operator", now, 24)
        p = G.approval_path("acme-dental", self.CID)
        with open(p) as f:
            rec = json.load(f)
        rec["reserved_at"] = "2026-08-12T10:30:00Z"
        with open(p, "w") as f:
            json.dump(rec, f)
        with self.assertRaises(ValueError) as ctx:
            C.verify_approval("acme-dental", self.CID, digest, now)
        self.assertIn("reserved", str(ctx.exception))

    def test_verify_accepts_an_unreserved_approval(self):
        """The control: without this, the refusal above proves nothing."""
        now = datetime.datetime(2026, 8, 12, 10, 0, tzinfo=datetime.timezone.utc)
        digest = C.write_snapshot("acme-dental", self.CID, self.src)
        C.write_approval("acme-dental", self.CID, digest, "operator", now, 24)
        rec = C.verify_approval("acme-dental", self.CID, digest, now)
        self.assertEqual(rec["operator"], "operator")
```

Add `import governance_lib as G` and `datetime` to the test file's imports if absent.

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 infra/hermes-agent/bin/changeset_lib.test.py -v 2>&1 | tail -20`
Expected: FAIL with `AttributeError: module 'changeset_lib' has no attribute 'write_snapshot'`.

- [ ] **Step 3: Write minimal implementation**

In `changeset_lib.py`, replace `approval_path(vault, cid)` with a delegation and add `write_snapshot`. Change `write_approval` and `verify_approval` to take a slug:

```python
def approval_path(slug, cid):
    return governance_lib.approval_path(slug, cid)


def snapshot_path(slug, cid):
    return governance_lib.snapshot_path(slug, cid)


def write_snapshot(slug, cid, src_path):
    """Copy the reviewed change-set BYTE-FOR-BYTE into the governance store and return
    its sha256.

    apply executes from THIS copy. Hashing the writable original would still leave the
    draft -> review -> swap window open; copying it somewhere Hermes cannot write closes
    it (spec section 7).
    """
    os.makedirs(governance_lib.approvals_dir(slug), exist_ok=True)
    dst = governance_lib.snapshot_path(slug, cid)
    with open(src_path, "rb") as src:
        data = src.read()
    tmp = dst + ".tmp"
    with open(tmp, "wb") as out:
        out.write(data)
        out.flush()
        os.fsync(out.fileno())
    os.replace(tmp, dst)
    return hashlib.sha256(data).hexdigest()
```

In `write_approval`, replace the `vault` parameter with `slug`, create `governance_lib.approvals_dir(slug)` before writing, and write to `governance_lib.approval_path(slug, cid)`. In `verify_approval`, replace `vault` with `slug`, read from `governance_lib.approval_path(slug, cid)`, and add this check immediately after the record parses as a dict:

```python
    if rec.get("reserved_at"):
        raise ValueError(
            "approval for %r is already reserved (reserved_at=%s) — approvals are "
            "single-use; approve again to authorise another apply" % (cid, rec["reserved_at"]))
```

Ensure `hashlib` is imported in `changeset_lib.py`.

In `approve-changeset.py`, write the snapshot first and bind the approval to the snapshot's digest:

```python
    digest = C.write_snapshot(rec["slug"], changeset_id, path)
    return C.write_approval(rec["slug"], changeset_id, digest, operator, now,
                            caps["approval_ttl_hours"])
```

In `apply-changeset.py`, guard 3 reads the snapshot and guard 5 verifies by slug:

```python
        # 3. change-set loads and validates — from the APPROVED SNAPSHOT in the
        #    governance store, never the vault copy Hermes can write.
        path = C.snapshot_path(rec["slug"], changeset_id)
        if not os.path.isfile(path):
            _refuse("no approved change-set %r for this client" % changeset_id)
```

and

```python
            approval = C.verify_approval(rec["slug"], changeset_id, C.file_digest(path), now)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `infra/hermes-agent/bin/run-bin-tests.sh`
Expected: all suites pass. `approve-changeset.test.py` and `apply-changeset.test.py` fixtures will need their approval paths moved to the governance store — that is part of this task.

- [ ] **Step 5: Commit**

```bash
git add infra/hermes-agent/bin/changeset_lib.py infra/hermes-agent/bin/changeset_lib.test.py \
        infra/hermes-agent/bin/approve-changeset.py infra/hermes-agent/bin/approve-changeset.test.py \
        infra/hermes-agent/bin/apply-changeset.py infra/hermes-agent/bin/apply-changeset.test.py
git commit -m "feat(hermes): execute from a byte-exact approved snapshot"
```

---

## Task 5: Move the audit log to the governance store

**Files:**
- Modify: `infra/hermes-agent/bin/changeset_lib.py:284-286, 392-463`
- Modify: `infra/hermes-agent/bin/apply-changeset.py:127, 193, 202, 295`
- Test: `infra/hermes-agent/bin/changeset_lib.test.py`

**Interfaces:**
- Consumes: `governance_lib.log_path(slug, root=None)`.
- Produces: `changeset_lib.log_path(slug)`, `append_log(slug, rec)`, `iter_log_records(slug)`, `day_counts(slug, day)` — all take a **slug** instead of a vault path. Durability semantics are unchanged: one JSON object per line, fsynced before the call returns.

Rationale (spec §2, F4): the log feeds the daily caps. While it sat in the read-write mount, Hermes could erase its own cap consumption.

- [ ] **Step 1: Write the failing test**

Append to `infra/hermes-agent/bin/changeset_lib.test.py`, above the trailing `unittest.main()`:

```python
class TestAuditLogInGovernanceStore(unittest.TestCase):
    def setUp(self):
        self.gov = tempfile.mkdtemp(prefix="gov-")
        self.addCleanup(shutil.rmtree, self.gov, True)
        os.environ["HERMES_GOVERNANCE_ROOT"] = self.gov
        self.addCleanup(os.environ.pop, "HERMES_GOVERNANCE_ROOT", None)

    def _rec(self, **kw):
        r = {"changeset_id": "20260812-101500-abcd1234", "action_index": 0,
             "status": "applied", "operator": "operator",
             "resource_name": "customers/1234567890/campaignCriteria/111~222",
             "applied_at": "2026-08-12T10:15:00Z"}
        r.update(kw)
        return r

    def test_append_writes_under_the_governance_root(self):
        C.append_log("acme-dental", self._rec())
        self.assertTrue(os.path.isfile(
            os.path.join(self.gov, "log", "acme-dental.jsonl")))

    def test_one_line_per_record(self):
        C.append_log("acme-dental", self._rec())
        C.append_log("acme-dental", self._rec(action_index=1))
        with open(C.log_path("acme-dental")) as f:
            self.assertEqual(len([x for x in f.read().splitlines() if x.strip()]), 2)

    def test_clients_do_not_share_a_log(self):
        C.append_log("acme-dental", self._rec())
        self.assertFalse(os.path.exists(C.log_path("other-clinic")))

    def test_day_counts_reads_the_new_location(self):
        C.append_log("acme-dental", self._rec())
        counts = C.day_counts("acme-dental", "2026-08-12")
        self.assertEqual(counts["actions"], 1)

    def test_a_log_at_the_old_vault_location_is_not_counted(self):
        """Control: pre-migration records left in the vault must not be silently
        double-counted or silently ignored — Task 6 migrates them deliberately."""
        vault = tempfile.mkdtemp(prefix="vault-")
        self.addCleanup(shutil.rmtree, vault, True)
        os.makedirs(os.path.join(vault, "changes"))
        with open(os.path.join(vault, "changes", "log.jsonl"), "w") as f:
            f.write(json.dumps(self._rec()) + "\n")
        self.assertEqual(C.day_counts("acme-dental", "2026-08-12")["actions"], 0)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 infra/hermes-agent/bin/changeset_lib.test.py -v 2>&1 | tail -20`
Expected: FAIL — `append_log` still treats its first argument as a vault directory.

- [ ] **Step 3: Write minimal implementation**

In `changeset_lib.py`, replace `log_path(vault)` with:

```python
def log_path(slug):
    return governance_lib.log_path(slug)
```

Change `append_log(vault, rec)` → `append_log(slug, rec)`, `iter_log_records(vault)` → `iter_log_records(slug)`, and `day_counts(vault, day)` → `day_counts(slug, day)`. Inside each, replace the vault-derived path with `log_path(slug)` and create the parent directory with `os.makedirs(os.path.dirname(log_path(slug)), exist_ok=True)` before the first write. Keep the existing fsync-before-return behaviour exactly.

In `apply-changeset.py`, update the four call sites to pass `rec["slug"]`. Guard 6 becomes:

```python
            counts = C.day_counts(rec["slug"], now.strftime("%Y-%m-%d"))
```

`_undo_targets` takes a slug instead of a vault path, and `plan` carries `"slug": rec["slug"]` so the live loop can call `C.append_log(plan["slug"], rec)`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `infra/hermes-agent/bin/run-bin-tests.sh`
Expected: all suites pass.

- [ ] **Step 5: Commit**

```bash
git add infra/hermes-agent/bin/changeset_lib.py infra/hermes-agent/bin/changeset_lib.test.py \
        infra/hermes-agent/bin/apply-changeset.py infra/hermes-agent/bin/apply-changeset.test.py
git commit -m "feat(hermes): move the audit log into the governance store"
```

---

## Task 6: Count-verified migration

**Files:**
- Create: `infra/hermes-agent/bin/migrate-governance.py`
- Test: `infra/hermes-agent/bin/migrate-governance.test.py`

**Interfaces:**
- Consumes: `governance_lib` paths, `vault_lib.vault_root()`.
- Produces: `migrate(vault_root, governance_root, dry_run=False)` → dict with `moved`, `counts_before`, `counts_after`, `skipped`. Raises `RuntimeError` if any post-move record count differs from its pre-move count.

Rationale (spec §6.1): moving the log without carrying its records resets the daily caps to zero — a guard that reads as green while measuring nothing.

- [ ] **Step 1: Write the failing test**

Create `infra/hermes-agent/bin/migrate-governance.test.py`:

```python
import json, os, shutil, sys, tempfile, unittest
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import migrate_governance_shim as M  # see Step 3 note on the module name


class TestMigration(unittest.TestCase):
    def setUp(self):
        self.vault = tempfile.mkdtemp(prefix="vault-")
        self.gov = tempfile.mkdtemp(prefix="gov-")
        self.addCleanup(shutil.rmtree, self.vault, True)
        self.addCleanup(shutil.rmtree, self.gov, True)
        os.makedirs(os.path.join(self.vault, "_registry"))
        with open(os.path.join(self.vault, "_registry", "clients.json"), "w") as f:
            json.dump({"clients": {"acme-dental": {
                "customer_id": "1234567890", "project": "claude_google_ads",
                "status": "active"}}}, f)
        os.makedirs(os.path.join(self.vault, "acme-dental", "changes"))
        with open(os.path.join(self.vault, "acme-dental", "changes", "log.jsonl"), "w") as f:
            for i in range(3):
                f.write(json.dumps({"changeset_id": "20260812-101500-abcd1234",
                                    "action_index": i, "status": "applied"}) + "\n")

    def test_registry_moves(self):
        M.migrate(self.vault, self.gov)
        self.assertTrue(os.path.isfile(
            os.path.join(self.gov, "registry", "clients.json")))

    def test_every_log_record_is_carried_across(self):
        res = M.migrate(self.vault, self.gov)
        with open(os.path.join(self.gov, "log", "acme-dental.jsonl")) as f:
            lines = [x for x in f.read().splitlines() if x.strip()]
        self.assertEqual(len(lines), 3)
        self.assertEqual(res["counts_before"]["acme-dental"], 3)
        self.assertEqual(res["counts_after"]["acme-dental"], 3)

    def test_a_short_write_is_detected(self):
        """The whole point of the count assertion: a truncated copy must RAISE, not
        report success. Simulated by making the destination unwritable mid-run."""
        os.makedirs(os.path.join(self.gov, "log"))
        open(os.path.join(self.gov, "log", "acme-dental.jsonl"), "w").close()
        os.chmod(os.path.join(self.gov, "log", "acme-dental.jsonl"), 0o400)
        try:
            with self.assertRaises((RuntimeError, OSError)):
                M.migrate(self.vault, self.gov)
        finally:
            os.chmod(os.path.join(self.gov, "log", "acme-dental.jsonl"), 0o600)

    def test_is_idempotent(self):
        M.migrate(self.vault, self.gov)
        res = M.migrate(self.vault, self.gov)
        self.assertIn("acme-dental", res["skipped"])

    def test_dry_run_writes_nothing(self):
        M.migrate(self.vault, self.gov, dry_run=True)
        self.assertFalse(os.path.exists(os.path.join(self.gov, "registry")))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 infra/hermes-agent/bin/migrate-governance.test.py`
Expected: FAIL with `ModuleNotFoundError: No module named 'migrate_governance_shim'`

- [ ] **Step 3: Write minimal implementation**

A hyphenated filename is not importable, and every other script here is invoked by path rather than imported. Create the logic in an importable module and a thin CLI over it.

Create `infra/hermes-agent/bin/migrate_governance_shim.py`:

```python
#!/usr/bin/env python3
"""Move mutation-governance state out of the read-write vault into the host-owned
governance store. Stdlib-only, idempotent, and count-verified.

Count verification is the point. Moving the audit log without carrying its records
resets the daily caps to zero — a guard that reads as green while measuring nothing.
"""
import json, os, shutil


def _count_lines(path):
    if not os.path.isfile(path):
        return 0
    with open(path, encoding="utf-8") as f:
        return len([x for x in f.read().splitlines() if x.strip()])


def migrate(vault_root, governance_root, dry_run=False):
    result = {"moved": [], "skipped": [], "counts_before": {}, "counts_after": {}}

    src_reg = os.path.join(vault_root, "_registry", "clients.json")
    dst_reg = os.path.join(governance_root, "registry", "clients.json")
    if os.path.isfile(src_reg) and not os.path.isfile(dst_reg):
        if not dry_run:
            os.makedirs(os.path.dirname(dst_reg), exist_ok=True)
            shutil.copy2(src_reg, dst_reg)
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
        os.makedirs(os.path.dirname(dst_log), exist_ok=True)
        shutil.copy2(src_log, dst_log)
        after = _count_lines(dst_log)
        result["counts_after"][slug] = after
        if after != before:
            raise RuntimeError(
                "migration lost records for %r: %d before, %d after — refusing to "
                "continue, because a short log silently resets the daily caps"
                % (slug, before, after))
        result["moved"].append(slug)

    return result
```

Create `infra/hermes-agent/bin/migrate-governance.py`:

```python
#!/usr/bin/env python3
"""CLI over migrate_governance_shim. Host-side, operator-run, dry-run by default."""
import argparse, json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import governance_lib
import migrate_governance_shim as M
import vault_lib


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--vault-root", default=None)
    ap.add_argument("--governance-root", default=None)
    ap.add_argument("--apply", action="store_true",
                    help="actually copy; without it this is a dry run")
    args = ap.parse_args(argv)
    try:
        res = M.migrate(args.vault_root or vault_lib.vault_root(),
                        args.governance_root or governance_lib.governance_root(),
                        dry_run=not args.apply)
    except (OSError, RuntimeError) as e:
        print("migrate-governance: %s" % e, file=sys.stderr)
        return 2
    print(json.dumps(res, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 infra/hermes-agent/bin/migrate-governance.test.py`
Expected: PASS, `OK`

- [ ] **Step 5: Confirm the suite count rose again**

Run: `infra/hermes-agent/bin/run-bin-tests.sh`
Expected: `hermes bin: N/N suites passed` with N one higher than after Task 1.

- [ ] **Step 6: Run the real migration, dry first**

```bash
cd infra/hermes-agent
export HERMES_GOVERNANCE_DIR="$HOME/.hermes/governance"
mkdir -p "$HERMES_GOVERNANCE_DIR" && chmod 700 "$HERMES_GOVERNANCE_DIR"
VAULT_ROOT=./data/vaults HERMES_GOVERNANCE_ROOT="$HERMES_GOVERNANCE_DIR" \
  python3 bin/migrate-governance.py
```
Expected: JSON listing what *would* move, with `counts_before` populated. Read it before proceeding.

Then re-run with `--apply` and confirm `counts_before` equals `counts_after` for every slug.

- [ ] **Step 7: Commit**

```bash
git add infra/hermes-agent/bin/migrate_governance_shim.py \
        infra/hermes-agent/bin/migrate-governance.py \
        infra/hermes-agent/bin/migrate-governance.test.py
git commit -m "feat(hermes): count-verified migration into the governance store"
```

---

## Task 7: The run record moves to the caller

**Files:**
- Modify: `infra/hermes-agent/bin/apply-changeset.py:305-315`
- Create: `infra/hermes-agent/bin/persist-run-record.py`
- Test: `infra/hermes-agent/bin/persist-run-record.test.py`

**Interfaces:**
- Consumes: nothing new.
- Produces: `apply-changeset.py` prints a final stdout line `HERMES-RESULT-JSON <compact-json>`. `persist-run-record.py` exposes `parse_result(text)` → dict or `None`, and `persist(vault, result)` → path of the written `result.json`.

Rationale (spec §6.5): `apply-changeset.py:306` writes `result.json` and `:311` appends `timeline.md` into the vault under `data/`, which the isolated container deliberately does not mount. Left alone, step 11 fails *after* live mutations have landed and turns a successful apply into exit 3.

- [ ] **Step 1: Write the failing test**

Create `infra/hermes-agent/bin/persist-run-record.test.py`:

```python
import json, os, shutil, sys, tempfile, unittest
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import persist_run_record_shim as P


class TestParse(unittest.TestCase):
    def test_finds_the_marker_line(self):
        text = "apply-changeset: ok\nHERMES-RESULT-JSON {\"changeset_id\": \"x\"}\n"
        self.assertEqual(P.parse_result(text), {"changeset_id": "x"})

    def test_absent_marker_returns_none(self):
        self.assertIsNone(P.parse_result("apply-changeset: refused\n"))

    def test_ignores_the_marker_word_inside_ordinary_output(self):
        """Control: the discriminator is a line PREFIX, not a substring anywhere."""
        self.assertIsNone(P.parse_result("see HERMES-RESULT-JSON for details\n"))

    def test_last_marker_wins(self):
        text = ('HERMES-RESULT-JSON {"n": 1}\n'
                'HERMES-RESULT-JSON {"n": 2}\n')
        self.assertEqual(P.parse_result(text), {"n": 2})


class TestPersist(unittest.TestCase):
    def setUp(self):
        self.vault = tempfile.mkdtemp(prefix="vault-")
        self.addCleanup(shutil.rmtree, self.vault, True)

    def test_writes_result_json_and_appends_timeline(self):
        res = {"changeset_id": "20260812-101500-abcd1234", "applied": 2,
               "status": "ok", "finished_at": "2026-08-12T10:20:00Z"}
        path = P.persist(self.vault, res)
        with open(path) as f:
            self.assertEqual(json.load(f)["applied"], 2)
        with open(os.path.join(self.vault, "timeline.md")) as f:
            self.assertIn("20260812-101500-abcd1234", f.read())

    def test_timeline_appends_rather_than_truncates(self):
        res = {"changeset_id": "20260812-101500-abcd1234", "applied": 1,
               "status": "ok", "finished_at": "2026-08-12T10:20:00Z"}
        P.persist(self.vault, res)
        P.persist(self.vault, dict(res, changeset_id="20260812-111500-beef5678"))
        with open(os.path.join(self.vault, "timeline.md")) as f:
            body = f.read()
        self.assertIn("abcd1234", body)
        self.assertIn("beef5678", body)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 infra/hermes-agent/bin/persist-run-record.test.py`
Expected: FAIL with `ModuleNotFoundError: No module named 'persist_run_record_shim'`

- [ ] **Step 3: Write minimal implementation**

Create `infra/hermes-agent/bin/persist_run_record_shim.py`:

```python
#!/usr/bin/env python3
"""Persist an executor run record into the client vault. Stdlib-only.

The executor runs in a one-shot container that deliberately does not mount the vault,
so it emits its result on stdout and the CALLER persists it. The audit log in the
governance store remains the reversibility record and is written by the executor,
fsynced per action; result.json and timeline.md are convenience artifacts for humans
and for Hermes. If this step is lost, the audit log still holds the truth and --undo
still works.
"""
import json, os

MARKER = "HERMES-RESULT-JSON "


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


def persist(vault, result):
    os.makedirs(vault, exist_ok=True)
    path = os.path.join(vault, "%s.result.json" % result["changeset_id"])
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, sort_keys=True)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)
    with open(os.path.join(vault, "timeline.md"), "a", encoding="utf-8") as f:
        f.write("- %s  change-set `%s`  status=%s  actions=%s\n"
                % (result.get("finished_at", ""), result["changeset_id"],
                   result.get("status", "?"), result.get("applied", "?")))
    return path
```

Create `infra/hermes-agent/bin/persist-run-record.py`:

```python
#!/usr/bin/env python3
"""CLI: read executor stdout on stdin, persist the run record into the client vault."""
import argparse, sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import persist_run_record_shim as P
import vault_lib


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--client", required=True)
    args = ap.parse_args(argv)
    text = sys.stdin.read()
    sys.stdout.write(text)          # pass the executor's output through, unchanged
    res = P.parse_result(text)
    if res is None:
        return 0                    # a refusal emits no result line; that is not an error here
    try:
        rec = vault_lib.resolve(args.client)
        P.persist(rec["vault_path"], res)
    except (ValueError, KeyError, OSError, TypeError) as e:
        print("persist-run-record: %s" % e, file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

In `apply-changeset.py`, replace the `result.json` + `timeline.md` block (currently `:305-315`) with a marker emission:

```python
            # 11. Emit the run record for the CALLER to persist. This container does
            #     not mount the vault; the audit log above is the reversibility record.
            print("HERMES-RESULT-JSON " + json.dumps(result, sort_keys=True))
```

Keep the existing `PostMutationError` handling around it — a failure to *print* is still a post-mutation failure and must exit 3, not 2.

- [ ] **Step 4: Run tests to verify they pass**

Run: `infra/hermes-agent/bin/run-bin-tests.sh`
Expected: all suites pass, suite count one higher again.

- [ ] **Step 5: Commit**

```bash
git add infra/hermes-agent/bin/persist_run_record_shim.py \
        infra/hermes-agent/bin/persist-run-record.py \
        infra/hermes-agent/bin/persist-run-record.test.py \
        infra/hermes-agent/bin/apply-changeset.py infra/hermes-agent/bin/apply-changeset.test.py
git commit -m "feat(hermes): emit the run record for the caller to persist"
```

---

## Task 8: The isolated executor container

**Files:**
- Modify: `infra/hermes-agent/docker-compose.yml`
- Modify: `infra/hermes-agent/run-ads-mutate.sh`
- Modify: `infra/hermes-agent/.env.example`

**Interfaces:**
- Consumes: `HERMES_GOVERNANCE_DIR` from `.env` (compose variable substitution), `persist-run-record.py` from Task 7.
- Produces: an `ads-mutator` compose service under the `tools` profile, invoked as `docker compose run --rm --no-deps ads-mutator --client <slug> --changeset <id>`. `run-ads-mutate.sh` keeps its exact command-line interface.

- [ ] **Step 1: Declare the governance directory**

Append to `infra/hermes-agent/.env.example` (tracked — keep it free of real values):

```
# Absolute host path to the governance store. Must be OUTSIDE this repo (the repo is
# bind-mounted into the container) and OUTSIDE ./data (the one read-write mount).
# Create it mode 700. Compose does not expand ~, so write the path in full.
HERMES_GOVERNANCE_DIR=/absolute/path/to/.hermes/governance
```

Set the real value in the gitignored `.env`.

- [ ] **Step 2: Add the one-shot service**

Add to `infra/hermes-agent/docker-compose.yml`, as a sibling of `hermes-agent`:

```yaml
  # One-shot executor for the mutation tier. Deliberately NOT the gateway container:
  # same container means same security domain, and F7 showed that concretely — same
  # UID plus a shared PID namespace makes an injected credential readable via /proc.
  # Started only by run-ads-mutate.sh via `docker compose run`; the `tools` profile
  # keeps `docker compose up` from ever starting it.
  #
  # NOTE the absence of `env_file: .env`. That is load-bearing: it would put
  # ANTHROPIC_API_KEY and the provider key into this container's environment.
  ads-mutator:
    build: .
    image: hermes-agent-claude
    profiles: ["tools"]
    entrypoint: ["python3", "/opt/cc-bin/apply-changeset.py"]
    environment:
      HERMES_GOVERNANCE_ROOT: /opt/governance
    volumes:
      - ${HERMES_GOVERNANCE_DIR}/approvals:/opt/governance/approvals:ro
      - ${HERMES_GOVERNANCE_DIR}/control:/opt/governance/control:ro
      - ${HERMES_GOVERNANCE_DIR}/registry:/opt/governance/registry:ro
      - ${HERMES_GOVERNANCE_DIR}/log:/opt/governance/log      # the ONLY writable path
      - ../../../claude-google-ads:/projects/claude_google_ads:ro
      - ./registry:/opt/registry:ro
      - ./bin:/opt/cc-bin:ro
```

- [ ] **Step 3: Point the wrapper at it**

In `run-ads-mutate.sh`, replace the final `exec docker compose ... exec ... hermes-agent ...` block with:

```sh
docker compose -f "$here/docker-compose.yml" run --rm --no-deps \
  -e GOOGLE_ADS_DEVELOPER_TOKEN -e GOOGLE_ADS_CLIENT_ID -e GOOGLE_ADS_CLIENT_SECRET \
  -e GOOGLE_ADS_REFRESH_TOKEN -e GOOGLE_ADS_LOGIN_CUSTOMER_ID -e GOOGLE_ADS_CUSTOMER_ID \
  -e GOOGLE_ADS_CREDENTIAL_ROLE \
  -T ads-mutator "$@" \
  | VAULT_ROOT="$here/data/vaults" HERMES_GOVERNANCE_ROOT="${HERMES_GOVERNANCE_DIR}" \
    python3 "$here/bin/persist-run-record.py" --client "$client"
rc=${PIPESTATUS:-$?}
exit "$rc"
```

**The exit status matters and a pipeline hides it.** `cmd | persist` takes its status from `persist`, which would turn an exit-2 refusal into a success. Use this POSIX-safe form instead of relying on bash's `PIPESTATUS`:

```sh
tmp_out="$(mktemp)"
trap 'rm -f "$tmp_out"' EXIT INT TERM
docker compose -f "$here/docker-compose.yml" run --rm --no-deps \
  -e GOOGLE_ADS_DEVELOPER_TOKEN -e GOOGLE_ADS_CLIENT_ID -e GOOGLE_ADS_CLIENT_SECRET \
  -e GOOGLE_ADS_REFRESH_TOKEN -e GOOGLE_ADS_LOGIN_CUSTOMER_ID -e GOOGLE_ADS_CUSTOMER_ID \
  -e GOOGLE_ADS_CREDENTIAL_ROLE \
  -T ads-mutator "$@" > "$tmp_out" 2>&1
rc=$?
cat "$tmp_out"
VAULT_ROOT="$here/data/vaults" HERMES_GOVERNANCE_ROOT="${HERMES_GOVERNANCE_DIR}" \
  python3 "$here/bin/persist-run-record.py" --client "$client" < "$tmp_out" > /dev/null
exit "$rc"
```

Parse `--client` out of `"$@"` near the top of the script to populate `$client`, and refuse with exit 1 if it is absent.

- [ ] **Step 4: Verify the executor's environment is clean**

```bash
cd infra/hermes-agent
docker compose run --rm --no-deps --entrypoint sh -T ads-mutator -c \
  'echo "anthropic vars: $(printenv | grep -c "^ANTHROPIC" || true)"; echo "control PATH: $(printenv | grep -c "^PATH=")"'
```
Expected: `anthropic vars: 0` and `control PATH: 1`. A zero on both would mean the probe itself is broken.

- [ ] **Step 5: Verify the guards still refuse with the kill switch absent**

```bash
cd infra/hermes-agent
./run-ads-mutate.sh --client <slug> --changeset 20260812-101500-abcd1234 --dry-run; echo "rc=$?"
```
Expected: `rc=2` with the kill-switch refusal message. This proves the new execution target still reaches guard 1.

- [ ] **Step 6: Commit**

```bash
git add infra/hermes-agent/docker-compose.yml infra/hermes-agent/run-ads-mutate.sh infra/hermes-agent/.env.example
git commit -m "feat(hermes): run the mutation executor in an isolated one-shot container"
```

---

## Task 9: Move the credential audit off the gateway container

**Files:**
- Modify: `infra/hermes-agent/docker-compose.yml`
- Modify: `infra/hermes-agent/audit-credential-access.sh:87`

**Interfaces:**
- Consumes: the `ads-mutator` service pattern from Task 8.
- Produces: an `ads-credential-audit` service under the `tools` profile.

Rationale (spec §2, F7): `audit-credential-access.sh --all` injects the **write** credential into the gateway container, where Hermes can read it from `/proc`. The probe logic is unchanged and stays structurally non-mutating — every `validate_only` assignment is a literal `True` and there is no flag to disable it (verified 2026-08-19).

- [ ] **Step 1: Add the service**

```yaml
  # Credential access audit. Same isolation rationale as ads-mutator: this injects the
  # WRITE credential, and must not do so into the container Hermes has a shell in.
  ads-credential-audit:
    build: .
    image: hermes-agent-claude
    profiles: ["tools"]
    entrypoint: ["/opt/ads-venv/bin/python3", "/opt/cc-bin/audit-credential-access.py"]
    volumes:
      - ../../../claude-google-ads:/projects/claude_google_ads:ro
      - ./registry:/opt/registry:ro
      - ./bin:/opt/cc-bin:ro
```

- [ ] **Step 2: Point the wrapper at it**

In `audit-credential-access.sh:87`, replace `exec ... -T hermes-agent /opt/ads-venv/bin/python3 /opt/cc-bin/audit-credential-access.py` with `run --rm --no-deps -T ads-credential-audit`, keeping every `-e` passthrough exactly as it is.

- [ ] **Step 3: Verify with the real credentials**

```bash
cd infra/hermes-agent
./audit-credential-access.sh --all --customer <digits>; echo "rc=$?"
```
Expected: `rc=0`, `.env.ga` measured `READ_ONLY`, `.env.gaw` measured `MUTATE_CAPABLE`, `mismatch false` on both. **This is the positive control for the whole task** — if the audit cannot run, the refusals it produces elsewhere prove nothing.

- [ ] **Step 4: Commit**

```bash
git add infra/hermes-agent/docker-compose.yml infra/hermes-agent/audit-credential-access.sh
git commit -m "feat(hermes): run the credential audit off the gateway container"
```

---

## Task 10: Mask credential files out of the project mounts

**Files:**
- Create: `infra/hermes-agent/masks/empty`
- Modify: `infra/hermes-agent/registry/projects.yaml`
- Modify: `infra/hermes-agent/docker-compose.yml`
- Modify: `infra/hermes-agent/bin/changeset_lib.py` (add `read_mask_paths`)
- Test: `infra/hermes-agent/bin/registry-invariants.test.py`

**Interfaces:**
- Consumes: the existing `discover_projects(path)` helper in `registry-invariants.test.py` (which returns project **names**, not configs) and `changeset_lib.read_workdir(path, project)`.
- Produces: a per-project `mask_paths` list in the registry, `changeset_lib.read_mask_paths(path, project)` → `list[str]`, and a registry invariant asserting every declared entry has a matching mount in `docker-compose.yml`.

Rationale (spec §18): the repo mount exposes every `.env.*` in `infra/hermes-agent/` plus the ads repo's `.env`. None of it is intentional and nothing in-container consumes any of it (verified with a positive control). Declaring the masks and testing that compose matches the declaration is what stops a future `.env.<x>` from silently restoring the exposure.

- [ ] **Step 1: Declare the masks**

Add to each project in `registry/projects.yaml`:

```yaml
  claude_code:
    # Paths (workdir-relative) masked out of the container view. The whole directory
    # is masked rather than each .env.* individually, so a newly minted credential file
    # cannot silently reappear in the container.
    mask_paths:
      - infra/hermes-agent

  claude_google_ads:
    # A single secret-bearing file: masked with an empty bind rather than a tmpfs, so
    # the file still EXISTS and load_dotenv() reads nothing instead of erroring.
    mask_paths:
      - .env
```

- [ ] **Step 2: Add a reader for the new key**

The existing suite discovers project **names** via `discover_projects(path)` and reads scalars via `changeset_lib.read_workdir(path, project)`; there is no reader for a bare list key. Add one to `changeset_lib.py`, mirroring `read_workdir`'s duplicate-refusal style and reusing the existing `_iter_project_lines` helper:

```python
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
```

- [ ] **Step 3: Write the failing invariant test**

Append to `infra/hermes-agent/bin/registry-invariants.test.py`, above its trailing `unittest.main()`:

```python
class TestMaskPathsAreActuallyMounted(unittest.TestCase):
    """A declared mask that compose does not implement is worse than no declaration:
    it reads as protection while providing none."""

    def setUp(self):
        here = os.path.dirname(os.path.abspath(__file__))
        with open(os.path.join(here, "..", "docker-compose.yml"), encoding="utf-8") as f:
            self.compose = f.read()

    def test_reader_finds_the_declarations(self):
        """Guards the reader itself: if the indentation convention changes, the
        assertion below would pass vacuously on an empty list."""
        total = sum(len(C.read_mask_paths(REGISTRY, p))
                    for p in discover_projects(REGISTRY))
        self.assertGreater(total, 0, "read_mask_paths found nothing — reader is blind")

    def test_every_declared_mask_has_a_mount(self):
        for project in discover_projects(REGISTRY):
            workdir = C.read_workdir(REGISTRY, project)
            for rel in C.read_mask_paths(REGISTRY, project):
                target = "%s/%s" % (workdir.rstrip("/"), rel)
                self.assertIn(target, self.compose,
                              "project %r declares mask_paths entry %r but no mount in "
                              "docker-compose.yml targets %s" % (project, rel, target))

    def test_a_bogus_target_would_be_caught(self):
        """Control: prove the containment check can fail."""
        self.assertNotIn("/projects/claude_code/definitely-not-mounted", self.compose)
```

- [ ] **Step 4: Run test to verify it fails**

Run: `python3 infra/hermes-agent/bin/registry-invariants.test.py -v 2>&1 | tail -20`
Expected: FAIL on `test_every_declared_mask_has_a_mount` — the declarations exist but compose has no matching mounts yet. If `test_reader_finds_the_declarations` also fails, fix the reader first; the mount assertion means nothing while the reader is blind.

- [ ] **Step 5: Implement the masks**

Create an empty tracked file:

```bash
: > infra/hermes-agent/masks/empty
```

Add to the `hermes-agent` service in `docker-compose.yml`, **after** the project mounts they override (later mounts win):

```yaml
      # --- credential masks (registry: mask_paths) ---
      # The repo mount exposes every .env.* under infra/hermes-agent/, including the
      # live write credential and the draft-PR bot PAT. Nothing in-container consumes
      # any of them (verified 2026-08-19 with a positive control). Masking the whole
      # directory covers files that do not exist yet.
      - type: tmpfs
        target: /projects/claude_code/infra/hermes-agent
      # The ads repo keeps its secret in one file at the root, so mask just that file —
      # masking the root would hide the project. An EMPTY file, not an absent one, so
      # load_dotenv() reads nothing rather than failing.
      - ./masks/empty:/projects/claude_google_ads/.env:ro
```

- [ ] **Step 6: Run test to verify it passes**

Run: `infra/hermes-agent/bin/run-bin-tests.sh`
Expected: all suites pass.

- [ ] **Step 7: Recreate the container and probe, with controls**

```bash
cd infra/hermes-agent
docker compose up -d --force-recreate hermes-agent
docker compose exec -T hermes-agent sh -c '
for p in /projects/claude_code/infra/hermes-agent/.env.gaw \
         /projects/claude_code/infra/hermes-agent/.env.ga \
         /projects/claude_code/infra/hermes-agent/.env \
         /projects/claude_code/infra/hermes-agent/.env.pr; do
  if [ -s "$p" ]; then echo "STILL EXPOSED $p"; else echo "masked        $p"; fi
done
echo "--- CONTROL: a file that MUST still be readable ---"
[ -s /projects/claude_code/CLAUDE.md ] && echo "readable CLAUDE.md (control OK)" || echo "CONTROL FAILED"
echo "--- ads repo .env must exist but be empty ---"
[ -f /projects/claude_google_ads/.env ] && echo "exists, bytes=$(wc -c < /projects/claude_google_ads/.env)"'
```
Expected: all four `masked`, the control readable, and the ads `.env` present at 0 bytes. **If the control fails, the probe is broken and the four `masked` lines mean nothing.**

- [ ] **Step 8: Prove nothing regressed**

Run the full read path, the collection, and a validate-only mutate against the authorised dormant client. Resolve its customer id programmatically — never hardcode it:

```bash
cd infra/hermes-agent
cid=$(VAULT_ROOT=./data/vaults HERMES_GOVERNANCE_ROOT="$HERMES_GOVERNANCE_DIR" \
      python3 bin/vault_lib.py --client <slug> --field customer_id)
./run-ads-report.sh --script account_overview --customer "$cid"; echo "report rc=$?"
./collect-audit-data.sh --client <slug>; echo "collect rc=$?"
```
Expected: both `rc=0`. For the collection, check **file existence** of the expected outputs — "no data" and "zero data" are different events and row-emptiness cannot separate them.

- [ ] **Step 9: Commit**

```bash
git add infra/hermes-agent/masks/empty infra/hermes-agent/registry/projects.yaml \
        infra/hermes-agent/docker-compose.yml infra/hermes-agent/bin/registry-invariants.test.py \
        infra/hermes-agent/bin/changeset_lib.py
git commit -m "feat(hermes): mask credential files out of the project mounts"
```

---

## Task 11: Verification gate and documentation

**Files:**
- Modify: `infra/hermes-agent/README.md`

**Interfaces:** none — this task produces evidence and corrected prose.

- [ ] **Step 1: Re-probe every finding from spec §2, each with its control**

```bash
cd infra/hermes-agent
docker compose exec -T hermes-agent sh -c '
echo "F1/F8 credential files:"
for p in /projects/claude_code/infra/hermes-agent/.env.gaw \
         /projects/claude_code/infra/hermes-agent/.env.pr \
         /projects/claude_google_ads/.env; do
  [ -s "$p" ] && echo "  EXPOSED $p" || echo "  masked  $p"
done
[ -s /projects/claude_code/CLAUDE.md ] && echo "  control readable (probe works)" || echo "  CONTROL FAILED"
echo "F3 gateway env: GOOGLE_ADS vars=$(printenv | grep -c "^GOOGLE_ADS" || true) control PATH=$(printenv | grep -c "^PATH=")"
echo "F4 governance reachable? $( [ -e /opt/governance ] && echo YES-BAD || echo no-good )"
echo "  control: /opt/data writable? $(touch /opt/data/.p 2>/dev/null && { echo yes; rm -f /opt/data/.p; } || echo no)"'
```
Expected: all three masked, control readable, `GOOGLE_ADS vars=0` with `PATH=1`, governance `no-good`, `/opt/data` still writable (that is the control proving the writability probe works).

- [ ] **Step 2: Prove the old forgery surfaces are dead**

```bash
cd infra/hermes-agent
# Write a kill switch at the OLD location from inside the container, then confirm
# mutation is still refused. Remove it immediately afterwards.
docker compose exec -T hermes-agent sh -c 'mkdir -p /opt/data/vaults/_governance && touch /opt/data/vaults/_governance/mutation-enabled'
./run-ads-mutate.sh --client <slug> --changeset 20260812-101500-abcd1234 --dry-run; echo "rc=$? (expect 2)"
docker compose exec -T hermes-agent sh -c 'rm -f /opt/data/vaults/_governance/mutation-enabled'
```
Expected: `rc=2`, refused at guard 1. This is the single most important assertion in the plan: it proves the container can no longer enable mutation.

- [ ] **Step 3: Confirm mutation is disabled at rest**

```bash
ls -la "$HERMES_GOVERNANCE_DIR/control/" 2>&1
docker compose exec -T hermes-agent sh -c 'ls -la /opt/data/vaults/_governance/ 2>&1'
```
Expected: no `mutation-enabled` file in either location.

- [ ] **Step 4: Run every suite**

```bash
node scripts/run-all-tests.js
infra/hermes-agent/bin/run-bin-tests.sh
cd ../../../claude-google-ads && .venv/bin/python code/mutate_campaign_negative.test.py
```
Expected: all green, and the hermes bin count is **five higher** than at the start of this plan (Tasks 1, 6, 7 add suites; Tasks 2–5 and 10 add classes to existing ones). Confirm the number, not just the `OK`.

- [ ] **Step 5: Correct the README**

Replace the "reaches ONLY this exec'd process" claim in the `run-ads-mutate.sh` header comment and in the README's credential-separation paragraph with the accurate statement:

> The write credential is injected per-invocation into a **one-shot container that Hermes has no shell in**. It never enters the gateway container at all. The earlier wording — "reaches only this exec'd process" — was true of delivery and false of visibility: `/proc/<pid>/environ` is readable by any same-UID process, and everything in the gateway container runs as the same user.

Add a "Governance store" section documenting the layout from spec §6.1, the `HERMES_GOVERNANCE_DIR` variable, and the migration command. Do **not** touch the "Provisioning a credential" section — its rule-1 drift is resolved by the separate revocation-isolation task, and correcting it twice would produce conflicting text.

- [ ] **Step 6: Commit and open the PR**

```bash
git add infra/hermes-agent/README.md infra/hermes-agent/run-ads-mutate.sh
git commit -m "docs(hermes): document the governance store and correct the credential-isolation claim"
git push -u origin HEAD
gh pr create --base main --title "Harden the Hermes runtime boundary" --body "$(cat <<'EOF'
Implements `docs/superpowers/specs/2026-08-19-hermes-mutation-syscall-design.md`, Plan 1 of 2.

Moves every piece of mutation-governance state out of the container's one read-write
mount into a host-owned governance store, executes approved change-sets from a
byte-exact snapshot, runs the executor in a one-shot container Hermes has no shell in,
and masks credential files out of the project mounts.

Verification evidence is in the task steps; the load-bearing one is that a kill switch
created from inside the container no longer enables mutation.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

---

## Self-Review

**Spec coverage.** §6.1 governance store → Tasks 1–5; migration → Task 6; §6.5 isolated executor and the run-record split → Tasks 7–8; F7 credential-audit relocation → Task 9; §18 masking → Task 10; §13 verification and §15 README correction → Task 11. **Deferred to Plan 2 by design:** §6.2 spool, §6.3 `hermes-syscall`, §6.4 broker and socket proxy, §7 reservation *writing* (the *refusal* ships in Task 4), §8 request schema and quotas, §17.3 audit-log visibility.

**Placeholders.** None. Every `<slug>` and `<digits>` is a deliberate instruction not to hardcode a client identifier, per the plan's global constraints.

**Type consistency.** `slug`-first signatures are introduced in Task 1 and used identically in Tasks 2–5 and 7. `write_snapshot` returns a digest consumed by `write_approval` in the same task. `parse_result`/`persist` are defined in Task 7 and consumed only by its own CLI. `mask_paths` is declared in Task 10, read by `read_mask_paths` added in the same task, and asserted by the invariant test alongside it.

**One defect found and fixed during this review:** Task 10's test originally called a helper `_load_projects()` returning project configs. No such helper exists — `registry-invariants.test.py` has `discover_projects(path)`, which returns names only, and there was no reader for a bare list key at all. Task 10 now adds `read_mask_paths` explicitly and the test uses the helpers that exist.

**Known gap, deliberate:** `--undo` reads the audit log, which now lives in the governance store; the undo path is exercised in Plan 2's live gate rather than here, because Plan 1 never performs a live mutation.
