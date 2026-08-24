import contextlib, errno, importlib.util, io, json, os, sys, tempfile, unittest

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
        # Post-rename: after a real, unpatched submit(), exactly one visible
        # request exists and it DOES match the broker's FILENAME_RE.
        self.run_cli(["apply", "--client", "pilot-1",
                      "--changeset", "20260824-101500-abcdef01"])
        names = os.listdir(S.requests_dir(self.root))
        visible = [n for n in names if not n.startswith(".")]
        self.assertEqual(len(visible), 1)
        self.assertTrue(S.FILENAME_RE.fullmatch(visible[0]))

        # Mid-write: os.replace() is synchronous within submit(), so a real call
        # never leaves anything to observe mid-flight — the property that actually
        # matters (a broker scanning DURING a write picks up nothing) can only be
        # proven by holding the write open. Patch os.replace, as seen by the
        # hermes-syscall module, to a no-op for one submit() call, so the temp
        # file is left in place instead of being renamed over the final path. Use
        # a fresh spool root so this half of the test isn't sharing a directory
        # with the real file written above.
        mid_root = tempfile.mkdtemp()
        real_replace = K.os.replace
        K.os.replace = lambda *a, **kw: None
        try:
            K.submit("pilot-2", "20260824-101500-abcdef02", mid_root)
        finally:
            K.os.replace = real_replace

        mid_names = os.listdir(S.requests_dir(mid_root))
        # Positive control: the temp file is really there — the patch took
        # effect, so the next assertion is not vacuously true over an empty dir.
        self.assertGreaterEqual(len(mid_names), 1)
        # The property that matters: while a request is mid-write, nothing in
        # requests/ matches FILENAME_RE — a broker scanning at that instant
        # picks up nothing.
        self.assertFalse(any(S.FILENAME_RE.fullmatch(n) for n in mid_names))

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

    def test_invalid_utf8_result_is_refused_without_leaking_raw_exception_text(self):
        # results/ lives inside the spool, which Hermes can write to. A planted
        # unreadable result must not leak raw codec/OS text into model-facing
        # output, because that text can carry retry-flavoured wording.
        path = S.result_path(self.RID, self.root)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as f:
            f.write(b"\xff\xfe not valid utf-8")
        rc, out, _ = self.run_cli(["result", "--request-id", self.RID])
        self.assertEqual(rc, 2)
        low = out.lower()
        for word in ("retry", "try again", "temporar", "transient"):
            self.assertNotIn(word, low)
        # Positive control: the unreadable-result branch was actually taken, not
        # merely silent — this must not pass by rendering nothing at all.
        self.assertIn("result_unreadable", out)

    def test_malformed_json_result_is_refused_without_leaking_raw_exception_text(self):
        path = S.result_path(self.RID, self.root)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write("{not valid json")
        rc, out, _ = self.run_cli(["result", "--request-id", self.RID])
        self.assertEqual(rc, 2)
        low = out.lower()
        for word in ("retry", "try again", "temporar", "transient"):
            self.assertNotIn(word, low)
        self.assertIn("result_unreadable", out)

    def test_os_error_reading_result_does_not_leak_retry_flavoured_text(self):
        # The concrete adversarial trigger: an OSError whose strerror is itself
        # retry-flavoured. errno EAGAIN renders as "Resource temporarily
        # unavailable" — a raw '%s' % e interpolation of that text would put
        # "temporar" directly into exit-2 output. Force exactly that by
        # monkeypatching the module-global `open` that fetch() resolves to.
        path = S.result_path(self.RID, self.root)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write('{"status": "applied"}')

        def _raise_eagain(*a, **kw):
            raise OSError(errno.EAGAIN, os.strerror(errno.EAGAIN))

        K.open = _raise_eagain
        try:
            rc, out, _ = self.run_cli(["result", "--request-id", self.RID])
        finally:
            del K.open  # restore fallback to the builtin

        self.assertEqual(rc, 2)
        low = out.lower()
        for word in ("retry", "try again", "temporar", "transient"):
            self.assertNotIn(word, low)
        self.assertIn("result_unreadable", out)


if __name__ == "__main__":
    unittest.main()
