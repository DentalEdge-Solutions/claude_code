---
name: project-brain-bootstrap
description: "Use when a project needs a brain capsule created — 'set up a project
  brain here', 'bootstrap the second brain', 'this project has no .project-brain'.
  Copies the second-brain template into .project-brain/, fills identity fields,
  and verifies structure. Not for: configuring brain modes or interviews
  (second-brain-setup, Phase 5), installing the whole toolkit (install.sh)."
compatibility: "Claude Code. Node.js ≥ 18."
risk_tier: standard
---

# Project Brain Bootstrap

Create a verified `.project-brain/` capsule from the template.

## Workflow
1. If `.project-brain/` already exists: STOP and report — never overwrite an existing capsule.
2. Run: `bash scripts/brain/brain-self-install.sh <target>` (from the toolkit repo; default target = cwd).
3. Confirm `brain-verify` passed; if it failed, show violations and stop.
4. Sync parent context (KJ OS pattern — keep the index aware of what exists): append a line to `.project-brain/index.md` noting bootstrap date, and capture a bootstrap note via brain-capture.js.
5. Point the user at next steps: capture with brain-capture; hooks now auto-log compaction and session end.

## Files it may edit
- `.project-brain/**` (creation only), `.claude/settings.local.json` (hook merge via script), `.gitignore` (one line via script)

## Files it must NOT edit
- An existing capsule's content; `CLAUDE.md`; `install.sh`.

## Failure modes
- brain-verify exit 1 → show violations verbatim; do not hand-patch canon or governance files to force a pass.

## Success criteria
- Fresh capsule passes brain-verify; existing capsules untouched; hooks registered.
