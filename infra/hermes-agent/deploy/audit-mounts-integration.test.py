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
        with open(os.path.join(cls.agent, ".env"), "w"):   # empty stand-in: config resolves every service's env_file
            pass
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
        for name in ("vault", "reports", "out"):
            p = os.path.join(cls.tmp, name + "/acme"); os.makedirs(p)
            os.chown(p, 10000, 10000); os.chmod(p, 0o700)
        cls.vault, cls.reports, cls.out = (os.path.join(cls.tmp, n + "/acme") for n in ("vault", "reports", "out"))
        open(os.path.join(cls.vault, "timeline.md"), "w").close()
        cls.env = dict(os.environ, HERMES_AUDIT_DATA_DIR=cls.data, HERMES_SPOOL_DIR=cls.tmp,
                       HERMES_GOVERNANCE_DIR=os.path.join(cls.tmp, "governance"),
                       HERMES_AGENT_DIR=cls.agent, HERMES_ADS_REPO_DIR=os.path.join(cls.tmp, "claude-google-ads"),
                       HERMES_VAULT_DIR=cls.vault, HERMES_REPORTS_DIR=cls.reports, HERMES_DRAFT_OUT_DIR=cls.out)
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
        r = sh(*self.compose, "config", "--format", "json", env=self.env, check=False)
        self.assertEqual(r.returncode, 0, r.stderr)
        cfg = json.loads(r.stdout)
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

    def test_reader_writes_per_client_reports(self):
        r = self.run_svc("--entrypoint", "sh", "ads-reader", "-c",
                         "echo x > /opt/data/reports/claude_google_ads/t.md")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(os.path.exists(os.path.join(self.reports, "t.md")))

    def test_drafter_mounts_one_client_ro_and_writes_only_out(self):
        script = ("id -u; test -r /work/vault/timeline.md && echo VAULT_R; "
                  "touch /work/vault/x 2>/dev/null && echo VAULT_W; "
                  "touch /work/reports/x 2>/dev/null && echo REPORTS_W; "
                  "touch /work/out/draft.md && echo OUT_W; touch /etc/x 2>/dev/null && echo ROOTFS_W; "
                  "test -e /var/lib/hermes && echo HOST_VISIBLE; env | cut -d= -f1 | grep -E '^GOOGLE_ADS_' || true")
        r = self.run_svc("ads-drafter", script)
        self.assertEqual(r.returncode, 0, r.stderr)
        out = r.stdout.split()
        self.assertEqual(out[0], "10000")
        self.assertIn("VAULT_R", out); self.assertIn("OUT_W", out)
        for bad in ("VAULT_W", "REPORTS_W", "ROOTFS_W", "HOST_VISIBLE"):
            self.assertNotIn(bad, out)
        self.assertFalse(any(x.startswith("GOOGLE_ADS_") for x in out))

    def test_drafter_has_no_route_out_except_the_proxy(self):
        sh(*self.compose, "up", "-d", "--no-deps", "egress-proxy", env=self.env)
        try:
            probe = ("import os,socket,sys\n"
                     "def direct():\n"
                     "  try: socket.create_connection(('1.1.1.1',443),timeout=5); return 'DIRECT_OK'\n"
                     "  except OSError: return 'DIRECT_BLOCKED'\n"
                     "def via(target):\n"
                     "  s=socket.create_connection(('egress-proxy',3128),timeout=10)\n"
                     "  s.sendall(('CONNECT %s HTTP/1.1\\r\\nHost: x\\r\\n\\r\\n'%target).encode())\n"
                     "  return s.recv(64).split(b'\\r\\n')[0].decode()\n"
                     "print(direct()); print(via('example.com:443')); print(via('api.anthropic.com:443'))\n")
            r = self.run_svc("ads-drafter", f"python3 -c \"{probe}\"")
            self.assertEqual(r.returncode, 0, r.stderr)
            lines = r.stdout.splitlines()
            self.assertEqual(lines[0], "DIRECT_BLOCKED")
            self.assertIn("403", lines[1])
            self.assertIn("200", lines[2])
        finally:
            sh(*self.compose, "rm", "-sf", "egress-proxy", env=self.env, check=False)


@unittest.skipUnless(CAN, "needs root + Linux + docker")
class TestOrchestratorSeams(unittest.TestCase):
    """I6: run-client-audit's REAL collect argv and env from plan(), run as real_runner runs it.
    Compose is called WITHOUT --env-file, so HERMES_* interpolation comes from the agent dir's
    .env, as on the box; the credential values come only from the step's env (-e NAME)."""
    @classmethod
    def setUpClass(cls):
        import importlib.util
        spec = importlib.util.spec_from_file_location("rca", os.path.join(AGENT, "bin", "run-client-audit.py"))
        cls.RCA = importlib.util.module_from_spec(spec); spec.loader.exec_module(cls.RCA)
        cls.tmp = tempfile.mkdtemp()
        agent = os.path.join(cls.tmp, "claude_code/infra/hermes-agent")
        shutil.copytree(AGENT, agent, ignore=shutil.ignore_patterns("data", "security-reviews", ".env*"))
        with open(os.path.join(agent, ".env"), "w") as f:   # interpolation source, as on the box
            f.write(f"HERMES_SPOOL_DIR={cls.tmp}\nHERMES_GOVERNANCE_DIR={cls.tmp}/governance\n"
                    f"HERMES_AGENT_DIR={agent}\nHERMES_ADS_REPO_DIR={cls.tmp}/claude-google-ads\n"
                    "ANTHROPIC_API_KEY=sk-ant-integration-fake\n")
        app = os.path.join(cls.tmp, "claude-google-ads")
        os.makedirs(os.path.join(app, "code")); os.makedirs(os.path.join(app, "audit_data"))
        open(os.path.join(app, ".env"), "w").close()
        with open(os.path.join(app, "code/audit_discovery.py"), "w") as f:
            f.write("import os\nprint('\\n'.join(sorted(k for k in os.environ\n"
                    "      if k.startswith(('GOOGLE_ADS_', 'ANTHROPIC')))))\n")
        os.chmod(app, 0o755)
        # <root>/opt/hermes-agent -> the agent copy, as /opt/hermes-agent is on the box. root sits
        # TWO levels under tmp on purpose: from the UNRESOLVED path, ../../../claude-google-ads
        # lands in tmp/deep/claude-google-ads, which does not exist, so the collect step fails;
        # only the symlink-resolved path (what run-client-audit must pass, 2026-09-30 box run)
        # reaches tmp/claude-google-ads. An earlier layout resolved either way and hid the bug.
        cls.root = os.path.join(cls.tmp, "deep", "root")
        os.makedirs(os.path.join(cls.root, "opt")); os.makedirs(os.path.join(cls.root, "etc/hermes"))
        os.symlink(agent, os.path.join(cls.root, "opt/hermes-agent"))
        cred = os.path.join(cls.root, "etc/hermes", ".env" + ".ga")
        with open(cred, "w") as f:
            for n in cls.RCA.CRED_NAMES:
                if n != "GOOGLE_ADS_CUSTOMER_ID":             # plan() sets it from the registry
                    f.write(f"{n}=fake-{n.lower()}\n")
            f.write("GOOGLE_ADS_CREDENTIAL_ROLE=read\n")
        os.chmod(cred, 0o400)
        cls.RCA.AUDIT_DATA = os.path.join(cls.tmp, "audit-data")   # the one knob: keep CI's /var clean
        cls.slug = "it-seams"
        data = os.path.join(cls.RCA.AUDIT_DATA, cls.slug)
        os.makedirs(data); os.chown(data, 10000, 10000); os.chmod(data, 0o700)
        d = os.path.join(cls.tmp, "img"); os.makedirs(d)
        with open(os.path.join(d, "Dockerfile"), "w") as f:
            f.write(STANDIN)
        sh("docker", "build", "-q", "-t", "hermes-agent-claude", d)

    def test_first_collect_step_sees_every_credential_name_and_no_anthropic_var(self):
        import datetime
        ts = datetime.datetime.now(datetime.timezone.utc).strftime(self.RCA.TS_FMT)
        steps = self.RCA.plan({"slug": self.slug, "customer_id": "1234567890"}, ts, self.root)
        key, argv, env = steps[0]
        self.assertEqual(key, "collect")
        self.assertNotIn("--env-file", argv)
        logs = os.path.join(self.tmp, "logs"); os.makedirs(logs)
        with self.RCA.open_log(logs + "/o") as out, self.RCA.open_log(logs + "/e") as err:
            rc = self.RCA.real_runner(argv, env, self.RCA.TIMEOUTS[key], out, err)
        with open(logs + "/o") as f:
            seen = f.read().split()
        with open(logs + "/e") as f:
            stderr = f.read()
        self.assertEqual(rc, 0, stderr)
        for n in self.RCA.CRED_NAMES:
            self.assertIn(n, seen)
        self.assertFalse([n for n in seen if n.startswith("ANTHROPIC")], seen)


if __name__ == "__main__":
    if not CAN:
        print("SKIPPED: audit-mounts integration needs root + Linux + docker")
        sys.exit(1 if REQUIRE else 0)
    unittest.main()
