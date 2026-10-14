---
name: claude-code-ultimate-guide
url: https://github.com/FlorianBruniaux/claude-code-ultimate-guide
owner: Florian Bruniaux (single maintainer)
type: [methodology-source, research-source]
status: reference
trust_level: independent (Tier C): corroboration only for native behaviour
install_policy: do-not-install-directly
last_reviewed: 2026-10-14
review_owner: Florian Bruniaux (single maintainer)
allowed_uses: [methodology vocabulary, ecosystem maps, comparison of third-party tools]
prohibited_uses: [direct install without audit, global install without approval, auto-update without approval, bypass skill-audit, bypass agent-audit]
---

# Source Summary
A large independent guide (v3.44.1, about 6.2k stars), also published at cc.bruniaux.com by the same publisher (one source, not two). Its release page tracks Claude Code 2.1.296, while the project runs 2.1.300.

# Why It Matters
Useful map of methodologies (spec-first, plan pipelines, agent-harness layers) and of third-party orchestrators, as input for the Phase 2 software-factory evaluation.

# Reusable Patterns
- Software factory = an operating model, not a product. The guide uses four layers: model, runtime harness, repo harness, orchestrator.
- Decision tree: guaranteed ordering, retries or a hard stop mean a hook, script, CI job or dynamic workflow; a reusable procedure means a skill; everything else goes in CLAUDE.md.

# Candidate Skills
None sourced.

# Candidate Agents
None.

# Security / Governance Notes
- License CC BY-SA 4.0 (templates CC0): quote and attribute. Adapted text inherits ShareAlike.
- Conflicts with official docs and primary sources are recorded in the evaluation record: CLAUDE.md size, hook input via env vars vs JSON on stdin, Hermes "formerly OpenClaw", and guide-assigned advisory IDs.

# Adaptation Strategy
Read-only. Every claim about a native feature must be confirmed against claude-code-docs before use.

# Eval Ideas
None.
