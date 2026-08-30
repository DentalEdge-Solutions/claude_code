---
name: reference-repo-pattern-extract
description: "Use when reusable patterns should be extracted from any registered
  reference source — 'extract patterns from <source>', 'what can we reuse from
  <source>', 'mine <source> for patterns'. Generic version of gstack-pattern-audit,
  parameterized by the source card's mapped patterns. Not for: GStack specifically
  (gstack-pattern-audit) or registering a new source (reference-repo-add)."
compatibility: "Claude Code. Node.js ≥ 18."
risk_tier: standard
---

# Reference Repo Pattern Extract

Distill any audited reference source into governed synthesis content.

## When to use
- The user wants patterns/candidate skills/candidate agents pulled from a registered source.

## Workflow
1. REQUIRE a clean audit first: `node scripts/brain/brain-reference-repo-audit.js --name <n>` (exit 0).
   An exit-3 source is blocked — resolve findings before extracting.
2. Map the card: `node scripts/brain/brain-reference-repo-map.js --name <n> --json`
   → `{patterns, candidate_skills, candidate_agents}`.
3. WebFetch the live repo (read-only) to enrich each mapped pattern; write findings to
   `.project-brain/synthesis/<name>-patterns/<topic>.md` (`type: synthesis`, `status: candidate`).
4. Run `node scripts/brain/brain-reference-repo-refresh.js --name <n>`.

## Files it may edit
- `.project-brain/synthesis/<name>-patterns/*`, `reference-repositories/sources/<n>/source-card.md`.

## Hard rules
- No extraction from a source with an open exit-3 audit finding.
- Output is synthesis authority — never canon; candidate skills/agents go through the full pipeline.

## Success criteria
- Clean-audit gate enforced; patterns captured as synthesis candidates; nothing installed directly.
