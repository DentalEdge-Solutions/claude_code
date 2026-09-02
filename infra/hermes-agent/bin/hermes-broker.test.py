import datetime, importlib.util, json, os, subprocess, sys, tempfile, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import spool_lib as S
import changeset_lib as C
import governance_lib


def _load(name, filename):
    spec = importlib.util.spec_from_file_location(name, os.path.join(HERE, filename))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


B = _load("hermes_broker", "hermes-broker.py")

NOW = datetime.datetime(2026, 8, 24, 10, 15, 0, tzinfo=datetime.timezone.utc)
CID = "20260824-101500-abcdef01"
SLUG = "pilot-1"
DIGEST = "a" * 64

REGISTRY_YAML = """version: 1
projects:
  testproj:
    workdir: /projects/testproj
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
        max_pending_requests: 2
        accepted_requests_per_client_day: 3
"""


class RecordingRunner:
    """A runner that records every invocation and NEVER executes anything.

    The point of this class is a single assertion used throughout: on a refusal,
    `calls` must stay EMPTY. Asserting only that the result says "refused" would pass
    against a broker that refused *after* mutating a live account.
    """

    def __init__(self, rc=0, stdout=""):
        self.calls = []
        self.rc = rc
        self.stdout = stdout

    def __call__(self, argv):
        self.calls.append(list(argv))
        return self.rc, self.stdout


class Base(unittest.TestCase):
    def setUp(self):
        self.gov = tempfile.mkdtemp()
        self.spool = tempfile.mkdtemp()
        self.regdir = tempfile.mkdtemp()
        self.registry = os.path.join(self.regdir, "projects.yaml")
        with open(self.registry, "w") as f:
            f.write(REGISTRY_YAML)
        # RULING R4: the client registry is only ever read via vault_lib.resolve, which
        # reads governance_lib.clients_registry_path() (below) — never a copy sitting in
        # regdir. Only the governance copy is written.
        self._env = {k: os.environ.get(k) for k in
                     ("HERMES_GOVERNANCE_ROOT", "HERMES_SPOOL_ROOT", "VAULT_ROOT")}
        os.environ["HERMES_GOVERNANCE_ROOT"] = self.gov
        os.environ["HERMES_SPOOL_ROOT"] = self.spool
        os.environ["VAULT_ROOT"] = os.path.join(self.regdir, "vaults")
        os.makedirs(os.path.join(self.gov, "registry"), exist_ok=True)
        with open(governance_lib.clients_registry_path(self.gov), "w") as f:
            json.dump({"clients": {SLUG: {"customer_id": "1234567890",
                                          "project": "testproj",
                                          "status": "active"}}}, f)
        C.write_approval(SLUG, CID, DIGEST, "operator", NOW, 24)

    def tearDown(self):
        for k, v in self._env.items():
            os.environ.pop(k, None)
            if v is not None:
                os.environ[k] = v

    def file_request(self, **over):
        req = {"request_id": over.pop("request_id", str(__import__("uuid").uuid4())),
               "op": "apply", "client": SLUG, "changeset": CID}
        req.update(over)
        d = S.requests_dir(self.spool)
        os.makedirs(d, exist_ok=True)
        name = over.get("_filename", "%s.json" % req["request_id"])
        with open(os.path.join(d, name), "w") as f:
            json.dump(req, f)
        return req["request_id"]

    def drain(self, runner):
        return B.drain(spool=self.spool, projects=self.registry,
                       runner=runner, now=NOW)

    def result_for(self, rid):
        with open(S.result_path(rid, self.spool)) as f:
            return json.load(f)


class TestRefusalsNeverExecute(Base):
    def test_control_a_valid_request_DOES_execute(self):
        # THE POSITIVE CONTROL for this whole class. Every "never spawned" assertion
        # below is worthless unless the broker can actually be made to spawn.
        rid = self.file_request()
        r = RecordingRunner()
        self.drain(r)
        self.assertEqual(len(r.calls), 1)
        self.assertEqual(self.result_for(rid)["classification"], "accepted_applied")

    def test_extra_key_refuses_without_spawning(self):
        rid = self.file_request(operator="root")
        r = RecordingRunner()
        self.drain(r)
        self.assertEqual(r.calls, [])
        self.assertEqual(self.result_for(rid)["classification"], "refused_request")

    def test_op_undo_refuses_without_spawning(self):
        rid = self.file_request(op="undo")
        r = RecordingRunner()
        self.drain(r)
        self.assertEqual(r.calls, [])

    def test_filename_mismatch_refuses_without_spawning(self):
        rid = self.file_request(_filename="1111aaaa-2222-4bbb-8ccc-3333dddd4444.json")
        r = RecordingRunner()
        self.drain(r)
        self.assertEqual(r.calls, [])

    def test_replayed_request_id_refuses_without_spawning(self):
        rid = self.file_request()
        self.drain(RecordingRunner())          # first pass consumes it
        C.write_approval(SLUG, CID, DIGEST, "operator", NOW, 24)   # fresh approval
        self.file_request(request_id=rid)      # same id, filed again
        r = RecordingRunner()
        self.drain(r)
        self.assertEqual(r.calls, [])
        self.assertEqual(self.result_for(rid)["classification"], "refused_replay")

    def test_replay_survives_deletion_of_the_whole_spool(self):
        # The property that justifies putting the seen-set in the governance store.
        # Hermes deleting the spool must not re-admit a used request_id.
        rid = self.file_request()
        self.drain(RecordingRunner())
        import shutil
        shutil.rmtree(self.spool)
        C.write_approval(SLUG, CID, DIGEST, "operator", NOW, 24)
        self.file_request(request_id=rid)
        r = RecordingRunner()
        self.drain(r)
        self.assertEqual(r.calls, [])
        self.assertEqual(self.result_for(rid)["classification"], "refused_replay")

    def test_replay_is_refused_via_a_directly_seeded_seen_set_without_spawning(self):
        # Independent of any accept-execute round trip: burns request_id via
        # C.append_seen directly (exactly what _process does BEFORE calling _execute),
        # then files a request carrying that same id. This must be refused as a replay
        # purely from the seen-set check in _process, and must never reach the runner —
        # provable even while _execute/_run_subprocess are still Task-6 stubs.
        rid = str(__import__("uuid").uuid4())
        C.append_seen(SLUG, rid, NOW)
        self.file_request(request_id=rid)
        r = RecordingRunner()
        self.drain(r)
        self.assertEqual(r.calls, [])
        self.assertEqual(self.result_for(rid)["classification"], "refused_replay")

    def test_replay_via_seeded_seen_set_survives_deletion_of_the_whole_spool(self):
        # The property that justifies putting the seen-set in the governance store
        # rather than the spool, proven without depending on execution: seed the
        # seen-set, delete the ENTIRE spool directory, then re-file the same id. It must
        # still be refused as a replay — Hermes deleting the spool it owns must not
        # re-admit a request_id the governance store has already burned.
        rid = str(__import__("uuid").uuid4())
        C.append_seen(SLUG, rid, NOW)
        import shutil
        shutil.rmtree(self.spool)
        self.file_request(request_id=rid)
        r = RecordingRunner()
        self.drain(r)
        self.assertEqual(r.calls, [])
        self.assertEqual(self.result_for(rid)["classification"], "refused_replay")

    def test_an_over_limit_client_is_refused_wholesale_until_its_queue_drains(self):
        # RULING R5: max_pending_requests is 2 in the fixture registry, but
        # pending_count is computed ONCE per drain, before any of the five requests are
        # processed — so all five see the same pending_count=5 > 2 and are refused, not
        # merely the three over the limit. Renamed from the brief's
        # test_pending_quota_refuses_the_excess_without_spawning: that name implied
        # trimming to the limit, which is not what a fail-closed once-per-drain count
        # does or should do. The original assertion (assertLessEqual(len(r.calls), 2))
        # still holds — it is just not tight enough to describe the real behaviour,
        # which is asserted explicitly below.
        for _ in range(5):
            self.file_request()
        r = RecordingRunner()
        self.drain(r)
        self.assertEqual(r.calls, [])
        classifications = [json.load(open(os.path.join(S.results_dir(self.spool), n)))
                           ["classification"] for n in os.listdir(S.results_dir(self.spool))]
        self.assertEqual(len(classifications), 5)
        self.assertTrue(all(c == "refused_quota" for c in classifications))

    def test_daily_accepted_quota_refuses_without_spawning(self):
        # accepted_requests_per_client_day is 3 in the fixture registry.
        for _ in range(3):
            self.file_request()
            self.drain(RecordingRunner())
            C.write_approval(SLUG, CID, DIGEST, "operator", NOW, 24)
        self.file_request()
        r = RecordingRunner()
        self.drain(r)
        self.assertEqual(r.calls, [])

    def test_daily_accepted_quota_is_refused_via_a_directly_seeded_seen_set(self):
        # Independent of any accept-execute round trip: seed the seen-set with
        # accepted_requests_per_client_day (3, in the fixture registry) entries dated
        # "today" via C.append_seen directly, then file one more request. It must be
        # refused as a quota violation purely from _accepted_today's read of the
        # seen-set, and must never reach the runner — provable even while
        # _execute/_run_subprocess are still Task-6 stubs.
        for _ in range(3):
            C.append_seen(SLUG, str(__import__("uuid").uuid4()), NOW)
        rid = self.file_request()
        r = RecordingRunner()
        self.drain(r)
        self.assertEqual(r.calls, [])
        self.assertEqual(self.result_for(rid)["classification"], "refused_quota")

    def test_symlinked_request_refuses_without_spawning(self):
        d = S.requests_dir(self.spool)
        os.makedirs(d, exist_ok=True)
        target = os.path.join(self.spool, "elsewhere.json")
        with open(target, "w") as f:
            json.dump({"request_id": "1111aaaa-2222-4bbb-8ccc-3333dddd4444",
                       "op": "apply", "client": SLUG, "changeset": CID}, f)
        os.symlink(target, os.path.join(d, "1111aaaa-2222-4bbb-8ccc-3333dddd4444.json"))
        r = RecordingRunner()
        self.drain(r)
        self.assertEqual(r.calls, [])

    def test_a_result_is_written_on_every_outcome(self):
        # §12: file EXISTENCE is the discriminator between "not processed yet" and
        # "processed and refused". A refusal that writes nothing is indistinguishable
        # from a broker that is down.
        rid = self.file_request(op="undo")
        self.drain(RecordingRunner())
        self.assertTrue(os.path.isfile(S.result_path(rid, self.spool)))

    def test_the_request_file_is_removed_after_processing(self):
        rid = self.file_request()
        self.drain(RecordingRunner())
        self.assertFalse(os.path.isfile(S.request_path(rid, self.spool)))

    def test_a_half_written_temp_file_is_never_scanned_or_touched(self):
        # Mirrors hermes-syscall.submit's own mkstemp artifact: a request_id-prefixed,
        # dot-led, ".tmp"-suffixed name that can never fullmatch S.FILENAME_RE because
        # mkstemp always inserts its own random infix. _scan's filter must exclude it
        # from the directory listing entirely — not merely have it refused later — so a
        # half-written request mid-write by the one untrusted writer is never read, and
        # (just as important) never discarded as a side effect of being rejected.
        d = S.requests_dir(self.spool)
        os.makedirs(d, exist_ok=True)
        tmp_name = ".deadbeef-dead-4eef-beef-deadbeefdead.abcd1234.tmp"
        tmp_path = os.path.join(d, tmp_name)
        with open(tmp_path, "w") as f:
            f.write('{"request_id": "deadbeef-dead-4eef-beef-deadbeefdead", '
                    '"op": "apply", "client": "%s", "changeset": "%s"}' % (SLUG, CID))
        r = RecordingRunner()
        self.drain(r)
        self.assertEqual(r.calls, [])
        self.assertTrue(os.path.isfile(tmp_path),
                         "a half-written temp artifact must be left untouched, not discarded")


class TestAcceptedTodayFailsClosed(Base):
    """FIX ROUND 2 (Finding 2, Important). _accepted_today's docstring claimed
    "fail-closed: an unreadable seen-set raises", but it counted by substring-matching
    raw lines and caught only OSError — so a seen-set corrupted in a way that mangles
    or drops the "seen_at" field silently undercounted (fail-OPEN) instead, while
    seen_contains on the SAME file correctly raised. Now both share
    changeset_lib.iter_seen_records, so they cannot drift into different failure
    semantics for the same file again.
    """

    def test_a_corrupt_seen_set_raises_rather_than_undercounting(self):
        # Valid JSON, but missing "seen_at" — exactly the field _accepted_today needs
        # to decide whether a record counts as "today". The old implementation would
        # simply fail to match the substring and count this as zero.
        p = governance_lib.seen_path(SLUG)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w") as f:
            f.write(json.dumps({"request_id": str(__import__("uuid").uuid4())}) + "\n")
        with self.assertRaises(ValueError):
            B._accepted_today(SLUG, NOW)

    def test_control_an_intact_seen_set_counts_correctly_without_raising(self):
        # The positive control for the refusal above.
        for _ in range(2):
            C.append_seen(SLUG, str(__import__("uuid").uuid4()), NOW)
        self.assertEqual(B._accepted_today(SLUG, NOW), 2)


class TestNoInterpolation(Base):
    def test_the_runner_receives_an_argv_list_of_validated_identifiers_only(self):
        rid = self.file_request()
        r = RecordingRunner()
        self.drain(r)
        argv = r.calls[0]
        self.assertIsInstance(argv, list)
        self.assertIn("--client", argv)
        self.assertIn("--changeset", argv)
        self.assertIn("--request", argv)
        self.assertEqual(argv[argv.index("--client") + 1], SLUG)
        self.assertEqual(argv[argv.index("--changeset") + 1], CID)
        self.assertEqual(argv[argv.index("--request") + 1], rid)
        # The request id reaches the command in exactly ONE place — the --request
        # value — never smuggled into another field or appended as a stray element.
        self.assertEqual(argv.count(rid), 1)
        # And undo is never passed, on any path.
        self.assertNotIn("--undo", argv)

    def test_a_shell_metacharacter_slug_never_reaches_the_runner(self):
        rid = self.file_request(client="pilot-1; rm -rf /")
        r = RecordingRunner()
        self.drain(r)
        self.assertEqual(r.calls, [])


class TimingOutRunner:
    """A runner that raises subprocess.TimeoutExpired instead of returning.

    Purpose-built rather than a RecordingRunner flag (R16): a runner whose ONLY
    behaviour is to time out cannot accidentally return a real rc and quietly test the
    wrong branch. It still records, so "the executor really was invoked" stays
    assertable — a timeout that never spawned anything would prove nothing about the
    path that handles one."""

    def __init__(self):
        self.calls = []

    def __call__(self, argv):
        self.calls.append(list(argv))
        raise subprocess.TimeoutExpired(cmd=list(argv), timeout=B.RUNNER_TIMEOUT_SECONDS)


class TestExecutorTimeoutDetail(Base):
    """R16. rc=3 from a real executor exit and rc=3 SYNTHESISED from a timeout both map
    to classification failed_after_mutation, but they are not equally certain. The fixed
    text for that classification asserts as FACT that a mutation landed; for a timeout
    that overclaims, because a mutation only MAY have been left in flight. The hedge was
    added for exactly that reason and then shipped with no test, so deleting it broke
    nothing."""

    def test_a_timeout_gets_the_hedged_detail_not_the_assertive_one(self):
        r = TimingOutRunner()
        rid = self.file_request()
        self.drain(r)
        self.assertEqual(len(r.calls), 1)            # the executor really was invoked
        result = self.result_for(rid)
        # Fail-closed classification is UNCHANGED by the hedge — only the text differs.
        self.assertEqual(result["classification"], "failed_after_mutation")
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["exit_code"], 3)
        self.assertNotEqual(result["detail"],
                            B.DETAIL_BY_CLASSIFICATION["failed_after_mutation"])
        self.assertIn("MAY", result["detail"])
        self.assertIn(str(B.RUNNER_TIMEOUT_SECONDS), result["detail"])

    def test_control_a_real_rc3_keeps_the_assertive_detail(self):
        """DISCRIMINATING CONTROL. Same classification, same exit code, different
        certainty. Without this the test above would pass against a broker that had
        simply replaced the assertive text everywhere, losing the distinction the hedge
        exists to draw."""
        rid = self.file_request()
        self.drain(RecordingRunner(rc=3, stdout="the mutator died"))
        result = self.result_for(rid)
        self.assertEqual(result["classification"], "failed_after_mutation")
        self.assertEqual(result["exit_code"], 3)
        self.assertEqual(result["detail"],
                         B.DETAIL_BY_CLASSIFICATION["failed_after_mutation"])
        self.assertNotIn("MAY", result["detail"])

    def test_a_timeout_still_records_the_outcome_on_the_approval(self):
        """A timeout must not leave the approval live: the run may have mutated, so the
        approval is spent whatever the text says."""
        self.file_request()
        self.drain(TimingOutRunner())
        with open(governance_lib.approval_path(SLUG, CID)) as f:
            self.assertEqual(json.load(f)["outcome"], "failed_after_mutation")

    def test_a_timeout_leaks_no_command_line_into_the_spool(self):
        """subprocess.TimeoutExpired carries the full argv it was constructed with, and
        str() renders it. That must not reach the Hermes-readable spool any more than a
        raw OSError does (S6)."""
        rid = self.file_request()
        self.drain(TimingOutRunner())
        blob = json.dumps(self.result_for(rid))
        self.assertNotIn(B.MUTATE_SH, blob)


class TestRefusalDetailIsFixedVocabulary(Base):
    """S6. hermes-broker's DETAIL_BY_CLASSIFICATION comment declares that detail
    strings are fixed and non-identifying and that output is deliberately kept out of
    the Hermes-readable spool. Two paths bypassed it: drain()'s per-request handler
    wrote `str(e)`, and _execute's reserve_approval failure wrote
    "approval unavailable: %s" % e.

    Every test here forces a REAL exception that genuinely carries a host path — proved
    by a positive control on the raw exception before anything is asserted about the
    spool — so an absence in the result cannot come from an exception that had nothing
    to leak in the first place. That is the failure mode that made an earlier probe of
    this question meaningless.

    Structurally the same fix as Task 2's Important #2 on hermes-syscall.py: fixed
    vocabulary to the reader that is the agent, full detail to stderr.
    """

    def _stderr(self):
        """Captured broker stderr, so 'the detail went host-side' is asserted, not
        assumed. A fix that merely deleted the text would pass every leak assertion
        below while destroying the operator's only diagnostic."""
        return self._err.getvalue()

    def setUp(self):
        super().setUp()
        import contextlib, io as _io
        self._err = _io.StringIO()
        cm = contextlib.redirect_stderr(self._err)
        cm.__enter__()
        self.addCleanup(cm.__exit__, None, None, None)

    def _break_the_approval_write(self):
        """Make reserve_approval's atomic write fail with a PermissionError naming the
        governance-store path. Returns the raw exception text for the control."""
        d = os.path.dirname(governance_lib.approval_path(SLUG, CID))
        os.chmod(d, 0o500)
        self.addCleanup(os.chmod, d, 0o700)
        try:
            C.reserve_approval(SLUG, CID, "1111aaaa-2222-4bbb-8ccc-3333dddd4444", NOW)
        except OSError as e:
            return str(e)
        self.fail("reserve_approval did not fail — the fixture no longer forces a leak")

    def test_control_the_forced_approval_failure_really_does_carry_the_store_path(self):
        """POSITIVE CONTROL, and it has to come first. Asserts the exception this test
        class provokes actually contains the host governance-store path. Without it,
        the absence asserted below would be satisfied by an exception that never had
        the path to leak."""
        raw = self._break_the_approval_write()
        self.assertIn(self.gov, raw)

    def test_refused_approval_detail_is_fixed_and_leaks_no_store_path(self):
        raw = self._break_the_approval_write()
        self.assertIn(self.gov, raw)                     # control, re-asserted in place
        rid = self.file_request()
        r = RecordingRunner()
        self.drain(r)
        self.assertEqual(r.calls, [])                    # nothing was executed
        result = self.result_for(rid)
        self.assertEqual(result["classification"], "refused_approval")
        self.assertEqual(result["exit_code"], 2)         # unchanged by this fix
        self.assertEqual(result["detail"], B.EXCEPTION_DETAIL_REFUSED_APPROVAL)
        self.assertNotIn(self.gov, json.dumps(result))
        self.assertIn(self.gov, self._stderr())          # the operator still gets it

    def test_refused_request_detail_is_fixed_and_leaks_no_registry_path(self):
        """drain()'s per-request except handler. Forced with a registry path that is a
        DIRECTORY, so read_spool_quotas raises IsADirectoryError naming it — an OSError
        carrying a host path, reached from inside _process."""
        os.unlink(self.registry)
        os.makedirs(self.registry)
        rid = self.file_request()
        r = RecordingRunner()
        outcomes = self.drain(r)
        self.assertEqual(r.calls, [])
        result = self.result_for(rid)
        self.assertEqual(result["classification"], "refused_request")
        self.assertEqual(result["exit_code"], 2)
        self.assertEqual(result["detail"], B.EXCEPTION_DETAIL_REFUSED_REQUEST)
        self.assertNotIn(self.registry, json.dumps(result))
        # The outcome dict drain() RETURNS carries the same field name; it must not
        # disagree with the spool copy just because it is read host-side.
        self.assertEqual(outcomes[0]["detail"], B.EXCEPTION_DETAIL_REFUSED_REQUEST)
        self.assertNotIn(self.registry, json.dumps(outcomes))
        self.assertIn(self.registry, self._stderr())     # the operator still gets it

    def test_control_a_healthy_run_leaks_nothing_either(self):
        """The other half of the pair: with nothing broken, the accepted path must also
        keep host paths out of the result. Establishes that the two tests above measure
        the refusal paths specifically, rather than a spool that is empty of paths for
        some unrelated reason."""
        rid = self.file_request()
        self.drain(RecordingRunner(rc=0, stdout="applied"))
        result = self.result_for(rid)
        self.assertEqual(result["classification"], "accepted_applied")
        blob = json.dumps(result)
        self.assertNotIn(self.gov, blob)
        self.assertNotIn(self.registry, blob)

    def test_every_spool_detail_string_comes_from_the_declared_vocabulary(self):
        """Pins the vocabulary itself: the two constants are distinct from each other
        and from every DETAIL_BY_CLASSIFICATION entry, and none of them is a format
        string waiting for an exception to be interpolated into it."""
        vocab = list(B.DETAIL_BY_CLASSIFICATION.values()) + [
            B._DETAIL_FALLBACK, B.EXCEPTION_DETAIL_REFUSED_REQUEST,
            B.EXCEPTION_DETAIL_REFUSED_APPROVAL]
        self.assertEqual(len(set(vocab)), len(vocab))    # no duplicates
        for text in vocab:
            self.assertIsInstance(text, str)
            self.assertNotIn("%s", text)
            self.assertNotIn("{}", text)


class TestGlobalCeiling(Base):
    def test_an_absurd_number_of_request_files_is_refused_wholesale(self):
        d = S.requests_dir(self.spool)
        os.makedirs(d, exist_ok=True)
        n = B.MAX_SPOOL_FILES + 5
        for i in range(n):
            with open(os.path.join(d, "%036d.json" % i), "w") as f:
                f.write("{}")
        r = RecordingRunner()
        out = self.drain(r)
        self.assertEqual(r.calls, [])
        self.assertTrue(any(o.get("classification") == "refused_spool_overflow"
                            for o in out))
        # FIX ROUND 2 (Finding 5): R6 says the flooded files are deliberately NOT
        # discarded — asserted only in a comment until now. Prove it: every one of the
        # flood's files must still be sitting in requests/ after the refusal, so a
        # human (or a later drain, once the flood is understood) can still find them.
        self.assertEqual(len(os.listdir(d)), n,
                          "spool-overflow refusal must not discard the flooded files")


class TestPoisonedSpoolEntries(Base):
    """FIX ROUND 2 (Finding 1, CRITICAL). Hermes can `mkdir` a UUID-shaped name in
    requests/ to defeat a scanner that only checks NAME shape, not file TYPE. _scan
    admits it; _parse_all correctly refuses it as non-regular; but a naive _discard
    doing a bare os.unlink() on a directory raises — uncaught — straight out of
    drain(). Because the un-removable directory is never cleared, EVERY subsequent
    drain died the identical way: one mkdir from exactly the actor this module's own
    docstring names as hostile permanently bricked the governed mutation rail, and
    starved every other client's requests queued in the same pass.
    """

    def test_a_poisoned_directory_does_not_crash_the_drain_or_block_other_requests(self):
        d = S.requests_dir(self.spool)
        os.makedirs(d, exist_ok=True)
        poison_name = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee.json"
        os.mkdir(os.path.join(d, poison_name))

        # THE POSITIVE CONTROL: without asserting some OTHER, genuinely valid request
        # in the SAME batch is actually processed, this test would only prove nothing
        # crashed — not that the poisoned entry failed to block anyone else. Deliberately
        # a replay (seen-set seeded directly), not a fresh accept: Task 5 has no working
        # _execute yet (RULING R12 — the stub must raise, not be swallowed), so a fresh
        # accept would itself raise NotImplementedError and this test could not tell
        # that failure apart from the bug under test.
        other_rid = str(__import__("uuid").uuid4())
        C.append_seen(SLUG, other_rid, NOW)
        self.file_request(request_id=other_rid)

        r = RecordingRunner()
        out = self.drain(r)                              # must not raise
        self.assertEqual(r.calls, [])
        self.assertEqual(self.result_for(other_rid)["classification"], "refused_replay")
        self.assertNotIn(poison_name, os.listdir(d),
                          "the poisoned directory must be moved out of requests/, not "
                          "left for every future drain to re-discover and re-reject")

        # A second drain must not repeat the crash, and must not find the poisoned
        # entry sitting in requests/ demanding another look — it must not be retried
        # forever as new work.
        out2 = self.drain(RecordingRunner())              # must not raise
        self.assertNotIn(poison_name, os.listdir(d))


class TestExecution(Base):
    def test_reservation_is_written_before_the_runner_is_called(self):
        # The ordering property from spec §7, asserted DIRECTLY: the runner inspects
        # the approval record at the moment it is invoked. If reservation happened
        # after execution, reserved_at would be absent here.
        seen = {}

        def runner(argv):
            p = governance_lib.approval_path(SLUG, CID)
            with open(p) as f:
                seen["rec"] = json.load(f)
            return 0, ""

        self.file_request()
        self.drain(runner)
        self.assertIn("reserved_at", seen["rec"])

    def test_a_failing_executor_still_leaves_the_approval_unusable(self):
        # The crash case. An interrupted apply is not a reusable approval.
        self.file_request()
        self.drain(RecordingRunner(rc=3))
        with self.assertRaises(ValueError):
            C.verify_approval(SLUG, CID, DIGEST, NOW)

    def test_exit_codes_are_not_collapsed(self):
        # Deviation from the brief's literal test body, noted per R3/R7-adjacent
        # transparency rather than silently patched: the shared REGISTRY_YAML fixture
        # sets accepted_requests_per_client_day to 3, deliberately low so
        # test_daily_accepted_quota_refuses_without_spawning (elsewhere in this file)
        # can exercise it cheaply. C.append_seen — and so the daily "accepted" count —
        # fires in _process for every request that clears classify(), regardless of
        # what _execute/the runner later does with it; it is not gated on the exit
        # code. Looping all four rc cases (0,1,2,3) against ONE client under that cap
        # therefore hits refused_quota on the 4th iteration before the executor is
        # even invoked, which would make this test assert something untrue about
        # quota enforcement rather than about exit-code mapping (a different property,
        # already covered by TestRefusalsNeverExecute). Uses a private copy of the
        # registry with a higher cap so this test's four sequential accepted requests
        # are about exit-code handling alone, and does not touch the shared fixture
        # every other quota test still depends on.
        registry = os.path.join(self.regdir, "projects-uncapped.yaml")
        with open(self.registry) as f:
            body = f.read()
        with open(registry, "w") as f:
            f.write(body.replace("accepted_requests_per_client_day: 3",
                                 "accepted_requests_per_client_day: 100"))
        cases = {0: ("accepted_applied", "applied"),
                 1: ("refused_usage", "refused"),
                 2: ("refused_preflight", "refused"),
                 3: ("failed_after_mutation", "failed")}
        for rc, (classification, status) in cases.items():
            C.write_approval(SLUG, CID, DIGEST, "operator", NOW, 24)
            rid = self.file_request()
            B.drain(spool=self.spool, projects=registry, runner=RecordingRunner(rc=rc), now=NOW)
            got = self.result_for(rid)
            self.assertEqual(got["classification"], classification, "rc=%d" % rc)
            self.assertEqual(got["status"], status, "rc=%d" % rc)
            self.assertEqual(got["exit_code"], rc)

    def test_an_unknown_exit_code_is_treated_as_failure_not_success(self):
        rid = self.file_request()
        self.drain(RecordingRunner(rc=42))
        got = self.result_for(rid)
        self.assertEqual(got["status"], "failed")
        self.assertNotEqual(got["classification"], "accepted_applied")

    def test_executor_output_never_reaches_the_spool_result(self):
        # §17.3: per-action resource names must not reach Hermes. The spool result is
        # Hermes-readable, so the executor's stdout must not be copied into it.
        marker = "CAMPAIGN-RESOURCE-NAME-MARKER-9f8e7d"
        rid = self.file_request()
        self.drain(RecordingRunner(rc=0, stdout="applied 3 actions %s" % marker))
        blob = json.dumps(self.result_for(rid))
        self.assertNotIn(marker, blob)

    def test_a_missing_approval_refuses_without_calling_the_runner(self):
        os.unlink(governance_lib.approval_path(SLUG, CID))
        rid = self.file_request()
        r = RecordingRunner()
        self.drain(r)
        self.assertEqual(r.calls, [])
        self.assertEqual(self.result_for(rid)["classification"], "refused_approval")

    def test_an_already_reserved_approval_refuses_without_calling_the_runner(self):
        C.reserve_approval(SLUG, CID, "1111aaaa-2222-4bbb-8ccc-3333dddd4444", NOW)
        rid = self.file_request()
        r = RecordingRunner()
        self.drain(r)
        self.assertEqual(r.calls, [])
        self.assertEqual(self.result_for(rid)["classification"], "refused_approval")

    def test_the_outcome_is_recorded_on_the_approval(self):
        self.file_request()
        self.drain(RecordingRunner(rc=0))
        with open(governance_lib.approval_path(SLUG, CID)) as f:
            self.assertEqual(json.load(f)["outcome"], "accepted_applied")

    def test_argv_carries_the_request_id_that_was_reserved(self):
        """The reservation and the executor's proof must be the SAME id. A broker that
        reserved with one id and spawned with another would refuse every apply — the
        2026-09-01 defect in a new disguise."""
        rid = self.file_request()
        r = RecordingRunner(rc=0)
        self.drain(r)
        argv = r.calls[0]
        self.assertIn("--request", argv)
        rid_in_argv = argv[argv.index("--request") + 1]
        self.assertEqual(rid_in_argv, rid)
        with open(governance_lib.approval_path(SLUG, CID)) as f:
            rec = json.load(f)
        self.assertEqual(rec["request_id"], rid_in_argv,
                         "argv id must match the id written by reserve_approval")

    def test_a_failure_writing_the_final_result_does_not_launder_into_a_false_refusal(self):
        # Post-Task-6 review FINDING 1. _execute's final _write_result is the LAST
        # thing it does, after a mutation may already have landed and after
        # record_outcome has already run. If THAT write fails (disk full, transient
        # I/O), the pre-fix code let the OSError propagate straight into drain()'s
        # per-request except tuple, which would then write a SECOND result for the
        # same request_id: classification="refused_request", exit_code=2. Under spec
        # §12, exit_code=2 GUARANTEES nothing was mutated — a false guarantee here,
        # since rc=0 means the change-set WAS applied. This is the mirror image of the
        # false-success case the brief already guarded against, just in the refusal
        # direction. A missing result is honest (the client already treats absence as
        # PENDING, which is recoverable); a wrong one is not.
        real_write_result = B.S.write_result
        calls = {"n": 0}

        def flaky_write_result(request_id, payload, root=None):
            calls["n"] += 1
            if calls["n"] == 1:
                raise OSError("simulated disk-full on the first write_result call")
            return real_write_result(request_id, payload, root)

        B.S.write_result = flaky_write_result
        try:
            rid = self.file_request()
            r = RecordingRunner(rc=0)
            self.drain(r)                      # must not raise
            # POSITIVE CONTROL: prove the runner actually ran — otherwise this test
            # would pass against a broker that never executes anything.
            self.assertEqual(len(r.calls), 1)
        finally:
            B.S.write_result = real_write_result

        self.assertFalse(
            os.path.isfile(S.result_path(rid, self.spool)),
            "a failed final write must leave NO result on disk, never a false "
            "refused_request standing in for a request that actually mutated")
        with self.assertRaises(ValueError):
            C.verify_approval(SLUG, CID, DIGEST, NOW)


class TestRealSubprocess(Base):
    """The fake runner proves the logic. This proves the WIRING — that the broker can
    actually start a program and read its status back."""

    def _fake_mutate(self, exit_code, body="echo ran"):
        p = os.path.join(self.regdir, "fake-mutate.sh")
        with open(p, "w") as f:
            f.write("#!/bin/sh\n%s\nexit %d\n" % (body, exit_code))
        os.chmod(p, 0o755)
        return p

    def test_a_real_subprocess_exit_code_reaches_the_result(self):
        script = self._fake_mutate(2)
        orig, B.MUTATE_SH = B.MUTATE_SH, script
        try:
            rid = self.file_request()
            B.drain(spool=self.spool, projects=self.registry, now=NOW)
            got = self.result_for(rid)
        finally:
            B.MUTATE_SH = orig
        self.assertEqual(got["exit_code"], 2)
        self.assertEqual(got["classification"], "refused_preflight")

    def test_control_a_real_subprocess_success_also_reaches_the_result(self):
        # The must-SUCCEED control: without it, "exit 2 arrives" could be produced by a
        # broker that reports 2 for everything.
        script = self._fake_mutate(0)
        orig, B.MUTATE_SH = B.MUTATE_SH, script
        try:
            rid = self.file_request()
            B.drain(spool=self.spool, projects=self.registry, now=NOW)
            got = self.result_for(rid)
        finally:
            B.MUTATE_SH = orig
        self.assertEqual(got["exit_code"], 0)
        self.assertEqual(got["classification"], "accepted_applied")

    def test_the_wrapper_is_invoked_with_exactly_six_argv_elements(self):
        # Was four (--client X --changeset Y) before the broker also passed the
        # reserved request id (--request Z) so the executor can re-verify the same
        # approval it was spawned for — see test_argv_carries_the_request_id_that_was_reserved.
        script = os.path.join(self.regdir, "echo-argv.sh")
        with open(script, "w") as f:
            f.write('#!/bin/sh\nprintf "%s\\n" "$#" > "$ARGC_OUT"\nexit 0\n')
        os.chmod(script, 0o755)
        argc_out = os.path.join(self.regdir, "argc.txt")
        os.environ["ARGC_OUT"] = argc_out
        orig, B.MUTATE_SH = B.MUTATE_SH, script
        try:
            self.file_request()
            B.drain(spool=self.spool, projects=self.registry, now=NOW)
        finally:
            B.MUTATE_SH = orig
            os.environ.pop("ARGC_OUT", None)
        with open(argc_out) as f:
            self.assertEqual(f.read().strip(), "6")   # --client X --changeset Y --request Z


class TestCliFlagsHonored(Base):
    """Nothing above proves the CLI actually READS --spool/--projects rather than
    silently falling back to the environment default that happens to agree with it —
    Base.setUp sets HERMES_SPOOL_ROOT to self.spool for every test, so a --spool that
    is quietly ignored is invisible unless the flag and the env default are made to
    DIFFER. That matters concretely: Task 11's systemd unit passes explicit --spool
    AND sets HERMES_SPOOL_ROOT in the same Environment block, so today the two always
    agree — right up until they diverge, at which point a broker that reads the env
    var instead of the flag would silently drain the wrong directory."""

    def test_cli_honors_explicit_spool_over_the_env_default(self):
        # HERMES_SPOOL_ROOT (env, set by Base.setUp) == self.spool. --spool points
        # somewhere ELSE. The flag must win.
        other = tempfile.mkdtemp()
        d = S.requests_dir(other)
        os.makedirs(d, exist_ok=True)
        rid = str(__import__("uuid").uuid4())
        with open(os.path.join(d, "%s.json" % rid), "w") as f:
            json.dump({"request_id": rid, "op": "apply", "client": SLUG,
                      "changeset": CID}, f)

        rc = B.main(["--once", "--spool", other, "--projects", self.registry])
        self.assertEqual(rc, 0)

        # POSITIVE: the request filed under --spool was drained.
        self.assertTrue(
            os.path.isfile(S.result_path(rid, other)),
            "the --spool directory's request was never processed — the flag is "
            "being ignored in favor of HERMES_SPOOL_ROOT")
        # NEGATIVE CONTROL: the env-default directory (self.spool) was never touched —
        # no result appears there, because nothing was ever filed there.
        req_dir = S.requests_dir(self.spool)
        self.assertFalse(
            os.path.isdir(req_dir) and os.listdir(req_dir),
            "a request appeared in HERMES_SPOOL_ROOT even though only --spool was "
            "given a request to drain")
        self.assertFalse(os.path.isfile(S.result_path(rid, self.spool)))

    def test_cli_honors_explicit_projects_over_the_env_default(self):
        # ADS_REGISTRY (env default read by changeset_lib.registry_projects_path) is
        # pointed at a registry whose max_pending_requests cap refuses two queued
        # requests on quota; --projects is pointed at self.registry, whose cap (2)
        # does not. The flag must win, and the same shape must fall back to the env
        # default's stricter cap when the flag is omitted.
        bad_registry = os.path.join(self.regdir, "projects-bad.yaml")
        bad_yaml = REGISTRY_YAML.replace("max_pending_requests: 2",
                                         "max_pending_requests: 1")
        assert bad_yaml != REGISTRY_YAML, "replace() found nothing — fixture drifted"
        with open(bad_registry, "w") as f:
            f.write(bad_yaml)
        orig_ads = os.environ.get("ADS_REGISTRY")
        os.environ["ADS_REGISTRY"] = bad_registry
        script = os.path.join(self.regdir, "fake-mutate-ok.sh")
        with open(script, "w") as f:
            f.write("#!/bin/sh\nexit 0\n")
        os.chmod(script, 0o755)
        orig_mutate, B.MUTATE_SH = B.MUTATE_SH, script
        try:
            # Two pending requests for the same client -> pending_count == 2.
            rid_a = self.file_request()
            rid_b = self.file_request()

            # POSITIVE: explicit --projects (max_pending_requests: 2) must NOT refuse
            # on quota, even though ADS_REGISTRY's registry (max: 1) would.
            rc = B.main(["--once", "--spool", self.spool, "--projects", self.registry])
            self.assertEqual(rc, 0)
            self.assertNotEqual(self.result_for(rid_a)["classification"], "refused_quota")
            self.assertNotEqual(self.result_for(rid_b)["classification"], "refused_quota")

            # NEGATIVE CONTROL: same two-pending-requests shape, no --projects this
            # time -> must fall back to ADS_REGISTRY's stricter registry and refuse
            # both on quota, purely because pending_count (2) > max_pending_requests (1).
            rid_c = self.file_request()
            rid_d = self.file_request()
            rc2 = B.main(["--once", "--spool", self.spool])
            self.assertEqual(rc2, 0)
            self.assertEqual(self.result_for(rid_c)["classification"], "refused_quota")
            self.assertEqual(self.result_for(rid_d)["classification"], "refused_quota")
        finally:
            B.MUTATE_SH = orig_mutate
            if orig_ads is None:
                os.environ.pop("ADS_REGISTRY", None)
            else:
                os.environ["ADS_REGISTRY"] = orig_ads


class TestCli(Base):
    def test_once_returns_zero_on_an_empty_spool(self):
        self.assertEqual(B.main(["--once", "--spool", self.spool,
                                 "--projects", self.registry]), 0)

    def test_watch_and_once_are_mutually_exclusive(self):
        self.assertNotEqual(B.main(["--once", "--watch", "--spool", self.spool,
                                    "--projects", self.registry]), 0)

    def test_a_zero_interval_is_rejected_before_any_drain_runs(self):
        # Finding 2 (post-Task-7 review): --interval 0 would spin the drain loop with
        # no pacing on a privileged daemon. Must be rejected at parse time -- SystemExit
        # from argparse's own clean usage-error path, exit code 2 -- and the request
        # filed below must still be sitting in the spool untouched, proving no drain
        # ran at all.
        rid = self.file_request()
        with self.assertRaises(SystemExit) as cm:
            B.main(["--watch", "--interval", "0", "--spool", self.spool,
                   "--projects", self.registry])
        self.assertEqual(cm.exception.code, 2)
        self.assertTrue(os.path.isfile(S.request_path(rid, self.spool)),
                        "the request was consumed -- a drain ran despite the bad "
                        "--interval")

    def test_a_negative_interval_is_rejected_before_any_drain_runs(self):
        rid = self.file_request()
        with self.assertRaises(SystemExit) as cm:
            B.main(["--watch", "--interval", "-1", "--spool", self.spool,
                   "--projects", self.registry])
        self.assertEqual(cm.exception.code, 2)
        self.assertTrue(os.path.isfile(S.request_path(rid, self.spool)))


if __name__ == "__main__":
    unittest.main()
