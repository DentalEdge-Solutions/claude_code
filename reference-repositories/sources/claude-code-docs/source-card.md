---
name: claude-code-docs
url: https://code.claude.com/docs/llms.txt
owner: Anthropic
type: [research-source, governance-source]
status: reference
trust_level: primary (official product documentation)
install_policy: do-not-install-directly
last_reviewed: 2026-10-14
review_owner: Anthropic
allowed_uses: [feature and configuration reference, version and limit verification, security and permissions guidance]
prohibited_uses: [direct install without audit, global install without approval, auto-update without approval, bypass skill-audit, bypass agent-audit]
---

# Source Summary
The official Claude Code documentation. `llms.txt` indexes about 233 pages, each served as `.md` (for example `https://code.claude.com/docs/en/memory.md`). The changelog is mirrored at `/docs/en/changelog.md` and weekly digests at `/docs/en/whats-new/2026-wNN.md`.

# Why It Matters
This is Tier A for every claim about how Claude Code behaves. The project's knowledge protocol is `docs/CLAUDE_CODE_KNOWLEDGE.md`; the verification record is `docs/evaluations/2026-10-14-claude-code-knowledge-sources.md`.

# Reusable Patterns
- Placement: CLAUDE.md holds facts every session needs. A multi-step procedure becomes a skill, and part-of-codebase guidance becomes a `.claude/rules/` file with `paths:`. Anything that must always hold becomes a hook (memory.md, features-overview.md).
- Size targets: CLAUDE.md under 200 lines, SKILL.md under 500 lines. The skill listing budget is 1% of the context window; descriptions are truncated at 1,536 characters, and the least-invoked skills lose theirs first on overflow (skills.md).
- Subagent `memory:` does nothing while auto memory is off (sub-agents.md).

# Candidate Skills
None sourced.

# Candidate Agents
None.

# Security / Governance Notes
- Instructions in CLAUDE.md and skills are advisory; hooks are deterministic (best-practices.md).
- Plugins run code with the user's privileges, outside the sandbox (plugins/security.md).
- In `-p` and SDK sessions, hooks from a repo's `.claude/settings.json` run as trusted (hooks.md).

# Adaptation Strategy
Read-only. Cite the `.md` URL and pin each claim to a changelog version. Do not copy whole pages.

# Eval Ideas
Re-run the three smoke queries in the evaluation record after each Claude Code upgrade.
