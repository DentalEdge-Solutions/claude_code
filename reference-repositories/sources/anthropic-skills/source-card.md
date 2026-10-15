---
name: anthropic-skills
url: https://github.com/anthropics/skills
owner: Anthropic
type: [skill-pattern-source, candidate-skill-source]
status: reference
trust_level: primary for the Agent Skills spec; examples are reference implementations
install_policy: do-not-install-directly
last_reviewed: 2026-10-14
review_owner: Anthropic
allowed_uses: [skill structure patterns, spec reference]
prohibited_uses: [direct install without audit, global install without approval, auto-update without approval, bypass skill-audit, bypass agent-audit]
---

# Source Summary
Anthropic's public Agent Skills repository: 19 skills, plus `spec/` and `template/`. The README calls them "for demonstration and educational purposes only."

# Why It Matters
This is the reference shape for SKILL.md frontmatter and progressive disclosure, against which the project's skill-adapt and skill-eval outputs can be compared.

# Reusable Patterns
- One SKILL.md per directory, with supporting files loaded on demand.

# Candidate Skills
None sourced.

# Candidate Agents
None.

# Security / Governance Notes
- Mixed licensing:
  - Apache-2.0: most skills.
  - Proprietary: docx, pdf, pptx, xlsx ("All rights reserved").
  - No license file: doc-coauthoring.
  - Check each skill's LICENSE.txt before reusing any text.

# Adaptation Strategy
Pattern source only. Any skill adopted from here goes through scout → audit → adapt → eval.

# Eval Ideas
None yet.
