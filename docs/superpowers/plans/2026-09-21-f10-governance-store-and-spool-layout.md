# F10 — Governance Store and Spool Layout Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give a fresh Linux host a documented, reproducible, tested way to create the governance
store and the request spool. Fix the two defects (F10a, F10b) that would make any layout fail on
Linux.

**Architecture:** One layout table (`bin/host_layout.py`) with three operations over it: `check`
(read-only, `lstat` only), `plan` (the dry run) and `apply` (root only; creates what is missing,
refuses on anything that exists and is wrong, never repairs). An operator CLI
(`bin/init-host-layout.py`) wraps them, and the broker unit runs `--check` before the pre-flight.
The spool moves out of the gateway-owned `data/` to `/var/lib/hermes/spool`. Spool files are
written `0640`. The broker verifies `.quarantine` before it moves anything into it. Tier 1 tests
run unprivileged everywhere. A Tier 2 suite runs as root on the Linux CI runner, with real uids,
and must prove it ran.

**Tech Stack:** Python 3 stdlib only (`unittest`, `os`, `pwd`, `grp`, `stat`), POSIX shell,
systemd unit files, Docker Compose, GitHub Actions (`ubuntu-latest`), `setpriv` (util-linux).

**Spec:** `docs/superpowers/specs/2026-09-21-f10-governance-store-and-spool-layout-design.md`
(amended with R1–R3 in `c3282ac`). Read it before starting any task. Where this plan and the code
disagree, the code wins. Stop and report the disagreement rather than bending the code to fit
the plan.

## Global Constraints

- **Mutation stays disabled.** Nothing creates `control/mutation-enabled`. No task touches the VPS.
- **Do not widen anything to make something pass.** No mode beyond the spec's §3.2/§3.3 tables,
  and no proxy allow-list change. F9 is out of scope.
- **Every new check needs a firing control:** a test that runs the check against a bad layout and
  shows it fails.
- **Stdlib only** in `infra/hermes-agent/bin/` and `infra/hermes-agent/deploy/*.py`. Invoke
  `python3`, never `python`.
- **Linux ownership cannot be proven on darwin.** Tier 2 runs on the CI runner only. Say plainly
  what stays unproven (spec §5.3).
- **NEVER run `docker compose config`.** It prints the `env_file` secrets in cleartext.
- **No client names, customer ids, campaign ids, metrics or drafts** in any added line. Sanctioned
  fixtures only: `acme-dental`, `acme`, `other-clinic`, `slug-1`, `"1234567890"`, `"9998887776"`,
  `"9999999999"`.
- **Stage by explicit path only.** Never `git add -A`, `git add .`, `.project-brain/`, `evals/`,
  or `CLAUDE.md`. The working tree carries unrelated operator changes; leave them alone.
- **Suites:** `infra/hermes-agent/bin/run-bin-tests.sh` (bin, discovered),
  `python3 infra/hermes-agent/deploy/units.test.py`,
  `python3 infra/hermes-agent/deploy/provision.test.py`, `node scripts/run-all-tests.js`.
  Baseline on darwin before this plan: bin 27/27, node 22/22.
- **Paths below are repo-relative.** `bin/` means `infra/hermes-agent/bin/`, and `deploy/` means
  `infra/hermes-agent/deploy/`.

## File map

| File | Status | Responsibility |
|---|---|---|
| `bin/host_layout.py` | create | The layout table, the name→id resolver, and `check` / `plan` / `apply` |
| `bin/host_layout.test.py` | create | Tier 1 tests for the table, `check`, `plan` and `apply` |
| `bin/init-host-layout.py` | create | The operator CLI: dry run / `--apply` / `--check`, exit 0/1/2 |
| `bin/init-host-layout.test.py` | create | Tier 1 CLI tests |
| `bin/spool_lib.py` | modify | `SPOOL_FILE_MODE = 0o640`; `write_result` `fchmod`s its fd (F10a) |
| `bin/spool_lib.test.py` | modify | Result-mode tests under two umasks |
| `bin/hermes-syscall.py` | modify | `submit` `fchmod`s its fd (F10a) |
| `bin/hermes-syscall.test.py` | modify | Request-mode tests under two umasks |
| `bin/hermes-broker.py` | modify | `_discard`: `rmdir` step, then quarantine verification (F10b, R1) |
| `bin/hermes-broker.test.py` | modify | Quarantine and planted-directory tests |
| `bin/preflight-governance-access.py` | modify | One line for a missing or unenterable root; "missing" child; new `REMEDY` |
| `bin/preflight-governance-access.test.py` | modify | New tests, plus three deliberate edits to existing ones (Task 6) |
| `bin/migrate_governance_shim.py` | modify | `bootstrap_logs`' missing-`log/` message names `init-host-layout.py` |
| `deploy/hermes-broker.service` | modify | New spool path, `ReadWritePaths`, layout `--check` in `ExecStartPre`, comment fix |
| `deploy/units.test.py` | modify | `ExecStartPre` order and the spool-path contract across unit, `.env.example`, compose |
| `docker-compose.yml` | modify | Gateway mounts `${HERMES_SPOOL_DIR:?…}` at `/opt/data/spool` |
| `.env.example` | modify | `HERMES_SPOOL_DIR`; governance comment no longer says "mode 700" |
| `deploy/layout-integration.test.py` | create | Tier 2: root, real ids, attack probes, mount-point probe, executed count |
| `.github/workflows/ci.yml` | modify | Tier 2 step under `sudo` |
| `README.md` | modify | Spool layout, governance store, ownership, syscall deploy step 1, VPS step 2 |
| `deploy/BRING-UP.md` | modify | Phase 2 layout, Phase 6 banner narrowed to F9 |
| `docs/superpowers/specs/2026-09-21-vps-first-bring-up-findings.md` | modify | F10 fixed; F12 added; effect on F9; open items |

---

### Task 1: The layout table and `check`

**Files:**
- Create: `infra/hermes-agent/bin/host_layout.py`
- Test: `infra/hermes-agent/bin/host_layout.test.py`

**Interfaces:**
- Consumes: `governance_lib.EXECUTOR_GID` (10000), `governance_lib.LOG_DIR_MODE` (0o2750).
- Produces (later tasks rely on these exact names):
  - `DEFAULT_STORE_ROOT = "/var/lib/hermes/governance"`, `DEFAULT_SPOOL_ROOT = "/var/lib/hermes/spool"`
  - `DIR`, `FILE` (the strings `"dir"`, `"file"`)
  - `Entry(root_key, relpath, kind, owner, group, mode, content)`, and `LAYOUT: tuple[Entry, ...]`
    ordered parent-first
  - `Step(action, path, detail, implied, entry)`, where `action` is one of `"ok"`, `"create"`,
    `"mismatch"`
  - `class LayoutError(Exception)`
  - `class Resolver(users: dict, groups: dict)` with `.uid(name) -> int` and `.gid(name) -> int`,
    each raising `LayoutError` for an unknown name
  - `system_resolver(getpwnam=pwd.getpwnam, getgrnam=grp.getgrnam) -> Resolver`, which raises
    `LayoutError` if `hermes` resolves to anything but 10000
  - `entry_path(entry, store_root, spool_root) -> str`
  - `expected(entry) -> str` (for example `"root:hermes 0640"`)
  - `check_ancestors(root, trusted_uids=(0,), top="/") -> list[tuple[str, str]]` (path, detail)
  - `plan(store_root, spool_root, resolver, ancestor_uids=(0,), ancestor_top="/") -> list[Step]`
  - `check(store_root, spool_root, resolver, ancestor_uids=(0,), ancestor_top="/") -> list[str]`,
    where each string is `"<path>: <detail>"`

- [ ] **Step 1: Write the failing tests**

Create `infra/hermes-agent/bin/host_layout.test.py`:

```python
import os, shutil, stat, sys, tempfile, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import host_layout as H


def make_layout(store, spool):
    """Build the layout BY HAND, as the test process's own user. Every mode in the table
    keeps owner rwx on directories, so cleanup never needs a chmod first."""
    for e in H.LAYOUT:
        p = H.entry_path(e, store, spool)
        if e.kind == H.DIR:
            os.mkdir(p)
        else:
            with open(p, "wb") as f:
                f.write(e.content)
        os.chmod(p, e.mode)


class Base(unittest.TestCase):
    """Tier 1: one unprivileged user. The resolver maps every table name onto that user's
    own uid/gid, so a correct layout is buildable without root. A WRONG owner or group is
    produced by pointing a name at some other id, never by chown."""

    def setUp(self):
        self.base = os.path.realpath(tempfile.mkdtemp(prefix="host-layout-"))
        self.addCleanup(shutil.rmtree, self.base, True)
        self.uid, self.gid = os.getuid(), os.getgid()
        self.set_roots(self.base)
        self.resolver = H.Resolver(
            users={"root": self.uid, "hermes-broker": self.uid},
            groups={"hermes": self.gid, "hermes-broker": self.gid})

    def set_roots(self, parent):
        self.store = os.path.join(parent, "governance")
        self.spool = os.path.join(parent, "spool")

    def kw(self, **over):
        # Ancestors are walked only up to self.base, and trust this user as well as root:
        # a tempdir's real ancestors (/var/folders on darwin, /tmp on Linux) are exactly
        # what production must refuse, and are exercised in Tier 2.
        kw = dict(resolver=self.resolver, ancestor_uids=(0, self.uid),
                  ancestor_top=self.base)
        kw.update(over)
        return kw

    def check(self, **over):
        return H.check(self.store, self.spool, **self.kw(**over))


class TestTable(unittest.TestCase):
    def test_the_table_is_the_spec(self):
        """Spec §3.2 and §3.3, pinned. A change here is a security design change and must
        come with a spec change, not a test edit."""
        got = {(e.root_key, e.relpath): (e.kind, e.owner, e.group, e.mode)
               for e in H.LAYOUT}
        self.assertEqual(got, {
            ("store", ""): ("dir", "root", "hermes", 0o750),
            ("store", "approvals"): ("dir", "hermes-broker", "hermes", 0o2750),
            ("store", "control"): ("dir", "root", "hermes", 0o2750),
            ("store", "control/.locks"): ("dir", "hermes-broker", "hermes-broker", 0o700),
            ("store", "registry"): ("dir", "root", "hermes", 0o2750),
            ("store", "registry/clients.json"): ("file", "root", "hermes", 0o640),
            ("store", "log"): ("dir", "root", "hermes", 0o2750),
            ("store", "seen"): ("dir", "hermes-broker", "hermes-broker", 0o700),
            ("spool", ""): ("dir", "root", "hermes", 0o750),
            ("spool", "requests"): ("dir", "hermes-broker", "hermes", 0o3770),
            ("spool", "requests/.quarantine"): ("dir", "hermes-broker", "hermes-broker", 0o700),
            ("spool", "results"): ("dir", "hermes-broker", "hermes", 0o2750),
        })

    def test_log_dir_mode_is_the_governance_lib_constant(self):
        log = [e for e in H.LAYOUT if e.relpath == "log"][0]
        self.assertEqual(log.mode, H.governance_lib.LOG_DIR_MODE)

    def test_the_registry_starts_as_zero_clients(self):
        reg = [e for e in H.LAYOUT if e.relpath == "registry/clients.json"][0]
        self.assertEqual(reg.content, b"{}\n")

    def test_parents_precede_children(self):
        seen = set()
        for e in H.LAYOUT:
            parent = os.path.dirname(e.relpath)
            if e.relpath:
                self.assertIn((e.root_key, parent), seen, e)
            seen.add((e.root_key, e.relpath))

    def test_default_roots(self):
        self.assertEqual(H.DEFAULT_STORE_ROOT, "/var/lib/hermes/governance")
        self.assertEqual(H.DEFAULT_SPOOL_ROOT, "/var/lib/hermes/spool")


class TestCheck(Base):
    def setUp(self):
        super().setUp()
        make_layout(self.store, self.spool)

    def test_control_the_correct_layout_has_no_problems(self):
        self.assertEqual(self.check(), [])

    def test_a_missing_entry_is_reported_as_missing(self):
        os.rmdir(os.path.join(self.store, "seen"))
        problems = self.check()
        self.assertEqual(len(problems), 1, problems)
        self.assertIn("seen", problems[0])
        self.assertIn("missing", problems[0])
        self.assertIn("expected dir hermes-broker:hermes-broker 0700", problems[0])

    def test_a_missing_root_is_one_problem_not_a_cascade(self):
        shutil.rmtree(self.spool)
        problems = self.check()
        self.assertEqual(len(problems), 1, problems)
        self.assertTrue(problems[0].startswith(self.spool + ":"), problems)

    def test_a_missing_setgid_bit_is_caught(self):
        os.chmod(os.path.join(self.store, "approvals"), 0o750)
        problems = self.check()
        self.assertEqual(len(problems), 1, problems)
        self.assertIn("mode 0750", problems[0])
        self.assertIn("expected hermes-broker:hermes 2750", problems[0])

    def test_a_missing_sticky_bit_is_caught(self):
        os.chmod(os.path.join(self.spool, "requests"), 0o2770)
        problems = self.check()
        self.assertEqual(len(problems), 1, problems)
        self.assertIn("expected hermes-broker:hermes 3770", problems[0])

    def test_a_wrong_owner_is_caught(self):
        r = H.Resolver(users={"root": self.uid, "hermes-broker": self.uid + 4242},
                       groups={"hermes": self.gid, "hermes-broker": self.gid})
        problems = self.check(resolver=r)
        owned = [e for e in H.LAYOUT if e.owner == "hermes-broker"]
        self.assertEqual(len(problems), len(owned), problems)
        for p in problems:
            self.assertIn("expected hermes-broker:", p)

    def test_a_wrong_group_is_caught(self):
        r = H.Resolver(users={"root": self.uid, "hermes-broker": self.uid},
                       groups={"hermes": self.gid + 4242, "hermes-broker": self.gid})
        problems = self.check(resolver=r)
        grouped = [e for e in H.LAYOUT if e.group == "hermes"]
        self.assertEqual(len(problems), len(grouped), problems)

    def test_a_symlink_in_place_of_a_directory_is_caught_and_not_followed(self):
        q = os.path.join(self.spool, "requests", ".quarantine")
        os.rmdir(q)
        target = os.path.join(self.base, "elsewhere")
        os.mkdir(target)
        os.chmod(target, 0o700)          # the target would PASS if it were followed
        os.symlink(target, q)
        problems = self.check()
        self.assertEqual(len(problems), 1, problems)
        self.assertIn("symlink", problems[0])

    def test_a_directory_in_place_of_the_registry_file_is_caught(self):
        reg = os.path.join(self.store, "registry", "clients.json")
        os.unlink(reg)
        os.mkdir(reg)
        os.chmod(reg, 0o640 | 0o100)
        problems = self.check()
        self.assertEqual(len(problems), 1, problems)
        self.assertIn("not a file", problems[0])

    def test_every_mismatch_line_names_the_expected_state(self):
        """R3. The tool never repairs, so a refusal must say what correct is."""
        reg = os.path.join(self.store, "registry", "clients.json")
        os.chmod(reg, 0o644)
        problems = self.check()
        self.assertEqual(len(problems), 1, problems)
        self.assertIn("registry/clients.json", problems[0])
        self.assertIn("mode 0644", problems[0])
        self.assertIn("expected root:hermes 0640", problems[0])


class TestAncestors(Base):
    def setUp(self):
        super().setUp()
        self.mid = os.path.join(self.base, "mid")
        os.mkdir(self.mid)
        os.chmod(self.mid, 0o755)
        self.set_roots(self.mid)
        make_layout(self.store, self.spool)

    def test_control_a_sound_ancestor_chain_passes(self):
        self.assertEqual(self.check(), [])

    def test_a_group_writable_ancestor_is_refused(self):
        os.chmod(self.mid, 0o775)
        problems = self.check()
        self.assertEqual(len(problems), 1, problems)     # one line, not one per root
        self.assertIn(self.mid, problems[0])
        self.assertIn("writable", problems[0])

    def test_a_world_writable_ancestor_is_refused(self):
        os.chmod(self.mid, 0o757)
        problems = self.check()
        self.assertEqual(len(problems), 1, problems)
        self.assertIn("writable", problems[0])

    @unittest.skipIf(os.geteuid() == 0, "as root the test directory IS root-owned")
    def test_an_ancestor_owned_by_an_untrusted_uid_is_refused(self):
        problems = self.check(ancestor_uids=(0,))
        self.assertTrue(any(self.mid in p and "owned by uid" in p for p in problems),
                        problems)

    def test_a_symlinked_ancestor_is_refused(self):
        link = os.path.join(self.base, "link")
        os.symlink(self.mid, link)
        self.set_roots(link)
        problems = self.check()
        self.assertTrue(any(p.startswith(link + ":") and "symlink" in p
                            for p in problems), problems)


class TestSystemResolver(unittest.TestCase):
    class _Pw:
        def __init__(self, uid):
            self.pw_uid = uid

    class _Gr:
        def __init__(self, gid):
            self.gr_gid = gid

    def _lookups(self, users, groups):
        def getpwnam(n):
            if n not in users:
                raise KeyError(n)
            return self._Pw(users[n])

        def getgrnam(n):
            if n not in groups:
                raise KeyError(n)
            return self._Gr(groups[n])
        return getpwnam, getgrnam

    def test_resolves_names_to_ids(self):
        pw, gr = self._lookups({"root": 0, "hermes-broker": 997},
                               {"hermes": 10000, "hermes-broker": 996})
        r = H.system_resolver(pw, gr)
        self.assertEqual((r.uid("hermes-broker"), r.gid("hermes")), (997, 10000))

    def test_refuses_a_hermes_group_that_is_not_the_executor_gid(self):
        pw, gr = self._lookups({"root": 0, "hermes-broker": 997},
                               {"hermes": 1234, "hermes-broker": 996})
        with self.assertRaises(H.LayoutError) as cm:
            H.system_resolver(pw, gr)
        self.assertIn("10000", str(cm.exception))

    def test_an_unknown_user_is_a_refusal_naming_it(self):
        pw, gr = self._lookups({"root": 0}, {"hermes": 10000, "hermes-broker": 996})
        r = H.system_resolver(pw, gr)
        with self.assertRaises(H.LayoutError) as cm:
            r.uid("hermes-broker")
        self.assertIn("hermes-broker", str(cm.exception))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the tests and confirm they fail**

Run: `python3 infra/hermes-agent/bin/host_layout.test.py`
Expected: an import error, `ModuleNotFoundError: No module named 'host_layout'`.

- [ ] **Step 3: Write the module**

Create `infra/hermes-agent/bin/host_layout.py`:

```python
#!/usr/bin/env python3
"""The host layout of the governance store and the request spool (F10). Stdlib-only.

ONE TABLE, three operations over it:
  check  — read-only. lstat only: a symlink is always a problem and is never followed.
  plan   — the dry run: per entry, create / ok / mismatch.
  apply  — root only. Creates what is MISSING. Refuses, before creating anything, if any
           entry that EXISTS is wrong, or any ancestor of either root is unsafe. It never
           chowns or chmods an entry it did not create in this call.

Why "never repair": the same reason bootstrap_logs refuses a missing log/ (ruling R23).
A store with the wrong owner is a store someone else laid down, and it is not safe to
"fix" silently. The operator is shown the expected state and sets it by hand.

Spec: docs/superpowers/specs/2026-09-21-f10-governance-store-and-spool-layout-design.md
§3.2 (store), §3.3 (spool), §4.1 (this module).
"""
import collections, grp, os, pwd, stat, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import governance_lib

DEFAULT_STORE_ROOT = "/var/lib/hermes/governance"
DEFAULT_SPOOL_ROOT = "/var/lib/hermes/spool"

DIR, FILE = "dir", "file"

Entry = collections.namedtuple("Entry", "root_key relpath kind owner group mode content")
Step = collections.namedtuple("Step", "action path detail implied entry")

# Parent-first. Rationale per row in the spec's §3.2 / §3.3 tables. The comments say
# only what a reader of THIS file needs in order not to "simplify" a row.
LAYOUT = (
    # Store root: broker and executor traverse via group; only root renames children.
    Entry("store", "", DIR, "root", "hermes", 0o750, None),
    # The broker reserves and records outcomes; setgid keeps group hermes on the slug dirs.
    Entry("store", "approvals", DIR, "hermes-broker", "hermes", 0o2750, None),
    # Root-owned so ONLY root can create the kill switch. The broker cannot enable mutation.
    Entry("store", "control", DIR, "root", "hermes", 0o2750, None),
    Entry("store", "control/.locks", DIR, "hermes-broker", "hermes-broker", 0o700, None),
    Entry("store", "registry", DIR, "root", "hermes", 0o2750, None),
    # Created as {} only if absent. Its content is never checked or rewritten here.
    Entry("store", "registry/clients.json", FILE, "root", "hermes", 0o640, b"{}\n"),
    # S3-b: no group write on the directory, because write on a directory grants unlink.
    Entry("store", "log", DIR, "root", "hermes", governance_lib.LOG_DIR_MODE, None),
    Entry("store", "seen", DIR, "hermes-broker", "hermes-broker", 0o700, None),
    # Spool root: nobody but root can rename requests/ or results/.
    Entry("spool", "", DIR, "root", "hermes", 0o750, None),
    # Sticky: the gateway cannot unlink or rename broker-owned entries, but the broker, as
    # the directory's owner, can unlink the gateway's. Setgid: new files carry group hermes.
    Entry("spool", "requests", DIR, "hermes-broker", "hermes", 0o3770, None),
    # Pre-created, so the gateway can never claim the name first (F10b).
    Entry("spool", "requests/.quarantine", DIR, "hermes-broker", "hermes-broker", 0o700, None),
    # Group read-only: the gateway reads results and can no longer forge one.
    Entry("spool", "results", DIR, "hermes-broker", "hermes", 0o2750, None),
)


class LayoutError(Exception):
    """A refusal. apply() never leaves a partial layout behind one."""


class Resolver:
    """Names to ids. system_resolver() fills it from pwd/grp; tests build one directly."""

    def __init__(self, users, groups):
        self._users = dict(users)
        self._groups = dict(groups)

    def uid(self, name):
        if name not in self._users:
            raise LayoutError("user %r does not exist on this host — create it first "
                              "(README \"VPS deploy sequence\" step 1)" % name)
        return self._users[name]

    def gid(self, name):
        if name not in self._groups:
            raise LayoutError("group %r does not exist on this host — create it first "
                              "(README \"VPS deploy sequence\" step 1)" % name)
        return self._groups[name]


def system_resolver(getpwnam=pwd.getpwnam, getgrnam=grp.getgrnam):
    """Resolve every name the table uses. A name that does not resolve is left out, so the
    refusal comes from Resolver.uid/gid naming it, at the point it is needed."""
    users, groups = {}, {}
    for e in LAYOUT:
        if e.owner not in users:
            try:
                users[e.owner] = getpwnam(e.owner).pw_uid
            except KeyError:
                pass
        if e.group not in groups:
            try:
                groups[e.group] = getgrnam(e.group).gr_gid
            except KeyError:
                pass
    if "hermes" in groups and groups["hermes"] != governance_lib.EXECUTOR_GID:
        raise LayoutError(
            "group 'hermes' is gid %d on this host, but the executor runs as gid %d "
            "(Dockerfile: USER hermes). Reconcile the group before creating the layout "
            "(README \"VPS deploy sequence\" step 1)"
            % (groups["hermes"], governance_lib.EXECUTOR_GID))
    return Resolver(users, groups)


def entry_path(entry, store_root, spool_root):
    root = store_root if entry.root_key == "store" else spool_root
    return os.path.join(root, entry.relpath) if entry.relpath else root


def expected(entry):
    return "%s:%s %04o" % (entry.owner, entry.group, entry.mode)


def _inspect(entry, path, resolver):
    """('ok' | 'missing' | 'mismatch', detail). lstat only — never follows a symlink."""
    try:
        st = os.lstat(path)
    except FileNotFoundError:
        return "missing", "missing, expected %s %s" % (entry.kind, expected(entry))
    except OSError as e:
        return "mismatch", "cannot lstat (%s), expected %s" % (e, expected(entry))
    if stat.S_ISLNK(st.st_mode):
        return "mismatch", ("is a symlink (never followed), expected a real %s %s"
                            % (entry.kind, expected(entry)))
    is_kind = stat.S_ISDIR if entry.kind == DIR else stat.S_ISREG
    if not is_kind(st.st_mode):
        return "mismatch", "is not a %s, expected %s %s" % (entry.kind, entry.kind,
                                                           expected(entry))
    uid, gid = resolver.uid(entry.owner), resolver.gid(entry.group)
    mode = stat.S_IMODE(st.st_mode)
    if (st.st_uid, st.st_gid, mode) != (uid, gid, entry.mode):
        return "mismatch", ("found uid %d gid %d mode %04o, expected %s (uid %d gid %d)"
                            % (st.st_uid, st.st_gid, mode, expected(entry), uid, gid))
    return "ok", ""


def check_ancestors(root, trusted_uids=(0,), top="/"):
    """Every directory above `root`, up to and including `top`, must be a real directory,
    owned by a trusted uid, and neither group- nor world-writable. Whoever can write an
    ancestor can rename the whole layout away and put their own in its place."""
    problems = []
    top = os.path.normpath(top)
    d = os.path.dirname(os.path.normpath(root))
    while True:
        try:
            st = os.lstat(d)
        except OSError as e:
            problems.append((d, "ancestor cannot be checked (%s)" % e))
        else:
            if stat.S_ISLNK(st.st_mode):
                problems.append((d, "ancestor is a symlink — the layout must sit on a "
                                    "real path"))
            elif not stat.S_ISDIR(st.st_mode):
                problems.append((d, "ancestor is not a directory"))
            else:
                if st.st_uid not in trusted_uids:
                    problems.append((d, "ancestor owned by uid %d, expected root"
                                        % st.st_uid))
                if st.st_mode & 0o022:
                    problems.append((d, "ancestor mode %04o is group- or world-writable — "
                                        "whoever can write it can rename the layout away"
                                        % stat.S_IMODE(st.st_mode)))
        if d == top or d == os.path.dirname(d):
            return problems
        d = os.path.dirname(d)


def plan(store_root, spool_root, resolver, ancestor_uids=(0,), ancestor_top="/"):
    for r in (store_root, spool_root):
        if not os.path.isabs(r):
            raise LayoutError("%r is not an absolute path" % r)
    steps, seen = [], set()
    for root in (store_root, spool_root):
        for path, detail in check_ancestors(root, ancestor_uids, ancestor_top):
            if (path, detail) not in seen:          # the two roots share ancestors
                seen.add((path, detail))
                steps.append(Step("mismatch", path, detail, False, None))
    missing = []
    for e in LAYOUT:
        p = entry_path(e, store_root, spool_root)
        if any(p.startswith(m + os.sep) for m in missing):
            steps.append(Step("create", p, "missing, expected %s %s"
                              % (e.kind, expected(e)), True, e))
            continue
        state, detail = _inspect(e, p, resolver)
        if state == "missing":
            steps.append(Step("create", p, detail, False, e))
            if e.kind == DIR:
                missing.append(p)
        else:
            steps.append(Step(state, p, detail, False, e))
    return steps


def check(store_root, spool_root, resolver, ancestor_uids=(0,), ancestor_top="/"):
    """Problems as '<path>: <detail>' lines; empty means the layout is exactly right.
    A missing directory is one line — its children are implied, not repeated."""
    return ["%s: %s" % (s.path, s.detail)
            for s in plan(store_root, spool_root, resolver, ancestor_uids, ancestor_top)
            if s.action == "mismatch" or (s.action == "create" and not s.implied)]
```

- [ ] **Step 4: Run the tests and confirm they pass**

Run: `python3 infra/hermes-agent/bin/host_layout.test.py -v`
Expected: every test passes (the untrusted-uid test is skipped only when run as root).
If `test_a_missing_setgid_bit_is_caught` fails because `os.chmod(…, 0o2750)` silently dropped
the setgid bit on this host, **stop and report it**. Do not change the table to make it pass.

- [ ] **Step 5: Commit**

```bash
git add infra/hermes-agent/bin/host_layout.py infra/hermes-agent/bin/host_layout.test.py
git commit -m "feat(hermes): F10 layout table and read-only check

One table for the governance store and the spool (spec §3.2, §3.3) and an
lstat-only check over it: missing, wrong kind, symlink, wrong uid/gid, inexact
mode (so a lost setgid or sticky bit is caught), and unsafe ancestors. Every
mismatch line names the expected owner:group mode (R3).

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: `apply` — create what is missing, refuse on anything wrong, roll back on failure

**Files:**
- Modify: `infra/hermes-agent/bin/host_layout.py` (append `apply`)
- Test: `infra/hermes-agent/bin/host_layout.test.py` (append classes)

**Interfaces:**
- Consumes: everything from Task 1.
- Produces: `apply(store_root, spool_root, resolver, ancestor_uids=(0,), ancestor_top="/", geteuid=os.geteuid) -> list[str]`,
  which returns the paths created in this call, parent-first. It raises `LayoutError` on any
  refusal and leaves nothing it created behind.

- [ ] **Step 1: Write the failing tests**

Append to `infra/hermes-agent/bin/host_layout.test.py`, above `if __name__ == "__main__":`:

```python
def snapshot(base):
    """Every path under base with its mode — to prove a refusal created nothing."""
    out = []
    for dirpath, dirnames, filenames in os.walk(base):
        for n in sorted(dirnames + filenames):
            p = os.path.join(dirpath, n)
            out.append((os.path.relpath(p, base), stat.S_IMODE(os.lstat(p).st_mode)))
    return sorted(out)


AS_ROOT = lambda: 0      # apply() checks euid; Tier 1 fakes it and maps names to itself


class TestPlan(Base):
    def test_dry_run_on_an_empty_host_creates_nothing(self):
        before = snapshot(self.base)
        steps = H.plan(self.store, self.spool, **self.kw())
        self.assertEqual(snapshot(self.base), before)
        self.assertEqual([s.action for s in steps], ["create"] * len(H.LAYOUT))
        self.assertEqual(sum(1 for s in steps if not s.implied), 2)   # the two roots

    def test_plan_reports_ok_for_a_correct_layout(self):
        make_layout(self.store, self.spool)
        self.assertEqual({s.action for s in H.plan(self.store, self.spool, **self.kw())},
                         {"ok"})

    def test_relative_roots_are_refused(self):
        with self.assertRaises(H.LayoutError):
            H.plan("governance", self.spool, **self.kw())


class TestApply(Base):
    def apply(self, **over):
        over.setdefault("geteuid", AS_ROOT)
        geteuid = over.pop("geteuid")
        return H.apply(self.store, self.spool, geteuid=geteuid, **self.kw(**over))

    def test_refuses_when_not_root_and_creates_nothing(self):
        before = snapshot(self.base)
        with self.assertRaises(H.LayoutError) as cm:
            self.apply(geteuid=lambda: 1000)
        self.assertIn("root", str(cm.exception))
        self.assertEqual(snapshot(self.base), before)

    def test_builds_a_layout_that_check_accepts_whatever_the_umask(self):
        old = os.umask(0o077)
        try:
            created = self.apply()
        finally:
            os.umask(old)
        self.assertEqual(len(created), len(H.LAYOUT))
        self.assertEqual(self.check(), [])

    def test_a_second_apply_creates_nothing(self):
        self.apply()
        self.assertEqual(self.apply(), [])

    def test_the_bring_up_store_is_refused_and_nothing_is_created(self):
        """Spec §3.4: the VPS store is an empty dir at 700 root:root. No adopt-if-empty."""
        os.mkdir(self.store)
        os.chmod(self.store, 0o700)
        before = snapshot(self.base)
        with self.assertRaises(H.LayoutError) as cm:
            self.apply()
        msg = str(cm.exception)
        self.assertIn(self.store, msg)
        self.assertIn("expected root:hermes 0750", msg)
        self.assertIn("never repairs", msg)
        self.assertEqual(snapshot(self.base), before)     # the spool was NOT created either

    def test_an_unsafe_ancestor_is_refused_and_nothing_is_created(self):
        mid = os.path.join(self.base, "mid")
        os.mkdir(mid)
        os.chmod(mid, 0o777)
        self.set_roots(mid)
        with self.assertRaises(H.LayoutError):
            self.apply()
        self.assertEqual(os.listdir(mid), [])

    def test_a_missing_user_is_refused_before_anything_is_created(self):
        r = H.Resolver(users={"root": self.uid},
                       groups={"hermes": self.gid, "hermes-broker": self.gid})
        with self.assertRaises(H.LayoutError) as cm:
            self.apply(resolver=r)
        self.assertIn("hermes-broker", str(cm.exception))
        self.assertEqual(os.listdir(self.base), [])

    @unittest.skipIf(os.geteuid() == 0, "root may chown to any gid")
    def test_a_failure_part_way_removes_everything_this_call_created(self):
        """Firing control for the rollback: map 'hermes' to a gid this process is not in,
        so the very first fchown fails with EPERM after the store root was mkdir'ed."""
        foreign = max(os.getgroups() + [self.gid]) + 4242
        r = H.Resolver(users={"root": self.uid, "hermes-broker": self.uid},
                       groups={"hermes": foreign, "hermes-broker": self.gid})
        with self.assertRaises(OSError):
            self.apply(resolver=r)
        self.assertEqual(os.listdir(self.base), [])

    def test_an_existing_registry_is_never_rewritten(self):
        self.apply()
        reg = os.path.join(self.store, "registry", "clients.json")
        os.chmod(reg, 0o600)
        with open(reg, "w") as f:
            f.write('{"clients": {"slug-1": {}}}\n')
        os.chmod(reg, 0o640)
        shutil.rmtree(os.path.join(self.store, "seen"))
        self.assertEqual(self.apply(), [os.path.join(self.store, "seen")])
        with open(reg) as f:
            self.assertEqual(f.read(), '{"clients": {"slug-1": {}}}\n')
```

- [ ] **Step 2: Run the tests and confirm they fail**

Run: `python3 infra/hermes-agent/bin/host_layout.test.py`
Expected: the `TestApply` tests error with `AttributeError: module 'host_layout' has no attribute 'apply'`.
The `TestPlan` tests pass already; that is fine, because `plan` landed in Task 1.

- [ ] **Step 3: Implement `apply`**

Append to `infra/hermes-agent/bin/host_layout.py`:

```python
def _remove(path):
    try:
        st = os.lstat(path)
        if stat.S_ISDIR(st.st_mode):
            os.rmdir(path)
        else:
            os.unlink(path)
    except OSError:
        pass


def _write_all(fd, data):
    view = memoryview(data)
    while view:
        view = view[os.write(fd, view):]


def apply(store_root, spool_root, resolver, ancestor_uids=(0,), ancestor_top="/",
          geteuid=os.geteuid):
    """Create every MISSING entry, parent-first. Returns the paths created.

    Refuses — before creating anything — when not root, when any ancestor is unsafe, when
    any EXISTING entry mismatches, or when any name does not resolve. Each entry is
    created with mkdir/O_EXCL, then opened with O_NOFOLLOW, and fchown'ed and fchmod'ed
    on that fd, so neither a planted symlink nor the umask can redirect or weaken it.
    Each entry is re-inspected after it is created. On ANY failure, everything created by
    this call is removed, children first, and the exception propagates."""
    if geteuid() != 0:
        raise LayoutError("--apply must run as root: it creates entries owned by users "
                          "other than the caller. Nothing was created.")
    steps = plan(store_root, spool_root, resolver, ancestor_uids, ancestor_top)
    bad = ["%s: %s" % (s.path, s.detail) for s in steps if s.action == "mismatch"]
    if bad:
        raise LayoutError(
            "refusing to create anything: these existing paths do not match the layout, "
            "and this tool never repairs. Set each to the expected state by hand (or, for "
            "an EMPTY directory left by an earlier bring-up, `sudo rmdir` it), then "
            "re-run:\n  - " + "\n  - ".join(bad))
    todo = [s for s in steps if s.action == "create"]
    ids = {s.path: (resolver.uid(s.entry.owner), resolver.gid(s.entry.group))
           for s in todo}                       # every name resolves before any mkdir
    created = []
    try:
        for s in todo:
            e, (uid, gid) = s.entry, ids[s.path]
            if e.kind == DIR:
                os.mkdir(s.path, 0o700)
                created.append(s.path)
                fd = os.open(s.path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            else:
                fd = os.open(s.path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                             0o600)
                created.append(s.path)
            try:
                if e.kind == FILE:
                    _write_all(fd, e.content)
                os.fchown(fd, uid, gid)
                os.fchmod(fd, e.mode)           # after fchown, which can clear setgid
                if e.kind == FILE:
                    os.fsync(fd)
            finally:
                os.close(fd)
            state, detail = _inspect(e, s.path, resolver)
            if state != "ok":
                raise LayoutError("%s did not land as specified: %s" % (s.path, detail))
    except BaseException:
        for p in reversed(created):
            _remove(p)
        raise
    return created
```

- [ ] **Step 4: Run the tests and confirm they pass**

Run: `python3 infra/hermes-agent/bin/host_layout.test.py -v`
Expected: all pass. The rollback test is skipped only when run as root.

- [ ] **Step 5: Mutation check on the rollback firing control**

Temporarily replace the body of the `except BaseException:` block with just `raise`, then rerun.
Expected: `test_a_failure_part_way_removes_everything_this_call_created` FAILS, because
`governance` is left behind. Restore the block, rerun, and confirm it is green. Write the
observed failure line into the Task 2 commit message.

- [ ] **Step 6: Commit**

```bash
git add infra/hermes-agent/bin/host_layout.py infra/hermes-agent/bin/host_layout.test.py
git commit -m "feat(hermes): F10 layout apply — create missing, refuse wrong, roll back

Root only. Refuses before creating anything on an unsafe ancestor, an existing
mismatch (including the bring-up's empty 700 root:root store, spec §3.4), or an
unresolvable name. mkdir/O_EXCL, then O_NOFOLLOW + fchown + fchmod on the fd,
then re-inspect; any failure removes everything this call created.
Mutation check: <paste the observed failure line>.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: The operator CLI `init-host-layout.py`

**Files:**
- Create: `infra/hermes-agent/bin/init-host-layout.py` (mode 755, like the other bin scripts)
- Test: `infra/hermes-agent/bin/init-host-layout.test.py`

**Interfaces:**
- Consumes: `host_layout.{plan, check, apply, system_resolver, LayoutError, DEFAULT_STORE_ROOT, DEFAULT_SPOOL_ROOT}`.
- Produces: `main(argv=None, resolver_factory=None, ancestor_uids=(0,), ancestor_top="/", geteuid=os.geteuid) -> int`.
  Exit `0` ok · `1` usage · `2` refusal or drift. Tasks 6, 7 and 8 call it as
  `init-host-layout.py [--store-root P] [--spool-root P] [--apply | --check]`.
  `--check` prints its problems to **stderr**, one per line, each prefixed `  - `.

- [ ] **Step 1: Write the failing tests**

Create `infra/hermes-agent/bin/init-host-layout.test.py`:

```python
import contextlib, importlib.util, io, os, shutil, sys, tempfile, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import host_layout as H


def _load(name, filename):
    spec = importlib.util.spec_from_file_location(name, os.path.join(HERE, filename))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


CLI = _load("init_host_layout", "init-host-layout.py")


class Base(unittest.TestCase):
    def setUp(self):
        self.base = os.path.realpath(tempfile.mkdtemp(prefix="init-host-layout-"))
        self.addCleanup(shutil.rmtree, self.base, True)
        self.store = os.path.join(self.base, "governance")
        self.spool = os.path.join(self.base, "spool")
        uid, gid = os.getuid(), os.getgid()
        self.resolver = H.Resolver(users={"root": uid, "hermes-broker": uid},
                                   groups={"hermes": gid, "hermes-broker": gid})
        self.uid = uid

    def run_cli(self, *flags, geteuid=os.geteuid, factory=None):
        out, err = io.StringIO(), io.StringIO()
        argv = ["--store-root", self.store, "--spool-root", self.spool] + list(flags)
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = CLI.main(argv, resolver_factory=factory or (lambda: self.resolver),
                          ancestor_uids=(0, self.uid), ancestor_top=self.base,
                          geteuid=geteuid)
        return rc, out.getvalue(), err.getvalue()


class TestCli(Base):
    def test_dry_run_prints_the_plan_and_creates_nothing(self):
        rc, out, _ = self.run_cli()
        self.assertEqual(rc, 0)
        self.assertEqual(os.listdir(self.base), [])
        self.assertEqual(sum(1 for l in out.splitlines() if l.startswith("create")),
                         len(H.LAYOUT))

    def test_apply_as_non_root_is_refused(self):
        rc, _, err = self.run_cli("--apply", geteuid=lambda: 1000)
        self.assertEqual(rc, 2)
        self.assertIn("root", err)
        self.assertEqual(os.listdir(self.base), [])

    def test_apply_then_check_passes(self):
        rc, out, err = self.run_cli("--apply", geteuid=lambda: 0)
        self.assertEqual(rc, 0, err)
        self.assertIn("layout OK", out)
        rc, out, err = self.run_cli("--check")
        self.assertEqual((rc, err), (0, ""))

    def test_check_reports_drift_with_the_expected_state(self):
        self.run_cli("--apply", geteuid=lambda: 0)
        os.chmod(os.path.join(self.spool, "results"), 0o2770)
        rc, _, err = self.run_cli("--check")
        self.assertEqual(rc, 2)
        self.assertIn("  - " + os.path.join(self.spool, "results"), err)
        self.assertIn("expected hermes-broker:hermes 2750", err)

    def test_check_on_a_missing_layout_says_missing(self):
        rc, _, err = self.run_cli("--check")
        self.assertEqual(rc, 2)
        self.assertIn("missing", err)

    def test_dry_run_with_a_mismatch_exits_two(self):
        os.mkdir(self.store)
        os.chmod(self.store, 0o700)
        rc, out, _ = self.run_cli()
        self.assertEqual(rc, 2)
        self.assertIn("mismatch", out)

    def test_apply_and_check_together_is_a_usage_error(self):
        rc, _, _ = self.run_cli("--apply", "--check")
        self.assertEqual(rc, 1)

    def test_an_unknown_flag_is_a_usage_error(self):
        rc, _, _ = self.run_cli("--repair")
        self.assertEqual(rc, 1)

    def test_a_resolver_refusal_is_exit_two(self):
        def refuse():
            raise H.LayoutError("group 'hermes' is gid 1234")
        rc, _, err = self.run_cli("--check", factory=refuse)
        self.assertEqual(rc, 2)
        self.assertIn("1234", err)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the tests and confirm they fail**

Run: `python3 infra/hermes-agent/bin/init-host-layout.test.py`
Expected: `FileNotFoundError` for `init-host-layout.py`.

- [ ] **Step 3: Write the CLI**

Create `infra/hermes-agent/bin/init-host-layout.py`, then run
`chmod 755 infra/hermes-agent/bin/init-host-layout.py`:

```python
#!/usr/bin/env python3
"""Create or verify the governance store and spool layout on a Linux host (F10).

Operator-run, host-side, the same governed-operator-CLI pattern as
`migrate-governance.py --bootstrap-logs` (ruling R23):

    init-host-layout.py            dry run: print what would be created (the default)
    init-host-layout.py --apply    create what is missing (root only; refuses on
                                   anything that exists and is wrong — never repairs)
    init-host-layout.py --check    verify only; the broker unit's first ExecStartPre

Exit 0 ok · 1 usage · 2 refusal or drift. The layout itself is bin/host_layout.py.
"""
import argparse, os, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import host_layout as H

EXIT_OK, EXIT_USAGE, EXIT_REFUSED = 0, 1, 2


def main(argv=None, resolver_factory=None, ancestor_uids=(0,), ancestor_top="/",
         geteuid=os.geteuid):
    ap = argparse.ArgumentParser(
        prog="init-host-layout",
        description="Create or verify the governance store and spool layout.")
    ap.add_argument("--store-root", default=H.DEFAULT_STORE_ROOT)
    ap.add_argument("--spool-root", default=H.DEFAULT_SPOOL_ROOT)
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--apply", action="store_true",
                      help="create what is missing (root only)")
    mode.add_argument("--check", action="store_true", help="verify only")
    try:
        args = ap.parse_args(argv)
    except SystemExit as e:                  # argparse exits 2; usage here is 1
        return EXIT_OK if e.code == 0 else EXIT_USAGE
    kw = dict(ancestor_uids=ancestor_uids, ancestor_top=ancestor_top)
    try:
        resolver = (resolver_factory or H.system_resolver)()
        if args.apply:
            for p in H.apply(args.store_root, args.spool_root, resolver,
                             geteuid=geteuid, **kw):
                print("created  %s" % p)
        if args.apply or args.check:
            problems = H.check(args.store_root, args.spool_root, resolver, **kw)
            if problems:
                print("init-host-layout: the layout does not match (this tool never "
                      "repairs — set each path to the expected state by hand):",
                      file=sys.stderr)
                for p in problems:
                    print("  - %s" % p, file=sys.stderr)
                return EXIT_REFUSED
            print("init-host-layout: layout OK")
            return EXIT_OK
        steps = H.plan(args.store_root, args.spool_root, resolver, **kw)
        for s in steps:
            print("%-8s %s%s" % (s.action, s.path, "  " + s.detail if s.detail else ""))
        return EXIT_REFUSED if any(s.action == "mismatch" for s in steps) else EXIT_OK
    except (H.LayoutError, OSError) as e:
        print("init-host-layout: %s" % e, file=sys.stderr)
        return EXIT_REFUSED


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run the tests and the whole bin suite**

Run: `python3 infra/hermes-agent/bin/init-host-layout.test.py -v && infra/hermes-agent/bin/run-bin-tests.sh`
Expected: the CLI tests all pass, and the bin runner reports **29/29** suites passed (27 plus
`host_layout.test.py` and `init-host-layout.test.py`, found by discovery).

- [ ] **Step 5: Commit**

```bash
git add infra/hermes-agent/bin/init-host-layout.py infra/hermes-agent/bin/init-host-layout.test.py
git commit -m "feat(hermes): init-host-layout.py — dry run, --apply, --check

The governed operator CLI over host_layout (ruling R23 pattern). Exit 0 ok,
1 usage, 2 refusal or drift; --check lists each mismatch with its expected
state on stderr.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: Spool files are `0640` (F10a)

**Files:**
- Modify: `infra/hermes-agent/bin/spool_lib.py` (the constants near `DEFAULT_SPOOL_ROOT`, line 21; `write_result`, around lines 186–207)
- Modify: `infra/hermes-agent/bin/hermes-syscall.py` (`submit`, around lines 52–65)
- Test: `infra/hermes-agent/bin/spool_lib.test.py`, `infra/hermes-agent/bin/hermes-syscall.test.py`

**Interfaces:**
- Produces: `spool_lib.SPOOL_FILE_MODE = 0o640`. Task 8's firing control rewrites this exact
  line (`SPOOL_FILE_MODE = 0o640`) in a copy of the file, so keep it on one line, spelled exactly
  like that.

- [ ] **Step 1: Write the failing tests**

Append to `infra/hermes-agent/bin/spool_lib.test.py`, above `if __name__ == "__main__":`:

```python
class TestResultFileMode(unittest.TestCase):
    """F10a. mkstemp always creates 0600, so on Linux a result written by hermes-broker
    was unreadable by the gateway (uid 10000): every fetch reported result_unreadable."""

    def test_the_spool_file_mode_is_group_read(self):
        self.assertEqual(S.SPOOL_FILE_MODE, 0o640)

    def test_a_result_lands_0640_whatever_the_umask(self):
        for umask in (0o000, 0o077):
            root = tempfile.mkdtemp()
            old = os.umask(umask)
            try:
                p = S.write_result(GOOD_ID, {"status": "refused"}, root)
            finally:
                os.umask(old)
            self.assertEqual(stat.S_IMODE(os.stat(p).st_mode), 0o640, oct(umask))
```

Append to `infra/hermes-agent/bin/hermes-syscall.test.py`, above `if __name__ == "__main__":`:

```python
class TestRequestFileMode(Base):
    """F10a, the other direction: a 0600 request written by the gateway could not be
    opened by hermes-broker, so every request was refused and discarded."""

    def test_a_request_lands_0640_whatever_the_umask(self):
        for umask in (0o000, 0o077):
            old = os.umask(umask)
            try:
                rc, out, _ = self.run_cli(["apply", "--client", "pilot-1",
                                           "--changeset", "20260824-101500-abcdef01"])
            finally:
                os.umask(old)
            self.assertEqual(rc, 0)
            p = S.request_path(out.strip(), self.root)
            self.assertEqual(stat.S_IMODE(os.stat(p).st_mode), 0o640, oct(umask))
```

Add `stat` to `hermes-syscall.test.py`'s first import line
(`import contextlib, errno, importlib.util, io, json, os, stat, sys, tempfile, unittest`).

- [ ] **Step 2: Run the tests and confirm they fail**

Run: `python3 infra/hermes-agent/bin/spool_lib.test.py; python3 infra/hermes-agent/bin/hermes-syscall.test.py`
Expected: `AttributeError: … 'SPOOL_FILE_MODE'`, and `0o600 != 0o640` for the request.

- [ ] **Step 3: Implement**

In `spool_lib.py`, directly below `DEFAULT_SPOOL_ROOT = "/opt/data/spool"`:

```python
# Every file in the spool is written 0640, set on the fd so the umask cannot defeat it
# (F10a). mkstemp always creates 0600, and the two sides of the spool are DIFFERENT
# users on Linux (gateway uid 10000, broker hermes-broker): 0600 made every request
# unreadable to the broker and every result unreadable to the gateway. Group read is
# enough because both files carry group hermes (10000) — requests/ and results/ are
# setgid (bin/host_layout.py). Invisible on darwin, where both sides are one user.
SPOOL_FILE_MODE = 0o640
```

In `spool_lib.write_result`, immediately after the `fd, tmp = tempfile.mkstemp(...)` line:

```python
    fd, tmp = tempfile.mkstemp(dir=d, prefix=".%s." % request_id, suffix=".tmp")
    try:
        os.fchmod(fd, SPOOL_FILE_MODE)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
```

That is: add `os.fchmod(fd, SPOOL_FILE_MODE)` as the first statement inside the existing `try:`,
so the existing cleanup path still removes the temp file if it fails.

In `hermes-syscall.py`'s `submit`, the same, as the first statement inside its existing `try:`:

```python
    fd, tmp = tempfile.mkstemp(dir=d, prefix=".%s." % request_id, suffix=".tmp")
    try:
        os.fchmod(fd, S.SPOOL_FILE_MODE)       # F10a: the broker is another user
        with os.fdopen(fd, "w", encoding="utf-8") as f:
```

- [ ] **Step 4: Run the tests and confirm they pass**

Run: `python3 infra/hermes-agent/bin/spool_lib.test.py && python3 infra/hermes-agent/bin/hermes-syscall.test.py`
Expected: both suites pass.

- [ ] **Step 5: Mutation check (spec §5.1)**

Comment out the `os.fchmod` line in `spool_lib.write_result` and rerun `spool_lib.test.py`.
Expected: `test_a_result_lands_0640_whatever_the_umask` FAILS with `384 != 416`. Restore it. Do
the same for `hermes-syscall.submit`, where `test_a_request_lands_0640_whatever_the_umask` must
fail. Restore it, and confirm both suites are green.

- [ ] **Step 6: Commit**

```bash
git add infra/hermes-agent/bin/spool_lib.py infra/hermes-agent/bin/spool_lib.test.py \
        infra/hermes-agent/bin/hermes-syscall.py infra/hermes-agent/bin/hermes-syscall.test.py
git commit -m "fix(hermes): spool files are 0640, set on the fd (F10a)

mkstemp creates 0600 and the two sides of the spool are different users on
Linux, so every request was unreadable to the broker and every result to the
gateway. Mutation-checked: removing either fchmod turns its test red.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: The broker verifies `.quarantine` and `rmdir`s empty planted directories (F10b, R1)

**Files:**
- Modify: `infra/hermes-agent/bin/hermes-broker.py` (`_discard`, around lines 156–211; add `import stat` if absent)
- Test: `infra/hermes-agent/bin/hermes-broker.test.py`

**Interfaces:**
- Produces: `_quarantine_problem(qdir) -> str | None` (module-private) and the new `_discard`
  order: `unlink` → `rmdir` → verified quarantine → leave in place with one stderr line.
  `_discard` still never raises.

- [ ] **Step 1: Write the failing tests**

In `hermes-broker.test.py`, change the first import line to
`import contextlib, datetime, importlib.util, io, json, os, subprocess, sys, tempfile, unittest, uuid`
and add `from unittest import mock` below it. Then add this class directly after
`class TestPoisonedSpoolEntries`:

```python
class TestQuarantineIsVerified(Base):
    """F10b and R1. The gateway can write requests/, so it can plant '.quarantine' first
    (as a symlink, or as a directory it owns) and have the broker move entries through
    it. The broker must verify the directory before using it. Empty planted directories
    are rmdir'ed instead (R1: a non-root broker cannot move a gateway-owned directory to
    another parent on Linux, so quarantine is not always available)."""

    POISON = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee.json"

    def plant(self, empty):
        d = S.requests_dir(self.spool)
        os.makedirs(d, exist_ok=True)
        p = os.path.join(d, self.POISON)
        os.mkdir(p)
        if not empty:
            with open(os.path.join(p, "x"), "w") as f:
                f.write("x")
        return d, p

    def other_request(self):
        rid = str(uuid.uuid4())
        C.append_seen(SLUG, rid, NOW)          # a replay: refused without a runner call
        self.file_request(request_id=rid)
        return rid

    def drain_stderr(self):
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            self.drain(RecordingRunner())          # must not raise
        return err.getvalue()

    def test_an_empty_planted_directory_is_removed_without_quarantine(self):
        d, p = self.plant(empty=True)
        self.drain_stderr()
        self.assertFalse(os.path.exists(p))
        self.assertFalse(os.path.exists(os.path.join(d, ".quarantine")))

    def test_control_a_non_empty_directory_goes_to_a_trusted_quarantine(self):
        d, p = self.plant(empty=False)
        other = self.other_request()
        self.drain_stderr()
        self.assertFalse(os.path.exists(p))
        q = os.path.join(d, ".quarantine")
        self.assertEqual(len(os.listdir(q)), 1)
        self.assertEqual(stat.S_IMODE(os.lstat(q).st_mode) & 0o022, 0)
        self.assertEqual(self.result_for(other)["classification"], "refused_replay")

    def test_a_symlinked_quarantine_is_refused_and_nothing_moves_through_it(self):
        d, p = self.plant(empty=False)
        elsewhere = tempfile.mkdtemp()
        os.symlink(elsewhere, os.path.join(d, ".quarantine"))
        other = self.other_request()
        err = self.drain_stderr()
        self.assertTrue(os.path.isdir(p))
        self.assertEqual(os.listdir(elsewhere), [])
        self.assertIn(".quarantine", err)
        self.assertEqual(self.result_for(other)["classification"], "refused_replay")

    def test_a_group_writable_quarantine_is_refused(self):
        d, p = self.plant(empty=False)
        q = os.path.join(d, ".quarantine")
        os.mkdir(q)
        os.chmod(q, 0o770)
        err = self.drain_stderr()
        self.assertTrue(os.path.isdir(p))
        self.assertEqual(os.listdir(q), [])
        self.assertIn("writable", err)

    def test_a_quarantine_owned_by_another_uid_is_refused(self):
        d, p = self.plant(empty=False)
        os.mkdir(os.path.join(d, ".quarantine"), 0o700)
        with mock.patch.object(B.os, "geteuid", return_value=os.geteuid() + 4242):
            err = self.drain_stderr()
        self.assertTrue(os.path.isdir(p))
        self.assertIn("owned by uid", err)
```

Also add `stat` to the first import line (`…, os, stat, subprocess, …`).

- [ ] **Step 2: Run the tests and confirm they fail**

Run: `python3 infra/hermes-agent/bin/hermes-broker.test.py TestQuarantineIsVerified -v`
Expected:
- the empty-directory test FAILS, because `.quarantine` exists (today's code quarantines it);
- the symlink, group-writable and other-uid tests FAIL, because the entry was moved;
- the control passes.

- [ ] **Step 3: Implement**

In `hermes-broker.py`, add `stat` to the imports if it is not already imported. Add this function
directly above `_discard`:

```python
def _quarantine_problem(qdir):
    """None if qdir is safe to move entries into, else the reason it is not.

    F10b: requests/ is gateway-writable, so the gateway can create '.quarantine' first —
    as a symlink into the governance store (the broker's only other writable tree under
    ProtectSystem=strict), or as a directory it owns and can empty. makedirs(exist_ok)
    accepted both. The layout pre-creates it broker-owned 0700 (bin/host_layout.py); this
    re-verifies it on every use, because a pre-created name is only safe while it is
    still the directory that was pre-created."""
    try:
        os.mkdir(qdir, 0o700)
    except FileExistsError:
        pass
    st = os.lstat(qdir)
    if not stat.S_ISDIR(st.st_mode):
        return "%s is not a real directory (a symlink or other entry)" % qdir
    if st.st_uid != os.geteuid():
        return "%s is owned by uid %d, not this broker (uid %d)" % (
            qdir, st.st_uid, os.geteuid())
    if st.st_mode & 0o022:
        return "%s is group- or world-writable (mode %04o)" % (
            qdir, stat.S_IMODE(st.st_mode))
    return None
```

In `_discard`, replace everything from the first `try:` to the end of the function with:

```python
    try:
        os.unlink(path)
        return
    except FileNotFoundError:
        return                          # already gone — not this function's problem
    except OSError:
        pass                            # not a plain deletable file; fall through

    # R1: an EMPTY directory is removable by the broker even when the gateway owns it —
    # requests/ is sticky and the broker owns it, and rmdir needs nothing from the entry
    # itself. Quarantine does: moving a directory to a different parent needs write on
    # the directory (it rewrites '..'), and the gateway chose that mode.
    try:
        os.rmdir(path)
        return
    except FileNotFoundError:
        return
    except OSError:
        pass                            # not empty, or not a directory; fall through

    try:
        qdir = os.path.join(os.path.dirname(path), ".quarantine")
        problem = _quarantine_problem(qdir)
        if problem:
            print("hermes-broker: refusing to quarantine %s: %s — leaving it in place; "
                  "an operator must inspect the spool" % (path, problem), file=sys.stderr)
            return
        dest = os.path.join(qdir, "%s.%d.%d" % (os.path.basename(path),
                                                 time.time_ns(), os.getpid()))
        os.replace(path, dest)
    except OSError as e:
        print("hermes-broker: could not remove or quarantine %s (%s) — leaving it in "
              "place; it may be re-scanned and re-rejected on a future drain"
              % (path, e), file=sys.stderr)
```

In `_discard`'s docstring, change step 2 and add the residual. Replace the paragraph
`2. If unlink fails for any other reason — …` so that it begins:

```
      2. If unlink fails, try rmdir (R1, F10): an EMPTY directory the gateway planted
         is removable by the broker, as owner of the sticky requests/, whoever owns it.
      3. Otherwise QUARANTINE it: os.replace() it into requests/.quarantine/ — but only
         after _quarantine_problem() has verified that directory is a real,
         broker-owned, non-group/world-writable directory (F10b) …
```

Keep the rest of the existing step-2 reasoning. Renumber the old step 3 to 4, and append this
paragraph before the closing `"""`:

```
    STATED RESIDUAL (R1). On Linux the broker is not root, and moving a directory to a
    different parent needs write permission on that directory. A NON-EMPTY directory the
    gateway planted at, say, 0700 can therefore be neither removed nor quarantined: it
    stays in requests/, is re-scanned, re-rejected (its refused_request result is
    rewritten) and logged on every drain pass. The drain survives it and every other
    request is still processed — deploy/layout-integration.test.py proves both on real
    uids. Removing it needs root. The "permanent stall" FIX ROUND 2 closed is closed for
    the drain; it is not closed for the log noise.
```

- [ ] **Step 4: Run the broker suite**

Run: `python3 infra/hermes-agent/bin/hermes-broker.test.py`
Expected: all pass, including the existing
`test_a_poisoned_directory_does_not_crash_the_drain_or_block_other_requests`. Its empty directory
is now removed by `rmdir` instead of being quarantined, and its assertions still hold.

- [ ] **Step 5: Commit**

```bash
git add infra/hermes-agent/bin/hermes-broker.py infra/hermes-agent/bin/hermes-broker.test.py
git commit -m "fix(hermes): verify .quarantine before use; rmdir empty planted dirs (F10b, R1)

makedirs(exist_ok=True) accepted a gateway-planted .quarantine (symlink or
gateway-owned dir) and os.replace moved entries through it. The broker now
requires a real, self-owned, non-group/world-writable directory, and removes
empty planted directories with rmdir. The non-empty residual is documented.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 6: The pre-flight separates "missing" from "unreadable"

**Files:**
- Modify: `infra/hermes-agent/bin/preflight-governance-access.py` (`_check_dir` ~line 90; `check()` ~line 390; `REMEDY` ~line 452)
- Modify: `infra/hermes-agent/bin/migrate_governance_shim.py:153-158` (`bootstrap_logs`' missing-`log/` message)
- Test: `infra/hermes-agent/bin/preflight-governance-access.test.py`

**Interfaces:**
- Produces: `_root_problem(root) -> str | None`. `check()` returns `[that line]` alone when it is
  not None. Task 8 relies on a missing root producing exactly one `  - ` line that contains
  `missing`.

This task **deliberately edits three existing tests**, and a reviewer must see each one:
1. `test_owner_class_wins_even_when_group_and_other_are_wider` counted the cascade: root `0o077`
   means the checking process cannot enter, so every child reported "cannot stat". It is
   re-pointed at the child directories, which keeps its owner-class meaning.
2. `test_a_missing_subdirectory_is_reported` asserted the old wording, "cannot stat". It now
   asserts "missing".
3. `test_cli_exits_two_and_names_the_remedy` (Linux-only) asserted `chown` is in the remedy.
   `REMEDY` no longer offers `chown -R`.

Any other existing test that goes red is **not** covered by this plan. Stop and investigate it;
do not edit it.

- [ ] **Step 1: Write the new tests and make the three edits**

In `TestLinuxSemantics`, replace `test_owner_class_wins_even_when_group_and_other_are_wider` with:

```python
    def test_owner_class_wins_even_when_group_and_other_are_wider(self):
        """POSIX selects exactly ONE permission class. A directory owned by the
        executor at mode 0o077 is unreadable to it however wide `other` is; an
        implementation that OR'd the classes would wrongly pass this.

        F10: the ROOT stays enterable here. With the root itself at 0o077 the checking
        process cannot enter it either, and that is now one collapsed line (see
        TestRootCollapse), so this test would count the collapse, not the class rule."""
        self._chmod_all(0o077)
        os.chmod(self.root, 0o700)
        problems = PF.check(self.root, self.uid, self.gid, platform="linux")
        self.assertEqual(len(problems), len(ALL_DIRS), problems)
```

Replace `test_a_missing_subdirectory_is_reported` with:

```python
    def test_a_missing_subdirectory_is_reported_as_missing(self):
        """F10: 'missing' is its own fault, with its own remedy. It used to read
        'cannot stat', which is indistinguishable from a permission fault."""
        self._chmod_all(0o755)
        os.rmdir(os.path.join(self.root, "control"))
        problems = PF.check(self.root, self.uid, self.gid, platform="linux")
        hits = [p for p in problems if "control" in p]
        self.assertEqual(len(hits), 1, problems)
        self.assertIn("missing", hits[0])
        self.assertNotIn("cannot stat", hits[0])
        self.assertIn("init-host-layout.py", hits[0])
```

In `TestCli.test_cli_exits_two_and_names_the_remedy`, replace `self.assertIn("chown", err)` with:

```python
        self.assertIn("init-host-layout.py", err)
        self.assertNotIn("chown -R", err)
```

Add a new class after `TestLinuxSemantics`:

```python
class TestRootCollapse(Base):
    """F10. Run as hermes-broker against an empty 700 root:root store, the pre-flight
    printed 'Permission denied' for every subdirectory and suggested chmod'ing a log/ that
    did not exist. When the CHECKING PROCESS cannot reach the root, nothing below it can
    be checked, so that is one line — with the right remedy for its cause."""

    def test_a_missing_root_is_one_line_naming_the_layout_tool(self):
        absent = os.path.join(self.root, "absent")
        problems = PF.check(absent, self.uid, self.gid, platform="linux")
        self.assertEqual(len(problems), 1, problems)
        self.assertIn("missing", problems[0])
        self.assertIn("init-host-layout.py", problems[0])

    @unittest.skipIf(os.geteuid() == 0, "root enters any directory")
    def test_an_unenterable_root_is_one_line(self):
        self._chmod_all(0o000)
        problems = PF.check(self.root, self.uid, self.gid, platform="linux")
        self.assertEqual(len(problems), 1, problems)
        self.assertIn("cannot enter", problems[0])

    def test_control_an_enterable_root_still_reports_each_child(self):
        """The collapse must not swallow real per-child faults the process CAN see."""
        self._chmod_all(0o700)
        problems = PF.check(self.root, self.other_uid, self.other_gid, platform="linux")
        self.assertEqual(len(problems), len(ALL_DIRS) + 1)

    def test_non_linux_still_reports_nothing(self):
        absent = os.path.join(self.root, "absent")
        self.assertEqual(PF.check(absent, self.uid, self.gid, platform="darwin"), [])
```

Check `_restore_modes` in `Base`: it `chmod`s the root and children back to `0o700` before
cleanup, so the `0o000` test cleans up without any further change.

- [ ] **Step 2: Run the tests and confirm what fails**

Run: `python3 infra/hermes-agent/bin/preflight-governance-access.test.py -v`
Expected, on darwin: failures in `test_a_missing_root_is_one_line_naming_the_layout_tool`,
`test_an_unenterable_root_is_one_line`, `test_a_missing_subdirectory_is_reported_as_missing` and
`test_owner_class_wins…`. (The owner-class test fails only if the old cascade produced a
different count; if it passes, that is also acceptable.) The Linux-only CLI test is skipped on
darwin.

- [ ] **Step 3: Implement**

In `_check_dir`, split the `except OSError` around `os.stat(path)`:

```python
    try:
        st = os.stat(path)
    except FileNotFoundError:
        return ("%s: missing — nothing has created it. Create the layout with "
                "init-host-layout.py (dry run, then --apply as root)" % path)
    except OSError as e:
        return "%s: cannot stat (%s)" % (path, e)
```

Add this function directly above `def check(`:

```python
def _root_problem(root):
    """F10: when THIS PROCESS cannot reach the root, every per-child check below it fails
    the same way, and the cascade reads as N permission faults — with a remedy that
    chmods directories that may not exist. One line instead, naming the real cause.

    Real I/O on purpose, unlike the _perm_bits simulation used everywhere else: this is
    about whether the check can run at all, not about what uid 10000 could do."""
    try:
        os.stat(root)
    except FileNotFoundError:
        return ("%s: missing — nothing has created the governance store. Create the "
                "layout with init-host-layout.py (dry run, then --apply as root, then "
                "--check)" % root)
    except OSError as e:
        return "%s: cannot stat (%s)" % (root, e)
    try:
        os.stat(os.path.join(root, "."))      # needs search permission on root itself
    except PermissionError:
        return ("%s: this process (uid %d) cannot enter the store, so nothing below it "
                "can be checked. Run as a member of gid %d, and verify the root with "
                "init-host-layout.py --check" % (root, os.geteuid(), EXECUTOR_GID))
    except OSError as e:
        return "%s: cannot enter (%s)" % (root, e)
    return None
```

In `check()`, directly after the `if not applies(platform): return []` lines:

```python
    p = _root_problem(root)
    if p:
        return [p]
```

Replace `REMEDY` with:

```python
REMEDY = """
Fix by LAYOUT, never by widening a mode. The store's owners and modes are one table
(bin/host_layout.py; README "Ownership on a Linux host"), created and verified by:

    init-host-layout.py --store-root %(root)s              # dry run
    sudo init-host-layout.py --store-root %(root)s --apply  # create what is missing
    sudo -u hermes-broker init-host-layout.py --store-root %(root)s --check

The tool never repairs an existing entry. When --check names a mismatch it prints the
expected owner, group and mode: set exactly that by hand, then re-run --check.

log/ gets NO group write: write on a directory is what grants unlink, and a deleted
audit log costs reversibility (both --undo and the daily caps read through it), not
merely quota. The executor appends to a PRE-CREATED per-client file instead, and setgid
on log/ is what makes host-created files inherit gid %(gid)d — without it, 0660 grants
the wrong group and uid %(uid)d falls through to `other`. Create missing per-client logs
with:

    migrate-governance.py --bootstrap-logs --apply

Do NOT `chmod 777`. The store is the one place Hermes cannot reach; making it
world-writable hands it to every process on the host and removes the isolation this
whole tier is built on."""
```

In `migrate_governance_shim.bootstrap_logs`, change the missing-`log/` message's last sentence
from `"Create it host-side at mode %04o (see the README's ownership section) and re-run."` to:

```python
            "Create the layout with init-host-layout.py --apply (it lays log/ down at "
            "mode %04o, root:hermes) and re-run." % (log_dir, governance_lib.LOG_DIR_MODE))
```

Then run `grep -n "README's ownership section" infra/hermes-agent/bin/migrate-governance.test.py`.
If a test asserts the old wording, update that assertion to `init-host-layout.py`, and list it in
the commit message as a fourth deliberate test edit.

- [ ] **Step 4: Run the suites**

Run: `python3 infra/hermes-agent/bin/preflight-governance-access.test.py && python3 infra/hermes-agent/bin/migrate-governance.test.py && python3 infra/hermes-agent/bin/run-ads-mutate.test.py`
Expected: all pass on darwin. Linux-only assertions run on CI; Task 10 checks them there.

- [ ] **Step 5: Commit**

```bash
git add infra/hermes-agent/bin/preflight-governance-access.py \
        infra/hermes-agent/bin/preflight-governance-access.test.py \
        infra/hermes-agent/bin/migrate_governance_shim.py
# add migrate-governance.test.py only if Step 3 changed it
git commit -m "fix(hermes): pre-flight says 'missing' or 'cannot enter', once (F10)

A root the checking process cannot reach is one line with its own remedy, not
a cascade of 'Permission denied' per child. A missing child says missing. The
remedy points at init-host-layout.py; the chown -R recipe is gone. Deliberate
edits to three existing tests, each explained in its docstring: the owner-class
count, the missing-subdirectory wording, and the Linux-only remedy assertion.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 7: Wiring — broker unit, compose, `.env.example`, contract tests

**Files:**
- Modify: `infra/hermes-agent/deploy/hermes-broker.service`
- Modify: `infra/hermes-agent/docker-compose.yml` (gateway `volumes:`, after `- ./data:/opt/data`, line ~50)
- Modify: `infra/hermes-agent/.env.example` (governance block, ~lines 32–38)
- Test: `infra/hermes-agent/deploy/units.test.py`

**Interfaces:**
- Consumes: `host_layout.DEFAULT_STORE_ROOT`, `host_layout.DEFAULT_SPOOL_ROOT`, and the CLI flags
  from Task 3.

- [ ] **Step 1: Write the failing tests**

In `deploy/units.test.py`, add `import sys` to the imports. Below `HERE = …`, add:

```python
AGENT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(AGENT, "bin"))
import host_layout as H


def live_lines(body):
    """Directive lines only: stripped, no comments, no blanks. A commented-out
    directive is how a gate gets disabled mid-debug and left that way."""
    return [l.strip() for l in body.splitlines()
            if l.strip() and not l.strip().startswith("#")]
```

Append to `class TestUnits`:

```python
    def test_the_layout_check_runs_before_the_preflight(self):
        """F10. The pre-flight predicts what uid 10000 can do; it cannot tell a wrong
        OWNER from a right one with the same bits. The layout --check can. It runs
        first so a wrong layout refuses with its own expected-state lines."""
        pre = [l for l in live_lines(unit("hermes-broker.service"))
               if l.startswith("ExecStartPre=")]
        layout = [i for i, l in enumerate(pre) if "init-host-layout.py" in l]
        flight = [i for i, l in enumerate(pre) if "preflight-governance-access.py" in l]
        self.assertEqual(len(layout), 1, pre)
        self.assertEqual(len(flight), 1, pre)
        self.assertLess(layout[0], flight[0])
        self.assertIn("--check", pre[layout[0]])
        self.assertNotIn("--apply", " ".join(pre))

    def test_the_broker_writes_only_the_store_and_the_spool(self):
        rw = [l.split("=", 1)[1].split() for l in live_lines(unit("hermes-broker.service"))
              if l.startswith("ReadWritePaths=")]
        self.assertEqual(rw, [[H.DEFAULT_STORE_ROOT, H.DEFAULT_SPOOL_ROOT]])

    def test_no_live_directive_points_the_broker_at_data_spool(self):
        """F10b: under the gateway-owned data/, the spool is a redirect into the store."""
        for l in live_lines(unit("hermes-broker.service")):
            self.assertNotIn("data/spool", l)


class TestSpoolPathContract(unittest.TestCase):
    """F10b. The unit, .env.example, the compose mount and host_layout must name one
    spool path, and compose must have no fallback to a path under data/."""

    def read(self, rel):
        return open(os.path.join(AGENT, rel), encoding="utf-8").read()

    def test_unit_and_env_example_agree_with_the_layout(self):
        self.assertIn("Environment=HERMES_SPOOL_ROOT=%s" % H.DEFAULT_SPOOL_ROOT,
                      live_lines(unit("hermes-broker.service")))
        self.assertRegex(self.read(".env.example"),
                         r"(?m)^HERMES_SPOOL_DIR=%s$" % re.escape(H.DEFAULT_SPOOL_ROOT))

    def test_the_gateway_mounts_the_spool_with_no_fallback(self):
        mounts = [l for l in live_lines(self.read("docker-compose.yml"))
                  if "/opt/data/spool" in l]
        self.assertEqual(len(mounts), 1, mounts)
        source = mounts[0].split(":/opt/data/spool")[0]
        self.assertTrue(source.startswith("- ${HERMES_SPOOL_DIR:?"), mounts[0])
        self.assertNotIn(":-", source)
```

- [ ] **Step 2: Run the tests and confirm they fail**

Run: `python3 infra/hermes-agent/deploy/units.test.py`
Expected: the four new tests (layout-check order, ReadWritePaths, data/spool, contract) FAIL
against the current files.

- [ ] **Step 3: Edit the unit**

In `deploy/hermes-broker.service`, replace the two comment lines above `User=` with:

```
# Its own user. .env.gaw is readable ONLY by this user, so even the deploy user's shell
# cannot read the write credential (spec §16.2). The governance store is NOT private to
# it: the executor (uid 10000) reads the store through group hermes (bin/host_layout.py).
```

Replace `Environment=HERMES_SPOOL_ROOT=/opt/hermes-agent/data/spool` with:

```
# Outside data/ on purpose (F10b): data/ is owned by the gateway's uid, which could
# rename the spool and leave a symlink into the governance store in its place.
Environment=HERMES_SPOOL_ROOT=/var/lib/hermes/spool
```

Replace the single `ExecStartPre=…preflight-governance-access.py…` directive (both lines) with:

```
# F10: the layout first — exact owners and modes, including what the pre-flight cannot
# see (a wrong OWNER with the right bits). It never repairs; a mismatch prints the
# expected state. Then the executor-access pre-flight.
ExecStartPre=/usr/bin/python3 /opt/hermes-agent/bin/init-host-layout.py --check \
    --store-root /var/lib/hermes/governance --spool-root /var/lib/hermes/spool
ExecStartPre=/usr/bin/python3 /opt/hermes-agent/bin/preflight-governance-access.py \
    --root /var/lib/hermes/governance
```

Keep the existing comment above the old `ExecStartPre` (the one about refusing at BOOT), directly
above the pre-flight directive. Replace `ReadWritePaths=` with:

```
ReadWritePaths=/var/lib/hermes/governance /var/lib/hermes/spool
```

- [ ] **Step 4: Edit compose and `.env.example`**

In `docker-compose.yml`, in the gateway service's `volumes:`, directly after
`- ./data:/opt/data                # Hermes state (gitignored)`:

```yaml
      # The request spool (F10b). Its own bind, OUTSIDE ./data: data/ is owned by the
      # gateway's uid, so a spool under it could be renamed and replaced with a symlink
      # the host-side broker would follow. Mounted here, /opt/data/spool is a mount point
      # the gateway cannot rename (EBUSY). No fallback on purpose: an unset variable must
      # stop compose, never quietly mean ./data/spool. Locally, HERMES_SPOOL_DIR=./data/spool
      # is fine — darwin has no uid separation to protect.
      - ${HERMES_SPOOL_DIR:?HERMES_SPOOL_DIR must be set, see README Spool layout}:/opt/data/spool
```

In `.env.example`, in the governance block, replace `# Create it mode 700. Compose does not
expand ~, so write the path in full.` with:

```
# On a Linux host, init-host-layout.py creates it (README "VPS deploy sequence" step 2);
# locally, any directory you own. Compose does not expand ~, so write the path in full.
```

Then add, directly after the `HERMES_GOVERNANCE_DIR=…` line:

```

# --- Request spool (mutation tier) ---
# Absolute host path to the spool: the only channel between Hermes and the broker. NOT
# free-choice on a VPS: hermes-broker.service hardcodes it, and init-host-layout.py
# creates it. Must be OUTSIDE ./data (F10b). REQUIRED — compose refuses to start without
# it. Locally, ./data/spool is acceptable.
HERMES_SPOOL_DIR=/var/lib/hermes/spool
```

In `.env.example`, fix the stale line references in the governance comment
(`hermes-broker.service:20-21`). Re-measure them with
`grep -n "HERMES_GOVERNANCE" infra/hermes-agent/deploy/hermes-broker.service` and write the new
numbers.

Do **not** edit your local, gitignored `.env`. Do **not** run `docker compose config`. Note for
the PR body: a local `.env` without `HERMES_SPOOL_DIR` now stops `docker compose up` with the
message above, until `HERMES_SPOOL_DIR=./data/spool` is added.

- [ ] **Step 5: Run the suites**

Run: `python3 infra/hermes-agent/deploy/units.test.py && python3 infra/hermes-agent/deploy/provision.test.py && infra/hermes-agent/bin/run-bin-tests.sh`
Expected: all pass. If `proxy-policy-sync.test.py`, `registry-invariants.test.py` or
`apply-changeset.test.py` (the suites that read compose or `.env.example`) go red, read the
assertion. Fix only if it pins something this task legitimately changed, and say so in the
commit message. Do not touch the proxy allow-list.

- [ ] **Step 6: Commit**

```bash
git add infra/hermes-agent/deploy/hermes-broker.service infra/hermes-agent/deploy/units.test.py \
        infra/hermes-agent/docker-compose.yml infra/hermes-agent/.env.example
git commit -m "feat(hermes): spool at /var/lib/hermes/spool; layout --check gates the broker (F10b)

The broker unit's spool path and ReadWritePaths move out of the gateway-owned
data/, and init-host-layout.py --check runs before the pre-flight. The gateway
bind-mounts \${HERMES_SPOOL_DIR:?} at the unchanged /opt/data/spool, with no
fallback. units.test.py pins the order and the path contract across the unit,
.env.example, compose and host_layout.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 8: Tier 2 — real uids on the Linux CI runner

**Files:**
- Create: `infra/hermes-agent/deploy/layout-integration.test.py`
- Modify: `.github/workflows/ci.yml` (the `tests` job, after the "Provisioning script suite" step)

**Interfaces:**
- Consumes: the `init-host-layout.py` CLI, `hermes-syscall.py apply|result --request-id`,
  `hermes-broker.py --once` (exit 0), `preflight-governance-access.py --root`,
  `migrate-governance.py --bootstrap-logs --apply --governance-root`, and the literal line
  `SPOOL_FILE_MODE = 0o640` in `spool_lib.py`.

- [ ] **Step 1: Write the suite**

Create `infra/hermes-agent/deploy/layout-integration.test.py`:

```python
#!/usr/bin/env python3
"""Tier 2 for F10: the store and spool layout under REAL Linux uids, gids and modes.

WHY A SEPARATE SUITE. Tier 1 (bin/host_layout.test.py and friends) runs as one
unprivileged user. It proves the table and the checks. It cannot prove that the gateway
(uid 10000) and the broker (hermes-broker) can each do what they must and nothing more.
That needs root, to create the identities, and setpriv, to become them.

WHERE IT RUNS. As root on Linux: the CI `tests` job runs it under sudo with
HERMES_REQUIRE_LINUX_INTEGRATION=1. Anywhere else it prints SKIPPED and exits 0 —
unless that variable is set, in which case any skip is a FAILURE. It prints how many
tests executed. Read that line in the CI log on the PR and on the merge commit: a green
job that executed 0 tests proves nothing.

NOT FOR THE VPS. It creates users and groups (idempotently, README step 1's names) and
writes under /var/lib. Run it on a CI runner, not on the deploy target.

UNPROVEN HERE (spec §5.3): systemd's ProtectSystem=strict with the new ReadWritePaths;
the real gateway identity inside the hermes-agent image; compose's :? interpolation
against a real .env.
"""
import os, shutil, stat, subprocess, sys, tempfile, unittest, uuid

HERE = os.path.dirname(os.path.abspath(__file__))
AGENT = os.path.dirname(HERE)
REQUIRED = os.environ.get("HERMES_REQUIRE_LINUX_INTEGRATION") == "1"
GATEWAY = ["setpriv", "--reuid", "10000", "--regid", "10000", "--clear-groups"]
# The broker unit's identity: User/Group hermes-broker, SupplementaryGroups hermes-rail hermes.
BROKER = ["setpriv", "--reuid", "hermes-broker", "--regid", "hermes-broker",
          "--groups", "hermes,hermes-rail"]
CID = "20260921-000000-abcdef01"
CLIENT = "slug-1"          # sanctioned fixture, deliberately NOT registered


def why_not_runnable():
    if not sys.platform.startswith("linux"):
        return "not Linux"
    if os.geteuid() != 0:
        return "not root"
    if shutil.which("setpriv") is None:
        return "setpriv not found"
    return None


def run(argv, env=None, check=False):
    return subprocess.run(argv, env=env, capture_output=True, text=True, check=check)


def setUpModule():
    why = why_not_runnable()
    if why:
        raise unittest.SkipTest(why)
    run(["groupadd", "-f", "hermes-rail"], check=True)
    run(["groupadd", "-f", "hermes-broker"], check=True)
    g = run(["getent", "group", "hermes"])
    if g.returncode != 0:
        run(["groupadd", "-g", "10000", "hermes"], check=True)
    elif g.stdout.split(":")[2] != "10000":
        raise RuntimeError("group 'hermes' is gid %s here, not 10000"
                           % g.stdout.split(":")[2])
    if run(["id", "hermes-broker"]).returncode != 0:
        run(["useradd", "--system", "--no-create-home", "--shell", "/usr/sbin/nologin",
             "-g", "hermes-broker", "hermes-broker"], check=True)


class Layout(unittest.TestCase):
    """A fresh layout per test, created the documented way: init-host-layout.py --apply,
    as root, from a private copy of bin/ that both identities can read."""

    def setUp(self):
        self.base = tempfile.mkdtemp(prefix="hermes-f10-it-", dir="/var/lib")
        self.addCleanup(shutil.rmtree, self.base, True)
        os.chmod(self.base, 0o755)
        agent = os.path.join(self.base, "agent")
        os.mkdir(agent, 0o755)
        self.bin = os.path.join(agent, "bin")
        skip = shutil.ignore_patterns("__pycache__", "*.pyc")
        shutil.copytree(os.path.join(AGENT, "bin"), self.bin, ignore=skip)
        shutil.copytree(os.path.join(AGENT, "registry"), os.path.join(agent, "registry"),
                        ignore=skip)
        run(["chmod", "-R", "a+rX", agent], check=True)
        self.store = os.path.join(self.base, "governance")
        self.spool = os.path.join(self.base, "spool")
        self.env = {"PATH": "/usr/sbin:/usr/bin:/sbin:/bin", "PYTHONDONTWRITEBYTECODE": "1",
                    "HERMES_SPOOL_ROOT": self.spool, "HERMES_GOVERNANCE_ROOT": self.store,
                    "VAULT_ROOT": os.path.join(self.base, "vaults")}
        r = self.layout_tool("--apply")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def py(self, name):
        return os.path.join(self.bin, name)

    def path(self, *parts):
        return os.path.join(self.spool, *parts)

    def layout_tool(self, *flags, who=()):
        return run(list(who) + ["python3", self.py("init-host-layout.py"),
                                "--store-root", self.store, "--spool-root", self.spool,
                                *flags], env=self.env)

    def gateway(self, *argv):
        return run(GATEWAY + list(argv), env=self.env)

    def broker(self, *argv):
        return run(BROKER + list(argv), env=self.env)

    def gw_os(self, fn, *args):
        """os.<fn>(*args) as the gateway. True if it succeeded."""
        r = self.gateway("python3", "-c", "import os, sys; os.%s(*sys.argv[1:])" % fn, *args)
        return r.returncode == 0

    def gw_create(self, p):
        r = self.gateway("python3", "-c", "import sys; open(sys.argv[1], 'w').close()", p)
        return r.returncode == 0

    def gw_plant_dir(self, mode, content=True):
        """The gateway mkdirs a UUID-named entry in requests/, optionally non-empty."""
        p = self.path("requests", "%s.json" % uuid.uuid4())
        code = ("import os, sys; os.mkdir(sys.argv[1]);"
                "sys.argv[3] == '1' and open(os.path.join(sys.argv[1], 'x'), 'w').close();"
                "os.chmod(sys.argv[1], int(sys.argv[2], 8))")
        r = self.gateway("python3", "-c", code, p, mode, "1" if content else "0")
        self.assertEqual(r.returncode, 0, r.stderr)
        return p

    def submit(self):
        r = self.gateway("python3", self.py("hermes-syscall.py"), "apply",
                         "--client", CLIENT, "--changeset", CID)
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout.strip()

    def fetch(self, rid):
        return self.gateway("python3", self.py("hermes-syscall.py"), "result",
                            "--request-id", rid)

    def drain(self):
        r = self.broker("python3", self.py("hermes-broker.py"), "--once")
        self.assertEqual(r.returncode, 0, r.stderr)
        return r

    def assert_check_names(self, needle):
        r = self.layout_tool("--check")
        self.assertEqual(r.returncode, 2, r.stdout)
        self.assertIn(needle, r.stderr)


class TestGates(Layout):
    def test_layout_check_passes_as_the_broker(self):
        r = self.layout_tool("--check", who=BROKER)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_preflight_passes_as_the_broker_on_a_fresh_store(self):
        """The state the bring-up never reached."""
        r = self.broker("python3", self.py("preflight-governance-access.py"),
                        "--root", self.store)
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_preflight_on_a_missing_root_is_one_line(self):
        r = self.broker("python3", self.py("preflight-governance-access.py"),
                        "--root", os.path.join(self.base, "absent"))
        self.assertEqual(r.returncode, 2)
        lines = [l for l in r.stderr.splitlines() if l.startswith("  - ")]
        self.assertEqual(len(lines), 1, r.stderr)
        self.assertIn("missing", lines[0])

    def test_bootstrap_logs_accepts_the_fresh_store(self):
        r = run(["python3", self.py("migrate-governance.py"), "--bootstrap-logs",
                 "--apply", "--governance-root", self.store], env=self.env)
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_a_layout_under_tmp_is_refused_and_nothing_is_created(self):
        """Firing control for the ancestor check: /tmp is world-writable."""
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        r = run(["python3", self.py("init-host-layout.py"), "--apply",
                 "--store-root", os.path.join(tmp, "g"),
                 "--spool-root", os.path.join(tmp, "s")], env=self.env)
        self.assertEqual(r.returncode, 2, r.stdout)
        self.assertIn("writable", r.stderr)
        self.assertEqual(os.listdir(tmp), [])

    def test_the_bring_up_store_is_refused_until_it_is_removed(self):
        """Spec §3.4: the VPS store is an empty 700 root:root dir. Refuse, rmdir, apply."""
        shutil.rmtree(self.store)
        os.mkdir(self.store, 0o700)
        r = self.layout_tool("--apply")
        self.assertEqual(r.returncode, 2)
        self.assertIn("expected root:hermes 0750", r.stderr)
        os.rmdir(self.store)
        r = self.layout_tool("--apply")
        self.assertEqual(r.returncode, 0, r.stderr)


class TestRoundTrip(Layout):
    def test_gateway_request_broker_result_gateway_read(self):
        rid = self.submit()
        req = self.path("requests", rid + ".json")
        st = os.stat(req)
        self.assertEqual((st.st_uid, st.st_gid, stat.S_IMODE(st.st_mode)),
                         (10000, 10000, 0o640))
        self.drain()
        self.assertFalse(os.path.exists(req))
        r = self.fetch(rid)
        self.assertNotIn("result_unreadable", r.stdout)
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)   # refused: unregistered
        self.assertIn("refused", r.stdout)

    def test_firing_control_0600_spool_files_break_the_round_trip(self):
        """F10a reinstated in this test's private copy of the code: the same round trip
        must now fail with result_unreadable. Proves the test above can go red."""
        p = self.py("spool_lib.py")
        with open(p) as f:
            src = f.read()
        needle = "SPOOL_FILE_MODE = 0o640"
        self.assertEqual(src.count(needle), 1, "control is vacuous: the constant moved")
        with open(p, "w") as f:
            f.write(src.replace(needle, "SPOOL_FILE_MODE = 0o600"))
        rid = self.submit()
        self.drain()
        self.assertIn("result_unreadable", self.fetch(rid).stdout)


class TestAttackProbes(Layout):
    """As uid 10000, against the correct layout: each attack fails."""

    def test_the_gateway_cannot_remove_rename_or_list_quarantine(self):
        q = self.path("requests", ".quarantine")
        self.assertFalse(self.gw_os("rename", q, q + "-moved"))
        self.assertFalse(self.gw_os("rmdir", q))
        self.assertFalse(self.gw_os("listdir", q))

    def test_the_gateway_cannot_rename_requests_or_results(self):
        self.assertFalse(self.gw_os("rename", self.path("requests"), self.path("r2")))
        self.assertFalse(self.gw_os("rename", self.path("results"), self.path("r3")))

    def test_the_gateway_cannot_forge_a_result(self):
        self.assertFalse(self.gw_create(self.path("results", "%s.json" % uuid.uuid4())))

    # Firing controls: each wrong layout lets the attack through, and --check names it.

    def test_control_without_the_sticky_bit_the_gateway_renames_quarantine(self):
        os.chmod(self.path("requests"), 0o2770)
        q = self.path("requests", ".quarantine")
        self.assertTrue(self.gw_os("rename", q, q + "-moved"))
        self.assert_check_names("expected hermes-broker:hermes 3770")

    def test_control_a_group_writable_results_lets_the_gateway_forge(self):
        os.chmod(self.path("results"), 0o2770)
        self.assertTrue(self.gw_create(self.path("results", "%s.json" % uuid.uuid4())))
        self.assert_check_names("expected hermes-broker:hermes 2750")

    def test_control_without_a_precreated_quarantine_the_gateway_claims_it(self):
        q = self.path("requests", ".quarantine")
        os.rmdir(q)
        self.assertTrue(self.gw_os("mkdir", q))
        self.assert_check_names(".quarantine")


class TestQuarantineOwnership(Layout):
    def test_control_a_planted_directory_goes_to_the_real_quarantine(self):
        p = self.gw_plant_dir("777")               # writable, so it CAN be moved
        self.drain()
        self.assertFalse(os.path.exists(p))
        self.assertEqual(len(os.listdir(self.path("requests", ".quarantine"))), 1)

    def test_a_gateway_created_quarantine_is_refused(self):
        q = self.path("requests", ".quarantine")
        os.rmdir(q)
        self.assertTrue(self.gw_os("mkdir", q))
        r = self.gateway("python3", "-c", "import os, sys; os.chmod(sys.argv[1], 0o777)", q)
        self.assertEqual(r.returncode, 0, r.stderr)
        p = self.gw_plant_dir("777")
        r = self.drain()
        self.assertTrue(os.path.isdir(p))
        self.assertEqual(os.listdir(q), [])
        self.assertIn(".quarantine", r.stderr)


class TestPlantedDirectories(Layout):
    """R1: the drain survives what it cannot remove, and still serves real requests."""

    def test_empty_is_removed_non_empty_stays_and_the_real_request_is_served(self):
        empty = self.gw_plant_dir("700", content=False)
        full = self.gw_plant_dir("700")
        rid = self.submit()
        for _ in range(2):                        # the residual repeats; nothing sticks
            r = self.drain()
            self.assertFalse(os.path.exists(empty))
            self.assertTrue(os.path.isdir(full))
            self.assertIn(os.path.basename(full), r.stderr)
        f = self.fetch(rid)
        self.assertEqual(f.returncode, 2, f.stdout)
        self.assertNotIn("result_unreadable", f.stdout)


class TestSpoolMountPoint(Layout):
    """F10b's premise: inside the container, a bind-mounted spool cannot be renamed."""

    def setUp(self):
        super().setUp()
        if shutil.which("docker") is None or run(["docker", "info"]).returncode != 0:
            self.skipTest("docker unavailable")
        self.data = os.path.join(self.base, "data")
        os.mkdir(self.data)
        os.chown(self.data, 10000, 10000)
        os.chmod(self.data, 0o700)

    def mv(self, *mounts):
        argv = ["docker", "run", "--rm", "--user", "10000:10000"]
        for m in mounts:
            argv += ["-v", m]
        return run(argv + ["busybox:1.36", "mv", "/opt/data/spool", "/opt/data/moved"])

    def test_the_gateway_cannot_move_the_bind_mounted_spool(self):
        r = self.mv(self.data + ":/opt/data", self.spool + ":/opt/data/spool")
        self.assertNotEqual(r.returncode, 0, r.stdout)
        self.assertTrue(os.path.isdir(self.path("requests")))

    def test_control_a_spool_under_data_is_movable(self):
        os.mkdir(os.path.join(self.data, "spool"))
        os.chown(os.path.join(self.data, "spool"), 10000, 10000)
        r = self.mv(self.data + ":/opt/data")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(os.path.isdir(os.path.join(self.data, "moved")))


if __name__ == "__main__":
    why = why_not_runnable()
    if why:
        print("layout-integration: SKIPPED — %s" % why)
        sys.exit(1 if REQUIRED else 0)
    suite = unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__])
    res = unittest.TextTestRunner(verbosity=2).run(suite)
    executed = res.testsRun - len(res.skipped)
    print("layout-integration: executed %d, skipped %d, failures %d, errors %d"
          % (executed, len(res.skipped), len(res.failures), len(res.errors)))
    if not res.wasSuccessful():
        sys.exit(1)
    if REQUIRED and (res.skipped or executed == 0):
        print("layout-integration: HERMES_REQUIRE_LINUX_INTEGRATION=1 and not every test "
              "executed — failing", file=sys.stderr)
        sys.exit(1)
```

- [ ] **Step 2: Confirm it skips cleanly on darwin, and fails when it is required**

Run: `python3 infra/hermes-agent/deploy/layout-integration.test.py; echo "exit $?"`
Expected: `layout-integration: SKIPPED — not Linux` and `exit 0`.

Run: `HERMES_REQUIRE_LINUX_INTEGRATION=1 python3 infra/hermes-agent/deploy/layout-integration.test.py; echo "exit $?"`
Expected: the same line and `exit 1`. This is the firing control for "proof it ran".

Run: `python3 -m py_compile infra/hermes-agent/deploy/layout-integration.test.py`
Expected: no output.

- [ ] **Step 3: Add the CI step**

In `.github/workflows/ci.yml`, in the `tests` job, after the "Provisioning script suite" step:

```yaml
      # F10 Tier 2: root, real uids/gids/modes, and Docker for the mount-point probe.
      # HERMES_REQUIRE_LINUX_INTEGRATION=1 turns any skip into a failure, and the suite
      # prints "executed N" — read that line on the PR run AND on the merge commit.
      - name: Host layout integration (root, real ids)
        run: sudo env HERMES_REQUIRE_LINUX_INTEGRATION=1 python3 infra/hermes-agent/deploy/layout-integration.test.py
```

- [ ] **Step 4: Commit**

```bash
git add infra/hermes-agent/deploy/layout-integration.test.py .github/workflows/ci.yml
git commit -m "test(hermes): F10 Tier 2 — real uids on the Linux runner

Round trip as uid 10000 and hermes-broker, with an in-test firing control that
reinstates F10a and must produce result_unreadable; attack probes, each paired
with a wrong layout where the attack succeeds and --check names it; quarantine
ownership; R1's planted directories; the mount-point probe. Required on CI:
any skip fails, and the executed count is printed.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

This suite cannot run on darwin. Its first real run is the PR's CI (Task 10). Budget for one
fix-up round there. If it fails, apply `superpowers:systematic-debugging` to the CI log. Do not
loosen an assertion to get green.

---

### Task 9: Documentation — README, BRING-UP, findings record

**Files:**
- Modify: `infra/hermes-agent/README.md`
- Modify: `infra/hermes-agent/deploy/BRING-UP.md`
- Modify: `docs/superpowers/specs/2026-09-21-vps-first-bring-up-findings.md`

Re-measure every line number named here with `grep -n` before editing. They are from 2026-09-21.

- [ ] **Step 1: README — "Spool layout" (heading `### Spool layout`, ~line 719)**

Replace the section body, from the heading down to the paragraph ending "…a quarantine for
entries it cannot parse.", with:

````markdown
### Spool layout

On a Linux host the spool is `/var/lib/hermes/spool` (`HERMES_SPOOL_DIR` in `.env`), bind-mounted
into the gateway at `/opt/data/spool`. Host-side callers use `HERMES_SPOOL_ROOT`.

```
/var/lib/hermes/spool/               root:hermes            0750
  requests/                          hermes-broker:hermes   3770  (setgid + sticky)
    .quarantine/                     hermes-broker:hermes-broker 0700
    <request_id>.json                10000:hermes           0640  Hermes writes; the broker reads and deletes
  results/                           hermes-broker:hermes   2750
    <request_id>.json                hermes-broker:hermes   0640  the broker writes; Hermes reads
```

`init-host-layout.py` creates it (see "Ownership on a Linux host"). The modes do work:

- **Sticky `requests/`, owned by the broker.** The gateway can create requests but cannot delete
  or rename anything the broker owns, including `.quarantine/`. The broker, as the directory's
  owner, can delete the gateway's requests.
- **Pre-created `.quarantine/`.** If it did not exist, the gateway could create the name first —
  as a symlink, or as a directory it controls — and the broker would move entries through it.
  The broker also re-checks it on every use: a real directory, its own, not group- or
  world-writable.
- **Group-read-only `results/`.** The gateway cannot forge a result.
- **`0640` files, set on the fd.** Both sides are different users on Linux. `mkstemp`'s `0600`
  made every request unreadable to the broker and every result unreadable to the gateway (F10a).

**Why not `data/spool`.** `data/` is owned by the gateway's uid. A spool under it could be renamed
and replaced with a symlink, which the host-side broker would follow into the only other tree it
can write: the governance store (F10b). As a separate bind mount, `/opt/data/spool` is a mount
point the gateway cannot rename. Compose has no fallback: an unset `HERMES_SPOOL_DIR` stops
`docker compose up`. On a laptop, `HERMES_SPOOL_DIR=./data/spool` is fine, because darwin has
no uid separation to protect.

`<request_id>` is a uuid, and the filename must match the `request_id` inside the file. The broker
treats every byte here as hostile: closed schema, size cap, regular-files-only, no symlinks, no
directories, and a quarantine for entries it cannot parse.

**Known residual.** A non-empty directory the gateway plants in `requests/` can be neither removed
nor quarantined by a non-root broker, because moving a directory needs write on it. It stays in
place and is re-rejected and logged on every drain. Other requests are still served. Remove it as
root.
````

In the "Client" code block below, change `result --request <request_id>` to
`result --request-id <request_id>`.

- [ ] **Step 2: README — syscall "Deploy sequence" step 1 (~line 801)**

Replace step 1 with:

```markdown
1. **Governance store and spool in place** — created by `init-host-layout.py --apply` and verified
   by `--check` (see "Ownership on a Linux host"). `seen/` is host-only and must **not** be mounted
   into the executor.
```

- [ ] **Step 3: README — "Governance store" paragraph (~line 838)**

Replace `Create it mode \`700\` before first use; Compose does not expand \`~\`, so write the
path in full` with:

```markdown
On a Linux host `init-host-layout.py` creates it, with the owners and modes below; locally, any
directory you own. Compose does not expand `~`, so write the path in full
```

Keep the rest of that sentence and paragraph.

- [ ] **Step 4: README — "Ownership on a Linux host" (~line 892)**

Replace everything from `### Ownership on a Linux host` up to, but not including,
`**Migration** copies…` with:

````markdown
### Ownership on a Linux host

The store is shared by three identities: the broker (`hermes-broker`), the one-shot executor
(`ads-mutator`, **uid 10000**, `Dockerfile`: `USER hermes`) and root. On Linux they share one
UID namespace with the host. On macOS none of this shows, because Docker Desktop remaps
ownership, so the local gate passes and the VPS is where it breaks. The layout is one table,
`bin/host_layout.py`:

| Path | Owner:group | Mode | Why |
|---|---|---|---|
| (root) | `root:hermes` | `0750` | broker and executor traverse; only root renames children |
| `approvals/` | `hermes-broker:hermes` | `2750` | the broker reserves and records; the executor reads |
| `control/` | `root:hermes` | `2750` | **only root can create the kill switch** — the broker cannot enable mutation |
| `control/.locks/` | `hermes-broker:hermes-broker` | `0700` | the broker's per-client locks |
| `registry/` | `root:hermes` | `2750` | operator-edited |
| `registry/clients.json` | `root:hermes` | `0640` | created as `{}` only if absent |
| `log/` | `root:hermes` | `2750` | append-but-not-unlink (below) |
| `seen/` | `hermes-broker:hermes-broker` | `0700` | broker-only replay state |

Create and verify it with the governed operator CLI. It is a dry run by default. `--apply`
creates only what is missing, and **refuses — creating nothing — if anything that exists is
wrong**. It never repairs.

```bash
python3 infra/hermes-agent/bin/init-host-layout.py                       # dry run
sudo python3 infra/hermes-agent/bin/init-host-layout.py --apply
sudo -u hermes-broker python3 infra/hermes-agent/bin/init-host-layout.py --check
```

The same `--check` is the broker unit's first `ExecStartPre`. A mismatch line names the path,
what it found and the expected `owner:group mode`. Set exactly that by hand, then re-run
`--check`.

**Editing the client registry.** An editor that replaces `clients.json` recreates it with the
editor's owner and umask, and `--check` then stops the broker. Edit a copy, then install it in
place:

```bash
sudo install -o root -g hermes -m 0640 clients.json.new /var/lib/hermes/governance/registry/clients.json
```

`log/` gets **no group write**. Write on a directory is what grants `unlink`, and
both the undo path and the daily caps read through `iter_log_records`, so an
executor that can delete `log/<slug>.jsonl` destroys the reversibility record — not
merely a quota. It appends to a **pre-created** per-client file instead; `setgid` on
`log/` is what makes those files inherit gid 10000, without which `0660` grants
the operator's own group and uid 10000 falls through to `other`.

Create the per-client logs. This is required for every registered client, and idempotent:

```bash
infra/hermes-agent/bin/migrate-governance.py --bootstrap-logs            # dry run
infra/hermes-agent/bin/migrate-governance.py --bootstrap-logs --apply
```

`seen/` is not mounted into the executor at all and needs no access for uid 10000.
Widening it would hand the governed party the replay-protection state again.

**Accepted residual.** `hermes-broker` is in gid 10000 so it can read `clients.json`, which
also gives it group write on `log/*.jsonl`. It can truncate an audit log, though it cannot
unlink one. Closing that needs a second, executor-only group. It is not justified now: the
broker already owns `approvals/` and `seen/`, so a compromised broker is already past it.

**Never `chmod 777`**, and never `chown -R` the store to the executor. POSIX selects the owner
class first, so an executor-owned `log/` is writable by it however tight the mode looks. The
store is the one tree Hermes cannot reach; making it world-writable hands it to every process
on the host.

`run-ads-mutate.sh` pre-flights executor access before it does anything else
(`bin/preflight-governance-access.py`), so a bad store surfaces as a refusal with the remedy
printed, rather than as an exit-3 failure halfway through an apply. The check is a no-op on
non-Linux, where a stat-based prediction would be false.
````

- [ ] **Step 5: README — "VPS deploy sequence" step 2 (~line 1011)**

Replace step 2 with:

````markdown
2. **Lay out the governance store and the spool.**

   On the box from the first bring-up (2026-09-21), the store exists as an **empty**
   `700 root:root` directory. The tool refuses it like any other mismatch. Remove it first
   (`rmdir` succeeds only on an empty directory, which is the check):

   ```bash
   sudo rmdir /var/lib/hermes/governance
   ```

   Set `HERMES_SPOOL_DIR=/var/lib/hermes/spool` in `.env` (see `.env.example`). Then, from
   `/opt/hermes-agent`:

   ```bash
   python3 bin/init-host-layout.py                              # dry run: every line "create"
   sudo python3 bin/init-host-layout.py --apply
   sudo -u hermes-broker python3 bin/init-host-layout.py --check      # must exit 0
   sudo -u hermes-broker python3 bin/preflight-governance-access.py \
     --root /var/lib/hermes/governance                                # must exit 0
   ```

   Both checks run as `hermes-broker`, as the broker unit will. The pre-flight passes on the
   fresh store because `clients.json` is `{}`, which means zero registered clients.
````

Step 3 (`--bootstrap-logs`) stays, and still comes before any unit is enabled. It is a no-op with
zero clients.

- [ ] **Step 6: BRING-UP.md — Phase 2 (~line 192)**

In the layout table, change the `/opt/hermes-agent` row's "Holds" cell to `` `bin/`, `registry/` ``.
Add a row after the governance row:

```markdown
| `/var/lib/hermes/spool` | the request spool | `hermes-broker.service` (`HERMES_SPOOL_ROOT`, `ReadWritePaths`); `docker-compose.yml` (`HERMES_SPOOL_DIR`) |
```

Re-measure the unit line numbers in the `Required by` cells with
`grep -n "opt/hermes-agent\|var/lib/hermes" infra/hermes-agent/deploy/*.service`, and update them.
In the commands block, replace `sudo install -d -m 700 /var/lib/hermes/governance` with:

```bash
sudo install -d -m 755 -o root -g root /var/lib/hermes
# the store and the spool under it are created by README "VPS deploy sequence" step 2
```

Replace the verify line `sudo stat -c '%a %U:%G %n' /var/lib/hermes/governance       # 700 root:root`
with `sudo stat -c '%a %U:%G %n' /var/lib/hermes                  # 755 root:root`.

- [ ] **Step 7: BRING-UP.md — Phase 6 (~line 386)**

Replace everything from the `**Blocked as of 2026-09-21 …**` paragraph through the paragraph
ending `…that does not exist yet.` with:

```markdown
**Blocked on F9 only** (the bind paths vs the proxy allow-list — see
`docs/superpowers/specs/2026-09-21-vps-first-bring-up-findings.md`). The store and spool layout
(F10) is landed: README "VPS deploy sequence" step 2 creates both on a fresh box with
`init-host-layout.py`, and the broker unit verifies them at every start. README step 1 (users
and groups) was run and verified on 2026-09-21.
```

Change the following sentence `Once the bind paths match (or are reconciled) **and the
store/spool layout is landed**, hand off to:` to `Once the bind paths match (or are reconciled),
hand off to:`.

- [ ] **Step 8: Findings record**

In `docs/superpowers/specs/2026-09-21-vps-first-bring-up-findings.md`:

- Outcome table, row 6: `| 6 Units | **parked** — README step 1 done and verified; the store/spool layout (F10) is fixed in PR #<N>; step 2+ still waits on F9 |`
- At the end of the F10 section, replace `**Open:** design and land the layout, with a test, before
  Phase 6 resumes. The units were not installed.` with:

```markdown
**Fixed** in PR #<N> (design: `docs/superpowers/specs/2026-09-21-f10-governance-store-and-spool-layout-design.md`).
Reading the code to design the layout found three more faults, fixed in the same PR:

- **F10a — the spool could not work on Linux in either direction.** Both sides wrote `0600`
  (`mkstemp`), so the broker could not read requests and the gateway could not read results.
  Spool files are now `0640`, set on the fd.
- **F10b — a spool under `data/` redirects the broker into the store.** The gateway owns `data/`,
  so it could swap the spool, or a pre-planted `.quarantine`, for a symlink. The spool moved to
  `/var/lib/hermes/spool` as its own bind mount, and the broker verifies `.quarantine` before use.
- **The pre-flight cascade.** A missing or unenterable root is now one line naming
  `init-host-layout.py`. A missing child says "missing".

Stated residual: a non-empty directory the gateway plants in `requests/` stays in place and is
logged on every drain (R1). Unproven until the VPS: the systemd sandbox with the new
`ReadWritePaths`, the gateway's real identity in the image, and compose's `:?` against the real
`.env`.

**Effect on F9.** The spool is not mounted into `ads-mutator` and is not in the proxy allow-list,
so F10 adds nothing there. The store's host path is unchanged. F9's design must not move the spool
back under `data/`.
```

- Add a new section after F11:

```markdown
### F12: approvals and run records are written by host-side tools that cannot reach `data/vaults` (recorded, not fixed)

Found while designing F10. `approve-changeset.py` reads the change-set from `data/vaults/`
(uid 10000, `700`) and writes `approvals/<slug>/` plus a `0600` lock file that the broker later
reopens. Run as root, it leaves root-owned `0600` locks, and `reserve_approval` fails on the
first apply. Run as `hermes-broker`, it cannot read `data/vaults`. Approval and snapshot files
are written with plain `open()`, so they are group-readable only because of the umask; the
2026-09-17 handoff's §6 `UMask=0077` would make every approval unreadable to the executor.

Second case: `run-ads-mutate.sh` runs as `hermes-broker` inside the broker's sandbox, and after
every apply it calls `persist-run-record.py`, which writes into `data/vaults/<slug>/`. `data/` is
`700` uid 10000, and `data/vaults` is not in `ReadWritePaths`, so the write fails. The failure
shows as the "RUN RECORD NOT PERSISTED" banner, with the executor's exit status kept.

**Gates creating the kill switch, not Phase 6.** Installing the units approves nothing.
F10's `approvals/` ownership (`hermes-broker:hermes 2750`) is compatible with any F12 fix.
```

- In "Open items, in order", replace item 1 with
  `1. F9: the allow-list and compose path design. This unblocks Phase 6.`, and renumber the rest.
  Append `N. F12: host-side approval and run-record writes vs data/vaults. Gates the kill switch.`

Leave `#<N>` literally for now. Task 10 fills it in once the PR exists.

- [ ] **Step 9: Check the docs and commit**

Run: `grep -n "data/spool" infra/hermes-agent/README.md infra/hermes-agent/deploy/BRING-UP.md`
Expected: every remaining hit is an explanation of *why not* `data/spool`, not an instruction
to use it.

Run: `grep -n "chown -R\|mode \`700\`\|result --request " infra/hermes-agent/README.md`
Expected: no instruction remains. The only allowed hit is the "never `chown -R`" warning.

```bash
git add infra/hermes-agent/README.md infra/hermes-agent/deploy/BRING-UP.md \
        docs/superpowers/specs/2026-09-21-vps-first-bring-up-findings.md
git commit -m "docs(hermes): F10 layout — README, BRING-UP Phase 2/6, findings record

README documents the store and spool tables, init-host-layout.py, safe registry
edits and the accepted residuals; deploy step 2 gives a fresh host (and the
2026-09-21 box) a path. BRING-UP Phase 6 is now blocked on F9 only. The findings
record marks F10 fixed with F10a/F10b, adds F12, and states the effect on F9.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 10: Verify, open the PR, and check CI on the PR and on the merge commit

**Files:** only `docs/superpowers/specs/2026-09-21-vps-first-bring-up-findings.md` (the PR number).

- [ ] **Step 1: All local suites**

```bash
infra/hermes-agent/bin/run-bin-tests.sh; echo "bin exit $?"
python3 infra/hermes-agent/deploy/units.test.py; echo "units exit $?"
python3 infra/hermes-agent/deploy/provision.test.py; echo "provision exit $?"
node scripts/run-all-tests.js; echo "node exit $?"
python3 infra/hermes-agent/deploy/layout-integration.test.py; echo "tier2 exit $?"
```

Expected: bin 29/29, units OK, provision OK, node 22/22, every exit 0, and Tier 2
`SKIPPED — not Linux` (exit 0). Record the actual counts. Do not pipe into `tail`: a pipeline
takes its exit status from `tail`.

- [ ] **Step 2: Redaction scan over added lines only, with a live control**

```bash
added=$(git diff origin/main...HEAD -U0 | grep '^+' | grep -v '^+++')
printf '%s\n' "$added" | grep -niE 'dentaledge|[0-9]{3}-[0-9]{3}-[0-9]{4}|\b[0-9]{10}\b' \
  | grep -vE '"(1234567890|9998887776|9999999999)"'; echo "scan exit: $?"
printf 'control: customer 5551234567 and 555-123-4567\n' \
  | grep -niE 'dentaledge|[0-9]{3}-[0-9]{3}-[0-9]{4}|\b[0-9]{10}\b'; echo "control exit: $?"
```

Expected: the scan prints nothing and exits 1. The control prints its line and exits 0; if it
does not, the pattern is dead and the scan proves nothing. Read any hit by eye before dismissing
it.

- [ ] **Step 3: Confirm nothing unintended is staged or committed**

Run: `git diff --stat origin/main...HEAD`
Expected: only the files in this plan's file map, plus the spec and this plan. Nothing under
`.project-brain/`, `evals/`, or `CLAUDE.md`.

- [ ] **Step 4: Push and open the PR — ask the user first**

Pushing and opening a PR is outward-facing, so confirm with the user before doing either. Then:

```bash
git push -u origin fix/f10-store-and-spool-layout
gh pr create --base main --title "fix(hermes): F10 — governance store and spool layout for a fresh Linux host" --body-file <body>
```

The PR body must state:
- what landed (Tasks 1–9);
- the three deliberate edits to existing pre-flight tests;
- the local `.env` consequence (`HERMES_SPOOL_DIR` is now required by compose);
- that nothing touched the VPS, and the kill switch is absent;
- what stays unproven until the VPS (spec §5.3);
- that Phase 6 is now blocked on F9 only;
- that F12 is recorded, not fixed.

End the body with `🤖 Generated with [Claude Code](https://claude.com/claude-code)`.

- [ ] **Step 5: Fill in the PR number**

Replace every `#<N>` in the findings record with the real number. Then:

```bash
git add docs/superpowers/specs/2026-09-21-vps-first-bring-up-findings.md
git commit -m "docs(hermes): F10 findings point at PR #<real number>

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
git push
```

- [ ] **Step 6: CI on the PR — read the Tier 2 count**

```bash
gh pr checks --watch
gh run view --log --job <tests job id> | grep -E "layout-integration: (executed|SKIPPED)"
```

Expected: every check is green, and the log shows
`layout-integration: executed 19, skipped 0, failures 0, errors 0`. That is the count of tests in
`layout-integration.test.py` as planned. Re-count with `grep -c "    def test_"` on the file and use that
number. If it executed 0 or skipped any, the job must have failed. If it did not fail, the
REQUIRED guard is broken: fix it before merging. Also confirm that the pre-flight's Linux-only
`test_cli_exits_two_and_names_the_remedy` actually ran (not skipped) in the "Hermes bin suites"
step.

- [ ] **Step 7: Merge — the user decides — then check CI on the merge commit**

`main` is protected. Merge only when the user says so. After the merge:

```bash
git fetch origin
gh run list --branch main --limit 3
gh run view <run id on the merge commit> --log | grep -E "layout-integration: (executed|SKIPPED)"
```

Expected: the run for the **merge commit's sha** is green, with the same executed count.

- [ ] **Step 8: Hand-off note**

Tell the user, without claiming more than was measured:
- F10 has landed.
- Phase 6 is now blocked on F9 only.
- On the box, README step 2 starts with `sudo rmdir /var/lib/hermes/governance`.
- The local `.env` needs `HERMES_SPOOL_DIR=./data/spool` before the next `docker compose up`.
- The kill switch is still absent.
