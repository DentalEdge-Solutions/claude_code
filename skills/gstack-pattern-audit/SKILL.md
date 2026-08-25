---
name: gstack-pattern-audit
description: "Use when reusable patterns should be extracted from the GStack
  reference source — 'analyze gstack', 'extract gstack patterns', 'what can we
  learn from gstack'. Compares the live GStack repo against its source card and
  writes synthesis-authority findings into .project-brain/synthesis/gstack-patterns/.
  Not for: installing a gstack skill (scout → audit → adapt → eval) or generic
  sources (reference-repo-pattern-extract)."
compatibility: "Claude Code. Node.js ≥ 18."
risk_tier: standard
---

# GStack Pattern Audit

Turn GStack (methodology + skill/agent patterns) into governed synthesis content.

## When to use
- The user wants GStack's sprint-loop / review-chain / QA patterns distilled for reuse.

## Workflow
1. Confirm the gstack entry passes `node scripts/brain/brain-reference-repo-audit.js --name gstack` (exit 0).
2. WebFetch the live GStack README + skill list (read-only); compare against
   `reference-repositories/sources/gstack/source-card.md`.
3. Write findings to `.project-brain/synthesis/gstack-patterns/<topic>.md` with frontmatter
   `type: synthesis`, `status: candidate` (synthesis is promoted like everything else — never write canon).
4. Update the card's `# Reusable Patterns` section with anything new.
5. Run `node scripts/brain/brain-reference-repo-refresh.js --name gstack` to bump last_reviewed.

## Files it may edit
- `.project-brain/synthesis/gstack-patterns/*`, `reference-repositories/sources/gstack/source-card.md`.

## Hard rules
- Extraction output is SYNTHESIS authority — never canon, never a direct skill install.
- Adopt any GStack skill only through scout → audit → adapt → eval.

## Success criteria
- Patterns captured as synthesis candidates citing the source; card refreshed; nothing installed.
