#!/usr/bin/env python3
import importlib.util, json, os, sys, unittest
from unittest import mock
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
spec = importlib.util.spec_from_file_location("collect_laptop", os.path.join(HERE, "collect-review-evidence-laptop.py"))
L = importlib.util.module_from_spec(spec); spec.loader.exec_module(L)


def doc(label, verdict, admin, rt="aaaaaaaaaaaa"):
    return json.dumps({"label": label, "fingerprints": {"refresh_token_sha12": rt, "client_id_sha12": "c"},
                       "declared_role": "write" if label.endswith("w") else "read",
                       "expected_verdict": verdict, "measured_verdict": verdict, "mismatch": False,
                       "manager_level_admin": {"admin": admin, "reason": "x"}}, indent=2)


AUDIT = ("Container x Creating\nContainer x Created\n" + doc(".env.ga", "READ_ONLY", False, "r" * 12) +
         "\nContainer y Created\n" + doc(".env.gaw", "MUTATE_CAPABLE", True) + "\n")


class TestParse(unittest.TestCase):
    def test_extracts_both_documents_through_compose_noise(self):
        rows = L.parse_audit(AUDIT)
        self.assertEqual([r["label"] for r in rows], [".env.ga", ".env.gaw"])
        self.assertEqual(rows[1]["admin"], True)

    def test_digest_is_stable_and_changes_with_access(self):
        a = L.access_digest(L.parse_audit(AUDIT))
        self.assertEqual(a, L.access_digest(L.parse_audit(AUDIT)))
        drift = AUDIT.replace('"admin": true', '"admin": false')
        self.assertNotEqual(a, L.access_digest(L.parse_audit(drift)))

    def test_no_documents_raises(self):
        with self.assertRaises(ValueError):
            L.parse_audit("Container x Created\n")


class TestAuditRun(unittest.TestCase):
    def test_exit_code_is_the_audits_own_and_stderr_is_discarded(self):
        fake = mock.Mock(returncode=3, stdout=AUDIT, stderr="Request made: ClientCustomerId: 1234567890 ...")
        with mock.patch.object(L.subprocess, "run", return_value=fake):
            out = L.run_audit("1234567890")
        self.assertEqual(out["rc"], 3)
        self.assertNotIn("1234567890", json.dumps(out))
        self.assertEqual(out["stderr_lines_discarded"], 1)


if __name__ == "__main__":
    unittest.main()
