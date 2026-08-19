import contextlib, datetime, importlib.util, io, json, os, stat, subprocess, sys, tempfile, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import changeset_lib as C
import governance_lib

def _load(name, filename):
    spec = importlib.util.spec_from_file_location(name, os.path.join(HERE, filename))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

P = _load("propose_changeset", "propose-changeset.py")
A = _load("approve_changeset", "approve-changeset.py")
X = _load("apply_changeset", "apply-changeset.py")

NOW = datetime.datetime(2026, 8, 12, 10, 15, 0, tzinfo=datetime.timezone.utc)

FULL_CRED = {"GOOGLE_ADS_DEVELOPER_TOKEN": "devtok-AAAAAAAAAAAAAAAAAAAA",
             "GOOGLE_ADS_CLIENT_ID": "clientid-BBBBBBBBBBBBBBBBBBBB",
             "GOOGLE_ADS_CLIENT_SECRET": "clientsecret-CCCCCCCCCCCCCCCC",
             "GOOGLE_ADS_REFRESH_TOKEN": "refresh-DDDDDDDDDDDDDDDDDDDD",
             "GOOGLE_ADS_LOGIN_CUSTOMER_ID": "1234567890",
             "GOOGLE_ADS_CUSTOMER_ID": "1234567890",
             "GOOGLE_ADS_CREDENTIAL_ROLE": "write"}

STUB = '''#!/usr/bin/env python3
# Test double for the ads-repo mutator. Communicates through FILES beside itself, not
# environment variables, so apply-changeset.py's restricted _child_env() needs no
# test-only entries.
import json, os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
CALLS = os.path.join(HERE, "calls.jsonl")
with open(CALLS, "a") as f:
    f.write(json.dumps(sys.argv[1:]) + "\\n")
# How many audit-log records existed at the MOMENT this process was spawned. Lets a
# test prove the per-action log write completed BEFORE the next action started,
# rather than only that the right number of records exist once the run has finished.
_log = os.path.join(HERE, "..", "acme-dental", "changes", "log.jsonl")
_n = sum(1 for line in open(_log) if line.strip()) if os.path.exists(_log) else 0
with open(os.path.join(HERE, "logcounts.jsonl"), "a") as f:
    f.write(json.dumps({"argv": sys.argv[1:], "log_records_at_spawn": _n}) + "\\n")
mode_file = os.path.join(HERE, "mode.txt")
mode = open(mode_file).read().strip() if os.path.exists(mode_file) else "ok"
if mode == "fail_validate" and "--validate-only" in sys.argv:
    sys.stderr.write("stub: validate refused\\n"); sys.exit(2)
if mode == "fail_second_live" and "--validate-only" not in sys.argv:
    n = sum(1 for _ in open(CALLS))
    if n > 3:
        sys.stderr.write("stub: live failure\\n"); sys.exit(2)
if mode == "leak_secret" and "--validate-only" in sys.argv:
    sys.stderr.write("boom " + os.environ["GOOGLE_ADS_REFRESH_TOKEN"] + "\\n"); sys.exit(2)
if "--validate-only" in sys.argv:
    print(json.dumps({"ok": True, "validate_only": True})); sys.exit(0)
if "--undo" in sys.argv:
    print(json.dumps({"ok": True, "removed": sys.argv[sys.argv.index("--undo") + 1]})); sys.exit(0)
i = sys.argv.index("--action")
a = json.loads(sys.argv[i + 1])
print(json.dumps({"ok": True,
                  "resource_name": "customers/1234567890/campaignCriteria/%s~9" % a["campaign_id"]}))
'''

def _reg_text(tmp, allow="mutate_campaign_negative", caps=None):
    caps = caps or {"actions_per_changeset": 25, "actions_per_client_day": 100,
                    "applies_per_client_day": 5, "approval_ttl_hours": 24}
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
        actions_per_changeset: {caps['actions_per_changeset']}
        actions_per_client_day: {caps['actions_per_client_day']}
        applies_per_client_day: {caps['applies_per_client_day']}
        approval_ttl_hours: {caps['approval_ttl_hours']}
"""

class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        os.environ["VAULT_ROOT"] = self.tmp
        os.environ["HERMES_GOVERNANCE_ROOT"] = self.tmp
        for k, v in FULL_CRED.items():
            os.environ[k] = v
        code = os.path.join(self.tmp, "code"); os.makedirs(code)
        self.calls = os.path.join(code, "calls.jsonl")
        self.mode_file = os.path.join(code, "mode.txt")
        self.stub = os.path.join(code, "mutate_campaign_negative.py")
        with open(self.stub, "w") as f:
            f.write(STUB)
        os.chmod(self.stub, os.stat(self.stub).st_mode | stat.S_IEXEC)
        d = os.path.join(self.tmp, "_registry"); os.makedirs(d)
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

    def _actions(self, n=1):
        return [{"type": "add_campaign_negative", "campaign_id": str(22233344450 + i),
                 "keyword": f"zzz test negative {i}", "match_type": "PHRASE"} for i in range(n)]

    def _proposed(self, n=1):
        src = os.path.join(self.tmp, "in.json")
        with open(src, "w") as f:
            json.dump({"actions": self._actions(n)}, f)
        return P.propose("acme-dental", src, NOW, registry=self.clients, projects=self.projects)

    def _approved(self, n=1):
        cs = self._proposed(n)
        A.approve("acme-dental", cs["changeset_id"], "erick", NOW,
                  registry=self.clients, projects=self.projects)
        return cs

    def _calls(self):
        if not os.path.exists(self.calls):
            return []
        with open(self.calls) as f:
            return [json.loads(x) for x in f if x.strip()]

    def _mode(self, m):
        with open(self.mode_file, "w") as f:
            f.write(m)

    def _run(self, cs_id, now=NOW, undo=None):
        """Runs apply() with stdout captured — the success-path print() is correct
        production behavior (the host wrapper reads it) but has no place in pristine
        test output. Returns (exit_code, captured_stdout) so a test that cares about
        the printed payload still can."""
        plan = X.build_plan("acme-dental", cs_id, now, registry=self.clients,
                            projects=self.projects, undo=undo)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = X.apply(plan, now)
        return rc, buf.getvalue()

class TestHappyPath(Base):
    def test_two_actions_validate_then_apply(self):
        cs = self._approved(2)
        rc, _ = self._run(cs["changeset_id"])
        self.assertEqual(rc, 0)
        calls = self._calls()
        self.assertEqual(len(calls), 4)                       # 2 validate + 2 live
        self.assertTrue(all("--validate-only" in c for c in calls[:2]))
        self.assertTrue(all("--validate-only" not in c for c in calls[2:]))

    def test_log_records_resource_names(self):
        cs = self._approved(2)
        self._run(cs["changeset_id"])
        with open(C.log_path(self.vault)) as f:
            recs = [json.loads(x) for x in f if x.strip()]
        self.assertEqual(len(recs), 2)
        self.assertTrue(all(r["status"] == "applied" for r in recs))
        self.assertTrue(all(r["resource_name"].startswith("customers/1234567890/") for r in recs))
        self.assertTrue(all(r["operator"] == "erick" for r in recs))

    def test_result_and_timeline_written(self):
        cs = self._approved(1)
        self._run(cs["changeset_id"])
        self.assertTrue(os.path.exists(C.result_path(self.vault, cs["changeset_id"])))
        with open(os.path.join(self.vault, "timeline.md")) as f:
            self.assertIn("change", f.read())

class TestPreflightRefusals(Base):
    """Every refusal must exit 2 AND never spawn the mutator."""

    def _assert_refused(self, cs_id, now=NOW):
        with self.assertRaises(SystemExit) as ctx:
            self._run(cs_id, now=now)
        self.assertEqual(ctx.exception.code, 2)
        self.assertEqual(self._calls(), [])

    def test_kill_switch_absent(self):
        cs = self._approved()
        os.remove(governance_lib.kill_switch_path(self.tmp))
        self._assert_refused(cs["changeset_id"])

    def test_no_approval(self):
        cs = self._proposed()
        self._assert_refused(cs["changeset_id"])

    def test_tampered_snapshot_after_approval_refused(self):
        """apply reads the governance-store SNAPSHOT, not the vault copy — so the
        thing that must still be tamper-checked is the snapshot's bytes."""
        cs = self._approved()
        with open(C.snapshot_path("acme-dental", cs["changeset_id"]), "ab") as f:
            f.write(b" ")
        self._assert_refused(cs["changeset_id"])

    def test_tampering_the_vault_copy_after_approval_does_not_block_apply(self):
        """The race this task closes, asserted at the integration level: apply no
        longer reads the vault copy at all, so editing it post-approval must have
        NO effect on the outcome — the run must still succeed from the untouched
        governance snapshot."""
        cs = self._approved()
        with open(C.changeset_path(self.vault, cs["changeset_id"]), "ab") as f:
            f.write(b" ")
        rc, _ = self._run(cs["changeset_id"])
        self.assertEqual(rc, 0)
        self.assertTrue(self._calls())

    def test_expired_approval(self):
        cs = self._approved()
        self._assert_refused(cs["changeset_id"], now=NOW + datetime.timedelta(hours=25))

    def test_offboarded_client(self):
        cs = self._approved()
        with open(self.clients, "w") as f:
            json.dump({"clients": {"acme-dental": {
                "project": "claude_google_ads", "customer_id": "1234567890",
                "status": "offboarded"}}}, f)
        self._assert_refused(cs["changeset_id"])

    def test_customer_id_mismatch_is_a_tamper_check(self):
        cs = self._approved()
        with open(self.clients, "w") as f:
            json.dump({"clients": {"acme-dental": {
                "project": "claude_google_ads", "customer_id": "9999999999",
                "status": "active"}}}, f)
        self._assert_refused(cs["changeset_id"])

    def test_injected_credential_for_another_client_refused(self):
        """The registry and change-set agree; only the injected credential differs."""
        cs = self._approved(1)
        os.environ["GOOGLE_ADS_CUSTOMER_ID"] = "9999999999"
        self._assert_refused(cs["changeset_id"])

    def test_undo_with_another_clients_credential_refused(self):
        cs = self._approved(1)
        self.assertEqual(self._run(cs["changeset_id"])[0], 0)
        os.remove(self.calls)
        os.environ["GOOGLE_ADS_CUSTOMER_ID"] = "9999999999"
        with self.assertRaises(SystemExit) as ctx:
            self._run(cs["changeset_id"], undo=cs["changeset_id"])
        self.assertEqual(ctx.exception.code, 2)
        self.assertEqual(self._calls(), [])

    def test_daily_applies_cap(self):
        with open(self.projects, "w") as f:
            f.write(_reg_text(self.tmp, caps={"actions_per_changeset": 25,
                                              "actions_per_client_day": 100,
                                              "applies_per_client_day": 1,
                                              "approval_ttl_hours": 24}))
        first = self._approved()
        rc, _ = self._run(first["changeset_id"])
        self.assertEqual(rc, 0)
        os.remove(self.calls)
        second = self._approved()
        self._assert_refused(second["changeset_id"])

    def test_daily_actions_cap(self):
        with open(self.projects, "w") as f:
            f.write(_reg_text(self.tmp, caps={"actions_per_changeset": 25,
                                              "actions_per_client_day": 2,
                                              "applies_per_client_day": 5,
                                              "approval_ttl_hours": 24}))
        first = self._approved(2)
        rc, _ = self._run(first["changeset_id"])
        self.assertEqual(rc, 0)
        os.remove(self.calls)
        second = self._approved(1)
        self._assert_refused(second["changeset_id"])

    def test_missing_credential_var(self):
        cs = self._approved()
        del os.environ["GOOGLE_ADS_REFRESH_TOKEN"]
        self._assert_refused(cs["changeset_id"])

    def test_wrong_credential_role(self):
        cs = self._approved()
        os.environ["GOOGLE_ADS_CREDENTIAL_ROLE"] = "read"
        self._assert_refused(cs["changeset_id"])

    def test_allow_list_overlap(self):
        cs = self._approved()
        with open(self.projects, "w") as f:
            f.write(_reg_text(self.tmp, allow="account_overview"))
        self._assert_refused(cs["changeset_id"])

class TestValidateOnlyGate(Base):
    def test_validate_failure_applies_nothing(self):
        cs = self._approved(2)
        self._mode("fail_validate")
        with self.assertRaises(SystemExit) as ctx:
            self._run(cs["changeset_id"])
        self.assertEqual(ctx.exception.code, 2)
        calls = self._calls()
        self.assertTrue(all("--validate-only" in c for c in calls))   # zero live calls
        self.assertFalse(os.path.exists(C.log_path(self.vault)))

    def test_stderr_secrets_are_scrubbed_in_failure_message(self):
        """A mutator failure must not surface credential values in the message."""
        cs = self._approved(1)
        self._mode("leak_secret")
        buf = io.StringIO()
        with self.assertRaises(SystemExit) as ctx, contextlib.redirect_stderr(buf):
            self._run(cs["changeset_id"])
        self.assertEqual(ctx.exception.code, 2)
        captured = buf.getvalue()
        self.assertIn("***", captured)
        self.assertNotIn(os.environ["GOOGLE_ADS_REFRESH_TOKEN"], captured)

class TestPostMutationFailure(Base):
    def test_partial_apply_exits_3_and_keeps_the_record(self):
        cs = self._approved(2)
        self._mode("fail_second_live")
        with self.assertRaises(SystemExit) as ctx:
            self._run(cs["changeset_id"])
        self.assertEqual(ctx.exception.code, 3)
        with open(C.log_path(self.vault)) as f:
            recs = [json.loads(x) for x in f if x.strip()]
        self.assertEqual(len(recs), 1)                     # the one that landed is recorded
        self.assertEqual(recs[0]["status"], "applied")

    def test_each_log_write_completes_before_the_next_action_spawns(self):
        """The durability property stated in spec §5, asserted directly.

        Previously this was only covered indirectly, by counting records after a failed
        second action — which proves the log holds one entry at the END, not that the
        write completed before the next mutator started. The stub now records how many
        records existed when it was spawned, so the ordering itself is observable: live
        action k must see exactly k records already durable.
        """
        cs = self._approved(3)
        self.assertEqual(self._run(cs["changeset_id"])[0], 0)
        p = os.path.join(self.tmp, "code", "logcounts.jsonl")
        entries = [json.loads(x) for x in open(p) if x.strip()]
        live = [e for e in entries if "--validate-only" not in e["argv"]]
        self.assertEqual(len(live), 3)
        self.assertEqual([e["log_records_at_spawn"] for e in live], [0, 1, 2])
        # And every validate_only call ran before any of them wrote anything.
        dry = [e for e in entries if "--validate-only" in e["argv"]]
        self.assertEqual([e["log_records_at_spawn"] for e in dry], [0, 0, 0])

    def test_io_failure_after_a_live_mutation_exits_3_not_1(self):
        """The 0/1/2/3 contract must be decided by WHAT HAPPENED, not by exception type.

        A post-mutation OSError previously escaped apply() as a traceback and exit 1,
        which an operator's tooling reads as 'usage error, nothing happened' — for a run
        that changed the account. A directory where timeline.md belongs reproduces it.
        """
        cs = self._approved(1)
        os.mkdir(os.path.join(self.vault, "timeline.md"))   # open(..., "a") will raise
        with self.assertRaises(SystemExit) as ctx:
            self._run(cs["changeset_id"])
        self.assertEqual(ctx.exception.code, 3)
        recs = [json.loads(x) for x in open(C.log_path(self.vault)) if x.strip()]
        self.assertEqual(len(recs), 1)                      # the mutation is still recorded
        self.assertEqual(recs[0]["status"], "applied")

    def test_failure_before_any_mutation_still_exits_2(self):
        """The other half of the same contract: a broken runner sends nothing, so exit 2's
        promise ('guaranteed nothing was mutated') must survive the new catch-all."""
        cs = self._approved(1)
        plan = X.build_plan("acme-dental", cs["changeset_id"], NOW,
                            registry=self.clients, projects=self.projects)
        plan["runner"] = os.path.join(self.tmp, "no-such-interpreter")
        with self.assertRaises(SystemExit) as ctx:
            X.apply(plan, NOW)
        self.assertEqual(ctx.exception.code, 2)
        self.assertEqual(self._calls(), [])

class TestUndo(Base):
    def _applied(self, n=1):
        cs = self._approved(n)
        self.assertEqual(self._run(cs["changeset_id"])[0], 0)
        os.remove(self.calls)
        return cs

    def _log_records(self):
        with open(C.log_path(self.vault)) as f:
            return [json.loads(x) for x in f if x.strip()]

    def test_undo_removes_each_applied_resource(self):
        """Asserts resource IDENTITY, not just counts. Counting alone would pass even if
        _undo_targets returned the same record twice instead of both distinct ones."""
        cs = self._applied(2)
        applied = [r["resource_name"] for r in self._log_records() if r["status"] == "applied"]
        self.assertEqual(self._run(cs["changeset_id"], undo=cs["changeset_id"])[0], 0)
        calls = self._calls()
        self.assertEqual(len(calls), 4)                        # 2 validate + 2 live
        undone_args = [c[c.index("--undo") + 1] for c in calls if "--undo" in c]
        self.assertEqual(len(set(undone_args)), 2)             # distinct, not one twice
        self.assertEqual(set(undone_args), set(applied))       # exactly what was applied

    def test_undo_appends_undone_lines(self):
        cs = self._applied(2)
        self._run(cs["changeset_id"], undo=cs["changeset_id"])
        recs = self._log_records()
        applied = {r["resource_name"] for r in recs if r["status"] == "applied"}
        undone = {r["resource_name"] for r in recs if r["status"] == "undone"}
        self.assertEqual(len(applied), 2)
        self.assertEqual(undone, applied)                      # every applied resource undone

    def test_undo_works_with_kill_switch_absent(self):
        """Guards constrain creating change, never reversing it."""
        cs = self._applied(1)
        os.remove(governance_lib.kill_switch_path(self.tmp))
        self.assertEqual(self._run(cs["changeset_id"], undo=cs["changeset_id"])[0], 0)

    def test_undo_works_with_daily_caps_exhausted(self):
        with open(self.projects, "w") as f:
            f.write(_reg_text(self.tmp, caps={"actions_per_changeset": 25,
                                              "actions_per_client_day": 1,
                                              "applies_per_client_day": 1,
                                              "approval_ttl_hours": 24}))
        cs = self._applied(1)
        self.assertEqual(self._run(cs["changeset_id"], undo=cs["changeset_id"])[0], 0)

    def test_second_undo_is_a_noop_refusal(self):
        cs = self._applied(1)
        self._run(cs["changeset_id"], undo=cs["changeset_id"])
        os.remove(self.calls)
        with self.assertRaises(SystemExit) as ctx:
            self._run(cs["changeset_id"], undo=cs["changeset_id"])
        self.assertEqual(ctx.exception.code, 2)
        self.assertEqual(self._calls(), [])

    def test_undo_of_unknown_changeset_refused(self):
        self._applied(1)
        with self.assertRaises(SystemExit) as ctx:
            self._run("20260812-999999-deadbeef", undo="20260812-999999-deadbeef")
        self.assertEqual(ctx.exception.code, 2)
        self.assertEqual(self._calls(), [])

    def test_undo_still_requires_credentials(self):
        cs = self._applied(1)
        del os.environ["GOOGLE_ADS_CLIENT_SECRET"]
        with self.assertRaises(SystemExit) as ctx:
            self._run(cs["changeset_id"], undo=cs["changeset_id"])
        self.assertEqual(ctx.exception.code, 2)
        self.assertEqual(self._calls(), [])        # refused BEFORE the mutator ran

    def test_undo_still_requires_write_role(self):
        cs = self._applied(1)
        os.environ["GOOGLE_ADS_CREDENTIAL_ROLE"] = "read"
        with self.assertRaises(SystemExit) as ctx:
            self._run(cs["changeset_id"], undo=cs["changeset_id"])
        self.assertEqual(ctx.exception.code, 2)
        self.assertEqual(self._calls(), [])        # refused BEFORE the mutator ran

    # --- spec §7.1 / §9: an undo can never reach another account -------------------
    #
    # These exercise the HERMES-side guard specifically. The ads-repo mutator carries an
    # equivalent check, so a live gate cannot distinguish "Hermes refused" from "the
    # mutator refused" — which is exactly how the Hermes-side guard went missing and
    # stayed missing. The stub here has NO such check, so a passing test means Hermes
    # refused on its own. Asserting _calls() == [] is the load-bearing half.

    def _rewrite_log(self, fn):
        p = C.log_path(self.vault)
        recs = [json.loads(x) for x in open(p) if x.strip()]
        with open(p, "w") as f:
            for r in recs:
                fn(r)
                f.write(json.dumps(r, sort_keys=True) + "\n")

    def test_undo_refuses_resource_name_of_another_customer(self):
        cs = self._applied(1)
        self._rewrite_log(lambda r: r.__setitem__(
            "resource_name", r["resource_name"].replace("customers/1234567890/",
                                                        "customers/9999999999/")))
        with self.assertRaises(SystemExit) as ctx:
            self._run(cs["changeset_id"], undo=cs["changeset_id"])
        self.assertEqual(ctx.exception.code, 2)
        self.assertEqual(self._calls(), [])

    def test_undo_refuses_malformed_resource_name(self):
        cs = self._applied(1)
        self._rewrite_log(lambda r: r.__setitem__("resource_name", "; rm -rf /  $(whoami)"))
        with self.assertRaises(SystemExit) as ctx:
            self._run(cs["changeset_id"], undo=cs["changeset_id"])
        self.assertEqual(ctx.exception.code, 2)
        self.assertEqual(self._calls(), [])

    def test_undo_refuses_record_missing_resource_name(self):
        """Previously surfaced as an uncaught KeyError and exit 1, not a refusal."""
        cs = self._applied(1)
        self._rewrite_log(lambda r: r.pop("resource_name", None))
        with self.assertRaises(SystemExit) as ctx:
            self._run(cs["changeset_id"], undo=cs["changeset_id"])
        self.assertEqual(ctx.exception.code, 2)
        self.assertEqual(self._calls(), [])

    def test_undo_refuses_record_with_non_string_status(self):
        """iter_log_records type-checks the fields both readers depend on."""
        cs = self._applied(1)
        self._rewrite_log(lambda r: r.__setitem__("status", 1))
        with self.assertRaises(SystemExit) as ctx:
            self._run(cs["changeset_id"], undo=cs["changeset_id"])
        self.assertEqual(ctx.exception.code, 2)
        self.assertEqual(self._calls(), [])


if __name__ == "__main__":
    unittest.main()
