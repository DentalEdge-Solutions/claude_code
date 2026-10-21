---
name: team-eval
description: "Use when: evaluating an agent team or multi-agent orchestration end-to-end, measuring dispatch-chain accuracy or handoff integrity, checking whether an orchestrator uses its member agents correctly, or auditing an ensemble like the repo-audit analysts as a unit. Evaluates the ORCHESTRATION (orchestrator + members together), not any single definition — for one skill use skill-eval, for one agent use agent-eval. Requires a team.json manifest. Triggers on: evaluate the team, team eval, test the orchestration, check the ensemble, dispatch-chain accuracy, handoff integrity."
compatibility: "Claude Code. Node.js ≥ 18. Requires Agent tool for scenario execution."
---

# Team Eval

Evaluate an agent team — an orchestrator plus the member agents it dispatches — as a single unit.
Per-definition evals (skill-eval, agent-eval) never exercise member selection, handoffs, or
ensemble degradation; this skill fills that blind spot.

## Quick start

```
User: evaluate the repo-audit-ensemble team
User: run a team eval on the repo-audit analysts
User: check whether the orchestration dispatches its members correctly
```

## The team manifest (team.json)

Every team eval starts from a committed manifest. Reference example:
`fixtures/teams/repo-audit-ensemble/team.json`.

```json
{
  "team_name": "repo-audit-ensemble",
  "description": "what the orchestration does",
  "orchestrator": { "type": "skill", "name": "repo-audit" },
  "members": [ { "agent": "repo-audit-runtime", "role": "runtime layer" } ],
  "handoff_contract": "what each member receives and must return",
  "expected_artifacts": ["docs/audits/"],
  "example_target": "https://github.com/expressjs/express"
}
```

All fields are required (members non-empty; every `members[].agent` must exist at
`.claude/agents/<agent>.md`; the orchestrator at `skills/<name>/SKILL.md` or
`.claude/agents/<name>.md`).

## Workflow

1. **Load the manifest** — read team.json, the orchestrator definition, and every member
   definition in full. Aggregate context footprint = total lines across orchestrator + all member
   definitions × 4 estimated tokens/line. Before any run, record the sha256 of the orchestrator and
   of every member definition (`shasum -a 256 <file>`) and the commit (`git rev-parse --short HEAD`):
   team-eval writes no run manifest, so these are the revisions the report cites.

2. **Generate scenarios**:
   `node skills/team-eval/scripts/generate-team-evals.js <team.json> --context evals/project-context.json`
   Writes 6 scenarios to `evals/teams/<team_name>/evals.json`:

   | Type | Dispatches? | Tests |
   |------|-------------|-------|
   | `full-run` | ✓ all members | end-to-end orchestration + final artifact |
   | `partial-team` | ✓ subset | only the requested members run |
   | `member-failure` | ✓ all minus one | graceful degradation, no fabricated layer |
   | `handoff-integrity` | ✓ all | member outputs consumed, not re-derived |
   | `negative` | ✗ | describe the team without dispatching it |
   | `adversarial` | ✗ | team vocabulary, wrong scope — must not dispatch |

3. **Execute scenarios** — one orchestrator run per scenario, executed by this Claude session
   (never auto-executed by a script; team runs spawn many subagents and are deliberately
   human-invoked). For each scenario, run the orchestrator against the scenario prompt with all
   artifacts rooted at `evals/teams/<team_name>/iteration-<N>/s<id>-<type>/run/` (workspace
   sandbox + output.md transcript, same layout as skill-eval scenario sides). The transcript MUST
   record each real member dispatch with the literal token `Agent(<member-name>)` — the same
   invocation-token contract as agent-eval; narrative mentions never count.

4. **Harvest evidence** — the existing harvester consumes team evidence unchanged:
   `node skills/skill-eval/scripts/harvest-evidence.js evals/teams/<team_name>/iteration-<N> --type agent --all`

5. **Grade evidence-first** — per scenario:
   - **Dispatch-chain correctness comes ONLY from evidence.json's `transcript_markers` array** —
     every member marker must match its `expect` (present/absent). Never use the single
     `agent_dispatched` boolean for team grading: it reflects only the first marker.
   - LLM-judge score (0–10) against the scenario's `expected.judgment` items plus output quality.
   - Composite = (dispatch-chain-correct ratio × 0.4) + (judgment/output × 0.4) + (artifact
     evidence × 0.2). Negative/adversarial are binary: 10 if zero members dispatched and the
     response was useful, 0 if any member dispatched.

6. **Compute 5 metrics**:

   | Metric | Definition | Threshold |
   |--------|------------|-----------|
   | Team Pass Rate | scenarios with composite ≥ 7 / total | ≥ 80% |
   | Dispatch-Chain Accuracy | correct member dispatch decisions / total member-checks | ≥ 85% |
   | Handoff Integrity | verifiably consumed member outputs / expected handoffs | ≥ 90% |
   | Aggregate Context Footprint | orchestrator + member definitions, lines / est. tokens | informational |
   | Team Resilience | negative + adversarial correctly not dispatching / total × 10 | ≥ 8/10 |

7. **Write the report** to `evals/teams/<team_name>/TEAM-EVAL.md` (same table format family as
   SKILL-EVAL.md), with per-scenario results and analyst observations, and the same **Evidence and
   Limits** section: the revisions recorded in step 1, untested items with reasons, limitations.
   Before writing, re-hash every definition; if any differs from step 1, the report says which, since
   the runs may have measured either text. As in skill and agent reports, the commit is HEAD when the
   run started, so it does not contain uncommitted edits.
   Its evidence line states that member dispatch is read from the `Agent(<member>)` token the run is
   instructed to write — a marker in the transcript, not an independent tool-call log.

8. **Below threshold?** Write `evals/teams/<team_name>/refine-input.json` routing to the
   ORCHESTRATOR's refine track (skill-refine for a skill orchestrator, agent-refine for an agent
   one). There is no team-refine — member definitions are refined individually via agent-refine
   when member-level defects are implicated.

## What NOT to Do

- Never evaluate a single skill/agent with this — that's skill-eval / agent-eval.
- Never auto-execute team scenarios from a script — execution is session-driven and human-invoked.
- Never mutate member or orchestrator definitions during an eval.
- Never grade dispatch-chain accuracy from the `agent_dispatched` boolean or from narrative
  mentions — only the full `transcript_markers` evidence counts.
- Never skip members in the manifest — every member carries a marker in every scenario.
