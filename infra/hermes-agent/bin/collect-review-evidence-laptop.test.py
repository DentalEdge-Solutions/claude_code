#!/usr/bin/env python3
import contextlib, importlib.util, io, json, os, sys, unittest
from unittest import mock
import review_lib as R
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
        cid = "1234567890"
        audit_with_cid = ("Container x Creating\nContainer x Created\n" + doc(f"{cid}-.env.ga", "READ_ONLY", False, "r" * 12) +
                          "\nContainer y Created\n" + doc(".env.gaw", "MUTATE_CAPABLE", True) + "\n")
        fake = mock.Mock(returncode=3, stdout=audit_with_cid, stderr="Request made: ClientCustomerId: 1234567890 ...")
        with mock.patch.object(L.subprocess, "run", return_value=fake):
            out = L.run_audit(cid)
        self.assertEqual(out["rc"], 3)
        out_json = json.dumps(out)
        self.assertNotIn(cid, out_json)
        redacted = "cid:" + R.sha12(cid)
        self.assertIn(redacted, out_json)
        self.assertEqual(out["stderr_lines_discarded"], 1)


class TestMain(unittest.TestCase):
    def test_non_digit_customer_refused(self):
        buf = io.StringIO()
        with contextlib.redirect_stderr(buf):
            rc = L.main(["--customer", "12-34"])
        self.assertEqual(rc, 1)
        self.assertIn("must be digits", buf.getvalue())

    def test_access_digest_mode(self):
        fake = mock.Mock(returncode=0, stdout=AUDIT, stderr="")
        with mock.patch.object(L.subprocess, "run", return_value=fake):
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                rc = L.main(["--customer", "1234567890", "--access-digest"])
            self.assertEqual(rc, 0)
            printed = buf.getvalue().strip()
            expected = L.access_digest(L.parse_audit(AUDIT))
            self.assertEqual(printed, expected)

    def test_access_digest_mode_fails_on_nonzero_rc(self):
        fake = mock.Mock(returncode=3, stdout=AUDIT, stderr="")
        with mock.patch.object(L.subprocess, "run", return_value=fake):
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                rc = L.main(["--customer", "1234567890", "--access-digest"])
            self.assertEqual(rc, 2)

    def test_package_items_need_all_three_args(self):
        fake = mock.Mock(returncode=0, stdout=AUDIT, stderr="")
        with mock.patch.object(L.subprocess, "run", return_value=fake):
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                rc = L.main(["--customer", "1234567890", "--package-project", "p"])
            bundle = json.loads(buf.getvalue())
            self.assertEqual(bundle["items"]["D6.3"]["status"], R.COULD_NOT_CHECK)
            self.assertIn("no --package-* arguments", bundle["items"]["D6.3"]["reason"])

    def test_package_hash_reports_build_output(self):
        fake_run = mock.Mock(returncode=0, stdout=AUDIT, stderr="")
        fake_pkg_hash = {"project": "p", "commit": "c" * 40, "sha256": "fakehash123", "files": 2}
        with mock.patch.object(L.subprocess, "run", return_value=fake_run):
            with mock.patch.object(L, "package_hash", return_value=fake_pkg_hash):
                buf = io.StringIO()
                with contextlib.redirect_stdout(buf):
                    rc = L.main(["--customer", "1234567890", "--package-project", "p",
                                "--package-repo", "/repo", "--package-commit", "c" * 40])
                bundle = json.loads(buf.getvalue())
                self.assertEqual(bundle["items"]["D6.3"]["status"], R.OBSERVED)
                self.assertEqual(bundle["items"]["D6.3"]["data"]["sha256"], "fakehash123")
                self.assertEqual(bundle["items"]["D6.3"]["data"]["files"], 2)


if __name__ == "__main__":
    unittest.main()
