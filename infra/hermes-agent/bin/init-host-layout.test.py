import contextlib, importlib.util, io, os, shutil, sys, tempfile, unittest
from unittest.mock import patch

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

    def test_an_os_error_with_a_rollback_note_surfaces_the_note(self):
        def raise_with_note(*a, **kw):
            e = PermissionError(1, "Operation not permitted")
            e.add_note("rollback could not remove: /x; remove by hand")
            raise e
        with patch.object(CLI.H, "apply", side_effect=raise_with_note):
            rc, _, err = self.run_cli("--apply", geteuid=lambda: 0)
        self.assertEqual(rc, 2)
        self.assertIn("Operation not permitted", err)
        self.assertIn("rollback could not remove", err)
        self.assertNotIn("Traceback", err)


class TestCliApp(Base):
    def setUp(self):
        super().setUp()
        gid = os.getgid()
        self.resolver = H.Resolver(
            users={"root": self.uid, "hermes-broker": self.uid, "hermes-app-ads-audit": self.uid},
            groups={"root": gid, "hermes": gid, "hermes-broker": gid, "hermes-app-ads-audit": gid})

    def run_app(self, *flags, geteuid=os.geteuid):
        out, err = io.StringIO(), io.StringIO()
        argv = ["--app", "ads-audit", "--apps-root", os.path.join(self.base, "apps"),
                "--state-root", os.path.join(self.base, "app-state")] + list(flags)
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = CLI.main(argv, resolver_factory=lambda: self.resolver,
                          ancestor_uids=(0, self.uid), ancestor_top=self.base,
                          geteuid=geteuid)
        return rc, out.getvalue(), err.getvalue()

    def test_app_check_reports_missing(self):
        rc, _, err = self.run_app("--check")
        self.assertEqual(rc, 2)
        self.assertIn("missing", err)

    def test_app_apply_then_check_passes(self):
        rc, out, err = self.run_app("--apply", geteuid=lambda: 0)
        self.assertEqual(rc, 0, err)
        self.assertIn("app layout OK", out)
        rc, out, err = self.run_app("--check")
        self.assertEqual((rc, err), (0, ""))

    def test_a_bad_app_name_is_refused(self):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = CLI.main(["--app", "../x", "--check"], resolver_factory=lambda: self.resolver)
        self.assertEqual(rc, 2)
        self.assertIn("invalid app name", err.getvalue())

    def test_the_default_resolver_covers_the_app_names(self):
        """Without a factory, the CLI must resolve the app's own user and group, not only
        the mutation layout's names, or --check could never pass on a real host."""
        seen = {}
        def fake(layout=H.LAYOUT, **_):
            seen["names"] = {e.owner for e in layout} | {e.group for e in layout}
            return self.resolver
        with patch.object(CLI.H, "system_resolver", side_effect=fake):
            out, err = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                CLI.main(["--app", "ads-audit", "--apps-root", os.path.join(self.base, "apps"),
                          "--state-root", os.path.join(self.base, "app-state"), "--check"],
                         ancestor_uids=(0, self.uid), ancestor_top=self.base)
        self.assertIn("hermes-app-ads-audit", seen["names"])


if __name__ == "__main__":
    unittest.main()
