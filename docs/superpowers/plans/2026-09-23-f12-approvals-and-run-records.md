# F12 — Approvals and Run Records Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the mutation rail's host-side tools work without reaching into the gateway-owned
vault: run records move into the governance store, and approval artifacts get deterministic
ownership and modes so the broker can reserve them and the executor can read them.

**Architecture:** `persist_run_record_shim.persist()` writes into `<store>/records/<slug>/`
instead of the vault, keeping its containment hardening. One new layout row creates
`records/` (`hermes-broker:hermes 2750`). A helper in `changeset_lib` sets owner and mode on the
open file descriptor for every approval artifact — approval `0640`, snapshot `0640`, lock sidecar
`0660`, owner `hermes-broker:hermes` when root — so nothing depends on umask.
`approve-changeset.py` refuses to run as non-root on Linux.

**Tech Stack:** Python 3 stdlib only (`os`, `pwd`, `grp`, `unittest`, `subprocess`), POSIX shell,
systemd unit files (read, not modified), GitHub Actions (`ubuntu-latest`), `setpriv`.

**Spec:** `docs/superpowers/specs/2026-09-23-f12-approvals-and-run-records-design.md`. Read it
before any task — especially §1.1 (why the executor cannot write the vault), §2.5 (why the
pre-flight must NOT learn about `records/`) and §3 (the proof obligations). Where this plan and
the code disagree, the code wins: stop and report rather than bending the code to the plan.

**Task order deviates from spec §5** — the spec lists the persist move first, but it depends on
the layout row and the new path helpers, so Task 1 creates those. Same work, dependency order.

## Global Constraints

- **Mutation stays disabled.** Nothing creates `control/mutation-enabled`. No task touches the VPS.
- **The security gate is untouched:** `bin/docker-create-proxy.py`, `deploy/hermes-docker-proxy.service`,
  the seven `ads-mutator` binds and `docker-compose.yml` must not change. `records/` is never mounted.
- **`preflight-governance-access.py` must NOT gain `records`** (spec §2.5) — it declares what the
  CONTAINER needs, and `records/` has no mount. A test pins its absence.
- **`ReadWritePaths=` and both unit files stay as they are.**
- **Every new check needs a firing control**: a test that shows it failing on bad input.
- **Stdlib only** in `infra/hermes-agent/bin/` and `deploy/*.py`. Invoke `python3`, never `python`.
- **Containment is not negotiable:** the persist path keeps `O_NOFOLLOW`, the regular-file
  assertion, the single-link (`st_nlink > 1`) refusal, and dir-fd-relative opens. A destination
  that cannot be proven raises `PersistRefused` — never "skip and continue".
- **Groups are resolved by NAME** (`hermes`, `hermes-broker`); a missing group is a refusal, never
  a guessed gid.
- **Linux ownership is proven on the Linux CI runner** with its executed count read, or stated as
  unproven. Docker/`setpriv` are unavailable on darwin.
- **Never read or print `.env`; never `docker compose config`.** Placeholder credentials only.
- **Stage by explicit path only.** Never `git add -A`, `evals/`, `.project-brain/`, `CLAUDE.md`.
- **Never read, write, stage or MENTION `.project-brain/canon/` in a Bash command** — a hook fires.
- **Never pipe a test command into `tail`.** Capture into a variable or read `${PIPESTATUS[0]}`.
- **No client names, customer ids, campaign ids or metrics** in added lines. Sanctioned fixtures
  only: `acme-dental`, `acme`, `other-clinic`, `slug-1`, `"1234567890"`, `"9998887776"`,
  `"9999999999"`.
- **Commit messages** end with `Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>`.

## File map

| File | Change | Responsibility |
|---|---|---|
| `infra/hermes-agent/bin/governance_lib.py` | Modify | `RECORDS_DIR_MODE`, `records_dir`, `record_path`, `records_timeline_path` |
| `infra/hermes-agent/bin/host_layout.py` | Modify | one `records` row in `LAYOUT` |
| `infra/hermes-agent/bin/host_layout.test.py` | Modify | table pin + mode-constant test + a check firing control |
| `infra/hermes-agent/bin/governance_lib.test.py` | Modify | path helper tests |
| `infra/hermes-agent/bin/preflight-governance-access.test.py` | Modify | `records` absent from the container's declared dirs |
| `infra/hermes-agent/bin/persist_run_record_shim.py` | Modify | write into the records dir; rewrite the stale threat docstring |
| `infra/hermes-agent/bin/persist-run-record.py` | Modify | resolve the store root, not the vault path |
| `infra/hermes-agent/bin/persist-run-record.test.py` | Modify | re-point every case, keep the containment controls |
| `infra/hermes-agent/bin/changeset_lib.py` | Modify | fd-based owner/mode helper; apply in the three writers |
| `infra/hermes-agent/bin/changeset_lib.test.py` | Modify | mode tests under a hostile umask |
| `infra/hermes-agent/bin/approve-changeset.py` | Modify | root requirement on Linux |
| `infra/hermes-agent/bin/approve-changeset.test.py` | Modify | refusal fires on Linux, not on darwin |
| `infra/hermes-agent/deploy/layout-integration.test.py` | Modify | Tier 2: records round trip; root-approves → broker-reserves |
| `infra/hermes-agent/README.md` | Modify | `sudo` for approve; where records live |
| `infra/hermes-agent/deploy/BRING-UP.md` | Modify | rehearsal gate prerequisites |
| `docs/superpowers/specs/2026-09-21-vps-first-bring-up-findings.md` | Modify | F12 fixed |

---

### Task 1: The `records` layout row and its path helpers

**Files:**
- Modify: `infra/hermes-agent/bin/governance_lib.py`
- Modify: `infra/hermes-agent/bin/host_layout.py` (the `LAYOUT` tuple, after the `log` row)
- Test: `infra/hermes-agent/bin/governance_lib.test.py`, `infra/hermes-agent/bin/host_layout.test.py`,
  `infra/hermes-agent/bin/preflight-governance-access.test.py`

**Interfaces:**
- Consumes: nothing.
- Produces (Tasks 2 and 5 use these exact names):
  - `governance_lib.RECORDS_DIR_MODE = 0o2750`
  - `governance_lib.records_dir(slug, root=None) -> str` — `<root>/records/<slug>`
  - `governance_lib.record_path(slug, cid, root=None) -> str` — `…/<cid>.result.json`
  - `governance_lib.records_timeline_path(slug, root=None) -> str` — `…/timeline.md`
  - `host_layout.LAYOUT` gains `Entry("store", "records", DIR, "hermes-broker", "hermes", RECORDS_DIR_MODE, None)`

- [ ] **Step 1: Write the failing path-helper tests**

In `infra/hermes-agent/bin/governance_lib.test.py`, beside the existing path tests (the file
already has `test_kill_switch_path` and friends using a root of `/tmp/gov`), add:

```python
    def test_records_dir(self):
        self.assertEqual(G.records_dir("acme-dental", self.R),
                         "/tmp/gov/records/acme-dental")

    def test_record_path(self):
        self.assertEqual(G.record_path("acme-dental", "20260824-101500-abcdef01", self.R),
                         "/tmp/gov/records/acme-dental/20260824-101500-abcdef01.result.json")

    def test_records_timeline_path(self):
        self.assertEqual(G.records_timeline_path("acme-dental", self.R),
                         "/tmp/gov/records/acme-dental/timeline.md")

    def test_a_bad_slug_is_refused_like_every_other_helper(self):
        for bad in ("../escape", "acme/dental", "acme\n", ""):
            with self.assertRaises(ValueError):
                G.records_dir(bad, self.R)

    def test_a_bad_changeset_id_is_refused(self):
        with self.assertRaises(ValueError):
            G.record_path("acme-dental", "not-a-changeset-id", self.R)
```

(Match the existing file's conventions for `G` and `self.R`; read the top of the file first. If
its root attribute is named differently, use that name — the code wins.)

- [ ] **Step 2: Run them and watch them fail**

Run: `python3 infra/hermes-agent/bin/governance_lib.test.py -v`
Expected: the new tests ERROR with `AttributeError: module 'governance_lib' has no attribute 'records_dir'`.

- [ ] **Step 3: Add the helpers**

In `infra/hermes-agent/bin/governance_lib.py`, beside `LOG_DIR_MODE` add:

```python
# F12: the broker writes run records here. Setgid (like approvals/ and log/) keeps group
# hermes on the per-client directories; no group write, because write on a directory grants
# unlink. NOT mounted into any container — the executor never sees records/, which is why
# preflight-governance-access.py must not list it (spec 2026-09-23 §2.5).
RECORDS_DIR_MODE = 0o2750
```

and, after `log_path`, mirroring `approvals_dir` / `approval_path` exactly (same `_root`, `_slug`
and `_cid` validation — do not invent new validation):

```python
def records_dir(slug, root=None):
    return os.path.join(_root(root), "records", _slug(slug))


def record_path(slug, cid, root=None):
    return os.path.join(records_dir(slug, root), "%s.result.json" % _cid(cid))


def records_timeline_path(slug, root=None):
    return os.path.join(records_dir(slug, root), "timeline.md")
```

- [ ] **Step 4: Verify they pass**

Run: `python3 infra/hermes-agent/bin/governance_lib.test.py -v`
Expected: all OK.

- [ ] **Step 5: Write the failing layout tests**

In `infra/hermes-agent/bin/host_layout.test.py`:

1. In `TestTable.test_the_table_is_the_spec`'s expected dict, add after the `("store", "log")` line:
```python
            ("store", "records"): ("dir", "hermes-broker", "hermes", 0o2750),
```
2. Beside `test_log_dir_mode_is_the_governance_lib_constant`, add:
```python
    def test_records_dir_mode_is_the_governance_lib_constant(self):
        rec = [e for e in H.LAYOUT if e.relpath == "records"][0]
        self.assertEqual(rec.mode, H.governance_lib.RECORDS_DIR_MODE)
```
3. In `TestCheck`, beside the existing `approvals` mode control, add a firing control:
```python
    def test_a_wrong_mode_on_records_is_reported(self):
        os.chmod(os.path.join(self.store, "records"), 0o770)
        problems = H.check(self.store, self.spool, self.resolver)
        self.assertEqual(len(problems), 1, problems)
        self.assertIn("expected hermes-broker:hermes 2750", problems[0])
```
(Read the neighbouring `approvals` test first and match its exact call signature for `H.check`
and its fixture helper — `make_layout` must create the new directory too, which it will once the
row exists, since it builds from `H.LAYOUT`.)

- [ ] **Step 6: Run them and watch them fail**

Run: `python3 infra/hermes-agent/bin/host_layout.test.py -v`
Expected: `test_the_table_is_the_spec` FAILS on the missing `records` key, and the two new tests
fail (`IndexError` on the empty list comprehension; the check test finds no such directory).

- [ ] **Step 7: Add the row**

In `infra/hermes-agent/bin/host_layout.py`, immediately after the `log` entry:

```python
    # F12: run records. The broker owns and writes them; setgid keeps group hermes on the
    # slug dirs so an operator in that group can read without root. Never mounted.
    Entry("store", "records", DIR, "hermes-broker", "hermes",
          governance_lib.RECORDS_DIR_MODE, None),
```

- [ ] **Step 8: Verify layout tests pass**

Run: `python3 infra/hermes-agent/bin/host_layout.test.py -v`
Expected: all OK, including `test_parents_precede_children`.

- [ ] **Step 9: Pin the pre-flight's deliberate omission**

In `infra/hermes-agent/bin/preflight-governance-access.test.py`, add:

```python
class TestRecordsIsNotTheExecutorsBusiness(unittest.TestCase):
    """F12/spec §2.5. READ_WRITE_DIRS and READ_ONLY_DIRS describe what the EXECUTOR needs
    inside the container. records/ is host-side only and has no bind — docker-compose.yml's
    ads-mutator mounts four governance directories and records/ is not one of them. Listing
    it here would make the pre-flight demand access to a path that does not exist in the
    container and false-refuse every run, the mirror of the seen/ coupling F10 fixed."""

    def test_records_is_not_declared(self):
        self.assertNotIn("records", PF.READ_WRITE_DIRS)
        self.assertNotIn("records", PF.READ_ONLY_DIRS)

    def test_control_the_dirs_it_does_declare(self):
        """Without this, the assertion above would pass against empty tuples."""
        self.assertIn("log", PF.READ_WRITE_DIRS)
        self.assertIn("approvals", PF.READ_ONLY_DIRS)
```

(Use whatever alias the file already imports the module under — read its top; `PF` is used in
`run-ads-mutate.test.py`.)

- [ ] **Step 10: Run the whole bin suite and commit**

```bash
python3 infra/hermes-agent/bin/preflight-governance-access.test.py -v; echo "exit $?"
infra/hermes-agent/bin/run-bin-tests.sh; echo "exit $?"
```
Expected: exit 0; the suite count goes from 31 to 31 (no new files, only edits).

```bash
git add infra/hermes-agent/bin/governance_lib.py infra/hermes-agent/bin/governance_lib.test.py \
  infra/hermes-agent/bin/host_layout.py infra/hermes-agent/bin/host_layout.test.py \
  infra/hermes-agent/bin/preflight-governance-access.test.py
git commit -m "feat(hermes): F12 — the store's records/ row and its path helpers

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: Run records are written into the store

**Files:**
- Modify: `infra/hermes-agent/bin/persist_run_record_shim.py` (module docstring; `persist()`)
- Modify: `infra/hermes-agent/bin/persist-run-record.py`
- Test: `infra/hermes-agent/bin/persist-run-record.test.py`

**Interfaces:**
- Consumes: `governance_lib.records_dir/record_path/records_timeline_path` (Task 1).
- Produces: `persist(record_dir, result, root=None) -> str` — `record_dir` is the per-client
  records directory (`governance_lib.records_dir(slug)`); returns the result file's path. Task 5
  drives it as `hermes-broker`.

- [ ] **Step 1: Re-point the tests first**

In `infra/hermes-agent/bin/persist-run-record.test.py`, change the fixture so the destination is a
records directory rather than a vault, and keep every containment case. Read the file first; the
edit is mechanical:
- wherever the test builds `<tmp>/vault` and passes it to `P.persist(...)`, build
  `<tmp>/governance/records/<slug>` instead and pass that;
- the result file is now `<records>/<slug>/<cid>.result.json` (no `changes/` component) —
  update the expected path;
- `timeline.md` stays directly under the per-client directory;
- **keep all three refusal cases unchanged in spirit**: `timeline.md` symlinked outside the tree,
  a hardlinked result file, a non-regular destination — each must still raise `P.PersistRefused`.

Add one new mode assertion:

```python
    def test_the_record_and_timeline_are_group_readable_not_umask_dependent(self):
        """F12: UMask=0077 must not make records unreadable. The modes are explicit."""
        old = os.umask(0o077)
        try:
            path = P.persist(self.records, RESULT)
        finally:
            os.umask(old)
        self.assertEqual(stat.S_IMODE(os.stat(path).st_mode), 0o640)
        timeline = os.path.join(self.records, "timeline.md")
        self.assertEqual(stat.S_IMODE(os.stat(timeline).st_mode), 0o640)
```

- [ ] **Step 2: Run them and watch them fail**

Run: `python3 infra/hermes-agent/bin/persist-run-record.test.py -v`
Expected: failures showing the old vault-shaped path (a `changes/` component, or a refusal because
the fixture no longer looks like a vault). Record the actual output.

- [ ] **Step 3: Move the destination**

In `infra/hermes-agent/bin/persist_run_record_shim.py`:

1. **Rewrite the module docstring's threat paragraph.** It currently says this step "WRITES INTO
   THE ONE TREE HERMES CAN WRITE" and cites the 2026-08-19 symlink demonstration against the vault.
   After this change the destination is `records/` in the store, which is `hermes-broker:hermes
   2750`, unmounted, and not writable by the gateway — so the planted-symlink vector is gone.
   Say exactly that, and say that the containment stays anyway as defence in depth and because a
   future writer or a mis-set mode must not silently become a write primitive. Keep the
   `OPERATIONAL CONSTRAINT (R20(a))` hard-link note, re-pointed at the records tree.
2. In `persist()`, replace the vault/`changes` composition with the records directory:
   - the function's first argument is the per-client records directory;
   - create it if missing, relative to its parent, then set mode `0o750` explicitly with
     `os.fchmod` on an opened dir fd (the setgid parent supplies the group; umask must not
     decide the mode);
   - the result file's basename is `os.path.basename(governance_lib.record_path(slug, cid))` —
     derive it from the helper, never by string-formatting a second definition;
   - keep `_check_dest`, `_open_dir`, `_refuse_if_hardlinked`, `_create_tmp_exclusive`,
     `_open_regular`, the `O_NOFOLLOW` opens and the dir-fd-relative `os.rename`;
   - after creating each file, set mode `0o640` with `os.fchmod` on the open fd, before the
     rename for the result file;
   - rename the internal `vault_real` / `vfd` identifiers to records-shaped names so the code does
     not lie about what it is writing.

In `infra/hermes-agent/bin/persist-run-record.py`, replace the vault resolution:

```python
        rec = vault_lib.resolve(args.client)      # still refuses an unregistered slug
        P.persist(governance_lib.records_dir(rec["slug"]), res)
```
and import `governance_lib`. Keep the existing exception tuple and the exit-2 contract.

- [ ] **Step 4: Verify**

```bash
python3 infra/hermes-agent/bin/persist-run-record.test.py -v; echo "exit $?"
python3 infra/hermes-agent/bin/run-ads-mutate.test.py -v; echo "exit $?"
infra/hermes-agent/bin/run-bin-tests.sh; echo "exit $?"
```
Expected: all exit 0. `run-ads-mutate.test.py` must still prove the persist banner is unmissable
and that the executor's status wins — if either broke, the move changed behaviour it must not.

- [ ] **Step 5: Commit**

```bash
git add infra/hermes-agent/bin/persist_run_record_shim.py infra/hermes-agent/bin/persist-run-record.py \
  infra/hermes-agent/bin/persist-run-record.test.py
git commit -m "fix(hermes): F12 — run records are written into the governance store

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: Approval artifacts get deterministic ownership and modes

**Files:**
- Modify: `infra/hermes-agent/bin/changeset_lib.py` (`_atomic_write_json`, `write_snapshot_bytes`, `_approval_lock`)
- Test: `infra/hermes-agent/bin/changeset_lib.test.py`

**Interfaces:**
- Produces: `changeset_lib.APPROVAL_ARTIFACT_MODE = 0o640`, `changeset_lib.APPROVAL_LOCK_MODE = 0o660`,
  and `_apply_owner_mode(fd, mode)`. Task 5 asserts the resulting owner and mode with real identities.

**Context the implementer needs:** all three `_atomic_write_json` call sites
(`changeset_lib.py:499` in `write_approval`, `:825` in `reserve_approval`, `:887` in
`record_outcome`) write approval records into `approvals/`, so applying the helper inside that
function is uniform and correct. Do not widen it to other writers.

- [ ] **Step 1: Write the failing mode tests**

In `infra/hermes-agent/bin/changeset_lib.test.py` add a class (match the file's existing fixture
style for building a store root and a client):

```python
class TestApprovalArtifactModes(unittest.TestCase):
    """F12: with UMask=0077 (the §6 hardening) the executor must still be able to READ an
    approval, and the broker must still be able to WRITE the lock sidecar. Neither may
    depend on the umask of whoever ran approve-changeset."""

    def test_approval_and_snapshot_are_0640_under_a_hostile_umask(self):
        old = os.umask(0o077)
        try:
            digest = C.write_snapshot_bytes(SLUG, CID, b'{"actions": []}\n')
            C.write_approval(SLUG, CID, digest, "operator", NOW, 24)
        finally:
            os.umask(old)
        for p in (governance_lib.approval_path(SLUG, CID),
                  governance_lib.snapshot_path(SLUG, CID)):
            self.assertEqual(stat.S_IMODE(os.stat(p).st_mode), 0o640, p)

    def test_the_lock_sidecar_is_0660_under_a_hostile_umask(self):
        old = os.umask(0o077)
        try:
            digest = C.write_snapshot_bytes(SLUG, CID, b'{"actions": []}\n')
            C.write_approval(SLUG, CID, digest, "operator", NOW, 24)
        finally:
            os.umask(old)
        lock = governance_lib.approval_lock_path(SLUG, CID)
        self.assertEqual(stat.S_IMODE(os.stat(lock).st_mode), 0o660, lock)

    def test_control_the_umask_really_is_hostile(self):
        """Without this the two tests above could pass on a lenient umask and prove nothing."""
        old = os.umask(0o077)
        try:
            p = os.path.join(self.tmp, "probe")
            with open(p, "w") as f:
                f.write("x")
            self.assertEqual(stat.S_IMODE(os.stat(p).st_mode), 0o600)
        finally:
            os.umask(old)
```

- [ ] **Step 2: Run them and watch them fail**

Run: `python3 infra/hermes-agent/bin/changeset_lib.test.py -v`
Expected: the two mode tests FAIL with `0o600 != 0o640` (approval/snapshot) and the lock test
fails at `0o600 != 0o660`. The control passes. Record the output.

- [ ] **Step 3: Add the helper and apply it**

In `infra/hermes-agent/bin/changeset_lib.py`, near the top add `import grp, pwd` to the existing
imports and:

```python
# F12. Every approval artifact's mode is set EXPLICITLY on the open fd, never left to the
# umask: with UMask=0077 (the §6 hardening) an approval written 0600 is unreadable to the
# executor that must verify it, and a 0600 lock sidecar cannot be flocked by the broker —
# which is exactly how F12 was found (root-owned 0600 sidecar, reserve_approval fails on
# the first apply). fchmod/fchown on the fd, not chmod/chown on the path: a path-based
# call can be redirected by a symlink swapped in between create and chmod.
APPROVAL_ARTIFACT_MODE = 0o640      # approval record, change-set snapshot: executor reads
APPROVAL_LOCK_MODE = 0o660          # lock sidecar: the broker must be able to flock it
APPROVAL_OWNER_USER = "hermes-broker"
APPROVAL_OWNER_GROUP = "hermes"


def _apply_owner_mode(fd, mode):
    """Set MODE on FD, and (as root, on Linux) owner hermes-broker:hermes.

    Non-root callers still get the explicit mode; ownership is left alone, because a
    non-root approve cannot produce broker-owned files and approve-changeset.py refuses
    that case on Linux anyway. Groups are resolved BY NAME — a missing group is a refusal,
    never a guessed gid.
    """
    os.fchmod(fd, mode)
    if not sys.platform.startswith("linux") or os.geteuid() != 0:
        return
    try:
        uid = pwd.getpwnam(APPROVAL_OWNER_USER).pw_uid
        gid = grp.getgrnam(APPROVAL_OWNER_GROUP).gr_gid
    except KeyError as e:
        raise RuntimeError(
            "F12: cannot set approval ownership — %s. Create the users and groups first "
            "(README 'VPS deploy sequence' step 1)." % e)
    os.fchown(fd, uid, gid)
```

Then:
- in `_atomic_write_json`, after `os.fsync(f.fileno())` and **before** `os.replace(tmp, path)`,
  call `_apply_owner_mode(f.fileno(), APPROVAL_ARTIFACT_MODE)` so the file that lands is never
  briefly wrong;
- in `write_snapshot_bytes`, the same, on the `out` fd before `os.replace`;
- in `_approval_lock`, after `fd = os.open(p, os.O_CREAT | os.O_RDWR, 0o600)`, call
  `_apply_owner_mode(fd, APPROVAL_LOCK_MODE)`.

- [ ] **Step 4: Verify**

```bash
python3 infra/hermes-agent/bin/changeset_lib.test.py -v; echo "exit $?"
infra/hermes-agent/bin/run-bin-tests.sh; echo "exit $?"
```
Expected: exit 0 both. If any pre-existing test asserted `0600` on these artifacts, that assertion
encoded the defect — update it and say so in the report.

- [ ] **Step 5: Commit**

```bash
git add infra/hermes-agent/bin/changeset_lib.py infra/hermes-agent/bin/changeset_lib.test.py
git commit -m "fix(hermes): F12 — approval artifacts get explicit modes and ownership

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: `approve-changeset.py` requires root on Linux

**Files:**
- Modify: `infra/hermes-agent/bin/approve-changeset.py` (`main`)
- Test: `infra/hermes-agent/bin/approve-changeset.test.py`

- [ ] **Step 1: Write the failing tests**

```python
class TestRootRequirement(unittest.TestCase):
    """F12: on Linux the proposal lives in the gateway-owned vault (data/ is 700 uid 10000),
    so reading it needs root; and a non-root writer leaves artifacts the broker cannot
    reserve. Refusing up front beats failing hours later at apply time, where it would look
    like a governance refusal."""

    def test_it_refuses_without_root_on_linux(self):
        with mock.patch.object(A.sys, "platform", "linux"), \
             mock.patch.object(A.os, "geteuid", return_value=1000):
            err = io.StringIO()
            with contextlib.redirect_stderr(err):
                rc = A.main(["--client", "acme-dental", "--changeset", CID,
                             "--operator", "operator"])
        self.assertEqual(rc, 2)
        self.assertIn("sudo", err.getvalue())

    def test_control_it_does_not_refuse_on_darwin(self):
        """The dev flow on a laptop has no uid separation to honour."""
        with mock.patch.object(A.sys, "platform", "darwin"), \
             mock.patch.object(A.os, "geteuid", return_value=1000):
            err = io.StringIO()
            with contextlib.redirect_stderr(err):
                rc = A.main(["--client", "acme-dental", "--changeset", CID,
                             "--operator", "operator"])
        self.assertNotIn("must run as root", err.getvalue())
```

(The second test will fail later for an unrelated reason — a missing registry or change-set — and
that is fine: it asserts only that the ROOT refusal did not fire. `approve-changeset.test.py`
already exists: read its header and reuse its loader alias for the CLI module rather than adding
a second `importlib.util` block — the filename has a hyphen, so it cannot be imported normally.)

- [ ] **Step 2: Run them and watch them fail**

Run: `python3 infra/hermes-agent/bin/approve-changeset.test.py -v`
Expected: the first test fails (no refusal exists yet — it exits for some other reason or not with 2).

- [ ] **Step 3: Add the guard**

As the first statement inside `main()`, before argument parsing does any work that touches the
vault:

```python
    if sys.platform.startswith("linux") and os.geteuid() != 0:
        print("approve-changeset: must run as root on Linux. The proposal lives in the "
              "gateway-owned vault (data/ is 700 uid 10000), and the approval must be left "
              "owned by hermes-broker so the broker can reserve it. Use: "
              "sudo ./changeset.sh approve --client <slug> --changeset <id> "
              "--operator <name> --expect-sha256 <hex>", file=sys.stderr)
        return 2
```

- [ ] **Step 4: Verify and commit**

```bash
python3 infra/hermes-agent/bin/approve-changeset.test.py -v; echo "exit $?"
infra/hermes-agent/bin/run-bin-tests.sh; echo "exit $?"
git add infra/hermes-agent/bin/approve-changeset.py infra/hermes-agent/bin/approve-changeset.test.py
git commit -m "fix(hermes): F12 — approve-changeset refuses non-root on Linux

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: Tier 2 — the failure F12 recorded, reproduced and fixed

**Files:**
- Modify: `infra/hermes-agent/deploy/layout-integration.test.py`

**Context:** this suite already runs as root on Linux CI under `HERMES_REQUIRE_LINUX_INTEGRATION=1`,
creates the README step 1 identities, builds a layout per test via `init-host-layout.py --apply`,
and provides `self.store`, `self.spool`, `self.env`, `self.py(name)`, `self.broker(*argv)` and
`self.gateway(*argv)` (setpriv wrappers). Reuse them; do not build a parallel harness. It prints
`layout-integration: executed N, skipped M` and fails when anything skips under the required flag.

- [ ] **Step 1: Add the records round trip**

```python
class TestRunRecords(Layout):
    """F12 half B, with real identities: the broker writes run records into the store, the
    gateway cannot, and the hermes group can read them."""

    SLUG = "slug-1"

    def register_client(self):
        """vault_lib.resolve refuses an unregistered slug, so the record path needs one."""
        reg = os.path.join(self.store, "registry", "clients.json")
        with open(reg, "w") as f:
            json.dump({"clients": {self.SLUG: {"project": "claude_google_ads",
                                               "customer_id": "1234567890",
                                               "status": "active"}}}, f)
        run(["chown", "root:hermes", reg], check=True)
        run(["chmod", "0640", reg], check=True)

    def persist_as_broker(self, payload):
        """Drive the real CLI the wrapper drives, on stdin, as hermes-broker."""
        p = subprocess.run(BROKER + ["python3", self.py("persist-run-record.py"),
                                     "--client", self.SLUG],
                           input=payload, capture_output=True, text=True, env=self.env)
        return p

    def test_the_broker_writes_a_record_the_group_can_read(self):
        self.register_client()
        cid = "20260923-120000-abcdef01"
        payload = ('HERMES-RESULT-JSON {"changeset_id": "%s", "status": "ok", "applied": 1, '
                   '"finished_at": "2026-09-23T12:00:00Z", "operator": "operator", '
                   '"actions": []}\n' % cid)
        p = self.persist_as_broker(payload)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        rec = os.path.join(self.store, "records", self.SLUG, cid + ".result.json")
        st = os.stat(rec)
        self.assertEqual(stat.S_IMODE(st.st_mode), 0o640, rec)
        self.assertEqual(grp.getgrgid(st.st_gid).gr_name, "hermes")
        self.assertTrue(os.path.isfile(os.path.join(self.store, "records", self.SLUG,
                                                    "timeline.md")))

    def test_the_gateway_cannot_write_into_records(self):
        self.register_client()
        target = os.path.join(self.store, "records", self.SLUG, "planted.json")
        r = self.gateway("python3", "-c",
                         "import sys; open(sys.argv[1], 'w').write('x')", target)
        self.assertNotEqual(r.returncode, 0, "the gateway wrote into records/: %s" % r.stdout)

    def test_control_a_group_writable_records_dir_lets_the_gateway_write(self):
        """Proves the refusal above comes from the MODE, not from something unrelated."""
        self.register_client()
        d = os.path.join(self.store, "records", self.SLUG)
        os.makedirs(d, exist_ok=True)
        os.chmod(d, 0o770)
        run(["chgrp", "hermes", d], check=True)
        target = os.path.join(d, "planted.json")
        r = self.gateway("python3", "-c",
                         "import sys; open(sys.argv[1], 'w').write('x')", target)
        self.assertEqual(r.returncode, 0, r.stderr)
```

- [ ] **Step 2: Add the approval round trip — the centrepiece**

```python
class TestApprovalOwnership(Layout):
    """F12 half A, the exact failure the finding records: root approves, then the broker
    must be able to reserve. Before the fix the lock sidecar is root-owned 0600 and
    reserve_approval fails on the first apply."""

    SLUG = "slug-1"
    CID = "20260923-120000-abcdef01"

    def approve_as_root(self):
        """Write the snapshot + approval the way approve-changeset does, as root."""
        code = (
            "import sys; sys.path.insert(0, %r);"
            "import changeset_lib as C, datetime;"
            "d = C.write_snapshot_bytes(%r, %r, b'{\"actions\": []}\\n');"
            "C.write_approval(%r, %r, d, 'operator',"
            " datetime.datetime(2026, 9, 23, 12, 0, 0, tzinfo=datetime.timezone.utc), 24)"
            % (self.bin, self.SLUG, self.CID, self.SLUG, self.CID))
        return run(["python3", "-c", code], env=self.env)

    def reserve_as_broker(self):
        code = (
            "import sys; sys.path.insert(0, %r);"
            "import changeset_lib as C, datetime;"
            "C.reserve_approval(%r, %r, '00000000-0000-4000-8000-000000000000',"
            " datetime.datetime(2026, 9, 23, 12, 5, 0, tzinfo=datetime.timezone.utc))"
            % (self.bin, self.SLUG, self.CID))
        return run(BROKER + ["python3", "-c", code], env=self.env)

    def test_root_approves_and_the_broker_can_reserve(self):
        r = self.approve_as_root()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        lock = os.path.join(self.store, "approvals", self.SLUG,
                            self.CID + ".approval.lock")
        st = os.stat(lock)
        self.assertEqual(stat.S_IMODE(st.st_mode), 0o660, lock)
        self.assertEqual(pwd.getpwuid(st.st_uid).pw_name, "hermes-broker")
        r = self.reserve_as_broker()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_firing_control_a_root_owned_0600_lock_breaks_reserve(self):
        """F12 as it was: this is the state the fix removes. If this ever passes, the
        assertion above is not proving what it claims."""
        self.approve_as_root()
        lock = os.path.join(self.store, "approvals", self.SLUG,
                            self.CID + ".approval.lock")
        os.chown(lock, 0, 0)
        os.chmod(lock, 0o600)
        r = self.reserve_as_broker()
        self.assertNotEqual(r.returncode, 0,
                            "the broker reserved through a root-owned 0600 lock")

    def test_the_executor_uid_can_read_the_approval(self):
        self.approve_as_root()
        approval = os.path.join(self.store, "approvals", self.SLUG,
                                self.CID + ".approval.json")
        r = self.gateway("python3", "-c",
                         "import sys; open(sys.argv[1]).read()", approval)
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_control_a_0600_approval_is_unreadable_to_the_executor(self):
        self.approve_as_root()
        approval = os.path.join(self.store, "approvals", self.SLUG,
                                self.CID + ".approval.json")
        os.chmod(approval, 0o600)
        r = self.gateway("python3", "-c",
                         "import sys; open(sys.argv[1]).read()", approval)
        self.assertNotEqual(r.returncode, 0)
```

Add `grp`, `pwd`, `json`, `stat` to the module's imports if they are not already there, and
`self.bin` is the private `bin/` copy the `Layout` fixture already builds.

- [ ] **Step 3: Check the skip path locally**

```bash
python3 -m py_compile infra/hermes-agent/deploy/layout-integration.test.py; echo "compile $?"
python3 infra/hermes-agent/deploy/layout-integration.test.py; echo "exit $?"
HERMES_REQUIRE_LINUX_INTEGRATION=1 python3 infra/hermes-agent/deploy/layout-integration.test.py; echo "required exit $?"
```
Expected on darwin: compile 0; `SKIPPED — not Linux`, exit 0; with the flag, exit 1.
**The Tier 2 bodies cannot be run here** — they need Linux, root and real identities. CI is the
proof, exactly as F9's Tier 2 was.

- [ ] **Step 4: Commit**

```bash
git add infra/hermes-agent/deploy/layout-integration.test.py
git commit -m "test(hermes): F12 Tier 2 — records round trip and root-approves/broker-reserves

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 6: Docs and the findings record

**Files:**
- Modify: `infra/hermes-agent/README.md`
- Modify: `infra/hermes-agent/deploy/BRING-UP.md` (the rehearsal gate's prerequisites)
- Modify: `docs/superpowers/specs/2026-09-21-vps-first-bring-up-findings.md`

- [ ] **Step 1: README**

1. In the change-set section (around README:526 and :558, where `./changeset.sh approve …` is
   shown), prefix the Linux invocations with `sudo` and add:
   > **`approve` must run as root on Linux.** The proposal lives in the gateway-owned vault
   > (`data/` is `700` uid 10000), and the approval, snapshot and lock sidecar must be left
   > `hermes-broker:hermes` so the broker can reserve them. The tool refuses non-root on Linux
   > rather than writing artifacts that fail later, at apply time (F12).
2. Where run records are described as living in the client vault, correct them to
   `<store>/records/<slug>/<cid>.result.json` and `<store>/records/<slug>/timeline.md`, and add:
   > Applied changes no longer appear in the vault's `timeline.md`: that file is the AUDIT path's
   > history, written from inside the container. The mutation path records to the store, where
   > the broker can write and the executor is never given access (F12).
3. Extend the container-path warning at README:533 to name the records root: these tools resolve
   `HERMES_GOVERNANCE_ROOT` and default to the CONTAINER path, so host invocations must set it
   (the broker unit does; `hostenv.sh` does for the wrappers).

- [ ] **Step 2: BRING-UP's rehearsal gate**

In `## Gate: First Approved Request (Rehearsal)`, change the prerequisites so F12 is landed:
> **It needs:** F9 (landed), F12 (landed — approvals are written `hermes-broker:hermes` and run
> records go to `<store>/records/`), `.env.gaw` carrying the WRITE Google Ads credential, and
> Phase 6 passed. After pulling F12, run README step 2's layout commands again so `records/` is
> created (`init-host-layout.py --apply`, then `--check` as `hermes-broker`); no unit changes, so
> nothing restarts.

- [ ] **Step 3: The findings record**

Change the F12 heading to `### F12: approvals and run records vs data/vaults — fixed (PR #<N>)`,
prefix its existing body with `**Was open:**`, and append:

```markdown
**Fix (PR #<N>).** Run records move to `<store>/records/<slug>/` — `hermes-broker:hermes 2750`,
files `0640`, created by `init-host-layout.py` — so the mutation path never writes the vault.
The executor could not have written it either: `ads-mutator` has no vault mount, and giving it
one would widen the proxy's pinned set (F9). Approval artifacts get explicit modes and ownership
set on the open fd: approval and snapshot `0640`, lock sidecar `0660`, owner
`hermes-broker:hermes` when root — killing both the root-owned `0600` sidecar that broke
`reserve_approval` and the umask dependence that `UMask=0077` would have made fatal.
`approve-changeset.py` now refuses non-root on Linux with a message naming `sudo`.

**Proven:** Tier 2 on Linux CI reproduces the recorded failure — root approves, the broker
reserves — with a firing control that forces the old root-owned `0600` sidecar and shows
`reserve_approval` still failing. A second round trip shows the broker writing a record the
`hermes` group can read and the gateway unable to write there, with a group-writable control.

**Deliberate loss:** applied changes no longer appear in the vault's `timeline.md`, which
`run-trend-audit.sh` feeds the analyst as client history. The audit path still writes that file;
governance is unaffected (the fsynced audit log is the authoritative record). Revisit as its own
design if the analyst is shown to need it.

**Still open:** F14 (a Compose failure reported as "nothing was mutated") and the §6 hardening
gates, including `UMask=0077`, which this fix makes safe to land but does not land.
```

Update the outcome table and open-items list: F12 leaves the open list; the rehearsal gate's
remaining prerequisite is `.env.gaw`.

- [ ] **Step 4: Commit**

```bash
git add infra/hermes-agent/README.md infra/hermes-agent/deploy/BRING-UP.md \
  docs/superpowers/specs/2026-09-21-vps-first-bring-up-findings.md
git commit -m "docs(hermes): F12 fixed — records in the store, approvals owned by the broker

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 7: Final review, PR, and the box step

- [ ] **Step 1: Full local suites (never pipe into `tail`)**

```bash
nlog=$(mktemp); node scripts/run-all-tests.js > "$nlog" 2>&1; echo "node exit $?"; grep 'suites passed' "$nlog"
blog=$(mktemp); infra/hermes-agent/bin/run-bin-tests.sh > "$blog" 2>&1; echo "bin exit $?"; grep 'suites passed' "$blog"
python3 infra/hermes-agent/deploy/units.test.py; echo "units exit $?"
python3 infra/hermes-agent/deploy/provision.test.py; echo "provision exit $?"
python3 infra/hermes-agent/deploy/layout-integration.test.py; echo "tier2 exit $?"
python3 infra/hermes-agent/deploy/bind-agreement-integration.test.py; echo "f9 tier2 exit $?"
```
Expected: node 22/22, bin 31/31 (or higher if Task 4 created a new test file), units OK, provision
OK, both integration suites `SKIPPED — not Linux` with exit 0. Record the actual counts.

- [ ] **Step 2: Final whole-branch review**

Dispatch a fresh reviewer over `git diff origin/main...HEAD` with the spec and this plan, on the
most capable model. Name these risks for it: that the persist move silently weakened a containment
check; that `_apply_owner_mode` could raise on a host without the groups and break the laptop dev
flow; that the pre-flight was "helpfully" taught about `records`; and that a Tier 2 control could
pass for an unrelated reason. Fix what it confirms, re-run Step 1, commit by explicit path.

- [ ] **Step 3: Redaction scan over added lines, with a live control**

```bash
added=$(git diff origin/main...HEAD -U0 | grep '^+' | grep -v '^+++')
printf '%s\n' "$added" | grep -niE 'dentaledge|[0-9]{3}-[0-9]{3}-[0-9]{4}|\b[0-9]{10}\b' \
  | grep -vE '"?(1234567890|9998887776|9999999999)"?'; echo "scan exit: $?"
printf 'control: customer 5551234567 and 555-123-4567\n' \
  | grep -niE 'dentaledge|[0-9]{3}-[0-9]{3}-[0-9]{4}|\b[0-9]{10}\b'; echo "control exit: $?"
```
Expected: the scan prints nothing and exits 1; the control prints its line and exits 0. Matches in
this plan's own quoted scan recipe are benign — read any hit by eye.

- [ ] **Step 4: Confirm the diff holds only this plan's files**

Run: `git diff --stat origin/main...HEAD`
Expected: the file map, plus the spec and this plan. Nothing under `.project-brain/`, `evals/`,
`CLAUDE.md`, and **no change to** `bin/docker-create-proxy.py`, either unit file, or
`docker-compose.yml`.

- [ ] **Step 5: Push and open the PR — ask the operator first**

Pushing and opening a PR are outward-facing. Ask, then push and open. The PR body must state:
what landed; that the proxy, its allow-list and the seven binds are untouched; the deliberate
`timeline.md` loss; the new `sudo` requirement for `approve`; the box step from spec §4; the Tier 2
executed count from the PR run; and what stays unproven (F14, the §6 hardening, and that no real
apply can be exercised while the kill switch is absent). End with
`🤖 Generated with [Claude Code](https://claude.com/claude-code)`.

- [ ] **Step 6: Fill in the PR number**

Replace every `#<N>` in the findings record with the real number, commit that file by explicit
path, and push.

- [ ] **Step 7: After the operator merges — CI on the merge commit**

```bash
sha=$(gh pr view <N> --json mergeCommit -q .mergeCommit.oid)
id=$(gh run list --commit "$sha" --workflow CI --limit 1 --json databaseId -q '.[0].databaseId')
gh run watch "$id" --exit-status; echo "watch exit $?"
gh run view "$id" --log | grep -E '(layout-integration|bind-agreement): (executed|SKIPPED)'
```
Expected: both `executed N, skipped 0`, run green. Quote both counts to the operator, then hand
over the box step from spec §4 (pull, `--apply`, `--check`; no restart).
