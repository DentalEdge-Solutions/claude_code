# Architecture Intelligence Report — consolidated findings, synergies, architectural principles and optimization opportunities
> Phase 2 of the Software Factory evaluation campaign · Date: 2026-10-22
> Inputs: phase 1 reports 01-11 (docs/evaluations/2026-10-22-factory-research/) · Framework: value definition (active decision 2026-10-22)
> Legend: [Obs] observed · [Docs] official docs · [Claim] unverified claim · [Inf] inference · [Unk] unknown

## 0. How to read this report

**Scope.** This report brings together the four phase 2 deliverables: D1 Comparative Architecture Matrix, D2
Capability & Engineering Matrix, D3 Best-Practice Assessment and D4 Reuse & Compatibility Matrix. It uses the 11
phase 1 reports to confirm load-bearing facts. It states findings, synergies, principles, generic opportunities and
open questions. It makes **no adoption decision and no recommendation for `claude_code`**. Candidate verdicts are
generic and provisional. Section 6 reports facts on the owner's open question and does not answer it.

**Citations.** `[D1 §5.7]` means deliverable 01, section 5.7. `[R05 §9]` means phase 1 report 05, section 9. A
`path:line` reference follows where it is decisive. "Clone" means I re-read the file in the read-only clone on
2026-10-22. Nothing was executed by anyone in the campaign.

**Evidence-strength scale for principles and opportunities.** This is the D3 scale [D3 §0], collapsed to the four levels the
brief asks for:

| Level | Meaning |
|---|---|
| **Validated** | Implemented, and backed by committed tests (T) or by published measurements (M). The tests were not run here and the measurements were not re-run. |
| **Implemented** | In code, but no covering test or measurement was found. |
| **Prompt-only** | Exists only as instructions an LLM is asked to follow. |
| **Claimed** | Asserted in docs or marketing. No implementing code or evidence was found. |

**Short names.** R01 Galea · R02 Ras Mic · R03 Super-Board · R04 Rezvani · R05 Lewis Factory · R06 Blueprint ·
R07 REA · R08 Sandcastle · R09 SSSF (IndyDevDan) · R10 Medin (over Archon) · R11 Replica.

**Comparable groups** (no ranking across groups) [D2 §0]. G-ORCH, orchestrating factories and runtimes: R03, R05,
R08, R09, R10. G-PACK, prose skill and agent packs and generators: R01, R02, R04, R06. G-RE, reverse engineering and
replication: R07, R11. D1 also groups by purpose, with seven overlapping groups. These two groupings are compatible,
not contradictory: R01 is a delivery factory by purpose [D1 §1] and a prose pack by execution model [D2 §0].

**Value dimensions** (owner weights, used as guidance only): EQ engineering quality 30 · AO autonomy and
orchestration 20 · DP development productivity 15 · SR security and reliability 15 · MA maintainability and
adaptability 10 · RE resource efficiency 10. Security (**S**) and correctness (**C**) are mandatory acceptance
criteria.

---

## 1. Executive summary

**Most consequential findings for the value definition**

1. **No repository meets the mandatory security criterion as shipped. Several components meet a security or
   correctness bar on their own.** Every repository has at least one evidenced default-path violation of the
   security criterion. The forms are: permission bypass, unrestricted pre-approved shell without isolation,
   untrusted text reaching write-capable agents, prose-only gates on consequential actions, or unpinned setup code
   [Obs] [D1 §5.7]. Components that meet a bar on their own [D1 §5.8]:
   - **Security bars:**
     - R03 merge gate, policy classifier and pinned approval
     - R07 effects table and untrusted-content marker
     - R08 environment allow-list, isolated-VM sync and privilege-split explore job
     - R05 hardened SDK options (no licence, idea only)
   - **Correctness bars:**
     - R02 review freshness helper
     - R05 three-valued check contract (idea only)
     - R07 obligation ledger
     - R09 write boundary and `finish(accepted)`
     - R10 candidate-identity binding and guard self-mutation check (idea only)
     - R11 provenance and scoring tools
   - **Rendering-only bar:** R06 `html_doc.py`
2. **The only controlled outcome evidence does not favour orchestration complexity.**
   - Source: one author's benchmark (R05). The tasks are synthetic, the work is on an unmerged branch, and the data
     was recomputed but not re-run.
   - Against Claude Code coordinating the same reviewer as a subagent, scripted orchestration accepted 30/36 against
     29/36. Code passed the independent tests 30/36 against **31/36** for the direct arm. False completions were 6/36
     against 5/36 [Obs, author data; clone `codex__eval-suite/evals/reports/2026-09-25-v3/README.md`] [D3 §4.1].
   - The measured benefit belongs to **independent acceptance checks plus review and repair**: 6/9 against 1-3/9, on
     hand-picked hard cases against no-review baselines.
   - It does not belong to the control loop. False completions persisted in every arm of v2-v4 (v3: 5/36 direct,
     6/36 Factory). v1 had none under its original tests, which were later found flawed [D3 §4.1].
   - Orchestration with review has a measured cost. In v1 every mode passed 36/36, and Factory ran at a median of
     61.8 s against 29.3 s for the task-only SDK prompt (about 2.1×), at $6.16 against $2.47 (about 2.5×). Its p90
     was 148.9 s against 43.9 s (clone v1 `README.md:17-34`). In v2 it ran at 118.5 s against 28-36 s. This is the
     only measured cost and latency overhead in the set.
3. **Where the acceptance decision sits matters more than the orchestration label.**
   - Where code owns acceptance and the checks can fail, failures route deterministically: the R03 merge gate, R05
     `pass|retry|stop`, R10 "zero tests is not a pass" [Obs] [D3 §5].
   - Where an LLM owns acceptance, instructions were observed being skipped. R01's UX/UI reviewers skipped the
     required browser check in 3 of 4 reviews, and nothing detected it [Obs] [R01 §7].
   - Code ownership is necessary but not sufficient. R09 owns acceptance in code, yet its shipped quality checks are
     `echo` placeholders that exit 0. R11's parity step is code that cannot fail the deploy [Obs] [D3 AP-14].
4. **Independent verification is mostly context separation.**
   - LLM reviewers are the same model family as the builder, with two exceptions. R09's starter roster pairs a
     gpt-5.6-terra reviewer with a Gemini-default builder [R09 §3]. R02's reviewer is an external bot, Greptile
     [R02 §5]. No default branch enforces a read-only reviewer by tool restriction [Obs] [D2 B2] [D4 §2.3].
   - Only R03 enforces a merge gate in code on its default branch [Obs] [D1 §1 item 4].
   - The strongest ideas for *proving* correctness carry **no licence**: R05's held-out grader and false-completion
     metric, and R10's mutation calibration and candidate-identity binding. They are idea-only [Obs] [D4 §5.2].
5. **Untrusted input is the weakest cross-cutting capability.**
   - The only structural control is R08's privilege-split explore job, and it covers one workflow.
   - R07 labels target content, but labelling is not enforcement.
   - R04 passes any outsider's issue text to an agent holding a write token [Obs] [D4 §2.11] [D1 §1 item 7].
6. **The owner's measures are almost entirely unmeasured across the set.**
   - Not measured on real work by any repository: first-pass acceptance, human interventions per task, time from
     specification to verified delivery, cost per accepted deliverable, recovery success, and reuse effectiveness
     [Obs] [D3 §4.4].
   - R05 covers part of this list, on synthetic tasks only: accepted rate, false completions, per-trial wall time and
     cost per accepted result. Recovery appears only as timeouts per arm. Human interventions were "not measured"
     (clone v2 `README.md:42`). Reuse effectiveness is not measured at all.
   - No repository implements a REUSE / ADAPT / COMPOSE / REIMPLEMENT / BUILD NEW decision for supplied references
     [Obs] [D2 G1].
7. **Reference-driven development exists at two levels that do not overlap.**
   - R07 works at artifact level with a fail-closed obligation ledger and a proof-authority lattice. The ledger trusts
     caller-supplied, integrity-only proofs, and no non-test code produces proof records.
   - R11 works at product level with an ID-keyed specification and a scored feature ledger. The score rests on the
     builder's self-marked rows, and the deploy parity step always exits 0 [Obs] [D4 §2.5].
   - Neither verifies parity independently of the party that claims it. Neither separates the session that studies
     the original from the session that builds [Obs] [D2 §5.12].
8. **No repository demonstrates building arbitrary applications end to end.** The largest evidenced outputs are:
   - two small features on an existing blog site (R01)
   - a ~330-line demo app whose traces are not in git (R09)
   - 16 synthetic single-file Python tasks (R05)
   - agent-authored commits merged by maintainers on the library's own repository (R08)

   Production readiness of factory-built software is not evidenced anywhere (§6).
9. **Maturity cuts both ways.** The most tested projects churn the most:
   - R03 has 62 suites and CI.
   - R07 has 2,081 test files, six major versions in three months, and an unstable main.
   - R08 has ~1,416 cases and is pre-1.0 with a breaking `v1` pending.

   Several of the most valuable mechanisms exist only on unmerged branches (R05 eval harness, R01 v2). Properties
   documented in ADRs or docs are contradicted or unimplemented in code in seven repositories [Obs] [D3 AP-07]
   [D2 §4]. Several are safety-related: R08 ADR 0015 (no bypass under `noSandbox()`), R04 "blocking" hooks, and R07
   evidence that "must authenticate".

**Observed against claimed, for the claims that matter most to the value definition**

| Claim type | Examples | Status |
|---|---|---|
| Unattended delivery | "Add tasks, walk away, get merged PRs with proof" (R03); "Filing an issue is the only input" (R10); "no human in the loop" (R05 example skill) | [Claim]. The loop and gate exist in R03 [Obs]; unattended outcomes were not demonstrated [D3 §4.3] |
| Productivity | "A booking tool is weeks" (R11); "Build a Skill in 2 Minutes" (R04) | [Claim]; no run artifacts [D3 §4.3] |
| Independent review | "Two reviewers that did not write it decide whether it merges" (R10); UX/UI reviewers "check the running app" (R01) | R10: Archon-side, not inspected [Unk]. R01: contradicted in 3 of 4 reviews [Obs] [D2 §4] |
| Security properties | ADR 0015, no bypass under `noSandbox()` (R08); "Four-Layer Security Model" (R04); evidence "must authenticate" (R07) | Contradicted by code / no code / integrity only [Obs] [D2 §4] |
| Quality from orchestration | "orchestration … 10x quality" (R06 roadmap: "an ambition, not a measured result") | The only measurement found no quality gain over a strong prompted baseline [Obs, author data] [D3 §4.1] |

---

## 2. Consolidated findings by theme

### 2.1 Control plane and execution models

**Who decides the next step** [Obs] [D1 §3.1, §3.4]:
- **Code:** R05 (one loop), R09 (straight-line phases), R08 (the iteration loop; multi-step flows are caller code),
  R03 (per card, through deterministic JS lanes with schema exits).
- **An LLM following prose:** R01 v1, R02, R04, R06, R11. R11 and R02 are largely human-sequenced.
- **None, by design:** R07, whose roadmap says "custom orchestration needs a demonstrated requirement"
  (`docs/roadmap.md:24-25`) [R07 §5].
- **Delegated:** R10, to the Archon engine, which was not inspected [Unk] [R10 §17].
- **Unmerged:** the GPL-3.0 R01 v2 branch adds a scripted transition table [R01 §2.4]. Its `gate` script also has a
  `--hook` mode that runs the checks and exits 2 on failure (`gate:7,85-105`). Its wiring as the builder's
  SubagentStop hook is described only in the v2 docs (`SF2/DESIGN.md:87-88`), because the builder agent file is
  not committed. It is the only Claude Code-native stage-enforcement design in the set [Obs] [R01 §2.4] [D2 A1,
  §6 item 16].

**Observed strengths and failure modes by model** [D1 §3.3] [D3 §5]:

| Model | Works when (observed) | Fails how (observed) |
|---|---|---|
| Deterministic (R05, R09, R08 loop) | Bounds, retries and outcomes cannot be skipped by the model, and are unit-testable with fake agents (R05: 28 cases; CI with ruff) [R05 §7] | The gate is only as good as its checks: R09 placeholders exit 0 and its claims gate checks only that files exist (`gates.py:61-68`) [R09 §7]. R05 removed its reviewer tamper check [R05 §8]. No quality gain over a strong prompted baseline [D3 §4.1] |
| Autonomous coordination (R01 v1, R06 coordinator, R10 via Archon) | Low code; rich, inspectable artifacts. R01 job 001 produced a precise policy escalation [R01 §5] | Required steps skipped undetected (R01 3/4). The orchestrator breaks its own rule: it writes `decision.md` despite "never write decisions" [R01 §5]. No crash resume [R01 §6]. Unbounded repair loop (R06 `/task-to-pr`) [R06 §5] |
| Hybrid (R03; R08 templates; R07 tools under an LLM host) | Safety decisions are scripts whose exit codes route to deterministic board moves. Board state makes "run" equal "resume". The wave script itself is unit-tested [R03 §5-7] | The outer planner still follows 816 + 420 lines of prose [R03 §14]. The rebuild-cap hash is prose-only [R03 §5]. Alternative backends weaken permissions [R03 §8] |
| Skill-driven (R02, R06, R11, R04) | Minimal context cost (R06: zero idle cost in Claude Code [Docs] [R06 §9]); portable across clients | Honour-system gates (R11 parity step exits 0; R02 iteration cap) [D1 §3.3]. No behavioural evals anywhere in this group [Obs] |

**Cross-model findings**
- **Control and quality are separate properties.** In R05 v3, scripted orchestration bought execution control: 0/36
  timeouts against 2/36, a median of 48.6 s against 75.5 s, and complete usage records. It did not buy code quality
  [Obs, author data] [D3 BP-01].
- **Every model leaks at the same three seams:** untrusted input, permissions, and self-reported proof [D3 §5 obs 3].
- **Spines conflict.** R03, R05, R08, R09 and R10 each assume they own sequencing, retries and "done". Nesting two
  spines produces two retry budgets and two sources of truth [Inf] [D4 §3.2 C1].
- **Platform coupling differs by model.** Deterministic runners couple to an SDK or CLI (R05 to the Agent SDK 0.1.x;
  R09 to Pi only, with a stub Claude Code adapter, `agent_cc.py:11-15`). The hybrid couples to the Claude Code
  Workflow tool and GitHub Projects v2. Packs couple only to frontmatter semantics [Obs] [D3 §5 obs 4] [D4 §3.1].

### 2.2 Verification and acceptance: where the acceptance decision sits

| Repo | Who decides "accepted" | What is checked mechanically | Evidence that acceptance can be wrong |
|---|---|---|---|
| R03 | Code gate for merge; LLM reviewer above that floor | `verify_commands` on the base-merged reviewed head, inside a `mkdir` lock; `--match-head-commit` (`merge-gate.sh:349-351`) [Obs] [R03 §12] | Config default `merge_policy: "auto"`: a model-run lane merges on its own review when no category or size cap trips (clone `config-schema.json:135`, `merge-policy.py:133`) [Obs] (§8 X1) |
| R05 | Code routes `pass\|retry\|stop`; the human accepts afterwards (the runner never commits or merges) | Configured shell checks; schema-valid LLM check results [Obs] [R05 §5] | Author data: false completions passed tests **and** structured review (v2 3/9; v3 6/36) [Obs, author data] [R05 §14] |
| R09 | Code: `run.finish(accepted=verified)` | Whatever the quality blocks run; shipped as `echo` placeholders that exit 0 (`quality.py:49-52`) [Obs] [R09 §7] | A fresh install's test phase is always green [Obs] |
| R10 | In repo: `ci.py` (zero tests fails; timeout = failure). Merge: Archon [Unk] | Candidate identity `sha256(source digest, argv, env)` re-probed (`runtime_host.py:236-307`) [Obs] [R10 §7] | Holdout not hidden from the builder by code (`HOLDOUT.md:5`) [Obs] [R10 §8] |
| R08 | Caller code | `sandbox.exec` gates as written by the caller [Obs] [R08 §7] | Template review is a second agent in the same sandbox [Obs] |
| R01 | LLM approver; `APPROVE` merges to local `main` | `merge-tree` conflict check only [Obs] [R01 §12.4] | UX/UI browser checks skipped 3 of 4 times, and the approver cited them [Obs] [R01 §7] |
| R06 | LLM, by prose; PRs stay open unless `/factory` is named | None for produced work (the renderer is document verification) [Obs] [R06 §7] | No behavioural evals; reviewer read-only is prose [Obs] |
| R02 | External bot score plus a human merge | Score counts only for the current head, from a trusted bot login (`github_review.py:45-63`) [Obs] [R02 §7] | Functional evidence is self-reported; `"verified": true` means "the video plays" [Obs] [R02 §7] |
| R11 | Builder self-marks `features.csv`; human gives the deploy "go" | `sweep.py` and `listing.py` exit 1; `parity.py` exits 1 only with `--fail-under` (`parity.py:218-224`) [Obs] [R11 §5] | Deploy preflight parity always exits 0 [Obs] |
| R07 | Code ledger, for reconstruction claims | Unique owner, every required case kind, verifier at comparable authority [Obs] [R07 §5] | Proofs are caller-supplied and integrity-only; only a fixture produces `rea.reconstruction-proof` [Obs] [R07 §5-6] |
| R04 | Same LLM run | None; `expected_output.json` is never executed [Obs] [R04 §7] | — |

**Findings**
- **Binding verification to the exact artifact works where it exists**, with validated tests in three forms [Obs]
  [D2 C1] [D3 BP-11-13, BP-17]:
  - the reviewed head (R03)
  - the current head for third-party review (R02)
  - the running candidate's bytes (R10)
- **Human approval is only as strong as identity separation.** R03's approval binds repo, PR, head and a sha256 of
  the policy plan. But a `done` from an agent sharing the human's token cannot be told apart from a human one [Inf]
  [D3 AP-02].
- **Checks that cannot fail are the commonest silent failure** [Obs] [D3 AP-14]:
  - R09 placeholders
  - R11 parity preflight
  - R04 kill switch read before checkout
  - R05 accepting a blank command on main [Inf]
  - R07 nightly mutation testing with `break: null`

  Only R10 tests its own guards by injecting defects (five anchored sabotage edits; `NOT_INJECTED` on ambiguity)
  [Obs] [R10 §7]. The self-check driver itself has no CI.
- **Self-reported verification is pervasive:** R11 parity rows, R02 evidence results, R01 approver reliance on
  `build.md`, R04 checklists, and R09 `diff_matches_claims` [Obs] [D3 AP-03].
- **Measuring "done is true" exists once:** R05's grader copies only the implementation, runs held-out tests under
  `python -I`, fails closed, and records `false_completion`. It is unmerged, has no licence, and imports agent code
  on the host [Obs] [D2 C1] [D4 §1.5].

### 2.3 Security, isolation and untrusted input

- **Permission bypass by default** [Obs] [D3 AP-01]:
  - R08 `run()` and `createSandbox().interactive()` hard-code `dangerouslySkipPermissions: true`, including with
    `noSandbox()` (`Orchestrator.ts:143`, `createSandbox.ts:631`). This contradicts ADR 0015.
  - R03's legacy builder runs `--dangerously-skip-permissions` on raw issue text. Its Codex lanes use
    `approval_policy="never"` with network on.
  - R09's example `just cc` bypasses permissions.
  - R10's runbook runs as root with `IS_SANDBOX=1`.
  - R05 pre-approves unrestricted Bash.
- **Isolation.** R08 is the only container or VM runtime, and its gaps are material [Obs] [D4 §2.7]:
  - the host `.git` is mounted read-write
  - the network is open by default with `GH_TOKEN` present
  - secrets travel in `docker run -e` arguments
  - model-chosen branch names reach host `exec`

  [Docs] `bypassPermissions` skips prompts even for writes to protected paths such as `.git`, so the bind-mount path
  is weaker than it looks [Inf] [D4 §2.7]. R10's runtime host and R07's process ownership own and identify
  processes. Both say they are "not a sandbox" [Obs].
- **Untrusted input.** There is one structural control: R08's explore job runs read-only, and a separate job
  validates the plan against a pre-agent snapshot and applies whitelisted effects only. It has one 33-line test, on
  verdict labels [Obs] [D3 BP-24, §8 X15]. Other measures are labelling (R07 `_meta.provenance.untrusted_content`),
  prompt lines (R05), or identity filtering (R02 trusted logins). Absent [Obs] [D4 §2.11]:
  - R03: issue, PR, comment and Sentry text reaches lanes that hold push and merge capability.
  - R11: fetched pages and review text.
  - R04: issue triage with a write token.
  - R08 plan prompts: text passed to permission-bypassed agents.
- **Supply chain** [Obs] [D2 D5] [D4 §2.8]:
  - R06 and R07 pin dependencies exactly and pin CI actions by SHA. D1 and D2 now agree: R06 Strong and R07
    Adequate. R07's skill tells the agent to run `@latest` code in its approved setup-apply step. R06's unpinned path
    is the third-party `npx skills add` command that installs its Markdown skills, recorded as a caveat
    [D2 D5] [D1 §4b] (§8 X3).
  - R10 is the only installer that pins and verifies its engine.
  - Every skill-pack installer in the set pulls an unpinned `main`.
  - R03, R08 and R10 contain `curl | bash` paths.
- **Guards that fail open or do not block** [Obs] [D3 AP-09]:
  - R03 guard hooks: `except Exception: pass`.
  - R04 templates use `exit 1`, which does not block.

  [Docs] A hook failure is non-blocking unless `onFailure: "block"` is set (v2.1.295+), and exit code 2 blocks
  [D4 §1.3, §2.9]. **`onFailure: "block"` does not close R03's fail-open path.** All five R03 guard hooks catch
  `except Exception: pass` in `main()` and exit 0. A swallowed exception that exits 0 is not a hook failure, so
  `onFailure` only covers crashes and timeouts (clone `guard-secrets.py:62-63`, `guard-delete-outside.py:199`,
  `guard-key-literals.py:100`, `guard-worktree-path.py:195`, `guard-protected-push.py:198`) [Obs]. Closing the
  path needs a change to the hook code, so that an internal error exits 2.
- **Host-side shell interpolation** crosses isolation from inside out [Inf, not executed] [D3 AP-10]:
  - R08 interpolates branch names into host `git merge`.
  - R03 `eval`s config commands that run PR code on the host.
  - R04 places `${{ github.event.pull_request.title }}` inside `run:`.

### 2.4 State, context and resumability

- **Durable external state lets "run" mean "resume".** R03 keeps no loop state outside the GitHub board, sweeps
  stranded cards back to Ready, and shares a halt file across worktrees [Obs] [R03 §6]. R08 resumes at agent-session
  level (capture, `cwd` rewrite, `resume()`/`fork()`), which relies on undocumented CLI session layouts [Obs]
  [D2 A3] [D3 AP-16]. R01 and R05 keep state on disk but cannot re-enter a job [Obs] [D4 §2.2].
- **Locks converge on filesystem primitives:** `mkdir`, `O_EXCL`, `fcntl` and OS single-flight locks. Only R03
  handles stale locks explicitly. All of them are single-host [Obs] [D4 §2.2] [D3 BP-18].
- **Handoff integrity.** R03 refuses to rewrite a PR-body block when the head has moved (exit 6). R09 adapts code and
  agent outputs into one typed envelope. R07 returns summary-first results with retained references and byte caps
  [Obs] [D2 B1].
- **Trade-offs.** A SaaS store adds rate limits: a 3-card wave used about 2,850 of 5,000 GraphQL points per hour
  [Claim] [R03 §9]. It also turns issue text into control input [D3 BP-19]. SQLite (R09) is the richest record, but
  it is an audit trail, not a resumable plan [D4 §2.2].

### 2.5 Observability and cost

- **Tracing.** R09 is the only complete trace on a default branch: phase, event and tool-call spans; gate evidence;
  per-phase cost including cache and reasoning; context occupancy kept separate from spend; and a process registry.
  It is Pi-shaped, stores raw prompts, and does not trace subagents [Obs] [D2 E1]. R08 reports per-iteration token
  usage across six CLIs, without dollar figures [Obs].
- **Budgets.** No repository enforces a per-task token or dollar budget on its default path [Obs] [D2 E2] [D3 AP-13].
  R03's plan-usage guard is the only enforced pause tied to spend: it pauses new waves at 95% [Obs]. R08 templates
  allow 100 iterations × 10 cycles [Obs]. A community report says one R09 run used 30 M tokens and cost $182.83
  [Claim] [R09 §5].
- **Cost per accepted deliverable** is computed only by R05's unmerged harness. v3: Factory $0.240; direct ≥ $0.240
  (a lower bound, because two timed-out runs lack usage records). v4: $0.364, $0.378 and ≥ $0.384 across its three
  arms. All figures are list-price estimates (clone v4 `README.md:58`). In v2 the cost per passing result was
  Factory $0.41 and direct CLI $0.30 [Obs, author data] [D3 §4.1].
- **Measured overhead of orchestration with review** (R05, author data, unmerged).
  - v1, easy tasks, all modes 36/36: Factory had a median of 61.8 s against 29.3 s for the task-only SDK prompt, and
    a p90 of 148.9 s against 43.9 s. It cost $6.16 against $2.47 for the 36 trials; direct CLI cost $3.52 (clone v1
    `README.md:17-34`).
  - v2: Factory had a median of 118.5 s against 28-36 s for the other arms.

  This is the only measured cost and latency overhead in the set (RE).
- **Model routing.** R03 is the only repository that routes models dynamically: a cheap classifier picks a tier
  ladder. No repository measured whether routing helps quality or cost [Obs] [D2 E3] [D3 BP-30].

### 2.6 Continuous improvement

- **No repository shows an automated closed loop with measured improvement** [Obs] [D2 F1].
- **Controlled-change methodology** exists once, on an unmerged branch. R05 freezes the suite and baseline, changes
  one element, keeps failures as regressions, and never lets the optimizer edit the evaluator. Its v4 cohort rejected
  a candidate reviewer prompt (12/16 in every arm) and published that negative result [Obs] [D3 BP-08].
- **Bounded self-modification** exists once. R03's calibration is external and off by default. It validates a
  receipt of 64 KiB or less and limits edits to an allowlist of at most 20 existing `SKILL.md` files, but the limit
  is not OS-enforced [Obs] [R03 §10].
- **Authoring-time gating.** R03's Stop hook blocks ending a turn while an edited skill's eval is stale. It fails
  open [Obs] [D4 §1.3].
- **Incident-to-rule logs.** R10 keeps 65 entries and R03 keeps dated notes beside mechanisms. The incidents
  themselves are [Claim]; the resulting code is [Obs]. Most R10 incidents describe code that has since moved into
  Archon [D3 BP-35].
- **Simplification regressions.** Three repositories removed a mechanical guard while the prose kept implying the
  property [Obs] [D3 AP-17]:
  - R05 removed its `unchanged()` tamper check.
  - R06 dropped its 3-round cap and its untrusted-browser rule.
  - R10 removed `holdoutwall.py`.

### 2.7 Reference-driven development and parity: REA versus Replica levels

| Aspect | R07 REA (artifact level) | R11 Replica (product level) |
|---|---|---|
| Input | Shipped binaries, bundles, APKs, firmware, captures; 220 deterministic MCP tools [Obs] [R07 §4] | Public sources only. JS bundle analysis and decompiling are explicitly forbidden (`replica-recon/SKILL.md:38-40`) [Obs] [R11 §8] |
| Specification output | Application graphs; version and source-to-bundle comparison with no fuzzy pairing. **No specification document** [Obs] [D2 G3] | ID-keyed recon map (S01…, F01…); inferred data model with evidence and confidence; explicit non-goals. **No automated capture** [Obs] [D2 G3] |
| Parity unit and rule | Obligation with an owner (module, symbol, implementation SHA-256) and every required case kind. Fail-closed authority lattice: a green unit test cannot close a `packaged-process` obligation (`ReconstructionObligationAuthority.ts:15-61`). Observed: a required `unit` proof accepts any authority [Obs] [D2 §6 item 12] | `parity.py` weights must 3 / should 2 / could 1, plus 20% layout from `imgdiff.py` (colour-invariant edge density) [Obs] [R11 §11.4-11.5] |
| Independence | Closure trusts caller-supplied proofs. Evidence "authentication" is a digest, not a signature. No non-test proof producer [Obs] [D3 AP-08] | The builder marks its own `clone` column. Preflight exits 0 [Obs] [D3 AP-03] |
| Visual / UI | Capture tools only, not executed [Unk] | Design-token roles; per-state component specs; `contrast.py` WCAG gate (tested) [Obs] [D2 G4] |
| Provenance | Separate `confidence` and `authority` axes; "unknown is not absence" [Obs] | `reviews.py` drops rows without a URL and quotes only verbatim substrings (tested) [Obs] |
| Legal and safety | 15 tools execute foreign code; HTTP mode has no authentication (documented); JEB EULA restricts disclosure; GPL engines [Obs] [D4 §5.3] | Clean-room rules are prose. The same session studies the original and builds. Patents and public-site terms of service are not covered [Obs] [R11 §3, §8] |
| Maturity | 2,081 test files; 6 majors in 3 months; main CI 19 ok / 14 failed / 66 cancelled / 1 action_required of the last 100 runs [Obs] [R07 §1] | One commit; 57 tests; no CI; a crash fix is unmerged (issue #10) [Obs] [R11 §1] |

**Findings**
- The two levels complement each other and do not overlap. R07 has the right closure rule but no producer of proof
  records. R11 has a producer but no independent closure [Obs] [D4 §2.5].
- Specification extraction composes naturally: R07 extraction feeds an R11-style specification model [Inf]
  [D2 G3].
- No repository combines automated capture, comparison and a threshold into one visual-verification gate [Obs]
  [D2 G5].
- No reference-driven repository separates the session that studies the original and specifies from the session
  that implements. Clean-room claims and verification both need that separation [Obs] [D2 §5.12] [D3 AP-15]. Outside
  reference-driven work, R01 (spec-writer vs builder subagents) and R09 (planner vs builder agents) do separate the
  roles [R01 §3] [R09 §3].

### 2.8 Engineering maturity and maintenance risk

- **Within G-ORCH** [Obs] [D2 §3]:
  - R03 and R08 combine large suites with CI and disciplined releases. R03 ships only the tested SHA. R08 publishes
    OIDC-attested npm releases.
  - R05 is small but complete for its scope.
  - R09 and R10 contain serious mechanisms but no CI. R10 compensates with guard self-mutation; R09 has no tests at
    all and three paths that break as committed.
- **Within G-PACK:** R06 is the only pack with CI and tested code. R01 has no tests. R04 has none and has been
  dormant for 11 months, with 7 community PRs unreviewed [Obs].
- **Within G-RE:** R07 has the deeper engineering practice of the two, but it was unstable on the evaluation day. R11
  has a well-tested small tool set but no CI [Obs].
- **Maintenance risks by source** [Obs] [D1 §2d] [D4 §4]:
  - churn: R07 (six majors in three months); R08 (pre-1.0, breaking `v1` pending); R03 (changes weekly)
  - unmerged key work: R05 PRs #4, #5, #8; R01 v2; R10 PR #58
  - a daily-moving pin to an unmerged engine branch, 92 commits ahead of Archon `dev` and 575 behind: R10
  - a single maintainer and a single commit: R11
- **Docs and ADRs are not guarantees.** Documented properties are contradicted or unimplemented in R08 (ADR 0015,
  ADR 0007), R03 (`humanApprovesMerge`), R09 (`parent_id`, `queued`, a generator emitting a removed API), R04 (hook
  format, invented `PrePush`), R10 (overlap "skip" against "queue"), R01 (`decision.md`) and R07 ("authenticate")
  [Obs] [D3 AP-07] [D2 §4].

### 2.9 Licensing as a constraint on reuse

- **No licence:** R01 v1, R05 and R10, plus R02's unlicensed folders, including `tests/`. All rights are reserved,
  so ideas can be reimplemented, but code reuse needs the author's permission [Obs] [D4 §5.2].
- **Consequence:** the strongest correctness ideas in the set are **idea-only** [Obs] [D4 §5.2]:
  - R05 held-out grader, false-completion metric and fail-closed SDK options
  - R10 mutation scoring, guard self-mutation and candidate-identity binding
- **GPL-3.0:** R01 v2 is copyleft for any distributed derivative. It is also unmerged and incomplete [Obs].
- **Noncompete:** R02 `before-and-after` uses a non-canonical "PolyForm Shield"-titled text with a noncompete
  clause, licensor James Clements [Obs] [D4 §5.2, discrepancy 4].
- **R07 third-party terms** [Obs] [D4 §5.3]:
  - LGPL-2.0 optional `frida`
  - a GPLv3 GCC runtime, with exception, statically linked into the Windows addon
  - GPL engines (Unicorn, GDB)
  - commercial EULAs (IDA, Hopper, JEB)
  - four README-listed tools missing from its notices
- **MIT** covers R03, R04, R06, R07, R08, R09, R11 and three R02 folders. Copies must keep the copyright notice [Obs].
- **Phase 1 class conflicts.** Four R10 rows and the research index called no-licence code "needs adaptation", which
  the brief does not allow. D4 reclassified them as REIMPLEMENT [Obs] [D4 §1.12], and the phase 1 reports have since
  been corrected (Report discrepancies E1).

### 2.10 Innovations

These are the distinctive mechanisms each report lists in §12, kept to those with evidence in code or published data.
Strength uses the §0 scale. Licence limits from §2.9 apply.

| Repo | Most distinctive innovations | Strength | Licence and reuse mode [D4 §1] |
|---|---|---|---|
| R01 | First-line verdict protocol; WAIT-FOR-ALL barrier with a named resumable builder; spec "Assumptions" as an escalation hook [R01 §12] | Prompt-only (two example jobs) | None: REIMPLEMENT the idea |
| R02 | Review freshness bound to the head, trigger and trusted login; post-once trigger reservation; PID-reuse-safe recorder [R02 §12] | Validated (T), no CI | MIT for `greploop/`; recorder unlicensed |
| R03 | Merge gate with proof under the lock; head- and scope-pinned approval; fail-closed evidence reader; dependency-sized waves; review remembers; eval-staleness Stop hook [R03 §12] | Validated (T, CI); review protocols prompt-only | MIT: REUSE, ADAPT or REIMPLEMENT per component (wave workflow REIMPLEMENT) [D4 §1.3] |
| R04 | Safe settings mutation (backup, rotate, atomic, rollback); least-privilege `allowed-tools` synthesis [R04 §12] | Implemented | MIT: ADAPT |
| R05 | Three-valued schema-enforced check contract; fail-closed SDK handling; held-out grader with `false_completion`; matched-baseline method [R05 §12] | Validated (T); grader and method Validated (T+M), unmerged | None: REIMPLEMENT the idea |
| R06 | Dual-client opt-in with a guard test; merge authority scoped by explicit invocation; fresh review on every repair; content-parity HTML renderer [R06 §12] | Renderer and opt-in Validated (T); delivery rules prompt-only | MIT |
| R07 | Authority-typed, content-addressed Evidence; fail-closed obligation ledger with authority lattice; partial-order behaviour comparison; untrusted-content marker; effects table; measured efficiency checkpoints [R07 §12] | Validated (T) (ledger via fixtures; effects table via `toolEffects.test.ts`); checkpoints Validated (M) | MIT; third-party terms (§2.9) |
| R08 | Agent × sandbox provider contracts; bundle-in / patch-out sync with save-before-apply; completion timeout for hanging processes; structured output with session-resume retries; privilege-split CI job [R08 §12] | Validated (T, CI); privilege split Implemented, thin test | MIT: REUSE, ADAPT or REIMPLEMENT per component (completion timeout and snapshot plan validation REIMPLEMENT; label-driven workflows REFERENCE ONLY) [D4 §1.8] |
| R09 | "Success must be earned" phase primitive with separate acceptance; code results adapted into agent envelopes; post-hoc write boundary; occupancy-vs-spend trace [R09 §12] | Implemented (no tests) | MIT: ADAPT |
| R10 | Verified engine pin; candidate identity binding; three-valued mutation scoring; guard self-mutation; two-level STOP/PAUSE brake; honest-failure markers [R10 §12] | Mostly Validated (T), no CI; the guard self-mutation driver is Implemented (§4 P4) | None: REIMPLEMENT the idea |
| R11 | One feature ledger across stages; colour-invariant layout diff; provenance enforced in code for research; evidence and confidence on inferred models [R11 §12] | Tools Validated (T); ledger self-reported | MIT |

**Common thread** [Inf]: most validated innovations make one decision mechanical and fail-closed. A merge,
a review signal, a check outcome, an evidence record or a parity row is accepted only when it is bound to an artifact
and its evidence can fail. This is the same direction as P1, P3, P4 and P10 (§4).

---

## 3. Synergies: cross-repository compositions

None of these compositions exists in any repository; each is [Inf]. They come from D4 §4, with conflicts from D4 §3.2
(C1-C12) and the compatibility notes n1-n34 in D4 §3.3. They are generic and **not** specific to any project. They are
ordered by the value dimension they mainly serve, not by overall merit.

| # | Composition (components → source) | What it would provide | Preconditions | Conflicts and risks | Effort · maintenance [D4] |
|---|---|---|---|---|---|
| S1 | **Checks shown to fail before they are trusted.** R10 three-valued mutation scoring and guard self-mutation (reimplemented); R05 held-out grader and `false_completion` (reimplemented; unmerged branch); R03 eval-staleness Stop hook; R03 workflow stub-test harness [D4 §4.4] | Evidence that gates and tests can fail; agents cannot weaken their own acceptance tests; skills are not shipped with stale evals; orchestration code tested without model calls. Serves EQ and the **C** criterion | Disposable workspaces; per-project defect catalogues and held-out cases; held-out tests hidden by code, not by folder naming [R10 §8] | INCONCLUSIVE must never count as caught. The grader imports candidate code on the host, so it needs isolation (S2). The Stop hook fails open | Medium-High · Medium; R05 and R10 are idea-only |
| S2 | **Isolated worker with a code-enforced merge gate.** R08 isolated provider and `Output.object`; R03 merge gate, policy, head-pinned approval and read helper; R02 review freshness [D4 §4.1] | Work in a container or microVM; review signals bound to the head; merge decided by code under a lock; policy categories routed to a human. Serves SR, EQ, AO | R08 bypass default turned off or the isolated path used; branch names validated; the gate's host `eval` moved into isolation (C9); a separate human approval identity (AP-02) | C1 (two loop owners if R08 templates and R03 waves both run); secrets in argv; R03 auto-merge default (§8 X1) | High · High (pre-1.0 library; weekly changes; Greptile format) |
| S3 | **Typed check contract with evidence and per-phase cost.** R05 `pass\|retry\|stop` and fail-closed SDK handling (reimplemented); R09 `GateReport`, `finish(accepted)` and SQLite tracer; R08 structured output with resume retries [D4 §4.2] | One outcome vocabulary for shell and LLM checks; acceptance only by an explicit decision; cost and context per phase; schema repair without redoing work. Serves EQ, AO, RE | One host language for the contract (R08 TypeScript vs R09 Python); R09 types de-Pi-ed; trace redaction | Raw prompts in the trace; `shell=True` in R09 gates; unrestricted Bash in R05 defaults | Medium · Medium (R09 looks unmaintained, with known defects) |
| S4 | **Review that persists, calibrates and stays fresh.** R06 `/review` format; R03 review-remembers and min-of-two truth checks; R06 fresh review on every repair; R02 freshness rule [D4 §4.3] | Findings with stable IDs across rounds; calibrated reporting (Priority × Confidence, nothing at 2 or below); re-review on every change; reviews that count only for the current head. Serves EQ | Host with fresh subagents; tool restrictions added (read-only is prose in every source) | Same model family, except R09's mixed-provider roster and R02's external bot reviewer, so independence is context-only; confidence is self-reported; R06 `/task-to-pr` merge authority would be a second merge path (C7) | Low-Medium · Low |
| S5 | **Structural handling of untrusted input.** R08 privilege-split job and plan validation against a pre-agent snapshot; R07 untrusted marker and effects table; R05 JSON-encoded context (reimplemented; no licence); R02 trusted-login rule [D4 §4.6] | Agents that read issue, PR, review or target text hold no write credential; a deterministic step applies only whitelisted effects; target-derived output labelled end to end. Serves SR and the **S** criterion | Per-job permission model; an allowed-effects schema; every intake path covered | The weakest intake path decides; labelling alone is advisory; the whitelist grows with each automation | Medium · Medium |
| S6 | **Guarded in-session execution for Claude Code.** R03 guard hooks, changed to exit 2 on internal error, plus `onFailure: "block"`; R06 opt-in invocation and guard test; R04 least-privilege `allowed-tools` synthesis [D4 §4.9] | Skills that never self-trigger; narrow tool patterns; pre-call checks on secrets, deletes outside the tree and protected pushes. Serves SR, RE | Claude Code ≥ v2.1.295 for `onFailure` [Docs]; hook code changed, because the shipped hooks swallow exceptions and exit 0, which `onFailure` does not catch [Obs] | Regex guards are bypassable; [Docs] deny rules remain the hard control. [Docs] Filesystem hooks are **not loaded** in SDK sessions with `setting_sources=[]`; managed policy settings, and so managed hooks, still load [D4 §3.2 C3] (C3). Hooks do not apply to other CLIs (C2) | Low · Low |
| S7 | **Two-level reference parity.** R11 recon map, `features.csv`, `parity.py`, `imgdiff.py`, `reviews.py`; R07 MCP server (graphs, comparisons, ledger); R06 `REQ`/`AC` IDs and `/spec` table [D4 §4.5] | Product coverage plus behaviour claims closed under a fail-closed rule, joined by stable IDs. Serves EQ, DP | Pinned REA over stdio; foreign-code tools behind host approval; a proof producer; independent status in place of builder-marked rows | Legal (patents, site terms, JEB EULA); injection from target content (R07 labels it, R11 does not); two data models (n30) | High · High (REA churn) |
| S8 | **Visual and runtime evidence.** R11 `imgdiff.py`, Playwright skeleton (console, 5xx, axe) and `contrast.py`; R02 evidence protocol and isolated runner (reimplemented); R06 `/test` criterion→evidence and network-dead Chromium [D4 §4.8] | Screenshots and video tied to acceptance IDs; deterministic layout comparison; accessibility and error hooks. Serves EQ | An independent step runs the comparison; `imgdiff.py` input bounds | Every source treats evidence as builder-produced; uncalibrated thresholds | Low-Medium · Low |
| S9 | **Safe, pinned configuration installation.** R04 settings installer; R07 plan, approve and backup flow (reference); R10 pinned-source verifier (reimplemented); R09 idempotent stamp with drift report [D4 §4.7] | Installs pinned to a revision, verified clean, shown as a plan, applied atomically and reversible. Serves SR, MA | R04 event list and file-format assumptions corrected; `input()` removed | Hook formats evolve (`onFailure` arrived in v2.1.295 [Docs]), so hard-coded lists go stale | Low-Medium · Low-Medium |
| S10 | **Traceable acceptance chain** (derived from D4 notes n6, n28, n29, n32, n34). R06 `AC-n` IDs as keys; R11 `features.csv` rows keyed by them; R05-style held-out checks with `pass\|retry\|stop` outcomes; R10-style mutation proof that each check can fail | Requirement → acceptance ID → independently executed check → parity row, with every check proven able to fail. Closes the gap that no repository links requirement IDs to executed test results [D2 §5.6] | Same as S1 and S4; one ID scheme | R11 status column is self-reported, so it must be replaced by check results; no licence for the R05 and R10 parts | Medium · Medium [Inf] |

**Cross-cutting composition constraints** [D4 §3.2]:
- **One spine.** One component owns the loop; the others contribute leaf components (C1).
- **One merge path** (C7).
- **One state truth** (C8).
- **Hook-based guards do not travel.** They are lost across hosts and in settings-isolated SDK sessions (C2, C3).
- **Diff-based write boundaries conflict with agent commits** (C5).
- **Licences limit composition.** No-licence parts cannot be combined as code. GPL-3.0 binds distributed
  combinations (C10).

---

## 4. Architectural principles supported by the evidence

Each principle below comes with the evidence for it, the evidence against it, counter-examples, and a strength level
(§0). No principle is stated without evidence.

**P1. Put the acceptance decision in code, and make "no evidence" a failure.**
- *For:*
  - R03's gate refuses heads that fail `verify_commands` on the current base (Validated (T), CI) [D3 BP-12].
  - R10's `ci.py` treats zero tests and timeouts as failures (Validated (T)) [D3 BP-05].
  - R05 stops on invalid check output (Validated (T)) [D3 BP-03].
  - R09's `finish(accepted)` separates "ran" from "accepted" (Implemented).
- *Against and counter-examples:*
  - Code-owned acceptance with vacuous checks is still wrong: R09 placeholders exit 0, and R11's parity code cannot
    fail the deploy [Obs] [D3 AP-14].
  - R05's code-routed checks plus an LLM review accepted false completions (v3: 6/36) [Obs, author data].
- *Strength:* **Validated** for the mechanism. Its effect on outcomes is only indirectly measured (R05, synthetic).
  The principle is necessary, not sufficient.

**P2. Orchestration complexity is not itself a source of quality; independent acceptance checks are.**
- *For:* R05 v3 matched baseline: 30/36 against 29/36 accepted, and 30/36 against 31/36 on code passing the
  independent tests. The authors conclude "orchestration alone has not shown better code quality" (clone v3
  `README.md:127-131`). In v2, review plus repair beat no-review baselines, 6/9 against 1-3/9 [Obs, author data]
  [D3 §4.1].
- *Against:*
  - In v3, scripted control gave fewer timeouts (0 against 2) and lower latency (48.6 s against 75.5 s median)
    than the reviewer-equipped direct arm. It has value for **reliability and records**, not quality.
  - The latency gain holds only against that arm. Against no-review baselines, orchestration with review was 2-4×
    slower: v1 61.8 s against 29.3 s median, about 2.5× the cost, with no acceptance gain; v2 118.5 s against
    28-36 s (clone v1 `README.md:17-34`).
  - The sample is small: 12 distinct small tasks, with correlated repetitions.
- *Counter-examples:* none measured. No other repository measures anything comparable.
- *Strength:* **Validated (M)**, one author, synthetic, unmerged, not re-run.

**P3. Bind every verification and approval to the exact artifact and to an identity the agent does not control.**
- *For:*
  - R03 head pin plus scope-pinned approval (Validated (T)).
  - R02 freshness: a score counts only for the current head and a trusted login (Validated (T), 33 tests).
  - R10 candidate identity re-probed on every request (Validated (T)) [D3 BP-11, BP-13, BP-17].
- *Against:* R03 approval collapses when agent and human share a token [Inf] [D3 AP-02]. R07 binds evidence by
  digest only, so it has integrity without provenance [Obs] [D3 AP-08].
- *Strength:* **Validated** for artifact binding. Identity separation is **not demonstrated** anywhere (a BUILD NEW
  gap) [D4 §2.1].

**P4. A check that has never been shown to fail proves nothing.**
- *For:* R10 guard self-mutation and three-valued product mutation scoring (scorer Validated (T); self-check driver
  Implemented). R05 `validate_cases` proves each starting workspace fails and each reference passes (Validated (T),
  unmerged) [D3 BP-16].
- *Against:* The failure mode is observed wherever the principle is missing: R09, R11, R04, R07 `break: null`, and
  R05's blank-command hole [Obs] [D3 AP-14].
- *Strength:* **Validated** in one repository (no licence) and one unmerged branch. The harm of its absence is
  **observed** in five.

**P5. The agent being judged must not be able to change what judges it.**
- *For:*
  - R05's grader copies only `app.py`, and post-run hashes invalidate tampered suites (Validated (T), unmerged).
  - R09 protects its own machinery by post-hoc diff and rollback (Implemented). Its motivation was an observed
    builder running `git checkout adws/` [Claim in comments].
  - R01 v2 judges branches with the main checkout's checks (Implemented, unmerged, GPL) [D3 BP-15].
- *Against:*
  - R09 is blind to ignored and outside paths and to agent commits.
  - R05 main removed its `unchanged()` check.
  - R10's default protected list omits `engineering.md`, the file an agent once rewrote [Obs] [D3 BP-15].
- *Strength:* **Validated** only in unmerged, unlicensed code. **Implemented** elsewhere, with blind spots.

**P6. Safety boundaries on agents that hold write tools must be enforced by tools, not prompts.**
- *For (evidence against prompt-only):* R01 reviewers skipped required steps (3/4), undetected. R01 "read-only"
  reviewers hold Bash and Write. The R06 and R11 boundaries are prose [Obs] [D3 AP-04].
- *Against:* No default branch demonstrates a tool-enforced read-only reviewer, so the positive alternative is
  untested in this set [Obs] [D2 B2]. Partial mechanisms exist:
  - R05's fail-closed allowlist (Validated (T)), which still pre-approves Bash
  - R09's post-hoc boundary (Implemented)
  - [Docs] Claude Code deny rules and hooks that exit 2 [D4 §2.9]
- *Strength:* the failure of prompt-only control is **observed** (n = 4 reviews). The tool-enforced remedy is
  **Implemented, partial**.

**P7. Separate the agent that reads untrusted text from the credentials that can act on it.**
- *For:* R08's explore privilege split (Implemented; thin test). R07 labels every target-derived result (Validated
  (T) for marker presence) [D3 BP-24, BP-25].
- *Against:* R08 implement and review jobs hold write tokens; R04 triage; R03 lanes. Effectiveness against injection
  is measured nowhere [Inf] [D3 BP-25].
- *Strength:* **Implemented** (structural) and **Validated** (labelling presence). Effectiveness is **unmeasured**.

**P8. Defaults decide the security posture. A safe option that is off by default is not a control.**
- *For:* R08 has per-provider opt-outs but bypasses permissions by default. R03 has a human merge policy, but its
  config default is `auto`. R06 drops merge authority unless `/factory` is named, and deploy is never allowed. R06 is
  the positive counter-case: authority comes only from explicit invocation, enforced as opt-in [Obs] [D3 AP-01]
  [D4 §2.1] (§8 X1).
- *Strength:* **Observed** in code across five repositories. Impact is [Inf], since nothing was executed.

**P9. Bounds belong in the runtime, and attempt counts are not money bounds.**
- *For:* R05 `--attempts`, turn and timeout limits; R08 `maxIterations` and idle and completion timeouts; R09 loop
  caps (Validated (T) in R05 and R08) [D3 BP-06].
- *Against:* No default path enforces a token or dollar ceiling. R08 templates allow 100 × 10 iterations. There is a
  $182.83 single-run report for R09 [Claim] [D3 AP-13]. Prose caps are honour-system (R01, R02, R06).
- *Strength:* **Validated** for attempt bounds. **Absent** for spend bounds.

**P10. Route outcomes with three values: fixable, needs a human, inconclusive. Never collapse "could not decide" into
pass.**
- *For:* R05 `pass|retry|stop` and shell exit codes 0/1/other; R10 CAUGHT/ESCAPED/INCONCLUSIVE; R03 gate exit codes
  2/4/5/6/7/8/9; R11 exit codes 0/1/2; R07 "unknown is not absence" (Validated (T)) [D3 BP-04] [D4 §2.4].
- *Against:* An unused flag defeats it (R11 `--fail-under`).
- *Strength:* **Validated**.

**P11. Measure a change against a strong simple baseline, with frozen suites, and keep negative results.**
- *For:* R05 v3 (matched baseline) and v4 (one change, rejected) (Validated (M); unmerged `codex/eval-suite`
  branch). R07 dated efficiency checkpoints,
  including negative ones (Validated (M), tool level) [D3 BP-08, BP-31].
- *Against:* Small n; real cost per cohort. R07's tool-level savings are not task outcomes ("Fewer bytes alone do not
  establish fewer tokens") [R07 §9].
- *Counter-examples:* Unmeasured claims cluster around autonomy and productivity in at least six repositories
  [D3 §4.3].
- *Strength:* **Validated (M)** in two repositories.

**P12. Make durable state external and re-plan from it, so a crash needs no checkpoint.**
- *For:* R03 board-only state with a stranded sweep (Implemented; planner tested).
- *Against:* Rate limits; platform lock-in; state becomes untrusted control input [D3 BP-19]. R01 and R05 show the
  alternative failing: state survives but cannot be re-entered [Obs].
- *Strength:* **Implemented, partly tested**. Recovery effectiveness is **unmeasured** [D2 §5.9].

**P13. Keep consequential workflows explicit, and keep the context footprint small.**
- *For:* R06 opt-in for all 12 skills, guarded by a unit test. [Docs] The opt-in gives zero idle context in Claude
  Code. R03 `skills-ready.py` rejects interactive skills for unattended workers (Validated (T)) [D3 BP-28].
- *Against:* Auto-discovery is lost; other clients may not enforce the flag; the guard test hardcodes a count.
- *Counter-example:* R11 recon triggers on "how does X work" [R11 §4].
- *Strength:* **Validated (T) + [Docs]**.

**P14. Stated safety properties must be verified in code; guards need regression tests so simplification cannot
remove them silently.**
- *For:* Documented properties are contradicted or unimplemented in code in seven repositories [Obs] [D3 AP-07]
  [D2 §4]. Several are safety-related: R08 ADR 0015, R04 "blocking" hooks, R07 evidence that "must authenticate".
  Others are functional: R09 `parent_id` and `queued`, R10 overlap "skip" against "queue". Guards removed while the prose
  stayed in R05, R06 and R10 [Obs] [D3 AP-17]. R10's self-mutation is the one mechanism that would catch this
  (Implemented).
- *Strength:* the problem is **observed**. The remedy is **Implemented** in one repository.

**P15. Parity is proven only by evidence produced independently of the builder, at an authority comparable to the
original observation.**
- *For:* R07 authority lattice (Validated (T) through fixtures) [D3 BP-33].
- *Against:* R07 has no non-test proof producer and integrity-only evidence. R11's score uses builder-marked rows
  [Obs] [D4 §2.5].
- *Strength:* **Validated** as a closure rule. **Not demonstrated** end to end anywhere.

**Candidate principles not supported** (stated so they are not assumed):
- "More agents or more automation improve quality." The only measurement is a wash (P2).
- "A green structured LLM review means correct." False completions passed tests and review [Obs, author data].
- "Container isolation alone makes bypassed permissions safe." There are `.git`, network and secret escape hatches
  [Obs] [D3 AP-11].
- "Model routing saves cost without hurting quality." It is unmeasured everywhere [D3 BP-30].

---

## 5. Optimization opportunities for a software factory (generic)

Each row is an opportunity for **a software factory in general**, not an instruction for any project. "Gap" states
what the 11 repositories show; "Best partial evidence" says where a remedy is closest to proven. Dimensions use §0
codes. **S** and **C** mark the mandatory criterion the opportunity bears on.

| # | Opportunity | Gap (evidence) | Best partial evidence | Dims | Mandatory | Strength (gap · remedy) |
|---|---|---|---|---|---|---|
| O1 | Tool-enforced least privilege for reviewer and verifier roles, plus tamper detection | No default branch restricts reviewers by tool *and* detects tampering [D2 §5.1] | R05 allowlist (Validated (T), Bash open); R09 post-hoc boundary (Implemented); [Docs] deny rules and exit-2 hooks [D4 §2.9] | EQ, SR | S, C | Observed · Implemented, partial |
| O2 | Structural separation of untrusted-text readers from write credentials on **every** intake path | One structural instance, covering one workflow [D2 §5.2] [D4 §2.11] | R08 explore split (Implemented); R07 marker (Validated (T), presence only) | SR | S | Observed · Implemented |
| O3 | Default-deny permissions with isolation that covers git metadata, network and secrets together | R08 comes closest; `.git` RW, open network, secrets in argv [D2 §5.10] | R08 isolated-VM path; R08 env allow-list; R10 stripped env (Validated (T)) | SR | S | Observed · Implemented, partial |
| O4 | Guards that fail closed and are tested by injected defects | R03 hooks swallow exceptions and exit 0, which `onFailure` cannot catch; R04 `exit 1` does not block [D3 AP-09] | Hook code that exits 2 on internal error, plus [Docs] `onFailure: "block"` for crashes and timeouts; R10 guard self-mutation (Implemented); R03 `test-guard-hooks.sh` | SR, EQ | S, C | Observed · Implemented |
| O5 | Independent acceptance with held-out checks and a standing false-completion metric | Exists only on R05's unmerged branch; no licence [D2 C1] | R05 grader (Validated (T+M)) | EQ | C | Observed · Validated (unmerged, synthetic) |
| O6 | Mutation calibration of product checks and of the factory's own guards | Only R10; R07 non-blocking [D2 C5] | R10 scorer (Validated (T)) | EQ, MA | C | Observed · Validated (one repo) |
| O7 | An approval channel the agent cannot write to, verified in code | No component separates human and agent identities [D4 §2.1] | R03 head/scope-pinned approval (Validated (T)); robot account optional | SR, AO | S | Observed · Absent (BUILD NEW) |
| O8 | Verification evidence with provenance (signed or attested), not only integrity | R07 digest only; nothing signs verification results [D2 §5.5] [D4 §2.5] | R08 OIDC-attested *releases* (packaging, not verification) | EQ, SR | C | Observed · Absent (BUILD NEW) |
| O9 | Mechanical traceability: requirement → acceptance ID → executed check result → parity row | No repository links IDs to executed results, except R07 for reconstruction [D2 §5.6] | R06 IDs (Prompt-only); R11 IDs (template); R07 obligation owners (Validated (T)) | EQ, DP | C | Observed · Partial (composition S10) |
| O10 | Per-task spend ceilings, and cost per accepted deliverable as a standing metric | No default path enforces a budget; cost per accepted result only in R05's unmerged harness [D2 §5.3] [D4 §2.6] | R09 per-phase cost (Implemented); R05 cost per accepted (Validated (M), unmerged); R03 usage pause (Validated (T)) | RE, AO | — | Observed · Implemented (measure) / Absent (cap) |
| O11 | Measurement of autonomy: human interventions per task, recovery success, time from spec to verified delivery | Not measured anywhere [D3 §4.4] [D2 §5.9] | R05 timeouts per arm (the only data) | AO, DP | — | Observed · Absent |
| O12 | Matched-baseline evaluation of any workflow or orchestration change | Only R05 (unmerged) [D2 §5.4] | R05 v3/v4 (Validated (M)) | EQ, MA | C | Observed · Validated (one author) |
| O13 | Behavioural evals of prompts, skills and agents as a standing regression gate, with results kept | R03 results gitignored; R07 eval not in CI; R05 unmerged [D2 §5.11] | R03 eval-staleness Stop hook (Implemented; fails open); R07 known-answer scorer (Implemented) | EQ, MA | C | Observed · Implemented, partial |
| O14 | A reuse-decision step for supplied references (REUSE … REJECT), applying licence and mandatory-criteria filters | No repository implements it [D2 §5.7] | D4's decision rules (licence first; security and correctness filter) show one generic procedure [D4 §0] | MA, DP | — (a decision procedure that applies the S and C filters to candidates) | Observed · Absent (BUILD NEW) |
| O15 | Clean-room role separation in reference-driven builds | R11 uses one session to study and build [D2 §5.12] | None | SR, EQ | — (legal and verification independence, not the security criterion as defined in D1 §5.7) | Observed · Absent |
| O16 | Visual verification as an automated, threshold-gated step run by an independent party | Capture, comparison and screenshots exist only separately [D2 §5.8] | R11 `imgdiff.py` (Validated (T)); R02 capture (Validated (T)); R03 viewports | EQ | C | Observed · Partial (S8) |
| O17 | Independent parity at two levels (product and artifact) joined by IDs | R07 has no proof producer; R11 is self-reported [D4 §2.5] | R07 lattice (Validated (T)); R11 scorer (Validated (T)) | EQ, DP | C | Observed · Partial (S7) |
| O18 | Conformance checks between documented safety properties and code, plus guard regression tests | Documented properties contradicted or unimplemented in code in seven repositories, several of them safety-related (R08 ADR 0015, R04 "blocking" hooks, R07 "authenticate"); three simplification regressions [D3 AP-07, AP-17] [D2 §4] | R03 `test_run_allowlist.py` fails when a lane calls an unlisted script (Validated (T)); R10 AST ownership audit (Implemented, not in CI) | MA, SR | S | Observed · Implemented, partial |
| O19 | Pinned, verified supply chain end to end, including install and setup paths | Every skill-pack installer pulls unpinned `main`; `@latest` in R07 setup-apply [D4 §2.8] | R10 `verify_source` (Validated (T)); R06/R07 in-repo pins | SR | S | Observed · Validated (one installer) |
| O20 | Bounded, reviewable self-improvement with the evaluator out of the optimizer's reach | No closed loop with measured improvement [D2 F1] | R05 frozen-baseline discipline (Validated (M), unmerged); R03 bounded calibration (Implemented; limit not OS-enforced) | MA, EQ | C | Observed · Partial |

**Reading across the table** [Inf]:
- Sixteen of the twenty opportunities bear directly on the mandatory security or correctness criteria. O10
  (spend), O11 (autonomy measurement), O14 (reuse decision) and O15 (clean room) do not, although O14 applies those
  criteria as filters.
- No repository implements O8, O14 or O15 at all. For O7 and O11 only adjacent partial evidence exists: R03's
  pinned approval, without identity separation, and R05's timeouts per arm.
- The remedies closest to proven (O5, O6, O12) all come from unlicensed or unmerged code. So their realistic reuse
  mode is reimplementation of the idea (§2.9).

### 5a. Implementation leverage, best approaches and trade-offs

**Candidate verdicts across D4's component inventory** (D4 §1, after its §1.12 reconciliation). The count is 175
component rows over the 11 repositories. Each row is counted by its first candidate verdict; rows with a split
verdict, such as "REUSE (library) / REIMPLEMENT (pattern)", count under the first. These counts were made here from D4
§1, are generic, and are not adoption decisions.

| Candidate verdict | Rows | What dominates |
|---|---:|---|
| REIMPLEMENT | 68 | Patterns, and all no-licence code (R01 v1, R05, R10, unlicensed R02 folders) |
| ADAPT | 46 | MIT code with a security or correctness gap that a bounded fix closes (R03 gate and hooks, R08 package, R09 tracer, R11 `imgdiff.py`) |
| REFERENCE ONLY | 30 | Product-specific, platform-bound or unevaluated material (Pi adapter, R07 setup planner, R04 prompts) |
| REUSE | 21 (incl. REA as an external tool, with conditions) | See below |
| REJECT | 10 | Default behaviour fails the security criterion, or the artifact contradicts the documented contract (R03 legacy builder and installer, R04 hook templates and issue automation, R02 `before-and-after`, R10 bootstrap, R05 story workflows) |
| COMPOSE | 0 as a row verdict | Nine generic compositions are in D4 §4.1-§4.9 (S1-S9 in §3 above); §3 adds a tenth, S10 |
| BUILD NEW | 0 as a row verdict | Four gaps, named in D4 §2: an approval channel the agent cannot write to; signed evidence records; cost per accepted deliverable; structural untrusted-input separation on every intake path (O7, O8, O10, O2). D2 adds the reuse-decision step (O14), least-privilege verifier roles (O1) and budget enforcement (the O10 cap) [D2 §5] |

**Components that pass the mandatory filters as they ship.** Under D4 rule 2, these are the REUSE rows [D4 §1]:
- **R03:** merge-policy classifier (as a pre-filter only), GitHub read helper, PR-body block editor, usage guard,
  `runtime_compare.py`
- **R06:** `/plan` and `/spec` templates, `html_doc.py`, link checker, `check_diff`, PR template
- **R08:** sandbox provider contract, bundle-in / patch-out sync (through the library), structured output (library),
  public-types check
- **R11:** `parity.py` (a scorer, not a gate), `contrast.py`, test-plan and bug-report formats
- **R02:** `unslop`, `greploop-apps`
- **R07:** the REA MCP server as an external tool (stdio, pinned version, foreign-code tools behind host approval)

None of them is a factory spine or a full verification layer. They are leaf components [Inf].

**Best-evidenced approaches by problem, with trade-offs** (pointers to the detailed sections):

| Problem | Best-evidenced approach | Main trade-off | See |
|---|---|---|---|
| Who decides "accepted" | A code-owned, fail-closed acceptance decision whose checks are shown to fail and cannot be edited by the judged agent | The checks must exist and be good; vacuous checks pass silently | §2.2; P1, P4, P5; S1, S10 |
| Value of orchestration | Keep the control loop small; invest in independent acceptance checks; measure against a strong prompted baseline | Scripted control buys records and deadline safety, at 2-4× latency against no-review baselines | §2.1, §2.5; P2, P11 |
| Binding verification to the artifact | Head pin, review freshness, candidate-identity binding | Human approval stays only as strong as identity separation | §2.2; P3; O7 |
| State and recovery | External durable state, re-planned each run | Rate limits; state becomes untrusted control input | §2.4; P12 |
| Isolation and untrusted input | Privilege split between readers and writers; default-deny permissions; isolated providers | Only partial instances exist; effectiveness is unmeasured | §2.3; P6-P8; S2, S5; O1-O3 |
| Reference parity | Fail-closed closure at matching authority, plus product-level ledgers joined by IDs | No proof producer; builder-marked rows; legal constraints | §2.7; P15; S7; O15, O17 |
| Cost | Per-phase tracing plus runtime bounds | No budget enforcement exists; tracing only reports | §2.5; P9; O10 |

---

## 6. Evidence bearing on the owner's open question: a general app-building factory

The question is whether becoming a factory that can "build any kind of app" is worth it. Below are facts only. This
section does not answer the question; phase 3 does.

### 6.1 What the 11 repositories actually built (evidence in the repositories)

| Repo | Largest evidenced output of the factory | Scope and type | Production readiness evidence | Failure data | Cost data | Human involvement |
|---|---|---|---|---|---|---|
| R01 | Two features on an existing Vue/Firebase blog: `001-blog-reading-time`, `002-not-found-page` [Obs] [R01 §5] | Small, single-feature changes to an existing site; local merges | None. Merged to local `main`; no deploy or post-merge validation [R01 §14] | 3 of 4 UX/UI reviews skipped the required browser check [Obs] | None | Job 001 escalated and ended merged; that a human approved it is the README's account. Job 002 merged autonomously [Obs end states; Claim for the human action] [R01 §5] |
| R02 | Its own repository: 12 "greploop iteration" commits [Obs] [R02 §7] | Factory self-maintenance | None | 4 macOS test failures reported in a PR [Claim] | None | Human merges ("do not merge unless instructed") |
| R03 | Its own repository (PR #73 uses the pack's format); "a real board" with 32 Ready cards [Obs / Claim] [R03 §1, §9] | Factory self-maintenance; target-repo work narrated only | None for factory output. The pack's own releases ship the tested SHA [Obs] | Incidents narrated (#381 worker storm; zero commits in six hours) [Claim] [R03 §10]; 7 paid evals with gitignored results | Evals "≈$0.25-0.45/run" [Claim] | Policy categories and migrations go to a human (exit 7/8); default `auto` merges otherwise [Obs] |
| R04 | Claude Code artifacts (skills, agents, hooks), not software [Obs] [R04 §1] | n/a | n/a. Generated hooks do not match the documented format [Obs] | Generator defects found by reading | None | Q&A-driven |
| R05 | 16 synthetic single-file Python tasks (e.g. `csv-export`, `cursor-pagination`, `schema-migration`); 300 scored trials [Obs, clone `evals/cases/`] [R05 §7] | Small synthetic tasks with hidden acceptance tests | None. The authors: "did not measure human time saved, maintainability, large-repository scaling or application-building performance" (clone v3 `README.md:136-137`) [Obs] | v3 false completions 6/36 (Factory) and 5/36 (direct); tasks accepted on all three repetitions 8/12 and 9/12; v2 Factory false completions 3/9 [Obs, author data] | v1 (36 trials per arm, all 36/36): Factory $6.16 against $2.47 for the task-only SDK prompt and $3.52 for direct CLI, with a median of 61.8 s against 29.3 s and a p90 of 148.9 s against 43.9 s (clone v1 `README.md:17-34`); v2 per passing result Factory $0.41, direct CLI $0.30; v3 per accepted result Factory $0.240, direct ≥ $0.240; v4 $0.364 / $0.378 / ≥ $0.384 (list price) [Obs, author data] | Runner never commits or merges; a human reviews the workspace [Obs] |
| R06 | None evidenced [Obs] [R06 §14] | — | — | — | — | PRs left open unless `/factory` is named |
| R07 | Analysis evidence, not applications. The DX-Ball reconstruction lives in an external repository, not checked [Claim] [R07 §16] | Tool platform | n/a | The tool's own main CI: 14 failed, 66 cancelled, 1 action_required of the last 100 runs [Obs] | Tool-level efficiency checkpoints [Obs] | Host agent and human drive |
| R08 | Its own library: 65 `agent/issue-*` and 21 `sandcastle/issue-*` branches; 5 sampled `sandcastle-agent[bot]` commits merged via maintainer PRs [Obs] [R08 §10, §16] | Library maintenance tasks from issues | None for factory output. The library's releases are attested [Obs] | Stale dogfood script with a prompt-arg mismatch [Obs] | Per-iteration tokens reported; no dollar figures | Humans apply labels and merge PRs [Obs] |
| R09 | Demo app `apps/inkwell/` on the `example` branch: Bun + `bun:sqlite`, `server.ts` 330 lines, 30 tests, 10 specs, 9 app docs [Obs] [R09 §17] | One small demo app | None. Traces gitignored; history squashed, so factory authorship is only partly verifiable [Obs] [R09 §14] | Five example ADWs break as committed [Obs] | Community issue: 30 M tokens / $182.83 for one run [Claim] | Operator launches; no approval phase [Obs] |
| R10 | No built application in the repository. Docs say the integration "stays supervised" and "still needs live end-to-end validation" [Obs as quoted, Claim as status] [R10 §14] | Governance and runtime-host layer over Archon | None in the repository. The human "judges the result in staging" [Claim] | 65 incident entries [Claim] [R10 §10] | None ("Instrument your tokens on day one" ships no instrument) [Obs] | Human decides scope and judges in staging [Claim] |
| R11 | None. "No end-to-end run artifacts"; walkthrough figures illustrative [Obs] [R11 §14, §16] | Intended: rebuild an existing SaaS or mobile app through deploy | None | Two input-handling defects; preflight parity cannot fail [Obs] | None | User sequences all 11 skills and holds credentials and the deploy "go" [Obs] |

### 6.2 What is demonstrated, what is only claimed, what is unmeasured

**Demonstrated** [Obs]:
- Factories can take small, well-specified changes on existing repositories to a merged state: R01 (n = 2) and R08
  (its own library, with maintainer-merged PRs). R03 shows only indicative usage on its own repository: PR #73 uses
  the pack's PR-body format, and its target-repo work is narrated only [R03 §1, §14].
- Code-owned gates can refuse unverified merges (R03).
- On small synthetic tasks, a prompted Claude Code session with a reviewer subagent performs about as well as
  scripted orchestration (R05 v3).
- Independent acceptance checks catch false completions that tests and review accepted (R05).

**Only claimed** [Claim]:
- unattended delivery at scale (R03 "walk away"; R10 "filing an issue is the only input")
- building or cloning a product in "weeks" (R11)
- end-to-end issue → staging → deploy (R10, through Archon, not inspected)
- a full binary-level reconstruction (R07, external)
- the R09 demo app "planned, built, tested, reviewed and documented" by the factory (partly verifiable)

**Unmeasured anywhere** [D3 §4.4]:
- building applications of different types (web, mobile, backend, data, desktop) or of non-trivial size
- greenfield builds from a specification
- performance on large repositories
- production readiness of factory output: security review, operational behaviour, maintainability over time
- human interventions per completed task
- time from specification to verified delivery
- failure-recovery success
- cost per accepted application, as distinct from per synthetic task
- maintenance burden of factory-built code
- reuse effectiveness

**Structural observations relevant to the question** [Obs / Inf]:
- **Breadth.** Verification breadth for arbitrary app types is thin. Only R11 (layout diff) and R03 (viewport screenshots, runtime comparison) compare UI mechanically. R02
  captures visual evidence by script (`evidence.py`) but self-reports pass or fail. R01 and R06 rely on prompted
  browser checks [D2 G5]. Only R10 binds runtime verification to the candidate, and only for Python and Node apps. No repository has a verification
  strategy that spans app types [D2 G5] [D3 BP-17].
- **Shared risks.** The three risks common to every execution model (untrusted input, permissions, self-reported
  proof) do not depend on app type. They apply to any factory scope [D3 §5 obs 3].
- **Scope choices.** The repositories that come closest to end-to-end delivery (R03, R10) chose GitHub-issue-driven
  scope on an *existing* repository with project-supplied `verify_commands` or journeys. They do not generate
  applications of arbitrary kind [Obs] [R03 §5] [R10 §4].

---

## 7. Open questions for phase 3 (Consolidated Optimization Strategy)

Each question says what phase 3 must decide or measure, and the evidence it should start from.

| # | Decide or measure | Question | Starting evidence |
|---|---|---|---|
| Q1 | Decide (with measurement) | Is a general app-building scope worth it, given that no repository demonstrates it and the only outcome data are small synthetic tasks? What evidence would be enough: a matched-baseline trial on representative real app tasks? | §6; R05 v3 limits (clone `README.md:136-137`); [D3 §4.4] |
| Q2 | Decide | Where should the acceptance decision sit, and what must it check, so that "accepted" cannot be self-reported or vacuous? | §2.2; P1, P4, P5; S1, S10 |
| Q3 | Measure | Does any orchestration layer beyond the host's native subagents add quality, or only control and records? Phase 3 would need its own matched baseline to answer this | P2; [D3 §4.1]; [D4 §2.3] |
| Q4 | Decide | What minimum security posture (permissions, isolation, untrusted-input separation, supply chain, fail-closed guards) must every adopted or reimplemented component meet, given that none meets it as shipped? | [D1 §5.7, §5.8]; O1-O4, O19; [D4 §1.12] |
| Q5 | Decide | For the strongest correctness ideas that have no licence (R05, R10): reimplement, ask the authors for permission, or do without? | §2.9; [D4 §5.2] |
| Q6 | Measure | Which of the owner's seven measures can be instrumented first, and with what baseline: first-pass acceptance, interventions per task, time to verified delivery, cost per accepted deliverable, recovery, maintenance, reuse effectiveness? | [D3 §4.4]; O10, O11; R09 tracer and R05 cost-per-accepted as reference designs |
| Q7 | Decide | How should approval be designed so the agent cannot satisfy it: separate identities, an out-of-band channel? | P3; AP-02; O7 |
| Q8 | Decide | For reference-driven development: which parity level (product, artifact, or both); how to obtain independent parity evidence; and which legal constraints apply (clean room, terms of service, patents, engine EULAs)? | §2.7; S7; O15, O17; [D4 §5.3] |
| Q9 | Decide | Should fast-churning dependencies (R07 six majors in three months; R08 pre-1.0 with breaking `v1`) be taken as dependencies or reimplemented narrowly, and with what pinning and upgrade policy? | §2.8; [D4 §4.1, §4.5] |
| Q10 | Decide | Which host and runtime semantics are assumed, given conflicts C1-C3: filesystem hooks not loaded under `setting_sources=[]`, though managed policy hooks still load [Docs], hooks are Claude Code only, and only one spine can own the loop? | [D4 §3.2]; S6 |
| Q11 | Decide | Which spend ceiling should apply per task, and how is it enforced rather than measured? | P9; O10; AP-13 |
| Q12 | Decide | Should a reuse-decision step (REUSE … REJECT) be part of the factory's standard approach, given that the value definition requires it and no repository provides one? | O14; [D2 G1]; [D4 §0] rules |
| Q13 | Measure | Would the gaps no repository fills, or fills only partly (O7, O8, O11, O14, O15), be cheaper to build or to compose from partial mechanisms? | §5; [D4 §2] BUILD NEW notes |

---

## 8. Cross-deliverable reconciliation

This section records two kinds of item. §8.1 lists disagreements that remain between D1-D4 as they now stand. §8.2
lists disagreements that the verification correction pass of 2026-10-22 resolved, with where each was resolved.
Item numbers from the first version of this report are kept so earlier references still resolve. X14 (category
placement) and X22 (D1/D2 scale divergences) are dropped: X14 was never a contradiction (see §0), and X22 is
superseded by D1 §4d and the D2 §1 note.

### 8.1 Remaining disagreements

| # | Topic | Where the deliverables stand now | Resolution in this report | Material? |
|---|---|---|---|---|
| X7 | R09 permission model | D1 D6 Adequate; D2 D1 W. One of the four divergences kept and explained in D1 §4d and the D2 §1 note: D1 credits the post-hoc write boundary as partial permission enforcement; D2 credits it under B2 and D6 | **Weak as a permission model.** The `pi --tools` allowlist is defeated by `bash` on every starter agent, and the example `just cc` skips permissions [R09 §8]. The write boundary is credited as judge protection (P5, O1) | Low |
| X23 | R08 approval gates | D1 D5 Weak (the library has no gate); D2 C2 A (also counts the repository's own privilege-split CI workflow and human merges). Kept divergence [D1 §4d] | **The library has no gate**, as a capability a caller inherits. The repository's own CI workflow is credited as a component (P7, S5) | Low |
| X24 | R06 cost control | D1 D11 Adequate; D2 E2 W, with E4 S. Kept divergence: D1 D11 includes context footprint, D2 rates it separately as E4 | **Spend control Weak; context economy Strong** (zero idle context in Claude Code [Docs] [R06 §9]) | Low |
| X10 | R07 cost control | D1 D11 Strong; D2 E2 A, with E4 S. Kept divergence, same boundary as X24 [D1 §4d] | **Context economy Strong** (measured checkpoints, byte caps); there is no budget on agent spend [R07 §9] | Low |
| X11 | Candidate verdicts, D2 vs D4 | Unchanged in both after the correction pass. D2 says REUSE for `imgdiff.py`, Sandcastle (as a dependency, "with ADAPT for hardening"), the R09 tracer, R09 envelope types, R03 guard hooks ("with fail-open noted") and the R03 Stop hook; REFERENCE ONLY for the R02 recorder. D4 says ADAPT for all six and REIMPLEMENT for the recorder. Three further D2 verdicts are looser than D4's: R08 package "REUSE as a dependency" with no ADAPT qualifier (D2 H2) and "ADAPT or REUSE R08 (as a library)" (D2 A4); R08 session handling "REUSE as a dependency or ADAPT" (D2 A3) against D4 §1.8 ADAPT; and the R07 ledger "REIMPLEMENT (or ADAPT)" (D2 G6) against D4 REIMPLEMENT | **D4 governs**, because its rule 2 applies the mandatory criteria [D4 §0]. ADAPT: `imgdiff.py` (unbounded decompression; crash on truncated IHDR); Sandcastle (bypass by default, `.git` RW, branch-name interpolation); R09 tracer (raw prompts); R09 envelopes (Pi-shaped); R03 guard hooks and Stop hook. For the guard hooks, D4 now says the hook code must exit 2 on internal error, because `onFailure: "block"` alone does not catch an exception that exits 0 [D4 P4-1]. R02 recorder: REIMPLEMENT the idea, REFERENCE ONLY the code (no licence). R03 read helper: REUSE (both). R08 package and session handling: ADAPT (bypass default; undocumented CLI session layouts). R07 ledger: REIMPLEMENT (the formalism is the value; closure trusts caller-supplied proofs) | **Yes** for phase 3 reuse planning |
| X15 | R08 explore privilege split, test status | D3 BP-24: Implemented, thin test (33-line `batch.test.ts` on verdict labels). D4 §1.8 row: status I (no tests). R08 §8 and §12.8 now state the test status (erratum E7 applied) | **Implemented with a thin test**; the snapshot-validation path and `apply.ts` have no visible test [R08 §8] | No |

### 8.2 Resolved by the correction pass (2026-10-22)

| # | Topic | Original disagreement | Resolved where | Status now |
|---|---|---|---|---|
| X1 | R03 merge-policy default | D2 C2 and D3 BP-14 read `human` as the default | D2 P2-2 (§C2); D3 P3-2 (BP-14); D1 P1-5 (Summary #4, §4a, §5.4, §5.7) | **All four say `auto`**: code `merge-policy.py:133`, schema `config-schema.json:135`, setup `super-board-setup.py:258`. `human` is opt-in. Unreadable metadata exits 2 and fails safe to a human (clone `merge-policy.py:21-22`). Material: a model lane merges its own reviewed PR by default |
| X2 | R05 independent verification on main | D1 Adequate vs D2 W | D2 P2-1 (C1 R05 → A) | Both Adequate |
| X3 | Supply chain, R06 and R07 | D1 R06 Strong, R07 Adequate; D2 both S | D2 P2-3 (D5 R07 → A; R06 S kept, with the reason stated in §D5) | **Both deliverables: R06 Strong, R07 Adequate.** This supersedes my first-version reading ("both Adequate end to end"). The distinction holds on the evidence: R07's skill instructs unpinned execution in-repo, while R06's gap is a third-party install command. The unpinned install path still counts toward O19 |
| X4 | R10 produced-work verification and merge gating | D1 Unknown vs D2 A | D2 P2-1 (C1, C2 R10 → U; D6 R10 → U) | Both Unknown. In-repo components are rated as components |
| X5 | R10 isolation | D1 Weak vs D2 A | D2 P2-1 (D2 R10 → W) | Both Weak as security isolation. Strong as app-under-test identity (D4 §2.7) |
| X6 | Untrusted input, R02 and R08 | D1 Weak for both vs D2 A for both | D2 P2-1 (D4 R02 → W); D1 §4d first pass (D8 R08 → Adequate) | **R02 Weak and R08 Adequate in both.** R08's Adequate credits the privilege-split explore job and the inert-argument marker; its default templates still pass issue text to permission-bypassed agents (§2.3) |
| X8 | R07 factory self-testing | D1 Adequate vs D2 S | D2 P2-3 (C3 R07 → A) | Both Adequate (main CI 19 ok / 14 failed / 66 cancelled / 1 action_required of the last 100 runs) |
| X9 | R08 state and resume | D1 Adequate vs D2 S | D2 P2-1 (A3 R08 → A) | Both Adequate. Session-level resume is tested (`SessionStore.test.ts`, D2 P2-10); there is no workflow checkpoint |
| X12 | Sandcastle test files | D4 "49 test files beside the sources in `src/`" | D4 P4-4 | 54 repo-wide, 53 under `src/`. Cases ~1,416 (R08) or 1,413 (regex); immaterial |
| X13 | R05 v3 code-pass measure | D3 alone gave code-pass 30/36 vs 31/36 | D4 P4-9 (§2.3); R05 erratum E6 applied | D3, D4 and R05 give both measures. D1 and D2 cite the acceptance headline only, which is not a contradiction. Reading: no quality advantage either way |
| X16 | R10 no-licence rows classed "needs adaptation" | Phase 1 vs D2/D4 REIMPLEMENT | Erratum E1 applied to R10 §13 and RESEARCH_INDEX | REIMPLEMENT everywhere |
| X17 | R03 guard-hook remedy | D4 said "set `onFailure: \"block\"`" | D4 P4-1 (§1.3, §1.12, §4.9) | The hook code must exit 2 on internal error (all five swallow exceptions and exit 0, clone-confirmed); `onFailure` covers only crashes and timeouts. D2's "REUSE with fail-open noted" remains under X11. Material (security) |
| X18 | R05 v3 false completions | D3 "5-8 of 36 in v3" | D3 P3-1, P3-6 | 5/36 direct, 6/36 Factory; they persist in every arm of v2-v4; v1 had none under its original tests |
| X19 | "All reviewers are the same model family" | D3 BP-09, D4 §2.3 absolute | D3 P3-8; D4 P4-3 | R09's starter reviewer (gpt-5.6-terra) differs from the builder default (gemini-3.6-flash). R02's reviewer is an external bot |
| X20 | `setting_sources=[]` and hooks | D4 tagged hook exclusion [Inf] | D4 P4-2 | [Docs]: filesystem hooks load only when their source is included; managed policy settings load regardless |
| X21 | R07 tool-effects table, test status | D3 BP-26 "tests not established" | D3 P3-4; R07 erratum E9 applied | Validated (T): `src/contracts/toolEffects.test.ts` (6 cases) |

Other corrections in D1-D4 that touch statements in this report and already agree with it are D2 P2-8 (clean-room
gap restricted to reference-driven builds), D2 P2-9 (R07 compared within G-RE only), D3 P3-7 (v3 and v4 cost per
accepted result), D4 P4-8 (R07 CI runs sum to 100) and D1 P1-6 (R03 has five guard hooks and one cleanup hook).


---

## Limits of this analysis

- **Nothing was executed.** All test, CI and runtime statements rest on the phase 1 reports' reading of the code and
  on GitHub metadata. "Validated" means tests are committed or measurements are published, never that this campaign
  reproduced them.
- **Second-hand, third-hand evidence.** This report synthesizes D1-D4, which synthesize phase 1. For load-bearing
  points I went back to the reports (§1, §14, §16 of all 11) and to the clones for nine checks:
  - R03 merge-policy default (`merge-policy.py:15-40,120-140`, `config-schema.json:135`, `super-board-setup.py:258`)
  - R08 test-file count (`git ls-files`)
  - R05 v1 and v2 results (`reports/2026-09-25-v1/README.md:10-36`, `v2/README.md:12-44`)
  - R05 v3 results table and stated limits (`reports/2026-09-25-v3/README.md:1-40,125-140`)
  - R05 v4 cost per accepted result (`v4/README.md:58`)
  - R05 case list (16 directories under `evals/cases/`)
  - R03 guard-hook exception handling (five `guard-*.py`)
  - R07 `src/contracts/toolEffects.test.ts`
  - D4 §1 candidate-verdict counts (§5a)

  Everything else relies on D1-D4 and the corrected reports.
- **Outcome evidence is extremely narrow.** The only controlled outcome data are one author's synthetic single-file
  Python benchmark, on an unmerged branch, with Sonnet 5 only and a 300-second budget. Nothing here generalizes to
  applications, large repositories, other models or real teams.
- **Out of scope or unread:**
  - Archon internals (R10)
  - Sandcastle's external daemon (R08)
  - most REA provider directories (R07)
  - Super-Board's auxiliary skills and docs site (R03)
  - Codex-side behaviour (R03, R06)

  Statements that depend on them are [Unk] or [Claim].
- **Synergies and opportunities are inferences.** No composition in §3 exists, and none was built. Effort and
  maintenance estimates are D4's qualitative readings. The opportunity list in §5 is generic and is not prioritized
  for any project.
- **Principles are capped by evidence strength.** P2, P4 and P5 rest substantially on one author's or one
  repository's unlicensed or unmerged work.
- **Licence statements** are technical readings, not legal advice.
- **Corrected deliverables.** This report cites D1-D4 as they stand after their verification corrections of
  2026-10-22 (D1 P1-1…P1-10, D2 P2-1…P2-12, the last three applied after this report's update and affecting no figure here; D3 P3-1…P3-9, D4 P4-1…P4-10), and the phase 1 reports after errata
  E1-E10 were applied. Guard-hook exits, `toolEffects.test.ts`, v4 costs and the merge-policy default were
  re-checked in the clone. The `setting_sources` docs reading comes from D4 (P4-2) and was not re-fetched here.
- **[Docs] facts** are those cited in D1-D4 and the reports (official docs accessed 2026-10-22). None were re-fetched
  here.

## Report discrepancies found

These are phase 1 report errata collected from D1-D4 and de-duplicated, plus any found in this pass. This analyst
did not edit the phase 1 reports; the coordinator applied the errata, and each report's §17 records them as
"(phase 2 erratum)". Errors inside the phase 2 deliverables are in §8.2.

| # | Report and location | Discrepancy | Evidence | Material? | Raised in | Status |
|---|---|---|---|---|---|---|
| E1 | R10 §13 and RESEARCH_INDEX §10 | Four no-licence rows are classed "needs adaptation": cross-platform timer generation, runtime host, revision-bound resource materializer, and the MISSION/WORKFLOW_POLICY/FACTORY_RULES/HOLDOUT templates. The index added "needs adaptation, with permission". V10-1 had reclassified only `run.py` and `ci.py` | R10 header: no licence; `gh api license: null`; the table's own preamble says reuse of code needs permission | **Yes**: reuse verdicts; at most REIMPLEMENT under rule 7 | D4 #1 | Applied in phase 1 reports (R10 §13 and §17; index) |
| E2 | R02 §13 | The `github_review.py` licence cell (MIT) omitted that its regression tests in `tests/` are unlicensed | R02 header lists `tests/` with no licence | **Yes** for reuse with tests (the tests must be reimplemented) | D4 #2 | Applied in phase 1 reports (R02 §13) |
| E3 | R07 §13 | The licence column omitted LGPL-2.0 `frida`, the GPLv3 GCC runtime (with exception) in the Windows addon, GPL engines (Unicorn GPL-2.0, GDB GPL-3.0-or-later), JEB's disclosure restriction, and four README-listed tools missing from the notices | Clone `THIRD_PARTY_NOTICES.md`, `licenses/` [D4 §5.3] | **Yes** for redistribution or hosted use | D4 #3 | Applied in phase 1 reports (R07 §13) |
| E4 | R02 §13 | The `before-and-after` licence row did not name the licensor (James Clements) | Clone `before-and-after/LICENSE:3` | No (provenance detail) | D4 #4 | Applied in phase 1 reports (R02 §13) |
| E5 | R01 §2.4 | Omitted that the v2 `factory/bin/gate` has a `--hook` mode that runs the checks and exits 2 on failure | Clone branch `8a428453` `…-v2/factory/bin/gate:7,85-105` | Low (unmerged, GPL), but it is the only Claude Code-native stage-gate design in the set | D2 #1 | Applied, qualified: the SubagentStop wiring appears only in the v2 docs (`SF2/DESIGN.md:87-88`, `SF2/BUILD_PROMPT.md:73-74`), and the builder agent file that would declare it is not committed [R01 §2.4] |
| E6 | R05 §7, §9, §14 | Cited the v3 headline (accepted 30/36 vs 29/36) but not the secondary measure "code passed independent tests, regardless of completion", 30/36 vs **31/36** in favour of the direct arm | Clone `codex__eval-suite/evals/reports/2026-09-25-v3/README.md` results table and `:127-131` | **Moderate**: it strengthens "no quality advantage from orchestration" | D3 #1 | Applied in phase 1 reports (R05 §7, §9, §14, §16) |
| E7 | R08 §8, §12.8 | Did not state whether the privilege-split explore workflow is tested. A 33-line `batch.test.ts` covers verdict labels only; the snapshot-validation path has no visible test | `.sandcastle/agent-workflows/explore/batch.test.ts` (D3 spot-check) | Low | D3 #2 | Applied in phase 1 reports (R08 §8, §12.8) |
| E8 | R08 §1, §7 | Test-case count "~1,416" / "~1,400"; a line-anchored regex gives 1,413 over the same 54 files | D1 and D2 recounts | No (within "~") | D1, D2 #2 | No change needed |
| E9 | R07 §4, §8, §12.5, §13 | Did not mention that the tool-effects table has a dedicated test, `src/contracts/toolEffects.test.ts` (6 cases) | Clone (file present); D3 P3-4 | Low (it raises BP-26 from Implemented to Validated (T)) | phase 2 verifier, re-checked here | Applied in phase 1 reports (R07 §4, §8, §12.5, §13) |
| E10 | R03 §13 | Said two guard hooks credit an `ai-builder-starter-kit` / `BookKeepingApp` origin | Clone `hooks/guard-secrets.py:9`; [D4 §5.1] | No (provenance detail) | phase 2 verifier (P4-5), re-checked here | Refined and applied: three guard hooks credit an origin (`guard-secrets.py:9`, `guard-key-literals.py:13`, `guard-worktree-path.py:13`), plus `cleanup-wt.py:34`, four hook files in all [R03 §13] |

No other load-bearing phase 1 claim checked by D1-D4 or in this pass was found wrong. D1 reports about twenty
re-checks, D2 eighteen, D3 about twenty-five and D4 a set of licence and code checks, all matching the reports.

## Revision notes (2026-10-22)

This update pass brings the report in line with the corrected D1-D4 (verification corrections P1-1…P4-10) and the
corrected phase 1 reports (errata E1-E10 applied). What changed:

1. **§8 rewritten in two parts.**
   - §8.1 now lists only the disagreements that remain:
     - X7, R09 permission model
     - X23 (new), R08 approval gates
     - X24 (new), R06 cost
     - X10, R07 cost
     - X11, D2 vs D4 candidate verdicts (unchanged in both deliverables)
     - X15, R08 explore test status

     The four rating divergences match D1 §4d and the D2 §1 note.
   - §8.2 marks X1-X6, X8, X9, X12, X13 and X16-X21 as resolved, each with the correction that resolved it.
   - X14 is dropped (never a contradiction). X22 is dropped (superseded by D1 §4d and the D2 §1 note).
2. **X3 resolution changed.** D1 and D2 now both rate supply chain R06 Strong and R07 Adequate, for a stated reason
   (in-repo `@latest` instruction vs a third-party install command). I adopted that reading and dropped my first
   version's "both Adequate end to end". §2.3's supply-chain bullet was updated to match.
3. **X6 resolution changed.** Both deliverables now rate R08 untrusted-input handling Adequate (D1 changed D8 R08)
   and R02 Weak. My first version had R08 Weak on the default path. The §2.3 facts about R08's templates are
   unchanged.
4. **Errata table.** It gained a "Status" column. E1-E7 and E9 are applied in the phase 1 reports; E8 needed no
   change. E10 is refined: three guard hooks plus `cleanup-wt.py`, four hook files. E5 is applied with a
   qualification: the SubagentStop wiring is only in the v2 docs, and the builder agent file is not committed. A
   stray blank line that split the table is removed. The intro now says the coordinator applied the errata.
5. **§2.1 R01 v2 sentence qualified** to match E5.
6. **§0** no longer points to the dropped X14. It states the grouping compatibility directly.
7. **§3 S6** cites [D4 §3.2 C3] for the `setting_sources` / managed-policy hooks reading, in place of the
   verifier relay.
8. **Limits and closing note.** The Limits bullet on corrections now names the corrected deliverables and errata.
   The closing note counts D2's spot-checks as eighteen (D2 added items 17 and 18).
9. **Checked, no change needed.** Nothing else in the report relies on a changed figure or rating:
   - merge-policy default `auto`, v3 false completions 5/36 and 6/36, code-pass 30/36 vs 31/36, v3 and v4 cost per
     accepted result, R07 CI 100-run split, Sandcastle 54 test files, the R09 model-family exception, the
     guard-hook remedy, and the clean-room gap restricted to reference-driven builds were already correct
   - R07 is compared within G-RE only

**Second correction pass** (verifier findings S1-S13 for this report). Each was confirmed against the evidence
before it was applied. All thirteen were applied.

- **S1:** §1 item 1 now says components meet "a security or correctness bar" [D1 §5.8]. They are split into
  security, correctness and rendering-only bars. The missing D1 §5.8 rows are added: R05 SDK options and contract,
  R07 ledger, R08 isolated-VM sync, R09 `finish(accepted)`, R10 guard self-mutation. The R05 and R10 items are marked
  "idea only".
- **S2:** R05 v1 figures were added to §1 item 2, P2 "Against", §2.5 and the §6.1 R05 cost cell, confirmed in the
  clone (v1 `README.md:17-34`): all modes 36/36; Factory 61.8 s vs 29.3 s median; $6.16 vs $2.47 (task-only SDK) and
  $3.52 (direct CLI); p90 148.9 s vs 43.9 s; v2 118.5 s vs 28-36 s. P2 now limits the latency gain to v3's
  reviewer-equipped arm.
- **S3:** §6.2 "Demonstrated" no longer lists R03. Its own-repository evidence is indicative usage only: PR #73
  format; target-repo work narrated.
- **S4:** §6.2 "Breadth" now says R11 and R03 treat UI evidence with tooling, R02 captures visual evidence
  (self-reported), and R01 and R06 rely on prompted browser checks [D2 G5].
- **S5:** §1 item 4 and §3 S4 now name both reviewer exceptions: R09's mixed-provider roster and R02's external bot.
- **S6:** §1 item 9, P14 and O18 now say "documented properties … in seven repositories, several safety-related".
  The safety-related ones (R08 ADR 0015, R04 "blocking" hooks, R07 "authenticate") are separated from the
  functional ones.
- **S7:** §1 item 6 now names what R05 measures: accepted rate, false completions, wall time, cost per accepted
  result, and timeouts as its only recovery data. It also names what R05 does not measure: human interventions (v2
  `README.md:42`) and reuse effectiveness.
- **S8:** §8.1 X11 adds the R08 package (D2 H2, A4), R08 session handling (D2 A3) and R07 ledger (D2 G6) verdict
  differences. All are resolved by D4.
- **S9:** two new subsections were added without renumbering any existing section:
  - §2.10 Innovations, from each report's §12
  - §5a Implementation leverage, best approaches and trade-offs: verdict counts over 175 D4 §1 rows, the 21 REUSE
    components that pass the mandatory filters, and a best-approach and trade-off table pointing to §2-§5
- **S10:** §6.1 R01 human-involvement cell: the end states are [Obs]; the human approval of job 001 is the README's
  account, [Claim] [R01 §5].
- **S11:** §5 reading-across corrected.
  - O14 and O15 are no longer mapped to the security criterion. The count is now sixteen of twenty.
  - The "no partial mechanism" claim is narrowed to O8, O14 and O15. O7 and O11 are noted as having only adjacent
    partial evidence. Q13 is aligned.
- **S12:** the Limits clone-check list now names all nine re-checks.
- **S13:** §3 S5 marks R05's JSON-encoded context "(reimplemented; no licence)". P11 marks R05 v3/v4 as the
  unmerged `codex/eval-suite` branch.
- **Also fixed:** the §2.9 E1 bullet is now in the past tense, since phase 1 was corrected.
- **S14-S16 (closure-pass nits, applied by the coordinator):** §2.10 reuse-mode cells for R03 and R08 now say REUSE, ADAPT or REIMPLEMENT per component (per D4 §1.3 and §1.8), and R10's evidence strength is qualified; §6.2 "Breadth" says R11 and R03 compare UI mechanically and R02 captures visual evidence by script, with the stray line breaks removed; the §5a BUILD NEW row adds D2's reuse-decision, least-privilege verifier and budget-enforcement candidates.
- **Limits (coordinator, after the index review C9):** the "Corrected deliverables" bullet now cites D1 P1-1…P1-10 and D2 P2-1…P2-12, noting the last three were applied after this report's update and affect no figure here.
