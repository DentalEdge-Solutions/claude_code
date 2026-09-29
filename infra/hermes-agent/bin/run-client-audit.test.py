#!/usr/bin/env python3
import contextlib, importlib.util, io, json, os, sys, tempfile, unittest
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import package_lib as PK
spec = importlib.util.spec_from_file_location("rca", os.path.join(HERE, "run-client-audit.py"))
RCA = importlib.util.module_from_spec(spec); spec.loader.exec_module(RCA)

TOKEN = "1//0gFAKEREFRESHTOKENabcdefghijklmnop"
CID = "1234567890"


def _write(dst, text):
    """The runner gets open log files (C1); a path is still accepted so old code shows RED."""
    if hasattr(dst, "write"):
        dst.write(text)
    else:
        with open(dst, "w") as f:
            f.write(text)


class FakeRunner:
    """Records every step; simulates collectors writing JSON and the analyst writing a draft."""
    def __init__(self, root, fail_on=None, collector_json=True, error_file=None, draft_text="DRAFT acme",
                 after=None, raise_on=None):
        self.root, self.calls, self.fail_on = root, [], fail_on
        self.collector_json, self.error_file, self.draft_text = collector_json, error_file, draft_text
        self.after, self.raise_on = after or {}, raise_on

    def __call__(self, argv, env, timeout, out, err):
        self.calls.append({"argv": argv, "env": dict(env or {}), "timeout": timeout})
        name = RCA.step_name(argv)
        _write(out, '{"customer": "x"}' if name == "snapshot" else f"stdout with {CID}\n")
        _write(err, f"stderr {CID}\n")
        if self.raise_on and self.raise_on[0] in name:
            raise self.raise_on[1]("boom")
        if name in self.after:
            self.after[name]()
        if self.fail_on and self.fail_on in name:
            return 1
        ad = self.root + "/var/lib/hermes/audit-data/acme-dental"
        if "ads-collector" in argv and self.collector_json:
            open(os.path.join(ad, argv[-1].split("/")[-1] + ".json"), "w").write("{}")
            if self.error_file:
                open(os.path.join(ad, self.error_file), "w").write("boom")
        ts = env.get("TS") or next((a[3:] for a in argv if a.startswith("TS=")), None)
        if name == "draft":
            d = self.root + "/opt/hermes-agent/data/audits/claude_google_ads"
            os.makedirs(d, exist_ok=True)
            open(os.path.join(d, ts + "-audit.md"), "w").write(self.draft_text)
        if name == "vault-write":
            v = self.root + "/opt/hermes-agent/data/vaults/acme-dental/audits"
            os.makedirs(v, exist_ok=True)
            open(os.path.join(v, ts + "-audit.md"), "w").write(self.draft_text)
        return 0


class Base(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        R = lambda p: self.root + p
        def w(p, body, mode=None):
            os.makedirs(os.path.dirname(R(p)), exist_ok=True); open(R(p), "w").write(body)
            if mode: os.chmod(R(p), mode)
        w("/var/lib/hermes/governance/registry/clients.json", json.dumps({"clients": {
            "acme-dental": {"customer_id": CID, "status": "active", "project": "claude_google_ads"},
            "other-dental": {"customer_id": "9998887777", "status": "active", "project": "claude_google_ads"}}}))
        w("/etc/hermes/.env" + ".ga", f"GOOGLE_ADS_REFRESH_TOKEN={TOKEN}\nGOOGLE_ADS_CREDENTIAL_ROLE=read\n", 0o400)
        w("/opt/hermes-agent/.env", "ANTHROPIC_API_KEY=sk-ant-api03-x\n")
        app = "/opt/projects/claude-google-ads"
        files = {"code/a.py": b"x"}
        w(app + "/code/a.py", "x")
        m = PK.build_manifest("claude_google_ads", "r", "a" * 40, files)
        open(R(app + "/" + PK.MANIFEST_NAME), "wb").write(PK.manifest_bytes(m))
        self.pin = PK.manifest_hash(m)
        os.makedirs(R("/run/lock"), exist_ok=True)
        RCA.PIN_OVERRIDE = self.pin          # tests bypass projects.yaml; main() reads the pin otherwise
        RCA.OWNER_UID = os.geteuid()         # tests are not root
        RCA.DATA_UID = RCA.DATA_GID = None   # skip chown to 10000 in tests
        RCA.RUN_AS_DATA_UID = []              # no setpriv in tests

    def run_main(self, runner, *extra):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = RCA.main(["acme-dental", *extra], runner=runner, root=self.root, now="2026-10-01_12-00-00")
        return rc, out.getvalue() + err.getvalue()


class TestHappyPath(Base):
    def test_all_steps_run_in_order_and_draft_lands_in_vault(self):
        r = FakeRunner(self.root)
        rc, text = self.run_main(r)
        self.assertEqual(rc, 0, text)
        names = [RCA.step_name(c["argv"]) for c in r.calls]
        self.assertEqual(names, [f"collect:{c}" for c in RCA.COLLECTORS] + ["snapshot"]
                         + [f"read:{x}" for x in RCA.READERS] + ["draft", "vault-write"])
        self.assertIn("data/vaults/acme-dental/audits/2026-10-01_12-00-00-audit.md", text)

    def test_credential_only_as_env_names_and_never_on_screen(self):
        r = FakeRunner(self.root)
        rc, text = self.run_main(r)
        for c in r.calls:
            self.assertNotIn(TOKEN, " ".join(c["argv"]))
        coll = r.calls[0]
        self.assertIn("GOOGLE_ADS_REFRESH_TOKEN", coll["argv"])           # passed as -e NAME
        self.assertEqual(coll["env"]["GOOGLE_ADS_REFRESH_TOKEN"], TOKEN)   # value only in env
        self.assertEqual(coll["env"]["GOOGLE_ADS_CUSTOMER_ID"], CID)
        self.assertEqual(coll["env"]["HERMES_AUDIT_DATA_DIR"], "/var/lib/hermes/audit-data/acme-dental")
        self.assertNotIn(TOKEN, text)
        self.assertNotIn(CID, text)

    def test_draft_step_never_gets_the_ads_credential(self):
        r = FakeRunner(self.root)
        self.run_main(r)
        draft = [c for c in r.calls if RCA.step_name(c["argv"]) == "draft"][0]
        self.assertFalse(any(k.startswith("GOOGLE_ADS_") for k in draft["env"]))

    def test_logs_are_0600_files_outside_the_mounted_tree(self):
        self.run_main(FakeRunner(self.root))
        logs = self.root + "/var/lib/hermes/audit-logs/acme-dental"
        self.assertTrue(os.path.exists(os.path.join(logs, "snapshot.stderr")))
        self.assertEqual(os.stat(logs).st_mode & 0o777, 0o711)
        names = os.listdir(logs)
        self.assertEqual(len(names), 2 * 10)                      # stdout + stderr for each step
        for n in names:
            self.assertEqual(os.lstat(os.path.join(logs, n)).st_mode & 0o777, 0o600, n)
        # the collector's rw mount holds no logs/ (C1): nothing there is ever opened as root
        self.assertFalse(os.path.lexists(self.root + "/var/lib/hermes/audit-data/acme-dental/logs"))

    def test_symlink_planted_at_the_next_log_is_not_followed(self):
        outside = tempfile.mkdtemp()
        target = os.path.join(outside, "profile.sh")
        open(target, "w").write("ORIGINAL\n")
        mode0 = os.stat(target).st_mode
        def plant():
            for d in (self.root + "/var/lib/hermes/audit-logs/acme-dental",
                      self.root + "/var/lib/hermes/audit-data/acme-dental/logs"):   # old layout
                if os.path.isdir(d):
                    os.symlink(target, os.path.join(d, f"collect-{RCA.COLLECTORS[1]}.stdout"))
        r = FakeRunner(self.root, after={f"collect:{RCA.COLLECTORS[0]}": plant})
        rc, text = self.run_main(r)
        self.assertNotEqual(rc, 0, text)
        self.assertEqual(open(target).read(), "ORIGINAL\n")
        self.assertEqual(os.stat(target).st_mode, mode0)                  # not chmodded either
        self.assertNotIn("Traceback", text); self.assertNotIn(CID, text)

    def test_snapshot_stdout_alone_is_handed_to_the_container_uid(self):
        from unittest import mock
        RCA.DATA_UID = RCA.DATA_GID = 10000
        fch, ch = [], []
        def rec_fchown(fd, uid, gid):
            fch.append((os.fstat(fd).st_ino, uid, gid))
        with mock.patch.object(RCA.os, "fchown", rec_fchown), \
             mock.patch.object(RCA.os, "chown", lambda p, u, g: ch.append((p, u, g))):
            rc, text = self.run_main(FakeRunner(self.root))
        self.assertEqual(rc, 0, text)
        snap = os.stat(self.root + "/var/lib/hermes/audit-logs/acme-dental/snapshot.stdout").st_ino
        self.assertEqual(fch, [(snap, 10000, 10000)])
        self.assertFalse(any(p.startswith(self.root + "/var/lib/hermes/audit-logs") and u == 10000
                             for p, u, g in ch), ch)

    def test_symlinked_transient_draft_or_vault_draft_is_not_trusted(self):
        outside = tempfile.mkdtemp()
        secret = os.path.join(outside, "x"); open(secret, "w").write("other-dental\n")
        ts = "2026-10-01_12-00-00"
        class Swap(FakeRunner):
            def __init__(s, root, where):
                super().__init__(root); s.where = where
            def __call__(s, argv, env, timeout, out, err):
                rc = super().__call__(argv, env, timeout, out, err)
                name = RCA.step_name(argv)
                if name == s.where:
                    d = {"draft": s.root + "/opt/hermes-agent/data/audits/claude_google_ads",
                         "vault-write": s.root + "/opt/hermes-agent/data/vaults/acme-dental/audits"}[name]
                    os.remove(os.path.join(d, ts + "-audit.md"))
                    os.symlink(secret, os.path.join(d, ts + "-audit.md"))
                return rc
        for where in ("draft", "vault-write"):
            self.setUp()
            rc, text = self.run_main(Swap(self.root, where))
            self.assertEqual(rc, 1, (where, text)); self.assertNotIn("Traceback", text)
            self.assertNotIn("draft ->", text)

    def test_vault_write_reads_the_snapshot_from_the_logs_dir(self):
        import client_audit_lib as L
        rec = L.eligible_client("acme-dental", self.root + RCA.REGISTRY)
        vw = [a for k, a, e in RCA.plan(rec, "2026-10-01_12-00-00", self.root) if k == "vault-write"][0]
        self.assertEqual(vw[vw.index("--metrics-file") + 1],
                         self.root + "/var/lib/hermes/audit-logs/acme-dental/snapshot.stdout")

    def test_timeouts_applied(self):
        r = FakeRunner(self.root)
        self.run_main(r)
        by = {RCA.step_name(c["argv"]): c["timeout"] for c in r.calls}
        self.assertEqual(by["draft"], RCA.TIMEOUTS["draft"])
        self.assertEqual(by[f"collect:{RCA.COLLECTORS[0]}"], RCA.TIMEOUTS["collect"])

    def test_vault_write_runs_as_the_container_uid(self):
        RCA.RUN_AS_DATA_UID = ["setpriv", "--reuid=10000", "--regid=10000", "--clear-groups"]
        import client_audit_lib as L
        rec = L.eligible_client("acme-dental", self.root + RCA.REGISTRY)
        vw = [a for k, a, e in RCA.plan(rec, "2026-10-01_12-00-00", self.root) if k == "vault-write"][0]
        self.assertEqual(vw[:4], ["setpriv", "--reuid=10000", "--regid=10000", "--clear-groups"])

    def test_transient_draft_is_removed_after_vault_write(self):
        self.run_main(FakeRunner(self.root))
        d = self.root + "/opt/hermes-agent/data/audits/claude_google_ads"
        self.assertEqual(os.listdir(d), [])


class TestFailClosed(Base):
    def test_stops_at_first_failed_step(self):
        r = FakeRunner(self.root, fail_on="snapshot")
        rc, text = self.run_main(r)
        self.assertEqual(rc, 1)
        self.assertNotIn("draft", [RCA.step_name(c["argv"]) for c in r.calls])
        self.assertIn("snapshot", text)

    def test_collector_error_file_blocks_draft(self):
        r = FakeRunner(self.root, error_file="negatives_audit.ERROR.txt")
        rc, text = self.run_main(r)
        self.assertEqual(rc, 1)
        self.assertIn("negatives_audit.ERROR.txt", text)
        self.assertNotIn("snapshot", [RCA.step_name(c["argv"]) for c in r.calls])

    def test_no_json_after_collection_blocks(self):
        rc, text = self.run_main(FakeRunner(self.root, collector_json=False))
        self.assertEqual(rc, 1)
        self.assertIn("no data", text)

    def test_stale_data_is_cleared_before_collecting(self):
        ad = self.root + "/var/lib/hermes/audit-data/acme-dental"
        os.makedirs(ad); open(ad + "/stale.json", "w").write("{}")
        self.run_main(FakeRunner(self.root))
        self.assertFalse(os.path.exists(ad + "/stale.json"))

    def test_draft_naming_another_client_fails_before_vault_write(self):
        r = FakeRunner(self.root, draft_text="compare with other-dental")
        rc, text = self.run_main(r)
        self.assertEqual(rc, 1)
        self.assertIn("other-dental", text)
        self.assertNotIn("vault-write", [RCA.step_name(c["argv"]) for c in r.calls])
        self.assertFalse(os.path.exists(self.root + "/opt/hermes-agent/data/vaults/acme-dental/audits/2026-10-01_12-00-00-audit.md"))
        self.assertEqual(os.listdir(self.root + "/opt/hermes-agent/data/audits/claude_google_ads"), [])


class TestPrechecks(Base):
    def test_retired_or_unknown_client_refused_before_any_step(self):
        r = FakeRunner(self.root)
        out = io.StringIO()
        with contextlib.redirect_stderr(out), contextlib.redirect_stdout(out):
            rc = RCA.main(["nobody"], runner=r, root=self.root, now="t")
        self.assertEqual(rc, 2); self.assertEqual(r.calls, [])

    def test_dummy_anthropic_key_refused(self):
        open(self.root + "/opt/hermes-agent/.env", "w").write("ANTHROPIC_API_KEY=dummy-key-this-wave\n")
        r = FakeRunner(self.root)
        rc, text = self.run_main(r)
        self.assertEqual(rc, 2); self.assertEqual(r.calls, []); self.assertIn("Anthropic", text)

    def test_package_mismatch_refused(self):
        open(self.root + "/opt/projects/claude-google-ads/code/a.py", "w").write("tampered")
        r = FakeRunner(self.root)
        self.assertEqual(self.run_main(r)[0], 2); self.assertEqual(r.calls, [])

    def test_lock_held_refused_with_rc_3(self):
        import client_audit_lib as L
        with L.AuditLock(self.root + "/run/lock/hermes-client-audit.lock"):
            r = FakeRunner(self.root)
            rc, text = self.run_main(r)
        self.assertEqual(rc, 3); self.assertEqual(r.calls, []); self.assertIn("another audit is running", text)

    def test_dry_run_prints_plan_runs_nothing_and_shows_no_secret(self):
        r = FakeRunner(self.root)
        rc, text = self.run_main(r, "--dry-run")
        self.assertEqual(rc, 0); self.assertEqual(r.calls, [])
        self.assertIn("ads-collector", text)
        self.assertNotIn(TOKEN, text); self.assertNotIn(CID, text)


class TestUnexpectedFailure(Base):
    def test_unreadable_credential_bytes_refused_rc2_normal_and_dry_run(self):
        p = self.root + "/etc/hermes/.env" + ".ga"
        os.chmod(p, 0o600); open(p, "wb").write(b"GOOGLE_ADS_X=\xff\n"); os.chmod(p, 0o400)
        for extra in ((), ("--dry-run",)):
            r = FakeRunner(self.root)
            rc, text = self.run_main(r, *extra)
            self.assertEqual(rc, 2, text); self.assertNotIn("Traceback", text)
            self.assertEqual(r.calls, [])

    def test_oserror_under_lock_is_a_redacted_rc1_not_a_traceback(self):
        parent = self.root + "/var/lib/hermes/audit-data"
        os.makedirs(os.path.dirname(parent), exist_ok=True)
        open(parent, "w").write("i am a file")          # reset_dir cannot create <parent>/<slug>
        r = FakeRunner(self.root)
        rc, text = self.run_main(r)
        self.assertEqual(rc, 1); self.assertEqual(r.calls, [])
        self.assertIn("run-client-audit: failed:", text)
        self.assertNotIn("Traceback", text); self.assertNotIn(CID, text)


if __name__ == "__main__":
    unittest.main()
