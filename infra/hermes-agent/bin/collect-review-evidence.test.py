#!/usr/bin/env python3
import contextlib, importlib.util, io, json, os, sys, tempfile, unittest
from unittest import mock
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import review_lib as R
spec = importlib.util.spec_from_file_location("collect_review_evidence", os.path.join(HERE, "collect-review-evidence.py"))
CE = importlib.util.module_from_spec(spec); spec.loader.exec_module(CE)

TOKEN = "1//0gFAKEREFRESHTOKENabcdefghijklmnop"


class FakeHost(CE.Host):
    def __init__(self, root, outputs):
        super().__init__(root=root, run=self._fake)
        self.outputs, self.calls = outputs, []

    def _fake(self, argv, timeout=60):
        self.calls.append(argv)
        for prefix, result in self.outputs.items():
            if tuple(argv[:len(prefix)]) == prefix:
                return result
        return (127, "", "not found")


class Base(unittest.TestCase):
    KEY = bytes.fromhex("11" * 32)

    def setUp(self):
        self.root = tempfile.mkdtemp()
        self._w(CE.GOV + "/registry/clients.json",
                json.dumps({"clients": {"acme-dental": {"customer_id": "1234567890", "status": "active",
                                                        "mutation_target": "dormant_pilot"}}}))
        self._w(CE.AGENT_DIR + "/.env.gaw", f"GOOGLE_ADS_CREDENTIAL_ROLE=write\nGOOGLE_ADS_REFRESH_TOKEN={TOKEN}\n")
        self.outputs = {
            ("find",): (0, CE.AGENT_DIR + "/.env.gaw\n" + CE.AGENT_DIR + "/.env.gaw.example\n", ""),
            # -tulnH: Netid is column 0, local address column 4 (final-review B1).
            ("ss",): (0, "tcp LISTEN 0 4096 0.0.0.0:22 0.0.0.0:*\n"
                         "tcp LISTEN 0 4096 127.0.0.1:9119 0.0.0.0:*\n", ""),
            ("runuser",): (1, "mismatch log/acme-dental.jsonl expected 0660\n", ""),
            ("docker", "ps"): (0, "", ""),
        }

    def _w(self, rel, body):
        p = os.path.join(self.root, rel.lstrip("/"))
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w") as f:
            f.write(body)
        return p

    def host(self):
        return FakeHost(self.root, self.outputs)


class TestBundle(Base):
    def test_foreign_tool_output_is_redacted(self):
        out = json.dumps(CE.collect(self.host(), self.KEY))
        self.assertNotIn("acme-dental", out)
        self.assertIn("log/<client>.jsonl", out)

    def test_no_credential_value_or_customer_id_anywhere(self):
        out = json.dumps(CE.collect(self.host(), self.KEY))
        self.assertNotIn(TOKEN, out)
        self.assertNotIn("1234567890", out)
        self.assertIn(R.sha12(TOKEN), out)                          # control: fingerprint present

    def test_failed_command_is_could_not_check(self):
        items = CE.collect(self.host(), self.KEY)["items"]
        self.assertEqual(items["D1.2"]["status"], R.COULD_NOT_CHECK)   # ufw: not in fake outputs
        self.assertEqual(items["D1.1"]["status"], R.OBSERVED)          # control: ss answered

    def test_gateway_not_running_is_could_not_check(self):
        items = CE.collect(self.host(), self.KEY)["items"]
        self.assertEqual(items["D4.1"]["status"], R.COULD_NOT_CHECK)

    def test_missing_clients_json_refuses_to_print(self):
        os.remove(os.path.join(self.root, CE.GOV.lstrip("/"), "registry/clients.json"))
        self.assertEqual(CE.main(["--fp-key-tty"], host=self.host(), read_key=lambda: "11" * 32), 2)

    def test_every_checklist_box_id_has_a_probe_and_nothing_else_runs(self):
        items = CE.collect(self.host(), self.KEY)["items"]
        self.assertEqual(sorted(items), sorted(CE.PROBES))

    def test_backup_dir_named_after_a_client_is_redacted(self):
        self._w("/root/live-gate-acme-dental-20260901/note.txt", "hi")
        out = json.dumps(CE.collect(self.host(), self.KEY))
        self.assertNotIn("acme-dental", out)
        self.assertIn("live-gate-<client>-20260901", out)

    def test_docker_group_absent_is_empty(self):
        self.outputs[("getent", "group", "docker")] = (2, "", "")
        items = CE.collect(self.host(), self.KEY)["items"]
        self.assertEqual(items["D1.6"]["status"], R.OBSERVED)
        self.assertEqual(items["D1.6"]["data"], {"docker_group_members": []})

    def test_getent_failure_is_could_not_check(self):
        self.outputs[("getent", "group", "docker")] = (1, "", "boom")
        items = CE.collect(self.host(), self.KEY)["items"]
        self.assertEqual(items["D1.6"]["status"], R.COULD_NOT_CHECK)

    # ---- A1: the sweep must be honest about a non-zero find, even rc 1 with output ----

    def test_find_rc1_with_output_is_still_could_not_check(self):
        self.outputs[("find",)] = (1, CE.AGENT_DIR + "/.env.gaw\n",
                                   "find: '/proc/1234/fd': Permission denied\n"
                                   "find: '/proc/5678/task': Permission denied\n")
        items = CE.collect(self.host(), self.KEY)["items"]
        self.assertEqual(items["D2.1"]["status"], R.COULD_NOT_CHECK)
        self.assertIn("exited 1", items["D2.1"]["reason"])
        self.assertIn("2 stderr lines", items["D2.1"]["reason"])
        self.assertNotIn("Permission denied", items["D2.1"]["reason"])

    def test_find_rc0_control_still_observed(self):
        items = CE.collect(self.host(), self.KEY)["items"]
        self.assertEqual(items["D2.1"]["status"], R.OBSERVED)   # control

    def test_d6_2_find_nonzero_is_could_not_check_never_leaks_stderr_text(self):
        # The generic ("find",) fixture answers every find call, including d6_2's — split
        # it into two specific prefixes so the sweep (D2.1) can stay healthy as a control
        # while only d6_2's own find call is made to fail.
        del self.outputs[("find",)]
        self.outputs[("find", "/", "-xdev")] = (
            0, CE.AGENT_DIR + "/.env.gaw\n" + CE.AGENT_DIR + "/.env.gaw.example\n", "")
        self.outputs[("find", "/root")] = (1, "", "find: '/root/x': Permission denied\n")
        items = CE.collect(self.host(), self.KEY)["items"]
        self.assertEqual(items["D6.2"]["status"], R.COULD_NOT_CHECK)
        self.assertIn("exited 1", items["D6.2"]["reason"])
        self.assertIn("1 stderr lines", items["D6.2"]["reason"])
        self.assertNotIn("Permission denied", items["D6.2"]["reason"])
        self.assertEqual(items["D2.1"]["status"], R.OBSERVED)   # control: sweep unaffected

    # ---- A2: filesystem coverage — what the sweep did NOT cross ----------------------

    def test_not_swept_lists_non_pseudo_mounts_other_than_root(self):
        self.outputs[("findmnt",)] = (0, "/ ext4\n/proc proc\n/dev/shm tmpfs\n/boot ext4\n", "")
        items = CE.collect(self.host(), self.KEY)["items"]
        self.assertEqual(items["D2.1"]["data"]["not_swept"], ["/boot", "/dev/shm"])

    def test_not_swept_could_not_check_when_findmnt_fails_but_item_stays_observed(self):
        # findmnt is not in the fake outputs -> falls through to (127, "", "not found")
        items = CE.collect(self.host(), self.KEY)["items"]
        self.assertEqual(items["D2.1"]["status"], R.OBSERVED)           # control
        self.assertEqual(items["D2.1"]["data"]["not_swept"], "could-not-check")

    # ---- A3: one sweep per run ---------------------------------------------------

    def test_sweep_runs_only_once_per_full_collect(self):
        h = self.host()
        CE.collect(h, self.KEY)
        sweep_calls = [c for c in h.calls if c[:3] == ["find", "/", "-xdev"]]
        self.assertEqual(len(sweep_calls), 1)

    def test_d2_1_and_installed_credentials_see_the_same_list(self):
        h = self.host()
        ctx = CE.context(h)
        d2_1_data = CE.d2_1(h, ctx)
        sweep = CE._shared_sweep(h, ctx)
        infos, _secrets, _unparsed, _unreadable = CE.installed_credentials(h, sweep=sweep)
        self.assertEqual(sorted(row["path"] for row in d2_1_data["files"]),
                         sorted({CE.AGENT_DIR + "/.env.gaw", CE.AGENT_DIR + "/.env.gaw.example"}))
        self.assertEqual([i["path"] for i in infos], [CE.AGENT_DIR + "/.env.gaw"])

    # ---- A4: unparsed / unreadable credential-shaped hits -------------------------

    def test_unparsed_credential_shaped_hit_is_flagged_and_credentials_only_exits_2(self):
        self.outputs[("find",)] = (0, CE.AGENT_DIR + "/.env.leaked\n", "")
        self._w(CE.AGENT_DIR + "/.env.leaked", f"leaked during debugging: {TOKEN}\n")
        items = CE.collect(self.host(), self.KEY)["items"]
        rows = items["D2.1"]["data"]["files"]
        self.assertEqual([r["kind"] for r in rows], ["unparsed"])
        self.assertNotIn("credential", rows[0])
        rc = CE.main(["--credentials-only"], host=self.host())
        self.assertEqual(rc, 2)

    def test_unreadable_credential_shaped_hit_is_flagged_and_credentials_only_exits_2(self):
        # A path the sweep reports that does not actually exist on disk -> OSError on open.
        self.outputs[("find",)] = (0, CE.AGENT_DIR + "/.env.ghost\n", "")
        rc = CE.main(["--credentials-only"], host=self.host())
        self.assertEqual(rc, 2)

    def test_clean_credential_control_credentials_only_exits_0(self):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = CE.main(["--credentials-only"], host=self.host())
        self.assertEqual(rc, 0)                                          # control

    def test_credentials_only_could_not_check_sweep_exits_2_no_traceback(self):
        self.outputs[("find",)] = (1, "", "boom\n")
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            rc = CE.main(["--credentials-only"], host=self.host())
        self.assertEqual(rc, 2)
        self.assertIn("collect-review-evidence:", err.getvalue())

    # ---- B: entry points include UDP -----------------------------------------------

    def test_d1_1_includes_tcp_and_udp_prefixed(self):
        self.outputs[("ss",)] = (0, "tcp LISTEN 0 4096 0.0.0.0:22 0.0.0.0:*\n"
                                     "udp UNCONN 0 0 0.0.0.0:41641 0.0.0.0:*\n", "")
        items = CE.collect(self.host(), self.KEY)["items"]
        self.assertEqual(items["D1.1"]["data"]["listeners"],
                         ["tcp 0.0.0.0:22", "udp 0.0.0.0:41641"])

    def _make_other_components_healthy(self):
        # box_fingerprint hashes 5 components; isolate the firewall-ruleset behaviour
        # below by making everything ELSE entry_points() and its sibling components
        # touch succeed too, so "complete" reflects only the nft/iptables-save outcome.
        self.outputs[("git",)] = (0, "deadbeefdeadbeefdeadbeefdeadbeefdeadbeef\n", "")
        self.outputs[("ufw",)] = (0, "Status: active\n", "")
        self.outputs[("sshd",)] = (0, "permitrootlogin no\n", "")
        self._w(CE.CHECKLIST, "version: 1.2\n")

    def test_entry_points_uses_nft_ruleset_when_available(self):
        self._make_other_components_healthy()
        self.outputs[("nft", "-s")] = (0, "table inet filter {}\n", "")
        h = self.host()
        fp = CE.box_fingerprint(h, CE.context(h))
        self.assertTrue(fp["complete"])

    def test_entry_points_falls_back_to_iptables_save(self):
        self._make_other_components_healthy()
        self.outputs[("iptables-save",)] = (0, "*filter\nCOMMIT\n", "")
        h = self.host()
        fp = CE.box_fingerprint(h, CE.context(h))
        self.assertTrue(fp["complete"])

    def test_entry_points_incomplete_when_both_firewall_reads_fail(self):
        self._make_other_components_healthy()
        h = self.host()                                       # neither nft nor iptables-save fake
        fp = CE.box_fingerprint(h, CE.context(h))
        self.assertFalse(fp["complete"])                       # control: everything else healthy

    def test_fingerprint_is_stable_across_counter_changes(self):
        self._make_other_components_healthy()
        base = ("table inet filter {\n"
                "\tchain input {\n"
                "\t\ttype filter hook input priority 0; policy drop;\n"
                "\t\tcounter packets 12 bytes 840\n"
                "\t\ttcp dport 22 accept\n"
                "\t}\n"
                "}\n"
                "table ip filter {\n"
                "\tchain DOCKER {\n"
                "\t\tcounter packets 3 bytes 180\n"
                "\t\tip daddr %s accept\n"
                "\t}\n"
                "\tchain DOCKER-USER {\n"
                "\t\treturn\n"
                "\t}\n"
                "}\n")
        h1 = self.host()
        self.outputs[("nft", "-s")] = (0, base % "172.17.0.2", "")
        fp1 = CE.box_fingerprint(h1, CE.context(h1))
        self.assertTrue(fp1["complete"])

        h2 = self.host()
        variant = (base % "172.17.0.9").replace("counter packets 12 bytes 840",
                                                  "counter packets 99 bytes 7331")
        self.outputs[("nft", "-s")] = (0, variant, "")
        fp2 = CE.box_fingerprint(h2, CE.context(h2))
        self.assertEqual(fp1["fingerprint"], fp2["fingerprint"])

        h3 = self.host()
        control = (base % "172.17.0.2").replace(
            "tcp dport 22 accept", "tcp dport 22 accept\n\t\tudp dport 41641 accept")
        self.outputs[("nft", "-s")] = (0, control, "")
        fp3 = CE.box_fingerprint(h3, CE.context(h3))
        self.assertNotEqual(fp1["fingerprint"], fp3["fingerprint"])


class TestTighteningAfterReview3(Base):
    """Review #3's non-blocking findings: freshness, in-memory mounts, .env kinds,
    the D6.1 .env exemption, and history coverage."""
    GATEWAY_ENV = CE.CHECKOUT + "/infra/hermes-agent/.env"
    APP_ENV = CE.APP_HOST_DIRS["claude_google_ads"] + "/.env"

    def _rows(self):
        return {r["path"]: r for r in CE.collect(self.host(), self.KEY)["items"]["D2.1"]["data"]["files"]}

    # ---- a: freshness ----------------------------------------------------------
    def test_bundle_carries_collected_at_utc(self):
        b = CE.collect(self.host(), self.KEY)
        self.assertRegex(b["collected_at"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$")

    def test_collected_at_is_not_part_of_the_fingerprint(self):
        h = self.host()
        self.assertNotIn("collected_at", json.dumps(CE.box_fingerprint(h, CE.context(h))))

    # ---- b: in-memory mounts are swept by the collector itself -------------------
    def test_memory_sweep_finds_credential_name_and_content_without_printing_the_value(self):
        self.outputs[("findmnt",)] = (0, "/ ext4\n/dev/shm tmpfs\n/run/user/1000 tmpfs\n/boot ext4\n", "")
        self._w("/dev/shm/.env.stash", "FOO=1\n")
        self._w("/run/user/1000/notes.txt", f"pasted {TOKEN}\n")
        self._w("/run/user/1000/clean.txt", "nothing here\n")
        out = CE.collect(self.host(), self.KEY)
        ms = out["items"]["D2.1"]["data"]["memory_sweep"]
        self.assertEqual(ms["mounts"], ["/dev/shm", "/run/user/1000"])
        self.assertEqual(ms["name_hits"], ["/dev/shm/.env.stash"])
        self.assertEqual(ms["content_hits"], ["/run/user/1000/notes.txt"])
        self.assertNotIn(TOKEN, json.dumps(out))

    def test_memory_sweep_clean_control(self):
        self.outputs[("findmnt",)] = (0, "/ ext4\n/dev/shm tmpfs\n", "")
        self._w("/dev/shm/sem.x", "nothing\n")
        ms = CE.collect(self.host(), self.KEY)["items"]["D2.1"]["data"]["memory_sweep"]
        self.assertEqual((ms["mounts"], ms["name_hits"], ms["content_hits"]), (["/dev/shm"], [], []))

    def test_memory_sweep_reports_an_unenterable_dir_instead_of_skipping_it(self):
        if os.geteuid() == 0:
            self.skipTest("root can enter a 0000 directory")
        self.outputs[("findmnt",)] = (0, "/ ext4\n/dev/shm tmpfs\n", "")
        self._w("/dev/shm/locked/f", "x\n")
        locked = os.path.join(self.root, "dev/shm/locked")
        os.chmod(locked, 0)
        try:
            ms = CE.collect(self.host(), self.KEY)["items"]["D2.1"]["data"]["memory_sweep"]
        finally:
            os.chmod(locked, 0o700)
        self.assertEqual(ms["unreadable"], ["/dev/shm/locked"])

    def test_memory_sweep_survives_a_dir_vanishing_mid_walk(self):
        self.outputs[("findmnt",)] = (0, "/ ext4\n/run tmpfs\n", "")
        self._w("/run/gone/f", "x\n")
        real = os.lstat
        def flaky(p, *a, **k):
            if p.endswith("/run/gone"):
                raise FileNotFoundError(p)
            return real(p, *a, **k)
        from unittest import mock
        with mock.patch.object(CE.os, "lstat", side_effect=flaky):
            items = CE.collect(self.host(), self.KEY)["items"]
        self.assertEqual(items["D2.1"]["status"], R.OBSERVED)
        self.assertEqual(items["D2.1"]["data"]["memory_sweep"]["mounts"], ["/run"])

    def test_memory_sweep_could_not_check_when_findmnt_fails_item_stays_observed(self):
        items = CE.collect(self.host(), self.KEY)["items"]                   # findmnt not faked
        self.assertEqual(items["D2.1"]["status"], R.OBSERVED)
        self.assertEqual(items["D2.1"]["data"]["memory_sweep"], R.COULD_NOT_CHECK)

    # ---- c: every sweep hit gets a meaningful kind -----------------------------------
    def test_env_files_are_classified(self):
        self._w(self.GATEWAY_ENV, "HERMES_DASHBOARD_BASIC_AUTH_PASSWORD=hunter2hunter2\n")
        self._w(self.APP_ENV, "")
        self._w("/etc/someapp/.env", "API_KEY=abc\n")
        self.outputs[("find",)] = (0, "\n".join([CE.AGENT_DIR + "/.env.gaw", self.GATEWAY_ENV,
                                                 self.APP_ENV, "/etc/someapp/.env"]) + "\n", "")
        rows = self._rows()
        self.assertEqual(rows[CE.AGENT_DIR + "/.env.gaw"]["kind"], "credential")
        self.assertEqual(rows[self.GATEWAY_ENV]["kind"], "authorised-other")
        self.assertEqual(rows[self.GATEWAY_ENV]["label"], "gateway-env")
        self.assertEqual(rows[self.APP_ENV]["kind"], "empty")
        self.assertEqual(rows["/etc/someapp/.env"]["kind"], "unlisted")

    def test_authorised_path_holding_a_google_credential_is_still_a_credential(self):
        self._w(self.GATEWAY_ENV, f"GOOGLE_ADS_REFRESH_TOKEN={TOKEN}\n")
        self.outputs[("find",)] = (0, self.GATEWAY_ENV + "\n", "")
        self.assertEqual(self._rows()[self.GATEWAY_ENV]["kind"], "credential")

    # ---- d: the app .env is exempt from `extra` only while empty ----------------------
    def _install_package(self, env_body):
        import package_lib as PK
        d = CE.APP_HOST_DIRS["claude_google_ads"]
        self._w(CE.CHECKOUT + "/infra/hermes-agent/registry/projects.yaml",
                "projects:\n  claude_google_ads:\n    workdir: /projects/claude_google_ads\n")
        self._w(d + "/code/a.py", "print(1)\n")
        m = PK.build_manifest("claude_google_ads", "r", "a" * 40, {"code/a.py": b"print(1)\n"})
        with open(os.path.join(self.root, (d + "/" + PK.MANIFEST_NAME).lstrip("/")), "wb") as f:
            f.write(PK.manifest_bytes(m))
        if env_body is not None:
            self._w(d + "/.env", env_body)

    def test_d6_1_empty_env_is_not_extra(self):
        self._install_package("")
        row = CE.collect(self.host(), self.KEY)["items"]["D6.1"]["data"]["claude_google_ads"]
        self.assertEqual(row["extra"], [])
        self.assertEqual(row["env_file"], {"present": True, "size": 0})

    def test_d6_1_non_empty_env_is_extra(self):
        self._install_package("GOOGLE_ADS_DEVELOPER_TOKEN=x\n")
        row = CE.collect(self.host(), self.KEY)["items"]["D6.1"]["data"]["claude_google_ads"]
        self.assertEqual(row["extra"], [".env"])

    def test_d6_1_absent_env_control(self):
        self._install_package(None)
        row = CE.collect(self.host(), self.KEY)["items"]["D6.1"]["data"]["claude_google_ads"]
        self.assertEqual((row["extra"], row["env_file"]), ([], {"present": False, "size": 0}))

    # ---- e: every home in /etc/passwd, and more history kinds --------------------------
    def test_history_sweep_covers_passwd_homes_and_more_file_kinds(self):
        self._w("/etc/passwd", "root:x:0:0:root:/root:/bin/bash\n"
                               "hermes-broker:x:998:998::/var/lib/hermes-broker:/usr/sbin/nologin\n")
        self._w("/var/lib/hermes-broker/.psql_history", f"\\set t {TOKEN}\n")
        self._w("/root/.bash_history", "ls\n")
        h = CE.collect(self.host(), self.KEY)["items"]["D2.2"]["data"]["histories"]
        self.assertEqual(h["/var/lib/hermes-broker/.psql_history"]["pattern_hits"], 1)
        self.assertEqual(h["/root/.bash_history"]["pattern_hits"], 0)      # control

    def test_history_sweep_without_passwd_falls_back_to_root_and_home(self):
        self._w("/home/alice/.bash_history", "ls\n")
        h = CE.collect(self.host(), self.KEY)["items"]["D2.2"]["data"]["histories"]
        self.assertIn("/home/alice/.bash_history", h)


class TestCredentialsOnly(Base):
    def test_lists_the_installed_set_by_fingerprint(self):
        infos, _secrets, _unparsed, _unreadable = CE.installed_credentials(self.host())
        self.assertEqual(R.credential_set(infos),
                         [{"role": "write", "refresh_token_sha12": R.sha12(TOKEN), "client_id_sha12": None}])

    def test_examples_are_not_credentials(self):
        infos, _secrets, _unparsed, _unreadable = CE.installed_credentials(self.host())
        self.assertEqual([os.path.basename(i["path"]) for i in infos], [".env.gaw"])


class TestFingerprint(Base):
    def test_stable_across_runs(self):
        h = self.host()
        self.assertEqual(CE.box_fingerprint(h, CE.context(h)), CE.box_fingerprint(h, CE.context(h)))

    def test_clients_change_changes_it(self):
        h = self.host(); a = CE.box_fingerprint(h, CE.context(h))
        self._w(CE.GOV + "/registry/clients.json", json.dumps({"clients": {}}))
        self.assertNotEqual(a["fingerprint"], CE.box_fingerprint(h, CE.context(h))["fingerprint"])

    def test_credentials_are_not_part_of_the_box_fingerprint(self):
        h = self.host(); a = CE.box_fingerprint(h, CE.context(h))
        os.remove(os.path.join(self.root, CE.AGENT_DIR.lstrip("/"), ".env.gaw"))
        self.assertEqual(a, CE.box_fingerprint(h, CE.context(h)))


class TestAuditsOnTheBox(Base):
    def test_gateway_probe_includes_the_box_credential_path(self):
        self.assertIn("/etc/hermes/.env" + ".ga", CE.GATEWAY_PROBE_PATHS)

    def test_d7_1_reports_audit_data_dirs_by_status_without_slugs(self):
        os.makedirs(os.path.join(self.root, "var/lib/hermes/audit-data/acme-dental"))
        os.makedirs(os.path.join(self.root, "var/lib/hermes/audit-data/ghost-client"))
        out = CE.collect(self.host(), self.KEY)
        rows = out["items"]["D7.1"]["data"]["audit_data"]
        self.assertEqual(sorted(r["status"] for r in rows), ["active", "unregistered"])
        self.assertNotIn("ghost-client", json.dumps(out))


    def _d7_setup(self):
        self._w(CE.GOV + "/registry/clients.json", json.dumps({"clients": {
            "acme-dental": {"customer_id": "1234567890", "status": "active"},
            "gone-dental": {"customer_id": "2223334444", "status": "retired"}}}))

    def test_d7_1_audit_logs_root_and_rows_by_status_without_slugs(self):
        self._d7_setup()
        base = os.path.join(self.root, "var/lib/hermes/audit-logs")
        for n in ("acme-dental", "gone-dental", "stray-dental"):
            os.makedirs(os.path.join(base, n))
        out = CE.collect(self.host(), self.KEY)
        al = out["items"]["D7.1"]["data"]["audit_logs"]
        self.assertEqual(set(al["root"]) & {"owner", "group", "mode"}, {"owner", "group", "mode"})
        self.assertEqual([r["status"] for r in al["rows"]], ["active", "retired", "unregistered"])
        for r in al["rows"]:
            self.assertEqual(set(r), {"status", "owner", "mode", "files"})
        dump = json.dumps(out)
        for slug in ("gone-dental", "stray-dental"):
            self.assertNotIn(slug, dump)

    def test_d7_1_audit_logs_absent_root(self):
        self._d7_setup()
        al = CE.collect(self.host(), self.KEY)["items"]["D7.1"]["data"]["audit_logs"]
        self.assertEqual(al, {"root": "absent", "rows": []})

    def test_d7_1_symlinked_audit_logs_root_is_reported_not_followed(self):
        self._d7_setup()
        target = os.path.join(self.root, "elsewhere")
        os.makedirs(os.path.join(target, "ghost-client"))
        link = os.path.join(self.root, "var/lib/hermes/audit-logs")
        os.makedirs(os.path.dirname(link), exist_ok=True)
        os.symlink(target, link)
        out = CE.collect(self.host(), self.KEY)
        self.assertEqual(out["items"]["D7.1"]["data"]["audit_logs"], {"root": "symlink", "rows": []})
        self.assertNotIn("ghost-client", json.dumps(out))

class TestOptionBLayout(Base):
    def test_d7_1_reads_the_new_paths_and_reports_old_data_absent(self):
        for d in ("vaults", "reports", "draft-out"):
            os.makedirs(os.path.join(self.root, "var/lib/hermes", d, "acme-dental"))
        items = CE.collect(self.host(), self.KEY)["items"]
        d = items["D7.1"]["data"]
        self.assertEqual([r["status"] for r in d["vaults"]], ["active"])
        self.assertEqual([r["status"] for r in d["reports_rows"]], ["active"])
        self.assertEqual([r["status"] for r in d["draft_out_rows"]], ["active"])
        self.assertEqual(d["old_data"], {"data/vaults": "absent", "data/reports": "absent"})
        self.assertIn("vaults", d["parents"])
        self.assertNotIn("reports", d)
        self.assertNotIn("acme-dental", json.dumps(d))

    def test_d7_1_client_rows_carry_status_owner_mode_without_slugs(self):
        vaults = os.path.join(self.root, "var/lib/hermes/vaults")
        for n in ("acme-dental", "gone-dental", "stray-dental"):
            os.makedirs(os.path.join(vaults, n))
        self._w(CE.GOV + "/registry/clients.json", json.dumps({"clients": {
            "acme-dental": {"customer_id": "1234567890", "status": "active"},
            "gone-dental": {"customer_id": "2223334444", "status": "retired"}}}))
        out = CE.collect(self.host(), self.KEY)
        rows = out["items"]["D7.1"]["data"]["vaults"]
        self.assertEqual([r["status"] for r in rows], ["active", "retired", "unregistered"])
        for r in rows:
            self.assertEqual(set(r), {"status", "owner", "mode"})
        for slug in ("gone-dental", "stray-dental"):
            self.assertNotIn(slug, json.dumps(out))

    def test_d7_1_flags_leftover_old_data(self):
        os.makedirs(os.path.join(self.root, CE.AGENT_DIR.lstrip("/"), "data/vaults/acme-dental"))
        d = CE.collect(self.host(), self.KEY)["items"]["D7.1"]["data"]
        self.assertIsInstance(d["old_data"]["data/vaults"], dict)

    def test_d7_1_symlinked_parent_is_reported_and_never_listed(self):
        target = os.path.join(self.root, "elsewhere")
        os.makedirs(os.path.join(target, "ghost-client"))
        link = os.path.join(self.root, "var/lib/hermes/reports")
        os.makedirs(os.path.dirname(link), exist_ok=True)
        os.symlink(target, link)
        out = CE.collect(self.host(), self.KEY)
        d = out["items"]["D7.1"]["data"]
        self.assertEqual(d["parents"]["reports"], "symlink")
        self.assertEqual(d["reports_rows"], [])
        self.assertNotIn("ghost-client", json.dumps(out))

    def test_d7_1_non_directory_parent_does_not_raise(self):
        self._w("/var/lib/hermes/draft-out", "not a directory")
        d = CE.collect(self.host(), self.KEY)["items"]["D7.1"]["data"]
        self.assertEqual(d["parents"]["draft-out"], "not-a-directory")
        self.assertEqual(d["draft_out_rows"], [])

    def test_d7_1_entry_vanishing_mid_listing_is_skipped(self):
        vaults = os.path.join(self.root, "var/lib/hermes/vaults")
        for n in ("acme-dental", "gone-dental"):
            os.makedirs(os.path.join(vaults, n))
        real = os.lstat

        def flaky(p, *a, **k):
            if str(p).endswith("gone-dental"):
                raise FileNotFoundError(p)
            return real(p, *a, **k)
        with mock.patch.object(CE.os, "lstat", flaky):
            rows = CE._client_rows(self.host(), {}, "/var/lib/hermes/vaults")
        self.assertEqual(len(rows), 1)

    def test_d4_1_probes_the_moved_data_and_the_key_file(self):
        for p in ("/var/lib/hermes/vaults", "/var/lib/hermes/reports", "/var/lib/hermes/draft-out",
                  "/var/lib/hermes/audit-data", "/var/lib/hermes/app-state", "/etc/hermes/.env.anthropic",
                  "/opt/data/vaults", "/opt/data/reports", "/opt/data/home/.claude/settings.json"):
            self.assertIn(p, CE.GATEWAY_PROBE_PATHS)

    def test_d2_1_anthropic_key_file_is_authorised_and_its_state_reported(self):
        self._w("/etc/hermes/.env.anthropic", "ANTHROPIC_API_KEY=sk-ant-api03-SECRETVALUE\n")
        self.outputs[("find",)] = (0, "/etc/hermes/.env.anthropic\n", "")
        rows = CE.collect(self.host(), self.KEY)["items"]["D2.1"]["data"]["files"]
        row = [r for r in rows if r["path"] == "/etc/hermes/.env.anthropic"][0]
        self.assertEqual((row["kind"], row["label"], row["anthropic_key_state"]), ("authorised-other", "anthropic-key", "real"))
        self.assertNotIn("SECRETVALUE", json.dumps(rows))

    def test_d2_1_anthropic_key_value_joins_the_secrets(self):
        self._w("/etc/hermes/.env.anthropic", "ANTHROPIC_API_KEY=sk-ant-api03-SECRETVALUE\n")
        self.outputs[("find",)] = (0, "/etc/hermes/.env.anthropic\n", "")
        _, secrets = CE.collect_with_secrets(self.host(), self.KEY)
        self.assertIn("sk-ant-api03-SECRETVALUE", secrets)

    def test_d4_1_reports_anthropic_and_openrouter_env_names_only(self):
        self.outputs[("docker", "exec")] = (0, "ANTHROPIC_API_KEY=sk-ant-XYZ\nOPENROUTER_API_KEY=or-ABC\nHOME=/x\n", "")
        self.outputs[("docker", "ps")] = (0, "a" * 64 + "\n", "")
        d = CE.collect(self.host(), self.KEY)["items"]["D4.1"]["data"]
        self.assertEqual(d["anthropic_env_names"], ["ANTHROPIC_API_KEY"])
        self.assertEqual(d["openrouter_env_names"], ["OPENROUTER_API_KEY"])


class TestKeyedBundle(Base):
    def test_cids_are_keyed_and_key_id_recorded(self):
        b = CE.collect(self.host(), self.KEY)
        self.assertEqual(b["cid_fingerprint"], "hmac-sha256/12")
        self.assertEqual(b["cid_key_id"], R.key_id(self.KEY))
        self.assertNotIn("cid:" + R.sha12("1234567890"), json.dumps(b))

    def test_fingerprint_does_not_depend_on_the_key(self):
        a = CE.collect(self.host(), self.KEY)["fingerprint"]
        b = CE.collect(self.host(), bytes.fromhex("22" * 32))["fingerprint"]
        self.assertEqual(a, b)

    def test_full_bundle_without_key_refuses(self):
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(CE.main([], host=self.host()), 2)
            self.assertEqual(CE.main(["--fp-key-tty"], host=self.host(), read_key=lambda: "nothex"), 2)

    def test_key_never_printed(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            CE.main(["--fp-key-tty"], host=self.host(), read_key=lambda: "11" * 32)
        self.assertNotIn("11" * 32, out.getvalue())


RID_A = "0f8e2c1a-1111-4222-8333-444455556666"
RID_B = "1f8e2c1a-1111-4222-8333-444455556666"
RID_C = "2f8e2c1a-1111-4222-8333-444455556666"
GW_ID = "ab" * 32
BROKER = "hermes-app-broker[ads-audit]: "


class TestD10(Base):
    def setUp(self):
        super().setUp()
        self.outputs[("run-client-audit", "--probe-env")] = (0, json.dumps({"matches_declared": True, "services": {}}), "")
        self.outputs[("run-client-audit", "--probe-egress")] = (0, json.dumps({"matches_expected": True}), "")
        self._journal(broker=BROKER + "request=x op=run client=acme-dental status=refused reason=quota\n"
                             + BROKER + "request=y op=run client=acme-dental status=ok reason=-\n",
                      runner="Collecting...\nAudit complete.\n")
        self.res = os.path.join(self.root, CE.APP_RESULTS.lstrip("/")); os.makedirs(self.res)
        self.good = {"request_id": RID_A, "op": "run", "client": "acme-dental",
                     "status": "ok", "reason": None, "exit_code": 0, "ts": "2026-10-01_12-00-00", "steps": [],
                     "vault_path": "/var/lib/hermes/vaults/acme-dental/audits/2026-10-01_12-00-00-audit.md"}
        self._result(self.good)
        self._result(dict(self.good, request_id=RID_B, reason="free text"))

    def _result(self, obj, name=None):
        with open(os.path.join(self.res, name or obj["request_id"] + ".json"), "w") as f:
            json.dump(obj, f)

    def _journal(self, broker=None, runner=None):
        """Each unit's journal text, or an (rc, out, err) tuple for a failing journalctl."""
        for unit, out in (("broker", broker), ("runner", runner)):
            if out is not None:
                self.outputs[("journalctl", "-u", f"hermes-app-{unit}@ads-audit")] = \
                    out if isinstance(out, tuple) else (0, out, "")

    def _item(self, iid):
        return CE.collect(self.host(), self.KEY)["items"][iid]

    def test_probes_registered(self):
        for k in ("D10.1", "D10.2", "D10.3", "D10.4", "D10.6", "D10.7", "D10.8"):
            self.assertIn(k, CE.PROBES)
        self.assertNotIn("D10.5", CE.PROBES)                          # manual

    # ---- D10.1 / D10.2 -----------------------------------------------------------------
    def test_d10_1_and_2_carry_the_probe_json(self):
        items = CE.collect(self.host(), self.KEY)["items"]
        self.assertTrue(items["D10.1"]["data"]["probe"]["matches_declared"])
        self.assertTrue(items["D10.2"]["data"]["probe"]["matches_expected"])
        self.assertEqual(items["D10.1"]["data"]["rc"], 0)

    def test_d10_1_mismatch_is_still_observed_with_its_exit_code(self):
        self.outputs[("run-client-audit", "--probe-env")] = (1, json.dumps({"matches_declared": False}), "")
        it = self._item("D10.1")
        self.assertEqual(it["status"], R.OBSERVED)
        self.assertEqual(it["data"], {"rc": 1, "probe": {"matches_declared": False}})

    def test_d10_probe_without_json_is_could_not_check_with_the_exit_code(self):
        for rc, out in ((3, ""), (124, ""), (1, "Traceback (most recent call last):\n"), (0, "[]"), (0, "null")):
            self.outputs[("run-client-audit", "--probe-env")] = (rc, out, "boom")
            self.outputs[("run-client-audit", "--probe-egress")] = (rc, out, "boom")
            for iid in ("D10.1", "D10.2"):
                with self.subTest(rc=rc, out=out, iid=iid):
                    it = self._item(iid)
                    self.assertEqual(it["status"], R.COULD_NOT_CHECK)
                    self.assertIn(f"exited {rc}", it["reason"])
                    self.assertNotIn("boom", it["reason"])

    def test_d10_probes_run_with_the_long_timeout(self):
        seen = {}

        def run(argv, timeout):
            seen[tuple(argv)] = timeout
            return 0, "{}", ""
        host = CE.Host(self.root, run)
        CE.d10_1(host, {}); CE.d10_2(host, {})
        self.assertEqual(seen, {("run-client-audit", "--probe-env"): 600,
                                ("run-client-audit", "--probe-egress"): 600})

    # ---- D10.3 -------------------------------------------------------------------------
    def _units(self):
        for u in CE.APP_UNITS:
            self._w("/etc/systemd/system/" + u, "unit " + u)
            self._w(CE.CHECKOUT + "/infra/hermes-agent/deploy/" + u, "unit " + u)
        self.outputs[("systemctl", "show", "hermes-app-broker@ads-audit")] = (
            0, "User=hermes-app-ads-audit\nNoNewPrivileges=yes\nCapabilityBoundingSet=\nPrivateNetwork=yes\n"
               "ProtectSystem=strict\nProtectHome=yes\nPrivateTmp=yes\nUMask=0077\n"
               "ReadWritePaths=/var/lib/hermes/spool/apps/ads-audit /var/lib/hermes/app-state/ads-audit\n"
               "ActiveState=active\nEnvironment=\n", "")
        self.outputs[("systemctl", "show", "hermes-app-runner@ads-audit")] = (0, "Environment=\n", "")
        self.outputs[("id", "-nG")] = (0, "hermes-app-ads-audit hermes\n", "")
        self.outputs[("sudo", "-l", "-U")] = (0, "User hermes-app-ads-audit is not allowed to run sudo on box-7.\n", "")
        self.outputs[("systemctl", "is-active", "hermes-app-runner@ads-audit.path")] = (0, "active\n", "")

    def test_d10_3_reports_units_groups_sudo_and_path(self):
        self._units()
        d = self._item("D10.3")["data"]
        self.assertEqual(d["broker_unit"]["User"], "hermes-app-ads-audit")
        self.assertEqual(d["broker_unit"]["CapabilityBoundingSet"], "")
        self.assertEqual(d["broker_unit"]["Environment"], [])
        self.assertEqual(d["broker_unit"]["EnvironmentFiles"], [])
        self.assertEqual(d["runner_unit"], {"Environment": [], "EnvironmentFiles": []})
        self.assertEqual(d["installed_equal_repo"], {u: True for u in CE.APP_UNITS})
        self.assertEqual(d["broker_user_groups"], ["hermes-app-ads-audit", "hermes"])
        self.assertEqual(d["sudo_rules"], {"rc": 0, "not_allowed": True, "command_lines": 0})
        self.assertEqual(d["runner_path_active"], "active")

    def test_d10_3_sudo_text_never_reaches_the_bundle(self):
        self._units()
        self.outputs[("sudo", "-l", "-U")] = (
            0, "Matching Defaults entries for hermes-app-ads-audit on box-7:\n    env_reset\n\n"
               "User hermes-app-ads-audit may run the following commands on box-7:\n"
               "    (root) NOPASSWD: /usr/bin/docker\n    (root) /bin/sh\n", "")
        it = self._item("D10.3")
        self.assertEqual(it["data"]["sudo_rules"], {"rc": 0, "not_allowed": False, "command_lines": 2})
        self.assertNotIn("box-7", json.dumps(it))

    def test_d10_3_environment_is_names_only_and_drop_in_files_are_listed(self):
        self._units()
        secret = "sk-ant-NOT-A-REAL-KEY-0123456789"
        self.outputs[("systemctl", "show", "hermes-app-runner@ads-audit")] = (
            0, f'Environment=ANTHROPIC_API_KEY={secret} "NOTE=two words"\n'
               "EnvironmentFiles=/etc/hermes/.env.anthropic (ignore_errors=no)\n"
               "EnvironmentFiles=/etc/extra (ignore_errors=yes)\n"
               "a line without an equals sign\nExecStart=/not/asked/for\n", "")
        it = self._item("D10.3")
        self.assertEqual(it["data"]["runner_unit"],
                         {"Environment": ["ANTHROPIC_API_KEY", "NOTE"],
                          "EnvironmentFiles": ["/etc/hermes/.env.anthropic (ignore_errors=no)",
                                               "/etc/extra (ignore_errors=yes)"]})
        self.assertNotIn(secret, json.dumps(it))

    def test_d10_3_a_property_systemd_did_not_print_is_could_not_check(self):
        self._units()
        self.outputs[("systemctl", "show", "hermes-app-broker@ads-audit")] = (0, "User=hermes-app-ads-audit\n", "")
        self.outputs[("systemctl", "show", "hermes-app-runner@ads-audit")] = (0, 'Environment="unbalanced\n', "")
        d = self._item("D10.3")["data"]
        self.assertEqual(d["broker_unit"]["NoNewPrivileges"], R.COULD_NOT_CHECK)
        self.assertEqual(d["broker_unit"]["Environment"], R.COULD_NOT_CHECK)
        self.assertEqual(d["runner_unit"]["Environment"], R.COULD_NOT_CHECK)

    def test_d10_3_changed_or_missing_installed_unit_is_not_equal(self):
        self._units()
        self._w("/etc/systemd/system/" + CE.APP_UNITS[0], "edited")
        os.remove(os.path.join(self.root, "etc/systemd/system", CE.APP_UNITS[1]))
        d = self._item("D10.3")["data"]
        self.assertEqual(d["installed_equal_repo"],
                         {CE.APP_UNITS[0]: False, CE.APP_UNITS[1]: False, CE.APP_UNITS[2]: True})

    def test_d10_3_inactive_path_unit_is_reported_not_could_not_check(self):
        self._units()
        self.outputs[("systemctl", "is-active", "hermes-app-runner@ads-audit.path")] = (3, "inactive\n", "")
        it = self._item("D10.3")
        self.assertEqual(it["status"], R.OBSERVED)
        self.assertEqual(it["data"]["runner_path_active"], "inactive")

    # ---- D10.4 -------------------------------------------------------------------------
    def _resolver(self):
        names = {"root": 0, "hermes": 10000, "hermes-app-ads-audit": 990}
        return mock.patch.object(CE.HL, "system_resolver", return_value=CE.HL.Resolver(names, names))

    def _containers(self, mounts):
        del self.outputs[("docker", "ps")]
        self.outputs[("docker", "ps", "-q", "--no-trunc", "--filter")] = (0, "", "")
        self.outputs[("docker", "ps", "-q", "--no-trunc")] = (0, "".join(c + "\n" for c in mounts), "")
        for cid, out in mounts.items():
            self.outputs[("docker", "inspect", "--format", "{{json .Mounts}}", cid)] = out

    def test_d10_4_layout_problems_and_no_container_mount(self):
        self._containers({"c1": (0, json.dumps([{"Type": "bind", "Source": "/var/lib/hermes/vaults/x"}]), "")})
        with self._resolver() as sr:
            it = self._item("D10.4")
        self.assertEqual(it["status"], R.OBSERVED)
        self.assertEqual(sr.call_args.kwargs["layout"], CE.HL.app_layout("ads-audit"))
        self.assertTrue(any("app-state" in p for p in it["data"]["layout_problems"]))   # nothing built here
        self.assertEqual({k: it["data"][k] for k in ("containers", "containers_mounting_app_state",
                                                     "containers_not_inspected")},
                         {"containers": 1, "containers_mounting_app_state": 0, "containers_not_inspected": 0})

    def test_d10_4_counts_a_mount_of_app_state_its_child_or_its_parent(self):
        def m(src):
            return (0, json.dumps([{"Type": "bind", "Source": src}]), "")
        self._containers({"c1": m("/var/lib/hermes/app-state"), "c2": m("/var/lib/hermes/app-state/ads-audit/jobs"),
                          "c3": m("/var/lib/hermes"), "c4": m("/"), "c5": m("/var/lib/hermes/app-state-other"),
                          "c6": m("/var/lib/docker/volumes/v/_data")})
        with self._resolver():
            d = self._item("D10.4")["data"]
        self.assertEqual((d["containers"], d["containers_mounting_app_state"], d["containers_not_inspected"]), (6, 4, 0))

    def test_d10_4_hostile_or_failed_inspect_is_counted_never_raised(self):
        self._containers({"c1": (1, "", "No such object"), "c2": (0, "not json", ""), "c3": (0, "null", ""),
                          "c4": (0, json.dumps(["x", {"Source": 7}, {}]), ""),
                          "c5": (0, json.dumps([{"Source": "/var/lib/hermes/app-state"}]), "")})
        with self._resolver():
            it = self._item("D10.4")
        self.assertEqual(it["status"], R.OBSERVED)
        self.assertEqual((it["data"]["containers"], it["data"]["containers_mounting_app_state"],
                          it["data"]["containers_not_inspected"]), (5, 1, 4))

    def test_d10_4_layout_refusal_is_could_not_check(self):
        with mock.patch.object(CE.HL, "system_resolver", side_effect=CE.HL.LayoutError("group 'hermes' is gid 5")):
            it = self._item("D10.4")
        self.assertEqual(it["status"], R.COULD_NOT_CHECK)
        self.assertIn("gid 5", it["reason"])

    # ---- D10.6 -------------------------------------------------------------------------
    CONFIG = ("model: x\n"
              "# the one app\n"
              "mcp_servers:\n"
              "  ads_audit:\n"
              "    command: \"python3\"\n"
              "    env: {}\n"
              "\n"
              "    tools:\n"
              "      include: [ads_audit_run, ads_audit_status, ads_audit_list]\n"
              "# a comment at column 0 stays in the block\n"
              "terminal:\n"
              "  backend: docker\n")

    def _gateway(self, listing):
        del self.outputs[("docker", "ps")]
        self.outputs[("docker", "ps", "-q", "--no-trunc", "--filter")] = (0, GW_ID + "\n", "")
        self.outputs[("docker", "ps", "-q", "--no-trunc")] = (0, "", "")
        self.outputs[("docker", "exec", GW_ID, "hermes", "mcp", "list")] = listing

    def test_d10_6_block_and_listing(self):
        self._w(CE.AGENT_DIR + "/data/config.yaml", self.CONFIG)
        self._gateway((0, "ads_audit  3 tools\n", ""))
        d = self._item("D10.6")["data"]
        self.assertEqual(d["mcp_block"][0], "mcp_servers:")
        self.assertIn("      include: [ads_audit_run, ads_audit_status, ads_audit_list]", d["mcp_block"])
        self.assertFalse(any("terminal" in l or "backend" in l or "model" in l for l in d["mcp_block"]))
        self.assertEqual((d["gateway_mcp_list"], d["gateway_mcp_list_rc"]), (["ads_audit  3 tools"], 0))

    def test_d10_6_failed_or_missing_listing_keeps_the_block(self):
        self._w(CE.AGENT_DIR + "/data/config.yaml", self.CONFIG)
        it = self._item("D10.6")                                        # no gateway container at all
        self.assertEqual(it["status"], R.OBSERVED)
        self.assertEqual((it["data"]["gateway_mcp_list"], it["data"]["gateway_mcp_list_rc"]), ([], None))
        self.assertEqual(it["data"]["mcp_block"][0], "mcp_servers:")
        self._gateway((127, "", "hermes: not found"))
        it = self._item("D10.6")
        self.assertEqual(it["status"], R.OBSERVED)
        self.assertEqual((it["data"]["gateway_mcp_list"], it["data"]["gateway_mcp_list_rc"]), ([], 127))
        self.assertEqual(it["data"]["mcp_block"][0], "mcp_servers:")

    def test_d10_6_env_values_in_the_block_are_withheld(self):
        secret = "sk-or-NOT-A-REAL-KEY-0123456789"
        self._w(CE.AGENT_DIR + "/data/config.yaml",
                "mcp_servers:\n  a:\n    env:\n      OPENROUTER_API_KEY: " + secret + "\n      # " + secret + "\n"
                "    timeout: 360\n  b:\n    env: {K: " + secret + "}\n  c:\n    env: {}\n    headers:\n"
                "      Authorization: Bearer " + secret + "\n")
        it = self._item("D10.6")
        self.assertNotIn(secret, json.dumps(it))
        block = it["data"]["mcp_block"]
        self.assertIn("      OPENROUTER_API_KEY: <withheld>", block)        # the name stays, the value goes
        self.assertIn("    timeout: 360", block)                             # control: outside env, untouched
        self.assertIn("    env: <withheld>", block)
        self.assertIn("    env: {}", block)                                  # control: empty is shown as empty
        self.assertIn("      Authorization: <withheld>", block)

    def test_d10_6_missing_config_is_could_not_check(self):
        self.assertEqual(self._item("D10.6")["status"], R.COULD_NOT_CHECK)

    # ---- D10.7 -------------------------------------------------------------------------
    def test_d10_7_counts_without_slugs(self):
        d = self._item("D10.7")["data"]
        self.assertEqual(d["journal_counts"], {"refused/quota": 1, "ok/-": 1})
        self.assertNotIn("acme-dental", json.dumps(d))

    def test_d10_7_counts_every_kind_of_line_the_broker_writes(self):
        self._journal(broker=(
            BROKER + f"request={RID_A} op=run client=acme-dental status=queued reason=-\n"
            + BROKER + "request=- op=- client=- status=dropped reason=bad_request\n"
            + BROKER + "request=- op=- client=- status=dropped reason=expired\n"
            + BROKER + f"request={RID_A} op=run client=acme-dental status=dropped reason=duplicate\n"
            + BROKER + f"request={RID_A} op=run client=acme-dental status=failed reason=proxy\n"
            + BROKER + f"request={RID_A} op=run client=acme-dental status=busy reason=busy\n"
            + BROKER + f"request={RID_B} op=- client=- status=refused reason=bad_request\n"
            + BROKER + "warning: daily refusal cap reached (request dropped, not recorded)\n"
            + BROKER + "error: could not remove a spool entry\n"
            + BROKER + "error: a request could not be processed (left for the next pass)\n"
            "Started hermes-app-broker@ads-audit.service.\n"
            "Traceback (most recent call last):\n"
            "\n"))
        d = self._item("D10.7")["data"]
        self.assertEqual(d["journal_counts"],
                         {"queued/-": 1, "dropped/bad_request": 1, "dropped/expired": 1, "dropped/duplicate": 1,
                          "failed/proxy": 1, "busy/busy": 1, "refused/bad_request": 1})
        self.assertEqual(d["note_counts"], {"warning": 1, "error": 2})
        self.assertEqual(d["other_lines"], 2)
        clean = {"credential_text_lines": 0, "customer_id_lines": 0, "pattern_hits": 0, "known_secret_hits": 0}
        self.assertEqual((d["broker_journal"], d["runner_journal"]), (clean, clean))

    def test_d10_7_unknown_status_or_reason_is_a_question_mark_never_the_text(self):
        self._journal(broker=BROKER + "request=x op=run client=acme-dental status=weird-host-name reason=quota\n"
                             + BROKER + "request=x op=run client=acme-dental status=ok reason=some-free-text\n"
                             "something status=ok reason=quota but not a broker line\n")
        it = self._item("D10.7")
        self.assertEqual(it["data"]["journal_counts"], {"?/quota": 1, "ok/?": 1})
        self.assertEqual(it["data"]["other_lines"], 1)
        self.assertNotIn("weird-host-name", json.dumps(it)); self.assertNotIn("some-free-text", json.dumps(it))

    def test_d10_7_counts_credential_text_and_customer_id_lines_never_the_lines(self):
        self._journal(broker=BROKER + "request=x op=run client=acme-dental status=ok reason=-\n"
                             f"oops GOOGLE_ADS_REFRESH_TOKEN={TOKEN}\n"
                             "customer 123-456-7890 failed\ncustomer 1234567890 failed\ncustomer 9999999999 is not ours\n")
        it = self._item("D10.7")
        self.assertEqual(it["data"]["broker_journal"], {"credential_text_lines": 1, "customer_id_lines": 2,
                                                        "pattern_hits": 1, "known_secret_hits": 1})
        self.assertEqual(it["data"]["runner_journal"], {"credential_text_lines": 0, "customer_id_lines": 0,
                                                        "pattern_hits": 0, "known_secret_hits": 0})
        self.assertEqual(it["data"]["other_lines"], 4)
        out = json.dumps(it)
        for leak in (TOKEN, "1234567890", "123-456-7890", "9999999999", "oops"):
            self.assertNotIn(leak, out)

    # The runner's journal is where run-client-audit's own output lands (the unit sets no
    # StandardOutput), so it is the likelier place for a customer id or a credential.
    CLIENT_SECRET = "GOCSPX-NOT-A-REAL-CLIENT-SECRET"                 # installed, and not Google-token shaped

    def _install_client_secret(self):
        self._w(CE.AGENT_DIR + "/.env.gaw", "GOOGLE_ADS_CREDENTIAL_ROLE=write\n"
                f"GOOGLE_ADS_REFRESH_TOKEN={TOKEN}\nGOOGLE_ADS_CLIENT_SECRET={self.CLIENT_SECRET}\n")

    def test_d10_7_runner_journal_customer_id_is_counted_under_the_runner_key(self):
        self._journal(runner="Collecting for customer 1234567890\nand again 123-456-7890\nAudit complete.\n")
        b = CE.collect(self.host(), self.KEY)
        d = b["items"]["D10.7"]["data"]
        self.assertEqual(d["runner_journal"]["customer_id_lines"], 2)
        self.assertEqual(d["broker_journal"]["customer_id_lines"], 0)
        self.assertEqual(d["journal_counts"], {"refused/quota": 1, "ok/-": 1})      # broker-only, unchanged
        self.assertEqual(d["other_lines"], 0)                                       # runner lines are not broker lines
        out = json.dumps(b)
        self.assertNotIn("1234567890", out); self.assertNotIn("123-456-7890", out)
        self.assertNotIn("Collecting for customer", out)

    def test_d10_7_runner_journal_installed_secret_value_is_counted_under_the_runner_key(self):
        self._install_client_secret()
        self._journal(runner=f"debug: secret is {self.CLIENT_SECRET}\nheader {self.CLIENT_SECRET} {self.CLIENT_SECRET}\n")
        b = CE.collect(self.host(), self.KEY)
        d = b["items"]["D10.7"]["data"]
        self.assertEqual(d["runner_journal"], {"credential_text_lines": 0,          # not Google-shaped text:
                                               "customer_id_lines": 0, "pattern_hits": 0,
                                               "known_secret_hits": 3})             # only the known value finds it
        self.assertEqual(d["broker_journal"]["known_secret_hits"], 0)
        self.assertEqual(d["known_secrets_checked"], 2)                             # the token and the client secret
        self.assertNotIn(self.CLIENT_SECRET, json.dumps(b))

    def test_d10_7_broker_journal_installed_secret_value_is_counted_under_the_broker_key(self):
        self._install_client_secret()
        self._journal(broker=f"Traceback: {self.CLIENT_SECRET}\n")
        d = self._item("D10.7")["data"]
        self.assertEqual((d["broker_journal"]["known_secret_hits"], d["runner_journal"]["known_secret_hits"]), (1, 0))

    def test_d10_7_reads_both_units_over_the_same_window(self):
        host = self.host()
        CE.collect(host, self.KEY)
        calls = [c for c in host.calls if c[:2] == ["journalctl", "-u"]]
        self.assertEqual([c[2] for c in calls], ["hermes-app-broker@ads-audit", "hermes-app-runner@ads-audit"])
        self.assertEqual(calls[0][3:], calls[1][3:])
        self.assertIn("-30d", calls[0])

    def test_d10_7_a_failing_journalctl_for_either_unit_is_could_not_check(self):
        for unit in ("broker", "runner"):
            with self.subTest(unit=unit):
                self.setUp()
                self._journal(**{unit: (1, "", "no journal")})
                it = self._item("D10.7")
                self.assertEqual(it["status"], R.COULD_NOT_CHECK)
                self.assertIn("journalctl exited 1", it["reason"])

    # ---- D10.8 -------------------------------------------------------------------------
    def test_d10_8_flags_out_of_whitelist_results(self):
        d = self._item("D10.8")["data"]
        self.assertEqual(d["out_of_whitelist"], 1)
        self.assertNotIn("acme-dental", json.dumps(d))
        self.assertEqual(d["results"], [
            {"op": "run", "status": "ok", "reason": "-", "keys_ok": True, "values_ok": True},
            {"op": "run", "status": "ok", "reason": "?", "keys_ok": True, "values_ok": False}])

    def test_d10_8_every_bad_entry_gets_a_row_and_none_hides_the_others(self):
        unread = {"keys_ok": False, "values_ok": False}
        with open(os.path.join(self.res, "a-not-json.json"), "w") as f:
            f.write("{not json")
        with open(os.path.join(self.res, "b-binary.json"), "wb") as f:
            f.write(b"\xff\xfe\x00")
        with open(os.path.join(self.res, "c-deep.json"), "w") as f:
            f.write("[" * 50000)
        with open(os.path.join(self.res, "d-big.json"), "w") as f:
            f.write(" " * (CE.A.MAX_DONE_BYTES + 1) + json.dumps(self.good))
        os.mkdir(os.path.join(self.res, "e-dir"))
        os.symlink(os.path.join(self.res, RID_A + ".json"), os.path.join(self.res, "f-link.json"))
        os.mkfifo(os.path.join(self.res, "g-fifo"))
        for name, obj in (("h-list.json", [1]), ("i-null.json", None), ("j-str.json", "ok")):
            self._result(obj, name)
        self._result({"status": ["ok"], "reason": {"a": 1}, "op": 7}, "k-types.json")
        self._result(dict(self.good, request_id=RID_C, steps=["rm -rf /"]), RID_C + ".json")
        d = self._item("D10.8")["data"]
        self.assertEqual(len(d["results"]), 14)
        self.assertEqual(d["out_of_whitelist"], 13)
        self.assertEqual(d["results"][:2], [                                # sorted: the two from setUp first
            {"op": "run", "status": "ok", "reason": "-", "keys_ok": True, "values_ok": True},
            {"op": "run", "status": "ok", "reason": "?", "keys_ok": True, "values_ok": False}])
        self.assertEqual(d["results"][2],
                         {"op": "run", "status": "ok", "reason": "-", "keys_ok": True, "values_ok": False})
        self.assertEqual(d["results"][3:13], [unread] * 10)
        self.assertEqual(d["results"][13], {"op": "?", "status": "?", "reason": "?", "keys_ok": False, "values_ok": False})

    def test_d10_8_deeply_nested_result_is_one_out_of_whitelist_row(self):
        # Valid JSON nested about as deep as the interpreter recurses: it parses, and the whitelist
        # check must not die on it (it once re-serialized the value, a few frames deeper). The
        # sweep is wide because the depth that bites depends on how deep the caller's own stack is.
        limit = sys.getrecursionlimit()
        host = self.host()
        for depth in list(range(limit - 150, limit + 10)) + [5000, 20000]:
            for nest in ("[" * depth + "]" * depth, '{"a":' * depth + "1" + "}" * depth):
                body = json.dumps(CE.A.refused_result(RID_C, "run", "acme-dental", "quota")).replace(
                    '"steps": []', '"steps": ' + nest)
                if len(body) > CE.A.MAX_DONE_BYTES:
                    continue
                with open(os.path.join(self.res, RID_C + ".json"), "w") as f:
                    f.write(body)
                with self.subTest(depth=depth, kind=nest[0]):
                    d = CE.d10_8(host, {})
                    self.assertEqual((len(d["results"]), d["out_of_whitelist"]), (3, 2))
                    self.assertIs(d["results"][2]["values_ok"], False)

    def test_d10_8_a_raise_from_the_whitelist_check_costs_one_row_never_the_item(self):
        real = CE.A.result_in_whitelist

        def flaky(obj):
            if obj["request_id"] == RID_A:
                raise RecursionError("maximum recursion depth exceeded")
            return real(obj)
        with mock.patch.object(CE.A, "result_in_whitelist", side_effect=flaky):
            it = self._item("D10.8")
        self.assertEqual(it["status"], R.OBSERVED)
        self.assertEqual(it["data"], {"out_of_whitelist": 2, "results": [
            {"keys_ok": False, "values_ok": False},
            {"op": "run", "status": "ok", "reason": "?", "keys_ok": True, "values_ok": False}]})

    def test_d10_8_rows_never_carry_a_slug_a_request_id_or_free_text(self):
        self._result(dict(self.good, request_id=RID_C, client="other-client", reason="leaked 1234567890"))
        out = json.dumps(self._item("D10.8"))
        for leak in ("acme-dental", "other-client", RID_A, RID_B, RID_C, "leaked", "free text"):
            self.assertNotIn(leak, out)

    def test_d10_8_a_result_under_another_file_name_is_out_of_whitelist(self):
        self._result(self.good, RID_C + ".json")                           # a copy: its id is RID_A
        d = self._item("D10.8")["data"]
        self.assertEqual(d["out_of_whitelist"], 2)
        self.assertEqual(d["results"][2], {"op": "run", "status": "ok", "reason": "-", "keys_ok": True, "values_ok": False})

    def test_d10_8_every_result_the_broker_writes_is_in_whitelist(self):
        for n in os.listdir(self.res):
            os.remove(os.path.join(self.res, n))
        self._result(CE.A.refused_result(RID_A, None, None, "bad_request"))
        self._result(CE.A.refused_result(RID_B, "list", "acme-dental", "interrupted", status="failed"))
        d = self._item("D10.8")["data"]
        self.assertEqual(d, {"out_of_whitelist": 0, "results": [
            {"op": "-", "status": "refused", "reason": "bad_request", "keys_ok": True, "values_ok": True},
            {"op": "list", "status": "failed", "reason": "interrupted", "keys_ok": True, "values_ok": True}]})

    def test_d10_8_missing_results_dir_is_could_not_check(self):
        import shutil
        shutil.rmtree(self.res)
        self.assertEqual(self._item("D10.8")["status"], R.COULD_NOT_CHECK)

    def test_d10_items_survive_the_redactor_and_the_secret_check(self):
        out = json.dumps(CE.collect(self.host(), self.KEY))
        self.assertNotIn("acme-dental", out); self.assertNotIn("1234567890", out)


class TestReview5FollowUps(Base):
    def test_audit_logs_file_modes_counted_without_names(self):
        d = os.path.join(self.root, "var/lib/hermes/audit-logs/acme-dental"); os.makedirs(d)
        for n, mode in (("collect-a.stdout", 0o600), ("collect-a.stderr", 0o644)):
            p = os.path.join(d, n); open(p, "w").close(); os.chmod(p, mode)
        row = CE.collect(self.host(), self.KEY)["items"]["D7.1"]["data"]["audit_logs"]["rows"][0]
        self.assertEqual(sum(row["files"].values()), 2)
        self.assertTrue(any(k.endswith("0o644") for k in row["files"]))
        self.assertNotIn("collect-a", json.dumps(row))

    def test_audit_logs_file_listing_survives_a_vanished_or_unlistable_entry(self):
        d = os.path.join(self.root, "var/lib/hermes/audit-logs/acme-dental"); os.makedirs(d)
        with open(os.path.join(d, "a"), "w"):
            pass
        st = os.lstat(d)
        real_lstat = os.lstat
        def flaky(path, *a, **k):
            if os.path.basename(path) == "a":
                raise FileNotFoundError(path)
            return real_lstat(path, *a, **k)
        with mock.patch.object(CE.os, "lstat", flaky):
            self.assertEqual(CE._file_modes(d, st), {})
        with mock.patch.object(CE.os, "listdir", side_effect=PermissionError):
            self.assertEqual(CE._file_modes(d, st), {})

    def test_nsfs_handles_are_classified_not_unreadable(self):
        run = os.path.join(self.root, "run/docker/netns"); os.makedirs(run)
        h = os.path.join(run, "abc123"); open(h, "w").close(); os.chmod(h, 0)
        mounts = [("/run", "tmpfs"), ("/run/docker/netns/abc123", "nsfs")]
        out = CE._memory_sweep(self.host(), mounts)
        self.assertIn("/run/docker/netns/abc123", out["namespace_handles"])
        self.assertNotIn("/run/docker/netns/abc123", out["unreadable"])

    def test_d4_2_compares_with_the_last_pass(self):
        self.outputs[("systemctl", "is-active")] = (0, "active\n", "")
        self.outputs[("systemctl", "show", "hermes-docker-proxy")] = (0, "ExecStart=x\n", "")
        self.addCleanup(setattr, CE, "LAST_PASS_EXECSTART", None)
        CE.LAST_PASS_EXECSTART = None
        d = CE.d4_2(self.host(), {})
        self.assertIsNone(d["matches_last_pass"])
        CE.LAST_PASS_EXECSTART = d["execstart_sha256"]
        self.assertTrue(CE.d4_2(self.host(), {})["matches_last_pass"])

    def _run_main(self, *extra):
        self.outputs[("systemctl", "is-active")] = (0, "active\n", "")
        self.outputs[("systemctl", "show", "hermes-docker-proxy")] = (0, "ExecStart=x\n", "")
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = CE.main(["--fp-key-tty", *extra], host=self.host(), read_key=lambda: "11" * 32)
        return rc, out.getvalue(), err.getvalue()

    def test_main_passes_a_valid_last_pass_execstart_and_does_not_leak_it(self):
        self.addCleanup(setattr, CE, "LAST_PASS_EXECSTART", None)
        sha = "ab" * 32
        rc, out, _ = self._run_main("--last-pass-execstart", sha)
        d = json.loads(out)["items"]["D4.2"]["data"]
        self.assertEqual(d["last_pass_execstart_sha256"], sha)
        self.assertFalse(d["matches_last_pass"])
        self.assertIsNone(CE.LAST_PASS_EXECSTART)
        _, out, _ = self._run_main()
        self.assertIsNone(json.loads(out)["items"]["D4.2"]["data"]["matches_last_pass"])

    def test_main_refuses_an_invalid_last_pass_execstart(self):
        self.addCleanup(setattr, CE, "LAST_PASS_EXECSTART", None)
        for bad in ("ab" * 31, "AB" * 32, "ab" * 32 + "\n", ""):
            rc, out, err = self._run_main("--last-pass-execstart", bad)
            self.assertEqual(rc, 2, repr(bad))
            self.assertEqual(out, "")
            self.assertIn("--last-pass-execstart", err)
            self.assertIsNone(CE.LAST_PASS_EXECSTART)


if __name__ == "__main__":
    unittest.main()
