---
name: nous-hermes-agent-self-evolution
url: https://github.com/NousResearch/hermes-agent-self-evolution
owner: Nous Research
type: [methodology-source, research-source]
status: reference
trust_level: primary for its own claims (official Nous Research project); experimental
install_policy: do-not-install-directly
last_reviewed: 2026-10-03
review_owner: operator
allowed_uses: [methodology reference for skill refinement]
prohibited_uses: [direct install without audit, global install without approval, auto-update without approval, bypass skill-audit, bypass agent-audit]
---

# Source Summary
Evolutionary optimisation of Hermes skills, tool descriptions, prompts and code using DSPy and GEPA. As read on 2026-10-03: phase 1 (SKILL.md files) is implemented; phases 2 to 5 (tools, prompts, code) are planned. It states that "all changes go through human review, never direct commit" and that every evolved variant must pass the full test suite, size limits, caching compatibility and semantic preservation. Cost stated as about $2 to $10 per optimisation run; it needs model API access.

# Why It Matters
It overlaps our own skill-refine / agent-refine loop (Karpathy autoresearch). Its constraint gates are a useful comparison for our refine levers.

# Reusable Patterns
- Human review as a hard gate on every evolved variant.
- Constraint gates (tests, size, caching, semantic preservation) before acceptance.

# Candidate Skills
None adopted. Any skill or agent from it goes through scout, audit, adapt and eval.

# Candidate Agents
None.

# Security / Governance Notes
Optimisation can read real session history; that history may hold client data and must not leave the box or the operator's control.

# Adaptation Strategy
Methodology only, compared against skill-refine. Revisit when phases beyond 1 ship.

# Eval Ideas
Compare its acceptance gates with skill-refine's levers on one of our skills.
