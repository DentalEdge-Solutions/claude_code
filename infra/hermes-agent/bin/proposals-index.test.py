import json, os, subprocess, sys, tempfile, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(HERE, "proposals-index.py")


def run(args, env_extra):
    env = {**os.environ, **env_extra}
    return subprocess.run([sys.executable, SCRIPT, *args],
                          capture_output=True, text=True, env=env)


class TestProposalsIndex(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        p = os.path.join(self.d, "claude_google_ads")
        os.makedirs(p)
        self.f = os.path.join(p, "2026-07-23_10-00-00.md")
        open(self.f, "w").write("# Improvement proposal\n## Summary\nTwo corrections found.\n")

    def test_json_lists_proposal_with_summary(self):
        r = run(["--json"], {"PROPOSALS_DIR": self.d})
        self.assertEqual(r.returncode, 0, r.stderr)
        rows = json.loads(r.stdout)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["project"], "claude_google_ads")
        self.assertEqual(rows[0]["summary"], "Two corrections found.")

    def test_open_prints_content(self):
        r = run(["--open", self.f], {"PROPOSALS_DIR": self.d})
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("Two corrections found.", r.stdout)

    def test_empty_dir_reports_none(self):
        with tempfile.TemporaryDirectory() as empty:
            r = run([], {"PROPOSALS_DIR": empty})
            self.assertEqual(r.returncode, 0)
            self.assertIn("No proposals yet", r.stdout)

    def test_open_refuses_path_outside_base(self):
        with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False) as outside:
            outside.write("secret outside base")
            outside_path = outside.name
        try:
            r = run(["--open", outside_path], {"PROPOSALS_DIR": self.d})
            self.assertEqual(r.returncode, 1)
            self.assertIn("outside PROPOSALS_DIR", r.stderr)
            self.assertNotIn("secret outside base", r.stdout)
        finally:
            os.unlink(outside_path)


if __name__ == "__main__":
    unittest.main()
