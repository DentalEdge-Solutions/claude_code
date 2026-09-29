#!/usr/bin/env python3
"""Spec 2026-09-29 ads-audits-on-the-box §2/§7: the one-shot audit containers' REAL mounts.
Runs only as root on Linux with Docker (CI "Bind agreement" job, HERMES_REQUIRE_LINUX_INTEGRATION=1);
elsewhere prints SKIPPED and exits 0 unless that variable is set, in which case a skip FAILS.
Uses a stand-in image tagged hermes-agent-claude (python:3.12-slim + uid 10000 + /opt/ads-venv)."""
import json, os, shutil, subprocess, sys, tempfile, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
AGENT = os.path.dirname(HERE)
REQUIRE = os.environ.get("HERMES_REQUIRE_LINUX_INTEGRATION") == "1"
CAN = sys.platform.startswith("linux") and os.geteuid() == 0 and shutil.which("docker")
STANDIN = """FROM python:3.12-slim
RUN useradd -u 10000 -m hermes && mkdir -p /opt/ads-venv/bin && ln -s /usr/local/bin/python3 /opt/ads-venv/bin/python3
USER hermes
"""


def sh(*a, env=None, check=True):
    return subprocess.run(list(a), capture_output=True, text=True, env=env, check=check)


@unittest.skipUnless(CAN, "needs root + Linux + docker")
class TestAuditMounts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        # Layout mirrors the box: <root>/claude_code/infra/hermes-agent and <root>/claude-google-ads,
        # so the compose file's ../../../claude-google-ads resolves as it does on the box.
        cls.agent = os.path.join(cls.tmp, "claude_code/infra/hermes-agent")
        shutil.copytree(AGENT, cls.agent, ignore=shutil.ignore_patterns("data", "security-reviews", ".env*"))
        app = os.path.join(cls.tmp, "claude-google-ads/code")
        os.makedirs(app)
        os.makedirs(os.path.join(cls.tmp, "claude-google-ads/audit_data"))   # as install-app-package creates it
        open(os.path.join(cls.tmp, "claude-google-ads/.env"), "w").close()    # as install-app-package creates it
        with open(os.path.join(app, "stub_write.py"), "w") as f:
            f.write("open('/projects/claude_google_ads/audit_data/out.json','w').write('{}')\n")
        os.chmod(os.path.join(cls.tmp, "claude-google-ads"), 0o755)
        cls.data = os.path.join(cls.tmp, "audit-data/acme")
        os.makedirs(cls.data)
        os.chown(cls.data, 10000, 10000); os.chmod(cls.data, 0o700)
        d = os.path.join(cls.tmp, "img"); os.makedirs(d)
        with open(os.path.join(d, "Dockerfile"), "w") as f:
            f.write(STANDIN)
        sh("docker", "build", "-q", "-t", "hermes-agent-claude", d)
        cls.env = dict(os.environ, HERMES_AUDIT_DATA_DIR=cls.data, HERMES_SPOOL_DIR=cls.tmp,
                       HERMES_GOVERNANCE_DIR=os.path.join(cls.tmp, "governance"),
                       HERMES_AGENT_DIR=cls.agent, HERMES_ADS_REPO_DIR=os.path.join(cls.tmp, "claude-google-ads"))
        cls.compose = ["docker", "compose", "--env-file", "/dev/null", "-f",
                       os.path.join(cls.agent, "docker-compose.yml"), "--profile", "tools"]

    def run_svc(self, *args):
        return sh(*self.compose, "run", "--rm", "--no-deps", "-T", *args, env=self.env, check=False)

    def test_collector_can_write_audit_data(self):
        r = self.run_svc("ads-collector", "code/stub_write.py")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(os.path.exists(os.path.join(self.data, "out.json")))

    def test_reader_cannot_write_audit_data(self):
        r = self.run_svc("--entrypoint", "python3", "ads-reader", "-c",
                         "open('/projects/claude_google_ads/audit_data/x','w')")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("Read-only file system", r.stderr)

    def test_collector_cannot_write_the_app_code(self):
        r = self.run_svc("ads-collector", "-c", "open('/projects/claude_google_ads/code/y','w')")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("Read-only file system", r.stderr)

    def test_no_audit_service_gets_env_file_or_mounts_etc_hermes(self):
        cfg = json.loads(sh(*self.compose, "config", "--format", "json", env=self.env).stdout)
        for name in ("ads-collector", "ads-reader"):
            svc = cfg["services"][name]
            self.assertNotIn("env_file", svc)
            self.assertNotIn("ANTHROPIC_API_KEY", json.dumps(svc.get("environment", {})))
            for v in svc.get("volumes", []):
                self.assertFalse(str(v.get("source", "")).startswith("/etc/hermes"), v)

    def test_unset_audit_data_dir_fails_closed(self):
        env = {k: v for k, v in self.env.items() if k != "HERMES_AUDIT_DATA_DIR"}
        r = sh(*self.compose, "run", "--rm", "--no-deps", "-T", "ads-collector", "code/stub_write.py",
               env=env, check=False)
        self.assertNotEqual(r.returncode, 0)
        self.assertNotIn("interpolating", r.stderr)   # must fail at the mount, not at interpolation


if __name__ == "__main__":
    if not CAN:
        print("SKIPPED: audit-mounts integration needs root + Linux + docker")
        sys.exit(1 if REQUIRE else 0)
    unittest.main()
