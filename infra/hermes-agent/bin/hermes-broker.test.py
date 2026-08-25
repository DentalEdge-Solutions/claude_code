import datetime, importlib.util, json, os, sys, tempfile, unittest

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
        self.assertEqual(argv[argv.index("--client") + 1], SLUG)
        self.assertEqual(argv[argv.index("--changeset") + 1], CID)
        # No request field reaches the command as anything but these two values.
        self.assertNotIn(rid, argv)
        # And undo is never passed, on any path.
        self.assertNotIn("--undo", argv)

    def test_a_shell_metacharacter_slug_never_reaches_the_runner(self):
        rid = self.file_request(client="pilot-1; rm -rf /")
        r = RecordingRunner()
        self.drain(r)
        self.assertEqual(r.calls, [])


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


if __name__ == "__main__":
    unittest.main()
