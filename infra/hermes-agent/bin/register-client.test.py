#!/usr/bin/env python3
"""register-client.py: the only way a client enters clients.json, and it can never install an
empty or broken registry (2026-09-29 incident)."""
import hashlib, json, os, subprocess, sys, tempfile, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(HERE, "register-client.py")
CID = "9876543210"
FP = hashlib.sha1(CID.encode()).hexdigest()[:12]
OLD = {"clients": {"pilot": {"project": "claude_google_ads", "customer_id": "1112223333", "currency": "USD",
                             "timezone": "America/New_York", "status": "active",
                             "mutation_target": "dormant_pilot"}}}


class TestRegisterClient(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.reg = os.path.join(self.tmp.name, "clients.json")
        self.cid = os.path.join(self.tmp.name, "cid")
        self.write_reg(json.dumps(OLD, indent=2) + "\n")
        with open(self.cid, "w") as f:
            f.write(CID + "\n")

    def tearDown(self):
        self.tmp.cleanup()

    def write_reg(self, text):
        with open(self.reg, "w") as f:
            f.write(text)

    def raw(self):
        with open(self.reg, "rb") as f:
            return f.read()

    def run_tool(self, slug="new-client", fp=FP):
        return subprocess.run([sys.executable, SCRIPT, "--slug=" + slug, "--fingerprint=" + fp,
                               "--registry", self.reg, "--cid-file", self.cid],
                              capture_output=True, text=True)

    def assert_refused(self, r, before):
        self.assertNotEqual(r.returncode, 0)
        self.assertEqual(self.raw(), before, "registry must be byte-identical after a refusal")
        self.assertNotIn(CID, r.stdout + r.stderr)
        self.assertNotIn("Traceback", r.stderr)
        self.assertEqual(len(r.stderr.strip().splitlines()), 1)
        self.assertFalse(os.path.exists(self.reg + ".new"))

    def test_happy_path(self):
        r = self.run_tool()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.strip(), "2 ['active', 'active'] 1")
        d = json.load(open(self.reg))["clients"]
        self.assertEqual(d["new-client"], {"project": "claude_google_ads", "customer_id": CID, "currency": "USD",
                                           "timezone": "America/New_York", "status": "active"})
        self.assertNotIn("mutation_target", d["new-client"])
        self.assertIn("pilot", d)
        self.assertEqual(oct(os.stat(self.reg).st_mode & 0o777), "0o640")
        self.assertFalse(os.path.exists(self.reg + ".new"))
        self.assertNotIn(CID, r.stdout + r.stderr)

    def test_empty_registry_refused(self):
        self.write_reg("")
        self.assert_refused(self.run_tool(), b"")

    def test_missing_registry_refused(self):
        os.remove(self.reg)
        r = self.run_tool()
        self.assertNotEqual(r.returncode, 0)
        self.assertFalse(os.path.exists(self.reg))
        self.assertNotIn("Traceback", r.stderr)
        self.assertNotIn(CID, r.stdout + r.stderr)

    def test_unparsable_registry_refused(self):
        self.write_reg('{"clients": {')
        self.assert_refused(self.run_tool(), b'{"clients": {')

    def test_registry_without_clients_object_refused(self):
        for body in ("{}", '{"clients": []}', "[]"):
            self.write_reg(body)
            self.assert_refused(self.run_tool(), body.encode())

    def test_duplicate_slug_refused(self):
        self.assert_refused(self.run_tool(slug="pilot"), self.raw())

    def test_duplicate_id_refused(self):
        d = json.loads(json.dumps(OLD))
        d["clients"]["other"] = {"customer_id": CID, "status": "active"}
        self.write_reg(json.dumps(d))
        self.assert_refused(self.run_tool(), self.raw())

    def test_wrong_fingerprint_refused(self):
        self.assert_refused(self.run_tool(fp="0" * 12), self.raw())

    def test_bad_slug_refused(self):
        for slug in ("Bad", "-x", "a b", "x" * 65, ""):
            self.assert_refused(self.run_tool(slug=slug), self.raw())

    def test_bad_cid_file_refused(self):
        for body in ("", "12ab\n", "123\n"):
            with open(self.cid, "w") as f:
                f.write(body)
            self.assert_refused(self.run_tool(), self.raw())


if __name__ == "__main__":
    unittest.main()
