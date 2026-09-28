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


class TestNoSecret(unittest.TestCase):
    def test_raises_when_a_secret_appears(self):
        with self.assertRaises(RuntimeError):
            R.assert_no_secret("bundle ... " + TOKEN, [TOKEN])

    def test_control_clean_text_passes(self):
        R.assert_no_secret("bundle " + R.sha12(TOKEN), [TOKEN])


if __name__ == "__main__":
    unittest.main()
