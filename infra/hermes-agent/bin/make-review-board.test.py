import json, os, subprocess, sys, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(HERE, "make-review-board.py")


def run(args):
    return subprocess.run([sys.executable, SCRIPT, *args], capture_output=True, text=True)


class TestMakeReviewBoard(unittest.TestCase):
    def test_dry_run_plans_fixed_four_task_shape(self):
        r = run(["--project", "claude_code", "--dry-run"])
        self.assertEqual(r.returncode, 0, r.stderr)
        plan = json.loads(r.stdout)
        titles = [t["title"] for t in plan]
        self.assertEqual(titles, ["analyze-architecture", "analyze-tests",
                                  "analyze-risks", "synthesize"])
        by = {t["title"]: t for t in plan}
        self.assertEqual(by["analyze-architecture"]["assignee"], "architect")
        self.assertEqual(by["synthesize"]["parents"],
                         ["analyze-architecture", "analyze-tests", "analyze-risks"])
        for t in plan:
            self.assertEqual(t["workspace"], "scratch")
            self.assertEqual(t["skill"], "claude-code-reviewer")

    def test_requires_project(self):
        r = run(["--dry-run"])
        self.assertNotEqual(r.returncode, 0)


if __name__ == "__main__":
    unittest.main()
