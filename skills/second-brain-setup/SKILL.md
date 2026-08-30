---
name: second-brain-setup
description: "Use when a freshly bootstrapped project brain needs personalizing —
  'set up the second brain', 'configure the brain', 'personalize BRAIN.md', or
  right after project-brain-bootstrap/install --with-second-brain. Interviews
  the user in 5 short rounds and fills BRAIN.md's human sections and brain-profile
  identity fields in the user's own voice. Not for: creating the capsule (project-brain-
  bootstrap) or capturing knowledge (brain-capture)."
compatibility: "Claude Code. Node.js ≥ 18."
risk_tier: standard
---

# Second Brain Setup (5-round interview)

Fill the brain's human context by interview. Scan before asking; write in the
user's voice; never fabricate — a thin answer produces a thin section.

## Preconditions
- `.project-brain/` exists and passes brain-verify (else route to project-brain-bootstrap).

## The 5 rounds (one round per message; summarize each round back before moving on)
1. **Project & purpose** — what this project is, who it serves, the mission behind it.
2. **Claude's role here** — what the brain should help with; the prime directive if only one thing.
3. **Rules & boundaries** — communication style (AskUserQuestion: blunt / supportive-but-honest / balanced), pet peeves, things Claude must never do here.
4. **Strengths & failure modes** — what the team/user is great at; recurring blind spots; stress defaults.
5. **Goals & current state** — the concrete target (numbers/dates where possible), where things stand today, known risks.

## After the interview
1. Update `BRAIN.md`: add sections `## Project & Purpose`, `## Working Rules`,
   `## Strengths & Failure Modes`, `## Goals & Current State` below the protocol —
   written in the user's voice, thin where answers were thin.
2. Update `context/brain-profile.json`: project_name, project_slug if placeholder-empty.
3. Update the five `context/*.md` stubs with anything the interview surfaced (stack, commands, conventions).
4. Show the full BRAIN.md diff for approval BEFORE writing; loop on targeted edits.
5. Capture: `node scripts/brain/brain-capture.js --type note --title "second-brain-setup completed" --message "<one-line summary>"`

## Hard rules
- Never overwrite the Second Brain Protocol / Memory Routing / Hard Rules sections of BRAIN.md.
- Never write canon; never touch decisions/.

## Files it may edit
- `.project-brain/BRAIN.md` (human sections only), `context/*.md`, `context/brain-profile.json` (identity fields only)
