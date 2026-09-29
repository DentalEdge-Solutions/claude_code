---
type: decision
title: "Improvement proposal — claude_code — 2026-07-24T22:51Z"
description: "The claude_code project is a multi-subsystem monorepo (skill pipeline toolkit, domain packs, reference-repo library, Second Brain memory system, and a Hermes Kanban control-plane) that has grown organically without module boundaries, shared abstractions, or CI enforcement. Across three dimensions (architecture, tests, risks), 30 distinct findings were identified. After dedup and merge, 14 prioritized items remain. The most urgent cluster around (1) untested critical-path scripts that can silently corrupt eval grading or miss security threats, (2) security guard inconsistencies that leave defense-in-depth gaps, and (3) structural duplication (registry resolution, secret patterns, skill trees) that amplifies every future change. No finding contradicts the project's own progress.md debts; several formalize and prioritize them."
tags: [hermes-generated]
author: hermes
timestamp: 2026-07-25
sources:
  - "/opt/data/proposals/claude_code/2026-07-24_22-54-03.md"
  - "hermes-run:2026-07-24_22-54-03"
status: candidate
---

# Improvement proposal — claude_code — 2026-07-24T22:51Z

## Summary

The claude_code project is a multi-subsystem monorepo (skill pipeline toolkit, domain packs, reference-repo library, Second Brain memory system, and a Hermes Kanban control-plane) that has grown organically without module boundaries, shared abstractions, or CI enforcement. Across three dimensions (architecture, tests, risks), 30 distinct findings were identified. After dedup and merge, 14 prioritized items remain. The most urgent cluster around (1) untested critical-path scripts that can silently corrupt eval grading or miss security threats, (2) security guard inconsistencies that leave defense-in-depth gaps, and (3) structural duplication (registry resolution, secret patterns, skill trees) that amplifies every future change. No finding contradicts the project's own progress.md debts; several formalize and prioritize them.

## Items (prioritized)

[P1] type: correction — Unify and test the secret-scanning pattern list

Rationale: Two independent pattern sets exist — brain-lib.js SENSITIVE_CONTENT_PATTERNS (6 patterns) and redact.js SECRET_PATTERNS (11 patterns). brain-capture and brain-promote use the 6-pattern list, so Slack tokens (xoxb-), Google API keys, JWTs, and Bearer tokens pass the canon-promotion gate. Telemetry redaction catches them, but the brain does not — the opposite of defense-in-depth.
Evidence: brain-lib.js:7-14 (6 patterns) vs redact.js:29-42 (11 patterns). Confirmed by risk analyst (finding 3) and corroborated by architecture analyst (cross-cutting scanSensitive reuse).
Impact: medium — secrets promoted to canon are persisted in .project-brain/canon/ and survive across sessions. Fix: extract a single shared pattern module (e.g., lib/secret-patterns.js) imported by both brain-lib.js and redact.js, with the superset of patterns. Add a test that asserts known token formats (Slack, Google, JWT, Bearer, Anthropic, AWS, GitHub, private-key, password) are all caught.

[P2] type: correction — Add test coverage for harvest-evidence.js (289 lines, critical grading component)

Rationale: harvest-evidence.js is the sole source of truth for skill_loaded/agent_dispatched and workflow-step scoring. It has complex regex matching logic and no dedicated test file. A bug silently corrupts all eval grading — the project's quality gate becomes unreliable.
Evidence: skills/skill-eval/scripts/harvest-evidence.js (289 lines, no test file). test-runners.js tests the aggregator but assumes harvest-evidence output is correct.
Impact: high — silent grading corruption with no test guardrail. Fix: create harvest-evidence.test.js with fixture transcripts covering marker matching, artifact path extraction, and edge cases (missing markers, malformed JSON, multi-agent transcripts).

[P3] type: correction — Add test coverage for static-scan.js (285 lines, security scanner)

Rationale: static-scan.js is the deterministic security scanner for skill directories, agent files, and settings.json. It detects prompt injection, dangerous bash, hardcoded secrets, and permissive config. No test file exists. A regex regression could miss real threats or flood with false positives — and this tool is the project's own security quality gate for new skills.
Evidence: skills/skill-audit/scripts/static-scan.js (285 lines, no test file). Output format: { verdict, findings, scanned }.
Impact: high — security scanner with no test coverage is a critical blind spot. Fix: create static-scan.test.js with fixture skill directories containing known-bad patterns (injection, secrets, dangerous bash) and known-clean patterns to verify both detection and false-positive resistance.

[P4] type: correction — Add test coverage for run-manifest.js (187 lines, resume/integrity gate)

Rationale: run-manifest.js implements idempotent resume tracking for eval iterations (init/mark/status subcommands). A bug causes interrupted eval runs to silently skip scenarios or use inconsistent baseline methods. It is referenced in SKILL-EVAL.md as the 'integrity gate passed' check — the gate itself is untested.
Evidence: skills/skill-eval/scripts/run-manifest.js (187 lines, no test file).
Impact: high — silent eval run corruption on resume. Fix: create run-manifest.test.js covering init→mark→status lifecycle, concurrent init calls, corrupt manifest recovery, and status reporting.

[P5] type: enhancement — Add CI pipeline (GitHub Actions or equivalent)

Rationale: The project has 27+ test suites and a run-all-tests.js runner but no CI configuration (no .github/workflows/ directory). Tests must be run manually. Regressions can merge without any test execution. This is the single highest-leverage improvement — it enforces all existing tests automatically and provides a foundation for adding coverage gates for P2-P4.
Evidence: No .github/workflows/ directory found. Only .yml is infra/hermes-agent/docker-compose.yml. run-all-tests.js exists but is not wired to any automated gate.
Impact: high — no automated test enforcement. Fix: add .github/workflows/ci.yml that runs `node scripts/run-all-tests.js` on push/PR. Optionally add validate-skills.js as a separate job.

[P6] type: correction — Fix BSD sed syntax in uninstall.sh (Linux container)

Rationale: uninstall.sh:108 uses `sed -i ''` which works on macOS/BSD sed but fails on GNU sed (Linux). The project runs in a Linux Docker container. The `set -euo pipefail` will cause the script to exit with an error after rm -rf operations have already executed — partial uninstall with error exit.
Evidence: uninstall.sh:108: `sed -i '' '/^# >>> skill-builder >>>/,/^# <<< skill-builder <<</d' "${CLAUDE_MD}"`
Impact: medium — CLAUDE.md pipeline section removal silently fails on Linux; partial uninstall. Fix: use `sed -i` (no backup arg) for GNU sed, or detect platform and branch, or use a portable approach: `sed -i.bak '...' file && rm -f file.bak`.

[P7] type: enhancement — Extract shared registry resolution library

Rationale: Registry resolution logic is duplicated 3+ times: claude-code-operator/SKILL.md, claude-code-proposer/SKILL.md, and make-review-board.py's resolve_workdir(). Each has slightly different error handling. make-review-board.py hand-parses YAML with string-level indent checks (fragile). Adding a project or changing the registry format requires touching all copies.
Evidence: make-review-board.py lines 38-45: `if line.startswith("  ") and not line.startswith("    ") and line.endswith(":")` — hand-rolled YAML parser. Contrast with setup-review-team.sh which uses Python's yaml module.
Impact: medium — a cosmetic YAML reformat silently breaks project resolution and the entire review pipeline. Fix: extract a shared resolve-project.js (or Python module) that all three consumers import. Use a proper YAML parser. Add a test for the resolver.

[P8] type: enhancement — Unify the two skill trees (skills/ vs infra/hermes-agent/skills/)

Rationale: The repo has two parallel skill trees: 30 skills in skills/ (with SKILL-EVAL.md, evals.json, auto-discovered by run-all-tests.js) and 3 skills in infra/hermes-agent/skills/ (claude-code-operator, claude-code-proposer, claude-code-reviewer — zero eval files, zero test coverage). The Hermes skills are held to a lower quality bar than the skills they operate alongside.
Evidence: skills/ has 33 SKILL-EVAL.md files; infra/hermes-agent/skills/ has zero. README describes 9 scenario types and 5 metric thresholds as the evaluation standard.
Impact: medium — the review pipeline's output quality depends entirely on the claude-code-reviewer skill's untested prompt quality. Fix: either (a) move Hermes skills into skills/ with eval scenarios, or (b) create a lightweight eval harness for infra skills that validates prompt structure and output format without full LLM-based grading.

[P9] type: correction — Add path guardrails to uninstall.sh rm -rf operations

Rationale: uninstall.sh uses `rm -rf` in 7 places with paths constructed from user-supplied TARGET. If TARGET is misconfigured (e.g., pointing to / or a parent directory), `rm -rf "${TARGET}/skills"` could remove unintended directories. There is no sanity check that the resolved path is reasonable.
Evidence: uninstall.sh:58: `rm -rf "${TARGET}/skills"` — TARGET from $1, resolved via `$(cd "${TARGET}" && pwd)` with no guardrails.
Impact: low-medium — destructive deletion on misconfigured TARGET. Fix: add a guard function that rejects paths matching /, $HOME, /opt, or paths shorter than N components before any rm -rf.

[P10] type: enhancement — Add monorepo structure or module manifest

Rationale: Five subsystems coexist in a flat repo with no module boundaries: skill pipeline, domain packs, reference-repo library, Second Brain, and Hermes infra. New contributors cannot easily determine which subsystem a change belongs to. Cross-cutting changes (e.g., scanSensitive) must be duplicated or shared via ad-hoc imports.
Evidence: No root package.json, pyproject.toml, or monorepo manifest exists. README.md describes skills/; infra/hermes-agent/README.md describes the Hermes layer; packs/registry.md and reference-repositories/registry.md show two more registries.
Impact: medium — structural ambiguity increases onboarding cost and divergence risk. Fix: add a root-level README or ARCHITECTURE.md that maps the five subsystems, their boundaries, and ownership. Optionally add a workspace manifest (pnpm-workspace.yaml or similar) to formalize package boundaries.

[P11] type: correction — Brain-security-guard: harden fail-open posture and regex bypass vectors

Rationale: The guard fails open on parser errors (line 52: `exit 0` on any node error), meaning a corrupted or resource-starved node runtime silently disables the only PreToolUse gate. Additionally, the regex-based mutation detection can be bypassed by non-standard tools (dd, install, ruby -e, php -r, awk with system()).
Evidence: brain-security-guard.sh:52 (fail-open) and :41-44 (mutation regex). Risk analyst finding 1 and 2.
Impact: medium — defense-in-depth layer can disappear silently or be bypassed. Fix: (1) Log fail-open events to telemetry so they are visible. (2) Expand mutation regex to include dd, install, and common scripting language -e/-r flags. (3) Consider an allowlist approach (only known-safe commands) instead of a denylist.

[P12] type: enhancement — Add test coverage for validate-skills.js, score-candidates.js, and extract-project-context.js

Rationale: Three medium-impact scripts lack tests: validate-skills.js (99 lines, CI gate that could block all commits or allow invalid skills), score-candidates.js (225 lines, could recommend wrong skills), and extract-project-context.js (context extraction errors cascade to all eval generation).
Evidence: scripts/validate-skills.js (99 lines, no test file), skills/skill-scout/scripts/score-candidates.js (225 lines, no test file), skills/skill-eval/scripts/extract-project-context.js (no test file).
Impact: medium — CI gate with no self-test; incorrect skill recommendations; malformed context propagation. Fix: create dedicated test files for each, covering valid/invalid inputs and edge cases.

[P13] type: correction — Fix test isolation issues in test-runners.js

Rationale: test-runners.js writes fixtures to real repo paths (evals/codex-runs/.test/ and evals/skill-eval/codex-baseline.json) instead of temp directories. A test crash mid-run leaves stale fixture dirs and could corrupt a real baseline file. All other test files in the project use __test_tmp__ dirs or os.tmpdir() — this is the lone outlier.
Evidence: scripts/codex/test-runners.js line 59: `const dir = 'evals/codex-runs/.test/healthy'`; line 203: `const baselinePath = path.join('evals', 'skill-eval', 'codex-baseline.json')`.
Impact: medium — stale test artifacts on crash; potential git pollution; real baseline corruption risk. Fix: use os.tmpdir() or fs.mkdtempSync() for all fixture paths, matching the pattern used by brain and telemetry tests.

[P14] type: enhancement — Update superseded architecture specs to reflect Hermes adoption

Rationale: The master architecture spec (specs/archive/2026-07-20-hermes-master-architecture.md) describes H0-H3 phases with a custom SQLite daemon, credential vault, guard hooks, policy engine, and budget ledger. The actual implementation adopted Nous Hermes Agent instead. The specs were not updated — a new contributor reading them builds a mental model of a custom daemon that doesn't exist.
Evidence: master-architecture.md line 3: '⚠ REVISED by the definitive roadmap'. H1/H2 features (vault, HITL, budget) are not implemented in the Hermes deployment and have no clear migration path.
Impact: low-medium — spec-to-implementation gap causes onboarding confusion. Fix: add a 'SUPERSEDED' banner to archived specs with a pointer to the current Hermes-based architecture. Optionally create a migration mapping doc (old spec feature → Hermes equivalent or 'not yet implemented').

## Sources consulted

- Parent handoff: t_6a7657fe (architecture) — 9 findings on module boundaries, execution paradigms, registry duplication, spec drift, skill tree divergence, proposal lineage.
- Parent handoff: t_cde17103 (tests) — 14 findings on coverage gaps (harvest-evidence.js, run-manifest.js, static-scan.js, validate-skills.js, score-candidates.js, extract-project-context.js), CI absence, test runner limitations, test isolation issues, and positive test quality assessment.
- Parent handoff: t_31fcc3af (risks) — 11 findings on security guard fail-open, regex bypass, divergent secret patterns, TOCTOU in brain-promote, BSD sed incompatibility, rm -rf guardrails, hardcoded /tmp paths, credential at rest, unbounded I/O, and known unaddressed progress.md debts.
- Direct verification: Confirmed absence of .github/workflows/ CI configuration, confirmed REFINE_RECOMMENDED telemetry flag in CLAUDE.md and aggregate-usage.js, confirmed project structure (skills/, infra/hermes-agent/skills/, packs/, reference-repositories/, hooks/brain/).
- Cross-dimensional merge: 30 raw findings → 14 deduplicated items. Merged overlaps: (a) secret-pattern divergence appeared in both risks (finding 3) and architecture (scanSensitive reuse) → P1. (b) Registry duplication appeared in both architecture (finding 2/3) and risks (progress.md known issues) → P7. (c) Test coverage gaps for static-scan.js appeared in both tests (finding 4) and risks (security scanner blind spot) → P3. (d) BSD sed issue appeared in risks (finding 5) and was corroborated by architecture (Linux container confirmation) → P6. (e) Skill tree divergence appeared in both architecture (finding 1/8) and tests (Hermes skills outside eval pipeline) → P8.
