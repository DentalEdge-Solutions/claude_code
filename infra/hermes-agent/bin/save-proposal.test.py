import json, os, subprocess, sys, tempfile, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(HERE, "save-proposal.py")


def run(args, stdin, env_extra):
    env = {**os.environ, **env_extra}
    return subprocess.run([sys.executable, SCRIPT, *args],
                          input=stdin, capture_output=True, text=True, env=env)


class TestSaveProposal(unittest.TestCase):
    def test_writes_proposal_and_prints_path(self):
        with tempfile.TemporaryDirectory() as d:
            r = run(["--project", "claude_google_ads", "--now", "2026-07-23_10-00-00"],
                    "# Proposal\nbody", {"PROPOSALS_DIR": d})
            self.assertEqual(r.returncode, 0, r.stderr)
            expected = os.path.join(d, "claude_google_ads", "2026-07-23_10-00-00.md")
            self.assertEqual(r.stdout.strip(), expected)
            self.assertEqual(open(expected).read(), "# Proposal\nbody")

    def test_slugs_project_name(self):
        with tempfile.TemporaryDirectory() as d:
            r = run(["--project", "My Ads!", "--now", "t"], "x", {"PROPOSALS_DIR": d})
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertTrue(os.path.isfile(os.path.join(d, "my-ads", "t.md")))

    def test_empty_stdin_fails(self):
        with tempfile.TemporaryDirectory() as d:
            r = run(["--project", "x", "--now", "t"], "   ", {"PROPOSALS_DIR": d})
            self.assertEqual(r.returncode, 1)


if __name__ == "__main__":
    unittest.main()
