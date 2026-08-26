---
name: repo-audit
description: "Use when: auditing a GitHub repository to extract tech stack signals for informing future Claude Code project architecture, running a deep reference audit from project-setup Phase 0 with --deep flag, or when asked to scan/map/audit a GitHub repo. Accepts a public GitHub URL and optional flags: --pipeline (inject into project-context.json), --layer <names> (comma-separated subset), --estimate (preview token count before running). Triggers on: audit this repo, scan this GitHub repo, deep audit, repo-audit, extract stack from, analyze this repository."
tools: Read, Write, Bash, Agent
compatibility: "Claude Code. Node.js ≥ 18. Requires npx (Repomix) and network access to GitHub; falls back to Gitingest on Repomix timeout."
---

# Repo Audit

Deep multi-layer audit of any public GitHub repository. Produces `docs/audits/<owner>-<repo>-<YYYY-MM-DD>.json` (machine-readable) and `.md` (human-readable) using 8 parallel layer agents backed by Repomix.

## Invocation

```
repo-audit <github-url> [--pipeline] [--layer runtime,framework,...] [--estimate]
```

## Workflow

### Phase 0 — Parse arguments

Extract from the user's message:
- `url`: the GitHub URL (required)
- `pipeline`: true if `--pipeline` present
- `layers`: comma-separated list after `--layer`, default all 8: `runtime,framework,database,testing,cicd,auth,ai_llm,claude_code`
- `estimate`: true if `--estimate` present

Normalize URL to `owner/repo`:
- Accept `https://github.com/owner/repo`, `https://github.com/owner/repo/tree/branch`, `owner/repo`
- If `owner/repo` cannot be extracted: print `"Could not parse '<url>' as a GitHub repo."` and stop.

### Phase 1 — Estimate (if --estimate)

```bash
npx repomix --remote <owner/repo> --compress --output-format json \
  --output /tmp/repo-audit-estimate-$(date +%s).json 2>&1 | head -5
```

Read the output JSON and extract `summary.totalFiles` and `summary.totalTokens`.

Print:
```
Repo: owner/repo — <N> files, ~<tokens> tokens (compressed)
Full audit: 8 agent calls. Proceed? [y/N]
```

Wait for user confirmation. If N or no response: stop. If Y: continue to Phase 2.

If `--estimate` was not passed: skip Phase 1 entirely and go to Phase 2.

### Phase 2 — Pack with Repomix

```bash
mkdir -p /tmp/repo-audit-<owner>-<repo>
npx repomix --remote <owner>/<repo> --compress --output-format xml \
  --output /tmp/repo-audit-<owner>-<repo>/packed.xml
```

If Repomix exits non-zero (private repo, network error, timeout after 60s):
```bash
pip install gitingest -q 2>/dev/null && \
  gitingest https://github.com/<owner>/<repo> --output /tmp/repo-audit-<owner>-<repo>/packed.xml 2>&1
```

If both fail: print `"Could not fetch repo. It may be private or inaccessible."` and stop. Copy packed.xml to `docs/audits/raw/<owner>-<repo>-<date>.xml` if it exists before stopping.

### Phase 3 — Categorize files

```bash
node skills/repo-audit/scripts/categorize-files.js \
  /tmp/repo-audit-<owner>-<repo>/packed.xml \
  /tmp/repo-audit-<owner>-<repo>/slices/
```

Read `manifest.json` from the slices directory. Print:
```
✓ Packed: <total_files> files categorized into 8 layers
  runtime:<N>  framework:<N>  database:<N>  testing:<N>
  cicd:<N>     auth:<N>       ai_llm:<N>    claude_code:<N>
```

### Phase 4 — Dispatch layer agents (parallel)

Dispatch only the layers specified in `layers`. Pass each agent:
- `slice_path`: `/tmp/repo-audit-<owner>-<repo>/slices/layer-<name>.xml`
- `repo`: `<owner>/<repo>`
- `layer`: layer name

Dispatch all selected agents **simultaneously** (parallel). Collect each agent's JSON output.

If an agent returns an error or non-JSON: mark that layer as:
```json
{ "layer": "<name>", "detected": null, "error": "agent failed — re-run with --layer <name>" }
```

Other layers continue unaffected.

### Phase 5 — Merge results

Collect all layer JSON objects. Build the final audit document:

```json
{
  "repo": "<owner>/<repo>",
  "audited_at": "<ISO timestamp>",
  "repomix_stats": {
    "total_files": "<N>",
    "total_tokens": "<N>",
    "compressed": true,
    "fallback_tool": null
  },
  "layers": {
    "runtime":    "<layer object>",
    "framework":  "<layer object>",
    "database":   "<layer object>",
    "testing":    "<layer object>",
    "cicd":       "<layer object>",
    "auth":       "<layer object>",
    "ai_llm":     "<layer object>",
    "claude_code":"<layer object>"
  },
  "architecture_signals": [],
  "ref_signals": {
    "ref_purpose":      "<first non-null purpose from layers>",
    "ref_stack":        ["<deduplicated stack tokens from runtime + framework signals>"],
    "ref_commands":     { "test": "", "build": "", "lint": "", "deploy": "" },
    "ref_rules_always": ["<from claude_code.signals.always_rules>"],
    "ref_rules_never":  ["<from claude_code.signals.never_rules>"],
    "ref_directories":  [],
    "ref_glossary":     [],
    "ref_skills":       ["<from claude_code.signals.installed_skills>"],
    "ref_agents":       ["<from claude_code.signals.agents>"]
  }
}
```

Derive `architecture_signals`: scan all layer signals and write 3–6 one-line summaries capturing the most distinctive cross-layer patterns (e.g. "Next.js 15 App Router + tRPC + Zod", "Drizzle ORM on Postgres via Neon").

Derive `ref_signals.ref_stack`: union of `runtime.signals.language`, `framework.signals.primary` (framework name only), `framework.signals.key_libraries`, filtered to non-null.

Set `ref_signals.ref_commands` to `{ test: "", build: "", lint: "", deploy: "" }` (empty strings). The cicd and runtime agents extract stage names, not executable command strings — leave this field blank so project-setup Phase 1 can discover actual commands from the target project's package.json/Makefile instead.

### Phase 6 — Write artifacts

```bash
mkdir -p docs/audits
```

**JSON file** — write to `docs/audits/<owner>-<repo>-<YYYY-MM-DD>.json`

**Markdown file** — write to `docs/audits/<owner>-<repo>-<YYYY-MM-DD>.md` with this structure:

```markdown
# Repo Audit: <owner>/<repo>
**Audited:** <YYYY-MM-DD> | **Files:** <N> | **Tokens:** <N> (compressed)

## Architecture Summary
<architecture_signals as bullet list>

## Layer: Runtime
**Confidence:** <confidence>
| Signal | Value |
|---|---|
<signals as table rows>

**Patterns worth adopting:** <patterns joined with "; ">
**Gaps:** <gaps joined with "; ">
> <notes>

## Layer: Framework
[same structure]

## Layer: Database
[same structure]

## Layer: Testing
[same structure]

## Layer: CI/CD
[same structure]

## Layer: Auth/Security
[same structure]

## Layer: AI/LLM
[same structure]

## Layer: Claude Code Config
[same structure]

## Recommendations for Future Projects
> Cross-layer pattern analysis

<3–5 specific, actionable recommendations derived from patterns and gaps across all layers>

## Re-run
`repo-audit https://github.com/<owner>/<repo> [--pipeline] [--layer <name>]`
```

For any layer where `detected: null` (agent failed), write:
```markdown
## Layer: <Name>
> Agent failed. Re-run with `repo-audit https://github.com/<owner>/<repo> --layer <name>`.
```

### Phase 7 — Pipeline injection (if --pipeline)

Read `evals/project-context.json`. If it doesn't exist: warn `"No project-context.json found — run /project-setup first."` and skip injection.

Merge `ref_signals` into `project-context.json`:
- Local values always win — never overwrite existing non-empty fields
- Append new `ref_stack` tokens not already in `stack`
- Append `ref_skills` items not in `installed_skills`
- Add `audited_repos` entry: `{ "repo": "<owner>/<repo>", "audited_at": "<date>", "report": "docs/audits/<owner>-<repo>-<date>.json" }`
- Set `audit_signals.architecture_patterns` to `architecture_signals`
- Set `audit_signals.ref_stack_extended` to `ref_signals.ref_stack`

Write updated `evals/project-context.json`.

Print:
```
✓ ref_signals injected into evals/project-context.json
  ref_stack:  <tokens added>
  ref_skills: <skills added>
  audited_repos: now <N> entries
```

### Phase 8 — Cleanup

```bash
rm -rf /tmp/repo-audit-<owner>-<repo>/
```

Print final summary:
```
✓ Audit complete: <owner>/<repo>
  docs/audits/<owner>-<repo>-<YYYY-MM-DD>.json
  docs/audits/<owner>-<repo>-<YYYY-MM-DD>.md
```

## Error handling

| Failure | Response |
|---|---|
| Private/inaccessible repo | Gitingest fallback → if also fails, abort cleanly |
| Repomix timeout (>60s) | Gitingest fallback |
| categorize-files.js returns 0 file blocks | Abort: "No files found in packed output." |
| Layer agent fails | Mark layer with error, continue other layers |
| All agents fail | Abort merge, preserve packed.xml in docs/audits/raw/ |
| --pipeline but no project-context.json | Warn + skip injection, still write audit artifacts |
