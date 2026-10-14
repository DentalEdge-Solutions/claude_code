---
name: anthropic-claude-plugins-official
url: https://github.com/anthropics/claude-plugins-official
owner: Anthropic
type: [skill-pattern-source, agent-pattern-source]
status: reference
trust_level: primary for the official plugin directory
install_policy: do-not-install-directly
last_reviewed: 2026-10-14
review_owner: Anthropic
allowed_uses: [plugin structure patterns, marketplace trust model]
prohibited_uses: [direct install without audit, global install without approval, auto-update without approval, bypass skill-audit, bypass agent-audit]
---

# Source Summary
Anthropic's managed directory of Claude Code plugins (Apache-2.0).

# Why It Matters
It shows how plugins bundle skills, agents, hooks and MCP servers. Relevant if the toolkit is ever packaged as a plugin (a Phase 2 question).

# Reusable Patterns
- Plugin manifest and layout conventions.

# Candidate Skills
None sourced.

# Candidate Agents
None.

# Security / Governance Notes
- Per plugins/security.md: "Anthropic does not control what MCP servers, files, or other software are included in plugins." Auto-update can change files after review.

# Adaptation Strategy
Pattern source only. Never install a plugin from here without project-audit.

# Eval Ideas
None yet.
