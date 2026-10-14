# Claude Code Skill & Agent Pipeline Toolkit — User Guide

## What This Project Is

The `claude_code` toolkit is a self-contained pipeline for finding, vetting, adapting, measuring, and continuously improving Claude Code skills and agents. It solves a specific problem: when you need a Claude Code skill for your project, you shouldn't write it from scratch or blindly install one from the internet. Instead, you source from known registries, apply a security gate, adapt to your project's context, measure effectiveness, and auto-improve until the skill meets measurable quality thresholds.

---

## Why It Exists

Claude Code's skill system is powerful but has two failure modes without this toolkit:

1. **Writing from scratch is slow and inconsistent.** Skills require careful trigger design, workflow structure, and project alignment. The ecosystem already has hundreds of skills — building what already exists wastes time.

2. **Installing blindly is dangerous.** External skills can contain prompt injection, permission escalation, or supply chain attacks. Without a security gate, you're trusting arbitrary GitHub content.

This toolkit closes both gaps: discover → vet → adapt → measure → improve.

---

## How It Works

### The Full Pipeline

```
project-setup → project-audit → skill-scout → skill-audit → skill-adapt → skill-eval → skill-refine
                                                               ↕
                                              agent-scout → agent-audit → agent-adapt
```

Each stage has a clear input and output:

| Stage | Input | Output |
|---|---|---|
| `project-setup` | Conversational interview | `CLAUDE.md` + `evals/project-context.json` |
| `project-audit` | `.claude/` directory | A–F security grade, findings report |
| `skill-scout` | Capability description | Ranked shortlist of 3 candidates |
| `skill-audit` | Candidate SKILL.md file | PASS / FLAG / BLOCK verdict |
| `skill-adapt` | PASS-audited skill + project context | Project-native adapted skill |
| `skill-eval` | Adapted skill | 5 metrics + `refine-input.json` if failing |
| `skill-refine` | `refine-input.json` | Iteratively improved skill |

The agent pipeline (`agent-scout → agent-audit → agent-adapt`) mirrors the skill pipeline for Claude Code sub-agent definitions.

### The Shared Data Contract: `evals/project-context.json`

Every downstream stage reads from a single file that describes the project:

| Field | Source | Used by |
|---|---|---|
| `project_name` | `package.json` / directory name | All stages |
| `stack` | `package.json` deps, `pyproject.toml`, `Cargo.toml`, `go.mod`, `engines.node` | skill-scout, skill-adapt, skill-needs-analysis |
| `workflow_terms` | `CLAUDE.md` all-caps tokens | skill-adapt, eval scenario 7 |
| `installed_skills` | `skills/` directory | skill-scout conflict check |
| `key_phrases` | `README.md`, `package.json` description | skill-eval scenario 7 |
| `artifact_paths` | `CLAUDE.md`, planning docs | skill-adapt |
| `hooks` | `.claude/settings.json` + `~/.claude/settings.json` | skill-adapt (avoid redundant steps) |
| `mcp_servers` | `.mcp.json` | skill-adapt, skill-needs-analysis |
| `plugins` | `~/.claude/settings.json:enabledPlugins` | skill-scout conflict check |

Run at any time to refresh: `node skills/skill-eval/scripts/extract-project-context.js`

---

## Installation

### Prerequisites

- Claude Code (any version)
- Node.js ≥ 18 (required for scanner scripts and eval generation; pipeline degrades gracefully without it but loses eval capabilities)

### Install to a target project

```bash
# Preview what will happen (no files written)
./install.sh --dry-run /path/to/your-project

# Apply installation
./install.sh /path/to/your-project

# Remove
./uninstall.sh /path/to/your-project
```

**What `install.sh` does:**

1. Copies all skills to `<project>/skills/` (source of truth)
2. Syncs all skills to `~/.claude/skills/` (Claude Code runtime)
3. Copies all specialist agents to `<project>/.claude/agents/`
4. Creates `<project>/evals/` workspace
5. Adds `.gitignore` entries for generated artifacts
6. If `evals/project-context.json` already exists and predates the June 2026 field expansion, offers to regenerate it

Skills and agents are discovered dynamically from the repo — no hardcoded list. Future skills added to `skills/` are automatically picked up.

---

## First-Time Setup (New Project)

Run these three steps before sourcing any skills:

### Step 1: Configure project context

```
/project-setup
```

This runs a guided 6-question interview (one question at a time, recommended answers pre-filled from your project files):

1. **Project purpose** — one sentence; recommended from README/package.json
2. **Tech stack** — recommended from auto-detected dependencies
3. **Key commands** — test/build/lint/deploy; recommended from `package.json:scripts`
4. **Claude's rules** — what Claude should always/never do; you must provide this
5. **Key directories** — recommended from directory scan
6. **Domain terminology** — optional glossary of project-specific terms

Optionally, paste up to 3 GitHub reference repo URLs at the start and the skill seeds its recommendations from those projects' conventions.

**Outputs:** `CLAUDE.md` (structured project memory) + `evals/project-context.json` (9-field structured data for the pipeline)

### Step 2: Audit project security

```
/project-audit
```

Runs `ecc-agentshield@1.4.0` across your `.claude/` directory — 102 rules across 5 categories (Secrets, Permissions, Hooks, MCP Servers, Agents). Returns an A–F grade. Advisory only — you decide whether to proceed. Also writes a dated artifact to `evals/project-audit-<date>.json` for trend tracking.

The CI gate requires grade ≥ C before merging.

### Step 3: Check what skills your project needs

```
skill-needs-analysis-agent
```

Reads `project-context.json` and maps your stack, workflow terms, and MCP servers against known skill categories. Returns a prioritized shortlist with copy-paste search terms for `skill-scout-agent`. This transforms the pipeline from pull (you know what you need) to push (the pipeline tells you what's missing).

---

## Sourcing a Skill

### Finding candidates

```
find a skill for <capability>
```

Or directly: `skill-scout-agent` for parallel registry search.

**skill-scout** checks 3 live registries (multica-ai, vercel-labs, Evol-ai/SkillCompass), falls back to GitHub search, scores on 7 dimensions, and presents the top 3:

| Dimension | Weight |
|---|---|
| Trigger precision | 25% |
| Instruction clarity | 20% |
| Context footprint | 15% |
| Project fit | 15% |
| Provenance | 10% |
| Source reputation | 10% |
| Conflict risk | 5% |

Source reputation rewards 15 trusted organisations across 3 tiers (Anthropic, Vercel, multica-ai, Evol-ai, affaan-m, mattpocock, ChrisWiles, and others).

### Security gate

```
/skill-audit skills/<candidate-dir>/
```

The 47-pattern `static-scan.js` scanner checks:

- **Prompt injection** (10 patterns) — `ignore previous instructions`, persona overrides, hidden unicode
- **Dangerous Bash** (7 patterns) — `rm -rf /`, curl-pipe-shell, SSH directory access
- **Hardcoded secrets** (11 patterns) — Anthropic API keys (`sk-ant-api03-`), GitHub PATs (`ghp_`, `github_pat_`), AWS keys (`AKIA`), Slack tokens (`xoxb-`), private keys, Bearer tokens
- **Permissions** (10 patterns, for `settings.json`) — `Bash(*)` wildcards, `bypassPermissions`, hook shell substitution
- **Script malware** (9 patterns) — `eval()`, `child_process`, `pickle.loads`, `os.system`, unsafe YAML

Returns PASS / FLAG / BLOCK. BLOCK stops the pipeline immediately.

The scanner also accepts `settings.json` directly: `node skills/skill-audit/scripts/static-scan.js .claude/settings.json`

### Adapting the skill

```
/skill-adapt
```

Rewrites the PASS-audited skill to match your project. Reads all 9 fields from `project-context.json`:

- Uses `workflow_terms` to inject project-native language into trigger phrases
- Checks `hooks` — if a `PostToolUse` hook already runs a formatter, doesn't add a redundant step
- Checks `mcp_servers` — adds prerequisite notes if the skill assumes an integration you don't have
- Checks `plugins` — flags capability conflicts with installed plugins
- Writes full provenance metadata block (source URL, commit hash, adapted date, license)

For 2+ PASS candidates, run `skill-synthesizer-agent` first to produce a synthesis plan before adapting.

---

## Measuring Skill Quality

### Running the evaluation

```
/skill-eval
```

Or: `skill-eval-agent` for parallel execution (up to 42 subagents).

Generates **9 scenario types** when project context is available:

| # | Type | Triggers? | What it tests |
|---|------|-----------|---------------|
| 1 | `direct` | ✓ | Cold-start primary trigger |
| 2 | `paraphrased` | ✓ | Same intent, different words |
| 3 | `edge_case` | ✓ | Mid-workflow entry |
| 4 | `negative` | ✗ | Explanation request — must NOT invoke |
| 5 | `semantic` | ✓ | Synonym verb variations |
| 6 | `adversarial` | ✗ | Skill vocabulary in wrong scope — binary 10/0, no partial credit |
| 7 | `project-native` | ✓ | Project terminology injected |
| 8 | `project-workflow` | ✓ | After a sibling skill |
| 9 | `multi-turn` | ✓ | Mid-session continuation; −3pts if re-asks established context |

**5 metrics with thresholds:**

| Metric | Threshold | Failing routes to |
|---|---|---|
| Eval pass rate | ≥ 80% | Levers B–E |
| Trigger accuracy | ≥ 85% | Lever A (description) |
| Context footprint | informational | — |
| Project fit score | ≥ 7/10 | Re-run skill-adapt (or Lever B if only multi-turn fails) |
| Resilience score | ≥ 8/10 | Lever A (tighten + add negative examples) |

### Auto-improving failing skills

```
/skill-refine
```

Or: `skill-refine-agent` for fully autonomous operation.

Runs the **Karpathy autoresearch loop**: one hypothesis → one surgical edit → re-score → keep or revert. Up to 10 iterations. Routes by failing metric to one of 5 levers:

- **Lever A** — Description trigger phrases (for low trigger accuracy or low resilience score)
- **Lever B** — Workflow checklist steps
- **Lever C** — Examples and quick-start content
- **Lever D** — REFERENCE.md depth for edge cases
- **Lever E** — Script output format

Train/test split: `adversarial` scenarios always stay in the training set (direct Lever A signal). `project-native`, `project-workflow`, and `multi-turn` are held out until final validation.

---

## Periodic Health Checks

```
skill-guardian
```

Runs the full pipeline orchestration cycle:

**Phase 0:** Refresh `project-context.json` if stale (>7 days). Run AgentShield scan; compare against prior audit artifact for grade trend.

**Phase 1:** Inventory skills → classify as ACTIVE / CANDIDATE / INSTALLED.

**Phase 2:** Static-scan any skill without a `SKILL-AUDIT.md`.

**Phase 3:** For each ACTIVE skill, generate 9 scenarios, run parallel eval, compute all 5 metrics.

**Phase 4:** For any skill below threshold, run up to 3 refinement iterations.

**Phase 5:** Write `PROJECT-SKILL-HEALTH.md` with per-skill status table, security trend, and recommendations.

---

## CI/CD

The GitHub Actions workflow (`.github/workflows/ci.yml`) runs five jobs on every push and PR to `main`:

1. **Validate skill frontmatter.** Every SKILL.md must have a valid `name` (≤64 chars, lowercase-hyphens), a `description` (≤1024 chars, containing "Use when") and a `compatibility` field. **Invocation-shaped skill and agent references must resolve.** A backticked kebab name (or `/name`) right after invoke, run, use, recommend, dispatch and similar verbs, or followed by "skill" or "agent", must be an existing skill or agent, or a plugin skill declared in `EXTERNAL_SKILLS` in `scripts/validate-skills.js`. Plugin skills are optional, because target projects and the Hermes box may not have them. Each reference to one must state its fallback ("if … installed" or "otherwise") on the same line or the next two. The check favours precision over recall: unquoted names, single-word names and other phrasings are not checked.
2. **Security gate.** Runs `ecc-agentshield@1.4.0` on `.claude/` and fails below grade C. If AgentShield is unavailable, it falls back to `static-scan.js` on the agent and settings files.
3. **Test suites.** Node (`scripts/run-all-tests.js`) and Hermes `bin/` (`run-bin-tests.sh`), plus the deploy suites.
4. **Bind agreement.** Linux, as root, against the real proxy.
5. **Static scan all skills.** `static-scan.js` on every `skills/*/` directory. A BLOCK not covered by the reviewed baseline (`.github/skill-scan-baseline.json`) fails the build.

**Merge gate.** The `main-protection` ruleset requires a pull request and checks 1–4, and requires the branch to be up to date with `main`. It also forbids force-pushes and deletion. Job 5 runs but is not a required check. Reviews follow `docs/REVIEW_PROTOCOL.md`.

Run locally: `make validate`, `make audit SKILL=<name>`

---

## Developer Shortcuts

```bash
make context          # Regenerate evals/project-context.json
make evals SKILL=X    # Generate 9 eval scenarios for skill X
make audit SKILL=X    # Static-scan skill X
make validate         # Validate all SKILL.md frontmatter
make install-to TARGET=/path  # Dry-run or install
```

---

## When This Toolkit Is Ideal

**Perfect fit:**

- You're building or maintaining a Claude Code project and want consistent, measurable skill quality
- You're adopting skills from the community and need a security gate before trusting them
- You have multiple projects and want to share a vetted skill library
- You're a team where different people source skills — the audit + adapt loop standardises quality
- You want skills that are explicitly tested against YOUR project's terminology, not generic prompts

**Works well for:**

- Any tech stack (Node.js, Python, Rust, Go, Ruby, Jupyter — all detected automatically)
- Projects with or without GSD installed (the pipeline is fully self-contained)
- Offline environments (static-scan.js and generate-seed-evals.js work without network; only skill-scout and project-audit require network)

**Not the right tool when:**

- You just need a one-off skill quickly and don't care about long-term maintenance
- You're working in a fully air-gapped environment with no npm access (project-audit won't run, though the static fallback still works)

---

## Things Users Often Overlook

### 1. Run `project-setup` before `skill-scout`

`evals/project-context.json` powers the entire pipeline. If it's empty or sparse, `skill-adapt` adapts to nothing, project-native eval scenarios fall back to generic placeholders, and the project fit score is omitted. Running `project-setup` first takes ~5 minutes and makes every subsequent stage significantly more accurate.

### 2. The `--dry-run` flag before installing on production projects

`./install.sh --dry-run /path/to/project` prints exactly what would be copied without touching any files. Always use this first when installing on a project you care about.

### 3. Adversarial scenarios belong in the training set

If you're running `skill-refine` and resilience score is failing, the `adversarial` scenarios must stay in the training set — not the held-out validation set. They are the direct signal for Lever A mutations (tightening trigger language). The held-out set is: `project-native`, `project-workflow`, `multi-turn`.

### 4. Project fit score < 7 has two different causes

- If `project-native` or `project-workflow` scenarios fail → exit refinement and re-run `skill-adapt` with richer project context (true mis-adaptation)
- If ONLY `multi-turn` fails → don't exit; work Lever B instead (the skill re-asks established context, fixable with a continuation-awareness note)

### 5. AgentShield is pinned to `1.4.0` — update deliberately

All references use `ecc-agentshield@1.4.0`, not `@latest`. When you want to pick up a new AgentShield version, update all three locations: `skills/project-audit/SKILL.md`, `.claude/agents/skill-guardian.md`, and `.github/workflows/ci.yml`.

### 6. The static scanner also accepts `settings.json`

`node skills/skill-audit/scripts/static-scan.js .claude/settings.json` runs the Permissions category (10 patterns) against your Claude Code configuration — detecting wildcard Bash rules, `bypassPermissions`, hook shell injection, and hardcoded API keys — with no network dependency.

### 7. `settings.local.json` is gitignored on purpose

Your project-level permission allowlist (`.claude/settings.local.json`) is correctly gitignored. It's machine-local and session-accumulated. Review it periodically with `make audit` and clean up one-off development entries — they accumulate and lower your AgentShield permissions score.

### 8. Two registries were dead as of 2026-06-22

`anthropics/claude-code-skills` and `ComposioHQ/awesome-claude-skills` both returned 404. skill-scout now uses only the three live ones. Check the comment in `skill-scout-agent.md` for the re-add date if they come back online.

### 9. The `skill-guardian` model must be `sonnet`, not `haiku`

`skill-guardian` is a heavy orchestrator (context gathering, parallel evals, refinement loops). It's been set to `sonnet` — never change it to `haiku` to save cost; the context window requirements will cause failures.

### 10. Agent eval baselines are pending full subagent runs

`agent-scout`, `agent-audit`, and `agent-adapt` have `evals.json` (9 scenarios each) and initial `SKILL-EVAL.md` assessments, but the measured metrics (eval pass rate, trigger accuracy, resilience score, project fit score) require a full `skill-eval-agent` run to populate. The SKILL-EVAL.md files currently contain observable baselines only.

---

## Security Architecture Summary

| Layer | Tool | Patterns | Self-contained |
|---|---|---|---|
| Skill content | `static-scan.js` | 47 (prompt injection, bash, secrets, permissions, scripts) | Yes |
| Project config | AgentShield@1.4.0 | 102 (5 full categories) | No — external npm |
| CI gate | Both above | — | Fallback if AgentShield unavailable |

**Current security grade: C (73/100)** — Secrets 100, Hooks 100, MCP 100, Permissions 59, Agents 5.

The remaining HIGH findings are intentional architectural decisions: Node.js interpreter access is required for a Node.js skill-builder; agent Bash access is required for all pipeline operations; skill-scout's web+write combination is required for registry fetching and skill installation.
