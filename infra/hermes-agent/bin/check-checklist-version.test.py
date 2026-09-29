import os, subprocess, sys, tempfile, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(HERE, "check-checklist-version.py")
REL = "infra/hermes-agent/deploy/security-review/CHECKLIST.md"

BODY = "# Hermes security review — checklist\n\nversion: {v}\n\n### D1.1 — item\n{extra}"


def git(repo, *args):
    return subprocess.run(["git", "-C", repo, *args], capture_output=True, text=True, check=True).stdout.strip()


class TestCheckChecklistVersion(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = self.tmp.name
        git(self.repo, "init", "-q")
        git(self.repo, "config", "user.email", "t@example.invalid")
        git(self.repo, "config", "user.name", "t")
        self.write(BODY.format(v="1.5", extra=""))
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "-m", "base")
        self.base = git(self.repo, "rev-parse", "HEAD")

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, text):
        path = os.path.join(self.repo, REL)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            f.write(text)

    def commit(self, text):
        self.write(text)
        git(self.repo, "commit", "-q", "-am", "change")

    def run_check(self, base=None):
        return subprocess.run([sys.executable, SCRIPT, "--repo", self.repo, "--base", base or self.base],
                              capture_output=True, text=True)

    def test_unchanged_checklist_passes(self):
        with open(os.path.join(self.repo, "other.txt"), "w") as f:
            f.write("x")
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "-m", "unrelated")
        r = self.run_check()
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_edit_without_bump_fails(self):
        self.commit(BODY.format(v="1.5", extra="- **expected:** tightened\n"))
        r = self.run_check()
        self.assertEqual(r.returncode, 1)
        self.assertIn("1.5", r.stderr)
        self.assertIn("without raising", r.stderr)

    def test_edit_with_bump_passes(self):
        self.commit(BODY.format(v="1.6", extra="- **expected:** tightened\n"))
        r = self.run_check()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("1.5 -> 1.6", r.stdout)

    def test_version_compared_numerically_not_as_text(self):
        # "1.10" > "1.9" numerically; a string compare would call it a downgrade.
        self.commit(BODY.format(v="1.9", extra=""))
        mid = git(self.repo, "rev-parse", "HEAD")
        self.commit(BODY.format(v="1.10", extra="more\n"))
        r = self.run_check(base=mid)
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_lowered_version_fails(self):
        self.commit(BODY.format(v="1.4", extra="x\n"))
        r = self.run_check()
        self.assertEqual(r.returncode, 1)

    def test_missing_version_line_fails_closed(self):
        self.commit("# checklist without a version\n")
        r = self.run_check()
        self.assertEqual(r.returncode, 2)
        self.assertIn("version", r.stderr)

    def test_checklist_new_at_head_passes(self):
        git(self.repo, "rm", "-q", REL)
        git(self.repo, "commit", "-q", "-m", "drop")
        base = git(self.repo, "rev-parse", "HEAD")
        self.write(BODY.format(v="1.0", extra=""))
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "-m", "re-add")
        r = self.run_check(base=base)
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_unknown_base_fails_closed(self):
        r = self.run_check(base="0" * 40)
        self.assertEqual(r.returncode, 2)


if __name__ == "__main__":
    unittest.main()
