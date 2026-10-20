---
name: skill-audit
description: Security gate that scans a skill sourced from GitHub for prompt injection, malicious scripts, permission escalation, and supply chain risks before installation. Use when auditing a skill, checking skill security, scanning a skill from GitHub, or before installing any externally sourced skill.
compatibility: "Claude Code. Node.js ≥ 18."
risk_tier: critical
---

# Skill Audit

Security gate. Run this **before** any external skill is installed into the project skills directory.

## Quick start

```
User: audit the skill at /tmp/candidate-skill
```

Run `node skills/skill-audit/scripts/static-scan.js /tmp/candidate-skill` then review the JSON output and produce SKILL-AUDIT.md.

## Workflow

1. **Static scan** — run the 47-pattern scanner against the skill directory, agent file, or settings file:
   ```bash
   node skills/skill-audit/scripts/static-scan.js <skill-dir|agent.md|settings.json>
   ```
   Covers 5 categories: prompt injection, dangerous Bash, hardcoded secrets (Anthropic/GitHub/AWS keys), overly permissive settings.json rules, and malicious scripts. Records PASS/FLAG/BLOCK per finding. Content it cannot fully check is never a silent PASS: an unreadable file or directory, or a FIFO or device, is BLOCK; a file too large to read whole, or a symlink leaving the tree, is FLAG. See REFERENCE.md, "What the scanner cannot check".

2. **Permissions audit** — read every `.md` file; list all tools, Bash commands, and external URLs the skill's instructions request. Check each against the skill's stated purpose. Flag mismatches (e.g., a "summarize" skill requesting `rm` or WebFetch to unknown domains).

3. **Provenance check** — if sourced from GitHub, note: repo age, star count, last commit date, contributor count. Flag repos <30 days old, 0 stars, or single-commit history.

4. **Diff review** — if updating an existing installed skill, generate a line-level diff vs the current version. Present the raw diff to the user, then perform an LLM review of the diff: flag any new tool permissions, new Bash commands, new network calls, changed verdict logic, or content that diverges from the skill's stated purpose.

5. **Write SKILL-AUDIT.md** — save report to `<skill-dir>/SKILL-AUDIT.md` using the template in REFERENCE.md.

## Verdicts

| Verdict | Meaning | Action |
|---------|---------|--------|
| PASS | No issues found | Proceed to skill-adapt |
| FLAG | Suspicious but not blocking | Show findings, ask user to confirm before proceeding |
| BLOCK | Confirmed threat | Do NOT write to `~/.claude/skills/`. Require manual clearance. |

## Rules

- Never write a BLOCK skill to the project skills directory for any reason.
- A FLAG requires explicit user confirmation before proceeding.
- Static scan output is authoritative — do not override it with judgment.
- Re-audit after any manual edits to a flagged skill.
- If a `skill-audit-policy.json` file exists in the project root, apply its `allowlist` (skip those check names) and `blocklist` (auto-BLOCK those check names) before finalizing the verdict.

See [REFERENCE.md](REFERENCE.md) for threat patterns, red-flag strings, and permission matrix.
