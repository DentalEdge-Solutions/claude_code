import importlib.util, io, json, os, sys, tempfile, unittest, contextlib

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import spool_lib as S


def _load(name, filename):
    spec = importlib.util.spec_from_file_location(name, os.path.join(HERE, filename))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


K = _load("hermes_syscall", "hermes-syscall.py")


class Base(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        self._saved = os.environ.get("HERMES_SPOOL_ROOT")
        os.environ["HERMES_SPOOL_ROOT"] = self.root

    def tearDown(self):
        os.environ.pop("HERMES_SPOOL_ROOT", None)
        if self._saved is not None:
            os.environ["HERMES_SPOOL_ROOT"] = self._saved

    def run_cli(self, argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = K.main(argv)
        return rc, out.getvalue(), err.getvalue()


class TestApply(Base):
    def test_writes_a_request_the_spool_validator_accepts(self):
        rc, out, _ = self.run_cli(["apply", "--client", "pilot-1",
                                   "--changeset", "20260824-101500-abcdef01"])
        self.assertEqual(rc, 0)
        rid = out.strip()
        p = S.request_path(rid, self.root)
        # The client and the broker must agree on what a request is. Round-tripping
        # through the BROKER's validator is the only check that proves they do.
        got = S.load_request(p)
        self.assertEqual(got["op"], "apply")
        self.assertEqual(got["client"], "pilot-1")
        self.assertEqual(set(got), set(S.REQUEST_KEYS))

    def test_each_call_gets_a_fresh_request_id(self):
        rids = {self.run_cli(["apply", "--client", "pilot-1",
                              "--changeset", "20260824-101500-abcdef01"])[1].strip()
                for _ in range(5)}
        self.assertEqual(len(rids), 5)

    def test_no_partial_file_is_ever_visible_to_the_broker(self):
        self.run_cli(["apply", "--client", "pilot-1",
                      "--changeset", "20260824-101500-abcdef01"])
        names = os.listdir(S.requests_dir(self.root))
        # Exactly one visible request; any temp file must be dot-prefixed so the
        # broker's FILENAME_RE scan cannot pick up a half-written request.
        visible = [n for n in names if not n.startswith(".")]
        self.assertEqual(len(visible), 1)
        self.assertTrue(S.FILENAME_RE.fullmatch(visible[0]))

    def test_bad_slug_is_refused_client_side_without_writing_anything(self):
        rc, _, err = self.run_cli(["apply", "--client", "../etc",
                                   "--changeset", "20260824-101500-abcdef01"])
        self.assertEqual(rc, 1)
        self.assertFalse(os.path.isdir(S.requests_dir(self.root))
                         and os.listdir(S.requests_dir(self.root)))
        self.assertIn("client", err)

    def test_undo_is_not_a_subcommand(self):
        rc, _, _ = self.run_cli(["undo", "--client", "pilot-1",
                                 "--changeset", "20260824-101500-abcdef01"])
        self.assertNotEqual(rc, 0)


class TestResult(Base):
    RID = "0f9c1a2b-3d4e-4f50-8a1b-2c3d4e5f6071"

    def _result(self, payload):
        S.write_result(self.RID, payload, self.root)

    def test_missing_result_is_pending_not_refused(self):
        # "No data" and "zero data" are different events; file EXISTENCE is the
        # discriminator. Collapsing these two would let a model read a pending
        # request as a refusal, or worse, a refusal as pending and retry it.
        rc, out, _ = self.run_cli(["result", "--request-id", self.RID])
        self.assertEqual(rc, 4)
        self.assertIn("pending", out.lower())

    def test_applied_result_exits_zero(self):
        self._result({"status": "applied", "classification": "accepted_applied",
                      "exit_code": 0})
        rc, _, _ = self.run_cli(["result", "--request-id", self.RID])
        self.assertEqual(rc, 0)

    def test_refusal_exits_two_and_is_not_rendered_as_retryable(self):
        self._result({"status": "refused", "classification": "refused_preflight",
                      "exit_code": 2, "detail": "guard 1: mutation is disabled"})
        rc, out, _ = self.run_cli(["result", "--request-id", self.RID])
        self.assertEqual(rc, 2)
        low = out.lower()
        self.assertIn("refused", low)
        # A model that retries a refusal is a model applying pressure to a guard.
        for word in ("retry", "try again", "temporar", "transient"):
            self.assertNotIn(word, low)

    def test_failure_after_mutation_is_its_own_exit_code(self):
        self._result({"status": "failed", "classification": "failed_after_mutation",
                      "exit_code": 3})
        rc, _, _ = self.run_cli(["result", "--request-id", self.RID])
        self.assertEqual(rc, 3)

    def test_classification_is_surfaced_verbatim(self):
        self._result({"status": "refused", "classification": "refused_quota",
                      "exit_code": 2})
        _, out, _ = self.run_cli(["result", "--request-id", self.RID])
        self.assertIn("refused_quota", out)


if __name__ == "__main__":
    unittest.main()
