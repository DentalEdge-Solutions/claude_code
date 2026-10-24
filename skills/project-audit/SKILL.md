---
name: project-audit
description: "Use when: auditing Claude Code project security, checking for hardcoded secrets or overly permissive Bash rules, reviewing hooks for injection risks, scanning MCP server configurations, checking agents for prompt injection, or before installing new skills. Wraps ecc-agentshield to scan .claude/ configuration files across 5 categories — Secrets, Permissions, Hooks, MCP Servers, Agents — and returns an A–F grade with numbered findings. Offers auto-fix for safe issues. Run after project-setup and before skill-scout as part of the pipeline, or standalone at any time. Requires Node.js ≥ 18 for npx."
compatibility: "Claude Code. Node.js ≥ 18 required (npx ecc-agentshield@1.4.0). No install needed — runs via npx."
risk_tier: critical
---

# Project Audit

Scan your Claude Code configuration for security issues and get an A–F grade across 102 rules.

## Quick start

```
User: audit my project security
User: check my Claude Code setup for secrets
User: scan before installing new skills
```

## Workflow

### Step 1 — Verify Node.js

```bash
node --version 2>/dev/null
```

If Node.js is unavailable, respond:
> "project-audit requires Node.js ≥ 18 (for npx ecc-agentshield). Install from https://nodejs.org/ and retry."

Stop here if Node is missing.

### Step 2 — Determine scan target

Identify which `.claude/` directory to scan:

- If `evals/project-context.json` exists, derive the project root from cwd.
- Scan path: `.claude/` relative to cwd (project-scoped configuration).
- Always also scan `~/.claude/` (global configuration — secrets and permissions apply globally).

### Step 3 — Run the scan

Run the JSON scan on the project directory:

```bash
npx ecc-agentshield@1.4.0 scan --format json --path .claude 2>/dev/null
```

If `.claude/` does not exist, scan the global directory instead:

```bash
npx ecc-agentshield@1.4.0 scan --format json 2>/dev/null
```

If the command fails or produces no output (network unavailable, npx error), fall back to text output:

```bash
npx ecc-agentshield@1.4.0 scan --path .claude 2>/dev/null
```

Present the text output as-is and skip Steps 4–6.

### Step 4 — Parse and present results

From the JSON output, extract and display:

```
══════════════════════════════════════════════════
 PROJECT AUDIT — Security Report
══════════════════════════════════════════════════

Grade: <A|B|C|D|F>  (<score>/100)

Category scores:
  Secrets        <score>/100
  Permissions    <score>/100
  Hooks          <score>/100
  MCP Servers    <score>/100
  Agents         <score>/100

Findings: <total> total
  <critical> critical  <high> high  <medium> medium  <low> low  <info> info
  Auto-fixable: <N>

──────────────────────────────────────────────────
```

Then list findings, grouped by severity. For each finding:

```
● <SEVERITY>  <title>
  File: <file>:<line>
  Evidence: <evidence (truncated to 60 chars)>
  Fix: <fix description>  [auto-fixable] or [manual]
```

Show ALL critical and high findings. For medium/low/info: show the first 3 and summarise the rest ("+ N more medium findings").

### Step 4b — Persist security posture to project-context.json

After displaying the report, update `evals/project-context.json` with the scan result so the current security posture travels with the project context and can be read without re-running AgentShield (`extract-project-context.js` keeps these three fields when it regenerates the file).

If `evals/project-context.json` exists and Node.js is available, run:

```bash
node -e "
const fs = require('fs'), p = 'evals/project-context.json';
try {
  const ctx = JSON.parse(fs.readFileSync(p, 'utf8'));
  ctx.security_grade = '<GRADE>';
  ctx.security_score = <SCORE>;
  ctx.security_last_scanned = new Date().toISOString().slice(0, 10);
  fs.writeFileSync(p, JSON.stringify(ctx, null, 2));
  console.log('Security posture saved to', p);
} catch (e) { /* silent — evals/ may not exist yet */ }
"
```

Replace `<GRADE>` with the letter grade (A/B/C/D/F) and `<SCORE>` with the numeric score from the JSON output. If the file does not exist or Node.js is unavailable, skip this step silently — it is a convenience record, not a blocking requirement.

### Step 4c — Write full audit artifact

Write a dated JSON artifact so security posture can be compared across runs:

```bash
node -e "
const fs = require('fs');
const date = new Date().toISOString().slice(0, 10);
const outDir = 'evals';
try { fs.mkdirSync(outDir, { recursive: true }); } catch {}
const artifact = {
  date,
  grade: '<GRADE>',
  score: <SCORE>,
  category_scores: {
    secrets:     <secrets_score>,
    permissions: <permissions_score>,
    hooks:       <hooks_score>,
    mcp_servers: <mcp_score>,
    agents:      <agents_score>
  },
  findings_summary: {
    total:    <total>,
    critical: <critical>,
    high:     <high>,
    medium:   <medium>,
    low:      <low>,
    info:     <info>,
    auto_fixable: <auto_fixable>
  }
};
fs.writeFileSync(outDir + '/project-audit-' + date + '.json', JSON.stringify(artifact, null, 2));
console.log('Audit artifact written to evals/project-audit-' + date + '.json');
"
```

If `evals/` does not exist or Node.js is unavailable, skip silently. The artifact is informational — no script or agent reads it automatically; it is for the owner to compare by hand: the most recent one (by filename date) against previous runs, to see security trends.

### Step 5 — Offer auto-fix

If any auto-fixable findings exist:

> "AgentShield can automatically fix <N> finding(s) (replacing hardcoded secrets with env var references and similar safe changes). Apply auto-fixes? [y/N]"

If user confirms:

```bash
npx ecc-agentshield@1.4.0 scan --fix --path .claude 2>/dev/null
```

Report which fixes were applied. Re-run Step 3 to show the updated score.

### Step 6 — Grade gate and handoff

| Grade | Action |
|-------|--------|
| A or B | "Security posture is strong. Safe to proceed with skill-scout." |
| C | "Acceptable but improvements recommended — review medium findings before sourcing production skills." |
| D | "Below threshold — address critical and high findings before installing new skills. Run `/project-audit` again after fixing." |
| F | "Critical issues found — do not install new skills until resolved. Run `npx ecc-agentshield@1.4.0 scan --fix` and address manual findings." |

For grade C or above: print handoff message:
> "Next: 'find a skill for <capability>' or run skill-needs-analysis-agent to get a prioritized skill shortlist."

## Rules

- **Never hard-block the pipeline** — this skill is advisory. Always show findings and let the user decide whether to proceed.
- **Never run `--opus`** unless the user explicitly requests it (it makes API calls and may incur cost).
- **Never modify configuration files directly** — use `--fix` flag only; never write settings.json or agents/*.md manually.
- **Never pipe output to a file without asking** — HTML reports (`--format html`) are opt-in only.
- If the scan takes >30 seconds (slow network downloading npx package), tell the user: "Downloading ecc-agentshield — this is a one-time download, subsequent runs are faster."
