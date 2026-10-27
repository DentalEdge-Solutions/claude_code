#!/usr/bin/env python3
import contextlib, importlib.util, io, json, os, subprocess, sys, tempfile, unittest
from unittest import mock
import review_lib as R
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
spec = importlib.util.spec_from_file_location("collect_laptop", os.path.join(HERE, "collect-review-evidence-laptop.py"))
L = importlib.util.module_from_spec(spec); spec.loader.exec_module(L)
spec_build = importlib.util.spec_from_file_location("build_app_package", os.path.join(HERE, "build-app-package.py"))
B = importlib.util.module_from_spec(spec_build); spec_build.loader.exec_module(B)


def doc(label, verdict, admin, rt="aaaaaaaaaaaa"):
    return json.dumps({"label": label, "fingerprints": {"refresh_token_sha12": rt, "client_id_sha12": "c"},
                       "declared_role": "write" if label.endswith("w") else "read",
                       "expected_verdict": verdict, "measured_verdict": verdict, "mismatch": False,
                       "manager_level_admin": {"admin": admin, "reason": "x"}}, indent=2)


def git(repo, *args):
    return subprocess.run(["git", "-C", repo, "-c", "user.email=t@t", "-c", "user.name=t", *args],
                          check=True, capture_output=True).stdout.decode().strip()


AUDIT = ("Container x Creating\nContainer x Created\n" + doc(".env.ga", "READ_ONLY", False, "r" * 12) +
         "\nContainer y Created\n" + doc(".env.gaw", "MUTATE_CAPABLE", True) + "\n")


class TestParse(unittest.TestCase):
    def test_extracts_both_documents_through_compose_noise(self):
        rows = L.parse_audit(AUDIT)
        self.assertEqual([r["label"] for r in rows], [".env.ga", ".env.gaw"])
        self.assertEqual(rows[1]["admin"], True)

    def test_digest_is_stable_and_changes_with_access(self):
        a = L.access_digest(L.parse_audit(AUDIT))
        self.assertEqual(a, L.access_digest(L.parse_audit(AUDIT)))
        drift = AUDIT.replace('"admin": true', '"admin": false')
        self.assertNotEqual(a, L.access_digest(L.parse_audit(drift)))

    def test_no_documents_raises(self):
        with self.assertRaises(ValueError):
            L.parse_audit("Container x Created\n")


class TestAuditRun(unittest.TestCase):
    def test_exit_code_is_the_audits_own_and_stderr_is_discarded(self):
        cid = "1234567890"
        audit_with_cid = ("Container x Creating\nContainer x Created\n" + doc(f"{cid}-.env.ga", "READ_ONLY", False, "r" * 12) +
                          "\nContainer y Created\n" + doc(".env.gaw", "MUTATE_CAPABLE", True) + "\n")
        fake = mock.Mock(returncode=3, stdout=audit_with_cid, stderr="Request made: ClientCustomerId: 1234567890 ...")
        with mock.patch.object(L.subprocess, "run", return_value=fake):
            out = L.run_audit(cid)
        self.assertEqual(out["rc"], 3)
        out_json = json.dumps(out)
        self.assertNotIn(cid, out_json)
        redacted = "cid:" + R.sha12(cid)
        self.assertIn(redacted, out_json)
        self.assertEqual(out["stderr_lines_discarded"], 1)


KEY_HEX = "11" * 32


class TestMain(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.keyfile = os.path.join(self.tmp.name, "fp.key")
        with open(self.keyfile, "w") as f:
            f.write(KEY_HEX + "\n")
        os.chmod(self.keyfile, 0o600)                            # as review-fp-key.py creates it
        # Docker is up for every test of this class: the pre-flight has its own class below.
        docker = mock.patch.object(L, "docker_problem", return_value=None)
        docker.start()
        self.addCleanup(docker.stop)

    def test_key_file_sets_cid_key_id(self):
        fake = mock.Mock(returncode=0, stdout=AUDIT, stderr="")
        with mock.patch.object(L.subprocess, "run", return_value=fake):
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                rc = L.main(["--customer", "1234567890", "--fp-key-file", self.keyfile])
        self.assertEqual(rc, 0)
        b = json.loads(buf.getvalue())
        self.assertEqual(b["cid_key_id"], R.key_id(bytes.fromhex(KEY_HEX)))
        self.assertEqual(b["cid_fingerprint"], "hmac-sha256/12")
        self.assertNotIn(KEY_HEX, buf.getvalue())

    def test_missing_or_bad_key_file_refuses(self):
        bad = os.path.join(self.tmp.name, "bad.key")
        with open(bad, "w") as f:
            f.write("nothex")
        os.chmod(bad, 0o600)                                     # refused for its content, not its mode
        for path in (os.path.join(self.tmp.name, "absent.key"), bad):
            err = io.StringIO()
            with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
                rc = L.main(["--customer", "1234567890", "--fp-key-file", path])
            self.assertEqual(rc, 2)
            self.assertIn("collect-review-evidence-laptop:", err.getvalue())

    def test_key_file_readable_by_group_or_other_refuses(self):
        fake = mock.Mock(returncode=0, stdout=AUDIT, stderr="")
        for mode in (0o640, 0o604, 0o660, 0o644, 0o610, 0o601, 0o602):
            os.chmod(self.keyfile, mode)
            out, err = io.StringIO(), io.StringIO()
            with mock.patch.object(L.subprocess, "run", return_value=fake) as run, \
                    contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                rc = L.main(["--customer", "1234567890", "--fp-key-file", self.keyfile])
            with self.subTest(mode=oct(mode)):
                self.assertEqual(rc, 2)
                self.assertEqual(out.getvalue(), "")
                self.assertEqual(len(err.getvalue().splitlines()), 1, err.getvalue())
                self.assertIn("collect-review-evidence-laptop:", err.getvalue())
                self.assertIn("0600", err.getvalue())
                self.assertNotIn(KEY_HEX, err.getvalue())
                run.assert_not_called()                          # refused before the audit runs
        for mode in (0o600, 0o400):                              # control: owner-only modes are used
            os.chmod(self.keyfile, mode)
            out = io.StringIO()
            with mock.patch.object(L.subprocess, "run", return_value=fake), contextlib.redirect_stdout(out):
                rc = L.main(["--customer", "1234567890", "--fp-key-file", self.keyfile])
            self.assertEqual(rc, 0, oct(mode))
            self.assertEqual(json.loads(out.getvalue())["cid_key_id"], R.key_id(bytes.fromhex(KEY_HEX)))

    def test_an_output_file_that_cannot_be_made_owner_only_gets_nothing_written(self):
        fake = mock.Mock(returncode=0, stdout=AUDIT, stderr="")
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.object(L.subprocess, "run", return_value=fake), \
                mock.patch.object(R, "restrict_output", return_value=False) as ro, \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = L.main(["--customer", "1234567890", "--fp-key-file", self.keyfile])
        self.assertEqual((rc, out.getvalue()), (2, ""))
        self.assertIn("owner-only", err.getvalue())
        ro.assert_called_once()

    def test_non_digit_customer_refused(self):
        buf = io.StringIO()
        with contextlib.redirect_stderr(buf):
            rc = L.main(["--customer", "12-34"])
        self.assertEqual(rc, 1)
        self.assertIn("must be digits", buf.getvalue())

    def test_access_digest_mode(self):
        fake = mock.Mock(returncode=0, stdout=AUDIT, stderr="")
        with mock.patch.object(L.subprocess, "run", return_value=fake):
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                rc = L.main(["--customer", "1234567890", "--access-digest"])
            self.assertEqual(rc, 0)
            printed = buf.getvalue().strip()
            expected = L.access_digest(L.parse_audit(AUDIT))
            self.assertEqual(printed, expected)

    def test_access_digest_mode_fails_on_nonzero_rc(self):
        fake = mock.Mock(returncode=3, stdout=AUDIT, stderr="")
        with mock.patch.object(L.subprocess, "run", return_value=fake):
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                rc = L.main(["--customer", "1234567890", "--access-digest"])
            self.assertEqual(rc, 2)

    def test_bundle_carries_collected_at_utc(self):
        fake = mock.Mock(returncode=0, stdout=AUDIT, stderr="")
        with mock.patch.object(L.subprocess, "run", return_value=fake):
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                L.main(["--customer", "1234567890", "--fp-key-file", self.keyfile])
        self.assertRegex(json.loads(buf.getvalue())["collected_at"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$")

    def test_package_items_need_all_three_args(self):
        # Review round 1, LC-R-1: one or two of the three is a usage error (exit 2), never a
        # bundle with D6.3 quietly could-not-check.
        fake = mock.Mock(returncode=0, stdout=AUDIT, stderr="")
        given = {"--package-project": "p", "--package-repo": "/r", "--package-commit": "a" * 40}
        import itertools
        for n in (1, 2):
            for names in itertools.combinations(given, n):
                args = [x for name in names for x in (name, given[name])]
                out, err = io.StringIO(), io.StringIO()
                with mock.patch.object(L.subprocess, "run", return_value=fake) as run, \
                        contextlib.redirect_stdout(out), contextlib.redirect_stderr(err), \
                        self.assertRaises(SystemExit) as cm:
                    L.main(["--customer", "1234567890", "--fp-key-file", self.keyfile, *args])
                with self.subTest(names=names):
                    self.assertEqual(cm.exception.code, 2)
                    self.assertEqual(out.getvalue(), "")
                    self.assertIn("--package-project, --package-repo and --package-commit", err.getvalue())
                    run.assert_not_called()

    def test_package_hash_reports_build_output(self):
        # Create a real temp git repo with registry
        repo = tempfile.mkdtemp()
        git(repo, "init", "-q")
        os.makedirs(os.path.join(repo, "code"))
        for rel, body in (("code/app.py", "app\n"), ("notes.md", "n\n")):
            with open(os.path.join(repo, rel), "w") as f:
                f.write(body)
        git(repo, "add", "-A")
        git(repo, "commit", "-qm", "c1")
        commit = git(repo, "rev-parse", "HEAD")

        # Create temp registry
        reg_dir = tempfile.mkdtemp()
        projects = os.path.join(reg_dir, "projects.yaml")
        with open(projects, "w") as f:
            f.write("""version: 1

projects:
  p:
    workdir: /projects/p
    mutate_execute:
      runner: /bin/true
      script_dir: code
      allow:
        - app
    package:
      include:
        - notes.md
""")

        # Call package_hash with temp registry
        result = L.package_hash("p", repo, commit, projects)

        # Get expected result by calling build directly
        expected = B.build("p", repo, commit, projects, tempfile.mkdtemp())

        # Assert they match
        self.assertEqual(result["project"], "p")
        self.assertEqual(result["commit"], commit)
        self.assertEqual(result["sha256"], expected["sha256"])
        self.assertEqual(result["files"], expected["files"])

    def test_package_hash_cleans_up_its_scratch_directory(self):
        # E2: package_hash must not leak the scratch dir build() writes the .tar and
        # .manifest.json into — it exists only long enough to hash them.
        repo = tempfile.mkdtemp()
        git(repo, "init", "-q")
        os.makedirs(os.path.join(repo, "code"))
        for rel, body in (("code/app.py", "app\n"), ("notes.md", "n\n")):
            with open(os.path.join(repo, rel), "w") as f:
                f.write(body)
        git(repo, "add", "-A")
        git(repo, "commit", "-qm", "c1")
        commit = git(repo, "rev-parse", "HEAD")

        reg_dir = tempfile.mkdtemp()
        projects = os.path.join(reg_dir, "projects.yaml")
        with open(projects, "w") as f:
            f.write("""version: 1

projects:
  p:
    workdir: /projects/p
    mutate_execute:
      runner: /bin/true
      script_dir: code
      allow:
        - app
    package:
      include:
        - notes.md
""")

        captured = {}
        real_td = L.tempfile.TemporaryDirectory

        class SpyTD(real_td):
            def __enter__(inner_self):
                path = super().__enter__()
                captured["path"] = path
                return path

        with mock.patch.object(L.tempfile, "TemporaryDirectory", SpyTD):
            L.package_hash("p", repo, commit, projects)

        self.assertIn("path", captured)                          # control: it was used
        self.assertFalse(os.path.exists(captured["path"]))


CID = "1234567890"
# What the audit leaves with Docker Desktop off (audit-credential-access.sh --all): its own
# separator lines on stdout, no document, and `docker compose`'s refusal on stderr. The stderr
# here carries a customer id on purpose: nothing of it may reach any output.
NO_DOCS_STDOUT = "===== .env.ga =====\n===== .env.gaw =====\n"
NO_DOCS_STDERR = (f"Cannot connect to the Docker daemon at unix:///x/docker.sock. Is the docker daemon running?\n"
                  f"Request made: ClientCustomerId: {CID} STDERR-MARKER\n")


class TestDockerProblem(unittest.TestCase):
    """docker_problem(): the pre-flight itself, with subprocess faked (no real Docker)."""

    def test_reachable_daemon_is_no_problem_and_the_check_prints_nothing(self):
        with mock.patch.object(L.subprocess, "run", return_value=mock.Mock(returncode=0)) as run:
            self.assertIsNone(L.docker_problem())
        run.assert_called_once()
        args, kw = run.call_args
        self.assertEqual(args[0], ["docker", "info"])
        for stream in ("stdin", "stdout", "stderr"):           # nothing of Docker's own output is shown
            self.assertIs(kw.get(stream), L.subprocess.DEVNULL, stream)
        self.assertEqual(kw.get("timeout"), L.DOCKER_INFO_TIMEOUT)
        self.assertLessEqual(L.DOCKER_INFO_TIMEOUT, 30)          # short: the pre-flight must not hang

    def test_unreachable_daemon_says_docker_is_not_running(self):
        with mock.patch.object(L.subprocess, "run", return_value=mock.Mock(returncode=1)):
            self.assertEqual(L.docker_problem(), "Docker is not running")

    def test_missing_docker_command_and_a_hang_are_problems(self):
        with mock.patch.object(L.subprocess, "run", side_effect=FileNotFoundError("docker")):
            self.assertIn("not found", L.docker_problem())
        with mock.patch.object(L.subprocess, "run",
                               side_effect=L.subprocess.TimeoutExpired(["docker", "info"], L.DOCKER_INFO_TIMEOUT)):
            self.assertIn("did not answer", L.docker_problem())
        with mock.patch.object(L.subprocess, "run", side_effect=PermissionError("docker")):
            self.assertIsNotNone(L.docker_problem())


class TestLoudFailures(unittest.TestCase):
    """The 2026-10-14 trap: Docker Desktop off, D3.1 could-not-check, and the collector exited 0."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.keyfile = os.path.join(self.tmp.name, "fp.key")
        with open(self.keyfile, "w") as f:
            f.write(KEY_HEX + "\n")
        os.chmod(self.keyfile, 0o600)

    def _main(self, argv, docker=None, audit=None):
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.object(L, "docker_problem", return_value=docker) as dp, \
                mock.patch.object(L.subprocess, "run", return_value=audit) as run, \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = L.main(argv)
        return rc, out.getvalue(), err.getvalue(), dp, run

    def _assert_nothing_sensitive(self, *texts):
        for text in texts:
            self.assertNotIn(CID, text)
            self.assertNotIn("STDERR-MARKER", text)
            self.assertNotIn("Cannot connect", text)               # the audit's stderr is never relayed
            self.assertNotIn(KEY_HEX, text)

    def test_exit_codes_are_distinct_from_the_existing_ones(self):
        codes = {L.EXIT_DOCKER_DOWN, L.EXIT_INCOMPLETE}
        self.assertEqual(len(codes), 2)
        self.assertFalse(codes & {0, 1, 2})                      # 1 bad --customer, 2 key/output/argparse

    def test_docker_down_refuses_before_the_audit_and_writes_no_bundle(self):
        rc, out, err, dp, run = self._main(["--customer", CID, "--fp-key-file", self.keyfile],
                                           docker="Docker is not running")
        self.assertEqual(rc, L.EXIT_DOCKER_DOWN)
        self.assertEqual(out, "")                                # no bundle: nothing to set aside
        self.assertEqual(len(err.splitlines()), 1, err)
        self.assertIn("collect-review-evidence-laptop:", err)
        self.assertIn("Docker is not running: start Docker Desktop, then re-run", err)
        dp.assert_called_once()
        run.assert_not_called()                                  # the audit never ran
        self._assert_nothing_sensitive(out, err)

    def test_the_review_key_is_checked_before_docker(self):
        rc, out, err, dp, run = self._main(["--customer", CID, "--fp-key-file",
                                            os.path.join(self.tmp.name, "absent.key")],
                                           docker="Docker is not running")
        self.assertEqual(rc, 2)
        dp.assert_not_called()

    def test_docker_up_but_no_audit_documents_writes_the_bundle_and_fails_loudly(self):
        fake = mock.Mock(returncode=1, stdout=NO_DOCS_STDOUT, stderr=NO_DOCS_STDERR)
        rc, out, err, dp, run = self._main(["--customer", CID, "--fp-key-file", self.keyfile], audit=fake)
        self.assertEqual(rc, L.EXIT_INCOMPLETE)
        bundle = json.loads(out)                                 # still written: it is the evidence
        self.assertEqual(bundle["items"]["D3.1"]["status"], R.COULD_NOT_CHECK)
        self.assertEqual(bundle["items"]["D3.1"]["data"]["rc"], 1)
        self.assertEqual(bundle["items"]["D3.1"]["data"]["stderr_lines_discarded"], 2)
        self.assertEqual(len(err.splitlines()), 1, err)
        self.assertIn("D3.1 could not be checked: no audit documents in the output", err)
        self.assertIn("the bundle is incomplete", err)
        self.assertIn("exited 1", err)
        # LC-R-4: the pre-flight just found Docker up, so the line points elsewhere.
        self.assertNotIn("Docker Desktop", err)
        self.assertIn(".env.ga", err)
        self.assertIn("docker compose", err)
        self._assert_nothing_sensitive(out, err)

    def _package_args(self):
        return ["--package-project", "p", "--package-repo", "/Users/someone/Projects/ads-repo",
                "--package-commit", "a" * 40]

    def test_package_build_failure_writes_the_bundle_and_exits_incomplete(self):
        fake = mock.Mock(returncode=0, stdout=AUDIT, stderr="")
        cases = (
            (ValueError("/Users/someone/Projects/ads-repo HEAD is 0123456789ab, not aaaaaaaaaaaa — check out "
                        "the verified commit first"), "the package repository is not checked out at --package-commit"),
            (ValueError("git rev-parse HEAD failed: fatal: not a git repository: /Users/someone/Projects/ads-repo"),
             "a git command in the package repository failed"),
            (ValueError("tracked files are modified — refusing; the package must equal the commit"),
             "tracked files are modified in the package repository"),
            (ValueError("refusing to package docs holding a customer-id-shaped number: ['/Users/someone/x.md']"),
             "a packaged doc holds a customer-id-shaped number"),
            (ValueError("--commit must be a full 40-hex commit sha"),
             "--package-commit is not a full 40-hex commit sha"),
            (OSError("[Errno 2] No such file or directory: '/Users/someone/Projects/ads-repo/registry'"),
             "the package build failed"),
            (ValueError("something new about /Users/someone"), "the package build failed"),
        )
        for exc, reason in cases:
            with self.subTest(exc=str(exc)), mock.patch.object(L, "package_hash", side_effect=exc):
                rc, out, err, dp, run = self._main(["--customer", CID, "--fp-key-file", self.keyfile,
                                                    *self._package_args()], audit=fake)
                self.assertEqual(rc, L.EXIT_INCOMPLETE)
                bundle = json.loads(out)                         # written: D3.1 is good evidence
                self.assertEqual(bundle["items"]["D3.1"]["status"], R.OBSERVED)
                self.assertEqual(bundle["items"]["D6.3"], {"status": R.COULD_NOT_CHECK, "reason": reason})
                self.assertEqual(len(err.splitlines()), 1, err)
                self.assertIn(f"D6.3 could not be checked: the package build failed: {reason}", err)
                self.assertIn("the bundle is incomplete", err)
                for text in (out, err):                          # never str(e): no path reaches the reviewer
                    self.assertNotIn("/Users/someone", text)
                    self.assertNotIn("fatal:", text)
                self._assert_nothing_sensitive(out, err)

    def test_package_build_success_exits_zero(self):
        fake = mock.Mock(returncode=0, stdout=AUDIT, stderr="")
        data = {"project": "p", "commit": "a" * 40, "sha256": "f" * 64, "files": 2}
        with mock.patch.object(L, "package_hash", return_value=data):
            rc, out, err, dp, run = self._main(["--customer", CID, "--fp-key-file", self.keyfile,
                                                *self._package_args()], audit=fake)
        self.assertEqual((rc, err), (0, ""))
        self.assertEqual(json.loads(out)["items"]["D6.3"], {"status": R.OBSERVED, "data": data})

    def test_d3_1_and_d6_3_both_incomplete_say_both(self):
        fake = mock.Mock(returncode=1, stdout=NO_DOCS_STDOUT, stderr=NO_DOCS_STDERR)
        with mock.patch.object(L, "package_hash", side_effect=ValueError("tracked files are modified — refusing")):
            rc, out, err, dp, run = self._main(["--customer", CID, "--fp-key-file", self.keyfile,
                                                *self._package_args()], audit=fake)
        self.assertEqual(rc, L.EXIT_INCOMPLETE)
        self.assertEqual(len(err.splitlines()), 2, err)
        self.assertIn("D3.1 could not be checked", err)
        self.assertIn("D6.3 could not be checked", err)
        self._assert_nothing_sensitive(out, err)

    def test_every_message_names_the_program(self):
        # LC-R-8: one spelling for the prefix, from PROG.
        with open(os.path.join(HERE, "collect-review-evidence-laptop.py"), encoding="utf-8") as f:
            src = f.read()
        self.assertEqual(L.PROG, "collect-review-evidence-laptop")
        self.assertNotIn('"collect-review-evidence-laptop:', src)
        self.assertNotIn("'collect-review-evidence-laptop:", src)

    def test_normal_path_is_unchanged(self):
        fake = mock.Mock(returncode=0, stdout=AUDIT, stderr=f"Request made: ClientCustomerId: {CID} STDERR-MARKER\n")
        rc, out, err, dp, run = self._main(["--customer", CID, "--fp-key-file", self.keyfile], audit=fake)
        self.assertEqual((rc, err), (0, ""))
        bundle = json.loads(out)
        self.assertEqual(bundle["items"]["D3.1"]["status"], R.OBSERVED)
        self.assertEqual(bundle["items"]["D3.1"]["data"]["digest"], L.access_digest(L.parse_audit(AUDIT)))
        # D6.3 without ANY --package-* argument stays could-not-check and does NOT fail the run
        # (a documented mode: the docstring and BRING-UP say so).
        self.assertEqual(bundle["items"]["D6.3"], {"status": R.COULD_NOT_CHECK, "reason": "no --package-* arguments"})
        dp.assert_called_once()
        run.assert_called_once()
        self._assert_nothing_sensitive(out, err)

    def test_access_digest_docker_down(self):
        rc, out, err, dp, run = self._main(["--customer", CID, "--access-digest"], docker="Docker is not running")
        self.assertEqual(rc, 2)                                  # the digest mode's contract: 0 or 2
        self.assertEqual(out.strip(), R.COULD_NOT_CHECK)
        self.assertEqual(len(err.splitlines()), 1, err)
        self.assertIn("Docker is not running: start Docker Desktop, then re-run", err)
        run.assert_not_called()
        self._assert_nothing_sensitive(out, err)

    def test_access_digest_docker_up_but_no_documents(self):
        fake = mock.Mock(returncode=1, stdout=NO_DOCS_STDOUT, stderr=NO_DOCS_STDERR)
        rc, out, err, dp, run = self._main(["--customer", CID, "--access-digest"], audit=fake)
        self.assertEqual(rc, 2)
        self.assertEqual(out.strip(), R.COULD_NOT_CHECK)
        self.assertEqual(len(err.splitlines()), 1, err)
        self.assertIn("no access digest", err)
        self.assertIn("D3.1 could not be checked: no audit documents in the output", err)
        self._assert_nothing_sensitive(out, err)

    def test_access_digest_nonzero_audit_rc_says_why(self):
        fake = mock.Mock(returncode=3, stdout=AUDIT, stderr=NO_DOCS_STDERR)
        rc, out, err, dp, run = self._main(["--customer", CID, "--access-digest"], audit=fake)
        self.assertEqual(rc, 2)
        self.assertEqual(out.strip(), L.access_digest(L.parse_audit(AUDIT)))   # stdout as before
        self.assertEqual(len(err.splitlines()), 1, err)
        self.assertIn("exited 3", err)
        self._assert_nothing_sensitive(out, err)

    def test_access_digest_normal_path_prints_nothing_on_stderr(self):
        fake = mock.Mock(returncode=0, stdout=AUDIT, stderr=NO_DOCS_STDERR)
        rc, out, err, dp, run = self._main(["--customer", CID, "--access-digest"], audit=fake)
        self.assertEqual((rc, err), (0, ""))
        self.assertEqual(out.strip(), L.access_digest(L.parse_audit(AUDIT)))


class TestRunbookNamesTheExitCodes(unittest.TestCase):
    """BRING-UP's laptop collection step and the module docstring must state what the code does:
    the 2026-10-14 runbook text said the collector 'still ends with exit code 0'."""

    def _laptop_step(self):
        """Step 4 of the review collection: its "4. Laptop:" line and the D3.1 line after it."""
        with open(os.path.join(os.path.dirname(HERE), "deploy", "BRING-UP.md"), encoding="utf-8") as f:
            text = f.read()
        anchor = "D3.1 runs the credential audit in a Docker container ON THE LAPTOP"
        self.assertIn(anchor, text)
        at = text.index(anchor)
        start = text.rindex("\n4. Laptop: ", 0, at) + 1
        return text[start:text.index("\n", at)]

    def test_bring_up_laptop_step(self):
        step = self._laptop_step()
        self.assertNotIn("still ends with exit code 0", step)
        for code in (1, 2, L.EXIT_DOCKER_DOWN, L.EXIT_INCOMPLETE):
            self.assertIn(f"exit code {code}", step)
        self.assertIn("D6.3", step)

    def test_bring_up_laptop_step_runs_the_collector_with_python3_and_shows_its_rc(self):
        # LC-R-2: the file is 100644, so `bin/collect-review-evidence-laptop.py` alone is rc 126.
        # LC-R-6: the step shows the collector's exit code in a fixed form.
        step = self._laptop_step()
        self.assertIn("`python3 bin/collect-review-evidence-laptop.py --customer", step)
        self.assertNotRegex(step, r"(?<!python3 )bin/collect-review-evidence-laptop\.py")
        self.assertIn('echo "collector_rc=$?"', step)
        self.assertIn("`collector_rc=0`", step)

    def test_module_docstring(self):
        for code in (1, 2, L.EXIT_DOCKER_DOWN, L.EXIT_INCOMPLETE):
            self.assertIn(f"exit {code}", L.__doc__)
        self.assertIn("D6.3", L.__doc__)


if __name__ == "__main__":
    unittest.main()
