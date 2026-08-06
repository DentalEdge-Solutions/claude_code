import json, os, importlib.util, tempfile, unittest, sys
_p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ads-metrics-snapshot.py")
_spec = importlib.util.spec_from_file_location("ads_metrics_snapshot", _p)
M = importlib.util.module_from_spec(_spec); _spec.loader.exec_module(M)

class T(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        # two campaigns: costMicros 100_000_000 (=100.0) + 300_000_000 (=300.0) => spend 400.0
        perf = [
          {"campaign":{"id":"1"},"metrics":{"costMicros":"100000000","conversions":10.0,
            "impressions":"1000","clicks":"100","ctr":0.1,"searchImpressionShare":0.5}},
          {"campaign":{"id":"2"},"metrics":{"costMicros":"300000000","conversions":30.0,
            "impressions":"3000","clicks":"300","ctr":0.1,"searchImpressionShare":0.9}},
        ]
        with open(os.path.join(self.d,"campaign_perf_cur30.json"),"w") as f:
            json.dump(perf, f)
        with open(os.path.join(self.d,"campaigns.json"),"w") as f:
            json.dump([{"campaign":{"id":"1"}},{"campaign":{"id":"2"}}], f)
    def test_aggregation(self):
        s = M.snapshot(self.d, "6764977319", collected_at="2026-08-06T00:00:00Z")
        self.assertEqual(s["spend"], 400.0)
        self.assertEqual(s["conversions"], 40.0)
        self.assertEqual(s["impressions"], 4000)
        self.assertEqual(s["clicks"], 400)
        self.assertEqual(s["cost_per_conv"], 10.0)          # 400/40
        self.assertEqual(s["ctr"], 0.1)                      # 400/4000 recomputed
        self.assertEqual(s["conv_rate"], 0.1)                # 40/400
        self.assertEqual(s["impression_share"], 0.8)         # (0.5*1000+0.9*3000)/4000
        self.assertEqual(s["campaign_count"], 2)
        self.assertEqual(s["customer_id"], "6764977319")
        self.assertEqual(s["collected_at"], "2026-08-06T00:00:00Z")
    def test_div0_guarded(self):
        with open(os.path.join(self.d,"campaign_perf_cur30.json"),"w") as f:
            json.dump([{"campaign":{"id":"1"},"metrics":{"costMicros":"0","conversions":0.0,
                "impressions":"0","clicks":"0"}}], f)
        s = M.snapshot(self.d, "1")
        self.assertEqual(s["cost_per_conv"], 0.0); self.assertEqual(s["ctr"], 0.0)
        self.assertEqual(s["conv_rate"], 0.0); self.assertEqual(s["impression_share"], 0.0)
    def test_missing_file_exit2(self):
        import subprocess
        r = subprocess.run([sys.executable, _p, "--audit-data", tempfile.mkdtemp(), "--customer","1"],
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 2)

if __name__ == "__main__": unittest.main()
