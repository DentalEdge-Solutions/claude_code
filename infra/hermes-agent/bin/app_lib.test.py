#!/usr/bin/env python3
import json, os, stat, tempfile, unittest
HERE = os.path.dirname(os.path.abspath(__file__)); import sys; sys.path.insert(0, HERE)
from unittest import mock
import app_lib as A

MANIFEST = os.path.join(os.path.dirname(HERE), "registry", "apps", "ads-audit.json")
RID = "0f8e2c1a-1111-4222-8333-444455556666"


def m():
    return A.load_manifest(MANIFEST, "ads-audit")


class TestManifest(unittest.TestCase):
    def test_repo_manifest_loads(self):
        man = m()
        self.assertEqual(man.user, "hermes-app-ads-audit")
        self.assertEqual(man.ops["run"]["args"], ["--json"])
        self.assertEqual(man.tools["status"], "ads_audit_status")

    def test_unknown_key_or_wrong_app_refused(self):
        raw = json.load(open(MANIFEST))
        for mutate in (lambda d: d.update(extra=1), lambda d: d.update(app="other"),
                       lambda d: d.update(user="root"), lambda d: d.update(command="run-client-audit"),
                       lambda d: d["ops"]["run"]["args"].append("; rm -rf /"),
                       lambda d: d["ops"].update(undo={"args": [], "timeout": 1, "quota": {}})):
            d = json.loads(json.dumps(raw)); mutate(d)
            p = tempfile.mktemp(); json.dump(d, open(p, "w"))
            with self.subTest(d=d), self.assertRaises(ValueError):
                A.load_manifest(p, "ads-audit")


class TestRequest(unittest.TestCase):
    def good(self, **kw):
        d = {"request_id": RID, "app": "ads-audit", "op": "run", "client": "acme-dental"}; d.update(kw)
        return json.dumps(d).encode()

    def test_good(self):
        r = A.parse_request(self.good(), RID + ".json", m())
        self.assertEqual(r["client"], "acme-dental")

    def test_refusals(self):
        man = m()
        for data, name in ((self.good(), "x.json"), (self.good(request_id="0" * 36), RID + ".json"),
                           (self.good(app="other"), RID + ".json"), (self.good(op="undo"), RID + ".json"),
                           (self.good(client="../x"), RID + ".json"), (b"{", RID + ".json"),
                           (json.dumps({"request_id": RID}).encode(), RID + ".json"),
                           (self.good()[:-1] + b', "x": 1}', RID + ".json")):
            with self.subTest(data=data, name=name), self.assertRaises(A.Refused):
                A.parse_request(data, name, man)

    def test_make_request_round_trips(self):
        r = A.make_request(m(), "list", "acme-dental")
        self.assertEqual(A.parse_request(json.dumps(r).encode(), r["request_id"] + ".json", m()), r)


class TestReadCapped(unittest.TestCase):
    def test_symlink_fifo_and_oversize_refused(self):
        d = tempfile.mkdtemp()
        big = os.path.join(d, "big"); open(big, "wb").write(b"x" * 2000)
        link = os.path.join(d, "l"); os.symlink(big, link)
        fifo = os.path.join(d, "f"); os.mkfifo(fifo)
        for p in (big, link, fifo):
            with self.subTest(p=p), self.assertRaises(A.Refused):
                A.read_capped(p, 1024)


REQ = {"request_id": RID, "app": "ads-audit", "op": "run", "client": "acme-dental"}
OK_STDOUT = json.dumps({"status": "ok", "reason": None, "exit_code": 0, "ts": "2026-10-01_12-00-00",
                        "steps": [{"name": "collect", "rc": 0, "seconds": 10.0}],
                        "vault_path": "/var/lib/hermes/vaults/acme-dental/audits/2026-10-01_12-00-00-audit.md"})


def done(rc=0, stdout=OK_STDOUT, **kw):
    d = {"job_id": RID, "rc": rc, "stdout": stdout + "\n", "timed_out": False, "interrupted": False}; d.update(kw)
    return d


class TestMapDone(unittest.TestCase):
    def test_ok(self):
        r = A.map_done(REQ, done(), m())
        self.assertEqual((r["status"], r["reason"], r["exit_code"]), ("ok", None, 0))
        self.assertEqual(set(r), {"request_id", "op", "client", "status", "reason", "exit_code", "ts",
                                  "steps", "vault_path"})

    def test_timeout_and_interrupted(self):
        self.assertEqual(A.map_done(REQ, done(rc=None, stdout="", timed_out=True), m())["reason"], "timeout")
        self.assertEqual(A.map_done(REQ, done(rc=None, stdout="", interrupted=True), m())["reason"], "interrupted")

    def test_out_of_contract_is_internal(self):
        bad = [
            json.dumps({**json.loads(OK_STDOUT), "extra": "x"}),
            json.dumps({**json.loads(OK_STDOUT), "vault_path": "/var/lib/hermes/vaults/other-dental/audits/2026-10-01_12-00-00-audit.md"}),
            json.dumps({**json.loads(OK_STDOUT), "status": "failed"}),        # rc 0 but failed
            json.dumps({**json.loads(OK_STDOUT), "reason": "free text here"}),
            json.dumps({**json.loads(OK_STDOUT), "steps": [{"name": "rm -rf", "rc": 0, "seconds": 1}]}),
            "not json", OK_STDOUT + "\n" + OK_STDOUT,
        ]
        for s in bad:
            with self.subTest(s=s):
                r = A.map_done(REQ, done(stdout=s), m())
                self.assertEqual((r["status"], r["reason"]), ("failed", "internal"))

    def test_busy_and_precheck(self):
        busy = json.dumps({"status": "busy", "reason": "busy", "exit_code": 3, "ts": None, "steps": [], "vault_path": None})
        self.assertEqual(A.map_done(REQ, done(rc=3, stdout=busy), m())["status"], "busy")
        pre = json.dumps({"status": "refused", "reason": "precheck", "exit_code": 2, "ts": None, "steps": [], "vault_path": None})
        self.assertEqual(A.map_done(REQ, done(rc=2, stdout=pre), m())["reason"], "precheck")

    def test_list(self):
        req = dict(REQ, op="list")
        r = A.map_done(req, done(stdout=json.dumps({"status": "ok", "audits": ["2026-10-01_12-00-00"]})), m())
        self.assertEqual((r["status"], r["audits"]), ("ok", ["2026-10-01_12-00-00"]))
        r = A.map_done(req, done(stdout=json.dumps({"status": "ok", "audits": ["../etc"]})), m())
        self.assertEqual(r["reason"], "internal")

    def test_list_internal_failure_payload_is_internal(self):
        req = dict(REQ, op="list")
        r = A.map_done(req, done(rc=1, stdout=json.dumps({"reason": "internal", "status": "failed"})), m())
        self.assertEqual((r["status"], r["reason"], r["audits"]), ("failed", "internal", []))

    def test_sigterm_rc_143_is_internal(self):
        s = json.dumps({"status": "failed", "reason": "internal", "exit_code": 143, "ts": None,
                        "steps": [], "vault_path": None})
        r = A.map_done(REQ, done(rc=143, stdout=s), m())
        self.assertEqual((r["status"], r["reason"], r["exit_code"]), ("failed", "internal", None))


class TestLedger(unittest.TestCase):
    def test_counts_seen_unresolved(self):
        L = A.Ledger(os.path.join(tempfile.mkdtemp(), "ledger.jsonl"))
        L.append("reserved", "a" * 36, "run", "acme", now="2026-10-01T10:00:00Z")
        L.append("reserved", "b" * 36, "run", "other", now="2026-10-01T11:00:00Z")
        L.append("released", "b" * 36, now="2026-10-01T11:05:00Z")
        L.append("reserved", "c" * 36, "run", "acme", now="2026-10-02T10:00:00Z")
        L.append("resulted", "c" * 36, now="2026-10-02T10:10:00Z")
        self.assertEqual(L.count("2026-10-01", "run"), 1)
        self.assertEqual(L.count("2026-10-01", "run", "acme"), 1)
        self.assertEqual(L.count("2026-10-01", "run", "other"), 0)
        self.assertTrue(L.seen("b" * 36)); self.assertFalse(L.seen("d" * 36))
        self.assertEqual(L.unresolved(), [("a" * 36, "run", "acme")])
        self.assertEqual(L.reserved("a" * 36), ("run", "acme"))

    def test_torn_last_line_ignored(self):
        p = os.path.join(tempfile.mkdtemp(), "l"); L = A.Ledger(p)
        L.append("reserved", "a" * 36, "run", "acme", now="2026-10-01T10:00:00Z")
        open(p, "a").write('{"event": "res')
        self.assertTrue(L.seen("a" * 36))


class TestLedgerIndex(unittest.TestCase):
    """The broker's per-pass in-memory index must answer exactly what the Ledger methods do."""

    def check(self, L, idx, rids, days, ops, clients):
        for r in rids:
            self.assertEqual(idx.seen(r), L.seen(r), r)
            self.assertEqual(idx.reserved(r), L.reserved(r), r)
        for d in days:
            for o in ops:
                for c in clients + [None]:
                    self.assertEqual(idx.count(d, o, c), L.count(d, o, c), (d, o, c))
        self.assertEqual(idx.unresolved(), L.unresolved())

    def test_index_matches_the_ledger_on_a_mixed_log_and_after_appends(self):
        p = os.path.join(tempfile.mkdtemp(), "ledger.jsonl"); L = A.Ledger(p)
        a, b, c, d, e = ("%s" % ch * 36 for ch in "abcde")
        L.append("released", c, now="2026-10-01T09:00:00Z")            # before its reservation: no effect
        L.append("reserved", a, "run", "acme", now="2026-10-01T10:00:00Z")
        L.append("reserved", b, "run", "other", now="2026-10-01T11:00:00Z")
        L.append("reserved", c, "list", "acme", now="2026-10-01T11:30:00Z")
        L.append("released", b, now="2026-10-01T11:05:00Z")
        L.append("refused", d, None, None, now="2026-10-01T12:00:00Z")
        L.append("reserved", e, "run", "acme", now="2026-10-02T10:00:00Z")
        L.append("resulted", e, now="2026-10-02T10:10:00Z")
        L.append("reserved", b, "run", "other", now="2026-10-02T11:00:00Z")  # re-reserved after release
        open(p, "a").write('{"event": "res')                           # torn last line
        idx = L.index()
        rids, days = [a, b, c, d, e, "f" * 36], ["2026-10-01", "2026-10-02", "2026-10-03"]
        ops, clients = ["run", "list"], ["acme", "other"]
        self.check(L, idx, rids, days, ops, clients)
        self.assertEqual(idx.refused_on("2026-10-01"), 1)
        self.assertEqual(idx.refused_on("2026-10-02"), 0)
        for ev in (("released", a, None, None, "2026-10-02T12:00:00Z"),
                   ("reserved", "f" * 36, "list", "other", "2026-10-03T08:00:00Z"),
                   ("resulted", c, None, None, "2026-10-03T09:00:00Z"),
                   ("refused", "g" * 36, None, None, "2026-10-03T09:30:00Z")):
            idx.apply(L.append(ev[0], ev[1], ev[2], ev[3], now=ev[4]))
            self.check(L, idx, rids + ["g" * 36], days, ops, clients)
        self.assertEqual(idx.refused_on("2026-10-03"), 1)


class TestWrite(unittest.TestCase):
    def test_atomic_mode(self):
        d = tempfile.mkdtemp()
        A.write_json_atomic(d, RID + ".json", {"a": 1})
        p = os.path.join(d, RID + ".json")
        self.assertEqual(json.load(open(p)), {"a": 1})
        self.assertEqual(stat.S_IMODE(os.stat(p).st_mode), 0o640)
        self.assertEqual([n for n in os.listdir(d) if n.endswith(".tmp")], [])

    def test_tmpdir_keeps_the_temp_file_out_of_the_target_dir(self):
        d, t = tempfile.mkdtemp(), tempfile.mkdtemp()
        seen = []
        real = A.tempfile.mkstemp

        def spy(*a, **kw):
            seen.append(kw.get("dir")); return real(*a, **kw)
        with mock.patch.object(A.tempfile, "mkstemp", spy):
            A.write_json_atomic(d, RID + ".json", {"a": 1}, tmpdir=t)
        self.assertEqual(seen, [t])
        self.assertEqual(json.load(open(os.path.join(d, RID + ".json"))), {"a": 1})
        self.assertEqual(os.listdir(t), [])


class TestHardening(unittest.TestCase):
    """Holes in the brief's code found in self-review: each is hostile input reaching past a
    parser. Trailing newline: `re.match` with `$` accepts "x\n" (governance_lib._slug's
    fullmatch rule)."""

    def test_trailing_newline_client_refused(self):
        d = json.dumps({"request_id": RID, "app": "ads-audit", "op": "run", "client": "acme-dental\n"})
        with self.assertRaises(A.Refused):
            A.parse_request(d.encode(), RID + ".json", m())

    def test_unhashable_op_refused_not_typeerror(self):
        d = json.dumps({"request_id": RID, "app": "ads-audit", "op": ["run"], "client": "acme-dental"})
        with self.assertRaises(A.Refused):
            A.parse_request(d.encode(), RID + ".json", m())

    def test_non_string_job_id_in_done_refused(self):
        d = json.dumps({"job_id": 1, "rc": 0, "stdout": "", "timed_out": False, "interrupted": False})
        with self.assertRaises(A.Refused):
            A.parse_done(d.encode(), RID + ".json")

    def test_trailing_newline_values_in_stdout_are_internal(self):
        ok = json.loads(OK_STDOUT)
        for s in (json.dumps({**ok, "ts": ok["ts"] + "\n"}),
                  json.dumps({**ok, "vault_path": ok["vault_path"] + "\n"})):
            with self.subTest(s=s):
                self.assertEqual(A.map_done(REQ, done(stdout=s), m())["reason"], "internal")
        r = A.map_done(dict(REQ, op="list"),
                       done(stdout=json.dumps({"status": "ok", "audits": ["2026-10-01_12-00-00\n"]})), m())
        self.assertEqual((r["status"], r["reason"]), ("failed", "internal"))

    def test_rc_none_without_timeout_is_internal_not_null_status(self):
        s = json.dumps({"status": None, "reason": "internal", "exit_code": None, "ts": None,
                        "steps": [], "vault_path": None})
        r = A.map_done(REQ, done(rc=None, stdout=s), m())
        self.assertEqual((r["status"], r["reason"]), ("failed", "internal"))

    def test_ledger_skips_non_object_lines(self):
        p = os.path.join(tempfile.mkdtemp(), "l"); L = A.Ledger(p)
        open(p, "w").write("123\n[1]\n")
        L.append("reserved", "a" * 36, "run", "acme", now="2026-10-01T10:00:00Z")
        self.assertEqual(L.unresolved(), [("a" * 36, "run", "acme")])
        self.assertEqual(L.count("2026-10-01", "run"), 1)

    def test_atomic_uid_without_gid_keeps_group(self):
        d = tempfile.mkdtemp()
        A.write_json_atomic(d, RID + ".json", {"a": 1}, uid=os.getuid())
        self.assertEqual(os.stat(os.path.join(d, RID + ".json")).st_gid, os.stat(d).st_gid)


class TestFixRound1(unittest.TestCase):
    def ledger(self):
        p = os.path.join(tempfile.mkdtemp(), "ledger.jsonl")
        return p, A.Ledger(p)

    def test_append_after_torn_line_is_not_lost(self):
        p, L = self.ledger()
        L.append("reserved", "a" * 36, "run", "acme", now="2026-10-01T10:00:00Z")
        with open(p, "a") as f:
            f.write('{"event": "res')
        L.append("reserved", "b" * 36, "run", "other", now="2026-10-01T11:00:00Z")
        self.assertTrue(L.seen("b" * 36))
        self.assertEqual(L.count("2026-10-01", "run"), 2)
        self.assertEqual(L.unresolved(), [("a" * 36, "run", "acme"), ("b" * 36, "run", "other")])

    def test_release_before_reservation_cancels_nothing(self):
        p, L = self.ledger()
        L.append("released", "x" * 36, now="2026-10-01T10:00:00Z")
        L.append("reserved", "x" * 36, "run", "acme", now="2026-10-02T10:00:00Z")
        self.assertEqual(L.count("2026-10-02", "run"), 1)
        self.assertEqual(L.unresolved(), [("x" * 36, "run", "acme")])

    def test_release_after_reservation_still_cancels(self):
        p, L = self.ledger()
        L.append("reserved", "x" * 36, "run", "acme", now="2026-10-02T10:00:00Z")
        L.append("released", "x" * 36, now="2026-10-02T10:01:00Z")
        self.assertEqual(L.count("2026-10-02", "run"), 0)

    def run_payload(self, rc, status, reason, vault_path=None):
        return json.dumps({"status": status, "reason": reason, "exit_code": rc, "ts": None,
                           "steps": [], "vault_path": vault_path})

    def test_reason_tied_to_status(self):
        for rc, status, reason in ((3, "busy", "vault-write"), (2, "refused", "collect"),
                                   (1, "failed", "precheck"), (1, "failed", "busy"),
                                   (3, "busy", "precheck"), (2, "refused", "internal"),
                                   (0, "ok", "internal")):
            with self.subTest(status=status, reason=reason):
                r = A.map_done(REQ, done(rc=rc, stdout=self.run_payload(rc, status, reason)), m())
                self.assertEqual((r["status"], r["reason"]), ("failed", "internal"))

    def test_consistent_reasons_pass(self):
        for rc, status, reason in ((3, "busy", "busy"), (2, "refused", "precheck"),
                                   (1, "failed", "internal"), (1, "failed", "vault-write"),
                                   (1, "failed", "collect")):
            with self.subTest(status=status, reason=reason):
                r = A.map_done(REQ, done(rc=rc, stdout=self.run_payload(rc, status, reason)), m())
                self.assertEqual((r["status"], r["reason"]), (status, reason))

    def test_vault_path_ts_must_equal_ts(self):
        ok = json.loads(OK_STDOUT)
        s = json.dumps({**ok, "vault_path": "/var/lib/hermes/vaults/acme-dental/audits/2026-10-01_12-00-01-audit.md"})
        r = A.map_done(REQ, done(stdout=s), m())
        self.assertEqual((r["status"], r["reason"]), ("failed", "internal"))
        s = json.dumps({**ok, "ts": None})
        self.assertEqual(A.map_done(REQ, done(stdout=s), m())["reason"], "internal")
        self.assertEqual(A.map_done(REQ, done(), m())["status"], "ok")


class TestWhitelist(unittest.TestCase):
    VP = "/var/lib/hermes/vaults/acme-dental/audits/2026-10-01_12-00-00-audit.md"

    def _run(self, rc, **payload):
        p = {"status": A.RC_STATUS[rc], "reason": None, "exit_code": rc, "ts": None, "steps": [], "vault_path": None}
        p.update(payload)
        return A.map_done(REQ, done(rc=rc, stdout=json.dumps(p)), m())

    def _list(self, rc, payload):
        return A.map_done(dict(REQ, op="list"), done(rc=rc, stdout=json.dumps(payload)), m())

    def test_result_in_whitelist(self):
        ok = A.refused_result("0f8e2c1a-1111-4222-8333-444455556666", "run", "acme", "quota")
        self.assertEqual(A.result_in_whitelist(ok), (True, True))
        self.assertEqual(A.result_in_whitelist(dict(ok, reason="free text")), (True, False))
        self.assertEqual(A.result_in_whitelist(dict(ok, extra=1)), (False, False))

    def test_everything_the_broker_writes_is_in_whitelist(self):
        step = {"name": "proxy", "rc": 1, "seconds": 2.5}
        written = [A.refused_result(RID, None, None, "bad_request")]
        written += [A.refused_result(RID, op, "acme-dental", r)
                    for op in A.KNOWN_OPS for r in ("disabled", "inactive_client", "quota")]
        written += [A.refused_result(RID, op, "acme-dental", r, status="failed")
                    for op in A.KNOWN_OPS for r in ("internal", "interrupted", "timeout")]
        written += [
            A.map_done(REQ, done(), m()),                                          # ok, with its vault path
            self._run(0, ts="2026-10-01_12-00-00"),                                # ok, nothing written
            self._run(3, reason="busy"),
            self._run(2, reason="precheck"),
            self._run(1, reason="proxy", ts="2026-10-01_12-00-00", steps=[dict(step, name="collect", rc=0), step]),
            self._run(1, reason="internal"),
            A.map_done(REQ, done(rc=None, stdout="", timed_out=True), m()),
            A.map_done(REQ, done(rc=None, stdout="", interrupted=True), m()),
            A.map_done(REQ, done(stdout="not json"), m()),
            self._list(0, {"status": "ok", "audits": []}),
            self._list(0, {"status": "ok", "audits": ["2026-10-01_12-00-00"] * A.LIST_LIMIT}),
            self._list(2, {"status": "refused", "reason": "precheck"}),
            self._list(1, {"status": "failed", "reason": "internal"}),
        ]
        expect = [("refused", "bad_request")] + [("refused", r) for _ in A.KNOWN_OPS
                                                 for r in ("disabled", "inactive_client", "quota")] \
            + [("failed", r) for _ in A.KNOWN_OPS for r in ("internal", "interrupted", "timeout")] \
            + [("ok", None), ("ok", None), ("busy", "busy"), ("refused", "precheck"), ("failed", "proxy"),
               ("failed", "internal"), ("failed", "timeout"), ("failed", "interrupted"), ("failed", "internal"),
               ("ok", None), ("ok", None), ("refused", "precheck"), ("failed", "internal")]
        self.assertEqual([(r["status"], r["reason"]) for r in written], expect)   # the fixtures are what they claim
        for r in written:
            with self.subTest(r=r):
                self.assertEqual(A.result_in_whitelist(json.loads(json.dumps(r))), (True, True))

    def test_what_the_broker_cannot_write_is_out(self):
        ok = A.map_done(REQ, done(), m())
        lst = self._list(0, {"status": "ok", "audits": ["2026-10-01_12-00-00"]})
        refused = A.refused_result(RID, "run", "acme-dental", "quota")
        bad = [
            dict(ok, reason="free text"), dict(ok, status="done"), dict(ok, status=["ok"]), dict(ok, reason=["x"]),
            dict(ok, reason={"a": 1}), dict(ok, status="failed"), dict(ok, exit_code=1), dict(ok, exit_code="0"),
            dict(ok, exit_code=True), dict(ok, exit_code=0.0), dict(ok, exit_code=None),
            dict(ok, ts="2026-10-01_12-00-00\n"), dict(ok, ts="yesterday"), dict(ok, ts=None), dict(ok, ts=5),
            dict(ok, vault_path=self.VP + "\n"), dict(ok, vault_path=self.VP.replace("acme-dental", "other-dental")),
            dict(ok, vault_path=self.VP.replace("12-00-00", "12-00-01")), dict(ok, vault_path="/etc/passwd"),
            dict(ok, vault_path=["x"]),
            dict(ok, steps=["rm -rf /"]), dict(ok, steps="collect"), dict(ok, steps=None),
            dict(ok, steps=[{"name": "collect", "rc": 0, "seconds": 1, "note": "free text"}]),
            dict(ok, steps=[{"name": "free text", "rc": 0, "seconds": 1}]),
            dict(ok, steps=[{"name": "collect", "rc": "0", "seconds": 1}]),
            dict(ok, steps=[{"name": "collect", "rc": 0, "seconds": True}]),
            dict(ok, steps=[{"name": "collect", "rc": 0, "seconds": 1}] * (len(A.STEP_CLASSES) + 1)),
            dict(ok, request_id="not-a-request-id"), dict(ok, request_id=RID + "\n"), dict(ok, request_id=7),
            dict(ok, client="Not A Slug"), dict(ok, client="acme-dental\n"), dict(ok, client=["acme-dental"]),
            dict(ok, client=None), dict(ok, op="list"), dict(ok, op="undo"), dict(ok, op=None), dict(ok, op=["run"]),
            dict(refused, reason="duplicate"),                    # journalled, never written as a result
            dict(refused, reason="precheck"),                     # a run's precheck carries exit code 2
            dict(refused, reason="timeout"), dict(refused, status="failed"), dict(refused, status="ok", reason=None),
            dict(refused, status="busy", reason="busy"), dict(refused, steps=[{"name": "collect", "rc": 0, "seconds": 1}]),
            dict(refused, op=None), dict(refused, client=None), dict(refused, op=None, client=None),
            dict(refused, reason="bad_request"),                  # bad_request never knows the op or the client
            dict(A.refused_result(RID, None, None, "bad_request"), ts="2026-10-01_12-00-00"),
            dict(self._run(1, reason="proxy"), reason="timeout"), dict(self._run(3, reason="busy"), reason=None),
            dict(lst, audits=["../etc"]), dict(lst, audits=["2026-10-01_12-00-00\n"]), dict(lst, audits=[7]),
            dict(lst, audits="2026-10-01_12-00-00"), dict(lst, audits=None),
            dict(lst, audits=["2026-10-01_12-00-00"] * (A.LIST_LIMIT + 1)),
            dict(lst, reason="quota"), dict(lst, status="refused", reason="quota"), dict(lst, status="busy", reason="busy"),
            dict(lst, op="run"), dict(lst, op=None, client=None, status="refused", reason="bad_request", audits=[]),
            dict(lst, status="failed", reason="proxy", audits=[]),
        ]
        for r in bad:
            with self.subTest(r=r):
                self.assertEqual(A.result_in_whitelist(json.loads(json.dumps(r))), (True, False))

    def test_wrong_keys_and_non_objects(self):
        ok = A.map_done(REQ, done(), m())
        missing = dict(ok); del missing["steps"]
        both = dict(ok, audits=[])
        for r in (None, True, 0, 1.5, "ok", [], [ok], {}, missing, both, dict(ok, note="x"), {"status": "ok"}):
            with self.subTest(r=r):
                self.assertEqual(A.result_in_whitelist(r), (False, False))

    def test_never_raises_on_any_json_value_in_any_field(self):
        hostile = (None, True, False, 0, -1, 1.5, 10 ** 30, "", "X y", "\n", [], [[]], [None], ["x"], {}, {"a": [1]},
                   [{"name": ["collect"], "rc": {}, "seconds": []}], [{"name": None, "rc": None, "seconds": None}])
        bases = (A.map_done(REQ, done(), m()), A.refused_result(RID, "run", "acme-dental", "quota"),
                 self._run(1, reason="proxy"), self._list(0, {"status": "ok", "audits": ["2026-10-01_12-00-00"]}),
                 A.refused_result(RID, "list", "acme-dental", "quota"), A.refused_result(RID, None, None, "bad_request"))
        for base in bases:
            for k in base:
                for v in hostile:
                    r = dict(base, **{k: v})
                    with self.subTest(k=k, v=v):
                        keys_ok, values_ok = A.result_in_whitelist(r)
                        self.assertIs(keys_ok, True)
                        # Only the unchanged value is in whitelist (compared as JSON: False is not 0),
                        # plus the three substitutions that give another result the broker can write.
                        same = json.dumps(r, sort_keys=True) == json.dumps(base, sort_keys=True)
                        self.assertIs(values_ok, same or (k, v) in (("audits", []), ("steps", []),
                                                                    ("vault_path", None)))


if __name__ == "__main__":
    unittest.main()
