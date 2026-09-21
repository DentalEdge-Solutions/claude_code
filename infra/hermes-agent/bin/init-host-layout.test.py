import contextlib, importlib.util, io, os, shutil, sys, tempfile, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import host_layout as H


def _load(name, filename):
    spec = importlib.util.spec_from_file_location(name, os.path.join(HERE, filename))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


CLI = _load("init_host_layout", "init-host-layout.py")


class Base(unittest.TestCase):
    def setUp(self):
        self.base = os.path.realpath(tempfile.mkdtemp(prefix="init-host-layout-"))
        self.addCleanup(shutil.rmtree, self.base, True)
        self.store = os.path.join(self.base, "governance")
        self.spool = os.path.join(self.base, "spool")
        uid, gid = os.getuid(), os.getgid()
        self.resolver = H.Resolver(users={"root": uid, "hermes-broker": uid},
                                   groups={"hermes": gid, "hermes-broker": gid})
        self.uid = uid

    def run_cli(self, *flags, geteuid=os.geteuid, factory=None):
        out, err = io.StringIO(), io.StringIO()
        argv = ["--store-root", self.store, "--spool-root", self.spool] + list(flags)
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = CLI.main(argv, resolver_factory=factory or (lambda: self.resolver),
                          ancestor_uids=(0, self.uid), ancestor_top=self.base,
                          geteuid=geteuid)
        return rc, out.getvalue(), err.getvalue()


class TestCli(Base):
    def test_dry_run_prints_the_plan_and_creates_nothing(self):
        rc, out, _ = self.run_cli()
        self.assertEqual(rc, 0)
        self.assertEqual(os.listdir(self.base), [])
        self.assertEqual(sum(1 for l in out.splitlines() if l.startswith("create")),
                         len(H.LAYOUT))

    def test_apply_as_non_root_is_refused(self):
        rc, _, err = self.run_cli("--apply", geteuid=lambda: 1000)
        self.assertEqual(rc, 2)
        self.assertIn("root", err)
        self.assertEqual(os.listdir(self.base), [])

    def test_apply_then_check_passes(self):
        rc, out, err = self.run_cli("--apply", geteuid=lambda: 0)
        self.assertEqual(rc, 0, err)
        self.assertIn("layout OK", out)
        rc, out, err = self.run_cli("--check")
        self.assertEqual((rc, err), (0, ""))

    def test_check_reports_drift_with_the_expected_state(self):
        self.run_cli("--apply", geteuid=lambda: 0)
        os.chmod(os.path.join(self.spool, "results"), 0o2770)
        rc, _, err = self.run_cli("--check")
        self.assertEqual(rc, 2)
        self.assertIn("  - " + os.path.join(self.spool, "results"), err)
        self.assertIn("expected hermes-broker:hermes 2750", err)

    def test_check_on_a_missing_layout_says_missing(self):
        rc, _, err = self.run_cli("--check")
        self.assertEqual(rc, 2)
        self.assertIn("missing", err)

    def test_dry_run_with_a_mismatch_exits_two(self):
        os.mkdir(self.store)
        os.chmod(self.store, 0o700)
        rc, out, _ = self.run_cli()
        self.assertEqual(rc, 2)
        self.assertIn("mismatch", out)

    def test_apply_and_check_together_is_a_usage_error(self):
        rc, _, _ = self.run_cli("--apply", "--check")
        self.assertEqual(rc, 1)

    def test_an_unknown_flag_is_a_usage_error(self):
        rc, _, _ = self.run_cli("--repair")
        self.assertEqual(rc, 1)

    def test_a_resolver_refusal_is_exit_two(self):
        def refuse():
            raise H.LayoutError("group 'hermes' is gid 1234")
        rc, _, err = self.run_cli("--check", factory=refuse)
        self.assertEqual(rc, 2)
        self.assertIn("1234", err)


if __name__ == "__main__":
    unittest.main()
