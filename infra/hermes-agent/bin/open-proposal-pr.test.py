import datetime, os, subprocess, sys, tempfile, unittest, json

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(HERE, "open-proposal-pr.py")
mod = {}
with open(SCRIPT) as f:
    exec(compile(f.read(), SCRIPT, "exec"), mod)  # import functions without running main

PROPOSAL = ("# Improvement proposal — claude_code — 2026-07-24\n"
            "## Summary\nUnify the divergent secret-scanning pattern lists.\n"
            "## Items (prioritized)\n- [P1] correction: one pattern source.\n"
            "## Sources consulted\n- .project-brain/\n")


class TestOfflineCore(unittest.TestCase):
    def test_read_pr_target(self):
        reg = ("version: 1\nprojects:\n  claude_code:\n    workdir: /projects/claude_code\n"
               "    scope: read\n    pr_target:\n      repo: DentalEdge-Solutions/claude_code\n"
               "      base: main\n      path: .project-brain/decisions/candidates\n")
        with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False) as f:
            f.write(reg); p = f.name
        t = mod["read_pr_target"](p, "claude_code")
        self.assertEqual(t, {"repo": "DentalEdge-Solutions/claude_code",
                             "base": "main", "path": ".project-brain/decisions/candidates"})
        os.unlink(p)

    def test_read_pr_target_missing_project(self):
        with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False) as f:
            f.write("version: 1\nprojects:\n  other:\n    scope: read\n"); p = f.name
        with self.assertRaises(SystemExit):
            mod["read_pr_target"](p, "claude_code")
        os.unlink(p)

    def test_render_candidate_filename_and_frontmatter(self):
        now = datetime.datetime(2026, 7, 25, 9, 30, 0)
        fn, content = mod["render_candidate"](
            PROPOSAL, "/opt/data/proposals/claude_code/2026-07-24_22-54-03.md",
            "2026-07-24_22-54-03", now)
        self.assertTrue(fn.startswith("2026-07-25-"), fn)
        self.assertTrue(fn.endswith(".md"))
        self.assertIn("type: decision", content)
        self.assertIn("author: hermes", content)
        self.assertIn("hermes-generated", content)
        self.assertIn("status: candidate", content)
        # provenance sources present
        self.assertIn("/opt/data/proposals/claude_code/2026-07-24_22-54-03.md", content)
        self.assertIn("2026-07-24_22-54-03", content)
        # body carried verbatim
        self.assertIn("Unify the divergent secret-scanning pattern lists.", content)
        # frontmatter is valid: exactly two '---' fences at the top
        self.assertEqual(content.split("\n")[0], "---")
        self.assertEqual(content.count("\n---\n"), 1)

    def test_render_candidate_escapes_colon_in_title(self):
        now = datetime.datetime(2026, 7, 25, 9, 30, 0)
        text = "# Proposal: fix things\n## Summary\nA: B needed.\n"
        _, content = mod["render_candidate"](text, "/p/x.md", "x", now)
        # title line must be a valid quoted YAML scalar (json.dumps form)
        self.assertIn('title: "Proposal: fix things"', content)

    def test_render_candidate_real_h1_strips_trailing_timestamp(self):
        # The ACTUAL proposal H1 on disk (review item #3) — must NOT slugify to date-twice-plus-noise.
        now = datetime.datetime(2026, 7, 25, 9, 30, 0)
        text = "# Improvement proposal — claude_code — 2026-07-24T22:51Z\n## Summary\nUnify things.\n"
        fn, content = mod["render_candidate"](text, "/opt/data/proposals/claude_code/x.md", "x", now)
        self.assertEqual(fn, "2026-07-25-improvement-proposal-claude-code.md")   # one date, no timestamp
        self.assertNotIn("22-51z", fn)
        self.assertNotIn("2026-07-24", fn)
        # frontmatter keeps the FULL title, but timestamp is DATE-ONLY (item #4)
        self.assertIn("title: \"Improvement proposal — claude_code — 2026-07-24T22:51Z\"", content)
        self.assertIn("timestamp: 2026-07-25\n", content)
        self.assertNotIn("timestamp: 2026-07-25T", content)

    def test_dry_run_no_side_effects(self):
        with tempfile.TemporaryDirectory() as d:
            pdir = os.path.join(d, "claude_code"); os.makedirs(pdir)
            pf = os.path.join(pdir, "2026-07-24_22-54-03.md")
            open(pf, "w").write(PROPOSAL)
            reg = os.path.join(d, "projects.yaml")
            open(reg, "w").write("version: 1\nprojects:\n  claude_code:\n    scope: read\n"
                                 "    pr_target:\n      repo: DentalEdge-Solutions/claude_code\n"
                                 "      base: main\n      path: docs/proposals\n")
            env = {**os.environ, "PROPOSALS_DIR": d, "PR_REGISTRY": reg}
            r = subprocess.run([sys.executable, SCRIPT, "--project", "claude_code",
                                "--proposal", "latest", "--dry-run"],
                               capture_output=True, text=True, env=env)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn("DentalEdge-Solutions/claude_code", r.stdout)
            self.assertIn("proposal/", r.stdout)          # branch name
            self.assertIn("docs/proposals/2026-07-25-", r.stdout)  # candidate path
            self.assertNotIn(os.environ.get("CLAUDE_CODE_PR_PAT", "NO_TOKEN_SET"), r.stdout)


if __name__ == "__main__":
    unittest.main()
