import json, os, importlib.util, subprocess, sys, tempfile, unittest
HERE = os.path.dirname(os.path.abspath(__file__))
def _reg(tmp, clients):
    d = os.path.join(tmp, "_registry"); os.makedirs(d, exist_ok=True)
    p = os.path.join(d, "clients.json")
    with open(p, "w") as f:
        json.dump({"clients": clients}, f)
    return p

class T(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(); os.environ["VAULT_ROOT"] = self.tmp
        self.reg = _reg(self.tmp, {"acme-dental":{"project":"claude_google_ads",
            "customer_id":"1234567890","status":"active"}})
        self.audit = os.path.join(self.tmp,"draft.md")
        with open(self.audit, "w") as f:
            f.write("> DRAFT\n## Overall\nok\n")
        self.metrics = os.path.join(self.tmp,"m.json")
        with open(self.metrics, "w") as f:
            json.dump({"spend":400.0,"customer_id":"1234567890",
                "collected_at":"2026-08-06T00:00:00Z"}, f)
    def _run(self, client, ts="2026-08-06_10-00-00"):
        return subprocess.run([sys.executable, os.path.join(HERE,"vault-write.py"),
            "--client",client,"--audit-file",self.audit,"--metrics-file",self.metrics,
            "--ts",ts,"--registry",self.reg], capture_output=True, text=True, env={**os.environ})
    def test_writes_land_in_vault(self):
        r = self._run("acme-dental"); self.assertEqual(r.returncode,0,r.stderr)
        v = os.path.join(self.tmp,"acme-dental")
        self.assertTrue(os.path.exists(os.path.join(v,"audits","2026-08-06_10-00-00-audit.md")))
        self.assertTrue(os.path.exists(os.path.join(v,"metrics","2026-08-06_10-00-00.json")))
        with open(os.path.join(v,"timeline.md")) as f:
            self.assertIn("2026-08-06_10-00-00", f.read())
        self.assertTrue(os.path.exists(os.path.join(v,"index.md")))
    def test_bad_slug_refused(self):
        self.assertEqual(self._run("../escape").returncode, 2)
    def test_unknown_client_refused(self):
        self.assertEqual(self._run("ghost").returncode, 2)

if __name__ == "__main__": unittest.main()
