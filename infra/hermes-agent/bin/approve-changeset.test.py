import datetime, importlib.util, json, os, subprocess, sys, tempfile, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import changeset_lib as C

def _load(name, filename):
    spec = importlib.util.spec_from_file_location(name, os.path.join(HERE, filename))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

P = _load("propose_changeset", "propose-changeset.py")
A = _load("approve_changeset", "approve-changeset.py")
NOW = datetime.datetime(2026, 8, 12, 10, 15, 0, tzinfo=datetime.timezone.utc)

REG = """version: 1

projects:
  claude_google_ads:
    workdir: /projects/claude_google_ads
    mutate_execute:
      runner: /opt/ads-venv/bin/python3
      script_dir: code
      allow:
        - mutate_campaign_negative
      caps:
        actions_per_changeset: 25
        actions_per_client_day: 100
        applies_per_client_day: 5
        approval_ttl_hours: 24
"""

class T(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        os.environ["VAULT_ROOT"] = self.tmp
        d = os.path.join(self.tmp, "_registry"); os.makedirs(d)
        self.clients = os.path.join(d, "clients.json")
        with open(self.clients, "w") as f:
            json.dump({"clients": {"acme-dental": {
                "project": "claude_google_ads", "customer_id": "1234567890",
                "status": "active"}}}, f)
        self.projects = os.path.join(self.tmp, "projects.yaml")
        with open(self.projects, "w") as f:
            f.write(REG)
        src = os.path.join(self.tmp, "in.json")
        with open(src, "w") as f:
            json.dump({"actions": [{"type": "add_campaign_negative",
                                    "campaign_id": "22233344455",
                                    "keyword": "free consultation",
                                    "match_type": "PHRASE"}]}, f)
        self.cs = P.propose("acme-dental", src, NOW, registry=self.clients, projects=self.projects)
        self.vault = os.path.join(self.tmp, "acme-dental")

    def test_approval_records_digest_and_expiry(self):
        rec = A.approve("acme-dental", self.cs["changeset_id"], "erick", NOW,
                        registry=self.clients, projects=self.projects)
        self.assertEqual(rec["sha256"],
                         C.file_digest(C.changeset_path(self.vault, self.cs["changeset_id"])))
        self.assertEqual(rec["expires_at"], "2026-08-13T10:15:00Z")

    def test_approval_verifies_after_write(self):
        A.approve("acme-dental", self.cs["changeset_id"], "erick", NOW,
                  registry=self.clients, projects=self.projects)
        digest = C.file_digest(C.changeset_path(self.vault, self.cs["changeset_id"]))
        self.assertEqual(
            C.verify_approval(self.vault, self.cs["changeset_id"], digest, NOW)["operator"], "erick")

    def test_tampered_changeset_refused_at_approve(self):
        p = C.changeset_path(self.vault, self.cs["changeset_id"])
        with open(p, "w") as f:
            json.dump({"changeset_id": self.cs["changeset_id"], "client": "acme-dental",
                       "project": "claude_google_ads", "customer_id": "1234567890",
                       "created_at": "2026-08-12T10:15:00Z",
                       "actions": [{"type": "set_campaign_budget", "campaign_id": "1",
                                    "keyword": "x", "match_type": "PHRASE"}]}, f)
        with self.assertRaises(ValueError):
            A.approve("acme-dental", self.cs["changeset_id"], "erick", NOW,
                      registry=self.clients, projects=self.projects)

    def test_missing_changeset_refused(self):
        with self.assertRaises(ValueError):
            A.approve("acme-dental", "20260812-999999-deadbeef", "erick", NOW,
                      registry=self.clients, projects=self.projects)

    def test_bad_changeset_id_refused(self):
        with self.assertRaises(ValueError):
            A.approve("acme-dental", "../../etc/passwd", "erick", NOW,
                      registry=self.clients, projects=self.projects)

    def test_bad_operator_refused(self):
        with self.assertRaises(ValueError):
            A.approve("acme-dental", self.cs["changeset_id"], "rm -rf /", NOW,
                      registry=self.clients, projects=self.projects)

    def test_cli_success_exit0(self):
        out = subprocess.run(
            [sys.executable, os.path.join(HERE, "approve-changeset.py"),
             "--client", "acme-dental", "--changeset", self.cs["changeset_id"],
             "--operator", "erick", "--registry", self.clients, "--projects", self.projects],
            capture_output=True, text=True, env={**os.environ})
        self.assertEqual(out.returncode, 0)

    def test_cli_bad_operator_exit2(self):
        out = subprocess.run(
            [sys.executable, os.path.join(HERE, "approve-changeset.py"),
             "--client", "acme-dental", "--changeset", self.cs["changeset_id"],
             "--operator", "a b", "--registry", self.clients, "--projects", self.projects],
            capture_output=True, text=True, env={**os.environ})
        self.assertEqual(out.returncode, 2)

if __name__ == "__main__":
    unittest.main()
