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


class TestEnvironmentFailureIsNotAUsageError(Base):
    """An OSError out of submit() — the spool absent, read-only, or full — used to
    return EXIT_USAGE, the same code as a malformed --client. Exit 1 tells a model its
    ARGUMENTS were wrong, so the only response it invites is to re-craft them and
    re-send: pointless work, and pressure applied to a rail that is simply down.

    The spool is made genuinely unreachable rather than patched, so this exercises the
    real errno path a container with a broken mount would hit."""

    def _break_the_spool(self):
        """Replace the spool root with a read-only directory. submit() must fail while
        creating its temp file, before anything is filed."""
        os.chmod(self.root, 0o500)
        self.addCleanup(os.chmod, self.root, 0o700)

    def test_control_apply_succeeds_while_the_spool_is_writable(self):
        """POSITIVE CONTROL: proves the fixture files a request normally, so the
        refusal below is caused by the broken spool and not by the arguments."""
        rc, out, _ = self.run_cli(["apply", "--client", "pilot-1",
                                   "--changeset", "20260824-101500-abcdef01"])
        self.assertEqual(rc, 0)
        self.assertTrue(out.strip())

    def test_an_unreachable_spool_is_not_reported_as_a_usage_error(self):
        self._break_the_spool()
        rc, out, err = self.run_cli(["apply", "--client", "pilot-1",
                                     "--changeset", "20260824-101500-abcdef01"])
        self.assertNotEqual(rc, K.EXIT_USAGE)
        self.assertEqual(rc, K.EXIT_REFUSED)
        self.assertIn("spool_unavailable", out)
        self.assertIn("nothing was mutated", out)
        self.assertTrue(err.strip(), "the operator gets no diagnostic at all")

    def test_control_a_malformed_argument_IS_still_a_usage_error(self):
        """DISCRIMINATING CONTROL. A bad --client is a genuine usage error and must
        keep exit 1: re-crafting the argument is the correct response there. Without
        this, the test above would pass against a client that had simply stopped using
        EXIT_USAGE for anything."""
        rc, _, err = self.run_cli(["apply", "--client", "NOT A SLUG",
                                   "--changeset", "20260824-101500-abcdef01"])
        self.assertEqual(rc, K.EXIT_USAGE)
        self.assertTrue(err.strip())

    def test_the_model_facing_text_invites_no_retry_and_leaks_no_errno_wording(self):
        """This client exists to refuse to say retry-flavoured things. An errno's
        strerror is arbitrary wording the caller does not control — EAGAIN renders as
        "Resource temporarily unavailable", which reads as an invitation to try again —
        so it belongs on stderr and nowhere near the text a model reads."""
        self._break_the_spool()
        _rc, out, err = self.run_cli(["apply", "--client", "pilot-1",
                                      "--changeset", "20260824-101500-abcdef01"])
        lowered = out.lower()
        for word in ("retry", "try again", "temporarily", "permission denied", "errno"):
            self.assertNotIn(word, lowered, "model-facing text contains %r" % word)
        self.assertIn("will not help", lowered)
        # The detail is not destroyed, only relocated.
        self.assertIn("Error", err)

    def test_nothing_is_left_in_the_spool_after_the_failure(self):
        """The exit-2 text asserts nothing was filed, and exit 2 is a spec-§12
        guarantee that nothing was mutated. Verified rather than trusted.

        On a read-only root the requests/ directory cannot even be created, so its
        ABSENCE is the strongest form of the assertion — no request, and no temp file
        left behind for the broker to trip over either."""
        self._break_the_spool()
        self.run_cli(["apply", "--client", "pilot-1",
                      "--changeset", "20260824-101500-abcdef01"])
        d = S.requests_dir(self.root)
        self.assertEqual(sorted(os.listdir(d)) if os.path.isdir(d) else [], [])
        self.assertEqual(sorted(os.listdir(self.root)), [])


class TestResult(Base):
    RID = "0f9c1a2b-3d4e-4f50-8a1b-2c3d4e5f6071"

    def _result(self, payload):
        S.write_result(self.RID, payload, self.root)

    def test_an_unhashable_exit_code_is_a_refusal_not_a_crash(self):
        """S6-M1. results/ is inside the spool — the one tree Hermes can write — so
        exit_code comes from an attacker-writable file. `_EXIT_BY_CODE.get([])` raises
        TypeError: unhashable type, which main() does not catch, so it escaped as a raw
        traceback and exit 1: a crash reported with the code that means "your arguments
        were wrong", provokable by writing one file."""
        for planted in ([], {}, [1, 2], {"a": 1}):
            self._result({"request_id": self.RID, "status": "ok",
                          "classification": "accepted_applied",
                          "exit_code": planted, "finished_at": "2026-08-24T10:15:00Z"})
            rc, out, err = self.run_cli(["result", "--request-id", self.RID])
            self.assertEqual(rc, K.EXIT_REFUSED, "planted %r gave rc=%s" % (planted, rc))
            self.assertNotIn("Traceback", err)
            self.assertIn("request %s" % self.RID, out)

    def test_a_planted_exit_code_never_becomes_a_success(self):
        """The direction that matters. A non-integer exit_code must never resolve to
        EXIT_OK: that would let a planted file tell the model a mutation succeeded."""
        for planted in ([], {}, "0", "ok", None, 0.0, [0]):
            self._result({"request_id": self.RID, "status": "ok",
                          "classification": "accepted_applied",
                          "exit_code": planted, "finished_at": "2026-08-24T10:15:00Z"})
            rc, _, _ = self.run_cli(["result", "--request-id", self.RID])
            self.assertNotEqual(rc, K.EXIT_OK, "planted %r read as success" % (planted,))

    def test_control_the_real_integer_codes_still_map(self):
        """DISCRIMINATING CONTROL. A guard that refused every code would satisfy both
        tests above while breaking the client's whole purpose — surfacing the broker's
        verdict unchanged."""
        for code, expected in ((0, K.EXIT_OK), (2, K.EXIT_REFUSED),
                               (3, K.EXIT_FAILED_AFTER_MUTATION)):
            self._result({"request_id": self.RID, "status": "ok",
                          "classification": "accepted_applied",
                          "exit_code": code, "finished_at": "2026-08-24T10:15:00Z"})
            rc, _, _ = self.run_cli(["result", "--request-id", self.RID])
            self.assertEqual(rc, expected, "code %r" % code)

    def test_the_planted_value_is_still_shown_to_the_operator(self):
        """This client surfaces the broker's record verbatim; the guard changes the
        EXIT CODE, not the rendering. A planted value being visible exactly as written
        is what lets an operator see they were attacked."""
        self._result({"request_id": self.RID, "status": "ok",
                      "classification": "accepted_applied",
                      "exit_code": [7], "finished_at": "2026-08-24T10:15:00Z"})
        _rc, out, _ = self.run_cli(["result", "--request-id", self.RID])
        self.assertIn("exit_code", out)
        self.assertIn("7", out)

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
