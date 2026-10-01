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


if __name__ == "__main__":
    unittest.main()
