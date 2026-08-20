import json, os, shutil, sys, tempfile, unittest
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import persist_run_record_shim as P


class TestParse(unittest.TestCase):
    def test_finds_the_marker_line(self):
        text = "apply-changeset: ok\nHERMES-RESULT-JSON {\"changeset_id\": \"x\"}\n"
        self.assertEqual(P.parse_result(text), {"changeset_id": "x"})

    def test_absent_marker_returns_none(self):
        self.assertIsNone(P.parse_result("apply-changeset: refused\n"))

    def test_ignores_the_marker_word_inside_ordinary_output(self):
        """Control: the discriminator is a line PREFIX, not a substring anywhere."""
        self.assertIsNone(P.parse_result("see HERMES-RESULT-JSON for details\n"))

    def test_last_marker_wins(self):
        text = ('HERMES-RESULT-JSON {"n": 1}\n'
                'HERMES-RESULT-JSON {"n": 2}\n')
        self.assertEqual(P.parse_result(text), {"n": 2})


class TestPersist(unittest.TestCase):
    def setUp(self):
        self.vault = tempfile.mkdtemp(prefix="vault-")
        self.addCleanup(shutil.rmtree, self.vault, True)

    def test_writes_result_json_and_appends_timeline(self):
        res = {"changeset_id": "20260812-101500-abcd1234", "applied": 2,
               "status": "ok", "finished_at": "2026-08-12T10:20:00Z"}
        path = P.persist(self.vault, res)
        with open(path) as f:
            self.assertEqual(json.load(f)["applied"], 2)
        with open(os.path.join(self.vault, "timeline.md")) as f:
            self.assertIn("20260812-101500-abcd1234", f.read())

    def test_timeline_appends_rather_than_truncates(self):
        res = {"changeset_id": "20260812-101500-abcd1234", "applied": 1,
               "status": "ok", "finished_at": "2026-08-12T10:20:00Z"}
        P.persist(self.vault, res)
        P.persist(self.vault, dict(res, changeset_id="20260812-111500-beef5678"))
        with open(os.path.join(self.vault, "timeline.md")) as f:
            body = f.read()
        self.assertIn("abcd1234", body)
        self.assertIn("beef5678", body)


if __name__ == "__main__":
    unittest.main()
