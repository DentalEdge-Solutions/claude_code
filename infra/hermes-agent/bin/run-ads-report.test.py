import os, subprocess, sys, tempfile, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(HERE, "run-ads-report.py")
mod = {}
with open(SCRIPT) as f:
    exec(compile(f.read(), SCRIPT, "exec"), mod)  # import functions without running main

REG = ("version: 1\nprojects:\n"
       "  claude_google_ads:\n"
       "    workdir: /projects/claude_google_ads\n"
       "    scope: read-execute\n"
       "    read_execute:\n"
       "      runner: /opt/ads-venv/bin/python3\n"
       "      script_dir: code\n"
       "      allow:\n"
       "        - test_connection\n"
       "        - account_overview\n"
       "  other:\n"
       "    workdir: /projects/other\n"
       "    scope: read\n")


def _reg(text=REG):
    f = tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False)
    f.write(text); f.close(); return f.name


class TestParse(unittest.TestCase):
    def test_read_workdir(self):
        p = _reg()
        self.assertEqual(mod["read_workdir"](p, "claude_google_ads"), "/projects/claude_google_ads")
        os.unlink(p)

    def test_read_read_execute(self):
        p = _reg()
        cfg = mod["read_read_execute"](p, "claude_google_ads")
        self.assertEqual(cfg["runner"], "/opt/ads-venv/bin/python3")
        self.assertEqual(cfg["script_dir"], "code")
        self.assertEqual(cfg["allow"], ["test_connection", "account_overview"])
        os.unlink(p)

    def test_missing_read_execute_rejected(self):
        p = _reg()
        with self.assertRaises(SystemExit):
            mod["read_read_execute"](p, "other")
        os.unlink(p)

    def test_sibling_after_allow_does_not_bleed(self):
        # A sibling scalar after the read_execute block must not be swallowed as allow items.
        text = REG + "    default_model: claude-haiku-4-5\n"
        p = _reg(text)
        cfg = mod["read_read_execute"](p, "claude_google_ads")
        self.assertEqual(cfg["allow"], ["test_connection", "account_overview"])
        self.assertNotIn("claude-haiku-4-5", cfg["allow"])
        os.unlink(p)

    def test_inline_comments_stripped(self):
        # Regression (Inc 3 Task 3 review): the REAL registry has inline `#
        # comments` on runner/script_dir/allow lines. A pre-fix parser would
        # append comment text onto runner/script_dir and would fail the
        # `stripped == "allow:"` check, corrupting the allow list.
        reg_with_comments = (
            "version: 1\nprojects:\n"
            "  claude_google_ads:\n"
            "    workdir: /projects/claude_google_ads\n"
            "    scope: read-execute\n"
            "    read_execute:\n"
            "      runner: /opt/ads-venv/bin/python3   # pinned build-time venv (Task 1), NOT base python\n"
            "      script_dir: code             # relative to workdir\n"
            "      allow:                       # EXACT basenames; fail-closed; READERS ONLY\n"
            "        - test_connection\n"
            "        - account_overview\n"
        )
        p = _reg(reg_with_comments)
        cfg = mod["read_read_execute"](p, "claude_google_ads")
        self.assertEqual(cfg["runner"], "/opt/ads-venv/bin/python3")
        self.assertEqual(cfg["script_dir"], "code")
        self.assertEqual(cfg["allow"], ["test_connection", "account_overview"])
        os.unlink(p)


class TestAllowList(unittest.TestCase):
    CFG = {"runner": "/opt/ads-venv/bin/python3", "script_dir": "code",
           "allow": ["test_connection", "account_overview"]}

    def test_allowed(self):
        self.assertEqual(mod["resolve_report"](self.CFG, "account_overview"), "account_overview")

    def test_not_in_allowlist_rejected(self):
        with self.assertRaises(SystemExit):
            mod["resolve_report"](self.CFG, "apply_negatives")   # a mutator — must be refused

    def test_path_separator_rejected(self):
        with self.assertRaises(SystemExit):
            mod["resolve_report"](self.CFG, "../account_overview")


class TestScrub(unittest.TestCase):
    def test_scrub_replaces_all_secrets(self):
        out = mod["_scrub"]("token=SEKRET id=999 refresh=RRR", ["SEKRET", "RRR", ""])
        self.assertNotIn("SEKRET", out)
        self.assertNotIn("RRR", out)
        self.assertIn("id=999", out)


class TestDryRun(unittest.TestCase):
    def test_dry_run_no_exec_no_creds(self):
        p = _reg()
        env = {**os.environ, "ADS_REGISTRY": p, "REPORTS_DIR": "/tmp/r"}
        for v in mod["CRED_VARS"]:
            env.pop(v, None)                       # dry-run must not need creds
        r = subprocess.run([sys.executable, SCRIPT, "--project", "claude_google_ads",
                            "--report", "account_overview", "--dry-run"],
                           capture_output=True, text=True, env=env)
        os.unlink(p)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("/opt/ads-venv/bin/python3", r.stdout)
        self.assertIn("code/account_overview.py", r.stdout)
        self.assertIn("/tmp/r/claude_google_ads/", r.stdout)

    def test_dry_run_rejects_disallowed_report(self):
        p = _reg()
        env = {**os.environ, "ADS_REGISTRY": p}
        r = subprocess.run([sys.executable, SCRIPT, "--project", "claude_google_ads",
                            "--report", "apply_negatives", "--dry-run"],
                           capture_output=True, text=True, env=env)
        os.unlink(p)
        self.assertNotEqual(r.returncode, 0)       # mutator refused even in dry-run


if __name__ == "__main__":
    unittest.main()
