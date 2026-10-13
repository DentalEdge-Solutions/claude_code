#!/usr/bin/env python3
"""Static assertions on the gateway's compose service and Hermes config (Option B §3.1, §6).
Text-level on purpose: stdlib has no YAML parser, and each check is a line that must or must not exist."""
import os, re, sys, unittest
AGENT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def read(p):
    return open(os.path.join(AGENT, p), encoding="utf-8").read()


def service_block(compose, name):
    m = re.search(r"^  %s:\n(.*?)(?=^  [a-z][a-z0-9-]*:\n|^[a-z]|\Z)" % re.escape(name), compose, re.S | re.M)
    return m.group(1) if m else ""


class T(unittest.TestCase):
    def test_claude_auth_init_is_gone(self):
        c = read("docker-compose.yml")
        self.assertNotIn("claude-auth-init", c)
        self.assertNotIn("bootstrap-claude-auth", read("Dockerfile"))
        self.assertFalse(os.path.exists(os.path.join(AGENT, "bootstrap-claude-auth.sh")))

    def test_gateway_mounts_no_client_data(self):
        gw_full = service_block(read("docker-compose.yml"), "hermes-agent")
        gw = gw_full
        self.assertTrue(gw)
        # the two skill mounts (ads-audits, ads-reports) are instruction files, not data: leave them out of the scan
        gw = "\n".join(l for l in gw.splitlines() if not l.lstrip().startswith(("- ./skills/ads-audits:", "- ./skills/ads-reports:")))
        for bad in ("vaults", "reports", "audit-data", "draft-out", "app-state", "/etc/hermes"):
            self.assertNotIn(bad, gw)
        self.assertIn("./skills/ads-audits:/opt/data/skills/ads-audits:ro", gw_full)
        self.assertIn("./skills/ads-reports:/opt/data/skills/ads-reports:ro", gw_full)

    def test_mcp_server_config_is_exact(self):
        cfg = read("config.yaml.example")
        self.assertIn('args: ["/opt/cc-bin/hermes-app-mcp.py", "--app", "ads-audit"]', cfg)
        self.assertIn("include: [ads_audit_run, ads_audit_status, ads_audit_list]", cfg)
        self.assertIn('args: ["/opt/cc-bin/hermes-app-mcp.py", "--app", "ads-report"]', cfg)
        self.assertIn("include: [ads_report_run, ads_report_status, ads_report_list]", cfg)
        self.assertIn("env: {}", cfg)

    def test_every_job_s_manifest_has_its_server_and_exactly_its_tools_in_the_template(self):
        sys.path.insert(0, os.path.join(AGENT, "bin"))
        import app_lib as A, mcp_config
        block, why = mcp_config.block_value(read("config.yaml.example"))
        self.assertIsNotNone(block, why)
        mans = A.load_manifests(os.path.join(AGENT, "registry/apps"))
        self.assertEqual(sorted(block), sorted(a.replace("-", "_") for a in mans))
        for app, man in mans.items():
            server = block[app.replace("-", "_")]
            self.assertEqual(server["args"], ["/opt/cc-bin/hermes-app-mcp.py", "--app", app])
            self.assertEqual(sorted(server["tools"]["include"]), sorted(man.tools.values()))
            self.assertEqual((server["env"], server["tools"]["resources"], server["tools"]["prompts"]), ({}, False, False))

    def test_privacy_routing_is_data_collection_deny_only(self):
        cfg = read("config.yaml.example")
        self.assertRegex(cfg, r'(?m)^provider_routing:\n(?:  #.*\n)*  data_collection: "deny"$')
        self.assertNotRegex(cfg, r"(?m)^\s*zdr:")
        self.assertNotRegex(cfg, r"(?m)^\s*only:")
        self.assertIn('default: "deepseek/deepseek-v3.2"', cfg)

    def test_env_example_names_openrouter_and_no_anthropic_for_gateway(self):
        env = read(".env.example")
        self.assertRegex(env, r"(?m)^OPENROUTER_API_KEY=$")
        self.assertNotRegex(env, r"(?m)^ANTHROPIC_API_KEY=")

    def test_skill_exists_and_names_the_tools(self):
        s = read("skills/ads-audits/SKILL.md")
        for t in ("ads_audit_run", "ads_audit_status", "ads_audit_list", "show-audit"):
            self.assertIn(t, s)

    def test_reports_skill_exists_names_its_tools_and_not_the_audit_s(self):
        s = read("skills/ads-reports/SKILL.md")
        for t in ("ads_report_run", "ads_report_status", "ads_report_list", "show-report"):
            self.assertIn(t, s)
        self.assertNotIn("ads_audit_run", s)


if __name__ == "__main__":
    unittest.main()
