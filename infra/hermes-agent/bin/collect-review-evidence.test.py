#!/usr/bin/env python3
import contextlib, importlib.util, io, json, os, sys, tempfile, unittest
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
        out = json.dumps(CE.collect(self.host()))
        self.assertNotIn("acme-dental", out)
        self.assertIn("log/<client>.jsonl", out)

    def test_no_credential_value_or_customer_id_anywhere(self):
        out = json.dumps(CE.collect(self.host()))
        self.assertNotIn(TOKEN, out)
        self.assertNotIn("1234567890", out)
        self.assertIn(R.sha12(TOKEN), out)                          # control: fingerprint present

    def test_failed_command_is_could_not_check(self):
        items = CE.collect(self.host())["items"]
        self.assertEqual(items["D1.2"]["status"], R.COULD_NOT_CHECK)   # ufw: not in fake outputs
        self.assertEqual(items["D1.1"]["status"], R.OBSERVED)          # control: ss answered

    def test_gateway_not_running_is_could_not_check(self):
        items = CE.collect(self.host())["items"]
        self.assertEqual(items["D4.1"]["status"], R.COULD_NOT_CHECK)

    def test_missing_clients_json_refuses_to_print(self):
        os.remove(os.path.join(self.root, CE.GOV.lstrip("/"), "registry/clients.json"))
        self.assertEqual(CE.main([], host=self.host()), 2)

    def test_every_checklist_box_id_has_a_probe_and_nothing_else_runs(self):
        items = CE.collect(self.host())["items"]
        self.assertEqual(sorted(items), sorted(CE.PROBES))

    def test_backup_dir_named_after_a_client_is_redacted(self):
        self._w("/root/live-gate-acme-dental-20260901/note.txt", "hi")
        out = json.dumps(CE.collect(self.host()))
        self.assertNotIn("acme-dental", out)
        self.assertIn("live-gate-<client>-20260901", out)

    def test_docker_group_absent_is_empty(self):
        self.outputs[("getent", "group", "docker")] = (2, "", "")
        items = CE.collect(self.host())["items"]
        self.assertEqual(items["D1.6"]["status"], R.OBSERVED)
        self.assertEqual(items["D1.6"]["data"], {"docker_group_members": []})

    def test_getent_failure_is_could_not_check(self):
        self.outputs[("getent", "group", "docker")] = (1, "", "boom")
        items = CE.collect(self.host())["items"]
        self.assertEqual(items["D1.6"]["status"], R.COULD_NOT_CHECK)

    # ---- A1: the sweep must be honest about a non-zero find, even rc 1 with output ----

    def test_find_rc1_with_output_is_still_could_not_check(self):
        self.outputs[("find",)] = (1, CE.AGENT_DIR + "/.env.gaw\n",
                                   "find: '/proc/1234/fd': Permission denied\n"
                                   "find: '/proc/5678/task': Permission denied\n")
        items = CE.collect(self.host())["items"]
        self.assertEqual(items["D2.1"]["status"], R.COULD_NOT_CHECK)
        self.assertIn("exited 1", items["D2.1"]["reason"])
        self.assertIn("2 stderr lines", items["D2.1"]["reason"])
        self.assertNotIn("Permission denied", items["D2.1"]["reason"])

    def test_find_rc0_control_still_observed(self):
        items = CE.collect(self.host())["items"]
        self.assertEqual(items["D2.1"]["status"], R.OBSERVED)   # control

    def test_d6_2_find_nonzero_is_could_not_check_never_leaks_stderr_text(self):
        # The generic ("find",) fixture answers every find call, including d6_2's — split
        # it into two specific prefixes so the sweep (D2.1) can stay healthy as a control
        # while only d6_2's own find call is made to fail.
        del self.outputs[("find",)]
        self.outputs[("find", "/", "-xdev")] = (
            0, CE.AGENT_DIR + "/.env.gaw\n" + CE.AGENT_DIR + "/.env.gaw.example\n", "")
        self.outputs[("find", "/root")] = (1, "", "find: '/root/x': Permission denied\n")
        items = CE.collect(self.host())["items"]
        self.assertEqual(items["D6.2"]["status"], R.COULD_NOT_CHECK)
        self.assertIn("exited 1", items["D6.2"]["reason"])
        self.assertIn("1 stderr lines", items["D6.2"]["reason"])
        self.assertNotIn("Permission denied", items["D6.2"]["reason"])
        self.assertEqual(items["D2.1"]["status"], R.OBSERVED)   # control: sweep unaffected

    # ---- A2: filesystem coverage — what the sweep did NOT cross ----------------------

    def test_not_swept_lists_non_pseudo_mounts_other_than_root(self):
        self.outputs[("findmnt",)] = (0, "/ ext4\n/proc proc\n/dev/shm tmpfs\n/boot ext4\n", "")
        items = CE.collect(self.host())["items"]
        self.assertEqual(items["D2.1"]["data"]["not_swept"], ["/boot", "/dev/shm"])

    def test_not_swept_could_not_check_when_findmnt_fails_but_item_stays_observed(self):
        # findmnt is not in the fake outputs -> falls through to (127, "", "not found")
        items = CE.collect(self.host())["items"]
        self.assertEqual(items["D2.1"]["status"], R.OBSERVED)           # control
        self.assertEqual(items["D2.1"]["data"]["not_swept"], "could-not-check")

    # ---- A3: one sweep per run ---------------------------------------------------

    def test_sweep_runs_only_once_per_full_collect(self):
        h = self.host()
        CE.collect(h)
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
        items = CE.collect(self.host())["items"]
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
        items = CE.collect(self.host())["items"]
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
        return {r["path"]: r for r in CE.collect(self.host())["items"]["D2.1"]["data"]["files"]}

    # ---- a: freshness ----------------------------------------------------------
    def test_bundle_carries_collected_at_utc(self):
        b = CE.collect(self.host())
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
        out = CE.collect(self.host())
        ms = out["items"]["D2.1"]["data"]["memory_sweep"]
        self.assertEqual(ms["mounts"], ["/dev/shm", "/run/user/1000"])
        self.assertEqual(ms["name_hits"], ["/dev/shm/.env.stash"])
        self.assertEqual(ms["content_hits"], ["/run/user/1000/notes.txt"])
        self.assertNotIn(TOKEN, json.dumps(out))

    def test_memory_sweep_clean_control(self):
        self.outputs[("findmnt",)] = (0, "/ ext4\n/dev/shm tmpfs\n", "")
        self._w("/dev/shm/sem.x", "nothing\n")
        ms = CE.collect(self.host())["items"]["D2.1"]["data"]["memory_sweep"]
        self.assertEqual((ms["mounts"], ms["name_hits"], ms["content_hits"]), (["/dev/shm"], [], []))

    def test_memory_sweep_reports_an_unenterable_dir_instead_of_skipping_it(self):
        if os.geteuid() == 0:
            self.skipTest("root can enter a 0000 directory")
        self.outputs[("findmnt",)] = (0, "/ ext4\n/dev/shm tmpfs\n", "")
        self._w("/dev/shm/locked/f", "x\n")
        locked = os.path.join(self.root, "dev/shm/locked")
        os.chmod(locked, 0)
        try:
            ms = CE.collect(self.host())["items"]["D2.1"]["data"]["memory_sweep"]
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
            items = CE.collect(self.host())["items"]
        self.assertEqual(items["D2.1"]["status"], R.OBSERVED)
        self.assertEqual(items["D2.1"]["data"]["memory_sweep"]["mounts"], ["/run"])

    def test_memory_sweep_could_not_check_when_findmnt_fails_item_stays_observed(self):
        items = CE.collect(self.host())["items"]                   # findmnt not faked
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
        row = CE.collect(self.host())["items"]["D6.1"]["data"]["claude_google_ads"]
        self.assertEqual(row["extra"], [])
        self.assertEqual(row["env_file"], {"present": True, "size": 0})

    def test_d6_1_non_empty_env_is_extra(self):
        self._install_package("GOOGLE_ADS_DEVELOPER_TOKEN=x\n")
        row = CE.collect(self.host())["items"]["D6.1"]["data"]["claude_google_ads"]
        self.assertEqual(row["extra"], [".env"])

    def test_d6_1_absent_env_control(self):
        self._install_package(None)
        row = CE.collect(self.host())["items"]["D6.1"]["data"]["claude_google_ads"]
        self.assertEqual((row["extra"], row["env_file"]), ([], {"present": False, "size": 0}))

    # ---- e: every home in /etc/passwd, and more history kinds --------------------------
    def test_history_sweep_covers_passwd_homes_and_more_file_kinds(self):
        self._w("/etc/passwd", "root:x:0:0:root:/root:/bin/bash\n"
                               "hermes-broker:x:998:998::/var/lib/hermes-broker:/usr/sbin/nologin\n")
        self._w("/var/lib/hermes-broker/.psql_history", f"\\set t {TOKEN}\n")
        self._w("/root/.bash_history", "ls\n")
        h = CE.collect(self.host())["items"]["D2.2"]["data"]["histories"]
        self.assertEqual(h["/var/lib/hermes-broker/.psql_history"]["pattern_hits"], 1)
        self.assertEqual(h["/root/.bash_history"]["pattern_hits"], 0)      # control

    def test_history_sweep_without_passwd_falls_back_to_root_and_home(self):
        self._w("/home/alice/.bash_history", "ls\n")
        h = CE.collect(self.host())["items"]["D2.2"]["data"]["histories"]
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
        os.makedirs(os.path.join(self.root, CE.AGENT_DIR.lstrip("/"), "data/vaults"), exist_ok=True)
        out = CE.collect(self.host())
        rows = out["items"]["D7.1"]["data"]["audit_data"]
        self.assertEqual(sorted(r["status"] for r in rows), ["active", "unregistered"])
        self.assertNotIn("ghost-client", json.dumps(out))

    def test_d7_1_vault_rows_carry_the_registry_status_without_slugs(self):
        self._w(CE.GOV + "/registry/clients.json", json.dumps({"clients": {
            "acme-dental": {"customer_id": "1234567890", "status": "active"},
            "gone-dental": {"customer_id": "2223334444", "status": "retired"}}}))
        vaults = os.path.join(self.root, CE.AGENT_DIR.lstrip("/"), "data/vaults")
        for n in ("acme-dental", "gone-dental", "stray-dental"):
            os.makedirs(os.path.join(vaults, n))
        out = CE.collect(self.host())
        rows = out["items"]["D7.1"]["data"]["vaults"]
        self.assertEqual([r["status"] for r in rows], ["active", "retired", "unregistered"])
        dump = json.dumps(out)
        for slug in ("gone-dental", "stray-dental"):
            self.assertNotIn(slug, dump)


if __name__ == "__main__":
    unittest.main()
