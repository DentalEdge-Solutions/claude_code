---
name: hermes-optimization-guide
url: https://github.com/OnlyTerp/hermes-optimization-guide
owner: Terp (Terpy AI Labs), independent; not affiliated with Nous Research
type: [methodology-source, human-workflow-source]
status: reference
trust_level: community (corroboration only)
install_policy: do-not-install-directly
last_reviewed: 2026-10-03
review_owner: operator
allowed_uses: [corroborating official Hermes sources, operations ideas to verify upstream]
prohibited_uses: [direct install without audit, global install without approval, auto-update without approval, bypass skill-audit, bypass agent-audit, sole basis for a decision]
---

# Source Summary
A community operations guide for Hermes Agent, stated as verified against v0.21.4 (2026-09-21), with weekly CI that checks commands, flags and config keys against the pinned version. As read on 2026-10-03 it says versions below v0.21.2 should update for `state.db` safety, which the official v0.21.2 and v0.21.3 release notes corroborate (lock, false-corruption and writer-handle fixes).

# Why It Matters
It is a cross-check on the official notes and a source of operational practice (cost routing of auxiliary models, `hermes update --check` / `--plan` before updating).

# Reusable Patterns
- Check upgrade impact before updating (`hermes update --check`, `--plan`).
- Route auxiliary tasks to cheap models deliberately.

# Candidate Skills
None adopted.

# Candidate Agents
None.

# Security / Governance Notes
Never the sole basis for a decision: every claim used is checked against the official repository, release notes or a measurement.

# Adaptation Strategy
Read for ideas; verify each against upstream before acting.

# Eval Ideas
None.
