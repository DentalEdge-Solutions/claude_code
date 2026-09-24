# §6 part B — Audit Logs Are Append-Only Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every `log/<slug>.jsonl` is sealed with the Linux append-only flag when it is created, and the pre-flight refuses any registered client's log that is not sealed — so neither the executor nor the broker can erase the audit trail or reset the daily caps.

**Architecture:** One helper pair in `governance_lib.py` (`is_append_only`, `set_append_only`) talks to the kernel through stdlib `fcntl.ioctl`. `migrate_governance_shim.bootstrap_logs` and `migrate()` seal each log they create; `preflight-governance-access.py` gains one check over the registered logs. Everything that writes or reads a log's contents is untouched.

**Tech Stack:** Python 3 stdlib only (`fcntl`, `array`, `errno`, `os`, `stat`), `unittest`; Linux CI (`deploy/layout-integration.test.py`, root, real ids, ext4).

**Spec:** `docs/superpowers/specs/2026-09-24-s6b-audit-log-append-only-design.md` — read it before starting any task. The spec wins where this plan is silent; **the code wins where either disagrees with it** (and the plan gets a fix).

## Global Constraints

- **Mutation stays disabled. The kill switch is ABSENT and nothing here creates it.**
- Stdlib only. No subprocess and no `chattr`/`lsattr` in shipped code (tests may call them).
- Flag values: `LOG_APPEND_ONLY_FL = 0x00000020`, `_FS_IOC_GETFLAGS = 0x80086601`, `_FS_IOC_SETFLAGS = 0x40086602`; the ioctl buffer is a 4-byte int (`array.array("i", [0])`).
- Pre-flight messages carry **counts, never slugs** (client slugs are client-private; stderr reaches the journal).
- Nothing adds `+a` to a log that already exists (spec D3). Only logs created by `bootstrap_logs` / `migrate()` are sealed.
- A failure to read or set the flag is **never** a pass: helpers raise; the pre-flight refuses.
- **Never edit a tracked file to run a mutation test.** Firing controls mutate the per-test copy of `bin/` that `Layout.setUp` makes (`self.bin`), or run in memory.
- **Stage by explicit path only.** Never `git add -A`, `.`, or `commit -a`; never stage `.project-brain/`, `evals/`, `CLAUDE.md`, `.obsidian/`, `infra/hermes-agent/CLAUDE.md`. The working tree has ~68 unrelated operator changes.
- Do not delete untracked files you did not create (e.g. `deploy/__pycache__/`).
- Every commit ends with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- Suites: `node scripts/run-all-tests.js` (node) and `infra/hermes-agent/bin/run-bin-tests.sh` (all `bin/*.test.py`). Run the **full** suite of any file you touch, not just new classes. Tier 2 (`deploy/layout-integration.test.py`) only executes on Linux as root — locally on Darwin it prints `SKIPPED`; CI is where it runs.
- Before adding any module-level name, `grep -n "^<NAME>\b\|^def <name>\b" <file>` to be sure it does not already exist (F19's `_TARGET_RE` collision).

## Review Focus

1. **A registered log that is a symlink** (even to a sealed file) — expected: the helper refuses it (`O_NOFOLLOW` → `ELOOP`) and the pre-flight counts it as "could not be checked", never as sealed. Pinned in Task 2 (Tier 1 + Tier 2) and Task 4 (a raising helper is refused).
2. **Re-running `--bootstrap-logs --apply` after a successful run** — expected: existing logs are skipped, the seal is never re-applied, exit 0. Pinned in Task 3.
3. **The real `append_log` (with its directory fsync) on a sealed log, as uid 10000** — expected: works, one line added. Pinned in Task 1 (Tier 2).
4. **A filesystem that does not support the flag** (`ENOTTY` / `EOPNOTSUPP`) — expected: the pre-flight refuses with "could not be checked (ENOTTY)". Pinned in Task 4.
5. **Non-client files in `log/`** (`acme.jsonl.1`, an unregistered slug's `x.jsonl`) — expected: never probed, never refused. Pinned in Task 4.

---

## File Structure

| File | Change | Responsibility |
|---|---|---|
| `infra/hermes-agent/bin/governance_lib.py` | modify | `is_append_only`, `set_append_only`, the three constants |
| `infra/hermes-agent/bin/governance_lib.test.py` | modify | Tier 1 for the helper (fake ioctl) |
| `infra/hermes-agent/bin/migrate_governance_shim.py` | modify | seal in `bootstrap_logs` and `migrate()` |
| `infra/hermes-agent/bin/migrate-governance.test.py` | modify | Tier 1 for sealing; fake sealer in two `setUp`s |
| `infra/hermes-agent/bin/apply-changeset.test.py` | modify | fake sealer before its `bootstrap_logs` call (~:152) |
| `infra/hermes-agent/bin/syscall-e2e.test.py` | modify | fake sealer before its `bootstrap_logs` call (~:165) |
| `infra/hermes-agent/bin/preflight-governance-access.py` | modify | `_check_registered_logs_sealed` |
| `infra/hermes-agent/bin/preflight-governance-access.test.py` | modify | Tier 1 for the check; existing positive control declares its log sealed |
| `infra/hermes-agent/deploy/layout-integration.test.py` | modify | Tier 2: property, helper vs kernel, pre-flight, firing controls |
| `infra/hermes-agent/README.md`, `deploy/BRING-UP.md`, `docker-compose.yml` (comment), `bin/changeset_lib.py` (comment), findings record, S3-b spec | modify | records (Task 5) |

---

### Task 1: Tier 2 RED first — the property and the pre-flight refusal, on today's code

**Files:**
- Modify: `infra/hermes-agent/deploy/layout-integration.test.py` (add `PROBE` after the `CLIENT = …` line ~:38; add two classes before the `if __name__ == "__main__":` runner block ~:530)

**Interfaces:**
- Consumes: the existing `Layout` fixture (`self.store`, `self.bin`, `self.env`, `self.py()`, `self.gateway()`, `self.broker()`), `run()`, `GATEWAY`, `BROKER`.
- Produces: `class TestAuditLogsAreAppendOnly(Layout)` with helpers `register_client()`, `bootstrap()`, `log()`, `probe(who)`, `lsattr_flags(path)`; Tasks 3 and 4 add tests to this class.

These tests use only CLIs that already exist, so on today's code they fail **on the security assertion**, not on an import. That is the RED we want to see.

- [ ] **Step 1: Add the probe script** (module level, after `CLIENT = "slug-1" …`)

```python
# §6B. Run as GATEWAY or BROKER against one log file. Prints one JSON object: each
# operation's outcome ("OK" or its errno name) and the line count around them. Only ever
# pointed at a test fixture's log inside this test's own store.
PROBE = r'''
import errno, json, os, sys
p = sys.argv[1]
def lines():
    with open(p, "rb") as f:
        return f.read().count(b"\n")
def attempt(fn):
    try:
        fn()
        return "OK"
    except OSError as e:
        return errno.errorcode.get(e.errno, str(e.errno))
def append():
    with open(p, "a") as f:
        f.write("{}\n")
def overwrite():
    fd = os.open(p, os.O_WRONLY)
    try:
        os.pwrite(fd, b"X", 0)
    finally:
        os.close(fd)
out = {"before": lines(), "append": attempt(append)}
out["after_append"] = lines()
out["overwrite"] = attempt(overwrite)
out["o_trunc"] = attempt(lambda: os.close(os.open(p, os.O_WRONLY | os.O_TRUNC)))
out["truncate"] = attempt(lambda: os.truncate(p, 0))
out["after"] = lines()
print(json.dumps(out))
'''
```

- [ ] **Step 2: Add the filesystem guard class**

```python
class TestTheRunnerSupportsAppendOnly(Layout):
    """Spec §6 Tier 2 (4). Every §6B test below depends on the runner's filesystem holding
    the append-only flag. If it cannot, that must FAIL — under
    HERMES_REQUIRE_LINUX_INTEGRATION=1 a skip is already a failure, and this is not a skip:
    a runner that silently cannot seal would make every EPERM assertion below meaningless."""

    def test_chattr_a_takes_on_this_filesystem(self):
        p = os.path.join(self.base, "fs-guard")
        open(p, "w").close()
        r = run(["chattr", "+a", p])
        self.addCleanup(run, ["chattr", "-a", p])      # LIFO: runs before Layout's rmtree
        self.assertEqual(r.returncode, 0, r.stderr)
        flags = run(["lsattr", p], check=True).stdout.split()[0]
        self.assertIn("a", flags)
```

- [ ] **Step 3: Add the property class**

```python
class TestAuditLogsAreAppendOnly(Layout):
    """§6B (spec 2026-09-24-s6b-audit-log-append-only-design.md). A log bootstrapped the
    documented way (root, migrate-governance.py --bootstrap-logs --apply) must admit
    appends and refuse truncation and overwrite — for the executor (uid 10000) AND the
    broker, which is in gid 10000 and so holds group write on the file. Measured on the box
    2026-09-24: before sealing, both could truncate."""

    SLUG = "s6b-client"

    def setUp(self):
        super().setUp()
        self.register_client()
        # Registered AFTER Layout's rmtree cleanup, so it runs FIRST (LIFO): rmtree cannot
        # remove an append-only file. A no-op when the file is absent or unsealed.
        self.addCleanup(run, ["chattr", "-a", self.log()])

    def register_client(self):
        reg = os.path.join(self.store, "registry", "clients.json")
        with open(reg, "w") as f:
            json.dump({"clients": {self.SLUG: {"project": "claude_google_ads",
                                               "customer_id": "1234567890",
                                               "status": "active"}}}, f)
        run(["chown", "root:hermes", reg], check=True)
        run(["chmod", "0640", reg], check=True)

    def bootstrap(self):
        r = run(["python3", self.py("migrate-governance.py"), "--bootstrap-logs", "--apply",
                 "--governance-root", self.store], env=self.env)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertTrue(os.path.isfile(self.log()))

    def log(self):
        return os.path.join(self.store, "log", "%s.jsonl" % self.SLUG)

    def probe(self, who):
        r = run(list(who) + ["python3", "-c", PROBE, self.log()], env=self.env)
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.loads(r.stdout)

    def lsattr_flags(self, path):
        return run(["lsattr", path], check=True).stdout.split()[0]

    def _assert_append_only_for(self, who):
        self.bootstrap()
        out = self.probe(who)
        # The security property FIRST (canon lesson "check why a RED is red"): on the
        # exact errno, not "some error". Truncation is what resets the caps.
        self.assertEqual(out["o_trunc"], "EPERM", out)
        self.assertEqual(out["truncate"], "EPERM", out)
        self.assertEqual(out["overwrite"], "EPERM", out)
        self.assertEqual(out["after"], out["after_append"], out)
        # ... and the one legitimate write still works.
        self.assertEqual(out["append"], "OK", out)
        self.assertEqual(out["after_append"], out["before"] + 1, out)
        self.assertIn("a", self.lsattr_flags(self.log()))

    def test_the_executor_cannot_truncate_a_bootstrapped_log(self):
        self._assert_append_only_for(GATEWAY)

    def test_the_broker_cannot_truncate_a_bootstrapped_log(self):
        self._assert_append_only_for(BROKER)

    def test_append_log_still_works_on_a_bootstrapped_log_as_the_executor(self):
        """Review Focus 3. The real writer, not the probe: append_log also fsyncs the log/
        DIRECTORY fd. A regression guard — it passes on pre-§6B code too."""
        self.bootstrap()
        code = ("import sys; sys.path.insert(0, sys.argv[1]); import changeset_lib as C; "
                "C.append_log(sys.argv[2], {'ts': '2026-09-24T00:00:00Z', "
                "'changeset_id': '20260924-000000-abcdef01', 'status': 'applied'})")
        r = self.gateway("python3", "-c", code, self.bin, self.SLUG)
        self.assertEqual(r.returncode, 0, r.stderr)
        with open(self.log(), "rb") as f:
            self.assertEqual(f.read().count(b"\n"), 1)

    def test_the_preflight_refuses_a_log_whose_flag_was_cleared(self):
        self.bootstrap()
        pf = ("python3", self.py("preflight-governance-access.py"), "--root", self.store)
        r = self.broker(*pf)
        self.assertEqual(r.returncode, 0, r.stderr)
        run(["chattr", "-a", self.log()], check=True)
        r = self.broker(*pf)
        self.assertEqual(r.returncode, 2, r.stderr)
        self.assertIn("not append-only", r.stderr)
        self.assertNotIn(self.SLUG, r.stderr)          # counts, never slugs
```

- [ ] **Step 4: Run locally to confirm it parses and skips on Darwin**

Run: `python3 infra/hermes-agent/deploy/layout-integration.test.py`
Expected: `layout-integration: executed 0, skipped N, …` and exit 0 (not Linux).

- [ ] **Step 5: Commit**

```bash
git add infra/hermes-agent/deploy/layout-integration.test.py
git commit -m "test(hermes): §6B Tier 2 RED first — logs must refuse truncation; pre-flight must refuse an unsealed log

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

- [ ] **Step 6: Push and open a DRAFT PR** (CI runs only on PRs to `main`)

```bash
git push -u origin spec/s6b-audit-log-append-only
gh pr create --draft --base main --title "§6B: audit logs are append-only (chattr +a)" \
  --body "Draft. Spec: docs/superpowers/specs/2026-09-24-s6b-audit-log-append-only-design.md. Plan: docs/superpowers/plans/2026-09-24-s6b-audit-log-append-only.md. First push is the Tier 2 tests alone, expected RED on the truncation assertion.

🤖 Generated with [Claude Code](https://claude.com/claude-code)"
```

- [ ] **Step 7: Confirm the RED is red for the right reason**

Run: `gh run watch` then `gh run view <run-id> --log-failed | grep -E "FAIL:|AssertionError|executed"`
Expected — exactly these three failures, each on the named assertion:
- `test_the_executor_cannot_truncate_a_bootstrapped_log` — `AssertionError: 'OK' != 'EPERM'` on `o_trunc`
- `test_the_broker_cannot_truncate_a_bootstrapped_log` — `AssertionError: 'OK' != 'EPERM'` on `o_trunc`
- `test_the_preflight_refuses_a_log_whose_flag_was_cleared` — `AssertionError: 0 != 2`

and `test_chattr_a_takes_on_this_filesystem` and `test_append_log_still_works…` **pass**. Any other failure (an import error, a bootstrap `rc != 0`, a `setpriv` error) is a test defect: fix it before Task 2. Record the run id and the three assertion lines for the PR body.

---

### Task 2: The helper pair in `governance_lib`

**Files:**
- Modify: `infra/hermes-agent/bin/governance_lib.py` (imports ~:17; new block after `log_path` ~:93)
- Test: `infra/hermes-agent/bin/governance_lib.test.py` (new class at the end)
- Test: `infra/hermes-agent/deploy/layout-integration.test.py` (new class `TestAppendOnlyHelper`)

**Interfaces:**
- Produces:
  - `governance_lib.LOG_APPEND_ONLY_FL: int = 0x20`, `_FS_IOC_GETFLAGS = 0x80086601`, `_FS_IOC_SETFLAGS = 0x40086602`
  - `governance_lib.is_append_only(path: str) -> bool` — raises `OSError` on any failure, including off Linux (`ENOTSUP`), a non-regular file (`EINVAL`), a symlink (`ELOOP`), an unsupported filesystem (`ENOTTY`/`EOPNOTSUPP`)
  - `governance_lib.set_append_only(path: str) -> None` — raises `OSError` on any failure, and `OSError(EIO)` if the flag reads back unset

- [ ] **Step 1: Write the failing Tier 1 tests** (append to `governance_lib.test.py`; add `import array, errno, shutil, tempfile` and `from unittest import mock` to its imports)

```python
class FakeKernel:
    """Stands in for one inode's flags. ioctl(GET) writes them into the int buffer;
    ioctl(SET) stores the buffer's value (unless honour_set is False)."""

    def __init__(self, flags=0, honour_set=True, error=None):
        self.flags, self.honour_set, self.error, self.calls = flags, honour_set, error, []

    def ioctl(self, fd, req, buf, mutate=True):
        self.calls.append(req)
        if self.error is not None:
            raise OSError(self.error, os.strerror(self.error))
        if req == G._FS_IOC_GETFLAGS:
            buf[0] = self.flags
        elif req == G._FS_IOC_SETFLAGS and self.honour_set:
            self.flags = buf[0]
        return 0


class TestAppendOnlyFlag(unittest.TestCase):
    """§6B helper logic, with the kernel faked. The real kernel is Tier 2's job
    (deploy/layout-integration.test.py TestAppendOnlyHelper)."""

    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="s6b-")
        self.addCleanup(shutil.rmtree, self.dir, True)
        self.file = os.path.join(self.dir, "acme.jsonl")
        open(self.file, "w").close()

    def _with(self, kernel, platform="linux"):
        for p in (mock.patch.object(G.sys, "platform", platform),
                  mock.patch.object(G.fcntl, "ioctl", kernel.ioctl)):
            p.start()
            self.addCleanup(p.stop)

    def test_a_sealed_file_reads_true(self):
        self._with(FakeKernel(flags=0x80000 | G.LOG_APPEND_ONLY_FL))
        self.assertTrue(G.is_append_only(self.file))

    def test_an_unsealed_file_reads_false(self):
        self._with(FakeKernel(flags=0x80000))
        self.assertFalse(G.is_append_only(self.file))

    def test_set_adds_the_flag_and_keeps_the_others(self):
        k = FakeKernel(flags=0x80000)
        self._with(k)
        G.set_append_only(self.file)
        self.assertEqual(k.flags, 0x80000 | G.LOG_APPEND_ONLY_FL)
        self.assertEqual(k.calls, [G._FS_IOC_GETFLAGS, G._FS_IOC_SETFLAGS,
                                   G._FS_IOC_GETFLAGS])

    def test_set_raises_when_the_flag_does_not_take(self):
        self._with(FakeKernel(flags=0, honour_set=False))
        with self.assertRaises(OSError) as cm:
            G.set_append_only(self.file)
        self.assertEqual(cm.exception.errno, errno.EIO)

    def test_an_ioctl_error_raises_and_is_never_read_as_false(self):
        self._with(FakeKernel(error=errno.ENOTTY))
        with self.assertRaises(OSError) as cm:
            G.is_append_only(self.file)
        self.assertEqual(cm.exception.errno, errno.ENOTTY)

    def test_off_linux_both_raise_without_touching_the_kernel(self):
        k = FakeKernel()
        self._with(k, platform="darwin")
        for fn in (G.is_append_only, G.set_append_only):
            with self.assertRaises(OSError) as cm:
                fn(self.file)
            self.assertEqual(cm.exception.errno, errno.ENOTSUP)
        self.assertEqual(k.calls, [])

    def test_a_symlink_is_refused_before_the_kernel_is_asked(self):
        """Review Focus 1: never report a symlink's TARGET as the log's state."""
        k = FakeKernel(flags=G.LOG_APPEND_ONLY_FL)
        self._with(k)
        link = os.path.join(self.dir, "link.jsonl")
        os.symlink(self.file, link)
        with self.assertRaises(OSError) as cm:
            G.is_append_only(link)
        self.assertEqual(cm.exception.errno, errno.ELOOP)
        self.assertEqual(k.calls, [])

    def test_a_directory_and_a_fifo_are_refused(self):
        k = FakeKernel()
        self._with(k)
        fifo = os.path.join(self.dir, "fifo.jsonl")
        os.mkfifo(fifo)
        for p in (self.dir, fifo):
            with self.assertRaises(OSError) as cm:
                G.is_append_only(p)
            self.assertEqual(cm.exception.errno, errno.EINVAL)
        self.assertEqual(k.calls, [])
```

- [ ] **Step 2: Run to verify they fail**

Run: `python3 infra/hermes-agent/bin/governance_lib.test.py -v 2>&1 | tail -5`
Expected: errors with `AttributeError: module 'governance_lib' has no attribute '_FS_IOC_GETFLAGS'` (or `sys`/`fcntl`).

- [ ] **Step 3: Implement** — `grep -n "^import\|LOG_APPEND_ONLY_FL\|_FS_IOC\|def is_append_only\|def set_append_only" infra/hermes-agent/bin/governance_lib.py` first (expect only the `import os, re` line). Change the import line to `import array, errno, fcntl, os, re, stat, sys`, then add after `log_path`:

```python
# §6B: every log/<slug>.jsonl carries the Linux append-only inode flag (chattr +a), so the
# file admits appends only — for the executor, the broker and root alike. Measured on the
# box 2026-09-24 (spec 2026-09-24-s6b-audit-log-append-only-design.md §2.3).
#
# linux/fs.h: FS_APPEND_FL, and FS_IOC_GETFLAGS / FS_IOC_SETFLAGS = _IOR/_IOW('f', 1|2, long)
# on a 64-bit kernel. The kernel moves an INT through these despite the `long` in the macro,
# so the buffer is 4 bytes. Not assumed: deploy/layout-integration.test.py cross-checks
# these numbers against lsattr on a real ext4 file.
LOG_APPEND_ONLY_FL = 0x00000020
_FS_IOC_GETFLAGS = 0x80086601
_FS_IOC_SETFLAGS = 0x40086602


def _open_regular(path):
    """An fd on path itself — never a symlink's target, never a FIFO we would block on."""
    if not sys.platform.startswith("linux"):
        raise OSError(errno.ENOTSUP,
                      "the append-only flag is Linux-only (platform %s)" % sys.platform, path)
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise OSError(errno.EINVAL, "not a regular file", path)
    except BaseException:
        os.close(fd)
        raise
    return fd


def _get_flags(fd):
    buf = array.array("i", [0])
    fcntl.ioctl(fd, _FS_IOC_GETFLAGS, buf, True)
    return buf[0]


def is_append_only(path):
    """True if path carries the append-only flag. RAISES on every failure — an unsupported
    filesystem, a symlink, a non-regular file, off Linux — and never returns False for one:
    'cannot tell' must not read as 'not sealed', and must never read as 'sealed'.
    Needs no root."""
    fd = _open_regular(path)
    try:
        return bool(_get_flags(fd) & LOG_APPEND_ONLY_FL)
    finally:
        os.close(fd)


def set_append_only(path):
    """Add the append-only flag, keeping every other flag, then read it back. Root only
    (CAP_LINUX_IMMUTABLE). Raises on any failure, and EIO if the flag did not take."""
    fd = _open_regular(path)
    try:
        buf = array.array("i", [_get_flags(fd) | LOG_APPEND_ONLY_FL])
        fcntl.ioctl(fd, _FS_IOC_SETFLAGS, buf, True)
    finally:
        os.close(fd)
    if not is_append_only(path):
        raise OSError(errno.EIO, "the append-only flag did not take", path)
```

Note the ordering in `_open_regular`: the non-Linux check comes before `os.open`, so the off-Linux test sees no ioctl call; `O_NOFOLLOW` makes `os.open` itself raise `ELOOP` on a symlink.

- [ ] **Step 4: Run the full file**

Run: `python3 infra/hermes-agent/bin/governance_lib.test.py -v 2>&1 | tail -3`
Expected: `OK`, all tests (old and new) passing.

- [ ] **Step 5: Add the Tier 2 helper-vs-kernel class** to `layout-integration.test.py` (before the runner block)

```python
class TestAppendOnlyHelper(Layout):
    """§6B Tier 2 (1): governance_lib's ioctl numbers and 4-byte buffer against the real
    kernel, cross-checked with lsattr — the same tool the box measurement used."""

    def g(self, code, path):
        """Run `code` with G = the copied governance_lib, as root. Returns the result."""
        return run(["python3", "-c",
                    "import sys; sys.path.insert(0, sys.argv[1]); import governance_lib as G; "
                    + code, self.bin, path], env=self.env)

    def fresh(self, name):
        p = os.path.join(self.base, name)
        open(p, "w").close()
        self.addCleanup(run, ["chattr", "-a", p])      # before Layout's rmtree (LIFO)
        return p

    def lsattr_flags(self, path):
        return run(["lsattr", path], check=True).stdout.split()[0]

    def test_set_then_read_agrees_with_lsattr(self):
        p = self.fresh("sealed")
        r = self.g("G.set_append_only(sys.argv[2]); print(G.is_append_only(sys.argv[2]))", p)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.strip(), "True")
        self.assertIn("a", self.lsattr_flags(p))

    def test_a_plain_file_reads_false(self):
        p = self.fresh("plain")
        r = self.g("print(G.is_append_only(sys.argv[2]))", p)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.strip(), "False")
        self.assertNotIn("a", self.lsattr_flags(p))

    def test_a_symlink_is_refused(self):
        target = self.fresh("target")
        run(["chattr", "+a", target], check=True)
        link = os.path.join(self.base, "link")
        os.symlink(target, link)
        r = self.g("G.is_append_only(sys.argv[2])", link)
        self.assertNotEqual(r.returncode, 0)
        # O_NOFOLLOW -> ELOOP; the traceback prints its strerror.
        self.assertIn("Too many levels of symbolic links", r.stderr)

    def test_control_a_wrong_flag_constant_is_caught_only_by_lsattr(self):
        """FIRING CONTROL for the lsattr cross-check. With the constant set to NODUMP (0x40,
        harmless) the helper sets and "verifies" the wrong bit and reports success — only
        lsattr shows the file is not append-only. This is why test_set_then_read_agrees_
        with_lsattr asserts lsattr and not just the helper's own answer."""
        p = self.fresh("wrong-constant")
        r = self.g("G.LOG_APPEND_ONLY_FL = 0x40; G.set_append_only(sys.argv[2]); "
                   "print(G.is_append_only(sys.argv[2]))", p)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.strip(), "True")      # the helper is fooled
        self.assertNotIn("a", self.lsattr_flags(p))     # lsattr is not
```

- [ ] **Step 6: Local syntax check of the Tier 2 file**

Run: `python3 infra/hermes-agent/deploy/layout-integration.test.py`
Expected: `executed 0, skipped N`, exit 0.

- [ ] **Step 7: Commit, push, read CI**

```bash
git add infra/hermes-agent/bin/governance_lib.py infra/hermes-agent/bin/governance_lib.test.py infra/hermes-agent/deploy/layout-integration.test.py
git commit -m "feat(hermes): §6B governance_lib.is_append_only / set_append_only (stdlib ioctl), proven against lsattr

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
git push
```

Expected on CI: the four `TestAppendOnlyHelper` tests **pass** (this is the proof of the ioctl numbers); Task 1's three RED tests are **still red on the same assertions** (nothing seals yet). If `test_set_then_read_agrees_with_lsattr` fails, the constants or buffer are wrong — stop and fix here.

---

### Task 3: Seal in `bootstrap_logs` and `migrate()`

**Files:**
- Modify: `infra/hermes-agent/bin/migrate_governance_shim.py` (`bootstrap_logs` try-block ~:209-242; `migrate()` after `os.replace(tmp_log, dst_log)` ~:319)
- Test: `infra/hermes-agent/bin/migrate-governance.test.py` (`TestMigration.setUp` ~:19, `TestBootstrapLogs.setUp` ~:223, new tests)
- Modify: `infra/hermes-agent/bin/apply-changeset.test.py` (before `M.bootstrap_logs(...)` ~:152)
- Modify: `infra/hermes-agent/bin/syscall-e2e.test.py` (before `M.bootstrap_logs(...)` ~:165)
- Test: `infra/hermes-agent/deploy/layout-integration.test.py` (one control in `TestAuditLogsAreAppendOnly`)

**Interfaces:**
- Consumes: `governance_lib.set_append_only(path) -> None` (Task 2). Called as the module attribute `governance_lib.set_append_only(...)` — resolved at call time, so tests replace it with `mock.patch.object(governance_lib, "set_append_only", …)`.
- Produces: unchanged signatures and result dicts for `bootstrap_logs` and `migrate()`.

- [ ] **Step 1: Give the existing suites a fake sealer.** Non-root processes cannot set the flag, and off Linux the helper raises, so every existing caller of `bootstrap_logs` / `migrate()` in `bin/` tests needs the stand-in — the same module-attribute idiom those files already use for `EXECUTOR_GID`.

In `migrate-governance.test.py`, at the end of `TestMigration.setUp` **and** at the end of `TestBootstrapLogs.setUp`:

```python
        # §6B: sealing needs root on Linux; this suite runs unprivileged everywhere. Record
        # what WOULD be sealed. Tier 2 (deploy/layout-integration.test.py) seals for real.
        import governance_lib
        self.sealed = []
        _p = mock.patch.object(governance_lib, "set_append_only", self.sealed.append)
        _p.start()
        self.addCleanup(_p.stop)
```

In `apply-changeset.test.py` and `syscall-e2e.test.py`, immediately before the `M.bootstrap_logs(self.tmp, dry_run=False, expected_gid=os.getgid())` line (keep that line's indentation):

```python
        import governance_lib   # §6B: sealing needs root; Tier 2 seals for real
        _p = mock.patch.object(governance_lib, "set_append_only", lambda path: None)
        _p.start()
        self.addCleanup(_p.stop)
```

(Check each file imports `mock` — `grep -n "^from unittest import mock\|^import.*mock" <file>` — and add `from unittest import mock` if missing.)

Run: `infra/hermes-agent/bin/run-bin-tests.sh`
Expected: all suites pass (the fake is not used yet).

- [ ] **Step 2: Write the failing Tier 1 tests** (in `TestBootstrapLogs`)

```python
    def test_apply_seals_each_log_it_creates(self):
        M.bootstrap_logs(self.gov, dry_run=False, expected_gid=os.getgid())
        self.assertEqual(self.sealed, [self._log("acme-dental"), self._log("other-clinic")])

    def test_dry_run_seals_nothing(self):
        M.bootstrap_logs(self.gov, dry_run=True, expected_gid=os.getgid())
        self.assertEqual(self.sealed, [])

    def test_an_existing_log_is_never_sealed(self):
        """Spec D3 / Review Focus 2: a log that already exists may have been emptied while
        unsealed; a person inspects it and seals it by hand. Re-running is still exit-0."""
        with open(self._log("acme-dental"), "w") as f:
            f.write('{"status": "applied"}\n')
        M.bootstrap_logs(self.gov, dry_run=False, expected_gid=os.getgid())
        self.assertEqual(self.sealed, [self._log("other-clinic")])
        M.bootstrap_logs(self.gov, dry_run=False, expected_gid=os.getgid())
        self.assertEqual(self.sealed, [self._log("other-clinic")])   # second run: nothing

    def test_a_sealing_failure_removes_the_created_log_and_refuses(self):
        import governance_lib
        def refuse(path):
            raise OSError(errno.EPERM, "Operation not permitted", path)
        with mock.patch.object(governance_lib, "set_append_only", refuse):
            with self.assertRaises(OSError):
                M.bootstrap_logs(self.gov, dry_run=False, expected_gid=os.getgid())
        # Sorted order: acme-dental is attempted first, fails, and is removed — never left
        # behind unsealed. other-clinic is never attempted.
        self.assertFalse(os.path.exists(self._log("acme-dental")))
        self.assertFalse(os.path.exists(self._log("other-clinic")))

    def test_cli_returns_2_when_sealing_fails(self):
        import governance_lib
        CLI = _load_cli()
        real = governance_lib.EXECUTOR_GID
        governance_lib.EXECUTOR_GID = os.getgid()
        self.addCleanup(setattr, governance_lib, "EXECUTOR_GID", real)
        def refuse(path):
            raise OSError(errno.EPERM, "Operation not permitted", path)
        with mock.patch.object(governance_lib, "set_append_only", refuse):
            self.assertEqual(
                CLI.main(["--bootstrap-logs", "--governance-root", self.gov, "--apply"]), 2)
```

and in `TestMigration`:

```python
    def test_a_migrated_log_is_sealed_after_the_rename(self):
        M.migrate(self.vault, self.gov)
        self.assertEqual(self.sealed, [os.path.join(self.gov, "log", "acme-dental.jsonl")])

    def test_a_sealing_failure_removes_the_copy_and_keeps_the_vault_original(self):
        import governance_lib
        def refuse(path):
            raise OSError(errno.EPERM, "Operation not permitted", path)
        src = os.path.join(self.vault, "acme-dental", "changes", "log.jsonl")
        dst = os.path.join(self.gov, "log", "acme-dental.jsonl")
        with mock.patch.object(governance_lib, "set_append_only", refuse):
            with self.assertRaises(OSError):
                M.migrate(self.vault, self.gov)
        self.assertFalse(os.path.exists(dst))
        with open(src) as f:
            self.assertEqual(len(f.read().splitlines()), 3)
        M.migrate(self.vault, self.gov)                 # a retry reproduces the result
        self.assertTrue(os.path.isfile(dst))
        self.assertEqual(self.sealed, [dst])
```

(Add `import errno` to the file's import line if absent.)

- [ ] **Step 3: Run to verify they fail**

Run: `python3 infra/hermes-agent/bin/migrate-governance.test.py -v 2>&1 | grep -E "FAIL|ERROR|^OK|Ran"`
Expected: the seal-recording tests FAIL (`[] != [...]`); the failure tests FAIL (`OSError not raised`).

- [ ] **Step 4: Implement.** In `bootstrap_logs`, inside the existing `try:` that follows `os.close(fd)`, as its **last** statement — after the `if st.st_gid != expected_gid:` block, at the `try` body's indentation, before `except Exception:`:

```python
            # §6B: seal LAST and INSIDE this try, so a failure takes the cleanup below —
            # the flag did not take, so this empty file is still removable, and a retry
            # starts clean. A log is either sealed or absent; never left flagless.
            governance_lib.set_append_only(dst)
```

In `migrate()`, replace:

```python
        os.replace(tmp_log, dst_log)
        result["moved"].append(slug)
```

with:

```python
        os.replace(tmp_log, dst_log)
        # §6B: seal AFTER the rename — Linux refuses to rename an append-only file (EPERM,
        # even for root; measured on the box 2026-09-24). On failure remove the copy: the
        # vault original is untouched, so a retry reproduces this exact result.
        try:
            governance_lib.set_append_only(dst_log)
        except Exception:
            try:
                os.remove(dst_log)
            except OSError:
                pass
            raise
        result["moved"].append(slug)
```

- [ ] **Step 5: Run the full bin suite**

Run: `infra/hermes-agent/bin/run-bin-tests.sh`
Expected: every suite passes, including `migrate-governance.test.py`, `apply-changeset.test.py`, `syscall-e2e.test.py`.

- [ ] **Step 6: Add the Tier 2 firing control** to `TestAuditLogsAreAppendOnly`

```python
    def test_control_without_the_seal_call_the_executor_truncates(self):
        """FIRING CONTROL for the property tests: the same bootstrap with the seal call
        removed from THIS TEST'S COPY of bin/ (never the tracked file) leaves truncation
        open — so those tests fail when the seal is missing, not by accident."""
        shim = os.path.join(self.bin, "migrate_governance_shim.py")
        with open(shim) as f:
            src = f.read()
        needle = "governance_lib.set_append_only(dst)\n"
        self.assertEqual(src.count(needle), 1)
        with open(shim, "w") as f:
            f.write(src.replace(needle, "pass\n"))
        self.bootstrap()
        out = self.probe(GATEWAY)
        self.assertEqual(out["o_trunc"], "OK", out)
        self.assertNotIn("a", self.lsattr_flags(self.log()))
```

- [ ] **Step 7: Commit, push, read CI**

```bash
git add infra/hermes-agent/bin/migrate_governance_shim.py infra/hermes-agent/bin/migrate-governance.test.py infra/hermes-agent/bin/apply-changeset.test.py infra/hermes-agent/bin/syscall-e2e.test.py infra/hermes-agent/deploy/layout-integration.test.py
git commit -m "feat(hermes): §6B bootstrap_logs and migrate() seal every log they create

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
git push
```

Expected on CI: Task 1's two truncation tests now **pass**; the new control **passes**; only `test_the_preflight_refuses_a_log_whose_flag_was_cleared` is still red, on `0 != 2`.

---

### Task 4: The pre-flight refuses an unsealed registered log

**Files:**
- Modify: `infra/hermes-agent/bin/preflight-governance-access.py` (import `errno`; new function after `_check_registered_logs` ~:397; one line in `check()` after `problems.extend(_check_registered_logs(root))` ~:481)
- Test: `infra/hermes-agent/bin/preflight-governance-access.test.py` (the existing `test_control_the_same_registry_with_the_log_present_is_healthy` ~:637; new class at the end)
- Test: `infra/hermes-agent/deploy/layout-integration.test.py` (one control in `TestAuditLogsAreAppendOnly`)

**Interfaces:**
- Consumes: `governance_lib.is_append_only(path) -> bool` (Task 2), called as the module attribute so tests patch `PF.governance_lib.is_append_only`; the existing `_check_file(path, uid, gid, need_write) -> str | None`.
- Produces: `_check_registered_logs_sealed(root, uid, gid) -> list[str]`, at most two messages.

**The double-count rule (spec §4.3), decided here:** a log whose open fails is counted as "could not be checked" **unless** `_check_file(path, uid, gid, need_write=True)` already reports that same file. In that case the file-level check has already refused the store (no fail-open), and a second message would count one fault twice (Ruling 9 / R19b). A log that is merely *not sealed* is always reported: that is a different fault with a different remedy.

- [ ] **Step 1: Make the existing positive control declare its log sealed.** In `test_control_the_same_registry_with_the_log_present_is_healthy`, wrap the final assertion:

```python
        # §6B: a healthy registered log is now also a SEALED one. The helper is faked
        # here (this suite runs unprivileged, and off Linux it cannot read flags);
        # Tier 2 reads real flags.
        with mock.patch.object(PF.governance_lib, "is_append_only", lambda path: True):
            self.assertEqual(
                PF.check(self.root, self.other_uid, self.gid, platform="linux"), [])
```

- [ ] **Step 2: Write the failing tests** (new class at the end of the file)

```python
class TestRegisteredLogsAreSealed(Base):
    """§6B. A registered client's log that is not append-only can be truncated by the
    executor or the broker, which erases the audit trail and resets the daily caps."""

    SLUG = "acme-dental"

    def _healthy_dirs(self):
        os.chmod(self.root, 0o750)
        for name in PF.READ_ONLY_DIRS:
            os.chmod(os.path.join(self.root, name), 0o750)
        for name in PF.READ_WRITE_DIRS:
            os.chmod(os.path.join(self.root, name), 0o2750)

    def _register(self, *slugs):
        reg = os.path.join(self.root, *PF.CLIENTS_REGISTRY_REL)
        with open(reg, "w") as f:
            json.dump({"clients": {s: {"status": "active"} for s in slugs}}, f)
        os.chmod(reg, 0o640)

    def _log(self, slug, mode=0o660):
        p = os.path.join(self.root, "log", "%s.jsonl" % slug)
        open(p, "w").close()
        os.chmod(p, mode)
        return p

    def _probe(self, answer):
        """Fake is_append_only: `answer` is a bool, or an errno to raise. Records paths."""
        self.asked = []
        def fake(path):
            self.asked.append(path)
            if isinstance(answer, bool):
                return answer
            raise OSError(answer, os.strerror(answer), path)
        p = mock.patch.object(PF.governance_lib, "is_append_only", fake)
        p.start()
        self.addCleanup(p.stop)

    def _check(self):
        return PF.check(self.root, self.other_uid, self.gid, platform="linux")

    def test_a_sealed_registered_log_is_healthy(self):
        self._healthy_dirs(); self._register(self.SLUG); self._log(self.SLUG)
        self._probe(True)
        self.assertEqual(self._check(), [])

    def test_an_unsealed_registered_log_is_refused_by_count(self):
        self._healthy_dirs(); self._register(self.SLUG); self._log(self.SLUG)
        self._probe(False)
        problems = self._check()
        self.assertEqual(len(problems), 1, problems)
        self.assertIn("1 registered client log(s) are not append-only", problems[0])
        self.assertIn("sudo lsattr", problems[0])
        self.assertIn("sudo chattr +a", problems[0])
        self.assertNotIn(self.SLUG, problems[0])

    def test_the_count_tracks_the_number_of_unsealed_logs(self):
        self._healthy_dirs(); self._register(self.SLUG, "other-clinic")
        self._log(self.SLUG); self._log("other-clinic")
        self._probe(False)
        problems = self._check()
        self.assertEqual(len(problems), 1, problems)
        self.assertIn("2 registered client log(s) are not append-only", problems[0])
        self.assertNotIn("other-clinic", problems[0])

    def test_an_unsupported_filesystem_is_refused_not_passed(self):
        """Review Focus 4. 'Cannot tell' is never 'sealed'."""
        self._healthy_dirs(); self._register(self.SLUG); self._log(self.SLUG)
        self._probe(errno.ENOTTY)
        problems = self._check()
        self.assertEqual(len(problems), 1, problems)
        self.assertIn("1 registered client log(s) could not be checked", problems[0])
        self.assertIn("ENOTTY", problems[0])
        self.assertNotIn(self.SLUG, problems[0])

    def test_an_unopenable_log_already_reported_is_not_counted_twice(self):
        """The §4.3 double-count rule. A 0600 log is refused by the file-level check (the
        executor cannot append to it); the checker's own open failing on the same file is
        the same fault, so exactly ONE problem."""
        self._healthy_dirs(); self._register(self.SLUG); self._log(self.SLUG, mode=0o600)
        self._probe(errno.EACCES)
        problems = self._check()
        self.assertEqual(len(problems), 1, problems)
        self.assertIn("%s.jsonl" % self.SLUG, problems[0])   # the file-level message
        self.assertNotIn("could not be checked", problems[0])

    def test_a_missing_registered_log_is_only_the_bootstrap_message(self):
        self._healthy_dirs(); self._register(self.SLUG)
        self._probe(False)
        problems = self._check()
        self.assertEqual(len(problems), 1, problems)
        self.assertIn("--bootstrap-logs", problems[0])
        self.assertEqual(self.asked, [])

    def test_files_that_are_not_registered_logs_are_never_probed(self):
        """Review Focus 5. Derived from clients.json, never from a listing of log/."""
        self._healthy_dirs(); self._register(self.SLUG); p = self._log(self.SLUG)
        self._log("unregistered")
        with open(os.path.join(self.root, "log", "%s.jsonl.1" % self.SLUG), "w"):
            pass
        self._probe(True)
        self.assertEqual(self._check(), [])
        self.assertEqual(self.asked, [p])

    def test_an_unparseable_registry_is_reported_once(self):
        self._healthy_dirs()
        reg = os.path.join(self.root, *PF.CLIENTS_REGISTRY_REL)
        with open(reg, "w") as f:
            f.write("{not json")
        os.chmod(reg, 0o640)
        self._probe(False)
        problems = self._check()
        self.assertEqual(len(problems), 1, problems)
        self.assertIn("malformed client registry", problems[0])

    def test_off_linux_the_check_does_not_run(self):
        self._healthy_dirs(); self._register(self.SLUG); self._log(self.SLUG)
        self._probe(False)
        self.assertEqual(PF.check(self.root, self.other_uid, self.gid, platform="darwin"), [])
        self.assertEqual(self.asked, [])
```

(Add `errno, json` to the file's import line if absent. `test_an_unopenable_log_already_reported…` relies on `other_uid` + matching `gid` making a 0600 file unwritable to the simulated executor — the same setup `test_existing_log_file_with_bad_mode_is_reported` uses.)

- [ ] **Step 3: Run to verify they fail**

Run: `python3 infra/hermes-agent/bin/preflight-governance-access.test.py -v 2>&1 | grep -E "FAIL|ERROR|Ran|^OK"`
Expected: the refusal tests FAIL (`0 != 1`, `[] != …`); the healthy/never-probed tests may pass vacuously (nothing probes yet) — `test_files_that_are_not_registered_logs_are_never_probed` FAILS on `[] != [p]`.

- [ ] **Step 4: Implement** — `grep -n "_check_registered_logs_sealed\|^import" infra/hermes-agent/bin/preflight-governance-access.py` first. Add `errno` to the imports. After `_check_registered_logs`:

```python
def _check_registered_logs_sealed(root, uid, gid):
    """§6B. Every REGISTERED client's existing log must carry the append-only flag.

    Without it, the executor (uid 10000) and the broker (gid 10000) can truncate the file —
    measured on the box 2026-09-24 — which erases the reversibility record --undo reads AND
    resets the daily caps day_counts reads from the same file. The flag is set when the log
    is created (migrate_governance_shim.bootstrap_logs / migrate); nothing sets it on a log
    that already exists, because a log that was ever unsealed may have been emptied and a
    person must look first (spec D3).

    Same slug list, same registry handling as _check_registered_logs: missing or
    unreadable -> [] (Ruling 9); unparseable -> [] here, because _check_registered_logs
    already reports it. A MISSING log is _check_registered_logs's; it is not probed here.

    'Cannot tell' is never 'sealed': a probe that raises is counted and refused — unless the
    file-level check already reports this same file, in which case the store is refused
    already and a second line would count one fault twice (Ruling 9 / R19b). A log that
    is merely unsealed is always reported: a different fault with a different remedy.

    Counts, never slugs (see _check_registered_logs)."""
    reg = governance_lib.clients_registry_path(root)
    try:
        with open(reg, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return []
    clients = data.get("clients", {}) if isinstance(data, dict) else None
    if not isinstance(clients, dict):
        return []
    unsealed, unchecked, errnos = 0, 0, set()
    for slug in clients:
        if not isinstance(slug, str) or not governance_lib.SLUG_RE.fullmatch(slug):
            continue
        p = governance_lib.log_path(slug, root)
        if not os.path.isfile(p):
            continue
        try:
            sealed = governance_lib.is_append_only(p)
        except OSError as e:
            if _check_file(p, uid, gid, need_write=True):
                continue
            unchecked += 1
            errnos.add(errno.errorcode.get(e.errno, str(e.errno)))
            continue
        if not sealed:
            unsealed += 1
    problems = []
    if unsealed:
        problems.append(
            "%s/log: %d registered client log(s) are not append-only, so their records and "
            "the daily caps can be erased by truncation. Inspect with: sudo lsattr %s/log/*.jsonl"
            " — then, for each log you have checked, run: sudo chattr +a %s/log/<slug>.jsonl"
            % (root, unsealed, root, root))
    if unchecked:
        problems.append(
            "%s/log: %d registered client log(s) could not be checked for the append-only "
            "flag (%s) — refusing, because an unverifiable log is not a sealed one"
            % (root, unchecked, ", ".join(sorted(errnos))))
    return problems
```

In `check()`, directly after `problems.extend(_check_registered_logs(root))`:

```python
    problems.extend(_check_registered_logs_sealed(root, uid, gid))
```

- [ ] **Step 5: Run the full bin suite**

Run: `infra/hermes-agent/bin/run-bin-tests.sh`
Expected: all suites pass. If an existing exact-count test changed, stop: that is a double count or a registered log the fixture did not declare sealed — understand which before changing any assertion.

- [ ] **Step 6: Add the Tier 2 firing control** to `TestAuditLogsAreAppendOnly`

```python
    def test_control_a_probe_that_always_says_sealed_passes_an_unsealed_log(self):
        """FIRING CONTROL for test_the_preflight_refuses_a_log_whose_flag_was_cleared: with
        is_append_only replaced in THIS TEST'S COPY of bin/ by one that always answers True,
        the pre-flight passes a cleared log — so the real test depends on the real flag."""
        self.bootstrap()
        with open(os.path.join(self.bin, "governance_lib.py"), "a") as f:
            f.write("\n\ndef is_append_only(path):\n    return True\n")
        run(["chattr", "-a", self.log()], check=True)
        r = self.broker("python3", self.py("preflight-governance-access.py"),
                        "--root", self.store)
        self.assertEqual(r.returncode, 0, r.stderr)
```

- [ ] **Step 7: Commit, push, read CI**

```bash
git add infra/hermes-agent/bin/preflight-governance-access.py infra/hermes-agent/bin/preflight-governance-access.test.py infra/hermes-agent/deploy/layout-integration.test.py
git commit -m "feat(hermes): §6B the pre-flight refuses a registered log that is not append-only

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
git push
```

Expected on CI: every job green. Read `layout-integration: executed N, skipped 0` with N = 30 + 11 = **41** (1 guard, 6 in `TestAuditLogsAreAppendOnly`, 4 in `TestAppendOnlyHelper`; 30 was the count on `main` at `a26f2a3`) and `bind-agreement: executed 7, skipped 0`.

- [ ] **Step 8: Check for order-dependence.** No sockets or threads here, so no socket loop — but the module-attribute patches could leak between suites. Run the full bin suite 3×: `for i in 1 2 3; do infra/hermes-agent/bin/run-bin-tests.sh || break; done`. Expected: 3 clean runs.

---

### Task 5: Records — README, BRING-UP rollout, comments, F20, S3-b pointer

**Files:**
- Modify: `infra/hermes-agent/README.md` (the "Accepted residual" paragraph ~:1048; after the bootstrap commands ~:1044; checklist step 3 ~:1187)
- Modify: `infra/hermes-agent/deploy/BRING-UP.md` (new section after the F19 `RESULT` paragraph, before its `---` ~:541)
- Modify: `infra/hermes-agent/docker-compose.yml` (comment only, ~:111-116)
- Modify: `infra/hermes-agent/bin/changeset_lib.py` (comment only, ~:763-767)
- Modify: `docs/superpowers/specs/2026-09-21-vps-first-bring-up-findings.md` (F20 after F19, before "## Final state"; open item 9)
- Modify: `docs/superpowers/specs/2026-09-04-s3b-audit-log-integrity-design.md` (one pointer line after the Truncation bullet, ~:71)

**Interfaces:** none (docs and comments). After the edits, `grep -rn "NOT append-only\|can truncate an audit log" infra/hermes-agent` must print nothing.

- [ ] **Step 1: README — replace the "Accepted residual" paragraph** (the one beginning `**Accepted residual.** \`hermes-broker\` is in gid 10000`) with:

```markdown
**Audit logs are append-only (§6B).** `--bootstrap-logs` seals every log it creates with the
Linux append-only flag (`chattr +a`): appends still work, but nobody — the executor, the broker,
or root — can truncate, overwrite, rename or delete it, so neither the audit trail nor the daily
caps can be reset. The pre-flight refuses a registered client's log that is not sealed, at broker
start and before every mutation run. Nothing seals a log that already exists: inspect it
(`sudo lsattr`, and read it yourself), then `sudo chattr +a` it. Deleting or restoring a log
needs `sudo chattr -a` first, and a restored copy does not carry the flag — re-seal it after
inspection.

**Accepted residual (F20).** Whoever can append can still append a fabricated record — the
executor, and `hermes-broker` through gid 10000, which it needs to read `clients.json`. A forged
`"undone"` record would hide a real change from `--undo`. The fix is a host-side writer or signed
records; see F20 in the findings record.
```

- [ ] **Step 2: README — after the two bootstrap commands** (the fenced block ending `--bootstrap-logs --apply`), add:

````markdown
Every created log is sealed. Check it:

```bash
sudo lsattr /var/lib/hermes/governance/log/*.jsonl    # every line's flags include an "a"
```
````

and in checklist step 3, directly after `sudo python3 bin/migrate-governance.py --governance-root /var/lib/hermes/governance --bootstrap-logs --apply` inside that fenced block, add the line:

```bash
   sudo lsattr /var/lib/hermes/governance/log/*.jsonl    # §6B: each shows an "a"
```

- [ ] **Step 3: `docker-compose.yml` comment.** Replace the four lines from `# unlink (same reason). It is NOT append-only, though: 0660 on the file itself` through the line `# "Explicitly not this wave"). Do not "fix" this to :ro — append_log would fail` (that last line carries both sentences) with:

```yaml
      # unlink (same reason). §6B closed the rest: every log/<slug>.jsonl carries the
      # append-only flag (chattr +a), so this container can append but never truncate
      # or overwrite it — measured through this bind mount on the box, 2026-09-24.
      # Do not "fix" this to :ro — append_log would fail
```

(The next line, `# mid-apply, which is exit 3 after a live account change.`, stays. Run `python3 infra/hermes-agent/bin/proxy-policy-sync.test.py` after — it parses this file.)

- [ ] **Step 4: `changeset_lib.py` comment.** Replace the last two sentences of the S3-a block — from `# nor unlink on the directory. Per R22 that is measured on Linux and UNMEASURED on the` through `# VPS — Phase B owns the bind-mount semantics there.` — with:

```python
# nor unlink on the directory. §6B then sealed each log append-only (chattr +a), which
# closes truncation and overwrite too — for the executor, the broker and root; measured
# through the bind mount on the box 2026-09-24. Appending a FABRICATED record is still
# possible for whoever can append (F20).
```

- [ ] **Step 5: S3-b spec pointer.** After the Truncation bullet's last line (`are a real design change, not a mode tweak, and are left for a separate wave.`), add:

```markdown
  **Closed by §6B (2026-09-24):** `docs/superpowers/specs/2026-09-24-s6b-audit-log-append-only-design.md`.
```

- [ ] **Step 6: Findings record — F20.** Insert before `## Final state of the box (end of session)`:

```markdown
### F20: whoever can append to an audit log can append a forged record — deferred, named

**Found 2026-09-24 (§6B assessment).** §6B seals every `log/<slug>.jsonl` append-only, which
stops truncation and overwrite — but not appending. The executor must append, and anything
running in its container as uid 10000 (including the ads-repo mutator subprocess) can; so can
`hermes-broker`, through gid 10000. A fabricated `status: "undone"` record for a real resource
makes `_undo_targets` skip it — reversibility lost as surely as by truncation. Fabricated
`"applied"` records only exhaust the daily caps (fail-safe). No file mode can deny the executor.
The real fix is a host-side writer or signed records — new code on the security path, its own
design. **Deliberately deferred by the operator 2026-09-24; does not gate the kill switch.**
```

and append to "## Open items, in order":

```markdown
9. §6B: audit logs append-only — see "After pulling §6B" in BRING-UP (fill from the PR).
10. F20: forged appends — deferred; needs its own design (host-side writer or signed records).
```

- [ ] **Step 7: BRING-UP — "After pulling §6B".** Insert after the F19 `RESULT` paragraph (before its `---`). The whole section, verbatim:

````markdown
**After pulling §6B** — no unit changes; the broker and pre-flight run their scripts from the
repo. The box has no registered clients, so the new pre-flight check is **vacuous on the real
store** — the proof uses a **scratch store** on the same disk. The real store, the real
registry and the kill switch are never touched. Stop at the first mismatch, but always run the
cleanup block.

Setup (same shell throughout; from `/opt/hermes-agent`):

```bash
cd /opt/hermes-agent
B=/var/lib/hermes-s6b-scratch; SG=$B/governance; SS=$B/spool; L=$SG/log/s6b-probe.jsonl
sudo test -e /var/lib/hermes/governance/control/mutation-enabled && echo PRESENT || echo ABSENT   # ABSENT
PROBE=$(cat <<'EOF'
import errno, os, sys
p = sys.argv[1]
def n():
    with open(p, 'rb') as f: return f.read().count(b'\n')
def t(label, fn):
    try: fn(); print('%-9s OK' % label)
    except OSError as e: print('%-9s DENIED (%s)' % (label, errno.errorcode.get(e.errno, e.errno)))
def app():
    with open(p, 'a') as f: f.write('{}\n')
print('uid=%d gid=%d' % (os.getuid(), os.getgid()))
t('append', app)
t('o_trunc', lambda: os.close(os.open(p, os.O_WRONLY | os.O_TRUNC)))
t('truncate', lambda: os.truncate(p, 0))
print('lines    ', n())
EOF
)
as_broker() { sudo systemd-run --quiet --pipe --wait --collect \
  -p User=hermes-broker -p Group=hermes-broker -p SupplementaryGroups="hermes-rail hermes" \
  -p NoNewPrivileges=true -p ProtectSystem=strict -p ProtectHome=true -p PrivateTmp=true \
  -p ReadWritePaths="$SG" /usr/bin/python3 -c "$PROBE" "$L"; }
as_executor() { sudo docker run --rm --network none --entrypoint python3 \
  -v $SG/log:/opt/governance/log hermes-agent-claude -c "$PROBE" /opt/governance/log/s6b-probe.jsonl; }
build_scratch() {
  sudo mkdir -m 0755 $B
  sudo python3 bin/init-host-layout.py --store-root $SG --spool-root $SS --apply
  sudo sh -c "printf '%s\n' '{\"clients\": {\"s6b-probe\": {\"status\": \"active\"}}}' > $SG/registry/clients.json"
  sudo python3 bin/migrate-governance.py --governance-root $SG --bootstrap-logs --apply
}
teardown_scratch() { sudo chattr -a $L 2>/dev/null; sudo rm -rf $B; sudo test -e $B && echo STILL-THERE || echo GONE; }
```

**Before the pull** (today's code):

```bash
build_scratch                                   # ends with a JSON result naming s6b-probe in "created"
sudo lsattr $L                                  # NO "a" in the flags
as_broker                                       # append OK · o_trunc OK · truncate OK · lines 0  ← the gap
sudo -u hermes-broker python3 bin/preflight-governance-access.py --root $SG; echo rc=$?   # rc=0
teardown_scratch                                # GONE
```

**Pull** (the broker restarts with the proxy):

```bash
sudo git -C /opt/projects/claude_code pull --ff-only
sudo git -C /opt/projects/claude_code log -1 --oneline          # the §6B merge commit
sudo systemctl restart hermes-docker-proxy
systemctl is-active hermes-docker-proxy hermes-broker           # active, active
systemctl show -p NRestarts hermes-docker-proxy hermes-broker   # 0, 0
```

**After:**

```bash
build_scratch
sudo lsattr $L                                  # an "a" in the flags
as_broker                                       # append OK · o_trunc DENIED (EPERM) · truncate DENIED (EPERM) · lines 1
as_executor                                     # uid=10000 · append OK · o_trunc DENIED (EPERM) · truncate DENIED (EPERM) · lines 2
sudo -u hermes-broker python3 bin/preflight-governance-access.py --root $SG; echo rc=$?   # rc=0
sudo chattr -a $L
sudo -u hermes-broker python3 bin/preflight-governance-access.py --root $SG; echo rc=$?   # rc=2, "1 registered client log(s) are not append-only"
```

**Cleanup — always:**

```bash
teardown_scratch                                                                          # GONE
sudo python3 bin/init-host-layout.py --check --store-root /var/lib/hermes/governance --spool-root /var/lib/hermes/spool; echo rc=$?   # layout OK, rc=0
sudo python3 bin/preflight-governance-access.py --root /var/lib/hermes/governance; echo rc=$?   # rc=0
systemctl is-active hermes-docker-proxy hermes-broker                                     # active, active
sudo test -e /var/lib/hermes/governance/control/mutation-enabled && echo PRESENT || echo ABSENT   # ABSENT
```

**When the first real client is registered:** `--bootstrap-logs --apply` seals its log; confirm
with `sudo lsattr /var/lib/hermes/governance/log/*.jsonl` (an `a` on every line).
````

- [ ] **Step 8: Verify and commit**

Run: `grep -rn "NOT append-only\|can truncate an audit log" infra/hermes-agent` → no output. Run `infra/hermes-agent/bin/run-bin-tests.sh` and `node scripts/run-all-tests.js` → all pass.

```bash
git add infra/hermes-agent/README.md infra/hermes-agent/deploy/BRING-UP.md infra/hermes-agent/docker-compose.yml infra/hermes-agent/bin/changeset_lib.py docs/superpowers/specs/2026-09-21-vps-first-bring-up-findings.md docs/superpowers/specs/2026-09-04-s3b-audit-log-integrity-design.md
git commit -m "docs(hermes): §6B records — README, BRING-UP rollout, F20, comments now true

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
git push
```

---

## After the tasks (controller, not an implementer)

1. Whole-branch review on the most capable model; ONE fix wave.
2. Mark the PR ready. PR body: the Task 1 RED run id and its three assertion lines; the firing controls and what each proved; `executed N, skipped 0` for `layout-integration` and `bind-agreement` on the PR. End with the Claude Code line.
3. After merge: read the same counts **on the merge commit**.
4. Box rollout: the operator runs BRING-UP "After pulling §6B", pasting output back.
5. A small docs PR adding the `RESULT` block (real output only) and marking open item 9 done; a brain `[decision]` entry.
