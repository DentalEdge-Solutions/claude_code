#!/usr/bin/env python3
import contextlib, importlib.util, io, os, tempfile, unittest
HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("sr", os.path.join(HERE, "show-report.py"))
S = importlib.util.module_from_spec(spec); spec.loader.exec_module(S)


class T(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.v = self.root + "/var/lib/hermes/report-archive"
        self.a = self.v + "/acme"; os.makedirs(self.a)
        open(self.a + "/2026-09-01_10-00-00-report.md", "w").write("OLD")
        open(self.a + "/2026-09-30_10-00-00-report.md", "w").write("NEW")

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

    def test_symlinked_report_not_followed(self):
        os.symlink("/etc/hostname", self.a + "/2026-10-01_00-00-00-report.md")
        rc, out, _ = self.run_("acme", "--ts", "2026-10-01_00-00-00")
        self.assertEqual(rc, 1); self.assertEqual(out, "")

    def test_no_reports(self):
        self.assertEqual(self.run_("other")[0], 1)

    def test_a_linked_entry_is_not_listed_and_not_the_latest(self):
        os.symlink("/etc/hostname", self.a + "/2026-10-05_00-00-00-report.md")
        rc, out, _ = self.run_("acme", "--list")
        self.assertEqual(out.split(), ["2026-09-01_10-00-00", "2026-09-30_10-00-00"])
        self.assertEqual(self.run_("acme", "--latest")[:2], (0, "NEW"))

    def test_symlinked_client_dir_clean_refusal(self):
        secret = tempfile.mkdtemp()
        open(secret + "/2026-09-30_10-00-00-report.md", "w").write("SECRET")
        os.symlink(secret, self.v + "/evil2")
        rc, out, err = self.run_("evil2", "--latest")
        self.assertEqual(rc, 2); self.assertEqual(out, "")
        self.assertNotIn("SECRET", out + err)

    def test_terminal_control_characters_are_stripped(self):
        """The report is model output steered by attacker-controlled search terms: no ESC (or any
        other C0 control but newline and tab) reaches the operator's terminal."""
        evil = "DRAFT\x1b]0;pwned\x07 title\n\tcol\x1b[2J\x1b[31mred\x00\x08\r\x7f ok\n"
        open(self.a + "/2026-10-01_00-00-00-report.md", "w").write(evil)
        rc, out, _ = self.run_("acme", "--ts", "2026-10-01_00-00-00")
        self.assertEqual(rc, 0)
        self.assertFalse([c for c in out if (ord(c) < 32 and c not in "\n\t") or ord(c) == 0x7f], repr(out))
        self.assertEqual(out, "DRAFT]0;pwned title\n\tcol[2J[31mred ok\n")
        open(self.a + "/2026-10-02_00-00-00-report.md", "w", encoding="utf-8").write("a\u009b31mb \u00e9\n")
        self.assertEqual(self.run_("acme", "--ts", "2026-10-02_00-00-00")[1], "a31mb \u00e9\n")   # C1 CSI too

    def test_missing_archive_base_is_not_found(self):
        self.root = tempfile.mkdtemp()
        rc, out, err = self.run_("acme")
        self.assertEqual(rc, 1); self.assertNotIn("Traceback", err)


if __name__ == "__main__":
    unittest.main()
