#!/usr/bin/env python3
import contextlib, hashlib, importlib.util, io, os, stat, tempfile, unittest
from unittest import mock
HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("mcd", os.path.join(HERE, "migrate-client-data.py"))
M = importlib.util.module_from_spec(spec); spec.loader.exec_module(M)


class T(unittest.TestCase):
    def setUp(self):
        self.t = tempfile.mkdtemp()
        self.agent = os.path.join(self.t, "agent"); self.dest = os.path.join(self.t, "dest")
        v = os.path.join(self.agent, "data/vaults/acme/audits"); os.makedirs(v)
        open(os.path.join(v, "2026-09-30_10-00-00-audit.md"), "w").write("draft")
        open(os.path.join(self.agent, "data/vaults/acme/timeline.md"), "w").write("t")
        os.chmod(os.path.join(self.agent, "data/vaults/acme"), 0o700)
        r = os.path.join(self.agent, "data/reports/claude_google_ads"); os.makedirs(r)
        open(os.path.join(r, "x.md"), "w").write("r")
        for tree in ("vaults", "reports"):
            os.makedirs(os.path.join(self.dest, tree)); os.chmod(os.path.join(self.dest, tree), 0o711)
        M.ROOT_UID = os.geteuid()

    def run_(self, *extra):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            rc = M.main(["--agent-dir", self.agent, "--dest-root", self.dest, *extra])
        return rc, out.getvalue()

    def test_dry_run_changes_nothing(self):
        rc, text = self.run_()
        self.assertEqual(rc, 0)
        self.assertTrue(os.path.isdir(os.path.join(self.agent, "data/vaults")))
        self.assertFalse(os.path.exists(os.path.join(self.dest, "vaults/acme")))
        self.assertNotIn("draft", text.replace("drafts", ""))

    def test_apply_copies_verifies_and_removes(self):
        rc, text = self.run_("--apply")
        self.assertEqual(rc, 0, text)
        got = os.path.join(self.dest, "vaults/acme/audits/2026-09-30_10-00-00-audit.md")
        self.assertEqual(open(got).read(), "draft")
        self.assertEqual(stat.S_IMODE(os.stat(os.path.join(self.dest, "vaults/acme")).st_mode), 0o700)
        self.assertFalse(os.path.exists(os.path.join(self.agent, "data/vaults")))
        self.assertFalse(os.path.exists(os.path.join(self.agent, "data/reports")))
        self.assertFalse(os.path.exists(os.path.join(self.dest, "reports/claude_google_ads")))

    def test_mtime_and_mode_preserved(self):
        f = os.path.join(self.agent, "data/vaults/acme/timeline.md")
        os.chmod(f, 0o640); os.utime(f, ns=(1_000_000_000_000_000_000, 1_100_000_000_000_000_000))
        rc, text = self.run_("--apply")
        self.assertEqual(rc, 0, text)
        st = os.stat(os.path.join(self.dest, "vaults/acme/timeline.md"))
        self.assertEqual(stat.S_IMODE(st.st_mode), 0o640)
        self.assertEqual(st.st_mtime_ns, 1_100_000_000_000_000_000)

    def test_verify_mismatch_keeps_source(self):
        real = M._sha256
        def flaky(p):
            return "0" * 64 if p.startswith(self.dest) else real(p)
        with mock.patch.object(M, "_sha256", flaky):
            rc, text = self.run_("--apply")
        self.assertEqual(rc, 1)
        self.assertTrue(os.path.isdir(os.path.join(self.agent, "data/vaults/acme")))
        self.assertTrue(os.path.isdir(os.path.join(self.agent, "data/reports")))
        # the operator is told which destination dir to remove, never contents
        self.assertIn(os.path.join(self.dest, "vaults", "acme"), text)
        self.assertNotIn("draft", text.replace("drafts", ""))

    def test_copy_failure_partway_names_created_dirs_and_keeps_source(self):
        os.makedirs(os.path.join(self.agent, "data/vaults/beta"))
        real = M._copy_client
        def boom(src, dst, entries):
            real(src, dst, entries)
            if dst.endswith("beta"):
                raise OSError("disk full")
        with mock.patch.object(M, "_copy_client", boom):
            rc, text = self.run_("--apply")
        self.assertEqual(rc, 1)
        self.assertTrue(os.path.isdir(os.path.join(self.agent, "data/vaults/acme")))
        self.assertIn(os.path.join(self.dest, "vaults", "acme"), text)
        self.assertIn(os.path.join(self.dest, "vaults", "beta"), text)

    def test_symlink_in_source_refused_before_copying(self):
        os.symlink("/etc/passwd", os.path.join(self.agent, "data/vaults/acme/evil"))
        rc, _ = self.run_("--apply")
        self.assertEqual(rc, 2)
        self.assertFalse(os.path.exists(os.path.join(self.dest, "vaults/acme")))

    def test_symlink_in_reports_refused_before_copying(self):
        os.symlink("/etc/passwd", os.path.join(self.agent, "data/reports/evil"))
        rc, _ = self.run_("--apply")
        self.assertEqual(rc, 2)
        self.assertFalse(os.path.exists(os.path.join(self.dest, "vaults/acme")))
        self.assertTrue(os.path.isdir(os.path.join(self.agent, "data/vaults/acme")))

    def test_swap_to_symlink_after_walk_is_not_followed(self):
        secret = os.path.join(self.t, "secret"); open(secret, "w").write("SECRET")
        src = os.path.join(self.agent, "data/vaults/acme")
        entries = M._walk(src)
        f = os.path.join(src, "timeline.md")
        os.remove(f); os.symlink(secret, f)
        dst = os.path.join(self.dest, "vaults/acme")
        with self.assertRaises(M.Refused):
            M._copy_client(src, dst, entries)
        for dp, _, fns in os.walk(dst):
            for n in fns:
                self.assertNotEqual(open(os.path.join(dp, n)).read(), "SECRET")

    def test_swap_dir_to_symlink_after_walk_is_not_followed(self):
        other = os.path.join(self.t, "other"); os.makedirs(other)
        open(os.path.join(other, "2026-09-30_10-00-00-audit.md"), "w").write("SECRET")
        src = os.path.join(self.agent, "data/vaults/acme")
        entries = M._walk(src)
        import shutil
        shutil.rmtree(os.path.join(src, "audits")); os.symlink(other, os.path.join(src, "audits"))
        dst = os.path.join(self.dest, "vaults/acme")
        with self.assertRaises(M.Refused):
            M._copy_client(src, dst, entries)

    def test_client_that_is_a_file_refused(self):
        open(os.path.join(self.agent, "data/vaults/stray"), "w").write("x")
        rc, _ = self.run_("--apply")
        self.assertEqual(rc, 2)
        self.assertFalse(os.path.exists(os.path.join(self.dest, "vaults/acme")))

    def test_existing_destination_refused(self):
        os.makedirs(os.path.join(self.dest, "vaults/acme"))
        rc, _ = self.run_("--apply")
        self.assertEqual(rc, 2)

    def test_bad_dest_parent_refused(self):
        os.chmod(os.path.join(self.dest, "vaults"), 0o755)
        rc, _ = self.run_("--apply")
        self.assertEqual(rc, 2)

    def _after_copy(self, fn):
        """Run fn(dst) right after each real client copy (i.e. between copy and verify/removal)."""
        real = M._copy_client
        def wrapped(src, dst, entries):
            out = real(src, dst, entries)
            fn(src, dst)
            return out
        return mock.patch.object(M, "_copy_client", wrapped)

    @unittest.skipIf(os.geteuid() == 0, "root ignores chmod 000")
    def test_unreadable_source_subdir_refused_before_copying(self):
        d = os.path.join(self.agent, "data/vaults/acme/audits")
        os.chmod(d, 0)
        self.addCleanup(os.chmod, d, 0o700)
        rc, _ = self.run_("--apply")
        self.assertEqual(rc, 2)
        self.assertFalse(os.path.exists(os.path.join(self.dest, "vaults/acme")))

    def test_file_added_after_copy_keeps_source(self):
        def add(src, dst):
            open(os.path.join(src, "late.md"), "w").write("new")
        with self._after_copy(add):
            rc, text = self.run_("--apply")
        self.assertEqual(rc, 1, text)
        self.assertTrue(os.path.exists(os.path.join(self.agent, "data/vaults/acme/late.md")))
        self.assertTrue(os.path.isdir(os.path.join(self.agent, "data/reports")))
        self.assertIn(os.path.join(self.dest, "vaults", "acme"), text)

    def test_source_file_modified_after_copy_keeps_source(self):
        def mod(src, dst):
            with open(os.path.join(src, "timeline.md"), "w") as f: f.write("changed!")
        with self._after_copy(mod):
            rc, text = self.run_("--apply")
        self.assertEqual(rc, 1, text)
        self.assertTrue(os.path.isdir(os.path.join(self.agent, "data/vaults/acme")))

    def test_new_client_dir_after_copy_keeps_source(self):
        def add(src, dst):
            os.makedirs(os.path.join(self.agent, "data/vaults/newclient"), exist_ok=True)
        with self._after_copy(add):
            rc, text = self.run_("--apply")
        self.assertEqual(rc, 1, text)
        self.assertTrue(os.path.isdir(os.path.join(self.agent, "data/vaults/newclient")))
        self.assertTrue(os.path.isdir(os.path.join(self.agent, "data/vaults/acme")))

    def test_dest_swapped_to_symlink_before_verify_fails(self):
        secret = os.path.join(self.t, "secret"); open(secret, "w").write("t")  # same bytes as timeline.md
        def swap(src, dst):
            f = os.path.join(dst, "timeline.md"); os.remove(f); os.symlink(secret, f)
        with self._after_copy(swap):
            rc, text = self.run_("--apply")
        self.assertEqual(rc, 1, text)
        self.assertTrue(os.path.isdir(os.path.join(self.agent, "data/vaults/acme")))

    def test_real_tamper_of_destination_detected_without_mocking_hash(self):
        def tamper(src, dst):
            f = os.path.join(dst, "audits/2026-09-30_10-00-00-audit.md")
            with open(f, "r+b") as fh: fh.write(b"X")  # same size, one byte differs
        with self._after_copy(tamper):
            rc, text = self.run_("--apply")
        self.assertEqual(rc, 1, text)
        self.assertTrue(os.path.isdir(os.path.join(self.agent, "data/vaults/acme")))
        self.assertIn("acme/audits/2026-09-30_10-00-00-audit.md", text)
        self.assertIn(os.path.join(self.dest, "vaults", "acme"), text)

    def test_source_removal_failure_is_rc3_and_says_keep_the_destination(self):
        """Copies verified but rmtree fails: NOT rc 1 (whose advice is to remove the destination)."""
        def boom(path, *a, **k):
            raise OSError(16, "Device or resource busy", path)
        with mock.patch.object(M.shutil, "rmtree", boom):
            rc, text = self.run_("--apply")
        self.assertEqual(rc, 3, text)
        got = os.path.join(self.dest, "vaults/acme/audits/2026-09-30_10-00-00-audit.md")
        self.assertEqual(open(got).read(), "draft")                  # destination intact
        self.assertIn("DO NOT remove the destination", text)
        self.assertIn("data/vaults and data/reports by hand", text)
        self.assertNotIn("remove each, then re-run", text)

    def test_dir_owner_mode_mtime_preserved_at_every_depth(self):
        """Deepest first, the client dir LAST: the final owner/mode/mtime of every dir is the source's."""
        src = os.path.join(self.agent, "data/vaults/acme")
        deep = os.path.join(src, "metrics/2026"); os.makedirs(deep)
        open(os.path.join(deep, "m.json"), "w").write("{}")
        want = {}
        for rel, mode, mt in (("metrics/2026", 0o750, 1_300_000_000_000_000_000),
                              ("metrics", 0o710, 1_200_000_000_000_000_000),
                              ("audits", 0o700, 1_150_000_000_000_000_000),
                              ("", 0o700, 1_100_000_000_000_000_000)):
            d = os.path.join(src, rel) if rel else src
            os.chmod(d, mode); os.utime(d, ns=(mt, mt))
            want[rel] = (mode, mt, os.stat(d).st_uid, os.stat(d).st_gid)
        order = []
        real_chown = os.chown
        def chown(p, *a, **k):
            order.append(os.path.relpath(p, os.path.join(self.dest, "vaults/acme")))
            return real_chown(p, *a, **k)
        with mock.patch.object(M.os, "chown", chown):
            rc, text = self.run_("--apply")
        self.assertEqual(rc, 0, text)
        self.assertEqual(order[-1], ".", order)                      # the client dir is applied last
        for rel, (mode, mt, uid, gid) in want.items():
            st = os.stat(os.path.join(self.dest, "vaults/acme", rel) if rel else os.path.join(self.dest, "vaults/acme"))
            self.assertEqual((stat.S_IMODE(st.st_mode), st.st_mtime_ns, st.st_uid, st.st_gid), (mode, mt, uid, gid), rel)


if __name__ == "__main__":
    unittest.main()
