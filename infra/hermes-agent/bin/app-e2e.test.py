#!/usr/bin/env python3
"""Option B end to end in temp dirs: MCP tool call -> spool -> broker -> job -> runner -> stub
command -> done -> broker -> result -> MCP. No Docker, no root: the runner's owner is None."""
import importlib.util, json, os, sys, tempfile, threading, unittest
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import app_lib as A


def load(name, file):
    s = importlib.util.spec_from_file_location(name, os.path.join(HERE, file))
    m = importlib.util.module_from_spec(s); s.loader.exec_module(m); return m


MCP, BRK, RUN = load("mcp", "hermes-app-mcp.py"), load("brk", "hermes-app-broker.py"), load("run", "hermes-app-runner.py")
STUB = """#!/bin/sh
slug="$1"; shift
if [ "$1" = "--list" ]; then echo '{"status": "ok", "audits": ["2026-09-30_10-00-00"]}'; exit 0; fi
echo "{\\"status\\": \\"ok\\", \\"reason\\": null, \\"exit_code\\": 0, \\"ts\\": \\"2026-10-01_12-00-00\\", \\"steps\\": [{\\"name\\": \\"draft\\", \\"rc\\": 0, \\"seconds\\": 1.0}], \\"vault_path\\": \\"/var/lib/hermes/vaults/$slug/audits/2026-10-01_12-00-00-audit.md\\"}"
"""


class E2E(unittest.TestCase):
    def setUp(self):
        t = tempfile.mkdtemp()
        stub = os.path.join(t, "stub"); open(stub, "w").write(STUB); os.chmod(stub, 0o755)
        raw = json.load(open(os.path.join(os.path.dirname(HERE), "registry/apps/ads-audit.json")))
        raw["command"] = stub
        mdir = os.path.join(t, "apps"); os.makedirs(mdir)
        json.dump(raw, open(os.path.join(mdir, "ads-audit.json"), "w"))
        self.m = A.load_manifest(os.path.join(mdir, "ads-audit.json"), "ads-audit")
        self.spool, self.state = os.path.join(t, "spool"), os.path.join(t, "state")
        for d in ("requests", "results"):
            os.makedirs(os.path.join(self.spool, d))
        for d in ("state", "jobs", "running", "done"):
            os.makedirs(os.path.join(self.state, d))
        reg = os.path.join(t, "clients.json")
        json.dump({"clients": {"acme-dental": {"status": "active", "customer_id": "1234567890"}}}, open(reg, "w"))
        self.ctx = BRK.Ctx(self.m, self.spool, self.state, reg, log=lambda s: None)

    def pump(self, _secs):
        """The MCP server's sleep: one broker + runner + broker cycle per poll."""
        BRK.drain_once(self.ctx); RUN.run_all(self.m, self.state, owner=None); BRK.collect_once(self.ctx)

    def call(self, name, **args):
        s = MCP.Server(self.m, self.spool, sleep=self.pump)
        r = s.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": name, "arguments": args}})
        return json.loads(r["result"]["content"][0]["text"])

    def test_run_then_quota_then_list(self):
        r = self.call("ads_audit_run", client="acme-dental")
        self.assertEqual((r["status"], r["vault_path"]),
                         ("ok", "/var/lib/hermes/vaults/acme-dental/audits/2026-10-01_12-00-00-audit.md"))
        r2 = self.call("ads_audit_run", client="acme-dental")
        self.assertEqual((r2["status"], r2["reason"]), ("refused", "quota"))
        l = self.call("ads_audit_list", client="acme-dental")
        self.assertEqual(l["audits"], ["2026-09-30_10-00-00"])
        self.assertEqual(self.call("ads_audit_status", request_id=r["request_id"])["status"], "ok")

    def test_reboot_mid_run_reports_interrupted_and_never_reruns(self):
        req = A.make_request(self.m, "run", "acme-dental")
        A.write_json_atomic(os.path.join(self.spool, "requests"), req["request_id"] + ".json", req)
        BRK.drain_once(self.ctx)
        n = req["request_id"] + ".json"
        os.rename(os.path.join(self.state, "jobs", n), os.path.join(self.state, "running", n))  # "reboot" here
        calls = []
        RUN.run_all(self.m, self.state, execute=lambda a, t: calls.append(a) or (0, "", False), owner=None)
        BRK.recover(self.ctx); BRK.collect_once(self.ctx)
        self.assertEqual(calls, [])
        r = json.load(open(os.path.join(self.spool, "results", n)))
        self.assertEqual((r["status"], r["reason"]), ("failed", "interrupted"))


if __name__ == "__main__":
    unittest.main()
