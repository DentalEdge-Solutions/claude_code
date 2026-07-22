---
name: claude-code-operator
description: >
  Operate a REGISTERED Claude Code project through Hermes by driving `claude -p`
  in that project's directory. Use when the user asks to inspect, summarize,
  audit, review, explain, or ask questions ABOUT a project by name — e.g. "in
  claude_code, summarize the testing setup", "what agents does <project> have",
  "audit <project>'s skills". Read-only for now: reporting/analysis only, no file
  writes. Resolves the project name to a working directory and model tier from
  the registry at /opt/registry/projects.yaml.
version: 0.1.0
author: claude_code AIOS (P2)
license: MIT
platforms: [linux]
metadata:
  hermes:
    tags: [Claude-Code, Orchestration, Project-Operator, Read-Only, AIOS]
    related_skills: [claude-code]
---

# Claude Code Operator — drive registered projects via `claude -p`

You are the control plane. This skill lets you OPERATE a Claude Code project on
the user's behalf by running `claude -p` (headless Claude Code) inside that
project's directory. Claude Code carries each project's own skills, agents,
`CLAUDE.md`, and governance — so `claude -p` is the correct executor; you just
route to it. For the raw `claude -p` mechanics (flags, JSON output, resuming
sessions), defer to the bundled **claude-code** skill; THIS skill adds project
resolution, model economy, and the read-only guardrail.

## 1. Resolve the project from the registry

The registry is the source of truth for which projects you may operate:

    cat /opt/registry/projects.yaml

Each entry has `workdir` (absolute path in the container), `scope`
(`read` | `write`), `default_model`, and a `description`. Match the user's named
project to an entry.

- If the name is NOT in the registry → tell the user it is not registered and
  list the available project names. Never operate an unregistered path.

## 2. Enforce scope (READ-ONLY for now)

- `scope: read` → read-only analysis ONLY. Every `claude -p` call MUST include
  `--permission-mode plan` and `--allowedTools 'Read,Grep,Glob'`. Never pass
  write tools (`Edit`/`Write`/`Bash`) or `--dangerously-skip-permissions`.
- `scope: write` → NOT YET PERMITTED (gated, plan P5). If the user asks to
  change/fix/refactor/commit, REFUSE and explain write access is gated and not
  yet enabled; offer a read-only plan of what WOULD change instead.

## 3. Pick the model tier (economy)

`claude -p` runs direct on Anthropic; pick the cheapest tier that fits:

- Routine read work (summaries, inventories, "how do I…", locating things) →
  the project's `default_model` (typically `claude-haiku-4-5`).
- Genuinely hard analysis (multi-file reasoning, subtle audits, architecture
  synthesis) → step up to `claude-sonnet-5`.
- Do not use Opus for routine operator tasks.

## 4. Run it

Use your terminal tool with `workdir` set to the resolved path:

    terminal(
      command="claude -p '<the user's task, as a precise instruction>' \
        --model <tier> --allowedTools 'Read,Grep,Glob' --permission-mode plan",
      workdir="<workdir from registry>",
      timeout=200
    )

Return Claude's answer to the user, grounded and attributed to the project. If
Claude reports it needs write access or more tools, surface that as a read-only
limitation (P2) — do not escalate tools.

## 5. Multi-step / scheduled workflows

For chained work, each step is its own `claude -p` call in the same `workdir`.
To run unattended, register the workflow with Hermes cron:

    hermes cron create <schedule> --workdir <path> --skill claude-code-operator "<task>"

Monitoring: `hermes cron runs` / `hermes cron history` show durable attempts;
report results back to the user.
