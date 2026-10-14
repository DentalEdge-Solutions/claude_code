---
name: anthropic-claude-code
url: https://github.com/anthropics/claude-code
owner: Anthropic
type: [research-source, governance-source]
status: reference
trust_level: primary (release and advisory evidence)
install_policy: do-not-install-directly
last_reviewed: 2026-10-14
review_owner: Anthropic
allowed_uses: [release tracking, changelog, security advisories]
prohibited_uses: [direct install without audit, global install without approval, auto-update without approval, bypass skill-audit, bypass agent-audit]
---

# Source Summary
The public Claude Code repository. It holds `CHANGELOG.md`, `feed.xml`, plugins, examples and the issue tracker. The product itself is not in this repo: it ships as a native binary. The license is proprietary (Commercial Terms of Service).

# Why It Matters
Releases and GitHub security advisories (GHSA) set version floors. As of 2026-10-14 there are 37 advisories (18 for the CLI, 19 for Desktop and other packages), and none affects CLI 2.1.300 or Desktop 2.37337.1.

# Reusable Patterns
- `feed.xml` and the releases API are the cheapest change signals (see the freshness proposal in docs/CLAUDE_CODE_KNOWLEDGE.md §5).

# Candidate Skills
None sourced.

# Candidate Agents
None.

# Security / Governance Notes
- Check the advisories API (`repos/anthropics/claude-code/security-advisories`) on every upgrade decision.
- Third-party advisory IDs (for example the guide-assigned `ADVISORY-CC-*`) are not GHSA IDs; verify them before relying on them.

# Adaptation Strategy
Read-only. Do not copy content (proprietary).

# Eval Ideas
On upgrade: `claude --version` equals the latest release, and no advisory's patched version is above the installed one.
