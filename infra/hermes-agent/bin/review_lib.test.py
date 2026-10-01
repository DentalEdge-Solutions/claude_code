#!/usr/bin/env python3
import hashlib, json, os, sys, tempfile, unittest
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import review_lib as R

TOKEN = "1//0gFAKEREFRESHTOKENabcdefghijklmnop"
CLIENT_ID = "123-fake.apps.googleusercontent.com"


def cred(d, name, body):
    p = os.path.join(d, name)
    with open(p, "w", newline="") as f:
        f.write(body)
    return p


class TestSha12(unittest.TestCase):
    def test_matches_audit_credential_access_convention(self):
        self.assertEqual(R.sha12("abc"), hashlib.sha1(b"abc").hexdigest()[:12])


class TestRedactor(unittest.TestCase):
    def setUp(self):
        d = tempfile.mkdtemp(); self.clients = os.path.join(d, "clients.json")
        with open(self.clients, "w") as f:
            json.dump({"clients": {"acme-dental": {"customer_id": "1234567890"},
                                   "acme": {"customer_id": "5555555555"}}}, f)
        self.r = R.Redactor.from_clients_json(self.clients)

    def test_slug_replaced_on_word_boundaries_only(self):
        self.assertEqual(self.r.text("log/acme-dental.jsonl and acme and acmex"),
                         "log/<client>.jsonl and <client> and acmex")

    def test_slug_joined_by_hyphen_or_underscore_is_redacted(self):
        self.assertEqual(self.r.text("live-gate-acme-dental-20260901 and x_acme_y"),
                         "live-gate-<client>-20260901 and x_<client>_y")

    def test_customer_ids_plain_and_dashed(self):
        out = self.r.text("id 1234567890 or 123-456-7890")
        self.assertNotIn("1234567890", out); self.assertNotIn("123-456-7890", out)
        self.assertEqual(out.count("cid:" + R.sha12("1234567890")), 2)

    def test_obj_redacts_keys_and_nested_values(self):
        out = self.r.obj({"acme-dental": ["x acme-dental", {"k": "1234567890"}], "n": 3})
        self.assertEqual(out, {"<client>": ["x <client>", {"k": "cid:" + R.sha12("1234567890")}], "n": 3})

    def test_firing_control_an_empty_redactor_redacts_nothing(self):
        self.assertIn("acme-dental", R.Redactor([], []).text("acme-dental"))

    def test_missing_or_malformed_clients_json_raises(self):
        with self.assertRaises(ValueError):
            R.Redactor.from_clients_json(self.clients + ".missing")
        with open(self.clients, "w") as f:
            f.write("{not json")
        with self.assertRaises(ValueError):
            R.Redactor.from_clients_json(self.clients)

    def test_dashed_customer_id_in_registry_redacts_both_forms(self):
        # E4: clients.json can itself store a dashed customer_id. Both the dashed and
        # the plain-digit spelling must be redacted, not just the literal one on file.
        d = tempfile.mkdtemp(); clients = os.path.join(d, "clients.json")
        with open(clients, "w") as f:
            json.dump({"clients": {"acme": {"customer_id": "123-456-7890"}}}, f)
        r = R.Redactor.from_clients_json(clients)
        out = r.text("id 1234567890 or 123-456-7890")
        self.assertNotIn("1234567890", out)
        self.assertNotIn("123-456-7890", out)
        self.assertEqual(out.count("cid:" + R.sha12("1234567890")), 2)


class TestCredentials(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()

    def test_parse_returns_fingerprints_and_role(self):
        p = cred(self.d, ".env.gaw", f"GOOGLE_ADS_CREDENTIAL_ROLE=write\nGOOGLE_ADS_REFRESH_TOKEN={TOKEN}\n"
                                     f"GOOGLE_ADS_CLIENT_ID={CLIENT_ID}\n")
        info, secrets = R.parse_credential_file(p)
        self.assertEqual((info["role"], info["refresh_token_sha12"], info["client_id_sha12"]),
                         ("write", R.sha12(TOKEN), R.sha12(CLIENT_ID)))
        self.assertIn(TOKEN, secrets)

    def test_role_from_filename_when_undeclared(self):
        info, _ = R.parse_credential_file(cred(self.d, ".env.ga", f"GOOGLE_ADS_REFRESH_TOKEN={TOKEN}\n"))
        self.assertEqual(info["role"], "read")

    def test_crlf_and_quotes_fingerprint_identically(self):
        a, _ = R.parse_credential_file(cred(self.d, "a.gaw", f"GOOGLE_ADS_REFRESH_TOKEN={TOKEN}\n"))
        b, _ = R.parse_credential_file(cred(self.d, "b.gaw", f'GOOGLE_ADS_REFRESH_TOKEN="{TOKEN}"\r\n'))
        self.assertEqual(a["refresh_token_sha12"], b["refresh_token_sha12"])

    def test_export_prefix_fingerprints_the_same_as_plain(self):
        # A4: a sourced-shell-style credential file (`export KEY=VALUE`) must fingerprint
        # identically to the plain `KEY=VALUE` form.
        plain, _ = R.parse_credential_file(cred(self.d, "plain.gaw", f"GOOGLE_ADS_REFRESH_TOKEN={TOKEN}\n"))
        exported, _ = R.parse_credential_file(
            cred(self.d, "exported.gaw", f"export GOOGLE_ADS_REFRESH_TOKEN={TOKEN}\n"))
        self.assertEqual(plain["refresh_token_sha12"], exported["refresh_token_sha12"])
        self.assertEqual(exported["refresh_token_sha12"], R.sha12(TOKEN))

    def test_credential_set_drops_paths_and_sorts(self):
        infos = [{"path": "/b", "role": "write", "refresh_token_sha12": "b", "client_id_sha12": "c"},
                 {"path": "/a", "role": "read", "refresh_token_sha12": "a", "client_id_sha12": "c"}]
        self.assertEqual(R.credential_set(infos),
                         [{"role": "read", "refresh_token_sha12": "a", "client_id_sha12": "c"},
                          {"role": "write", "refresh_token_sha12": "b", "client_id_sha12": "c"}])


class TestLooksLikeCredentialText(unittest.TestCase):
    def test_bare_refresh_token_prefix_matches(self):
        self.assertTrue(R.looks_like_credential_text(f"leaked: {TOKEN}\n"))

    def test_key_value_shape_matches_without_a_real_value(self):
        self.assertTrue(R.looks_like_credential_text("GOOGLE_ADS_CLIENT_SECRET=whatever\n"))

    def test_control_ordinary_text_does_not_match(self):
        self.assertFalse(R.looks_like_credential_text("just some notes about the deploy\n"))


class TestFingerprint(unittest.TestCase):
    def test_deterministic_and_order_independent(self):
        a = R.fingerprint({"x": [1, 2], "y": {"b": 1, "a": 2}})
        b = R.fingerprint({"y": {"a": 2, "b": 1}, "x": [1, 2]})
        self.assertEqual(a, b); self.assertTrue(a["complete"])

    def test_any_component_change_changes_it(self):
        self.assertNotEqual(R.fingerprint({"x": "a"})["fingerprint"], R.fingerprint({"x": "b"})["fingerprint"])

    def test_could_not_check_component_marks_incomplete(self):
        self.assertFalse(R.fingerprint({"x": {R.COULD_NOT_CHECK: "unreadable"}})["complete"])


NFT_BASE = """table inet filter {
\tchain input {
\t\ttype filter hook input priority 0; policy drop;
\t\tcounter packets 12 bytes 840
\t\ticmp type echo-request accept
\t\ttcp dport 22 accept
\t}
\tchain forward {
\t\ttype filter hook forward priority 0; policy drop;
\t\toifname "br-__BR__" accept
\t}
\tchain output {
\t\ttype filter hook output priority 0; policy accept;
\t}
}
table ip filter {
\tchain DOCKER {
\t\tcounter packets 3 bytes 180
\t\tip daddr __CONTAINERS__ accept
\t}
\tchain DOCKER-USER {
\t\treturn
\t}
\tchain DOCKER-FORWARD {
\t\tjump DOCKER-ISOLATION-STAGE-1
\t\tjump DOCKER
\t}
}
"""

IPTABLES_BASE = """# Generated by iptables-save __TS__
*filter
:INPUT ACCEPT [__N1__:__N2__]
:FORWARD DROP [__N1__:__N2__]
:OUTPUT ACCEPT [__N1__:__N2__]
:DOCKER - [0:0]
:DOCKER-USER - [0:0]
:DOCKER-FORWARD - [0:0]
-A FORWARD -j DOCKER-USER
-A FORWARD -j DOCKER-FORWARD
-A DOCKER-USER -j RETURN
-A DOCKER-FORWARD -j DOCKER
-A DOCKER -d __IP__ -j ACCEPT
COMMIT
# Completed on __TS__
"""


def _nft(br, containers):
    return NFT_BASE.replace("__BR__", br).replace("__CONTAINERS__", containers)


def _iptables(ts, n1, n2, ip):
    return (IPTABLES_BASE.replace("__TS__", ts).replace("__N1__", str(n1))
            .replace("__N2__", str(n2)).replace("__IP__", ip))


class TestNormalizeRuleset(unittest.TestCase):
    def test_nft_counters_br_id_and_docker_chain_contents_normalise_identically(self):
        a = _nft("a1b2c3d4e5f6", "172.17.0.2")
        b = _nft("00112233aabb", "172.17.0.9")
        # also perturb a counter value directly so the defensive counter-strip is exercised
        b = b.replace("counter packets 12 bytes 840", "counter packets 99 bytes 7331")
        self.assertEqual(R.normalize_ruleset(a, "nft"), R.normalize_ruleset(b, "nft"))

    def test_nft_control_rule_added_to_input_changes_result(self):
        a = _nft("a1b2c3d4e5f6", "172.17.0.2")
        b = a.replace("tcp dport 22 accept", "tcp dport 22 accept\n\t\tudp dport 41641 accept")
        self.assertNotEqual(R.normalize_ruleset(a, "nft"), R.normalize_ruleset(b, "nft"))

    def test_nft_rule_added_to_docker_user_changes_result(self):
        a = _nft("a1b2c3d4e5f6", "172.17.0.2")
        b = a.replace("chain DOCKER-USER {\n\t\treturn",
                       "chain DOCKER-USER {\n\t\ttcp dport 41641 accept\n\t\treturn")
        self.assertNotEqual(R.normalize_ruleset(a, "nft"), R.normalize_ruleset(b, "nft"))

    def test_iptables_timestamps_counters_and_docker_rules_normalise_identically(self):
        a = _iptables("Mon Sep 28 00:00:00 2026", 0, 0, "172.17.0.2")
        b = _iptables("Mon Sep 28 12:34:56 2026", 99, 7331, "172.17.0.9")
        self.assertEqual(R.normalize_ruleset(a, "iptables"), R.normalize_ruleset(b, "iptables"))

    def test_iptables_control_rule_added_to_input_changes_result(self):
        a = _iptables("Mon Sep 28 00:00:00 2026", 0, 0, "172.17.0.2")
        b = a.replace("-A FORWARD -j DOCKER-USER",
                       "-A INPUT -p tcp --dport 8080 -j ACCEPT\n-A FORWARD -j DOCKER-USER")
        self.assertNotEqual(R.normalize_ruleset(a, "iptables"), R.normalize_ruleset(b, "iptables"))

    # ---- fix round 1, item 1 (Critical): fail2ban's live ban list must not be hashed ----

    def test_nft_f2b_chain_and_jump_absent_vs_present_with_different_bans_normalise_identically(self):
        no_jail = ("table inet filter {\n"
                    "\tchain input {\n"
                    "\t\ttype filter hook input priority 0; policy drop;\n"
                    "\t\ttcp dport 22 accept\n"
                    "\t}\n"
                    "}\n")
        jail_a = ("table inet filter {\n"
                   "\tchain input {\n"
                   "\t\ttype filter hook input priority 0; policy drop;\n"
                   "\t\ttcp dport 22 accept\n"
                   "\t\tjump f2b-sshd\n"
                   "\t}\n"
                   "\tchain f2b-sshd {\n"
                   "\t\tip saddr 203.0.113.5 drop\n"
                   "\t\tip saddr 198.51.100.9 drop\n"
                   "\t}\n"
                   "}\n")
        jail_b = ("table inet filter {\n"
                  "\tchain input {\n"
                  "\t\ttype filter hook input priority 0; policy drop;\n"
                  "\t\ttcp dport 22 accept\n"
                  "\t\tjump f2b-sshd\n"
                  "\t}\n"
                  "\tchain f2b-sshd {\n"
                  "\t\tip saddr 10.20.30.40 drop\n"
                  "\t}\n"
                  "}\n")
        normalized = R.normalize_ruleset(no_jail, "nft")
        self.assertEqual(normalized, R.normalize_ruleset(jail_a, "nft"))
        self.assertEqual(normalized, R.normalize_ruleset(jail_b, "nft"))

    def test_nft_f2b_control_rule_added_to_input_changes_result(self):
        a = ("table inet filter {\n"
             "\tchain input {\n"
             "\t\ttype filter hook input priority 0; policy drop;\n"
             "\t\ttcp dport 22 accept\n"
             "\t\tjump f2b-sshd\n"
             "\t}\n"
             "\tchain f2b-sshd {\n"
             "\t\tip saddr 203.0.113.5 drop\n"
             "\t}\n"
             "}\n")
        b = a.replace("tcp dport 22 accept", "tcp dport 22 accept\n\t\tudp dport 41641 accept")
        self.assertNotEqual(R.normalize_ruleset(a, "nft"), R.normalize_ruleset(b, "nft"))

    def test_nft_f2b_table_contents_normalise_identically(self):
        def full(set_elements, extra_sshd_rule, tail_rule):
            return ("table ip filter {\n"
                    "\tchain input {\n"
                    "\t\ttcp dport 22 accept\n"
                    "\t}\n"
                    "}\n"
                    "table inet f2b-table {\n"
                    "\tset addr-set-sshd {\n"
                    "\t\ttype ipv4_addr\n"
                    f"\t\telements = {{ {set_elements} }}\n"
                    "\t}\n"
                    "\tchain f2b-sshd {\n"
                    "\t\ttype filter hook input priority -1; policy accept;\n"
                    "\t\tip saddr @addr-set-sshd drop\n"
                    f"{extra_sshd_rule}"
                    "\t}\n"
                    "}\n"
                    "table ip nat {\n"
                    "\tchain POSTROUTING {\n"
                    f"\t\t{tail_rule}\n"
                    "\t}\n"
                    "}\n")
        a = full("1.2.3.4, 5.6.7.8", "", "masquerade")
        b = full("9.9.9.9", "\t\tip saddr 8.8.8.8 drop\n", "masquerade")
        self.assertEqual(R.normalize_ruleset(a, "nft"), R.normalize_ruleset(b, "nft"))

        # control: a rule change in the table AFTER f2b-table must still be detected —
        # proves the brace-depth skip stops at f2b-table's own closing brace, not later.
        c = full("1.2.3.4, 5.6.7.8", "", "masquerade comment weird")
        self.assertNotEqual(R.normalize_ruleset(a, "nft"), R.normalize_ruleset(c, "nft"))

    def test_iptables_f2b_chain_rules_and_target_normalise_identically(self):
        def ruleset(ts, decl_and_rules):
            return (f"# Generated by iptables-save v1.8.9 on {ts}\n"
                     "*filter\n"
                     ":INPUT ACCEPT [0:0]\n"
                     ":FORWARD ACCEPT [0:0]\n"
                     ":OUTPUT ACCEPT [0:0]\n"
                     f"{decl_and_rules}"
                     "-A INPUT -p tcp -m tcp --dport 22 -j ACCEPT\n"
                     "COMMIT\n"
                     f"# Completed on {ts}\n")
        no_jail = ruleset("Mon Sep 28 00:00:00 2026", "")
        jail_a = ruleset("Mon Sep 28 06:00:00 2026",
                          ":f2b-sshd - [0:0]\n"
                          "-A INPUT -p tcp -m tcp --dport 22 -j f2b-sshd\n"
                          "-A f2b-sshd -s 203.0.113.5/32 -j REJECT --reject-with icmp-port-unreachable\n")
        jail_b = ruleset("Mon Sep 28 12:00:00 2026",
                          ":f2b-sshd - [0:0]\n"
                          "-A INPUT -p tcp -m tcp --dport 22 -j f2b-sshd\n"
                          "-A f2b-sshd -s 10.20.30.40/32 -j REJECT --reject-with icmp-port-unreachable\n"
                          "-A f2b-sshd -s 44.55.66.77/32 -j REJECT --reject-with icmp-port-unreachable\n")
        normalized = R.normalize_ruleset(no_jail, "iptables")
        self.assertEqual(normalized, R.normalize_ruleset(jail_a, "iptables"))
        self.assertEqual(normalized, R.normalize_ruleset(jail_b, "iptables"))

    def test_iptables_f2b_control_rule_added_to_input_changes_result(self):
        a = ("# Generated by iptables-save v1.8.9 on Mon Sep 28 00:00:00 2026\n"
             "*filter\n"
             ":INPUT ACCEPT [0:0]\n"
             ":FORWARD ACCEPT [0:0]\n"
             ":OUTPUT ACCEPT [0:0]\n"
             ":f2b-sshd - [0:0]\n"
             "-A INPUT -p tcp -m tcp --dport 22 -j f2b-sshd\n"
             "-A INPUT -p tcp -m tcp --dport 22 -j ACCEPT\n"
             "-A f2b-sshd -s 203.0.113.5/32 -j REJECT --reject-with icmp-port-unreachable\n"
             "COMMIT\n"
             "# Completed on Mon Sep 28 00:00:00 2026\n")
        b = a.replace("-A INPUT -p tcp -m tcp --dport 22 -j ACCEPT",
                       "-A INPUT -p tcp --dport 8080 -j ACCEPT\n"
                       "-A INPUT -p tcp -m tcp --dport 22 -j ACCEPT")
        self.assertNotEqual(R.normalize_ruleset(a, "iptables"), R.normalize_ruleset(b, "iptables"))

    def test_unknown_kind_raises(self):
        with self.assertRaises(ValueError):
            R.normalize_ruleset("anything", "nftables")


class TestNoSecret(unittest.TestCase):
    def test_raises_when_a_secret_appears(self):
        with self.assertRaises(RuntimeError):
            R.assert_no_secret("bundle ... " + TOKEN, [TOKEN])

    def test_control_clean_text_passes(self):
        R.assert_no_secret("bundle " + R.sha12(TOKEN), [TOKEN])


class TestKeyedFingerprints(unittest.TestCase):
    KEY = bytes.fromhex("11" * 32)

    def test_hmac12_is_keyed_and_12_hex(self):
        a, b = R.hmac12(self.KEY, "1234567890"), R.hmac12(bytes.fromhex("22" * 32), "1234567890")
        self.assertEqual(len(a), 12); self.assertNotEqual(a, b)
        self.assertNotEqual(a, R.sha12("1234567890"))

    def test_redactor_uses_the_key_for_cids_only(self):
        red = R.Redactor(["acme"], ["123-456-7890"], fp_key=self.KEY)
        out = red.text("acct 1234567890 and 123-456-7890")
        self.assertEqual(out.count("cid:" + R.hmac12(self.KEY, "1234567890")), 2)
        self.assertNotIn(R.sha12("1234567890"), out)

    def test_no_key_keeps_sha12(self):
        self.assertIn(R.sha12("1234567890"), R.Redactor([], ["1234567890"]).text("1234567890"))

    def test_load_fp_key(self):
        self.assertEqual(R.load_fp_key(" " + "ab" * 32 + "\n"), bytes.fromhex("ab" * 32))
        for bad in ("", "ab" * 31, "zz" * 32, "ab" * 33):
            with self.assertRaises(ValueError):
                R.load_fp_key(bad)

    def test_key_id(self):
        self.assertEqual(len(R.key_id(self.KEY)), 8)


if __name__ == "__main__":
    unittest.main()
