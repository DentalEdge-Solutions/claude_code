import json, os, importlib.util, tempfile, unittest, sys
_p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ads-metrics-snapshot.py")
_spec = importlib.util.spec_from_file_location("ads_metrics_snapshot", _p)
M = importlib.util.module_from_spec(_spec); _spec.loader.exec_module(M)

class T(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        # two campaigns: costMicros 100_000_000 (=100.0) + 200_000_000 (=200.0) => spend 300.0
        perf = [
          {"campaign":{"id":"1"},"metrics":{"costMicros":"100000000","conversions":10.0,
            "impressions":"1000","clicks":"100","ctr":0.1,"searchImpressionShare":0.5}},
          {"campaign":{"id":"2"},"metrics":{"costMicros":"200000000","conversions":40.0,
            "impressions":"3000","clicks":"150","ctr":0.05,"searchImpressionShare":0.9}},
        ]
        with open(os.path.join(self.d,"campaign_perf_30d.json"),"w") as f:
            json.dump(perf, f)
        # account.json records which account audit_data/ belongs to. snapshot() now
        # refuses without it — "cannot verify provenance" must not round to "fine" —
        # so every fixture has to declare the account it is pretending to be.
        with open(os.path.join(self.d,"account.json"),"w") as f:
            json.dump([{"customer":{"id":"1234567890"}}], f)
        with open(os.path.join(self.d,"campaigns.json"),"w") as f:
            json.dump([{"campaign":{"id":"1"}},{"campaign":{"id":"2"}}], f)
    def test_aggregation(self):
        s = M.snapshot(self.d, "1234567890", collected_at="2026-08-06T00:00:00Z")
        self.assertEqual(s["spend"], 300.0)
        self.assertEqual(s["conversions"], 50.0)
        self.assertEqual(s["impressions"], 4000)
        self.assertEqual(s["clicks"], 250)
        self.assertEqual(s["cost_per_conv"], 6.0)           # 300/50
        self.assertEqual(s["ctr"], 0.0625)                  # 250/4000 recomputed
        self.assertEqual(s["conv_rate"], 0.2)               # 50/250
        self.assertEqual(s["impression_share"], 0.8)         # (0.5*1000+0.9*3000)/4000
        self.assertEqual(s["campaign_count"], 2)
        self.assertEqual(s["customer_id"], "1234567890")
        self.assertEqual(s["collected_at"], "2026-08-06T00:00:00Z")
    def test_div0_guarded(self):
        with open(os.path.join(self.d,"campaign_perf_30d.json"),"w") as f:
            json.dump([{"campaign":{"id":"1"},"metrics":{"costMicros":"0","conversions":0.0,
                "impressions":"0","clicks":"0"}}], f)
        # customer id must match the fixture's account.json — this test is about
        # division guards, not provenance, so it uses the dir's declared account.
        s = M.snapshot(self.d, "1234567890")
        self.assertEqual(s["cost_per_conv"], 0.0); self.assertEqual(s["ctr"], 0.0)
        self.assertEqual(s["conv_rate"], 0.0); self.assertEqual(s["impression_share"], 0.0)
    def test_missing_file_exit2(self):
        import subprocess
        r = subprocess.run([sys.executable, _p, "--audit-data", tempfile.mkdtemp(), "--customer","1"],
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 2)



class TestProvenanceGuard(unittest.TestCase):
    """audit_data/ is one flat dir shared by every client, so a snapshot taken after a
    failed or skipped collection would otherwise label client A's numbers with client
    B's id and write them into B's vault."""

    def _dir(self, account_id):
        d = tempfile.mkdtemp()
        with open(os.path.join(d, "campaign_perf_30d.json"), "w") as f:
            json.dump([{"campaign": {"id": "1"}, "metrics": {"costMicros": "1000000"}}], f)
        if account_id is not None:
            with open(os.path.join(d, "account.json"), "w") as f:
                json.dump([{"customer": {"id": account_id}}], f)
        return d

    def test_matching_account_is_accepted(self):
        d = self._dir("1234567890")
        self.assertEqual(M.snapshot(d, "1234567890")["customer_id"], "1234567890")

    def test_dashed_customer_id_still_matches(self):
        d = self._dir("1234567890")
        self.assertEqual(M.assert_provenance(d, "123-456-7890"), "1234567890")

    def test_mismatched_account_is_refused(self):
        d = self._dir("1234567890")
        with self.assertRaises(M.ProvenanceMismatch):
            M.snapshot(d, "9999999999")

    def test_refusal_message_never_leaks_a_raw_id(self):
        d = self._dir("1234567890")
        try:
            M.snapshot(d, "9999999999")
            self.fail("expected ProvenanceMismatch")
        except M.ProvenanceMismatch as e:
            self.assertNotIn("1234567890", str(e))
            self.assertNotIn("9999999999", str(e))

    def test_missing_account_json_is_refused_not_assumed_ok(self):
        # "cannot verify" must never round to "verified".
        d = self._dir(None)
        with self.assertRaises((FileNotFoundError, KeyError)):
            M.snapshot(d, "1234567890")

    def test_account_json_without_customer_id_is_refused(self):
        d = self._dir(None)
        with open(os.path.join(d, "account.json"), "w") as f:
            json.dump([{"customer": {"descriptiveName": "x"}}], f)
        with self.assertRaises(KeyError):
            M.snapshot(d, "1234567890")


if __name__ == "__main__":
    unittest.main(verbosity=2)
