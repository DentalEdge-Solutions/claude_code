#!/usr/bin/env python3
import json, os, sys, tempfile, unittest
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import client_audit_lib as L
import package_lib as PK


def w(path, body, mode=None):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(body)
    if mode is not None:
        os.chmod(path, mode)
    return path


class Base(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.reg = w(os.path.join(self.d, "clients.json"), json.dumps({"clients": {
            "acme-dental": {"customer_id": "123-456-7890", "status": "active", "project": "claude_google_ads"},
            "old-dental": {"customer_id": "1112223333", "status": "retired", "project": "claude_google_ads"},
            "pilot": {"customer_id": "4445556666", "status": "active", "mutation_target": "dormant_pilot",
                      "project": "claude_google_ads"}}}))


class TestCredEnv(Base):
    def test_parses_like_the_shell_parser(self):
        p = w(os.path.join(self.d, "c"), 'GOOGLE_ADS_REFRESH_TOKEN="1//abc"\r\n'
                                         "export GOOGLE_ADS_CLIENT_ID='cid'\n# c\nOTHER=x\n"
                                         "GOOGLE_ADS_CREDENTIAL_ROLE=read\n")
        self.assertEqual(L.load_cred_env(p), {"GOOGLE_ADS_REFRESH_TOKEN": "1//abc",
                                               "GOOGLE_ADS_CLIENT_ID": "cid",
                                               "GOOGLE_ADS_CREDENTIAL_ROLE": "read"})


class TestSecretFile(Base):
    def test_wrong_mode_refused(self):
        p = w(os.path.join(self.d, "c"), "x", 0o644)
        with self.assertRaises(L.PrecheckError):
            L.check_secret_file(p, uid=os.geteuid(), mode=0o400)

    def test_right_owner_and_mode_pass(self):
        p = w(os.path.join(self.d, "c"), "x", 0o400)
        L.check_secret_file(p, uid=os.geteuid(), mode=0o400)

    def test_missing_refused(self):
        with self.assertRaises(L.PrecheckError):
            L.check_secret_file(os.path.join(self.d, "nope"), uid=os.geteuid())


class TestAnthropicKey(Base):
    def test_states(self):
        self.assertEqual(L.anthropic_key_state(w(os.path.join(self.d, "a"), "ANTHROPIC_API_KEY=sk-ant-api03-x\n")), "real")
        self.assertEqual(L.anthropic_key_state(w(os.path.join(self.d, "b"), "ANTHROPIC_API_KEY=dummy-key-this-wave\n")), "dummy")
        self.assertEqual(L.anthropic_key_state(w(os.path.join(self.d, "c"), "OTHER=1\n")), "missing")
        self.assertEqual(L.anthropic_key_state(os.path.join(self.d, "none")), "missing")


class TestEligibleClient(Base):
    def test_active_client_resolves_with_digit_id(self):
        rec = L.eligible_client("pilot", self.reg)
        self.assertEqual((rec["slug"], rec["customer_id"]), ("pilot", "4445556666"))

    def test_dashed_or_non_ten_digit_id_refused_without_naming_it(self):
        # vault-write's validate_customer_id rejects dashes: refuse now, not after the spend (M7).
        with self.assertRaises(L.PrecheckError) as cm:
            L.eligible_client("acme-dental", self.reg)          # "123-456-7890" in the registry
        self.assertNotIn("123-456-7890", str(cm.exception)); self.assertNotIn("1234567890", str(cm.exception))
        for bad in ("12345678901", "123456789", 1234567890, None, "12345 67890"):
            reg = w(os.path.join(self.d, "r2.json"), json.dumps({"clients": {
                "x-dental": {"customer_id": bad, "status": "active"}}}))
            with self.assertRaises(L.PrecheckError, msg=repr(bad)):
                L.eligible_client("x-dental", reg)

    def test_dormant_pilot_is_allowed(self):
        self.assertEqual(L.eligible_client("pilot", self.reg)["slug"], "pilot")

    def test_retired_unknown_and_malformed_refused(self):
        for slug in ("old-dental", "nobody", "../x", "A B", ""):
            with self.assertRaises(L.PrecheckError, msg=slug):
                L.eligible_client(slug, self.reg)

    def test_refusal_message_never_carries_a_customer_id(self):
        with self.assertRaises(L.PrecheckError) as cm:
            L.eligible_client("old-dental", self.reg)
        self.assertNotIn("1112223333", str(cm.exception))


class TestPackage(Base):
    def _install(self, app, files):
        m = PK.build_manifest("claude_google_ads", "r", "a" * 40, files)
        for p, b in files.items():
            w(os.path.join(app, p), b.decode())
        with open(os.path.join(app, PK.MANIFEST_NAME), "wb") as f:
            f.write(PK.manifest_bytes(m))
        return PK.manifest_hash(m)

    def test_matching_package_passes_and_tampered_file_refused(self):
        app = os.path.join(self.d, "app")
        pin = self._install(app, {"code/a.py": b"print(1)\n"})
        L.package_matches(app, pin)
        w(os.path.join(app, "code/a.py"), "print(2)\n")
        with self.assertRaises(L.PrecheckError):
            L.package_matches(app, pin)

    def test_wrong_pin_refused(self):
        app = os.path.join(self.d, "app")
        self._install(app, {"code/a.py": b"x"})
        with self.assertRaises(L.PrecheckError):
            L.package_matches(app, "0" * 64)


class TestDirsAndScans(Base):
    def test_reset_dir_empties_and_is_0700(self):
        p = os.path.join(self.d, "audit-data/acme")
        w(os.path.join(p, "old.json"), "{}")
        L.reset_dir(p, uid=os.geteuid(), gid=os.getegid())
        self.assertEqual(os.listdir(p), [])
        self.assertEqual(os.stat(p).st_mode & 0o777, 0o700)

    def test_error_files_and_json_count(self):
        p = os.path.join(self.d, "ad")
        w(os.path.join(p, "a.json"), "{}"); w(os.path.join(p, "b.ERROR.txt"), "boom")
        self.assertEqual(L.error_files(p), ["b.ERROR.txt"])
        self.assertEqual(L.json_count(p), 1)

    def test_others_named(self):
        self.assertEqual(L.others_named("Report for Old-Dental ...", "acme-dental", ["acme-dental", "old-dental"]),
                         ["old-dental"])
        self.assertEqual(L.others_named("acme-dental only", "acme-dental", ["acme-dental", "old-dental"]), [])


class TestLock(Base):
    def test_second_holder_refused(self):
        p = os.path.join(self.d, "lock")
        with L.AuditLock(p):
            with self.assertRaises(L.PrecheckError) as cm:
                with L.AuditLock(p):
                    pass
            self.assertIn("another audit is running", str(cm.exception))
        with L.AuditLock(p):                               # released after the first exits
            pass


if __name__ == "__main__":
    unittest.main()
