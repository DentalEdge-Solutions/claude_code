import contextlib, datetime, hashlib, importlib.util, io, json, os, subprocess, sys, tempfile, unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import changeset_lib as C

def _load(name, filename):
    spec = importlib.util.spec_from_file_location(name, os.path.join(HERE, filename))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

P = _load("propose_changeset", "propose-changeset.py")
A = _load("approve_changeset", "approve-changeset.py")
NOW = datetime.datetime(2026, 8, 12, 10, 15, 0, tzinfo=datetime.timezone.utc)
CID = "20260824-101500-abcdef01"

REG = """version: 1

projects:
  claude_google_ads:
    workdir: /projects/claude_google_ads
    mutate_execute:
      runner: /opt/ads-venv/bin/python3
      script_dir: code
      allow:
        - mutate_campaign_negative
      caps:
        actions_per_changeset: 25
        actions_per_client_day: 100
        applies_per_client_day: 5
        approval_ttl_hours: 24
"""

class T(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        os.environ["VAULT_ROOT"] = self.tmp
        os.environ["HERMES_GOVERNANCE_ROOT"] = self.tmp
        d = os.path.join(self.tmp, "_registry"); os.makedirs(d)
        self.clients = os.path.join(d, "clients.json")
        with open(self.clients, "w") as f:
            json.dump({"clients": {"acme-dental": {
                "project": "claude_google_ads", "customer_id": "1234567890",
                "status": "active"}}}, f)
        self.projects = os.path.join(self.tmp, "projects.yaml")
        with open(self.projects, "w") as f:
            f.write(REG)
        src = os.path.join(self.tmp, "in.json")
        with open(src, "w") as f:
            json.dump({"actions": [{"type": "add_campaign_negative",
                                    "campaign_id": "22233344455",
                                    "keyword": "free consultation",
                                    "match_type": "PHRASE"}]}, f)
        self.cs = P.propose("acme-dental", src, NOW, registry=self.clients, projects=self.projects)
        self.vault = os.path.join(self.tmp, "acme-dental")

    def _digest(self):
        return C.file_digest(C.changeset_path(self.vault, self.cs["changeset_id"]))

    def test_approval_records_digest_and_expiry(self):
        rec = A.approve("acme-dental", self.cs["changeset_id"], "erick", NOW,
                        registry=self.clients, projects=self.projects,
                        expect_sha256=self._digest())
        self.assertEqual(rec["sha256"],
                         C.file_digest(C.changeset_path(self.vault, self.cs["changeset_id"])))
        self.assertEqual(rec["expires_at"], "2026-08-13T10:15:00Z")

    def test_approval_verifies_after_write(self):
        A.approve("acme-dental", self.cs["changeset_id"], "erick", NOW,
                  registry=self.clients, projects=self.projects,
                  expect_sha256=self._digest())
        digest = C.file_digest(C.changeset_path(self.vault, self.cs["changeset_id"]))
        self.assertEqual(
            C.verify_approval("acme-dental", self.cs["changeset_id"], digest, NOW)["operator"], "erick")

    def test_tampered_changeset_refused_at_approve(self):
        p = C.changeset_path(self.vault, self.cs["changeset_id"])
        with open(p, "w") as f:
            json.dump({"changeset_id": self.cs["changeset_id"], "client": "acme-dental",
                       "project": "claude_google_ads", "customer_id": "1234567890",
                       "created_at": "2026-08-12T10:15:00Z",
                       "actions": [{"type": "set_campaign_budget", "campaign_id": "1",
                                    "keyword": "x", "match_type": "PHRASE"}]}, f)
        with self.assertRaises(ValueError):
            A.approve("acme-dental", self.cs["changeset_id"], "erick", NOW,
                      registry=self.clients, projects=self.projects)

    def test_missing_changeset_refused(self):
        with self.assertRaises(ValueError):
            A.approve("acme-dental", "20260812-999999-deadbeef", "erick", NOW,
                      registry=self.clients, projects=self.projects)

    def test_bad_changeset_id_refused(self):
        with self.assertRaises(ValueError):
            A.approve("acme-dental", "../../etc/passwd", "erick", NOW,
                      registry=self.clients, projects=self.projects)

    def test_bad_operator_refused(self):
        # Supplies a matching --expect-sha256 so the failure exercised here is the
        # operator-format check, not the (now default) missing-confirmation refusal.
        with self.assertRaises(ValueError):
            A.approve("acme-dental", self.cs["changeset_id"], "rm -rf /", NOW,
                      registry=self.clients, projects=self.projects,
                      expect_sha256=self._digest())

    def test_cli_success_exit0(self):
        out = subprocess.run(
            [sys.executable, os.path.join(HERE, "approve-changeset.py"),
             "--client", "acme-dental", "--changeset", self.cs["changeset_id"],
             "--operator", "erick", "--registry", self.clients, "--projects", self.projects,
             "--expect-sha256", self._digest()],
            capture_output=True, text=True, env={**os.environ})
        self.assertEqual(out.returncode, 0)

    def test_cli_bad_operator_exit2(self):
        # Supplies a matching --expect-sha256 so exit 2 here is provably caused by the
        # bad operator, not by the (now default) missing-confirmation refusal.
        out = subprocess.run(
            [sys.executable, os.path.join(HERE, "approve-changeset.py"),
             "--client", "acme-dental", "--changeset", self.cs["changeset_id"],
             "--operator", "a b", "--registry", self.clients, "--projects", self.projects,
             "--expect-sha256", self._digest()],
            capture_output=True, text=True, env={**os.environ})
        self.assertEqual(out.returncode, 2)

class TestOperatorCanSeeWhatIsBound(T):
    """I3 (final whole-branch review). The snapshot closes approve -> apply, not
    review -> approve: approve binds whatever the vault holds AT APPROVE TIME. The only
    defence against that residual window is the operator being able to see what they
    are binding — so the digest and the per-action summary are load-bearing output, not
    decoration."""

    def _cli(self, *extra):
        return subprocess.run(
            [sys.executable, os.path.join(HERE, "approve-changeset.py"),
             "--client", "acme-dental", "--changeset", self.cs["changeset_id"],
             "--operator", "erick", "--registry", self.clients,
             "--projects", self.projects, *extra],
            capture_output=True, text=True, env={**os.environ})

    def _digest(self):
        return C.file_digest(C.changeset_path(self.vault, self.cs["changeset_id"]))

    def test_cli_prints_the_digest_and_one_line_per_action(self):
        out = self._cli("--expect-sha256", self._digest())
        self.assertEqual(out.returncode, 0)
        self.assertIn(self._digest(), out.stdout)
        self.assertIn("1 action(s) bound by this approval", out.stdout)
        self.assertIn("add_campaign_negative", out.stdout)
        self.assertIn("22233344455", out.stdout)

    def test_expect_sha256_matching_is_accepted(self):
        """CONTROL for the refusal below: the same flag with the RIGHT digest must
        approve normally, or the refusal only proves the flag rejects everything."""
        out = self._cli("--expect-sha256", self._digest())
        self.assertEqual(out.returncode, 0)
        self.assertTrue(os.path.isfile(C.approval_path("acme-dental",
                                                       self.cs["changeset_id"])))

    def test_expect_sha256_mismatch_refuses_and_writes_no_approval(self):
        out = self._cli("--expect-sha256", "0" * 64)
        self.assertEqual(out.returncode, 2)
        self.assertIn("--expect-sha256 mismatch", out.stderr)
        self.assertFalse(os.path.exists(C.approval_path("acme-dental",
                                                        self.cs["changeset_id"])))
        self.assertFalse(os.path.exists(C.snapshot_path("acme-dental",
                                                        self.cs["changeset_id"])))

    def test_expect_sha256_that_is_not_a_digest_refuses(self):
        out = self._cli("--expect-sha256", "not-a-digest")
        self.assertEqual(out.returncode, 2)
        self.assertIn("invalid --expect-sha256", out.stderr)

    def test_the_summary_describes_the_bytes_that_were_snapshotted(self):
        """Deferred minor #3: approve used to read the file twice — validate read #1,
        snapshot read #2. It now reads once, so the digest printed, the actions listed
        and the bytes in the governance store are provably the same content. Asserted
        by comparing all three against each other rather than against the vault file,
        which is the copy that could have changed between reads.
        """
        rec = A.approve("acme-dental", self.cs["changeset_id"], "erick", NOW,
                        registry=self.clients, projects=self.projects,
                        expect_sha256=self._digest())
        with open(C.snapshot_path("acme-dental", self.cs["changeset_id"]), "rb") as f:
            snap = f.read()
        self.assertEqual(rec["sha256"], hashlib.sha256(snap).hexdigest())
        self.assertEqual(rec["actions"], json.loads(snap.decode("utf-8"))["actions"])
        self.assertIn(rec["sha256"], A.summarise(rec))


class TestExpectShaIsRequired(T):
    """Task 9: --expect-sha256 is now the DEFAULT path. Omitting it must refuse — but
    the refusal is a workflow step (it prints the digest and the action summary the
    operator needs to build a paste-ready re-run), not a bare rejection. This does not
    close review -> approve structurally: an operator who pastes the digest back
    without reading the summary above it has confirmed nothing. See the module
    docstring and ExpectShaRequired's docstring in approve-changeset.py."""

    def _cli(self, *extra):
        return subprocess.run(
            [sys.executable, os.path.join(HERE, "approve-changeset.py"),
             "--client", "acme-dental", "--changeset", self.cs["changeset_id"],
             "--operator", "erick", "--registry", self.clients,
             "--projects", self.projects, *extra],
            capture_output=True, text=True, env={**os.environ})

    def test_approving_without_expect_sha256_refuses_and_prints_the_digest(self):
        out = self._cli()
        self.assertEqual(out.returncode, 2)
        text = out.stdout + out.stderr
        self.assertIn("--expect-sha256", text)
        self.assertIn(self._digest(), text)      # paste-ready
        self.assertIn("action(s)", text)          # and the summary to read

    def test_no_approval_record_or_snapshot_is_written_by_the_refusing_call(self):
        self._cli()
        self.assertFalse(os.path.isfile(
            C.approval_path("acme-dental", self.cs["changeset_id"])))
        self.assertFalse(os.path.isfile(
            C.snapshot_path("acme-dental", self.cs["changeset_id"])))

    def test_control_supplying_the_digest_approves(self):
        # The must-SUCCEED control: the new refusal must not have broken approval.
        out = self._cli("--expect-sha256", self._digest())
        self.assertEqual(out.returncode, 0)
        self.assertTrue(os.path.isfile(
            C.approval_path("acme-dental", self.cs["changeset_id"])))

    def test_a_wrong_digest_still_refuses(self):
        out = self._cli("--expect-sha256", "b" * 64)
        self.assertEqual(out.returncode, 2)
        self.assertIn("mismatch", out.stderr)


class TestRootRequirement(unittest.TestCase):
    """F12 (spec 2.3): on Linux the proposal lives in the gateway-owned vault (data/ is
    700 uid 10000), so reading it needs root; and a non-root writer leaves artifacts the
    broker cannot reserve. Refusing up front beats failing hours later at apply time,
    where it would look like a governance refusal rather than a setup mistake."""

    def setUp(self):
        # Own tmp dir, deliberately with NO client registry written into it: the
        # darwin control test is expected to fail later for that unrelated reason —
        # it asserts only that the ROOT refusal specifically did not fire.
        self.tmp = tempfile.mkdtemp()
        os.environ["VAULT_ROOT"] = self.tmp
        os.environ["HERMES_GOVERNANCE_ROOT"] = self.tmp

    def test_it_refuses_without_root_on_linux(self):
        with mock.patch.object(A.sys, "platform", "linux"), \
             mock.patch.object(A.os, "geteuid", return_value=1000):
            err = io.StringIO()
            with contextlib.redirect_stderr(err):
                rc = A.main(["--client", "acme-dental", "--changeset", CID,
                             "--operator", "operator"])
        self.assertEqual(rc, 2)
        self.assertIn("sudo", err.getvalue())

    def test_control_it_does_not_refuse_on_darwin(self):
        """The dev flow on a laptop has no uid separation to honour. This call fails
        anyway (no client registry set up in this test's tmp dir) — that failure is
        expected and irrelevant; only the ROOT-refusal message is asserted absent."""
        with mock.patch.object(A.sys, "platform", "darwin"), \
             mock.patch.object(A.os, "geteuid", return_value=1000):
            err = io.StringIO()
            with contextlib.redirect_stderr(err):
                rc = A.main(["--client", "acme-dental", "--changeset", CID,
                             "--operator", "operator"])
        self.assertNotIn("must run as root", err.getvalue())


if __name__ == "__main__":
    unittest.main()
