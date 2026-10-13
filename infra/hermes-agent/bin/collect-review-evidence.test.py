#!/usr/bin/env python3
import subprocess, base64, contextlib, hashlib, importlib.util, io, json, os, shutil, stat, sys, tempfile, time, unittest
from unittest import mock
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import review_lib as R
spec = importlib.util.spec_from_file_location("collect_review_evidence", os.path.join(HERE, "collect-review-evidence.py"))
CE = importlib.util.module_from_spec(spec); spec.loader.exec_module(CE)

TOKEN = "1//0gFAKEREFRESHTOKENabcdefghijklmnop"


def _four(two, new="unset"):
    """D4.1 `secret_env`: the states of the two older labels plus the two since checklist v1.17
    (the dashboard's password hash and session secret), which are `new`."""
    return {**two, "dashboard-password-hash": new, "dashboard-session-secret": new}


def _as_entries(text):
    """A test's journal text as `journalctl -o json` prints it: one entry per line with the line
    as MESSAGE. A line that is already a JSON object is left as it is."""
    out = []
    for line in text.splitlines():
        try:
            is_entry = isinstance(json.loads(line), dict)
        except ValueError:
            is_entry = False
        out.append(line if is_entry else json.dumps({"MESSAGE": line}, ensure_ascii=False))
    return "".join(l + "\n" for l in out)


class FakeHost(CE.Host):
    def __init__(self, root, outputs):
        super().__init__(root=root, run=self._fake)
        self.outputs, self.calls = outputs, []

    def _fake(self, argv, timeout=60):
        self.calls.append(argv)
        for prefix, result in self.outputs.items():
            if tuple(argv[:len(prefix)]) == prefix:
                if result[0] == 0 and argv[0] == "journalctl" and "--all" in argv:
                    return (0, _as_entries(result[1]), result[2])
                return result
        return (127, "", "not found")


APPS = ("ads-audit", "ads-report")
BOTH = {"declared": True, "installed": True}        # what every per-job entry says of a job that is both


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
            ("systemctl", "list-units"): (0, "".join(f"hermes-app-{k}@{a}.{s} loaded active running x\n"
                                                     for a in APPS
                                                     for k, s in (("broker", "service"), ("runner", "path"))), ""),
        }
        man_dir = os.path.join(self.root, CE.AGENT_DIR.lstrip("/"), "registry", "apps"); os.makedirs(man_dir)
        for app in APPS:                                # the fake box holds both jobs
            shutil.copy(os.path.join(os.path.dirname(HERE), "registry", "apps", app + ".json"), man_dir)

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

    def test_an_output_file_that_cannot_be_made_owner_only_gets_nothing_written(self):
        with mock.patch.object(R, "restrict_output", return_value=False) as ro, \
                contextlib.redirect_stdout(io.StringIO()) as out, contextlib.redirect_stderr(io.StringIO()) as err:
            rc = CE.main(["--credentials-only"], host=self.host())
        self.assertEqual((rc, out.getvalue()), (2, ""))
        self.assertIn("owner-only", err.getvalue())
        ro.assert_called_once()

    def test_the_output_is_restricted_before_it_is_written(self):
        order = []
        buf = io.StringIO()
        buf.write = lambda text, w=buf.write: (order.append("write"), w(text))[1]
        with mock.patch.object(R, "restrict_output", side_effect=lambda s: order.append("restrict") or True), \
                contextlib.redirect_stdout(buf):
            rc = CE.main(["--credentials-only"], host=self.host())
        self.assertEqual((rc, order[0]), (0, "restrict"))
        self.assertIn("write", order)

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

    def test_the_git_status_call_takes_no_optional_lock(self):
        h = self.host()
        h.outputs[("git",)] = (0, "", "")
        CE.box_fingerprint(h, CE.context(h))
        status = [c for c in h.calls if c[0] == "git" and "status" in c]
        self.assertTrue(status)
        for c in status:
            self.assertIn("--no-optional-locks", c[:c.index("status")])

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
        for name, _label in CE.OTHER_SECRET_NAMES[CE.GATEWAY_ENV_FILE]:
            self.outputs[("docker", "exec", "a" * 64, "printenv", name)] = (1, "", "")
        self.outputs[("docker", "exec")] = (0, "ANTHROPIC_API_KEY=sk-ant-XYZ\nOPENROUTER_API_KEY=or-ABC\nHOME=/x\n", "")
        self.outputs[("docker", "ps")] = (0, "a" * 64 + "\n", "")
        bundle, secrets = CE.collect_with_secrets(self.host(), self.KEY)
        d = bundle["items"]["D4.1"]["data"]
        self.assertEqual(d["anthropic_env_names"], ["ANTHROPIC_API_KEY"])
        self.assertEqual(d["openrouter_env_names"], ["OPENROUTER_API_KEY"])
        self.assertEqual(d["secret_env"], _four({"openrouter-key": "unset", "dashboard-password": "unset"}))
        self.assertEqual(set(secrets), {TOKEN})                         # no command's output became a "secret"

    # ---- v1.16: the Hermes home secrets file (v0.21.5 writes a generated API_SERVER_KEY into it)
    HERMES_HOME_ENV = CE.CHECKOUT + "/infra/hermes-agent/data/.env"
    API_KEY = "c0ffee" * 10 + "0a1b"                                  # 64 hex, built so no hex run sits in the source
    # Shaped like the bundled template: comments (one naming a provider key), non-secret defaults.
    TEMPLATE = ("# Hermes Agent environment\n# OPENROUTER_API_KEY=your-key-here\n"
                "HERMES_LOG_LEVEL=info\nexport TERMINAL_BACKEND=local\nBROWSER_HEADLESS=true\n")

    def _hermes_home_env(self, body):
        self._w(self.HERMES_HOME_ENV, body)
        self.outputs[("find",)] = (0, self.HERMES_HOME_ENV + "\n", "")

    def test_d2_1_the_hermes_home_env_is_authorised_and_its_key_inventoried(self):
        self._hermes_home_env(self.TEMPLATE + f"API_SERVER_KEY={self.API_KEY}\n")
        self.outputs[("journalctl", "-o")] = (0, f"api_server: key {self.API_KEY}\n", "")
        bundle, secrets = CE.collect_with_secrets(self.host(), self.KEY)
        row = bundle["items"]["D2.1"]["data"]["files"][0]
        self.assertEqual((row["path"], row["kind"], row["label"]),
                         (self.HERMES_HOME_ENV, "authorised-other", "hermes-home-env"))
        self.assertEqual((row["secrets_held"], row["secrets_not_searchable"], row["credential_shaped_names"]),
                         (["api-server-key"], [], []))
        self.assertIn(self.API_KEY, secrets)
        self.assertEqual(bundle["items"]["D2.3"]["data"]["journal"]["known_secret_hits"], 1)
        self.assertNotIn(self.API_KEY, json.dumps(bundle))
        self.assertIn({"label": "api-server-key", "sha12": R.sha12(self.API_KEY)}, bundle["credentials"])

    def test_d2_1_names_a_credential_placed_in_the_hermes_home_env_and_never_its_value(self):
        openrouter, github = "sk-or-v1-NOT-A-REAL-HOME-KEY-0123456789", "ghp_NOTAREALTOKEN-zyxwvutsrqponm"
        self._hermes_home_env(self.TEMPLATE + f"API_SERVER_KEY={self.API_KEY}\n"
                              f"OPENROUTER_API_KEY={openrouter}\n  export GITHUB_TOKEN = {github}\n")
        bundle = CE.collect(self.host(), self.KEY)
        row = bundle["items"]["D2.1"]["data"]["files"][0]
        self.assertEqual(row["credential_shaped_names"], ["GITHUB_TOKEN", "OPENROUTER_API_KEY"])
        text = json.dumps(bundle)
        for value in (openrouter, github, self.API_KEY):
            self.assertNotIn(value, text)

    def test_credential_shaped_names_is_on_the_hermes_home_row_only(self):
        self._gateway_env(f"OPENROUTER_API_KEY={self.OPENROUTER}\n")
        self._w(self.HERMES_HOME_ENV, self.TEMPLATE + f"API_SERVER_KEY={self.API_KEY}\n")
        self.outputs[("find",)] = (0, self.GATEWAY_ENV + "\n" + self.HERMES_HOME_ENV + "\n", "")
        rows = {r["label"]: r for r in CE.collect(self.host(), self.KEY)["items"]["D2.1"]["data"]["files"]}
        self.assertEqual(set(rows), {"gateway-env", "hermes-home-env"})
        self.assertNotIn("credential_shaped_names", rows["gateway-env"])
        self.assertEqual(rows["hermes-home-env"]["credential_shaped_names"], [])

    # ---- v1.16: D4.1 `listeners`, the gateway container's listening ports
    TCP_HEADER = ("  sl  local_address rem_address   st tx_queue rx_queue tr tm->when retrnsmt"
                  "   uid  timeout inode\n")
    TCP = TCP_HEADER + (
        "   0: 0100007F:21C2 00000000:0000 0A 00000000:00000000 00:00000000 00000000 10000 0 1 1 0 100 0 0 10 0\n"
        "   1: 0100007F:21C2 0100007F:D3F0 01 00000000:00000000 00:00000000 00000000 10000 0 2 1 0 20 4 30 10 -1\n"
        "   2: 0100007F:9C40 0100007F:21C2 01 00000000:00000000 00:00000000 00000000 10000 0 3 1 0 20 4 30 10 -1\n")
    TCP6_HEADER = ("  sl  local_address                         remote_address                        st tx_queue"
                   " rx_queue tr tm->when retrnsmt   uid  timeout inode\n")
    ANY6 = "0" * 32                                                   # the IPv6 any-address, as /proc spells it
    TCP6 = TCP6_HEADER + (
        f"   0: {ANY6}:239F {ANY6}:0000 0A "
        "00000000:00000000 00:00000000 00000000 10000 0 4 1 0 100 0 0 10 0\n")

    def _d4_1(self, cat):
        gw = "a" * 64
        self.outputs[("docker", "ps")] = (0, gw + "\n", "")
        self.outputs[("docker", "exec", gw, "cat")] = cat
        self.outputs[("docker", "exec", gw, "printenv")] = (1, "", "")
        self.outputs[("docker", "exec", gw, "env")] = (0, "HOME=/opt/data\n", "")
        self.outputs[("docker", "exec", gw, "sh")] = (0, "/opt/governance absent\n", "")
        h = self.host()
        return CE.d4_1(h, {}), h

    def test_d4_1_listeners_are_the_listening_ports_of_both_tables(self):
        d, h = self._d4_1((0, self.TCP + self.TCP6, ""))
        self.assertEqual(d["listeners"], [8642, 9119])
        self.assertIn(["docker", "exec", "a" * 64, "cat", "/proc/net/tcp", "/proc/net/tcp6"], h.calls)
        self.assertNotIn("0100007F", json.dumps(d))

    def test_d4_1_listeners_are_deduplicated(self):
        tcp6 = self.TCP6_HEADER + self.TCP6.splitlines(True)[1].replace("239F", "21C2")
        self.assertEqual(self._d4_1((0, self.TCP + tcp6, ""))[0]["listeners"], [8642])

    DNS4 = "   0: 0B00007F:8693 00000000:0000 0A 00000000:00000000 00:00000000 00000000 0 0 5 1 0 100 0 0 10 0\n"
    DASH4 = "   1: 00000000:239F 00000000:0000 0A 00000000:00000000 00:00000000 00000000 10000 0 6 1 0 100 0 0 10 0\n"

    def test_d4_1_docker_dns_listener_is_counted_not_listed(self):
        """The box: the dashboard on 0.0.0.0:9119 and Docker's embedded DNS on 127.0.0.11:34451."""
        d, _ = self._d4_1((0, self.TCP_HEADER + self.DNS4 + self.DASH4 + self.TCP6_HEADER, ""))
        self.assertEqual((d["listeners"], d["docker_dns_listeners"]), ([9119], 1))
        self.assertNotIn("34451", json.dumps(d))

    def test_d4_1_docker_dns_listener_in_tcp6_mapped_form_is_excluded(self):
        mapped = "0" * 16 + "FFFF0000" + "0B00007F"
        tcp6 = self.TCP6_HEADER + (f"   0: {mapped}:8693 {self.ANY6}:0000 0A "
                                   "00000000:00000000 00:00000000 00000000 0 0 7 1 0 100 0 0 10 0\n")
        d, _ = self._d4_1((0, self.TCP_HEADER + self.DASH4 + tcp6, ""))
        self.assertEqual((d["listeners"], d["docker_dns_listeners"]), ([9119], 1))

    def test_d4_1_a_loopback_listener_is_still_reported(self):
        d, _ = self._d4_1((0, self.TCP + self.TCP6_HEADER, ""))         # 127.0.0.1:8642 LISTEN
        self.assertEqual((d["listeners"], d["docker_dns_listeners"]), ([8642], 0))

    def test_d4_1_listeners_empty_tables(self):
        self.assertEqual(self._d4_1((0, self.TCP_HEADER + self.TCP6_HEADER, ""))[0]["listeners"], [])

    def test_d4_1_listeners_could_not_check_keeps_the_rest_of_the_item(self):
        for cat in ((1, "", "cat: /proc/net/tcp6: No such file or directory"),
                    (0, "", ""), (0, "not a table\n", ""),
                    (0, self.TCP, ""),                                   # one table only: tcp6 not read
                    (0, self.TCP_HEADER + "   0: garbage\n" + self.TCP6_HEADER, "")):
            with self.subTest(cat=cat):
                d, _ = self._d4_1(cat)
                self.assertEqual((d["listeners"], d["docker_dns_listeners"]), (R.COULD_NOT_CHECK,) * 2)
                self.assertEqual(d["paths"], ["/opt/governance absent"])
                self.assertEqual(d["secret_env"], _four({"openrouter-key": "unset", "dashboard-password": "unset"}))
                self.assertNotIn("No such file", json.dumps(d))


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


class JobBox(Base):
    """The fake box with both jobs' journals and results: the audit's hold what the tests of the
    audit read, the second job's are there and empty."""
    def setUp(self):
        super().setUp()
        self.outputs[("run-client-audit", "--probe-env")] = (0, json.dumps({"matches_declared": True, "services": {}}), "")
        self.outputs[("run-client-audit", "--probe-egress")] = (0, json.dumps({"matches_expected": True}), "")
        self._journal(broker=BROKER + "request=x op=run client=acme-dental status=refused reason=quota\n"
                             + BROKER + "request=y op=run client=acme-dental status=ok reason=-\n",
                      runner="Collecting...\nAudit complete.\n")
        self._journal(app="ads-report", broker="", runner="")
        for app in APPS:
            os.makedirs(self._results_dir(app))
        self.res = self._results_dir("ads-audit")
        self.good = {"request_id": RID_A, "op": "run", "client": "acme-dental",
                     "status": "ok", "reason": None, "exit_code": 0, "ts": "2026-10-01_12-00-00", "steps": [],
                     "vault_path": "/var/lib/hermes/vaults/acme-dental/audits/2026-10-01_12-00-00-audit.md"}
        self._result(self.good)
        self._result(dict(self.good, request_id=RID_B, reason="free text"))

    def _results_dir(self, app):
        return os.path.join(self.root, "var/lib/hermes/spool/apps", app, "results")

    def _result(self, obj, name=None, app="ads-audit"):
        with open(os.path.join(self._results_dir(app), name or obj["request_id"] + ".json"), "w") as f:
            json.dump(obj, f)

    def _journal(self, broker=None, runner=None, app="ads-audit"):
        """Each unit's journal text, or an (rc, out, err) tuple for a failing journalctl."""
        for unit, out in (("broker", broker), ("runner", runner)):
            if out is not None:
                self.outputs[("journalctl", "-u", f"hermes-app-{unit}@{app}")] = \
                    out if isinstance(out, tuple) else (0, out, "")

    def _item(self, iid):
        return CE.collect(self.host(), self.KEY)["items"][iid]


class TestD10(JobBox):
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
        for app in APPS:                                # the second job answers as the audit does
            self.outputs[("systemctl", "show", f"hermes-app-broker@{app}")] = (
                0, f"User=hermes-app-{app}\nNoNewPrivileges=yes\nCapabilityBoundingSet=\nPrivateNetwork=yes\n"
                   "ProtectSystem=strict\nProtectHome=yes\nPrivateTmp=yes\nUMask=0077\n"
                   f"ReadWritePaths=/var/lib/hermes/spool/apps/{app} /var/lib/hermes/app-state/{app}\n"
                   "ActiveState=active\nEnvironment=\n", "")
            self.outputs[("systemctl", "show", f"hermes-app-runner@{app}")] = (0, "Environment=\n", "")
            for u in self.INSTANCES:
                self.outputs[("systemctl", "show", u.replace("ads-audit", app), "-p", "DropInPaths")] = (0, "DropInPaths=\n", "")
            self.outputs[("systemctl", "is-active", f"hermes-app-runner@{app}.path")] = (0, "active\n", "")
        self.outputs[("id", "-nG")] = (0, "hermes-app-ads-audit hermes\n", "")
        self.outputs[("sudo", "-l", "-U")] = (0, "User hermes-app-ads-audit is not allowed to run sudo on box-7.\n", "")

    def test_d10_3_reports_units_groups_sudo_and_path(self):
        self._units()
        top = self._item("D10.3")["data"]
        d = top["apps"]["ads-audit"]
        self.assertEqual(d["broker_unit"]["User"], "hermes-app-ads-audit")
        self.assertEqual(d["broker_unit"]["CapabilityBoundingSet"], "")
        self.assertEqual(d["broker_unit"]["Environment"], [])
        self.assertEqual(d["broker_unit"]["EnvironmentFiles"], [])
        self.assertEqual(d["runner_unit"], {"Environment": [], "EnvironmentFiles": []})
        self.assertEqual(top["installed_equal_repo"], {u: True for u in CE.APP_UNITS})
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
        self.assertEqual(it["data"]["apps"]["ads-audit"]["sudo_rules"], {"rc": 0, "not_allowed": False, "command_lines": 2})
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
        self.assertEqual(it["data"]["apps"]["ads-audit"]["runner_unit"],
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
        self.assertEqual(d["apps"]["ads-audit"]["drop_in_paths"], {self.INSTANCES[0]: [], self.INSTANCES[1]: [d1, d2],
                                                                   self.INSTANCES[2]: []})
        self.assertEqual(d["installed_equal_repo"], {u: True for u in CE.APP_UNITS})    # control

    def test_d10_3_drop_ins_that_cannot_be_read_are_never_an_empty_list(self):
        self._units()
        self.outputs[("systemctl", "show", self.INSTANCES[0], "-p", "DropInPaths")] = (0, "\n", "")
        self.assertEqual(self._item("D10.3")["data"]["apps"]["ads-audit"]["drop_in_paths"][self.INSTANCES[0]], R.COULD_NOT_CHECK)
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
        self.assertEqual(it["data"]["apps"]["ads-audit"]["runner_unit"]["Environment"], ["?", "OK"])
        self.assertNotIn("sk-live-secret-fragment", json.dumps(it))

    def test_d10_3_a_property_systemd_did_not_print_is_could_not_check(self):
        self._units()
        self.outputs[("systemctl", "show", "hermes-app-broker@ads-audit")] = (0, "User=hermes-app-ads-audit\n", "")
        self.outputs[("systemctl", "show", "hermes-app-runner@ads-audit")] = (0, 'Environment="unbalanced\n', "")
        d = self._item("D10.3")["data"]["apps"]["ads-audit"]
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
        self.assertEqual(it["data"]["apps"]["ads-audit"]["runner_path_active"], "inactive")

    def test_d10_3_sudo_that_gave_neither_answer_is_could_not_check(self):
        self._units()
        for rc, out in ((127, ""), (1, "sudo: unknown user hermes-app-ads-audit\n"), (0, ""),
                        (0, "L'utilisateur hermes-app-ads-audit n'est pas autorisé\n")):
            with self.subTest(rc=rc, out=out):
                self.outputs[("sudo", "-l", "-U")] = (rc, out, "")
                it = self._item("D10.3")
                self.assertEqual(it["status"], R.OBSERVED)
                self.assertEqual(it["data"]["apps"]["ads-audit"]["sudo_rules"],
                                 {"rc": rc, "not_allowed": R.COULD_NOT_CHECK, "command_lines": R.COULD_NOT_CHECK})

    def test_d10_3_a_missing_app_user_costs_only_the_groups(self):
        self._units()
        self.outputs[("id", "-nG")] = (1, "", "id: 'hermes-app-ads-audit': no such user\n")
        it = self._item("D10.3")
        self.assertEqual(it["status"], R.OBSERVED)
        self.assertEqual(it["data"]["apps"]["ads-audit"]["broker_user_groups"], R.COULD_NOT_CHECK)
        self.assertEqual(it["data"]["apps"]["ads-audit"]["broker_unit"]["User"], "hermes-app-ads-audit")
        self.assertEqual(it["data"]["apps"]["ads-audit"]["runner_path_active"], "active")
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
        self.assertEqual([c.kwargs["layout"] for c in sr.call_args_list], [CE.HL.app_layout(a) for a in APPS])
        self.assertTrue(any("app-state" in p for p in it["data"]["apps"]["ads-audit"]["layout_problems"]))   # nothing built here
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

    def test_d10_4_a_layout_refusal_costs_each_job_its_layout_and_the_item_stays_observed(self):
        # Per job since the collector checks every job: the item stays observed, the containers are still counted.
        self._containers({"c1": (0, json.dumps([{"Type": "bind", "Source": "/var/lib/hermes/app-state"}]), "")})
        with mock.patch.object(CE.HL, "system_resolver", side_effect=CE.HL.LayoutError("group 'hermes' is gid 5")):
            it = self._item("D10.4")
        self.assertEqual(it["status"], R.OBSERVED)
        self.assertEqual(it["data"]["apps"], {a: {"layout_problems": R.COULD_NOT_CHECK, "layout_reason": "host-layout", **BOTH}
                                              for a in APPS})
        self.assertEqual((it["data"]["containers"], it["data"]["containers_mounting_app_state"]), (1, 1))
        self.assertNotIn("gid 5", json.dumps(it))

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
                 "  ads_report:\n"
                 "    command: python3\n"
                 "    args:\n"
                 "      - /opt/cc-bin/hermes-app-mcp.py\n"
                 "      - --app\n"
                 "      - ads-report\n"
                 "    env: {}\n"
                 "    timeout: 360\n"
                 "    tools:\n"
                 "      include:\n"
                 "        - ads_report_run\n"
                 "        - ads_report_status\n"
                 "        - ads_report_list\n"
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
        for name in ("HERMES_DASHBOARD_BASIC_AUTH_PASSWORD", "HERMES_DASHBOARD_BASIC_AUTH_PASSWORD_HASH",
                     "HERMES_DASHBOARD_BASIC_AUTH_SECRET"):
            self.outputs[("docker", "exec", GW_ID, "printenv", name)] = (1, "", "")

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
    HASH_NAME, SECRET_NAME = "HERMES_DASHBOARD_BASIC_AUTH_PASSWORD_HASH", "HERMES_DASHBOARD_BASIC_AUTH_SECRET"
    HEALTHY = _four({"openrouter-key": "matches-file", "dashboard-password": "unset"})

    def _printenv(self, openrouter, dash=NOT_SET, pw_hash=NOT_SET, secret=NOT_SET):
        """What the running gateway answers `printenv` for its four names (a string is the value
        it holds, a tuple is the (rc, out, err) itself), and enough for D4.1 to be observed.
        Every key is one whole command: none of these can answer for another."""
        for name, answer in ((self.OR_NAME, openrouter), (self.DASH_NAME, dash),
                             (self.HASH_NAME, pw_hash), (self.SECRET_NAME, secret)):
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
        self.assertEqual(self._secret_env(bundle), _four({"openrouter-key": "differs-from-file", "dashboard-password": "unset"}))
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
        self.assertEqual(list(d["secret_env"]), ["openrouter-key", "dashboard-password",
                                                 "dashboard-password-hash", "dashboard-session-secret"])
        self.assertEqual(set(d), {"paths", "google_ads_env_names", "anthropic_env_names", "openrouter_env_names",
                                  "secret_env", "listeners", "docker_dns_listeners"})
        self.assertEqual(d["openrouter_env_names"], ["OPENROUTER_API_KEY"])
        self.assertEqual(bundle["credentials"], [{"label": "openrouter-key", "sha12": R.sha12(self.OPENROUTER)}])
        self.assertEqual(bundle["items"]["D2.3"]["data"]["journal"], {"pattern_hits": 0, "known_secret_hits": 0})
        self.assertEqual(bundle["items"]["D10.6"]["data"]["gateway_mcp_list"], ["ads_audit  3 tools"])
        # The gateway is asked once for each name in the whole run, and never through a shell.
        self.assertEqual(self._printenv_calls(h), [["docker", "exec", GW_ID, "printenv", name] for name in
                                                   (self.OR_NAME, self.DASH_NAME, self.HASH_NAME, self.SECRET_NAME)])
        rc, out, err = self._main(self.host(), "--fp-key-tty")
        self.assertEqual((rc, err), (0, ""))
        self.assertEqual(json.loads(out)["items"]["D4.1"]["data"]["secret_env"], self.HEALTHY)
        self.assertNotIn(self.OPENROUTER, out)

    def test_with_the_dashboard_on_both_values_match_the_file(self):
        self._box(f"OPENROUTER_API_KEY={self.OPENROUTER}\nHERMES_DASHBOARD=1\n"
                  f"HERMES_DASHBOARD_BASIC_AUTH_PASSWORD={self.DASH}\n", self.OPENROUTER, dash=self.DASH)
        bundle, secrets = CE.collect_with_secrets(self.host(), self.KEY)
        self.assertEqual(self._secret_env(bundle), _four({"openrouter-key": "matches-file", "dashboard-password": "matches-file"}))
        self.assertEqual(secrets, [self.OPENROUTER, self.DASH])
        rc, out, err = self._main(self.host(), "--fp-key-tty")
        self.assertEqual((rc, err), (0, ""))
        for value in (self.OPENROUTER, self.DASH):
            self.assertNotIn(value, out)

    def test_a_file_edited_after_the_gateway_started_makes_both_keys_known(self):
        self._box(f"OPENROUTER_API_KEY={self.OPENROUTER}\n", self.OLD_OPENROUTER, leaked=self.OLD_OPENROUTER)
        bundle, secrets = CE.collect_with_secrets(self.host(), self.KEY)
        self.assertEqual(self._secret_env(bundle), _four({"openrouter-key": "differs-from-file", "dashboard-password": "unset"}))
        self.assertEqual(secrets, [self.OPENROUTER, self.OLD_OPENROUTER])
        self.assertEqual(bundle["items"]["D2.3"]["data"]["journal"]["known_secret_hits"], 1)
        self.assertEqual(bundle["credentials"], [{"label": "openrouter-key", "sha12": R.sha12(self.OPENROUTER)}])
        rc, out, err = self._main(self.host(), "--fp-key-tty")
        self.assertIsInstance(rc, RuntimeError)
        self.assertEqual(out + err, "")

    def test_a_password_the_gateway_holds_and_the_file_does_not_is_a_known_secret(self):
        self._box(f"OPENROUTER_API_KEY={self.OPENROUTER}\n", self.OPENROUTER, dash=self.DASH, leaked=self.DASH)
        bundle, secrets = CE.collect_with_secrets(self.host(), self.KEY)
        self.assertEqual(self._secret_env(bundle), _four({"openrouter-key": "matches-file", "dashboard-password": "differs-from-file"}))
        self.assertEqual(secrets, [self.OPENROUTER, self.DASH])
        self.assertEqual(bundle["items"]["D2.3"]["data"]["journal"]["known_secret_hits"], 1)

    def test_a_gateway_env_that_cannot_be_read_never_matches(self):
        self._box("", self.OPENROUTER, leaked=self.OPENROUTER)
        os.remove(os.path.join(self.root, self.GATEWAY_ENV.lstrip("/")))
        os.mkdir(os.path.join(self.root, self.GATEWAY_ENV.lstrip("/")))    # open() raises whoever asks
        self.outputs[("find",)] = (0, "", "")
        states, values = CE.gateway_secret_env(self.host())
        self.assertEqual((states, values), (_four({"openrouter-key": "differs-from-file", "dashboard-password": "unset"}),
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
                (self.OPENROUTER, failed, _four({"openrouter-key": "matches-file", "dashboard-password": R.COULD_NOT_CHECK}),
                 [self.OPENROUTER]),
                (failed, self.DASH, _four({"openrouter-key": R.COULD_NOT_CHECK, "dashboard-password": "differs-from-file"}),
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
        # The two names that failed are not measured; the two that answered "not set" are.
        self.assertEqual(self._secret_env(bundle), _four({"openrouter-key": R.COULD_NOT_CHECK, "dashboard-password": R.COULD_NOT_CHECK}))
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
                                 (_four({"openrouter-key": state, "dashboard-password": "unset"}), values))

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
                want = _four({"openrouter-key": R.COULD_NOT_CHECK, "dashboard-password": "differs-from-file"})
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
        self.assertEqual(d["secret_env"], _four({"openrouter-key": "differs-from-file", "dashboard-password": "differs-from-file"}))
        self.assertEqual(ctx["secrets"], [self.OPENROUTER, self.DASH])
        self.assertEqual(len(self._printenv_calls(h)), 4)                # one for each name the file may hold
        CE.d4_1(h, ctx)                                                  # a second item in the same run does not ask again
        self.assertEqual(len(self._printenv_calls(h)), 4)
        self.assertEqual(ctx["secrets"], [self.OPENROUTER, self.DASH])

    def test_d4_1_reports_a_state_for_each_label_when_the_gateway_could_not_be_asked(self):
        """The run found no gateway when it asked for the values, and D4.1 finds one a moment
        later: every label is could-not-check, and the gateway is not asked a second time."""
        self._box(f"OPENROUTER_API_KEY={self.OPENROUTER}\n", self.OPENROUTER)
        h, ctx = self.host(), {"secret_env": R.COULD_NOT_CHECK}
        self.assertEqual(CE.d4_1(h, ctx)["secret_env"],
                         _four({"openrouter-key": R.COULD_NOT_CHECK, "dashboard-password": R.COULD_NOT_CHECK}, R.COULD_NOT_CHECK))
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
        both = _four({"openrouter-key": "differs-from-file", "dashboard-password": "unset"})
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
        d = self._item("D10.7")["data"]["apps"]["ads-audit"]
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
        d = self._item("D10.7")["data"]["apps"]["ads-audit"]
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
        self.assertEqual(it["data"]["apps"]["ads-audit"]["journal_counts"], {"?/quota": 1, "ok/?": 1})
        self.assertEqual(it["data"]["apps"]["ads-audit"]["other_lines"], 1)
        self.assertNotIn("weird-host-name", json.dumps(it)); self.assertNotIn("some-free-text", json.dumps(it))

    def test_d10_7_counts_credential_text_and_customer_id_lines_never_the_lines(self):
        self._journal(broker=BROKER + "request=x op=run client=acme-dental status=ok reason=-\n"
                             f"oops GOOGLE_ADS_REFRESH_TOKEN={TOKEN}\n"
                             "customer 123-456-7890 failed\ncustomer 1234567890 failed\ncustomer 9999999999 is not ours\n")
        it = self._item("D10.7")
        a = it["data"]["apps"]["ads-audit"]
        self.assertEqual(a["broker_journal"], {"credential_text_lines": 1, "customer_id_lines": 2,
                                               "pattern_hits": 1, "known_secret_hits": 1})
        self.assertEqual(a["runner_journal"], {"credential_text_lines": 0, "customer_id_lines": 0,
                                               "pattern_hits": 0, "known_secret_hits": 0})
        self.assertEqual(a["other_lines"], 4)
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
        d = b["items"]["D10.7"]["data"]["apps"]["ads-audit"]
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
        d = b["items"]["D10.7"]["data"]["apps"]["ads-audit"]
        self.assertEqual(d["runner_journal"], {"credential_text_lines": 0,          # not Google-shaped text:
                                               "customer_id_lines": 0, "pattern_hits": 0,
                                               "known_secret_hits": 3})             # only the known value finds it
        self.assertEqual(d["broker_journal"]["known_secret_hits"], 0)
        self.assertEqual(b["items"]["D10.7"]["data"]["known_secrets_checked"], 2)                             # the token and the client secret
        self.assertNotIn(self.CLIENT_SECRET, json.dumps(b))

    def test_d10_7_broker_journal_installed_secret_value_is_counted_under_the_broker_key(self):
        self._install_client_secret()
        self._journal(broker=f"Traceback: {self.CLIENT_SECRET}\n")
        d = self._item("D10.7")["data"]["apps"]["ads-audit"]
        self.assertEqual((d["broker_journal"]["known_secret_hits"], d["runner_journal"]["known_secret_hits"]), (1, 0))

    def test_d10_7_counts_a_customer_id_in_the_runner_s_command_line_field(self):
        self._journal(runner=_e(MESSAGE="Audit complete.", _CMDLINE="python3 tool --customer 1234567890",
                                __REALTIME_TIMESTAMP="1761234567890123"))
        d = self._item("D10.7")["data"]["apps"]["ads-audit"]
        self.assertEqual(d["runner_journal"]["customer_id_lines"], 1)
        self.assertEqual(d["journal_read"]["runner"], {"entries": 1, "fields": 3, "undecodable_characters": 0})
        self.assertEqual(set(d["journal_read"]), {"broker", "runner"})

    def test_d10_7_reads_each_unit_with_every_field(self):
        host = self.host()
        CE.collect(host, self.KEY)
        calls = [c for c in host.calls if c[:2] == ["journalctl", "-u"] and "--all" in c]
        self.assertEqual([c[3:] for c in calls], [["--since", "-30d", "-o", "json", "--all", "--no-pager", "-q"]] * 4)   # two jobs

    def test_d10_7_reads_both_units_over_the_same_window(self):
        host = self.host()
        CE.collect(host, self.KEY)
        calls = [c for c in host.calls if c[:2] == ["journalctl", "-u"]]
        self.assertEqual([c[2] for c in calls], ["hermes-app-broker@ads-audit", "hermes-app-runner@ads-audit",
                                                 "hermes-app-broker@ads-report", "hermes-app-runner@ads-report"])
        self.assertEqual({tuple(c[3:]) for c in calls}, {tuple(calls[0][3:])})
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
    def test_d10_8_could_not_check_when_a_description_file_does_not_load(self):
        man = os.path.join(self.root, CE.AGENT_DIR.lstrip("/"), "registry", "apps", "ads-audit.json")
        old_shape = {"app": "ads-audit", "user": "hermes-app-ads-audit", "command": "/usr/local/sbin/run-client-audit",
                     "ops": {}, "tools": {}, "wait_seconds": {}}
        for name, write in (("old shape", lambda: json.dump(old_shape, open(man, "w"))),
                            ("not an object", lambda: open(man, "w").write("5"))):
            shutil.copy(os.path.join(os.path.dirname(HERE), "registry", "apps", "ads-audit.json"), man)
            write()
            with self.subTest(name=name):
                bundle = CE.collect(self.host(), self.KEY)
                it = bundle["items"]["D10.8"]
                self.assertEqual(it["status"], R.COULD_NOT_CHECK)
                self.assertEqual(it["reason"], "CouldNotCheck: the jobs' description files could not all be loaded")
                self.assertNotIn("ads-audit.json", json.dumps(bundle))

    def test_d10_8_a_job_without_a_description_file_is_observed_and_its_results_are_not_judged(self):
        # Missing, with the job still known to systemd: its results have no rule to be judged by.
        os.unlink(os.path.join(self.root, CE.AGENT_DIR.lstrip("/"), "registry", "apps", "ads-audit.json"))
        bundle = CE.collect(self.host(), self.KEY)
        it = bundle["items"]["D10.8"]
        self.assertEqual(it["status"], R.OBSERVED)
        self.assertEqual(it["data"]["apps"]["ads-audit"], {"results": R.COULD_NOT_CHECK, "out_of_whitelist": R.COULD_NOT_CHECK,
                                                           "declared": False, "installed": True})
        self.assertNotIn("ads-audit.json", json.dumps(bundle))

    def test_d10_8_flags_out_of_whitelist_results(self):
        d = self._item("D10.8")["data"]["apps"]["ads-audit"]
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
        d = self._item("D10.8")["data"]["apps"]["ads-audit"]
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
                    d = CE.d10_8(host, {})["apps"]["ads-audit"]
                    self.assertEqual((len(d["results"]), d["out_of_whitelist"]), (3, 2))
                    self.assertIs(d["results"][2]["values_ok"], False)

    def test_d10_8_a_raise_from_the_whitelist_check_costs_one_row_never_the_item(self):
        real = CE.A.result_in_whitelist

        def flaky(obj, manifest):
            if obj["request_id"] == RID_A:
                raise RecursionError("maximum recursion depth exceeded")
            return real(obj, manifest)
        with mock.patch.object(CE.A, "result_in_whitelist", side_effect=flaky):
            it = self._item("D10.8")
        self.assertEqual(it["status"], R.OBSERVED)
        self.assertEqual(it["data"]["apps"]["ads-audit"], {**BOTH, "out_of_whitelist": 2, "results": [
            {"keys_ok": False, "values_ok": False},
            {"op": "run", "status": "ok", "reason": "?", "keys_ok": True, "values_ok": False}]})

    def test_d10_8_rows_never_carry_a_slug_a_request_id_or_free_text(self):
        self._result(dict(self.good, request_id=RID_C, client="other-client", reason="leaked 1234567890"))
        out = json.dumps(self._item("D10.8"))
        for leak in ("acme-dental", "other-client", RID_A, RID_B, RID_C, "leaked", "free text"):
            self.assertNotIn(leak, out)

    def test_d10_8_a_result_under_another_file_name_is_out_of_whitelist(self):
        self._result(self.good, RID_C + ".json")                           # a copy: its id is RID_A
        d = self._item("D10.8")["data"]["apps"]["ads-audit"]
        self.assertEqual(d["out_of_whitelist"], 2)
        self.assertEqual(d["results"][2], {"op": "run", "status": "ok", "reason": "-", "keys_ok": True, "values_ok": False})

    def test_d10_8_every_result_the_broker_writes_is_in_whitelist(self):
        for n in os.listdir(self.res):
            os.remove(os.path.join(self.res, n))
        self._result(CE.A.refused_result(RID_A, None, None, "bad_request"))
        self._result(CE.A.refused_result(RID_B, "list", "acme-dental", "interrupted", status="failed"))
        d = self._item("D10.8")["data"]["apps"]["ads-audit"]
        self.assertEqual(d, {**BOTH, "out_of_whitelist": 0, "results": [
            {"op": "-", "status": "refused", "reason": "bad_request", "keys_ok": True, "values_ok": True},
            {"op": "list", "status": "failed", "reason": "interrupted", "keys_ok": True, "values_ok": True}]})

    def test_d10_8_a_missing_results_dir_is_could_not_check_for_that_job_alone(self):
        # For that job alone: the item stays observed and the other job is judged as usual.
        import shutil
        shutil.rmtree(self.res)
        self._result(CE.A.refused_result(RID_A, None, None, "bad_request"), app="ads-report")
        it = self._item("D10.8")
        self.assertEqual(it["status"], R.OBSERVED)
        self.assertEqual(it["data"]["apps"]["ads-audit"], {"results": R.COULD_NOT_CHECK, "out_of_whitelist": R.COULD_NOT_CHECK, **BOTH})
        self.assertEqual(it["data"]["apps"]["ads-report"], {**BOTH, "out_of_whitelist": 0, "results": [
            {"op": "-", "status": "refused", "reason": "bad_request", "keys_ok": True, "values_ok": True}]})

    def test_a_declared_job_that_is_not_installed_leaves_the_four_job_items_observed(self):
        """Between the pull and the job's installation: no account, no units, no spool, no journal."""
        self._units()
        self.outputs[("systemctl", "list-units")] = (0, "hermes-app-broker@ads-audit.service loaded active running x\n"
                                                        "hermes-app-runner@ads-audit.path loaded active waiting x\n", "")
        # as systemd answers for an instance of an installed template that was never started: `show` exits 0
        # with every property (the template's values) and ActiveState=inactive, LoadState=loaded; list-units does
        # not list it; `is-active` says `inactive` and exits 3
        shown = self.outputs[("systemctl", "show", "hermes-app-broker@ads-report")][1]
        self.outputs[("systemctl", "show", "hermes-app-broker@ads-report")] = (
            0, shown.replace("ActiveState=active", "ActiveState=inactive") + "LoadState=loaded\n", "")
        self.outputs[("systemctl", "show", "hermes-app-runner@ads-report")] = (0, "Environment=\nLoadState=loaded\n", "")
        self.outputs[("systemctl", "is-active", "hermes-app-runner@ads-report.path")] = (3, "inactive\n", "")
        for cmd in (("id", "-nG"), ("sudo", "-l", "-U")):          # the audit's account answers, the other does not exist
            self.outputs[(*cmd, "hermes-app-ads-audit")] = self.outputs.pop(cmd)
            self.outputs[(*cmd, "hermes-app-ads-report")] = (1, "", "unknown user")
        shutil.rmtree(os.path.dirname(self._results_dir("ads-report")))
        for unit in ("broker", "runner"):                          # a unit that never logged: nothing, exit 0
            self.outputs[_oldest_key("-u", f"hermes-app-{unit}@ads-report")] = (0, "", "")
        self._containers({})
        CN = R.COULD_NOT_CHECK
        with self._resolver():                                     # resolves the audit's account only
            b = CE.collect(self.host(), self.KEY)["items"]
        self.assertEqual({i: b[i]["status"] for i in ("D10.3", "D10.4", "D10.7", "D10.8")},
                         dict.fromkeys(("D10.3", "D10.4", "D10.7", "D10.8"), R.OBSERVED))
        d3 = b["D10.3"]["data"]
        self.assertEqual((d3["declared_apps"], d3["installed_apps"]), (list(APPS), ["ads-audit"]))
        report = d3["apps"]["ads-report"]
        # installed: false is said in the entry itself, so `inactive`, no groups and no sudo answer are not
        # read as a fault of an installed job
        self.assertEqual((report["declared"], report["installed"]), (True, False))
        self.assertEqual({k: v for k, v in report.items() if k != "broker_unit"}, {
            "runner_unit": {"Environment": [], "EnvironmentFiles": []},
            "drop_in_paths": {u.replace("ads-audit", "ads-report"): [] for u in self.INSTANCES},
            "broker_user_groups": CN, "sudo_rules": {"rc": 1, "not_allowed": CN, "command_lines": CN},
            "runner_path_active": "inactive", "declared": True, "installed": False})
        self.assertEqual((report["broker_unit"]["ActiveState"], report["broker_unit"]["User"], report["broker_unit"]["NoNewPrivileges"]),
                         ("inactive", "hermes-app-ads-report", "yes"))
        self.assertNotIn(CN, report["broker_unit"].values())
        self.assertEqual((d3["on_disk_apps"], d3["units_not_counted"]), (["ads-audit"], 0))
        self.assertEqual((d3["apps"]["ads-audit"]["declared"], d3["apps"]["ads-audit"]["installed"]), (True, True))
        for iid in ("D10.4", "D10.7", "D10.8"):
            self.assertEqual((b[iid]["data"]["apps"]["ads-report"]["declared"], b[iid]["data"]["apps"]["ads-report"]["installed"]),
                             (True, False), iid)
        self.assertEqual(d3["apps"]["ads-audit"]["broker_unit"]["User"], "hermes-app-ads-audit")
        self.assertEqual(d3["apps"]["ads-audit"]["broker_user_groups"], ["hermes-app-ads-audit", "hermes"])
        d4 = b["D10.4"]["data"]
        # Never an empty list: what is missing is listed, or (a directory there whose account is not) could-not-check.
        self.assertTrue(d4["apps"]["ads-report"]["layout_problems"] == CN or
                        any("missing" in p for p in d4["apps"]["ads-report"]["layout_problems"]))
        self.assertIsInstance(d4["apps"]["ads-audit"]["layout_problems"], list)
        self.assertEqual(d4["containers"], 0)
        zero = dict.fromkeys(CE.LEAK_COUNTS, 0)
        read = {u: dict.fromkeys(CE.READ_COUNTS, 0) for u in ("broker", "runner")}
        self.assertEqual(b["D10.7"]["data"]["apps"]["ads-report"], {
            "journal_counts": {}, "note_counts": {}, "other_lines": 0, "broker_journal": zero, "runner_journal": zero,
            "journal_read": read, "oldest_entry_read": {"broker": None, "runner": None}, "first_entry": None,
            "installed_since_last_pass": None, "declared": True, "installed": False})
        self.assertEqual(b["D10.7"]["data"]["apps"]["ads-audit"]["journal_counts"], {"refused/quota": 1, "ok/-": 1})
        self.assertEqual(b["D10.8"]["data"]["apps"]["ads-report"], {"results": CN, "out_of_whitelist": CN,
                                                                    "declared": True, "installed": False})
        self.assertEqual(b["D10.8"]["data"]["apps"]["ads-audit"]["out_of_whitelist"], 1)

    def test_d10_items_survive_the_redactor_and_the_secret_check(self):
        out = json.dumps(CE.collect(self.host(), self.KEY))
        self.assertNotIn("acme-dental", out); self.assertNotIn("1234567890", out)


class TestEveryJob(JobBox):
    APPS = ["ads-audit", "ads-report"]

    def setUp(self):
        super().setUp()
        self.outputs[("systemctl", "show")] = (0, "", "")      # every unit answers, with no property

    def test_the_jobs_are_read_from_the_description_files_and_from_systemd(self):
        d = self._item("D10.3")["data"]
        self.assertEqual((d["declared_apps"], d["installed_apps"], sorted(d["apps"])), (self.APPS, self.APPS, self.APPS))
        for app in self.APPS:
            self.assertEqual(set(d["apps"][app]), {"broker_unit", "runner_unit", "drop_in_paths", "broker_user_groups",
                                                   "sudo_rules", "runner_path_active", "declared", "installed"})
        self.assertEqual(sorted(d["installed_equal_repo"]), sorted(CE.APP_UNITS))

    def test_a_job_installed_without_a_description_file_and_the_reverse_are_both_shown(self):
        os.unlink(os.path.join(self.root, "opt/hermes-agent/registry/apps/ads-report.json"))
        self.outputs[("systemctl", "list-units")] = (0, "hermes-app-broker@ads-audit.service loaded active running x\n"
                                                        "hermes-app-broker@ghost.service loaded active running x\n", "")
        d = self._item("D10.3")["data"]
        self.assertEqual((d["declared_apps"], d["installed_apps"]), (["ads-audit"], ["ads-audit", "ghost"]))
        self.assertEqual(sorted(d["apps"]), ["ads-audit", "ads-report", "ghost"])   # the undeclared one is still measured; so is
        self.assertEqual(d["apps"]["ads-report"]["declared"], False)                # the one that is only a spool directory

    def test_a_description_file_that_does_not_load_makes_the_job_items_could_not_check(self):
        open(os.path.join(self.root, "opt/hermes-agent/registry/apps/ads-report.json"), "w").write("{}")
        for iid in ("D10.3", "D10.4", "D10.7", "D10.8"):
            self.assertEqual(self._item(iid)["status"], R.COULD_NOT_CHECK, iid)

    def test_a_unit_name_that_is_not_a_job_s_is_not_an_app(self):
        self.outputs[("systemctl", "list-units")] = (0, "hermes-app-broker@Bad..Name.service loaded active running x\n"
                                                        "hermes-app-runner@ads-audit.path loaded active waiting x\n", "")
        self.assertEqual(self._item("D10.3")["data"]["installed_apps"], ["ads-audit"])

    def test_each_job_s_journal_is_searched_and_counted_on_its_own(self):
        self._journal(app="ads-report", broker="hermes-app-broker[ads-report]: request=1 op=run client=x status=ok reason=-\n",
                      runner=_e(MESSAGE="done", _CMDLINE="tool --customer 1234567890"))
        d = self._item("D10.7")["data"]
        self.assertEqual(sorted(d["apps"]), self.APPS)
        self.assertEqual(d["apps"]["ads-report"]["journal_counts"], {"ok/-": 1})
        self.assertEqual(d["apps"]["ads-report"]["runner_journal"]["customer_id_lines"], 1)
        self.assertEqual(d["apps"]["ads-audit"]["runner_journal"]["customer_id_lines"], 0)
        self.assertNotIn("1234567890", json.dumps(d))

    def test_a_broker_line_of_another_job_in_a_job_s_journal_is_not_its_count(self):
        self._journal(app="ads-report", broker="hermes-app-broker[ads-audit]: request=1 op=run client=x status=ok reason=-\n")
        a = self._item("D10.7")["data"]["apps"]["ads-report"]
        self.assertEqual((a["journal_counts"], a["other_lines"]), ({}, 1))

    def test_a_job_whose_first_entry_is_after_the_last_pass_is_marked_installed_since(self):
        self.outputs[_oldest_key("-u", "hermes-app-broker@ads-report")] = (0, _entry(1760500000), "")
        self.outputs[_oldest_key("-u", "hermes-app-broker@ads-audit")] = (0, _entry(1759000000), "")
        with mock.patch.object(CE, "LAST_PASS_COLLECTED_AT", "2025-10-10T00:00:00Z"):
            d = self._item("D10.7")["data"]["apps"]
        self.assertEqual((d["ads-report"]["installed_since_last_pass"], d["ads-audit"]["installed_since_last_pass"]), (True, False))
        self.assertRegex(d["ads-report"]["first_entry"], r"^2025-10-1\dT")
        self.assertIsNone(self._item("D10.7")["data"]["apps"]["ads-report"]["installed_since_last_pass"])   # no flag given

    def test_each_job_s_results_are_judged_by_its_own_rule(self):
        report_ok = {"request_id": "0" * 8 + "-0000-4000-8000-" + "0" * 12, "op": "run", "client": "acme-dental",
                     "status": "ok", "reason": None, "exit_code": 0, "ts": "2026-10-01_12-00-00",
                     "steps": [{"name": "store", "rc": 0, "seconds": 0.1}],
                     "vault_path": "/var/lib/hermes/report-archive/acme-dental/2026-10-01_12-00-00-report.md"}
        self._result(report_ok, app="ads-report")
        self._result(report_ok, app="ads-audit")                      # the same file in the audit's results is out of ITS rule
        d = self._item("D10.8")["data"]["apps"]
        self.assertEqual(d["ads-report"]["out_of_whitelist"], 0)
        self.assertEqual(d["ads-audit"]["out_of_whitelist"], 2)       # the report's result, and the fixture's one bad result

    def test_the_layout_is_checked_per_job(self):
        with self._audit_resolver():
            d = self._item("D10.4")["data"]
        self.assertEqual(sorted(d["apps"]), self.APPS)
        self.assertIn("containers_mounting_app_state", d)
        audit = d["apps"]["ads-audit"]
        self.assertTrue(any("app-state" in p for p in audit["layout_problems"]))        # nothing built here
        self.assertEqual({k: v for k, v in audit.items() if k != "layout_problems"},
                         {"layout_reason": None, "declared": True, "installed": True})

    def test_the_journal_reach_and_the_restart_items_name_every_job(self):
        b = CE.collect(self.host(), self.KEY)["items"]
        self.assertEqual(sorted(b["D2.4"]["data"]["oldest_entry"]["apps"]), self.APPS)
        self.assertEqual(set(b["D2.4"]["data"]["oldest_entry"]["apps"]["ads-report"]), {"broker", "runner"})
        for key in ("started_at", "started_after_last_pass", "files_newer_than_start", "files_checked"):
            for app in self.APPS:
                self.assertIn(f"hermes-app-broker@{app}", b["D4.6"]["data"][key], key)

    # ---- beyond the brief: the design points it states and its tests do not pin
    def test_a_job_s_layout_that_cannot_be_judged_costs_that_job_alone(self):
        with self._audit_resolver():                                            # the audit's account resolves, the report's does not
            it = self._item("D10.4")
        self.assertEqual(it["status"], R.OBSERVED)
        self.assertIsInstance(it["data"]["apps"]["ads-audit"]["layout_problems"], list)
        self.assertEqual(it["data"]["apps"]["ads-report"], {"layout_problems": R.COULD_NOT_CHECK, "layout_reason": "no-account", **BOTH})
        self.assertEqual((it["data"]["containers"], it["data"]["containers_not_inspected"]), (0, 0))
        with self._audit_resolver(**{"hermes-app-ads-report": 991}):            # control: with its account, it is judged
            self.assertIsInstance(self._item("D10.4")["data"]["apps"]["ads-report"]["layout_problems"], list)

    def test_a_job_without_a_results_directory_costs_that_job_alone(self):
        shutil.rmtree(self._results_dir("ads-report"))
        it = self._item("D10.8")
        self.assertEqual(it["status"], R.OBSERVED)
        self.assertEqual(it["data"]["apps"]["ads-report"], {"results": R.COULD_NOT_CHECK, "out_of_whitelist": R.COULD_NOT_CHECK, **BOTH})
        self.assertEqual((len(it["data"]["apps"]["ads-audit"]["results"]), it["data"]["apps"]["ads-audit"]["out_of_whitelist"]), (2, 1))
        os.makedirs(self._results_dir("ads-report"))                            # control: an empty directory is judged
        self.assertEqual(self._item("D10.8")["data"]["apps"]["ads-report"], {"results": [], "out_of_whitelist": 0, **BOTH})

    def test_an_installed_list_line_that_is_not_a_loaded_unit_of_a_job_is_not_installed(self):
        self.outputs[("systemctl", "list-units")] = (0, "\n● hermes-app-broker@ads-report.service not-found inactive dead x\n"
                                                        "0 loaded units listed.\nhermes-app-broker@ads-audit.socket loaded x\n"
                                                        "  hermes-app-runner@ads-audit.path loaded active waiting x\n", "")
        d = self._item("D10.3")["data"]
        self.assertEqual((d["installed_apps"], d["units_not_counted"]), (["ads-audit"], 3))

    def test_a_job_systemd_knows_without_a_description_file_is_measured_and_its_results_are_not_judged(self):
        self.outputs[("systemctl", "list-units")] = (0, "hermes-app-broker@ghost.service loaded active running x\n", "")
        self._journal(app="ghost", broker="hermes-app-broker[ghost]: request=1 op=run client=x status=ok reason=-\n", runner="")
        b = CE.collect(self.host(), self.KEY)["items"]
        self.assertEqual(b["D10.7"]["data"]["apps"]["ghost"]["journal_counts"], {"ok/-": 1})
        self.assertEqual(b["D10.8"]["data"]["apps"]["ghost"], {"results": R.COULD_NOT_CHECK, "out_of_whitelist": R.COULD_NOT_CHECK,
                                                               "declared": False, "installed": True})
        self.assertEqual(b["D10.8"]["data"]["apps"]["ads-audit"]["out_of_whitelist"], 1)     # the declared ones are still judged
        self.assertIn("ghost", b["D10.4"]["data"]["apps"])
        self.assertNotIn("ghost", b["D2.4"]["data"]["oldest_entry"]["apps"])                 # D2.4 and D4.6: declared jobs only
        self.assertEqual(b["D4.6"]["data"]["apps_declared"], self.APPS)

    def test_description_files_that_do_not_load_cost_the_reach_and_restart_items_their_per_job_part_only(self):
        self.outputs[_oldest_key()] = (0, _entry(int(time.time()) - 86400 * 3), "")
        self._w(CE.APPS_DIR + "/ads-report.json", "{}")
        b = CE.collect(self.host(), self.KEY)["items"]
        self.assertEqual((b["D2.4"]["status"], b["D4.6"]["status"]), (R.OBSERVED, R.OBSERVED))
        d24, d46 = b["D2.4"]["data"], b["D4.6"]["data"]
        self.assertEqual((d24["oldest_entry"]["apps"], d24["reach_days"]), (R.COULD_NOT_CHECK, 3))
        self.assertEqual(d46["apps_declared"], R.COULD_NOT_CHECK)
        # the brokers are then those systemd lists
        self.assertEqual(set(d46["started_at"]), set(CE.SERVICE_FILES) | set(CE.OTHER_STARTS) | {f"hermes-app-broker@{a}" for a in APPS})
        self.assertEqual(d46["apps_installed"], self.APPS)
        for iid in ("D10.3", "D10.4", "D10.7", "D10.8"):
            self.assertEqual(b[iid]["reason"], "CouldNotCheck: the jobs' description files could not all be loaded", iid)

    def test_a_job_that_never_logged_is_installed_since_and_an_unread_first_entry_is_could_not_check(self):
        self.outputs[_oldest_key("-u", "hermes-app-broker@ads-report")] = (0, "", "")
        self.outputs[_oldest_key("-u", "hermes-app-broker@ads-audit")] = (1, "", "Failed")
        with mock.patch.object(CE, "LAST_PASS_COLLECTED_AT", "2025-10-10T00:00:00Z"):
            d = self._item("D10.7")["data"]["apps"]
        self.assertEqual((d["ads-report"]["first_entry"], d["ads-report"]["installed_since_last_pass"]), (None, True))
        self.assertEqual((d["ads-audit"]["first_entry"], d["ads-audit"]["installed_since_last_pass"]),
                         (R.COULD_NOT_CHECK, R.COULD_NOT_CHECK))

    def test_systemd_not_answering_for_the_jobs_is_could_not_check_never_an_empty_list(self):
        self.outputs[("systemctl", "list-units")] = (1, "", "Failed to connect to bus")
        for iid in ("D10.3", "D10.4", "D10.7", "D10.8"):
            self.assertEqual(self._item(iid)["status"], R.COULD_NOT_CHECK, iid)

    # ---- fix round 1: a job is declared, installed or on disk, and each entry says which
    def _audit_resolver(self, **more):
        names = {"root": 0, "hermes": 10000, "hermes-app-ads-audit": 990, **more}
        return mock.patch.object(CE.HL, "system_resolver", return_value=CE.HL.Resolver(names, names))

    def test_a_unit_systemd_only_remembers_the_name_of_is_not_installed_and_is_counted(self):
        self.outputs[("systemctl", "list-units")] = (0, "hermes-app-broker@ads-audit.service loaded active running x\n"
                                                        "hermes-app-broker@ads-report.service not-found inactive dead x\n"
                                                        "hermes-app-runner@ads-report.path masked inactive dead x\n"
                                                        "hermes-app-broker@Bad..Name.service loaded active running x\n"
                                                        "hermes-app-broker@ads-audit.socket loaded active running x\n"
                                                        "hermes-app-runner@ads-audit.path\n"
                                                        "\n", "")
        d = self._item("D10.3")["data"]
        self.assertEqual((d["installed_apps"], d["units_not_counted"]), (["ads-audit"], 5))
        self.assertEqual((d["apps"]["ads-report"]["declared"], d["apps"]["ads-report"]["installed"]), (True, False))
        self.assertNotIn("Bad..Name", json.dumps(d))
        self.setUp(); self.outputs[("systemctl", "show")] = (0, "", "")
        self.assertEqual(self._item("D10.3")["data"]["units_not_counted"], 0)        # the healthy box

    def test_a_job_that_exists_only_as_a_spool_directory_is_listed_and_measured(self):
        os.makedirs(os.path.join(self.root, "var/lib/hermes/spool/apps/stopped/results"))
        os.makedirs(os.path.join(self.root, "var/lib/hermes/spool/apps/Bad..Name"))
        self._w("/var/lib/hermes/app-state/a-file", "x")
        os.symlink(self._results_dir("ads-audit"), os.path.join(self.root, "var/lib/hermes/app-state/linked"))
        os.makedirs(os.path.join(self.root, "var/lib/hermes/app-state/parked"))
        for app in ("stopped", "parked"):
            self._journal(app=app, broker="", runner="")
        b = CE.collect(self.host(), self.KEY)["items"]
        d = b["D10.3"]["data"]
        self.assertEqual((d["on_disk_apps"], d["on_disk_not_counted"]), (["ads-audit", "ads-report", "parked", "stopped"], 3))
        self.assertEqual((d["declared_apps"], d["installed_apps"]), (self.APPS, self.APPS))
        for iid in ("D10.3", "D10.4", "D10.7", "D10.8"):
            apps = b[iid]["data"]["apps"]
            self.assertEqual(sorted(apps), ["ads-audit", "ads-report", "parked", "stopped"], iid)
            self.assertEqual((apps["stopped"]["declared"], apps["stopped"]["installed"]), (False, False), iid)
        self.assertEqual(b["D10.8"]["data"]["apps"]["stopped"]["results"], R.COULD_NOT_CHECK)   # no rule to judge by
        self.assertNotIn("Bad..Name", json.dumps(b)); self.assertNotIn("a-file", json.dumps(b))

    def test_the_restart_item_covers_an_undeclared_running_broker_and_says_when_systemd_did_not_answer(self):
        self.outputs[("systemctl", "list-units")] = (0, "hermes-app-broker@ads-audit.service loaded active running x\n"
                                                        "hermes-app-broker@ghost.service loaded active running x\n", "")
        d = CE.collect(self.host(), self.KEY)["items"]["D4.6"]["data"]
        self.assertEqual((d["apps_declared"], d["apps_installed"]), (self.APPS, ["ads-audit", "ghost"]))
        want = {f"hermes-app-broker@{a}" for a in (*self.APPS, "ghost")}
        for key in ("started_at", "started_after_last_pass", "files_newer_than_start", "files_checked"):
            self.assertEqual({k for k in d[key] if k.startswith("hermes-app-broker@")}, want, key)
        self.outputs[("systemctl", "list-units")] = (1, "", "Failed to connect to bus")
        d = CE.collect(self.host(), self.KEY)["items"]["D4.6"]["data"]
        self.assertEqual((d["apps_declared"], d["apps_installed"]), (self.APPS, R.COULD_NOT_CHECK))
        self.assertEqual({k for k in d["started_at"] if k.startswith("hermes-app-broker@")},
                         {f"hermes-app-broker@{a}" for a in self.APPS})

    def test_every_per_job_entry_says_whether_the_job_is_declared_and_installed(self):
        os.unlink(os.path.join(self.root, "opt/hermes-agent/registry/apps/ads-report.json"))
        shutil.rmtree(os.path.dirname(self._results_dir("ads-report")))
        self._journal(app="ghost", broker="", runner="")
        self.outputs[("systemctl", "list-units")] = (0, "hermes-app-broker@ads-report.service loaded active running x\n"
                                                        "hermes-app-broker@ghost.service loaded active running x\n", "")
        b = CE.collect(self.host(), self.KEY)["items"]
        for iid in ("D10.3", "D10.4", "D10.7", "D10.8"):
            self.assertEqual({a: (e["declared"], e["installed"]) for a, e in b[iid]["data"]["apps"].items()},
                             {"ads-audit": (True, False), "ads-report": (False, True), "ghost": (False, True)}, iid)

    def test_a_layout_that_cannot_be_checked_says_which_kind_of_refusal(self):
        CN = R.COULD_NOT_CHECK
        with self._audit_resolver():                                    # the report's own account does not resolve
            d = self._item("D10.4")["data"]["apps"]
        self.assertEqual((d["ads-report"]["layout_problems"], d["ads-report"]["layout_reason"]), (CN, "no-account"))
        self.assertIsInstance(d["ads-audit"]["layout_problems"], list)
        self.assertIsNone(d["ads-audit"]["layout_reason"])
        names = {"root": 0, "hermes-app-ads-audit": 990, "hermes-app-ads-report": 991}      # the shared group does not
        with mock.patch.object(CE.HL, "system_resolver", return_value=CE.HL.Resolver(names, names)):
            d = self._item("D10.4")["data"]["apps"]
        self.assertEqual({a: (e["layout_problems"], e["layout_reason"]) for a, e in d.items()},
                         {a: (CN, "host-layout") for a in self.APPS})
        with mock.patch.object(CE.HL, "system_resolver", side_effect=CE.HL.LayoutError("group 'hermes' is gid 5")):
            it = self._item("D10.4")
        self.assertEqual({e["layout_reason"] for e in it["data"]["apps"].values()}, {"host-layout"})
        self.assertNotIn("gid 5", json.dumps(it))
        with self._audit_resolver(**{"hermes-app-ads-report": 991}), \
                mock.patch.object(CE.HL, "check_app", side_effect=CE.HL.LayoutError("something else")):
            it = self._item("D10.4")
        self.assertEqual({e["layout_reason"] for e in it["data"]["apps"].values()}, {"other"})
        self.assertNotIn("something else", json.dumps(it))

    def test_the_job_sets_are_computed_once_per_collection(self):
        host = self.host()
        CE.collect(host, self.KEY)
        self.assertEqual(len([c for c in host.calls if c[:2] == ["systemctl", "list-units"]]), 1)
        with mock.patch.object(CE.A, "load_manifests", wraps=CE.A.load_manifests) as lm:
            CE.collect(self.host(), self.KEY)
        self.assertEqual(lm.call_count, 1)

    def test_a_known_secret_in_the_second_job_s_journal_is_counted_under_that_job(self):
        self._journal(app="ads-report", runner=f"debug: token is {TOKEN}\n")
        b = CE.collect(self.host(), self.KEY)
        d = b["items"]["D10.7"]["data"]["apps"]
        self.assertEqual((d["ads-report"]["runner_journal"]["known_secret_hits"], d["ads-report"]["broker_journal"]["known_secret_hits"]), (1, 0))
        self.assertEqual((d["ads-audit"]["runner_journal"]["known_secret_hits"], d["ads-audit"]["broker_journal"]["known_secret_hits"]), (0, 0))
        self.assertNotIn(TOKEN, json.dumps(b))

    def test_no_constant_names_a_job(self):
        src = open(os.path.join(HERE, "collect-review-evidence.py")).read()
        code = "\n".join(l.split("#", 1)[0] for l in src.splitlines() if not l.lstrip().startswith(("#", '"""')))
        self.assertNotRegex(code, r'"ads-(audit|report)"')
        for name in ("APP", "APP_USER", "APP_RESULTS", "JOURNAL_UNITS", "_BROKER_LINE"):
            self.assertFalse(hasattr(CE, name), name)


class TestRunReal(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.d, True)
        self.marker = os.path.join(self.d, "cleaned")

    def test_a_35_day_journal_passes_through_the_real_runner_whole(self):
        n = 5 * 4630823
        rc, out, err = CE._run_real([sys.executable, "-c", f"import sys; sys.stdout.write('x' * {n})"], timeout=120)
        self.assertEqual((rc, len(out), err), (0, n, ""))

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


class TestD45ListenerCheck(Base):
    """D4.5: the periodic listener check (F50) is live, and what it recorded."""
    STATE = "/var/lib/hermes/listener-check"
    NOW = "2026-10-07T12:10:00Z"
    OK_LAST = {"ts": "2026-10-07T12:00:00Z", "status": "ok", "reason": "-", "listeners": [9119],
               "unexpected": [], "docker_dns_listeners": 1}

    def _healthy(self):
        for u in CE.LISTENER_UNITS:
            self._w("/etc/systemd/system/" + u, "unit " + u)
            self._w(CE.CHECKOUT + "/infra/hermes-agent/deploy/" + u, "unit " + u)
            self.outputs[("systemctl", "show", u, "-p", "DropInPaths")] = (0, "DropInPaths=\n", "")
        self.outputs[("systemctl", "is-active", "hermes-listener-check.timer")] = (0, "active\n", "")
        self.outputs[("systemctl", "is-enabled", "hermes-listener-check.timer")] = (0, "enabled\n", "")
        self._w(self.STATE + "/last.json", json.dumps(self.OK_LAST))
        self._w(self.STATE + "/history.jsonl", json.dumps(self.OK_LAST) + "\n" + json.dumps(self.OK_LAST) + "\n")
        os.chmod(os.path.join(self.root, self.STATE.lstrip("/")), 0o700)

    def _d(self):
        with mock.patch.object(CE.R, "utc_now", return_value=self.NOW):
            return CE.d4_5(self.host(), {})

    def test_registered(self):
        self.assertIs(CE.PROBES["D4.5"], CE.d4_5)

    def test_a_healthy_box(self):
        self._healthy()
        self.assertEqual(self._d(), {
            "timer_active": "active", "timer_enabled": "enabled",
            "installed_equal_repo": {u: True for u in CE.LISTENER_UNITS},
            "drop_in_paths": {u: [] for u in CE.LISTENER_UNITS},
            "state_dir": {"owner": CE._owner(os.getuid()), "group": CE._group(os.stat(self.root).st_gid), "mode": "0o700"},
            "max_age_seconds": 2700, "last": self.OK_LAST, "last_age_seconds": 600,
            "alert_present": False, "alert": None, "history_counts": {"ok": 2},
            "alert_log": {"alert": 0, "alert-cleared": 0, "?": 0, "first_ts": None, "last_ts": None}})

    def test_a_stopped_or_disabled_timer_is_reported_as_its_state(self):
        self._healthy()
        self.outputs[("systemctl", "is-active", "hermes-listener-check.timer")] = (3, "inactive\n", "")
        self.outputs[("systemctl", "is-enabled", "hermes-listener-check.timer")] = (1, "disabled\n", "")
        d = self._d()
        self.assertEqual((d["timer_active"], d["timer_enabled"]), ("inactive", "disabled"))

    def test_no_answer_from_systemctl_is_could_not_check(self):
        self._healthy()
        del self.outputs[("systemctl", "is-active", "hermes-listener-check.timer")]     # 127, no output
        self.outputs[("systemctl", "is-enabled", "hermes-listener-check.timer")] = (1, "", "Failed to connect to bus")
        d = self._d()
        self.assertEqual((d["timer_active"], d["timer_enabled"]), ("could-not-check", "could-not-check"))

    def test_a_unit_that_differs_from_the_repo_or_is_not_installed(self):
        self._healthy()
        self._w("/etc/systemd/system/hermes-listener-check.service", "unit edited on the box")
        os.unlink(os.path.join(self.root, "etc/systemd/system/hermes-listener-check.timer"))
        self.assertEqual(self._d()["installed_equal_repo"],
                         {"hermes-listener-check.service": False, "hermes-listener-check.timer": False})

    def test_a_drop_in_is_listed(self):
        self._healthy()
        path = "/etc/systemd/system/hermes-listener-check.service.d/override.conf"
        self.outputs[("systemctl", "show", "hermes-listener-check.service", "-p", "DropInPaths")] = (
            0, f"DropInPaths={path}\n", "")
        self.assertEqual(self._d()["drop_in_paths"]["hermes-listener-check.service"], [path])

    def test_the_check_never_ran(self):
        self._healthy()
        shutil.rmtree(os.path.join(self.root, self.STATE.lstrip("/")))
        d = self._d()
        self.assertEqual((d["last"], d["last_age_seconds"], d["alert_present"], d["history_counts"]),
                         (None, None, False, {}))
        self.assertEqual(d["state_dir"], "absent")

    def test_the_state_directory_is_reported_as_it_is_and_never_followed(self):
        self._healthy()
        state = os.path.join(self.root, self.STATE.lstrip("/"))
        os.chmod(state, 0o755)
        self.assertEqual(self._d()["state_dir"]["mode"], "0o755")
        shutil.rmtree(state)
        os.symlink(self.root, state)
        d = self._d()
        self.assertEqual(d["state_dir"], "symlink")
        shutil.os.unlink(state)
        open(state, "w").close()
        d = self._d()                                                  # a file where the directory should be
        self.assertEqual((d["state_dir"], d["last"], d["alert_present"]), ("not-a-directory", "could-not-check", True))

    def test_a_stale_result_shows_its_age(self):
        self._healthy()
        self._w(self.STATE + "/last.json", json.dumps({**self.OK_LAST, "ts": "2026-10-07T10:00:00Z"}))
        self.assertEqual(self._d()["last_age_seconds"], 7800)

    def test_an_alert_is_reported_with_its_first_time_and_ports(self):
        self._healthy()
        alert = {"since": "2026-10-06T03:15:00Z", "reason": "unexpected-port", "unexpected": [8642],
                 "docker_dns_listeners": 1}
        self._w(self.STATE + "/ALERT", json.dumps(alert))
        bad = {**self.OK_LAST, "status": "alert", "reason": "unexpected-port", "listeners": [8642, 9119],
               "unexpected": [8642]}
        self._w(self.STATE + "/history.jsonl", "".join(json.dumps(e) + "\n" for e in (
            bad, self.OK_LAST, {"ts": "x", "status": "could-not-check"}, {"ts": "y", "status": "alert-cleared"})))
        self._w(self.STATE + "/alerts.jsonl", json.dumps({**bad, "ts": "2026-06-01T00:00:00Z"}) + "\n"
                + json.dumps({"ts": "2026-06-01T00:05:00Z", "status": "alert-cleared"}) + "\n" + json.dumps(bad) + "\n")
        d = self._d()
        self.assertEqual((d["alert_present"], d["alert"]), (True, alert))
        self.assertEqual(d["history_counts"], {"alert": 1, "ok": 1, "could-not-check": 1, "alert-cleared": 1})
        # The log is never trimmed: it still holds the alert of June, which the history has lost.
        self.assertEqual(d["alert_log"], {"alert": 2, "alert-cleared": 1, "?": 0,
                                          "first_ts": "2026-06-01T00:00:00Z", "last_ts": "2026-10-07T12:00:00Z"})

    def test_damaged_state_files_are_could_not_check_for_their_field_only(self):
        self._healthy()
        self._w(self.STATE + "/last.json", "{not json")
        self._w(self.STATE + "/ALERT", "[1, 2]")
        self._w(self.STATE + "/history.jsonl", "not json\n" + json.dumps(self.OK_LAST) + "\n[]\n")
        d = self._d()
        self.assertEqual((d["last"], d["last_age_seconds"], d["alert_present"], d["alert"]),
                         ("could-not-check", "could-not-check", True, "could-not-check"))
        self.assertEqual(d["history_counts"], {"?": 2, "ok": 1})
        self.assertEqual(d["timer_active"], "active")                              # the rest still stands

    def test_it_is_in_the_bundle_and_carries_no_address(self):
        self._healthy()
        with mock.patch.object(CE.R, "utc_now", return_value=self.NOW):
            item = CE.collect(self.host(), self.KEY)["items"]["D4.5"]
        self.assertEqual(item["status"], "observed")
        self.assertEqual(item["data"]["last"]["listeners"], [9119])
        self.assertNotIn("0B00007F", json.dumps(item))


class TestDashboardHashAndSessionSecret(Base):
    """Checklist v1.17: the gateway `.env` may hold the dashboard password as a scrypt hash (F47),
    written single-quoted because Compose interpolates `$` (F52), and a session-signing secret."""
    # HASH is synthetic: its salt and hash decode to "not-a-real-salt!" and "not-a-real-scrypt-hash-…".
    GATEWAY_ENV = CE.GATEWAY_ENV_FILE
    OPENROUTER = "sk-or-v1-NOT-A-REAL-KEY-0123456789abcdef"
    HASH = "scrypt$16384$8$1$bm90LWEtcmVhbC1zYWx0IQ==$bm90LWEtcmVhbC1zY3J5cHQtaGFzaC0wMTIzNDU2Nzg="
    SECRET = "c2Vzc2lvbi1zaWduaW5nLXNlY3JldC1ub3QtcmVhbC0wMTIzNA=="
    GW = "a" * 64
    NAMES = ("OPENROUTER_API_KEY", "HERMES_DASHBOARD_BASIC_AUTH_PASSWORD",
             "HERMES_DASHBOARD_BASIC_AUTH_PASSWORD_HASH", "HERMES_DASHBOARD_BASIC_AUTH_SECRET")

    def _box(self, env_text, held):
        """A gateway .env of this text, and a running gateway holding `held` ({name: value})."""
        self._w(self.GATEWAY_ENV, env_text)
        self.outputs[("find",)] = (0, self.GATEWAY_ENV + "\n", "")
        self.outputs[("docker", "ps")] = (0, self.GW + "\n", "")
        for name in self.NAMES:
            self.outputs[("docker", "exec", self.GW, "printenv", name)] = \
                (0, held[name] + "\n", "") if name in held else (1, "", "")
        self.outputs[("docker", "exec", self.GW, "sh", "-c")] = (0, "/opt/governance absent\n", "")
        self.outputs[("docker", "exec", self.GW, "env")] = (0, "HOME=/x\n", "")

    def _new_form(self, hash_line=None):
        hash_line = hash_line or f"HERMES_DASHBOARD_BASIC_AUTH_PASSWORD_HASH='{self.HASH}'"
        self._box(f"OPENROUTER_API_KEY={self.OPENROUTER}\nHERMES_DASHBOARD=1\n"
                  f"HERMES_DASHBOARD_BASIC_AUTH_USERNAME=hermesadmin\n{hash_line}\n"
                  f"HERMES_DASHBOARD_BASIC_AUTH_SECRET={self.SECRET}\n",
                  {"OPENROUTER_API_KEY": self.OPENROUTER,
                   "HERMES_DASHBOARD_BASIC_AUTH_PASSWORD_HASH": self.HASH,
                   "HERMES_DASHBOARD_BASIC_AUTH_SECRET": self.SECRET})

    def _row(self, bundle):
        return next(r for r in bundle["items"]["D2.1"]["data"]["files"] if r.get("label") == "gateway-env")

    def test_the_new_form_is_held_matches_the_file_and_no_value_is_printed(self):
        self._new_form()
        bundle, secrets = CE.collect_with_secrets(self.host(), self.KEY)
        row = self._row(bundle)
        self.assertEqual(row["secrets_held"], ["openrouter-key", "dashboard-password-hash", "dashboard-session-secret"])
        self.assertEqual(row["secrets_not_searchable"], [])
        self.assertEqual(bundle["items"]["D4.1"]["data"]["secret_env"],
                         {"openrouter-key": "matches-file", "dashboard-password": "unset",
                          "dashboard-password-hash": "matches-file", "dashboard-session-secret": "matches-file"})
        for value in (self.HASH, self.SECRET, self.OPENROUTER):
            self.assertIn(value, secrets)                               # a known secret for the leak checks
            self.assertNotIn(value, json.dumps(bundle))
        self.assertNotIn("bm90LW", json.dumps(bundle))                  # nor a piece of the hash

    def test_the_hash_has_no_fingerprint_and_the_random_secret_has_one(self):
        self._new_form()
        rows = {r["label"]: r["sha12"] for r in CE.collect(self.host(), self.KEY)["credentials"]}
        self.assertEqual(rows, {"openrouter-key": R.sha12(self.OPENROUTER), "dashboard-password-hash": None,
                                "dashboard-session-secret": R.sha12(self.SECRET)})

    def test_a_hash_written_bare_is_seen_as_differing_from_what_the_gateway_holds(self):
        """F52, on a box where it happened: the file holds the whole hash, bare; Compose gave the
        gateway a truncated one. The review must not say `matches-file`."""
        truncated = "scrypt$16384$8$1" + self.HASH.split("$")[4][2:]
        self._new_form(hash_line=f"HERMES_DASHBOARD_BASIC_AUTH_PASSWORD_HASH={self.HASH}")
        self.outputs[("docker", "exec", self.GW, "printenv", self.NAMES[2])] = (0, truncated + "\n", "")
        bundle, secrets = CE.collect_with_secrets(self.host(), self.KEY)
        self.assertEqual(bundle["items"]["D4.1"]["data"]["secret_env"]["dashboard-password-hash"], "differs-from-file")
        self.assertIn(truncated, secrets)                               # what the gateway really holds is searched for too
        self.assertNotIn(truncated, json.dumps(bundle))

    def test_a_dollar_escaped_hash_does_not_match_so_single_quotes_are_the_one_form(self):
        self._new_form(hash_line="HERMES_DASHBOARD_BASIC_AUTH_PASSWORD_HASH=" + self.HASH.replace("$", "$$"))
        d = CE.d4_1(self.host(), {})
        self.assertEqual(d["secret_env"]["dashboard-password-hash"], "differs-from-file")

    def test_plaintext_and_hash_together_are_both_named(self):
        """The plaintext wins upstream, so the hash does nothing: D2.1's pass rule fails it, and
        the collector's part is to name both."""
        self._box(f"OPENROUTER_API_KEY={self.OPENROUTER}\nHERMES_DASHBOARD_BASIC_AUTH_PASSWORD=NOT-A-REAL-PASSWORD-0123\n"
                  f"HERMES_DASHBOARD_BASIC_AUTH_PASSWORD_HASH='{self.HASH}'\n", {"OPENROUTER_API_KEY": self.OPENROUTER})
        row = self._row(CE.collect(self.host(), self.KEY))
        self.assertEqual(row["secrets_held"], ["openrouter-key", "dashboard-password", "dashboard-password-hash"])

    def test_a_leaked_session_secret_is_counted_in_the_journal(self):
        self._new_form()
        self.outputs[("journalctl",)] = (0, f"debug: signing with {self.SECRET}\n", "")
        bundle = CE.collect(self.host(), self.KEY)
        self.assertEqual(bundle["items"]["D2.3"]["data"]["journal"]["known_secret_hits"], 1)
        self.assertNotIn(self.SECRET, json.dumps(bundle))


TUNNEL_OPTS = 'restrict,port-forwarding,permitopen="127.0.0.1:9119",permitlisten="127.0.0.1:1",command="/bin/false"'


def _keybody(seed):
    """A well-formed ed25519 public key body (test value: 32 equal bytes)."""
    return base64.b64encode(b"\x00\x00\x00\x0bssh-ed25519\x00\x00\x00 " + bytes([seed]) * 32).decode()


class TestD17AcceptedKeys(Base):
    SSHD = ("authorizedkeysfile .ssh/authorized_keys .ssh/authorized_keys2\nauthorizedkeyscommand none\n"
            "authorizedprincipalsfile none\ntrustedusercakeys none\nallowtcpforwarding yes\n"
            "allowstreamlocalforwarding yes\ngatewayports no\npermittunnel no\npermitrootlogin no\n")
    PASSWD = ("root:x:0:0:root:/root:/bin/bash\n"
              "hermesops:x:1000:1000::/home/hermesops:/bin/bash\n"
              "hermes-broker:x:997:997::/var/lib/hermes-broker:/usr/sbin/nologin\n"
              "daemon:x:1:1:daemon:/usr/sbin:/usr/sbin/nologin\n"
              "bin:x:2:2:bin:/usr/sbin:/usr/sbin/nologin\n")

    def setUp(self):
        super().setUp()
        self._w("/etc/passwd", self.PASSWD)
        self.outputs[("sshd", "-T")] = (0, self.SSHD, "")

    def _keys(self, home, body):
        p = self._w(home + "/.ssh/authorized_keys", body)
        os.chmod(p, 0o600)
        return p

    def _two(self):
        self._keys("/home/hermesops", f"ssh-ed25519 {_keybody(1)} operator@laptop.example\n"
                                      f"{TUNNEL_OPTS} ssh-ed25519 {_keybody(2)} hermes-box-tunnel\n")

    def test_two_keys_one_bare_one_limited(self):
        self._two()
        d = CE.d1_7(self.host(), {})
        self.assertEqual(d["accounts_checked"], 5)
        self.assertEqual(len(d["files"]), 1)
        row = d["files"][0]
        self.assertEqual((row["path"], row["users"], row["kind"], row["mode"], row["unparsed_lines"]),
                         ("/home/hermesops/.ssh/authorized_keys", ["hermesops"], "file", "0o600", 0))
        self.assertEqual(row["keys"][0], {"type": "ssh-ed25519", "options": [],
                                          "sha12": hashlib.sha256(base64.b64decode(_keybody(1))).hexdigest()[:12]})
        self.assertEqual(row["keys"][1]["options"],
                         ['command="/bin/false"', 'permitlisten="127.0.0.1:1"', 'permitopen="127.0.0.1:9119"',
                          "port-forwarding", "restrict"])
        self.assertNotEqual(row["keys"][0]["sha12"], row["keys"][1]["sha12"])

    def test_no_key_body_and_no_comment_leave_the_collector(self):
        self._two()
        out = json.dumps(CE.d1_7(self.host(), {}))
        for gone in (_keybody(1), _keybody(2), "laptop.example", "operator@", "hermes-box-tunnel"):
            self.assertNotIn(gone, out)

    def test_the_sshd_settings_that_accept_keys_or_forwards_are_reported(self):
        d = CE.d1_7(self.host(), {})
        self.assertEqual(d["sshd"], {"authorizedkeysfile": ".ssh/authorized_keys .ssh/authorized_keys2",
                                     "authorizedkeyscommand": "none", "authorizedprincipalsfile": "none",
                                     "trustedusercakeys": "none", "allowtcpforwarding": "yes",
                                     "allowstreamlocalforwarding": "yes", "gatewayports": "no", "permittunnel": "no"})
        self.assertEqual(d["files"], [])

    def test_the_first_unprivileged_port_is_reported(self):
        for text, expected in (("1024\n", 1024), ("0\n", 0), ("1\n", 1), ("65535\n", 65535)):
            self._w(CE.UNPRIVILEGED_PORT_START, text)
            self.assertEqual(CE.d1_7(self.host(), {})["unprivileged_port_start"], expected, text)

    def test_a_missing_or_odd_unprivileged_port_setting_is_could_not_check(self):
        self.assertEqual(CE.d1_7(self.host(), {})["unprivileged_port_start"], R.COULD_NOT_CHECK)   # no file
        for text in ("", "\n", "abc\n", "-1\n", "1024 2048\n", "10.5\n", "999999\n"):
            self._w(CE.UNPRIVILEGED_PORT_START, text)
            self.assertEqual(CE.d1_7(self.host(), {})["unprivileged_port_start"], R.COULD_NOT_CHECK, repr(text))

    def _port_file(self, raw):
        p = os.path.join(self.root, CE.UNPRIVILEGED_PORT_START.lstrip("/"))
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "wb") as f:
            f.write(raw)

    def test_only_a_plain_ascii_port_number_is_accepted(self):
        for raw in ("١٠٢٤\n".encode(), "１０２４\n".encode(), b"0001\n", b"00\n", b"01024\n", b" 1024\n",
                    b"1024 \n", b"1024\n\n", b"1024\r\n", b"+1024\n", b"1024\x00\n", b"\xff\xfe1024\n",
                    b"\xff\n", b"1" * 4096):
            self._port_file(raw)
            self.assertEqual(CE.d1_7(self.host(), {})["unprivileged_port_start"], R.COULD_NOT_CHECK, repr(raw[:24]))
        for raw, expected in ((b"1024\n", 1024), (b"1024", 1024), (b"0\n", 0), (b"65535\n", 65535)):
            self._port_file(raw)
            self.assertEqual(CE.d1_7(self.host(), {})["unprivileged_port_start"], expected, repr(raw))

    def test_a_directory_in_place_of_the_port_setting_is_could_not_check(self):
        os.makedirs(os.path.join(self.root, CE.UNPRIVILEGED_PORT_START.lstrip("/")))
        self.assertEqual(CE.d1_7(self.host(), {})["unprivileged_port_start"], R.COULD_NOT_CHECK)

    def test_the_result_has_exactly_these_top_level_fields(self):
        self.assertEqual(sorted(CE.d1_7(self.host(), {})),
                         ["accounts_checked", "daemon_options", "files", "include_elsewhere", "match_lines", "sshd",
                          "unprivileged_port_start"])

    def _sshd_config(self, main, **drop_ins):
        self._w("/etc/ssh/sshd_config", main)
        for name, body in drop_ins.items():
            self._w("/etc/ssh/sshd_config.d/" + name.replace("_", "."), body)

    def test_match_lines_are_counted_in_the_main_file_and_the_conf_files(self):
        self._two()
        self._sshd_config("Include /etc/ssh/sshd_config.d/*.conf\nPort 22\n# Match User x\n"
                          "Match User a\n  X11Forwarding no\n\tmatch=Group b\n",
                          a_conf="MATCH all\nPermitRootLogin no\n", b_txt="Match User ignored\n")
        d = CE.d1_7(self.host(), {})
        self.assertEqual((d["match_lines"], d["include_elsewhere"]), (3, 0))

    def test_no_match_line_is_zero_not_could_not_check(self):
        self._two()
        self._sshd_config("Include /etc/ssh/sshd_config.d/*.conf\nPermitRootLogin no\nAllowUsers matchbox\n")
        d = CE.d1_7(self.host(), {})
        self.assertEqual((d["match_lines"], d["include_elsewhere"]), (0, 0))

    def test_an_include_that_reaches_elsewhere_is_counted_per_line(self):
        self._two()
        self._sshd_config('Include /etc/ssh/sshd_config.d/*.conf\ninclude /etc/ssh/extra/*.conf "/opt/x y.conf"\n'
                          "Include sshd_config.d/*.conf\nInclude other.conf\n")
        d = CE.d1_7(self.host(), {})
        self.assertEqual((d["match_lines"], d["include_elsewhere"]), (0, 2))

    def test_every_match_form_sshd_honoured_counts(self):
        """Each form opened a Match block (or, marked below, was ignored or refused) in sshd 9.6p1:
        docs/evaluations/2026-10-10-journal-retention-35-days.md. The count is a superset by construction."""
        forms = ['Match User u', '"Match" User u', 'Ma"tch" User u', 'Match"" User u', '""Match User u',
                 '"" "Match" User u', '"Match"User u', 'Match\rUser u', '\rMatch User u', 'Match=User u',
                 'Match\tUser u', '=Match User u', '= Match User u', '="Match" User u',
                 '==Match User u', '""=Match User u', '"" ""Match User u',      # these three: sshd ignored the line
                 '"Match"=User u', '"Match User" u']                         # these two: sshd refuses the file
        self._two()
        for form in forms:
            self._sshd_config(form + "\n  X11Forwarding yes\n")
            d = CE.d1_7(self.host(), {})
            self.assertEqual((d["match_lines"], d["include_elsewhere"]), (1, 0), repr(form))

    def test_matchmaker_counts_as_a_match_line(self):
        """sshd 9.6p1 refuses a file with `Matchmaker yes` (rc 255): counting it is an over-count that can
        only fall on a file sshd will not run, which is what a superset must do."""
        self._two()
        self._sshd_config('Matchmaker yes\n"Matchmaker" yes\n')
        self.assertEqual(CE.d1_7(self.host(), {})["match_lines"], 2)

    def test_lines_that_are_not_a_match_or_an_include_do_not_count(self):
        self._two()
        self._sshd_config('# Match User x\n # Include /opt/x\nPort 22\nPermitRootLogin no\nAllowUsers matchbox\n\n'
                          '\r\n"" ""\n')
        d = CE.d1_7(self.host(), {})
        self.assertEqual((d["match_lines"], d["include_elsewhere"]), (0, 0))

    def test_every_include_form_sshd_honoured_is_read(self):
        """An outside path counts in every spelling sshd honoured (9.6p1, see the evaluation record)."""
        self._two()
        forms = ['Include {}', '"Include" {}', 'In"clude" {}', 'Include\r{}', 'Include "{}"', 'Include={}',
                 '=Include {}', '""Include {}', '"Include"{}', 'Include\t{}', 'Include = {}']
        for form in forms:
            self._sshd_config(form.format("/opt/extra.conf") + "\n")
            d = CE.d1_7(self.host(), {})
            self.assertEqual((d["match_lines"], d["include_elsewhere"]), (0, 1), repr(form))

    GLOB = "/etc/ssh/sshd_config.d/*.conf"

    def _include_elsewhere(self, line):
        self._sshd_config(line + "\n")
        return CE.d1_7(self.host(), {})["include_elsewhere"]

    def test_the_standard_glob_is_recognised_only_in_a_closed_set_of_spellings(self):
        self._two()
        for line in (f"Include {self.GLOB}", f"  include\t{self.GLOB}", f'INCLUDE "{self.GLOB}"',
                     f"Include {self.GLOB} \r", "Include sshd_config.d/*.conf", 'Include "sshd_config.d/*.conf"'):
            self.assertEqual(self._include_elsewhere(line), 0, repr(line))

    def test_anything_else_around_the_standard_glob_is_elsewhere(self):
        """Measured on sshd 9.6p1 (-ddd 'new include'): `= =`, a quoted `=` or blank, `==`, a control
        character before or after the glob each make sshd read another path or pattern as well."""
        self._two()
        g = self.GLOB
        for line in (f"Include = = {g}", f'Include "=" {g}', f'Include " " {g}', f"Include =={g}",
                     f"Include \x01{g}", f"Include {g}\x01", f"Include {g}\x0b", f"Include {g}\x7f",
                     f"Include {g}\x0c", f'"Include" {g}', f"Include={g}", f"Include = {g}", f"Include\r{g}",
                     f"Include {g} # c", f'Include "{g}', f'Include {g}"', f"Include {g}\r/opt/x.conf",
                     f"Include {g} /opt/x.conf", "Include /etc/ssh/x/../sshd_config.d/*.conf",
                     "Include ~/../" + g, "Include /etc/ssh/sshd_ config.d/*.conf", "Include", f"Include {g}x",
                     f"Include /{g}", f'Include "{g}""', f"=Include {g}", f"Include\t{g}\x0c",
                     f"Include=={g}", f"Include \x0b{g}", f'Include /etc/ssh/sshd_config.d/"*.conf'):
            self.assertEqual(self._include_elsewhere(line), 1, repr(line))

    def test_the_keyword_case_folding_is_ascii_only(self):
        """Python folds U+0130 and U+0131 onto `i` in a str pattern; sshd does not (ASCII letters only)."""
        for line in (f"\u0130nclude {self.GLOB}", f"\u0131nclude {self.GLOB}"):
            self.assertIsNone(CE._SSHD_STANDARD_INCLUDE_RE.fullmatch(line), repr(line))
        self.assertIsNotNone(CE._SSHD_STANDARD_INCLUDE_RE.fullmatch(f"iNcLuDe {self.GLOB}"))   # control

    # The process lists below are what `ps -C sshd -o args=` printed on sshd 9.6p1 (the evaluation record,
    # "How the running sshd was started"), one line per process.
    LISTENER = "sshd: /usr/sbin/sshd -D [listener] 0 of 10-100 startups\n"
    CHILDREN = "sshd: u [priv]\nsshd: u@notty\nsshd: [accepted]\n"

    PS = ("ps", "-ww", "-C", "sshd", "-o", "args=")

    def _ps(self, out, rc=0, err=""):
        self.outputs[self.PS] = (rc, out, err)
        return CE.d1_7(self.host(), {})["daemon_options"]

    def host_calls_for(self, name):
        host = self.host()
        CE.d1_7(host, {})
        return [c for c in host.calls if c[0] == name]

    def _opts(self, listeners, f, o):
        return {"listeners": listeners, "config_file_options": f, "setting_options": o}

    def test_a_plain_listener_has_no_options(self):
        for out in ("sshd: /usr/sbin/sshd [listener] 0 of 10-100 startups\n", self.LISTENER):
            self.assertEqual(self._ps(out), self._opts(1, 0, 0), repr(out))

    def test_children_of_the_listener_are_not_counted(self):
        self.assertEqual(self._ps("sshd: /usr/sbin/sshd -D [listener] 1 of 10-100 startups\n" + self.CHILDREN),
                         self._opts(1, 0, 0))
        self.assertEqual(self._ps("sshd: /usr/sbin/sshd -D -f /tmp/alt.conf -o X11Forwarding=yes "
                                  "[listener] 0 of 10-100 startups\nsshd: u [priv]\nsshd: u@notty\n"),
                         self._opts(1, 1, 1))

    def test_config_file_and_setting_options_are_counted_in_every_spelling(self):
        for args, f, o in (("-f /tmp/alt.conf -o X11Forwarding=yes", 1, 1),
                           ("-f/tmp/alt.conf -oX11Forwarding=yes", 1, 1),
                           ("-D -f /tmp/alt.conf -o X11Forwarding=yes -o Port=22", 1, 2),
                           ("-o A=1 -oB=2 -o C=3", 0, 3), ("-f /a -f /b", 2, 0),
                           ("-Df /tmp/alt.conf", 1, 0), ("-Dfpath", 1, 0), ("-Do X=1", 0, 1),
                           ("-p 2222 -4", 0, 0), ("-o -f", 1, 1), ("-o X=1 -- -f", 1, 1),
                           ("-D -o AllowUsers u v -o X11Forwarding=yes", 0, 2),
                           ("-f /tmp/a b.conf -o X11Forwarding=yes", 1, 1),
                           ("-o Banner /etc/x y -f /tmp/alt.conf", 1, 1), ("-D -e -f /tmp/alt.conf", 1, 0),
                           ("-De -f /tmp/alt.conf", 1, 0), ("-Def/tmp/alt.conf", 1, 0),
                           ("-Def /tmp/alt.conf", 1, 0), ("-Deo X11Forwarding=yes", 0, 1),
                           ("-Dof X11Forwarding=yes", 0, 1), ("-f /tmp/alt.conf -f /tmp/alt.conf", 2, 0),
                           ("-4 -6 -D -d -e -i -q -t", 0, 0)):
            out = f"sshd: /usr/sbin/sshd {args} [listener] 0 of 10-100 startups\n"
            self.assertEqual(self._ps(out), self._opts(1, f, o), repr(args))

    CNC = {k: R.COULD_NOT_CHECK for k in ("listeners", "config_file_options", "setting_options")}
    # Every title below is one `ps -ww -C sshd -o args=` printed on sshd 9.6p1 during or after a login
    # (the evaluation record, "How the running sshd was started", fix round 1).
    CHILD_TITLES = ("sshd: [accepted]\n", "sshd: [net]\n", "sshd: [rexeced]\n", "sshd: hermesops\n", "sshd: u [net]\n",
                    "sshd: u [priv]\n", "sshd: u@notty\n", "sshd: u@pts/0\n", "sshd: unknown [net]\n",
                    "sshd: unknown [priv]\n", "/usr/sbin/sshd -D -R\n", "[sshd]\n", "[sshd] <defunct>\n")

    def test_every_measured_child_title_beside_a_listener_is_ignored(self):
        for child in self.CHILD_TITLES:
            self.assertEqual(self._ps(self.LISTENER + child), self._opts(1, 0, 0), repr(child))
        self.assertEqual(self._ps(self.LISTENER + "".join(self.CHILD_TITLES)), self._opts(1, 0, 0))

    def test_two_full_listeners_one_with_an_option_are_both_counted(self):
        self.assertEqual(self._ps(self.LISTENER + "sshd: /usr/sbin/sshd -D -f /x [listener] 0 of 10-100 startups\n"),
                         self._opts(2, 1, 0))
        self.assertEqual(self._ps(self.LISTENER * 2), self._opts(2, 0, 0))

    def test_a_line_that_is_not_a_listener_or_a_measured_child_makes_the_item_could_not_check(self):
        """Never a quiet skip: a second daemon whose title is cut short or was never retitled (measured:
        a small environment cuts it, `... -o AuthorizedKey x`) would otherwise read as healthy. Any local
        account can also make such a line, which gives CANNOT-VERIFY, not a pass."""
        for extra in ("sshd: /usr/sbin/sshd -D -f /opt/alt/sshd_config -o Port=2222 -o AuthorizedKeysFile=/x [liste\n",
                      "sshd: /usr/sbin/sshd -D -f /tmp/alt.conf -o AuthorizedKey x\n",
                      "/usr/sbin/sshd -D -f /x -o A=b\n", "/usr/sbin/sshd -D\n", "sshd: /usr/sbin/sshd -D [listener]\n",
                      "sshd: /usr/sbin/sshd -D [listener] 0 of 10-100 startups x\n",
                      "sshd: /usr/sbin/sshd -D [listener] 0 of 10-100 startupsX\n", "sshd: [listener] 0 of 10-100 startups\n",
                      "sshd: u [pam]\n", "sshd: -f [priv]\n", "sshd: u [priv] \n", " sshd: u [priv]\n", "sshd: u [priv]\r\n",
                      "sshd: u@notty \n", "sshd: u -f /x [priv]\n", "sshd:  u\n",
                      # measured on 9.6p1 (record, fix round 1): the cut titles of a daemon started with an
                      # empty environment, a title cut by COLUMNS=60, and a title cut after the program path
                      "sshd: /usr/sbin/sshd -D -f /tmp/alt.conf -o Port=2222 -o AuthorizedKey x\n",
                      "sshd: /usr/sbin/sshd -D -f /tmp/alt.conf -o 2\n",
                      "sshd: /usr/sbin/sshd -D -f /tmp/a-rather-long-directory-name\n", "sshd: /usr/sbin/sshd\n",
                      "sshd: s x\n", "s: s x\n"):
            self.assertEqual(self._ps(self.LISTENER + extra), self.CNC, repr(extra))
            self.assertEqual(self._ps(extra), self.CNC, repr(extra))               # alone, too

    def test_a_bare_sshd_name_line_is_ignored_only_for_a_real_account(self):
        """A daemon's own cut title can end as `sshd: x` (the last character of its last argument): the
        bare form is a child only when NAME is an account in /etc/passwd. Only `unknown [net]` and
        `unknown [priv]` were seen, never a bare `sshd: unknown`."""
        for name in ("x", "unknown", "u", "Hermesops", "hermesop"):
            self.assertEqual(self._ps(self.LISTENER + f"sshd: {name}\n"), self.CNC, name)
        for name in ("hermesops", "hermes-broker", "root", "daemon"):
            self.assertEqual(self._ps(self.LISTENER + f"sshd: {name}\n"), self._opts(1, 0, 0), name)
        self.assertEqual(self._ps(self.LISTENER + "sshd: x [priv]\nsshd: x@notty\nsshd: x [net]\n"),
                         self._opts(1, 0, 0))                      # a suffixed form needs no account

    def test_a_bare_sshd_name_line_with_no_readable_account_list_is_could_not_check(self):
        os.remove(os.path.join(self.root, "etc/passwd"))
        self.outputs[self.PS] = (0, self.LISTENER + "sshd: hermesops\n", "")
        self.assertEqual(CE._sshd_daemon_options(self.host()), self.CNC)
        self.outputs[self.PS] = (0, self.LISTENER + "sshd: u [priv]\n", "")
        self.assertEqual(CE._sshd_daemon_options(self.host()), self._opts(1, 0, 0))

    def test_the_process_list_is_not_cut_to_a_width(self):
        """`ps -ww`: without it procps applies COLUMNS even to a pipe (measured), cutting a long title."""
        self._ps(self.LISTENER)
        self.assertEqual(self.host_calls_for("ps"), [["ps", "-ww", "-C", "sshd", "-o", "args="]])

    def test_no_listener_is_zero_and_the_checklist_judges_it(self):
        self.assertEqual(self._ps("", rc=1), self._opts(0, 0, 0))

    def test_a_failing_process_list_is_could_not_check(self):
        cnc = {k: R.COULD_NOT_CHECK for k in ("listeners", "config_file_options", "setting_options")}
        self.assertEqual(self._ps("", rc=1, err='error: unknown user-defined format specifier "x"\n'), cnc)
        self.assertEqual(self._ps("", rc=127, err="not found"), cnc)
        self.assertEqual(self._ps(self.LISTENER, rc=2), cnc)
        self.assertEqual(self._ps(self.LISTENER, rc=1), cnc)               # output on a non-zero rc

    def test_a_process_list_that_cannot_be_run_is_could_not_check(self):
        """No `ps` answer in the fake at all (it reports 127)."""
        self.assertEqual(CE.d1_7(self.host(), {})["daemon_options"],
                         {k: R.COULD_NOT_CHECK for k in ("listeners", "config_file_options", "setting_options")})

    def test_the_daemon_options_hold_no_path_and_no_value(self):
        out = json.dumps(self._ps(
            "sshd: /usr/sbin/sshd -f /tmp/alt.conf -o X11Forwarding=yes [listener] 0 of 10-100 startups\n"))
        self.assertIn('"config_file_options": 1', out)                # control: the line was read
        for gone in ("/tmp/alt.conf", "X11Forwarding", "alt.conf", "yes", "/usr/sbin/sshd"):
            self.assertNotIn(gone, out)

    def test_a_nul_byte_in_a_configuration_file_is_could_not_check(self):
        """sshd 9.6p1 honoured `Ma<NUL>` newline `tch User u` as a Match block: a NUL may join lines."""
        self._two()
        self._sshd_config("Port 22\n", a_conf="Ma\x00\ntch User u\n")
        self.assertEqual({k: CE.d1_7(self.host(), {})[k] for k in ("match_lines", "include_elsewhere")},
                         {"match_lines": R.COULD_NOT_CHECK, "include_elsewhere": R.COULD_NOT_CHECK})
        self._sshd_config("Po\x00rt 22\n")
        self.assertEqual(CE.d1_7(self.host(), {})["match_lines"], R.COULD_NOT_CHECK)

    def test_a_configuration_file_over_the_read_limit_is_could_not_check(self):
        self._two()
        self._sshd_config("Port 22\n" + "#" * CE.AUTHORIZED_KEYS_READ_LIMIT + "\n")
        d = CE.d1_7(self.host(), {})
        self.assertEqual((d["match_lines"], d["include_elsewhere"]), (R.COULD_NOT_CHECK, R.COULD_NOT_CHECK))

    def test_a_configuration_that_cannot_be_read_is_could_not_check_and_the_keys_are_still_listed(self):
        self._two()                                             # no /etc/ssh/sshd_config in the fake root
        d = CE.d1_7(self.host(), {})
        self.assertEqual((d["match_lines"], d["include_elsewhere"]), (R.COULD_NOT_CHECK, R.COULD_NOT_CHECK))
        self.assertEqual(len(d["files"][0]["keys"]), 2)

    def test_a_setting_sshd_did_not_print_is_could_not_check(self):
        self.outputs[("sshd", "-T")] = (0, self.SSHD.replace("trustedusercakeys none\n", ""), "")
        self.assertEqual(CE.d1_7(self.host(), {})["sshd"]["trustedusercakeys"], R.COULD_NOT_CHECK)

    def test_sshd_failing_or_naming_no_key_file_is_could_not_check(self):
        for result in ((1, "", "boom"), (0, "port 22\n", "")):
            self.outputs[("sshd", "-T")] = result
            with self.assertRaises(CE.CouldNotCheck):
                CE.d1_7(self.host(), {})

    def test_an_account_without_a_login_shell_is_read_too(self):
        self._keys("/var/lib/hermes-broker", f"ssh-ed25519 {_keybody(3)}\n")
        rows = CE.d1_7(self.host(), {})["files"]
        self.assertEqual([(r["users"], len(r["keys"])) for r in rows], [(["hermes-broker"], 1)])

    def test_accounts_that_share_a_home_give_one_row_naming_both(self):
        self._keys("/usr/sbin", f"ssh-ed25519 {_keybody(4)}\n")
        rows = CE.d1_7(self.host(), {})["files"]
        self.assertEqual([r["users"] for r in rows], [["bin", "daemon"]])

    def test_the_second_file_name_is_read(self):
        self._w("/root/.ssh/authorized_keys2", f"ssh-ed25519 {_keybody(5)}\n")
        rows = CE.d1_7(self.host(), {})["files"]
        self.assertEqual([r["path"] for r in rows], ["/root/.ssh/authorized_keys2"])

    def test_percent_tokens_and_an_absolute_pattern_are_expanded(self):
        self.outputs[("sshd", "-T")] = (0, self.SSHD.replace(".ssh/authorized_keys .ssh/authorized_keys2",
                                                              "%h/.ssh/authorized_keys /etc/ssh/keys/%u"), "")
        self._keys("/home/hermesops", f"ssh-ed25519 {_keybody(1)}\n")
        self._w("/etc/ssh/keys/root", f"ssh-ed25519 {_keybody(6)}\n")
        self.assertEqual(sorted(r["path"] for r in CE.d1_7(self.host(), {})["files"]),
                         ["/etc/ssh/keys/root", "/home/hermesops/.ssh/authorized_keys"])

    def test_a_token_the_collector_does_not_expand_is_could_not_check(self):
        self.outputs[("sshd", "-T")] = (0, self.SSHD.replace(".ssh/authorized_keys .ssh/authorized_keys2",
                                                              "/etc/ssh/keys/%U"), "")
        with self.assertRaises(CE.CouldNotCheck):
            CE.d1_7(self.host(), {})

    def test_comments_and_blank_lines_are_skipped_and_other_lines_are_counted(self):
        self._keys("/home/hermesops", f"# a comment\n\nssh-ed25519 {_keybody(1)}\nnot a key line\n"
                                      f"ssh-ed25519 not*base64\nssh-ed25519\n"
                                      f'command="unbalanced ssh-ed25519 {_keybody(2)}\n')
        row = CE.d1_7(self.host(), {})["files"][0]
        self.assertEqual((len(row["keys"]), row["unparsed_lines"]), (1, 4))

    def test_a_quoted_value_with_a_space_and_a_comma_is_one_option(self):
        self._keys("/home/hermesops", f'command="/bin/echo a,b c",no-pty ssh-ed25519 {_keybody(1)}\n')
        key = CE.d1_7(self.host(), {})["files"][0]["keys"][0]
        self.assertEqual(key["options"], ["command=<withheld>", "no-pty"])

    def test_an_address_or_an_odd_command_is_withheld(self):
        self._keys("/home/hermesops",
                   f'from="203.0.113.7",permitopen="203.0.113.9:443",command="/usr/bin/x --token=abc",'
                   f'permitopen="127.0.0.1:9119",environment="A=b" ssh-ed25519 {_keybody(1)}\n')
        out = CE.d1_7(self.host(), {})["files"][0]["keys"][0]["options"]
        self.assertEqual(out, ["command=<withheld>", "environment=<withheld>", "from=<withheld>",
                               'permitopen="127.0.0.1:9119"', "permitopen=<withheld>"])
        self.assertNotIn("203.0.113", json.dumps(out))

    def test_a_symlink_in_place_of_the_file_is_never_read_as_empty(self):
        os.makedirs(os.path.join(self.root, "home/hermesops/.ssh"))
        os.symlink("/etc/passwd", os.path.join(self.root, "home/hermesops/.ssh/authorized_keys"))
        row = CE.d1_7(self.host(), {})["files"][0]
        self.assertEqual((row["kind"], row["keys"], row["unparsed_lines"]),
                         ("symlink", R.COULD_NOT_CHECK, R.COULD_NOT_CHECK))

    def test_a_certificate_authority_line_is_a_key_with_that_option(self):
        self._keys("/home/hermesops", f"cert-authority ssh-ed25519 {_keybody(7)}\n")
        self.assertEqual(CE.d1_7(self.host(), {})["files"][0]["keys"][0]["options"], ["cert-authority"])

    def test_an_escaped_backslash_before_a_quote_does_not_close_it_early_as_sshd_reads_it(self):
        """sshd: a backslash escapes only a double quote. In `command="a\\" ssh-ed25519 B1 x"` the
        `\\"` is a backslash then an escaped quote, so the value runs to the last quote and the
        accepted key is body 2; body 1 is only text inside the option."""
        self._keys("/home/hermesops", f'command="a\\\\" ssh-ed25519 {_keybody(1)} x" ssh-ed25519 {_keybody(2)}\n')
        out = CE.d1_7(self.host(), {})
        keys = out["files"][0]["keys"]
        self.assertEqual([k["sha12"] for k in keys], [hashlib.sha256(base64.b64decode(_keybody(2))).hexdigest()[:12]])
        self.assertNotIn(hashlib.sha256(base64.b64decode(_keybody(1))).hexdigest()[:12], json.dumps(out))

    def test_an_escaped_quote_inside_a_value_stays_in_the_value(self):
        self._keys("/home/hermesops", f'command="echo \\"hi\\"",no-pty ssh-ed25519 {_keybody(1)}\n')
        key = CE.d1_7(self.host(), {})["files"][0]["keys"][0]
        self.assertEqual(key["options"], ["command=<withheld>", "no-pty"])

    def test_blanks_before_the_key_are_skipped(self):
        self._keys("/home/hermesops", f"  \t ssh-ed25519 {_keybody(1)}\n \tno-pty ssh-ed25519 {_keybody(2)}\n")
        row = CE.d1_7(self.host(), {})["files"][0]
        self.assertEqual(([k["options"] for k in row["keys"]], row["unparsed_lines"]), ([[], ["no-pty"]], 0))

    def test_only_a_newline_ends_a_line_as_sshd_reads_the_file(self):
        """Python's splitlines also splits on \\r, \\f and U+2028; sshd does not. A key after one of
        them in a comment line is not a key, and a decoy key in front of one is not the line's key."""
        self._keys("/home/hermesops", f"# note\rssh-ed25519 {_keybody(1)}\n# note\u2028ssh-ed25519 {_keybody(2)}\n"
                                      f"\x0cssh-ed25519 {_keybody(3)}\n")
        row = CE.d1_7(self.host(), {})["files"][0]
        self.assertEqual((row["keys"], row["unparsed_lines"]), ([], 1))

    def test_a_file_that_is_swapped_for_a_symlink_is_not_followed(self):
        """The path is a file when it is first examined and a link by the time it is opened (once,
        between the examination and the open, whichever way the collector examines it)."""
        p = self._keys("/home/hermesops", f"ssh-ed25519 {_keybody(1)}\n")
        real_lstat, real_open, state = os.lstat, os.open, {"seen": 0, "swapped": False}
        def swap():
            if not state["swapped"]:
                state["swapped"] = True
                os.unlink(p)
                os.symlink("/etc/passwd", p)
        def lstat(path, *a, **kw):
            st = real_lstat(path, *a, **kw)
            if path == p:
                state["seen"] += 1
                if state["seen"] == 2:                  # d1_7 looked once; the row looks again
                    swap()
            return st
        def opener(path, *a, **kw):
            if path == p:
                swap()
            return real_open(path, *a, **kw)
        with mock.patch.object(os, "lstat", lstat), mock.patch.object(os, "open", opener):
            row = CE.d1_7(self.host(), {})["files"][0]
        self.assertEqual((row["kind"], row["keys"], row["unparsed_lines"]),
                         ("symlink", R.COULD_NOT_CHECK, R.COULD_NOT_CHECK))

    def test_a_file_over_the_read_limit_is_could_not_check_not_a_partial_list(self):
        self._keys("/home/hermesops", f"ssh-ed25519 {_keybody(1)}\nssh-ed25519 {_keybody(2)}\n")
        with mock.patch.object(CE, "AUTHORIZED_KEYS_READ_LIMIT", 64):
            row = CE.d1_7(self.host(), {})["files"][0]
        self.assertEqual((row["kind"], row["keys"], row["unparsed_lines"]),
                         ("file", R.COULD_NOT_CHECK, R.COULD_NOT_CHECK))

    def test_a_file_that_grows_past_the_limit_while_read_is_could_not_check(self):
        """fstat said small; the bytes read exceed the limit: still no partial list."""
        self._keys("/home/hermesops", f"ssh-ed25519 {_keybody(1)}\nssh-ed25519 {_keybody(2)}\n")
        real_fstat = os.fstat
        def small(fd):
            r = real_fstat(fd)
            return os.stat_result((r.st_mode, r.st_ino, r.st_dev, r.st_nlink, r.st_uid, r.st_gid, 1, 0, 0, 0))
        with mock.patch.object(CE, "AUTHORIZED_KEYS_READ_LIMIT", 64), mock.patch.object(os, "fstat", small):
            row = CE.d1_7(self.host(), {})["files"][0]
        self.assertEqual((row["keys"], row["unparsed_lines"]), (R.COULD_NOT_CHECK, R.COULD_NOT_CHECK))

    def test_a_quote_in_a_keys_comment_does_not_hide_the_key(self):
        self._keys("/home/hermesops", f'ssh-ed25519 {_keybody(1)} com"ment\n'
                                      f'no-pty ssh-ed25519 {_keybody(2)} com"ment\n')
        row = CE.d1_7(self.host(), {})["files"][0]
        self.assertEqual(([k["options"] for k in row["keys"]], row["unparsed_lines"]), ([[], ["no-pty"]], 0))
        self.assertNotIn("ment", json.dumps(row))

    def test_a_carriage_return_after_the_key_body_does_not_hide_the_key(self):
        self._keys("/home/hermesops", f"ssh-ed25519 {_keybody(1)}\r\n{TUNNEL_OPTS} ssh-ed25519 {_keybody(2)}\r\n")
        row = CE.d1_7(self.host(), {})["files"][0]
        self.assertEqual((len(row["keys"]), row["unparsed_lines"]), (2, 0))
        self.assertEqual(row["keys"][0]["sha12"], hashlib.sha256(base64.b64decode(_keybody(1))).hexdigest()[:12])

    def test_an_unclosed_quote_in_the_options_is_still_not_a_key(self):
        self._keys("/home/hermesops", f'command="unbalanced ssh-ed25519 {_keybody(1)}\n')
        row = CE.d1_7(self.host(), {})["files"][0]
        self.assertEqual((row["keys"], row["unparsed_lines"]), ([], 1))

    def test_the_rows_of_ordinary_lines_are_what_they_were(self):
        self._two()
        row = CE.d1_7(self.host(), {})["files"][0]
        self.assertEqual([k["options"] for k in row["keys"]],
                         [[], ['command="/bin/false"', 'permitlisten="127.0.0.1:1"',
                               'permitopen="127.0.0.1:9119"', "port-forwarding", "restrict"]])

    def test_an_empty_line_in_a_file_with_cr_lf_endings_is_blank(self):
        self._keys("/home/hermesops", f"# two keys\r\n\r\nssh-ed25519 {_keybody(1)} one\r\n   \r\n")
        row = CE.d1_7(self.host(), {})["files"][0]
        self.assertEqual((len(row["keys"]), row["unparsed_lines"]), (1, 0))

    def test_a_path_that_cannot_be_examined_is_reported_not_skipped(self):
        p = self._keys("/home/hermesops", f"ssh-ed25519 {_keybody(1)}\n")
        real_lstat, real_open = os.lstat, os.open
        def deny(real):
            def call(path, *a, **kw):
                if path == p:
                    raise PermissionError(13, "denied")
                return real(path, *a, **kw)
            return call
        with mock.patch.object(os, "lstat", deny(real_lstat)), mock.patch.object(os, "open", deny(real_open)):
            rows = CE.d1_7(self.host(), {})["files"]
        self.assertEqual(len(rows), 1)
        self.assertEqual({k: rows[0][k] for k in ("path", "users", "kind", "owner", "group", "mode", "keys", "unparsed_lines")},
                         {"path": "/home/hermesops/.ssh/authorized_keys", "users": ["hermesops"],
                          "kind": R.COULD_NOT_CHECK, "owner": R.COULD_NOT_CHECK, "group": R.COULD_NOT_CHECK,
                          "mode": R.COULD_NOT_CHECK, "keys": R.COULD_NOT_CHECK, "unparsed_lines": R.COULD_NOT_CHECK})
        self.assertEqual(set(rows[0]), {"path", "users", "kind", "owner", "group", "mode", "keys", "unparsed_lines"})

    def test_a_six_field_account_line_is_could_not_check_not_skipped(self):
        self._w("/etc/passwd", self.PASSWD + "short:x:1002:1002::/home/short\n")
        self._keys("/home/short", f"ssh-ed25519 {_keybody(6)}\n")
        with self.assertRaises(CE.CouldNotCheck):
            CE.d1_7(self.host(), {})

    def test_an_eight_field_account_line_is_could_not_check(self):
        self._w("/etc/passwd", self.PASSWD + "long:x:1003:1003::/home/long:/bin/sh:extra\n")
        with self.assertRaises(CE.CouldNotCheck):
            CE.d1_7(self.host(), {})

    def test_blank_lines_and_comment_lines_in_passwd_are_skipped(self):
        self._w("/etc/passwd", "\n# a comment\n" + self.PASSWD + "\n#another\n\n")
        self.assertEqual(CE.d1_7(self.host(), {})["accounts_checked"], 5)

    def test_full_width_digits_in_a_forward_target_are_withheld(self):
        self._keys("/home/hermesops",
                   f'permitopen="127.0.0.1:９１１９",permitlisten="127.0.0.1:１" '
                   f'ssh-ed25519 {_keybody(1)}\n')
        out = CE.d1_7(self.host(), {})["files"][0]["keys"][0]["options"]
        self.assertEqual(out, ["permitlisten=<withheld>", "permitopen=<withheld>"])


# `systemd-analyze cat-config --tldr` layout, measured on systemd 255 (docs/evaluations/2026-10-10-journal-retention-35-days.md, R8, R9):
# a `# <path>` header per file, one empty line between files, no comment lines of the contents.
MAIN = "/etc/systemd/journald.conf"
SYSLOG = "/usr/lib/systemd/journald.conf.d/syslog.conf"
OURS = "/etc/systemd/journald.conf.d/50-hermes-retention.conf"
FILES = {MAIN: "[Journal]\nSystemMaxFileSize=100M\nCompress=yes\nSystemMaxUse=1G\nMaxRetentionSec=7day\nMaxFileSec=1day\n",
         OURS: "[Journal]\nMaxRetentionSec=35day\nSystemMaxFiles=500\n",
         SYSLOG: "[Journal]\nForwardToSyslog=yes\n"}
CAT_CONFIG = "\n".join(f"# {p}\n{c}" for p, c in FILES.items())


def _oldest_key(*selector):
    return tuple(["journalctl", *CE.OLDEST_ENTRY_ARGS, *selector])


def _entry(epoch):
    return json.dumps({"__CURSOR": "s=abc", "__REALTIME_TIMESTAMP": str(epoch * 1000000 + 123456),
                       "__MONOTONIC_TIMESTAMP": "1", "_BOOT_ID": "0" * 32,
                       "__SEQNUM": "1", "__SEQNUM_ID": "0" * 32}) + "\n"


class TestJournalReach(Base):
    SECRET = "sk-or-v1-" + "0123456789abcdef" * 4
    M2_BYTES = 4630823                                  # the whole journal on the box, 2026-10-10 (7 days)

    def test_d2_3_reads_every_field_in_one_call(self):
        self.outputs[("journalctl", "-o")] = (0, _e(MESSAGE="Started.", _CMDLINE=f"tool {self.SECRET}"), "")
        self.outputs[_oldest_key()] = (0, _entry(1760000000), "")
        host = self.host()
        d = CE.d2_3(host, {"secrets": [self.SECRET]})
        self.assertEqual(d["journal"], {"pattern_hits": 0, "known_secret_hits": 1})
        self.assertEqual((d["entries"], d["fields"]), (1, 2))
        searches = [c for c in host.calls if "--all" in c]
        self.assertEqual(searches, [["journalctl", "-o", "json", "--all", "--no-pager", "-q"]])

    def test_d2_3_at_the_35_day_size_finds_what_is_at_the_far_end(self):
        """185,000 entries of about 1,000 characters (M1 of 2026-10-13, scaled to 35 days), never held whole."""
        secret, n = self.SECRET, 185000
        filler = _e(MESSAGE="x" * 600, _CMDLINE="/usr/bin/python3 " + "y" * 300, _PID="1234")

        class Lines:
            rc, err = 0, ""

            def __iter__(self):
                yield _e(MESSAGE="first", _CMDLINE=f"leak {secret}")
                for _ in range(n):
                    yield filler
                yield _e(COMMAND=f"GOOGLE_ADS_REFRESH_TOKEN={TOKEN}")

        class Big(CE.Host):
            def stream(self, argv, timeout=60):
                return Lines()
        host = Big(self.root, lambda argv, timeout=60: (0, _entry(1760000000), ""))
        t0 = time.monotonic()
        d = CE.d2_3(host, {"secrets": [secret]})
        self.assertEqual(d["journal"], {"pattern_hits": 1, "known_secret_hits": 1})
        self.assertEqual(d["entries"], n + 2)
        self.assertGreater(d["scanned_characters"], 150 * 1000 * 1000)
        self.assertLess(time.monotonic() - t0, CE.JOURNAL_SCAN_TIMEOUT / 3)

    def test_d2_3_reports_the_size_searched_and_the_oldest_entry_read_after_the_search(self):
        self.outputs[("journalctl", "-o")] = (0, "Started.\n" * 3, "")
        self.outputs[_oldest_key()] = (0, _entry(1760000000), "")
        host = self.host()
        d = CE.d2_3(host, {"secrets": []})
        self.assertEqual(d, {"journal": {"pattern_hits": 0, "known_secret_hits": 0}, "entries": 3, "fields": 3,
                             "scanned_characters": 72, "undecodable_characters": 0, "oldest_entry_read": "2025-10-09T08:53:20Z"})
        self.assertEqual([c[1] for c in host.calls], ["-o", "-q"])      # the search first, then the oldest entry

    def test_d2_3_an_oldest_entry_that_cannot_be_read_is_could_not_check_and_the_search_still_counts(self):
        CN = R.COULD_NOT_CHECK
        self.outputs[("journalctl", "-o")] = (0, "Started.\n", "")
        for answer, want in (((1, "", "Failed"), CN), ((127, "", "not found"), CN), ((0, "not json\n", ""), CN),
                             ((0, _entry(1760000000) * 2, ""), CN), ((0, "", ""), None)):
            with self.subTest(answer=answer):
                self.outputs[_oldest_key()] = answer
                d = CE.d2_3(self.host(), {"secrets": []})
                self.assertEqual((d["oldest_entry_read"], d["scanned_characters"]), (want, 24))
        def run(argv, timeout=60):
            if argv[1] == "-q":
                raise UnicodeDecodeError("utf-8", b"\xff", 0, 1, "invalid start byte")
            return (0, _as_entries("Started.\n"), "")
        d = CE.d2_3(CE.Host(self.root, run), {"secrets": []})
        self.assertEqual((d["oldest_entry_read"], d["scanned_characters"]), (CN, 24))

    # Measured (record R14, systemd 255): a truncated archived file is skipped with this on stderr and rc 0;
    # without rights journalctl says the second line, with rc 1 and nothing on stdout.
    TRUNCATED = "Journal file /var/log/journal/" + "0" * 32 + "/system@" + "0" * 32 + "-1-2.journal is truncated, ignoring file.\n"
    NO_RIGHTS = "No journal files were opened due to insufficient permissions.\n"

    def test_d2_3_a_read_that_ends_with_a_warning_is_could_not_check_never_a_healthy_count(self):
        self.outputs[_oldest_key()] = (0, _entry(1760000000), "")
        for what, answer in (("truncated file, rc 0", (0, "Started.\n", self.TRUNCATED)),
                             ("no rights, rc 0 (NOT produced in the measurement: rc 1 was; kept as the case the stderr rule exists for)", (0, "", self.NO_RIGHTS)),
                             ("no rights, rc 1", (1, "", self.NO_RIGHTS)),
                             ("time-out", (124, "", "journalctl: timed out")),
                             ("rc 1 without a word", (1, "", ""))):
            with self.subTest(what=what):
                self.outputs[("journalctl", "-o")] = answer
                with self.assertRaises(CE.CouldNotCheck):
                    CE.d2_3(self.host(), {"secrets": []})
                it = CE.collect(self.host(), self.KEY)["items"]["D2.3"]
                self.assertEqual(it["status"], R.COULD_NOT_CHECK)
                self.assertNotIn("truncated", it["reason"])               # the warning's text is not carried
                self.assertNotIn("/var/log/journal", it["reason"])

    BAD_BYTE_CHILD = ["-c", "import sys; sys.stdout.buffer.write(b'ok\\n\\xff GOOGLE_ADS_REFRESH_TOKEN=" + TOKEN + "\\n')"]

    def test_the_strict_runner_raises_on_a_byte_that_is_not_text_and_the_lossy_one_replaces_it(self):
        argv = [sys.executable, *self.BAD_BYTE_CHILD]
        with self.assertRaises(UnicodeDecodeError):
            CE._run_real(argv)
        rc, out, err = CE._run_real(argv, errors="replace")
        self.assertEqual((rc, err), (0, ""))
        self.assertEqual(out, "ok\n\ufffd GOOGLE_ADS_REFRESH_TOKEN=" + TOKEN + "\n")

    BAD_BYTE_ENTRIES = ["-c", "import sys; sys.stdout.buffer.write(b'{\"MESSAGE\": \"ok\"}\\n"
                              "{\"MESSAGE\": \"\\xff GOOGLE_ADS_REFRESH_TOKEN=" + TOKEN + "\"}\\n')"]

    def test_d2_3_searches_past_a_byte_that_is_not_text_and_says_how_many_were_replaced(self):
        argv = [sys.executable, *self.BAD_BYTE_ENTRIES]
        real = CE._RealStream
        # the real stream is reached through Host(root) with no fake: patch only the program that is started
        with mock.patch.object(CE, "_RealStream", lambda a, timeout: real(argv, timeout)), \
                mock.patch.object(CE, "_run_real", lambda a, timeout=60, errors="strict": (0, "", "")), \
                mock.patch.object(os, "geteuid", return_value=0):               # this host is the real one: root only
            d = CE.d2_3(CE.Host(self.root), {"secrets": []})
        self.assertEqual((d["journal"]["pattern_hits"], d["undecodable_characters"], d["entries"]), (1, 1, 2))

    def test_a_known_secret_beside_a_replaced_byte_is_still_counted(self):
        self.outputs[("journalctl", "-o")] = (0, "x \ufffd " + self.SECRET + "\n", "")
        self.outputs[_oldest_key()] = (0, "", "")
        d = CE.d2_3(self.host(), {"secrets": [self.SECRET]})
        self.assertEqual((d["journal"]["known_secret_hits"], d["undecodable_characters"]), (1, 1))

    def test_a_fake_run_host_works_with_run_lossy_unchanged(self):
        seen = []
        def run(argv, timeout=60):
            seen.append((argv, timeout))
            return (0, "t", "")
        self.assertEqual(CE.Host(self.root, run).run_lossy(["x"], 7), (0, "t", ""))
        self.assertEqual(seen, [(["x"], 7)])

    def test_the_reason_of_a_failed_journal_read_holds_no_journalctl_words_nor_path_nor_machine_id(self):
        mid = "0123456789abcdef0123456789abcdef"
        said = f"Journal file /var/log/journal/{mid}/system@x.journal is truncated, ignoring file.\n"
        for answer in ((0, "x\n", said), (1, "", said), (1, said, "")):
            with self.subTest(answer=answer[0]):
                self.outputs[("journalctl", "-o")] = answer
                it = CE.collect(self.host(), self.KEY)["items"]["D2.3"]
                self.assertEqual(it["status"], R.COULD_NOT_CHECK)
                for bad in (mid, "/var/log/journal", "truncated", "system@x"):
                    self.assertNotIn(bad, it["reason"])
                self.outputs[("journalctl", "-u")] = answer
                it = CE.collect(self.host(), self.KEY)["items"]["D10.7"]
                self.assertEqual(it["status"], R.COULD_NOT_CHECK)
                for bad in (mid, "/var/log/journal", "truncated"):
                    self.assertNotIn(bad, it["reason"])

    def _real_host(self):
        """A host that counts as the real one (built with the real runner) but whose commands are the fake's."""
        host = self.host()
        host._real = True
        fake = host._fake
        stack = contextlib.ExitStack()
        stack.enter_context(mock.patch.object(CE, "_run_real", lambda argv, timeout=60, errors="strict": fake(argv, timeout)))
        stack.enter_context(mock.patch.object(CE, "_RealStream", lambda argv, timeout: CE._TextStream(fake(argv, timeout))))
        return host, stack

    def test_the_journal_is_read_as_root_only_on_a_real_host(self):
        self.outputs[("journalctl", "-o")] = (0, "Started.\n", "")
        self.outputs[_oldest_key()] = (0, _entry(1760000000), "")
        self.outputs[("journalctl", "-u")] = (0, "", "")
        self.outputs[_oldest_key("-u", "hermes-app-broker@ads-audit")] = (0, _entry(1760000000), "")
        self.outputs[_oldest_key("-u", "hermes-app-runner@ads-audit")] = (0, _entry(1760000000), "")
        for euid, ok in ((1000, False), (0, True)):
            with self.subTest(euid=euid):
                host, patch = self._real_host()
                with patch, mock.patch.object(os, "geteuid", return_value=euid):
                    if ok:
                        self.assertEqual(CE.d2_3(host, {"secrets": []})["scanned_characters"], 24)
                        self.assertEqual(CE.d10_7(host, CE.context(host, self.KEY))["apps"]["ads-audit"]["oldest_entry_read"]["runner"], "2025-10-09T08:53:20Z")
                    else:
                        with self.assertRaises(CE.CouldNotCheck) as c:
                            CE.d2_3(host, {"secrets": []})
                        self.assertEqual(str(c.exception), "the journal is read as root only")
                        with self.assertRaises(CE.CouldNotCheck):
                            CE.d10_7(host, CE.context(host, self.KEY))
                        self.assertEqual(CE._oldest_entry(host), R.COULD_NOT_CHECK)
                        self.assertEqual([c for c in host.calls if c[0] == "journalctl"], [])    # nothing was run
        with mock.patch.object(os, "geteuid", return_value=1000):                   # a test host is unaffected
            self.assertEqual(CE.d2_3(self.host(), {"secrets": []})["scanned_characters"], 24)

    def test_a_warning_on_stderr_at_rc_0_makes_an_oldest_entry_could_not_check(self):
        for answer in ((0, _entry(1760000000), self.TRUNCATED), (0, "", self.TRUNCATED)):
            with self.subTest(answer=answer[1][:1]):
                self.outputs[_oldest_key()] = answer
                self.outputs[("journalctl", "-o")] = (0, "Started.\n", "")
                self.assertEqual(CE._oldest_entry(self.host()), R.COULD_NOT_CHECK)
                self.assertEqual(CE.d2_3(self.host(), {"secrets": []})["oldest_entry_read"], R.COULD_NOT_CHECK)
        self.outputs[_oldest_key()] = (0, _entry(1760000000), " \n")
        self.assertEqual(CE._oldest_entry(self.host()), "2025-10-09T08:53:20Z")

    def test_the_lossy_read_names_utf_8_and_the_strict_read_does_not(self):
        seen = []
        class P:
            def __init__(self, argv, **kw):
                seen.append(kw)
                raise FileNotFoundError
        with mock.patch.object(subprocess, "Popen", P):
            CE._run_real(["x"], errors="replace")
            CE._run_real(["x"])
        self.assertEqual((seen[0]["encoding"], seen[0]["errors"]), ("utf-8", "replace"))
        self.assertNotIn("encoding", seen[1])
        self.assertEqual(seen[1]["errors"], "strict")

    def test_d2_3_empty_stderr_at_rc_0_reads_as_before(self):
        self.outputs[("journalctl", "-o")] = (0, "Started.\n", "  \n")
        self.outputs[_oldest_key()] = (0, _entry(1760000000), "")
        self.assertEqual(CE.d2_3(self.host(), {"secrets": []})["scanned_characters"], 24)

    def test_d10_7_a_journal_read_that_ends_with_a_warning_is_could_not_check(self):
        for unit in ("broker", "runner"):
            for what, answer in (("truncated file, rc 0", (0, _as_entries("x\n"), self.TRUNCATED)),
                                 ("no rights, rc 0 (NOT produced in the measurement: rc 1 was; kept as the case the stderr rule exists for)", (0, "", self.NO_RIGHTS)),
                                 ("time-out", (124, "", "journalctl: timed out"))):
                with self.subTest(unit=unit, what=what):
                    host = self.host()
                    ok = (0, "", "")
                    def run(argv, timeout=60):
                        return answer if argv[:3] == ["journalctl", "-u", f"hermes-app-{unit}@ads-audit"] and "--all" in argv else ok
                    host = CE.Host(self.root, run)
                    with self.assertRaises(CE.CouldNotCheck):
                        CE.d10_7(host, CE.context(host, self.KEY))

    def test_d2_3_gives_the_journal_300_seconds(self):
        seen = {}
        def run(argv, timeout=60):
            seen[tuple(argv[:2])] = timeout
            return (0, "", "")
        CE.d2_3(CE.Host(self.root, run), {"secrets": []})
        self.assertEqual(seen[("journalctl", "-o")], 300)

    def test_d2_3_finds_a_secret_and_a_pattern_at_the_far_end_of_35_days_of_journal(self):
        line = "hermes-app-broker[ads-audit]: request=0 op=run client=x status=ok reason=-\n"
        filler = line * (5 * self.M2_BYTES // len(line))
        text = f"leak {self.SECRET}\n" + filler + f"GOOGLE_ADS_REFRESH_TOKEN={TOKEN}\n"
        self.assertGreaterEqual(len(text), 5 * self.M2_BYTES - len(line))
        self.outputs[("journalctl", "-o")] = (0, text, "")
        t0 = time.monotonic()
        d = CE.d2_3(self.host(), {"secrets": [self.SECRET]})
        took = time.monotonic() - t0
        self.assertEqual(d["journal"], {"pattern_hits": 1, "known_secret_hits": 1})
        self.assertEqual(d["scanned_characters"], len(_as_entries(text)))
        self.assertLess(took, 60, "the search of a 35-day journal must end far inside the 300 s limit")

    def test_d10_7_reports_the_oldest_entry_read_for_each_unit_inside_its_30_days(self):
        self.outputs[_oldest_key("-u", "hermes-app-broker@ads-audit")] = (0, _entry(1760000000), "")
        self.outputs[_oldest_key("-u", "hermes-app-runner@ads-audit")] = (0, "", "")
        self.outputs[("journalctl", "-u")] = (0, "", "")
        host = self.host()
        d = CE.d10_7(host, CE.context(host, self.KEY))["apps"]["ads-audit"]
        self.assertEqual(d["oldest_entry_read"], {"broker": "2025-10-09T08:53:20Z", "runner": None})
        oldest = [c for c in host.calls if c[1] == "-q"]
        first = [c for c in oldest if "--since" not in c]       # each job's first entry: the whole journal, its broker
        self.assertEqual([c[-2:] for c in first], [["-u", f"hermes-app-broker@{a}"] for a in APPS])
        oldest = [c for c in oldest if c not in first]
        self.assertEqual(len(oldest), 4)                        # two units for each of the two jobs
        self.assertTrue(all(c[-2:] == ["--since", "-30d"] for c in oldest), oldest)

    def test_d10_7_an_oldest_entry_that_cannot_be_read_is_could_not_check_for_that_unit_alone(self):
        CN = R.COULD_NOT_CHECK
        self.outputs[_oldest_key("-u", "hermes-app-broker@ads-audit")] = (1, "", "Failed")
        self.outputs[_oldest_key("-u", "hermes-app-runner@ads-audit")] = (0, _entry(1760000000), "")
        self.outputs[("journalctl", "-u")] = (0, "", "")
        host = self.host()
        d = CE.d10_7(host, CE.context(host, self.KEY))["apps"]["ads-audit"]
        self.assertEqual(d["oldest_entry_read"], {"broker": CN, "runner": "2025-10-09T08:53:20Z"})
        def run(argv, timeout=60):
            if argv[1] == "-q":
                raise UnicodeDecodeError("utf-8", b"\xff", 0, 1, "invalid start byte")
            return (0, "", "")
        host = CE.Host(self.root, run)
        d = CE.d10_7(host, CE.context(host, self.KEY))["apps"]["ads-audit"]
        self.assertEqual(d["oldest_entry_read"], {"broker": CN, "runner": CN})


class TestJournalHelpers(Base):
    def _disk(self, files):
        for path, content in files.items():
            self._w(path, content)

    def _read(self, files, text=None):
        """Write `files` under the fake root and read them with the printout `text` (default: what --tldr prints)."""
        self._disk(files)
        return CE._journald_settings(self.host(), text if text is not None else
                                     "\n".join(f"# {p}\n{c}" for p, c in files.items()))

    def test_the_last_file_that_sets_a_value_is_the_one_reported(self):
        got, files = self._read(FILES)
        self.assertEqual(files, [MAIN, OURS, SYSLOG])
        self.assertEqual(got["MaxRetentionSec"], {"value": "35day", "file": OURS})
        self.assertEqual(got["SystemMaxFiles"], {"value": "500", "file": OURS})
        self.assertEqual(got["SystemMaxUse"], {"value": "1G", "file": MAIN})
        self.assertEqual(got["MaxFileSec"], {"value": "1day", "file": MAIN})

    def test_last_wins_empty_value_and_unknown_or_lower_case_keys(self):
        got, files = self._read({MAIN: "[Journal]\nMaxRetentionSec=7day\nmaxretentionsec=1day\nSystemMaxUse=\n"
                                       "MaxRetentionSec=40day\nFoo=bar\n"})
        self.assertEqual(files, [MAIN])
        self.assertEqual(got["MaxRetentionSec"], {"value": "40day", "file": MAIN})
        self.assertEqual(got["SystemMaxUse"], {"value": "", "file": MAIN})
        self.assertEqual(got["SystemMaxFiles"], {"value": None, "file": None})

    def test_comments_and_blank_lines_in_a_real_file_are_fine(self):
        files = {**FILES, MAIN: "#  This file is part of systemd.\n\n  # indented\n; semi\n \t \n[Journal]\n#Storage=auto\n"
                                "SystemMaxUse=1G\nMaxRetentionSec=7day\nMaxFileSec=1day\n"}
        # the printout has no comment lines: build it from the measured layout instead
        printed = ("# " + MAIN + "\n[Journal]\nSystemMaxUse=1G\nMaxRetentionSec=7day\nMaxFileSec=1day\n\n"
                   "# " + OURS + "\n[Journal]\nMaxRetentionSec=35day\nSystemMaxFiles=500\n\n"
                   "# " + SYSLOG + "\n[Journal]\nForwardToSyslog=yes\n")
        got, _ = self._read(files, printed)
        self.assertEqual(got["MaxRetentionSec"]["value"], "35day")
        self.assertEqual(got["SystemMaxUse"], {"value": "1G", "file": MAIN})

    def test_the_command_is_the_measured_one(self):
        self.assertEqual(CE.JOURNALD_CAT_CONFIG, ["systemd-analyze", "cat-config", "--tldr", "systemd/journald.conf"])

    def _raises(self, later, path="/etc/systemd/journald.conf.d/99-local.conf"):
        with self.assertRaises(CE.CouldNotCheck):
            self._read({**{k: FILES[k] for k in (MAIN, OURS)}, path: later})

    def test_lines_outside_the_closed_grammar_are_could_not_check(self):
        for later in ("[Journal]\n\n# /run/systemd/journald.conf.d/zz.conf\nMaxRetentionSec=1day\n",   # C1
                      "[Journal]\nCompress=yes \\\n[Other]\nMaxRetentionSec=1day\n",                  # C2
                      "\ufeff[Journal]\nMaxRetentionSec=1day\n",                                      # C3
                      "[Journal\nMaxRetentionSec=1day\n",                                              # I4
                      "[Journal]\n\n# /etc/systemd/journald.conf.d/99+local.conf\nMaxRetentionSec=40day\n",  # I5
                      "[Journal]\n; a comment\n",    # the printout never shows a comment
                      "[Journal]\nMaxRetentionSec = 1day\n", "[Journal]\n MaxRetentionSec=1day\n",
                      "[Journal]\nMaxRetentionSec=1day \n", "[Journal]\nMaxRetentionSec=1day\\\n",
                      "[journal]\nMaxRetentionSec=1day\n", "[ Journal ]\nMaxRetentionSec=1day\n",
                      "MaxRetentionSec=1day\n[Journal]\n", "[Journal]\nMaxRetentionSec=1d\u00e4y\n",
                      "[Journal]\nMaxRetentionSec=1day\x01\n", "[Journal]\nMaxRetentionSec=1\tday\n",
                      "[Journal]\nnot an assignment\n"):
            with self.subTest(later=later):
                self._raises(later)

    def test_a_broken_section_line_that_the_printout_shows_cleanly_is_could_not_check(self):
        # Record R9 (N1): systemd stops reading at `[Broken`, so a later file's value never applies. Each printout
        # here is clean and AGREES with what a reader that skipped the broken line would find in the files, so
        # only the file reader's refusal of that line can raise.
        ours = FILES[OURS]
        for broken in ("[Broken\n[Journal]\nCompress=yes\n", "[Broken\n", "[Journal]\nX=1\n[Broken\n[Journal]\nMaxRetentionSec=35day\n"):
            with self.subTest(broken=broken):
                self._disk({MAIN: FILES[MAIN], "/etc/systemd/journald.conf.d/10-x.conf": broken, OURS: ours})
                printed = ("# " + MAIN + "\n" + FILES[MAIN] + "\n# /etc/systemd/journald.conf.d/10-x.conf\n"
                           "[Journal]\nCompress=yes\n\n# " + OURS + "\n" + ours)
                CE._journald_printout_settings(printed)                    # the printout alone is accepted
                with self.assertRaises(CE.CouldNotCheck):
                    CE._journald_settings(self.host(), printed)
        os.remove(self.host().path("/etc/systemd/journald.conf.d/10-x.conf"))
        # our own file with a broken section line after a [Journal] block; the printout does not show that line
        self._disk({MAIN: FILES[MAIN], OURS: "[Journal]\nX=1\n[Broken\n[Journal]\nMaxRetentionSec=35day\n"})
        printed = "# " + MAIN + "\n" + FILES[MAIN] + "\n# " + OURS + "\n[Journal]\nX=1\nMaxRetentionSec=35day\n"
        CE._journald_printout_settings(printed)
        with self.assertRaises(CE.CouldNotCheck):
            CE._journald_settings(self.host(), printed)

    def test_the_file_reader_alone_refuses_each_line_it_does_not_model(self):
        # The line is in the FILE only; the printout is clean and agrees with what a reader that trimmed
        # blanks, joined or skipped the line would find. So the file reader (step b) is what raises.
        local = "/etc/systemd/journald.conf.d/99-local.conf"
        clean = "[Journal]\nMaxRetentionSec=40day\n"
        head = "# " + MAIN + "\n" + FILES[MAIN] + "\n# " + OURS + "\n" + FILES[OURS] + "\n# " + local + "\n"
        for name, body, shown in (
                ("a blank before a key", "[Journal]\n MaxRetentionSec=40day\n", clean),
                ("a tab before a key", "[Journal]\n\tMaxRetentionSec=40day\n", clean),
                ("blanks around the equals sign", "[Journal]\nMaxRetentionSec = 40day\n", clean),
                ("a trailing blank", "[Journal]\nMaxRetentionSec=40day \n", clean),
                ("a line ending in a backslash", "[Journal]\nMaxRetentionSec=40day\\\n", clean),
                ("a continued line", "[Journal]\nCompress=yes\\\nMaxRetentionSec=40day\n", "[Journal]\nMaxRetentionSec=40day\n"),
                ("a section line with a trailing blank", "[Journal] \nMaxRetentionSec=40day\n", clean),
                ("a broken section line after a blank", "[Journal]\nMaxRetentionSec=40day\n [Broken\n", clean)):
            with self.subTest(name=name):
                self._disk({**{k: FILES[k] for k in (MAIN, OURS)}, local: body})
                files = CE._journald_printout_settings(head + shown)[1]    # the printout alone is accepted
                self.assertEqual(files, [MAIN, OURS, local])
                with self.assertRaises(CE.CouldNotCheck):
                    CE._journald_file_settings(self.host(), files)
                with self.assertRaises(CE.CouldNotCheck):
                    CE._journald_settings(self.host(), head + shown)
        # the control: the clean body in the file reads, so the cases above fail for their one line
        self._disk({local: clean})
        self.assertEqual(CE._journald_settings(self.host(), head + clean)[0]["MaxRetentionSec"],
                         {"value": "40day", "file": local})

    def test_a_main_file_ending_in_a_broken_section_line_is_refused_by_the_file_reader(self):
        self._disk({**FILES, MAIN: FILES[MAIN] + "[Broken\n"})
        self.assertEqual(CE._journald_printout_settings(CAT_CONFIG)[1], [MAIN, OURS, SYSLOG])
        with self.assertRaises(CE.CouldNotCheck):
            CE._journald_file_settings(self.host(), [MAIN, OURS, SYSLOG])
        with self.assertRaises(CE.CouldNotCheck):
            CE._journald_settings(self.host(), CAT_CONFIG)

    def test_an_oddly_named_settings_file_in_any_drop_in_directory_is_could_not_check(self):
        # Record R9 (N2): systemd lists a `.conf` file whose NAME holds newlines, and the printout then shows
        # header and content lines that stand in no file. The printout here is the healthy one.
        for d in CE.JOURNALD_DROP_IN_DIRS:
            for name in ("50-hermes-retention.conf\n[Journal]\nMaxRetentionSec=35day\nX=.conf", "my file.conf",
                         "a;b.conf", "café.conf", ".conf"):
                with self.subTest(d=d, name=name):
                    self._disk(FILES)
                    odd = self._w(d + "/" + name, "[Journal]\n")
                    with self.assertRaises(CE.CouldNotCheck):
                        CE._journald_settings(self.host(), CAT_CONFIG)
                    os.remove(odd)
                    self.assertEqual(CE._journald_settings(self.host(), CAT_CONFIG)[1], [MAIN, OURS, SYSLOG])

    def test_the_four_drop_in_directories_are_the_ones_journald_reads(self):
        self.assertEqual(CE.JOURNALD_DROP_IN_DIRS, ("/etc/systemd/journald.conf.d", "/run/systemd/journald.conf.d",
                                                    "/usr/local/lib/systemd/journald.conf.d",
                                                    "/usr/lib/systemd/journald.conf.d"))

    def test_an_odd_name_that_is_not_a_settings_file_is_ignored(self):
        self._disk(FILES)
        self._w("/usr/lib/systemd/journald.conf.d/odd name;\n.bak", "x")
        self._w("/etc/systemd/journald.conf.d/README", "x")
        self._w("/etc/systemd/journald.conf.d/x.conf\n", "x")              # does not END in .conf
        self.assertEqual(CE._journald_settings(self.host(), CAT_CONFIG)[1], [MAIN, OURS, SYSLOG])

    def test_a_drop_in_directory_that_cannot_be_listed_is_could_not_check(self):
        self._disk(FILES)
        self._w("/run/systemd/journald.conf.d", "a file where a directory belongs")
        with self.assertRaises(CE.CouldNotCheck):
            CE._journald_settings(self.host(), CAT_CONFIG)
        os.remove(self.host().path("/run/systemd/journald.conf.d"))
        with mock.patch.object(CE.os, "listdir", side_effect=PermissionError("no")):
            with self.assertRaises(CE.CouldNotCheck):
                CE._journald_settings(self.host(), CAT_CONFIG)
        CE._journald_settings(self.host(), CAT_CONFIG)

    def test_a_listed_file_is_opened_without_following_a_link_and_judged_by_what_was_opened(self):
        self._disk(FILES)
        real = self.host().path(OURS)
        opened = []
        real_open, real_lstat = os.open, os.lstat
        listed = {self.host().path(p) for p in (MAIN, OURS, SYSLOG)}

        def lstat(p, *a, **k):                         # the directories are looked at by path; a listed file never is
            if p in listed:
                raise AssertionError("judged by path, not by the open file")
            return real_lstat(p, *a, **k)
        with mock.patch.object(CE.os, "open", lambda p, flags, *a, **k: opened.append((p, flags)) or real_open(p, flags, *a, **k)), \
                mock.patch.object(CE.os, "lstat", lstat):
            CE._journald_settings(self.host(), CAT_CONFIG)
        self.assertEqual([p for p, _ in opened], [self.host().path(p) for p in (MAIN, OURS, SYSLOG)])
        for _, flags in opened:
            self.assertTrue(flags & os.O_NOFOLLOW)
            self.assertTrue(flags & os.O_NONBLOCK)
        os.remove(real)
        os.mkfifo(real)                                # a FIFO: opening it must not wait for a writer
        with self.assertRaises(CE.CouldNotCheck):
            CE._journald_settings(self.host(), CAT_CONFIG)
        before = len(os.listdir("/dev/fd"))
        for _ in range(5):                             # the refused file's descriptor is closed
            with self.assertRaises(CE.CouldNotCheck):
                CE._journald_settings(self.host(), CAT_CONFIG)
        self.assertEqual(len(os.listdir("/dev/fd")), before)

    def test_a_header_forged_through_a_file_name_is_could_not_check(self):
        # Record R9 (N2): the printout shows our header and 35day; no file of our name exists on disk.
        self._disk({MAIN: FILES[MAIN], SYSLOG: FILES[SYSLOG]})
        with self.assertRaises(CE.CouldNotCheck):
            CE._journald_settings(self.host(), CAT_CONFIG)

    def test_a_listed_file_that_is_not_a_plain_small_ascii_file_is_could_not_check(self):
        self._disk(FILES)
        real = self.host().path(OURS)
        elsewhere = self._w("/elsewhere.conf", FILES[OURS])
        os.remove(real)
        os.symlink(elsewhere, real)                                        # a symbolic link
        with self.assertRaises(CE.CouldNotCheck):
            CE._journald_settings(self.host(), CAT_CONFIG)
        os.remove(real)
        os.mkdir(real)                                                     # a directory
        with self.assertRaises(CE.CouldNotCheck):
            CE._journald_settings(self.host(), CAT_CONFIG)
        os.rmdir(real)
        for body in (FILES[OURS] + "#" + "x" * 70000 + "\n", FILES[OURS] + "# a\0b\n"):    # too large; a NUL
            with open(real, "w") as f:
                f.write(body)
            with self.assertRaises(CE.CouldNotCheck):
                CE._journald_settings(self.host(), CAT_CONFIG)
        with open(real, "wb") as f:                                         # a non-ASCII byte
            f.write(FILES[OURS].encode() + b"# \xc3\xa9\n")
        with self.assertRaises(CE.CouldNotCheck):
            CE._journald_settings(self.host(), CAT_CONFIG)
        with open(real, "w", newline="") as f:                              # a carriage return
            f.write(FILES[OURS].replace("\n", "\r\n"))
        with self.assertRaises(CE.CouldNotCheck):
            CE._journald_settings(self.host(), CAT_CONFIG)

    def test_the_printout_and_the_files_must_agree(self):
        self._disk({**FILES, OURS: "[Journal]\nMaxRetentionSec=1day\nSystemMaxFiles=500\n"})
        with self.assertRaises(CE.CouldNotCheck):
            CE._journald_settings(self.host(), CAT_CONFIG)

    def test_headers_that_cannot_be_trusted_are_could_not_check(self):
        self._disk(FILES)
        host = self.host()
        for text in (CAT_CONFIG + "\n# " + OURS + "\n[Journal]\nMaxRetentionSec=1day\n",           # our header twice
                     CAT_CONFIG + "\n# /etc/systemd/journald.conf.d/x/y.conf\n[Journal]\n",           # not a known path
                     "# Main configuration file systemd/journald.conf not found\n",                    # the tool's note
                     "[Journal]\nMaxRetentionSec=1day\n",                                              # content before a header
                     CAT_CONFIG + "\n# " + MAIN + "\n[Journal]\nMaxRetentionSec=1day\n",               # main header twice
                     "", "\n", "\n\n"):                                                              # nothing at all
            with self.subTest(text=text):
                with self.assertRaises(CE.CouldNotCheck):
                    CE._journald_settings(host, text)
        self._w("/usr/lib/systemd/journald.conf", FILES[MAIN])             # a main file only under /etc counts
        with self.assertRaises(CE.CouldNotCheck):
            CE._journald_settings(host, "# /usr/lib/systemd/journald.conf\n" + FILES[MAIN])

    def test_spans_sizes_and_what_cannot_be_converted(self):
        CN = R.COULD_NOT_CHECK
        for text, want in (("35day", 3024000), ("7day", 604800), ("1month", 2629800), ("1w", 604800), ("90", 90),
                           ("0", 0), ("0day", 0), ("1y", 31557600), ("213503981day", 213503981 * 86400), ("213503982day", CN),
                           ("584541y", 584541 * 31557600), ("584542y", CN), ("999999999y", CN),
                           ("2h 30min", CN), ("1.5h", CN), ("29.99999999999999999day", CN), ("3000000000day", CN),
                           ("99999999999999999999day", CN), ("0.99999999999999999999s", CN), ("1 fortnight", CN),
                           ("", CN), ("infinity", CN), ("day", CN), ("-1day", CN), ("+35day", CN), ("35 day", CN),
                           ("35ms", CN), (" 35day", CN), ("35day ", CN)):
            self.assertEqual(CE._span_seconds(text), want, text)
        for text, want in (("1G", 1 << 30), ("500M", 500 << 20), ("4096", 4096), ("8K", 8192), ("2T", 2 << 40),
                           ("1.5G", CN), ("", CN), ("big", CN), ("16E", CN), ("99999999999999999999G", CN),
                           ("1024B", CN), ("1G 500M", CN)):
            self.assertEqual(CE._size_bytes(text), want, text)

    def test_the_oldest_entry_is_a_utc_time_and_the_selector_comes_last(self):
        self.outputs[_oldest_key("-u", "hermes-app-broker@ads-audit")] = (0, _entry(1760000000), "")
        self.outputs[_oldest_key()] = (0, _entry(1759000000), "")
        host = self.host()
        self.assertEqual(CE._oldest_entry(host), "2025-09-27T19:06:40Z")
        self.assertEqual(CE._oldest_entry(host, ("-u", "hermes-app-broker@ads-audit", "--since", "-30d")),
                         "2025-10-09T08:53:20Z")
        self.assertEqual(host.calls[-1][-4:], ["-u", "hermes-app-broker@ads-audit", "--since", "-30d"])
        self.assertEqual(host.calls[0][:2], ["journalctl", "-q"])     # never the leak checks' own prefixes

    def test_no_entry_is_none_and_a_failure_is_could_not_check(self):
        self.outputs[_oldest_key()] = (0, "", "")
        self.assertIsNone(CE._oldest_entry(self.host()))
        for bad in ((1, "", "boom"), (0, "not json\n", ""), (0, "{}\n", ""), (0, '{"__REALTIME_TIMESTAMP": "x"}\n', ""),
                    (0, "[1]\n", ""), (0, '{"__REALTIME_TIMESTAMP": "9" }\n' * 2, ""),
                    (0, '{"__REALTIME_TIMESTAMP": true}\n', ""), (0, '{"__REALTIME_TIMESTAMP": 1760000000000000}\n', ""),
                    (0, '{"__REALTIME_TIMESTAMP": "-5000000"}\n', ""), (0, '{"__REALTIME_TIMESTAMP": "0"}\n', ""),
                    (0, '{"__REALTIME_TIMESTAMP": "' + "1" * 18 + '"}\n', "")):
            self.outputs[_oldest_key()] = bad
            self.assertEqual(CE._oldest_entry(self.host()), R.COULD_NOT_CHECK, bad)

    def test_ok_passes_its_time_limit_to_the_host(self):
        seen = []
        host = CE.Host(self.root, lambda argv, timeout=60: seen.append(timeout) or (0, "x", ""))
        CE._ok(host, ["true"])
        CE._ok(host, ["true"], timeout=300)
        self.assertEqual(seen, [60, 300])


class TestD24Journal(Base):
    MID = "0123456789abcdef0123456789abcdef"
    REPO_FILE = CE.CHECKOUT + "/infra/hermes-agent/deploy/journald-hermes-retention.conf"
    # as `systemctl show systemd-journald --timestamp=us+utc -p ExecMainStartTimestamp -p ActiveState -p MainPID`
    # prints it (record R7, R11): the three properties come back named, in systemd's order, not the order asked for
    START_TEXT = "Sat 2026-10-10 12:00:00.500000 UTC"

    @staticmethod
    def _shown(started=START_TEXT, state="active", pid="146"):
        return f"MainPID={pid}\nExecMainStartTimestamp={started}\nActiveState={state}\n"

    STARTED = _shown.__func__()
    START_NS = CE._epoch("2026-10-10T12:00:00Z") * 10 ** 9 + 500 * 10 ** 6
    DIRS = ("/etc/systemd/journald.conf.d", "/usr/lib/systemd/journald.conf.d")

    def setUp(self):
        super().setUp()
        self.cat_key, self.start_key = tuple(CE.JOURNALD_CAT_CONFIG), tuple(CE.JOURNALD_STARTED)
        self._w("/etc/machine-id", self.MID + "\n")
        for name in ("system.journal", "user-1000.journal", "system@a-1-2.journal", "user-1000@b-1-2.journal~"):
            self._w(f"/var/log/journal/{self.MID}/{name}", "x" * 8192)
        self._w(f"/var/log/journal/{self.MID}/not-a-journal.txt", "x")
        self._w(self.REPO_FILE, FILES[OURS])
        self.conf_paths = [self._w(p, FILES[p]) for p in (MAIN, OURS, SYSLOG)]   # they AGREE with CAT_CONFIG
        os.chmod(self.conf_paths[1], 0o644)
        self._all_older_than_the_start()
        self.outputs[self.cat_key] = (0, CAT_CONFIG, "")
        self.outputs[self.start_key] = (0, self.STARTED, "")
        now = int(time.time())
        self.outputs[_oldest_key("-u", "hermes-app-broker@ads-audit")] = (0, _entry(now - 3 * 86400), "")
        self.outputs[_oldest_key("-u", "hermes-app-runner@ads-audit")] = (0, "", "")
        self.outputs[_oldest_key()] = (0, _entry(now - 31 * 86400 - 60), "")
        self.disk_key = ("journalctl", "-D", "/var/log/journal/" + self.MID)
        self.flag = self._w("/run/systemd/journal/flushed", "")
        self.outputs[self.disk_key] = (0, _entry(now - 7), "")

    def _all_older_than_the_start(self):
        old = CE._epoch("2026-10-10T11:00:00Z")
        for p in [*self.conf_paths, *(os.path.join(self.root, d.lstrip("/")) for d in self.DIRS)]:
            os.utime(p, (old, old))

    def _content_time_only(self):
        """A test cannot set a file's inode change time: compare by the content time alone."""
        return mock.patch.object(CE, "_changed_at_ns", lambda host, p: os.lstat(host.path(p)).st_mtime_ns)

    def _set(self, path, ns):
        os.utime(os.path.join(self.root, path.lstrip("/")), ns=(ns, ns))

    def _swap(self, main_body):
        """The main file alone, on disk and in the printout."""
        self._w(MAIN, main_body)
        self.outputs[self.cat_key] = (0, "# " + MAIN + "\n" + main_body, "")

    def _raising(self, first, exc):
        host = self.host()
        fake = host._run

        def run(argv, timeout=60):
            if argv[0] == first:
                raise exc
            return fake(argv, timeout)
        host._run = run
        return host

    def test_a_healthy_box(self):
        with self._content_time_only():
            d = CE.d2_4(self.host(), {})
        self.assertEqual(sorted(d), ["config_files", "drop_in", "oldest_entry", "reach_days", "service", "settings", "usage"])
        self.assertEqual(d["reach_days"], 31)
        self.assertRegex(d["oldest_entry"]["journal"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$")
        self.assertRegex(d["oldest_entry"]["apps"]["ads-audit"]["broker"], r"Z$")
        self.assertIsNone(d["oldest_entry"]["apps"]["ads-audit"]["runner"])
        self.assertEqual(d["settings"]["MaxRetentionSec"], {"value": "35day", "file": OURS, "number": 3024000})
        self.assertEqual(d["settings"]["SystemMaxFiles"], {"value": "500", "file": OURS, "number": 500})
        self.assertEqual(d["settings"]["SystemMaxUse"], {"value": "1G", "file": MAIN, "number": 1 << 30})
        self.assertEqual(d["settings"]["MaxFileSec"], {"value": "1day", "file": MAIN, "number": 86400})
        self.assertEqual(d["config_files"], [MAIN, OURS, SYSLOG])
        self.assertEqual((d["drop_in"]["equals_repo"], d["drop_in"]["mode"], d["drop_in"]["other_files"]),
                         (True, "0o644", []))
        self.assertEqual(d["service"], {"active": True, "started_at": "2026-10-10T12:00:00Z",
                                        "config_changed_after_start": False})
        self.assertEqual(d["settings"]["Storage"], {"value": None, "file": None, "number": None})
        self.assertEqual(list(d["settings"]), ["MaxRetentionSec", "SystemMaxUse", "SystemMaxFiles", "MaxFileSec", "Storage"])
        own = os.path.join(self.root, "var/log/journal", self.MID)
        blocks = sum(os.lstat(os.path.join(own, n)).st_blocks for n in os.listdir(own) if ".journal" in n)
        self.assertEqual((d["usage"]["files"], d["usage"]["bytes"], d["usage"]["other_directories"]),
                         (4, blocks * 512, 0))
        self.assertEqual(d["usage"]["files_percent_of_max_files"], 0.8)
        self.assertIsInstance(d["usage"]["bytes_percent_of_max_use"], float)
        self.assertIsInstance(d["usage"]["free_bytes"], int)
        self.assertTrue(0 <= d["usage"]["free_percent"] <= 100)

    def test_the_names_later_tasks_read(self):
        self.assertEqual(CE.JOURNALD_DROP_IN, OURS)
        self.assertEqual(CE._journal_units("ads-audit"), {"broker": "hermes-app-broker@ads-audit", "runner": "hermes-app-runner@ads-audit"})
        self.assertIs(CE.PROBES["D2.4"], CE.d2_4)
        self.assertEqual(list(CE.PROBES)[list(CE.PROBES).index("D2.3") + 1], "D2.4")

    def test_the_commands_are_the_measured_ones_and_each_unit_is_asked_for(self):
        self.assertEqual(CE.JOURNALD_STARTED, ["systemctl", "show", "systemd-journald", "--timestamp=us+utc",
                                               "-p", "ExecMainStartTimestamp", "-p", "ActiveState", "-p", "MainPID"])
        host = self.host()
        CE.d2_4(host, {})
        self.assertIn(CE.JOURNALD_CAT_CONFIG, host.calls)
        self.assertIn(CE.JOURNALD_STARTED, host.calls)
        for selector in ([], ["-u", "hermes-app-broker@ads-audit"], ["-u", "hermes-app-runner@ads-audit"]):
            self.assertIn(["journalctl", *CE.OLDEST_ENTRY_ARGS, *selector], host.calls)

    # ---- service: has the running journal service read the files shown?
    def test_a_settings_file_newer_than_the_service_start_is_reported(self):
        for path in (MAIN, OURS, SYSLOG):
            with self.subTest(path=path):
                self._all_older_than_the_start()
                self._set(path, self.START_NS + 1000)                       # one microsecond after the start
                with self._content_time_only():
                    d = CE.d2_4(self.host(), {})
                self.assertIs(d["service"]["config_changed_after_start"], True)

    def test_installed_then_restarted_within_one_second_is_not_reported(self):
        # Record R7: in the rehearsal our file was written 21 ms before the service's process started, in
        # the same second. At second precision that reads as "changed after the start".
        self._set(OURS, self.START_NS - 21 * 10 ** 6)
        self._set(self.DIRS[0], self.START_NS - 22 * 10 ** 6)
        with self._content_time_only():
            self.assertIs(CE.d2_4(self.host(), {})["service"]["config_changed_after_start"], False)

    def test_a_change_stamped_within_one_clock_tick_before_the_start_counts_as_after(self):
        # A file's time is taken from the kernel's coarse clock: up to one tick (10 ms at most) older than the change.
        self.assertEqual(CE._CLOCK_TICK_NS, 10 * 10 ** 6)
        for before_ns, want in ((10 * 10 ** 6 - 1, True), (10 * 10 ** 6, False), (0, True)):
            with self.subTest(before_ns=before_ns):
                self._set(OURS, self.START_NS - before_ns)
                with self._content_time_only():
                    self.assertIs(CE.d2_4(self.host(), {})["service"]["config_changed_after_start"], want)

    def test_a_file_added_to_or_removed_from_a_settings_directory_after_the_start_is_reported(self):
        # A drop-in the service read and that was then deleted is still in force, and is in no list.
        for d in self.DIRS:
            with self.subTest(d=d):
                self._all_older_than_the_start()
                self._set(d, self.START_NS + 10 ** 9)
                with self._content_time_only():
                    got = CE.d2_4(self.host(), {})
                self.assertIs(got["service"]["config_changed_after_start"], True)
                self.assertEqual(got["config_files"], [MAIN, OURS, SYSLOG])
        self._all_older_than_the_start()                                    # and really, with the real clock:
        self.outputs[self.start_key] = (0, self._shown(time.strftime("%a %Y-%m-%d %H:%M:%S.000000 UTC", time.gmtime(time.time() + 3600))), "")
        self.assertIs(CE.d2_4(self.host(), {})["service"]["config_changed_after_start"], False)   # control: start in an hour
        os.utime(os.path.join(self.root, self.DIRS[1].lstrip("/")), None)
        self.outputs[self.start_key] = (0, self._shown(time.strftime("%a %Y-%m-%d %H:%M:%S.000000 UTC", time.gmtime(time.time() - 3600))), "")
        self.assertIs(CE.d2_4(self.host(), {})["service"]["config_changed_after_start"], True)

    def test_a_file_just_written_is_newer_than_an_old_start_without_any_patching(self):
        # the real clock: every file of this test was created just now, the service started long ago
        self.outputs[self.start_key] = (0, self._shown("Thu 2020-01-02 00:00:00.000000 UTC"), "")
        d = CE.d2_4(self.host(), {})["service"]
        self.assertEqual(d, {"active": True, "started_at": "2020-01-02T00:00:00Z", "config_changed_after_start": True})

    def test_the_inode_change_time_counts_not_only_the_content_time(self):
        # a copy that keeps an old content time (cp -p, tar, touch -d) still changed the file just now
        before = time.time_ns() - 5 * 10 ** 9
        self.assertEqual(os.lstat(self.conf_paths[1]).st_mtime, CE._epoch("2026-10-10T11:00:00Z"))
        self.assertGreater(CE._changed_at_ns(self.host(), OURS), before)
        os.symlink("/nowhere", os.path.join(self.root, "a-link"))            # the link itself, never its target
        self.assertGreater(CE._changed_at_ns(self.host(), "/a-link"), before)

    def test_a_start_time_that_cannot_be_read_is_could_not_check_never_false(self):
        CN = R.COULD_NOT_CHECK
        for started in ("", "Sat 2026-10-10 12:00:00 UTC",                    # empty; no microseconds
                        "Sat 2026-10-10 14:00:00.500000 CEST",                # not UTC
                        "Sat 2026-13-45 12:00:00.500000 UTC",                 # not a date
                        "@1791654218", "n/a"):
            with self.subTest(started=started):
                self.outputs[self.start_key] = (0, self._shown(started), "")
                with self._content_time_only():
                    d = CE.d2_4(self.host(), {})
                self.assertEqual(d["service"], {"active": True, "started_at": CN, "config_changed_after_start": CN})

    def test_a_service_that_is_not_running_is_never_reported_as_having_read_the_settings(self):
        # Record R11: a stopped journal service keeps its ExecMainStartTimestamp (and shows MainPID=0, inactive).
        CN = R.COULD_NOT_CHECK
        for state, pid, active in (("inactive", "0", False), ("failed", "0", False), ("deactivating", "146", False),
                                   ("activating", "146", False), ("reloading", "146", False), ("maintenance", "0", False),
                                   ("active", "0", CN),                       # active without a process: not understood
                                   ("active", "", CN), ("active", "-1", CN), ("active", "1e3", CN), ("active", "0146", CN),
                                   ("Active", "146", CN), ("", "146", CN), ("active (running)", "146", CN)):
            with self.subTest(state=state, pid=pid):
                self.outputs[self.start_key] = (0, self._shown(state=state, pid=pid), "")
                with self._content_time_only():
                    d = CE.d2_4(self.host(), {})
                self.assertEqual(d["service"], {"active": active, "started_at": CN, "config_changed_after_start": CN})
                self.assertEqual(d["settings"]["MaxRetentionSec"]["number"], 3024000)     # the other parts are still read

    def test_an_answer_about_the_service_that_is_not_the_three_properties_is_could_not_check(self):
        CN = R.COULD_NOT_CHECK
        good = self.STARTED
        for answer in ((0, "\n", ""), (0, "", ""), (1, good, ""), (127, "", "not found"),
                       (0, self.START_TEXT + "\n", ""),                               # the bare value
                       (0, good + good, ""),                                          # each property twice
                       (0, good + "SubState=running\n", ""),                          # one more
                       (0, good.replace("ActiveState=active\n", ""), ""),             # one missing
                       (0, good.replace("MainPID=146\n", "MainPID=146\nMainPID=147\n").replace("ActiveState=active\n", ""), ""),
                       (0, good.replace("ActiveState=", "ActiveState "), ""),
                       (0, good.replace("\n", "\r\n"), "")):
            with self.subTest(answer=answer):
                self.outputs[self.start_key] = answer
                with self._content_time_only():
                    d = CE.d2_4(self.host(), {})
                self.assertEqual(d["service"], {"active": CN, "started_at": CN, "config_changed_after_start": CN})
        self.outputs[self.start_key] = (0, "ActiveState=active\nExecMainStartTimestamp=" + self.START_TEXT + "\nMainPID=7\n", "")
        with self._content_time_only():                                               # any order of the three is read
            self.assertEqual(CE.d2_4(self.host(), {})["service"],
                             {"active": True, "started_at": "2026-10-10T12:00:00Z", "config_changed_after_start": False})

    # ---- a settings directory that is not a real directory (review of Task 7, Critical 1)
    def _link_a_directory(self, d):
        """`d` becomes a symbolic link to a real directory holding what `d` held."""
        real = os.path.join(self.root, d.lstrip("/"))
        elsewhere = os.path.join(self.root, "elsewhere" + d.replace("/", "-"))
        if os.path.isdir(real):
            os.rename(real, elsewhere)
        else:
            os.makedirs(elsewhere)
            os.makedirs(os.path.dirname(real), exist_ok=True)
        os.symlink(elsewhere, real)
        old = CE._epoch("2026-10-10T11:00:00Z")
        os.utime(elsewhere, (old, old))
        os.utime(real, (old, old), follow_symlinks=False)
        return elsewhere

    def _nothing_about_the_settings_is_claimed(self, d):
        CN = R.COULD_NOT_CHECK
        self.assertEqual((d["settings"], d["config_files"]), (CN, CN))
        self.assertEqual(d["service"], {"active": True, "started_at": CN, "config_changed_after_start": CN})
        self.assertEqual((d["usage"]["bytes_percent_of_max_use"], d["usage"]["files_percent_of_max_files"]), (CN, CN))

    def test_a_drop_in_directory_that_is_a_link_is_could_not_check_never_false(self):
        # The reviewer's case: the directory is a link, the service read a second file there (7 days) and that
        # file was removed since. The link's own time did not change, and every file read through it looks healthy.
        for d in CE.JOURNALD_DROP_IN_DIRS:
            with self.subTest(d=d):
                elsewhere = self._link_a_directory(d)
                if d == CE.JOURNALD_DROP_IN_DIR:
                    short = os.path.join(elsewhere, "99-short.conf")
                    with open(short, "w") as f:
                        f.write("[Journal]\nMaxRetentionSec=7day\n")
                    os.remove(short)                                        # the real directory's time is now: after the start
                with self._content_time_only():
                    d24 = CE.d2_4(self.host(), {})
                self._nothing_about_the_settings_is_claimed(d24)
                os.remove(os.path.join(self.root, d.lstrip("/")))
                os.rename(elsewhere, os.path.join(self.root, d.lstrip("/")))
                self._all_older_than_the_start()
                with self._content_time_only():                             # control: a real directory again
                    self.assertIs(CE.d2_4(self.host(), {})["service"]["config_changed_after_start"], False)

    def test_a_parent_of_a_settings_directory_reached_through_a_link_is_could_not_check(self):
        for parent in ("/etc/systemd", "/etc", "/usr/lib/systemd", "/usr/lib", "/usr", "/usr/local", "/usr/local/lib",
                       "/usr/local/lib/systemd", "/run", "/run/systemd"):
            with self.subTest(parent=parent):
                elsewhere = self._link_a_directory(parent)
                with self._content_time_only():
                    d = CE.d2_4(self.host(), {})
                self._nothing_about_the_settings_is_claimed(d)
                os.remove(os.path.join(self.root, parent.lstrip("/")))
                os.rename(elsewhere, os.path.join(self.root, parent.lstrip("/")))
                self._all_older_than_the_start()
                with self._content_time_only():
                    self.assertEqual(CE.d2_4(self.host(), {})["config_files"], [MAIN, OURS, SYSLOG])

    def test_a_settings_directory_that_is_a_file_is_could_not_check(self):
        self._w("/run/systemd/journald.conf.d", "a file where a directory belongs")
        with self._content_time_only():
            self._nothing_about_the_settings_is_claimed(CE.d2_4(self.host(), {}))

    @unittest.skipIf(os.geteuid() == 0, "root reads through any permission")
    def test_an_existing_directory_whose_time_cannot_be_read_is_could_not_check(self):
        # Nothing is patched: the directory exists, and its parent does not let this user look at it.
        os.makedirs(os.path.join(self.root, "usr/local/lib/systemd/journald.conf.d"))
        parent = os.path.join(self.root, "usr/local/lib/systemd")
        with self._content_time_only():
            self.assertIs(CE.d2_4(self.host(), {})["service"]["config_changed_after_start"], True)    # the new directory
        old = CE._epoch("2026-10-10T11:00:00Z")
        os.utime(os.path.join(parent, "journald.conf.d"), (old, old))
        with self._content_time_only():
            self.assertIs(CE.d2_4(self.host(), {})["service"]["config_changed_after_start"], False)   # control
        os.chmod(parent, 0)
        self.addCleanup(os.chmod, parent, 0o755)
        with self.assertRaises(PermissionError):
            os.lstat(os.path.join(parent, "journald.conf.d"))
        with self._content_time_only():
            self._nothing_about_the_settings_is_claimed(CE.d2_4(self.host(), {}))
        self._nothing_about_the_settings_is_claimed(CE.d2_4(self.host(), {}))              # and with the real function

    def test_the_service_part_refuses_a_linked_directory_on_its_own(self):
        # even handed a list of files (as if the settings reader had accepted them)
        self._link_a_directory("/run/systemd/journald.conf.d")
        with self._content_time_only():
            got = CE._journald_service(self.host(), [MAIN, OURS, SYSLOG])
        self.assertEqual(got, {"active": True, "started_at": R.COULD_NOT_CHECK, "config_changed_after_start": R.COULD_NOT_CHECK})

    # ---- Storage= (record R10)
    def test_storage_is_reported_as_written_by_the_file_that_sets_it_last(self):
        for value in ("volatile", "none", "persistent", "auto", "Volatile", "", "disk"):
            with self.subTest(value=value):
                self._swap("[Journal]\nStorage=persistent\nSystemMaxUse=1G\nStorage=" + value + "\n")
                d = CE.d2_4(self.host(), {})["settings"]
                self.assertEqual(d["Storage"], {"value": value, "file": MAIN, "number": None})
        local = "/etc/systemd/journald.conf.d/90-s.conf"                    # as measured: a later drop-in wins
        self._w(MAIN, FILES[MAIN] + "Storage=persistent\n")
        self._w(local, "[Journal]\nStorage=volatile\n")
        self.outputs[self.cat_key] = (0, "\n".join(f"# {p}\n{c}" for p, c in (
            (MAIN, FILES[MAIN] + "Storage=persistent\n"), (OURS, FILES[OURS]), (local, "[Journal]\nStorage=volatile\n"),
            (SYSLOG, FILES[SYSLOG]))), "")
        d = CE.d2_4(self.host(), {})
        self.assertEqual(d["settings"]["Storage"], {"value": "volatile", "file": local, "number": None})
        self.assertEqual(d["settings"]["MaxRetentionSec"]["value"], "35day")
        self._w(local, "[Journal]\n")                                      # the printout says volatile, no file does
        self.assertEqual(CE.d2_4(self.host(), {})["settings"], R.COULD_NOT_CHECK)

    def test_a_listed_file_whose_time_cannot_be_read_is_could_not_check_and_the_start_is_still_shown(self):
        def gone(host, p):
            raise PermissionError(p)
        with mock.patch.object(CE, "_changed_at_ns", gone):
            d = CE.d2_4(self.host(), {})
        self.assertEqual(d["service"], {"active": True, "started_at": "2026-10-10T12:00:00Z",
                                        "config_changed_after_start": R.COULD_NOT_CHECK})

    # ---- drop_in
    def test_a_missing_a_different_and_a_neighbouring_file_are_each_visible(self):
        self._w("/etc/systemd/journald.conf.d/99-other.conf", "[Journal]\n")
        self._w("/etc/systemd/journald.conf.d/odd name;.conf", "")
        self._w(OURS, FILES[OURS].replace("35day", "36day"))
        d = CE.d2_4(self.host(), {})["drop_in"]
        self.assertEqual((d["equals_repo"], d["other_files"]), (False, ["99-other.conf", CE.WITHHELD]))
        shutil.rmtree(os.path.join(self.root, "etc/systemd/journald.conf.d"))
        d = CE.d2_4(self.host(), {})["drop_in"]
        self.assertEqual(d, {"equals_repo": False, "owner": R.COULD_NOT_CHECK, "group": R.COULD_NOT_CHECK,
                             "mode": R.COULD_NOT_CHECK, "other_files": []})

    def test_a_drop_in_directory_that_cannot_be_listed_and_a_missing_repo_file(self):
        os.remove(os.path.join(self.root, self.REPO_FILE.lstrip("/")))
        real = os.listdir
        with mock.patch.object(CE.os, "listdir", lambda p: (_ for _ in ()).throw(PermissionError(p))
                               if p.endswith("journald.conf.d") else real(p)):
            d = CE.d2_4(self.host(), {})
        self.assertEqual((d["drop_in"]["equals_repo"], d["drop_in"]["other_files"], d["drop_in"]["mode"]),
                         (False, R.COULD_NOT_CHECK, "0o644"))
        self.assertEqual((d["settings"], d["config_files"]), (R.COULD_NOT_CHECK, R.COULD_NOT_CHECK))

    # ---- settings
    def test_no_setting_by_any_file_uses_systemds_default_file_limit(self):
        self._swap("[Journal]\nMaxRetentionSec=1.5h\n")
        d = CE.d2_4(self.host(), {})
        self.assertEqual(d["config_files"], [MAIN])
        self.assertEqual(d["settings"]["MaxRetentionSec"], {"value": "1.5h", "file": MAIN, "number": R.COULD_NOT_CHECK})
        self.assertEqual(d["settings"]["SystemMaxFiles"], {"value": None, "file": None, "number": None})
        self.assertEqual(d["settings"]["SystemMaxUse"], {"value": None, "file": None, "number": None})
        self.assertEqual(d["usage"]["files_percent_of_max_files"], 4.0)        # 4 files of the default 100
        self.assertEqual(d["usage"]["bytes_percent_of_max_use"], R.COULD_NOT_CHECK)   # no default is assumed for the size
        self.assertIsInstance(d["usage"]["bytes"], int)

    def test_a_value_the_reader_does_not_model_makes_the_settings_could_not_check(self):
        self._swap("[Journal]\nMaxRetentionSec=1 fortnight\n")             # a blank in a value: refused as a line
        d = CE.d2_4(self.host(), {})
        self.assertEqual((d["settings"], d["config_files"]), (R.COULD_NOT_CHECK, R.COULD_NOT_CHECK))
        self.assertEqual((d["usage"]["files"], d["usage"]["files_percent_of_max_files"],
                          d["usage"]["bytes_percent_of_max_use"]), (4, R.COULD_NOT_CHECK, R.COULD_NOT_CHECK))
        self.assertEqual(d["service"]["config_changed_after_start"], R.COULD_NOT_CHECK)

    def test_a_number_systemd_might_read_otherwise_is_could_not_check_never_a_guess(self):
        CN = R.COULD_NOT_CHECK
        for value, number, percent in (("500", 500, 0.8), ("100", 100, 4.0), ("4", 4, 100.0), ("999999999", 999999999, 0.0),
                                       ("0", 0, CN),                        # no count to compare with
                                       ("0500", CN, CN), ("00", CN, CN),     # a leading zero: octal to a C parser
                                       ("0x10", CN, CN), ("1000000000", CN, CN), ("+5", CN, CN), ("5e2", CN, CN),
                                       ("", CN, CN)):                       # an empty assignment resets the setting
            with self.subTest(value=value):
                self._swap("[Journal]\nSystemMaxUse=1G\nSystemMaxFiles=" + value + "\n")
                d = CE.d2_4(self.host(), {})
                self.assertEqual(d["settings"]["SystemMaxFiles"], {"value": value, "file": MAIN, "number": number})
                self.assertEqual(d["usage"]["files_percent_of_max_files"], percent)
        for value in ("0", "", "1.5G"):
            with self.subTest(max_use=value):
                self._swap("[Journal]\nSystemMaxUse=" + value + "\n")
                d = CE.d2_4(self.host(), {})
                self.assertEqual(d["usage"]["bytes_percent_of_max_use"], CN)
        self._swap("[Journal]\nMaxRetentionSec=0\nMaxFileSec=\n")           # 0: no time limit to systemd; shown as it is
        d = CE.d2_4(self.host(), {})["settings"]
        self.assertEqual((d["MaxRetentionSec"]["number"], d["MaxFileSec"]["number"]), (0, CN))

    def test_the_command_exiting_non_zero_is_could_not_check_and_the_other_parts_are_still_read(self):
        self.outputs[self.cat_key] = (1, CAT_CONFIG, "Failed to read a file")     # a full, healthy-looking printout
        with self._content_time_only():
            d = CE.d2_4(self.host(), {})
        self._settings_unknown_the_rest_read(d)
        self.assertIs(d["drop_in"]["equals_repo"], True)

    def test_a_printout_and_files_that_disagree_are_could_not_check(self):
        self._w(MAIN, FILES[MAIN].replace("SystemMaxUse=1G", "SystemMaxUse=2G"))
        self._all_older_than_the_start()
        with self._content_time_only():
            d = CE.d2_4(self.host(), {})
        self._settings_unknown_the_rest_read(d)
        self.assertIs(d["drop_in"]["equals_repo"], True)

    def test_our_file_listed_by_the_printout_and_missing_from_disk(self):
        os.remove(self.conf_paths[1])
        with self._content_time_only():
            d = CE.d2_4(self.host(), {})
        self._settings_unknown_the_rest_read(d)
        self.assertEqual(d["drop_in"], {"equals_repo": False, "owner": R.COULD_NOT_CHECK, "group": R.COULD_NOT_CHECK,
                                        "mode": R.COULD_NOT_CHECK, "other_files": []})

    def _settings_unknown_the_rest_read(self, d):
        CN = R.COULD_NOT_CHECK
        self.assertEqual((d["settings"], d["config_files"]), (CN, CN))
        self.assertEqual(d["reach_days"], 31)
        self.assertRegex(d["oldest_entry"]["journal"], r"Z$")
        self.assertEqual(d["service"], {"active": True, "started_at": "2026-10-10T12:00:00Z", "config_changed_after_start": CN})
        self.assertEqual((d["usage"]["files"], d["usage"]["other_directories"]), (4, 0))
        self.assertIsInstance(d["usage"]["bytes"], int)
        self.assertIsInstance(d["usage"]["free_percent"], float)
        self.assertEqual((d["usage"]["bytes_percent_of_max_use"], d["usage"]["files_percent_of_max_files"]), (CN, CN))

    def test_a_runner_that_raises_is_could_not_check_for_that_part_only(self):
        CN = R.COULD_NOT_CHECK
        for exc in (UnicodeDecodeError("utf-8", b"\xff", 0, 1, "invalid start byte"), PermissionError("no"), OSError("gone")):
            with self.subTest(exc=type(exc).__name__):
                d = CE.d2_4(self._raising("systemd-analyze", exc), {})
                self.assertEqual((d["settings"], d["config_files"], d["reach_days"]), (CN, CN, 31))
                d = CE.d2_4(self._raising("journalctl", exc), {})
                self.assertEqual((d["oldest_entry"], d["reach_days"]), ({"journal": CN, "apps": {a: {"broker": CN, "runner": CN} for a in APPS}}, CN))
                self.assertEqual(d["config_files"], [MAIN, OURS, SYSLOG])
                d = CE.d2_4(self._raising("systemctl", exc), {})
                self.assertEqual(d["service"], {"active": CN, "started_at": CN, "config_changed_after_start": CN})
                self.assertEqual(d["settings"]["MaxRetentionSec"]["number"], 3024000)

    def test_what_cannot_be_read_is_could_not_check_part_by_part(self):
        self.outputs[self.cat_key] = (1, "", "boom")
        self.outputs[_oldest_key()] = (1, "", "boom")
        os.remove(os.path.join(self.root, "etc/machine-id"))
        d = CE.d2_4(self.host(), {})
        self.assertEqual(d["oldest_entry"]["journal"], R.COULD_NOT_CHECK)
        self.assertEqual(d["reach_days"], R.COULD_NOT_CHECK)
        self.assertEqual(d["settings"], R.COULD_NOT_CHECK)
        self.assertEqual(d["config_files"], R.COULD_NOT_CHECK)
        self.assertEqual(set(d["usage"].values()), {R.COULD_NOT_CHECK})
        self.assertIs(d["drop_in"]["equals_repo"], True)                # the other parts are still read

    # ---- reach
    def test_a_journal_without_an_entry_has_no_reach_and_an_entry_from_the_future_is_could_not_check(self):
        self.outputs[_oldest_key()] = (0, "", "")
        d = CE.d2_4(self.host(), {})
        self.assertEqual((d["oldest_entry"]["journal"], d["reach_days"]), (None, None))
        now = int(time.time())
        for age, want in ((-3600, R.COULD_NOT_CHECK), (0, 0), (86340, 0), (86460, 1), (30 * 86400 - 60, 29), (30 * 86400 + 60, 30)):
            with self.subTest(age=age):
                self.outputs[_oldest_key()] = (0, _entry(now - age), "")
                self.assertEqual(CE.d2_4(self.host(), {})["reach_days"], want)

    def test_d2_4_reads_no_journal_as_a_user_who_is_not_root_on_a_real_host(self):
        CN = R.COULD_NOT_CHECK
        with mock.patch.object(os, "geteuid", return_value=1000):
            host = self.host()
            host._real = True
            d = CE.d2_4(host, {})
            self.assertEqual(d["oldest_entry"], {"journal": CN, "apps": {a: {"broker": CN, "runner": CN} for a in APPS}})
            self.assertEqual((d["reach_days"], d["usage"]["newest_entry_on_disk"], d["usage"]["on_disk_age_seconds"]), (CN, CN, CN))
            self.assertEqual(d["usage"]["files"], 4)                                  # what is not a journal read is read
            d = CE.d2_4(self.host(), {})
            self.assertEqual(d["reach_days"], 31)                                     # a test host is unaffected
        with mock.patch.object(os, "geteuid", return_value=0):
            host = self.host()
            host._real = True
            self.assertEqual(CE.d2_4(host, {})["reach_days"], 31)

    def test_a_warning_on_stderr_at_rc_0_makes_d2_4s_entry_times_could_not_check(self):
        CN = R.COULD_NOT_CHECK
        warn = "Journal file /var/log/journal/" + "0" * 32 + "/system@1-2.journal is truncated, ignoring file.\n"
        self.outputs[_oldest_key()] = (0, _entry(int(time.time()) - 31 * 86400), warn)
        self.outputs[self.disk_key] = (0, _entry(int(time.time()) - 7), warn)
        d = CE.d2_4(self.host(), {})
        self.assertEqual((d["oldest_entry"]["journal"], d["reach_days"]), (CN, CN))
        self.assertEqual((d["usage"]["newest_entry_on_disk"], d["usage"]["on_disk_age_seconds"]), (CN, CN))

    # ---- usage
    def test_another_machines_directory_is_counted_not_measured(self):
        self._w("/var/log/journal/ffffffffffffffffffffffffffffffff/system.journal", "y" * 4096)
        self._w("/var/log/journal/a-loose-file", "y")
        d = CE.d2_4(self.host(), {})["usage"]
        self.assertEqual((d["files"], d["other_directories"]), (4, 1))

    def test_a_usage_that_cannot_be_counted_is_could_not_check_never_zero(self):
        keys = {"bytes", "files", "bytes_percent_of_max_use", "files_percent_of_max_files", "free_bytes",
                "free_percent", "other_directories", "newest_entry_on_disk", "on_disk_age_seconds", "flushed_to_disk"}
        mid_path = os.path.join(self.root, "etc/machine-id")
        for body in ("uninitialized\n", "", self.MID.upper() + "\n", self.MID[:31] + "\n", "../../etc\n"):
            with self.subTest(body=body):
                with open(mid_path, "w") as f:
                    f.write(body)
                self.assertEqual(CE.d2_4(self.host(), {})["usage"], {k: R.COULD_NOT_CHECK for k in keys})
        with open(mid_path, "w") as f:
            f.write(self.MID + "\n")
        self.assertEqual(CE.d2_4(self.host(), {})["usage"]["files"], 4)     # control
        shutil.rmtree(os.path.join(self.root, "var/log/journal", self.MID))  # e.g. a journal kept in memory only
        self.assertEqual(CE.d2_4(self.host(), {})["usage"], {k: R.COULD_NOT_CHECK for k in keys})

    # ---- is the on-disk journal the one being written? (record R13)
    def test_a_journal_being_written_to_disk_has_a_newest_entry_a_few_seconds_old(self):
        host = self.host()
        d = CE.d2_4(host, {})["usage"]
        self.assertRegex(d["newest_entry_on_disk"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$")
        self.assertIn(d["on_disk_age_seconds"], (7, 8, 9))
        self.assertEqual(CE.NEWEST_ENTRY_ARGS, ["-q", "--no-pager", "-o", "json", "--output-fields=__REALTIME_TIMESTAMP", "-n", "1"])
        self.assertIn(["journalctl", "-D", "/var/log/journal/" + self.MID, *CE.NEWEST_ENTRY_ARGS], host.calls)
        self.assertEqual(list(CE.d2_4(host, {})["usage"])[-3:], ["newest_entry_on_disk", "on_disk_age_seconds", "flushed_to_disk"])

    def test_a_relinquished_on_disk_journal_shows_its_age_while_everything_else_reads_healthy(self):
        # Record R13: after `journalctl --relinquish-var` (and after a restart of the service) the on-disk directory
        # answers with ONE object, rc 0, whose time stays where it was; the merged journal goes on growing.
        now = int(time.time())
        measured = ('{"__MONOTONIC_TIMESTAMP":"9160068110","__SEQNUM":"2152","__SEQNUM_ID":"' + "0" * 32 + '",'
                    '"__REALTIME_TIMESTAMP":"' + str((now - 3 * 3600) * 1000000 + 486776) + '","__CURSOR":"s=abc","_BOOT_ID":"' + "0" * 32 + '"}\n')
        self.outputs[self.disk_key] = (0, measured, "")
        with self._content_time_only():
            d = CE.d2_4(self.host(), {})
        self.assertEqual(d["usage"]["newest_entry_on_disk"], CE._iso(now - 3 * 3600))
        self.assertIn(d["usage"]["on_disk_age_seconds"], (10800, 10801, 10802))
        self.assertEqual((d["reach_days"], d["settings"]["Storage"]["value"], d["service"]["active"],
                          d["service"]["config_changed_after_start"], d["usage"]["files"]), (31, None, True, False, 4))

    def test_systemds_own_flag_says_whether_the_journal_is_on_disk(self):
        # Record R13: /run/systemd/journal/flushed is there once the journal was moved to disk, gone after
        # `journalctl --relinquish-var` (also after a restart of the service), back after `journalctl --flush`.
        # The age alone read 150 s in the relinquished state: inside any limit that a quiet box needs.
        self.assertEqual(CE.JOURNAL_FLUSHED_FLAG, "/run/systemd/journal/flushed")
        self.assertIs(CE.d2_4(self.host(), {})["usage"]["flushed_to_disk"], True)
        os.remove(self.flag)
        d = CE.d2_4(self.host(), {})["usage"]
        self.assertIs(d["flushed_to_disk"], False)
        self.assertIn(d["on_disk_age_seconds"], (7, 8, 9))                   # the age is read on its own
        shutil.rmtree(os.path.join(self.root, "run/systemd/journal"))
        self.assertIs(CE.d2_4(self.host(), {})["usage"]["flushed_to_disk"], False)
        shutil.rmtree(os.path.join(self.root, "run"))
        self.assertIs(CE.d2_4(self.host(), {})["usage"]["flushed_to_disk"], False)

    def test_a_link_or_a_directory_where_the_flag_belongs_is_could_not_check(self):
        # systemd tests the path with access(), which follows links: a dangling link is absent for it.
        # Only an ordinary file is "true"; anything else there cannot be judged.
        real = self._w("/run/systemd/journal/real-file", "")
        for what in ("dangling link", "link to a real file", "directory"):
            with self.subTest(what=what):
                if os.path.lexists(self.flag):
                    (shutil.rmtree if os.path.isdir(self.flag) and not os.path.islink(self.flag) else os.remove)(self.flag)
                if what == "dangling link":
                    os.symlink("/nowhere", self.flag)
                elif what == "link to a real file":
                    os.symlink(real, self.flag)
                else:
                    os.mkdir(self.flag)
                d = CE.d2_4(self.host(), {})["usage"]
                self.assertEqual(d["flushed_to_disk"], R.COULD_NOT_CHECK)
                self.assertEqual(d["files"], 4)

    def test_a_journal_directory_that_is_a_link_makes_all_of_usage_could_not_check(self):
        keys = ("bytes", "files", "bytes_percent_of_max_use", "files_percent_of_max_files", "free_bytes",
                "free_percent", "other_directories", "newest_entry_on_disk", "on_disk_age_seconds", "flushed_to_disk")
        CN = {k: R.COULD_NOT_CHECK for k in keys}
        self.assertEqual(CE.d2_4(self.host(), {})["usage"]["files"], 4)                  # control: healthy stays healthy
        elsewhere = os.path.join(self.root, "elsewhere")
        for part in ("var/log/journal/" + self.MID, "var/log/journal", "var/log", "var"):
            with self.subTest(part=part):
                target = os.path.join(self.root, part)
                moved = target + ".moved"
                os.rename(target, moved)
                try:
                    os.symlink(moved, target)               # the link leads to a real, healthy-looking directory
                    self.assertEqual(CE.d2_4(self.host(), {})["usage"], CN)
                finally:
                    os.remove(target)
                    os.rename(moved, target)
        self.assertEqual(CE.d2_4(self.host(), {})["usage"]["files"], 4)

    def test_a_journal_directory_that_is_a_file_makes_all_of_usage_could_not_check(self):
        target = os.path.join(self.root, "var/log/journal", self.MID)
        shutil.rmtree(target)
        self._w("/var/log/journal/" + self.MID, "not a directory")
        d = CE.d2_4(self.host(), {})["usage"]
        self.assertEqual({v for v in d.values()}, {R.COULD_NOT_CHECK})

    @unittest.skipIf(os.geteuid() == 0, "root reads through any permission")
    def test_a_flag_that_cannot_be_looked_at_is_could_not_check_never_false(self):
        parent = os.path.dirname(self.flag)
        os.chmod(parent, 0)
        self.addCleanup(os.chmod, parent, 0o755)
        d = CE.d2_4(self.host(), {})["usage"]
        self.assertEqual(d["flushed_to_disk"], R.COULD_NOT_CHECK)
        self.assertEqual(d["files"], 4)
        os.chmod(parent, 0o755)
        os.remove(self.flag)
        os.rmdir(parent)
        self._w("/run/systemd/journal", "a file where a directory belongs")  # ENOTDIR: not "does not exist"
        self.assertEqual(CE.d2_4(self.host(), {})["usage"]["flushed_to_disk"], R.COULD_NOT_CHECK)

    def test_an_on_disk_journal_without_an_entry_or_that_cannot_be_read_has_no_age(self):
        CN = R.COULD_NOT_CHECK
        for answer, newest in (((0, "", ""), None), ((0, "\n", ""), None),               # measured: an empty directory, rc 0
                               ((1, "", "Failed to open"), CN), ((127, "", "not found"), CN),
                               ((0, "not json\n", ""), CN), ((0, _entry(1760000000) * 2, ""), CN),
                               ((0, '{"__REALTIME_TIMESTAMP": "0"}\n', ""), CN)):
            with self.subTest(answer=answer):
                self.outputs[self.disk_key] = answer
                d = CE.d2_4(self.host(), {})["usage"]
                self.assertEqual((d["newest_entry_on_disk"], d["on_disk_age_seconds"]), (newest, CN))
                self.assertEqual(d["files"], 4)                                         # the counts are still read

        def run(argv, timeout=60, fake=self.host()._run):
            if argv[:2] == ["journalctl", "-D"]:
                raise UnicodeDecodeError("utf-8", b"\xff", 0, 1, "invalid start byte")
            return fake(argv, timeout)
        d = CE.d2_4(CE.Host(self.root, run), {})["usage"]
        self.assertEqual((d["newest_entry_on_disk"], d["on_disk_age_seconds"], d["files"]), (CN, CN, 4))

    def test_an_on_disk_entry_later_than_the_clock_has_no_age(self):
        now = int(time.time())
        self.assertEqual(CE._CLOCK_STEP_MARGIN, 2)
        for ahead, want in ((0, (0, 1)), (2, (0,)), (60, (R.COULD_NOT_CHECK,)), (86400, (R.COULD_NOT_CHECK,))):
            with self.subTest(ahead=ahead):
                self.outputs[self.disk_key] = (0, _entry(now + ahead), "")
                d = CE.d2_4(self.host(), {})["usage"]
                self.assertIn(d["on_disk_age_seconds"], want)
                self.assertEqual(d["newest_entry_on_disk"], CE._iso(now + ahead))

    def test_the_oldest_and_the_newest_entry_are_read_by_one_grammar(self):
        seen = []
        real = CE._entry_time
        with mock.patch.object(CE, "_entry_time", lambda host, argv: seen.append(argv[1]) or real(host, argv)):
            CE.d2_4(self.host(), {})
        self.assertEqual(seen, ["-q"] * 5 + ["-D"])            # the journal, then two units for each of the two jobs

    def test_percent_is_only_ever_computed_from_two_counts(self):
        CN = R.COULD_NOT_CHECK
        self.assertEqual(CE._percent(1, 8), 12.5)
        for part, whole in ((1, 0), (1, None), (1, CN), (CN, 8), (None, 8), (True, 8), (1, True), (1, -8), (1.0, 8)):
            self.assertEqual(CE._percent(part, whole), CN, (part, whole))

    # ---- what the item may hold
    def test_no_machine_id_no_path_outside_the_settings_and_no_journal_text_in_the_item(self):
        self._w("/var/log/journal/ffffffffffffffffffffffffffffffff/system.journal", "y")
        out = json.dumps(CE.d2_4(self.host(), {}))
        self.assertNotIn(self.MID, out)
        self.assertNotIn("f" * 32, out)
        self.assertNotIn("s=abc", out)
        self.assertNotIn(self.root, out)
        self.assertNotIn("/var/log", out)
        self.assertIn('"newest_entry_on_disk": "2', out)                     # read, and still no id in the item

    def test_it_is_in_the_bundle(self):
        self.assertEqual(CE.collect(self.host(), self.KEY)["items"]["D2.4"]["status"], R.OBSERVED)


class TestD46StartTimes(Base):
    START = "Wed 2026-10-07 06:45:46 UTC"      # as `systemctl show -p ActiveEnterTimestamp --value` prints it
    START_ISO = "2026-10-07T06:45:46Z"
    BOOT = 1758448800                          # /proc/stat btime, seconds since the epoch

    def setUp(self):
        super().setUp()
        self.addCleanup(setattr, CE, "LAST_PASS_COLLECTED_AT", None)
        CE.LAST_PASS_COLLECTED_AT = None
        for unit in ("docker", "systemd-journald", *CE.SERVICE_FILES, self.APP, self.APP2):
            self._start(unit, self.START)
        self.outputs[("docker", "ps")] = (0, "a" * 64 + "\n", "")
        self.outputs[("docker", "inspect", "--format", "{{.State.StartedAt}}")] = (0, "2026-10-07T15:39:12.123456789Z\n", "")
        self._w("/proc/stat", f"cpu  1 2 3\nbtime {self.BOOT}\nprocesses 5\n")
        self.t0 = CE._epoch(self.START_ISO)
        for unit_file, script in (*CE.SERVICE_FILES.values(), CE.APP_BROKER_FILES):
            self._file("/etc/systemd/system/" + unit_file, "[Unit]\n")
            self._file(CE.AGENT_DIR + "/bin/" + script, "import os\n")

    def _start(self, unit, text):
        self.outputs[("systemctl", "show", unit, "-p", "ActiveEnterTimestamp", "--value")] = (0, text + "\n", "")

    def _file(self, rel, body, age=-3600):
        """A file whose modification time is `age` seconds after the services' start."""
        p = self._w(rel, body)
        os.utime(p, (self.t0 + age, self.t0 + age))
        return p

    APP = "hermes-app-broker@ads-audit"
    APP2 = "hermes-app-broker@ads-report"

    def test_every_start_is_reported_in_utc(self):
        d = CE.d4_6(self.host(), {})
        self.assertEqual(sorted(d["started_at"]), sorted(["boot", "docker", "gateway-container", "hermes-broker",
                                                          "hermes-docker-proxy", "systemd-journald", self.APP, self.APP2]))
        for unit in ("docker", "hermes-broker", "hermes-docker-proxy", self.APP, self.APP2):
            self.assertEqual(d["started_at"][unit], self.START_ISO)
        self.assertEqual(d["started_at"]["gateway-container"], "2026-10-07T15:39:12Z")
        self.assertEqual(d["started_at"]["boot"], CE._iso(self.BOOT))
        self.assertRegex(d["started_at"]["boot"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$")

    def test_the_journal_service_s_start_is_reported_and_compared_with_the_last_pass(self):
        self.outputs[("systemctl", "show", "systemd-journald", "-p", "ActiveEnterTimestamp", "--value")] = \
            (0, "Mon 2026-10-12 09:10:11 UTC\n", "")
        with mock.patch.object(CE, "LAST_PASS_COLLECTED_AT", "2026-10-12T13:39:00Z"):
            d = CE.d4_6(self.host(), {})
        self.assertEqual(d["started_at"]["systemd-journald"], "2026-10-12T09:10:11Z")
        self.assertIs(d["started_after_last_pass"]["systemd-journald"], False)
        self.assertNotIn("systemd-journald", d["files_newer_than_start"])
        self.assertEqual(set(d["started_at"]), set(CE.SERVICE_FILES) | {self.APP, self.APP2} | set(CE.OTHER_STARTS))
        self.assertNotIn("systemd-journald", d["files_checked"])

    def test_a_journal_service_start_that_cannot_be_read_is_could_not_check_for_that_entry_only(self):
        CE.LAST_PASS_COLLECTED_AT = "2026-10-07T10:00:00Z"
        self._start("systemd-journald", "")
        d = CE.d4_6(self.host(), {})
        self.assertEqual(d["started_at"]["systemd-journald"], R.COULD_NOT_CHECK)
        self.assertEqual(d["started_after_last_pass"]["systemd-journald"], R.COULD_NOT_CHECK)
        self.assertEqual(d["started_at"]["hermes-broker"], self.START_ISO)         # control: the others stand

    def test_without_a_baseline_nothing_is_compared(self):
        d = CE.d4_6(self.host(), {})
        self.assertIsNone(d["last_pass_collected_at"])
        self.assertEqual(set(d["started_after_last_pass"].values()), {None})

    def test_a_start_after_the_last_pass_is_marked(self):
        CE.LAST_PASS_COLLECTED_AT = "2026-10-07T10:00:00Z"
        d = CE.d4_6(self.host(), {})
        self.assertEqual(d["last_pass_collected_at"], "2026-10-07T10:00:00Z")
        self.assertEqual(d["started_after_last_pass"],
                         {"boot": False, "docker": False, "systemd-journald": False, "hermes-broker": False,
                          "hermes-docker-proxy": False, self.APP: False, self.APP2: False, "gateway-container": True})
        CE.LAST_PASS_COLLECTED_AT = self.START_ISO          # the same second is not "after"
        self.assertFalse(CE.d4_6(self.host(), {})["started_after_last_pass"]["hermes-broker"])

    def test_a_time_that_is_empty_or_not_utc_is_could_not_check(self):
        CE.LAST_PASS_COLLECTED_AT = "2026-10-07T10:00:00Z"
        for text in ("", "n/a", "Wed 2026-10-07 08:45:46 CEST", "2026-10-07 06:45:46", "Wed 2026-10-07 06:45:46 UTC extra"):
            self._start("hermes-broker", text)
            d = CE.d4_6(self.host(), {})
            self.assertEqual(d["started_at"]["hermes-broker"], R.COULD_NOT_CHECK, text)
            self.assertEqual(d["started_after_last_pass"]["hermes-broker"], R.COULD_NOT_CHECK, text)
            self.assertEqual(d["files_newer_than_start"]["hermes-broker"], R.COULD_NOT_CHECK, text)
            self.assertEqual(d["started_at"]["hermes-docker-proxy"], self.START_ISO)   # control: the others stand

    def test_systemctl_failing_is_could_not_check(self):
        self.outputs[("systemctl", "show", "docker", "-p", "ActiveEnterTimestamp", "--value")] = (1, self.START, "")
        self.assertEqual(CE.d4_6(self.host(), {})["started_at"]["docker"], R.COULD_NOT_CHECK)

    def test_no_gateway_or_an_odd_container_time_is_could_not_check(self):
        self.outputs[("docker", "inspect", "--format", "{{.State.StartedAt}}")] = (0, "0001-01-01T00:00:00+02:00\n", "")
        self.assertEqual(CE.d4_6(self.host(), {})["started_at"]["gateway-container"], R.COULD_NOT_CHECK)
        self.outputs[("docker", "ps")] = (0, "", "")
        self.assertEqual(CE.d4_6(self.host(), {})["started_at"]["gateway-container"], R.COULD_NOT_CHECK)

    def test_no_boot_time_is_could_not_check(self):
        self._w("/proc/stat", "cpu  1 2 3\n")
        self.assertEqual(CE.d4_6(self.host(), {})["started_at"]["boot"], R.COULD_NOT_CHECK)

    def test_files_older_than_the_start_are_not_listed(self):
        d = CE.d4_6(self.host(), {})
        self.assertEqual(d["files_newer_than_start"], {"hermes-broker": [], "hermes-docker-proxy": [], self.APP: [], self.APP2: []})
        self.assertEqual(d["files_checked"], {"hermes-broker": 2, "hermes-docker-proxy": 2, self.APP: 2, self.APP2: 2})

    def test_a_script_or_a_unit_file_changed_after_the_start_is_listed(self):
        self._file(CE.AGENT_DIR + "/bin/hermes-broker.py", "import os\n", age=60)
        self._file("/etc/systemd/system/hermes-app-broker@.service", "[Unit]\n", age=60)
        d = CE.d4_6(self.host(), {})["files_newer_than_start"]
        self.assertEqual(d, {"hermes-broker": ["hermes-broker.py"], "hermes-docker-proxy": [], self.APP: ["unit"],
                             self.APP2: ["unit"]})

    def test_a_file_changed_in_the_same_second_as_the_start_is_not_listed(self):
        self._file(CE.AGENT_DIR + "/bin/hermes-broker.py", "import os\n", age=0)
        self.assertEqual(CE.d4_6(self.host(), {})["files_newer_than_start"]["hermes-broker"], [])

    def test_an_import_inside_a_function_and_a_transitive_import_are_followed(self):
        b = CE.AGENT_DIR + "/bin/"
        self._file(b + "hermes-app-broker.py", "import os, app_lib as A\n\ndef f():\n    from lazy_lib import x\n")
        self._file(b + "app_lib.py", "import vault_lib\n")
        self._file(b + "vault_lib.py", "import json\n", age=60)
        self._file(b + "lazy_lib.py", "x = 1\n", age=60)
        self._file(b + "unrelated_lib.py", "y = 1\n", age=60)
        d = CE.d4_6(self.host(), {})
        self.assertEqual(d["files_newer_than_start"][self.APP], ["lazy_lib.py", "vault_lib.py"])
        self.assertEqual(d["files_checked"][self.APP], 5)       # the unit, the script and three modules

    def test_a_file_loaded_by_its_name_is_followed(self):
        b = CE.AGENT_DIR + "/bin/"
        self._file(b + "hermes-broker.py", 'import os\nP = os.path.join(HERE, "side-loaded.py")\n')
        self._file(b + "side-loaded.py", "z = 1\n", age=60)
        self.assertEqual(CE.d4_6(self.host(), {})["files_newer_than_start"]["hermes-broker"], ["side-loaded.py"])

    def test_a_missing_or_unparsable_script_costs_that_service_only(self):
        os.remove(os.path.join(self.root, CE.AGENT_DIR.lstrip("/"), "bin/hermes-broker.py"))
        self._file(CE.AGENT_DIR + "/bin/docker-create-proxy.py", "def broken(:\n")
        d = CE.d4_6(self.host(), {})
        self.assertEqual(d["files_newer_than_start"], {"hermes-broker": R.COULD_NOT_CHECK,
                                                       "hermes-docker-proxy": R.COULD_NOT_CHECK, self.APP: [], self.APP2: []})
        self.assertEqual(d["files_checked"]["hermes-broker"], R.COULD_NOT_CHECK)

    def test_each_service_is_paired_with_the_script_its_unit_runs(self):
        deploy = os.path.join(os.path.dirname(HERE), "deploy")
        for unit_file, script in (*CE.SERVICE_FILES.values(), CE.APP_BROKER_FILES):
            with open(os.path.join(deploy, unit_file)) as f:
                self.assertRegex(f.read(), r"(?m)^ExecStart=.*/opt/hermes-agent/bin/" + script.replace(".", r"\."), unit_file)

    def test_the_repos_own_app_broker_loads_what_review_8_named(self):
        loaded = CE._loaded_files(HERE, "hermes-app-broker.py")
        for name in ("hermes-app-broker.py", "app_lib.py", "vault_lib.py", "governance_lib.py", "client_audit_lib.py"):
            self.assertIn(name, loaded)
        self.assertNotIn("collect-review-evidence.py", loaded)

    def test_main_refuses_an_invalid_last_pass_collected_at(self):
        for bad in ("2026-10-07", "2026-10-07T16:21:22", "2026-10-07T16:21:22+00:00", "2026-13-40T00:00:00Z",
                    "2026-10-07T16:21:22Z\n", ""):
            out, err = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                rc = CE.main(["--fp-key-tty", "--last-pass-collected-at", bad], host=self.host(),
                             read_key=lambda: "11" * 32)
            self.assertEqual((rc, out.getvalue()), (2, ""), repr(bad))
            self.assertIn("--last-pass-collected-at", err.getvalue())
            self.assertIsNone(CE.LAST_PASS_COLLECTED_AT)

    def test_main_refuses_a_collected_at_written_with_full_width_digits(self):
        bad = "２０２６-10-07T16:21:22Z"
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = CE.main(["--fp-key-tty", "--last-pass-collected-at", bad], host=self.host(),
                         read_key=lambda: "11" * 32)
        self.assertEqual((rc, out.getvalue()), (2, ""))
        self.assertIn("--last-pass-collected-at", err.getvalue())

    def test_a_systemd_or_docker_time_with_full_width_digits_is_could_not_check(self):
        self._start("hermes-broker", "Wed ２０２６-10-07 06:45:46 UTC")
        self.assertEqual(CE.d4_6(self.host(), {})["started_at"]["hermes-broker"], R.COULD_NOT_CHECK)
        self.outputs[("docker", "inspect", "--format", "{{.State.StartedAt}}")] = \
            (0, "２０２６-10-07T15:39:12Z\n", "")
        self.assertEqual(CE.d4_6(self.host(), {})["started_at"]["gateway-container"], R.COULD_NOT_CHECK)

    def test_a_script_too_deep_to_parse_is_could_not_check_for_that_service_only(self):
        self._file(CE.AGENT_DIR + "/bin/hermes-broker.py", "x = " + "1+" * 200000 + "1\n")
        d = CE.d4_6(self.host(), {})
        self.assertEqual(d["files_newer_than_start"]["hermes-broker"], R.COULD_NOT_CHECK)
        self.assertEqual(d["files_newer_than_start"]["hermes-docker-proxy"], [])

    def test_main_passes_a_valid_last_pass_collected_at_and_does_not_leak_it(self):
        def run(*extra):
            out = io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
                rc = CE.main(["--fp-key-tty", *extra], host=self.host(), read_key=lambda: "11" * 32)
            return rc, json.loads(out.getvalue())["items"]
        rc, items = run("--last-pass-collected-at", "2026-10-07T10:00:00Z")
        self.assertEqual(items["D4.6"]["status"], R.OBSERVED)
        self.assertEqual(items["D4.6"]["data"]["last_pass_collected_at"], "2026-10-07T10:00:00Z")
        self.assertTrue(items["D4.6"]["data"]["started_after_last_pass"]["gateway-container"])
        self.assertIsNone(CE.LAST_PASS_COLLECTED_AT)
        _, items = run()
        self.assertIsNone(items["D4.6"]["data"]["last_pass_collected_at"])

    def test_the_bundle_carries_both_new_items(self):
        items = CE.collect(self.host(), self.KEY)["items"]
        self.assertEqual(items["D4.6"]["status"], R.OBSERVED)
        self.assertEqual(items["D1.7"]["status"], R.COULD_NOT_CHECK)      # no sshd in this fake host


def _e(**fields):
    """One journal entry as `journalctl -o json` prints it."""
    return json.dumps(fields) + "\n"


class TestSearchJournal(Base):
    SECRET = "sk-or-v1-" + "0123456789abcdef" * 4
    ARGV = ["journalctl", "-o", "json", "--all", "--no-pager", "-q"]

    def _search(self, text, secrets=(), redactor=True, rc=0, err="", on_message=None):
        # A plain Host with a fake runner, not FakeHost: from Task 2 on FakeHost rewrites a line
        # that is not a JSON object into an entry, and these tests need the text as given.
        host = CE.Host(self.root, lambda argv, timeout=60: (rc, text, err))
        red = CE.context(host, self.KEY)["redactor"] if redactor else None
        return CE._search_journal(host, self.ARGV, list(secrets), red, on_message=on_message)

    def test_the_constants_are_the_design_s(self):
        self.assertEqual(CE.JOURNAL_ALL_FIELDS, ["-o", "json", "--all", "--no-pager", "-q"])
        self.assertEqual(CE.CID_SKIP_FIELDS, frozenset({
            "__CURSOR", "__REALTIME_TIMESTAMP", "__MONOTONIC_TIMESTAMP", "__SEQNUM", "__SEQNUM_ID",
            "_SOURCE_REALTIME_TIMESTAMP", "_SOURCE_MONOTONIC_TIMESTAMP", "_BOOT_ID", "_MACHINE_ID",
            "_STREAM_ID", "_SYSTEMD_INVOCATION_ID", "_PID", "_UID", "_GID", "_AUDIT_LOGINUID",
            "_AUDIT_SESSION", "_SYSTEMD_OWNER_UID"}))
        for name in ("MESSAGE", "_CMDLINE", "COMMAND", "_COMM", "_EXE", "CPU_USAGE_NSEC", "MAX_USE"):
            self.assertNotIn(name, CE.CID_SKIP_FIELDS)
        self.assertTrue(all(n.startswith("_") for n in CE.CID_SKIP_FIELDS))     # journald-written only

    def test_a_secret_in_the_command_line_field_is_counted(self):
        c = self._search(_e(MESSAGE="Started.", _CMDLINE=f"curl -H {self.SECRET}"), [self.SECRET])
        self.assertEqual((c["known_secret_hits"], c["entries"], c["fields"]), (1, 1, 2))

    def test_a_credential_pattern_in_sudo_s_command_field_is_counted(self):
        c = self._search(_e(MESSAGE="x", COMMAND=f"/usr/bin/env GOOGLE_ADS_REFRESH_TOKEN={TOKEN} true"))
        self.assertEqual((c["pattern_hits"], c["credential_text_lines"]), (1, 1))

    def test_a_value_that_is_not_text_arrives_as_bytes_and_is_searched(self):
        c = self._search(_e(MESSAGE=list(f"leak {self.SECRET} \xff".encode("latin-1"))), [self.SECRET])
        self.assertEqual((c["known_secret_hits"], c["undecodable_characters"]), (1, 1))

    def test_a_secret_at_the_end_of_a_very_long_field_is_counted(self):
        c = self._search(_e(MESSAGE="x" * 100000 + self.SECRET), [self.SECRET])
        self.assertEqual(c["known_secret_hits"], 1)

    def test_a_field_set_twice_is_searched_in_both_values(self):
        c = self._search(_e(MESSAGE=["a " + self.SECRET, list(("b " + self.SECRET).encode())]), [self.SECRET])
        self.assertEqual((c["known_secret_hits"], c["fields"]), (2, 1))

    def test_a_customer_id_in_a_clock_field_is_not_counted_and_in_the_command_line_is(self):
        entry = dict(__REALTIME_TIMESTAMP="1760123456789000", _SOURCE_REALTIME_TIMESTAMP="1761234567890123",
                     _AUDIT_LOGINUID="1234567890", MESSAGE="ok")
        self.assertEqual(self._search(_e(**entry))["customer_id_lines"], 0)
        self.assertEqual(self._search(_e(**entry, _CMDLINE="tool --customer 1234567890"))["customer_id_lines"], 1)
        self.assertEqual(self._search(_e(**entry, MAX_USE="1234567890"))["customer_id_lines"], 1)   # a program can write it

    def test_a_secret_in_a_skipped_field_is_still_counted(self):
        c = self._search(_e(_STREAM_ID=self.SECRET, MESSAGE="ok"), [self.SECRET])
        self.assertEqual(c["known_secret_hits"], 1)

    def test_without_a_redactor_the_two_line_counts_stay_zero(self):
        c = self._search(_e(MESSAGE=f"GOOGLE_ADS_REFRESH_TOKEN={TOKEN} 1234567890"), redactor=False)
        self.assertEqual((c["pattern_hits"], c["credential_text_lines"], c["customer_id_lines"]), (1, 0, 0))

    def test_the_size_is_the_text_read_and_the_keys_are_closed(self):
        text = _e(MESSAGE="Started.") * 3
        c = self._search(text)
        self.assertEqual(set(c), set(CE.SEARCH_COUNTS))
        self.assertEqual((c["scanned_characters"], c["entries"], c["fields"]), (len(text), 3, 3))

    def test_json_escaping_does_not_hide_a_value(self):
        secret = 'pa"ss\\word/1234'
        c = self._search(_e(MESSAGE="x " + secret), [secret])
        self.assertEqual(c["known_secret_hits"], 1)

    def test_each_message_is_handed_to_the_caller(self):
        seen = []
        self._search(_e(MESSAGE="one\ntwo", _COMM="x") + _e(MESSAGE="three"), on_message=seen.append)
        self.assertEqual(seen, ["one\ntwo", "three"])

    def test_an_entry_that_does_not_parse_makes_the_search_could_not_check(self):
        for bad in ("not json\n", "[1, 2]\n", '{"MESSAGE": "cut\n'):
            with self.subTest(bad=bad), self.assertRaises(CE.CouldNotCheck) as cm:
                self._search(_e(MESSAGE="ok") + bad)
            self.assertIn("did not parse", str(cm.exception))

    def test_a_field_printed_as_null_makes_the_search_could_not_check(self):
        with self.assertRaises(CE.CouldNotCheck) as cm:
            self._search(_e(MESSAGE=None))
        self.assertIn("not printed", str(cm.exception))

    def test_a_failed_or_warned_read_is_could_not_check_in_fixed_words(self):
        for rc, err, want in ((1, "Failed to open /var/log/journal/0123", "journalctl exited 1"),
                              (0, "Journal file /var/log/journal/0123/x corrupted", "wrote a warning on stderr")):
            with self.subTest(rc=rc), self.assertRaises(CE.CouldNotCheck) as cm:
                self._search(_e(MESSAGE="ok"), rc=rc, err=err)
            self.assertIn(want, str(cm.exception))
            self.assertNotIn("/var/log", str(cm.exception))

    def test_a_repeated_key_in_one_entry_makes_the_search_could_not_check(self):
        with self.assertRaises(CE.CouldNotCheck) as cm:
            self._search('{"MESSAGE": "a", "MESSAGE": "b"}\n')
        self.assertIn("did not parse", str(cm.exception))

    def test_a_line_longer_than_the_bound_makes_the_search_could_not_check(self):
        code = "import json; print(json.dumps({'MESSAGE': 'x' * 1000}))"
        with mock.patch.object(CE._RealStream, "MAX_LINE", 100):
            host = CE.Host()
            host._real = False          # past the root check; the stream is still the real one
            host.stream = lambda argv, timeout=60: CE._RealStream([sys.executable, "-c", code], 30)
            with self.assertRaises(CE.CouldNotCheck) as cm:
                CE._search_journal(host, self.ARGV, [])
        self.assertIn("did not parse", str(cm.exception))

    def test_an_error_in_the_loop_closes_the_stream_at_once(self):
        class Stream:
            rc, err = 0, ""
            closed = False
            def __iter__(self):
                def gen():
                    try:
                        yield _e(MESSAGE="one")
                        yield _e(MESSAGE="two")
                    finally:
                        Stream.closed = True
                self.gen = gen()            # the test keeps it: garbage collection cannot close it
                return self.gen
        stream = Stream()

        class H(CE.Host):
            def stream(self, argv, timeout=60):
                return stream

        def boom(_m):
            raise RuntimeError("boom")
        try:
            CE._search_journal(H(self.root, lambda argv, timeout=60: (0, "", "")), self.ARGV, [], on_message=boom)
        except RuntimeError:
            self.assertTrue(Stream.closed)      # still inside the except block: the traceback is alive
        else:
            self.fail("no error")

    def test_blank_lines_are_not_entries(self):
        self.assertEqual(self._search("\n" + _e(MESSAGE="ok") + "\n")["entries"], 1)


class TestStream(unittest.TestCase):
    def _real(self, code, timeout=30):
        return CE.Host().stream([sys.executable, "-c", code], timeout)

    def test_the_35_day_size_passes_through_the_real_stream_line_by_line(self):
        """185,000 lines of 1,000 characters: M1 of 2026-10-13 scaled to 35 days (about 184 MB)."""
        s = self._real("import sys\nline = 'x' * 999 + '\\n'\nfor i in range(185000): sys.stdout.write(line)", timeout=120)
        n = size = 0
        for line in s:
            n += 1; size += len(line)
        self.assertEqual((n, size, s.rc, s.err), (185000, 185000000, 0, ""))

    def test_a_byte_that_is_not_text_becomes_one_replacement_character(self):
        s = self._real("import sys; sys.stdout.buffer.write(b'a\\xffb\\n')")
        self.assertEqual((list(s), s.rc), (["a\ufffdb\n"], 0))

    def test_stderr_and_a_non_zero_exit_are_kept(self):
        s = self._real("import sys; print('out'); sys.stderr.write('warn'); sys.exit(3)")
        self.assertEqual((list(s), s.rc, s.err), (["out\n"], 3, "warn"))

    def test_a_command_that_does_not_exist_is_127(self):
        s = CE.Host().stream(["/nonexistent/hermes-test-binary"], 5)
        self.assertEqual((list(s), s.rc), ([], 127))

    def test_a_timeout_ends_the_lines_and_reads_as_124(self):
        s = self._real("import time; print('first', flush=True); time.sleep(60)", timeout=2)
        t0 = time.monotonic()
        self.assertEqual((list(s), s.rc), (["first\n"], 124))
        self.assertLess(time.monotonic() - t0, 30)

    def test_a_child_that_ignores_sigterm_is_killed_after_the_grace(self):
        code = ("import signal, time\nsignal.signal(signal.SIGTERM, lambda s, f: None)\n"
                "print('first', flush=True)\ntime.sleep(60)")
        s = self._real(code, timeout=1)
        t0 = time.monotonic()
        with mock.patch.object(CE._RealStream, "TERM_GRACE", 2):
            self.assertEqual((list(s), s.rc), (["first\n"], 124))
        self.assertLess(time.monotonic() - t0, 30)

    def test_a_warning_after_a_lot_of_blank_stderr_is_not_blank(self):
        s = self._real("import sys; sys.stderr.write(' ' * 70000 + 'warn')")
        list(s)
        self.assertTrue(s.err.strip())

    def test_a_piece_of_a_long_line_is_yielded_without_a_newline(self):
        with mock.patch.object(CE._RealStream, "MAX_LINE", 100):
            s = self._real("print('x' * 1000)")
            pieces = list(s)
        self.assertGreater(len(pieces), 1)
        self.assertTrue(pieces[0].endswith("x") and pieces[-1].endswith("\n"))

    def test_only_a_newline_splits_a_fake_runner_s_text(self):
        line = '{"MESSAGE": "a\u2028b\rc"}\n'
        s = CE.Host("/", lambda argv, timeout=60: (0, line + line, "")).stream(["x"])
        self.assertEqual(list(s), [line, line])

    def test_a_fake_runner_s_text_is_streamed_as_lines(self):
        s = CE.Host("/", lambda argv, timeout=60: (0, "a\nb\n", "w")).stream(["x"])
        self.assertEqual((list(s), s.rc, s.err), (["a\n", "b\n"], 0, "w"))


class TestOtherJournals(Base):
    MID, OTHER = "a" * 32, "b" * 32

    def setUp(self):
        super().setUp()
        self._w("/etc/machine-id", self.MID + "\n")
        self._w(f"/var/log/journal/{self.MID}/system.journal", "x" * 10)
        self._w(f"/var/log/journal/{self.OTHER}/system.journal", "y" * 4096)

    def test_only_the_other_directory_is_searched_and_only_counts_come_back(self):
        self.outputs[("journalctl", "-D", "/var/log/journal/" + self.OTHER)] = \
            (0, _e(MESSAGE="boot", _CMDLINE="tool --customer 1234567890"), "")
        host = self.host()
        d = CE.other_journals(host, CE.context(host, self.KEY), [])
        self.assertEqual((d["directories"], d["files"], d["bytes"]), (1, 1, 4096))
        self.assertEqual(d["search"]["customer_id_lines"], 1)
        self.assertEqual(set(d["search"]), set(CE.SEARCH_COUNTS))
        self.assertEqual([c[:3] for c in host.calls if c[0] == "journalctl"],
                         [["journalctl", "-D", "/var/log/journal/" + self.OTHER]])
        self.assertNotIn(self.OTHER, json.dumps(d)); self.assertNotIn(self.MID, json.dumps(d))

    def test_no_other_directory_is_zero_and_nothing_is_read(self):
        shutil.rmtree(os.path.join(self.root, "var/log/journal", self.OTHER))
        host = self.host()
        d = CE.other_journals(host, CE.context(host, self.KEY), [])
        self.assertEqual((d["directories"], d["files"], d["search"]["entries"]), (0, 0, 0))

    def test_a_linked_directory_is_not_followed(self):
        os.symlink("/etc", os.path.join(self.root, "var/log/journal", "c" * 32))
        host = self.host()
        self.outputs[("journalctl", "-D")] = (0, _e(MESSAGE="boot"), "")
        d = CE.other_journals(host, CE.context(host, self.KEY), [])
        self.assertEqual((d["directories"], d["skipped_entries"]), (1, 1))

    def test_a_read_that_warns_is_could_not_check_without_the_directory_s_name(self):
        self.outputs[("journalctl", "-D")] = (0, "", f"Journal file /var/log/journal/{self.OTHER}/x is truncated")
        host = self.host()
        with self.assertRaises(CE.CouldNotCheck) as cm:
            CE.other_journals(host, CE.context(host, self.KEY), [])
        self.assertNotIn(self.OTHER, str(cm.exception))

    def _search(self):
        host = self.host()
        return CE.other_journals(host, CE.context(host, self.KEY), []), host

    def _refused(self, words):
        host = self.host()
        with self.assertRaises(CE.CouldNotCheck) as cm:
            CE.other_journals(host, CE.context(host, self.KEY), [])
        self.assertIn(words, str(cm.exception))
        for text in (self.OTHER, self.MID, self.root):
            self.assertNotIn(text, str(cm.exception))

    def test_a_directory_with_a_sub_directory_a_link_or_a_foreign_file_is_could_not_check(self):
        self.outputs[("journalctl", "-D")] = (0, _e(MESSAGE="boot"), "")
        other = os.path.join(self.root, "var/log/journal", self.OTHER)
        for make in (lambda: os.mkdir(os.path.join(other, "sub")),
                     lambda: os.symlink("/etc/passwd", os.path.join(other, "l.journal")),
                     lambda: open(os.path.join(other, "notes.txt"), "w").close()):
            for n in os.listdir(other):
                if n != "system.journal":
                    p = os.path.join(other, n)
                    os.rmdir(p) if os.path.isdir(p) and not os.path.islink(p) else os.remove(p)
            make()
            self._refused("a file journalctl does not read")

    def test_a_directory_with_files_and_no_entry_read_is_could_not_check(self):
        self.outputs[("journalctl", "-D")] = (0, "", "")
        self._refused("no entry was read from a directory that holds files")

    def test_only_machine_directories_are_searched_the_rest_are_counted(self):
        j = os.path.join(self.root, "var/log/journal")
        os.symlink("/etc", os.path.join(j, "c" * 32))
        os.mkdir(os.path.join(j, "remote")); os.mkdir(os.path.join(j, self.MID + ".ns"))
        self._w("/var/log/journal/stray.txt", "x")
        self.outputs[("journalctl", "-D")] = (0, _e(MESSAGE="boot"), "")
        d, host = self._search()
        self.assertEqual((d["directories"], d["skipped_entries"]), (1, 4))
        self.assertEqual([c[2] for c in host.calls if c[0] == "journalctl"], ["/var/log/journal/" + self.OTHER])

    def test_a_link_above_the_journal_directory_is_a_value_error(self):
        real = tempfile.mkdtemp(); self.addCleanup(shutil.rmtree, real, True)
        shutil.move(os.path.join(self.root, "var/log"), os.path.join(real, "log"))
        os.symlink(os.path.join(real, "log"), os.path.join(self.root, "var/log"))
        with self.assertRaises(ValueError):
            self._search()

    def test_the_mode_prints_nothing_and_exits_2_when_the_secrets_cannot_be_loaded(self):
        self.outputs[("find",)] = (0, CE.AGENT_DIR + "/.env.ghost\n", "")
        self.outputs[("journalctl", "-D")] = (0, _e(MESSAGE="boot"), "")
        with contextlib.redirect_stdout(io.StringIO()) as out, contextlib.redirect_stderr(io.StringIO()) as err:
            rc = CE.main(["--other-journals"], host=self.host())
        self.assertEqual((rc, out.getvalue()), (2, ""))
        self.assertNotIn(self.OTHER, err.getvalue())

    def test_the_mode_prints_nothing_and_exits_2_when_the_search_raises(self):
        self.outputs[("journalctl", "-D")] = (0, "", f"Journal file /var/log/journal/{self.OTHER}/x is truncated")
        with contextlib.redirect_stdout(io.StringIO()) as out, contextlib.redirect_stderr(io.StringIO()) as err:
            rc = CE.main(["--other-journals"], host=self.host())
        self.assertEqual((rc, out.getvalue()), (2, ""))
        self.assertNotIn(self.OTHER, err.getvalue())

    def test_the_other_journals_mode_prints_counts_and_needs_no_key(self):
        self.outputs[("journalctl", "-D")] = (0, _e(MESSAGE="boot"), "")
        with contextlib.redirect_stdout(io.StringIO()) as out:
            rc = CE.main(["--other-journals"], host=self.host())
        d = json.loads(out.getvalue())
        self.assertEqual((rc, d["kind"], d["directories"], d["search"]["entries"]), (0, "other-journals", 1, 1))
        self.assertNotIn(self.OTHER, out.getvalue())


if __name__ == "__main__":
    unittest.main()
