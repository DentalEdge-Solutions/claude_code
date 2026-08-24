import importlib.util, io, os, shutil, sys, tempfile, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)


def _load(name, filename):
    spec = importlib.util.spec_from_file_location(name, os.path.join(HERE, filename))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


PF = _load("preflight_governance_access", "preflight-governance-access.py")

ALL_DIRS = PF.READ_ONLY_DIRS + PF.READ_WRITE_DIRS


class Base(unittest.TestCase):
    """A governance store laid out the way the real one is, with every subdirectory
    present so a reported problem is about MODE, never about absence."""

    def setUp(self):
        self.root = os.path.realpath(tempfile.mkdtemp(prefix="governance-"))
        self.addCleanup(shutil.rmtree, self.root, True)
        # Restore traversable modes before the rmtree above runs (cleanups run LIFO),
        # or a test that removes owner-x leaves the tempdir behind.
        self.addCleanup(self._restore_modes)
        for name in ALL_DIRS:
            os.makedirs(os.path.join(self.root, name))
        self.uid = os.getuid()
        self.gid = os.getgid()
        # A UID that is definitely not this process's owner, and a GID likewise:
        # the executor's real UID (10000) may coincidentally match on some hosts,
        # which would silently turn every negative test into a control.
        self.other_uid = self.uid + 4242
        self.other_gid = self.gid + 4242

    def _restore_modes(self):
        os.chmod(self.root, 0o700)
        for name in ALL_DIRS:
            p = os.path.join(self.root, name)
            if os.path.isdir(p):
                os.chmod(p, 0o700)

    def _chmod_all(self, mode):
        # Children first: dropping owner-x on the root would make the children
        # unreachable for their own chmod.
        for name in ALL_DIRS:
            os.chmod(os.path.join(self.root, name), mode)
        os.chmod(self.root, mode)


class TestLinuxSemantics(Base):
    """platform is passed explicitly so these run identically on macOS and on the VPS —
    the whole point of the finding is that the local host cannot reproduce the VPS."""

    def test_mode_700_owned_by_someone_else_is_refused(self):
        """The exact VPS condition: store owned by the deploy user at 700, executor
        running as uid 10000."""
        self._chmod_all(0o700)
        problems = PF.check(self.root, self.other_uid, self.other_gid, platform="linux")
        self.assertEqual(len(problems), len(ALL_DIRS) + 1)     # +1 for the root itself
        for name in ALL_DIRS:
            self.assertTrue(any(name in p for p in problems), name)

    def test_control_same_store_same_mode_but_the_owning_uid_passes(self):
        """CONTROL. Without this the refusal above proves only that the function can
        return something — it must ACCEPT the identical layout when the UID matches."""
        self._chmod_all(0o700)
        self.assertEqual(PF.check(self.root, self.uid, self.gid, platform="linux"), [])

    def test_group_readable_store_with_a_matching_gid_passes(self):
        """The documented remedy: keep the store off `other`, grant the executor's
        group. log/ and seen/ additionally need write, hence 0o770 there."""
        os.chmod(self.root, 0o750)
        for name in PF.READ_ONLY_DIRS:
            os.chmod(os.path.join(self.root, name), 0o750)
        for name in PF.READ_WRITE_DIRS:
            os.chmod(os.path.join(self.root, name), 0o770)
        self.assertEqual(PF.check(self.root, self.other_uid, self.gid, platform="linux"), [])

    def test_read_only_store_flags_only_the_writable_directories(self):
        """0o755 throughout: everything is readable, but the executor must WRITE the
        audit log and the seen-set. A check that only tested readability would pass
        here and let append_log fail mid-apply — which is the finding."""
        self._chmod_all(0o755)
        problems = PF.check(self.root, self.other_uid, self.other_gid, platform="linux")
        self.assertEqual(len(problems), len(PF.READ_WRITE_DIRS))
        for name in PF.READ_WRITE_DIRS:
            self.assertTrue(any(name in p for p in problems), name)
        for name in PF.READ_ONLY_DIRS:
            self.assertFalse(any(name in p for p in problems), name)

    def test_owner_class_wins_even_when_group_and_other_are_wider(self):
        """POSIX selects exactly ONE permission class. A directory owned by the
        executor at mode 0o077 is unreadable to it however wide `other` is; an
        implementation that OR'd the classes would wrongly pass this."""
        self._chmod_all(0o077)
        problems = PF.check(self.root, self.uid, self.gid, platform="linux")
        self.assertEqual(len(problems), len(ALL_DIRS) + 1)

    def test_a_missing_subdirectory_is_reported(self):
        self._chmod_all(0o755)
        os.rmdir(os.path.join(self.root, "seen"))
        problems = PF.check(self.root, self.uid, self.gid, platform="linux")
        self.assertTrue(any("seen" in p and "cannot stat" in p for p in problems))


class TestScope(Base):
    def test_non_linux_reports_nothing_even_when_unreadable(self):
        """Deliberate scope, not an oversight: Docker Desktop remaps ownership on
        macOS, so a stat-based prediction there would be false. Paired with the Linux
        test above, which refuses the identical layout."""
        self._chmod_all(0o700)
        self.assertEqual(PF.check(self.root, self.other_uid, self.other_gid,
                                  platform="darwin"), [])
        self.assertFalse(PF.applies("darwin"))
        self.assertTrue(PF.applies("linux"))


class TestCli(Base):
    def _main(self, argv):
        err = io.StringIO()
        old = sys.stderr
        sys.stderr = err
        try:
            rc = PF.main(argv)
        finally:
            sys.stderr = old
        return rc, err.getvalue()

    def test_cli_exits_zero_when_the_store_is_usable(self):
        self._chmod_all(0o700)
        rc, _ = self._main(["--root", self.root, "--uid", str(self.uid),
                            "--gid", str(self.gid)])
        self.assertEqual(rc, 0)

    @unittest.skipUnless(PF.applies(), "stat-based prediction only holds on Linux")
    def test_cli_exits_two_and_names_the_remedy(self):
        self._chmod_all(0o700)
        rc, err = self._main(["--root", self.root, "--uid", str(self.other_uid),
                              "--gid", str(self.other_gid)])
        self.assertEqual(rc, 2)
        self.assertIn("chown", err)
        self.assertIn("Do NOT `chmod 777`", err)


if __name__ == "__main__":
    unittest.main()
