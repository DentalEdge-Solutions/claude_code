import json, os, subprocess, sys, tempfile, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(HERE, "make-review-board.py")


def run(args, registry=None):
    env = os.environ.copy()
    if registry is not None:
        env["REVIEW_BOARD_REGISTRY"] = registry
    return subprocess.run([sys.executable, SCRIPT, *args], capture_output=True, text=True, env=env)


def write_registry(text):
    fd, path = tempfile.mkstemp(suffix=".yaml")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(text)
    return path


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

    # P7: the workdir comes from the shared registry walker (changeset_lib), not a
    # hand-rolled copy that kept inline comments and took the first of two workdir keys.
    def test_inline_comment_is_not_part_of_the_workdir(self):
        reg = write_registry("version: 1\n\nprojects:\n  demo:  # a project\n"
                             "    workdir: /projects/demo  # mounted read-only\n    scope: read\n")
        try:
            r = run(["--project", "demo", "--dry-run"], registry=reg)
        finally:
            os.unlink(reg)
        self.assertEqual(r.returncode, 0, r.stderr)
        body = json.loads(r.stdout)[0]["body"]
        self.assertIn("Workdir: /projects/demo.", body)
        self.assertNotIn("#", body)

    def test_duplicate_workdir_is_refused(self):
        reg = write_registry("projects:\n  demo:\n    workdir: /projects/demo\n"
                             "    workdir: /somewhere/else\n")
        try:
            r = run(["--project", "demo", "--dry-run"], registry=reg)
        finally:
            os.unlink(reg)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("duplicate", r.stderr)

    def test_undecodable_registry_is_reported_as_unreadable(self):
        fd, reg = tempfile.mkstemp(suffix=".yaml")
        with os.fdopen(fd, "wb") as f:
            f.write(b"projects:\n  demo:\n    workdir: /projects/\xff\xfe\n")
        try:
            r = run(["--project", "demo", "--dry-run"], registry=reg)
        finally:
            os.unlink(reg)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("unreadable", r.stderr)

    def test_unknown_project_is_refused(self):
        reg = write_registry("projects:\n  demo:\n    workdir: /projects/demo\n")
        try:
            r = run(["--project", "other", "--dry-run"], registry=reg)
        finally:
            os.unlink(reg)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("other", r.stderr)


if __name__ == "__main__":
    unittest.main()
