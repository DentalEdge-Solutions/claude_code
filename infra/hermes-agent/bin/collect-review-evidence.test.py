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


if __name__ == "__main__":
    unittest.main()
