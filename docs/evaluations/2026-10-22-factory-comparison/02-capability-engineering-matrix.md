# Capability & Engineering Matrix: strongest implementations by category
> Phase 2 of the Software Factory evaluation campaign · Date: 2026-10-22
> Inputs: phase 1 reports 01-11 (docs/evaluations/2026-10-22-factory-research/) · Framework: value definition (active decision 2026-10-22)
> Legend: [Obs] observed · [Docs] official docs · [Claim] unverified claim · [Inf] inference · [Unk] unknown

## 0. How to read this document

**Scope.** This document compares *capabilities*, not whole projects. The 11 repositories fall into three groups
that are not ranked against each other [R-index "Repositories at a glance"]:

| Group | Repositories | Execution model |
|---|---|---|
| G-ORCH: orchestrating factories and runtimes | R03 Super-Board, R05 Lewis Factory, R08 Sandcastle, R09 SSSF (IndyDevDan), R10 Medin (consumer over Archon) | Code-driven or hybrid control with LLM workers |
| G-PACK: prose-driven skill/agent packs and generators | R01 Galea v1, R02 Ras Mic, R04 Rezvani, R06 Blueprint | The LLM follows Markdown |
| G-RE: reverse engineering and replication | R07 REA, R11 Replica | Tool platform (R07); prose plus deterministic tools (R11) |

**Licences.** These decide what a candidate verdict can be (brief rule 7). No licence: R01 v1, R05, R10, so ideas
only (REIMPLEMENT or REFERENCE ONLY). GPL-3.0: the R01 v2 branch, which is copyleft. Mixed: R02, where MIT covers
`greploop`, `greploop-apps` and `unslop` only. MIT: R03, R04, R06, R07, R08, R09, R11 [R-index "Cross-cutting"].

**Rating scale.** Each rating applies to one capability and does not blend capabilities.
- **S (Strong):** enforced by code, not prose; verified at file:line; covers the core of the capability with no material gap found.
- **A (Adequate):** in code but partial or with a material gap; or well specified with partial code.
- **W (Weak):** prose only, or code that is broken or bypassed by default.
- **–:** absent.
- **U:** delegated to code that was not inspected (Archon, for R10).
- **n/a:** outside the project's purpose by design.
- **b:** applies only to an unmerged branch.

For template-type capabilities (F2, F3, G3, G4) the "mechanism" is the artifact design itself, so the rating
reflects structure and completeness rather than enforcement. "Strongest" always means best *demonstrated in code
or tests*, not best documented.

**Evidence base.** The evidence is the 11 phase 1 reports, plus 18 spot-checks in the read-only clones (listed in
§6). Nothing was executed.

---

## 1. Capability taxonomy and summary heatmap

Value dimensions: EQ engineering quality 30 · AO autonomy and orchestration 20 · DP development productivity 15 ·
SR security and reliability 15 · MA maintainability and adaptability 10 · RE resource efficiency 10.

| # | Capability | Dim. | R01 | R02 | R03 | R04 | R05 | R06 | R07 | R08 | R09 | R10 | R11 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| **A** | **Orchestration and control** | | | | | | | | | | | | |
| A1 | Orchestration control and stage enforcement | AO | W (b:A) | W | **S** | W | **S** | W | n/a | A | S | U | W |
| A2 | Parallelism and concurrency control | AO | W | W | **S** | – | – (b:A) | W | A | A | W | A | – |
| A3 | State persistence and resume | AO | W | A | **S** | – | W | W | A | A | A | A | W |
| A4 | Failure recovery, timeouts, retries | SR | W | S | **S** | – | S | W | A | **S** | A | A | W |
| **B** | **Context and agents** | | | | | | | | | | | | |
| B1 | Context construction and handoff artifacts | AO/RE | A | A | **S** | W | A | A | **S** | A | **S** | A | A |
| B2 | Agent role design and least privilege | SR | W | W | A | W | A | W | A | W | A | U | – |
| B3 | Structured agent output contracts | EQ | W | A | S | – | **S** | W | S (tools) | S | A | A | A |
| **C** | **Quality and verification** | | | | | | | | | | | | |
| C1 | Independent review and verification of produced work | EQ | W | **A** | **S** | – | A (**b:S**) | W | A | W | W | **U** | W |
| C2 | Merge/release gating and human approval | SR | W | W | **S** | W | n/a | W | A | A | – | U | W |
| C3 | Testing of the factory itself | EQ | – | A | **S** | – | S | A | A | S | – | A | A |
| C4 | Behavioural evals of prompts/skills/agents; benchmark method | EQ | – | – | A | – | – (**b:S**) | – | A | – | – | U | – |
| C5 | Checker validation ("shown to fail") | EQ | – | – | W | – | – (b:A) | – | W | – | W | **S** | – |
| **D** | **Security and reliability** | | | | | | | | | | | | |
| D1 | Permission model | SR | W | W | W | W | **A** | W | A | W | W | U | W |
| D2 | Sandbox/isolation | SR | W | W | W | – | W | W | W | **A** | – | W | – |
| D3 | Secret handling | SR | W | W | A | W | W | – | W | A | W | A | W |
| D4 | Untrusted-input handling | SR | W (b:A) | W | – | – | W | W | **A** | **A** | – | U | – |
| D5 | Supply-chain hygiene | SR | W | A | W | W | A | **S** | A | **W** | W | **A** | W |
| D6 | Protection of the factory's own judge/grader | EQ/SR | – (**b:A**) | – | – | – | – (**b:S**) | – | – | – | **A** | U | – |
| **E** | **Operations and efficiency** | | | | | | | | | | | | |
| E1 | Observability/tracing | SR | A | W | A | W | A | W | A | A | **S** | W | W |
| E2 | Cost and token control | RE | W | W | A | – | A | W | A | A | W | A | W |
| E3 | Model routing | RE | A | – | **S** | W | – | – | n/a | A | A | U | – |
| E4 | Invocation control and context footprint | RE | – | A | A | W | n/a | **S** | **S** | n/a | A | n/a | W |
| **F** | **Improvement and planning** | | | | | | | | | | | | |
| F1 | Continuous improvement / learning capture | MA | – | W | **A** | – | W (**b:S**) | – | A | W | W | A | – |
| F2 | Specification and planning artifacts | DP | A | W | A | W | W | **S** | n/a | W | A | A | **S** |
| F3 | Requirement traceability (IDs across spec, test, review) | EQ | A | – | A | – | – | **S** | **S** | – | – | – | A |
| **G** | **Reference-driven development** | | | | | | | | | | | | |
| G1 | Reference-driven development (sources, provenance, reuse decisions) | DP/MA | – | W | W | W | – | W | **A** | – | – | – | **A** |
| G2 | Application reverse engineering | DP | n/a | n/a | n/a | n/a | n/a | n/a | **S** | n/a | n/a | n/a | W |
| G3 | Specification extraction | DP | n/a | n/a | n/a | n/a | n/a | n/a | A | n/a | n/a | n/a | A |
| G4 | UI/UX reconstruction | DP | n/a | n/a | W | n/a | n/a | n/a | – | n/a | n/a | n/a | **A** |
| G5 | Visual verification | EQ | W | **A** | A | – | – | W | W | – | – | – | **A** |
| G6 | Feature-parity measurement | EQ | n/a | n/a | W | n/a | n/a | n/a | **A** | n/a | n/a | n/a | **A** |
| **H** | **Distribution** | | | | | | | | | | | | |
| H1 | Installation/distribution | MA | W | W | **A** | W | A | W | **A** | **S** | A | A | A |
| H2 | Cross-agent portability | MA | – | W | A | W | – | A | **S** | **S** | W | U | – |

Each rating is justified in §2. **Bold marks every implementation that §2 names "Strongest"** for that capability (all parallel
"Strongest" bullets), whatever its rating; a branch-only one is bolded inside its `b:` marker. A "strongest
component" mention within a weaker repository (A3 R08) is not bolded. An unbolded S is a Strong implementation that §2 does not name strongest. No
bold in a row (B2, D3, E2, G3) means §2 found no implementation that stands out. R10 cells are rated on the
`main` branch; its unmerged PRs (#58 lap ceilings, #60 browser driver) are not rated.

**Rating scales and divergences from D1** (`01-comparative-architecture-matrix.md` §4). The scales map one to one:
S = Strong, A = Adequate, W = Weak, – = Absent, U = Unknown. Two definitions differ.
- D1's Strong needs "tests or a traced path". This document's S needs code enforcement with no material gap, and
  rates tests separately in C3.
- Both documents use n/a for outside scope by design (D1 added n/a to its scale in its correction pass).

After re-checking the evidence, these cells were changed to agree with D1 (cell IDs use this document's
capability codes; "D1 R01" means capability D1 Permission model, row R01):
- A1 R09 → S; A3 R08 → A; C1 R05 → A; C1 R10 → U; C2 R04 → W; C2 R10 → U; C3 R07 → A;
- D1 R01 → W; D1 R11 → W; D2 R10 → W; D4 R02 → W; D5 R07 → A; D5 R08 → W;
- E1 R02 → W; E1 R06 → W; E1 R10 → W; E1 R11 → W; E2 R08 → A.

C2 R05 is n/a in both documents. The runner contains no git or `gh` calls, so it never commits, pushes or merges,
and there is nothing for a gate to hold [R05 §5, §16].

D1 later changed its R09 resume, R08 untrusted-input and R05 continuous-improvement cells to match this document
(A3 R09 A, D4 R08 A, F1 R05 W (b:S)), so those cells now agree.

Exactly four divergences are kept, each because the two documents draw the capability boundary differently:
- **C2 R08 A (D1 Weak).** D1 rates the library ("none in library"). C2 here also counts the repository's own
  privilege-split explore workflow and human merges [R08 §5, §12.8].
- **D1 R09 W (D1 Adequate).** The after-the-fact write boundary is credited under B2 (A) and D6 (A). The
  permission model itself gives every agent `bash`, and the example `just cc` skips permissions [R09 §8].
- **E2 R06 W (D1 Adequate).** Context footprint has its own capability here, E4, where R06 is S. E2 counts only
  controls on spend during execution.
- **E2 R07 A (D1 Strong).** E2's S requires enforcement of a budget or cap on spend. R07 enforces response byte
  caps and measures carefully, but sets no budget on agent spend [R07 §9].

---

## 2. Capabilities in detail

Format for each capability: **Implementations** (one line per repository, tagged, cited) · **Strongest** ·
**Runner-up / alternatives** · **Claimed, not implemented** · **Candidate verdict** (generic and provisional,
licence-bound).

### A. Orchestration and control

#### A1 Orchestration control and stage enforcement

**Implementations**
- R03 [Obs]: per-card lane chains are deterministic JS over Claude Code Workflow `agent()` calls with JSON-schema
  exits (`workflows/super-board-wave.js:288-341`). Merge, policy, approval and halt are scripts whose exit codes
  the lanes must route. The outer orchestrator is an LLM session following `run-workflow.md` [R03 §5]. The
  orchestration script itself is unit-tested with `agent/pipeline/log` stubbed (`tests/test-wave-preflight.sh:12-33`)
  [R03 §7, §12.1].
- R05 [Obs]: about 290 lines of Python: setup once → worker → ordered checks → bounded retry
  (`src/factory/runner.py:99-186`). Covered by 17 test functions / 28 cases with fake agents [R05 §5, §7].
- R09 [Obs]: ADW scripts are straight-line Python, so the LLM never picks the next phase. Phases default to `fail`,
  and `finish(accepted=…)` separates "the runner worked" from "the result is acceptable" (`M/runner.py:72-142`).
  No tests [R09 §5, §7].
- R08 [Obs]: the library's iteration loop stops on a completion signal (`src/Orchestrator.ts:355-589`).
  Plan → implement → review → merge is caller code or templates (`Promise.allSettled` fan-out) [R08 §5].
- R10 [Obs/Claim]: the consumer is deterministic and calls no model. Stages, retries and gates belong to Archon
  [Claim, R10 §5.1].
- R01 [Obs]: v1 is a fixed graph written in prose. The LLM writes `job.json` and nothing validates transitions
  [R01 §5]. The unmerged GPL v2 branch adds a `TRANSITIONS` table with an `fcntl` lock (`job:40-52,104-113`)
  [R01 §2.4]. Spot-check: v2 `factory/bin/gate` also has a `--hook` mode, wired as a builder SubagentStop hook
  that exits 2 when checks fail (`gate:7,85-105`).
- R02, R06, R11, R04 [Obs]: sequencing is prose only [R02 §5; R06 §5; R11 §5; R04 §5.1].
- R07 [Obs]: no orchestration by design: "custom orchestration needs a demonstrated requirement"
  (`docs/roadmap.md:24-25`) [R07 §5].

**Strongest**
- Multi-stage: R03, the hybrid "deterministic lane chain over LLM steps".
  - Each step returns a schema-validated status from a fixed enum (`advanced|bounced|blocked|human-gate|failed|halted`;
    spot-check `super-board-wave.js:67-86`).
  - Each safety decision is an exit code from a script.
  - The control script has its own deterministic test.
- Single loop: R05. The control flow, bounds and stop/retry semantics are entirely in tested code
  (`runner.py:147-183`; tests `:67-177`).

**Runner-up / alternatives**
- R09 is also rated S: the ADW scripts own order, loops and acceptance in code, and both traced paths confirm it
  [R09 §5]. It is not named strongest because the factory has no tests (C3 –), and its generator emits scripts
  that call a removed API [R09 §7]. Its phase primitive ("success must be earned" plus an acceptance predicate) is
  a clean model for verification steps.
- R01 v2 (unmerged, incomplete) shows a scripted state machine plus a SubagentStop gate as a Claude Code-native
  way to enforce a stage.

**Claimed, not implemented**
- R03: `humanApprovesMerge` "serializes Review", contradicted by `super-board-wave.js:94-108`. The rebuild cap's
  `root-cause-hash` has no script that computes it [R03 §5, §16].
- R02: the greploop iteration cap exists only as prose (`greploop/SKILL.md:20`) [R02 §16].
- R04: `factory-guide` "delegates" but lacks the `Agent` tool [Docs via R04 §3].
- R06: every merge gate is prose [R06 §16].

**Candidate verdict:** REIMPLEMENT the R03 wave pattern (MIT, but bound to the Workflow runtime and super-board's
lifecycle docs, [R03 §13]) and the R05 loop contract (no licence).

#### A2 Parallelism and concurrency control

**Implementations**
- R03 [Obs]:
  - Wave width comes from the dependency graph: Ready cards whose blockers are closed (`scripts/super-board-wave-plan.sh:6-27,159-166`).
  - The runtime cap is "up to 16 concurrent agents by default, fewer with fewer CPUs" [Docs via R03 §5].
  - The merge mutex is an atomic `mkdir` lock with the freshness proof taken inside the lock (`merge-gate.sh:165-195`).
    The promise-chain mutex was removed because it serialized the whole lane (spot-check `super-board-wave.js:94-108`).
  - Claims are made by assignee, then re-read and verified (`run-workflow.md:239-247`).
  - A throttle steps `max_workers` down (∞ → 3 → 2 → 1) after a rate-limit hit (`throttle.sh`) [R03 §5].
- R01 [Obs]: four reviewers are spawned "in one message" behind a WAIT-FOR-ALL barrier (`SKILL.md:136-144`).
  Jobs are claimed with an atomic `mkdir` (`:103-107`) and get per-job ports and worktrees. No parallel run is
  evidenced [R01 §5, §16].
- R10 [Obs]: `parallel` laps from 1 to 8, `capacity=parallel`, `overlap: "skip"`, and non-blocking OS file locks
  per phase (`consumer.py:410-416,432-434,512-532`). Work-claiming is Archon's [Claim, R10 §5.2].
- R08 [Obs]: the library has no limiter. Runs are isolated by `sandcastle-<uuid>` containers and per-branch
  worktrees. The local loop uses a hand-written max-4 semaphore (`.sandcastle/run.ts:42-55`) [R08 §5].
- R07 [Obs]: session-scoped admission serializes operations on a target, and external-mutation admission retires
  stale sessions (`src/server/externalMutationAdmission.ts:14-60`). Parallel agent work is advice only [R07 §5].
- R06 [Obs, prose]: the coordinator defaults to 2 Codex workers (`codex-issue-coordinator/SKILL.md:41-42`) [R06 §5].
- R09 [Obs]: phases are sequential. Pi subagents run fire-and-forget and are untraced (`subagents.ts:335-337`) [R09 §3, §5].
- R02 [Obs]: a per-session lock serializes concurrent `annotate` calls, and a test covers it
  (`evidence.py:261-293`; `tests/test_evidence.py:130`). The multi-agent repo rules are prose
  (`AGENTS.md:54-72`) [R02 §3, §5].
- R05 [Obs]: main is sequential. The unmerged eval harness runs trials with `ThreadPoolExecutor(--jobs)` [R05 §5].
- R04, R11: none.

**Strongest:** R03.
- Parallelism is sized to the real dependency graph rather than a fixed cap.
- Mutual exclusion sits only at the contended resource (the merge into one base), with proof under the lock.
- Throttling adapts to the external rate limit.
- All three are in code.

**Runner-up / alternatives**
- R10: capacity, overlap skip and per-phase OS locks.
- R01: a barrier plus a named resumable worker, as a pattern in prose.

**Claimed, not implemented**
- R08: ADR 0007 worktree locking has no code in `src/` [R08 §16].
- R03: the `min(16, cpus-2)` formula is [Unk] for the Claude backend [R03 §16].
- R01: parallel jobs are not evidenced [R01 §16].

**Candidate verdict:** REIMPLEMENT (R03 MIT: the patterns transfer; the code is bound to GitHub Projects v2).

#### A3 State persistence and resume

**Implementations**
- R03 [Obs]:
  - The GitHub board is the only loop state: "Resume: just run again" (`run-workflow.md:315-317`).
  - Stranded Building cards go back to Ready (`wave-plan.sh:43-49`).
  - A shared halt file works across worktrees (`github-read.py:295-344`).
  - A stopped workflow relaunches with cached results [Docs via R03 §6]; the `resumeFromRunId` name is [Unk].
- R08 [Obs]:
  - Session transcripts are captured with `cwd` rewritten, then `resume()`/`fork()` use native CLI flags
    (`src/run.ts:801-840`; `src/AgentProvider.ts:331-420`).
  - Named-branch worktrees are reused with a safe fast-forward (`WorktreeManager.ts:236-252`).
  - At workflow level, resume means re-running the caller script with deterministic branch names [R08 §6].
- R09 [Obs]: `agent_map.json` resumes each agent's session on `--adw-id`. There is no phase checkpoint; a re-run
  starts at phase 1 [R09 §6].
- R10 [Obs]: native `--resume/--adopt` pass through. A durable `workflow wake` runs on every tick
  (`consumer.py:336-340,762-769`). Runtime-host runs cannot resume [R10 §5.3, §6].
- R02 [Obs]: the recorder's state machine has explicit recovery states and an idempotent `stop`
  (`evidence.py:1198-1233`). `wait` can be re-run on an attempt file [R02 §6].
- R07 [Obs/Claim]: evidence bundles can be exported (import is a [Claim]). The unknowns registry uses optimistic
  concurrency with `expected_revision` [R07 §6].
- R05 [Obs]: `run.json` plus per-attempt logs, but "no automatic cleanup or resume" (`README.md:146-148`) [R05 §6].
- R01 [Obs]: `job.json` survives, but no command re-enters a job after the orchestrator dies [R01 §5, §6].
- R06 [prose]: reuses the existing branch, worktree or PR [R06 §6].
- R11 [Obs]: the `replica/` file ledger, with no state machine [R11 §6].
- R04: none.

**Strongest**
- Workflow level: R03. External durable state is recomputed every wave and sweeps crashed work.
- Agent-session level: R08, the strongest component. Session capture, path rewrite and resume/fork are tested:
  42 cases in `src/SessionStore.test.ts` plus `src/SessionStore.windowsPath.test.ts` (spot-check). R08 is rated A
  overall, because workflow-level resume means re-running the caller script and there is no checkpoint for the
  orchestration loop [R08 §6].

**Runner-up / alternatives**
- R02's crash-safe state machine for one tool (raw MPEG-TS recovery is tested, `tests/test_evidence.py:730`).

**Claimed, not implemented**
- R09: "losing the db loses nothing you cannot rebuild", but no rebuild tool exists [R09 §16].
- R01 v2: resume through `/factory run` [Claim, R01 §5].

**Candidate verdict**
- R03 pattern: REIMPLEMENT.
- R08 session handling: REUSE as a dependency or ADAPT (MIT), noting that it relies on undocumented CLI session layouts [R08 §13].

#### A4 Failure recovery, timeouts, retries

**Implementations**
- R08 [Obs]:
  - Timeouts: an idle timeout (600 s) and a completion-window timeout for hanging processes
    (`Orchestrator.ts:89-121,174-185`; ADR 0019); container start, sync and hooks each have their own step timeout
    (`startSandbox.ts:73-75`, `SandboxLifecycle.ts:19-22`).
  - Retries: git setup is retried only on 126/137 (`:24-82`); structured output is retried through session resume.
    Provider errors are deliberately not retried (`.out-of-scope/provider-error-retry.md`).
  - Recovery: a dirty worktree is kept and its path attached to the error (`SandboxFactory.ts:203-252`); patches
    are saved before they are applied (`syncOut.ts:1-15`) [R08 §5].
- R03 [Obs]:
  - Required reads get 3 attempts; permanent errors halt at once; mutations are never retried; exhaustion exits 79
    with a shared halt file (`github-read.py:47-73,295-344`).
  - A lost merge response is reconciled, and a head that moved during the gate exits 6
    (spot-check `merge-gate.sh:361-372`).
  - Halt rules: zero-progress waves, block rate, a usage pause [R03 §5].
- R05 [Obs]: process-group SIGKILL on timeout; `asyncio.timeout` per agent call; a timeout stops the run and is not
  repaired; `stop` and `retry` are distinct; any exception sets `needs_attention` (`runner.py:21-39,69,181-186`).
  Tested (`tests/test_pipeline.py:159-177`) [R05 §5].
- R02 [Obs]: a deadline-bounded wait; a post-once trigger reservation by exclusive create
  (`github_review.py:155-183`); recorder states `startup_failed|recorder_lost|finalization_failed`; crash-tolerant
  capture. Tested [R02 §5].
- R09 [Obs]: JSON repair up to 2 times in the same session; bounded gate and fix loops. No timeout on the Pi
  subprocess, and a possible stderr pipe deadlock (`M/agent_pi.py:243-281`) [R09 §5, §7].
- R10 [Obs]: never retries ("No subprocess deadline or retry can guess…", `consumer.py:344-352`). A stuck-run
  sweeper (`:537-568`); the runtime host tears down everything on a failed request [R10 §5.3].
- R07 [Obs]: a tagged `Result` error algebra; cleanup retries that keep ownership; agent-side retry rules in the
  skill [R07 §5].
- R01 [Obs]: `MAX_RESUMES=2`. No timeouts and no crash retry [R01 §5].
- R06 [prose]: a 3-strike pause in the coordinator; `/task-to-pr` has no budget [R06 §5].
- R11: prose loops. R04: none.

**Strongest**
- R08: a timeout taxonomy that includes the "finished but a child holds stdout" case, recovery artifacts by
  default, and an explicit non-retry policy.
- R03: fail-closed evidence reads, no mutation retries, and reconciliation of an ambiguous merge.
- Both are MIT and tested.

**Runner-up / alternatives**
- R05: minimal and fully tested.

**Claimed, not implemented**
- None material. The gap is R09's missing subprocess timeout, which its own docs acknowledge.

**Candidate verdict:** ADAPT or REUSE R08 (as a library); REIMPLEMENT R03's read helper pattern, or REUSE it
directly, since the report classes it "directly reusable" [R03 §13].

### B. Context and agents

#### B1 Context construction and handoff artifacts

**Implementations**
- R03 [Obs]:
  - Lane prompts are short pointers, and each lane gets a fresh sub-agent.
  - PR-body marker blocks are rewritten through `super-board-pr-body.sh --block <name> --expect-head <sha>`, which
    refuses (exit 6) when the head has moved.
  - Comments carry machine lines.
  - The prompt has the reviewer form hypotheses before reading the builder's account [R03 §6].
- R09 [Obs]: typed envelopes (Pydantic) pass forward as `previous=`. Deterministic code results are adapted into
  the same envelope shape (`M/quality.py:193-211`, `M/changes.py:87-103`). Evidence is bounded: diff ≤ 2,000
  lines, output tail ≤ 4,000 chars [R09 §6].
- R07 [Obs]: results are summary-first, with the full record retained under a `parent_evidence_id`; a per-response
  byte cap; compact input schemas; a deferred catalog verified by digest (`src/main/deferredRuntime.ts:25-46`)
  [R07 §6, §9].
- R01 [Obs]: one-line prompts with absolute paths. Handoff is by file (`spec.md`, `build.md`,
  `round-N/review-*.md`, `decision.md`) with machine-checkable first lines [R01 §4, §6].
- R05 [Obs]: a static prompt plus JSON context. Feedback is *replaced*, not accumulated (`runner.py:176`). Prompts
  are read before setup runs [R05 §6].
- R08 [Obs]: `{{KEY}}` substitution plus `` !`cmd` `` expansion inside the sandbox, with an inert marker so
  arguments cannot create shell blocks (`PromptArgumentSubstitution.ts:92-105`). A produce → extract split
  [R08 §4, §12].
- R06 [prose]: explicit read steps and a defined reviewer context; coordinator "compact `wait_threads` snapshots";
  plans are not persisted [R06 §6].
- R11 [Obs]: a `replica/` artifact table keyed by stable IDs [R11 §6].
- R02 [Obs]: progressive reference loading; `report.md`/`manifest.json` handoff [R02 §6].
- R10: governance files (`MISSION.md`, `WORKFLOW_POLICY.md`); how Archon loads context is [Unk] [R10 §6].
- R04 [Obs]: loads a whole ~1,000-line factory prompt [R04 §6].

**Strongest**
- Handoff integrity: R03. A handoff refuses to write when its basis (the PR head) has moved.
- Handoff uniformity: R09. Code and agent outputs share one typed contract.
- Context economy for large tool outputs: R07.

**Runner-up / alternatives**
- R01's first-line verdict tokens: the cheapest parseable coupling.

**Claimed, not implemented:** none material.

**Candidate verdict**
- R09 envelope types: REUSE (MIT, "directly reusable (types)" [R09 §13]).
- R03 block editor: REUSE [R03 §13].
- R07 summary-first: REIMPLEMENT.

#### B2 Agent role design and least privilege

**Implementations**
- R09 [Obs]:
  - Per-agent `tools:` maps to `pi --tools`.
  - `writes:` and default `protected_files` are enforced *after* each call: the working-tree change set is diffed,
    unauthorized changes are rolled back, and the phase raises (`M/permissions.py:50-185`; spot-check docstring
    `:1-30`, defaults `data_types.py:332-337`).
  - Blind spots: gitignored and outside-repo paths, and an agent that runs `git commit`/`stash` [R09 §8].
- R05 [Obs]:
  - SDK calls fail closed: tools are the allowlist, `dontAsk`, any `permission_denials` fail the run,
    `setting_sources=[]` and `strict_mcp_config=True` (spot-check `runner.py:53-82`).
  - The check toolset omits Write/Edit but keeps unrestricted `Bash` (`config.py:19,25`).
  - The code-enforced reviewer read-only check (`disallowed_tools` plus `unchanged()`) was removed in `9b7f5cf`
    [R05 §8].
- R03 [Obs/Docs]:
  - Lane agents use the session's permission rules [Docs].
  - `tests/test_run_allowlist.py` fails when a lane calls a script missing from the allowlist.
  - Merge permission is added only on auto boards (`run-workflow.md:369-381`).
  - Undercutting this: the legacy builder runs with `--dangerously-skip-permissions`, and Codex lanes use
    `approval_policy="never"` [R03 §8].
- R07 [Obs]:
  - Every tool declares its effects; 15 declare `executesForeignCode`; MCP annotations are derived from the
    effects (`src/contracts/toolEffects.ts:1-31`).
  - Its own agent eval runs Codex with `--sandbox read-only` and a per-tool approve allowlist [R07 §3, §8].
- R04 [Obs]:
  - The slash-command generator synthesizes narrow `allowed-tools` and rejects a bare `Bash`
    (`command_generator.py:319-344`), though `sed:*`/`awk:*` still allow writes.
  - Generated agents default to full toolsets [R04 §4.2, §8].
- R01 [Obs]: 7 role agents, all with `Bash`+`Write`; "read-only" holds by prompt only [R01 §3, §8].
- R06 [Obs]: no agent files; the reviewer is read-only "by prose only" [R06 §3, §8].
- R08 [Obs]: roles are prompts; every AFK run bypasses permissions (§D1) [R08 §3].
- R02 [Obs]: one skill declares broad `allowed-tools` (unpinned `npx`, `gh pr edit *`) [R02 §8].
- R10: Archon's [Unk]. R11: none.

**Strongest:** no repository demonstrates a tool-enforced read-only reviewer or verifier on its default branch.
The best partial mechanisms:
- R09's after-the-fact write boundary, which works with any harness.
- R05's fail-closed SDK allowlist.

**Runner-up / alternatives**
- R07's per-tool effect declarations make risk machine-readable, so hosts can gate on them.

**Claimed, not implemented**
- R01: "read-only" reviewers.
- R06: a read-only reviewer.
- R05: "checks should inspect work without editing it" [R05 §16 "partly"].

**Candidate verdict**
- R09 `permissions.py`: ADAPT (MIT).
- R05 SDK options and R07 effects table: REIMPLEMENT.
- The capability as a whole is a BUILD NEW candidate (see §5).

#### B3 Structured agent output contracts

**Implementations**
- R05 [Obs]: `CheckResult{status: pass|retry|stop, feedback}` comes back through SDK
  `output_format=json_schema` and is validated strictly. Missing or invalid output stops the run, with no
  free-text fallback (`config.py:43-51`; `runner.py:64,83-87`; spot-check `:63-87`). Tested [R05 §5].
- R03 [Obs]:
  - `STAGE_SCHEMA` and `PREFLIGHT_SCHEMA` constrain every Workflow agent (spot-check `super-board-wave.js:67-86`).
  - Codex lane output is validated by an in-script schema checker, with tests (`codex-lane.sh:147-216`;
    `tests/test_codex_lane_schema.py`) [R03 §3, "Changes since"].
- R08 [Obs]: `Output.object({tag, schema, maxRetries})` validates against any Standard Schema validator. Retries
  resume the same session with a short correction prompt (`src/run.ts:842-890`). The CI workflows use a
  produce → extract split [R08 §12.6].
- R09 [Obs]: a Pydantic output type is bound at each call site. Parse repair runs in the same session; gates
  return a `GateReport` with per-item evidence (`M/agents.py:147-173,267-287`) [R09 §5, §12].
- R07 [Obs]: every tool has Zod input/output schemas and validated examples (`toolContractTypes.ts:43-68`). These
  are tool outputs, not agent outputs [R07 §4].
- R10 [Obs]: three-valued mutation scoring (`run.py:73-187`) [R10 §12].
- R11 [Obs]: tool exit codes 0/1/2 [R11 §5]. R02 [Obs]: JSON on stdout from its CLIs [R02 §8].
- R01 [Obs]: first-line tokens (`VERDICT:`, `STATUS:`, `APPROVE|ESCALATE`), parsed by the orchestrator LLM and a
  dashboard regex [R01 §4].
- R06 [prose]: verdict vocabulary plus a Priority × Confidence finding format [R06 §4].
- R04: none.

**Strongest:** R05. Schema enforcement is delegated to the SDK, and the three values separate "worker can fix"
from "needs a human".

**Runner-up / alternatives**
- R08: the same idea as a reusable MIT library, with retry by session resume.
- R03: per-stage enum statuses inside the Claude Code Workflow runtime.

**Claimed, not implemented:** none.

**Candidate verdict**
- R08 structured output: REUSE (MIT).
- R05 contract: REIMPLEMENT (no licence).

### C. Quality and verification

#### C1 Independent review and verification of produced work

**Implementations**
- R03 [Obs]: three layers.
  1. A Tester writes and runs tests and audits test gaps.
  2. A Reviewer re-runs the Tester's command and launches two truth-check sub-agents; the **minimum** score wins
     (`super-review/SKILL.md:403-447`).
  3. The merge gate merges the current base into the reviewed head in a scratch worktree and runs `verify_commands`
     inside the lock (`merge-gate.sh:269-290`). Landing is checked by ancestry (`run.md:456-461`).
  - Only layer 3 is code. All layers share one model family [R03 §7].
- R05 (unmerged `codex/eval-suite`) [Obs]: the grader copies **only** `app.py`, runs the visible tests plus
  held-out `acceptance.py` under `python -I`, fails closed, and records `false_completion` (spot-check
  `evals/run.py:120-151`). On main (rated A), configured command checks run in code and the reviewer is a fresh,
  context-independent SDK session, but in the same workspace with no tamper check
  [R05 §7, §8].
- R02 [Obs]: a third-party Greptile score counts only if it is fresh against the trigger, comes from a trusted bot
  login, and is bound to the current head SHA, which is re-read after fetch (spot-check `github_review.py:45-63`;
  33 tests). The screen-evidence results are self-reported, and `"verified": true` means only that the video is
  playable (`evidence.py:1002-1007`) [R02 §7].
- R10 [Obs/Claim]:
  - The runtime host binds the app under test to `sha256(source digest, argv, env)` and re-probes identity
    (`runtime_host.py:236-307`).
  - Mutation scoring counts CAUGHT only for a product rung's verdict.
  - Reviewer independence is in Archon [Claim, `WORKFLOW_POLICY.md:52-56`] [R10 §7, §12]. The capability is
    therefore rated U; identity binding is a strong in-repo component.
- R07 [Obs]: a reconstruction obligation closes only with a passing verifier at comparable authority. Proof
  records are supplied by the caller and carry integrity, not provenance [R07 §5 path 2, §6].
- R01 [Obs]:
  - `reviewer-code` re-runs validation, and the approver spot-checks at least one AC.
  - UX/UI reviewers skipped the required browser check in 3 of 4 example reviews, and nothing detected it
    (`001/round-1/review-ux.md:7` etc.) [R01 §7].
- R09 [Obs]: a reviewer on a different model. `diff_matches_claims` checks only that the files exist (spot-check
  `gates.py:61-68`). The quality placeholders exit 0 [R09 §7].
- R06 [prose]: a fresh-subagent review on every repair; `Blocked` if subagents are unavailable [R06 §7].
- R08 [Obs]: verification is caller-written. The template review is a second agent in the same sandbox [R08 §7].
- R11 [Obs]: the same session builds, tests and marks `features.csv` [R11 §7]. R04: none.

**Strongest**
- Gate verification: R03's merge gate. Deterministic verification against the *current* base, pinned to the
  reviewed head, under a mutex.
- Measuring whether "done" is true: R05's held-out grader (unmerged).
- Binding verification to the delivered bytes: R10.
- Third-party review freshness: R02.

**Runner-up / alternatives**
- R03's prompt techniques: hypotheses before reading, minimum-of-two aggregation, "review remembers".

**Claimed, not implemented**
- R10: "Two reviewers that did not write it decide whether it merges" (README) [R10 §16, not found here].
- R01: UX/UI browser checks.
- R11: "the skills enforce it".

**Evidence of effect**
- R05's author data, recomputed but not re-run: false completions passed **both** tests and structured review
  (v2 3/9; v3 6/36) [R05 §14]. An LLM review gate is not a correctness guarantee.

**Candidate verdict**
- R03 merge gate: ADAPT (MIT; it `eval`s config commands on the host).
- R05 grader pattern: REIMPLEMENT.
- R10 identity binding: REIMPLEMENT.
- R02 `github_review.py`: ADAPT (MIT).

#### C2 Merge/release gating and human approval

**Implementations**
- R03 [Obs]:
  - `merge-policy.py`: `merge_policy.default: "human"`, size > 400 lines, or a money/auth/schema category hit →
    exit 7; migrations → exit 8 (`:50-66,125-193`). The shipped and code default is `auto` (spot-check
    `merge-policy.py:133`; `config-schema.json:135`, [R03 "Changes since"]). Category detection matches
    label/path/substring, so code that matches no category passes as auto unless the size cap trips [R03 §8].
  - Approval is a pinned JSON request (repo, PR, 40-char head, sha256 of the policy plan). It needs a later,
    unedited, exact `done` from a `User` with write permission, and it is re-read just before merge (spot-check
    `approval.py:110-133`; `merge-gate.sh:324-338`).
  - `gh pr merge --match-head-commit` (spot-check `merge-gate.sh:346-351`).
  - Caveats: the shipped default is `merge_policy: "auto"` ["Changes since", R03]. Approval is only as strong as
    the separation between the agent's and the human's tokens [Inf, R03 §8].
  - Release: `release.yml` publishes only the tested SHA [R03 §7].
- R08 [Obs]:
  - The explore workflow is privilege-split. The agent job is read-only; a separate apply job validates the plan
    against a snapshot taken before the agent ran, and applies only whitelisted effects
    (`agent-explore.yml:111-161`; `explore/batch.ts:171-219`).
  - Humans apply labels and merge PRs.
  - Release: npm OIDC trusted publishing with attestations [R08 §5, §7].
- R10 [Obs/Claim]: `merge_mode` preview/approve/auto is passed through to Archon. A STOP brake blocks launches and
  continuations; PAUSE blocks only launches (`consumer.py:286-311,734-773`). Merge enforcement is [Unk]
  [R10 §5.4].
- R07 [Obs]: setup shows a plan and needs approval before writing client config (`Setup.ts:255-290`). A human
  declares PR readiness (`pr-readiness.yml`) [R07 §5].
- R01 [Obs]:
  - The approver's ESCALATE list (money, auth, deploy/CI, schema, email, production data, dependencies,
    product-decision assumptions) is prompt-only. APPROVE merges to local main with no human (`approver.md:10-12,39-47`).
  - The v2 branch gate runs the **main checkout's** `checks.sh` and fails edits to protected paths [R01 §2.4].
- R06 [prose]: merge authority is attached to the explicit invocation, with 5 (task-to-pr) or 10 (coordinator)
  enumerated gates; "never deployment" [R06 §5, §12.2].
- R11 [Obs]: deploy "go" is prose. The preflight's parity step always exits 0 without `--fail-under` (spot-check
  `parity.py:218-224`) [R11 §5].
- R02 [prose/Obs]: "Do not merge unless explicitly instructed"; `--accept-untracked-recorder` is enforced in code
  [R02 §5].
- R05 [Obs]: the runner contains no git or `gh` calls, so it never commits, pushes or merges; the human reviews the
  preserved workspace (`README.md:128-130`). There is nothing for a merge gate to hold, so the cell is n/a
  [R05 §5, §16].
- R10 [Obs/Unk]: the brakes are code, but the merge gate is Archon's, so the capability is rated U.
- R09: no approval phase [R09 §5]. R04 [Obs]: Q&A turns, hook-factory confirm and installer prompts only (W)
  [R04 §5.1].

**Strongest:** R03. The only code-enforced, head-pinned, scope-pinned human approval. Unreadable metadata fails
safe to human (`merge-gate.sh:232-243`), but with the shipped `auto` default, code that matches no category merges
without a human [R03 §8].

**Runner-up / alternatives**
- R08's privilege-split pattern, for applying agent-proposed effects.
- R10's two-level brake.
- R06's "authority by explicit invocation", as a policy design.

**Claimed, not implemented**
- R03: draft-PR delivery messaging versus Reviewer auto-merge [R03 "Changes since"].
- R11: the deploy gate as "any failure stops the deploy" [R11 §5].
- R01: ESCALATE as a safety boundary, which is prompt-only.

**Candidate verdict**
- R03 `merge-policy.py`: REUSE (MIT, "directly reusable").
- R03 approval and gate: ADAPT.
- R08 privilege split: REIMPLEMENT.

#### C3 Testing of the factory itself

Counts and CI per repository are in §3. Strongest by kind:
- R03 [Obs]: tests the **orchestration script itself** by stubbing the Workflow primitives
  (`tests/test-wave-preflight.sh:12-33`), plus safety suites on stubbed `gh` and bare origins [R03 §7].
- R08 [Obs]: replays scripted stream-json against real temp git repos (`src/Orchestrator.test.ts:162-190`) [R08 §7].
- R05 [Obs]: fake agents need no credentials or model calls (`AGENTS.md:9-10`) [R05 §7].
- R07 [Obs]: a written test hierarchy (`docs/testing.md`) plus about 100 real-toolchain `verify:*` lanes. Rated A:
  of the last 100 completed main CI runs, 19 succeeded and 66 were cancelled; the evaluated commit's run was
  cancelled; mutation testing does not block (`stryker.config.mjs:20`) [R07 §1, §7].
- R10 [Obs]: tests whose ability to fail is itself checked (C5) [R10 §7].
- R02, R06, R11 [Obs]: 71, 28 and 57 cases respectively; R06 has CI, R02 and R11 do not [§3].
- R01, R04, R09: none.

**Strongest:** R03 for orchestration-level testing, because the control flow is tested deterministically.
R07 and R08 have the largest suites.

**Runner-up / alternatives**
- R08: real git and fake-agent replay, at about 1,416 cases. CI runs on push to main only, without typecheck or
  lint [R08 §7].
- R05: small but complete, with ruff in CI and no credentials needed [R05 §7].

**Claimed, not implemented**
- R04: "Production-Ready Output" with no tests [R04 §16].
- R02: PR #17's "67 passed, 4 skipped" [Claim], and no CI runs it [R02 §7].

**Candidate verdict:** REIMPLEMENT the stub-the-runtime harness pattern (R03 MIT, [R03 §13]).

#### C4 Behavioural evals of prompts/skills/agents and benchmark methodology

**Implementations**
- R05 (unmerged PR #5) [Obs]: 16 synthetic cases, each with a failing workspace, a reference solution and
  held-out acceptance tests.
  - `validate_cases` proves each start fails and each reference passes.
  - Suite files are hashed, and a post-run re-hash invalidates the run if anything changed.
  - Seeded random schedules.
  - Review evidence comes from real `tool_use`/`tool_result` events, not prose (spot-check `evals/run.py:64-89`).
  - Usage totals include child models.
  - A matched baseline (Claude Code plus the same reviewer as a subagent).
  - 300 scored trials, with negative results kept.
  - [R05 §7, §10, §12]
- R07 [Obs]: an agent-experience eval runs real Codex transcripts and scores first-tool choice, repetition,
  validation failures, token use, Evidence-ID citation and a known-answer check (`src/evaluation/CodexAgentEval.ts:136-245`).
  It is not in CI and needs local Codex auth. `experiments/analysis-efficiency/` keeps dated, partly negative
  results [R07 §7, §9].
- R03 [Obs]: 7 paid `claude plugin eval` cases with deterministic graders (`tool_used`, the absence of `pr merge`)
  plus an LLM judge. Results are gitignored, so no pass rates are in the repo. A Stop hook blocks ending a turn
  while an edited skill's eval is stale (spot-check `hooks/dev/gate-skill-evals.py:1-36`) [R03 §7].
- R06 [Obs, unmerged]: a behavioural baseline is proposed only ("planned, not implemented",
  `guides/blueprint-plan.md:3`) [R06 §7].
- R01, R02, R04, R08, R09, R11: none. R10: Archon [Unk].

**Strongest:** R05's methodology, unmerged and with no licence. It is the only repository that measures whether
the factory beats a matched baseline. Its result: 30/36 versus 29/36 against a prompted reviewer subagent, faster
but at similar cost (author data, recomputed, not re-run) [R05 §9].

**Runner-up / alternatives**
- R07: evaluates the tool surface with real agent transcripts.
- R03: gates prompt edits on eval freshness at authoring time.

**Claimed, not implemented**
- R03: eval pass rates and costs ("≈$0.25-0.45/run") are not in the repo [R03 §16].
- R06: "the best agent skills in the world" [R06 §16].

**Candidate verdict**
- R05 method: REIMPLEMENT.
- R03 Stop hook: REUSE (MIT, "directly reusable").
- R07 scorer: ADAPT (MIT, Codex JSONL-specific).

#### C5 Checker validation ("a check never shown to fail proves nothing")

**Implementations**
- R10 [Obs]: `bin/selfcheck-mutations.py` copies the tree, applies 5 one-line sabotage edits to `consumer.py`, and
  requires the paired test to report `FAIL:`. It returns `NOT_INJECTED` if an anchor is not unique (spot-check
  `:9-41`).
  - The product mutation tool is three-valued; `ci.py` treats zero tests as a failure [R10 §7, §12].
- R05 (unmerged) [Obs]: `validate_cases` proves each starting workspace fails and each reference passes
  (`evals/run.py:154-167`) [R05 §5].
- R07 [Obs]: nightly Stryker with `thresholds.break: null`, which never fails a build (`stryker.config.mjs:20`) [R07 §7].
- R03 [prose]: a "test the tests" mutation check in `super-qa` (`SKILL.md:481-511`) [R03 §4].
- R09 [Obs]: phases default to `fail`, but the shipped quality blocks are `echo` placeholders that exit 0
  (`M/quality.py:49-52`) [R09 §7].
- Others: none.

**Strongest:** R10. It applies the principle to the factory's *own* guards, not only to the product.

**Runner-up / alternatives**
- R05's `validate_cases` (unmerged): it proves the eval fixtures, not the factory's guards.

**Claimed, not implemented**
- R07: mutation testing "guards reverse tools", but its threshold never blocks [R07 §16].
- R10: the defect catalogue ships empty (`defects.json:48`) [R10 §7].

**Candidate verdict:** REIMPLEMENT (no licence).

### D. Security and reliability

#### D1 Permission model

**Implementations**
- R05 [Obs]: fail-closed SDK options (§B2): allowlist, `dontAsk`, denial = failure, no settings or MCP loaded.
  Unrestricted `Bash` is acknowledged: "Shell access is not a read-only sandbox" (`README.md:96-100`) [R05 §8].
- R07 [Obs]: per-tool effect declarations feed MCP annotations. The host's approval policy is the gate
  (`SKILL.md:391-395`) [R07 §8].
- R06 [Docs/Obs]: the only enforced control is opt-in invocation (§E4). Authority is prose [R06 §8].
- R03 [Obs/Docs]:
  - Lane agents inherit the session rules [Docs].
  - Guard hooks deny `.env`/key reads and key-literal writes, but **fail open** (spot-check
    `hooks/guard-secrets.py:62-63`).
  - The legacy builder uses `--dangerously-skip-permissions` with raw issue text
    (`super-build-dispatch.sh:140-145`).
  - Codex lanes use `approval_policy="never"` with network on (`codex-lane.sh:188-198`) [R03 §8].
- R08 [Obs]:
  - `run()` and `createSandbox().run()` always pass `dangerouslySkipPermissions: true`, even with `noSandbox()`
    (spot-check `Orchestrator.ts:143`). `createSandbox().interactive()` hard-codes it too (spot-check
    `createSandbox.ts:631`). Both contradict ADR 0015.
  - A per-provider opt-out exists (`claudeCode(…,{permissionMode})`) [R08 §8].
- R04 [Obs/Docs]: the hook factory generates hooks that do not match the documented contract (object matchers, a
  non-existent env var, `exit 1` that does not block) [Docs via R04 §5.3].
- R09 [Obs]: a `pi --tools` allowlist, and every starter agent has `bash`. The example `just cc` uses
  `--dangerously-skip-permissions` [R09 §8].
- R02 [Obs]: broad `allowed-tools` on one skill [R02 §8].
- R01, R11 (W): no permission configuration shipped, so the host's settings apply. R01 scopes tools in agent
  frontmatter, but every agent keeps `Bash`+`Write` [R01 §8]. R11's limits ("never sign up", "user's go") are
  prose [R11 §8]. R10: Archon [Unk]; the systemd unit sets `IS_SANDBOX=1` as root [R10 §8].

**Strongest:** R05, the only default-deny posture enforced in code, though it leaves Bash open.

**Runner-up / alternatives**
- R07: risk metadata per tool.
- R03: Claude Code hooks as a deny layer (fail-open).

**Claimed, not implemented**
- R08: ADR 0015.
- R04: "blocking" validation hooks (`templates.json:242-245`).
- R04: a "Four-Layer Security Model" with no code [R04 §8].

**Candidate verdict:** REIMPLEMENT (R05 no licence); R03 guard hooks REUSE (MIT), with fail-open noted.

#### D2 Sandbox/isolation

**Implementations**
- R08 [Obs]:
  - Docker/Podman bind-mount containers run as host UID, non-root. Vercel/Daytona VMs receive a git bundle in and
    return format-patch out.
  - Gaps: the host `.git` is mounted **read-write** (spot-check `SandboxFactory.ts:264-288`), with no hook
    hardening; the network is open by default; secrets travel in `docker run -e` argv; the `head` strategy writes
    the developer's working directory; host git commands interpolate branch names that may be LLM-generated
    (`SandboxLifecycle.ts:443,517-518`) [R08 §8].
- R10 [Obs]: the runtime host gives each slot a fresh snapshot, state, port and stripped env; a loopback control
  API with an HMAC-compared token; process-tree ownership. It is "not a filesystem sandbox", by its own docs
  (`RUNTIME_HOST.md:285-291`) [R10 §8]. It isolates the app under test, not the agents, whose worktrees are
  Archon's [Unk], so the capability is rated W.
- R07 [Obs]: owned process groups, `prlimit`/Job Objects, Ghidra in a private temp project; "This is not a
  sandbox" (`SECURITY.md:33-37`) [R07 §8].
- R01, R02, R03, R06 [Obs]: git worktrees per job or task. R03 verifies in a throwaway worktree but `eval`s
  verify/migrate commands on the host (`merge-gate.sh:283,307`) [R03 §8].
- R05 [Obs]: none by default (`cwd="."`); a worktree is opt-in through a `pre` command [R05 §8].
- R04, R09, R11: none; R09 runs in the live checkout [R09 §8].

**Strongest:** R08, the only container/VM isolation runtime. Its gaps (`.git`, network, secrets) are material.

**Runner-up / alternatives**
- R10's app-under-test isolation (identity and process ownership, not security).

**Claimed, not implemented**
- R08: "Sandcastle handles sandboxing the agent" (partly) [R08 §16].
- R04: "Sandboxed execution" [R04 §16].

**Candidate verdict:** R08 REUSE as a dependency with ADAPT for hardening (MIT). R10 REIMPLEMENT.

#### D3 Secret handling

**Implementations**
- R08 [Obs]: env is an allowlist; only keys declared in `.sandcastle/.env` are pulled from `process.env`
  (`EnvResolver.ts:56-72`); overlapping keys throw. Values do appear in `docker run` argv, and `GH_TOKEN` sits in a
  sandbox that has network access [R08 §8].
- R10 [Obs]: the app under test gets a minimal env; provider credentials are not inherited
  (`runtime_host.py:213-217`); the connection file is created `O_EXCL` with mode 0600 [R10 §8].
- R03 [Obs]: `guard-secrets`/`guard-key-literals` hooks (14 key regexes, never print the value), but fail open.
  The migrate DB URL resolves from the project `.env` [R03 §8].
- R04 [Obs]: about 20 secret regexes in the hook validator (`validator.py:520-579`) [R04 §8].
- R07 [Claim]: credential redaction (`AGENTS.md:13`). Per-session capability tokens for the bridges are not
  traced [R07 §8].
- R05, R09 [Obs]: the full parent environment reaches shell checks and agents [R05 §8; R09 §8].
- R02 [Obs]: a prose guardrail, but the default evidence upload goes to public 0x0.st [R02 §8].
- R01, R11 [prose]: reviewer checks commits; `.env.example` holds names only. R06: none.

**Strongest:** none is Strong. R08's declarative allowlist and R10's stripped env are the best
code-level mechanisms.

**Claimed, not implemented:** none material.

**Candidate verdict:** REIMPLEMENT (R08 pattern, MIT).

#### D4 Untrusted-input handling

**Implementations**
- R08 [Obs]:
  - Structural mitigation: the explore job runs read-only, and an apply job validates the plan against a
    pre-agent snapshot.
  - Untrusted titles and bodies pass through `env:`, not `${{ }}`.
  - The explore prompt frames issues as untrusted (`explore/prompt.md:7`), and `triage-repro` has explicit rules.
  - But the implement and review jobs run the agent with a write token and no framing [R08 §8].
- R07 [Obs]: every result carrying target content gets `_meta.provenance.untrusted_content: true`, and the server
  instructions tell the agent to treat that content as data and report requests to run, install or send
  (spot-check `src/server/toolResultEncoding.ts:24-37`). A boundary test exists. This is labelling, not
  enforcement [R07 §8].
- R02 [Obs]: only exact trusted bot logins count for scores, with an imposter test (`test_github_review.py:97-101`).
  Bot bodies are not sanitized, and the agent acts on PR thread text, so the rating is W: the code only filters
  whose score counts [R02 §8].
- R05 [Obs]: prompt lines "treat as data" and JSON-encoded context [R05 §8].
- R01 v2 (unmerged) [Obs]: a "quoted data, not instructions" banner; keeps only comments from the issue author
  and the operator (`job:178-203`) [R01 §2.4].
- R06 [Obs]: "reviewer comment is evidence" exists only on an unmerged branch. The "browser content is
  untrusted" rule was dropped when `browser-verify` was folded into `/test` [R06 §8].
- R04 [Obs]: the clearest exposure. Any outsider's issue body goes into a Claude prompt that holds a write token
  (`issue-triage.yml:15-17,59-62`) [R04 §8].
- R03, R09, R11 [Obs]: no guidance [R03 §8; R09 §8; R11 §8]. R10: [Unk].

**Strongest:** R08's privilege split, the only *structural* mitigation. R07's marker is the best labelling.

**Claimed, not implemented**
- R11: "never scrapes … against a site's terms" has no public-site ToS step [R11 §8].

**Candidate verdict:** REIMPLEMENT both (MIT patterns).

#### D5 Supply-chain hygiene

**Implementations**
- R06 [Obs]: CI actions pinned to full SHAs; exact npm pins with lockfile integrity; Dependabot. The
  `npx skills add` install is unpinned [R06 §2, §8].
- R07 [Obs]: every runtime dependency exactly pinned; SHA-pinned actions; registration pinned to
  `rea-agents@<version>`. But the skill's diagnostics and setup-apply step use `@latest` (`SKILL.md:46,60,65`)
  [R07 §8].
- R10 [Obs]: the engine is pinned by full SHA and verified clean under its authoring roots, plus capability
  probes (`consumer.py:76-218`). But the pin points at an unmerged Archon branch (92 ahead / 575 behind), and the
  root bootstrap pipes unversioned installers to a shell (`bootstrap-ubuntu.sh:65-84`) [R10 §2.2, §8].
- R08 [Obs]: npm OIDC trusted publishing with attestations. The scaffolds use `curl … | bash`, `@latest` and
  unpinned base images [R08 §8].
- R05 [Obs]: `uv.lock` with `--locked` in CI; tag-pinned actions [R05 §8].
- R02 [Obs]: Playwright pinned with integrity and installed with `--ignore-scripts` in a temp dir. Other external
  CLIs are unpinned [R02 §8].
- R03 [Obs]: `curl | bash` with no checksum and a fallback to `main`; `npx -y skills@latest`. Mitigations: a
  `main()` wrapper and a refusal to run as root [R03 §8].
- R04 [Obs]: `.pyc` bytecode inside ZIPs [R04 §8]. R09 [Obs]: unpinned Python deps [R09 §8].
- R01, R11 [Obs]: unpinned externals and `main` installs.

**Ratings**
- R06 keeps S. Everything the repository itself pins or runs is pinned: SHA-pinned actions, exact npm versions
  with integrity, Dependabot. The unpinned path is the third-party `npx skills add` command for installing
  Markdown skills, recorded as a caveat.
- R07 is A. Its own shipped skill tells the agent to fetch and execute `rea-agents@latest`, including the
  approved setup-apply step that writes client configuration (`SKILL.md:46,60,65`; `src/identity.ts:9`). That is an
  in-repository instruction to execute unpinned code.
- R08 is W. The scaffolds users run pipe installers into a shell and use `@latest` and unpinned base images; only
  the library's own release path is attested.

**Strongest**
- Repository hygiene: R06.
- Pinned runtime-engine verification: R10.
- Publishing provenance: R08.

**Runner-up / alternatives**
- R07: repository-internal pinning as strict as R06, undercut by `@latest` in its skill.

**Claimed, not implemented**
- R07: "Registration is version-pinned" is true for the registered command but not for the skill's diagnostics
  and setup path [R07 §16, §8].
- R06: `SECURITY.md` "latest published release" refers to a single stale tag [R06 §16].

**Candidate verdict:** REIMPLEMENT (R10 `verify_source` pattern); R06 CI workflow is REFERENCE ONLY [R06 §13].

#### D6 Protection of the factory's own judge or grader

**Implementations**
- R09 [Obs]: `protected_files` defaults to the factory's own code, "an agent must not be able to edit the
  machinery that decides whether its work passed" (spot-check `data_types.py:332-337`). Enforced after the fact
  with rollback [R09 §8].
- R05 (unmerged) [Obs]: the grader copies only the implementation; suite and harness hashes are re-checked after
  the run, and any change invalidates it (`evals/run.py:563-614`). The rule "never let the optimising agent edit
  the evaluator" [R05 §7, §10].
- R10 [Obs/Unk]: `protected_paths` defaults are forwarded only to merging workflows (`harness.config.json:6`;
  `consumer.py:221-243`). Enforcement is Archon's [Unk]. `engineering.md`, which an agent once rewrote, is not on
  the list [R10 §8].
- R01 v2 (unmerged) [Obs]: the gate runs the main checkout's checks, so a branch cannot edit what judges it;
  protected-path edits fail (spot-check `factory/bin/gate:9-12`) [R01 §2.4].
- R03 [Obs]: the calibration learner's write allowlist is not OS-enforced (`calibration.md`) [R03 §10].
- Others: none.

R10 is rated U: forwarding the protected paths is in code, but enforcing them is Archon's.

**Strongest**
- Evaluation: R05 (unmerged).
- Runtime: R09.
- Gate design: R01 v2 (unmerged, GPL).

**Runner-up / alternatives**
- R10's MISSION rule "the factory cannot modify its own judge", with protected-path defaults (enforcement
  unknown).

**Claimed, not implemented**
- R10: protected paths "hold any PR touching a match", forwarding only [R10 §16].
- R03: the calibration "edits only allowlisted files", not OS-enforced [R03 §16].

**Candidate verdict:** R09 ADAPT (MIT); R05 and R01 v2 REIMPLEMENT the idea.

### E. Operations and efficiency

#### E1 Observability/tracing

**Implementations**
- R09 [Obs]: a WAL SQLite trace with 7 tables and 10 event types.
  - Tool calls are folded into one spanned row each.
  - Gates record evidence per item.
  - Cost is itemized per phase (input, output, cache read/write, reasoning); context occupancy is tracked
    separately from spend.
  - A process registry, and the exact prompts are saved before execution.
  - A polling visualizer reads the trace.
  - Pi subagents are untraced [R09 §8].
- R08 [Obs]: `IterationUsage` token and cache counts; a per-iteration "Context window" line; an
  `onAgentStreamEvent` hook; file logs. No dollar figures [R08 §8].
- R03 [Obs]: a run manifest per wave, `gh-quota-on-exit:` on every handoff, `status.py`, and a PR history table.
  No per-card token or dollar figures [R03 §8].
- R07 [Obs]: pino structured logs, progress notifications, `doctor` [R07 §8].
- R05 [Obs]: `run.json` state transitions plus the raw SDK stream. Tokens are counted only on the eval branch
  (`usage_all_models`) [R05 §8].
- R01 [Obs]: a dependency-free dashboard polling every 2 s; no cost [R01 §8].
- R10 [Obs]: launch decisions logged with reasons. "Instrument your tokens on day one" ships no instrument
  [R10 §8, §16].
- R02 [Obs]: per-tool logs and JSON only, no workflow-level view (W) [R02 §8]. R04: console output.
- R06 and R11 [Obs]: no logging or tracing; the audit trail is GitHub artifacts (R06) or project files such as
  `build-log.md` and `deploy.md` (R11) (W) [R06 §8; R11 §8].
- R10 is W: launch reasons only, no metrics or traces [R10 §8].

**Strongest:** R09.

**Runner-up / alternatives**
- R08's stream-event hook, for external collectors.

**Candidate verdict:** R09 tracer REUSE (MIT, "directly reusable"; stores full prompts, so secrets need care).

#### E2 Cost and token control

**Implementations**
- R03 [Obs]: the usage guard reads plan usage from a status-line snapshot and pauses new waves at 95%
  (`super-board-usage.sh:1-40`). GraphQL point accounting, a cached card helper and pre-flight batching. No
  token/dollar budget per card in the default backend [R03 §9].
- R07 [Obs]: a token-first priority order; compact schemas; summary-first results; response byte caps; dated
  measurements, some negative [R07 §9].
- R10 [Obs]: the launch gate suppresses empty or duplicate laps. Lap ceilings are only in unmerged PR #58 [R10 §9].
- R05 [Obs]: `--max-turns` 30, `--timeout` 600 s, `--attempts` default 1, all per call. No accounting on main
  [R05 §9].
- R08 [Obs]: `maxIterations` (default 1), idle and completion timeouts, and `AbortSignal`, all enforced in code (A,
  like R05's per-call caps). There is no budget, and templates allow 100 iterations × 10 cycles [R08 §9].
- R09 [Obs]: measured, not capped. Community issue #13 reports a $182.83 run [Claim, R09 §5].
- R06 [Docs/Obs]: phase skipping, and zero idle context through opt-in [R06 §9].
- R02 [Obs]: an iteration cap (prose) and a duplicate-trigger guard (code) [R02 §9].
- R01: ≤3 rounds. R11: offloads computation to deterministic tools.
- R04: an inverted token estimator, `word_count*0.75` (`validator.py:216-218`) [R04 §4.2].

**Strongest:** none enforces a per-task budget. R03's usage guard is the only enforced pause tied to spend.

**Claimed, not implemented**
- R03: "≈20x fewer GraphQL points" [R03 §16].
- R09: "~1M tokens" saved by code phases [R09 §16].

**Candidate verdict:** R03 usage guard REUSE (MIT, Pro/Max only); budget enforcement is BUILD NEW (see §5).

#### E3 Model routing

**Implementations**
- R03 [Obs]: a cheap router classifies complexity, and the result picks a model on a tier ladder
  (`super-board-wave.js:176-184,290-307`). Review stays on the session model; a Codex fallback handles build/QA
  [R03 §2, §9].
- R09 [Obs]: per-agent model and thinking level in the roster; ADWs name agents, never models; whole-roster swap
  with `--config` [R09 §9].
- R01 [Obs]: static `opus`/`sonnet` per agent. The v2 branch adds risk/surface routing (`config.json:11-19`)
  [R01 §9].
- R08 [Obs]: chosen per call by the caller. Templates use Opus to plan and Sonnet to implement [R08 §9].
- R04 [Obs]: fixed per agent; generated agents default to `opus` [R04 §9].
- R10 [Claim]: Archon tiers; Sonnet-for-large was tried and reverted [R10 §1.1].
- R05: a single `--model`. R02, R06, R11: none.

**Strongest:** R03, the only dynamic, per-task routing. No repository measured whether routing helps.

**Runner-up / alternatives**
- R09: a static per-agent roster that can be swapped whole.
- R01 v2 (unmerged): risk/surface routing.

**Claimed, not implemented**
- R03: the README's concrete model names ("Sonnet 5.5 / Opus 5.5 / Haiku 4.5"), while the code passes aliases.
- R03: the Codex ladder's rationale ("ties … on DeepSWE") [Claim, R03 §2, §16].

**Candidate verdict:** REIMPLEMENT.

#### E4 Invocation control and context footprint

**Implementations**
- R06 [Obs/Docs]: all 12 skills set `disable-model-invocation: true` plus Codex `allow_implicit_invocation:
  false`, and a unit test guards it (spot-check `scripts/tests/test_check_repo.py:71-81`).
  - In Claude Code this keeps descriptions out of context: zero idle cost [Docs via R06 §9].
  - Dependencies are read as files so blocked skills still compose (`skills/factory/SKILL.md:18`).
- R07 [Obs]: compact input schemas by default; output schemas optional; a deferred, digest-verified catalog [R07 §9].
- R03 [Obs]: a 47-line router skill. But each lane reads `run.md` (816 lines) plus a 300-700-line lane skill
  [Inf, R03 §9].
- R09 [Obs]: lazy cookbooks, "do nothing until asked" [R09 §6].
- R02 [Obs]: per-platform references loaded on demand; effort scaled to the task (`AGENTS.md:6-13`) [R02 §9].
- R11 [Obs]: ~5.7k characters of descriptions; broad triggers ("how does X work") and no negative triggers [R11 §4, §9].
- R04 [Obs]: 1,000-line prompts and a 1,109-line SKILL.md [R04 §9].

**Strongest:** R06 for skills; R07 for MCP tool surfaces.

**Runner-up / alternatives**
- R09 and R02: lazy, progressive loading of references.

**Claimed, not implemented**
- R04: "~155 lines" for CLAUDE.md, which has 235 [R04 §16].
- R06: Codex idle cost under its opt-out flag is [Unk] [R06 §9].

**Candidate verdict:** REIMPLEMENT (pattern; the R06 test hardcodes the count of 12).

### F. Improvement and planning

#### F1 Continuous improvement / learning capture

**Implementations**
- R05 [Obs]:
  - The evaluation-driven change discipline is on the unmerged branch: freeze the suite and baseline, change one
    element, keep failures as regressions, never let the optimizer edit the evaluator. Cohort v4 rejected a
    candidate reviewer prompt and kept it opt-in (`v4/README.md:3-5,146-152`).
  - Main has an `improve-factory` skill that counts a problem only if it was corrected in ≥2 PRs and never merges
    (prose) [R05 §10].
- R03 [Obs]:
  - Optional, default-off calibration: a bounded receipt (`completion.json` ≤ 64 KiB) is validated, and an
    external learner may edit only an allowlist of ≤20 existing SKILL.md files, reviewed by diff
    (`super-board-calibration.py:50-57`).
  - `super-collect prs` correction prevention.
  - The eval-staleness Stop hook.
  - Dated incident notes tied to mechanisms [R03 §10].
- R10 [Obs]: `docs/incidents.md` (65 entries, "What happened / The cause / The rule") plus mutation self-checks
  [R10 §10].
- R07 [Obs]: agent-experience evals and efficiency experiments feed tool design [R07 §10].
- R08 [Obs]: ADRs, `.out-of-scope/` decisions, a permission-bug catalogue [R08 §10].
- R09 [Obs]: lessons as incident-narrating code comments [R09 §10].
- R02 [Obs]: dogfooded greploop iterations [R02 §10].
- R06: only a proposed roadmap. R01, R04, R11: none.

**Strongest**
- Controlled-change methodology with demonstrated application: R05 (unmerged).
- A bounded, reviewable self-edit loop: R03 (the learner itself is external, and the limit is not OS-enforced).
- No repository shows an automated closed loop with measured improvement.

**Claimed, not implemented**
- R03: "Self-improving software factory" (partly) [R03 §16].
- R04: roadmap items [R04 §10].

**Candidate verdict:** R05 REIMPLEMENT; R03 receipt validator REFERENCE ONLY [R03 §13].

#### F2 Specification and planning artifacts

**Implementations**
- R06 [Obs]:
  - `/requirements` (REQ-n, "do not invent"); `/architecture` (Mermaid, INV-n with intended enforcement and
    proof, decision status separate from implementation status).
  - `/spec` (acceptance table `ID | Done when | How to check`, "do not invent executable commands").
  - `/plan` (two-reader tickets, 250-500 words, never persisted) [R06 §4, §12].
- R11 [Obs]: an ID-keyed recon map; an inferred data model with evidence and confidence; explicit non-goals as
  `skip` rows; S/M/L/XL sizing, where XL means "rescope it" [R11 §11.2].
- R10 [Obs]: `MISSION.md` "never, not 'not yet'" list; open questions (merge held) kept separate from irreversible
  decisions (stop); end-to-end journeys; holdout [R10 §4, §12.7].
- R01 [Obs]: the spec template's "Assumptions" become an approver escalation hook; demonstrated in two example
  specs (`spec-writer.md:51-53`; `approver.md:46-47`) [R01 §12].
- R03 [Obs]: AC lint (`lint.md`); one test per AC; a risk block (unmerged branch adds Door/Blast radius) [R03 §4, §17].
- R09 [Obs]: planner writes `specs/<adw_id>_<slug>.md` [R09 §6].
- R05 [Obs]: the story example's PRODUCT/TECHNICAL_SPEC; a spec-stage gate is on unmerged PR #8 [R05 §4].
- R02, R04, R08: thin or template-filling.

**Strongest:** R06 for forward delivery; R11 for specification derived from a reference.

**Runner-up / alternatives:** R10's governance templates.

**Claimed, not implemented**
- R11: "sizes it honestly before you start", an instruction only [R11 §16].
- R05: the spec-stage gate exists only on unmerged PR #8 [R05 §4].

**Candidate verdict:** R06 `/plan`, `/spec` REUSE (MIT, "directly reusable"); R10 REIMPLEMENT.

#### F3 Requirement traceability

**Implementations**
- R07 [Obs]: each obligation needs a unique owner (module, symbol, implementation SHA-256), every required case
  kind, and a verifier that **enumerates** the obligation (`ReconstructionObligationLedgerEvaluation.ts:173-245`) [R07 §5].
- R06 [Obs, prose]: REQ/AC/INV IDs are never renumbered and are carried through spec, test report and review
  findings [R06 §6].
- R11 [Obs]: S/F screen and flow IDs, F01-H1/E/N test IDs, BUG-nnn. The `features.csv` status is self-reported and
  not linked to test results [R11 §6, §11.5].
- R03 [Obs]: stable R-ids in the review report; one test per AC [R03 §6].
- R01 [Obs]: per-AC evidence in `build.md` [R01 §7].

**Strongest:** R07 is formally the strongest, but only for reconstruction obligations. R06 is the best for
software delivery, though prose.

**Runner-up / alternatives**
- R11: IDs cover screen → flow → test → bug, but parity status is not linked to test results.

**Claimed, not implemented**
- R11: `/replica-diff` "gives you a real number, not a vibe", but over self-reported values [R11 §16].

**Candidate verdict:** REIMPLEMENT.

### G. Reference-driven development

#### G1 Reference-driven development: sources, provenance, reuse decisions

**Implementations**
- R11 [Obs]: an 8-row source hierarchy with "a URL on every row" (`replica-recon/SKILL.md:58-69`).
  `reviews.py` drops unlinked rows and quotes only exact substrings (`reviews.py:104-111,138-150`; tested) [R11 §11.1, §11.6].
- R07 [Obs]: Evidence carries `confidence` (observed/derived/inferred) and `authority`
  (shipped-artifact/controlled-replay/…) as separate axes; "unknown is not absence" [R07 §6, §12].
- R03 [prose]: docs-first rule: read the current official docs for the installed version and cite them as `Docs:`
  bullets (`super-build/SKILL.md:274-290`) [R03 §11].
- R06 [prose]: verify claims about the existing system against code and runtime evidence [R06 §11].
- R04 [Obs]: "validate against official native examples", a rule its own hook generator breaks [R04 §11].
- R02 [Obs]: vendored skills with attribution, but drift (greploop rewritten yet still credited upstream; unslop
  differs from upstream) [R02 §16].

**Strongest:** R11 and R07 for provenance of reference evidence. **No repository implements a REUSE / ADAPT /
COMPOSE / REIMPLEMENT / BUILD NEW decision step for supplied references.**

**Runner-up / alternatives**
- R03's docs-first rule: cite current official docs for the installed version (prose).

**Claimed, not implemented**
- R04: "Always validate your output against official native examples", which its own hook generator contradicts
  [R04 §11].
- R02: `unslop` "body matches upstream", contradicted for the current upstream [R02 §16].

**Candidate verdict:** R11 `reviews.py` ADAPT (MIT); the reuse-decision capability is BUILD NEW.

#### G2 Application reverse engineering

**Implementations**
- R07 [Obs]: 220 deterministic MCP tools over native, JS/Electron, .NET, Android, firmware, captures, and more.
  Application Graphs; version and source-to-bundle comparison with "no fuzzy pairing". There is no planner; the
  host agent drives (`toolEffects.ts:55-728`; `applicationToolContracts.ts:126-195`) [R07 §4, §11].
- R11 [Obs]: product-level only, from public sources. It explicitly forbids JS bundle analysis and decompiling
  (`replica-recon/SKILL.md:38-40`) [R11 §8].
- Others: n/a.

**Strongest:** R07. Caveats: 15 tools execute foreign code with user permissions; HTTP mode has no
authentication (a documented limit); six major versions in three months; main CI unstable on the evaluation day [R07 §1, §8].

**Runner-up / alternatives:** none found. R11 works at product level from public sources only, by design.

**Claimed, not implemented**
- R07: the DX-Ball and TH04 showcase results live in external repositories and were not verified
  [R07 §11.5, §16].
- R07: "One MCP for reverse engineering across binaries, apps and runtime behaviour" (partly; not executed).

**Candidate verdict:** R07 REUSE as an external tool, not as code [R07 §13].

#### G3 Specification extraction

**Implementations**
- R11 [Obs, template-driven]:
  - A screen inventory with enumerated states; flows with click counts; components.
  - An inferred data model with evidence and confidence, turned into SQL with explicit rules
    (`replica-architect/SKILL.md:44-81`).
  - Explicit non-goals [R11 §11.2].
- R07 [Obs, tool-driven]: Application Graph extractors, mobile and managed graphs. Static candidates are kept
  separate from runtime proof. It does **not** write a specification document [R07 §11].

**Strongest:** they work at different levels; neither is Strong. R11 has the best specification *model* but no
automated capture. R07 has the best automated *extraction* but no specification output.

**Runner-up / alternatives:** none found outside G-RE. R10's existing-codebase mode only answers setup questions
[R10 §11].

**Claimed, not implemented**
- R07: "build a version for your project" [Claim]. REA produces no specification document [R07 §11].

**Candidate verdict:** COMPOSE (R07 extraction feeding an R11-style specification model), REIMPLEMENT for the
R11 schema.

#### G4 UI/UX reconstruction

**Implementations**
- R11 [Obs]:
  - Design tokens are extracted as roles, not values; the rebrand changes values while names stay.
  - Component specs list every state; primitives are built first.
  - Screens are built one by one in every state at 390 and 1440 px.
  - `contrast.py` is a WCAG gate (tested) [R11 §11.3].
- R03 [Obs]: `ui-refine-loop` polishes an *existing* UI: critique → fix → grade rounds with screenshots (light/dark,
  1440/390) [R03 §11].
- R07 [Obs]: capture tools only [R07 §11].

**Strongest:** R11. It is prose apart from `contrast.py`; no repository automates reconstruction.

**Runner-up / alternatives**
- R03 `ui-refine-loop`: improves an existing UI against a taste file; it does not reconstruct one.

**Claimed, not implemented:** none found. Note that R11's README says "the skills enforce it" about the asset
rules, but only `sweep.py` (hex colours, names, domains) checks them, and binaries are skipped [R11 §11.7].

**Candidate verdict:** R11 `contrast.py` REUSE (MIT); the method is REIMPLEMENT.

#### G5 Visual verification

**Implementations**
- R11 [Obs]: `imgdiff.py` layout mode. Edge density on a 12-column grid, so a rebrand keeps the layout score;
  drift is localized in the original's coordinates. Includes a stdlib PNG codec. Tested, including rebrand
  invariance (`test_imgdiff.py:145-162`).
  - Limits: thresholds are uncalibrated; per-cell density only; capture is manual [R11 §11.4].
- R02 [Obs]: the evidence recorder burns assertion annotations into video, with a PID-reuse-safe process control
  and an isolated Playwright runner. The pass/fail annotations are typed by the working agent [R02 §5, §7].
- R03 [Obs]: the Tester commits screenshots at 3 viewports via SHA-pinned URLs. A `ui-refine-loop` finish reviewer
  grades each fix. `runtime_compare.py` compares timing and heap, treating noisy results as inconclusive [R03 §11].
- R01 [Obs]: `agent-browser` checks, skipped in 3 of 4 reviews [R01 §7].
- R06 [prose]: real-browser proof required in `/test` [R06 §11].
- R07 [Obs]: browser, Electron and native-UI capture tools exist in code (contracts read); their behaviour was not
  executed or traced, and there is no image comparison. Rated W: capture without comparison or gate [R07 §11].
- R10: browser driver only in unmerged PR #60, not rated. Others: none.

**Strongest**
- Automated comparison: R11.
- Capture: R02.
- No repository uses automated capture, comparison and a threshold together as a gate.

**Runner-up / alternatives**
- R03: committed, SHA-pinned screenshots plus a finish reviewer that grades each fix (LLM judgement, not a metric).

**Claimed, not implemented**
- R01: UX/UI reviewers "check the running app", contradicted in 3 of 4 example reviews [R01 §16].
- R09: "browser-validated through the factory", with no browser tooling in the factory [R09 §16].
- R02: the recorder "verifies the result", which means only that the video is playable [R02 §16].

**Candidate verdict:** R11 `imgdiff.py` REUSE (MIT, with its crash fix pending: issue #10); R02 recorder
REFERENCE ONLY (no licence).

#### G6 Feature-parity measurement

**Implementations**
- R07 [Obs]: a fail-closed obligation ledger with case kinds and a proof-authority lattice. Spot-check
  `ReconstructionObligationAuthority.ts:15-61`: a required `packaged-process` proof is satisfied only by
  `packaged-process` or `live-observation`; `native-abi` only by `native-abi`; a required `unit` proof accepts any
  authority. Concurrent behaviour is compared by partial order.
  - Material gaps: Evidence "authentication" is a content digest, not a signature, so fabricated records pass, and
    no non-test code produces `rea.reconstruction-proof` [R07 §5, §6].
- R11 [Obs]: `parity.py` weights must 3 / should 2 / could 1, excludes skip and differentiator rows, and folds in
  20% layout.
  - Gaps: the `clone` column is self-reported; the deploy preflight exits 0 on missing must-haves (spot-check
    `parity.py:218-224`) [R11 §11.5].
- R03 [Obs]: runtime performance parity only (`runtime_compare.py`) [R03 §11].

**Strongest:** R07 formally; R11 pragmatically. Neither ties parity to independently produced proof.

**Runner-up / alternatives**
- R03 `runtime_compare.py`: timing and heap parity, with noise counted as inconclusive.

**Claimed, not implemented**
- R07: Evidence "must authenticate" is integrity only [R07 §16].
- R11: "Missing must-haves means not shippable", which it prints but does not signal by exit code [R11 §16].

**Candidate verdict:** R07 ledger REIMPLEMENT (or ADAPT); R11 `parity.py` REUSE (MIT).

### H. Distribution

#### H1 Installation/distribution

**Implementations**
- R08 [Obs]: an npm package published with OIDC attestations; `sandcastle init` scaffolds Dockerfile, env,
  prompts and templates [R08 §7].
- R07 [Obs]: `rea setup` shows a dry-run plan, asks for approval and writes backups, for about 15 clients
  (`Setup.ts:255-290`) [R07 §5].
- R03 [Obs]: a plugin, `get.sh` with a `main()` wrapper and root refusal, and an `install.sh` that installs into a
  shared `.agents/` tree with per-host symlinks and is tested (`tests/test-install.sh`). No checksum [R03 §8].
- R10 [Obs]: an installer that preserves personal files, backs up machinery files and clones a pinned SHA. It
  never deletes files removed from the template [R10 §6].
- R09 [Obs]: an idempotent stamp that doubles as a drift report; `--force` overwrites [R09 §16].
- R11 [Obs/Docs]: a Claude Code plugin plus marketplace; `"skills": "./"` is accepted per current docs [Docs via R11 §16].
- R04 [Obs]: `cp -r`. Its settings installer is atomic with backup rotation (`installer.py:50-189`) [R04 §12].
- R05 [Obs]: `uv tool install`. R06, R02 [Obs]: unpinned `npx skills add`. R01: copy-in.

**Strongest:** R08 for release provenance; R07 and R03 for safe installation into a host.

**Runner-up / alternatives**
- R10's upgrade, which keeps "personal" files and backs up machinery files.
- R09's idempotent stamp that doubles as a drift check.

**Claimed, not implemented**
- R01 v2: the install path fetches files from `main`, where `SF2/` does not exist [R01 §2.4].
- R04: "where is the marketplace?" (issue #1024) [R04 §2.2].
- R11: PR #4's claim that the plugin layout is rejected is contradicted by current docs [Docs via R11 §16].

**Candidate verdict:** REIMPLEMENT the patterns; R04 settings installer ADAPT (MIT).

#### H2 Cross-agent portability

**Implementations**
- R08 [Obs]: two orthogonal provider contracts: 6 agent CLIs × 5 sandbox backends (`AgentProvider.ts:264-277`;
  `SandboxProvider.ts:24-330`) [R08 §12.1].
- R07 [Obs]: an MCP server usable by any MCP host, with setup for about 15 clients [R07 §1].
- R03 [Obs]: Claude Workflow, Codex and legacy backends; host detection is tested; OpenCode is detected and
  refused [R03 §16].
- R06 [Obs]: dual-client opt-in flags. The coordinator is Codex-only by design [R06 §3].
- R09 [Obs]: Pi only; the Claude Code adapter raises `NotImplementedError` (`M/agent_cc.py:11-15`) [R09 §1].
- R02 [Claim]: the `AGENTS.md` convention. R04 [Obs]: `codex-cli-bridge`. R10 [Claim]: through Archon.
- R01, R05, R11: Claude Code only.

**Strongest:** R08 for agent runtimes; R07 for tool platforms.

**Runner-up / alternatives**
- R03: three execution backends behind one lifecycle document.
- R06: dual-client invocation flags.

**Claimed, not implemented**
- R02: "For Claude Code, Cursor, and Codex", not demonstrated [R02 §16].
- R03: OpenCode support, detected and refused [R03 §16].
- R09: the Claude Code adapter is a stub [R09 §1].

**Candidate verdict:** R08 REUSE as a dependency (MIT, pre-1.0, breaking `v1` pending).

---

## 3. Engineering-practice comparison (per repository)

Test counts were re-verified in the clones (§6). Other figures (commits, releases, CI runs, open PRs and issues)
come from the reports, which took them from `gh api` metadata. No tests were executed by anyone.

| Repo | Tests (count; what they cover) | CI | Typing / linting | Release discipline | Docs vs code drift | Maintenance (2026-10-22) |
|---|---|---|---|---|---|---|
| R01 Galea | None [R01 §7] | None (0 workflows) | None | No tags or releases; one commit added the folder (2026-10-02) | BUILD_PROMPT describes an obsolete `board.json`; orchestrator writes `decision.md` despite "never write decisions" (`SKILL.md:9-10` vs `:151-154`) [R01 §15] | Static v1; unmerged and incomplete v2 branch (GPL-3.0) |
| R02 Ras Mic | 61 functions / 71 cases: review freshness (stale, edited, imposter, wrong commit), recorder real-process, Playwright runner [R02 §7] | None | Type hints; no linter or type checker | No tags | greploop credited upstream but rewritten; unslop drifted; "PolyForm Shield" text non-canonical [R02 §16] | Active (37 commits Jul–Oct 2026) |
| R03 Super-Board | 62 suites (36 sh + 26 py, 286 py test functions): merge gate locking and head pins, approval, reads, orchestration script stubbed, installer; 7 paid evals [R03 §7] | Cross-platform smoke (incl. Windows) + safety suite on Linux/macOS; `release.yml` ships only the tested SHA; actions tag-pinned, `persist-credentials: false` | No linter or type checker; `node --check` on workflows | Tags v1.2.0 → v3.1.2; 35 commits since the last tag | `humanApprovesMerge`, the 422 claim, and the wave-plan lock comment contradict code [R03 §14, §16] | Active (two committing accounts) |
| R04 Rezvani | None [R04 §7] | `compileall` + `safety` + link check; YAML lint commented out | Type hints only | README 1.4.0 vs CHANGELOG 1.5.0/2.2.0 vs status 2.1.0 | Promised examples gitignored; "Four-Layer Security Model" has no code; hook format contradicts its own docs copy [R04 §7, §16] | Dormant since 2025-11-12; 7 unreviewed PRs |
| R05 Lewis Factory | 17 functions / 28 cases (fake agents, real subprocess/git; exit codes, schemas, denials); +12 harness tests on unmerged branch [R05 §7] | `uv sync --locked`, pytest, ruff check, ruff format --check; tag-pinned actions | ruff; Pydantic `strict`/`extra="forbid"`; no type checker | No releases; 12 commits in one week | Low; a blank-command validation hole is fixed only on a branch [R05 §7] | Young; key work in open PRs #4, #5, #8 |
| R06 Blueprint | 28 (11 repo checks, 4 diff checks on real git, 13 renderer incl. a network-isolation test) [R06 §7] | Single job, SHA-pinned actions, `contents: read`; green on 12 main runs | `bash -n`, `git diff --check`; no Python linter | One stale tag v0.2.0; CHANGELOG "Unreleased"; both npm Dependabot PRs fail CI [Inf cause] | Low; high skill churn (MIGRATION) | Active |
| R07 REA | 2,081 `*.test.*` files (boundary 956, domain 303, acceptance 181, …) + ~100 real-toolchain `verify:*` lanes [R07 §7] | Hourly/daily qualification on Linux/macOS/Windows, SHA-pinned; last 100 main runs: 19 ok / 14 fail / 66 cancelled (bulk merge) | Strict TS, oxlint, oxfmt, knip, jscpd, boundary verifier; mutation testing non-blocking | release-please, 38 releases, 6 majors in 3 months | Main ahead of npm; prose correct in sampled areas | Very active, high churn |
| R08 Sandcastle | 54 files, ~1,416 cases (recount 1,413 with a different regex), fake-agent replay on real git repos [R08 §7] | Push to main only: build + test; no typecheck or lint in CI; no PR CI | `tsgo` locally; Prettier pre-commit; public-types firewall | Changesets + OIDC trusted publishing with attestations; no release since v0.12.0 (2026-06-29) | ADR 0015 contradicted; ADR 0007 and `AgentInvoker` unimplemented; stale `.sandcastle/run.ts` [R08 §16] | Active, pre-1.0, breaking `v1` pending |
| R09 SSSF | None [R09 §7] | None | Pydantic models; visualizer typecheck/lint not wired | No tags; squashed single commit per branch | Heavy: generator calls a removed API; example branch breaks 5 ADWs; SKILL.md and observability docs drift [R09 §7] | Last commit 2026-08-02; issues open |
| R10 Medin | 83 unittest methods (real git, fake Archon CLI, runtime host process cleanup) + guard self-mutation + AST audit; real-Archon conformance skipped by default [R10 §7] | None | Type hints; no linter | 0 releases or tags; several pin bumps a day | Overlap skip vs "queues"; incident log describes removed code; dead fixture ledger; unused port-killing `appproc.py` [R10 §8] | 7 weeks old, very active; `consumer.py` slated for retirement |
| R11 Replica | 57 unittest (PNG codec against an independent encoder, rebrand invariance, quote-substring provenance) [R11 §7] | None | None | v1.0.0 in manifest; no tags | "the skills enforce it" overstated; walkthrough figures unbacked [R11 §16] | One commit; 12 unmerged issues/PRs incl. a crash fix |

**Within-group observations** [Inf from the table]
- G-ORCH: R03 and R08 combine large test suites with CI and disciplined releases. R05 is small but complete for
  its scope. R09 and R10 have serious mechanisms with no CI: R10 compensates with self-mutation; R09 has none.
- G-PACK: R06 is the only pack with CI and tested code. R01 and R04 have none, and R04 is dormant.
- G-RE: R07 has the deeper engineering practice of the two, with current instability. R11 has a well-tested small
  tool set but no CI.

---

## 4. Claimed but not implemented: consolidated list

| Repo | Claim | Status | Source |
|---|---|---|---|
| R03 | `humanApprovesMerge` serializes Review | contradicted | [R03 §16] |
| R03 | Rebuild cap via `root-cause-hash` | prose only; no script | [R03 §5] |
| R04 | factory-guide delegates; hooks "block"; kill switch halts workflows; 4-layer security | contradicted / not found | [R04 §16] |
| R05 | Reviewer does not edit the workspace | prompt only on main | [R05 §16] |
| R06 | Delivery skills test, review, pass CI | instructions only | [R06 §16] |
| R08 | ADR 0015 (no bypass under `noSandbox()`); ADR 0007 locking | contradicted / not found | [R08 §16] |
| R09 | `parent_id` span nesting; `queued` status; runnable `make_adw.py` | not found / contradicted | [R09 §16] |
| R10 | Two independent reviewers decide merges; deterministic sealed merge gate | not in this repo (Archon) | [R10 §16] |
| R11 | "the skills enforce it"; must-haves gate deploy | partly; preflight exits 0 | [R11 §16] |
| R01 | UX/UI reviewers check the running app | contradicted in 3/4 examples | [R01 §16] |
| R02 | Recorder "verified" | only "video is playable" | [R02 §16] |
| R07 | Evidence "must authenticate" | integrity digest, no provenance | [R07 §16] |

---

## 5. Gaps across all 11 (capabilities important to the value definition that no repository demonstrates well)

1. **Tool-enforced least privilege for verifier roles (SR, EQ).** No default branch restricts reviewers or
   verifiers by tool *and* detects tampering. R05 removed its `disallowed_tools` + `unchanged()` check [R05 §8].
   R09's boundary is after the fact and blind to ignored paths [R09 §8].
2. **Untrusted-input enforcement for agents that hold write capability (SR).** The only structural instance is
   R08's explore privilege split. R07 labels content, and everything else is prose or absent [§D4].
3. **Per-task cost budgets and cost per accepted deliverable (RE).** None enforce a token or dollar budget per task.
   R09 measures, R03 pauses on plan usage, and no repository reports cost per *accepted* deliverable outside R05's
   unmerged harness [§E2].
4. **Evidence that orchestration adds value (AO, EQ).** Only R05 (unmerged, synthetic, author data, not re-run)
   compares against a matched baseline, and it finds parity with a prompted reviewer subagent (30/36 vs 29/36)
   [R05 §9]. No other repository measures throughput, first-pass acceptance or human interventions per task.
5. **Verification evidence with provenance (EQ, SR).** Nothing signs or attests verification results. R07 has
   integrity only; R03's human approval is only as strong as token separation; R11's parity is self-reported
   [§C1, §G6].
6. **Mechanical traceability from requirement to passing test (EQ).** No repository links requirement or
   acceptance IDs to executed test results, except R07 for reconstruction obligations with caller-supplied
   proofs [§F3].
7. **Reuse-decision capability (MA, DP).** No repository decides REUSE / ADAPT / COMPOSE / REIMPLEMENT / BUILD NEW
   for supplied references, although the value definition requires it [§G1].
8. **Visual verification as an automated gate (EQ).** Capture (R02), comparison (R11) and screenshots (R03) exist
   separately. None combine them into a threshold-gated step [§G5].
9. **Failure-recovery and autonomy measurement (AO).** No repository measures recovery success or human
   interventions per task; recovery mechanisms exist, but their effectiveness is unmeasured [§A4].
10. **Isolation that covers git metadata, network and secrets together (SR).** R08 comes closest but leaves `.git`
    writable, the network open and secrets in argv [§D2].
11. **Behavioural evals as a standing regression gate (EQ, MA).** R03's evals are paid and offline with results
    gitignored; R07's agent eval is not in CI; R05's harness is unmerged [§C4].
12. **Clean-room role separation in reference-driven builds (SR, EQ).** R11 uses one session to study the original
    and write the clone [R11 §3]. Among the reference-driven projects, nothing separates the context that studies
    the original from the one that implements it. In forward delivery, R01 (spec-writer vs builder subagents,
    [R01 §3]) and R09 (planner vs builder agents, [R09 §3]) do separate the specifying and implementing agents.

---

## 6. Spot-checks performed in the clones (2026-10-22, read-only)

| # | Repo | Location checked | Result |
|---|---|---|---|
| 1 | R03 | `scripts/super-board-merge-gate.sh:346-372` | `--match-head-commit "$HEAD_SHA"`; lost-response reconciliation; exit 6 on moved head. Confirms [R03 §5] |
| 2 | R03 | `scripts/super-board-approval.py:110-133` | Edited request voids; author `User` with write/maintain/admin; created after request and unedited. Confirms |
| 3 | R03 | `workflows/super-board-wave.js:67-86, 94-108` | `STAGE_SCHEMA` status enum; promise-chain mutex removal note. Confirms |
| 4 | R03 | `hooks/guard-secrets.py:62-63`; `hooks/dev/gate-skill-evals.py:1-36` | `except Exception: pass` (fail open); Stop hook exits 2 on a stale eval. Confirms |
| 5 | R05 | `src/factory/runner.py:53-90` | `allowed_tools=tools`, `dontAsk`, `strict_mcp_config`, `setting_sources=[]`, denial → error. Confirms |
| 6 | R05 | branch `codex/eval-suite` `evals/run.py:64-89, 120-151` | Tool-event review evidence; grader copies only `app.py`, `python -I`, fail-closed. Confirms |
| 7 | R08 | `src/Orchestrator.ts:143`; `src/createSandbox.ts:631` | Both hard-code `dangerouslySkipPermissions: true`. Confirms [R08 §8] |
| 8 | R08 | `src/SandboxFactory.ts:264-288` | `.git` (and parent `.git` for worktrees) mounted at host paths, no read-only flag set here. Consistent with [R08 §8] |
| 9 | R09 | `adw_modules/permissions.py:1-30`; `data_types.py:332-337`; `gates.py:61-68` | After-the-fact change-set enforcement; protected machinery defaults; `diff_matches_claims` checks existence only. Confirms |
| 10 | R10 | `bin/selfcheck-mutations.py:9-41` | 5 anchored defects; `NOT_INJECTED`/`NOT_CAUGHT`/`CAUGHT`. Confirms |
| 11 | R11 | `replica-diff/parity.py:218-224` | Exit 1 only with `--fail-under`; otherwise 0. Confirms |
| 12 | R07 | `src/application/ReconstructionObligationAuthority.ts:15-61` | Lattice as reported. Also observed: a required `unit` proof accepts any authority incl. `external` |
| 13 | R07 | `src/server/toolResultEncoding.ts:24-37` | `untrusted_content: true`, `source: "analysis_target"` plus instruction text. Confirms |
| 14 | R06 | `scripts/tests/test_check_repo.py:71-81` | Asserts 12 skills, both opt-out flags. Confirms |
| 15 | R02 | `greploop/scripts/github_review.py:45-63` | Head check, trigger time, baseline exclusion. Confirms |
| 16 | R01 | branch `8a428453` `…-v2/factory/bin/gate:1-12, 85-105` | Main-checkout checks and protected paths; also a `--hook` SubagentStop mode (exit 2) not mentioned in [R01] |
| 17 | R08 | `src/SessionStore.test.ts`, `src/SessionStore.windowsPath.test.ts` | Both exist; 42 + 1 `it(`/`test(` cases (correction pass, P2-10) |
| 18 | R03 | `scripts/super-board-merge-policy.py:133` | `(policy.get("default") or "auto") == "human"`: the code default is `auto` (correction pass, P2-2) |

Test counts re-verified: R03 62 suites / 286 py test functions; R05 17 (+12 branch); R06 11+4+13; R07 2,081 files;
R08 54 files / 1,413 by my regex; R10 65+13+5; R11 57; R02 33+25+3.

---

## Limits of this analysis

- **Nothing was executed.** Ratings rest on the phase 1 reports (already verified and corrected) plus the 18
  spot-checks. Runtime behaviour, test pass status, costs and security impacts remain unverified. The security
  impacts the reports mark [I] (R08 git-hook escape, branch-name injection) are inferences.
- **Ratings are capability-local.** A per-repository row in §1 is not a project score and must not be summed.
  Group differences (G-ORCH / G-PACK / G-RE) mean an "–" often reflects scope, not quality; n/a marks the clear cases.
- **Archon was not inspected.** R10's agent, review and merge behaviour is [Unk], so R10 is rated U for A1, B2, C1,
  C2, C4, D1, D4, D6, E3 and H2; those cells say nothing about Archon's quality either way. In-repo components
  (identity binding, brakes, launch gate) are described in the text.
- **Branch-only capabilities** (R01 v2, R05 eval suite and dogfood, R06 roadmap) are marked "b" and are not counted
  as the repository's default capability. R08 `v1` and R10's unmerged PRs #58 (lap ceilings) and #60 (browser
  driver) are mentioned in the text but not rated; the R10 cells for E2 and G5 rate `main`.
- **Benchmark figures are the authors' own data.** R05's figures were recomputed from published JSON, not re-run.
  R03, R09 and R07 efficiency claims are tagged as in the reports.
- **[Docs] facts are taken from the phase 1 reports** (official docs accessed 2026-10-22) and were not re-fetched here.
- **Not covered:** the parts the phase 1 reports skipped (most REA providers, Super-Board's docs site and auxiliary
  skills, R04's domain skills).
- **Licence notes are not legal advice.** Candidate verdicts are generic and provisional; this document makes no
  project-specific adoption decision.

## Report discrepancies found

No material discrepancies. Two minor notes, neither of which changes a finding:
1. **[R01 §2.4] omission.** The v2 branch's `factory/bin/gate` also has a `--hook` mode, documented as a "builder
   SubagentStop hook: run the checks once, exit 2 on failure" (`gate:7`, handler at `:85-105`). It is a
   Claude Code-native stage-enforcement mechanism on the unmerged branch.
2. **[R08 §7] count variance.** The test-case count is "~1,416" in the report; my regex gives 1,413 across the same
   54 files. The difference is within the report's "~", and comes from different regex patterns.

## Verification corrections (2026-10-22)

An independent verifier rated this document accurate with corrections. Each finding was checked against the
evidence before it was applied.

- **P2-1 applied (partly by change, partly by explanation).** I re-checked each divergent cell against D1 §4.
  - Changed to agree with D1: A1 R09, A3 R08, C1 R05, C1 R10, C2 R04, C2 R05, C2 R10, C3 R07, permissions R01 and
    R11, isolation R10, untrusted input R02, supply chain R07 and R08, observability R02/R06/R10/R11, cost R08.
  - Kept, with reasons in the "Rating scales and divergences from D1" note in §1: A3 R09, C2 R08, permissions R09,
    untrusted input R08, cost R06, cost R07, continuous improvement R05. (Superseded by the follow-up below.)
  - Also set D6 R10 to U, for consistency with C1/C2.
- **P2-2 applied.** §C2 R03 now states that the shipped and code default is `auto` (`merge-policy.py:133`,
  spot-check 18), and that code matching no category merges without a human.
- **P2-3 applied for R07** (D5 → A, C3 → A). **Not applied for D5 R06:** S is kept because everything the
  repository itself pins or runs is pinned. The unpinned path is the third-party `npx skills add` command for
  installing Markdown skills, recorded as a caveat. R07's `@latest`, by contrast, is an in-repository instruction to
  execute unpinned code. The reasoning is stated in §D5.
- **P2-4 applied.** The bold legend now reads "named Strongest in §2", and bolding was redone for every row.
- **P2-5 applied.** G5 R07 changed from U to W (capture tools are in code but not executed; there is no comparison).
- **P2-6 applied.** The Limits section lists every R10 U cell (A1, B2, C1, C2, C4, D1, D4, D6, E3, H2). The
  branch-only scope is clarified: R10's PRs #58/#60 and R08 `v1` are not rated, and the R10 cells for E2 and G5
  rate `main`.
- **P2-7 applied.** The §3 header now says test counts are re-verified and other figures come from the reports'
  `gh api` metadata.
- **P2-8 applied.** Gap 12 is restricted to reference-driven builds. R01 and R09 are noted as separating the
  specifying and implementing agents in forward delivery.
- **P2-9 applied.** The §3 G-RE sentence compares R07 within the group only.
- **P2-10 applied.** §A3 cites `src/SessionStore.test.ts` (42 cases) and `src/SessionStore.windowsPath.test.ts`
  (spot-check 17).
- **P2-11 applied.** Runner-up and "Claimed, not implemented" entries were added to C3, C5, D5, D6, E3, E4, F2, F3,
  G1–G6, H1 and H2, with "none found" where applicable.
- **P2-1 follow-up (after D1's re-sync).**
  - C2 R05 is reverted from A to n/a, agreeing with D1 (verifier finding P1-8): the runner never commits, pushes or
    merges, so there is nothing for a gate to hold. The §C2 text is updated to match.
  - D1 changed its A3 R09, D4 R08 and F1 R05 cells to match this document, so those entries were removed from the
    kept list.
  - The note now keeps exactly four divergences: C2 R08 (approval gates), D1 R09 (permission model), E2 R06 and
    E2 R07 (cost).
- P2-4 reopened and P2-12 (closure pass, applied by the coordinator): the bold legend now covers only the primary "Strongest" implementation(s), not secondary or branch-only mentions; the §1 note says both documents use n/a.
- P2-4 (second reopening, applied by the coordinator): legend changed to bold every parallel "Strongest" implementation, branch-only ones inside the `b:` marker; bold added to C1 R02, C1 R10, C1 R05 `b:S`, D5 R08, D5 R10 and D6 R01 `b:A`.
