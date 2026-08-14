import datetime, importlib.util, json, os, subprocess, sys, tempfile, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

def _load(name, filename):
    spec = importlib.util.spec_from_file_location(name, os.path.join(HERE, filename))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

P = _load("propose_changeset", "propose-changeset.py")
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
        actions_per_changeset: 2
        actions_per_client_day: 100
        applies_per_client_day: 5
        approval_ttl_hours: 24
"""

def _action(**kw):
    a = {"type": "add_campaign_negative", "campaign_id": "22233344455",
         "keyword": "free consultation", "match_type": "PHRASE"}
    a.update(kw)
    return a

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

    def _actions_file(self, actions):
        p = os.path.join(self.tmp, "in.json")
        with open(p, "w") as f:
            json.dump({"actions": actions}, f)
        return p

    def test_fills_identity_from_resolver(self):
        cs = P.propose("acme-dental", self._actions_file([_action()]), NOW,
                       registry=self.clients, projects=self.projects)
        self.assertEqual(cs["customer_id"], "1234567890")
        self.assertEqual(cs["client"], "acme-dental")
        self.assertEqual(cs["project"], "claude_google_ads")
        self.assertEqual(cs["created_at"], "2026-08-12T10:15:00Z")

    def test_changeset_id_shape_and_uniqueness(self):
        a = P.propose("acme-dental", self._actions_file([_action()]), NOW,
                      registry=self.clients, projects=self.projects)
        b = P.propose("acme-dental", self._actions_file([_action()]), NOW,
                      registry=self.clients, projects=self.projects)
        self.assertRegex(a["changeset_id"], r"^\d{8}-\d{6}-[0-9a-f]{8}$")
        self.assertNotEqual(a["changeset_id"], b["changeset_id"])

    def test_writes_canonical_bytes_to_vault(self):
        import changeset_lib as C
        cs = P.propose("acme-dental", self._actions_file([_action()]), NOW,
                       registry=self.clients, projects=self.projects)
        path = C.changeset_path(os.path.join(self.tmp, "acme-dental"), cs["changeset_id"])
        with open(path, "rb") as f:
            self.assertEqual(f.read(), C.canonical_bytes(cs))

    def test_operator_supplied_identity_fields_refused(self):
        p = os.path.join(self.tmp, "bad.json")
        with open(p, "w") as f:
            json.dump({"actions": [_action()], "customer_id": "9999999999"}, f)
        with self.assertRaises(ValueError):
            P.propose("acme-dental", p, NOW, registry=self.clients, projects=self.projects)

    def test_over_cap_refused(self):
        with self.assertRaises(ValueError):
            P.propose("acme-dental", self._actions_file([_action()] * 3), NOW,
                      registry=self.clients, projects=self.projects)

    def test_bad_action_refused(self):
        with self.assertRaises(ValueError):
            P.propose("acme-dental", self._actions_file([_action(type="set_budget")]), NOW,
                      registry=self.clients, projects=self.projects)

    def test_unknown_client_refused(self):
        with self.assertRaises(KeyError):
            P.propose("nope", self._actions_file([_action()]), NOW,
                      registry=self.clients, projects=self.projects)

    def test_cli_bad_slug_exit2(self):
        out = subprocess.run(
            [sys.executable, os.path.join(HERE, "propose-changeset.py"),
             "--client", "../etc", "--from", self._actions_file([_action()]),
             "--registry", self.clients, "--projects", self.projects],
            capture_output=True, text=True, env={**os.environ})
        self.assertEqual(out.returncode, 2)

    def test_cli_from_directory_exit2(self):
        d = os.path.join(self.tmp, "adir")
        os.makedirs(d)
        out = subprocess.run(
            [sys.executable, os.path.join(HERE, "propose-changeset.py"),
             "--client", "acme-dental", "--from", d,
             "--registry", self.clients, "--projects", self.projects],
            capture_output=True, text=True, env={**os.environ})
        self.assertEqual(out.returncode, 2)
        self.assertEqual(out.stderr.count("Traceback"), 0)

    def test_cli_success_prints_path_exit0(self):
        out = subprocess.run(
            [sys.executable, os.path.join(HERE, "propose-changeset.py"),
             "--client", "acme-dental", "--from", self._actions_file([_action()]),
             "--registry", self.clients, "--projects", self.projects],
            capture_output=True, text=True, env={**os.environ})
        self.assertEqual(out.returncode, 0)
        self.assertTrue(os.path.exists(out.stdout.strip()))

if __name__ == "__main__":
    unittest.main()
