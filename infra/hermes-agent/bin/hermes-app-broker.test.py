#!/usr/bin/env python3
import importlib.util, io, json, os, sys, tempfile, time, unittest
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import app_lib as A
spec = importlib.util.spec_from_file_location("brk", os.path.join(HERE, "hermes-app-broker.py"))
B = importlib.util.module_from_spec(spec); spec.loader.exec_module(B)
MAN = A.load_manifest(os.path.join(os.path.dirname(HERE), "registry/apps/ads-audit.json"), "ads-audit")


class Base(unittest.TestCase):
    def setUp(self):
        t = tempfile.mkdtemp()
        self.spool, self.state = os.path.join(t, "spool"), os.path.join(t, "state")
        for d in (self.spool + "/requests", self.spool + "/results", self.state + "/state",
                  self.state + "/jobs", self.state + "/done", self.state + "/running"):
            os.makedirs(d)
        self.reg = os.path.join(t, "clients.json")
        json.dump({"clients": {"acme-dental": {"status": "active", "customer_id": "1234567890"},
                               "old-dental": {"status": "retired", "customer_id": "1234567891"},
                               "b-dental": {"status": "active", "customer_id": "1234567892"}}}, open(self.reg, "w"))
        self.day = "2026-10-01"
        self.logs = []
        self.ctx = B.Ctx(MAN, self.spool, self.state, self.reg, now=lambda: self.day + "T10:00:00Z",
                         log=self.logs.append)

    def file(self, op="run", client="acme-dental", rid=None, raw=None):
        r = A.make_request(MAN, op, client)
        if rid:
            r["request_id"] = rid
        name = r["request_id"] + ".json"
        open(os.path.join(self.spool, "requests", name), "wb").write(raw if raw is not None else json.dumps(r).encode())
        return r["request_id"]

    def result(self, rid):
        p = os.path.join(self.spool, "results", rid + ".json")
        return json.load(open(p)) if os.path.exists(p) else None

    def jobs(self):
        return sorted(os.listdir(os.path.join(self.state, "jobs")))


class TestAdmit(Base):
    def test_good_request_becomes_a_job_and_is_removed(self):
        rid = self.file()
        B.drain_once(self.ctx)
        self.assertEqual(self.jobs(), [rid + ".json"])
        self.assertEqual(os.listdir(os.path.join(self.spool, "requests")), [])
        self.assertIsNone(self.result(rid))
        job = A.parse_job(open(os.path.join(self.state, "jobs", rid + ".json"), "rb").read(), rid + ".json")
        self.assertEqual((job["op"], job["client"]), ("run", "acme-dental"))

    def test_inactive_and_unknown_refused(self):
        for c in ("old-dental", "nobody"):
            rid = self.file(client=c); B.drain_once(self.ctx)
            self.assertEqual(self.result(rid)["reason"], "inactive_client")
        self.assertEqual(self.jobs(), [])

    def test_kill_switch_refuses_and_the_refusal_is_final(self):
        open(os.path.join(self.state, "DISABLED"), "w").close()
        rid = self.file(); B.drain_once(self.ctx)
        self.assertEqual(self.result(rid)["reason"], "disabled")
        os.unlink(os.path.join(self.state, "DISABLED"))
        self.file(rid=rid); B.drain_once(self.ctx)                  # same id again
        self.assertEqual(self.result(rid)["reason"], "disabled")   # unchanged; no job
        self.assertEqual(self.jobs(), [])

    def test_quota_per_client_and_per_box(self):
        r1 = self.file(); B.drain_once(self.ctx)
        r2 = self.file(); B.drain_once(self.ctx)
        self.assertEqual(self.result(r2)["reason"], "quota")
        for c in ("b-dental",):
            self.file(client=c)
        B.drain_once(self.ctx)
        self.assertEqual(len(self.jobs()), 2)
        self.day = "2026-10-02"
        r3 = self.file(); B.drain_once(self.ctx)
        self.assertIsNone(self.result(r3))                          # a new day: admitted

    def test_duplicate_id_writes_no_second_result(self):
        rid = self.file(client="nobody"); B.drain_once(self.ctx)
        first = self.result(rid)
        self.file(rid=rid, client="acme-dental"); B.drain_once(self.ctx)
        self.assertEqual(self.result(rid), first)
        self.assertEqual(self.jobs(), [])

    def test_malformed_request_bad_request_result_when_id_known(self):
        rid = "0f8e2c1a-1111-4222-8333-444455556666"
        open(os.path.join(self.spool, "requests", rid + ".json"), "w").write("{nope")
        B.drain_once(self.ctx)
        r = self.result(rid)
        self.assertEqual((r["status"], r["reason"], r["op"], r["client"]), ("refused", "bad_request", None, None))

    def test_junk_names_fifos_and_old_requests_removed_unread(self):
        os.mkfifo(os.path.join(self.spool, "requests", "0f8e2c1a-1111-4222-8333-444455556666.json"))
        open(os.path.join(self.spool, "requests", "junk.txt"), "w").close()
        rid = self.file(); old = time.time() - 7200
        os.utime(os.path.join(self.spool, "requests", rid + ".json"), (old, old))
        B.drain_once(self.ctx)                                        # must not block on the FIFO
        self.assertEqual(os.listdir(os.path.join(self.spool, "requests")), [])
        self.assertEqual(self.jobs(), [])

    def test_bounded_work_per_pass(self):
        for _ in range(B.MAX_PER_PASS + 10):
            self.file(op="list")
        B.drain_once(self.ctx)
        self.assertEqual(len(os.listdir(os.path.join(self.spool, "requests"))), 10)

    def test_journal_line_has_no_customer_id(self):
        self.file(); B.drain_once(self.ctx)
        self.assertTrue(self.logs)
        self.assertFalse(any("1234567890" in l for l in self.logs))


class TestCollect(Base):
    def done(self, rid, rc, stdout, **kw):
        d = {"job_id": rid, "rc": rc, "stdout": stdout, "timed_out": False, "interrupted": False}; d.update(kw)
        A.write_json_atomic(os.path.join(self.state, "done"), rid + ".json", d)
        os.unlink(os.path.join(self.state, "jobs", rid + ".json"))

    def test_ok_result(self):
        rid = self.file(); B.drain_once(self.ctx)
        self.done(rid, 0, json.dumps({"status": "ok", "reason": None, "exit_code": 0, "ts": "2026-10-01_10-00-00",
                                      "steps": [], "vault_path": "/var/lib/hermes/vaults/acme-dental/audits/2026-10-01_10-00-00-audit.md"}))
        B.collect_once(self.ctx)
        self.assertEqual(self.result(rid)["status"], "ok")
        self.assertEqual(os.listdir(os.path.join(self.state, "done")), [])

    def test_busy_releases_quota(self):
        rid = self.file(); B.drain_once(self.ctx)
        self.done(rid, 3, json.dumps({"status": "busy", "reason": "busy", "exit_code": 3, "ts": None,
                                      "steps": [], "vault_path": None}))
        B.collect_once(self.ctx)
        self.assertEqual(self.result(rid)["status"], "busy")
        rid2 = self.file(); B.drain_once(self.ctx)
        self.assertIsNone(self.result(rid2))                          # admitted again today

    def test_done_without_a_reservation_is_dropped(self):
        rid = "0f8e2c1a-1111-4222-8333-444455556666"
        A.write_json_atomic(os.path.join(self.state, "done"), rid + ".json",
                            {"job_id": rid, "rc": 0, "stdout": "", "timed_out": False, "interrupted": False})
        B.collect_once(self.ctx)
        self.assertIsNone(self.result(rid))
        self.assertEqual(os.listdir(os.path.join(self.state, "done")), [])


class TestRecover(Base):
    def test_reservation_with_nothing_in_flight_is_interrupted(self):
        rid = self.file(); B.drain_once(self.ctx)
        os.unlink(os.path.join(self.state, "jobs", rid + ".json"))   # lost before the runner took it
        B.recover(self.ctx)
        self.assertEqual(self.result(rid)["reason"], "interrupted")

    def test_in_flight_job_is_left_alone(self):
        rid = self.file(); B.drain_once(self.ctx)
        os.rename(os.path.join(self.state, "jobs", rid + ".json"), os.path.join(self.state, "running", rid + ".json"))
        B.recover(self.ctx)
        self.assertIsNone(self.result(rid))


class TestExpire(Base):
    def test_old_results_removed(self):
        rid = self.file(client="nobody"); B.drain_once(self.ctx)
        p = os.path.join(self.spool, "results", rid + ".json"); old = time.time() - 8 * 86400
        os.utime(p, (old, old))
        B.expire_results(self.ctx)
        self.assertFalse(os.path.exists(p))


class TestHardening(Base):
    """Controller-requested invariants beyond the brief."""

    def ledger_events(self):
        p = os.path.join(self.state, "state", "ledger.jsonl")
        return [json.loads(l) for l in open(p)] if os.path.exists(p) else []

    def done(self, rid, rc, stdout, **kw):
        d = {"job_id": rid, "rc": rc, "stdout": stdout, "timed_out": False, "interrupted": False}; d.update(kw)
        A.write_json_atomic(os.path.join(self.state, "done"), rid + ".json", d)

    def test_released_never_written_for_a_non_busy_result(self):
        outcomes = [
            (0, json.dumps({"status": "ok", "reason": None, "exit_code": 0, "ts": "2026-10-01_10-00-00",
                            "steps": [], "vault_path": None}), {}),
            (1, json.dumps({"status": "failed", "reason": "collect", "exit_code": 1, "ts": None,
                            "steps": [], "vault_path": None}), {}),
            (2, json.dumps({"status": "refused", "reason": "precheck", "exit_code": 2, "ts": None,
                            "steps": [], "vault_path": None}), {}),
            (None, "", {"timed_out": True}),
            (None, "", {"interrupted": True}),
            (0, "garbage not json", {}),
        ]
        for i, (rc, out, kw) in enumerate(outcomes):
            self.day = "2026-10-%02d" % (i + 1)                        # fresh quota each time
            rid = self.file(); B.drain_once(self.ctx)
            self.assertEqual(self.jobs(), [rid + ".json"])
            os.unlink(os.path.join(self.state, "jobs", rid + ".json"))
            self.done(rid, rc, out, **kw); B.collect_once(self.ctx)
            self.assertNotEqual(self.result(rid)["status"], "busy")
        self.assertEqual([e for e in self.ledger_events() if e["event"] == "released"], [])
        self.assertEqual(sum(e["event"] == "resulted" for e in self.ledger_events()), len(outcomes))

    def test_malformed_done_with_a_reservation_is_failed_internal(self):
        rid = self.file(); B.drain_once(self.ctx)
        os.unlink(os.path.join(self.state, "jobs", rid + ".json"))
        open(os.path.join(self.state, "done", rid + ".json"), "w").write("{not a done file")
        B.collect_once(self.ctx)
        r = self.result(rid)
        self.assertEqual((r["status"], r["reason"], r["op"], r["client"]), ("failed", "internal", "run", "acme-dental"))
        self.assertEqual(os.listdir(os.path.join(self.state, "done")), [])
        self.assertEqual([e for e in self.ledger_events() if e["event"] == "released"], [])

    def test_second_done_for_a_resulted_id_does_not_overwrite_the_first_result(self):
        rid = self.file(); B.drain_once(self.ctx)
        os.unlink(os.path.join(self.state, "jobs", rid + ".json"))
        self.done(rid, 0, json.dumps({"status": "ok", "reason": None, "exit_code": 0, "ts": "2026-10-01_10-00-00",
                                      "steps": [], "vault_path": None}))
        B.collect_once(self.ctx)
        first = self.result(rid)
        self.done(rid, 3, json.dumps({"status": "busy", "reason": "busy", "exit_code": 3, "ts": None,
                                      "steps": [], "vault_path": None}))
        B.collect_once(self.ctx)
        self.assertEqual(self.result(rid), first)
        self.assertEqual(os.listdir(os.path.join(self.state, "done")), [])
        self.assertEqual([e for e in self.ledger_events() if e["event"] == "released"], [])

    def test_runner_temp_file_in_done_is_left_alone(self):
        tmp = os.path.join(self.state, "done", ".0f8e2c1a-1111-4222-8333-444455556666.json.abc123.tmp")
        open(tmp, "w").write("{}")
        B.collect_once(self.ctx)
        self.assertTrue(os.path.exists(tmp))

    def test_registry_unreadable_or_garbage_refuses_inactive_client(self):
        for content in (None, "{garbage", "[]", '{"clients": []}', '{"clients": {"acme-dental": "active"}}'):
            if content is None:
                os.unlink(self.reg)
            else:
                open(self.reg, "w").write(content)
            rid = self.file(); B.drain_once(self.ctx)
            self.assertEqual(self.result(rid)["reason"], "inactive_client", content)
        self.assertEqual(self.jobs(), [])

    def test_trailing_newline_filename_is_not_a_request(self):
        r = A.make_request(MAN, "run", "acme-dental")
        open(os.path.join(self.spool, "requests", r["request_id"] + ".json\n"), "w").write(json.dumps(r))
        B.drain_once(self.ctx)
        self.assertEqual(os.listdir(os.path.join(self.spool, "requests")), [])
        self.assertIsNone(self.result(r["request_id"]))
        self.assertEqual(self.jobs(), [])
        self.assertEqual(self.ledger_events(), [])

    def test_journal_never_has_a_customer_id_on_any_path(self):
        rid = self.file(); B.drain_once(self.ctx)                     # queued
        self.file(); B.drain_once(self.ctx)                           # quota
        self.file(client="old-dental"); B.drain_once(self.ctx)        # inactive
        self.file(client="b-dental"); B.drain_once(self.ctx)          # queued
        os.unlink(os.path.join(self.state, "jobs", rid + ".json"))
        self.done(rid, 0, "x"); B.collect_once(self.ctx)              # failed/internal
        B.recover(self.ctx)                                           # b-dental's job still queued
        self.assertGreaterEqual(len(self.logs), 5)
        for cid in ("1234567890", "1234567891", "1234567892"):
            self.assertFalse(any(cid in l for l in self.logs), cid)


class TestFixRound1(Base):
    """Review fix round 1: directory DoS, result-before-ledger, one journal line per request."""

    def ledger_events(self):
        p = os.path.join(self.state, "state", "ledger.jsonl")
        return [json.loads(l) for l in open(p)] if os.path.exists(p) else []

    def unresolved(self):
        return [r for r, _, _ in A.Ledger(os.path.join(self.state, "state", "ledger.jsonl")).unresolved()]

    def fail_results_once(self):
        """Patch app_lib.write_json_atomic so the next write into results/ raises once."""
        orig, res_dir, state = A.write_json_atomic, os.path.join(self.spool, "results"), {"left": 1}

        def flaky(dirpath, name, obj, *a, **kw):
            if dirpath == res_dir and state["left"]:
                state["left"] -= 1
                raise OSError("disk full")
            return orig(dirpath, name, obj, *a, **kw)
        A.write_json_atomic = flaky
        self.addCleanup(setattr, A, "write_json_atomic", orig)

    def test_directories_in_requests_do_not_stop_the_broker(self):
        for name in ("0f8e2c1a-1111-4222-8333-444455556666.json", "junkdir"):
            d = os.path.join(self.spool, "requests", name)
            os.mkdir(d); open(os.path.join(d, "x"), "w").close()      # non-empty: cannot be removed
        rid = self.file()
        B.drain_once(self.ctx)                                         # must return, not raise
        self.assertEqual(self.jobs(), [rid + ".json"])
        rid2 = self.file(client="b-dental")
        B.drain_once(self.ctx)                                         # a second pass still works
        self.assertEqual(self.jobs(), sorted([rid + ".json", rid2 + ".json"]))
        self.assertEqual(sorted(os.listdir(os.path.join(self.spool, "requests"))),
                         ["0f8e2c1a-1111-4222-8333-444455556666.json", "junkdir"])
        self.assertFalse(any("junkdir" in l for l in self.logs))       # hostile names never logged

    def test_an_exception_in_one_request_costs_one_log_line_not_the_pass(self):
        bad, good = self.file(), self.file(client="b-dental")
        orig = B._admit

        def boom(ctx, req):
            if req["request_id"] == bad:
                raise RuntimeError("unexpected")
            return orig(ctx, req)
        B._admit = boom
        self.addCleanup(setattr, B, "_admit", orig)
        B.drain_once(self.ctx)
        self.assertEqual(self.jobs(), [good + ".json"])
        self.assertTrue(any("error" in l for l in self.logs))

    def test_collect_writes_the_result_before_closing_the_ledger(self):
        rid = self.file(); B.drain_once(self.ctx)
        os.unlink(os.path.join(self.state, "jobs", rid + ".json"))
        A.write_json_atomic(os.path.join(self.state, "done"), rid + ".json",
                            {"job_id": rid, "rc": 3, "timed_out": False, "interrupted": False,
                             "stdout": json.dumps({"status": "busy", "reason": "busy", "exit_code": 3, "ts": None,
                                                   "steps": [], "vault_path": None})})
        self.fail_results_once()
        B.collect_once(self.ctx)
        self.assertIsNone(self.result(rid))
        self.assertEqual(self.unresolved(), [rid])                     # still open, done file kept
        self.assertEqual(os.listdir(os.path.join(self.state, "done")), [rid + ".json"])
        self.assertEqual([e for e in self.ledger_events() if e["event"] == "released"], [])
        B.collect_once(self.ctx)
        self.assertEqual(self.result(rid)["status"], "busy")
        self.assertEqual(self.unresolved(), [])
        self.assertEqual(os.listdir(os.path.join(self.state, "done")), [])
        self.assertEqual(len([e for e in self.ledger_events() if e["event"] == "released"]), 1)

    def test_recover_writes_the_result_before_closing_the_ledger(self):
        rid = self.file(); B.drain_once(self.ctx)
        os.unlink(os.path.join(self.state, "jobs", rid + ".json"))
        self.fail_results_once()
        B.recover(self.ctx)
        self.assertIsNone(self.result(rid))
        self.assertEqual(self.unresolved(), [rid])
        B.recover(self.ctx)
        self.assertEqual(self.result(rid)["reason"], "interrupted")
        self.assertEqual(self.unresolved(), [])

    def test_refusal_writes_the_result_before_the_ledger(self):
        rid = self.file(client="nobody")
        self.fail_results_once()
        B.drain_once(self.ctx)
        self.assertIsNone(self.result(rid))
        self.assertEqual(self.ledger_events(), [])                     # nothing recorded yet
        self.assertEqual(os.listdir(os.path.join(self.spool, "requests")), [rid + ".json"])  # retried
        B.drain_once(self.ctx)
        self.assertEqual(self.result(rid)["reason"], "inactive_client")
        self.assertEqual([e["event"] for e in self.ledger_events()], ["refused"])

    def test_every_dropped_request_gets_one_journal_line(self):
        rid = self.file(client="nobody"); B.drain_once(self.ctx)        # seen
        open(os.path.join(self.spool, "requests", rid + ".json"), "w").write("{nope")
        open(os.path.join(self.spool, "requests", "junk.txt"), "w").close()
        self.logs.clear()
        B.drain_once(self.ctx)
        self.assertIn(f"hermes-app-broker[ads-audit]: request={rid} op=- client=- status=dropped reason=bad_request",
                      self.logs)
        self.assertIn("hermes-app-broker[ads-audit]: request=- op=- client=- status=dropped reason=bad_request",
                      self.logs)
        self.assertFalse(any("junk" in l for l in self.logs))


class TestFixRound2(Base):
    """Review fix round 2: a failed job write closes its reservation; an orphan result stands."""

    def ledger(self):
        return A.Ledger(os.path.join(self.state, "state", "ledger.jsonl"))

    def fail_dir_once(self, dirpath, times=1):
        orig, state = A.write_json_atomic, {"left": times}

        def flaky(d, name, obj, *a, **kw):
            if d == dirpath and state["left"]:
                state["left"] -= 1
                raise OSError("disk full")
            return orig(d, name, obj, *a, **kw)
        A.write_json_atomic = flaky
        self.addCleanup(setattr, A, "write_json_atomic", orig)

    def test_failed_job_write_closes_the_reservation_failed_internal(self):
        self.fail_dir_once(os.path.join(self.state, "jobs"))
        rid = self.file(); B.drain_once(self.ctx)
        r = self.result(rid)
        self.assertEqual((r["status"], r["reason"], r["op"], r["client"]), ("failed", "internal", "run", "acme-dental"))
        self.assertEqual(self.jobs(), [])
        self.assertEqual(self.ledger().unresolved(), [])
        self.assertEqual(self.ledger().count(self.day, "run", "acme-dental"), 1)   # a reservation counts
        self.assertEqual(os.listdir(os.path.join(self.spool, "requests")), [])

    def test_failed_job_and_result_write_leaves_the_reservation_for_recover(self):
        self.fail_dir_once(os.path.join(self.state, "jobs"))
        self.fail_dir_once(os.path.join(self.spool, "results"))
        rid = self.file(); B.drain_once(self.ctx)
        self.assertIsNone(self.result(rid))
        self.assertEqual([x[0] for x in self.ledger().unresolved()], [rid])
        B.recover(self.ctx)
        self.assertEqual(self.result(rid)["reason"], "interrupted")
        self.assertEqual(self.ledger().unresolved(), [])

    def test_orphan_result_stands_and_is_recorded(self):
        rid = self.file(client="nobody")
        A.write_json_atomic(os.path.join(self.spool, "results"), rid + ".json",
                            A.refused_result(rid, "run", "nobody", "disabled"))   # crash before ledger
        B.drain_once(self.ctx)
        self.assertEqual(self.result(rid)["reason"], "disabled")                  # not re-decided
        self.assertTrue(self.ledger().seen(rid))
        self.assertEqual(os.listdir(os.path.join(self.spool, "requests")), [])
        self.file(rid=rid, client="acme-dental"); B.drain_once(self.ctx)          # replay after: still stands
        self.assertEqual(self.result(rid)["reason"], "disabled")
        self.assertEqual(self.jobs(), [])

    def test_orphan_result_for_a_malformed_request_stands(self):
        rid = "0f8e2c1a-1111-4222-8333-444455556666"
        res = A.refused_result(rid, None, None, "disabled")
        A.write_json_atomic(os.path.join(self.spool, "results"), rid + ".json", res)
        open(os.path.join(self.spool, "requests", rid + ".json"), "w").write("{nope")
        B.drain_once(self.ctx)
        self.assertEqual(self.result(rid), res)
        self.assertTrue(self.ledger().seen(rid))


class TestFinalFix(Base):
    """Final whole-branch review: a stale temp file in jobs/ must never wedge the path unit."""

    def test_job_temp_file_is_written_outside_jobs(self):
        seen, real = [], A.tempfile.mkstemp

        def spy(*a, **kw):
            seen.append(kw.get("dir")); return real(*a, **kw)
        A.tempfile.mkstemp = spy
        self.addCleanup(setattr, A.tempfile, "mkstemp", real)
        rid = self.file(); B.drain_once(self.ctx)
        self.assertEqual(self.jobs(), [rid + ".json"])
        self.assertNotIn(os.path.join(self.state, "jobs"), seen)
        self.assertIn(os.path.join(self.state, "state"), seen)

    def test_stale_temp_files_in_jobs_are_swept_fresh_ones_kept(self):
        jobs = os.path.join(self.state, "jobs")
        old, new = os.path.join(jobs, ".x.json.old.tmp"), os.path.join(jobs, ".y.json.new.tmp")
        open(old, "w").close(); open(new, "w").close()
        t = time.time() - B.REQUEST_MAX_AGE - 10
        os.utime(old, (t, t))
        B.collect_once(self.ctx)
        self.assertEqual(self.jobs(), [".y.json.new.tmp"])


if __name__ == "__main__":
    unittest.main()
