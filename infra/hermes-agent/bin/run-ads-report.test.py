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


import datetime


class TestRunReport(unittest.TestCase):
    def _workdir_with_fake_reader(self, d, body):
        code = os.path.join(d, "code"); os.makedirs(code)
        with open(os.path.join(code, "fake_reader.py"), "w") as f:
            f.write(body)
        return d

    def _env_with_creds(self, extra):
        env = {**os.environ, **extra}
        for i, v in enumerate(mod["CRED_VARS"]):
            env[v] = env.get(v) or f"SECRET{i}"
        return env

    def test_run_report_scrubs_and_persists(self):
        with tempfile.TemporaryDirectory() as d, tempfile.TemporaryDirectory() as out:
            # fake reader echoes the injected developer token (a "secret") + a benign line
            self._workdir_with_fake_reader(
                d, "import os\nprint('token=' + os.environ['GOOGLE_ADS_DEVELOPER_TOKEN'])\nprint('campaigns=3')\n")
            plan = {"workdir": d, "runner": sys.executable,
                    "script": os.path.join(d, "code", "fake_reader.py"),
                    "report": "fake_reader", "project": "claude_google_ads"}
            env = self._env_with_creds({"GOOGLE_ADS_DEVELOPER_TOKEN": "TOPSECRETTOKEN",
                                        "REPORTS_DIR": out})
            old = dict(os.environ); os.environ.clear(); os.environ.update(env)
            try:
                rc = mod["run_report"](plan, datetime.datetime(2026, 8, 3, 12, 0, 0))
            finally:
                os.environ.clear(); os.environ.update(old)
            self.assertEqual(rc, 0)
            report_dir = os.path.join(out, "claude_google_ads")
            files = os.listdir(report_dir)
            self.assertEqual(len(files), 1)
            content = open(os.path.join(report_dir, files[0])).read()
            self.assertNotIn("TOPSECRETTOKEN", content)     # secret scrubbed
            self.assertIn("***", content)
            self.assertIn("campaigns=3", content)           # benign output preserved

    def test_run_report_refuses_missing_cred(self):
        with tempfile.TemporaryDirectory() as d:
            self._workdir_with_fake_reader(d, "print('hi')\n")
            plan = {"workdir": d, "runner": sys.executable,
                    "script": os.path.join(d, "code", "fake_reader.py"),
                    "report": "fake_reader", "project": "claude_google_ads"}
            env = {k: v for k, v in os.environ.items() if k not in mod["CRED_VARS"]}
            old = dict(os.environ); os.environ.clear(); os.environ.update(env)
            try:
                with self.assertRaises(SystemExit):
                    mod["run_report"](plan, datetime.datetime(2026, 8, 3, 12, 0, 0))
            finally:
                os.environ.clear(); os.environ.update(old)

    def test_run_report_nonzero_reader_raises(self):
        with tempfile.TemporaryDirectory() as d:
            self._workdir_with_fake_reader(d, "import sys\nsys.exit(2)\n")
            plan = {"workdir": d, "runner": sys.executable,
                    "script": os.path.join(d, "code", "fake_reader.py"),
                    "report": "fake_reader", "project": "claude_google_ads"}
            env = self._env_with_creds({})
            old = dict(os.environ); os.environ.clear(); os.environ.update(env)
            try:
                with self.assertRaises(SystemExit):
                    mod["run_report"](plan, datetime.datetime(2026, 8, 3, 12, 0, 0))
            finally:
                os.environ.clear(); os.environ.update(old)


if __name__ == "__main__":
    unittest.main()
