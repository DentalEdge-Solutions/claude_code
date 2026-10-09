# Project Brain — claude_code

> **Created:** 2026-07-09 · **Mode:** standard · **Capsule:** `.project-brain/`
> Last reviewed: 2026-10-09

Status page and operating protocol for this project's Second Brain.

## Second Brain Protocol

Before architecture, workflow, skill, agent, hook, or governance decisions:

1. Read this file and `MEMORY.md`.
2. Check `index.md` for entry points; prefer existing decisions over new assumptions.
3. Authority ranking: canon > active decision > validated lesson > synthesis > session note > raw source.
4. If memory conflicts with the task, state the conflict before proceeding.

## Memory Routing

- Durable project knowledge → `.project-brain/` (this capsule — git-versioned, shared).
- Personal machine-local observations → Claude Code native auto-memory (`~/.claude/projects/<project>/memory/`).
- Current task context → stays in the session.
- Repeated corrections → lesson candidates via capture-learning.
- Canon → only through `brain-promote --approve`. Never write `canon/` directly.
- NotebookLM/deep-research output → `support/sources/` at raw-source authority,
  then compile → promote like any other content. Research tooling (notebooklm-py,
  notebooklm-skill, deep-research-notebooklm) is registered in the reference
  library — adopt skills from them only through scout → audit → adapt → eval.

## Hard Rules

- No secrets, credentials, tokens, client-private, patient, financial, or legal-sensitive content in memory.
- Do not install directly from reference repositories.
- External skills/agents must pass scout → audit → adapt → eval before activation.

## Reference

Operator manual (every script, hook, and skill): `docs/BRAIN_KERNEL.md`.
Architecture: `docs/SECOND_BRAIN.md` · Security: `docs/SECOND_BRAIN_SECURITY.md`.
