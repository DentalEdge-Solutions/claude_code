#!/usr/bin/env python3
import contextlib, importlib.util, io, json, os, signal, stat, subprocess, sys, tempfile, threading, unittest
from unittest import mock
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import package_lib as PK
spec = importlib.util.spec_from_file_location("rca", os.path.join(HERE, "run-client-audit.py"))
RCA = importlib.util.module_from_spec(spec); spec.loader.exec_module(RCA)
REAL_STOP_PROXY = RCA.stop_proxy      # Base stubs the module attribute; the real one is tested below

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
            d = self.root + "/var/lib/hermes/draft-out/acme-dental"
            os.makedirs(d, exist_ok=True)
            open(os.path.join(d, ts + "-audit.md"), "w").write(self.draft_text)
        if name == "vault-write":
            v = self.root + "/var/lib/hermes/vaults/acme-dental/audits"
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
        w("/etc/hermes/.env.anthropic", "ANTHROPIC_API_KEY=sk-ant-api03-x\n", 0o400)
        app = "/opt/projects/claude-google-ads"
        files = {"code/a.py": b"x"}
        w(app + "/code/a.py", "x")
        m = PK.build_manifest("claude_google_ads", "r", "a" * 40, files)
        open(R(app + "/" + PK.MANIFEST_NAME), "wb").write(PK.manifest_bytes(m))
        self.pin = PK.manifest_hash(m)
        os.makedirs(R("/run/lock"), exist_ok=True)
        for parent in ("/var/lib/hermes/vaults", "/var/lib/hermes/reports", "/var/lib/hermes/draft-out"):
            os.makedirs(R(parent), exist_ok=True); os.chmod(R(parent), 0o711)
        os.makedirs(R("/var/lib/hermes/vaults/acme-dental"), exist_ok=True)
        self.proxy_stops = []
        RCA.stop_proxy = lambda root, logs, say: self.proxy_stops.append((root, logs))
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
                         + [f"read:{x}" for x in RCA.READERS] + ["proxy", "draft", "vault-write"])
        self.assertIn("/var/lib/hermes/vaults/acme-dental/audits/2026-10-01_12-00-00-audit.md", text)

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
        self.assertEqual(len(names), 2 * 11)                      # stdout + stderr for each step (incl. proxy)
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
        # the test user cannot own the vault dir as 10000: that pre-check is not this test's subject
        with mock.patch.object(RCA.os, "fchown", rec_fchown), \
             mock.patch.object(RCA.os, "chown", lambda p, u, g: ch.append((p, u, g))), \
             mock.patch.object(RCA.L, "check_client_dir", lambda p, uid: None):
            rc, text = self.run_main(FakeRunner(self.root))
        self.assertEqual(rc, 0, text)
        snap = os.stat(self.root + "/var/lib/hermes/audit-logs/acme-dental/snapshot.stdout").st_ino
        self.assertEqual(sorted(fch), [(snap, 10000, 10000)])   # nothing else
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
                    d = {"draft": s.root + "/var/lib/hermes/draft-out/acme-dental",
                         "vault-write": s.root + "/var/lib/hermes/vaults/acme-dental/audits"}[name]
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

    def test_snapshot_runs_as_the_container_uid_and_keeps_its_name(self):
        # F2: the snapshot reads collector-controlled audit-data/<slug>/*.json; not as root
        RCA.RUN_AS_DATA_UID = ["setpriv", "--reuid=10000", "--regid=10000", "--clear-groups"]
        import client_audit_lib as L
        rec = L.eligible_client("acme-dental", self.root + RCA.REGISTRY)
        snap = [a for k, a, e in RCA.plan(rec, "2026-10-01_12-00-00", self.root) if k == "snapshot"][0]
        self.assertEqual(snap[:4], ["setpriv", "--reuid=10000", "--regid=10000", "--clear-groups"])
        self.assertEqual(RCA.step_name(snap), "snapshot")

    def test_transient_draft_is_removed_after_vault_write(self):
        self.run_main(FakeRunner(self.root))
        d = self.root + "/var/lib/hermes/draft-out/acme-dental"
        self.assertEqual(os.listdir(d), [])


class TestTimeouts(Base):
    def test_every_compose_run_step_is_named(self):
        import re
        r = FakeRunner(self.root)
        self.assertEqual(self.run_main(r)[0], 0)
        runs = [c["argv"] for c in r.calls if "run" in c["argv"] and "docker" in c["argv"]]
        self.assertEqual(len(runs), len(RCA.COLLECTORS) + len(RCA.READERS) + 1)   # + the drafter
        for a in runs:
            name = a[a.index("--name") + 1]
            slug = RCA.step_name(a).replace(":", "-")
            self.assertEqual(name, f"hermes-audit-2026-10-01_12-00-00-{slug}")
            self.assertRegex(name, r"^[a-z0-9_-]+$")
            svc = next(x for x in ("ads-collector", "ads-reader", "ads-drafter") if x in a)
            self.assertLess(a.index("--name"), a.index(svc))

    def test_timed_out_run_step_removes_its_container(self):
        d = tempfile.mkdtemp()
        cmds = []
        out, err = RCA.open_log(d + "/s.stdout"), RCA.open_log(d + "/s.stderr")
        with out, err:
            rc = RCA.real_runner(["sh", "-c", "sleep 5", "--name", "hermes-audit-x-collect-a"], None, 0.2,
                                 out, err, cleanup=lambda argv: cmds.append(argv) or 0)
        self.assertEqual(rc, 124)
        self.assertEqual(cmds, [["docker", "rm", "-f", "hermes-audit-x-collect-a"]])
        log = open(d + "/s.stderr").read()
        self.assertIn("timed out", log); self.assertIn("docker rm -f hermes-audit-x-collect-a", log)

    def test_timed_out_host_step_removes_nothing(self):
        d = tempfile.mkdtemp()
        cmds = []
        with RCA.open_log(d + "/o") as out, RCA.open_log(d + "/e") as err:
            rc = RCA.real_runner(["sleep", "5"], None, 0.2, out, err, cleanup=lambda a: cmds.append(a) or 0)
        self.assertEqual((rc, cmds), (124, []))

    def test_the_analyst_dies_inside_the_container_before_the_host_timeout(self):
        self.assertIn("timeout -k 30 1150 claude -p", RCA.DRAFT_SCRIPT)   # F3: SIGKILL if TERM is ignored
        self.assertLess(1150 + 30, RCA.TIMEOUTS["draft"])
        self.assertLess(1150, RCA.TIMEOUTS["draft"])


class TestDraftAndSnapshotArgs(Base):
    def test_snapshot_collected_at_is_iso_from_the_same_instant(self):
        r = FakeRunner(self.root)
        self.run_main(r)
        snap = [c["argv"] for c in r.calls if RCA.step_name(c["argv"]) == "snapshot"][0]
        self.assertEqual(snap[snap.index("--collected-at") + 1], "2026-10-01T12:00:00Z")
        vw = [c["argv"] for c in r.calls if RCA.step_name(c["argv"]) == "vault-write"][0]
        self.assertEqual(vw[vw.index("--ts") + 1], "2026-10-01_12-00-00")      # file names keep ts

    def test_draft_gets_its_values_inline_and_no_credential(self):
        r = FakeRunner(self.root)
        self.run_main(r)
        d = [c for c in r.calls if RCA.step_name(c["argv"]) == "draft"][0]
        a = d["argv"]
        for kv in ("PROJECT=claude_google_ads", "CLIENT=acme-dental", "TS=2026-10-01_12-00-00"):
            self.assertEqual(a[a.index(kv) - 1], "-e", kv)
        self.assertEqual(a[a.index("ANTHROPIC_API_KEY") - 1], "-e")           # a name only
        self.assertEqual(d["env"]["ANTHROPIC_API_KEY"], "sk-ant-api03-x")    # the value only in env
        self.assertFalse(any(k.startswith("GOOGLE_ADS_") for k in d["env"]), d["env"])
        self.assertFalse(any("GOOGLE_ADS_" in x for x in a), a)
        self.assertFalse(any("sk-ant" in x for x in a), a)

    def test_a_malformed_ts_is_refused(self):
        import client_audit_lib as L
        rec = L.eligible_client("acme-dental", self.root + RCA.REGISTRY)
        with self.assertRaises(ValueError):
            RCA.plan(rec, "2026-10-01_12-00-00; rm -rf /", self.root)


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

    def test_transient_draft_is_removed_when_a_later_step_fails(self):
        d = self.root + "/var/lib/hermes/draft-out/acme-dental"
        for runner in (FakeRunner(self.root, fail_on="vault-write"),
                       FakeRunner(self.root, raise_on=("vault-write", OSError))):
            rc, text = self.run_main(runner)
            self.assertEqual(rc, 1, text)
            self.assertEqual(os.listdir(d), [], text)

    def test_draft_naming_another_client_fails_before_vault_write(self):
        r = FakeRunner(self.root, draft_text="compare with other-dental")
        rc, text = self.run_main(r)
        self.assertEqual(rc, 1)
        self.assertIn("other-dental", text)
        self.assertNotIn("vault-write", [RCA.step_name(c["argv"]) for c in r.calls])
        self.assertFalse(os.path.exists(self.root + "/var/lib/hermes/vaults/acme-dental/audits/2026-10-01_12-00-00-audit.md"))
        self.assertEqual(os.listdir(self.root + "/var/lib/hermes/draft-out/acme-dental"), [])


class TestPrechecks(Base):
    def test_retired_or_unknown_client_refused_before_any_step(self):
        r = FakeRunner(self.root)
        out = io.StringIO()
        with contextlib.redirect_stderr(out), contextlib.redirect_stdout(out):
            rc = RCA.main(["nobody"], runner=r, root=self.root, now="t")
        self.assertEqual(rc, 2); self.assertEqual(r.calls, [])

    def test_dummy_anthropic_key_refused(self):
        p = self.root + "/etc/hermes/.env.anthropic"
        os.chmod(p, 0o600); open(p, "w").write("ANTHROPIC_API_KEY=dummy\n"); os.chmod(p, 0o400)
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
        self.assertIn("ANTHROPIC_API_KEY", text)          # the draft's env NAME is shown...
        self.assertNotIn("sk-ant-api03-x", text)          # ...never its value


class TestUnexpectedFailure(Base):
    def test_unreadable_credential_bytes_refused_rc2_normal_and_dry_run(self):
        p = self.root + "/etc/hermes/.env" + ".ga"
        os.chmod(p, 0o600); open(p, "wb").write(b"GOOGLE_ADS_X=\xff\n"); os.chmod(p, 0o400)
        for extra in ((), ("--dry-run",)):
            r = FakeRunner(self.root)
            rc, text = self.run_main(r, *extra)
            self.assertEqual(rc, 2, text); self.assertNotIn("Traceback", text)
            self.assertEqual(r.calls, [])

    def test_malformed_registry_entry_is_a_clean_refusal(self):
        # M12: a non-dict entry raises TypeError/AttributeError, not ValueError
        for entry in (5, None):
            open(self.root + RCA.REGISTRY, "w").write(json.dumps({"clients": {"acme-dental": entry}}))
            r = FakeRunner(self.root)
            rc, text = self.run_main(r)
            self.assertEqual(rc, 2, text); self.assertNotIn("Traceback", text); self.assertEqual(r.calls, [])

    def test_type_or_attribute_error_in_prechecks_is_rc2(self):
        from unittest import mock
        for exc in (TypeError, AttributeError):
            with mock.patch.object(RCA.L, "package_matches", side_effect=exc("bad manifest")):
                r = FakeRunner(self.root)
                rc, text = self.run_main(r)
            self.assertEqual(rc, 2, text); self.assertIn("refused", text); self.assertEqual(r.calls, [])

    def test_type_or_attribute_error_under_lock_is_rc1(self):
        for exc in (TypeError, AttributeError):
            r = FakeRunner(self.root, raise_on=("read:", exc))
            rc, text = self.run_main(r)
            self.assertEqual(rc, 1, text); self.assertIn("run-client-audit: failed:", text)
            self.assertNotIn(CID, text)

    def test_oserror_under_lock_is_a_redacted_rc1_not_a_traceback(self):
        parent = self.root + "/var/lib/hermes/audit-data"
        os.makedirs(os.path.dirname(parent), exist_ok=True)
        open(parent, "w").write("i am a file")          # reset_dir cannot create <parent>/<slug>
        r = FakeRunner(self.root)
        rc, text = self.run_main(r)
        self.assertEqual(rc, 1); self.assertEqual(r.calls, [])
        self.assertIn("run-client-audit: failed:", text)
        self.assertNotIn("Traceback", text); self.assertNotIn(CID, text)



class TestComposePathResolution(Base):
    """2026-09-30, first box run: /opt/hermes-agent is a SYMLINK into the checkout. Given
    `-f /opt/hermes-agent/docker-compose.yml`, compose resolved `../../../claude-google-ads`
    from the symlink's own location, to /claude-google-ads (an empty dir docker then created),
    so the collector failed to mount its .env mask. The compose file path must be resolved."""
    def _box_layout(self):
        import shutil
        os.makedirs(self.root + "/opt/hermes-agent", exist_ok=True)   # setUp no longer needs data/ under it
        real = self.root + "/opt/projects/claude_code/infra/hermes-agent"
        os.makedirs(os.path.dirname(real), exist_ok=True)
        shutil.move(self.root + "/opt/hermes-agent", real)
        os.symlink(real, self.root + "/opt/hermes-agent")
        return real

    def test_compose_gets_the_symlink_resolved_file(self):
        real = self._box_layout()
        import client_audit_lib as L
        rec = L.eligible_client("acme-dental", self.root + RCA.REGISTRY)
        for key, argv, env in RCA.plan(rec, "2026-10-01_12-00-00", self.root):
            if argv[:2] == ["docker", "compose"]:
                f = argv[argv.index("-f") + 1]
                self.assertEqual(f, os.path.realpath(real + "/docker-compose.yml"), key)
                self.assertNotIn("/opt/hermes-agent/", f)

    def test_draft_run_targets_the_drafter_in_the_hermes_agent_project(self):
        real = self._box_layout()
        import client_audit_lib as L
        rec = L.eligible_client("acme-dental", self.root + RCA.REGISTRY)
        draft = [a for k, a, e in RCA.plan(rec, "2026-10-01_12-00-00", self.root) if k == "draft"][0]
        f = draft[draft.index("-f") + 1]
        self.assertEqual(f, os.path.realpath(real + "/docker-compose.yml"))
        self.assertIn("run", draft); self.assertIn("ads-drafter", draft)
        self.assertNotIn("exec", draft); self.assertNotIn("hermes-agent", draft)   # not the gateway
        # compose derives the project name from the file's directory: it must stay "hermes-agent",
        # so the one-shot drafter joins the project's networks (and reaches egress-proxy).
        self.assertEqual(os.path.basename(os.path.dirname(f)), "hermes-agent")

class TestOptionBLayout(Base):
    def test_draft_gets_one_client_dirs_and_the_key_by_name(self):
        r = FakeRunner(self.root)
        rc, text = self.run_main(r)
        self.assertEqual(rc, 0, text)
        d = [c for c in r.calls if RCA.step_name(c["argv"]) == "draft"][0]
        self.assertEqual(d["env"]["HERMES_VAULT_DIR"], "/var/lib/hermes/vaults/acme-dental")
        self.assertEqual(d["env"]["HERMES_REPORTS_DIR"], "/var/lib/hermes/reports/acme-dental")
        self.assertEqual(d["env"]["HERMES_DRAFT_OUT_DIR"], "/var/lib/hermes/draft-out/acme-dental")
        self.assertIn("ANTHROPIC_API_KEY", d["argv"])
        self.assertNotIn("sk-ant-api03-x", " ".join(d["argv"]))
        self.assertNotIn("sk-ant-api03-x", text)

    def test_readers_get_the_per_client_reports_dir(self):
        r = FakeRunner(self.root)
        self.run_main(r)
        for c in r.calls:
            if RCA.step_name(c["argv"]).startswith("read:"):
                self.assertEqual(c["env"]["HERMES_REPORTS_DIR"], "/var/lib/hermes/reports/acme-dental")

    def test_proxy_started_before_draft_and_stopped_on_every_exit(self):
        for kw in ({}, {"fail_on": "draft"}, {"draft_text": "DRAFT names other-dental"},
                   {"raise_on": ("draft", OSError)}):
            with self.subTest(kw=kw):
                self.proxy_stops.clear()
                r = FakeRunner(self.root, **kw)
                self.run_main(r)
                names = [RCA.step_name(c["argv"]) for c in r.calls]
                self.assertEqual(names[names.index("draft") - 1], "proxy")
                self.assertEqual(self.proxy_stops,
                                 [(self.root, self.root + "/var/lib/hermes/audit-logs/acme-dental")])

    def test_proxy_stopped_even_if_removing_the_transient_draft_raises(self):
        def boom(root, slug, ts):
            raise OSError("draft-out vanished")
        with mock.patch.object(RCA, "remove_transient", boom):
            rc, text = self.run_main(FakeRunner(self.root))
        self.assertEqual(rc, 1, text); self.assertNotIn("Traceback", text)
        self.assertEqual(len(self.proxy_stops), 1)

    def test_proxy_not_started_when_collection_fails(self):
        r = FakeRunner(self.root, fail_on="collect")
        self.run_main(r)
        self.assertNotIn("proxy", [RCA.step_name(c["argv"]) for c in r.calls])

    def test_reports_and_draft_out_reset_each_run(self):
        stale = self.root + "/var/lib/hermes/reports/acme-dental/old.md"
        os.makedirs(os.path.dirname(stale)); open(stale, "w").close()
        self.run_main(FakeRunner(self.root))
        self.assertFalse(os.path.exists(stale))

    def test_bad_host_parent_refused_before_any_step(self):
        os.chmod(self.root + "/var/lib/hermes/vaults", 0o755)
        r = FakeRunner(self.root)
        rc, text = self.run_main(r)
        self.assertEqual(rc, 2); self.assertEqual(r.calls, [])

    def test_missing_client_vault_refused_before_any_step(self):
        os.rmdir(self.root + "/var/lib/hermes/vaults/acme-dental")
        r = FakeRunner(self.root)
        rc, text = self.run_main(r)
        self.assertEqual(rc, 2); self.assertEqual(r.calls, [])

    def test_anthropic_key_file_wrong_mode_refused(self):
        os.chmod(self.root + "/etc/hermes/.env.anthropic", 0o600)
        rc, text = self.run_main(FakeRunner(self.root))
        self.assertEqual(rc, 2)

    def test_symlink_in_draft_out_is_neither_read_nor_removed(self):
        """The drafter (uid 10000) plants a symlink where the draft should be: root must refuse
        to read it (rc 1, nothing reaches the vault) and must not unlink its target."""
        outside = tempfile.mkdtemp(); target = os.path.join(outside, "secret.md")
        open(target, "w").write("secret")
        fake = FakeRunner(self.root)
        def runner(argv, env, timeout, out, err):
            if RCA.step_name(argv) == "draft":        # plant instead of writing a draft
                d = self.root + "/var/lib/hermes/draft-out/acme-dental"
                os.symlink(target, os.path.join(d, "2026-10-01_12-00-00-audit.md"))
                return 0
            return fake(argv, env, timeout, out, err)
        rc, text = self.run_main(runner)
        self.assertEqual(rc, 1, text)
        self.assertEqual(open(target).read(), "secret")
        self.assertFalse(os.path.exists(self.root + "/var/lib/hermes/vaults/acme-dental/audits/"
                                        "2026-10-01_12-00-00-audit.md"))


class TestJson(Base):
    def run_json(self, runner, *extra):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = RCA.main(["acme-dental", "--json", *extra], runner=runner, root=self.root, now="2026-10-01_12-00-00")
        lines = out.getvalue().splitlines()
        self.assertEqual(len(lines), 1, out.getvalue())
        return rc, json.loads(lines[0]), err.getvalue()

    def test_ok(self):
        rc, j, _ = self.run_json(FakeRunner(self.root))
        self.assertEqual((rc, j["status"], j["reason"], j["exit_code"]), (0, "ok", None, 0))
        self.assertEqual(j["vault_path"], "/var/lib/hermes/vaults/acme-dental/audits/2026-10-01_12-00-00-audit.md")
        self.assertEqual([s["name"] for s in j["steps"]],
                         ["collect", "snapshot", "read", "proxy", "draft", "vault-write"])
        self.assertEqual(set(j), {"status", "reason", "exit_code", "ts", "steps", "vault_path"})

    def test_failed_step_names_its_class(self):
        rc, j, _ = self.run_json(FakeRunner(self.root, fail_on="read:audit_search_terms"))
        self.assertEqual((rc, j["status"], j["reason"]), (1, "failed", "read"))
        self.assertIsNone(j["vault_path"])

    def test_isolation_failure(self):
        rc, j, _ = self.run_json(FakeRunner(self.root, draft_text="DRAFT names other-dental"))
        self.assertEqual((j["status"], j["reason"]), ("failed", "isolation"))

    def test_collector_errors_are_collect(self):
        rc, j, _ = self.run_json(FakeRunner(self.root, error_file="x.ERROR.txt"))
        self.assertEqual((j["status"], j["reason"]), ("failed", "collect"))

    def test_precheck_refused(self):
        os.chmod(self.root + "/var/lib/hermes/vaults", 0o755)
        rc, j, err = self.run_json(FakeRunner(self.root))
        self.assertEqual((rc, j["status"], j["reason"]), (2, "refused", "precheck"))

    def test_unregistered_client_refused(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            rc = RCA.main(["nobody", "--json"], runner=FakeRunner(self.root), root=self.root)
        self.assertEqual(rc, 2)
        self.assertEqual(json.loads(out.getvalue())["reason"], "precheck")

    def test_busy(self):
        import fcntl
        fd = os.open(self.root + RCA.LOCK, os.O_RDWR | os.O_CREAT, 0o600); fcntl.flock(fd, fcntl.LOCK_EX)
        try:
            rc, j, _ = self.run_json(FakeRunner(self.root))
        finally:
            os.close(fd)
        self.assertEqual((rc, j["status"], j["reason"]), (3, "busy", "busy"))

    def test_unexpected_error_is_internal(self):
        rc, j, _ = self.run_json(FakeRunner(self.root, raise_on=("collect", OSError)))
        self.assertEqual((rc, j["status"], j["reason"]), (1, "failed", "internal"))

    def test_json_never_carries_a_customer_id_or_key(self):
        rc, j, err = self.run_json(FakeRunner(self.root))
        blob = json.dumps(j)
        self.assertNotIn(CID, blob); self.assertNotIn("sk-ant", blob); self.assertNotIn(CID, err)

    def test_dry_run_prints_one_line_and_runs_nothing(self):
        r = FakeRunner(self.root)
        rc, j, err = self.run_json(r, "--dry-run")
        self.assertEqual((rc, j["status"], j["reason"], j["steps"], j["vault_path"]), (0, "ok", None, [], None))
        self.assertEqual(r.calls, [])
        self.assertIn("would run [draft]", err)

    def test_plain_output_unchanged_without_json(self):
        rc, text = self.run_main(FakeRunner(self.root))
        self.assertEqual(rc, 0)
        self.assertNotIn('"status"', text)


class TestList(Base):
    def run_list(self, client="acme-dental"):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            rc = RCA.main([client, "--list", "--json"], runner=FakeRunner(self.root), root=self.root)
        return rc, json.loads(out.getvalue())

    def test_lists_timestamps_only_and_takes_no_lock(self):
        a = self.root + "/var/lib/hermes/vaults/acme-dental/audits"; os.makedirs(a)
        for ts in ("2026-09-01_10-00-00", "2026-09-30_10-00-00"):
            open(f"{a}/{ts}-audit.md", "w").close()
        open(f"{a}/readme.md", "w").close()
        import fcntl
        fd = os.open(self.root + RCA.LOCK, os.O_RDWR | os.O_CREAT, 0o600); fcntl.flock(fd, fcntl.LOCK_EX)
        try:
            rc, j = self.run_list()
        finally:
            os.close(fd)
        self.assertEqual((rc, j), (0, {"status": "ok", "audits": ["2026-09-01_10-00-00", "2026-09-30_10-00-00"]}))

    def test_no_audits_yet(self):
        self.assertEqual(self.run_list(), (0, {"status": "ok", "audits": []}))

    def test_inactive_client_refused(self):
        rc, j = self.run_list("nobody")
        self.assertEqual((rc, j["status"]), (2, "refused"))

    def test_list_requires_json(self):
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                RCA.main(["acme-dental", "--list"], runner=FakeRunner(self.root), root=self.root)

    def test_list_keeps_only_the_newest_24(self):
        a = self.root + "/var/lib/hermes/vaults/acme-dental/audits"; os.makedirs(a)
        all_ts = [f"2026-09-{d:02d}_10-00-00" for d in range(1, 31)]
        for ts in all_ts:
            open(f"{a}/{ts}-audit.md", "w").close()
        self.assertEqual(self.run_list(), (0, {"status": "ok", "audits": all_ts[-24:]}))

    def test_list_oserror_is_a_failed_list(self):
        """Controller addition: an entry vanishing between listdir and stat (a container-controlled
        dir) must still yield exactly one JSON line, not a traceback."""
        os.makedirs(self.root + "/var/lib/hermes/vaults/acme-dental/audits")
        def boom(fd):
            raise FileNotFoundError("vanished")
        with mock.patch.object(RCA.L, "list_audit_ts", boom):
            out = io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
                rc = RCA.main(["acme-dental", "--list", "--json"], runner=FakeRunner(self.root), root=self.root)
        lines = out.getvalue().splitlines()
        self.assertEqual(len(lines), 1, out.getvalue())
        self.assertEqual(lines[0], '{"reason": "internal", "status": "failed"}')
        self.assertEqual(rc, 1)


class TestJsonUnexpectedExceptions(Base):
    """Fix round 1: an exception OUTSIDE the caught tuple still yields one JSON line under --json
    (failed/internal, exit 1, only the type name on stderr); plain mode keeps its traceback."""
    def call(self, argv, runner=None):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = RCA.main(argv, runner=runner or FakeRunner(self.root), root=self.root, now="2026-10-01_12-00-00")
        lines = out.getvalue().splitlines()
        self.assertEqual(len(lines), 1, out.getvalue())
        self.assertNotIn("Traceback", err.getvalue())
        return rc, json.loads(lines[0]), err.getvalue()

    def test_eligible_client_keyerror(self):
        def boom(*a):
            raise KeyError(CID)
        with mock.patch.object(RCA.L, "eligible_client", boom):
            rc, j, err = self.call(["acme-dental", "--json"])
        self.assertEqual((rc, j["status"], j["reason"], j["steps"]), (1, "failed", "internal", []))
        self.assertIn("KeyError", err); self.assertNotIn(CID, err)

    def test_precheck_keyerror(self):
        def boom(*a, **k):
            raise KeyError(CID)
        with mock.patch.object(RCA.L, "package_matches", boom):
            rc, j, err = self.call(["acme-dental", "--json"])
        self.assertEqual((rc, j["status"], j["reason"], j["exit_code"], j["steps"]), (1, "failed", "internal", 1, []))
        self.assertIn("KeyError", err); self.assertNotIn(CID, err)

    def test_runner_runtimeerror_mid_run(self):
        rc, j, err = self.call(["acme-dental", "--json"],
                               FakeRunner(self.root, raise_on=("read:audit_search_terms", RuntimeError)))
        self.assertEqual((rc, j["status"], j["reason"]), (1, "failed", "internal"))
        self.assertEqual([s["name"] for s in j["steps"]], ["collect", "snapshot", "read"])
        self.assertEqual(len(self.proxy_stops), 1)
        self.assertIn("RuntimeError", err); self.assertNotIn("boom", err)

    def test_list_runtimeerror(self):
        def boom(fd):
            raise RuntimeError(CID)
        os.makedirs(self.root + "/var/lib/hermes/vaults/acme-dental/audits")
        with mock.patch.object(RCA.L, "list_audit_ts", boom):
            out, err = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                rc = RCA.main(["acme-dental", "--list", "--json"], runner=FakeRunner(self.root), root=self.root)
        self.assertEqual((rc, out.getvalue()), (1, '{"reason": "internal", "status": "failed"}\n'))
        self.assertNotIn(CID, err.getvalue())

    def test_list_eligible_client_runtimeerror(self):
        def boom(*a):
            raise RuntimeError("x")
        with mock.patch.object(RCA.L, "eligible_client", boom):
            out = io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
                rc = RCA.main(["acme-dental", "--list", "--json"], runner=FakeRunner(self.root), root=self.root)
        self.assertEqual((rc, out.getvalue()), (1, '{"reason": "internal", "status": "failed"}\n'))

    def test_plain_mode_still_propagates(self):
        with self.assertRaises(RuntimeError):
            self.run_main(FakeRunner(self.root, raise_on=("read:audit_search_terms", RuntimeError)))
        self.assertEqual(len(self.proxy_stops), 1)

    def test_keyboard_interrupt_propagates_under_json(self):
        with self.assertRaises(KeyboardInterrupt):
            self.run_main(FakeRunner(self.root, raise_on=("draft", KeyboardInterrupt)), "--json")
        self.assertEqual(len(self.proxy_stops), 1)


def Term(_msg):
    """What the SIGTERM handler raises, as FakeRunner's raise_on factory."""
    return SystemExit(143)


class TestSigterm(Base):
    """Spec §7: a host-runner timeout (SIGTERM, then SIGKILL after a grace) must not skip cleanup."""
    def test_handler_raises_systemexit_143_once(self):
        old = signal.signal(signal.SIGTERM, signal.SIG_DFL)
        self.addCleanup(signal.signal, signal.SIGTERM, old)
        with self.assertRaises(SystemExit) as cm:
            RCA._on_sigterm(signal.SIGTERM, None)
        self.assertEqual(cm.exception.code, 143)
        # a second TERM (the runner's process-group kill reaching us again) must not cut cleanup short
        self.assertEqual(signal.getsignal(signal.SIGTERM), signal.SIG_IGN)

    def test_sigterm_mid_run_still_stops_proxy_and_removes_the_transient_draft(self):
        r = FakeRunner(self.root, raise_on=("vault-write", Term))   # the draft is on disk by then
        with self.assertRaises(SystemExit) as cm:
            self.run_main(r)
        self.assertEqual(cm.exception.code, 143)
        self.assertEqual(len(self.proxy_stops), 1)
        self.assertEqual(os.listdir(self.root + "/var/lib/hermes/draft-out/acme-dental"), [])

    def test_sigterm_under_json_prints_one_failed_internal_line(self):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err), \
                self.assertRaises(SystemExit) as cm:
            RCA.main(["acme-dental", "--json"], runner=FakeRunner(self.root, raise_on=("draft", Term)),
                     root=self.root, now="2026-10-01_12-00-00")
        self.assertEqual(cm.exception.code, 143)
        lines = out.getvalue().splitlines()
        self.assertEqual(len(lines), 1, out.getvalue())
        j = json.loads(lines[0])
        self.assertEqual((j["status"], j["reason"]), ("failed", "internal"))
        self.assertEqual(len(self.proxy_stops), 1)
        self.assertNotIn("Traceback", err.getvalue())

    def test_real_sigterm_during_a_named_run_step_removes_its_container(self):
        old = signal.signal(signal.SIGTERM, RCA._on_sigterm)
        self.addCleanup(signal.signal, signal.SIGTERM, old)
        d = tempfile.mkdtemp(); cmds = []
        t = threading.Timer(0.3, os.kill, (os.getpid(), signal.SIGTERM)); t.start()
        self.addCleanup(t.cancel)
        with RCA.open_log(d + "/o") as out, RCA.open_log(d + "/e") as err, self.assertRaises(SystemExit) as cm:
            RCA.real_runner(["sh", "-c", "sleep 5", "--name", "hermes-audit-x-draft"], None, 10, out, err,
                            cleanup=lambda a: cmds.append(a) or 0)
        self.assertEqual(cm.exception.code, 143)
        self.assertEqual(cmds, [["docker", "rm", "-f", "hermes-audit-x-draft"]])
        self.assertIn("docker rm -f hermes-audit-x-draft", open(d + "/e").read())

    def test_second_term_during_cleanup_cannot_cut_stop_proxy_short(self):
        """Carried fix: as the real entrypoint, SIGTERM is blocked for _run's finally, so a TERM that
        lands while the proxy is being stopped is delivered only after stop_proxy has finished."""
        old = signal.signal(signal.SIGTERM, RCA._on_sigterm)
        self.addCleanup(signal.signal, signal.SIGTERM, old)
        steps = []
        def stop(root, logs, say):
            steps.append("start")
            os.kill(os.getpid(), signal.SIGTERM)          # the runner's TERM arrives mid-cleanup
            for _ in range(1000):                          # bytecode boundaries for a handler to run
                pass
            steps.append("rm")
        with mock.patch.object(RCA, "BLOCK_TERM_IN_CLEANUP", True), \
                mock.patch.object(RCA, "stop_proxy", stop), self.assertRaises(SystemExit) as cm:
            self.run_main(FakeRunner(self.root))
        self.assertEqual(steps, ["start", "rm"])           # stop_proxy ran to completion
        self.assertEqual(cm.exception.code, 143)            # the pending TERM still lands, after cleanup
        self.assertNotIn(signal.SIGTERM, signal.pthread_sigmask(signal.SIG_BLOCK, []))   # mask restored

    def test_cleanup_does_not_touch_the_signal_mask_under_tests(self):
        seen = []
        with mock.patch.object(RCA, "stop_proxy",
                               lambda r, l, s: seen.append(signal.SIGTERM in signal.pthread_sigmask(signal.SIG_BLOCK, []))):
            self.run_main(FakeRunner(self.root))
        self.assertEqual(seen, [False])

    def test_cleanup_commands_are_bounded_to_20s(self):
        seen = []
        def fake_run(argv, **kw):
            seen.append(kw.get("timeout"))
            return subprocess.CompletedProcess(argv, 0)
        with mock.patch.object(RCA.subprocess, "run", fake_run):
            RCA._quiet(["docker", "rm", "-f", "x"])
        self.assertTrue(seen and all(t is not None and t <= 20 for t in seen), seen)


class TestStopProxyKeepsTheDecisionLog(Base):
    """Spec §5.2 / D10.2: the proxy's host+decision log is captured before `rm -sf` destroys it."""
    def setUp(self):
        super().setUp()
        self.logs = self.root + "/var/lib/hermes/audit-logs/acme-dental"
        os.makedirs(self.logs)
        self.said = []

    def call(self, rm_rc=0, logs_rc=0):
        argvs = []
        def fake_run(argv, **kw):
            argvs.append((argv, kw.get("timeout")))
            if "logs" in argv:
                kw["stdout"].write("egress-proxy  | CONNECT api.anthropic.com:443 allow 1234 5678\n")
                kw["stdout"].flush()
                return subprocess.CompletedProcess(argv, logs_rc)
            return subprocess.CompletedProcess(argv, rm_rc)
        with mock.patch.object(RCA.subprocess, "run", fake_run):
            rc = REAL_STOP_PROXY(self.root, self.logs, self.said.append)
        return rc, argvs

    def test_logs_captured_before_rm_with_both_rcs(self):
        rc, argvs = self.call()
        self.assertEqual(rc, 0)
        self.assertEqual([("logs" in a, "rm" in a) for a, _ in argvs], [(True, False), (False, True)])
        self.assertIn("--no-color", argvs[0][0]); self.assertEqual(argvs[0][0][-1], "egress-proxy")
        self.assertEqual(argvs[1][0][-3:], ["rm", "-sf", "egress-proxy"])
        self.assertTrue(all(t is not None and t <= 20 for _, t in argvs), argvs)
        p = self.logs + "/proxy.log"
        st = os.lstat(p)
        self.assertEqual(stat.S_IMODE(st.st_mode), 0o600)
        text = open(p).read()
        self.assertIn("CONNECT api.anthropic.com:443 allow", text)
        self.assertIn("logs rc 0", text); self.assertIn("rm -sf egress-proxy rc 0", text)
        self.assertEqual(self.said, [])

    def test_failed_rm_is_recorded_and_warned(self):
        rc, _ = self.call(rm_rc=1)
        self.assertEqual(rc, 1)
        self.assertIn("rm -sf egress-proxy rc 1", open(self.logs + "/proxy.log").read())
        self.assertEqual(len(self.said), 1); self.assertIn("WARNING", self.said[0])
        self.assertIn("egress-proxy", self.said[0])

    def test_planted_proxy_log_is_not_followed_and_rm_still_runs(self):
        target = os.path.join(tempfile.mkdtemp(), "t"); open(target, "w").write("keep")
        os.symlink(target, self.logs + "/proxy.log")
        rc, argvs = self.call()
        self.assertEqual(open(target).read(), "keep")
        self.assertTrue(any("rm" in a for a, _ in argvs))
        self.assertTrue(self.said and "WARNING" in self.said[0])

    def test_failed_proxy_log_write_does_not_skip_rm(self):
        """Carried fix: an OSError writing/flushing/closing proxy.log (disk full) must not skip `rm -sf`."""
        class Full:
            def write(self, _): raise OSError(28, "No space left on device")
            def flush(self): raise OSError(28, "No space left on device")
            def close(self): raise OSError(28, "No space left on device")
            def fileno(self): return 2
        argvs = []
        def fake_run(argv, **kw):
            argvs.append(argv)
            return subprocess.CompletedProcess(argv, 0)
        with mock.patch.object(RCA, "open_log", lambda p: Full()), \
                mock.patch.object(RCA.subprocess, "run", fake_run):
            rc = REAL_STOP_PROXY(self.root, self.logs, self.said.append)
        self.assertEqual(rc, 0)
        self.assertTrue(any(a[-3:] == ["rm", "-sf", "egress-proxy"] for a in argvs), argvs)
        self.assertTrue(any("proxy.log" in m and "WARNING" in m for m in self.said), self.said)

    def test_real_run_writes_proxy_log_on_every_exit(self):
        for kw in ({}, {"fail_on": "collect"}, {"raise_on": ("draft", OSError)}):
            with self.subTest(kw=kw):
                calls = []
                def fake_run(argv, **k):
                    calls.append(argv)
                    if "logs" in argv:
                        k["stdout"].write("proxy decision\n")
                    return subprocess.CompletedProcess(argv, 0)
                with mock.patch.object(RCA, "stop_proxy", REAL_STOP_PROXY), \
                        mock.patch.object(RCA.subprocess, "run", fake_run):
                    self.run_main(FakeRunner(self.root, **kw))
                self.assertIn("proxy decision", open(self.logs + "/proxy.log").read())


if __name__ == "__main__":
    unittest.main()
