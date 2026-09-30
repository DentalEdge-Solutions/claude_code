#!/usr/bin/env python3
"""register-client.py: the only way a client enters clients.json, and it can never install an
empty or broken registry (2026-09-29 incident)."""
import hashlib, importlib.util, json, os, subprocess, sys, tempfile, unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(HERE, "register-client.py")
spec = importlib.util.spec_from_file_location("register_client", SCRIPT)
RC = importlib.util.module_from_spec(spec); spec.loader.exec_module(RC)
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

    def assert_refused(self, r, before, why):
        self.assertNotEqual(r.returncode, 0)
        self.assertIn(why, r.stderr)
        if before is not None:
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
        self.assert_refused(self.run_tool(), b"", "registry is empty")

    def test_missing_registry_refused(self):
        os.remove(self.reg)
        r = self.run_tool()
        self.assert_refused(r, None, "registry unreadable")
        self.assertFalse(os.path.exists(self.reg))

    def test_unparsable_registry_refused(self):
        self.write_reg('{"clients": {')
        self.assert_refused(self.run_tool(), b'{"clients": {', "registry does not parse")

    def test_registry_without_clients_object_refused(self):
        for body in ("{}", '{"clients": []}', "[]"):
            self.write_reg(body)
            self.assert_refused(self.run_tool(), body.encode(), "no 'clients' object")

    def test_duplicate_slug_refused(self):
        self.assert_refused(self.run_tool(slug="pilot"), self.raw(), "slug already registered")

    def test_duplicate_id_refused(self):
        d = json.loads(json.dumps(OLD))
        d["clients"]["other"] = {"customer_id": CID, "status": "active"}
        self.write_reg(json.dumps(d))
        self.assert_refused(self.run_tool(), self.raw(), "customer id already registered")

    def test_wrong_fingerprint_refused(self):
        self.assert_refused(self.run_tool(fp="0" * 12), self.raw(), "does not match its fingerprint")

    def test_bad_slug_refused(self):
        for slug in ("Bad", "-x", "a b", "x" * 65, ""):
            self.assert_refused(self.run_tool(slug=slug), self.raw(), "bad slug")

    def test_bad_cid_file_refused(self):
        for body in ("", "12ab\n", "123\n"):
            with open(self.cid, "w") as f:
                f.write(body)
            self.assert_refused(self.run_tool(), self.raw(), "10-digit id")

    def in_process(self):
        before = self.raw()
        with self.assertRaises(Exception):
            RC.register("new-client", FP, self.reg, self.cid)
        self.assertEqual(self.raw(), before)
        self.assertFalse(os.path.exists(self.reg + ".new"))

    def test_reparse_count_mismatch_refused_and_cleaned_up(self):
        real = json.load
        calls = []

        def fake_load(f):
            calls.append(1)
            d = real(f)
            d["clients"].pop("new-client", None)         # the re-parse "loses" the new entry
            return d
        with mock.patch.object(RC.json, "load", fake_load):
            self.in_process()
        self.assertTrue(calls)

    def test_chown_failure_leaves_registry_and_no_new_file(self):
        boom = mock.Mock(side_effect=KeyError("hermes"))
        with mock.patch.object(RC.os, "geteuid", lambda: 0), mock.patch.object(RC.grp, "getgrnam", boom):
            self.in_process()
        boom.assert_called()

    def test_summary_survives_odd_entries_after_the_swap(self):
        d = json.loads(json.dumps(OLD))
        d["clients"]["odd"] = "not-a-dict"
        d["clients"]["nostatus"] = {"customer_id": "5556667777", "status": None}
        self.write_reg(json.dumps(d))
        r = self.run_tool()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertNotIn("nothing changed", r.stdout + r.stderr)
        self.assertNotIn("Traceback", r.stderr)
        self.assertIn("new-client", json.load(open(self.reg))["clients"])

    def test_new_file_is_created_exclusively_owner_only(self):
        with open(self.reg + ".new", "w") as f:
            f.write("stale")
        r = self.run_tool()                              # a stale .new is refused, registry untouched
        self.assertEqual(r.returncode, 1)
        self.assertEqual(self.raw(), json.dumps(OLD, indent=2).encode() + b"\n")


if __name__ == "__main__":
    unittest.main()
