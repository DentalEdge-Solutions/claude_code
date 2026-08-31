import json, os, shutil, subprocess, sys, tempfile, unittest
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import vault_lib as V

def _reg(tmp, clients):
    d = os.path.join(tmp, "_registry"); os.makedirs(d, exist_ok=True)
    p = os.path.join(d, "clients.json")
    with open(p, "w") as f: json.dump({"clients": clients}, f)
    return p

class T(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        os.environ["VAULT_ROOT"] = self.tmp
        self.reg = _reg(self.tmp, {
            "acme-dental": {"project": "claude_google_ads", "customer_id": "1234567890",
                            "currency": "USD", "timezone": "America/New_York", "status": "active"},
        })
    def test_resolve_ok(self):
        r = V.resolve("acme-dental", self.reg)
        self.assertEqual(r["customer_id"], "1234567890")
        self.assertEqual(r["vault_path"], os.path.join(self.tmp, "acme-dental"))
        self.assertEqual(r["slug"], "acme-dental")
    def test_unknown_slug_raises(self):
        with self.assertRaises(KeyError): V.resolve("nope", self.reg)
    def test_unknown_slug_does_not_leak_known_slugs(self):
        reg = _reg(self.tmp, {
            "acme-dental": {"customer_id": "1234567890"},
            "beta-health": {"customer_id": "12345"},
        })
        with self.assertRaises(KeyError) as ctx: V.resolve("nope", reg)
        self.assertNotIn("beta-health", str(ctx.exception))
    def test_bad_slugs_rejected(self):
        for bad in ["../x", "a/b", "a b", "a;b", "A", "-x", "", "x"*65]:
            with self.assertRaises(ValueError): V.validate_slug(bad)
    def test_trailing_newline_rejected(self):
        with self.assertRaises(ValueError): V.validate_slug("acme-dental\n")
        with self.assertRaises(ValueError): V.validate_customer_id("1234567890\n")
    def test_bad_customer_id_rejected(self):
        for bad in ["", "12-34", "abc", "12 34", "1"*16]:
            with self.assertRaises(ValueError): V.validate_customer_id(bad)
    def test_missing_registry(self):
        with self.assertRaises(FileNotFoundError): V.load_registry(os.path.join(self.tmp, "no.json"))
    def test_cli_field(self):
        out = subprocess.run([sys.executable, os.path.join(os.path.dirname(__file__), "vault_lib.py"),
                              "--client", "acme-dental", "--field", "customer_id", "--registry", self.reg],
                             capture_output=True, text=True, env={**os.environ})
        self.assertEqual(out.returncode, 0); self.assertEqual(out.stdout.strip(), "1234567890")
    def test_cli_bad_slug_exit2(self):
        out = subprocess.run([sys.executable, os.path.join(os.path.dirname(__file__), "vault_lib.py"),
                              "--client", "../etc", "--registry", self.reg], capture_output=True, text=True)
        self.assertEqual(out.returncode, 2)
    def test_cli_registry_directory_exit2(self):
        out = subprocess.run([sys.executable, os.path.join(os.path.dirname(__file__), "vault_lib.py"),
                              "--client", "acme-dental", "--registry", self.tmp], capture_output=True, text=True)
        self.assertEqual(out.returncode, 2)

class TestRegistryLivesInGovernanceStore(unittest.TestCase):
    def setUp(self):
        self.gov = tempfile.mkdtemp(prefix="gov-")
        self.vault = tempfile.mkdtemp(prefix="vault-")
        self.addCleanup(shutil.rmtree, self.gov, True)
        self.addCleanup(shutil.rmtree, self.vault, True)
        os.makedirs(os.path.join(self.gov, "registry"))
        os.environ["HERMES_GOVERNANCE_ROOT"] = self.gov
        os.environ["VAULT_ROOT"] = self.vault
        self.addCleanup(os.environ.pop, "HERMES_GOVERNANCE_ROOT", None)
        self.addCleanup(os.environ.pop, "VAULT_ROOT", None)
        with open(os.path.join(self.gov, "registry", "clients.json"), "w") as f:
            json.dump({"clients": {"acme-dental": {
                "customer_id": "1234567890", "project": "claude_google_ads",
                "status": "active"}}}, f)

    def test_registry_path_points_at_the_governance_store(self):
        self.assertEqual(V.registry_path(),
                         os.path.join(self.gov, "registry", "clients.json"))

    def test_resolve_reads_it(self):
        rec = V.resolve("acme-dental")
        self.assertEqual(rec["customer_id"], "1234567890")

    def test_vault_path_still_points_at_the_vault(self):
        """The vault is NOT being emptied — results and reports stay readable by Hermes."""
        rec = V.resolve("acme-dental")
        self.assertEqual(rec["vault_path"], os.path.join(self.vault, "acme-dental"))

    def test_a_registry_at_the_old_vault_location_is_not_read(self):
        """Control: writing the old path must NOT satisfy resolve."""
        os.makedirs(os.path.join(self.vault, "_registry"))
        with open(os.path.join(self.vault, "_registry", "clients.json"), "w") as f:
            json.dump({"clients": {"other-clinic": {
                "customer_id": "9999999999", "project": "claude_google_ads",
                "status": "active"}}}, f)
        with self.assertRaises(KeyError):
            V.resolve("other-clinic")


class TestResolveDormantPilot(unittest.TestCase):
    """P7. The live gate may mutate exactly one client, and must never infer which.

    Every case below is about REFUSING rather than choosing. The one positive case is
    last, so a regression that made the resolver always-raise would still be caught.
    """

    def _reg(self, clients):
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d, True)
        p = os.path.join(d, "clients.json")
        with open(p, "w") as f:
            json.dump({"clients": clients}, f)
        return p

    ACTIVE = {"customer_id": "1234567890", "status": "active", "project": "p"}

    def test_no_marked_client_refuses(self):
        p = self._reg({"alpha": dict(self.ACTIVE), "beta": dict(self.ACTIVE)})
        with self.assertRaises(ValueError) as cm:
            V.resolve_dormant_pilot(p)
        self.assertIn("mutation_target", str(cm.exception))

    def test_absence_of_the_field_means_LIVE_not_eligible(self):
        # The fail-safe default, and the reason absence must not read as "safe": every
        # registry written before this field existed has no marks at all.
        p = self._reg({"alpha": dict(self.ACTIVE)})
        with self.assertRaises(ValueError):
            V.resolve_dormant_pilot(p)

    def test_two_marked_clients_refuse_rather_than_pick(self):
        a = dict(self.ACTIVE, mutation_target="dormant_pilot")
        b = dict(self.ACTIVE, mutation_target="dormant_pilot")
        p = self._reg({"alpha": a, "beta": b})
        with self.assertRaises(ValueError) as cm:
            V.resolve_dormant_pilot(p)
        self.assertIn("exactly one", str(cm.exception))

    def test_refusal_never_names_the_candidate_slugs(self):
        # A refusal that listed eligible clients would print client-private identifiers
        # into whatever log or terminal caught it.
        a = dict(self.ACTIVE, mutation_target="dormant_pilot")
        b = dict(self.ACTIVE, mutation_target="dormant_pilot")
        p = self._reg({"zebraclient": a, "quokkaclient": b})
        with self.assertRaises(ValueError) as cm:
            V.resolve_dormant_pilot(p)
        msg = str(cm.exception)
        self.assertNotIn("zebraclient", msg)
        self.assertNotIn("quokkaclient", msg)

    def test_a_near_miss_value_does_not_count_as_marked(self):
        for bad in ("dormant", "DORMANT_PILOT", "pilot", True, 1, None, ""):
            p = self._reg({"alpha": dict(self.ACTIVE, mutation_target=bad)})
            with self.assertRaises(ValueError):
                V.resolve_dormant_pilot(p)

    def test_status_active_does_not_disqualify_the_marked_client(self):
        # mutation_target is deliberately independent of status: the pilot is an active
        # engagement, and that must not make it ineligible.
        p = self._reg({"alpha": dict(self.ACTIVE),
                       "beta": dict(self.ACTIVE, mutation_target="dormant_pilot")})
        rec = V.resolve_dormant_pilot(p)
        self.assertEqual(rec["slug"], "beta")
        self.assertEqual(rec["status"], "active")
        self.assertEqual(rec["customer_id"], "1234567890")


if __name__ == "__main__": unittest.main()
