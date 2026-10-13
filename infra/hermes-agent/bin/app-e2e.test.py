#!/usr/bin/env python3
"""Option B end to end in temp dirs: MCP tool call -> spool -> broker -> job -> runner -> stub
command -> done -> broker -> result -> MCP. No Docker, no root: the runner's owner is None."""
import importlib.util, json, os, sys, tempfile, unittest
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import app_lib as A


def load(name, file):
    s = importlib.util.spec_from_file_location(name, os.path.join(HERE, file))
    m = importlib.util.module_from_spec(s); s.loader.exec_module(m); return m


MCP, BRK, RUN = load("mcp", "hermes-app-mcp.py"), load("brk", "hermes-app-broker.py"), load("run", "hermes-app-runner.py")
STUB = """#!/bin/sh
slug="$1"; shift
for a in "$@"; do
  if [ "$a" = "--list" ]; then echo '{"status": "ok", "audits": ["2026-09-30_10-00-00"]}'; exit 0; fi
done
echo "{\\"status\\": \\"ok\\", \\"reason\\": null, \\"exit_code\\": 0, \\"ts\\": \\"2026-10-01_12-00-00\\", \\"steps\\": [STEPS], \\"vault_path\\": \\"PATH\\"}"
"""
STEPS = {"ads-audit": ["draft"], "ads-report": ["collect", "read", "store"]}     # the classes a run of each job reports
REGISTRY_DIR = os.path.join(os.path.dirname(HERE), "registry/apps")


def stub_for(man):
    """A fake command whose result is valid for THAT job: its stored path is built from the manifest."""
    path = A.RESULT_ROOTS[man.result["root"]] + "/$slug" + ("/" + man.result["subdir"] if man.result["subdir"] else "") \
        + "/2026-10-01_12-00-00" + man.result["suffix"]
    steps = ", ".join('{\\"name\\": \\"%s\\", \\"rc\\": 0, \\"seconds\\": 1.0}' % c for c in STEPS[man.app])
    return STUB.replace("STEPS", steps).replace("PATH", path)


class Job:
    """One job's manifest, spool and state: nothing is shared between two jobs."""
    def __init__(self, t, app, reg):
        raw = json.load(open(os.path.join(REGISTRY_DIR, app + ".json")))
        base = os.path.join(t, app); os.makedirs(base)
        stub = os.path.join(base, "stub")
        mdir = os.path.join(base, "apps"); os.makedirs(mdir)
        json.dump(dict(raw, command=stub), open(os.path.join(mdir, app + ".json"), "w"))
        self.m = A.load_manifest(os.path.join(mdir, app + ".json"), app)
        open(stub, "w").write(stub_for(self.m)); os.chmod(stub, 0o755)
        self.spool, self.state = os.path.join(base, "spool"), os.path.join(base, "state")
        for d in ("requests", "results"):
            os.makedirs(os.path.join(self.spool, d))
        for d in ("state", "jobs", "running", "done"):
            os.makedirs(os.path.join(self.state, d))
        self.ctx = BRK.Ctx(self.m, self.spool, self.state, reg, log=lambda s: None)

    def tree(self):
        """Every file under the job's spool and state, with its content: the ledger included."""
        out = {}
        for top in (self.spool, self.state):
            for d, _, files in os.walk(top):
                out[d] = sorted(files)
                for f in files:
                    out[os.path.join(d, f)] = open(os.path.join(d, f), "rb").read()
        return out


class E2E(unittest.TestCase):
    def setUp(self):
        t = tempfile.mkdtemp()
        reg = os.path.join(t, "clients.json")
        json.dump({"clients": {"acme-dental": {"status": "active", "customer_id": "1234567890"}}}, open(reg, "w"))
        self.jobs = {app: Job(t, app, reg) for app in sorted(A.load_manifests(REGISTRY_DIR))}
        self.assertEqual(sorted(self.jobs), ["ads-audit", "ads-report"])

    def pump(self, job):
        """The MCP server's sleep: one broker + runner + broker cycle per poll."""
        def go(_secs):
            BRK.drain_once(job.ctx); RUN.run_all(job.m, job.state, owner=None); BRK.collect_once(job.ctx)
        return go

    def call(self, job, name, **args):
        s = MCP.Server(job.m, job.spool, sleep=self.pump(job))
        r = s.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": name, "arguments": args}})
        return json.loads(r["result"]["content"][0]["text"])

    def test_run_then_quota_then_list_for_each_job(self):
        for app, job in self.jobs.items():
            with self.subTest(app=app):
                others = {a: j.tree() for a, j in self.jobs.items() if a != app}
                tools = job.m.tools
                want = A.RESULT_ROOTS[job.m.result["root"]] + "/acme-dental" \
                    + ("/" + job.m.result["subdir"] if job.m.result["subdir"] else "") \
                    + "/2026-10-01_12-00-00" + job.m.result["suffix"]
                r = self.call(job, tools["run"], client="acme-dental")
                self.assertEqual((r["status"], r["vault_path"]), ("ok", want))
                self.assertEqual([s["name"] for s in r["steps"]], STEPS[app])
                with open(os.path.join(job.spool, "results", r["request_id"] + ".json")) as f:
                    self.assertEqual(json.load(f)["vault_path"], want)      # the broker wrote this path
                r2 = self.call(job, tools["run"], client="acme-dental")
                self.assertEqual((r2["status"], r2["reason"]), ("refused", "quota"))
                l = self.call(job, tools["list"], client="acme-dental")
                self.assertEqual(l["audits"], ["2026-09-30_10-00-00"])
                self.assertEqual(self.call(job, tools["status"], request_id=r["request_id"])["status"], "ok")
                for a, before in others.items():                            # the other jobs' spool, state and ledger
                    self.assertEqual(self.jobs[a].tree(), before)

    def test_reboot_mid_run_reports_interrupted_and_never_reruns(self):
        for app, job in self.jobs.items():
            with self.subTest(app=app):
                req = A.make_request(job.m, "run", "acme-dental")
                A.write_json_atomic(os.path.join(job.spool, "requests"), req["request_id"] + ".json", req)
                BRK.drain_once(job.ctx)
                n = req["request_id"] + ".json"
                os.rename(os.path.join(job.state, "jobs", n), os.path.join(job.state, "running", n))  # "reboot" here
                calls = []
                RUN.run_all(job.m, job.state, execute=lambda a, t: calls.append(a) or (0, "", False), owner=None)
                BRK.recover(job.ctx); BRK.collect_once(job.ctx)
                self.assertEqual(calls, [])
                r = json.load(open(os.path.join(job.spool, "results", n)))
                self.assertEqual((r["status"], r["reason"]), ("failed", "interrupted"))
                self.assertEqual(os.listdir(os.path.join(job.state, "running")), [])
                self.assertEqual(os.listdir(os.path.join(job.state, "jobs")), [])


if __name__ == "__main__":
    unittest.main()
