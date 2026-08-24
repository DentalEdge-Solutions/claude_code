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
