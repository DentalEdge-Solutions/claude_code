#!/usr/bin/env python3
import contextlib, importlib.util, io, os, tempfile, unittest
HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("sa", os.path.join(HERE, "show-audit.py"))
S = importlib.util.module_from_spec(spec); spec.loader.exec_module(S)


class T(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.v = self.root + "/var/lib/hermes/vaults"
        self.a = self.v + "/acme/audits"; os.makedirs(self.a)
        open(self.a + "/2026-09-01_10-00-00-audit.md", "w").write("OLD")
        open(self.a + "/2026-09-30_10-00-00-audit.md", "w").write("NEW")

    def run_(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = S.main(list(argv), root=self.root)
        return rc, out.getvalue(), err.getvalue()

    def test_latest_is_default(self):
        self.assertEqual(self.run_("acme")[:2], (0, "NEW"))

    def test_named_ts(self):
        self.assertEqual(self.run_("acme", "--ts", "2026-09-01_10-00-00")[:2], (0, "OLD"))

    def test_list(self):
        rc, out, _ = self.run_("acme", "--list")
        self.assertEqual(out.split(), ["2026-09-01_10-00-00", "2026-09-30_10-00-00"])

    def test_bad_slug_and_bad_ts_refused(self):
        self.assertEqual(self.run_("../x")[0], 2)
        self.assertEqual(self.run_("acme", "--ts", "../../etc/passwd")[0], 2)

    def test_symlinked_draft_not_followed(self):
        os.symlink("/etc/hostname", self.a + "/2026-10-01_00-00-00-audit.md")
        rc, out, _ = self.run_("acme", "--ts", "2026-10-01_00-00-00")
        self.assertEqual(rc, 1); self.assertEqual(out, "")

    def test_no_audits(self):
        self.assertEqual(self.run_("other")[0], 1)

    def test_symlinked_audits_dir_clean_refusal(self):
        secret = tempfile.mkdtemp()
        open(secret + "/2026-09-30_10-00-00-audit.md", "w").write("SECRET")
        os.makedirs(self.v + "/evil"); os.symlink(secret, self.v + "/evil/audits")
        rc, out, err = self.run_("evil")
        self.assertEqual(rc, 2); self.assertEqual(out, "")
        self.assertNotIn("Traceback", err); self.assertNotIn("SECRET", out + err)

    def test_symlinked_client_dir_clean_refusal(self):
        secret = tempfile.mkdtemp(); os.makedirs(secret + "/audits")
        open(secret + "/audits/2026-09-30_10-00-00-audit.md", "w").write("SECRET")
        os.symlink(secret, self.v + "/evil2")
        rc, out, err = self.run_("evil2", "--latest")
        self.assertEqual(rc, 2); self.assertEqual(out, "")

    def test_missing_vaults_base_is_not_found(self):
        self.root = tempfile.mkdtemp()
        rc, out, err = self.run_("acme")
        self.assertEqual(rc, 1); self.assertNotIn("Traceback", err)


if __name__ == "__main__":
    unittest.main()
