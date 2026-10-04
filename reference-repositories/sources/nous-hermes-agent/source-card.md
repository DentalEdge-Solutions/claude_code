---
name: nous-hermes-agent
url: https://github.com/NousResearch/hermes-agent
owner: Nous Research
type: [research-source, governance-source]
status: reference
trust_level: primary (official upstream of the runtime we deploy)
install_policy: do-not-install-directly
last_reviewed: 2026-10-03
review_owner: operator
allowed_uses: [release and security tracking, documentation of the runtime, upgrade evaluation]
prohibited_uses: [direct install without audit, global install without approval, auto-update without approval, bypass skill-audit, bypass agent-audit]
---

# Source Summary
The upstream of Hermes Agent, the runtime our box runs as the gateway (canon 2026-07-21, adopt Nous Hermes Agent). Related official sources: the release notes (https://github.com/NousResearch/hermes-agent/releases), the documentation site (https://hermes-agent.nousresearch.com/docs/), the repository's security advisories page, and the Docker Hub image `nousresearch/hermes-agent`.

# Why It Matters
Every upgrade, security posture and configuration decision about the gateway rests on what this source says and what its pinned image measurably does. Verified data from it is recorded per decision in `docs/evaluations/` (latest: `2026-10-03-hermes-v0-21-5-upgrade-evaluation.md`).

# Reusable Patterns
- MCP client: explicit `mcp_servers` config, `tools.include` allow-list, a filtered environment for stdio servers (only a safe baseline plus the configured `env`).
- Secrets live in `$HERMES_HOME/.env`; non-secret settings in `config.yaml`.
- Dashboard basic auth accepts a password hash (`HERMES_DASHBOARD_BASIC_AUTH_PASSWORD_HASH`) as well as a plaintext password (measured in v0.21.5).

# Candidate Skills
None sourced. Upstream bundled skills are not adopted directly.

# Candidate Agents
None.

# Security / Governance Notes
- As of 2026-10-03 the repository publishes no GitHub security advisories. CVEs filed in third-party databases (CVE-2026-9353, -9366, -9367, -9368, -10221, -10223, -14617, -14625, -17432) affect versions up to 0.15.2, 0.12.0, 2026.4.x or 2026.6.5 builds, or the SimpleX adapter; none affects v0.19.0 or later as recorded. CVE-2026-14617 was declined by the maintainers (no fix).
- The image tag `latest` moves on every push; pin by the multi-arch index digest and re-run the security audit on every upgrade.

# Adaptation Strategy
Read-only source. Upgrades follow a laptop evaluation (local-first canon), then a pull on the box and a security review.

# Eval Ideas
Per upgrade: version and digest, container user (uid 10000), `printenv` present, the committed `mcp_servers` block still parses equal after the gateway runs, `hermes mcp list` without a TTY, our app MCP server connects and lists its three tools.
