#!/usr/bin/env python3
"""End-to-end: broker -> real apply-changeset.py, no mocked executor.

ZERO SPEND BY CONSTRUCTION. `mutate_campaign_negative.py` is a stub script that never
reaches a real Google Ads account, and every test here runs the executor with
--dry-run, which returns before the mutator is ever invoked (build_plan() runs, then
main()'s `if args.dry_run:` branch prints and exits — apply()/the mutator subprocess
is never reached). What is real here is the part that was never tested together: the
broker's reservation (changeset_lib.reserve_approval) and the executor's independent
re-verification of that same approval record, invoked as a REAL SUBPROCESS through
apply-changeset.py's main(), exactly as the broker invokes it in production.

Every refusal below is paired with a positive control. A guard nobody can pass is
indistinguishable from a guard that works, until someone tries the legitimate case —
that is precisely how the 2026-09-01 CRITICAL survived eleven task reviews, a seam
review, a fix wave and a readiness pass: broker tests injected a fake runner and
never ran the real executor; executor tests approved directly and never passed
through the broker's reservation. Both sides were tested rigorously with the other
mocked, and the contradiction lived in the gap.
"""
import datetime, json, os, shutil, stat, subprocess, sys, tempfile, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import changeset_lib as C
import governance_lib

import importlib.util


def _load(name, filename):
    spec = importlib.util.spec_from_file_location(name, os.path.join(HERE, filename))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


P = _load("propose_changeset_e2e", "propose-changeset.py")
A = _load("approve_changeset_e2e", "approve-changeset.py")

APPLY = os.path.join(HERE, "apply-changeset.py")

NOW = datetime.datetime(2026, 9, 2, 10, 15, 0, tzinfo=datetime.timezone.utc)
RID = "11111111-2222-3333-4444-555555555555"
FOREIGN_RID = "99999999-9999-9999-9999-999999999999"

FULL_CRED = {"GOOGLE_ADS_DEVELOPER_TOKEN": "devtok-AAAAAAAAAAAAAAAAAAAA",
             "GOOGLE_ADS_CLIENT_ID": "clientid-BBBBBBBBBBBBBBBBBBBB",
             "GOOGLE_ADS_CLIENT_SECRET": "clientsecret-CCCCCCCCCCCCCCCC",
             "GOOGLE_ADS_REFRESH_TOKEN": "refresh-DDDDDDDDDDDDDDDDDDDD",
             "GOOGLE_ADS_LOGIN_CUSTOMER_ID": "1234567890",
             "GOOGLE_ADS_CUSTOMER_ID": "1234567890",
             "GOOGLE_ADS_CREDENTIAL_ROLE": "write"}

# Stub for the ads-repo mutator. Never invoked by any test in this suite (all runs use
# --dry-run, which returns before the mutator is spawned) but wired up anyway so the
# fixture matches production shape and so ZERO SPEND holds even if that assumption
# about --dry-run ever regresses: the stub records every call it receives and never
# reaches a real API either way.
STUB = '''#!/usr/bin/env python3
import json, os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
with open(os.path.join(HERE, "calls.jsonl"), "a") as f:
    f.write(json.dumps(sys.argv[1:]) + "\\n")
if "--validate-only" in sys.argv:
    print(json.dumps({"ok": True, "validate_only": True})); sys.exit(0)
i = sys.argv.index("--action")
a = json.loads(sys.argv[i + 1])
print(json.dumps({"ok": True,
                  "resource_name": "customers/1234567890/campaignCriteria/%s~9" % a["campaign_id"]}))
'''


def _reg_text(tmp, allow="mutate_campaign_negative"):
    return f"""version: 1

projects:
  claude_google_ads:
    workdir: {tmp}
    read_execute:
      runner: /bin/true
      script_dir: code
      allow:
        - account_overview
    mutate_execute:
      runner: {sys.executable}
      script_dir: code
      allow:
        - {allow}
      caps:
        actions_per_changeset: 25
        actions_per_client_day: 100
        applies_per_client_day: 5
        approval_ttl_hours: 24
"""


class Base(unittest.TestCase):
    """Reuses apply-changeset.test.py's fixture pattern (lines 107-134 there):
    real propose()/approve() calls so the on-disk change-set and approval formats are
    correct by construction, a stub mutator for ZERO SPEND, and both VAULT_ROOT and
    HERMES_GOVERNANCE_ROOT pointed at the temp governance store."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        os.environ["VAULT_ROOT"] = self.tmp
        os.environ["HERMES_GOVERNANCE_ROOT"] = self.tmp
        self.addCleanup(os.environ.pop, "VAULT_ROOT", None)
        self.addCleanup(os.environ.pop, "HERMES_GOVERNANCE_ROOT", None)
        for k, v in FULL_CRED.items():
            os.environ[k] = v
            self.addCleanup(os.environ.pop, k, None)

        code = os.path.join(self.tmp, "code")
        os.makedirs(code)
        self.stub = os.path.join(code, "mutate_campaign_negative.py")
        with open(self.stub, "w") as f:
            f.write(STUB)
        os.chmod(self.stub, os.stat(self.stub).st_mode | stat.S_IEXEC)

        d = os.path.join(self.tmp, "_registry")
        os.makedirs(d)
        self.clients = os.path.join(d, "clients.json")
        with open(self.clients, "w") as f:
            json.dump({"clients": {"acme-dental": {
                "project": "claude_google_ads", "customer_id": "1234567890",
                "status": "active"}}}, f)
        self.projects = os.path.join(self.tmp, "projects.yaml")
        with open(self.projects, "w") as f:
            f.write(_reg_text(self.tmp))

        switch = governance_lib.kill_switch_path(self.tmp)
        os.makedirs(os.path.dirname(switch))
        with open(switch, "w") as f:
            f.write("enabled\n")

        self.vault = os.path.join(self.tmp, "acme-dental")

    def _proposed(self):
        src = os.path.join(self.tmp, "in.json")
        actions = [{"type": "add_campaign_negative", "campaign_id": "1",
                    "keyword": "e2e fixture", "match_type": "PHRASE"}]
        with open(src, "w") as f:
            json.dump({"actions": actions}, f)
        return P.propose("acme-dental", src, NOW, registry=self.clients, projects=self.projects)

    def _approved(self):
        cs = self._proposed()
        digest = C.file_digest(C.changeset_path(self.vault, cs["changeset_id"]))
        A.approve("acme-dental", cs["changeset_id"], "erick", NOW,
                  registry=self.clients, projects=self.projects,
                  expect_sha256=digest)
        return cs

    def _run_executor(self, cid, request_id=None):
        """Invokes the REAL apply-changeset.py as a SUBPROCESS through main()'s
        argparse — the seam under test is broker-reservation -> real-executor-process,
        and an in-process call (X.build_plan()/X.apply(), as apply-changeset.test.py
        uses) would bypass main() and miss the wire entirely."""
        argv = [sys.executable, APPLY, "--client", "acme-dental", "--changeset", cid,
                "--dry-run", "--registry", self.clients, "--projects", self.projects]
        if request_id:
            argv += ["--request", request_id]
        return subprocess.run(argv, capture_output=True, text=True, timeout=120)


class TestReservationHandoffEndToEnd(Base):
    def test_the_happy_path_actually_succeeds(self):
        """THE TEST THAT DID NOT EXIST. Reserve exactly as the broker does, then run
        the REAL executor with that request id. Before the handoff this refused with
        'already reserved' for every possible input."""
        cs = self._approved()
        C.reserve_approval("acme-dental", cs["changeset_id"], RID, NOW)
        p = self._run_executor(cs["changeset_id"], request_id=RID)
        self.assertEqual(p.returncode, 0,
                         "happy path must succeed; stderr=%s" % p.stderr[:400])
        self.assertNotIn("already reserved", p.stderr)

    def test_a_foreign_request_id_is_refused(self):
        cs = self._approved()
        C.reserve_approval("acme-dental", cs["changeset_id"], RID, NOW)
        p = self._run_executor(cs["changeset_id"], request_id=FOREIGN_RID)
        self.assertNotEqual(p.returncode, 0)

    def test_a_reserved_approval_refuses_an_operator_apply(self):
        cs = self._approved()
        C.reserve_approval("acme-dental", cs["changeset_id"], RID, NOW)
        p = self._run_executor(cs["changeset_id"])  # no --request: the manual path
        self.assertNotEqual(p.returncode, 0)

    def test_an_unreserved_approval_still_serves_the_operator_path(self):
        # Positive control for the clause above: the manual path must still work.
        cs = self._approved()
        p = self._run_executor(cs["changeset_id"])
        self.assertEqual(p.returncode, 0,
                         "operator path regressed; stderr=%s" % p.stderr[:400])

    def test_a_completed_run_cannot_be_replayed_by_its_own_request_id(self):
        cs = self._approved()
        C.reserve_approval("acme-dental", cs["changeset_id"], RID, NOW)
        C.record_outcome("acme-dental", cs["changeset_id"], "accepted_applied", NOW)
        p = self._run_executor(cs["changeset_id"], request_id=RID)
        self.assertNotEqual(p.returncode, 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
