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
B = _load("hermes_broker_e2e", "hermes-broker.py")
import spool_lib as S
import migrate_governance_shim as M

APPLY = os.path.join(HERE, "apply-changeset.py")

# Real wall-clock "now", not a fixed constant: apply-changeset.py's own _utcnow()
# (called inside the REAL subprocess this suite spawns) is not injectable and always
# reads the actual system clock. A fixed historical constant here would drift out of
# the approval's 24h TTL window the moment real time passes it — exactly what
# happened when this suite was first written against a fixed 2026-09-02 constant and
# the host's clock later advanced past it. Computed once at import time, which is
# always within microseconds of when the tests that use it actually run.
NOW = datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0)
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
        max_pending_requests: 2
        accepted_requests_per_client_day: 3
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

        # S3-b Task 4: iter_log_records now raises on a missing log, and log/ is
        # host-owned 2750 in production so the executor can no longer create its own.
        # Give acme-dental a pre-created log through the real deploy path
        # (migrate-governance.py --bootstrap-logs) rather than hand-writing one — same
        # pattern as apply-changeset.test.py's Base.setUp. bootstrap_logs reads the
        # registry from the CANONICAL governance-store path (registry/clients.json),
        # distinct from self.clients (_registry/clients.json, handed explicitly to
        # propose()/approve() below).
        reg_dir = os.path.join(self.tmp, "registry")
        os.makedirs(reg_dir)
        with open(os.path.join(reg_dir, "clients.json"), "w") as f:
            json.dump({"clients": {"acme-dental": {
                "project": "claude_google_ads", "customer_id": "1234567890",
                "status": "active"}}}, f)
        os.makedirs(os.path.join(self.tmp, "log"), mode=0o2750)
        M.bootstrap_logs(self.tmp, dry_run=False, expected_gid=os.getgid())

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


class TestBrokerBuiltArgvComposition(Base):
    """The composition Task 4 exists to net: the BROKER constructs the argv
    (hermes-broker.py:506) and the REAL EXECUTOR PROCESS (apply-changeset.py's
    main(), via subprocess) consumes it. TestReservationHandoffEndToEnd above
    simulates the broker's half in-process (C.reserve_approval called directly)
    and hand-builds its own argv — that proves the executor accepts a
    CLI-presented reservation, which apply-changeset.test.py's
    test_cli_forwards_a_valid_request_id_and_it_is_accepted already covers from the
    executor's side. This class is the missing third leg: hermes-broker.py's OWN
    argv construction, fed to a real executor process, with nothing hand-built in
    between.
    """

    def setUp(self):
        super().setUp()
        # TRAP (fix round 1): hermes-broker.py's _process() resolves the client via
        # vault_lib.resolve(slug) with NO registry override, which reads
        # governance_lib.clients_registry_path() == <root>/registry/clients.json —
        # a DIFFERENT file from the `_registry/clients.json` copy Base.setUp wrote
        # above (which propose/approve/the executor are pointed at explicitly via
        # --registry). Both copies must exist with identical content, or drain()
        # fails on client resolution and looks like a broken seam when it is not.
        gov_clients = governance_lib.clients_registry_path(self.tmp)
        os.makedirs(os.path.dirname(gov_clients), exist_ok=True)
        with open(gov_clients, "w") as f:
            json.dump({"clients": {"acme-dental": {
                "project": "claude_google_ads", "customer_id": "1234567890",
                "status": "active"}}}, f)
        self.spool = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.spool, True)

    def _file_request(self, cid, request_id):
        req = {"request_id": request_id, "op": "apply", "client": "acme-dental",
               "changeset": cid}
        os.makedirs(S.requests_dir(self.spool), exist_ok=True)
        with open(S.request_path(request_id, self.spool), "w") as f:
            json.dump(req, f)

    def _real_executor_runner(self, argv):
        """argv[0] is MUTATE_SH in production (hermes-broker.py:41); argv[1:] is the
        BROKER'S OWN construction at hermes-broker.py:506 —
        ["--client", slug, "--changeset", cid, "--request", rid]. --dry-run and the
        explicit --registry/--projects are added here only to keep this test at zero
        spend and pointed at the temp fixture; they are not part of what the broker
        itself builds."""
        cmd = [sys.executable, APPLY] + list(argv[1:]) + [
            "--dry-run", "--registry", self.clients, "--projects", self.projects]
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        return p.returncode, (p.stdout or "") + (p.stderr or "")

    def test_the_broker_built_argv_runs_against_the_real_executor(self):
        """THE COMPOSITION THAT FAILED IN PRODUCTION: the broker reserves the
        approval AND builds the argv that is handed to the executor, and that exact
        argv is fed to the REAL apply-changeset.py subprocess — no hand-built argv,
        no in-process reservation shortcut."""
        cs = self._approved()
        self._file_request(cs["changeset_id"], RID)
        outcomes = B.drain(spool=self.spool, projects=self.projects,
                           runner=self._real_executor_runner, now=NOW)
        self.assertEqual(len(outcomes), 1)
        self.assertEqual(outcomes[0]["classification"], "accepted_applied")
        with open(S.result_path(RID, self.spool)) as f:
            result = json.load(f)
        self.assertEqual(result["exit_code"], 0)
        self.assertEqual(result["classification"], "accepted_applied")


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
