#!/usr/bin/env python3
import importlib.util, io, json, os, shutil, sys, tempfile, unittest
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import app_lib as A
spec = importlib.util.spec_from_file_location("mcp", os.path.join(HERE, "hermes-app-mcp.py"))
M = importlib.util.module_from_spec(spec); spec.loader.exec_module(M)
MAN = A.load_manifest(os.path.join(os.path.dirname(HERE), "registry/apps/ads-audit.json"), "ads-audit")


class T(unittest.TestCase):
    def setUp(self):
        self.spool = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.spool, True)
        for d in ("requests", "results"):
            os.makedirs(os.path.join(self.spool, d))
        self.t = [0.0]
        self.s = M.Server(MAN, self.spool, sleep=lambda s: self.t.__setitem__(0, self.t[0] + s),
                          clock=lambda: self.t[0])

    def call(self, name, **args):
        r = self.s.handle({"jsonrpc": "2.0", "id": 7, "method": "tools/call",
                           "params": {"name": name, "arguments": args}})
        return r["result"]

    def test_initialize_echoes_supported_version(self):
        r = self.s.handle({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                           "params": {"protocolVersion": "2025-06-18", "capabilities": {}}})
        self.assertEqual(r["result"]["protocolVersion"], "2025-06-18")
        self.assertIn("tools", r["result"]["capabilities"])

    def test_notifications_get_no_reply(self):
        self.assertIsNone(self.s.handle({"jsonrpc": "2.0", "method": "notifications/initialized"}))

    def test_exactly_three_tools(self):
        r = self.s.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        self.assertEqual(sorted(t["name"] for t in r["result"]["tools"]),
                         ["ads_audit_list", "ads_audit_run", "ads_audit_status"])

    def test_run_writes_a_valid_request_and_returns_pending(self):
        res = self.call("ads_audit_run", client="acme-dental")
        body = json.loads(res["content"][0]["text"])
        self.assertEqual(body["status"], "pending"); self.assertFalse(res["isError"])
        names = os.listdir(os.path.join(self.spool, "requests"))
        self.assertEqual(len(names), 1)
        req = A.parse_request(open(os.path.join(self.spool, "requests", names[0]), "rb").read(), names[0], MAN)
        self.assertEqual((req["op"], req["client"]), ("run", "acme-dental"))
        self.assertGreaterEqual(self.t[0], 300)            # waited the manifest's run budget

    def test_run_returns_the_result_when_it_appears(self):
        def sleep(s):
            names = os.listdir(os.path.join(self.spool, "requests"))
            rid = names[0][:-5]
            A.write_json_atomic(os.path.join(self.spool, "results"), rid + ".json",
                                A.refused_result(rid, "run", "acme-dental", "quota"))
        self.s.sleep = sleep
        body = json.loads(self.call("ads_audit_run", client="acme-dental")["content"][0]["text"])
        self.assertEqual((body["status"], body["reason"]), ("refused", "quota"))

    def test_bad_slug_is_an_error_and_files_nothing(self):
        res = self.call("ads_audit_run", client="../etc")
        self.assertTrue(res["isError"])
        self.assertEqual(os.listdir(os.path.join(self.spool, "requests")), [])

    def test_trailing_newline_is_not_a_slug_or_request_id(self):
        self.assertTrue(self.call("ads_audit_run", client="acme-dental\n")["isError"])
        self.assertEqual(os.listdir(os.path.join(self.spool, "requests")), [])
        self.assertTrue(self.call("ads_audit_status",
                                  request_id="0f8e2c1a-1111-4222-8333-444455556666\n")["isError"])

    def test_status_never_files_a_request(self):
        rid = "0f8e2c1a-1111-4222-8333-444455556666"
        body = json.loads(self.call("ads_audit_status", request_id=rid)["content"][0]["text"])
        self.assertEqual(body, {"status": "pending", "request_id": rid})
        self.assertEqual(os.listdir(os.path.join(self.spool, "requests")), [])
        self.assertTrue(self.call("ads_audit_status", request_id="../x")["isError"])

    def test_garbage_result_file_is_pending_not_a_crash(self):
        rid = "0f8e2c1a-1111-4222-8333-444455556666"
        for junk in (b"not json {{", b"[1, 2]", b"\xff\xfe", b'"str"'):
            with open(os.path.join(self.spool, "results", rid + ".json"), "wb") as f:
                f.write(junk)
            body = json.loads(self.call("ads_audit_status", request_id=rid)["content"][0]["text"])
            self.assertEqual(body, {"status": "pending", "request_id": rid}, junk)

    def test_status_returns_a_present_result_verbatim(self):
        rid = "0f8e2c1a-1111-4222-8333-444455556666"
        A.write_json_atomic(os.path.join(self.spool, "results"), rid + ".json",
                            A.refused_result(rid, "run", "acme-dental", "quota"))
        res = self.call("ads_audit_status", request_id=rid)
        body = json.loads(res["content"][0]["text"])
        self.assertEqual((body["status"], body["reason"]), ("refused", "quota"))
        self.assertFalse(res["isError"])               # a refusal is never a retryable error

    def test_unknown_method_and_tool(self):
        self.assertEqual(self.s.handle({"jsonrpc": "2.0", "id": 3, "method": "resources/list"})["error"]["code"], -32601)
        self.assertTrue(self.call("delete_everything")["isError"])


class StdioLoop(unittest.TestCase):
    def run_main(self, lines, boom=False):
        d = tempfile.mkdtemp(); self.addCleanup(shutil.rmtree, d, True)
        os.makedirs(os.path.join(d, "spool", "ads-audit", "requests"))
        os.makedirs(os.path.join(d, "spool", "ads-audit", "results"))
        mdir = os.path.join(d, "man")
        os.makedirs(mdir)
        shutil.copy(os.path.join(os.path.dirname(HERE), "registry/apps/ads-audit.json"), mdir)
        old = sys.stdin, sys.stdout, M.Server.handle
        sys.stdin, sys.stdout = io.StringIO("".join(l + "\n" for l in lines)), io.StringIO()
        if boom:
            def handle(self, msg):
                raise RuntimeError("boom")
            M.Server.handle = handle
        try:
            M.main(["--app", "ads-audit", "--manifest-dir", mdir, "--spool-root", os.path.join(d, "spool")])
            return [json.loads(l) for l in sys.stdout.getvalue().splitlines()]
        finally:
            sys.stdin, sys.stdout, M.Server.handle = old

    def test_non_dict_lines_do_not_kill_the_loop(self):
        out = self.run_main(["[1,2]", "5", '"x"', "null", "garbage",
                             json.dumps({"jsonrpc": "2.0", "id": 9, "method": "ping"})])
        self.assertEqual(out[-1], {"jsonrpc": "2.0", "id": 9, "result": {}})
        self.assertEqual([o["error"]["code"] for o in out[:-1]], [-32600] * 4 + [-32700])

    def test_exception_in_handle_is_internal_error_and_loop_survives(self):
        out = self.run_main([json.dumps({"jsonrpc": "2.0", "id": 4, "method": "ping"}),
                             json.dumps({"jsonrpc": "2.0", "method": "notifications/x"}),
                             json.dumps({"jsonrpc": "2.0", "id": 5, "method": "ping"})], boom=True)
        self.assertEqual([(o["id"], o["error"]["code"]) for o in out], [(4, -32603), (5, -32603)])


if __name__ == "__main__":
    unittest.main()
