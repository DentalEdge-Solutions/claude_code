# Research index: Individual Repository Deep Dives (11 repositories)

> **Date:** 2026-10-22 · **Phase:** 1 of 3 (Individual Repository Deep Dives). Phase 2 is Comparative
> Architecture Intelligence; phase 3 is Consolidated Optimization Strategy.
> **Framework:** the owner's Software Factory value definition (active decision
> `.project-brain/decisions/active/2026-10-22-software-factory-value-definition-the-yardstick-for-the-eval.md`;
> verbatim text in `.project-brain/support/sources/software-factory-value-definition-2026-10-22.md`).
> **Scope rule for this phase:** independent research. No changes to `claude_code`, no external code installed or
> executed, no project-specific integration recommendations. The reports classify reuse generically.
> **Legend used in the reports:** [F] verified fact · [I] inference · [C] unverified claim · [U] unknown · [F docs] fact from the official Claude Code docs (cited with access date; not executed).

## Method

1. **Sources.** Each repository was shallow-cloned read-only at its default branch on 2026-10-22, with git hooks
   disabled and no submodules or LFS content. Material branches were cloned into separate read-only folders.
   Metadata (licences, releases, issues, PRs, CI runs) came from read-only `gh api` calls. Official Claude Code docs
   (code.claude.com) were consulted where a claim depended on Claude Code behaviour.
2. **No execution.** No repository code, tests, installers, builds or containers were run. Anything that only running
   code could confirm is marked unverified (not executed) in the reports.
3. **Untrusted content.** Repository text was treated as data. Instructions addressed to AI agents were reported, never
   followed. No prompt-injection content aimed at an evaluator was found in any repository.
4. **Research.** 11 researchers worked in parallel, one per repository, under one shared brief with a fixed
   17-section report structure, so the reports can be compared section by section.
5. **Verification.** 4 independent verifiers re-checked each report's header facts and at least 10 of its most
   load-bearing claims (22 for report 07) against the clones and official docs. They raised 39 findings
   (V1-1 … V11-1); a correction pass applied them and found 4 more (C-1 … C-4); the verifiers' closure pass raised 3
   small consistency points (N3-1, N3-2, N10-1), also fixed. Each report's §17 ends with a "Verification corrections
   (2026-10-22)" list. The verifiers re-checked and closed every correction (see
   [Verification record](#verification-record)). Claim counts and closures are from the verifiers' returns to the
   coordinator; the reports record the corrections.
6. **Index review.** An independent reviewer checked this index against the corrected reports (findings I1–I20, all
   applied).

## Repositories at a glance

| # | Repository | Report | Evaluated version | Licence | Category (primary first) | Completeness | Verification verdict |
|---|---|---|---|---|---|---|---|
| 1 | Alexander Galea — Software Factory for Claude Code (`zazencodes/zazencodes-season-3`, folder `src/software-factory-claude-code`) | [01](01-galea-software-factory-claude-code.md) | `6cd82a0` (2026-10-21), main; branch `8a428453` (unmerged v2) | none (v1); GPL-3.0 (v2 branch) | hybrid execution, LLM-driven · skill/agent pack | complete (v1); partial (v2) | accurate with corrections |
| 2 | Ras Mic — Software Factory Skills (`michaelshimeles/skills`) | [02](02-rasmic-software-factory-skills.md) | `69558ea` (2026-10-18), main | mixed: none at root; MIT for 3 skills; modified "PolyForm Shield" text for one | skill/agent pack · spec/planning methodology · verification tooling | complete | accurate with corrections |
| 3 | Eric Tech — Super-Board (`EricTechPro/super-board`) | [03](03-erictech-super-board.md) | `f014cfa` (2026-10-19), main; branch `risk-door-blast-radius` | MIT | board/issue-driven factory · hybrid execution · skill/agent pack | mostly | accurate with corrections |
| 4 | Alireza Rezvani — Skills & Agents Factory (`alirezarezvani/claude-code-skill-factory`) | [04](04-rezvani-skill-factory.md) | `ba18b31` (2025-11-12), default branch `dev` | MIT | skill/agent generator · skill/agent pack | mostly | accurate with corrections |
| 5 | Owain Lewis — Factory (`owainlewis/factory`) | [05](05-lewis-factory.md) | `5b0ff7e` (2026-09-30), main; branches `codex/eval-suite`, `codex/factory-dogfood`, `examples/story-to-code` | none | deterministic orchestration pipeline (minimal hybrid) · example skill pack · eval/benchmark harness (unmerged) | complete (main); mostly (overall) | accurate |
| 6 | Owain Lewis — Blueprint (`owainlewis/blueprint`) | [06](06-lewis-blueprint.md) | `74210b5` (2026-10-12), main; 4 branches | MIT | skill/agent pack · spec/planning methodology | complete | accurate with corrections |
| 7 | Morluto — REA (`morluto/rea`) | [07](07-morluto-rea.md) | `7091be2` (2026-10-22 UTC), main | MIT (third-party tools under their own licences) | reverse-engineering/replication · MCP tool platform · small skill pack | mostly | accurate with corrections |
| 8 | Matt Pocock — Sandcastle (`mattpocock/sandcastle`) | [08](08-pocock-sandcastle.md) | `a53e227` (2026-10-19), main; branch `v1` | MIT | sandbox/isolation runtime · deterministic orchestration (caller-authored) · board/issue-driven factory (its own workflows) · hybrid | mostly | accurate with corrections |
| 9 | IndyDevDan — Super Simple Software Factory (`disler/super-simple-software-factory`) | [09](09-indydevdan-super-simple-software-factory.md) | `de31374` (2026-08-02), main; branch `example` | MIT | deterministic orchestration pipeline · skill/agent pack · minor generator | complete (core); mostly (overall) | accurate with corrections |
| 10 | Cole Medin — AI Software Factory (`coleam00/ai-software-factory`) | [10](10-medin-ai-software-factory.md) | `d2b0fcd` (2026-10-22), main; branch `tested-plus-pins` | none | board/issue-driven factory over the external Archon engine · planning method | mostly | accurate with corrections |
| 11 | Jake Schincariol — Replica Skill (`Jakeschincariol/replica-skill`) | [11](11-schincariol-replica-skill.md) | `77c9436` (2026-10-03), main (only branch) | MIT | reverse-engineering/replication · skill/agent pack · spec/planning | complete | accurate with corrections |

Full commit SHAs, branch heads and access details are in each report's header.

## Key findings and reusable capabilities by repository

Reuse classes are generic: **directly reusable**, **needs adaptation**, **reimplement the idea**, **reference only**.
Code with no licence is never classed directly reusable.

### 1. Galea — Software Factory for Claude Code ([report](01-galea-software-factory-claude-code.md))
- One 221-line skill and seven agent definitions run the whole factory; nothing in code enforces stage transitions,
  and a job cannot resume after the orchestrator session dies.
- An approver agent merges without a human except for a policy list (money, auth, deploy, schema, email, production
  data, dependencies, product-decision assumptions).
- Verification is only partly independent: UX/UI reviewers skipped the required browser check in 3 of 4 example
  reviews, undetected; every "read-only" reviewer has Bash and Write.
- The unmerged v2 (GPL-3.0) adds a scripted state machine with locking, a protected-path gate and risk-based routing,
  but its agents and skill are missing from the commit.
- **Reusable:** first-line verdict protocol, wait-for-all review round with a resumable builder, worktree/port/session
  isolation, atomic `mkdir` job claim, approver escalation policy, spec template with Assumptions — all **reimplement
  the idea** (no licence); dashboard and v2 scripts **reference only / reimplement the idea** (no licence; v2 GPL-3.0).

### 2. Ras Mic — Software Factory Skills ([report](02-rasmic-software-factory-skills.md))
- The workflow (isolate, build, prove, ship) and its iteration cap are Markdown only; two scripts do real work.
- `github_review.py` accepts a review score only when tied to the current commit (trigger, snapshot, trusted bot
  login, commit match, exclusive-create reservation); 33 tests cover it.
- `evidence.py` is a robust screen recorder, but "verified" means only that the video is playable; pass/fail is
  self-reported by the working agent.
- 71 test cases, no CI. Vendoring claims are partly accurate for `greploop` (a near-total rewrite still credited to
  upstream), and `unslop` no longer matches current upstream.
- **Reusable:** review-freshness pattern (**reimplement the idea**); `github_review.py` (**needs adaptation**, MIT);
  `unslop` (**directly reusable**, MIT); evidence recorder (**reference only / reimplement**, no licence).

### 3. Eric Tech — Super-Board ([report](03-erictech-super-board.md))
- An in-session Claude Code Workflow script runs cards in waves through JS-controlled steps with JSON-schema outputs;
  GitHub is the only state store, so "run" is also "resume".
- The merge gate is the strongest asset: atomic lock, reviewed-head pinning, checks run against the current base inside
  the lock, distinct exit codes for policy, migrations and human approval; human approval is pinned to head and scope,
  but is only as strong as the separation between the agent's and the human's GitHub tokens.
- 62 offline test suites with CI on Linux and macOS; 7 paid eval cases whose results are not in the repo.
- Security gaps: a legacy builder runs with permission checks disabled on raw issue text; Codex lanes run with no
  approvals and network on; verify/migrate commands evaluate PR code on the host; guard hooks fail open; unchecked
  `curl|bash` install; no untrusted-input guidance.
- **Reusable:** merge-policy classifier, GitHub read helper, guard hooks, usage guard (**directly reusable**, MIT);
  merge gate, approval script, wave planner (**needs adaptation**); wave-workflow pattern, review-remembers protocol,
  adversarial min-score review (**reimplement the idea**).

### 4. Rezvani — Skills & Agents Factory ([report](04-rezvani-skill-factory.md))
- Dormant: no commit since 2025-11-12; 7 community PRs unreviewed; the owner works in another repository.
- No tests; CI is a syntax check (`compileall`) plus a safety check and a link check. Quality gates are LLM
  self-checks or keyword counts.
- The hook factory generates hooks that do not match Claude Code's documented format (object matchers, a non-existent
  environment variable, an invented event, `exit 1` that does not block); the guide agents cannot work as described.
- An active issue-triage workflow passes any outsider's issue text into a Claude prompt holding a write token; the
  workflow kill switch is ineffective.
- **Reusable:** backup-and-atomic-write settings installer, least-privilege `allowed-tools` generation (**needs
  adaptation**); hook safety linter, "prompt only, then stop" rule (**reimplement the idea**); prompt presets
  (**directly reusable** as content, quality not evaluated).

### 5. Owain Lewis — Factory ([report](05-lewis-factory.md))
- About 290 lines of Python on claude-agent-sdk: setup, one worker, ordered checks, bounded retries; checks return a
  strictly validated pass/retry/stop result and missing output stops the run.
- SDK calls fail closed (allowlist, no settings sources, strict MCP config), but Bash is unrestricted and the worker
  edits the live checkout by default; a code check that reviewers changed nothing was removed.
- The author's own published benchmarks show no clear quality advantage for orchestration over Claude Code with a
  prompted reviewer subagent (30/36 vs 29/36 on the v3 suite); figures recomputed from the published data, not re-run.
- Most material work (16-case benchmark with held-out tests and a false-completion metric) sits in open PRs.
- **Reusable (all reimplement the idea, no licence):** pass/retry/stop check contract, fail-closed SDK handling,
  independent grader with held-out tests, counting a review only from real tool events; also the frozen-baseline
  method for testing one prompt change at a time (§10; not in the §13 table).

### 6. Owain Lewis — Blueprint ([report](06-lewis-blueprint.md))
- 12 Markdown workflow skills, no agents, no orchestrator code; all sequencing and gates are prose.
- Every skill is opt-in in both Claude Code and Codex, guarded by a unit test. In Claude Code the idle context cost is
  zero (official docs); the Codex runtime behaviour is unverified.
- Merge authority only through explicitly invoked skills and listed gates, including a fresh-subagent approval on the
  final commit (with a documented self-review exception); not tool-enforced. No behavioural evals.
- The `/html-doc` renderer is the strongest engineering: per-block content-parity hashes, SVG allowlist, network-blocked
  Chromium, atomic finalize.
- **Reusable:** `/plan` and `/spec` templates, `html_doc.py`, repo link checker (**directly reusable**, MIT); `/review`
  findings format, `/task-to-pr` merge gates (**needs adaptation**); opt-in invocation pattern (**reimplement the
  idea**).

### 7. Morluto — REA ([report](07-morluto-rea.md))
- Not a software factory: a reverse-engineering tool platform (220 deterministic MCP tools, 6 prompts, one skill) with
  no planner; no model calls were found (an inference from the code read); the host agent drives the work.
- Formal parity checking: a reconstruction obligation ledger accepts a reimplemented behaviour only with one owner,
  every required case kind and a passing verifier at matching authority; concurrent behaviour is compared by partial
  order.
- "Authenticated" evidence is integrity only (content hash, no signing), so a well-formed fabricated record passes;
  no non-test code produces the proof evidence the ledger needs.
- Security: marks target-derived results as untrusted and declares effects per tool, pins dependencies and CI actions;
  but "not a sandbox", 15 tools run foreign code with user permissions, HTTP mode has no authentication (documented).
- Large and churning: about 2,081 test files, six major versions in three months, unstable main CI during a bulk merge.
- **Reusable:** the REA MCP server as a whole (**directly reusable** as an external tool, not as code); proof-authority
  rules, per-tool effects table, untrusted-content marker, reconstruction ledger (**reimplement the idea**); evidence
  record model, concurrent-behaviour comparison, transcript scorer (**needs adaptation**).

### 8. Matt Pocock — Sandcastle ([report](08-pocock-sandcastle.md))
- A TypeScript library with two plug-in contracts: agent providers (Claude Code, Codex, Pi, Cursor, OpenCode, Copilot)
  and sandbox providers (Docker, Podman, Vercel, Daytona, none). Planning, review and merge are the caller's code.
- By default, `run()` disables the agent's permission checks even with `noSandbox()` (per-provider opt-outs exist), and
  `createSandbox().interactive()` always does; both contradict the project's own ADR 0015.
- Isolation gaps read from code: host `.git` mounted writable, open network with a GitHub token present, secrets in
  `docker run` arguments, and model-chosen branch names interpolated unescaped into host shell commands.
- Strong error handling (idle and hanging-process timeouts, schema-checked output with session-resume retries, dirty
  worktrees kept); about 1,416 tests; attested npm releases; CI without typecheck or lint.
- **Reusable:** the npm library, provider contracts, structured-output retries (**directly reusable**, MIT);
  hanging-process timeout, bundle-in/patch-out sync, privileged plan validation (**reimplement the idea**); Docker
  provider and templates (**needs adaptation**).

### 9. IndyDevDan — Super Simple Software Factory ([report](09-indydevdan-super-simple-software-factory.md))
- A skill that installs a Python workflow framework: scripts own phase order, bounded loops and acceptance; agents
  return typed envelopes that code checks afterwards.
- Runs on the Pi coding agent only; the Claude Code adapter is a stub. No sandbox, no approval step, no spending cap;
  agents inherit the operator's environment; commits stage the whole tree.
- Write boundaries are checked after each agent call by diffing changes, with rollback, but are blind to ignored and
  outside paths.
- Strong, low-tech observability: a SQLite trace with cost and context use per phase, gate evidence, and a
  process registry.
- No tests or CI; several defects found by reading (generator calls a removed API, renamed functions break five
  example workflows, placeholder checks that always pass).
- **Reusable:** typed envelope contracts, change capture, SQLite tracer (**directly reusable**, MIT); phase primitive
  with single acceptance, gate reports, write-boundary check (**needs adaptation**).

### 10. Cole Medin — AI Software Factory ([report](10-medin-ai-software-factory.md))
- A thin installer and consumer over the external Archon engine, pinned to an unmerged Archon branch (92 commits ahead
  of and 575 behind Archon `dev`); reviewer independence, the merge gate and agent permissions live in Archon and could
  not be verified here.
- Strong integrity code: refuses to run unless Archon is at the pinned SHA and clean (in the checked paths); the runtime
  host binds each app under test to a hash of its source and revision.
- Checks must be shown to fail before they are trusted: three-valued mutation scoring and a self-mutation check of the
  factory's own guards.
- Low maturity: 7 weeks old, no releases, no CI; setup runs as root with unpinned installer scripts.
- **Reusable (no licence, so ideas or with the author's permission):** pinned-source verifier, guard self-mutation
  check, board-aware launch gate, mutation scorer and CI gate (**reimplement the idea**); runtime host (**needs
  adaptation**, with permission).

### 11. Jake Schincariol — Replica Skill ([report](11-schincariol-replica-skill.md))
- 11 skills and 6 small Python tools guide one person through rebuilding someone else's app, through to deploy; fully
  LLM-driven, with no separation between the session that studies the original and the one that writes the code.
- A main strength is the specification and parity model: stable IDs for screens, flows and tests, evidence and
  confidence on inferred data models, and a scored feature ledger.
- `imgdiff.py` compares layouts by edge density; its layout mode is designed to be colour-invariant so a rebrand does
  not lower the score (luminance edges make it not fully colour-invariant).
- Legal and terms-of-service rules are extensive but mostly instructions; only three tools check anything; patents and
  public-website terms are not covered.
- The deploy preflight's parity step always exits 0, so the must-have gate depends on the LLM reading text (its
  `sweep.py` and `listing.py` steps do fail by exit code); parity rests on the builder marking its own rows done; two
  input-handling bugs confirmed by reading.
- **Reusable:** `imgdiff.py`, `parity.py`, `contrast.py` (**directly reusable**, MIT); `reviews.py`, `sweep.py`,
  `listing.py` (**needs adaptation**); feature-matrix schema and evidence-and-confidence recon map (**reimplement the
  idea**).

## Cross-cutting observations (facts for phase 2)

These are observations across the reports, not rankings or recommendations.

- **Licensing.** No licence for the evaluated code: Galea v1 (its unmerged v2 is GPL-3.0), Lewis Factory, Medin; their
  code can only inform ideas unless the author grants permission. Mixed: Ras Mic (no root licence; MIT for three
  skills, which are reusable; a modified "PolyForm Shield" text for one; none for the original skills). MIT: the other
  seven.
- **Execution models.** Prose-driven (the LLM follows Markdown): Galea v1, Ras Mic, Blueprint, Replica, Rezvani.
  Code-driven control with LLM workers: Lewis Factory, IndyDevDan, Sandcastle (caller-authored loops). Medin delegates
  all AI orchestration to Archon, which was not inspected, so its execution model is a claim from this repo's
  configuration [C]. Hybrid scripted workflow: Super-Board. Tool platform with no orchestration: REA.
- **Permissions and isolation.** Permission checks disabled by default or in some paths: Sandcastle (`run()` by default
  and `createSandbox().interactive()`), Super-Board (legacy builder; Codex lanes with no approvals),
  IndyDevDan (example `cc` recipe). Unrestricted shell pre-approved: Lewis Factory (worker and reviewer). No permission
  configuration shipped, so the host's settings apply: Galea. Root execution with `IS_SANDBOX=1`; agent permissions
  live in Archon and are unverified: Medin. Sandcastle is the only project built around container isolation, and it
  has gaps.
- **Untrusted input.** Marked or guided: REA marks target-derived results as untrusted; Galea's unmerged v2 adds a
  "quoted data, not instructions" banner; Lewis Factory has prompt-level "treat as data" lines; Sandcastle's
  `triage-repro` skill has explicit untrusted-input rules. Passed without such guidance: Super-Board (card, issue, PR
  and Sentry text), Replica (fetched pages and review text), Sandcastle's plan prompts (issue bodies, into agents with
  permissions bypassed), Rezvani (issue-triage workflow with a write token, the clearest exposure). Galea v1's inputs
  are the local operator's text and `AGENTS.md`, plus a browser guide fetched at runtime.
- **Independent verification.** Enforced in code, with caveats: Super-Board's head-pinned merge gate (human approval is
  only as strong as token separation); Medin's self-mutation check (tests the factory's own guards, not the produced
  software, and runs only when invoked); Lewis Factory's held-out grader (unmerged); REA's authority rules (proof
  records come from the caller, evidence has integrity only, and nothing outside tests produces proofs). Prompt-only or
  self-reported: Galea's reviewers, Replica's parity rows, Ras Mic's evidence results, Blueprint's gates.
- **Evidence of value.** Lewis Factory is the only project publishing orchestration-versus-baseline benchmarks (author
  data, recomputed but not re-run): on easy tasks every mode passed 36/36, with Factory about 2.1× the median time and
  2.5× the cost of task-only baselines; on harder targeted cases Factory passed 6/9 against 1–3/9, at higher cost;
  against Claude Code with a prompted reviewer subagent, 30/36 vs 29/36, faster (48.6 s vs 75.5 s median) at similar
  cost. REA publishes dated, partly negative efficiency benchmark checkpoints for its own tools.
- **Reverse engineering and parity.** Two distinct levels: REA works at binary and process level with a formal
  obligation ledger; Replica works at product level (screens, flows, features) with a scored feature ledger and
  layout image diff.
- **Maturity.** Tested and released: Sandcastle (~1,416 tests, attested releases), Super-Board (62 suites, CI), REA
  (~2,081 test files, frequent releases, churn). Dormant: Rezvani. Young: Medin (7 weeks, no releases). No tests and no
  CI: Galea, IndyDevDan. No tests, CI limited to syntax, safety and link checks: Rezvani.

## Corrections to the 2026-10-14 evaluation

Four repositories were also covered in `docs/evaluations/2026-10-14-software-factory-architecture-evaluation.md`.
Each report's §17 has a "Changes since the 2026-10-14 evaluation" subsection; the main corrections:

- **Ras Mic (report 02).** `greploop` no longer pre-approves broad `gh`/`git` commands or stages with `git add -A`
  (true at the earlier revision `4b72f46`, removed since). "23 tests for `evidence.py` only" is outdated (now 71 cases
  across three suites). "Only 3 original skills" and "discipline mostly prose" need qualifying for `greploop`. The
  "PolyForm Shield" label is not the real PolyForm text.
- **Super-Board (report 03).** The "contradicted by `run.md:141`" citation was attached to the wrong clause; the
  underlying finding (draft-PR delivery contradicted by Reviewer auto-merge) stands. The test count was 57 at the
  earlier revision, not 59 (62 now). The runtime is the in-session Workflow script; GitHub Projects is the state store.
  The earlier revision `7d848f7` is 27 commits after the v3.1.2 tag.
- **Rezvani (report 04).** Same commit in both reviews; the earlier findings were confirmed (including the kill switch
  read before checkout and `exit 1` blocking). Several new defects were found.
- **REA (report 07).** The earlier "strongest asset" (hashed evidence IDs) gives integrity, not provenance. Counts
  updated: 220 tools (not "150+"), test files about 1,294 → 2,081, 1,146 commits since. The reconstruction and parity
  layer was not covered earlier.

## Research completeness and limits

- **Completeness.** Complete: 02, 06, 11 and the in-scope v1 of 01. Mostly: 03, 04, 05 (overall), 07, 08, 09
  (overall), 10. Each report's §17 lists what was read and skipped.
- **Not executed.** No test results, runtime behaviour, costs or security impacts were observed by running code.
  Security findings are read from code and marked as inferences where impact depends on execution.
- **Not covered.** Out of scope by the brief: Archon internals (report 10). Skipped for breadth: most of REA's format
  and provider directories (report 07). Not available: the external daemon that Sandcastle's `.factory/` points to is
  not in the repository [U] (report 08). Unverified: the Codex side of cross-client behaviour (reports 03, 06).
- **Unverified external figures.** Star counts (for example REA's 365k), community cost reports (IndyDevDan issue #13)
  and author benchmarks (Lewis Factory) are cited as reported; the Lewis Factory totals were recomputed from published
  data but not re-run.

## Verification record

| Report | Verifier findings | Corrector findings | Status |
|---|---|---|---|
| 01 | V1-1 … V1-3 | — | closed |
| 02 | V2-1, V2-2 | — | closed |
| 03 | V3-1 … V3-5; closure pass N3-1, N3-2 | C-3 | closed |
| 04 | V4-1 … V4-6; closure pass N3-2 (legend) | — | closed |
| 05 | V5-1 (no change needed) | — | closed |
| 06 | V6-1, V6-2; closure pass N3-2 (legend) | C-2 | closed |
| 07 | V7-1 … V7-9 | C-1 | closed |
| 08 | V8-1, V8-2 | — | closed |
| 09 | V9-1 … V9-3 | — | closed |
| 10 | V10-1 … V10-5; closure pass N10-1 | C-4 | closed |
| 11 | V11-1; closure pass N3-2 (legend) | — | closed |

N3-2 (the `[F docs]` legend entry) was raised on report 03 and applied to every report that uses the tag (03, 04, 06,
11). Closures are from the verifiers' returns to the coordinator.

**Process deviations, disclosed** (from the researchers', verifiers' and corrector's own returns to the
coordinator). No repository code was executed by anyone. A few writes went outside the brief's
limits, all in the session's temporary area and none in this project or the clones: a researcher's upstream comparison
folder (report 02) and branch-list file (report 07), both deleted at once; a verifier's copy of one upstream file
(deleted by the coordinator); the corrector's API tree file (deleted). The corrector edited report 02 with a Python
heredoc instead of the editing tool (same content). The report 04 researcher used one local `python3 -I` command to
read committed JSON data files and `unzip -l` to list archive contents; neither ran repository code.

## Inputs for phase 2

Phase 2 (Comparative Architecture Intelligence) should read the 11 reports, using the same 17 sections for
side-by-side comparison, §13 for the cross-repository reuse matrix, §14 for evidence against the six value
dimensions, and §16 to keep verified behaviour separate from claims.
