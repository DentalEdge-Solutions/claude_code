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


if __name__ == "__main__":
    unittest.main()
