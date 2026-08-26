---
name: reference-repo-add
description: "Use when an external repo should be registered as governed source
  material — 'register X as a reference repo', 'add this repo to the reference
  library', 'track this source'. Adds a registry entry + scaffolds a source card;
  never clones or installs the repo. Not for: installing a skill (scout → audit →
  adapt → eval) or auditing an existing entry (reference-repo-audit)."
compatibility: "Claude Code. Node.js ≥ 18."
risk_tier: standard
---

# Reference Repo Add

Register a repository as source material only — metadata + a source card, never an install.

## When to use
- The user wants a repo tracked as methodology/pattern/candidate-skill source material.

## Workflow
1. Confirm with the user: `name` (kebab-case), `url`, and `types` (from the schema enum:
   methodology-source, skill-pattern-source, agent-pattern-source, candidate-skill-source,
   eval-scenario-source, governance-source, retrieval-source, research-source, human-workflow-source).
2. Run: `node scripts/brain/brain-reference-repo-add.js --name <n> --url <u> --types a,b [--use "..."] [--risk "..."]`
3. Open the scaffolded `reference-repositories/sources/<n>/source-card.md`; fill Source Summary /
   Why It Matters / Reusable Patterns with the user (or a quick WebFetch of the repo README — read only).
4. Run `node scripts/brain/brain-reference-repo-audit.js --name <n>` and report the result.

## Files it may edit
- `reference-repositories/registry.json`, `reference-repositories/registry.md`,
  `reference-repositories/sources/<n>/source-card.md` (via the script + card fill).

## Hard rules
- Never clone or install the repo. Registration is metadata + card only.
- `install_policy` is always `do-not-install-directly` — never change it.

## Success criteria
- Entry added, card scaffolded and filled, audit run; nothing cloned or installed.
