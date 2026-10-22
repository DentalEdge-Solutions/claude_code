# Comparative Architecture Matrix: all 11 repositories

> Phase 2 of the Software Factory evaluation campaign · Date: 2026-10-22
> Inputs: phase 1 reports 01-11 (docs/evaluations/2026-10-22-factory-research/) · Framework: value definition (active decision 2026-10-22)
> Legend: [Obs] observed · [Docs] official docs · [Claim] unverified claim · [Inf] inference · [Unk] unknown

**Citation format.** `[R07 §11]` means report 07, section 11. A decisive `path:line` follows where it matters.
"re-checked" means this analyst opened the cited lines in the read-only clone at the evaluated commit and found
them as the report describes. [Docs] is used only where a phase 1 report cites the official Claude Code docs
(code.claude.com, accessed 2026-10-22); no new docs were fetched for this deliverable. Nothing was executed.

**Short names.** R01 Galea Software Factory · R02 Ras Mic skills · R03 Super-Board · R04 Rezvani Skill Factory ·
R05 Lewis Factory · R06 Lewis Blueprint · R07 REA · R08 Sandcastle · R09 IndyDevDan SSSF · R10 Medin AI Software
Factory · R11 Replica.

**Scope.** This deliverable compares. It makes no adoption decision and no recommendation for `claude_code`.

---

## Summary of comparative findings

1. **No repository meets the mandatory security criterion as shipped** under the definition in §5.7. Every one
   has at least one evidenced default-path gap (permission bypass, unrestricted pre-approved shell without
   isolation, untrusted text reaching write-capable agents, or unpinned install paths). Several contain
   components that meet a security bar on their own (§5.8).
2. **Where the next step is decided splits the set cleanly.** Code decides in R05, R09 and (per iteration) R08;
   code decides per card with script-enforced gates in R03; an LLM following prose decides in R01, R02, R04, R06
   and R11; R07 has no orchestration by design; R10 delegates it to Archon, which was not inspected (§3).
3. **Code-owned control flow did not by itself produce correctness.** R09's deterministic chain ships test
   phases that pass by default and a claims gate that checks only file existence; R05's author-published data
   shows false completions that passed tests plus an LLM review (v3: 6 of 36) and no quality advantage over
   Claude Code with a prompted reviewer subagent (30/36 vs 29/36). These are author data, recomputed but not
   re-run [R05 §7, §9].
4. **The only mechanically enforced merge gate is R03's** (lock, head pin, project checks on the base-merged
   head inside the lock, policy and head- and scope-pinned approval) [R03 §12]. Its shipped default is
   `merge_policy.default: "auto"`, so the model-run Reviewer merges ordinary PRs itself; a human is asked only on
   a size, category or migration trigger [R03 §8, §17; re-checked `super-board-merge-policy.py:133`,
   `config-schema.json:135`]. Elsewhere: R11's `sweep.py` and `listing.py` block a deploy by exit code, but only
   when the LLM runs them [R11 §5]; R01's v2 branch has a scripted gate (main-checkout checks, protected paths)
   that is unmerged [R01 §2.4]. Every other merge or deploy gate is prose, external (R10/Archon) or absent.
5. **Prose instructions were observably skipped where evidence exists.** R01's UX/UI reviewers skipped the
   required browser check in 3 of 4 example reviews, undetected [R01 §7]. No other prose-driven repo ships run
   artifacts that would show compliance or non-compliance.
6. **Independent verification is mostly context separation, not model or execution separation.** Only R03's
   gate and R10's runtime identity binding verify produced work against the delivered head or bytes,
   independently of the producing agent's account [R03 §12, R10 §12]. Other code checks exist but are weaker in
   that respect: R05's runner-run command checks (0/1/other exit contract) run in the worker's own unprotected
   workspace [R05 §5, §8]; R02's code binds an external LLM review to the current head but the agent decides
   whether to run it [R02 §5]; R11's `sweep.py`/`listing.py` exit codes count only when the LLM runs them
   [R11 §5]; R09's code-run test phases ship as placeholders [R09 §7]. R07's ledger verifies reconstruction
   claims but trusts caller-supplied proofs; R11's parity score rests on the builder's own entries [§4 D4].
7. **Untrusted-input handling is the weakest cross-cutting capability.** Result-level marking exists only in
   R07; a privilege-split agent job exists only in R08's own CI explore workflow; R04's active issue-triage
   workflow passes any outsider's issue text to an agent holding a write token [R04 §8].
8. **Reference-driven development exists at two non-comparable levels:** artifact/binary level with a formal
   proof-authority ledger (R07) and product level with an ID-keyed specification and a scored feature ledger
   (R11). Neither verifies parity independently of the party claiming it [R07 §6, R11 §11.5].

---

## 1. Category grouping

A repository can sit in several groups. Bold marks the group where the repository's main value lies.

| Group | Defining question | Members | Notes |
|---|---|---|---|
| G1 End-to-end delivery factories | Does it take a request or issue to a merged change? | **R03**, **R01**, **R10**, R06 (`/factory`, `/codex-issue-coordinator`), R08 (its own label-driven workflows and templates), R05 (example `/factory` skill only), R01 v2 (unmerged branch) | [Obs] [R03 §1, R01 §1, R10 §1, R06 §5, R08 §5, R05 §4]. R10's delivery path is Archon's and was not inspected [R10 §17] |
| G2 Programmable orchestration engines | Does code own the loop that calls the agents? | **R05**, **R09**, **R08**, R03 (wave script), R10 (scheduling layer only), R01 v2 spine (unmerged) | [Obs] [R05 §5, R09 §5, R08 §5, R03 §5, R10 §5.1, R01 §2.4] |
| G3 Prose skill and methodology packs | Is the workflow Markdown that an LLM follows? | **R02**, **R06**, **R11**, R01 v1, R04 (generator prompts) | [Obs] [R02 §5, R06 §5, R11 §5, R01 §5, R04 §5.1] |
| G4 Reference-driven development and reverse engineering | Does it extract a specification from an existing artifact and measure parity? | **R07** (artifact/binary level), **R11** (product level) | [Obs] [R07 §11, R11 §11] |
| G5 Claude Code artifact generators | Does it generate skills, agents, hooks or commands? | **R04**, R09 (`make_adw.py`, `make_config.py`, minor) | [Obs] [R04 §1, R09 §4] |
| G6 Isolation runtimes | Does it isolate agent execution? | **R08**; R10 runtime host (process and identity ownership, explicitly "not a sandbox") | [Obs] [R08 §8, R10 §8] |
| G7 Verification tooling components | Deterministic checkers usable inside another factory | R02 (`github_review.py`, `evidence.py`), R03 (merge gate, approval, read helper), R07 (obligation ledger, effects table), R09 (gates, write-boundary check), R10 (mutation scorer, runtime host), R11 (`imgdiff.py`, `parity.py`, `reviews.py`, `sweep.py`), R06 (`html_doc.py`: document rendering verification, not product verification) | [Obs] [§13 of each report] |

**Meaningful comparisons.**
- Within G1: the path from request to merge, where merge authority lives, which gates are code and which are
  prose, recovery after a crash. R10 is comparable only on its in-repo layer (pin verification, scheduling,
  runtime host), because its review and merge logic is in Archon [R10 §3].
- Within G2: the control-plane contract (result types, retry bounds, timeouts), testability with fake agents,
  isolation defaults, cost bounds.
- Within G3: invocation control, gate wording, context footprint, independence instructions. None of G3 has
  behavioural evals, so these comparisons are of design, not of effect [R02 §7, R06 §7, R11 §7, R01 §7, R04 §7].
- Within G4: specification model, parity measure, proof authority. Scale is not comparable (220 tools against six
  scripts).
- Across groups, capabilities (not projects): permission defaults, untrusted-input handling, supply chain,
  observability, cost control, factory self-testing, licence.

**Comparisons that are not meaningful.**
- Whole-project rankings across groups, for example REA against Galea or Sandcastle against Blueprint.
- Raw test counts as a quality proxy across very different sizes (R07: 2,081 test files; R11: 57 test functions).
- "Autonomy" for R02, R04, R07 and R11, which keep autonomy low or external by design [R02 §14, R04 §14, R07 §5,
  R11 §14].
- Anything about R10's review independence, merge correctness or agent behaviour: Archon was out of scope
  [R10 §17].
- Stars and forks as adoption evidence: R07's 365,013 stars are of unknown organic nature [R07 §1].
- Efficiency or quality gains of orchestration: only R05 publishes orchestration-versus-baseline data; no other
  repo has a comparable measurement [R05 §9; index "Evidence of value"].
- R04's "factory" against software-delivery factories: it generates Claude Code artifacts, not software
  [R04 §1].

---

## 2. Master matrix

Every cell is tagged and cited. Cells keep the evidence; §4 holds the ratings.

### 2a. Architecture, control plane, orchestration, host, licence

| Repo | Architecture style | Control plane (who decides the next step) | Orchestration model | Host agent(s) | Licence |
|---|---|---|---|---|---|
| R01 Galea | [Obs] 1 orchestrator skill (221 lines), 7 subagents, file job state, HTML dashboard; no executable factory code [R01 §1-2] | [Obs] LLM: orchestrator session reads first-line verdicts and writes `job.json`; nothing validates transitions [R01 §5 `SKILL.md:83-89`]. Unmerged v2 has a Python `TRANSITIONS` table [Obs, branch only] [R01 §2.4] | [Obs] LLM-coordinated fixed graph: spec → build → 4 parallel reviewers → approver [R01 §5] | [Obs] Claude Code (named subagents, `SendMessage` resume) [R01 §2.2]; minimum version [Unk] | [Obs] none for v1 (re-checked: no licence file in folder or root); v2 branch GPL-3.0 [R01 header] |
| R02 Ras Mic | [Obs] 7 skills + `AGENTS.md` template + 2 Python CLIs (recorder 1,358 lines; review freshness 257 lines) [R02 §1-2] | [Obs] LLM: step order, iteration cap and stop live in Markdown; scripts decide only freshness and playability [R02 §5] | [Obs] skill-driven, single host agent; no orchestrator or subagents [R02 §3] | [Obs] Claude Code [R02 §3]; Cursor and Codex [Claim] [R02 §16] | [Obs] none at root (re-checked); MIT for `greploop`, `greploop-apps`, `unslop`; non-canonical "PolyForm Shield" text for `before-and-after` [R02 header, §16] |
| R03 Super-Board | [Obs] skill pack/plugin + Workflow script `super-board-wave.js` + ~8,200 lines of bash/Python safety scripts + 5 guard hooks and 1 cleanup hook (re-checked `hooks/`; README's "6 guard hooks" rated "partly" [R03 §16]); GitHub Projects v2 is the state store [R03 §1-2] | [Obs] hybrid: JS fixes each card's lane order; scripts decide merge, policy, approval and halt by exit code; an LLM orchestrator session plans and reconciles waves from prose [R03 §5] | [Obs] hybrid wave fan-out; Codex backend and legacy `nohup claude -p` backend [R03 §1, §5] | [Obs] Claude Code (Workflow tool), Codex CLI; OpenCode detected and refused [R03 §16]; "tested on 2.1.302" [Claim] [R03 §2] | [Obs] MIT |
| R04 Rezvani | [Obs] 5 factory prompts (857-1,152 lines), 5 guide subagents, `/build`, Python generators, 6 generator + 8 domain skills (14 under `generated-skills/`, re-checked), 19 governance workflows [R04 §1-2, §4.2-4.3] | [Obs] LLM with human Q&A; code only inside generator scripts [R04 §5.1] | [Obs] command/skill-driven generation; `factory-guide` cannot delegate (no `Agent` tool) [Obs+Docs] [R04 §3] | [Obs] Claude Code; Codex via `codex-cli-bridge` [R04 §4.2] | [Obs] MIT |
| R05 Lewis Factory | [Obs] ~290-line Python CLI on claude-agent-sdk: setup → worker → ordered checks → bounded retry; TOML + Markdown prompts [R05 §1-2] | [Obs] code: `runner.run` owns order, retry bound and pass/retry/stop [R05 §5; re-checked loop at `runner.py:147-183`, whole run `:99-186`] | [Obs] deterministic single-stage pipeline, sequential [R05 §5] | [Obs] Claude Code through the Agent SDK (`claude` on PATH); POSIX only [R05 §2] | [Obs] none (re-checked) |
| R06 Blueprint | [Obs] 12 Markdown skills, no agents, no orchestrator; `html_doc.py` renderer (694 lines) + repo checks [R06 §1-2] | [Obs] LLM following prose; skills compose by reading each other's `SKILL.md` [R06 §2, §5] | [Obs] skill-driven; `/codex-issue-coordinator` runs up to 2 Codex worker threads [R06 §3, §5] | [Obs] Claude Code and Codex (opt-in flags for both); coordinator Codex-only [R06 §3, §12] | [Obs] MIT |
| R07 REA | [Obs] MCP server + CLI (TypeScript), 220 deterministic tools with effect declarations, 6 MCP prompts, 1 product skill [R07 §1, §4] | [Obs] host LLM decides; REA tools are deterministic; no planner [R07 §5]; no model calls [Inf] [R07 §2] | [Obs] none by design: "custom orchestration needs a demonstrated requirement" [R07 §5 `docs/roadmap.md:24-25`] | [Obs] any MCP client; setup supports ~15 clients [R07 §14] | [Obs] MIT; external engines under their own licences, some commercial [R07 header, §13] |
| R08 Sandcastle | [Obs] TypeScript library + small CLI; agent-provider and sandbox-provider plug-in contracts; templates hold multi-step flows [R08 §1-2] | [Obs] code: iteration loop, completion signal, timeouts; multi-step flow is caller code; inside an iteration the agent acts autonomously [R08 §5] | [Obs] caller-authored deterministic scripts (plan → parallel implement → review → merge templates) [R08 §5] | [Obs] Claude Code, Codex, Pi, Cursor, OpenCode, Copilot CLIs [R08 §3] | [Obs] MIT |
| R09 SSSF | [Obs] one skill that stamps a Python ADW framework (15 modules, 12 workflow scripts), 5 agent prompt pairs, SQLite tracer + Vue visualizer [R09 §1-2] | [Obs] code: straight-line ADW scripts; the LLM never picks the next phase; the outer orchestrator only launches and observes [R09 §5] | [Obs] deterministic pipeline, sequential phases [R09 §5] | [Obs] workers: Pi CLI only; Claude Code adapter raises `NotImplementedError` (re-checked `agent_cc.py:11-15`); outer orchestrator: Claude Code or Pi [R09 §1, §3] | [Obs] MIT |
| R10 Medin | [Obs] installer + `consumer.py` (810 lines) forwarding to a pinned Archon engine; runtime host; mutation harness; governance templates; no agents, prompts or workflows in repo [R10 §1-2] | [Obs] in repo: code (pin verification, scheduling, launch gate); stage control: Archon [Claim/Unk] [R10 §5.1] | [Claim] delegated to Archon's SDLC pack (not inspected) [R10 §3] | [Claim] Claude Code or Codex via Archon [R10 §2.1] | [Obs] none (re-checked; issues #32, #61 ask); Archon MIT [R10 §2.2] |
| R11 Replica | [Obs] 11 skills + 6 stdlib Python tools + templates; plugin manifest [R11 §2] | [Obs] human sequences the skills; LLM interprets each; tools gate by exit code only when run [R11 §5] | [Obs] skill-driven, single session, file handoff [R11 §5] | [Obs] Claude Code (plugin) [R11 §2] | [Obs] MIT |

### 2b. Agents, skills, workflow, parallelism, state

| Repo | Agents / roles | Skills | Execution workflow | Parallelism | Context, state and resume |
|---|---|---|---|---|---|
| R01 | [Obs] 7 subagents: spec-writer, builder, 4 reviewers, approver; opus ×4, sonnet ×3; all have Bash and Write [R01 §3] | [Obs] 1 skill, 4 verbs (`/factory <feature>`, `next`, `approve`, `rework`) [R01 §4] | [Obs] spec → build → 4 reviewers (wait for all) → ≤2 builder resumes → approver APPROVE (local merge) or ESCALATE [R01 §5] | [Obs] 4 reviewers per round in one message; multi-job by separate sessions + worktrees + `mkdir` claims; multi-job runs not evidenced [R01 §5, §16] | [Obs] `job.json` + round files; builder resumed via `SendMessage`; no command re-enters a job after the orchestrator dies [R01 §6] |
| R02 | [Obs] none; rules for concurrent agents in `AGENTS.md:54-72` [R02 §3] | [Obs] 7 (new-feature, code-structure, evidence-driven-testing, before-and-after, greploop, greploop-apps, unslop) [R02 §4] | [Obs] isolate → build → prove → ship; greploop bounded loop, default 10, agent-enforced [R02 §5] | [Obs] none inside the pack [R02 §5] | [Obs] `.artifacts/` JSON; `wait` re-runnable, `stop` idempotent; no workflow ledger [R02 §6] |
| R03 | [Obs] no agent files; Workflow `agent()` calls: pre-flight, classifier, builder, tester, reviewer + 2 truth-check sub-agents; model ladder by complexity; reviewer on session model [R03 §3] | [Obs] 8 skills with ~4,000 lines of references [R03 §2, §4] | [Obs] Ready → Building → QA → Review → Done per card; merge only through the gate; exit codes routed to board moves [R03 §5 paths 1-2] | [Obs] dependency-sized waves, no width cap unless `max_workers`; merge serialized by `mkdir` lock [R03 §5]; Workflow runtime up to 16 concurrent agents by default [Docs] [R03 §5] | [Obs] GitHub board is the only loop state, "run again" resumes; stranded-card sweep; shared halt file [R03 §6]; Workflow relaunch returns cached results in the same session [Docs] [R03 §6] |
| R04 | [Obs] 5 guides (haiku/sonnet) + `claude-md-guardian`; guides are multi-turn Q&A, which subagents cannot hold because `AskUserQuestion` is removed from subagents [Obs+Docs] [R04 §3] | [Obs] 6 generator skills (agent-, hook-, prompt-, slash-command-factory, codex-cli-bridge, claude-md-enhancer) + 8 domain skills, 14 under `generated-skills/` (re-checked); factory commands lack frontmatter [R04 §4.2-4.3] | [Obs] `/build` → guide → template fill or Python generator → files/ZIP [R04 §5.2-5.3] | [Obs] none [R04 §5.1] | [Obs] files only; no resume [R04 §6] |
| R05 | [Obs] per-call SDK sessions: worker (Read, Glob, Grep, Write, Edit, Bash); agent check (Read, Glob, Grep, Bash, Skill, Agent) [R05 §3; re-checked `config.py:17-25`] | [Obs] example `/factory` issue → PR and `improve-factory` skills only [R05 §4] | [Obs] setup once → worker → checks in order → retry with latest feedback; `--attempts` default 1 [R05 §5] | [Obs] none; separate processes only [R05 §5] | [Obs] `run.json` + per-attempt logs; feedback replaced, not accumulated; no resume [R05 §6] |
| R06 | [Obs] none; fresh generic subagent for review; coordinator and worker roles as Codex threads [R06 §3] | [Obs] 12, all opt-in [R06 §4] | [Obs] `/factory` → `/task-to-pr`: worktree, `/test`, PR, fresh `/review`, CI, repair loop, five merge gates [R06 §5 path 1] | [Obs] `/task-to-pr` unbounded "start independent work together"; coordinator default 2 workers [R06 §5] | [Obs] GitHub is the tracker; the spec file keeps proof and PR links; resume by reusing branch/worktree/PR; no checkpoint [R06 §6] |
| R07 | [Obs] none; Codex CLI used only in its own agent-experience eval [R07 §3] | [Obs] 1 product skill (451 lines + references), 4 maintainer skills, 6 MCP prompts [R07 §4] | [Obs] host calls tools → Evidence into session ledger → obligation ledger evaluates reconstruction claims [R07 §5 paths 1-2] | [Obs] advice only; session admission serializes operations on the bound target [R07 §5] | [Obs] content-addressed Evidence ledger, portable bundles, unknowns registry with optimistic concurrency [R07 §6] |
| R08 | [Obs] agent providers for 6 CLIs; planner, implementer, reviewer, merger as template prompts [R08 §3] | [Obs] 2 repo skills (`pre-release`, `triage-repro`); prompt templates with `{{KEY}}` and shell expressions [R08 §4] | [Obs] per iteration: fresh worktree + container → print-mode agent run → commits merged back by branch strategy [R08 §5 path 1] | [Obs] caller fan-out (`Promise.allSettled`; max-4 semaphore in a dogfood script); no limiter in the library; ADR 0007 locking not implemented [R08 §5] | [Obs] git is the store; session capture with cwd rewrite, resume and fork; no workflow checkpoint [R08 §6] |
| R09 | [Obs] 5 Pi agents (planner, builder, scout, reviewer, documenter) with per-agent models; tests are code phases, no tester agent [R09 §3] | [Obs] 1 skill + 9 cookbooks + generators [R09 §4] | [Obs] plan → commit → build → test/fix ≤3 → review/revise ≤2 → commit → document → `finish(accepted)` [R09 §5 path 2] | [Obs] sequential phases; untraced Pi subagents inside planner and scout [R09 §3, §5] | [Obs] typed envelopes + `context_handoff/` + SQLite mirror; `--adw-id` rejoins sessions but there is no phase-level skip [R09 §6] |
| R10 | [Obs] none (audit bans them); Archon roles [Claim] [R10 §3] | [Obs] none; governance templates (MISSION, WORKFLOW_POLICY, HOLDOUT) [R10 §4] | [Obs] verify pin → discover/validate → forward `workflow run` with policy inputs; scheduled laps through the launch gate [R10 §5.5-5.6] | [Obs] `parallel` 1-8 laps, `overlap: "skip"` [R10 §5.2; re-checked `consumer.py:432-434`] | [Obs] `.factory/` files; run state in Archon [Claim]; native resume passthrough [R10 §6] |
| R11 | [Obs] none; the same session studies the original and writes the code [R11 §3] | [Obs] 11 `replica-*` skills [R11 §4] | [Obs] recon → architect → design → build → backend → test → diff → entrepreneur → brand → launch → deploy, user-invoked [R11 §5] | [Obs] none [R11 §5] | [Obs] `replica/` files with stable IDs (S01, F01, F01-H1, BUG-001); re-run any skill [Inf]; no state machine [R11 §6] |

### 2c. Testing, verification, permissions, isolation, untrusted input

| Repo | Testing of the factory | Verification of produced work | Permission model | Isolation | Untrusted-input handling |
|---|---|---|---|---|---|
| R01 | [Obs] none; no CI; 2 example jobs [R01 §7] | [Obs] builder self-evidence; code reviewer re-runs validation; approver spot-checks ≥1 AC; UX/UI reviewers skipped the browser in 3 of 4 reviews, undetected (re-checked `001/round-1/review-ux.md:7`) [R01 §7] | [Obs] none shipped; host settings apply; "read-only" is prompt-only [R01 §8] | [Obs] worktree, ports and browser session per job; no sandbox [R01 §8] | [Obs] inputs are operator text; target `AGENTS.md` treated as canonical; browser guide fetched at runtime; v2 adds a "quoted data" banner (unmerged) [R01 §8] |
| R02 | [Obs] 61 functions / 71 cases incl. adversarial freshness and real-process recorder tests; no CI [R02 §7] | [Obs] Greptile score accepted only when bound to the current head by code (re-checked `github_review.py:73-84`); evidence pass/fail self-reported; `"verified": true` means a playable video [R02 §7] | [Obs] `before-and-after` `allowed-tools` pre-approves unpinned global npm install and `gh pr edit *` [R02 §8] | [Obs] worktree per task; Playwright deps in a temp dir with `--ignore-scripts` [R02 §8] | [Obs] trusted-login filter for scores; bot text not sanitised [R02 §8] |
| R03 | [Obs] 62 offline suites (re-checked count) incl. a stubbed test of `wave.js`; CI on Linux and macOS + Windows smoke; 7 paid evals, results gitignored [R03 §7] | [Obs] Tester tests → Reviewer reruns + 2 truth-check sub-agents (minimum score) → gate runs `verify_commands` on the base-merged head inside the lock, merges with `--match-head-commit` (re-checked `merge-gate.sh:349-351`) [R03 §7, §12] | [Docs] workflow subagents use the session's permission rules [R03 §8]; [Obs] legacy builder `--dangerously-skip-permissions` (re-checked `super-build-dispatch.sh:140-145`); Codex lanes `approval_policy="never"` + network (re-checked `codex-lane.sh:188-198`) [R03 §8] | [Obs] per-lane worktrees enforced by hook; verify/migrate commands `eval`ed on the host (re-checked `merge-gate.sh:281-290`) [R03 §8] | [Obs] none: issue, PR, comment and Sentry text reach agents with push and (on auto boards) merge capability; an issue `Skills:` line selects worker skills [R03 §8] |
| R04 | [Obs] none; CI is `compileall` + safety + link check; YAML lint commented out [R04 §7] | [Obs] none independent; `expected_output.json` written by the same LLM run, never executed [R04 §7] | [Obs] guides declare tools; factory commands have no `allowed-tools`; generated agents default to Bash/Write [R04 §8] | [Obs] none [R04 §8] | [Obs] issue-triage puts any outsider's issue title and body into a Claude prompt holding a write PAT; filter is label-based only (re-checked `issue-triage.yml:15-17,59-62`); kill switch read before checkout [R04 §5.4, §8] |
| R05 | [Obs] 17 functions / 28 cases with fake agents; CI pytest + ruff check + format (re-checked `ci.yml`) [R05 §7] | [Obs] command checks + fresh-session LLM review with schema output; reviewer non-modification prompt-only after the tamper check was removed (9b7f5cf); held-out grader only on unmerged branch [R05 §7, §8] | [Obs] `dontAsk`, allowlist = tools, denial fails the run, `setting_sources=[]`, strict MCP; but unrestricted Bash pre-approved for worker and reviewer [R05 §8; re-checked `runner.py:53-67`, `config.py:19,25`] | [Obs] none; default `cwd="."` edits the live checkout; worktree opt-in via a `pre` command [R05 §8] | [Obs] JSON-encoded context + "treat as data" prompt lines; example skill acts on bot comments with "no human in the loop" [R05 §8] |
| R06 | [Obs] 28 test methods (repo checks + renderer); SHA-pinned CI green; no behavioural evals of the skills [R06 §7] | [Obs] `/test` criterion → evidence + fresh-subagent `/review` on every repair + CI; all prose; same-model independence [R06 §7] | [Obs] none configured; the only enforced control is opt-in invocation, guarded by a unit test; reviewer read-only is prose (re-checked `review/SKILL.md:13,85`) [R06 §8] | [Obs] worktrees (prose); renderer's Chromium network-blocked, proven by test [R06 §8] | [Obs] scope rules only; "reviewer comment is evidence" rule only on unmerged branch; untrusted-browser rule dropped from `/test` [R06 §8] |
| R07 | [Obs] 2,081 test files, ~100 real-toolchain `verify:*` scripts, SHA-pinned CI; main unstable at evaluation (19 success, 14 fail, 66 cancelled of last 100 runs) [R07 §1, §7] | [Obs] (reconstruction claims) fail-closed obligation ledger with an authority lattice; proofs supplied by caller; integrity-only digests; only a fixture produces `rea.reconstruction-proof` (re-checked by grep: fixture and the authority checker only) [R07 §5 path 2, §6] | [Obs] host approval; per-tool effect declarations drive MCP annotations; 15 tools execute foreign code [R07 §8] | [Obs] "not a sandbox"; process groups, prlimit/Job Objects, private Ghidra projects; HTTP loopback default, no auth (documented) [R07 §8] | [Obs] every target-derived result marked `untrusted_content`; server instructions treat target content as data; labelling, not enforcement [R07 §8] |
| R08 | [Obs] 54 files / ~1,416 cases (re-checked: 54 files; 1,413 by a line-anchored regex); CI on push to main only, build + test, no typecheck or lint (re-checked `ci.yml`) [R08 §7] | [Obs] caller-defined; `sandbox.exec` gates; review is a second agent in the same sandbox; no evals [R08 §7] | [Obs] AFK runs always pass `dangerouslySkipPermissions: true`, including with `noSandbox()` (re-checked `Orchestrator.ts:143`, `createSandbox.ts:631`), contradicting ADR 0015; per-provider opt-outs [R08 §8] | [Obs] Docker/Podman with host `.git` mounted read-write and open network by default; Vercel/Daytona VMs via git bundle; `noSandbox()` inherits the full env [R08 §8] | [Obs] explore workflow privilege-split with untrusted framing; plan/implement prompts pass issue text into permission-bypassed agents; LLM-generated branch names interpolated into host shell commands [Obs code; impact Inf] [R08 §8] |
| R09 | [Obs] none; no CI; generator and example-branch defects [R09 §7] | [Obs] quality phases ship as `echo` placeholders that exit 0; reviewer on a different model; `diff_matches_claims` checks only that files exist (re-checked `gates.py:61-68`) [R09 §7] | [Obs] `pi --tools` allowlist; bash for every agent; post-hoc write-boundary diff with rollback; grader files protected [R09 §8] | [Obs] none; live checkout; full operator env; `git add -A` (re-checked `git_helper.py:49`) [R09 §8] | [Obs] envelopes inlined verbatim into the next prompt; no data-not-instructions guidance [R09 §8] |
| R10 | [Obs] 83 unittest methods with a fake Archon CLI; guard self-mutation check; no CI; Archon conformance test skipped by default [R10 §7] | [Obs] in repo: `ci.py` (zero tests fails), runtime identity binding, three-valued mutation scoring; review and merge gate in Archon [Claim] [R10 §7] | [Obs] none in repo; systemd unit sets `IS_SANDBOX=1` for root runs; agent permissions in Archon [Unk] [R10 §8] | [Obs] runtime host: stripped env, loopback bearer token, "not a sandbox"; lap worktrees in Archon [Unk] [R10 §8] | [Inf] issue/PR text reaches Archon agents; mitigations are policy inputs enforced in Archon [Claim] [R10 §8] |
| R11 | [Obs] 57 unittest functions for tools; no CI; no skill evals [R11 §7] | [Obs] Playwright/axe templates, TDD loop, parity and layout scores; parity rests on the builder's self-reported `clone` column; preflight parity step always exits 0 (re-checked `parity.py:218-224`, `replica-deploy/SKILL.md:33`) [R11 §5, §7] | [Obs] none; prose rules (no signups, user's "go") [R11 §8] | [Obs] none [R11 §8] | [Obs] none; public web pages and review text ingested without data-not-instructions guidance [R11 §8] |

**Supply chain and secrets.** These two security sub-dimensions are not separate columns above. Supply-chain
evidence per repo is in the §4b D9 cells (with citations); secret handling is compared in §4b D15 below, and in
more detail in the companion capability matrix (`02-capability-engineering-matrix.md`, capability D3).

### 2d. Observability, cost, improvement, reference-driven support, maturity

| Repo | Observability | Cost / token control | Continuous improvement | Reference-driven / reverse-engineering | Maturity signals |
|---|---|---|---|---|---|
| R01 | [Obs] `job.json` + 2 s polling dashboard; no cost or time [R01 §8] | [Obs] opus/sonnet tiering; ≤3 rounds; all 4 reviewers on every job; no budget [R01 §9] | [Obs] none in v1; v2 credits commenter feedback [Claim] [R01 §10] | [Obs] not applicable; agent-browser screenshots only [R01 §11] | [Obs] one commit added the folder (2026-10-02); no tests, CI or releases; demo [R01 §1] |
| R02 | [Obs] recorder logs, session/attempt JSON; no token or cost [R02 §8] | [Obs] iteration cap 10 (agent-enforced), post-once trigger, proportional workflow [R02 §9] | [Obs] manual, review-driven; 12 greploop-iteration commits [R02 §7, §10] | [Obs] before/after captures and assertion-annotated video; no parity [R02 §11] | [Obs] 37 commits Jul-Oct 2026; no releases, no CI; 1,374 stars [R02 §1] |
| R03 | [Obs] run manifest per wave, status snapshot, `gh-quota-on-exit` lines, plan usage %; no per-card tokens or dollars [R03 §8] | [Obs] complexity model ladder, plan-usage pause, throttle, GraphQL point budgeting; "~20x fewer points" [Claim]; no token/$ budget [R03 §9] | [Obs] optional external calibration on allowlisted files (default off); correction-prevention tickets; eval-staleness Stop hook for authors [R03 §10] | [Obs] screenshots at 3 viewports, `runtime_compare.py`; no spec extraction [R03 §11] | [Obs] tags v1.2.0 → v3.1.2; 62 suites + CI; active Oct 2026; 457 stars [R03 §1] |
| R04 | [Obs] console prints only [R04 §8] | [Obs] none; inverted token estimator; ~1,000-line prompts per generation [R04 §9] | [Obs] none [R04 §10] | [Obs] "validate against official examples" rule, not followed by the hook generator [R04 §11] | [Obs] dormant since 2025-11-12; 7 unreviewed community PRs [R04 §2.4] |
| R05 | [Obs] `run.json` transitions + raw SDK stream logs; token/cost only on the eval branch [R05 §8] | [Obs] max-turns 30, timeout 600 s, attempts default 1, 12 KB feedback tail; no routing or budget [R05 §9] | [Obs, unmerged] frozen-baseline, one-change-at-a-time eval discipline applied in v4; example `improve-factory` skill [R05 §10] | [Obs] not applicable [R05 §11] | [Obs] 12 commits in one week; no releases; 17 stars; main work in open PRs #4, #5, #8 [R05 §1, §15] |
| R06 | [Obs] GitHub artifacts only [R06 §8] | [Docs] `disable-model-invocation: true` keeps idle context cost at zero in Claude Code [R06 §9]; ~3k tokens per full chain [Inf]; no budgets [Obs] | [Obs] none on main; behavioural-eval roadmap unmerged [R06 §10] | [Obs] not applicable [R06 §11] | [Obs] ~278 commits; one stale tag; high skill churn; CI green; 419 stars [R06 §1] |
| R07 | [Obs] pino structured logs, MCP progress notifications, `doctor`; no runtime cost (no model calls) [R07 §8] | [Obs] token-first policy; compact schemas, summary-first views, response byte caps; dated efficiency checkpoints incl. negative results [R07 §9] | [Obs] developer-side agent-experience eval (not in CI); measured optimization checkpoints [R07 §10] | [Obs] core purpose: spec extraction from shipped artifacts, version and source-to-bundle comparison, partial-order behaviour comparison, obligation ledger; runtime not executed [R07 §11] | [Obs] ~4,296 commits; 38 releases; 6 majors in 3 months; unstable main CI [R07 §1] |
| R08 | [Obs] per-run log, context-window line and token usage per iteration, stream event hook; no dollars [R08 §8] | [Obs] `maxIterations`, idle and completion timeouts; no token/$ budget; `run()` recreates worktree + container per iteration [R08 §9] | [Obs] issue-driven dogfooding, ADRs, out-of-scope records [R08 §10] | [Obs] not applicable [R08 §11] | [Obs] 44 npm versions; latest v0.12.0 (2026-06-29); OIDC-attested releases; breaking `v1` branch pending; 8.6k stars [R08 §1, §7] |
| R09 | [Obs] SQLite (7 tables) with tool-call spans, gate evidence, per-phase cost and context occupancy, process registry; subagents untraced [R09 §8] | [Obs] per-agent model routing; code phases for known commands; no enforced budget or timeout; $182.83 single run [Claim, issue #13] [R09 §5, §9] | [Obs] manual observe → edit loop; lessons as code comments [R09 §10] | [Obs] not applicable [R09 §11] | [Obs] squashed single commit per branch; no tests, CI or releases; 999 stars [R09 §1] |
| R10 | [Obs] launch decisions logged with reasons; status passthrough; no metrics or tokens [R10 §8] | [Obs] launch gate suppresses empty and duplicate laps; no ceilings (PR #58 unmerged) [R10 §9] | [Obs] `incidents.md` (65 entries) as a lesson log; mutation-tested checkers [R10 §10] | [Claim] not applicable; PRD → backlog via Archon [R10 §11] | [Obs] created 2026-09-01; 265 commits; no releases, CI or licence; pin to unmerged Archon branch (92 ahead, 575 behind) [R10 §1, §2.2] |
| R11 | [Obs] artifacts only (build log, bugs, deploy record) [R11 §8] | [Obs] maths offloaded to tools; ~5.7k characters of always-loaded descriptions; no routing [R11 §9] | [Obs] product-level loops only [R11 §10] | [Obs] core purpose at product level: sourced recon, ID-keyed spec, evidence + confidence data model, feature ledger, colour-invariant layout diff, provenance-enforced review mining [R11 §11] | [Obs] single commit, v1.0.0, no CI, 12 unmerged issues/PRs; 4,540 stars [R11 §1] |

---

## 3. Execution-model comparison

### 3.1 Which repository implements which model

| Model | Repositories | Who decides the next step | Where bounds live |
|---|---|---|---|
| Deterministic orchestration | R05, R09, R08 (library loop and caller scripts), R10 consumer (scheduling layer), R01 v2 spine (unmerged) | Code | Code: R05 `--attempts`, R09 `MAX_FIX_LOOPS`, R08 `maxIterations` [Obs] [R05 §5, R09 §5, R08 §5] |
| Autonomous agent coordination | R01 v1, R06 `/codex-issue-coordinator`, R03's outer orchestrator session, R10 via Archon [Claim] | LLM orchestrator over subagents or threads | Prose: R01 `MAX_RESUMES = 2` in skill text; R06 3-strike rule [Obs] [R01 §5, R06 §5] |
| Hybrid | R03 (JS lanes + script gates + LLM lane agents + LLM wave planner), R08 (code loop around an autonomous agent), R09 at its outermost layer, R07 (deterministic tools under an LLM host) | Code for structure, LLM for content and (R03) for wave planning | Mixed [Obs] [R03 §5, R08 §5, R09 §5, R07 §5] |
| Skill-driven workflows | R02, R06, R11, R04, R01 (delivered as a skill) | LLM following Markdown, often human-sequenced | Prose; scripts gate only when the LLM runs them [Obs] [R02 §5, R06 §5, R11 §5, R04 §5.1] |

### 3.2 How control actually flows (traced paths from the reports' §5)

**Deterministic: R05 path A** [Obs] [R05 §5]. `cli.main` → `runner.run` → strict `Config.load` → prompts read before
setup → attempt loop: SDK `agent()` with `dontAsk` → `summary.md` → checks in order. A shell check exits 0
(pass), 1 (retry with a 12 KB log tail) or other (stop); an agent check returns a schema-validated `CheckResult`.
A retry re-runs the worker and then all checks. The run ends `passed` or `needs_attention`.

**Deterministic: R09 path 2** [Obs] [R09 §5]. ADW script pins the baseline → planner phase with
`artifacts_exist` gates → code phase commits → builder phase → loop of code test phase and builder fix (≤3) →
reviewer with `verdict_consistent` gate and revise (≤2) → `verified = test.passed and review.approved` → capture
diff → documenter → `run.finish(accepted=verified)`.

**Deterministic loop with autonomous iteration: R08 path 1** [Obs] [R08 §5]. `run()` validates options → env from
declared keys → temp branch → per iteration: fresh worktree and container → prompt shell expressions run in the
container → agent CLI with permissions bypassed (`Orchestrator.ts:143`) → completion signal or timeout → commits
merged to the host branch → container and clean worktree removed.

**Autonomous coordination: R01 paths A and B** [Obs] [R01 §5]. The orchestrator LLM creates the job (atomic
`mkdir`), spawns spec-writer then a named builder, spawns 4 reviewers in one message, waits for all four files,
then the approver writes `APPROVE` (job 002, merged to local `main` with no human) or `ESCALATE` (job 001,
human ran `/factory approve`). Every transition is the LLM writing `job.json`.

**Autonomous coordination: R06 path 2** [Obs] [R06 §5]. Pinned Codex coordinator thread builds a dependency
graph from GitHub, dispatches ≤2 worker threads running `/task-to-pr`, monitors with `wait_threads`, pauses an
issue after three failed attempts. Codex tool names unverified [Unk].

**Hybrid: R03 paths 1 and 2** [Obs] [R03 §5]. The LLM orchestrator runs precondition scripts, the wave planner
script and an assignee claim, then launches the Workflow script. In JS: pre-flight batch → classify → build →
QA → review lanes, each an `agent()` with a JSON-schema exit. The reviewer calls the merge gate, whose exit code
(2/5 rebase, 4 retry, 6 re-review, 7/8 human, 9 halt) becomes a board move. Path 2: policy exit 7 → Blocked →
human `done` comment → next wave's planner (script) moves the card to Review → gate re-checks head, scope and
approver permission, re-reads approval before merging.

**Skill-driven: R11 paths A and B** [Obs] [R11 §5]. The user invokes each skill; `features.csv` is created by
recon, mutated by build, scored by `parity.py` (exit 0 unless `--fail-under`); `sweep.py` exits 1 on any brand
hit and the LLM is told to refuse deploy. **R02 path A** [Obs] [R02 §5]: the agent runs `github_review.py start`
and `wait`; code decides freshness, the agent decides what to fix and when to stop. **R04 trace 2** [Obs]
[R04 §5.3]: guide → `hook_factory.py` → generator → installer; static reading shows the output does not match the
documented hook contract.

**Tool platform: R07 paths 1 and 2** [Obs] [R07 §5]. Host LLM calls a tool → typed, admitted, deterministic
analysis → content-addressed Evidence in the session ledger, marked untrusted when it carries target content →
ledger evaluation per obligation against the authority lattice.

### 3.3 Observed strengths and failure modes per model

| Model | Observed strengths (evidence) | Observed failure modes (evidence) |
|---|---|---|
| Deterministic orchestration | Bounds and outcomes cannot be skipped by the model: R05 three-valued check contract with fail-closed SDK handling, all tested with fake agents [Obs] [R05 §7, §12]; R09 "success must be earned" phases and a single acceptance call [Obs] [R09 §12]. Orchestration code is unit-testable [Obs] [R05 §7] | Code-owned flow did not guarantee correct gates: R09 placeholder checks exit 0 and the claims gate checks existence only [Obs] [R09 §7]; R05 removed its reviewer tamper check and the author's data shows false completions that passed tests and review (v2 3/9; v3 6/36) [Obs, author data] [R05 §8, §14]. Missing operational bounds: R09 has no subprocess timeout or spend cap [Obs] [R09 §5]; R08 bypasses agent permissions by default [Obs] [R08 §8]; R08 recreates worktree + container per iteration [Obs] [R08 §9]. Value over a prompted baseline not shown: 30/36 vs 29/36 [Obs, author data] [R05 §14] |
| Autonomous agent coordination | Low code, rich inspectable artifacts (R01 example specs and build reports with per-AC evidence) [Obs] [R01 §7]; policy-based escalation produced a precise human question in job 001 [Obs] [R01 §5] | Instruction non-compliance undetected: 3 of 4 UX/UI reviews skipped the required browser check [Obs] [R01 §7]. Self-contradiction: orchestrator writes `decision.md` despite "never write decisions" (re-checked `SKILL.md:9-10` vs `:151-154`) [Obs] [R01 §5]. No crash resume [Obs] [R01 §6]. Effectiveness of the R06 coordinator and Archon cannot be observed (not executed; Archon not inspected) [Unk] [R06 §5, R10 §17] |
| Hybrid | Safety-critical decisions in scripts with exit codes routed to deterministic actions [Obs] [R03 §5]; GitHub as the only state makes "run" equal "resume" [Obs] [R03 §6]; orchestration script tested by stubbing `agent/pipeline/log` [Obs] [R03 §7]. R07 keeps every tool deterministic and typed while the host plans [Obs] [R07 §5] | The LLM layer still governs much: wave planning and lifecycle follow 816 + 420 lines of prose [Obs] [R03 §14]; the rebuild cap's root-cause hash is computed by prose, no script [Obs] [R03 §5]; doc/code drift (`humanApprovesMerge` documented as serializing Review but never read) [Obs] [R03 §16]; alternative backends weaken the permission posture (legacy bypass; Codex `approval_policy="never"`) [Obs] [R03 §8] |
| Skill-driven workflows | Low context cost: zero idle cost for opt-in skills in Claude Code [Docs] [R06 §9]; portability across hosts [Obs] [R06 §2]; explicit human gates for credentials and deploy [Obs] [R11 §5]; deterministic tools handle the maths [Obs] [R11 §9] | Gates not enforced: R11 parity step cannot fail the deploy by exit code (re-checked) [Obs] [R11 §5]; R02 iteration cap is honour-system [Obs] [R02 §5]; R06 `/task-to-pr` repair loop has no numeric bound [Obs] [R06 §5]. Platform semantics conflicts: R04 guides assume multi-turn Q&A in subagents, which the docs rule out [Obs+Docs] [R04 §3]. Broad triggers: R11 recon fires on "how does X work" [Obs] [R11 §4]. No behavioural evals anywhere in this group [Obs] |

### 3.4 Code versus prose enforcement map

Code = enforced by executable code in the repo; Prose = instruction only; Ext = in an external dependency;
Absent = not present; n/a = role or action does not exist.

| Repo | Step order | Retry / iteration bound | Reviewer cannot modify work | Merge or consequential-action gate | Untrusted-input guard | Spend bound |
|---|---|---|---|---|---|---|
| R01 | Prose [R01 §5] | Prose (`MAX_RESUMES` in skill text) [R01 §5] | Prose (all agents have Write, Bash) [R01 §3] | Prose (approver ESCALATE list) [R01 §8] | Absent (v1) [R01 §8] | Absent [R01 §9] |
| R02 | Prose [R02 §5] | Prose (cap agent-enforced) [R02 §5] | n/a (external bot reviewer) | Prose ("do not merge unless instructed") [R02 §5] | Code, partial (trusted bot logins) [R02 §8] | Absent [R02 §9] |
| R03 | Code per card; Prose per wave [R03 §5] | Prose in default backend; Code in legacy runner [R03 §5] | Prose (Tester writes tests, not app code) [R03 §3] | Code (merge gate, policy, approval) [R03 §5] | Absent [R03 §8] | Code, partial (plan-usage pause) [R03 §5] |
| R04 | Prose [R04 §5.1] | Absent [R04 §5.1] | n/a | Prose (Q&A, installer prompt) [R04 §5.1] | Absent [R04 §8] | Absent (kill switch ineffective) [R04 §5.4] |
| R05 | Code [R05 §5] | Code (`--attempts`) [R05 §5] | Prose on main [R05 §8] | Code, structural (runner never commits or pushes) [R05 §5] | Prose [R05 §8] | Code, partial (turns, timeout; no tokens) [R05 §9] |
| R06 | Prose [R06 §5] | Prose (coordinator only) [R06 §5] | Prose [R06 §8] | Prose + Code for invocation opt-in [R06 §8] | Prose (scope rules) [R06 §8] | Absent [R06 §9] |
| R07 | n/a (host decides) | n/a | n/a | Code (setup dry-run and approval) [R07 §5] | Code (marking, not enforcement) [R07 §8] | Code, partial (response byte caps) [R07 §9] |
| R08 | Code (loop) + caller code [R08 §5] | Code (`maxIterations`) [R08 §5] | Absent (review agent in same sandbox, bypassed permissions) [R08 §7-8] | Absent in library; label + human PR merge in its own CI [R08 §5] | Code, partial (inert-arg marker; explore privilege split) [R08 §8] | Code, partial (iterations, timeouts) [R08 §9] |
| R09 | Code [R09 §5] | Code (`MAX_FIX_LOOPS`, `MAX_REVISION_LOOPS`) [R09 §5] | Code, post-hoc (`writes: []` rollback) [R09 §8] | Absent [R09 §5] | Absent [R09 §8] | Absent (measured only) [R09 §9] |
| R10 | Ext [R10 §5.1] | Ext [R10 §5.1] | Ext [R10 §7] | Ext + Code (STOP/PAUSE, policy-input injection) [R10 §5.4] | Ext [R10 §8] | Code, partial (launch gate) [R10 §9] |
| R11 | Prose, human-sequenced [R11 §5] | Prose [R11 §5] | n/a | Prose (user's "go") + Code when run (`sweep.py`, `listing.py` exit 1) [R11 §5] | Absent [R11 §8] | Absent [R11 §9] |

### 3.5 What the evidence says about the value of orchestration

- Only R05 measures orchestration against baselines (synthetic single-file Python tasks; author data,
  recomputed from published `runs.json`, not re-run) [Obs] [R05 §7, §9]: v1 easy tasks 36/36 in every mode with
  Factory at ≈2.1× median latency and ≈2.5× cost; v2 harder cases 6/9 vs 1-3/9 at higher cost; v3 30/36 vs 29/36
  against Claude Code with a prompted reviewer subagent, faster (48.6 s vs 75.5 s median) at similar cost; v4 a
  reviewer-prompt change gave no gain.
- R03 and R10 justify mechanisms with dated incident notes; the code is observed, the incidents are [Claim]
  [R03 §10, R10 §10].
- R09's efficiency rationale ("an agent rediscovering `bun test` cost ~1M tokens") is an anecdote in a comment
  [Claim] [R09 §9].
- No repository measures first-pass acceptance, human interventions per task or cost per accepted deliverable on
  real work.

---

## 4. Per-dimension qualitative ratings

**Scale.** Strong = enforced in code or config and evidenced by tests or a traced path. Adequate = present and
partly enforced, or enforced with material gaps or without tests. Weak = present only in prose, or enforced with
serious evidenced gaps. Absent = not present. n/a = the action or role the dimension gates does not exist in
the project by design. Unknown = lives outside the evaluated code. Ratings are per dimension. **They are not summed, averaged or compared across categories, and no
row total exists.** A Strong in one repository's dimension does not make it "better" than a repository in
another group.

### 4a. Control and verification

| Repo | D1 Control-plane enforcement | D2 Recovery and resume | D3 Factory self-testing | D4 Independent verification of produced work | D5 Enforced approval gates |
|---|---|---|---|---|---|
| R01 | Weak: LLM writes `job.json`, no transition check [R01 §5] | Weak: state on disk, no re-entry after crash [R01 §6] | Absent: no tests or CI [R01 §7] | Weak: separate subagents, but required browser checks skipped 3/4 undetected [R01 §7] | Weak: ESCALATE policy prompt-only; APPROVE merges with no human [R01 §8] |
| R02 | Weak: order and cap in Markdown [R02 §5] | Adequate: recorder recovery states, idempotent `stop`, re-runnable `wait` [R02 §5-6] | Adequate: 71 cases incl. adversarial; no CI [R02 §7] | Adequate: third-party review bound to head in code; functional evidence self-reported [R02 §7] | Weak: "do not merge" prose; one code flag for untracked recorder [R02 §5] |
| R03 | Strong: per-card JS lanes with schema exits and exit-code routing; wave planning prose [R03 §5] | Strong: board-only state, stranded sweep, halt file [R03 §5-6] | Strong: 62 suites incl. stubbed orchestration test; CI on 2 OS [R03 §7] | Strong: project checks on base-merged head inside lock, head-pinned merge [R03 §12] | Strong (mechanism), with a permissive default: policy classifier + head/scope-pinned approval re-read before merge; shipped `merge_policy.default` is `"auto"`, so the model-run Reviewer self-merges ordinary PRs and a human is asked only on size (>400 lines), category or migration triggers; category detection is label/path-glob/substring matching [Inf: bypassable by naming]; spoofable on a shared token [Inf] [R03 §8, §17; re-checked `merge-policy.py:133`, `config-schema.json:135`] |
| R04 | Weak: no orchestrator code; step order exists only as prose in `/build` and the guides [R04 §5.1-5.2] | Absent [R04 §6] | Absent: no tests; CI syntax only [R04 §7] | Absent: same-LLM expected outputs, never run [R04 §7] | Weak: Q&A and installer prompts [R04 §5.1] |
| R05 | Strong: loop, bounds and outcomes in code, tested [R05 §5, §7] | Weak: logs preserved, no resume [R05 §5] | Strong: 28 cases with fake agents; CI with ruff [R05 §7] | Adequate: command checks + fresh-session review; no tamper check on main; held-out grader unmerged [R05 §7-8] | n/a: the runner never commits, pushes or merges, so there is no consequential action to gate; the human reviews the preserved workspace [R05 §5] |
| R06 | Weak: gates, waits and retries are prose [R06 §5] | Weak: resume by reusing branch/PR (prose) [R06 §6] | Adequate: 28 tests for renderer and checks; none for skill behaviour [R06 §7] | Weak: fresh-subagent review required in prose only [R06 §7] | Weak: invocation opt-in enforced; merge gates prose [R06 §8] |
| R07 | n/a: no orchestration by design; the host decides [R07 §5] | Adequate: Result-typed errors, cleanup retry; bundle import [Claim] [R07 §5-6] | Adequate: very large suite and real-engine lanes; main CI unstable, mutation non-blocking [R07 §7] | Adequate (reconstruction claims): fail-closed ledger; caller-supplied, integrity-only proofs [R07 §5-6] | Adequate: setup dry-run + approval; tools defer to host [R07 §5] |
| R08 | Adequate: library loop and timeouts in code; multi-step flow is caller code [R08 §5] | Adequate: session resume/fork, preserved worktrees, saved patches [R08 §5-6] | Strong: ~1,416 cases; CI on push only, no typecheck or lint [R08 §7] | Weak: caller-defined; review agent in same sandbox [R08 §7] | Weak: none in library [R08 §5] |
| R09 | Strong: ADW scripts own order, loops and acceptance [R09 §5] | Adequate: `--adw-id` rejoins the session and each agent's context in code; no phase skip on rerun; no subprocess timeout, hung agents killed by hand [R09 §5-6] | Absent: no tests or CI [R09 §7] | Weak: placeholder checks pass; claims gate checks existence only [R09 §7] | Absent: "no human-in-the-loop approval phase" [R09 §5] |
| R10 | Unknown: stage control in Archon; scheduling is code [R10 §5.1] | Adequate (in repo): stuck sweeper, durable wake, STOP/PAUSE [R10 §5.3] | Adequate: 83 methods + guard self-mutation; no CI; conformance skipped by default [R10 §7] | Unknown: review and merge in Archon; in-repo identity binding is a strong component [R10 §7, §12] | Unknown: `merge_mode` forwarded to Archon; local brakes in code [R10 §5.4] |
| R11 | Weak: human sequencing, prose [R11 §5] | Weak: files allow re-running a skill; no state machine [R11 §6] | Adequate: 57 tool tests with an independent PNG encoder; no CI [R11 §7] | Weak: parity on self-reported column; preflight parity exits 0 [R11 §5, §11.5] | Weak: deploy "go" is prose [R11 §5] |

### 4b. Security posture

| Repo | D6 Permission model | D7 Isolation | D8 Untrusted-input handling | D9 Supply-chain hygiene | D15 Secret handling |
|---|---|---|---|---|---|
| R01 | Weak: none shipped; frontmatter tool scoping only, read-only by prompt [R01 §8] | Weak: worktree/port/session per job; host execution [R01 §8] | Weak: no guidance; target `AGENTS.md` canonical [R01 §8] | Weak: unpinned `agent-browser`, runtime-fetched guide [R01 §8] | Weak: none specified; security reviewer checks commits for keys (prose) [R01 §8] |
| R02 | Weak: pre-approved unpinned global npm install, `gh pr edit *` [R02 §8] | Weak: worktree per task [R02 §8] | Weak: the code's trusted-login filter authenticates which review counts as a score, but the bot and PR-thread text the agent acts on is unsanitised and guarded only by prose ("evaluate each finding") [R02 §8] | Adequate: Playwright pinned with integrity, `--ignore-scripts`; other CLIs unpinned [R02 §8] | Weak: "never record secrets" (prose); credentials delegated to CLI logins; agent fetches a Vercel bypass token [R02 §8] |
| R03 | Weak: session allowlist [Docs], but bypass in legacy builder, `approval_policy="never"` in Codex lanes [R03 §8] | Weak: worktrees enforced by hook; PR code `eval`ed on host [R03 §8] | Absent: no guidance; issue text reaches push/merge-capable agents [R03 §8] | Weak: `curl \| bash` without checksum; `npx skills@latest` [R03 §8] | Adequate: `guard-secrets` and `guard-key-literals` hooks (fail open); migrate DB URL from `.env`, not the session [R03 §8] |
| R04 | Weak: generated agents default to Bash/Write [R04 §8] | Absent [R04 §8] | Absent: outsider issue text to write-token agent [R04 §8] | Weak: `.pyc` in ZIPs; tag-pinned actions [R04 §8] | Weak: secret regexes in the hook validator (for generated hooks); write PAT exposed to the triage agent [R04 §8] |
| R05 | Adequate: `dontAsk`, allowlist, denial fails, no ambient settings; unrestricted Bash [R05 §8] | Weak: live checkout by default; worktree opt-in [R05 §8] | Weak: prompt-level "treat as data" [R05 §8] | Adequate: `uv.lock`, `--locked` CI; tag-pinned actions [R05 §8] | Weak: commands get the full parent env incl. API keys and `GH_TOKEN`; `.env` gitignored [R05 §8] |
| R06 | Weak: none configured; opt-in invocation only [R06 §8] | Weak: worktrees by prose; renderer network-blocked [R06 §8] | Weak: scope rules; untrusted-browser rule dropped [R06 §8] | Strong: exact npm pins with integrity, SHA-pinned actions; unpinned `npx skills add` install [R06 §2, §8] | Absent: only a "remove secrets" line in the bug template [R06 §8] |
| R07 | Adequate: per-tool effects drive annotations; enforcement depends on host [R07 §8] | Weak: "not a sandbox"; process bounds only [R07 §8] | Adequate: result-level untrusted marker + instructions; labelling only [R07 §8] | Adequate: exact pins, SHA-pinned actions, pinned registration; `@latest` in skill setup path [R07 §8] | Weak: redaction and no env persistence are [Claim]; bridge capability tokens not traced [R07 §8, §16] |
| R08 | Weak: bypass by default incl. `noSandbox()`, contradicts ADR 0015 [R08 §8] | Adequate: container/VM per run, env allow-list; host `.git` RW, open network, secrets in argv [R08 §8] | Adequate: privilege-split explore job, untrusted framing, inert-arg marker in code; templates pass issue text to bypassed agents [R08 §8] | Weak: runtime deps caret-ranged (lockfile present); the default `sandcastle init` scaffolds use unpinned images, `curl \| bash` and `@latest`; CI installs Claude Code unpinned. OIDC-attested releases cover what it publishes, not what it consumes [R08 §2, §7-8] | Adequate: only keys declared in `.sandcastle/.env` pass in; values in `docker run -e` argv; `GH_TOKEN` in a networked sandbox [R08 §8] |
| R09 | Adequate: tool allowlist + post-hoc write boundary with rollback; bash everywhere [R09 §8] | Absent: live checkout, full env [R09 §8] | Absent [R09 §8] | Weak: unpinned Python deps and Pi [R09 §8] | Weak: agents inherit the full operator env; tracer stores full prompts and tool args [R09 §8, §13] |
| R10 | Unknown: agent permissions in Archon; root + `IS_SANDBOX=1` [R10 §8] | Weak (in repo): runtime host not a sandbox; Archon worktrees [Unk] [R10 §8] | Unknown: Archon side [R10 §8] | Adequate: Archon pinned by SHA and verified clean; root `curl \| bash` bootstrap unpinned [R10 §8] | Adequate: runtime host strips provider credentials from the app's env; token file mode 600 [R10 §8] |
| R11 | Weak: none; prose rules [R11 §8] | Absent [R11 §8] | Absent [R11 §8] | Weak: installs from unpinned `main`; unpinned Playwright in skill text [R11 §8] | Weak: prose (never type keys; `.env.example` names only) [R11 §8] |

### 4c. Operations, improvement, reference-driven support, maintenance

| Repo | D10 Observability | D11 Cost / token control | D12 Continuous improvement | D13 Reference-driven / parity | D14 Maintenance and maturity |
|---|---|---|---|---|---|
| R01 | Adequate: live job dashboard; no cost or time [R01 §8] | Weak: tiering, ≤3 rounds; fixed 4 reviewers [R01 §9] | Absent [R01 §10] | Absent [R01 §11] | Weak: single-commit demo, no licence [R01 §1] |
| R02 | Weak: per-tool diagnostics only (recorder logs, session/attempt JSON, structured stdout); no view of the workflow itself [R02 §8] | Weak: agent-enforced cap, duplicate-trigger guard [R02 §9] | Weak: manual, review-driven [R02 §10] | Weak: visual evidence; no parity [R02 §11] | Adequate: active, dogfooded; no CI; mixed licence [R02 §1] |
| R03 | Adequate: run manifest, status, quota lines; no per-card tokens [R03 §8] | Adequate: ladder, usage pause, throttle; no budget [R03 §9] | Adequate: bounded calibration (external, off), correction tickets, eval-staleness hook [R03 §10] | Weak: screenshots, runtime comparison; no spec extraction [R03 §11] | Strong: releases, CI, active, incident-driven [R03 §1, §10] |
| R04 | Weak: console prints [R04 §8] | Absent: inverted estimator, large prompts [R04 §9] | Absent [R04 §10] | Absent [R04 §11] | Weak: dormant 11 months [R04 §2.4] |
| R05 | Adequate: state file + raw streams; tokens only on eval branch [R05 §8] | Adequate: turn, time and attempt bounds in code [R05 §9] | Weak on main (example `improve-factory` skill, prose); Strong on the unmerged eval branch (frozen-baseline, one-change discipline) [R05 §10] | Absent [R05 §11] | Weak: one week of history, key work unmerged, no licence [R05 §1] |
| R06 | Weak: GitHub artifacts only [R06 §8] | Adequate: zero idle context [Docs], phase skipping; no budgets [R06 §9] | Absent on main [R06 §10] | Absent [R06 §11] | Adequate: active, CI green; high churn [R06 §1] |
| R07 | Adequate: structured logs, progress, `doctor` [R07 §8] | Strong: token-first policy with measured, dated checkpoints [R07 §9] | Adequate: agent-experience eval (not in CI), measured optimizations [R07 §10] | Strong: artifact-level extraction, comparison, fail-closed ledger; proofs caller-supplied [R07 §11] | Adequate: very active, many releases; 6 majors in 3 months, unstable main [R07 §1] |
| R08 | Adequate: per-iteration tokens, event hook; no dollars [R08 §8] | Adequate: iteration and timeout bounds; no budget [R08 §9] | Weak: documents and dogfooding [R08 §10] | Absent [R08 §11] | Strong: attested releases, ADRs, tests; pre-1.0 churn [R08 §7] |
| R09 | Strong: SQLite trace with spans, gate evidence, per-phase cost and occupancy; subagents untraced [R09 §8] | Weak: measured, not enforced; no timeout [R09 §5, §9] | Weak: manual loop; lessons in comments [R09 §10] | Absent [R09 §11] | Weak: squashed commits, no tests, drift [R09 §1, §7] |
| R10 | Weak: in repo, only launch-decision reasons; run status and events are Archon's, passed through; no metrics or tokens [R10 §8] | Adequate: empty-lap suppression; no ceilings [R10 §9] | Adequate: incident log + mutation-tested guards [R10 §10] | Absent [R10 §11] | Weak: 7 weeks, no releases/CI/licence, daily pin to unmerged branch [R10 §1] |
| R11 | Weak: artifacts only [R11 §8] | Weak: tool offloading; no controls [R11 §9] | Absent (pack) [R11 §10] | Adequate: structured spec and ledger; parity self-reported [R11 §11] | Weak: single commit, unmerged fixes [R11 §1] |

### 4d. Rating scales and divergences from D2

The companion capability matrix (`02-capability-engineering-matrix.md`, "D2"; §1 heatmap and its note "Rating
scales and divergences from D1", both as reconciled on 2026-10-22) rates overlapping dimensions on its own scale.
Mapping:

| This document | D2 | Difference in definition |
|---|---|---|
| Strong | S | Here Strong needs code or config enforcement evidenced by tests or a traced path, and can carry a noted gap; D2's S needs code enforcement with no material gap and rates tests separately (C3) |
| Adequate | A | Equivalent (present and partly enforced) |
| Weak | W | Equivalent (prose only, or code with serious gaps); D2's W also names "bypassed by default" |
| Absent | – | Equivalent |
| Unknown | U | Equivalent (outside the evaluated code; here used for Archon) |
| n/a | n/a | Equivalent |
| "(unmerged branch: …)" in the cell | b | Equivalent marker for branch-only evidence |

Dimension boundaries: D1↔A1; D2↔A3 (resume; A4 timeout and failure recovery is compared only partly, because this dimension rates resume: R02, R05 and R08 are S on A4 against Adequate, Weak and Adequate here); D3↔C3; D4↔C1; D5↔C2; D6↔D1 (D2 rates
judge protection separately as D6); D7↔D2; D8↔D4; D9↔D5; D15↔D3; D10↔E1; D11↔E2 + E4 (context footprint
included here); D12↔F1; D13↔G1-G6; D14 has no D2 equivalent.

**Status after both documents reconciled.** On every mapped cell (D1-D12 and D15 against A1, A3, C1-C3, D1-D5,
E1, E2, F1), the two documents now agree except for the four cells below. D13 (reference-driven, one rating
here against six D2 capabilities) and D14 (no D2 equivalent) are not compared cell by cell.

Cells changed in this document to reach agreement, each after re-checking the evidence:
- First pass (verifier P1-8, P2-1): R09 D2 Weak→Adequate (session rejoin in code) [R09 §6]; R07 D1 "Absent by
  design"→n/a; R08 D8 Weak→Adequate (privilege-split explore job, inert-arg marker) [R08 §8]; R05 D12 → Weak on
  main, Strong on the unmerged branch [R05 §10].
- Second pass (after D2's reconciliation): R04 D1 Absent→Weak (prose step order counts as Weak on this scale)
  [R04 §5.1-5.2]. Three first-pass moves were reverted because the evidence does not support them: R02 D8 back to
  Weak (the code filter authenticates the score source, not the content the agent acts on) [R02 §8]; R08 D9 back
  to Weak (attested releases cover what it publishes; its default scaffolds consume unpinned code) [R08 §8];
  R02 D10 and R10 D10 back to Weak (no workflow-level view in the repo) [R02 §8, R10 §8]. D2 had already moved
  those four cells to W.

**Remaining divergences, with the reason:**

| Cell (here / D2) | Here | D2 | Reason |
|---|---|---|---|
| R08 D5 / C2 | Weak | A | D5 here rates the library, which has no gate; D2's C2 also credits the repository's own CI workflows (privilege-split explore job, label trigger, human PR merge) [R08 §5, §12.8] |
| R09 D6 / D1 | Adequate | W | D6 here credits the post-hoc write boundary with rollback as partial permission enforcement; D2 credits it under B2 and D6 (judge protection) and rates the permission model itself W because every agent has `bash` [R09 §8] |
| R06 D11 / E2 | Adequate | W | D11 here includes context footprint, which D2 rates separately as E4 (S for R06): zero idle context in Claude Code [Docs] [R06 §9]. D2's E2 counts only controls on spend during execution |
| R07 D11 / E2 | Strong | A | Same boundary: D11 here includes the token footprint of the tool surface, measured with dated checkpoints and capped by response byte limits (D2's E4 rates R07 S); D2's E2 requires a budget on agent spend, which R07 does not set [R07 §9] |

**Consistency with D2's note.** D2's final note lists exactly the four divergences in the table above (C2 R08,
D1 R09, E2 R06, E2 R07). A3 R09 (both Adequate/A), D4 R08 (both Adequate/A) and F1 R05 (both Weak on main, Strong
on the branch) agree because this document changed its cells. C2 R05 agrees because D2 moved its cell back to n/a
after re-checking (the runner never commits, pushes or merges, verifier finding P1-8).

---

## 5. Mapping to the six value dimensions

Facts from each report's §14 and §16, split into what the evidence demonstrates and what is only claimed or not
demonstrated. No blended score. Weights (30/20/15/15/10/10) are strategic guidance and are not applied here.

### 5.1 Engineering quality (30%)

| Repo | Demonstrated | Claimed or not demonstrated |
|---|---|---|
| R01 | [Obs] precise file contracts and severity rules; two example jobs with rich specs and per-AC evidence [R01 §14] | No tests or CI; CHANGES loop, rework and parallel jobs not exercised; one self-contradiction [R01 §14] |
| R02 | [Obs] two scripts with explicit failure states, atomic writes, locks; 71 cases incl. imposter and wrong-commit cases [R02 §14] | No CI, lint or type checks; Windows paths excluded from coverage; 4 macOS failures [Claim] [R02 §7] |
| R03 | [Obs] 62 suites, CI on Linux/macOS + Windows smoke, release gated on the tested SHA, fail-closed validators, stubbed orchestration test [R03 §14] | Eval pass rates not in repo [Claim]; doc/code contradictions (`humanApprovesMerge`, 422 claim) [R03 §16] |
| R04 | [Obs] typed stdlib Python, path-traversal and atomic-write code [R04 §14] | No tests; generator defects (object matchers, invented `PrePush`, `exit 1` that does not block); "production-ready" [Claim] [R04 §5.3, §16] |
| R05 | [Obs] ~290 lines with strict schemas and fail-closed handling; 28 cases + CI with lint and format; careful eval hygiene on the unmerged branch [R05 §14] | No type checker; blank-command validation hole on main; tamper checks removed [R05 §7-8] |
| R06 | [Obs] `html_doc.py` with atomic finalize, content-parity hashes, SVG allowlist, network-blocked Chromium, 13 tests incl. fault injection [R06 §14] | Any measured effect of the skills on agent output (author concedes on unmerged branch) [R06 §7] |
| R07 | [Obs] layered architecture with a boundary verifier, exact pins, typed errors, single-source contracts, 2,081 test files [R07 §14] | Main CI unstable on the evaluation day; mutation testing non-blocking; no test results executed [R07 §7, §14] |
| R08 | [Obs] typed internals with timeouts on every lifecycle step, ~1,416 cases, public-type firewall, attested releases [R08 §14] | No typecheck or lint in CI; ADR 0007 and ADR 0015 not honoured by code; stale dogfood script [R08 §16] |
| R09 | [Obs] small typed core with consistent conventions [R09 §14] | No tests or CI; three paths fail as committed (`make_adw.py`, example renames, missing `models.json`) [R09 §7] |
| R10 | [Obs] stdlib fail-closed code, 83 methods with real git and subprocess fixtures, guard self-mutation check, AST audit [R10 §14] | No CI, no licence; conformance test skipped by default; macOS runtime-host bug open [R10 §14] |
| R11 | [Obs] six tools with 0/1/2 exit contracts; 57 tests incl. an independent PNG encoder and a quote-provenance property [R11 §14] | No CI; two confirmed input-handling defects; README walkthrough numbers [Claim] [R11 §16] |

### 5.2 Autonomy and orchestration (20%)

| Repo | Demonstrated | Claimed or not demonstrated |
|---|---|---|
| R01 | [Obs] one autonomous merge (job 002) and one policy escalation (job 001), from committed artifacts [R01 §14] | Multi-round and parallel runs; enforced state machine; crash resume [R01 §14] |
| R02 | [Obs] bounded agent-run review loop with a code freshness gate [R02 §14] | Any orchestrator, scheduler, parallel dispatch or state machine [R02 §14] |
| R03 | [Obs] board → merged PR loop with deterministic exit-code routing; dependency-sized waves; stranded recovery; three backends [R03 §14] | Unattended "walk away" operation at scale [Claim]; Workflow runtime behaviour not executed [R03 §14] |
| R04 | None for software; repo-governance issue automation only [Obs] [R04 §14] | — |
| R05 | [Obs] one deterministic worker-plus-checks loop with bounded retries and three-valued stop [R05 §14] | Multi-stage chaining, parallelism, decomposition; autonomous issue → PR exists only as an example skill [R05 §14] |
| R06 | Instructions only: issue → merge with dependency graphs, 2 workers, repair loops [R06 §14] | No runs evidenced; coordinator is Codex-only [R06 §14] |
| R07 | [Obs] none by design; deterministic tools with admission and serialization [R07 §14] | Parallelism is skill advice only [R07 §14] |
| R08 | [Obs] AFK loop with timeouts and abort; templates; dogfood workflows produced merged `sandcastle-agent[bot]` commits [R08 §14, §16] | Scheduler, queue, dependency engine, concurrency limiter [R08 §14] |
| R09 | [Obs] deterministic chains with bounded loops, typed handoffs and an acceptance model [R09 §14] | Parallel phases, isolation, budgets, timeouts, phase resume, approval phases [R09 §14] |
| R10 | [Obs] in repo: deterministic scheduling, launch gate, parallel laps, durable wake, stuck sweep [R10 §14] | Triage → merge → deploy in Archon [Claim]; the repo's own docs say it "stays supervised" and needs live end-to-end validation [R10 §14] |
| R11 | Deliberately low autonomy; human-sequenced [Obs] [R11 §14] | — |

### 5.3 Development productivity (15%)

| Repo | Demonstrated | Claimed or not demonstrated |
|---|---|---|
| R01 | [Obs] four-step copy-in; live dashboard [R01 §14] | Gains not measured; two small example features only [R01 §14] |
| R02 | [Obs] dogfooding: 12 greploop-iteration commits [R02 §7] | PR-body outcomes [Claim]; gains not measured [R02 §14] |
| R03 | [Obs] one-line install, onboarding wizard, PR size cap, rebase passes, intake from Sentry/PostHog/PRs; own PRs use the pack's format [R03 §14] | Throughput or merge-rate metrics [Claim/Unk] [R03 §14] |
| R04 | [Obs] templates and 69 presets to copy [R04 §14] | "Build a Skill in 2 Minutes" [Claim]; hooks path broken by a hardcoded developer directory [R04 §5.3] |
| R05 | [Obs, author data, not re-run] v1 no acceptance gain at ≈2.1× latency, ≈2.5× cost; v2 6/9 vs 1-3/9 at higher cost; v3 parity with prompted subagent, faster; v4 no gain [R05 §14] | Human time saved not measured [R05 §14] |
| R06 | [Obs] low context cost; reusable plan, spec and review templates [R06 §14] | "Opt-in avoids unnecessary stopping points" [Claim]; no measurements [R06 §14] |
| R07 | [Obs] one-command setup across ~15 clients with dry-run plans and backups [R07 §14] | "Understand a feature and build a version"; external showcases [Claim] [R07 §11] |
| R08 | [Obs] `sandcastle init` scaffolding, one-call `run()`, warm sandboxes, resume/fork, typed structured output [R08 §14] | "Great for parallelizing AFK agents" [Claim]; no throughput data [R08 §14] |
| R09 | [Obs] 12 chains, installer, generators, trace UI [R09 §14] | Example-branch build claim only partly verifiable (traces gitignored); default test phase is a placeholder [R09 §14] |
| R10 | [Obs] one-command `init`, preserving upgrade with backups, `doctor` [R10 §14] | "Filing an issue is the only input" [Claim]; setup still heavy [R10 §14] |
| R11 | [Obs] structured path from an existing app to a build order [R11 §14] | "A booking tool is weeks" [Claim]; no end-to-end run artifacts [R11 §14] |

### 5.4 Security and reliability (15%)

| Repo | Demonstrated | Claimed or not demonstrated / evidenced gaps |
|---|---|---|
| R01 | [Obs] worktree isolation, branch per job, no push, ESCALATE list, clean-checkout precondition, safe markdown renderer [R01 §14] | No permission config, no sandbox, prompt-only read-only on agents with Bash/Write, no post-merge validation [R01 §14] |
| R02 | [Obs] PID-reuse-safe process control, post-once trigger, trusted-login filtering, pinned Playwright with `--ignore-scripts` [R02 §14] | Public upload host by default (0x0.st), unpinned global npm install in `allowed-tools`, no sandbox [R02 §14] |
| R03 | [Obs] merge mutex with proof under lock, head pinning, head/scope-pinned approval, unreadable metadata fails safe to human, read halts, guard hooks [R03 §14] | Shipped default `merge_policy.default: "auto"`: the model-run Reviewer self-merges ordinary PRs; code that avoids the label/path/keyword patterns passes as auto unless the size cap trips [R03 §8, §17]; legacy bypass, Codex lanes without approvals, host `eval` of PR code, fail-open guards, unchecked `curl \| bash`, no untrusted-content rules, approval only as strong as token separation [R03 §14] |
| R04 | [Obs] hook safety linting; backup and rollback installer [R04 §14] | Triage workflow with untrusted text and write token; ineffective kill switch; "Four-Layer Security Model" exists only in docs [R04 §8, §16] |
| R05 | [Obs] no bypass flag, allowlist + `dontAsk` + denial-as-failure, no ambient settings/MCP, process-group timeouts [R05 §14] | Unrestricted pre-approved Bash, no sandbox, in-place workspace, prompt-only reviewer restraint, full env to commands [R05 §14] |
| R06 | [Obs] renderer hardening with tests; SHA-pinned CI; enforced opt-in invocation [R06 §14] | Merge authority, reviewer read-only and no-deploy are prose; injection exposure from issues/PR comments; no retry ceiling in `/task-to-pr` [R06 §14] |
| R07 | [Obs] per-tool effects, untrusted-content marking, bridge capability tokens [Claim for behaviour], prlimit/Job Objects, loopback HTTP default, exact pins [R07 §14] | No sandbox; 15 foreign-code tools; HTTP without auth (documented); integrity without provenance; `@latest` in setup path [R07 §14] |
| R08 | [Obs] env allow-list, non-root container, isolated-VM path, inert-arg marker, privilege-split explore workflow, crash-safe patch application [R08 §14] | Bypass by default incl. `noSandbox()`; host `.git` RW; open network with tokens; secrets in argv; unescaped branch names [Obs code, impact Inf]; `curl \| bash` scaffolds [R08 §14] |
| R09 | [Obs] post-hoc write boundaries with rollback, protected grader files, signal-safe trace finalization [R09 §14] | No sandbox, full credentials, bash everywhere, `git add -A`, enforcement blind spots, no timeout or spend ceiling; $182.83 run [Claim] [R09 §14] |
| R10 | [Obs] SHA-pinned engine with clean-tree checks on authoring roots, authenticated loopback runtime host with stripped env, STOP/PAUSE brakes, policy inputs [R10 §14] | Root + `IS_SANDBOX=1`, unpinned root bootstrap, daily-moving unmerged pin, holdout not isolated by code; merge-gate enforcement not verifiable here [R10 §14] |
| R11 | [Obs] network-free, subprocess-free tools; credentials and deploy reserved to the human (prose) [R11 §14] | No untrusted-content guidance for web and review text; prose-only enforcement; preflight parity cannot fail by exit code [R11 §14] |

### 5.5 Maintainability and adaptability (10%)

| Repo | Demonstrated | Claimed or not demonstrated / constraints |
|---|---|---|
| R01 | [Obs] small surface (~1,960 lines, mostly Markdown); repo specifics only in target `AGENTS.md` [R01 §14] | No licence; README vs BUILD_PROMPT drift [R01 §14] |
| R02 | [Obs] 29 small self-contained files; vendored sources documented [R02 §14] | `greploop` rewrite still labelled upstream-authored; `unslop` drifted from upstream [R02 §16] |
| R03 | [Obs] lifecycles centralized in `run.md`; one skill registry; per-host install links [R03 §14] | Very large prose contracts; GitHub Projects v2 lock-in; duplicated label routing [R03 §14] |
| R04 | [Obs] MIT, plain Markdown, stdlib Python [R04 §14] | ~1,000-line monolithic prompts; inconsistent versions; missing example dirs; dormant [R04 §14] |
| R05 | [Obs] all project specifics in `.factory/`; scope-limiting `AGENTS.md` rules [R05 §14] | No per-stage model; SDK pinned `<0.2`; POSIX-only; no licence [R05 §14] |
| R06 | [Obs] one skill per phase, central policy, migration guide, CI link checks; portable across clients [R06 §14] | ≥10 skills added and removed since March 2026; hardcoded skill count in test [R06 §14] |
| R07 | [Obs] ownership rules, provider-neutral contracts, ports between layers [R07 §14] | 220 tools, ~45 provider dirs, six breaking majors in three months; main ahead of npm [R07 §14] |
| R08 | [Obs] clean plug-in seams, ubiquitous language, 20 ADRs, out-of-scope records [R08 §14] | Very large modules; parsers coupled to each CLI's JSON; pre-1.0 breaking changes [R08 §14] |
| R09 | [Obs] identity/use separation, one-file changes, harness swap point, additive migrations [R09 §14] | Pi-only in v1; hand-synced triad; stamped copies diverge [R09 §14] |
| R10 | [Obs] ownership boundary enforced by audit; manifest-driven defaults; personal/machinery file separation [R10 §14] | Tight coupling to Archon flags, JSON and paths; `consumer.py` slated for retirement (#55-57) [R10 §14] |
| R11 | [Obs] uniform skill structure; stdlib-only editable tools and templates [R11 §14] | Single maintainer and commit; sibling-relative tool paths; brittle repo-shape tests [R11 §14] |

### 5.6 Resource efficiency (10%)

| Repo | Demonstrated | Claimed or not demonstrated |
|---|---|---|
| R01 | [Obs] bounded rounds; builder resume saves re-reading [R01 §14] | Opus for 4 of 7 roles; all reviewers on every job; no tracking; v2 routing [Claim, branch] [R01 §14] |
| R02 | [Obs] progressive loading of references; scaled workflow [R02 §14] | No token, cost or time measurement [R02 §14] |
| R03 | [Obs] GraphQL accounting with cached helper, batching, complexity ladders, usage pause, throttle [R03 §14] | "~20x fewer GraphQL points" [Claim]; no per-card token/$ accounting [R03 §14] |
| R04 | [Obs] CI rate-limit breaker gating the agentic job [R04 §14] | Large always-loaded prompts; opus defaults; undercounting estimator [R04 §14] |
| R05 | [Obs] minimal footprint; per-call turn and time limits; opt-in retries [R05 §14] | No accounting in the runner; Factory costs more than single-session prompting on easy tasks (author data) [R05 §14] |
| R06 | [Obs] small skills, explicit-only loading, confidence floor, compact snapshots [R06 §14] | No routing, caching or cost accounting [R06 §14] |
| R07 | [Obs] token-first policy, compact schemas, summary-first views, byte caps, lazy catalog, dated checkpoints incl. negative results [R07 §14] | Engine runtime costs high (330 s Ghidra cold deadline), not measured here [R07 §14] |
| R08 | [Obs] stdin prompts, bounded output tails, container reuse, session-resume retries, token reporting [R08 §14] | Per-iteration recreation in `run()`; no budgets; templates allow 100 iterations × 10 cycles [R08 §14] |
| R09 | [Obs] code phases for known commands, per-agent routing, evidence truncation, per-phase cost and occupancy [R09 §14] | No enforcement; savings are anecdotes [Claim] [R09 §14] |
| R10 | [Obs] launch-gate rules suppress empty and duplicate laps [R10 §14] | Engine-side savings in pin messages [Claim]; no ceilings [R10 §14] |
| R11 | [Obs] deterministic tools keep computation out of context [R11 §14] | Moderate always-loaded footprint; `imgdiff.py` full decode inefficient [Inf]; no controls [R11 §14] |

### 5.7 Mandatory security and correctness criteria

**Definitions used (an analytical reading of "security and correctness are mandatory acceptance criteria").**
- **Security.** As shipped, with its defaults, the repository does not (a) bypass the host's permission checks or
  pre-approve unrestricted shell without isolation, (b) let untrusted text reach write-capable agents without a
  guard, (c) gate consequential actions (merge, deploy, publish) only by prose, or (d) install or run unpinned
  code in its own setup path. Met = no evidenced violation. Not met = at least one evidenced default-path
  violation. Not demonstrated = the relevant behaviour lives outside the repo, or nothing is evidenced either way.
- **Correctness splits in two.** C1: the repository's own executable logic is shown to do what it claims (tests
  run in CI or equivalent, no evidenced defects in core paths). C2: its mechanism for judging produced work does
  not accept unverified or incorrect work as done.
- "As far as the evidence shows": nobody in this campaign executed code; CI status comes from `gh api` metadata.

| Repo | Security | C1 Own code correct | C2 Produced-work assurance |
|---|---|---|---|
| R01 | **Not met**: no permission config; all agents hold Bash/Write with prompt-only restraint; APPROVE merges with a prompt-only policy boundary [R01 §8] | **Not demonstrated**: no executable core beyond the dashboard; no tests [R01 §7] | **Not met**: required browser checks skipped in 3 of 4 reviews and the approver approved citing them [R01 §7] |
| R02 | **Not met**: public upload host by default; pre-approved unpinned global npm install [R02 §8] | **Not demonstrated**: 71 cases but no CI; 4 macOS failures [Claim] [R02 §7] | **Not demonstrated**: review freshness enforced, but functional evidence is self-reported and merge is left to a human [R02 §7] |
| R03 | **Not met**: legacy builder bypasses permissions on raw issue text; Codex lanes run with no approvals and network; host `eval` of PR code; no untrusted-input rules; `curl \| bash` unchecked [R03 §8] | **Met, as far as the evidence shows**: 62 suites, CI green on main (2026-10-19), gate code read end to end; doc/code drift noted [R03 §7, §14] | **Met for the merge path**: the gate refuses work that fails `verify_commands` on the base-merged head; above that floor, judgement is LLM, and with the shipped `auto` default no human sees ordinary PRs [R03 §7-8] |
| R04 | **Not met**: outsider issue text to a write-token agent; kill switch no-op [R04 §5.4, §8] | **Not met**: hook generator output does not match the documented contract; validator and installer reject each other's formats [R04 §5.3] | **Not met**: expected outputs written by the same LLM and never executed [R04 §7] |
| R05 | **Not met**: unrestricted Bash pre-approved for worker and reviewer; live checkout by default [R05 §8] | **Met, as far as the evidence shows**: 28 cases, CI with lint; one blank-command hole on main [R05 §7] | **Not demonstrated**: reviewer restraint prompt-only on main; author data shows false completions passing tests + review; held-out grader unmerged [R05 §7-8, §14] |
| R06 | **Not met**: no data-not-instructions rule while agents with push (and, under `/factory`, merge) authority act on issue and PR text; merge gates prose [R06 §8] | **Met, as far as the evidence shows (renderer and repo checks only)**: 28 tests, SHA-pinned CI green; skills have no executable logic [R06 §7] | **Not demonstrated**: review and gates in prose; no behavioural evals [R06 §7] |
| R07 | **Not met**: approved setup step and diagnostics use `@latest`; foreign-code tools run with user permissions; HTTP has no auth (documented, loopback default) [R07 §8] | **Not demonstrated**: very large suite, but main CI unstable and the evaluated commit's run cancelled [R07 §1, §7] | **Not demonstrated** (reconstruction claims): ledger is fail-closed, but proofs are caller-supplied and integrity-only; no in-repo proof producer [R07 §5-6] |
| R08 | **Not met**: AFK runs bypass permissions by default, also with `noSandbox()`; host `.git` RW; open network with tokens [R08 §8] | **Met, as far as the evidence shows, with exceptions**: ~1,416 cases, CI green on push to main; ADR 0015 and ADR 0007 not honoured by code [R08 §7, §16] | **Not demonstrated**: verification is caller-defined [R08 §7] |
| R09 | **Not met**: no sandbox, full credentials, bash for every agent, `git add -A`, no timeout or spend cap [R09 §8] | **Not met**: no tests; generator uses a removed API; example branch breaks five ADWs [R09 §7] | **Not met**: default quality phases exit 0; claims gate checks existence only [R09 §7] |
| R10 | **Not met**: root execution with `IS_SANDBOX=1`; unpinned root `curl \| bash` bootstrap; agent permissions unknown [R10 §8] | **Not demonstrated**: 83 methods but no CI; conformance against real Archon skipped by default [R10 §7] | **Not demonstrated**: review and merge in Archon (not inspected); in-repo identity binding and mutation calibration are code [R10 §7, §12] |
| R11 | **Not met**: untrusted web and review text with no guidance; prose-only enforcement; unpinned installs [R11 §8] | **Not demonstrated**: 57 tests, no CI; two confirmed input-handling defects [R11 §7] | **Not met**: parity rests on self-reported entries; preflight parity step cannot fail by exit code [R11 §5, §11.5] |

### 5.8 Components that meet a security or correctness bar on their own (facts, not adoption)

Listed so phase 3 can weigh them; licence limits apply (no licence: idea only; GPL: copyleft).

| Component | Bar it meets | Evidence | Licence |
|---|---|---|---|
| R03 merge gate + policy classifier + head/scope-pinned approval | Enforced consequential-action gate with tests | [Obs] [R03 §12, §7] | MIT |
| R02 `github_review.py` | Review accepted only when bound to the current head by trusted bot; 33 tests | [Obs] [R02 §12, §7] | MIT (folder) |
| R05 hardened SDK options and three-valued check contract | Fail-closed result handling; denial fails the run | [Obs] [R05 §12] | none: idea only |
| R06 `html_doc.py` | Network-isolated, content-parity-checked rendering with tests | [Obs] [R06 §12] | MIT |
| R07 effects table + untrusted-content marker; obligation ledger | Machine-visible risk per tool; fail-closed parity accounting | [Obs] [R07 §12] | MIT |
| R08 env allow-list, isolated-VM sync, privilege-split explore job | Least-privilege secret passing; agent job without write token | [Obs] [R08 §8, §12] | MIT |
| R09 write-boundary check with rollback; `finish(accepted)` | Graders protected from the graded agent (git-visible paths only) | [Obs] [R09 §12] | MIT |
| R10 runtime host + revision-bound resource; guard self-mutation check | Verification bound to candidate bytes; checks shown to fail before trusted | [Obs] [R10 §12] | none: idea only |
| R11 `reviews.py`, `parity.py`, `imgdiff.py` | Provenance enforced in code; deterministic scoring | [Obs] [R11 §12] | MIT |

---

## Limits of this analysis

- **Second-hand evidence.** Every statement rests on the phase 1 reports, which were themselves produced by
  reading code, not running it. About twenty load-bearing claims across all 11 clones were re-checked (marked
  "re-checked"), plus licence files and two test counts; the cited lines matched the reports. One citation was
  attached to the wrong claim in the first version: the R05 control-plane cell cited `runner.py:53-67` (the SDK
  options block) for the loop, which is at `:147-183`; corrected (P1-1). No test, workflow, container or agent was executed by anyone in the campaign.
- **Docs.** [Docs] tags reuse the official-docs citations in the reports (accessed 2026-10-22); no new docs were
  fetched for this deliverable.
- **Ratings are judgements.** The qualitative scale in §4 and the criteria in §5.7 are this analyst's reading of
  the evidence against stated rubrics. Another reader could place borderline cells (for example R08 D3, R10 D9,
  R09 D6) one step differently.
- **External code.** R10's agents, gates and review independence live in Archon and were out of scope; R08's
  external factory daemon is not in its repository; R03 and R02 depend on unfetched external skills and services
  [R10 §17, R08 §17, R03 §17].
- **Unmerged work.** R01 v2, R05's eval harness and dogfood fixes, and R06's roadmap exist only on branches and are
  marked so where cited.
- **Coverage.** R03, R07 and R08 were read "mostly"; long tails (R07 format providers, R03 docs site) were skipped
  [index "Research completeness"].
- **Measures.** No repository supplies first-pass acceptance, human interventions per task, time to verified
  delivery or cost per accepted deliverable on real work; R05's benchmark is synthetic and author-run.

## Report discrepancies found

No material discrepancy between the reports and the clones was found in the spot-checks. One immaterial note:

- **R08 test-case count.** Report 08 §7 gives "~1,416 `it(`/`test(` cases (regex count)" and §1 "~1,400". A
  line-anchored count (`^\s*(it|test)\(`) over the 54 tracked `*.test.ts` files gives 1,413. The difference comes
  from the regex choice and is within the report's "~"; no correction needed.

## Verification corrections (2026-10-22)

Each finding was confirmed against the reports and the clones before it was applied.

- P1-1 applied: R05 control-plane citation now points to the loop at `runner.py:147-183` (re-checked); noted in Limits.
- P1-2 applied: R04 now "6 generator + 8 domain skills (14 under `generated-skills/`)" in §2a and §2b (re-checked 14 dirs).
- P1-3 applied: Summary #6 narrowed to verification against the delivered head or bytes, and lists R05, R02, R11 and R09 code checks with their limits.
- P1-4 applied: Summary #4 now names R11's exit-code gates (when run) and R01 v2's scripted gate (unmerged).
- P1-5 applied: shipped `merge_policy.default: "auto"` (re-checked `merge-policy.py:133`, `config-schema.json:135`) stated in Summary #4, §4a R03 D5, §5.4 and §5.7.
- P1-6 applied: R03 now "5 guard hooks and 1 cleanup hook" (re-checked `hooks/`).
- P1-7 applied: added D15 secret-handling ratings in §4b and a supply-chain and secrets cross-reference after §2c.
- P1-8 applied: R05 D5 is now n/a; n/a added to the scale (R07 D1 moved to n/a for consistency).
- (Superseded by the follow-up and final-sync lines below.) P2-1 applied (this document's half): eight of the 26 listed cells now converge with D2 (seven re-rated plus R05 D5 via P1-8); 18 kept with reasons; §4d maps the two scales and explains each kept divergence.
- (Superseded by the final-sync line below.) Follow-up after D2's reconciliation: §4d rewritten against D2's reconciled heatmap and note. R04 D1 Absent→Weak; R02 D8, R08 D9, R02 D10 and R10 D10 reverted to Weak after re-checking the evidence. Five divergences remain (R05 D5, R08 D5, R09 D6, R06 D11, R07 D11); R05 D5 is not in D2's note.
- Final sync (coordinator, 2026-10-22): D2 moved C2 R05 back to n/a, so the R05 D5 divergence is closed; §4d now lists four remaining divergences (R08 D5, R09 D6, R06 D11, R07 D11), matching D2's note.
- P1-9 and P1-10 (closure pass, applied by the coordinator): §4d boundary table now maps D2 to A3 only and states that A4 is compared partly, naming the three A4 cells that differ; the two earlier P2-1 history lines are marked superseded.
