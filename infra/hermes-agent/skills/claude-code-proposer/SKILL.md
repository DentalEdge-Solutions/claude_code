---
name: claude-code-proposer
description: >
  Analyze a REGISTERED Claude Code project (read-only) and produce a structured
  IMPROVEMENT PROPOSAL — enhancements, corrections, new features, or new
  projects — grounded in the project's code and any existing results. Use when
  the user asks to "review", "propose improvements for", "audit for
  opportunities", or "suggest enhancements/new features" for a project by name.
  Proposes only; never modifies the project. Writes the proposal to Hermes
  state via save-proposal.py.
version: 0.1.0
author: claude_code AIOS (P5 Track A)
license: MIT
platforms: [linux]
metadata:
  hermes:
    tags: [Claude-Code, Improvement-Proposal, Read-Only, AIOS, Analysis]
    related_skills: [claude-code-operator, claude-code]
---

# Claude Code Proposer — read-only improvement proposals

You are the control plane. This skill analyzes a registered Claude Code project
and proposes improvements. It is strictly READ-ONLY on projects: it never edits,
commits, or runs mutating commands. It proposes; the human + Claude Code build.

## 1. Resolve the project (read-only)

Read the registry to resolve the project name to its read `workdir`:

    cat /opt/registry/projects.yaml

If the name is not present, tell the user and list the registered names. Never
analyze an unregistered path.

## 2. Analyze (read-only claude -p, Sonnet)

Run Claude Code in the project's read-only workdir to analyze it. Use EXACTLY:

    terminal(
      command="claude -p '<analysis instruction below>' \
        --model claude-sonnet-5 --allowedTools 'Read,Grep,Glob' --permission-mode plan",
      workdir="<workdir from registry>",
      timeout=240
    )

Analysis instruction to pass to claude -p:

    Analyze this project and produce a STRUCTURED IMPROVEMENT PROPOSAL in this
    exact markdown shape:

    # Improvement proposal — <project> — <UTC timestamp>
    ## Summary
    <2-3 sentences>
    ## Items (prioritized)
    - [P1] type: enhancement | correction | feature | new-project
          title: ...
          rationale: ... (grounded in what you actually read)
          evidence: <file paths / observed facts>
          impact / effort: <rough sizing>
    - [P2] ...
    ## Sources consulted
    <code paths; and any brain/telemetry/eval files you read>

    Ground every item in evidence you actually read. Prefer corrections and
    high-impact enhancements first. It is fine to propose an entirely new
    project when the gap warrants it.

## 3. Ground on claude_code signals IF present (read-only, file reads only)

If the project contains any of these, READ them (Read/Grep/Glob only — do NOT
execute scripts) and fold their signals into the proposal, citing them:
- `.project-brain/` — read `canon/`, `decisions/`, `index.md`, `MEMORY.md` to
  align with governance and AVOID re-proposing already-rejected ideas.
- `evals/telemetry/usage-summary.json` and any `REFINE_RECOMMENDED` flags —
  real-usage signals.
- `SKILL-EVAL.md` / `<agent>-EVAL.md` / `project-audit` outputs — quality signals.

## 4. Boundaries — NEVER duplicate claude_code's own machinery

- NEVER run `skill-refine` / `agent-refine` or mutate skills/agents. Capability-
  level improvement is delegated to the project's OWN pipeline if installed —
  you only surface and cite its `REFINE_RECOMMENDED` flags.
- NEVER write to a project's brain `canon/` or `active/`. Read only.
- NEVER reinvent telemetry / `REFINE_RECOMMENDED` / `skill-eval`. Read and cite.

You work at the OPERATIONS/project level (features, corrections, strategy, new
projects); the capability level (skills/agents) belongs to the project's pipeline.

## 5. Persist and surface

Take claude's full proposal output and persist it deterministically:

    <claude's proposal markdown> | python3 /opt/cc-bin/save-proposal.py --project <name>

save-proposal.py prints the written path. Then give the user the `## Summary`
and the saved path. Do NOT write anywhere except via save-proposal.py (which
writes only under Hermes state, never a project).

## 6. Scheduling & monitoring

To run unattended: `hermes cron create <schedule> --skill claude-code-proposer
"review <project> and propose improvements"`. List past proposals with
`python3 /opt/cc-bin/proposals-index.py` (add `--project <name>` or `--open <path>`).
