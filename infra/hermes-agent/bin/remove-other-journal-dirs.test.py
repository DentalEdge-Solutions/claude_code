#!/usr/bin/env python3
import contextlib, importlib.util, unittest.mock, io, os, shutil, stat, sys, tempfile, time, unittest
HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("rm_other", os.path.join(HERE, "remove-other-journal-dirs.py"))
RM = importlib.util.module_from_spec(spec); spec.loader.exec_module(RM)
MID, OTHER = "a" * 32, "b" * 32
OK_ARGS = ("--expect-dirs", "1", "--expect-files", "1", "--expect-bytes", "4096", "--apply")


def build(addcleanup):
    """A fresh temporary root: the machine's own directory (newer file) and one leftover directory."""
    root = tempfile.mkdtemp()
    addcleanup(shutil.rmtree, root, True)
    j = os.path.join(root, "var/log/journal")
    os.makedirs(os.path.join(root, "etc"))
    with open(os.path.join(root, "etc/machine-id"), "w") as f:
        f.write(MID + "\n")
    now = time.time()
    for d, n, age in ((MID, 10, 0), (OTHER, 4096, 1000)):
        os.makedirs(os.path.join(j, d))
        p = os.path.join(j, d, "system.journal")
        with open(p, "w") as f:
            f.write("x" * n)
        os.utime(p, (now - age, now - age))
    return root, j


class T(unittest.TestCase):
    def setUp(self):
        self.root, self.j = build(self.addCleanup)

    def run_(self, *args, root=None):
        with contextlib.redirect_stdout(io.StringIO()) as out, contextlib.redirect_stderr(io.StringIO()) as err:
            rc = RM.main(["--root", root or self.root, *args])
        self.out, self.err = out.getvalue(), err.getvalue()
        return rc, self.out

    def left(self):
        return sorted(os.listdir(self.j))

    def no_ids(self, root=None):
        for text in (self.out, self.err):
            self.assertNotIn(MID, text); self.assertNotIn(OTHER, text); self.assertNotIn(root or self.root, text)

    def test_without_apply_it_only_says_what_it_would_do(self):
        rc, out = self.run_("--expect-dirs", "1", "--expect-files", "1", "--expect-bytes", "4096")
        self.assertEqual((rc, self.left()), (0, [MID, OTHER]))
        self.assertIn("would remove: directories 1 | files 1 | bytes 4096", out)
        self.no_ids()

    def test_with_apply_and_the_expected_counts_it_removes_the_other_directory_only(self):
        rc, out = self.run_(*OK_ARGS)
        self.assertEqual((rc, self.left()), (0, [MID]))
        self.assertIn("removed: directories 1 | files 1 | still there: 0", out)
        self.assertTrue(os.path.exists(os.path.join(self.j, MID, "system.journal")))
        self.no_ids()

    def test_zero_other_directories_with_zero_expected_is_done_and_removes_nothing(self):
        shutil.rmtree(os.path.join(self.j, OTHER))
        rc, out = self.run_("--expect-dirs", "0", "--expect-files", "0", "--expect-bytes", "0", "--apply")
        self.assertEqual((rc, self.left()), (0, [MID]))
        self.assertTrue(os.path.exists(os.path.join(self.j, MID, "system.journal")))

    def test_any_other_count_removes_nothing(self):
        for args in (("2", "1", "4096"), ("1", "2", "4096"), ("1", "1", "4097")):
            with self.subTest(args=args):
                rc, out = self.run_("--expect-dirs", args[0], "--expect-files", args[1],
                                    "--expect-bytes", args[2], "--apply")
                self.assertEqual((rc, self.left()), (1, [MID, OTHER]))
                self.assertIn("STOPPED: nothing was removed", out)
                self.no_ids()

    def test_a_link_or_a_sub_directory_inside_removes_nothing(self):
        for make in (lambda d: os.symlink("/etc/passwd", os.path.join(d, "l")), lambda d: os.mkdir(os.path.join(d, "sub"))):
            root, j = build(self.addCleanup)
            make(os.path.join(j, OTHER))
            rc, _ = self.run_(*OK_ARGS, root=root)
            self.assertEqual((rc, sorted(os.listdir(j))), (1, [MID, OTHER]))
            self.assertTrue(os.path.exists(os.path.join(j, OTHER, "system.journal")))
            self.no_ids(root)

    def test_a_linked_other_directory_removes_nothing_and_leaves_its_target(self):
        os.symlink(os.path.join(self.j, MID), os.path.join(self.j, "c" * 32))
        rc, _ = self.run_("--expect-dirs", "2", "--expect-files", "2", "--expect-bytes", "4106", "--apply")
        self.assertEqual(rc, 1)
        self.assertTrue(os.path.exists(os.path.join(self.j, MID, "system.journal")))
        self.assertTrue(os.path.exists(os.path.join(self.j, OTHER, "system.journal")))
        self.no_ids()

    def test_a_bad_machine_id_removes_nothing(self):
        with open(os.path.join(self.root, "etc/machine-id"), "w") as f:
            f.write("not-an-id\n")
        rc, _ = self.run_(*OK_ARGS)
        self.assertEqual((rc, self.left()), (1, [MID, OTHER]))
        self.no_ids()

    # R1
    @unittest.skipIf(hasattr(os, "geteuid") and os.geteuid() == 0, "root ignores directory modes")
    def test_a_file_that_cannot_be_removed_stops_with_one_fixed_line(self):
        d = os.path.join(self.j, OTHER)
        os.chmod(d, 0o555)
        self.addCleanup(os.chmod, d, 0o755)
        rc, out = self.run_(*OK_ARGS)
        self.assertEqual(rc, 1)
        self.assertIn("STOPPED PART-WAY: files removed 0 of 1 | directories removed 0 of 1 (PermissionError)", out)
        self.assertNotIn("Traceback", self.err)
        self.no_ids()

    # R2
    def test_a_directory_swapped_for_a_link_after_the_count_removes_nothing_outside_the_plan(self):
        real = RM._plan
        def swapping(root):
            plan = real(root)
            shutil.rmtree(os.path.join(self.j, OTHER))
            os.symlink(os.path.join(self.j, MID), os.path.join(self.j, OTHER))
            return plan
        with unittest.mock.patch.object(RM, "_plan", swapping):
            rc, out = self.run_(*OK_ARGS)
        self.assertEqual(rc, 1)
        self.assertIn("STOPPED PART-WAY: files removed 0 of 1 | directories removed 0 of 1", out)
        self.assertTrue(os.path.exists(os.path.join(self.j, MID, "system.journal")))
        self.no_ids()

    # R3
    def test_a_link_above_the_journal_directory_is_refused(self):
        real = tempfile.mkdtemp(); self.addCleanup(shutil.rmtree, real, True)
        shutil.move(os.path.join(self.root, "var/log"), os.path.join(real, "log"))
        os.symlink(os.path.join(real, "log"), os.path.join(self.root, "var/log"))
        rc, out = self.run_(*OK_ARGS)
        self.assertEqual(rc, 1)
        self.assertIn("STOPPED: nothing was removed", out)
        self.assertTrue(os.path.exists(os.path.join(real, "log/journal", OTHER, "system.journal")))
        self.no_ids()

    # R4
    def test_only_a_machine_s_journal_directory_may_be_removed(self):
        for extra in (MID + ".ns", "remote"):
            with self.subTest(extra=extra):
                root, j = build(self.addCleanup)
                os.mkdir(os.path.join(j, extra))
                rc, out = self.run_("--expect-dirs", "2", "--expect-files", "1", "--expect-bytes", "4096",
                                    "--apply", root=root)
                self.assertEqual((rc, sorted(os.listdir(j))), (1, sorted([MID, OTHER, extra])))
                self.assertIn("STOPPED: nothing was removed", out)
                self.no_ids(root)

    # R5
    def test_a_directory_newer_than_the_machine_s_own_is_refused(self):
        now = time.time()
        os.utime(os.path.join(self.j, MID, "system.journal"), (now - 5000, now - 5000))
        rc, out = self.run_(*OK_ARGS)
        self.assertEqual((rc, self.left()), (1, [MID, OTHER]))
        self.assertIn("another directory is newer than this machine's own", out)
        self.no_ids()

    # R6
    def test_an_unreadable_machine_id_prints_the_type_name_only(self):
        with open(os.path.join(self.root, "etc/machine-id"), "wb") as f:
            f.write(b"\xff\xfe" + b"a" * 30)
        rc, out = self.run_(*OK_ARGS)
        self.assertEqual((rc, self.left()), (1, [MID, OTHER]))
        self.assertIn("UnicodeDecodeError", out)
        self.assertNotIn("codec", out + self.err); self.assertNotIn("utf-8", out + self.err)
        self.no_ids()

    def test_an_unexpected_exception_prints_no_traceback(self):
        with unittest.mock.patch.object(RM, "_plan", side_effect=RuntimeError("secret text")):
            rc, out = self.run_(*OK_ARGS)
        self.assertEqual(rc, 1)
        self.assertIn("STOPPED: an unexpected error (RuntimeError)", out)
        self.assertNotIn("secret text", out + self.err); self.assertNotIn("Traceback", self.err)

    # each safeguard of the removal, pinned one at a time (the plan is patched, as in the swap test)
    def _after_the_count(self, change):
        real = RM._plan
        def changing(root):
            plan = real(root)
            change()
            return plan
        with unittest.mock.patch.object(RM, "_plan", changing):
            return self.run_(*OK_ARGS)

    def test_a_different_directory_of_the_same_name_is_not_removed(self):
        def change():
            d = os.path.join(self.j, OTHER)
            os.rename(d, os.path.join(self.root, "moved"))
            os.mkdir(d)
            with open(os.path.join(d, "system.journal"), "w") as f:
                f.write("new")
        rc, out = self._after_the_count(change)
        self.assertEqual(rc, 1)
        self.assertIn("STOPPED PART-WAY: files removed 0 of 1 | directories removed 0 of 1", out)
        self.assertTrue(os.path.exists(os.path.join(self.j, OTHER, "system.journal")))
        self.no_ids()

    def test_a_planned_file_replaced_by_a_link_is_not_removed(self):
        def change():
            p = os.path.join(self.j, OTHER, "system.journal")
            os.remove(p)
            os.symlink(os.path.join(self.j, MID, "system.journal"), p)
        rc, out = self._after_the_count(change)
        self.assertEqual(rc, 1)
        self.assertIn("STOPPED PART-WAY: files removed 0 of 1 | directories removed 0 of 1", out)
        self.assertTrue(os.path.exists(os.path.join(self.j, MID, "system.journal")))
        self.no_ids()

    def test_the_part_way_line_counts_what_was_removed(self):
        def change():
            with open(os.path.join(self.j, OTHER, "added.journal"), "w") as f:
                f.write("z")
        rc, out = self._after_the_count(change)
        self.assertEqual(rc, 1)
        self.assertRegex(out, r"STOPPED PART-WAY: files removed 1 of 1 \| directories removed 0 of 1 \(OSError\)\n")
        self.assertEqual(os.listdir(os.path.join(self.j, OTHER)), ["added.journal"])
        self.no_ids()

    def test_a_sub_directory_in_the_own_directory_does_not_hide_a_newer_leftover(self):
        now = time.time()
        os.utime(os.path.join(self.j, MID, "system.journal"), (now - 5000, now - 5000))
        os.utime(os.path.join(self.j, OTHER, "system.journal"), (now - 100, now - 100))
        os.mkdir(os.path.join(self.j, MID, "fresh"))
        rc, out = self.run_(*OK_ARGS)
        self.assertEqual((rc, self.left()), (1, [MID, OTHER]))
        self.assertIn("another directory is newer than this machine's own", out)
        self.no_ids()

    def test_an_interrupt_during_removal_prints_the_part_way_line(self):
        def interrupted(plan, done):
            done[0] = 1
            raise KeyboardInterrupt
        with unittest.mock.patch.object(RM, "_remove", interrupted):
            rc, out = self.run_(*OK_ARGS)
        self.assertEqual(rc, 1)
        self.assertIn("STOPPED PART-WAY: files removed 1 of 1 | directories removed 0 of 1 (KeyboardInterrupt)", out)
        self.assertNotIn("Traceback", self.err)

    # R7
    def test_an_abbreviated_flag_is_a_usage_error(self):
        with self.assertRaises(SystemExit) as cm:
            self.run_("--expect-dirs", "1", "--expect-files", "1", "--expect-bytes", "4096", "--app")
        self.assertEqual(cm.exception.code, 2)
        self.assertEqual(self.left(), [MID, OTHER])


if __name__ == "__main__":
    unittest.main()
