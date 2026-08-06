import json, os, subprocess, sys, tempfile, unittest
HERE = os.path.dirname(os.path.abspath(__file__))
def _reg(tmp, clients):
    d=os.path.join(tmp,"_registry"); os.makedirs(d,exist_ok=True)
    p=os.path.join(d,"clients.json")
    with open(p,"w") as f:
        json.dump({"clients":clients}, f)
    return p

class T(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.mkdtemp(); os.environ["VAULT_ROOT"]=self.tmp
        self.reg=_reg(self.tmp, {"acme-dental":{"project":"claude_google_ads",
            "customer_id":"6764977319","status":"offboarded"}})
        v=os.path.join(self.tmp,"acme-dental","audits"); os.makedirs(v,exist_ok=True)
        with open(os.path.join(v,"x-audit.md"),"w") as f:
            f.write("data")
        self.exp=tempfile.mkdtemp()
    def _run(self, *extra, client="acme-dental"):
        return subprocess.run([sys.executable, os.path.join(HERE,"vault-purge.py"),
            "--client",client,"--export-to",self.exp,"--registry",self.reg,*extra],
            capture_output=True, text=True, env={**os.environ})
    def test_export_then_delete_then_log(self):
        r=self._run("--confirm"); self.assertEqual(r.returncode,0,r.stderr)
        self.assertFalse(os.path.exists(os.path.join(self.tmp,"acme-dental")))   # deleted
        self.assertTrue(any(f.endswith(".tar.gz") for f in os.listdir(self.exp)))  # exported
        log=os.path.join(self.tmp,"_governance","deletions.log")
        with open(log) as f:
            self.assertIn("acme-dental", f.read())
    def test_refuses_without_confirm(self):
        self.assertEqual(self._run().returncode, 2)
        self.assertTrue(os.path.exists(os.path.join(self.tmp,"acme-dental")))     # untouched
    def test_refuses_active_without_force(self):
        reg=_reg(self.tmp, {"live":{"project":"p","customer_id":"1","status":"active"}})
        os.makedirs(os.path.join(self.tmp,"live"),exist_ok=True)
        r=subprocess.run([sys.executable, os.path.join(HERE,"vault-purge.py"),"--client","live",
            "--export-to",self.exp,"--registry",reg,"--confirm"], capture_output=True, text=True, env={**os.environ})
        self.assertEqual(r.returncode, 2)

if __name__ == "__main__": unittest.main()
