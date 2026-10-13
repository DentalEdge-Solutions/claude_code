#!/usr/bin/env python3
import contextlib, importlib.util, io, os, sys, tempfile, unittest
HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("rm_other", os.path.join(HERE, "remove-other-journal-dirs.py"))
RM = importlib.util.module_from_spec(spec); spec.loader.exec_module(RM)
MID, OTHER = "a" * 32, "b" * 32


class T(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.j = os.path.join(self.root, "var/log/journal")
        os.makedirs(os.path.join(self.root, "etc"))
        with open(os.path.join(self.root, "etc/machine-id"), "w") as f:
            f.write(MID + "\n")
        for d, n in ((MID, 10), (OTHER, 4096)):
            os.makedirs(os.path.join(self.j, d))
            with open(os.path.join(self.j, d, "system.journal"), "w") as f:
                f.write("x" * n)

    def run_(self, *args):
        with contextlib.redirect_stdout(io.StringIO()) as out:
            rc = RM.main(["--root", self.root, *args])
        return rc, out.getvalue()

    def left(self):
        return sorted(os.listdir(self.j))

    def test_without_apply_it_only_says_what_it_would_do(self):
        rc, out = self.run_("--expect-dirs", "1", "--expect-files", "1", "--expect-bytes", "4096")
        self.assertEqual((rc, self.left()), (0, [MID, OTHER]))
        self.assertIn("would remove: directories 1 | files 1 | bytes 4096", out)
        self.assertNotIn(OTHER, out); self.assertNotIn(MID, out)

    def test_with_apply_and_the_expected_counts_it_removes_the_other_directory_only(self):
        rc, out = self.run_("--expect-dirs", "1", "--expect-files", "1", "--expect-bytes", "4096", "--apply")
        self.assertEqual((rc, self.left()), (0, [MID]))
        self.assertIn("removed: directories 1 | files 1 | still there: 0", out)
        self.assertTrue(os.path.exists(os.path.join(self.j, MID, "system.journal")))

    def test_any_other_count_removes_nothing(self):
        for args in (("2", "1", "4096"), ("1", "2", "4096"), ("1", "1", "4097")):
            with self.subTest(args=args):
                rc, out = self.run_("--expect-dirs", args[0], "--expect-files", args[1],
                                    "--expect-bytes", args[2], "--apply")
                self.assertEqual((rc, self.left()), (1, [MID, OTHER]))
                self.assertIn("STOPPED: nothing was removed", out)

    def test_a_link_or_a_sub_directory_inside_removes_nothing(self):
        for make in (lambda d: os.symlink("/etc/passwd", os.path.join(d, "l")), lambda d: os.mkdir(os.path.join(d, "sub"))):
            self.setUp()
            make(os.path.join(self.j, OTHER))
            rc, _ = self.run_("--expect-dirs", "1", "--expect-files", "1", "--expect-bytes", "4096", "--apply")
            self.assertEqual((rc, self.left()), (1, [MID, OTHER]))

    def test_a_linked_other_directory_or_a_bad_machine_id_removes_nothing(self):
        os.symlink(os.path.join(self.j, MID), os.path.join(self.j, "c" * 32))
        rc, _ = self.run_("--expect-dirs", "2", "--expect-files", "2", "--expect-bytes", "4106", "--apply")
        self.assertEqual(rc, 1)
        with open(os.path.join(self.root, "etc/machine-id"), "w") as f:
            f.write("not-an-id\n")
        rc, _ = self.run_("--expect-dirs", "1", "--expect-files", "1", "--expect-bytes", "4096", "--apply")
        self.assertEqual((rc, MID in self.left()), (1, True))


if __name__ == "__main__":
    unittest.main()
