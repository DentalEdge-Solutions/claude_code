# Cross-Repository Reuse & Compatibility Matrix — reuse opportunities, dependencies, conflicts and implementation trade-offs
> Phase 2 of the Software Factory evaluation campaign · Date: 2026-10-22
> Inputs: phase 1 reports 01-11 (docs/evaluations/2026-10-22-factory-research/) · Framework: value definition (active decision 2026-10-22)
> Legend: [Obs] observed · [Docs] official docs · [Claim] unverified claim · [Inf] inference · [Unk] unknown

## 0. How to read this document

**Scope.** This is a component-level comparison. It inventories every component the 11 phase 1 reports list as
reusable (§13 of each report), plus §12 innovations and a few §8 items that matter for the overlap analysis. It then
groups components that solve the same problem, records what composes and what conflicts, and describes generic
combinations. It makes no adoption decision and no recommendation for any specific project. Every verdict is a
**candidate verdict**: generic and provisional, in the owner's vocabulary (REUSE, ADAPT, COMPOSE, REIMPLEMENT,
BUILD NEW, REFERENCE ONLY, REJECT).

**Citations.** `[R07 §13]` means report 07, section 13. Path and line references come from the reports unless marked
"clone", which means I re-read the file in the read-only clone on 2026-10-22. Official Claude Code docs were read on
2026-10-22 (code.claude.com/docs/en/hooks, /permissions, /agent-sdk/python).

**Verification status codes** (for the "Status" column). Nothing was executed in phase 1 or here. Test and CI status
comes from the reports' reading of the repositories and GitHub metadata.

| Code | Meaning |
|---|---|
| **T-CI** | Implemented code with in-repo tests that the repository's CI runs (pass status from GitHub metadata, not executed) |
| **T** | Implemented code with in-repo tests, no CI |
| **I** | Implemented code, no tests found |
| **P** | Prompt or prose only: an LLM is asked to honour it, nothing enforces it |
| **D** | Document, schema or method: design knowledge, not an executable |
| **U** | Exists only on an unmerged branch (combined with the codes above) |
| **X** | Defects found by reading that break the stated function |

**Report reuse classes** are abbreviated: **DR** directly reusable · **NA** needs adaptation · **RI** reimplement the
idea · **RO** reference only.

**Rules applied to the candidate verdicts.**
1. Licence first (brief rule 7). Code with no licence is never REUSE or ADAPT as code: at most REIMPLEMENT (the idea)
   or REFERENCE ONLY. GPL code carries copyleft implications. Mixed-licence repositories are judged per component.
2. Security and correctness are mandatory acceptance criteria (value definition). A component whose default
   behaviour fails one of them is not REUSE as-is, whatever its other qualities: it is ADAPT (if a bounded fix or a
   configuration change closes the gap), REFERENCE ONLY, or REJECT.
3. A pattern (an idea expressed in someone else's code or prose) is REIMPLEMENT even when the licence is MIT, unless
   the text itself (a prompt or template) is what would be reused, in which case ADAPT or REUSE.
4. COMPOSE is used for components whose value depends on being combined with a component from another repository
   (section 4 lists the combinations). BUILD NEW is used only in section 2, for capabilities no repository provides
   adequately.

---

## 1. Consolidated component inventory

### 1.1 Report 01 — Galea, Software Factory for Claude Code (v1: no licence; v2 branch: GPL-3.0)

Runtime for every v1 row: Claude Code with project subagents, named-agent spawn and `SendMessage` resume (minimum
version [Unk]), git worktrees, unpinned `agent-browser` CLI (Apache-2.0 per `gh api`, accessed 2026-10-22) [R01 §2.2].
v1 has no tests and no CI [R01 §1].

| Component (path) | Kind | Licence | Extra deps | Security notes | Status | R-class | Candidate verdict — reason |
|---|---|---|---|---|---|---|---|
| Factory orchestrator loop (`SF/.claude/skills/factory/SKILL.md`) | skill | none | — | LLM writes `job.json` and runs `git merge` with no code checks [R01 §13] | P | RI | **REFERENCE ONLY** — not resumable, no transition validation; code-owned loops exist elsewhere (R03, R05, R09) |
| First-line verdict protocol (agent "Write" sections; `dashboard.html:298-301,439-444`) | pattern | none | — | strict regex on line 1 | P | RI | **REIMPLEMENT** — cheapest parse contract in the set; orchestrator stops rather than retries on an invalid line |
| WAIT-FOR-ALL parallel review round (`SKILL.md:132-154`) | pattern | none | parallel subagents | — | P | RI | **REIMPLEMENT** — 4 fixed lenses, no routing in v1 |
| Named builder resumed via `SendMessage` (`SKILL.md:121-122,147-149`) | pattern | none | Claude Code agent naming | — | P | RI | **REIMPLEMENT** — keeps builder context across rounds; version floor [Unk] |
| Per-job worktree + port + browser-session isolation (`SKILL.md:40-54,97-99,108-114`) | pattern | none | git, agent-browser | host-level only, no sandbox | P | RI | **REIMPLEMENT** — port formula `5100+10n+offset` collides with targets that use that range |
| Atomic `mkdir` job claim; Edit-based backlog claim (`SKILL.md:103-107,193-196`) | pattern | none | filesystem | Edit claim is optimistic [R01 §13] | P | RI | **REIMPLEMENT** — `mkdir` claim is sound; the Edit claim is not a lock |
| Approver ESCALATE policy (`SF/.claude/agents/approver.md:29-47`) | agent / pattern | none | git ≥ 2.38 [Inf] | the only auto-merge safety boundary, prompt-only | P | RI (after V1-1) | **REIMPLEMENT** — the category list (money, identity, deploy/CI, schema, email, production data, dependencies, product assumptions) is a reusable policy input |
| Spec template with Assumptions (`spec-writer.md:28-65`) | prompt template | none | AGENTS.md conventions | feature text inserted verbatim | P | RI | **REIMPLEMENT** — "Assumptions" as an escalation hook [R01 §12.5] |
| Builder evidence-per-AC report (`builder.md:43-96`) | prompt template | none | agent-browser | self-reported evidence; builder has Bash/Edit/Write | P | RI | **REIMPLEMENT** — evidence is not independent |
| Four reviewer lenses (`reviewer-*.md`) | agents | none | agent-browser | "read-only" reviewers hold Bash+Write; UX/UI browser checks skipped in 3 of 4 example reviews [R01 §7, §13] | P | RI | **REIMPLEMENT** — lenses are useful; enforcement must come from tool restrictions |
| Live dashboard (`SF/factory/dashboard.html`) | UI | none | browser, `python3 -m http.server` listing HTML | escapes markdown; no auth (localhost) | I | RO / RI | **REFERENCE ONLY** — coupled to http.server listing format; no poll overlap guard |
| v2 deterministic spine (`SF2/factory/bin/{job,gate,route}`, `checks.sh`, `config.json`, branch `8a428453`) | scripts | GPL-3.0 (+ commercial option, clone `SF2/README.md:169-174`) | Python ≥ 3.10 stdlib, `gh`, git | `gate` runs the main checkout's `checks.sh` and blocks protected-path edits; issue text quoted under a "data, not instructions" banner; cost parsing relies on undocumented transcript format [R01 §2.4] | U, I | RO / RI | **REFERENCE ONLY** — copyleft, unmerged, and its `.claude/` agents and skill are missing from the commit; the ideas (transition table, judge-from-main gate, risk routing) are **REIMPLEMENT** candidates |

### 1.2 Report 02 — Ras Mic, Software Factory Skills (mixed licence)

No CI; 71 pytest cases exist for the two scripts and the Playwright runner [R02 §1]. The `tests/` folder has no licence
[R02 header].

| Component (path) | Kind | Licence | Runtime / service deps | Security notes | Status | R-class | Candidate verdict — reason |
|---|---|---|---|---|---|---|---|
| Review freshness helper (`greploop/scripts/github_review.py`) | script | MIT, © Greptile AI (clone `greploop/LICENSE:3`) | Python 3.10+, `gh` with `--slurp`, Greptile SaaS | posts one PR comment; trusts exact bot logins (`:14`); imposter test | T (33 tests, unlicensed) | NA | **ADAPT** — Greptile score format and marker are hard-coded (`:36,:41`); reuse the script, reimplement its tests (no licence on `tests/`) |
| Trigger/snapshot/head-recheck freshness pattern (`github_review.py:45-212`) | pattern | MIT | any bot reviewer exposing timestamps and commit ids | closes "old 5/5 accepted for new code" [R02 §12.1] | T | RI | **REIMPLEMENT** — generic rule: a review counts only if it names the current head |
| Post-once trigger reservation + strict score parsing (`:155-183`, `:22-37`) [R02 §12.2-3] | pattern | MIT | filesystem | exclusive-create before any network write | T | (in helper) | **REIMPLEMENT** — filesystem idempotency key; refuse ambiguous scores |
| Bounded review-fix loop (`greploop/SKILL.md:40-72`) | skill | MIT | Greptile, `gh` (GitLab/Perforce prose only) | cap is agent-enforced | P | NA | **ADAPT** — needs a SaaS reviewer; cap should move into code |
| Evidence recorder CLI (`evidence-driven-testing/scripts/evidence.py`, 1,358 lines) | script | none | Python 3.10+, ffmpeg/ffprobe (libx264, ass), wf-recorder | spawns detached processes; full-screen capture; PID-reuse-safe control [R02 §12.4] | T (25 tests) | RO / RI | **REIMPLEMENT** — no licence; "verified" means only that the video plays |
| Evidence protocol (`SKILL.md:127-154,296-305`) | pattern | none | — | results self-reported | P | RI | **REIMPLEMENT** — assertion-annotated, commit-stamped evidence; not independent |
| Isolated Playwright runner (`run-playwright.sh`, `scripts/playwright/`) | script | none | Bash, Node 20+, Playwright 1.63.0 pinned with integrity hashes | `--ignore-scripts`; Chromium downloaded at run time | T (3 tests) | RI | **REIMPLEMENT** — temp-dir, lockfile-pinned capture runner |
| Worktree-per-task skill (`new-feature/SKILL.md`) | skill | none | git, `gh` | `git branch -D` on cleanup | P | RI | **REIMPLEMENT** — warns that worktrees do not isolate ports or databases (`:61-64`) |
| Multi-agent repo rules (`AGENTS.md:54-91`) and scaled workflow (`AGENTS.md:6-13`) [R02 §12.7] | pattern | none | — | — | P | RI | **REIMPLEMENT** — run only the steps a task needs |
| Service-layer guidance (`code-structure/SKILL.md`) | skill | none | — | — | P | RO | **REFERENCE ONLY** — generic advice |
| `unslop` prose editor (`unslop/SKILL.md`) | skill | MIT, © Lauren Tan | — | auto-invocation on all human-facing text | P | DR | **REUSE** — but the body has drifted from current upstream [R02 §16]; provenance favours taking upstream |
| Before/after capture + upload (`before-and-after/`) | skill + scripts | file titled "PolyForm Shield 1.0.0", © James Clements: MIT-style grant plus a noncompete clause (clone `LICENSE:1-27`) | `@vercel/before-and-after` (unpinned), `agent-browser`, curl, 0x0.st | public upload by default; broad `allowed-tools` incl. `npx @vercel/before-and-after *`; `IMAGE_ADAPTER` path not sanitised [R02 §8] | I | RO | **REJECT** — ambiguous, noncompete licence; public-host default and unpinned remote execution fail the security criterion |
| `greploop-apps` alias (`greploop-apps/SKILL.md`) | skill | MIT, © Greptile AI | `greploop` | — | P | DR | **REUSE** — trivial 27-line alias, only meaningful beside `greploop` |

### 1.3 Report 03 — Eric Tech, Super-Board (MIT)

Runtime: bash 3.2+, Python 3.9+ stdlib, `jq`, `gh`, git, Node 22 (syntax checks, Playwright), Claude Code with the
Workflow tool; GitHub REST/GraphQL is the only state store [R03 §2]. 62 offline suites run in CI on Linux and macOS
[R03 §7]. Suite names below were matched to components in the clone (`tests/`, 2026-10-22) [Obs].

| Component (path) | Kind | Extra deps | Security notes | Status (suite) | R-class | Candidate verdict — reason |
|---|---|---|---|---|---|---|
| Merge gate (`scripts/super-board-merge-gate.sh`) | script | jq, gh, git, python3, read helper, policy, approval, verification-ready | `eval`s config verify/migrate commands on the host, so PR code runs with user privileges (clone `merge-gate.sh:283,307`) [Obs]; local-FS lock | T-CI (`test-merge-gate.sh`, `test-run-gates.sh`) | NA | **ADAPT** — strongest code-enforced gate in the set (lock, head pin, base merged into reviewed head, checks inside the lock, routed exit codes) [R03 §12.2]; GitHub-only, squash-only, super-board config shape; host `eval` needs isolation |
| Merge policy classifier (`super-board-merge-policy.py`) | library | python3 stdlib | label/path-glob/added-line heuristics, bypassable by naming; unreadable metadata fails safe to human [R03 §8] | T-CI (via gate suites) [Inf] | DR | **REUSE** — as a fail-safe-to-human pre-filter, not as a security boundary |
| Head- and scope-pinned approval (`super-board-approval.py`) | library | python3, gh via read helper | cannot tell an agent-posted `done` from a human one when both share a token [R03 §8] | T-CI (`test_approval.py`) | NA | **ADAPT** — only sound with a separate human or robot identity |
| Bounded GitHub read helper (`super-board-github-read.py`) | library / CLI | python3, gh | read-only allowlist; validates diffs and paginations; shared halt file [R03 §12.4] | T-CI (`test_github_reads.py`) | DR | **REUSE** — fail-closed evidence reader |
| Wave workflow (`workflows/super-board-wave.js`) | workflow | Claude Code Workflow tool (`agent`, `pipeline`, `log`) | interpolates card titles into prompts | T-CI (`test-wave-preflight.sh`, `test-workflow-halt.sh`) | RI | **REIMPLEMENT** — bound to the Workflow runtime and super-board lifecycle docs |
| Workflow stub-test harness (`tests/test-wave-preflight.sh`) | pattern | node | — | T-CI | RI | **REIMPLEMENT** — deterministic test of an orchestration script by stubbing primitives |
| Wave planner + deps (`super-board-wave-plan.sh`, `super-board-deps.sh`) | script | bash, jq, gh | read-only; unparseable `blocked-by` never frees a card [R03 §12.5] | T-CI (`test-wave-plan.sh`, `test-deps.sh`) | NA | **ADAPT** — GitHub Projects v2 columns and `## Blocked by` convention |
| Pre-flight duplicate/overlap check (`super-board-preflight.sh`) | script + prompt | bash, gh, jq | read-only | T-CI (`test-preflight.sh`) | NA | **ADAPT** — title Jaccard 0.6 + file overlap; needs the semantic agent half |
| Card I/O cache (`super-board-card.sh`) | script | bash, gh GraphQL | writes card moves | T-CI (`test-card.sh`) | NA | **ADAPT** — Projects v2 only |
| PR body block editor (`super-board-pr-body.sh`) | script | bash, gh | `--expect-head` guard | T-CI (`test-pr-body.sh`) | DR | **REUSE** — marker-block convention `<!-- sb:NAME -->` |
| Skill-readiness resolver (`super-board-skills-ready.py`) | library | python3 | rejects interactive skills for unattended workers | T-CI (`test_skills_readiness.py`) | NA | **ADAPT** — registry hard-codes lane → `mattpocock-skills:*` chains (clone `:19-41`) |
| Guard hooks (`hooks/guard-*.py`, `settings-snippet.json`) | hooks | python3 stdlib | **fail open** on internal errors: each of the five guards catches `except Exception: pass` in `main()` and exits 0 (clone `guard-secrets.py:62-63`, `guard-delete-outside.py:199`, `guard-key-literals.py:100`, `guard-worktree-path.py:195`, `guard-protected-push.py:198`) [Obs]; regex heuristics on command strings [R03 §8] | T-CI (`test-guard-hooks.sh`) | DR | **ADAPT** — fail-open contradicts the security criterion; the hook code must exit 2 (or non-zero) on internal error. [Docs, hooks, accessed 2026-10-22] `onFailure: "block"` (v2.1.295+) acts only on hook failures (cannot start, exit other than 0/2, timeout, invalid output), so it would then cover crashes and timeouts but never a swallowed exception that exits 0. Defence in depth only |
| Worktree cleanup hook (`hooks/cleanup-wt.py`) | hook | python3, git | deletes merged worktrees/branches (recovery file) | T-CI (`test-cleanup-wt.sh`) | NA | **ADAPT** — expects `.claude/worktrees/` |
| Eval-staleness Stop hook (`hooks/dev/gate-skill-evals.py`) | hook | python3, git | blocks turn end (exit 2); fails open | I (no suite found) | DR | **ADAPT** — assumes `claude plugin eval` result locations |
| Usage guard (`super-board-usage.sh`) | script | bash, jq, status-line hook | reads status-line snapshot | T-CI (`test-usage.sh`) | DR | **REUSE** — Pro/Max plans only |
| Throttle (`super-board-throttle.sh`) + measured GraphQL price list [R03 §12.9] | script | bash, jq, gh | writes config | T-CI (`test-throttle.sh`) | NA | **ADAPT** — `max_workers` semantics |
| Codex lane launcher (`super-board-codex-lane.sh`) | script | python3, Codex CLI | `approval_policy="never"`, repo write, network on (`:188-198`) | T-CI (`test-codex-lane.sh`, schema test) | RO | **REJECT** (as configured) — schema-validated lane output is a reference idea |
| Review-remembers protocol (`super-review/SKILL.md:188-219`) | prompt / pattern | gh | — | P, with offline test (`test-wave-review-memory.sh`) and a paid eval | RI | **ADAPT** — MIT prompt text; stable finding ids, mandatory recheck of prior findings |
| Fixed adversarial brief + min aggregation (`super-review/SKILL.md:403-447`) | prompt / pattern | sub-agents | scores are LLM self-reports | P | RI | **REIMPLEMENT** — anti-anchoring; over-engineering never blocks alone |
| Test-gap check (`super-qa/SKILL.md:481-511`) | prompt | external `tdd` skill | — | P | DR (as text) | **ADAPT** — depends on an external skill |
| Writing standard + format tests | spec + test | python3 | — | T-CI (`test_writing_format.py`) | NA | **REFERENCE ONLY** — opinionated emoji/commit format |
| Runtime compare (`super-qa/scripts/runtime_compare.py`) | script | python3, project Playwright scenarios | runs argv commands | T-CI (`test_runtime_compare.py`) | DR | **REUSE** — needs project-owned scenarios |
| Calibration receipt validator (`super-board-calibration.py`) | script | python3, git, external `calibrate` skill | read-only | T-CI (`test_calibration.py`) | RO | **REFERENCE ONLY** — depends on a skill not in the repo |
| Legacy builder (`super-build-dispatch.sh:98-145`) [R03 §8] | script | `claude -p` | `--dangerously-skip-permissions` with the raw issue body in the prompt | I | — | **REJECT** — untrusted text into an unrestricted agent |
| Installer (`get.sh`, `install.sh`) [R03 §8] | script | curl, bash, `npx -y skills@latest` | `curl \| bash`; no checksum; falls back to `main`; unpinned third-party skills; refuses root; truncation guard | T-CI (`test-get.sh`, `test-install.sh`) | — | **REJECT** (as is) — supply-chain posture fails the security criterion; `.agents/` + per-host symlink layout is a reference idea |

### 1.4 Report 04 — Rezvani, Skills & Agents Factory (MIT, dormant since 2025-11-12)

Runtime: Python 3 stdlib helpers; Claude Code (guides, commands); GitHub Actions with `claude-code-action@v1`. No tests;
CI is a syntax, safety and link check [R04 §1, §7].

| Component (path) | Kind | Security notes | Status | R-class | Candidate verdict — reason |
|---|---|---|---|---|---|
| Settings installer (`hook-factory/installer.py:24-322`) | library | writes `~/.claude/settings.json`; `input()` on duplicates | I | NA | **ADAPT** — backup/rotate/atomic/rollback pattern is sound [R04 §12.2]; event list hard-codes the nonexistent `PrePush` (`:213`); rejects 9 of 15 shipped hook files (V4-2) |
| Hook command safety linter (`validator.py:47-56,486-579`) | library | regex heuristics; 40-char base64 false positives | I | RI | **REIMPLEMENT** — structural checks assume the wrong hook schema |
| Hook templates (`templates.json`) | data | object matchers, `$CLAUDE_TOOL_FILE_PATH`, `exit 1` that does not block [R04 §5.3] | X | RO | **REJECT** — contradicts the documented hook contract |
| Hook generator / CLI (`hook_factory.py`, `generator.py`) | script | path-traversal guards present | X | RO | **REJECT** — discards interactive answers; SessionStart key mismatch |
| Skills factory prompt (`SKILLS_FACTORY_PROMPT.md`) | prompt template | — | P | NA | **REFERENCE ONLY** — Python-centric; self-attested checklist |
| Agents/hooks/prompts/slash factory prompts | prompt templates | hook prompt has a wrong event table | P, X (hooks) | RO | **REFERENCE ONLY** (hooks prompt: **REJECT**) |
| Guide subagents (`.claude/agents/*-guide.md`) and question-flow UX [R04 §12.1] | agents | hard-coded `/Users/rezarezvani/...` path; `factory-guide` lacks the Agent tool | X | RI | **REFERENCE ONLY** — multi-turn Q&A conflicts with subagent semantics; the question-then-template idea is REIMPLEMENT |
| Slash-command `allowed-tools` generator + validator (`slash-command-factory/*`) [R04 §12.4] | library | allowlisted `find`/`sed`/`awk` still write or exec | I | NA | **ADAPT** — least-privilege synthesis; rejects bare `Bash` |
| Prompt-factory presets (69 files) | prompt library | — | D | DR (content) | **REFERENCE ONLY** — general-LLM role prompts; quality unevaluated |
| Prompt validator (`prompt-factory/scripts/validator.py`) | script | — | X | RI | **REJECT** — inverted token estimate; keyword-count gates |
| Codex CLI wrapper (`codex-cli-bridge/codex_executor.py`) | library | `--full-auto` + `workspace-write`; `--skip-git-repo-check` | I | NA | **REFERENCE ONLY** — model names and flags from 2025-11 [Unk] |
| CLAUDE.md quality scorer (`claude-md-enhancer/*`) | library | — | I | RO | **REFERENCE ONLY** — heuristic score |
| Workflow kill switch + rate-limit breaker (`.github/WORKFLOW_KILLSWITCH`; `plan-to-tasks.yml:26-69`) | pattern | kill switch read before checkout, and unwired in `plan-to-tasks.yml` (V4-4) | X (kill switch), I (breaker) | RI | **REIMPLEMENT** — gate agentic jobs with a cheap pre-job; the kill switch as built is a no-op |
| Agentic issue automation (`issue-triage.yml` and three others) | workflow | any outsider's issue body into a Claude prompt with a write token and no author filter [R04 §8] | I (active, failing) | RO | **REJECT** |
| Domain skill pack (`generated-skills/*`, 11 ZIPs) | skills | ZIPs ship `.pyc` bytecode | I | RO | **REFERENCE ONLY** (ZIPs: **REJECT**, unreviewable bytecode) |
| "Generate prompts only, then STOP" scope contract (`prompt-factory/SKILL.md:12-48`) [R04 §12.5] | pattern | — | P | (§12) | **REIMPLEMENT** — scope guard for generator skills |

### 1.5 Report 05 — Owain Lewis, Factory (no licence)

Runtime: Python ≥ 3.11, `claude-agent-sdk` 0.1.81 (locked), `pydantic` 2.13.5, an authenticated `claude` CLI on
PATH; POSIX only [R05 §2]. Main has 17 tests and CI (pytest, ruff); the benchmark harness is on the unmerged
`codex/eval-suite` branch [R05 §7]. Every row: licence none, so code reuse needs the author's permission.

| Component (path) | Kind | Security notes | Status | R-class | Candidate verdict — reason |
|---|---|---|---|---|---|
| Bounded worker/check retry loop (`runner.py:99-186`) | workflow | unrestricted Bash pre-approved; runs in the live checkout by default; no tamper detection [R05 §8] | T-CI | RI | **REIMPLEMENT** — setup once, one worker, ordered checks, bounded retries |
| `CheckResult` pass/retry/stop + SDK json_schema output (`config.py:43-51`; `runner.py:64,83-87`) | pattern | validates structure, not judgment | T-CI | RI | **REIMPLEMENT** — separates "worker can fix" from "needs a human" |
| Exit-code contract 0 pass / 1 retry / other stop + 12 KB tail feedback (`runner.py:93-96,162-167`) | pattern | check output flows into the worker prompt | T-CI | RI | **REIMPLEMENT** — one outcome vocabulary for shell and LLM checks |
| Hardened SDK call options (`runner.py:53-67,79-90`; clone re-read) | pattern | `dontAsk` + allowlist, fail on any denial, `strict_mcp_config`, `setting_sources=[]` | T-CI | RI | **REIMPLEMENT** — [Docs] `setting_sources=[]` disables user, project and local settings (Python SDK > 0.1.59), so project `settings.json` hooks and CLAUDE.md are not loaded [Docs, agent-sdk/claude-code-features, accessed 2026-10-22: the `"project"` source loads "Project `settings.json` and hooks"; filesystem hooks load "when `settingSources` includes the relevant source"]; managed policy settings (and their hooks) are read regardless |
| Process-group timeout kill (`runner.py:21-39`) | pattern | kills child trees | T-CI | RI | **REIMPLEMENT** — POSIX only |
| Strict TOML config schema (`config.py:10-40`) | pattern | `extra="forbid"`; blank command accepted on main | T-CI | RI | **REIMPLEMENT** |
| Prompts frozen before setup; checks validated before side effects (`runner.py:109-117`) [R05 §12.3] | pattern | setup cannot alter instructions | T-CI | (§12) | **REIMPLEMENT** |
| BUILD / REVIEW / TRIAGE prompts (`.factory/*.md`) | prompt | prompt-level data/instruction separation only | P | RO | **REFERENCE ONLY** |
| Probe-based reviewer prompt (`eval-suite:.factory/REVIEW-EXPERIMENTAL.md`) | prompt | — | U, P | RO | **REFERENCE ONLY** — measured no gain in v4 (12/16 all arms) |
| Issue→PR and improve-factory skills (`examples/story/skill/*`) | skills | autonomous push acting on bot comments, "no human in the loop" | P | RO | **REJECT** as workflows; the "only problems corrected in ≥ 2 PRs count" evidence rule is a REFERENCE idea |
| Coding-workflow benchmark harness (`eval-suite:evals/run.py`, `grade.py`, `cases/*`) | script | not a sandbox; grader imports agent code on the host | U, T (12 tests) | RI | **REIMPLEMENT** — false-completion metric, suite hashing, seeded schedules |
| Independent grader: copy implementation only, held-out tests, fail-closed (`eval-suite:run.py:120-151`, `grade.py:11-36`) | pattern | executes candidate code unsandboxed | U, T | RI | **REIMPLEMENT** — the clearest "agent says done" vs "independently correct" separation in the set |
| Review evidence from transcript tool events (`eval-suite:run.py:64-89`) | pattern | — | U, T | RI | **REIMPLEMENT** — a review counts only if tool events show it ran |
| Matched-baseline and frozen-baseline one-change methods (`eval-suite:evals/README.md:94-108,156-199`) [R05 §10, §12.6] | method | — | U, D | (not in §13) | **REIMPLEMENT** — change one element, rerun matched cases, evaluator not editable by the optimiser |
| Fake-agent test approach (`tests/test_pipeline.py:44-56,207-283`) | pattern | no credentials | T-CI | RI | **REIMPLEMENT** |

### 1.6 Report 06 — Owain Lewis, Blueprint (MIT)

Runtime: Markdown skills for Claude Code and Codex; `html-doc` needs Python ≥ 3.11, Pandoc ≥ 3, Node ≥ 22.12,
`@mermaid-js/mermaid-cli` 11.16.0 and `puppeteer` 25.5.0 (lockfile with integrity hashes); repo checks need
`PyYAML==6.0.3`. 28 tests, CI with SHA-pinned actions [R06 §2, §7]. No behavioural evals of the skills.

| Component (path) | Kind | Security notes | Status | R-class | Candidate verdict — reason |
|---|---|---|---|---|---|
| Opt-in invocation pattern + guard test (`agents/openai.yaml`, frontmatter, `test_check_repo.py:71-81`) | pattern | [Docs] `disable-model-invocation: true` keeps the description out of context and blocks Claude's own invocation [R06 §9, §17] | T-CI | RI | **REIMPLEMENT** — test hard-codes 12 skills; Codex behaviour [Unk] |
| Read-dependency-as-file composition (`skills/factory/SKILL.md:18`) | pattern | — | P | RI | **REIMPLEMENT** — composes opt-in skills without unblocking them |
| `/review` finding format and verdict rules (`skills/review/SKILL.md`) | skill | read-only by prose; fresh subagent or `Blocked`, unless the user accepts a documented self-review (`:85`) | P | NA | **ADAPT** — Priority × Confidence, "do not report ≤ 2", trigger-and-effect field [R06 §12.4] |
| `/test` criterion→evidence template | skill | lacks the untrusted-browser-content rule dropped with `browser-verify` | P | NA | **ADAPT** — add the untrusted-data rule |
| `/task-to-pr` delivery + merge gates, fresh-review-on-every-repair [R06 §12.3] | skill / workflow | merge authority by prose; unbounded repair loop | P | NA | **ADAPT** — any change invalidates prior evidence; needs a retry budget and code enforcement |
| Coordinator merge-gate list and worker prompt (`codex-issue-coordinator/SKILL.md:125-170`) | workflow | 3-strike escalation | P | RO / RI | **REFERENCE ONLY** — Codex-only by design (`CLAUDE.md:8-9`) |
| `/plan` two-reader ticket template (`skills/plan/SKILL.md:36-62`) | prompt template | — | P | DR | **REUSE** |
| `/spec` acceptance table + lifecycle rules (`skills/spec/SKILL.md:43-59`), decision vs implementation status [R06 §12.8] | prompt template | — | P | DR | **REUSE** — opinionated `docs/<slug>/spec.md` path |
| `/architecture-review` material-question rule | skill | read-only by prose | P | NA | **ADAPT** |
| Stacked-PR dependency rule (`task-to-pr/SKILL.md:37-43`) [R06 §12.5] | pattern | — | P | (§12) | **REIMPLEMENT** — start on an open prerequisite only after a fresh Approve |
| `html_doc.py` renderer + assets | script | Mermaid input filter, `securityLevel: strict`, network-dead Chromium proven by test, SVG allowlist, CSP [R06 §8] | T-CI | DR | **REUSE** — heavy toolchain; exact-version check breaks Dependabot bumps [Inf] |
| Candidate/lock/atomic-finalize lifecycle (`html_doc.py:490-659`) | pattern | `O_EXCL` lock, `0o600`, path-constrained candidates | T-CI | RI | **REIMPLEMENT** — single writer, single directory |
| Markdown link/fence checker (`scripts/check_repo.py`) | script | read-only | T-CI | DR | **REUSE** |
| `check_diff` fail-closed whitespace check | script | fails if base missing | T-CI | DR | **REUSE** |
| PR template with real-status checklist | template | — | D | DR | **REUSE** |
| SHA-pinned CI workflow (`check.yml`) | workflow | `contents: read` | D | RO | **REFERENCE ONLY** |

### 1.7 Report 07 — Morluto, REA (MIT; third-party engines under their own licences)

Runtime: Node `^22.19.0 || ^24.11.0 || >=26.0.0`, `npm@11.16.0`, exact-pinned runtime deps (MCP SDK 2.3.1, zod 4.4.3
and others); external engines are bring-your-own [R07 §2]. 2,081 test files, SHA-pinned CI; main CI unstable on
2026-10-22 during a bulk merge (19 success / 14 failed / 66 cancelled / 1 `action_required` of the last 100 completed runs) [R07 §1, V7-9]. REA calls
no LLM [Inf, R07 §2].

| Component (path) | Kind | Security notes | Status | R-class | Candidate verdict — reason |
|---|---|---|---|---|---|
| REA MCP server as a whole (npm `rea-agents`) | tool server | 15 tools declare `executesForeignCode`; HTTP mode has no authentication (documented design limit); "not a sandbox" (`SECURITY.md:33-37`); diagnostics and setup-apply use `@latest` (`SKILL.md:46,65`) | T-CI (unstable) | DR (as tool) | **REUSE as an external tool** — stdio only, pinned version, foreign-code tools behind host approval; six majors in three months |
| Evidence record + bundle model (`src/domain/evidence.ts`, `evidenceBundle.ts`, `canonicalDigest.ts`) | library / pattern | integrity digest only, no signing | T-CI | NA | **ADAPT** — coupled to REA domain types; add a key if provenance matters |
| Reconstruction obligation ledger (`ReconstructionObligation*.ts`, `reconstructionObligationLedger*.ts`) | library / pattern | closure trusts caller-supplied proof records; no non-test producer of proof evidence [R07 §11] | T-CI | RI (or NA) | **REIMPLEMENT** — the formalism (unique owner, every required case kind, verifier at comparable authority) is the value |
| Proof-authority lattice (`ReconstructionObligationAuthority.ts:15-108`) | pattern | — | T-CI | RI (V7-8) | **REIMPLEMENT** — "a green unit test cannot close a packaged-process obligation" |
| Coverage + verification + readiness stages (`reconstructionCoverage*.ts`, `reconstructionVerification.ts`, `reconstructionReadiness*.ts`) | pattern | fail/unknown/unsupported/truncated/skipped never aggregate to pass | T-CI (readiness wired in CI) | RI | **REIMPLEMENT** — nine-stage readiness checklist |
| Process trace specification (`processTraceSpecification.ts`) | library | — | T-CI | NA | **ADAPT** — only where concurrent behaviour must be compared (partial order, finite traces) |
| Untrusted-content result marker (`toolResultEncoding.ts:26-37`, clone re-read) | pattern | labelling, not enforcement | T-CI (boundary test) | RI (C-1) | **REIMPLEMENT** — any tool server can mark target-derived output |
| Tool effects table → MCP annotations (`src/contracts/toolEffects.ts`) | pattern | makes risky tools machine-visible | T-CI | RI (V7-8) | **REIMPLEMENT** |
| Agent-experience eval scorer (`CodexAgentEval.ts`, `KnownAnswerEvaluation.ts`, `verify-agent-experience.mjs`) | library | runs Codex `--sandbox read-only`, `approval_policy=never` | I (not in CI) | NA | **ADAPT** — parses Codex JSONL specifically; known-answer check is the reusable part |
| Digest-verified recorded tool catalog (`deferredRuntime.ts:25-46`) [R07 §12.6] | pattern | catalog trusted only if its SHA-256 matches a compiled value | T-CI | (§12) | **REIMPLEMENT** — fast, lazy MCP startup |
| Measured efficiency checkpoints (`experiments/analysis-efficiency/`) [R07 §12.8] | method | — | D | (§12) | **REFERENCE ONLY** — dated, partly negative benchmarks as practice |
| `reverse-engineer-anything` skill | skill | `@latest` in diagnostics and setup-apply | P | RO | **REFERENCE ONLY** — bound to REA tool names |
| `rea-analysis-optimization` skill | skill | — | P | RI | **REIMPLEMENT** — oracle-first, measure-first workflow |
| Setup planner (`Setup*.ts`, `ClientConfiguration*.ts`) | library | dry-run, backups, approval; writes ~15 clients' configs | T-CI | RO | **REFERENCE ONLY** — product-specific |
| Process ownership / supervision (`src/process/`, `src/windows/`) | library | owned process groups, `prlimit`, Job Objects; not a sandbox | T-CI | RO | **REFERENCE ONLY** — large, platform-specific |

### 1.8 Report 08 — Matt Pocock, Sandcastle (MIT)

Runtime: TypeScript ESM, Node ≥ 22, sole runtime dependency `@clack/prompts`; Effect bundled; optional
`@vercel/sandbox`, `@daytona/sdk`; Docker or Podman on the host; agent CLIs installed in the image. ~1,416 vitest
cases (54 `*.test.*` files repo-wide, 53 under `src/`, 47 of them at its top level, clone; R08 §7 says 54); CI without typecheck or lint; npm releases attested;
v0.12.0, pre-1.0, breaking `v1` branch pending [R08 §1, §2, §7].

| Component (path) | Kind | Security notes | Status | R-class | Candidate verdict — reason |
|---|---|---|---|---|---|
| `@ai-hero/sandcastle` package (`run`, `createSandbox`, `createWorktree`, `interactive`) | library | `run()` always passes `dangerouslySkipPermissions: true` (clone `Orchestrator.ts:143`) [Obs]; host `.git` bind-mounted read-write; secrets as `docker run -e`; network open by default; LLM-chosen branch names interpolated into host `exec` (`SandboxLifecycle.ts:443,517-518`) [R08 §8] | T-CI | DR | **ADAPT** — only Claude's `permissionMode` narrows privilege (`AgentProvider.ts:1196-1202`); Codex's `approvalsReviewer: "auto_review"` swaps the bypass for per-action approvals by an auto reviewer but passes `-s danger-full-access`, disabling Codex's own sandbox (clone `AgentProvider.ts:790-797`); `.git` mount and branch-name injection need code-level fixes or the isolated-provider path |
| Sandbox provider contract + factories (`SandboxProvider.ts:24-330`) | library / pattern | isolation strength left to the implementer | T-CI | DR | **REUSE** — small Promise contract; streaming `onLine` mandatory |
| Agent provider contract + 6 providers (`AgentProvider.ts`) | library | bypass flags baked into AFK commands | T-CI | DR / NA | **ADAPT** — stream parsers track each CLI's JSON format |
| Docker/Podman providers (`sandboxes/docker.ts`, `podman.ts`, `DockerLifecycle.ts`) | library | no mem/pids/cap-drop/seccomp; `-e` secrets visible in argv | T-CI | NA | **ADAPT** |
| Git bundle sync-in / format-patch sync-out (`syncIn.ts`, `syncOut.ts`) | library | host applies agent-produced patches | T-CI (`syncIn.test.ts`, `syncOut.test.ts`) | RI (or reuse) | **REUSE** (through the library) — the isolated path avoids mounting `.git` |
| Completion-timeout / hanging-process race (`Orchestrator.ts:22-244`; ADR 0019/0021) | pattern | in-band marker can be quoted | T-CI | RI | **REIMPLEMENT** |
| Session capture + cwd rewrite, resume/fork (`SessionStore.ts`) | library | copies transcripts (may hold secrets) to the host | T-CI | NA | **ADAPT** — undocumented CLI session layouts |
| Structured output + resume retry; produce→extract (`Output.ts`, `extractStructuredOutput.ts`, `run.ts:842-890`) | library / pattern | JSON only | T-CI | DR / RI | **REUSE** (library) / **REIMPLEMENT** (pattern) — schema repair never redoes work |
| Prompt template engine (`PromptArgumentSubstitution.ts`, `PromptPreprocessor.ts`) | library | args inside a template's `` !`…` `` block are interpolated unescaped | T-CI | RI | **REIMPLEMENT** — keep the inert-arg marker idea, fix the shell interpolation |
| Workflow templates (`src/templates/*`) | workflow | LLM-generated branch names reach host shell | T-CI (partly) | NA | **ADAPT** |
| Label-driven GitHub agent workflows (`.github/workflows/agent-*.yml`) | workflow | explore job privilege-split; implement/review run with write tokens via `noSandbox()` | I | RO / RI | **REFERENCE ONLY** |
| Plan validation against a pre-agent snapshot (`explore/batch.ts`, `apply.ts`) [R08 §12.8] | pattern | whitelisted effects only; all-or-nothing apply | I | RI | **REIMPLEMENT** — the most transferable untrusted-input control in the set |
| `triage-repro` skill | skill | explicit untrusted-input rules | P | NA | **ADAPT** |
| Public-types-effect-free check | script | — | I | DR | **REUSE** — narrow purpose |
| ADRs, `.out-of-scope/`, `CONTEXT.md` | method | — | D | RI | **REIMPLEMENT** — documented rejections reused by triage |

### 1.9 Report 09 — IndyDevDan, Super Simple Software Factory (MIT)

Runtime: Python 3 via `uv run` PEP 723 scripts with **unpinned** `pydantic`, `python-dotenv`, `pyyaml`, `rich`; the
**Pi** coding-agent CLI only (Claude Code adapter raises `NotImplementedError`, clone `agent_cc.py:11-15`) [Obs];
`git`, `sqlite3`; visualizer on Bun + Vue 3 + Vite 7 with committed `bun.lock`. No tests, no CI; defects found by
reading [R09 §2, §7].

| Component (path) | Kind | Security notes | Status | R-class | Candidate verdict — reason |
|---|---|---|---|---|---|
| Phase context manager + `finish(accepted)` (`M/runner.py`) | library | — | I | NA | **ADAPT** — "success must be earned"; coupled to Tracer/Console |
| Typed envelope contracts + `PhaseParams` validator (`M/data_types.py`) | library | config models ignore unknown keys | I | DR / NA | **ADAPT** — generic types reusable; `PiRequest`, `UsageBreakdown` mirror Pi |
| Parse-and-correct loop in the same session (`M/agents.py:253-287`) | pattern | re-prompts can bill no-op turns (issue #13 [Claim]) | I | RI | **REIMPLEMENT** |
| Evidence-carrying gates `GateReport` (`M/gates.py`) | library | `tests_pass` uses `shell=True`; `diff_matches_claims` checks existence only | I | NA | **ADAPT** |
| Post-hoc write-boundary enforcement (`M/permissions.py`) | library | blind to gitignored and outside-repo paths and to agent `git commit`/`stash`; after the fact [R09 §8] | I | NA | **ADAPT** — useful as a cheap "do not edit your grader" tripwire; not a boundary |
| Deterministic quality blocks + `as_envelope` (`M/quality.py`) | library | placeholders exit 0 until replaced | I, X | NA | **ADAPT** |
| Change capture with reasoned base (`M/changes.py`, `M/git_helper.py`) | library | `git add -A` commits the whole tree (`git_helper.py:49`) | I | DR | **ADAPT** — capture is reusable; staging must be explicit |
| SQLite WAL tracer + schema + migrations (`M/tracer.py`) | library | stores full prompts and tool args (may contain secrets) | I | DR | **ADAPT** — add redaction and retention; schema is Pi-shaped for usage |
| Pi JSONL adapter + `ToolCallTracker` (`M/agent_pi.py`) | library | no subprocess timeout; inherits full env | I | NA | **REFERENCE ONLY** outside Pi hosts |
| Operator-env helper (`M/utils.py:16-38`) | library | passes all credentials to children | I | DR | **REFERENCE ONLY** — trivial; full-credential inheritance |
| Twelve ADW chain templates (`A/adw_*.py`) | workflow | `git add -A` | I, X (example branch renames break five ADWs) | NA | **REFERENCE ONLY** |
| Agent prompt pairs (`P/*/`) | prompt | — | P | NA | **ADAPT** |
| Orchestrator skill + cookbooks (`S/SKILL.md`, `S/cookbooks/`) | skill | — | P | RO / NA | **REFERENCE ONLY** — written for Pi v1 |
| Request-translation contract (`how_to_prompt_for_the_eng.md:29-55`) | pattern | — | P | RI | **REIMPLEMENT** |
| Phase-description validator (`data_types.py:31-53`) and per-agent commit authorship [R09 §12.5, §12.7] | pattern | — | I | (§12) | **REIMPLEMENT** |
| Subagent fan-out extension (`subagents.ts`) | Pi extension | children untraced, outside the process registry | I | RO | **REFERENCE ONLY** — Pi API |
| Trace visualizer (`S/apps/visualizer/`) | app | `Bun.serve` without `hostname` may bind all interfaces [Inf]; archive POST unauthenticated | I | NA | **ADAPT** — bind to loopback, authenticate writes |
| Installer: idempotent stamp + drift report (`S/scripts/install.py`) | script | `--force` overwrites user prompts and config | I | DR (pattern) | **ADAPT** |

### 1.10 Report 10 — Cole Medin, AI Software Factory (no licence)

Runtime: Python ≥ 3.10 stdlib; git, `gh` (with `workflow` scope), bun, uv; a coding-agent CLI (Claude Code or Codex);
the external **Archon** engine (TypeScript under bun, MIT per `gh api`, accessed 2026-10-22) pinned to SHA `4eb7bd77`
on branch `factory/sdlc-on-dev`, 92 ahead of and 575 behind Archon `dev` [R10 §2.2]. 83 unittest methods, no CI
[R10 §7]. Every row: licence none.

| Component (path) | Kind | Security notes | Status | R-class | Candidate verdict — reason |
|---|---|---|---|---|---|
| Pinned-source verifier (`consumer.py:76-218`) | library / pattern | HEAD = SHA, clean status, no untracked/ignored/symlinked files under `.archon` and `packages/cli/src` only; `node_modules` presence-checked (V10-3, C-4) | T | RI | **REIMPLEMENT** — refuse to run on an ambient or modified engine |
| Default-input injection with caller override (`consumer.py:221-256`) | pattern | keeps policy facts out of agent discretion | T | RI | **REIMPLEMENT** |
| Board-aware launch gate (`consumer.py:535-687`) | pattern | fails open by design | T | RI | **REIMPLEMENT** — signature dedupe, idle lap, stuck sweep |
| Single-flight OS lock (`consumer.py:512-532`) | library | advisory | T | RI | **REIMPLEMENT** (trivial) |
| Cross-platform timer generation (`consumer.py:442-509`) | script | embeds full PATH; `IS_SANDBOX=1`; no `KillMode` (issue #59) | T | NA | **REIMPLEMENT** — reconciled from NA (no licence) |
| STOP/PAUSE brake files (`consumer.py:286-311,734-773`) [R10 §12.8] | pattern | local only | T | RI | **REIMPLEMENT** — two-level brake keeps in-flight work |
| Runtime host (`runtime_host.py`, `runtime_process.py`) [R10 §12.2] | library | loopback bearer auth, stripped env, no shell; documented as not a sandbox; macOS path bug (issue #4) | T (13 tests) | NA | **REIMPLEMENT** — reconciled from NA; candidate identity binding is the idea |
| Revision-bound resource materializer (`runtime_resource.py`) | script | zip-slip and symlink checks | T (5 tests) | NA | **REIMPLEMENT** — reconciled from NA |
| Mutation apply/score tool (`harness/mutations/run.py`) [R10 §12.3] | script | sanitised output | T | RI (V10-1) | **REIMPLEMENT** — three-valued CAUGHT / ESCAPED / INCONCLUSIVE |
| Defect-catalogue guidance (`defects.json`) | doc | ships empty | D | RI | **REIMPLEMENT** |
| Ordinary gate runner (`harness/ci.py`) [R10 §12.9] | script | "zero tests is not a pass"; timeout = failure | T | RI (V10-1) | **REIMPLEMENT** |
| Guard self-mutation check (`bin/selfcheck-mutations.py`) | script | temp copies | I (it is itself a test driver) | RI | **REIMPLEMENT** — each guard paired with the test that must go red |
| Ownership auditor (`bin/audit.py`) | script | static; not run by any CI (V10-5) | I | RI | **REIMPLEMENT** |
| MISSION / WORKFLOW_POLICY / FACTORY_RULES / HOLDOUT templates [R10 §12.7] | templates | governance by convention + `protected_paths` | D | NA | **REIMPLEMENT** — reconciled from NA; text copying needs permission |
| Incident log (`docs/incidents.md`) | reference | describes mostly removed code | D | RO | **REFERENCE ONLY** |
| Ubuntu bootstrap (`bin/bootstrap-ubuntu.sh`) | script | run as root via `curl \| bash`; unpinned `curl`-pipe installers | I | RO | **REJECT** |
| Archon SDLC pack (external, `coleam00/Archon`, MIT) | engine | agents, merge gate, review independence not inspected (out of scope) | [Unk] | — | **REFERENCE ONLY** — unevaluated; pinned to an unmerged branch |

### 1.11 Report 11 — Jake Schincariol, Replica Skill (MIT, © 2026 Jake Schincariol)

Runtime: Markdown skills (Claude Code plugin); six Python 3 stdlib tools (README claims ≥ 3.8 [Claim]) with no
network or subprocess imports; 57 unittest functions, no CI [R11 §2, §7].

| Component (path) | Kind | Security notes | Status | R-class | Candidate verdict — reason |
|---|---|---|---|---|---|
| Layout and pixel screenshot diff + stdlib PNG codec (`replica-diff/imgdiff.py`) | script / library | unbounded `zlib.decompress` (`:152`); uncaught `struct.error` on truncated IHDR (issue #10) | T (14 tests) | DR | **ADAPT** — bound decompression and handle malformed input; layout mode is colour-invariant by design (luminance edges, not fully) |
| Weighted feature-parity scorer (`replica-diff/parity.py`) | script | — | T (10 tests) | DR | **REUSE** — as a scorer; it has no must-have exit code, so it is not a gate on its own |
| Feature-matrix schema (`replica-recon/features.csv`) | template | self-reported status; no link to tests | D | RI | **ADAPT** — MIT template; add test links and an independent status column |
| Provenance-enforcing evidence ranker (`replica-entrepreneur/reviews.py` + `themes.json`) | script | ingests untrusted third-party text the LLM later reads | T (11 tests) | NA | **ADAPT** — quotes are substrings of sourced rows [R11 §12.3] |
| Denylist identity sweep (`replica-brand/sweep.py`) | script | 2 MB cap; no symlink following | T (5 tests) | NA | **ADAPT** — hex-only colours; binaries skipped |
| WCAG contrast gate (`replica-design/contrast.py`) | script | — | T (in 12) | DR | **REUSE** — WCAG 2 only |
| Store-listing linter (`replica-launch/listing.py`) | script | literal invisible Unicode in source (`:50,53`) | T (in 12) | NA | **ADAPT** — store limits hard-coded |
| Recon map template with stable S/F IDs, evidence + confidence | template / skill | reads untrusted web content with no data-not-instructions rule | P | RI | **ADAPT** — MIT text; add an untrusted-content rule |
| Clean-room and ToS rules block | pattern | prose; omits patents, public-site ToS, retention [R11 §8] | P | RO | **REFERENCE ONLY** |
| Test-plan and bug-report formats | template | — | D | DR | **REUSE** |
| Playwright spec skeleton with console, 5xx and axe guards (`e2e.example.spec.ts`) | template | unpinned `@playwright/test`, `@axe-core/playwright` | D | NA | **ADAPT** — role/label selectors survive a rebrand |
| Deploy preflight checklist | workflow | LLM-enforced; `parity.py` step always exits 0 | P | RI | **REIMPLEMENT** — make every step exit-code gated |
| "to run" vs dated-result rule (`replica-brand/SKILL.md:40-57`) | pattern | guards against hallucinated verification | P | RI | **REIMPLEMENT** |

### 1.12 Reconciliation with the licence rules and the mandatory criteria

**Licence reconciliations** (report class conflicts with brief rule 7):

| Report | Component | Report class | Reconciled verdict | Reason |
|---|---|---|---|---|
| 10 | Cross-platform timer generation | NA | REIMPLEMENT | no licence (`gh api license: null`, R10 header); NA implies modifying the code |
| 10 | Runtime host (`runtime_host.py`, `runtime_process.py`) | NA ("with permission" in the index) | REIMPLEMENT | same; the index's "needs adaptation, with permission" is outside the brief's rule |
| 10 | Revision-bound resource materializer | NA | REIMPLEMENT | same |
| 10 | MISSION / WORKFLOW_POLICY / FACTORY_RULES / HOLDOUT templates | NA | REIMPLEMENT | template text is code-equivalent for copyright purposes [Inf] |
| 02 | `github_review.py` regression tests (`tests/test_github_review.py`) | (covered by the MIT row) | REIMPLEMENT the tests | `tests/` has no licence (R02 header); only `greploop/` is MIT |
| 01 | v2 spine | RO / RI (GPL) | REFERENCE ONLY | consistent; copyleft would bind any distributed derivative |

No other §13 class conflicts with rule 7. Reports 01 (after V1-1), 05 and 10 (after V10-1, apart from the four rows
above) already cap no-licence code at "reimplement the idea" or "reference only".

**Verdicts that differ from the report class for non-licence reasons** (mandatory security and correctness criteria):

| Component | Report class | Candidate verdict | Deciding fact |
|---|---|---|---|
| R03 guard hooks | DR | ADAPT | fail open: internal exceptions swallowed with exit 0 in all five guards (`guard-secrets.py:62-63` and peers); [Docs] `onFailure: "block"` does not catch an exit-0 swallow, so the code itself must change |
| R03 eval-staleness hook | DR | ADAPT | fails open; result paths specific |
| R03 Codex lane launcher | RO | REJECT (as configured) | `approval_policy="never"`, network on |
| R02 before-and-after | RO | REJECT | public upload default, unpinned remote execution, noncompete licence |
| R04 hook templates, hook generator, prompt validator, issue automation | RO / RI | REJECT | contradict the documented hook contract; inverted estimator; untrusted text to a write token |
| R04 prompt presets | DR (content) | REFERENCE ONLY | quality never evaluated |
| R08 Sandcastle package | DR | ADAPT | permission bypass by default; host `.git` mounted read-write; branch-name injection |
| R09 SQLite tracer, change capture | DR | ADAPT | stores raw prompts; `git add -A` |
| R09 operator-env helper | DR | REFERENCE ONLY | passes every credential to child processes |
| R11 `imgdiff.py` | DR | ADAPT | decompression bomb and crash on malformed PNG |
| R07 REA MCP server | DR (as tool) | REUSE as external tool, with conditions | unauthenticated HTTP mode, foreign-code tools, `@latest` in skill |
| R10 Ubuntu bootstrap | RO | REJECT | run as root via unpinned `curl \| bash` installers |
| R05 issue→PR and improve-factory skills | RO | REJECT (as workflows) | autonomous push acting on bot comments, "no human in the loop" |
| R09 Pi JSONL adapter | NA | REFERENCE ONLY | Pi-specific; no subprocess timeout; inherits the full environment |
| R09 twelve ADW chain templates | NA | REFERENCE ONLY | `git add -A`; example-branch renames break five ADWs |
| R09 installer | DR (pattern) | ADAPT | `--force` overwrites user prompts and config |
| R04 skills factory prompt | NA | REFERENCE ONLY | Python-centric; self-attested checklist |
| R04 Codex CLI wrapper | NA | REFERENCE ONLY | `--full-auto`, `--skip-git-repo-check`; 2025-11 flags and model names |
| R04 guide subagents | RI | REFERENCE ONLY | cannot work as described (no Agent tool, hard-coded path) |
| R04 hooks factory prompt; domain-pack ZIPs | RO | REJECT (these parts only) | wrong hook event table; ZIPs ship unreviewable `.pyc` bytecode |
| R03 review-remembers protocol | RI | ADAPT | MIT prompt text reused, not only the idea |
| R03 test-gap check | DR (text) | ADAPT | depends on an external `tdd` skill |
| R03 writing standard + format tests | NA | REFERENCE ONLY | opinionated emoji and commit format |
| R11 feature-matrix schema | RI | ADAPT | MIT template text reused, with test links and independent status added |
| R11 recon map template | RI | ADAPT | MIT text; needs an untrusted-content rule |
| R01 factory orchestrator loop | RI | REFERENCE ONLY | not resumable; superseded by code-owned loops elsewhere |
| R08 sync-in / sync-out | RI (or reuse) | REUSE (through the library) | isolated path avoids mounting `.git` |

With these rows the table covers every section 1 row whose candidate verdict differs from the report's class for a
non-licence reason (audited row by row on 2026-10-22). Licence-driven changes are in the licence table above.

---

## 2. Overlap and redundancy

Each group compares components from different repositories that solve the same problem. Ratings use Strong /
Adequate / Weak / Absent / Unknown against the group's own problem, never a blended score.

### 2.1 Merge gates and merge authority

| Component | Enforcement | Review bound to commit | Human approval | Where checks run | Status · licence | Rating |
|---|---|---|---|---|---|---|
| R03 merge gate + policy + approval | code: `mkdir` lock with stale-after, `--expect-head` + `--match-head-commit`, distinct exit codes 2/4/5/6/7/8/9 [R03 §12.2] | yes (head pin; approval binds repo, PR, 40-char head, sha256 of the policy plan) [R03 §12.3] | `done` comment by a write-permission `User`, re-read before merge; weak when agent and human share a token [R03 §8] | current base merged into reviewed head, scratch worktree, inside the lock, via host `eval` | T-CI · MIT | **Strong** (code), with a host-execution gap |
| R01 v1 approver | prompt; `merge-tree --write-tree` conflict check [R01 §12.4] | no | ESCALATE on policy categories | host, local `main` | P · none | **Weak** |
| R01 v2 `gate` + `job` | code: main-checkout `checks.sh` judges the branch, protected paths, `gh pr merge` after re-sync [R01 §2.4] | partly (re-gate after re-sync) | — | worktree | U · GPL-3.0 | **Adequate** on paper, unusable (unmerged, incomplete) |
| R06 `/task-to-pr`, `/factory` | prose: fresh Approve on the final commit; authority only by explicit invocation [R06 §12.2-3] | by instruction | PRs left open unless `/factory` is named | GitHub CI | P · MIT | **Weak** (enforcement) / **Strong** (authority model) |
| R10 merge inputs | declared facts `required_checks`, `protected_paths` injected into merging workflows; enforcement in Archon [R10 §12.6] | [Unk] (Archon) | `merge_mode` [Unk] | Archon | T (consumer) · none | **Unknown** |
| R02 review freshness | code: bot score counts only for the current head [R02 §12.1] | yes (signal, not merge) | human merges | Greptile SaaS | T · MIT | **Strong** for its narrow problem |
| R08 Sandcastle | none in the library; repo CI uses `--force-with-lease` pinned to the event head [R08 §8] | — | caller | caller | — · MIT | **Absent** (by design) |
| R05 Factory | removed with the Git logic in `9b7f5cf` [R05 §8] | — | — | — | — · none | **Absent** |

Trade-offs. Only R03 enforces the gate in code on main; R01 v2 shows a second design (judge from main, protected paths)
that is unmerged and copyleft. Code gates and prose authority solve different halves: R03 decides *whether a head is
mergeable*; R06 decides *who may grant merge at all* (explicit invocation, never deploy). R01's ESCALATE list and R03's
merge-policy categories overlap almost one to one (money, auth, deploy/CI, schema, dependencies); both are keyword or
path heuristics that a renamed path bypasses [R03 §8]. The default differs sharply: R03 boards default to
`merge_policy.default: "auto"` [R03 §17], R06 leaves PRs open. No component separates human and agent GitHub identities
in code; R03 offers a robot account as an option. **BUILD NEW** gap: an approval channel the agent cannot write to,
verified in code.

### 2.2 Job and state stores, locks and claims

| Component | Store | Lock / claim primitive | Resume | Multi-host | Status · licence |
|---|---|---|---|---|---|
| R01 v1 | `factory/jobs/<id>/job.json` + Markdown artifacts | atomic `mkdir` job claim; optimistic Edit backlog claim | no (session death strands the job) [R01 §1] | no | P · none |
| R01 v2 | `job.json` written only by `bin/job` | `fcntl` lock per job, atomic replace, `TRANSITIONS` table | yes (scripted) [Claim, not executed] | no | U · GPL-3.0 |
| R03 | GitHub Projects v2 board (only loop state) + PR/issue comments | `mkdir` mutex with `--lock-timeout` / `--stale-after` (30-min floor); shared halt file | yes: "run" is "resume" [R03 §12.1]; Workflow relaunch returns cached agent results [Docs, via R03 §17] | yes (GitHub), lock is local-FS only | T-CI · MIT |
| R05 | `run.json` (`setup → working → checking → passed / needs_attention`) | none | no [R05 §13] | no | T-CI · none |
| R08 | git worktrees and branches; `SessionStore` transcripts | — | session `resume()` / `fork()` [R08 §12.5] | via isolated providers | T-CI · MIT |
| R09 | SQLite WAL (`sessions, phases, events, envelopes, gate_results, processes, agent_sessions`) | process registry; single writer per run | no (trace, not a resumable plan) | no | I · MIT |
| R10 | Archon state [Unk] + `.factory/` STOP/PAUSE files + OS timers | single-flight OS lock | Archon `resume` [Claim] | no | T · none |
| R02 | attempt JSON files | exclusive-create reservation before any network write | partial (idempotent re-trigger) | no | T · MIT |
| R06 | GitHub PRs; html-doc candidate/lock | `O_EXCL` `0o600` lock | — | — | T-CI · MIT |
| R11 | `replica/` folder, `features.csv` ledger | none | file hand-off | no | P · MIT |
| R07 | content-addressed Evidence bundles | — | evidence replay with tamper rejection [R07 §7] | — | T-CI · MIT |

Trade-offs. A SaaS store (R03) gives resume and multi-machine visibility at the cost of rate limits (R03 measured
GraphQL point costs and throttles workers) and of making issue text a control input. Local files (R01, R05, R10) are
cheap and private but single-host, and only R01 v2 validates transitions in code. SQLite (R09) is the richest record
but is an audit trail, not a plan. Lock primitives converge: `mkdir` (R01, R03), `O_EXCL` (R02, R06), `fcntl` (R01 v2),
OS single-flight (R10); only R03 handles staleness explicitly.

### 2.3 Review protocols and verdict formats

| Component | Reviewer independence | Read-only enforced | Finding format | Re-review on change | Status · licence |
|---|---|---|---|---|---|
| R01 four lenses + WAIT-FOR-ALL | fresh subagents, same session family | no (Bash + Write) [R01 §8] | first-line `VERDICT:` | up to 2 builder resumes, ≤ 3 rounds | P · none |
| R03 Reviewer + 2 truth-check sub-agents | separate lane on the session model [R03 §2] | [Unk] | stable finding ids, one in-place report; min of two scores; over-engineering never blocks alone [R03 §12.6-7] | mandatory recheck of prior findings | P + offline test + paid eval · MIT |
| R06 `/review`, `/architecture-review` | fresh subagent, else `Blocked` (or documented self-review) | no (prose) | Priority × Confidence 0-5, floor ≤ 2 not reported, trigger-and-effect [R06 §12.4] | any change invalidates prior Approve | P · MIT |
| R05 LLM check + review evidence | separate fresh SDK session; same workspace [R05 §7] | no (check tools include Bash) | `CheckResult` pass/retry/stop + feedback | all checks rerun after a retry | T-CI (main); review-from-tool-events U · none |
| R02 greploop | external bot (Greptile) | n/a | bot score + threads | freshness tied to head | T · MIT |
| R09 reviewer agent | separate Pi session | post-hoc write boundary | typed envelope + `GateReport` | bounded loops | I · MIT |
| R10 / Archon | "independent of the implementer" [Claim, `WORKFLOW_POLICY.md:52-56`] | [Unk] | [Unk] | [Unk] | [Unk] · none |

Trade-offs. All LLM reviewers here are the same model family as the builder [R03 §7, R06 §7, R05 §7], except SSSF (R09),
whose starter roster gives the reviewer `gpt-5.6-terra` while the builder inherits the `gemini-3.6-flash` default
[R09 §3]; elsewhere independence is context separation only. No repository enforces reviewer read-only by tool restriction (R01 and R05 hand reviewers
Bash). R05's author data is the only measurement: Factory's scripted review vs Claude Code with a prompted reviewer
subagent, 30/36 vs 29/36 completed-and-passed, but 30/36 vs 31/36 on "code passed independent tests, regardless of
completion", which favours the subagent arm (two direct runs timed out with passing code) [R05 §9; clone
`codex/eval-suite:evals/reports/2026-09-25-v3/README.md`, unmerged branch; author data, not re-run], so a code-owned
loop showed no clear quality gain over a prompted subagent on that suite. The formats are complementary rather than redundant: R06 calibrates
*what* to report, R03 governs *how findings persist across rounds*, R01 and R05 define *how the orchestrator reads the
verdict*.

### 2.4 Structured outcome contracts

| Component | Outcome vocabulary | How produced | Repair on invalid output | Status · licence |
|---|---|---|---|---|
| R05 `CheckResult` | pass / retry / stop + mandatory feedback; shell 0 / 1 / other | SDK `output_format` json_schema; missing output stops the run | none (stop) | T-CI · none |
| R08 `Output.object` | caller schema (any Standard Schema validator) | parsed from the agent's final message | session-resume retries; produce→extract split [R08 §12.6] | T-CI · MIT |
| R09 envelopes + `GateReport` | typed pydantic models; gates record evidence on passes too | parsed from Pi output | parse-and-correct in the same session | I · MIT |
| R03 workflow exits | JSON-schema outputs per `agent()`; gate exit codes route to board actions | Workflow tool | lane-level | T-CI · MIT |
| R01 first-line token | `VERDICT:` / `STATUS:` / `APPROVE` / `ESCALATE` | prose | none (orchestrator stops) | P · none |
| R10 mutation scoring | CAUGHT / ESCAPED / INCONCLUSIVE / NOT_INJECTED | code over gate logs | n/a | T · none |
| R07 Evidence | confidence and authority as separate axes; "unknown is not absence" | code | n/a | T-CI · MIT |

Trade-offs. R05 is the strictest (fail on anything not schema-valid) but requires SDK structured output; R08 is the
most forgiving (resume and correct) and keeps the repair cheap; R09 adds evidence to passes, which the others lack.
Three-valued outcomes recur (R05 retry vs stop, R10 inconclusive vs caught, R07 unknown vs absent): each refuses to
collapse "could not decide" into pass or fail.

### 2.5 Parity ledgers and specification traceability

| Component | Level | Unit | Closure rule | Independent of builder | Status · licence |
|---|---|---|---|---|---|
| R07 obligation ledger + authority lattice | binary / process / bundle | obligation with owner (module, symbol, implementation SHA-256) and required case kinds | fail-closed; verifier at comparable authority; blocked/out-of-scope never count [R07 §11] | in principle, but proof records come from the caller and have integrity only; no non-test producer | T-CI · MIT |
| R07 `compare_application_versions`, `compare_source_to_bundle` | application graph | modules, routes, IPC | unique-only matching, no fuzzy pairing | yes (deterministic) | T-CI · MIT |
| R11 `features.csv` + `parity.py` | product (screens, flows, features) | weighted rows must/should/could, `skip`, `original=no` | score only; flat 0.5 partial; no must-have exit code [R11 §13] | no — the builder marks its own rows [R11 §7] | T · MIT |
| R11 `imgdiff.py` | visual layout | edge-density grid | `--fail-under` | yes (deterministic) | T · MIT |
| R06 `REQ-n` / `AC-n` / `INV-n` + `/test` | requirement | acceptance id → evidence | prose | fresh reviewer | P · MIT |
| R10 holdout + mutation | behaviour | holdout scenarios, injected defects | three-valued scoring | holdout not hidden from the builder by code [R10 §8] | T · none |
| R01 builder evidence-per-AC | feature | AC rows | self-reported | reviewers (skipped browser checks) | P · none |

Trade-offs. R07 and R11 do not overlap in practice: R07 proves behavioural claims about artifacts and leaves planning
and coding to the host; R11 measures product coverage and leaves proof to the builder's honesty. R07 has the right
closure rule and no producer; R11 has the producer and no independent closure. R06 IDs are the thinnest bridge between
spec and evidence. **BUILD NEW** gap: signed (not merely hashed) evidence records, so a fabricated verifier record
cannot close an obligation [R07 §6, §11].

### 2.6 Tracing, observability and cost

| Component | Granularity | Tokens / cost | Persistence | Status · licence |
|---|---|---|---|---|
| R09 SQLite tracer | phase, event, folded tool-call span, gate evidence, process registry | per phase, summed across retries; context occupancy separate from spend [R09 §12.6] | WAL SQLite + JSONL; Bun/Vue visualizer | I · MIT |
| R08 run telemetry | iteration; stream events (`onAgentStreamEvent`) | `IterationUsage` input / cache / output; "Context window: NNNk"; no dollars | file log | T-CI · MIT |
| R05 eval branch | trial | top-level vs `usage_all_models` incl. subagents | JSON reports | U · none |
| R01 v2 | job | priced from undocumented subagent transcript files [R01 §2.4] | `job.json` | U · GPL-3.0 |
| R03 | card per wave | usage 5h %; no per-card cost [R03 §8] | run manifest, PR body history table | T-CI · MIT |
| R07 | tool call | none at runtime (no model calls); agent-eval token use | `pino` logs, progress notifications | T-CI · MIT |
| R01 v1 dashboard | job state | none | files, 2 s polling | I · none |
| R02, R06, R10, R11 | — | none | artifacts only | — |

Trade-offs. R09 is the only complete cost-per-phase trace on main, but it is Pi-shaped and stores raw prompts. R08
gives per-iteration usage across six agent CLIs without dollars. Cost per accepted deliverable is computed nowhere on
main; only R05's unmerged harness ties cost to independently graded acceptance. **BUILD NEW** gap: cost per accepted
(independently verified) deliverable as a standing metric.

### 2.7 Isolation runtimes

| Component | Boundary | Network | Secrets | Known gaps | Status · licence |
|---|---|---|---|---|---|
| R08 Docker/Podman | container, host UID | open by default | allow-listed keys via `docker run -e` (argv) | host `.git` read-write, permission bypass by default, no mem/pids/cap-drop/seccomp [R08 §8] | T-CI · MIT |
| R08 Vercel / Daytona | microVM / remote sandbox; git bundle in, patches out | `networkPolicy` pass-through (Vercel) | provider env | patches applied on host | T-CI · MIT |
| R10 runtime host | process tree + identity (Job Object / process group), loopback bearer API | no proxies, no redirects | stripped env | documented "not a sandbox"; macOS path bug | T · none |
| R07 process ownership | owned process groups, `prlimit`, Job Objects, Ghidra private dirs | n/a | redaction [Claim] | "not a sandbox"; Evidence `isolation` is `none` or `process` [R07 §8] | T-CI · MIT |
| R06 html-doc Chromium | network-dead browser for rendering only | blocked, proven by test | n/a | narrow purpose | T-CI · MIT |
| Worktrees (R01, R02, R03, R06, R10 via Archon) | git working copy | host | host | do not isolate ports, databases or host state (R02 `new-feature/SKILL.md:61-64`) | various |
| None (R05 default, R09) | live checkout | host | full env inherited | — | — |

Trade-offs. Sandcastle is the only general isolation runtime and its defaults conflict with its own ADR 0015; the
isolated providers avoid the `.git` mount but need a remote service. R10's runtime host and R07's process ownership
solve a different problem (owning and identifying the process under test), not containment. [Docs]
`bypassPermissions` skips prompts even for writes to protected paths such as `.git` and `.claude` and should be used
only in isolated environments; combined with R08's read-write `.git` mount, this makes the bind-mount path weaker than
it appears [Inf].

### 2.8 Installers and configuration writers

| Component | Integrity | Reversibility | Approval / dry-run | Notable defects | Status · licence |
|---|---|---|---|---|---|
| R04 `installer.py` | atomic temp file + re-parse | timestamped backup, keep-N rotation, rollback on exception | `input()` prompt | hard-coded event list incl. nonexistent `PrePush`; rejects 9 of 15 shipped hook files | I · MIT |
| R07 setup planner | `write-file-atomic`, `jsonc-parser` | backups | plan shown, approval required | skill uses `@latest` for diagnostics and setup-apply | T-CI · MIT |
| R09 `install.py` | copy | idempotent unless `--force`; drift report | — | `--force` overwrites user prompts | I · MIT |
| R10 `install.py` | Archon cloned at exact SHA, verified clean, `bun install --frozen-lockfile` | preserves personal files, backs up changed machinery | — | — | T · none |
| R03 `get.sh` / `install.sh` | tag tarball, no checksum or signature, `main` fallback | — | refuses root; truncation guard | `npx -y skills@latest add mattpocock/skills --skill '*'` | T-CI · MIT |
| R01 v2 `INSTALL.md` | unpinned `curl` from a branch where the files do not exist | — | — | cannot work at the inspected commit | U · GPL-3.0 |
| R10 `bootstrap-ubuntu.sh` | unpinned `curl \| bash` as root | — | — | root | I · none |
| R02, R06, R11 install docs | `npx skills add` / `cp` of moving `main` | — | — | unpinned | — |

Trade-offs. R04's write discipline and R07's plan-approve-backup flow are complementary halves of a safe config
writer; neither pins what it installs. R10 is the only installer that pins and verifies its engine. Every
skill-pack installer in the set pulls an unpinned `main`.

### 2.9 Policy guards: hooks, write boundaries, protected paths, invocation control

| Component | Mechanism | When it acts | Fails | Status · licence |
|---|---|---|---|---|
| R03 guard hooks | PreToolUse/PostToolUse regex and tokenizer checks (secrets, key literals, delete-outside, worktree path, protected push) | before and after the tool call | **open** on internal error | T-CI · MIT |
| R09 write boundary | change-set diff before/after each agent call, rollback, `PermissionBreach` | after the call | blind spots (ignored paths, outside repo, agent commits) | I · MIT |
| R01 v2 protected paths | gate fails a branch that touches `protected_paths` | at gate time | closed | U · GPL-3.0 |
| R10 `protected_paths` | policy input to Archon's `path-policy` hold | merge time | [Unk] | T (injection) · none |
| R05 SDK options | `dontAsk` + tool allowlist; any denial fails the run | per call | closed | T-CI · none |
| R06 opt-in invocation | `disable-model-invocation`, `allow_implicit_invocation: false`, unit test | skill selection | n/a | T-CI · MIT |
| R04 `allowed-tools` synthesis | least-privilege tool patterns; rejects bare `Bash` | authoring time | n/a | I · MIT |
| R07 tool effects | per-tool effect declarations → MCP annotations | host approval | depends on the host honouring annotations | T-CI · MIT |

Trade-offs. Pre-call hooks (R03) can block but are regex over command text and fail open; [Docs] PreToolUse hooks run
before the permission prompt for every tool, a hook exiting 2 blocks even when an allow rule matches, and deny rules
hold regardless of the hook's answer. Post-call diffs (R09) and gate-time path checks (R01 v2, R10) cannot prevent
side effects, only detect them. R05's allowlist is the only fail-closed per-call control, and it pre-approves
unrestricted Bash. These layers stack rather than compete.

### 2.10 Verifying the verifiers

| Component | What it proves | Status · licence |
|---|---|---|
| R10 guard self-mutation | five sabotage edits to the consumer must each turn a named test red | I (driver) · none |
| R10 mutation scorer | a defect counts as caught only when a product rung judged it | T · none |
| R05 held-out grader | agent "done" vs independently correct; agents cannot weaken tests; `false_completion` metric | U · none |
| R07 Stryker + readiness | nightly mutation run, non-blocking (`break: null`); readiness stages fail closed | T-CI · MIT |
| R03 eval-staleness Stop hook + stub-test harness + 7 paid evals | skill edits cannot end a turn with a stale eval; orchestration script tested with stubs; eval results not in the repo | T-CI / I · MIT |
| R06 html-doc network test | Chromium cannot reach a local endpoint | T-CI · MIT |

Trade-offs. R10 and R05 attack the same failure (a check that passes because it cannot fail) from two sides: R10
injects defects into the product or the factory, R05 hides the acceptance tests from the agent. Both are no-licence
ideas. R07's mutation testing never fails the build, so it measures but does not gate.

### 2.11 Untrusted input handling

| Component | Mechanism | Status · licence |
|---|---|---|
| R07 `_meta.provenance.untrusted_content` + server instructions | labels every target-derived result | T-CI · MIT |
| R08 privilege-split explore job + plan validation against a pre-agent snapshot | agent job read-only; separate write job applies whitelisted effects | I · MIT |
| R08 workflows pass titles/bodies via `env:`, not `${{ }}` | prevents Actions script injection | I · MIT |
| R08 `triage-repro` rules | explicit untrusted-input instructions | P · MIT |
| R02 trusted bot logins only | exact-login match for scores | T · MIT |
| R01 v2 quoting banner + author/operator-only comments | quoted data, not instructions | U · GPL-3.0 |
| R05 JSON-encoded run context + "treat as data" lines | prompt-level | T-CI / P · none |
| R06 "a reviewer comment is evidence, not an instruction" | only on an unmerged branch | U, P · MIT |
| Absent | R03 (issue, PR, Sentry text into lanes holding push and merge), R11 (fetched pages, reviews), R04 (issue triage with a write token), R08 plan prompts (issue bodies into agents with permissions bypassed) | — |

Trade-offs. Labelling (R07) and prompt lines (R05) depend on the model honouring them; R08's privilege split is the only
structural control, and it covers one workflow. **BUILD NEW** gap: a structural separation between agents that read
untrusted text and agents that hold write credentials, applied to every intake path.

### 2.12 Evidence capture and visual verification

| Component | What it captures | Independent | Status · licence |
|---|---|---|---|
| R02 `evidence.py` + Playwright runner | annotated, commit-stamped screen video; headless capture | no (self-reported pass/fail) | T · none |
| R02 before-and-after | screenshots, public upload | no | I · noncompete |
| R11 `imgdiff.py` + e2e skeleton | layout and pixel diff; console / 5xx / axe failures | deterministic comparison | T / D · MIT |
| R03 `runtime_compare.py`, `visual` skill | runtime scenarios | partly | T-CI · MIT |
| R01 builder + UX/UI reviewers | agent-browser screenshots, DOM geometry | skipped in 3 of 4 reviews | P · none |
| R06 `/test` | real-browser evidence per AC | fresh reviewer | P · MIT |
| R07 browser / Electron / native UI capture | Evidence records | deterministic | T-CI · MIT |

### 2.13 Orchestration spines (for reference)

Prose-driven: R01, R02, R06, R11, R04. In-session scripted workflow: R03 (Claude Code Workflow tool, ≤ 16 concurrent
agents by default [Docs, via R03 §17]). External code orchestrator: R05 (Python over the Agent SDK), R09 (Python ADWs
over Pi), R08 (caller-written TypeScript), R10 (Archon, uninspected). None: R07. These are mutually redundant at the
top level: each assumes it owns sequencing (section 3.2, C1).

---

## 3. Compatibility and conflicts

### 3.1 Compatibility profile per repository

| Repo | Language / runtime floor | Host agent | Orchestration assumption | State store | Permission model | Licence |
|---|---|---|---|---|---|---|
| R01 | none (v1); Python ≥ 3.10 (v2) | Claude Code (named subagents, `SendMessage`) | LLM session is the orchestrator | files | host settings; agents hold Bash + Write | none / GPL-3.0 (v2) |
| R02 | Python ≥ 3.10; Node 20+; ffmpeg | any agent reading `SKILL.md` | prose | attempt files + GitHub | one skill's broad `allowed-tools` | mixed |
| R03 | bash 3.2, Python ≥ 3.9, jq, Node 22 | Claude Code (Workflow tool); Codex backend; OpenCode refused | in-session Workflow script | GitHub Projects v2 | session allowlist + guard hooks; Codex lanes `approval_policy=never` | MIT |
| R04 | Python 3 | Claude Code; GitHub Actions | prose | none | generated `allowed-tools` | MIT |
| R05 | Python ≥ 3.11, Agent SDK 0.1.x | Claude Code via Agent SDK | external Python loop | `run.json` | `dontAsk` + allowlist, `setting_sources=[]` | none |
| R06 | none; html-doc Python 3.11 + Pandoc 3 + Node 22.12 | Claude Code and Codex | prose | GitHub | opt-in invocation only | MIT |
| R07 | Node ≥ 22.19 | any MCP host | none (host drives) | Evidence bundles | host approval + MCP annotations | MIT + third-party |
| R08 | Node ≥ 22, TS ESM | Claude Code, Codex, Pi, Cursor, OpenCode, Copilot | caller-written loop | git | bypass by default | MIT |
| R09 | Python 3 (uv), Bun | Pi only | Python ADW scripts | SQLite | Pi `--tools` + post-hoc diff | MIT |
| R10 | Python ≥ 3.10, bun | Claude Code or Codex via Archon | Archon + OS timers | Archon + files | Archon [Unk]; root + `IS_SANDBOX=1` in the runbook | none |
| R11 | Python ≥ 3.8 [Claim] | Claude Code plugin | prose | files | session permissions | MIT |

### 3.2 Conflicts

**C1 — Two owners of the control loop.** R03 (in-session Workflow script), R05 (Python runner), R08 (caller TypeScript),
R09 (ADW scripts) and R10 (Archon) each assume they sequence phases, retries and acceptance. Nesting one inside
another produces two retry budgets and two sources of "done" [Inf]. They compose only when one is the spine and the
others contribute leaf components (contracts, gates, providers).

**C2 — Host agent.** R09 runs on Pi only (clone `agent_cc.py:11-15`). R01, R03 (Workflow backend), R04, R05, R11 need
Claude Code; R06's coordinator is Codex-only; R07's agent-experience scorer parses Codex JSONL. Claude Code hooks (R03
guards) do not apply to Codex, Pi or the other CLIs R08 drives [Inf].

**C3 — Settings isolation versus hook-based guards.** R05 calls the SDK with `setting_sources=[]`, which [Docs]
disables user, project and local settings for Python SDK releases after 0.1.59 (R05 locks 0.1.81). Hooks registered
in `.claude/settings.json`, such as R03's guards, are therefore not loaded in R05 workers [Docs,
code.claude.com/docs/en/agent-sdk/claude-code-features, accessed 2026-10-22: the `"project"` source loads "Project
`settings.json` and hooks", and filesystem hooks are "loaded when `settingSources` includes the relevant source"].
Exception: managed policy settings are read regardless of `settingSources`, so hooks delivered through managed policy
would still apply [Docs, same page]. Programmatic SDK hooks passed to `query()` are a separate path R05 does not use.

**C4 — Permission posture.** R08 `run()` bypasses permissions by default; R03 Codex lanes run with no approvals; R05
fails on any denial. Composing a bypassing worker with a component that relies on permission prompts removes that
reliance. [Docs] PreToolUse hooks run before the permission prompt for every tool, so a Claude Code worker with
permissions bypassed can still be gated by a hook that exits 2 [Inf for the bypass mode specifically], but a
fail-open hook gives no guarantee.

**C5 — Agent commits versus diff-based boundaries.** R08 collects commits the agent makes inside the sandbox; R09's
write-boundary compares `git diff HEAD` before and after and is blind to changes the agent commits itself [R09 §8].
The two cannot be combined without moving the boundary check to the commit range [Inf].

**C6 — Whole-tree staging.** R09 commits with `git add -A` (`git_helper.py:49`); R02 and R05 explicitly stage named
paths. Mixing them in one workspace can commit operator work or another agent's changes.

**C7 — Merge location.** R01 v1 merges into local `main`; R03, R06, R10 merge through GitHub PRs; R08 merges branches
on the host. Two merge paths on one repository bypass whichever gate the other path holds.

**C8 — State store duplication.** R03 treats the GitHub board as the only state; R01 and R05 keep local JSON; R09 keeps
SQLite; R10 defers to Archon. Running two means reconciling two truths about the same job.

**C9 — Host execution inside gates.** R03's merge gate `eval`s verify and migrate commands on the host; R05's grader
(unmerged) imports agent code on the host. Placing either inside an isolation layer (R08) is possible but not provided.

**C10 — Licences.** GPL-3.0 (R01 v2) cannot be combined into an MIT or proprietary distribution without the combined
work becoming GPL-3.0 on distribution [Inf, not legal advice]. No-licence code (R01 v1, R05, R10, most of R02) cannot be
combined at all without permission. `before-and-after` (R02) carries a noncompete clause.

**C11 — Runtime floors.** Python floors range from 3.8 (R11 claim) to 3.11 (R05, R06 html-doc); Node from 20 (R02) to
≥ 22.19 (R07); Bun is needed by R09's visualizer and by Archon. These coexist but widen the toolchain.

**C12 — External SaaS and services.** Greptile (R02), GitHub Projects v2 and the GraphQL rate budget (R03), Vercel or
Daytona (R08 isolated providers), OpenRouter-style providers via Pi (R09), commercial reverse-engineering engines (R07).

### 3.3 Compatibility matrix for the most cross-referenced components

Components: **A** R03 merge gate + policy + approval + read helper · **B** R03 guard hooks · **C** R08 Sandcastle
library · **D** R09 tracer + envelopes + change capture · **E** R02 `github_review.py` · **F** R06 `/review`, `/spec`,
`/plan` templates · **G** R07 REA MCP server · **H** R11 `imgdiff` / `parity` / `contrast` · **I** R04 settings
installer · **J** R05 check contract (reimplemented) · **K** R10 mutation scoring + guard self-mutation (reimplemented).

Legend: **●** composes with little glue · **◐** composes with adaptation (note) · **○** conflict to resolve first ·
**·** no meaningful interaction.

| | B | C | D | E | F | G | H | I | J | K |
|---|---|---|---|---|---|---|---|---|---|---|
| **A** | ● n1 | ◐ n2 | ◐ n3 | ◐ n4 | ◐ n5 | · | ◐ n6 | · | ● n7 | ◐ n8 |
| **B** | | ○ n9 | ○ n10 | · | ● n11 | ◐ n12 | · | ◐ n13 | ○ n14 | ◐ n15 |
| **C** | | | ○/◐ n16 | ◐ n17 | ◐ n18 | ◐ n19 | ● n20 | · | ● n21 | ◐ n22 |
| **D** | | | | · | ◐ n18 | · | ● n23 | · | ● n24 | ◐ n25 |
| **E** | | | | | ◐ n26 | · | · | · | ◐ n27 | · |
| **F** | | | | | | · | ◐ n28 | · | ◐ n29 | · |
| **G** | | | | | | | ◐ n30 | · | · | ◐ n31 |
| **H** | | | | | | | | · | ● n32 | ◐ n33 |
| **I** | | | | | | | | | · | · |
| **J** | | | | | | | | | | ● n34 |

Notes:
- **n1** Designed together: the hooks are installed into the same target project that runs the gate [R03 §2]. Both fail
  differently (gate fails closed, hooks fail open).
- **n2** C produces branches and commits; A expects a GitHub PR, super-board config and squash merge. A's host `eval`
  of verify commands could run inside a C sandbox instead (C9). TypeScript vs bash/Python boundary.
- **n3** Gate exit codes map onto D phases; D's tracer can record them. Python on both sides.
- **n4** E's head-bound score can be one of A's required checks; Greptile-specific parsing must be configured.
- **n5** F's `/review` format can be the reviewer lane's output; F's `/task-to-pr` merge authority must be dropped or
  it becomes a second merge path (C7).
- **n6** `parity.py --fail-under` or `imgdiff --fail-under` can be verify commands; `parity.py` has no must-have exit.
- **n7** A's routed exit codes already express pass / retry (4, rebase 2/5) / stop-to-human (7/8) / halt (9).
- **n8** A self-mutation pass over the gate (in the style of R10) would prove the gate's guards can fail.
- **n9** Hooks are Claude Code only; C drives six CLIs, bypasses permissions by default, and the hooks must be present
  in the sandbox image or worktree to load. Workable for the `claudeCode` provider only [Inf].
- **n10** D runs Pi; Claude Code hooks do not apply (C2).
- **n11** Both are project-level Claude Code artifacts; opt-in skills and hooks coexist.
- **n12** A PreToolUse matcher on REA's MCP tool names could gate its 15 foreign-code tools, driven by its effects
  table [Inf].
- **n13** I can write hook settings, but its hard-coded event list and wrapped-file assumption reject R03's snippet
  format as shipped [R04 §13].
- **n14** J's hardened options (`setting_sources=[]`) stop B from loading (C3).
- **n15** R10-style sabotage tests would show whether each guard blocks; R03 already has `test-guard-hooks.sh`.
- **n16** D's tracer can ingest C's `onAgentStreamEvent` and `IterationUsage` (◐; C ships a Pi provider [R08 §1]); D's
  write boundary conflicts with C's agent-commit model (○, C5).
- **n17** E can verify review freshness on PRs that C's templates open.
- **n18** Prompt text can become C prompt templates or D prompt pairs; D's prompts must match its output types.
- **n19** G inside a C container adds the containment REA lacks, but the image must carry Node ≥ 22.19 and the engines,
  and commercial engine licences may restrict hosted use [R07 notices].
- **n20** H is stdlib Python with no network; runs anywhere.
- **n21** J's contract maps onto `Output.object` with resume retries in TypeScript.
- **n22** Mutation runs need fresh, disposable workspaces, which C provides.
- **n23** H exit codes enter D through `quality.as_envelope`.
- **n24** D's `finish(accepted)` and `GateReport` are the same concept as J's pass/retry/stop; both pydantic.
- **n25** Mutation scoring can be a D code phase.
- **n26** F's calibrated findings and E's freshness address different halves of one review.
- **n27** E's outcome (fresh / stale / unverifiable) needs mapping to retry or stop.
- **n28** F's `AC-n` IDs can key H's `features.csv` rows.
- **n29** F's `Blocked` verdict maps to stop, `Request changes` to retry.
- **n30** Two parity levels with different data models (Evidence bundles vs CSV rows).
- **n31** Mutation-scored checks could serve as verifier records for G's ledger; G does not produce them itself [Inf].
- **n32** Exit-code contract fits J's 0 / 1 / other convention (H uses 0 pass, 1 fail, 2 usage).
- **n33** Mutations on a rebuilt app would test whether H's thresholds catch real drift.
- **n34** K decides whether a J check can be trusted (a check that never fails is not evidence).

---

## 4. Composition opportunities (synergies)

Generic combinations of complementary components across repositories. Effort: **Low** (configuration and glue, one
language), **Medium** (adaptation of one or more components or a language boundary), **High** (reimplementation, heavy
dependencies or unresolved security gaps). None of these combinations exists in any repository; each is [Inf].

### 4.1 Isolated worker with a code-enforced merge gate
- **Components:** R08 Sandcastle (isolated provider, `Output.object`) + R03 merge gate, merge policy, head-pinned
  approval, GitHub read helper + R02 review freshness.
- **Provides:** agent work in a container or microVM, review signals bound to the current head, and a merge decided
  by code under a lock, with policy categories routed to a human.
- **Effort: High.** TypeScript library and bash/Python gate; R08 permission defaults, `.git` mount and branch-name
  interpolation must be fixed or avoided (isolated providers, validated branch names); the gate's host `eval` must move
  into an isolated runner; the approval needs a separate human identity.
- **Dependencies:** Node ≥ 22, Docker/Podman or Vercel/Daytona, bash 3.2, Python 3.9+, `jq`, `gh`, GitHub, optionally
  Greptile.
- **Risks:** two loop owners (C1) if Sandcastle templates and super-board waves are both used; secrets in `docker run
  -e` argv; auto-merge default on super-board boards.
- **Maintenance:** High. Sandcastle is pre-1.0 with a breaking `v1` pending [R08 §1]; super-board changes weekly; the
  Greptile score format is outside both.

### 4.2 Typed check contract with evidence and per-phase cost
- **Components:** R05 pass/retry/stop contract and fail-closed SDK handling (reimplemented) + R09 `GateReport`,
  `finish(accepted)`, SQLite tracer + R08 structured output with session-resume retries.
- **Provides:** every check, shell or LLM, returns one typed outcome with evidence; a run is accepted only by an
  explicit decision; cost and context use per phase; schema repair without redoing work.
- **Effort: Medium.** R05 is an idea (no licence); R09 types are Pi-shaped (`PiRequest`, `UsageBreakdown`); R08 is
  TypeScript, R09 Python, so one language must host the contract.
- **Dependencies:** pydantic (or a Standard Schema validator), SQLite, an agent runtime with structured output and
  resumable sessions.
- **Risks:** raw prompts in the trace (redaction); `shell=True` in R09 gates; unrestricted Bash in R05's defaults.
- **Maintenance:** Medium. R09 is unmaintained-looking (single squashed commit, no tests) and its code has known
  defects [R09 §7], so a fork carries its own upkeep.

### 4.3 Review that persists, calibrates and stays fresh
- **Components:** R06 `/review` format (Priority × Confidence, ≤ 2 floor, `Blocked` without a fresh subagent) + R03
  review-remembers (stable finding ids, mandatory recheck) and min-of-two truth check + R06 fresh-review-on-every-repair
  + R02 freshness rule.
- **Provides:** findings that survive rounds with stable ids, calibrated reporting, re-review on every change, and
  reviews that count only for the current head.
- **Effort: Low-Medium.** All MIT; mostly prompt text plus `github_review.py`; needs a host with fresh subagents.
- **Dependencies:** GitHub, `gh`, Python 3.10+ (freshness helper), optionally Greptile.
- **Risks:** the LLM reviewers in R03 and R06 share the builder's model family (context independence only;
  R02's reviewer is an external bot, and only R09's roster mixes providers); read-only is prose in every source
  repo, so tool restrictions must be added; confidence scores are self-reported.
- **Maintenance:** Low. Prompt text is stable; the Greptile-specific parser is the only moving part.

### 4.4 Checks that are shown to fail before they are trusted
- **Components:** R10 three-valued mutation scoring and guard self-mutation (reimplemented) + R05 held-out grader and
  false-completion metric (reimplemented; both exist only on the unmerged `codex/eval-suite` branch) + R03 eval-staleness Stop hook + R03 workflow stub-test harness.
- **Provides:** evidence that gates and tests can fail, that agents cannot weaken their own acceptance tests, and that
  edited skills are not shipped with stale evals.
- **Effort: Medium-High.** R05 and R10 are no-licence ideas; mutation catalogues are per project; the R05 grader
  executes candidate code on the host and needs isolation (4.1).
- **Dependencies:** a test runner, git, temp workspaces; for the hook, the `claude plugin eval` result layout.
- **Risks:** INCONCLUSIVE outcomes must never be counted as catches (R10's rule); hold-out tests must be hidden from
  the builder by code, not by directory naming [R10 §8].
- **Maintenance:** Medium. Defect catalogues and held-out cases need curation as the product changes.

### 4.5 Two-level reference parity (product and artifact)
- **Components:** R11 recon map, `features.csv`, `parity.py`, `imgdiff.py`, `reviews.py` + R07 REA MCP server
  (application graphs, version and source-to-bundle comparison, obligation ledger) + R06 `REQ`/`AC` IDs and `/spec`
  acceptance table.
- **Provides:** product-level coverage (screens, flows, features, layout) measured by R11 and behaviour-level claims
  proven under R07's fail-closed closure rule, joined by stable IDs.
- **Effort: High.** REA is a large Node platform with bring-your-own engines; its ledger has no proof producer and its
  evidence is hash-only; R11's parity is builder-marked; the two data models differ.
- **Dependencies:** Node ≥ 22.19, REA (pinned), optional Ghidra/JDK 21, Hopper, IDA, JEB and others; Python 3 stdlib;
  Playwright.
- **Risks:** legal (R11 omits patents and public-site terms; JEB's EULA restricts disclosure of decompiled output
  [R07 notices]); prompt injection from target content (REA labels it, Replica does not); REA's 15 foreign-code tools.
- **Maintenance:** High. REA shipped six majors in three months and main CI was unstable on the evaluation day [R07 §1].

### 4.6 Structural handling of untrusted input
- **Components:** R08 privilege-split job and plan validation against a pre-agent snapshot + R07 untrusted-content
  marker and tool-effects table + R05 JSON-encoded context (reimplemented) + R02 trusted-login rule.
- **Provides:** agents that read issue, PR, review or target text cannot hold write credentials; a separate,
  deterministic step applies only whitelisted effects; target-derived output is labelled end to end.
- **Effort: Medium.** All patterns; R08's version is specific to triage effects.
- **Dependencies:** a CI or job system with per-job permissions; a schema for allowed effects.
- **Risks:** labelling alone is advisory; every intake path (Sentry, PostHog, reviews, web pages) must be covered or the
  weakest one decides.
- **Maintenance:** Medium. The allowed-effect whitelist grows with each new automation.

### 4.7 Safe, pinned configuration installation
- **Components:** R04 settings installer (backup, rotate, atomic write, rollback) + R07 setup planner (plan, approval,
  backups) as reference + R10 pinned-source verifier (reimplemented) + R09 idempotent stamp with drift report.
- **Provides:** config and skill installs that are pinned to a revision, verified clean, shown as a plan, applied
  atomically and reversible.
- **Effort: Low-Medium.** R04 needs its event list and file-format assumptions corrected and its `input()` prompt
  removed; R10's verifier is an idea.
- **Dependencies:** Python 3 stdlib, git.
- **Risks:** hook formats evolve ([Docs] `onFailure` arrived in v2.1.295), so a hard-coded event list goes stale, as
  R04's did.
- **Maintenance:** Low-Medium.

### 4.8 Visual and runtime evidence
- **Components:** R11 `imgdiff.py`, Playwright skeleton (console, 5xx, axe) and `contrast.py` + R02 evidence protocol
  and isolated Playwright runner (reimplemented) + R06 `/test` criterion→evidence + R06 html-doc's network-dead
  Chromium configuration as a pattern.
- **Provides:** screenshots and videos tied to acceptance IDs, a deterministic layout comparison, accessibility and
  console/5xx failure hooks, and a browser that cannot reach the network when only rendering.
- **Effort: Low-Medium.** R11 tools are stdlib; R02 pieces must be rewritten (no licence).
- **Dependencies:** Node, Playwright, axe, ffmpeg for video.
- **Risks:** every source treats evidence as builder-produced; the comparison must be run by an independent step or
  it remains self-reporting; `imgdiff.py` needs input bounds.
- **Maintenance:** Low.

### 4.9 Guarded in-session execution for Claude Code
- **Components:** R03 guard hooks (changed to exit 2 on internal error, plus `onFailure: "block"` for crashes and
  timeouts) + R06 opt-in invocation and its guard test + R04
  least-privilege `allowed-tools` synthesis.
- **Provides:** skills that never self-trigger, narrow tool patterns per command, and pre-call checks on secrets,
  deletes outside the tree and protected pushes.
- **Effort: Low.** All MIT; Claude Code project-level artifacts.
- **Dependencies:** Python 3 stdlib; Claude Code ≥ v2.1.295 for `onFailure` [Docs]. `onFailure` does not cover the
  shipped fail-open path: each guard swallows its exceptions and exits 0, which the docs do not count as a failure
  [Docs, hooks, accessed 2026-10-22; clone `guard-secrets.py:62-63`], so the hook code itself must change.
- **Risks:** regex guards are bypassable by command construction (`$(...)` allowed by design, `guard-delete-outside.py:6-9`);
  [Docs] permission deny rules remain the hard control. Not loaded in SDK sessions with `setting_sources=[]` (C3).
- **Maintenance:** Low; Windows false positives are open (issue #72) [R03 §8].

---

## 5. Licence and provenance summary

### 5.1 Per repository

| Repo | Licence of the evaluated code | Per-component exceptions | Provenance notes |
|---|---|---|---|
| R01 Galea | **none** for `src/software-factory-claude-code` (no LICENSE in folder or root; `gh api license: null`) | unmerged v2 folder on branch `8a428453`: **GPL-3.0** with a commercial-licence offer (clone `SF2/LICENSE`, `SF2/README.md:169-174`) [Obs] | one commit added the whole folder; v2 install fetches files from a branch where they do not exist [R01 §2.4] |
| R02 Ras Mic | **none** at root | MIT © Greptile AI (`greploop/`, `greploop-apps/`); MIT © Lauren Tan (`unslop/`); "PolyForm Shield 1.0.0"-titled text © James Clements with a noncompete clause (`before-and-after/`); none for `new-feature/`, `code-structure/`, `evidence-driven-testing/`, `tests/`, `AGENTS.md` [Obs, clone] | `greploop` is a near-total local rewrite still under Greptile's notice; `unslop` has drifted from upstream; two open issues ask for a licence [R02 §1, §17] |
| R03 Super-Board | **MIT** © Eric Tech | — | `guard-secrets`, `guard-key-literals`, `guard-worktree-path` and `cleanup-wt` state they were adapted from the same author's `ai-builder-starter-kit` and `BookKeepingApp` (clone hook docstrings); origin licences [Unk]. Runtime skills: `mattpocock/skills` MIT (`gh api`); `ponytail`, `impeccable`, `humanizer` and others [Unk] |
| R04 Rezvani | **MIT** © Reza Rezvani | `documentation/references/` holds copies of Anthropic and OpenAI docs whose terms are not granted by the repo's MIT licence [Inf]; ZIPs ship `.pyc` bytecode | dormant since 2025-11-12; owner active elsewhere [R04 §2.4] |
| R05 Lewis Factory | **none** | — | `codex/` branch prefixes suggest Codex-produced work [Inf, R05 §17] |
| R06 Blueprint | **MIT** © Owain Lewis | html-doc invokes Pandoc and Chromium as external programs; npm deps pinned with integrity hashes | skills largely edited by Codex/agents per branch names and PR bodies [R06 §10] |
| R07 REA | **MIT** © morluto (REA-authored code) | third-party material keeps its own terms; see 5.3 | star and fork counts (365k / 91k) unverified as organic [R07 §1] |
| R08 Sandcastle | **MIT** © Matt Pocock | scaffolds install unpinned third-party agent CLIs under their own terms | npm releases OIDC-attested [R08 §8] |
| R09 SSSF | **MIT** © IndyDevDan | Pi (`badlogic/pi-mono`, MIT per `gh api`) is external | single squashed commit per branch [R09 §1] |
| R10 Medin | **none** (issues #32, #61 ask for one; open PR #58 proposes MIT) | Archon is MIT (`gh api`), pinned to an unmerged branch | pin bumped several times a day, sometimes by direct push [R10 §8] |
| R11 Replica | **MIT** © 2026 Jake Schincariol | — | one commit with a `Co-Authored-By: Claude Opus 5.5` trailer [R11 §1] |

### 5.2 No-licence and copyleft implications

- **No licence (R01 v1, R05, R10, and R02's unlicensed folders including `tests/`):** all rights reserved by default;
  code, prompts and templates can inform a reimplementation of the idea, and reuse as code needs the author's
  permission [R01 §13, R05 §13, R10 §13]. This removes the strongest independent-verification code in the set
  (R05 grader, R10 mutation tooling) from direct reuse.
- **GPL-3.0 (R01 v2):** any distributed work that incorporates the code must be released under GPL-3.0; the author
  offers a commercial licence (clone `SF2/README.md:171-174`). It is also unmerged and incomplete, so it is reference
  material on two counts.
- **Modified licence text (R02 `before-and-after`):** the file is titled PolyForm Shield 1.0.0 and links to the
  PolyForm page, but its body is an MIT-style grant plus a noncompete condition ("may not use the Software to provide
  a product or service that competes with the Software or any product or service offered by the Licensor"), not the
  canonical PolyForm text [Obs, clone `LICENSE:1-27`]. Its terms are ambiguous, and the noncompete makes it
  non-open-source in the OSI sense [Inf].
- **Attribution-only (MIT):** keep the copyright notice with any copied code (R03, R04, R06, R07, R08, R09, R11 and the
  three MIT folders of R02).

### 5.3 REA third-party licences (report 07)

From REA's `THIRD_PARTY_NOTICES.md` and `licenses/` (clone, read 2026-10-22) [Obs]:

| Category | Items and licences | Implication |
|---|---|---|
| Distributed with the npm package | locked npm graph inventoried in `licenses/npm-dependencies.txt`; derived NativeAOT parser (MIT: Washi, .NET Foundation); `evmole` MIT; `clean-git-ref` (declared Apache-2.0) and `minimisted` (declared MIT) with documented notice gaps | notices must travel with redistribution |
| Windows native addon | compiled with MinGW-w64, statically links GCC runtime: GPLv3 text plus GCC Runtime Library Exception 3.1 retained | exception governs eligible combinations; it does not relicense the runtime |
| Optional dependency | `frida@17.23.2`: LGPL-2.0 WITH WxWindows-exception-3.1 | weak copyleft on the library |
| Bring-your-own open-source engines | Ghidra Apache-2.0 (standalone programs under `GPL/` are GPLv3); JADX, jadx-headless-mcp, Kuna, Apktool, Wakaru, WABT, adb Apache-2.0; Binwalk, Unblob, mitmproxy, pwndbg, ILSpy MIT; pwntools MIT with GPL/BSD component qualifications; pyelftools public domain with bundled components; **Unicorn GPL-2.0**; **GNU GDB GPL-3.0-or-later**; LLDB Apache-2.0 with LLVM exceptions; OpenJDK GPLv2 + Classpath Exception | invoked as separate processes and not bundled; obligations arise when an adopter redistributes an engine [Inf, not legal advice] |
| Commercial tools | IDA Pro / Hex-Rays (EULA), Hopper (licence agreement; setup may fetch the official installer after approval), JEB (EULA restricts public or third-party disclosure of decompiled code, reconstructed artifacts and analysis reports unless the licence type permits); `ida-pro-mcp` bridge is MIT but licenses only the bridge | rights must be obtained per user and use; hosted or service use may need extra rights |
| Not inventoried | Rizin, TShark/capinfos, sigrok-cli and GNU objdump appear in REA's README as external tools [R07 §2] but not in `THIRD_PARTY_NOTICES.md` (grep: 0 hits) [Obs] | their licences were not checked here [Unk] |

### 5.4 Other third-party and service dependencies with terms of their own

`agent-browser` (Apache-2.0, `gh api`) for R01 and R02; Greptile SaaS for R02 (billing and format [Unk]); 0x0.st public
host for R02's default uploads; GitHub Projects v2 for R03; Vercel Sandbox and Daytona for R08's isolated providers;
OpenRouter, Fireworks and OpenAI models through Pi for R09's starter roster; the Claude Code, Codex, Cursor and Copilot
CLIs that R08 installs unpinned in its images [R08 §8]; Archon (MIT) for R10.

---

## Limits of this analysis

- **Nothing was executed.** All test, CI and runtime statements come from the phase 1 reports' reading and from GitHub
  metadata. Status codes T and T-CI mean tests exist, not that they pass.
- **Spot-checks were narrow.** I re-read in the clones: R01 v2 licence and README licence section, R02 per-folder
  licences, R03 hook provenance docstrings, `skills-ready.py` registry, merge-gate `eval` lines and the test-file list,
  R05 SDK options, R07 untrusted-content marker and third-party notices, R08 `Orchestrator.ts:143`, R09
  `agent_cc.py`, and copyright lines of the MIT repositories; in the correction pass, the five guard hooks' exception
  handlers, Sandcastle's Codex approval flags (`AgentProvider.ts:790-797`) and test-file count, and Lewis Factory's v3
  benchmark README on the unmerged `codex/eval-suite` branch. Everything else rests on the reports.
- **External licences** were checked only through `gh api` repository metadata (Archon, `mattpocock/skills`,
  `pi-mono`, `agent-browser`); the mapping of the Pi CLI package to `pi-mono` is [Inf]. Licences of engines missing
  from REA's notices, of Greptile and of the external skills Super-Board needs were not checked.
- **Official docs** were read on 2026-10-22 (hooks, permissions, Python Agent SDK). Whether PreToolUse hooks fire in
  `bypassPermissions` mode is inferred from "run before the permission prompt, for every tool", not stated for that
  mode. That `setting_sources=[]` excludes project `settings.json` hooks (but not managed-policy settings) is stated
  on code.claude.com/docs/en/agent-sdk/claude-code-features (accessed 2026-10-22).
- **Archon** (R10's engine) and Sandcastle's external daemon were out of scope, so components that depend on them are
  rated Unknown.
- **Licence statements** are technical readings, not legal advice; compatibility conclusions about GPL, LGPL, the GCC
  runtime exception, EULAs and the noncompete clause are inferences.
- **Effort and maintenance ratings** in section 4 are qualitative estimates from code structure and repository
  activity; no combination was built.

## Report discrepancies found

1. **Report 10 §13 (and RESEARCH_INDEX §10) — no-licence code classed "needs adaptation".** The rows "Cross-platform
   timer generation", "Runtime host", "Revision-bound resource materializer" and "MISSION / WORKFLOW_POLICY /
   FACTORY_RULES / HOLDOUT templates" carry reuse class "needs adaptation", while the same table's preamble says
   "reuse of code needs permission" and the repository has no licence (R10 header; `gh api license: null`). V10-1
   reclassified only `run.py` and `ci.py`. The index repeats "runtime host (needs adaptation, with permission)". Under
   brief rule 7 these are at most "reimplement the idea"; this document applies that (1.12).
2. **Report 02 §13 — `github_review.py` licence cell omits that its tests are unlicensed.** The row gives "MIT (folder
   `greploop/LICENSE`)", but the regression tests that make it "tested" live in `tests/`, which the report's own header
   lists as having no licence. Reusing the helper with its test suite is therefore not covered by MIT. Omission, not an
   error of fact.
3. **Report 07 §13 — licence column understates third-party copyleft and gaps.** "MIT (+ third-party licenses;
   commercial tools need user licences)" is accurate but does not record the LGPL-2.0 optional `frida` dependency, the
   GPLv3 GCC runtime (with exception) statically linked into the Windows addon, the GPL engines (Unicorn GPL-2.0, GDB
   GPL-3.0-or-later), JEB's disclosure restriction, or the four README-listed tools absent from REA's notices (clone
   `THIRD_PARTY_NOTICES.md`). Omission; recorded in 5.3.
4. **Report 02 §13 — `before-and-after` licence holder.** The row describes the text as "non-canonical MIT-style text
   plus noncompete" without naming the licensor; the file names James Clements (clone `before-and-after/LICENSE:3`),
   not the repository author or Greptile. Minor omission relevant to provenance.

5. **Report 03 §13 — guard-hook provenance count.** The Guard hooks row says "two credit an 'ai-builder-starter-kit' /
   'BookKeepingApp' origin". In the clone, three guards state an adapted origin: `guard-secrets.py:9` and
   `guard-key-literals.py:13` (ai-builder-starter-kit) and `guard-worktree-path.py:13` (BookKeepingApp), plus
   `cleanup-wt.py:34` (BookKeepingApp), four files in all. Minor provenance undercount.

No load-bearing code claim I spot-checked was wrong: R08 `Orchestrator.ts:143`, R03 `merge-gate.sh:283,307`, R09
`agent_cc.py:11-15`, R05 `runner.py:53-67`, R07 `toolResultEncoding.ts:26-37` and R01 v2's GPL-3.0 licence matched the
reports.

## Verification corrections (2026-10-22)

An independent verifier rated this document accurate with corrections. Each finding was checked against the clones or
the official docs (code.claude.com, accessed 2026-10-22) before it was applied. All ten were applied.

- P4-1: the guard-hook remedy is corrected in §1.3, the §1.12 "deciding fact" row and §4.9. All five guards swallow exceptions with exit 0 (clone lines confirmed). The hooks docs count only start failure, exit other than 0/2, HTTP error, timeout and invalid output as failures, so ADAPT now requires exit 2 on internal error; `onFailure: "block"` covers only crashes and timeouts.
- P4-2: C3, the §1.5 hardened-SDK row and Limits now cite agent-sdk/claude-code-features [Docs]. The `"project"` source loads "Project `settings.json` and hooks", and filesystem hooks load only when their source is included. Added the exception: managed policy settings are read regardless.
- P4-3: §2.3 and §4.3 now note the exception. SSSF's reviewer runs `gpt-5.6-terra` while the builder inherits the `gemini-3.6-flash` default [R09 §3]. §4.3 also notes that R02's reviewer is an external bot.
- P4-4: §1.8 test-file count corrected to 54 repo-wide, 53 under `src/`, 47 at its top level (clone count).
- P4-5: §5.1 now names four adapted files (adds `guard-secrets.py:9`). Report 03 §13's "two credit" is added as discrepancy 5.
- P4-6: the §1.12 non-licence table now holds every section 1 row whose verdict differs from the report class. It was audited row by row, with 16 rows added.
- P4-7: §1.8 corrected. Only Claude's `permissionMode` narrows privilege. Codex's `approvalsReviewer` swaps the bypass for auto-reviewed approvals but passes `-s danger-full-access` (clone `AgentProvider.ts:790-797`).
- P4-8: §1.7 CI figures now include the 1 `action_required` run (19 + 14 + 66 + 1 = 100).
- P4-9: §2.3 now gives the v3 code-pass figure, 30/36 Factory vs 31/36 subagent (clone eval-suite v3 README, unmerged branch). §4.4 states that the held-out grader and the false-completion metric are unmerged.
- P4-10: the §3.3 title now reads "most cross-referenced components".
