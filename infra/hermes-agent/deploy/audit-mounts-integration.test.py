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


ANTHROPIC_FAKE = "sk-ant-integration-fake"


def seams_root(root, agent, cred_names):
    """The box-shaped root plan() reads (TestOrchestratorSeams): <root>/opt/hermes-agent -> agent,
    the Google READ credential (every name but the customer id, 0400) and, since Option B, the
    Anthropic key file (0400) that plan() reads for the draft step. Pure file setup: importable
    and runnable without root or Docker."""
    os.makedirs(os.path.join(root, "opt")); os.makedirs(os.path.join(root, "etc/hermes"))
    os.symlink(agent, os.path.join(root, "opt/hermes-agent"))
    cred = os.path.join(root, "etc/hermes", ".env" + ".ga")
    with open(cred, "w") as f:
        for n in cred_names:
            if n != "GOOGLE_ADS_CUSTOMER_ID":             # plan() sets it from the registry
                f.write(f"{n}=fake-{n.lower()}\n")
        f.write("GOOGLE_ADS_CREDENTIAL_ROLE=read\n")
    os.chmod(cred, 0o400)
    anth = os.path.join(root, "etc/hermes", ".env" + ".anthropic")
    with open(anth, "w") as f:
        f.write(f"ANTHROPIC_API_KEY={ANTHROPIC_FAKE}\n")
    os.chmod(anth, 0o400)


@unittest.skipUnless(CAN, "needs root + Linux + docker")
class TestAuditMounts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        # Layout mirrors the box: <root>/claude_code/infra/hermes-agent and <root>/claude-google-ads,
        # so the compose file's ../../../claude-google-ads resolves as it does on the box.
        cls.agent = os.path.join(cls.tmp, "claude_code/infra/hermes-agent")
        shutil.copytree(AGENT, cls.agent, ignore=shutil.ignore_patterns("data", "security-reviews", ".env*"))
        # Stand-in .env: config resolves every service's env_file, and run-client-audit's probes
        # call compose WITHOUT --env-file (as on the box), so their interpolation comes from here.
        # The tests that pass --env-file /dev/null still interpolate from cls.env alone.
        with open(os.path.join(cls.agent, ".env"), "w") as f:
            f.write(f"HERMES_SPOOL_DIR={cls.tmp}\nHERMES_GOVERNANCE_DIR={cls.tmp}/governance\n"
                    f"HERMES_AGENT_DIR={cls.agent}\nHERMES_ADS_REPO_DIR={cls.tmp}/claude-google-ads\n")
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

    def run_svc(self, *args, env=None):
        return sh(*self.compose, "run", "--rm", "--no-deps", "-T", *args, env=env or self.env, check=False)

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
        # Non-vacuous: the compose CLIENT holds a Google credential name; the drafter must not.
        r = self.run_svc("ads-drafter", script, env=dict(self.env, GOOGLE_ADS_DEVELOPER_TOKEN="probe"))
        self.assertEqual(r.returncode, 0, r.stderr)
        out = r.stdout.split()
        self.assertEqual(out[0], "10000")
        self.assertIn("VAULT_R", out); self.assertIn("OUT_W", out)
        for bad in ("VAULT_W", "REPORTS_W", "ROOTFS_W", "HOST_VISIBLE"):
            self.assertNotIn(bad, out)
        self.assertFalse(any(x.startswith("GOOGLE_ADS_") for x in out), out)
        self.assertNotIn("GOOGLE_ADS_DEVELOPER_TOKEN", r.stdout)

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
                     "def dns():\n"
                     "  try: socket.getaddrinfo('example.com',443); return 'DNS_RESOLVES'\n"
                     "  except OSError: return 'DNS_BLOCKED'\n"
                     "print(direct()); print(via('example.com:443')); print(via('api.anthropic.com:443'))\n"
                     "print(dns())\n")
            r = self.run_svc("ads-drafter", f"python3 -c \"{probe}\"")
            self.assertEqual(r.returncode, 0, r.stderr)
            lines = r.stdout.splitlines()
            self.assertEqual(lines[0], "DIRECT_BLOCKED")
            self.assertIn("403", lines[1])
            self.assertIn("200", lines[2])
            # CVE-2024-29018: Docker < 26.0.0 (25.0.4, 23.0.11) forwards an internal network's
            # external DNS lookups, a covert exit. The drafter must not resolve an outside name.
            self.assertEqual(lines[3], "DNS_BLOCKED")
        finally:
            sh(*self.compose, "rm", "-sf", "egress-proxy", env=self.env, check=False)

    def _rca(self):
        import importlib.util
        s = importlib.util.spec_from_file_location("rca_it", os.path.join(self.agent, "bin/run-client-audit.py"))
        m = importlib.util.module_from_spec(s); s.loader.exec_module(m)
        m.AGENT_DIR = self.agent            # compose file of the copied tree
        m.PROBE_DIR = os.path.join(self.tmp, "probe")
        return m

    def test_probe_env_matches_the_declared_map(self):
        j = self._rca().probe_env("")
        self.assertTrue(j["matches_declared"], json.dumps(j, indent=1))

    def test_probe_egress_matches_expected(self):
        j = self._rca().probe_egress("")
        self.assertTrue(j["matches_expected"], json.dumps(j, indent=1))


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
        seams_root(cls.root, agent, cls.RCA.CRED_NAMES)
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
        self.assertFalse([k for k in env if k.startswith("ANTHROPIC")], sorted(env))   # host side
        self.assertEqual(dict((k, e) for k, _, e in steps)["draft"]["ANTHROPIC_API_KEY"], ANTHROPIC_FAKE)
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
