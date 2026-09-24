import array, errno, os, shutil, sys, tempfile, unittest
from unittest import mock
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


class TestLockPath(unittest.TestCase):
    def test_lock_path(self):
        self.assertEqual(G.lock_path("acme-dental", "/tmp/gov"),
                         "/tmp/gov/control/.locks/acme-dental.lock")

    def test_lock_path_is_not_in_the_spool(self):
        self.assertNotIn("spool", G.lock_path("acme-dental", "/tmp/gov"))

    def test_bad_slug_refuses(self):
        for bad in ("../etc", "UPPER", "acme-dental\n", ""):
            with self.assertRaises(ValueError):
                G.lock_path(bad, "/tmp/gov")


class TestApprovalLockPath(unittest.TestCase):
    """Coverage gap, not a bug: every sibling path helper here had tests and this one
    had none, although it is the path whose IDENTITY makes single-use approval
    self-enforcing. reserve_approval and record_outcome flock this sidecar precisely
    because the approval record itself is rewritten via os.replace and a lock on that
    fd would be a lock on the old inode. A silent change to this helper — a different
    directory, a suffix collision, a dropped validation — would have broken that with
    nothing going red."""

    R = "/tmp/gov"
    SLUG = "acme-dental"
    CID = "20260812-101500-abcd1234"

    def test_approval_lock_path(self):
        self.assertEqual(G.approval_lock_path(self.SLUG, self.CID, self.R),
                         "/tmp/gov/approvals/acme-dental/%s.approval.lock" % self.CID)

    def test_it_is_a_sibling_of_the_approval_record_not_the_record_itself(self):
        """The whole reason this helper exists. If it ever returned approval_path()'s
        own path, flock would be taken on an inode os.replace is about to swap out and
        single-use approval would stop being enforced — silently, because the lock call
        would still succeed."""
        lock = G.approval_lock_path(self.SLUG, self.CID, self.R)
        record = G.approval_path(self.SLUG, self.CID, self.R)
        snapshot = G.snapshot_path(self.SLUG, self.CID, self.R)
        self.assertNotEqual(lock, record)
        self.assertNotEqual(lock, snapshot)
        self.assertEqual(os.path.dirname(lock), os.path.dirname(record))
        self.assertEqual(os.path.dirname(lock),
                         G.approvals_dir(self.SLUG, self.R))

    def test_it_lives_in_the_governance_store_not_the_spool(self):
        """It is lockable mutual exclusion only because no container can delete it: the
        gateway does not mount the governance store and the executor mounts approvals/
        read-only. A lock in the spool would be one the governed party can remove."""
        lock = G.approval_lock_path(self.SLUG, self.CID, self.R)
        self.assertTrue(lock.startswith(self.R + "/"))
        self.assertNotIn("spool", lock)

    def test_distinct_changesets_get_distinct_locks(self):
        """Per-approval, not per-client: two change-sets for one client must not
        serialise against each other. A helper that ignored the cid would pass every
        single-path assertion above."""
        other = "20260812-101500-abcd1235"
        self.assertNotEqual(G.approval_lock_path(self.SLUG, self.CID, self.R),
                            G.approval_lock_path(self.SLUG, other, self.R))

    def test_it_never_collides_with_the_lock_path_of_the_other_lock(self):
        """lock_path() and approval_lock_path() are documented as DIFFERENT FILES so
        that nesting them cannot deadlock. Pinned, because that is a claim in prose
        that nothing else checks."""
        self.assertNotEqual(G.approval_lock_path(self.SLUG, self.CID, self.R),
                            G.lock_path(self.SLUG, self.R))

    def test_bad_slug_refuses(self):
        for bad in ("../etc", "UPPER", "acme-dental\n", "", None, 7):
            with self.assertRaises(ValueError):
                G.approval_lock_path(bad, self.CID, self.R)

    def test_bad_changeset_id_refuses(self):
        """A path helper that accepts junk is a path-traversal primitive, and this one
        interpolates the cid straight into a filename."""
        for bad in ("../etc", "20260812-101500-ABCD1234", "20260812-101500-abcd123",
                    "a/b", "", None, 7):
            with self.assertRaises(ValueError):
                G.approval_lock_path(self.SLUG, bad, self.R)


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


if __name__ == "__main__":
    unittest.main()
