# Skill Audit: project-audit
**Date:** 2026-06-23
**Source:** local — /Users/erick/projects/claude_code/skills/project-audit/
**Verdict:** PASS

## Static Scan Results

| Check | Severity | Detail |
|-------|----------|--------|
| Prompt injection patterns | PASS | No issues |
| Dangerous Bash in instructions | PASS | No issues |
| Hardcoded secrets | PASS | No issues |
| Overly permissive settings rules | PASS | No issues |
| Malicious JS/Python/Shell in scripts | PASS | No issues |

**Scanner output:** `{ "verdict": "PASS", "summary": { "total": 0, "BLOCK": 0, "FLAG": 0 }, "findings": [] }`

## Permissions Audit

**Tools requested by skill:** Bash (to run `npx ecc-agentshield@1.4.0`), Read, Write (to save audit artifact to evals/)
**Purpose stated:** Wraps ecc-agentshield to scan .claude/ configuration files across 5 categories and return an A-F grade with numbered findings.
**Mismatches:** none — npx invocation, read of .claude/ config, and write to evals/ are all scoped to the skill's stated purpose

## Provenance

| Attribute | Value | Flag? |
|-----------|-------|-------|
| Repo age | Project-internal — not sourced from GitHub | no |
| Stars | N/A | no |
| Last commit | 2026-06-22 (per git log) | no |
| Contributors | Project team | no |

## Diff from current version

N/A — first audit of this skill; no prior installed version to diff.

## Decision

**Verdict:** PASS
**Reason:** Static scanner found zero findings; Bash access to npx and write access to evals/ are both required for the security audit workflow and are appropriately scoped.
**Next step:** Proceed to skill-eval
