#!/usr/bin/env python3
import contextlib, hashlib, importlib.util, io, json, os, shutil, sys, tempfile, time, unittest
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

    GATEWAY_ENV = CE.CHECKOUT + "/infra/hermes-agent/.env"
    OPENROUTER = "sk-or-v1-NOT-A-REAL-KEY-0123456789abcdef"

    def _gateway_env(self, body):
        self._w(self.GATEWAY_ENV, body)
        self.outputs[("find",)] = (0, self.GATEWAY_ENV + "\n", "")

    def test_d2_1_openrouter_key_value_joins_the_secrets_and_never_the_bundle(self):
        self._gateway_env(f"HERMES_SPOOL_DIR=/var/lib/hermes/spool\nOPENROUTER_API_KEY={self.OPENROUTER}\n")
        bundle, secrets = CE.collect_with_secrets(self.host(), self.KEY)
        self.assertIn(self.OPENROUTER, secrets)
        self.assertNotIn(self.OPENROUTER, json.dumps(bundle))
        row = bundle["items"]["D2.1"]["data"]["files"][0]
        self.assertEqual((row["kind"], row["label"]), ("authorised-other", "gateway-env"))
        self.assertNotIn("anthropic_key_state", row)

    DASH = "NOT-A-REAL-DASHBOARD-PASSWORD-0123"

    def test_d2_1_the_dashboard_password_joins_the_secrets_and_is_never_fingerprinted(self):
        self._gateway_env(f"OPENROUTER_API_KEY={self.OPENROUTER}\nHERMES_DASHBOARD=1\n"
                          f"HERMES_DASHBOARD_BASIC_AUTH_PASSWORD={self.DASH}\n")
        bundle, secrets = CE.collect_with_secrets(self.host(), self.KEY)
        self.assertIn(self.DASH, secrets)
        text = json.dumps(bundle)
        self.assertNotIn(self.DASH, text)
        self.assertNotIn(R.sha12(self.DASH), text)
        row = bundle["items"]["D2.1"]["data"]["files"][0]
        self.assertEqual(row["secrets_held"], ["openrouter-key", "dashboard-password"])
        self.assertEqual(bundle["credentials"], [{"label": "dashboard-password", "sha12": None},
                                                 {"label": "openrouter-key", "sha12": R.sha12(self.OPENROUTER)}])

    def test_d2_1_a_gateway_env_with_the_dashboard_off_is_healthy(self):
        self._gateway_env(f"OPENROUTER_API_KEY={self.OPENROUTER}\n")
        bundle = CE.collect(self.host(), self.KEY)
        self.assertEqual(bundle["items"]["D2.1"]["data"]["files"][0]["secrets_held"], ["openrouter-key"])
        self.assertEqual(bundle["credentials"], [{"label": "openrouter-key", "sha12": R.sha12(self.OPENROUTER)}])

    def test_the_dashboard_password_is_a_known_secret_for_the_journal_counts(self):
        self._gateway_env(f"HERMES_DASHBOARD_BASIC_AUTH_PASSWORD={self.DASH}\n")
        self.outputs[("journalctl", "-o")] = (0, f"basic auth failed for {self.DASH}\n", "")
        it = CE.collect(self.host(), self.KEY)["items"]["D2.3"]
        self.assertEqual(it["data"]["journal"]["known_secret_hits"], 1)

    def test_credentials_only_lists_the_non_google_secrets_and_no_value(self):
        self._w("/etc/hermes/.env.anthropic", "ANTHROPIC_API_KEY=sk-ant-api03-SECRETVALUE\n")
        self._gateway_env(f"OPENROUTER_API_KEY={self.OPENROUTER}\nHERMES_DASHBOARD_BASIC_AUTH_PASSWORD={self.DASH}\n")
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = CE.main(["--credentials-only"], host=self.host())
        self.assertEqual(rc, 0)
        self.assertEqual(json.loads(buf.getvalue()),
                         [{"label": "anthropic-key", "sha12": R.sha12("sk-ant-api03-SECRETVALUE")},
                          {"label": "dashboard-password", "sha12": None},
                          {"label": "openrouter-key", "sha12": R.sha12(self.OPENROUTER)}])
        for value in ("SECRETVALUE", self.OPENROUTER, self.DASH):
            self.assertNotIn(value, buf.getvalue())

    def _a_directory_instead(self, rel):
        """Make an installed file unreadable for real, as root too: a directory of its name
        (open() raises IsADirectoryError whoever asks). Returns the directory's path."""
        p = os.path.join(self.root, rel.lstrip("/"))
        os.remove(p)
        os.mkdir(p)
        return p

    def test_an_authorised_file_that_cannot_be_read_is_never_an_empty_set(self):
        self._gateway_env(f"OPENROUTER_API_KEY={self.OPENROUTER}\n")
        p = self._a_directory_instead(self.GATEWAY_ENV)
        rows, secrets, failed = CE.other_credentials(self.host())
        self.assertEqual((rows, secrets), ([], []))
        self.assertIn("gateway-env: IsADirectoryError", failed)        # the label, not a path
        self.assertNotIn(self.root, "".join(failed))
        os.rmdir(p)
        self._gateway_env(f"OPENROUTER_API_KEY={self.OPENROUTER}\n")
        rows, secrets, failed = CE.other_credentials(self.host())      # control: readable again
        self.assertEqual((secrets, failed), ([self.OPENROUTER], []))

    def test_one_unreadable_authorised_file_keeps_the_other_files_values(self):
        self._w("/etc/hermes/.env.anthropic", "ANTHROPIC_API_KEY=sk-ant-api03-SECRETVALUE\n")
        with open(self._w(self.GATEWAY_ENV, ""), "wb") as f:
            f.write(b"OPENROUTER_API_KEY=\xff\xfe\n")
        rows, secrets, failed = CE.other_credentials(self.host())
        self.assertIn("sk-ant-api03-SECRETVALUE", secrets)
        self.assertEqual(rows[0], {"label": "anthropic-key", "sha12": R.sha12("sk-ant-api03-SECRETVALUE")})
        self.assertEqual(failed, ["gateway-env: undecodable bytes"])
        self._a_directory_instead(self.GATEWAY_ENV)                    # and one that cannot be opened at all
        rows, secrets, failed = CE.other_credentials(self.host())
        self.assertEqual(secrets, ["sk-ant-api03-SECRETVALUE"])
        self.assertEqual(failed, ["gateway-env: IsADirectoryError"])

    # ---- final review C1: one tolerant read; every value a name is given is a known secret ----
    def test_the_two_tables_of_authorised_files_name_the_same_files(self):
        self.assertEqual(set(CE.OTHER_SECRET_NAMES), set(CE.AUTHORISED_OTHER))

    def _openrouter_row(self):
        return {"label": "openrouter-key", "sha12": R.sha12(self.OPENROUTER)}

    def test_a_name_given_the_same_value_twice_is_not_a_problem(self):
        for body in (f"OPENROUTER_API_KEY={self.OPENROUTER}\nOPENROUTER_API_KEY={self.OPENROUTER}\n",
                     f"OPENROUTER_API_KEY={self.OPENROUTER}\nexport OPENROUTER_API_KEY='{self.OPENROUTER}' # again\n"):
            with self.subTest(body=body):
                self._gateway_env(body)
                rows, secrets, failed = CE.other_credentials(self.host())
                self.assertEqual((rows, secrets, failed), ([self._openrouter_row()], [self.OPENROUTER], []))

    def test_a_healthy_gateway_env_in_every_ordinary_shape_is_healthy_and_loses_no_value(self):
        key = self.OPENROUTER
        shapes = {"plain": f"OPENROUTER_API_KEY={key}\n",
                  "no final newline": f"OPENROUTER_API_KEY={key}",
                  "blank lines and comments": f"\n# the gateway's own key\n\nHERMES_SPOOL_DIR=/x\n\nOPENROUTER_API_KEY={key}\n\n# end\n",
                  "a commented-out assignment": f"# OPENROUTER_API_KEY=sk-or-v1-NOT-A-REAL-KEY-commented\n"
                                                f"#OPENROUTER_API_KEY=sk-or-v1-NOT-A-REAL-KEY-commented\nOPENROUTER_API_KEY={key}\n",
                  "another name with this one as its prefix": f"OPENROUTER_API_KEY_NOTE=not-the-key-at-all\nOPENROUTER_API_KEY={key}\n",
                  "export": f"export OPENROUTER_API_KEY={key}\n",
                  "export and a tab": f"export\tOPENROUTER_API_KEY={key}\n",
                  "CRLF line ends": f"HERMES_SPOOL_DIR=/x\r\nOPENROUTER_API_KEY={key}\r\nHERMES_DASHBOARD=0\r\n",
                  "a byte-order mark": f"\ufeffOPENROUTER_API_KEY={key}\n",
                  "a byte-order mark and CRLF": f"\ufeffOPENROUTER_API_KEY={key}\r\n",
                  "an indented line": f"  \tOPENROUTER_API_KEY={key}\n",
                  "blanks around the equals sign": f"OPENROUTER_API_KEY = {key}\n",
                  "single quotes": f"OPENROUTER_API_KEY='{key}'\n",
                  "double quotes and a comment": f'OPENROUTER_API_KEY="{key}"  # rotated in the autumn\n',
                  "an inline comment": f"OPENROUTER_API_KEY={key} # rotated in the autumn\n",
                  "a tab after the value": f"OPENROUTER_API_KEY={key}\t\n"}
        for shape, body in shapes.items():
            with self.subTest(shape=shape):
                with open(self._w(self.GATEWAY_ENV, ""), "wb") as f:
                    f.write(body.encode("utf-8"))
                self.outputs[("find",)] = (0, self.GATEWAY_ENV + "\n", "")
                self.assertEqual(CE.other_credentials(self.host()), ([self._openrouter_row()], [key], []))
                bundle, secrets = CE.collect_with_secrets(self.host(), self.KEY)
                self.assertEqual(bundle["credentials"], [self._openrouter_row()])
                self.assertEqual(secrets, [key])
                row = bundle["items"]["D2.1"]["data"]["files"][0]
                self.assertEqual((row["kind"], row["label"], row["secrets_held"], row["secrets_not_searchable"]),
                                 ("authorised-other", "gateway-env", ["openrouter-key"], []))
                self.assertNotIn("error", row)

    def test_a_hash_sign_inside_a_value_is_part_of_the_value(self):
        password = "NOT#A#REAL-DASHBOARD-PASSWORD#"
        self._gateway_env(f"OPENROUTER_API_KEY={self.OPENROUTER}\nHERMES_DASHBOARD_BASIC_AUTH_PASSWORD={password}\n")
        rows, secrets, failed = CE.other_credentials(self.host())
        self.assertEqual((secrets, failed), ([self.OPENROUTER, password], []))
        self.assertEqual(rows, [{"label": "dashboard-password", "sha12": None}, self._openrouter_row()])

    def test_two_different_values_for_one_name_are_both_secrets_and_the_set_is_not_certified(self):
        old = "NOT-A-REAL-DASHBOARD-PASSWORD-BEFORE"
        self._gateway_env(f"OPENROUTER_API_KEY={self.OPENROUTER}\nHERMES_DASHBOARD_BASIC_AUTH_PASSWORD={old}\n"
                          f"HERMES_DASHBOARD_BASIC_AUTH_PASSWORD={self.DASH}\n")
        rows, secrets, failed = CE.other_credentials(self.host())
        self.assertEqual(secrets, [self.OPENROUTER, old, self.DASH])
        self.assertEqual(failed, ["gateway-env: duplicate dashboard-password"])   # fixed text: no value, path or length
        self.assertEqual(rows, [self._openrouter_row()])                          # a label with two values has no row

    def test_the_anthropic_file_is_read_by_the_same_rules(self):
        key, old = "sk-ant-api03-SECRETVALUE", "sk-ant-api03-ROTATED-OUT-VALUE"
        self.outputs[("find",)] = (0, "/etc/hermes/.env.anthropic\n", "")
        for body, want in ((f'ANTHROPIC_API_KEY="{key}" \n'.encode(), ([key], [])),
                           (f"ANTHROPIC_API_KEY={old}\nANTHROPIC_API_KEY={key}\n".encode(),
                            ([old, key], ["anthropic-key: duplicate anthropic-key"])),
                           (f"ANTHROPIC_API_KEY={key}\n# \xff\n".encode("latin-1"),
                            ([key], ["anthropic-key: undecodable bytes"]))):
            with self.subTest(body=body):
                with open(self._w("/etc/hermes/.env.anthropic", ""), "wb") as f:
                    f.write(body)
                _rows, secrets, failed = CE.other_credentials(self.host())
                self.assertEqual((secrets, failed), want)

    def test_d2_1_on_its_own_seeds_every_value_of_a_damaged_anthropic_file(self):
        key = "sk-ant-api03-SECRETVALUE"
        for raw in (b"# caf\xe9\n" + f"ANTHROPIC_API_KEY={key}\n".encode(),
                    f"ANTHROPIC_API_KEY={key}\n".encode() + b"# padding line\n" * 800 + b"\xff\n"):
            with self.subTest(size=len(raw)):
                with open(self._w("/etc/hermes/.env.anthropic", ""), "wb") as f:
                    f.write(raw)
                self.outputs[("find",)] = (0, "/etc/hermes/.env.anthropic\n", "")
                h = self.host()
                ctx = CE.context(h)
                (row,) = CE.d2_1(h, ctx)["files"]
                self.assertEqual(ctx["secrets"], [key])
                self.assertEqual((row["kind"], row["error"], row["label"], row["secrets_held"], row["secrets_not_searchable"]),
                                 ("unreadable", "undecodable", "anthropic-key", ["anthropic-key"], []))
                self.assertNotIn("anthropic_key_state", row)        # nothing more is stated about a damaged file

    def test_d2_1_on_its_own_seeds_both_values_of_a_duplicated_name(self):
        old = "sk-or-v1-NOT-A-REAL-KEY-ROTATED-OUT-zyxwvu"
        self._gateway_env(f"OPENROUTER_API_KEY={old}\nOPENROUTER_API_KEY={self.OPENROUTER}\n"
                          "HERMES_DASHBOARD_BASIC_AUTH_PASSWORD=short77\nHERMES_DASHBOARD_BASIC_AUTH_PASSWORD=short78\n")
        h = self.host()
        ctx = CE.context(h)
        (row,) = CE.d2_1(h, ctx)["files"]
        self.assertEqual(ctx["secrets"], [old, self.OPENROUTER, "short77", "short78"])
        self.assertEqual((row["kind"], row["secrets_held"], row["secrets_not_searchable"]),
                         ("authorised-other", ["openrouter-key", "dashboard-password"], ["dashboard-password"]))
        self.assertNotIn("error", row)

    def test_credentials_only_refuses_a_name_given_two_different_values(self):
        old = "sk-or-v1-NOT-A-REAL-KEY-ROTATED-OUT-zyxwvu"
        self._gateway_env(f"OPENROUTER_API_KEY={old}\nOPENROUTER_API_KEY={self.OPENROUTER}\n")
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = CE.main(["--credentials-only"], host=self.host())
        self.assertEqual((rc, out.getvalue()), (2, ""))
        self.assertIn("gateway-env: duplicate openrouter-key", err.getvalue())
        for text in (old, self.OPENROUTER, self.root, str(len(self.OPENROUTER))):
            self.assertNotIn(text, err.getvalue())

    def test_the_anthropic_key_is_searched_for_when_the_gateway_env_cannot_be_read(self):
        self._w("/etc/hermes/.env.anthropic", "ANTHROPIC_API_KEY=sk-ant-api03-SECRETVALUE\n")
        with open(self._w(self.GATEWAY_ENV, ""), "wb") as f:
            f.write(b"OPENROUTER_API_KEY=\xff\xfe\n")
        self.outputs[("find",)] = (0, f"{self.GATEWAY_ENV}\n/etc/hermes/.env.anthropic\n", "")
        self.outputs[("journalctl", "-o")] = (0, "leak sk-ant-api03-SECRETVALUE\n", "")
        bundle, secrets = CE.collect_with_secrets(self.host(), self.KEY)
        self.assertEqual(secrets.count("sk-ant-api03-SECRETVALUE"), 1)
        self.assertEqual(bundle["items"]["D2.3"]["data"]["journal"]["known_secret_hits"], 1)
        self.assertIn("gateway-env", bundle["credentials"][R.COULD_NOT_CHECK])

    def test_the_openrouter_key_is_searched_for_when_the_anthropic_file_cannot_be_read(self):
        with open(self._w("/etc/hermes/.env.anthropic", ""), "wb") as f:
            f.write(b"ANTHROPIC_API_KEY=\xff\xfe\n")
        self._gateway_env(f"OPENROUTER_API_KEY={self.OPENROUTER}\n")
        self.outputs[("find",)] = (0, f"{self.GATEWAY_ENV}\n/etc/hermes/.env.anthropic\n", "")
        self.outputs[("journalctl", "-o")] = (0, f"leak {self.OPENROUTER}\n", "")
        bundle, secrets = CE.collect_with_secrets(self.host(), self.KEY)
        self.assertEqual(secrets.count(self.OPENROUTER), 1)
        self.assertEqual(bundle["items"]["D2.3"]["data"]["journal"]["known_secret_hits"], 1)
        self.assertIn("anthropic-key", bundle["credentials"][R.COULD_NOT_CHECK])

    def test_a_secret_listed_twice_is_counted_once(self):
        self.assertEqual(CE._count_cred_text("x SECRETVALUE12 y", ["SECRETVALUE12", "SECRETVALUE12"])
                         ["known_secret_hits"], 1)

    def test_the_google_secrets_survive_a_failed_d2_1_and_an_unreadable_authorised_file(self):
        with open(self._w(self.GATEWAY_ENV, ""), "wb") as f:
            f.write(b"OPENROUTER_API_KEY=\xff\xfe\n")
        self.outputs[("find",)] = (0, f"{CE.AGENT_DIR}/.env.gaw\n{self.GATEWAY_ENV}\n", "")

        def boom(host, ctx):
            raise CE.CouldNotCheck("x")
        with mock.patch.dict(CE.PROBES, {"D2.1": boom}):
            bundle, secrets = CE.collect_with_secrets(self.host(), self.KEY)
        self.assertEqual(bundle["items"]["D2.1"]["status"], R.COULD_NOT_CHECK)
        self.assertIn("gateway-env", bundle["credentials"][R.COULD_NOT_CHECK])
        self.assertIn(TOKEN, secrets)

    def test_an_unreadable_gateway_env_keeps_the_google_secrets_and_costs_only_its_row(self):
        with open(self._w(self.GATEWAY_ENV, ""), "wb") as f:
            f.write(b"OPENROUTER_API_KEY=\xff\xfe\n")
        self.outputs[("find",)] = (0, f"{CE.AGENT_DIR}/.env.gaw\n{self.GATEWAY_ENV}\n", "")
        bundle, secrets = CE.collect_with_secrets(self.host(), self.KEY)
        self.assertIn(TOKEN, secrets)
        (reason,) = bundle["credentials"].values()
        self.assertEqual(list(bundle["credentials"]), [R.COULD_NOT_CHECK])
        self.assertIn("gateway-env", reason)
        self.assertNotIn(self.root, reason)
        d2_1 = bundle["items"]["D2.1"]
        self.assertEqual(d2_1["status"], R.OBSERVED)
        row = [r for r in d2_1["data"]["files"] if r["path"] == self.GATEWAY_ENV][0]
        self.assertEqual(row["kind"], "unreadable")

    def test_the_dashboard_password_is_searched_for_even_when_the_sweep_misses_the_file(self):
        self._w(self.GATEWAY_ENV, f"HERMES_DASHBOARD_BASIC_AUTH_PASSWORD={self.DASH}\n")
        self.outputs[("journalctl", "-o")] = (0, f"basic auth failed for {self.DASH}\n", "")
        it = CE.collect(self.host(), self.KEY)["items"]["D2.3"]
        self.assertEqual(it["data"]["journal"]["known_secret_hits"], 1)

    def test_d2_1_names_the_held_secrets_too_short_to_be_searched_for(self):
        self._w("/etc/hermes/.env.anthropic", "ANTHROPIC_API_KEY=sk-ant-api03-SECRETVALUE\n")
        for pw, expect in (("short77", ["dashboard-password"]), (self.DASH, [])):
            self._w(self.GATEWAY_ENV, f"OPENROUTER_API_KEY={self.OPENROUTER}\n"
                                      f"HERMES_DASHBOARD_BASIC_AUTH_PASSWORD={pw}\n")
            self.outputs[("find",)] = (0, f"{self.GATEWAY_ENV}\n/etc/hermes/.env.anthropic\n", "")
            rows = {r["path"]: r for r in CE.collect(self.host(), self.KEY)["items"]["D2.1"]["data"]["files"]}
            row = rows[self.GATEWAY_ENV]
            self.assertEqual(row["secrets_held"], ["openrouter-key", "dashboard-password"])
            self.assertEqual(row["secrets_not_searchable"], expect)
            self.assertEqual(rows["/etc/hermes/.env.anthropic"]["secrets_not_searchable"], [])

    def test_credentials_only_refuses_when_an_authorised_file_cannot_be_read(self):
        self._gateway_env(f"OPENROUTER_API_KEY={self.OPENROUTER}\n")
        self._a_directory_instead(self.GATEWAY_ENV)
        self.outputs[("find",)] = (0, CE.AGENT_DIR + "/.env.gaw\n", "")     # a directory is not a sweep hit
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = CE.main(["--credentials-only"], host=self.host())
        self.assertEqual((rc, out.getvalue()), (2, ""))
        self.assertTrue("anthropic-key" in err.getvalue() or "gateway-env" in err.getvalue())

    def test_d2_1_gateway_env_without_an_openrouter_key_adds_no_secret(self):
        for body in ("HERMES_SPOOL_DIR=/var/lib/hermes/spool\n", "OPENROUTER_API_KEY=\nHERMES_SPOOL_DIR=/x\n"):
            self._gateway_env(body)
            _, secrets = CE.collect_with_secrets(self.host(), self.KEY)
            self.assertEqual(secrets, [])

    def test_the_openrouter_key_is_a_known_secret_for_the_journal_counts(self):
        self._gateway_env(f"OPENROUTER_API_KEY={self.OPENROUTER}\n")
        self.outputs[("journalctl", "-o")] = (0, f"debug: Authorization: Bearer {self.OPENROUTER}\n", "")
        items = CE.collect(self.host(), self.KEY)["items"]
        self.assertEqual(items["D2.3"]["data"]["journal"], {"pattern_hits": 0, "known_secret_hits": 1})
        self.assertNotIn(self.OPENROUTER, json.dumps(items))

    def test_d4_1_reports_anthropic_and_openrouter_env_names_only(self):
        # Specific, and first: the catch-all `docker exec` answer below must not also answer the
        # two `printenv` calls, or the `env` text would be taken for the gateway's secret values.
        for name in ("OPENROUTER_API_KEY", "HERMES_DASHBOARD_BASIC_AUTH_PASSWORD"):
            self.outputs[("docker", "exec", "a" * 64, "printenv", name)] = (1, "", "")
        self.outputs[("docker", "exec")] = (0, "ANTHROPIC_API_KEY=sk-ant-XYZ\nOPENROUTER_API_KEY=or-ABC\nHOME=/x\n", "")
        self.outputs[("docker", "ps")] = (0, "a" * 64 + "\n", "")
        bundle, secrets = CE.collect_with_secrets(self.host(), self.KEY)
        d = bundle["items"]["D4.1"]["data"]
        self.assertEqual(d["anthropic_env_names"], ["ANTHROPIC_API_KEY"])
        self.assertEqual(d["openrouter_env_names"], ["OPENROUTER_API_KEY"])
        self.assertEqual(d["secret_env"], {"openrouter-key": "unset", "dashboard-password": "unset"})
        self.assertEqual(set(secrets), {TOKEN})                         # no command's output became a "secret"


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
            rc = CE.main(["--fp-key-tty"], host=self.host(), read_key=lambda: "11" * 32)
        self.assertEqual(rc, 0)                                  # a refusal prints nothing: it must not pass this
        self.assertEqual(json.loads(out.getvalue())["cid_key_id"], R.key_id(self.KEY))
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
    INSTANCES = ("hermes-app-broker@ads-audit.service", "hermes-app-runner@ads-audit.service",
                 "hermes-app-runner@ads-audit.path")

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
        for u in self.INSTANCES:
            self.outputs[("systemctl", "show", u, "-p", "DropInPaths")] = (0, "DropInPaths=\n", "")
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
        self.assertEqual(d["drop_in_paths"], {u: [] for u in self.INSTANCES})
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

    def test_d10_3_lists_each_units_drop_ins_with_the_unit_files_still_equal(self):
        # A drop-in changes what a unit runs (ExecStart, User, Environment) with the unit file
        # byte-identical: installed_equal_repo alone cannot see it.
        self._units()
        d1 = "/etc/systemd/system/hermes-app-runner@.service.d/override.conf"
        d2 = "/run/systemd/system/hermes-app-runner@ads-audit.service.d/10-x.conf"
        self.outputs[("systemctl", "show", self.INSTANCES[1], "-p", "DropInPaths")] = (
            0, f"DropInPaths={d1} {d2}\n", "")
        d = self._item("D10.3")["data"]
        self.assertEqual(d["drop_in_paths"], {self.INSTANCES[0]: [], self.INSTANCES[1]: [d1, d2],
                                              self.INSTANCES[2]: []})
        self.assertEqual(d["installed_equal_repo"], {u: True for u in CE.APP_UNITS})    # control

    def test_d10_3_drop_ins_that_cannot_be_read_are_never_an_empty_list(self):
        self._units()
        self.outputs[("systemctl", "show", self.INSTANCES[0], "-p", "DropInPaths")] = (0, "\n", "")
        self.assertEqual(self._item("D10.3")["data"]["drop_in_paths"][self.INSTANCES[0]], R.COULD_NOT_CHECK)
        self.outputs[("systemctl", "show", self.INSTANCES[2], "-p", "DropInPaths")] = (1, "", "Failed to connect to bus")
        it = self._item("D10.3")
        self.assertEqual(it["status"], R.COULD_NOT_CHECK)
        self.assertIn("systemctl exited 1", it["reason"])

    def test_d10_3_environment_tokens_that_are_not_names_never_reach_the_bundle(self):
        # A token without `=` (a broken quote, a pasted value) was returned whole.
        self.assertEqual(CE._env_names('A=1 sk-live-secret-fragment "B=x y"'), ["?", "A", "B"])
        self.assertEqual(CE._env_names("9BAD=1 =x GOOD_1=2 with-dash=3"), ["?", "GOOD_1"])
        self.assertEqual(CE._env_names(""), [])
        self._units()
        self.outputs[("systemctl", "show", "hermes-app-runner@ads-audit")] = (
            0, "Environment=OK=1 sk-live-secret-fragment\n", "")
        it = self._item("D10.3")
        self.assertEqual(it["data"]["runner_unit"]["Environment"], ["?", "OK"])
        self.assertNotIn("sk-live-secret-fragment", json.dumps(it))

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

    def test_d10_3_sudo_that_gave_neither_answer_is_could_not_check(self):
        self._units()
        for rc, out in ((127, ""), (1, "sudo: unknown user hermes-app-ads-audit\n"), (0, ""),
                        (0, "L'utilisateur hermes-app-ads-audit n'est pas autorisé\n")):
            with self.subTest(rc=rc, out=out):
                self.outputs[("sudo", "-l", "-U")] = (rc, out, "")
                it = self._item("D10.3")
                self.assertEqual(it["status"], R.OBSERVED)
                self.assertEqual(it["data"]["sudo_rules"],
                                 {"rc": rc, "not_allowed": R.COULD_NOT_CHECK, "command_lines": R.COULD_NOT_CHECK})

    def test_d10_3_a_missing_app_user_costs_only_the_groups(self):
        self._units()
        self.outputs[("id", "-nG")] = (1, "", "id: 'hermes-app-ads-audit': no such user\n")
        it = self._item("D10.3")
        self.assertEqual(it["status"], R.OBSERVED)
        self.assertEqual(it["data"]["broker_user_groups"], R.COULD_NOT_CHECK)
        self.assertEqual(it["data"]["broker_unit"]["User"], "hermes-app-ads-audit")
        self.assertEqual(it["data"]["runner_path_active"], "active")
        self.assertNotIn("no such user", json.dumps(it))

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
    BLOCK = ("mcp_servers:\n"
             "  ads_audit:\n"
             "    command: \"python3\"\n"
             "    args: [\"/opt/cc-bin/hermes-app-mcp.py\", \"--app\", \"ads-audit\"]\n"
             "    env: {}\n"
             "\n"
             "    # three tools, nothing else\n"
             "    tools:\n"
             "      include: [ads_audit_run, ads_audit_status, ads_audit_list]\n")
    BLOCK_SHA256 = hashlib.sha256(
        b'{"ads_audit":{"args":["/opt/cc-bin/hermes-app-mcp.py","--app","ads-audit"],"command":"python3",'
        b'"env":{},"tools":{"include":["ads_audit_run","ads_audit_status","ads_audit_list"]}}}').hexdigest()
    # The whole file as the gateway rewrote it on the box: the template's values, another layout.
    REWRITTEN = ("model:\n  default: deepseek/deepseek-v3.2\n  provider: openrouter\n"
                 "terminal:\n  backend: local\n  cwd: .\n  timeout: 300\n"
                 "provider_routing:\n  data_collection: deny\n"
                 "mcp_servers:\n"
                 "  ads_audit:\n"
                 "    command: python3\n"
                 "    args:\n"
                 "      - /opt/cc-bin/hermes-app-mcp.py\n"
                 "      - --app\n"
                 "      - ads-audit\n"
                 "    env: {}\n"
                 "    timeout: 360\n"
                 "    tools:\n"
                 "      include:\n"
                 "        - ads_audit_run\n"
                 "        - ads_audit_status\n"
                 "        - ads_audit_list\n"
                 "      resources: false\n"
                 "      prompts: false\n"
                 "onboarding:\n  seen:\n  - welcome\n  note: |\n    any shape: {not, parsed}\n")
    BOX_CONFIG = CE.AGENT_DIR + "/data/config.yaml"

    def _configs(self, box, repo=None):
        """The box's live config and the checkout's committed template. Around the block the two
        differ (the gateway rewrites its own keys); the block is what is compared."""
        if box is not None:
            self._w(self.BOX_CONFIG, "model: x\n# the one app\n" + box + "terminal:\n  backend: docker\n")
        self._w(CE.MCP_REPO_CONFIG, "# template\nmodel:\n  default: y\n\n" + (self.BLOCK if repo is None else repo))

    def _real_template(self):
        with open(os.path.join(os.path.dirname(HERE), "config.yaml.example"), encoding="utf-8") as f:
            return f.read()

    OPENROUTER = "sk-or-v1-NOT-A-REAL-KEY-0123456789abcdef"

    def _load_openrouter_key(self):
        """D2.1 reads the gateway's .env and puts the key among the known secrets."""
        env = CE.CHECKOUT + "/infra/hermes-agent/.env"
        self._w(env, f"HERMES_SPOOL_DIR=/var/lib/hermes/spool\nOPENROUTER_API_KEY={self.OPENROUTER}\n")
        self.outputs[("find",)] = (0, env + "\n", "")

    def _gateway(self, listing):
        """A running gateway with this `hermes mcp list` answer. It holds the OpenRouter key and
        no dashboard password, and says so to `printenv`: D10.6 emits the listing only when every
        D4.1 secret_env state was measured."""
        del self.outputs[("docker", "ps")]
        self.outputs[("docker", "ps", "-q", "--no-trunc", "--filter")] = (0, GW_ID + "\n", "")
        self.outputs[("docker", "ps", "-q", "--no-trunc")] = (0, "", "")
        self.outputs[("docker", "exec", GW_ID, "hermes", "mcp", "list")] = listing
        self.outputs[("docker", "exec", GW_ID, "printenv", "OPENROUTER_API_KEY")] = (0, self.OPENROUTER + "\n", "")
        self.outputs[("docker", "exec", GW_ID, "printenv", "HERMES_DASHBOARD_BASIC_AUTH_PASSWORD")] = (1, "", "")

    def test_d10_6_block_equal_to_the_committed_one_and_the_listing(self):
        self._configs(self.BLOCK)
        self._gateway((0, "ads_audit  3 tools\n", ""))
        it = self._item("D10.6")
        d = it["data"]
        self.assertEqual(d["mcp_block"], {"equals_repo": True, "reason": "-", "canonical_sha256": self.BLOCK_SHA256})
        self.assertEqual((d["gateway_mcp_list"], d["gateway_mcp_list_rc"]), (["ads_audit  3 tools"], 0))
        self.assertEqual(set(d), {"mcp_block", "gateway_mcp_list", "gateway_mcp_list_rc"})
        for text in ("ads_audit_run", "python3", "hermes-app-mcp"):      # the block's text is never emitted
            self.assertNotIn(text, json.dumps(it))

    def test_d10_6_the_rewritten_layout_equals_the_template(self):
        """The first box rollout: the gateway re-serialised data/config.yaml (quotes dropped, the
        flow lists one item per line, a key added after the block). Same values: equal."""
        template = self._real_template()
        self._w(CE.MCP_REPO_CONFIG, template)
        self._w(self.BOX_CONFIG, self.REWRITTEN)
        it = self._item("D10.6")
        self.assertEqual(it["status"], R.OBSERVED)
        mine = it["data"]["mcp_block"]
        self.assertEqual((mine["equals_repo"], mine["reason"]), (True, "-"))
        self._w(self.BOX_CONFIG, template)                               # the template itself, as installed
        self.assertEqual(self._item("D10.6")["data"]["mcp_block"], mine)
        self.assertEqual(mine["canonical_sha256"], CE.mcp_config.compare(template, template)["canonical_sha256"])
        self.assertNotEqual(mine["canonical_sha256"], self.BLOCK_SHA256)

    def test_d10_6_equal_means_the_same_values_whatever_the_layout(self):
        # Quoting, flow or block lists, key order, comments and blank lines are layout, and so is
        # what trails the block: the blank lines after it and the comment that heads the next key.
        box = ("mcp_servers:\n  ads_audit:\n    tools:\n      include:\n      - 'ads_audit_run'\n      - ads_audit_status\n"
               "      - ads_audit_list\n    # four tools? no: three\n    env: {}\n    args:\n      - /opt/cc-bin/hermes-app-mcp.py\n"
               "      - \"--app\"\n      - ads-audit\n    command: python3\n\n\n# about the terminal\n")
        self._configs(box)
        self.assertEqual(self._item("D10.6")["data"]["mcp_block"],
                         {"equals_repo": True, "reason": "-", "canonical_sha256": self.BLOCK_SHA256})
        self._configs(self.BLOCK, repo=self.BLOCK + "\n# trailing note\n")
        self.assertEqual(self._item("D10.6")["data"]["mcp_block"]["equals_repo"], True)

    def test_d10_6_a_differing_block_is_not_equal_and_none_of_its_text_is_emitted(self):
        secret = "sk-or-NOT-A-REAL-KEY-0123456789"
        second = "terminal:\n  x: 1\n%s:\n  evil:\n    command: sh\n"
        cases = {"a secret in args": ("differs", self.BLOCK.replace('"--app", "ads-audit"]', '"--token", "' + secret + '"]')),
                 "a fourth tool": ("differs", self.BLOCK.replace("ads_audit_list]", "ads_audit_list, shell]")),
                 "a second server": ("differs", self.BLOCK + "  evil:\n    command: sh\n    args: [-c, " + secret + "]\n"),
                 "list order changed": ("differs", self.BLOCK.replace("ads_audit_run, ads_audit_status", "ads_audit_status, ads_audit_run")),
                 "a string where the template has none": ("differs", self.BLOCK.replace("env: {}", 'env: "{}"')),
                 "a url with a password": ("unparseable", self.BLOCK + "  other:\n    url: https://user:" + secret + "@host.internal/x\n"),
                 "a non-empty env": ("unparseable", self.BLOCK.replace("env: {}", "env: {K: " + secret + "}")),
                 "an indent changed": ("unparseable", self.BLOCK.replace("      include:", "    include:")),
                 "an anchor": ("unparseable", self.BLOCK.replace("env: {}", "env: &evil {}")),
                 "CRLF line ends": ("unparseable", self.BLOCK.replace("\n", "\r\n")),
                 "a repeated key in the block": ("duplicate_key", self.BLOCK + "    env: {}\n"),
                 "the block declared a second time": ("duplicate_key", self.BLOCK + second % "mcp_servers"),
                 "a second declaration with the key quoted": ("top_level_not_plain", self.BLOCK + second % '"mcp_servers"'),
                 "a second declaration with an escape in the key": ("top_level_not_plain", self.BLOCK + second % '"mcp\\x5fservers"'),
                 "a second declaration under a merge key": ("top_level_not_plain", self.BLOCK + "<<:\n  mcp_servers:\n    evil:\n      command: sh\n"),
                 "a second document": ("top_level_not_plain", self.BLOCK + "---\nmcp_servers:\n  evil:\n    command: sh\n"),
                 "an empty block": ("no_block", "mcp_servers: {}\n"),
                 "no block at all": ("no_block", "provider_routing:\n  data_collection: deny\n")}
        self.assertIn('"mcp\\x5fservers":', cases["a second declaration with an escape in the key"][1])
        for why, (reason, box) in cases.items():
            with self.subTest(why=why):
                self._configs(box)
                b = CE.collect(self.host(), self.KEY)
                self.assertEqual(b["items"]["D10.6"]["status"], R.OBSERVED)
                d = b["items"]["D10.6"]["data"]["mcp_block"]
                self.assertIs(d["equals_repo"], False)
                self.assertEqual(set(d), {"equals_repo", "reason", "canonical_sha256"})
                self.assertEqual(d["reason"], reason)
                self.assertIn(d["reason"], CE.mcp_config.REASONS)
                if reason == "differs":                                   # it parsed: the sha256 of what it holds
                    self.assertRegex(d["canonical_sha256"], r"^[0-9a-f]{64}$")
                    self.assertNotEqual(d["canonical_sha256"], self.BLOCK_SHA256)
                else:
                    self.assertIsNone(d["canonical_sha256"])
                out = json.dumps(b)
                for text in (secret, "host.internal", "evil", "shell", "--token"):
                    self.assertNotIn(text, out)

    def test_d10_6_binary_content_is_unparseable_never_an_exception(self):
        self._configs(self.BLOCK)
        path = os.path.join(self.root, self.BOX_CONFIG.lstrip("/"))
        for body in (bytes(range(256)) * 16, b"\xff\xfe" + self.BLOCK.encode("utf-16-le"), self.BLOCK.encode() + b"\x00",
                     b"model: \xff\n" + self.BLOCK.encode(), b"\xef\xbb\xbf" + self.BLOCK.encode()):
            with self.subTest(body=body[:12]):
                with open(path, "wb") as f:
                    f.write(body)
                it = self._item("D10.6")
                self.assertEqual(it["status"], R.OBSERVED)
                self.assertEqual(it["data"]["mcp_block"], {"equals_repo": False, "reason": "unparseable", "canonical_sha256": None})

    def _d10_6_could_not_check(self, expect):
        done = []

        def run():
            done.append(self._item("D10.6"))
        import threading
        t = threading.Thread(target=run, daemon=True)                    # a hang must fail, not stall the suite
        t.start(); t.join(20)
        self.assertTrue(done, "D10.6 did not return: the config was opened without O_NONBLOCK")
        self.assertEqual(done[0]["status"], R.COULD_NOT_CHECK)
        self.assertIn(expect, done[0]["reason"])
        return done[0]

    def test_d10_6_missing_config_is_could_not_check(self):
        self._configs(None)
        self._d10_6_could_not_check("data/config.yaml: cannot open")

    def test_d10_6_a_fifo_at_the_config_path_is_could_not_check_never_a_hang(self):
        self._configs(None)
        os.makedirs(os.path.dirname(os.path.join(self.root, self.BOX_CONFIG.lstrip("/"))))
        os.mkfifo(os.path.join(self.root, self.BOX_CONFIG.lstrip("/")))
        self._d10_6_could_not_check("data/config.yaml: not a regular file")

    def test_d10_6_a_symlinked_config_is_could_not_check_and_never_followed(self):
        self._configs(None)
        target = self._w("/root/elsewhere.yaml", self.BLOCK.replace("ads_audit:", "stolen_from_the_target:"))
        link = os.path.join(self.root, self.BOX_CONFIG.lstrip("/"))
        os.makedirs(os.path.dirname(link))
        os.symlink(target, link)
        it = self._d10_6_could_not_check("data/config.yaml: cannot open")
        self.assertNotIn("stolen_from_the_target", json.dumps(it))

    def test_d10_6_an_over_size_config_is_could_not_check(self):
        self._configs(self.BLOCK + "# " + "x" * CE.MCP_CONFIG_CAP + "\n")
        self._d10_6_could_not_check("data/config.yaml: too large")

    def test_d10_6_without_the_committed_block_nothing_can_be_compared(self):
        marker = "only-in-the-template"
        for why, repo in {"no block": "terminal:\n  backend: local\n",
                          "a block outside the subset": self.BLOCK.replace("env: {}", "env: {K: " + marker + "}"),
                          "two blocks": self.BLOCK + "mcp_servers:\n  " + marker + ":\n    command: sh\n",
                          "a top level that is not plain": self.BLOCK + "--- " + marker + "\n"}.items():
            with self.subTest(why=why):
                self._configs(self.BLOCK, repo=repo)
                it = self._d10_6_could_not_check("config.yaml.example: no usable mcp_servers block")
                self.assertNotIn(marker, json.dumps(it))
        # The box's own state does not turn that into a verdict.
        self._configs("provider_routing:\n  data_collection: deny\n", repo="terminal:\n  backend: local\n")
        self._d10_6_could_not_check("config.yaml.example: no usable mcp_servers block")
        os.remove(os.path.join(self.root, CE.MCP_REPO_CONFIG.lstrip("/")))
        self._d10_6_could_not_check("config.yaml.example: cannot open")

    def test_d10_6_failed_or_missing_listing_keeps_the_comparison(self):
        self._configs(self.BLOCK)
        it = self._item("D10.6")                                        # no gateway container at all
        self.assertEqual(it["status"], R.OBSERVED)
        # Nobody to ask for the listing, nor for the values to look for in one: not measured.
        self.assertEqual((it["data"]["gateway_mcp_list"], it["data"]["gateway_mcp_list_rc"]), (R.COULD_NOT_CHECK, None))
        self.assertIs(it["data"]["mcp_block"]["equals_repo"], True)
        self._gateway((127, "", "hermes: not found"))
        it = self._item("D10.6")
        self.assertEqual(it["status"], R.OBSERVED)
        self.assertEqual((it["data"]["gateway_mcp_list"], it["data"]["gateway_mcp_list_rc"]), ([], 127))
        self.assertIs(it["data"]["mcp_block"]["equals_repo"], True)

    def test_d10_6_listing_is_capped_in_lines_and_in_line_length_and_stays_redacted(self):
        self._configs(self.BLOCK)
        long = "ads_audit " + "x" * 5000
        self._gateway((0, long + "\n" + f"oops GOOGLE_ADS_REFRESH_TOKEN={TOKEN}\n" + "row\n" * 100, ""))
        it = self._item("D10.6")
        listing = it["data"]["gateway_mcp_list"]
        self.assertEqual(len(listing), 40)
        self.assertEqual(listing[0], long[:200])
        self.assertEqual(listing[1], "<withheld>")
        self.assertEqual(max(len(l) for l in listing), 200)
        self.assertNotIn(TOKEN, json.dumps(it))

    def test_d10_6_a_known_secret_straddling_the_cut_refuses_the_bundle_and_prints_nothing(self):
        """The 200-character cut must not hide a known secret from assert_no_secret: a line that
        holds one is not cut, so the whole-bundle refusal still fires and no prefix is printed."""
        self._load_openrouter_key()
        self._configs(self.BLOCK)
        straddle = "ads_audit " + "y" * (CE.MCP_LIST_WIDTH - 10 - 20) + self.OPENROUTER
        self.assertLess(straddle.index(self.OPENROUTER), CE.MCP_LIST_WIDTH)
        self.assertGreater(straddle.index(self.OPENROUTER) + len(self.OPENROUTER), CE.MCP_LIST_WIDTH)
        self._gateway((0, straddle + "\nrow\n", ""))
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            with self.assertRaises(RuntimeError):
                CE.main(["--fp-key-tty"], host=self.host(), read_key=lambda: "11" * 32)
        printed = out.getvalue() + err.getvalue()
        for n in range(8, len(self.OPENROUTER) + 1):
            self.assertNotIn(self.OPENROUTER[:n], printed)
        self.assertEqual(printed, "")

    def test_an_unreadable_gateway_env_does_not_hide_the_anthropic_key_from_the_whole_bundle_refusal(self):
        self._configs(self.BLOCK)
        self._w("/etc/hermes/.env.anthropic", "ANTHROPIC_API_KEY=sk-ant-api03-SECRETVALUE\n")
        env = CE.CHECKOUT + "/infra/hermes-agent/.env"
        with open(self._w(env, ""), "wb") as f:
            f.write(b"OPENROUTER_API_KEY=\xff\xfe\n")
        self.outputs[("find",)] = (0, env + "\n/etc/hermes/.env.anthropic\n", "")
        self.outputs[("journalctl", "-o")] = (0, "leak sk-ant-api03-SECRETVALUE\n", "")
        self._gateway((0, "ads_audit sk-ant-api03-SECRETVALUE\nrow\n", ""))
        bundle, secrets = CE.collect_with_secrets(self.host(), self.KEY)
        self.assertIn("sk-ant-api03-SECRETVALUE", secrets)
        self.assertEqual(bundle["items"]["D2.3"]["data"]["journal"]["known_secret_hits"], 1)
        self.assertIn("gateway-env", bundle["credentials"][R.COULD_NOT_CHECK])
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            with self.assertRaises(RuntimeError):
                CE.main(["--fp-key-tty"], host=self.host(), read_key=lambda: "11" * 32)
        self.assertEqual(out.getvalue() + err.getvalue(), "")

    # ---- final review C1: the value parsed from the gateway .env must be the live one -------
    GATEWAY_ENV = CE.CHECKOUT + "/infra/hermes-agent/.env"
    OLD_OPENROUTER = "sk-or-v1-NOT-A-REAL-KEY-ROTATED-OUT-zyxwvu"

    def _leaking_box(self, env_bytes):
        """A gateway .env of exactly these bytes, on a box whose journal and whose gateway's
        `hermes mcp list` text both hold the live OpenRouter key."""
        with open(self._w(self.GATEWAY_ENV, ""), "wb") as f:
            f.write(env_bytes)
        self.outputs[("find",)] = (0, self.GATEWAY_ENV + "\n", "")
        self.outputs[("journalctl", "-o")] = (0, f"debug: Authorization: Bearer {self.OPENROUTER}\n", "")
        self._configs(self.BLOCK)
        self._gateway((0, f"ads_audit {self.OPENROUTER}\nrow\n", ""))

    def _assert_the_live_key_is_guarded(self):
        """The three things a live key must never slip past: the known-secrets list, the leak
        count, and the whole-bundle refusal. Returns the bundle and the list."""
        # The file alone gives the key: the running gateway (see _gateway) holds it as well.
        self.assertIn(self.OPENROUTER, CE.other_credentials(self.host())[1])
        bundle, secrets = CE.collect_with_secrets(self.host(), self.KEY)
        self.assertIn(self.OPENROUTER, secrets)
        self.assertGreaterEqual(bundle["items"]["D2.3"]["data"]["journal"]["known_secret_hits"], 1)
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            with self.assertRaises(RuntimeError):
                CE.main(["--fp-key-tty"], host=self.host(), read_key=lambda: "11" * 32)
        self.assertEqual(out.getvalue() + err.getvalue(), "")
        return bundle, secrets

    def _gateway_row(self, bundle):
        return [r for r in bundle["items"]["D2.1"]["data"]["files"] if r["path"] == self.GATEWAY_ENV][0]

    def _assert_undecodable(self, bundle):
        row = self._gateway_row(bundle)
        self.assertEqual((row["kind"], row["error"], row["label"]), ("unreadable", "undecodable", "gateway-env"))
        self.assertEqual(row["secrets_held"], ["openrouter-key"])
        self.assertEqual(list(bundle["credentials"]), [R.COULD_NOT_CHECK])
        self.assertIn("gateway-env: undecodable bytes", bundle["credentials"][R.COULD_NOT_CHECK])

    def test_case_a_a_bad_byte_far_below_the_key_line_does_not_drop_the_key(self):
        padding = b"# padding line\n" * 800
        self.assertGreater(len(padding), 8192)                      # past the text layer's first chunk
        self._leaking_box(f"OPENROUTER_API_KEY={self.OPENROUTER}\n".encode() + padding + b"\xff\n")
        bundle, _ = self._assert_the_live_key_is_guarded()
        self._assert_undecodable(bundle)

    def test_case_b_a_bad_byte_in_a_comment_above_the_key_line_does_not_drop_the_key(self):
        self._leaking_box(b"# caf\xe9 notes\n" + f"OPENROUTER_API_KEY={self.OPENROUTER}\n".encode())
        bundle, _ = self._assert_the_live_key_is_guarded()
        self._assert_undecodable(bundle)

    def _assert_healthy_apart_from_the_refusal(self, bundle):
        self.assertEqual(bundle["credentials"], [{"label": "openrouter-key", "sha12": R.sha12(self.OPENROUTER)}])
        row = self._gateway_row(bundle)
        self.assertEqual((row["kind"], row["secrets_held"], row["secrets_not_searchable"]),
                         ("authorised-other", ["openrouter-key"], []))
        self.assertNotIn("error", row)

    def test_case_d_a_trailing_space_after_the_key_is_not_part_of_the_key(self):
        self._leaking_box(f"OPENROUTER_API_KEY={self.OPENROUTER} \n".encode())
        bundle, _ = self._assert_the_live_key_is_guarded()
        self._assert_healthy_apart_from_the_refusal(bundle)

    def test_case_d2_a_trailing_space_after_a_quoted_key_leaves_the_bare_key(self):
        self._leaking_box(f'OPENROUTER_API_KEY="{self.OPENROUTER}" \n'.encode())
        bundle, _ = self._assert_the_live_key_is_guarded()
        self._assert_healthy_apart_from_the_refusal(bundle)

    def test_case_g_a_name_given_twice_makes_both_values_known_secrets(self):
        self._leaking_box(f"OPENROUTER_API_KEY={self.OLD_OPENROUTER}\n"
                          f"OPENROUTER_API_KEY={self.OPENROUTER}\n".encode())
        bundle, secrets = self._assert_the_live_key_is_guarded()
        self.assertIn(self.OLD_OPENROUTER, secrets)
        self.assertEqual(list(bundle["credentials"]), [R.COULD_NOT_CHECK])
        self.assertIn("gateway-env: duplicate openrouter-key", bundle["credentials"][R.COULD_NOT_CHECK])
        row = self._gateway_row(bundle)
        self.assertEqual((row["kind"], row["secrets_held"]), ("authorised-other", ["openrouter-key"]))
        self.assertNotIn("error", row)

    # ---- F43: the gateway's own values come from the running gateway (D4.1 secret_env) ------
    OR_NAME, DASH_NAME = "OPENROUTER_API_KEY", "HERMES_DASHBOARD_BASIC_AUTH_PASSWORD"
    DASH = "NOT-A-REAL-DASHBOARD-PASSWORD-0123"
    QUOTED_KEY = 'sk-or-v1-NOT"A"REAL-KEY-with-two-quotes-zyxwvu'
    NOT_SET = (1, "", "")                                   # printenv: the name is not in the environment
    HEALTHY = {"openrouter-key": "matches-file", "dashboard-password": "unset"}

    def _printenv(self, openrouter, dash=NOT_SET):
        """What the running gateway answers `printenv` for its two names (a string is the value
        it holds, a tuple is the (rc, out, err) itself), and enough for D4.1 to be observed.
        Every key is one whole command: none of these can answer for another."""
        for name, answer in ((self.OR_NAME, openrouter), (self.DASH_NAME, dash)):
            self.outputs[("docker", "exec", GW_ID, "printenv", name)] = \
                answer if isinstance(answer, tuple) else (0, answer + "\n", "")
        self.outputs[("docker", "exec", GW_ID, "sh", "-c")] = (0, "/opt/governance absent\n", "")
        self.outputs[("docker", "exec", GW_ID, "env")] = (0, "OPENROUTER_API_KEY=x\nHOME=/x\n", "")

    def _box(self, env_text, openrouter, dash=NOT_SET, leaked=None):
        """A gateway .env of exactly this text on a box whose running gateway answers `printenv`
        with `openrouter` and `dash`. `leaked` is in the journal and in the gateway's `hermes mcp
        list` text; with none, both are clean."""
        with open(self._w(self.GATEWAY_ENV, ""), "wb") as f:
            f.write(env_text.encode("utf-8"))
        self.outputs[("find",)] = (0, self.GATEWAY_ENV + "\n", "")
        self._configs(self.BLOCK)
        self.outputs[("journalctl", "-o")] = (0, f"debug: Authorization: Bearer {leaked}\n" if leaked else "Started.\n", "")
        self._gateway((0, f"ads_audit {leaked}\nrow\n" if leaked else "ads_audit  3 tools\n", ""))
        self._printenv(openrouter, dash)

    def _printenv_calls(self, host):
        return [c for c in host.calls if c[:2] == ["docker", "exec"] and "printenv" in c]

    def _secret_env(self, bundle):
        return bundle["items"]["D4.1"]["data"]["secret_env"]

    def _main(self, host, *argv):
        """(rc or the exception main raised, stdout, stderr) of one run."""
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                rc = CE.main(list(argv), host=host, read_key=lambda: "11" * 32)
            except RuntimeError as e:
                rc = e
        return rc, out.getvalue(), err.getvalue()

    def _assert_a_line_the_gateway_reads_differently_is_guarded(self, env_text, live):
        """The gateway holds `live`, the file spells it so that the collector's own parse does
        not give it, and it has leaked: the known-secrets list, the leak count and the
        whole-bundle refusal must all see it, and D4.1 must say the two differ."""
        self._box(env_text, live, leaked=live)
        self.assertNotIn(live, [v for _, v in CE._other_secrets(self.host(), self.GATEWAY_ENV)[0]])  # control
        bundle, secrets = CE.collect_with_secrets(self.host(), self.KEY)
        self.assertIn(live, secrets)
        self.assertGreaterEqual(bundle["items"]["D2.3"]["data"]["journal"]["known_secret_hits"], 1)
        self.assertEqual(self._secret_env(bundle), {"openrouter-key": "differs-from-file", "dashboard-password": "unset"})
        rc, out, err = self._main(self.host(), "--fp-key-tty")
        self.assertIsInstance(rc, RuntimeError)
        self.assertEqual(out + err, "")

    def test_shape_1_a_quoted_key_followed_by_a_comment_without_a_blank(self):
        self._assert_a_line_the_gateway_reads_differently_is_guarded(
            f'OPENROUTER_API_KEY="{self.OPENROUTER}"#note\n', self.OPENROUTER)

    def test_shape_2_a_quoted_key_followed_by_text(self):
        self._assert_a_line_the_gateway_reads_differently_is_guarded(
            f'OPENROUTER_API_KEY="{self.OPENROUTER}" note\n', self.OPENROUTER)

    def test_shape_3_a_backslash_escaped_key(self):
        escaped = self.QUOTED_KEY.replace('"', '\\"')
        self.assertIn('NOT\\"A\\"REAL', escaped)                   # the file holds the backslashes, the gateway does not
        self._assert_a_line_the_gateway_reads_differently_is_guarded(
            f'OPENROUTER_API_KEY="{escaped}"\n', self.QUOTED_KEY)

    def test_shape_4_a_colon_for_the_equals_sign(self):
        self._assert_a_line_the_gateway_reads_differently_is_guarded(
            f"OPENROUTER_API_KEY: {self.OPENROUTER}\n", self.OPENROUTER)

    def test_shape_5_a_variable_reference(self):
        self._assert_a_line_the_gateway_reads_differently_is_guarded(
            "OPENROUTER_API_KEY=${THE_REAL_NAME}\n", self.OPENROUTER)

    def test_a_gateway_key_that_json_escapes_refuses_the_bundle(self):
        """The file and the gateway agree, so the value was always known: but it holds a `"`, so
        the printed JSON holds it only escaped, which the guard has to look for too."""
        self._box(f"OPENROUTER_API_KEY={self.QUOTED_KEY}\n", self.QUOTED_KEY, leaked=self.QUOTED_KEY)
        bundle, secrets = CE.collect_with_secrets(self.host(), self.KEY)
        self.assertIn(self.QUOTED_KEY, secrets)
        self.assertNotIn(self.QUOTED_KEY, json.dumps(bundle))            # control: only its escaped form is there
        self.assertIn(json.dumps(self.QUOTED_KEY)[1:-1], json.dumps(bundle))
        rc, out, err = self._main(self.host(), "--fp-key-tty")
        self.assertIsInstance(rc, RuntimeError)
        self.assertEqual(out + err, "")
        self.assertEqual(self._secret_env(bundle), self.HEALTHY)

    def test_a_healthy_box_says_matches_file_and_prints_a_bundle_holding_no_value(self):
        self._box(f"OPENROUTER_API_KEY={self.OPENROUTER}\n", self.OPENROUTER)
        h = self.host()
        bundle, secrets = CE.collect_with_secrets(h, self.KEY)
        self.assertEqual(secrets, [self.OPENROUTER])                     # known once, however often it was read
        d = bundle["items"]["D4.1"]["data"]
        self.assertEqual(d["secret_env"], self.HEALTHY)
        self.assertEqual(list(d["secret_env"]), ["openrouter-key", "dashboard-password"])
        self.assertEqual(set(d), {"paths", "google_ads_env_names", "anthropic_env_names", "openrouter_env_names",
                                  "secret_env"})
        self.assertEqual(d["openrouter_env_names"], ["OPENROUTER_API_KEY"])
        self.assertEqual(bundle["credentials"], [{"label": "openrouter-key", "sha12": R.sha12(self.OPENROUTER)}])
        self.assertEqual(bundle["items"]["D2.3"]["data"]["journal"], {"pattern_hits": 0, "known_secret_hits": 0})
        self.assertEqual(bundle["items"]["D10.6"]["data"]["gateway_mcp_list"], ["ads_audit  3 tools"])
        # The gateway is asked once for each name in the whole run, and never through a shell.
        self.assertEqual(self._printenv_calls(h), [["docker", "exec", GW_ID, "printenv", self.OR_NAME],
                                                   ["docker", "exec", GW_ID, "printenv", self.DASH_NAME]])
        rc, out, err = self._main(self.host(), "--fp-key-tty")
        self.assertEqual((rc, err), (0, ""))
        self.assertEqual(json.loads(out)["items"]["D4.1"]["data"]["secret_env"], self.HEALTHY)
        self.assertNotIn(self.OPENROUTER, out)

    def test_with_the_dashboard_on_both_values_match_the_file(self):
        self._box(f"OPENROUTER_API_KEY={self.OPENROUTER}\nHERMES_DASHBOARD=1\n"
                  f"HERMES_DASHBOARD_BASIC_AUTH_PASSWORD={self.DASH}\n", self.OPENROUTER, dash=self.DASH)
        bundle, secrets = CE.collect_with_secrets(self.host(), self.KEY)
        self.assertEqual(self._secret_env(bundle), {"openrouter-key": "matches-file", "dashboard-password": "matches-file"})
        self.assertEqual(secrets, [self.OPENROUTER, self.DASH])
        rc, out, err = self._main(self.host(), "--fp-key-tty")
        self.assertEqual((rc, err), (0, ""))
        for value in (self.OPENROUTER, self.DASH):
            self.assertNotIn(value, out)

    def test_a_file_edited_after_the_gateway_started_makes_both_keys_known(self):
        self._box(f"OPENROUTER_API_KEY={self.OPENROUTER}\n", self.OLD_OPENROUTER, leaked=self.OLD_OPENROUTER)
        bundle, secrets = CE.collect_with_secrets(self.host(), self.KEY)
        self.assertEqual(self._secret_env(bundle), {"openrouter-key": "differs-from-file", "dashboard-password": "unset"})
        self.assertEqual(secrets, [self.OPENROUTER, self.OLD_OPENROUTER])
        self.assertEqual(bundle["items"]["D2.3"]["data"]["journal"]["known_secret_hits"], 1)
        self.assertEqual(bundle["credentials"], [{"label": "openrouter-key", "sha12": R.sha12(self.OPENROUTER)}])
        rc, out, err = self._main(self.host(), "--fp-key-tty")
        self.assertIsInstance(rc, RuntimeError)
        self.assertEqual(out + err, "")

    def test_a_password_the_gateway_holds_and_the_file_does_not_is_a_known_secret(self):
        self._box(f"OPENROUTER_API_KEY={self.OPENROUTER}\n", self.OPENROUTER, dash=self.DASH, leaked=self.DASH)
        bundle, secrets = CE.collect_with_secrets(self.host(), self.KEY)
        self.assertEqual(self._secret_env(bundle), {"openrouter-key": "matches-file", "dashboard-password": "differs-from-file"})
        self.assertEqual(secrets, [self.OPENROUTER, self.DASH])
        self.assertEqual(bundle["items"]["D2.3"]["data"]["journal"]["known_secret_hits"], 1)

    def test_a_gateway_env_that_cannot_be_read_never_matches(self):
        self._box("", self.OPENROUTER, leaked=self.OPENROUTER)
        os.remove(os.path.join(self.root, self.GATEWAY_ENV.lstrip("/")))
        os.mkdir(os.path.join(self.root, self.GATEWAY_ENV.lstrip("/")))    # open() raises whoever asks
        self.outputs[("find",)] = (0, "", "")
        states, values = CE.gateway_secret_env(self.host())
        self.assertEqual((states, values), ({"openrouter-key": "differs-from-file", "dashboard-password": "unset"},
                                            [self.OPENROUTER]))
        bundle, secrets = CE.collect_with_secrets(self.host(), self.KEY)
        self.assertEqual(secrets, [self.OPENROUTER])
        self.assertEqual(bundle["items"]["D2.3"]["data"]["journal"]["known_secret_hits"], 1)

    def test_without_a_gateway_container_nothing_is_asked_and_the_files_values_stay_known(self):
        self._w(self.GATEWAY_ENV, f"OPENROUTER_API_KEY={self.OPENROUTER}\n")
        self.outputs[("find",)] = (0, self.GATEWAY_ENV + "\n", "")
        self._printenv("sk-or-v1-NOT-A-REAL-KEY-never-asked-for")         # no container: nobody may ask
        h = self.host()
        bundle, secrets = CE.collect_with_secrets(h, self.KEY)
        self.assertEqual(bundle["items"]["D4.1"], {"status": R.COULD_NOT_CHECK, "reason":
                                                   "CouldNotCheck: gateway container not running — isolation cannot be observed"})
        self.assertEqual(secrets, [self.OPENROUTER])
        self.assertEqual(self._printenv_calls(h), [])
        with self.assertRaises(CE.CouldNotCheck) as cm:
            CE.gateway_secret_env(h)
        self.assertEqual(str(cm.exception), CE.NO_GATEWAY)

    def test_a_failing_docker_ps_is_could_not_check_with_a_fixed_message(self):
        marker = "Cannot-connect-to-the-daemon-MARKER"
        self.outputs[("docker", "ps")] = (1, marker + "\n", marker + "\n")
        for answer in ((1, marker + "\n", marker + "\n"), (0, marker + "\n", ""), (0, GW_ID + "\n" + GW_ID + "\n", ""),
                       (0, "", ""), (124, "", "docker: timed out")):
            with self.subTest(answer=answer):
                self.outputs[("docker", "ps")] = answer
                h = self.host()
                with self.assertRaises(CE.CouldNotCheck) as cm:
                    CE.gateway_secret_env(h)
                self.assertEqual(str(cm.exception), CE.NO_GATEWAY)
                self.assertEqual(self._printenv_calls(h), [])
        ctx = {}
        self.assertEqual(CE._gateway_secret_states(self.host(), ctx), R.COULD_NOT_CHECK)
        self.assertEqual(ctx, {"secret_env": R.COULD_NOT_CHECK})        # nothing seeded

    def test_printenv_failing_for_one_name_costs_that_label_only(self):
        marker = "docker-daemon-said-MARKER"
        failed = (125, marker + "\n", marker + "\n")
        for openrouter, dash, want, known in (
                (self.OPENROUTER, failed, {"openrouter-key": "matches-file", "dashboard-password": R.COULD_NOT_CHECK},
                 [self.OPENROUTER]),
                (failed, self.DASH, {"openrouter-key": R.COULD_NOT_CHECK, "dashboard-password": "differs-from-file"},
                 [self.DASH])):
            with self.subTest(want=want):
                self.outputs[("docker", "ps")] = (0, "", "")            # _gateway() replaces it, each time
                self._box(f"OPENROUTER_API_KEY={self.OPENROUTER}\n", openrouter, dash=dash)
                self.assertEqual(CE.gateway_secret_env(self.host()), (want, known))
                bundle = CE.collect(self.host(), self.KEY)
                self.assertEqual(self._secret_env(bundle), want)
                self.assertNotIn(marker, json.dumps(bundle))

    def test_no_text_a_printenv_call_prints_reaches_a_reason_or_the_bundle(self):
        out_marker, err_marker = "PRINTENV-STDOUT-MARKER", "PRINTENV-STDERR-MARKER"
        self._box(f"OPENROUTER_API_KEY={self.OPENROUTER}\n", (125, out_marker + "\n", err_marker + "\n"),
                  dash=(1, "", "Error response from daemon: " + err_marker + "\n"))
        bundle, secrets = CE.collect_with_secrets(self.host(), self.KEY)
        self.assertEqual(self._secret_env(bundle), {"openrouter-key": R.COULD_NOT_CHECK, "dashboard-password": R.COULD_NOT_CHECK})
        self.assertEqual(secrets, [self.OPENROUTER])                     # the file's value only: no output was seeded
        rc, out, err = self._main(self.host(), "--fp-key-tty")
        self.assertEqual(rc, 0)
        for marker in (out_marker, err_marker, "daemon"):
            self.assertNotIn(marker, json.dumps(bundle))
            self.assertNotIn(marker, out + err)
        # A value read with exit 0 is still read when the command also wrote to stderr.
        self.outputs[("docker", "exec", GW_ID, "printenv", self.OR_NAME)] = (0, self.OPENROUTER + "\n", err_marker + "\n")
        bundle = CE.collect(self.host(), self.KEY)
        self.assertEqual(self._secret_env(bundle)["openrouter-key"], "matches-file")
        self.assertNotIn(err_marker, json.dumps(bundle))

    def test_what_each_printenv_answer_means(self):
        """Exit 0 gives the value (one trailing newline removed, nothing else); exit 1 with no
        output is a name that is not set; anything else was not measured. Fail closed: `docker
        exec` itself exits 1, with a message, when the container stopped a moment ago."""
        two_lines = "NOT-A-REAL-KEY line one\nNOT-A-REAL-KEY line two\n"
        cases = {"the file's value": ((0, self.OPENROUTER + "\n", ""), "matches-file", [self.OPENROUTER]),
                 "the file's value with no newline": ((0, self.OPENROUTER, ""), "matches-file", [self.OPENROUTER]),
                 "another value": ((0, self.OLD_OPENROUTER + "\n", ""), "differs-from-file", [self.OLD_OPENROUTER]),
                 "a value of several lines stays whole": ((0, two_lines + "\n", ""), "differs-from-file", [two_lines]),
                 "the file's value and a blank": ((0, self.OPENROUTER + " \n", ""), "differs-from-file", [self.OPENROUTER + " "]),
                 "a short value": ((0, "short77\n", ""), "differs-from-file", ["short77"]),
                 "set but empty": ((0, "\n", ""), "unset", []),
                 "exit 0 and no output at all": ((0, "", ""), R.COULD_NOT_CHECK, []),   # printenv always ends a value
                 "not set": ((1, "", ""), "unset", []),
                 "exit 1 with a message": ((1, "", "Error response from daemon: not running\n"), R.COULD_NOT_CHECK, []),
                 "exit 1 with output": ((1, "sk-or-v1-NOT-A-REAL-KEY-from-a-failed-call\n", ""), R.COULD_NOT_CHECK, []),
                 "exit 2": ((2, "", ""), R.COULD_NOT_CHECK, []),
                 "a timeout": ((124, "", "docker: timed out"), R.COULD_NOT_CHECK, []),
                 "a docker error": ((125, "", "boom"), R.COULD_NOT_CHECK, []),
                 "not executable": ((126, "", "boom"), R.COULD_NOT_CHECK, []),
                 "no printenv": ((127, "", "boom"), R.COULD_NOT_CHECK, []),
                 "killed": ((-9, "", ""), R.COULD_NOT_CHECK, [])}
        self._box(f"OPENROUTER_API_KEY={self.OPENROUTER}\n", self.OPENROUTER)
        for what, (answer, state, values) in cases.items():
            with self.subTest(what=what):
                self.outputs[("docker", "exec", GW_ID, "printenv", self.OR_NAME)] = answer
                self.assertEqual(CE.gateway_secret_env(self.host()),
                                 ({"openrouter-key": state, "dashboard-password": "unset"}, values))

    def test_a_printenv_that_cannot_be_run_or_decoded_is_could_not_check_never_an_exception(self):
        """The real runner decodes strictly: a value that is not UTF-8 raises there. That must
        cost its own label only, and none of the bytes may reach anything."""
        self._box(f"OPENROUTER_API_KEY={self.OPENROUTER}\n", self.OPENROUTER, dash=self.DASH)
        child = [sys.executable, "-c", "import sys; sys.stdout.buffer.write(b'NOT-A-REAL-\\xff\\xfe-KEY\\n')"]
        with self.assertRaises(UnicodeDecodeError):                      # control: what the real runner does
            CE._run_real(child)
        fake = self.host()

        def undecodable(argv, timeout=60):
            if argv[3:] == ["printenv", self.OR_NAME]:
                return CE._run_real(child, timeout)
            return fake.run(argv, timeout)

        def unrunnable(argv, timeout=60):
            if argv[3:] == ["printenv", self.OR_NAME]:
                raise PermissionError(13, "Permission denied: NOT-A-REAL-PATH-MARKER")
            return fake.run(argv, timeout)
        for run in (undecodable, unrunnable):
            with self.subTest(run=run.__name__):
                host = CE.Host(self.root, run)
                want = {"openrouter-key": R.COULD_NOT_CHECK, "dashboard-password": "differs-from-file"}
                self.assertEqual(CE.gateway_secret_env(host), (want, [self.DASH]))
                bundle, secrets = CE.collect_with_secrets(host, self.KEY)
                self.assertEqual(self._secret_env(bundle), want)
                self.assertEqual(bundle["items"]["D4.1"]["status"], R.OBSERVED)
                self.assertEqual(secrets, [self.OPENROUTER, self.DASH])
                for text in ("NOT-A-REAL-", "codec", "MARKER", "Permission"):
                    self.assertNotIn(text, json.dumps(bundle["items"]["D4.1"]))

    def test_d4_1_on_its_own_asks_the_gateway_and_seeds_what_it_holds(self):
        self._box("OPENROUTER_API_KEY=${THE_REAL_NAME}\n", self.OPENROUTER, dash=self.DASH)
        h, ctx = self.host(), {}
        d = CE.d4_1(h, ctx)
        self.assertEqual(d["secret_env"], {"openrouter-key": "differs-from-file", "dashboard-password": "differs-from-file"})
        self.assertEqual(ctx["secrets"], [self.OPENROUTER, self.DASH])
        self.assertEqual(len(self._printenv_calls(h)), 2)
        CE.d4_1(h, ctx)                                                  # a second item in the same run does not ask again
        self.assertEqual(len(self._printenv_calls(h)), 2)
        self.assertEqual(ctx["secrets"], [self.OPENROUTER, self.DASH])

    def test_d4_1_reports_a_state_for_each_label_when_the_gateway_could_not_be_asked(self):
        """The run found no gateway when it asked for the values, and D4.1 finds one a moment
        later: every label is could-not-check, and the gateway is not asked a second time."""
        self._box(f"OPENROUTER_API_KEY={self.OPENROUTER}\n", self.OPENROUTER)
        h, ctx = self.host(), {"secret_env": R.COULD_NOT_CHECK}
        self.assertEqual(CE.d4_1(h, ctx)["secret_env"],
                         {"openrouter-key": R.COULD_NOT_CHECK, "dashboard-password": R.COULD_NOT_CHECK})
        self.assertEqual(self._printenv_calls(h), [])

    def test_fingerprint_only_and_credentials_only_never_ask_the_gateway(self):
        self._box(f"OPENROUTER_API_KEY={self.OPENROUTER}\n", self.OPENROUTER)
        for flag in ("--fingerprint-only", "--credentials-only"):
            with self.subTest(flag=flag):
                h = self.host()
                _rc, out, _err = self._main(h, flag)
                self.assertTrue(out)                                     # control: it ran and printed
                self.assertEqual(self._printenv_calls(h), [])
                self.assertNotIn("secret_env", out)

    # ---- fix round 1: trimmed forms are known secrets; the gateway's text needs known secrets ----
    def _assert_the_bare_key_is_guarded(self, env_text, held, state):
        """The gateway holds `held`, a value with the key inside it (a blank, a line break), and
        the BARE key has leaked, mid-line in the journal and into the `hermes mcp list` text."""
        key = self.OPENROUTER
        self.assertNotEqual(held, key)
        self.assertIn(key, held)
        self._box(env_text, (0, held + "\n", ""), leaked=key)
        self.outputs[("journalctl", "-o")] = (0, f"debug: Authorization: Bearer {key} was sent\n", "")
        bundle, secrets = CE.collect_with_secrets(self.host(), self.KEY)
        self.assertIn(key, secrets)
        self.assertIn(held, secrets)                                     # the value itself stays known
        self.assertGreaterEqual(bundle["items"]["D2.3"]["data"]["journal"]["known_secret_hits"], 1)
        self.assertEqual(self._secret_env(bundle)["openrouter-key"], state)
        rc, out, err = self._main(self.host(), "--fp-key-tty")
        self.assertIsInstance(rc, RuntimeError)
        self.assertEqual(out + err, "")

    def test_a_gateway_value_that_ends_in_a_line_break_makes_the_bare_key_known(self):
        self._assert_the_bare_key_is_guarded(f'OPENROUTER_API_KEY="{self.OPENROUTER}\\n"\n',
                                             self.OPENROUTER + "\n", "differs-from-file")

    def test_a_gateway_value_with_a_blank_after_the_key_makes_the_bare_key_known(self):
        self._assert_the_bare_key_is_guarded(f'OPENROUTER_API_KEY="{self.OPENROUTER} "\n',
                                             self.OPENROUTER + " ", "matches-file")

    def test_a_gateway_value_with_a_blank_before_the_key_makes_the_bare_key_known(self):
        self._assert_the_bare_key_is_guarded(f'OPENROUTER_API_KEY=" {self.OPENROUTER}"\n',
                                             " " + self.OPENROUTER, "matches-file")

    def test_a_gateway_value_with_the_key_on_its_second_line_makes_the_bare_key_known(self):
        self._assert_the_bare_key_is_guarded(f'OPENROUTER_API_KEY="prefix-not-a-secret\\n{self.OPENROUTER}"\n',
                                             "prefix-not-a-secret\n" + self.OPENROUTER, "differs-from-file")

    def test_a_file_value_with_a_blank_inside_its_quotes_makes_the_bare_key_known_without_a_gateway(self):
        key = self.OPENROUTER
        self._w(self.GATEWAY_ENV, f'OPENROUTER_API_KEY="{key} "\n')
        self.outputs[("find",)] = (0, self.GATEWAY_ENV + "\n", "")
        self.outputs[("journalctl", "-o")] = (0, f"debug: Authorization: Bearer {key} was sent\n", "")
        bundle, secrets = CE.collect_with_secrets(self.host(), self.KEY)
        self.assertEqual(secrets, [key + " ", key])
        self.assertGreaterEqual(bundle["items"]["D2.3"]["data"]["journal"]["known_secret_hits"], 1)
        h = self.host()
        ctx = CE.context(h)                                              # and D2.1 on its own seeds the same
        CE.d2_1(h, ctx)
        self.assertEqual(ctx["secrets"], [key + " ", key])

    def test_the_forms_of_a_secret_value(self):
        for value, want in (("NOT-A-REAL-KEY", ["NOT-A-REAL-KEY"]),
                            ("NOT-A-REAL-KEY ", ["NOT-A-REAL-KEY ", "NOT-A-REAL-KEY"]),
                            ("\tNOT-A-REAL-KEY", ["\tNOT-A-REAL-KEY", "NOT-A-REAL-KEY"]),
                            ("NOT-A-REAL-KEY\n", ["NOT-A-REAL-KEY\n", "NOT-A-REAL-KEY"]),
                            ("one \n two\r\n\nthree", ["one \n two\r\n\nthree", "one", "two", "three"]),
                            (" \n ", [" \n "]), ("", [])):
            with self.subTest(value=value):
                self.assertEqual(CE._secret_forms(value), want)

    def test_the_gateways_text_is_withheld_when_its_key_could_not_be_read(self):
        key = self.OPENROUTER
        self._box(f'OPENROUTER_API_KEY="{key}"#note\n', (125, "", "boom"), leaked=key)
        bundle, secrets = CE.collect_with_secrets(self.host(), self.KEY)
        self.assertNotIn(key, secrets)                                   # control: nothing here knows the key
        self.assertEqual(self._secret_env(bundle)["openrouter-key"], R.COULD_NOT_CHECK)
        d = bundle["items"]["D10.6"]["data"]
        self.assertEqual((d["gateway_mcp_list"], d["gateway_mcp_list_rc"]), (R.COULD_NOT_CHECK, 0))
        self.assertIs(d["mcp_block"]["equals_repo"], True)               # the comparison is still reported
        rc, out, err = self._main(self.host(), "--fp-key-tty")
        self.assertEqual((rc, err), (0, ""))
        self.assertNotIn(key, out)
        self.assertEqual(json.loads(out)["items"]["D10.6"]["data"]["gateway_mcp_list"], R.COULD_NOT_CHECK)

    def test_d10_6_prints_the_gateways_text_only_with_every_secret_env_state_measured(self):
        self._box(f"OPENROUTER_API_KEY={self.OPENROUTER}\n", self.OPENROUTER)
        h = self.host()
        both = {"openrouter-key": "differs-from-file", "dashboard-password": "unset"}
        for why, ctx in {"measured": {"secret_env": dict(self.HEALTHY)}, "measured, one differs": {"secret_env": both}}.items():
            with self.subTest(why=why):
                d = CE.d10_6(h, ctx)
                self.assertEqual((d["gateway_mcp_list"], d["gateway_mcp_list_rc"]), (["ads_audit  3 tools"], 0))
        for why, ctx in {"never asked": {}, "no gateway when asked": {"secret_env": R.COULD_NOT_CHECK},
                         "one label not measured": {"secret_env": dict(self.HEALTHY, **{"dashboard-password": R.COULD_NOT_CHECK})},
                         "not a dict": {"secret_env": ["matches-file"]}}.items():
            with self.subTest(why=why):
                before = len(self._printenv_calls(h))
                d = CE.d10_6(h, ctx)
                self.assertEqual((d["gateway_mcp_list"], d["gateway_mcp_list_rc"]), (R.COULD_NOT_CHECK, 0))
                self.assertIs(d["mcp_block"]["equals_repo"], True)
                self.assertEqual(len(self._printenv_calls(h)), before)   # D10.6 never asks itself

    def test_a_secret_that_holds_a_client_slug_is_caught_before_redaction(self):
        """The redactor rewrites the slug inside the password, so the redacted text no longer
        holds the value: the guard has to read the text as it was before redaction too."""
        password = "NOT-A-REAL-acme-dental-PASSWORD-0123"
        self._box(f"OPENROUTER_API_KEY={self.OPENROUTER}\nHERMES_DASHBOARD_BASIC_AUTH_PASSWORD={password}\n",
                  self.OPENROUTER, dash=password, leaked=password)
        bundle, secrets = CE.collect_with_secrets(self.host(), self.KEY)
        self.assertIn(password, secrets)
        self.assertNotIn(password, json.dumps(bundle))                   # control: the redacted text hides it
        self.assertIn("NOT-A-REAL-<client>-PASSWORD-0123", json.dumps(bundle))
        rc, out, err = self._main(self.host(), "--fp-key-tty")
        self.assertIsInstance(rc, RuntimeError)
        self.assertEqual(out + err, "")

    def test_d10_6_a_long_line_without_a_secret_is_still_cut_with_secrets_loaded(self):
        self._load_openrouter_key()
        self._configs(self.BLOCK)
        self._gateway((0, "ads_audit " + "x" * 5000 + "\n", ""))
        listing = self._item("D10.6")["data"]["gateway_mcp_list"]
        self.assertEqual(listing, [("ads_audit " + "x" * 5000)[:200]])

    def test_the_committed_template_has_the_block_the_collector_compares_with(self):
        """The real config.yaml.example, parsed by the parser the collector compares with."""
        value, reason = CE.mcp_config.block_value(self._real_template())
        self.assertIsNone(reason)
        self.assertEqual(value["ads_audit"]["tools"]["include"], ["ads_audit_run", "ads_audit_status", "ads_audit_list"])
        self.assertEqual(value["ads_audit"]["env"], {})
        self.assertTrue(CE.MCP_REPO_CONFIG.endswith("/infra/hermes-agent/config.yaml.example"))
        for gone in ("_mcp_block", "_block_sha256", "_MCP_KEY_RE"):
            self.assertFalse(hasattr(CE, gone))

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


class TestRunReal(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.d, True)
        self.marker = os.path.join(self.d, "cleaned")

    # What gives the child's interpreter time to install its handler before SIGTERM arrives.
    TIMEOUT = 5

    def _child(self, on_term):
        return [sys.executable, "-c",
                "import signal, sys, time\n"
                f"def h(s, f):\n    {on_term}\n"
                "signal.signal(signal.SIGTERM, h)\n"
                "time.sleep(60)\n"]

    def test_a_timeout_sends_sigterm_and_waits_for_the_cleanup(self):
        argv = self._child(f"open({self.marker!r}, 'w').close(); sys.exit(143)")
        rc, out, err = CE._run_real(argv, timeout=self.TIMEOUT)
        self.assertEqual((rc, out), (124, ""))
        self.assertIn("timed out", err)
        self.assertTrue(os.path.exists(self.marker))            # the child's own cleanup ran

    def test_a_child_that_ignores_sigterm_is_killed_after_the_grace(self):
        argv = self._child("pass")
        t0 = time.monotonic()
        with mock.patch.object(CE, "TERM_GRACE", 1):
            rc, _, _ = CE._run_real(argv, timeout=self.TIMEOUT)
        elapsed = time.monotonic() - t0
        self.assertEqual(rc, 124)
        self.assertGreaterEqual(elapsed, self.TIMEOUT + 1)      # the grace was waited out before the kill
        self.assertLess(elapsed, 15)                            # and the kill ended it: not the child's 60 s

    def test_a_grandchild_holding_the_pipe_cannot_hang_the_runner(self):
        pidfile = os.path.join(self.d, "grandchild.pid")
        def reap():
            try:
                with open(pidfile) as f:
                    os.kill(int(f.read()), 9)
            except (OSError, ValueError):       # never started, or already gone
                pass
        self.addCleanup(reap)
        argv = [sys.executable, "-c",
                "import signal, subprocess, sys, time\n"
                "signal.signal(signal.SIGTERM, lambda s, f: None)\n"
                "g = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(20)'])\n"   # inherits stdout
                f"open({pidfile!r}, 'w').write(str(g.pid))\n"
                "time.sleep(60)\n"]
        t0 = time.monotonic()
        with mock.patch.object(CE, "TERM_GRACE", 1):
            rc, _, _ = CE._run_real(argv, timeout=self.TIMEOUT)
        self.assertEqual(rc, 124)
        self.assertLess(time.monotonic() - t0, 12)      # timeout + grace is 6 s; not the grandchild's 20 s

    def test_ordinary_results_are_unchanged(self):
        self.assertEqual(CE._run_real([sys.executable, "-c",
                                       "import sys; print('o'); print('e', file=sys.stderr); sys.exit(3)"]),
                         (3, "o\n", "e\n"))
        self.assertEqual(CE._run_real(["/nonexistent/binary-for-this-test"])[0], 127)


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

    def test_nsfs_handle_from_the_real_findmnt_listing_reaches_namespace_handles(self):
        # Through the real _mounts() output, not a hand-built list: findmnt lists the handle as an
        # nsfs mount under a tmpfs /run. not_swept must stay what it was (nsfs is still not a target).
        run = os.path.join(self.root, "run/docker/netns"); os.makedirs(run)
        h = os.path.join(run, "abc123"); open(h, "w").close(); os.chmod(h, 0)
        self.addCleanup(os.chmod, h, 0o600)
        self.outputs[("findmnt",)] = (0, "/ ext4\n/run tmpfs\n/run/docker/netns/abc123 nsfs\n", "")
        d = CE.collect(self.host(), self.KEY)["items"]["D2.1"]["data"]
        self.assertEqual(d["memory_sweep"]["namespace_handles"], ["/run/docker/netns/abc123"])
        self.assertEqual(d["memory_sweep"]["unreadable"], [])
        self.assertEqual(d["not_swept"], ["/run"])

    EXECSTART = ("ExecStart={ path=/opt/hermes-agent/bin/docker-create-proxy.py ; "
                 "argv[]=/opt/hermes-agent/bin/docker-create-proxy.py --listen /run/hermes/docker.sock%s ; "
                 "ignore_errors=no ; start_time=[%s] ; stop_time=[n/a] ; pid=%d ; code=(null) ; status=0/0 }\n")

    def _proxy(self, execstart="ExecStart=x\n", drop_ins=(0, "DropInPaths=\n", "")):
        """The more specific prefix first: FakeHost answers with the first prefix that matches."""
        for k in [k for k in self.outputs if k[:3] == ("systemctl", "show", "hermes-docker-proxy")]:
            del self.outputs[k]
        self.outputs[("systemctl", "is-active")] = (0, "active\n", "")
        self.outputs[("systemctl", "show", "hermes-docker-proxy", "-p", "DropInPaths")] = drop_ins
        self.outputs[("systemctl", "show", "hermes-docker-proxy")] = (0, execstart, "")

    def test_d4_2_argv_hash_survives_a_restart_and_changes_with_the_argv(self):
        self.addCleanup(setattr, CE, "LAST_PASS_EXECSTART", None)
        self._proxy(self.EXECSTART % ("", "Thu 2026-09-25 10:00:00 UTC", 1234))
        a = CE.d4_2(self.host(), {})
        self._proxy(self.EXECSTART % ("", "Wed 2026-10-01 07:30:12 UTC", 99871))    # restarted: same argv
        b = CE.d4_2(self.host(), {})
        self.assertRegex(a["execstart_argv_sha256"], r"^[0-9a-f]{64}$")
        self.assertEqual(a["execstart_argv_sha256"], b["execstart_argv_sha256"])
        self.assertNotEqual(a["execstart_sha256"], b["execstart_sha256"])           # the whole line did change
        self._proxy(self.EXECSTART % (" --allow-privileged", "Thu 2026-09-25 10:00:00 UTC", 1234))
        c = CE.d4_2(self.host(), {})
        self.assertNotEqual(a["execstart_argv_sha256"], c["execstart_argv_sha256"])
        # An argument that itself holds ` ; ` must not end the hashed segment early.
        self._proxy(self.EXECSTART % (" ; rm -rf /", "Thu 2026-09-25 10:00:00 UTC", 1234))
        self.assertNotEqual(a["execstart_argv_sha256"], CE.d4_2(self.host(), {})["execstart_argv_sha256"])
        for line in ("ExecStart=x\n", "", "ExecStart={ path=/x ; ignore_errors=no ; pid=1 }\n"):
            self._proxy(line)
            self.assertIsNone(CE.d4_2(self.host(), {})["execstart_argv_sha256"], line)

    def test_d4_2_the_whole_line_hash_and_the_comparison_are_unchanged(self):
        self.addCleanup(setattr, CE, "LAST_PASS_EXECSTART", None)
        line = self.EXECSTART % ("", "Thu 2026-09-25 10:00:00 UTC", 1234)
        self._proxy(line)
        CE.LAST_PASS_EXECSTART = CE.PK.sha256_bytes(line.encode())
        d = CE.d4_2(self.host(), {})
        self.assertEqual(d["execstart_sha256"], CE.PK.sha256_bytes(line.encode()))
        self.assertIs(d["matches_last_pass"], True)
        self.assertEqual(set(d), {"active", "execstart_sha256", "execstart_argv_sha256", "last_pass_execstart_sha256",
                                  "matches_last_pass", "drop_in_paths"})

    def test_d4_2_lists_the_proxys_drop_ins_from_a_separate_call(self):
        self._proxy()
        host = self.host()
        self.assertEqual(CE.d4_2(host, {})["drop_in_paths"], [])
        shows = [c for c in host.calls if c[:2] == ["systemctl", "show"]]
        self.assertEqual(shows, [["systemctl", "show", "hermes-docker-proxy", "-p", "ExecStart"],
                                 ["systemctl", "show", "hermes-docker-proxy", "-p", "DropInPaths"]])
        over = "/etc/systemd/system/hermes-docker-proxy.service.d/override.conf"
        self._proxy(drop_ins=(0, f"DropInPaths={over}\n", ""))
        d = CE.d4_2(self.host(), {})
        self.assertEqual(d["drop_in_paths"], [over])
        self.assertEqual(d["execstart_sha256"], CE.PK.sha256_bytes(b"ExecStart=x\n"))    # the hashed text is the same

    def test_d4_2_drop_ins_that_cannot_be_read_are_never_an_empty_list(self):
        self._proxy(drop_ins=(0, "\n", ""))                           # systemd printed no such property
        self.assertEqual(CE.d4_2(self.host(), {})["drop_in_paths"], R.COULD_NOT_CHECK)
        self._proxy(drop_ins=(1, "", "Failed to connect to bus"))
        it = CE.collect(self.host(), self.KEY)["items"]["D4.2"]
        self.assertEqual(it["status"], R.COULD_NOT_CHECK)
        self.assertIn("systemctl exited 1", it["reason"])

    def test_d4_2_compares_with_the_last_pass(self):
        self._proxy()
        self.addCleanup(setattr, CE, "LAST_PASS_EXECSTART", None)
        CE.LAST_PASS_EXECSTART = None
        d = CE.d4_2(self.host(), {})
        self.assertIsNone(d["matches_last_pass"])
        CE.LAST_PASS_EXECSTART = d["execstart_sha256"]
        self.assertTrue(CE.d4_2(self.host(), {})["matches_last_pass"])

    def _run_main(self, *extra):
        self._proxy()
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
