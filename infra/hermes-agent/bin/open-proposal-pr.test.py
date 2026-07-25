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

    def test_read_pr_target_mapping_sibling_after_pr_target_no_bleed(self):
        # Review finding #1: a mapping-valued sibling AFTER pr_target must not bleed its
        # indent-6 children into pr_target's fields. The correct target must survive.
        reg = ("version: 1\nprojects:\n  claude_code:\n    scope: read\n"
               "    pr_target:\n      repo: DentalEdge-Solutions/claude_code\n"
               "      base: main\n      path: .project-brain/decisions/candidates\n"
               "    notify:\n      repo: SOME/other-repo\n      base: dev\n      path: /wrong\n")
        with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False) as f:
            f.write(reg); p = f.name
        t = mod["read_pr_target"](p, "claude_code")
        self.assertEqual(t, {"repo": "DentalEdge-Solutions/claude_code",
                             "base": "main", "path": ".project-brain/decisions/candidates"})
        os.unlink(p)

    def test_read_pr_target_empty_value_rejected(self):
        # Review finding #5: a present-but-empty scalar (repo:) must be rejected, not
        # silently accepted into a broken clone URL.
        reg = ("version: 1\nprojects:\n  claude_code:\n    pr_target:\n"
               "      repo:\n      base: main\n      path: docs\n")
        with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False) as f:
            f.write(reg); p = f.name
        with self.assertRaises(SystemExit):
            mod["read_pr_target"](p, "claude_code")
        os.unlink(p)

    def test_resolve_proposal_rejects_path_traversal(self):
        # Review finding #4: --proposal must be a bare filename; a path escapes the dir.
        with tempfile.TemporaryDirectory() as d:
            pdir = os.path.join(d, "claude_code"); os.makedirs(pdir)
            with open(os.path.join(pdir, "2026-07-24_22-54-03.md"), "w") as f:
                f.write(PROPOSAL)
            os.environ["PROPOSALS_DIR"] = d
            try:
                with self.assertRaises(SystemExit):
                    mod["resolve_proposal"]("claude_code", "../../etc/passwd")
            finally:
                del os.environ["PROPOSALS_DIR"]

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
            with open(pf, "w") as f:
                f.write(PROPOSAL)
            reg = os.path.join(d, "projects.yaml")
            with open(reg, "w") as f:
                f.write("version: 1\nprojects:\n  claude_code:\n    scope: read\n"
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


class TestPrePushHook(unittest.TestCase):
    HOOK = os.path.join(HERE, "pre-push-refuse-base.sh")
    def _run(self, remote_ref):
        stdin = f"refs/heads/x deadbeef {remote_ref} 0000000\n"
        return subprocess.run(["sh", self.HOOK], input=stdin, capture_output=True, text=True,
                              env={**os.environ, "PREPUSH_BASE": "main"})
    def test_refuses_main(self):
        self.assertEqual(self._run("refs/heads/main").returncode, 1)
    def test_allows_feature_branch(self):
        self.assertEqual(self._run("refs/heads/proposal/2026-07-24_22-54-03").returncode, 0)


class TestSecretHandling(unittest.TestCase):
    def test_no_token_leak_on_clone_failure(self):
        # Blocking review item #1: force a clone failure (bogus .invalid host = fast NXDOMAIN)
        # and assert the token appears in NEITHER stdout NOR stderr — including any traceback.
        with tempfile.TemporaryDirectory() as d:
            pdir = os.path.join(d, "claude_code"); os.makedirs(pdir)
            with open(os.path.join(pdir, "2026-07-24_22-54-03.md"), "w") as f:
                f.write(PROPOSAL)
            reg = os.path.join(d, "projects.yaml")
            with open(reg, "w") as f:
                f.write("version: 1\nprojects:\n  claude_code:\n    scope: read\n"
                        "    pr_target:\n      repo: DentalEdge-Solutions/claude_code\n"
                        "      base: main\n      path: docs/proposals\n")
            SENTINEL = "ghp_SENTINELtoken000000000000000000000000"
            env = {**os.environ, "PROPOSALS_DIR": d, "PR_REGISTRY": reg,
                   "CLAUDE_CODE_PR_PAT": SENTINEL, "PR_GIT_HOST": "example.invalid"}
            r = subprocess.run([sys.executable, SCRIPT, "--project", "claude_code", "--proposal", "latest"],
                               capture_output=True, text=True, env=env)
            self.assertNotEqual(r.returncode, 0)          # clone must fail
            self.assertNotIn(SENTINEL, r.stdout)
            self.assertNotIn(SENTINEL, r.stderr)


class TestRestFallback(unittest.TestCase):
    def test_open_draft_pr_rest_posts_draft(self):
        # Review item #9: the REST path never runs live when gh is present, so unit-test it
        # with gh forced absent and a stubbed urlopen.
        import urllib.request as ur
        captured = {}
        class FakeResp:
            def __enter__(self): return self
            def __exit__(self, *a): return False
            def read(self): return b'{"html_url": "https://github.com/o/r/pull/7"}'
        def fake_urlopen(req):
            captured["data"] = req.data.decode(); captured["auth"] = req.headers.get("Authorization")
            return FakeResp()
        orig_which, orig_urlopen = mod["shutil"].which, ur.urlopen
        mod["shutil"].which = lambda name: None
        ur.urlopen = fake_urlopen
        try:
            out = mod["_open_draft_pr"](
                {"repo": "o/r", "base": "main"},
                {"title": "T", "branch": "proposal/x", "dest": "docs/x.md", "proposal_path": "/p/x.md"},
                "SENTINELPAT")
        finally:
            mod["shutil"].which, ur.urlopen = orig_which, orig_urlopen
        self.assertIn("pull/7", out)
        self.assertIn('"draft": true', captured["data"])
        self.assertIn("proposal/x", captured["data"])
        self.assertEqual(captured["auth"], "Bearer SENTINELPAT")

    def test_open_draft_pr_rest_httperror_is_scrubbed(self):
        # Review finding #3: a REST failure must raise a clean SystemExit that surfaces
        # GitHub's body but never leaks the PAT (even if the body echoed it).
        import io, urllib.request as ur, urllib.error
        SENTINEL = "ghp_SENTINELtoken000000000000000000000000"
        def fake_urlopen(req):
            raise urllib.error.HTTPError(
                req.full_url, 422, "Unprocessable Entity", {},
                io.BytesIO(b'{"message":"No commits between main and head; token=' +
                           SENTINEL.encode() + b'"}'))
        orig_which, orig_urlopen = mod["shutil"].which, ur.urlopen
        mod["shutil"].which = lambda name: None
        ur.urlopen = fake_urlopen
        try:
            with self.assertRaises(SystemExit) as cm:
                mod["_open_draft_pr"]({"repo": "o/r", "base": "main"},
                                      {"title": "T", "branch": "proposal/x",
                                       "dest": "docs/x.md", "proposal_path": "/p/x.md"},
                                      SENTINEL)
        finally:
            mod["shutil"].which, ur.urlopen = orig_which, orig_urlopen
        msg = str(cm.exception)
        self.assertIn("422", msg)
        self.assertNotIn(SENTINEL, msg)          # PAT scrubbed even out of the echoed body


if __name__ == "__main__":
    unittest.main()
