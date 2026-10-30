# S6 — Strategic Optimization Report
> Phase 3 of the Software Factory evaluation campaign · Date: 2026-10-22 · Status: proposal for owner approval; nothing implemented
> Inputs: phase 1 (docs/evaluations/2026-10-22-factory-research/), phase 2 (docs/evaluations/2026-10-22-factory-comparison/), claude_code at b8ed8a7
> Legend: [Ver] verified in claude_code · [Res] research finding · [Exp] expected benefit · [Asm] assumption · [Unk] unknown · [Inf] inference from verified facts · [Docs] official documentation, as read by the cited deliverable on 2026-10-22

## 0. How to read this report

- **Who it is for.** §1 is written for the owner, in plain language, with the reason behind each point. §2 onwards
  holds the detail and the citations.
- **What it is.** The closing report of phase 3. It collects S1 (gap analysis), S2 (reuse matrix), S3 (target
  architecture), S4 (reference-driven engineering) and S5 (roadmap) into findings, expected benefits, risks,
  alternatives and one decision register. **It adds no recommendation of its own.** The one piece of S6 framing is
  the option set for D-28 (§5), which is labelled as such. Where the inputs disagree or
  leave a gap, §9 records it and does not fix it.
- **Numbering.** Decisions in this report are **D-01 … D-28** (two digits, §7). They are not the same as S2's DEFER
  list "D-1 … D-12" (cited here as "S2 §4.2 D-n"), the 2026-10-14 decisions "D1 … D6", or Hermes "D3.2". Roadmap IDs
  (P0-nn … P3-nn, batches B0 … B9) are S5's; gap IDs (GAP-nn) are S1's; opportunity IDs (OPP-nn) are S2's.
  **OC-1 … OC-4** are the owner choices made on 2026-10-23 (§7, "Owner choices, 2026-10-23"), and **OC-5 … OC-8**
  the owner choices made on 2026-10-29 after the P0-10 step-1b record (§7, "Owner choices, 2026-10-29"); round 2
  review findings are cited as R-A-n and R-B-n.
- **Checked for this report** [Ver, read-only, 2026-10-22]: `docs/superpowers/plans/2026-10-14-review-11-rollout.md:144`
  and `:187` (PAT expiry); `infra/hermes-agent/skills/claude-code-proposer/SKILL.md:42`,
  `infra/hermes-agent/run-ads-audit.sh:25`, `infra/hermes-agent/bin/run-client-audit.py:82` (the `--allowedTools`
  flags); `CLAUDE.md:75,83`; `git ls-files evals`; `.project-brain/canon/2026-07-17-ai-os-charter.md:3,14,33`; `.project-brain/BRAIN.md:4`;
  the Hermes key records (`docs/superpowers/handoffs/2026-10-14-software-factory-phase3-merged.md:92`,
  `docs/evaluations/2026-10-19-hr1-secret-read-controls.md:168-192`); `git status` and HEAD `b8ed8a7`. Everything
  else is cited from S1–S5 or phase 1/2 as they stand after their verification corrections.

---

## 1. Executive summary

**Where the factory stands today.** `claude_code` is already a careful, well-governed factory for its own tools.
Every change passes required automated checks before it can merge. Skills and agents are tested by behaviour against
a "no skill" baseline, and a second model (Codex) can re-judge them. Nothing merges automatically, and project
knowledge becomes canon only with explicit approval. In several of these areas it is ahead of all 11 projects the
campaign studied [S1 §6]. Measured against your value definition, two things hold it back:
- **Security and correctness, the two mandatory criteria, are not yet met.** Security has known breaches (below).
  Correctness of the software it produces is proven only at the floor: the tests CI runs are written by the same
  session that writes the code. Nothing written independently of the builder checks it, and false completions are
  not measured [S1 §4.2].
- **Your outcome measures are not measured.** First-pass acceptance, interventions per task, time from spec to
  delivery, cost per accepted result and reuse effectiveness have no numbers today. The 25 existing skill eval
  reports all predate the current eval method, so none can be compared with new runs [S1 L-06, L-07].

**The security breaches, and what P0 does about each** [S3 §3.1; S5 §0]:
- **(b) Agents that read outside text can also write or run commands.** The 8 repo-audit analysts, skill-guardian
  and skill-scout-agent read web pages or other people's repositories and hold write or shell tools. P0 takes those
  tools away or retires the agent. This **narrows** the breach but **does not close it**. The sessions that combine
  the readers' results can still write, and they still receive text derived from the outside content. P2-06 is the
  planned follow-up that narrows it further; the synthesizer and adapt steps stay an accepted residual.
- **(c) Human approval is a habit, not a lock.** The agent works under your GitHub login. GitHub requires 0
  approvals, and pushes and PR commands are pre-approved on the laptop. The last 10 PRs were opened and merged by the
  same account, with no approval [S1 L-03]. P0 first adds prompts. It then builds a real lock: a separate machine
  account for the agent (you chose on 2026-10-23 to reuse the existing `dentaledge-bot` account, OC-1), your
  approval as the only one that counts, and that approval tied to the last push. The lock holds **only as long as
  every path to your own GitHub authority stays out of the agent's reach** (your `gh` login, keychain, SSH keys,
  tokens, and any browser or desktop channel signed in to github.com) [Asm until measured in P0-10]. Gaps remain:
  - the agent account can still merge a PR you have already approved, unless GitHub restricts merging into `main`.
    P0-10's tests found a way: candidate B, the classic "Restrict who can push", refused every merge attempt by the
    agent account through the API (`merge`, `merge-async`) on a test branch (the UI merge button and `gh pr merge`
    were not tried), and you chose on 2026-10-29 to put it on `main` (OC-6). If B is removed, this is an
    exception you accept explicitly to "Approve, don't merge" (OC-2);
  - even with B, the bot's approval counts on your own PRs, so you could merge one of your PRs normally after a bot
    approval and it would look reviewed [Inf, untested]; the agent account never approves PRs, and bot approvals on your PRs are
    counted monthly (OC-6);
  - prompts can be dodged by other command spellings, and skill deploys and other local actions are only prompted,
    not bounded by GitHub;
  - your own PRs merge through a bypass that skips review (never the checks).
- **(d) Unpinned software is downloaded at run time** (repo-audit's packers, plus one unpinned command in
  project-audit's advice). P0 pins them and adds a CI pattern check that catches the known unpinned forms if they
  come back. Closed for the known cases, held for `skills/`, `.claude/agents/`, `packs/` and
  `infra/hermes-agent/skills/` by the required "Test suites" job through `ci-scan-skills.test.js` from P0-02 (B1); no
  ruleset change needed (OC-3, revised). `npx` still downloads the pinned version without a lockfile integrity check.
- **A fourth form stays open.** Shell commands are pre-approved on the laptop without isolation. P0 only trims your
  local allow list; isolation is deferred.

**What the research showed that changes the strategy:**
1. **More orchestration did not buy quality.** In the only controlled measurement, scripted orchestration and a
   plain Claude Code session with a reviewer scored 30/36 against 29/36. On independent tests the plain session did
   slightly better (31/36 against 30/36). The gain came from *independent acceptance checks plus review and repair*
   (6/9 against 1-3/9, on hand-picked hard cases, against no-review baselines) [Res P2-D5 §1 item 2]. So the plan adds no orchestrator. It invests in checks written apart
   from the builder.
2. **Who decides "done" matters more than the workflow label.** Where code decides, and the checks have been shown
   to fail, errors are caught. Where an AI reviewer decides by following instructions, required steps were skipped:
   one project's UX/UI reviewers (R01) skipped the required browser check in 3 of 4 reviews, and nobody noticed
   [Res P2-D5 §1 item 3]. So the plan uses reviewers that cannot edit files,
   and judges that the judged agent cannot change.
3. **Outside text is the weakest area everywhere**, here too [Res P2-D5 §1 item 5; S1 §4.1 D8].
4. **Approval is only as strong as the separation between the human's and the agent's identities.** No researched
   project separates them [Res P2-D5 P3]. This is new work, done with native GitHub features.
5. **Nothing external is worth adopting wholesale.** None of the 21 external components that passed the safety
   filters fills a real need here. The strongest correctness ideas have no licence, so we can only rebuild the idea
   ourselves [S2 §0, §3.1].

**The shape of the plan.** Keep and strengthen. 41 roadmap items: 11 in P0, 17 in P1, 10 in P2 and 3 in P3 [S5].
- **Additions.** Two small agent definitions: a reviewer that cannot edit, and a read-only `reference-analyst`.
  Plus templates and fields.
- **Retirements.** Two: skill-guardian and gstack-pattern-audit.
- **Not added.** No external frameworks, no new orchestrators, no new runtime dependencies [S3 §0].
- **Order.** Measure first (B0), then the smallest safe changes (B1 already holds the unpinned-install check for every
  scope), then the GitHub lock (B5). P0 counts as done after the P1-10 runs that measure part of its acceptance (B6).

**What you must decide (§7).** 28 decisions, 14 of them before P0 can start (D-01 … D-14). On 2026-10-23 you made
four choices that settle parts of them (OC-1 … OC-4, recorded in §7; OC-3 revised the same day). On 2026-10-29,
after the P0-10 test results, you made four more (OC-5 … OC-8, §7). The ones that matter most:
- D-01: approve the P0 set and its order, and accept its stated exceptions.
- D-12 and D-13: the approval lock and the agent's own account (account chosen: `dentaledge-bot`, OC-1; merge
  restriction checked first, OC-2, and chosen, OC-6; token type, OC-5).
- D-10: stop skills deploying themselves, which changes `CLAUDE.md:75`.
- D-11: make the brain guard fail closed (kept, and it reverses an earlier failure policy, OC-4).
- P0-02 holds the unpinned-install check for every scope through an already-required job; D-15 (making the general
  scan of packs and Hermes skills required) is back before P1 (OC-3, revised).

Several of them need you to act yourself: GitHub settings, a new token for the agent account, retiring the expired
bot token's leftover value, and your local allow list. P0 deliberately adds routine human steps (prompts, deploys,
approvals). §6 lists six items to know now. Two stand out:
- **Bot token expiry, decided.** The Hermes bot token `dentaledge-bot-pat` expires on **2026-10-23**. You decided on
  2026-10-14 to let it expire, not renewed (daily note `2026-10-14.md:35-37`), so Hermes draft-PR delivery is
  dormant from that date and the bot account becomes the laptop agent's account (OC-1). Before a new token is
  minted, you confirm the old one is refused and remove its value from `infra/hermes-agent/.env.pr` (§6 item 1).
- **Correction, with no deadline.** The Hermes proposer is **not** tool-restricted as was believed.

Whether to become a factory that builds any kind of app stays your decision. Phase 3's suggestion is to measure
first (§5, D-28).

---

## 2. Expected benefits

All entries are **[Exp]**: estimates, not results. "Measure first" means no baseline exists yet; B0 or the named item
creates it. Baselines are to be kept as dated, tracked records in `docs/evaluations/` (D-04).

### 2.1 Mandatory criteria

| Criterion | Today [S1 §4.2; S3 §3.1] | Expected after the plan [Exp] | How measured | Baseline |
|---|---|---|---|---|
| S (a) no pre-approved shell without isolation | met as shipped; not met as operated | improved, not closed: local allow list trimmed (P0-07, owner); isolation DEFER | inventory of local allow entries, before and after (owner) | `settings.local.json:10,28,59,63,68` pre-approve `git push *`, `Agent`, `python3 *`, `git *`, `gh pr *` [Ver via S1, machine-local] |
| S (b) untrusted text to write-capable agents | not met | **narrowed, not closed**: no named agent both reads untrusted text directly and holds write tools; orchestrator residuals listed | tools × input-source inventory, reviewed in each P0 PR [S5 §3] | 10 direct readers with write tools (8 analysts, guardian, scout-agent) → target 0 |
| S (c) consequential actions enforced | not met as operated | closed at the GitHub boundary after P0-10, as far as every path to the owner's GitHub authority stays out of reach [Asm until P0-10 measures it]; approved-head merge by the agent account restricted by GitHub (candidate B on `main`, OC-6), or an owner-accepted exception if B is removed (OC-2); local actions only prompted | PRs merged without the owner's code-owner approval covering the merged PR diff (a kept approval's `commit_id` is not evidence on its own, step-1b record §6, OC-8; method for "the approved PR diff" open: to be defined and recorded before the first probe (a) run); owner-bypass merges counted separately (audit log) [S5 P0-10] | 10 of the last 10 (#164-#173) → 0 |
| S (d) unpinned code in shipped paths | not met | closed for the known cases, held for `skills/`, `.claude/agents/`, `packs/` and `infra/hermes-agent/skills/` by the required "Test suites" job through `ci-scan-skills.test.js` from P0-02 (B1); no ruleset change needed; npx fetch without lockfile integrity accepted | P0-02 conformance check, red on a fixture | at least 3 known; **measure first** with P0-02's differential [S5 P0-01] |
| C1 own code correct | met, with named exceptions | exceptions reduced (brain-guard gaps G1-G5, installer, F1 flake) | required CI; each named exception closed per S5 acceptance | exceptions listed in S1 §4.2 |
| C2 produced-work assurance | met for the merge-path floor; not demonstrated above it | demonstrated per requirement ID on piloted tasks | per-ID "verified at first review" rate; false completions caught by independent tests (P1-08, P1-09) | **measure first**: 0 of 38 specs use IDs [S4 §1.1] |

### 2.2 Value dimensions

| Dimension (weight) | Expected benefit [Exp] | How measured [S5 §3] | Baseline |
|---|---|---|---|
| Engineering quality (30) | Fewer false completions and post-merge fixes; every guard and acceptance check shown able to fail; fresh, comparable eval baselines | post-merge `fix(...)` commits within 7 and 30 days; false completions per piloted PR; share of IDs verified at first review; E12 pass rate; share of guard rules with a red-on-removal test | post-merge fixes: **measure first** (B0, P1-01; the 10-14 proxy was planned and never computed [S3 §2.6]); false completions: first pilot; E12: 0 post-E12 reports; guard tests: [Unk] → 100% target (P1-13) |
| Autonomy and orchestration (20) | No added orchestration. Approvals concentrated at decision points (merge, reference gate G1, deploy); fewer rework loops if the acceptance pilot works. **Deliberate cost:** about 2-4 more prompts per PR (more with `gh api`, read-only calls included), one approval click per PR and an owner deploy per skill change; the B0/P1-03 intervention measures are therefore expected to rise, which is not a regression (R-B-13) | prompts per PR-producing session (P1-03); review rounds per PR; dispatch accuracy held ≥ 85%; refine revert correctness (P1-12) | prompts: none (first 30 days after P1-03); review rounds: B0; delivery-lane recovery: **unmeasured**, stated [S5 §3] |
| Development productivity (15) | Reference analysis keyed to named requirements, not generic breadth; reuse decisions recorded | time from spec/plan commit to merge; S4 M1 (references → approved capability map) | spec-to-merge: B0 (38 specs, 51 plans); M1: no requirement-keyed run; the generic proxy is this campaign, about 5.2 h with no target app [S4 §4.1] |
| Security and reliability (15) | The four breach forms reduced as in §2.1; guard blocks instead of failing open; Hermes PAT `/proc` window removed if draft-PR delivery is ever restored (dormant from 2026-10-23, OC-1) | breach inventory; fail-open entries in `guard-failures.log`; P1-16 acceptance (review #12 PASS; no PAT in `/proc` only if delivery is restored) | 50 fail-open entries, all on 2026-10-15 [S1 §3.1]; PAT window mechanism present in `open-proposal-pr.sh:7-15` [S1 GAP-20]; no live token since 2026-10-23 (dormant) |
| Maintainability and adaptability (10) | Smaller surface (agents +2 −1, skills −1); one eval method; one deploy rule; doc drift fixed | definition count (dynamic `find`/`ls`); drift items; stale-eval warnings; model-run deploy steps in definitions | drift items 4 [S1 L-14]; stale eval reports 29/29 [S2 OPP-17]; deploy steps 3 + 1 sanction [S5 §3] |
| Resource efficiency (10) | Cost per accepted result becomes visible; re-baseline staged by tier; reference verification depth set by risk. **Costs added:** E12 re-baseline (18-42 subagents per skill [Res: documented]); +1 subagent per piloted task | tokens per accepted eval scenario (`timing.json`); tokens per merged task (PR line); correction rounds per reference analysis | tokens: **measure first** (unknown [S1 L-11]); campaign verification: about 152 findings over three layers [S4 §2.4] |

**Owner measures not covered, or covered only late** [S5 §3]:
- **Not covered by any item:** delivery-lane failure recovery stays unmeasured.
- **Covered only late:** reuse effectiveness has an instrument (S4 M5), but no baseline until the first reference
  project (P1-14), and only trend data until at least 5 components per verdict class exist.

---

## 3. Risks

### 3.1 Risks of the plan

| # | Risk | Where | Mitigation in the plan | Source |
|---|---|---|---|---|
| RK-1 | **Merges blocked.** If the review rule takes effect before agent PRs come from the agent account (`dentaledge-bot`, OC-1) and the owner's bypass exists, every owner-authored merge blocks (authors cannot approve their own PRs [Docs via S2]) | P0-10 | strict order inside P0-10; a test PR; rollback = disable the review ruleset (owner) | S3 §2.2; S5 P0-10 |
| RK-2 | **Required scan blocks PRs** on existing findings in packs and Hermes skills | P1-06 (before P1, D-15); P0-02 for its conformance findings | triage findings into the baseline before the check is made required (D-15); P0-02 triages its new-scope conformance findings first (OC-3, revised) | S2 OPP-05; S5 P1-06 |
| RK-3 | **CI changes need an owner push**, because the agent token has no `workflow` scope (classic `public_repo`, OC-5; step 1b measured the refusal, step-1b record §3.3); probe (g) measures that the push is refused with GitHub's workflow-scope or Workflows-permission message, against a control push of a non-workflow file that succeeds, after the step-1b test rulesets and probe branches are deleted (V3-ID-1). CI changes therefore travel as owner-authored PRs made outside agent sessions and merged through the PR-only bypass, which skips review (as §3.2 states for owner PRs) | P0-10 | accepted trade-off; it is also the judge protection; runbook: the owner never pushes to agent branches (V2-ID-9) | S3 §2.2; S5 P0-10 |
| RK-4 | **Credential handling.** A new token on the laptop (a classic PAT with `public_repo` only, no `workflow` scope, 90-day expiry, OC-5; it stops working if the repository is made private), its rotation, and secret-read deny rules that must cover its location; the expired `dentaledge-bot-pat` value still sits in `infra/hermes-agent/.env.pr` until the owner removes it. The PR-only bypass is a standing merge path for whoever holds the admin role or sits in the owner-only team | P0-10 | the agent account holds no admin role and is in no bypass team (probe f); measured access re-run at every rotation (probe g); the owner proves the old token dead and removes it; runbook | S2 OPP-08; S5 P0-10; OC-1 |
| RK-5 | **The boundary fails if a session can act as the owner**: `gh` multi-account switching [Asm]; the git credential helper or keychain; SSH keys registered with GitHub [Unk, owner checks]; `GH_TOKEN`/`GITHUB_TOKEN`-style variables; tokens printed into earlier transcripts; any agent-driven browser or desktop channel where the owner is signed in to github.com (Claude in Chrome, the desktop app's built-in browser pane with persistent sign-ins, desktop computer use) [Unk]; any other write-capable bot token reachable from a session. The committed deny rules on `.env.pr` cover Read/Edit, not Bash readers such as the locally pre-approved `python3 *` | P0-10 | D-13 option (b), with every path enumerated and its exposure measured before it is declared out of reach (P0-10 step 3); the owner approves in the browser or mobile app outside agent control; option (c), a second device, if (b) cannot be verified | S3 §2.2; DECISION-S3-1; `credential-governance-lessons.md:115-117,130-132` |
| RK-6 | **A fail-closed guard blocks every guarded tool call** if node breaks; false positives become blocks | P0-09 | G3 fixed in the same change; written break-glass (owner edits settings outside Claude Code); the F1 test flake resolved, or quarantined with a recorded reason, first; differential + timing for regex changes | S2 DECISION-S2-2; S5 P0-09 |
| RK-7 | **Owner time.** More prompts per PR, one approval per PR, a manual deploy after every skill merge (from B1), telemetry labelling (~30 min), reference gate G1 per reference project, weekly brain review | P0-07, P0-08, P0-10, P1-02, P1-14, P2-09 | deliberate: approvals sit at decision points; counted as a measure (§2.2) | S5 §2.3, §3 |
| RK-8 | **Eval and pilot spend.** 18-42 subagents per skill [Res: documented]; tokens [Unk]; +1 subagent per piloted task, cost [Unk] | P1-10, P1-09 | tiered re-baseline (D-03); tokens recorded first (P1-04); pilot limited to 5 tasks before widening | S5 DECISION-S5-2; S2 OPP-11 |
| RK-9 | **Behaviour changes in edited definitions**: scout ranking and dispatch (P0-05); trigger accuracy from description edits (P0-04, P1-14, P2-05, P2-08) | several | agent-eval dispatch ≥ 85%; ranking within a stated tolerance on fixtures; skill-eval against a fresh pre-edit baseline | S5 P0-05, P1-14 |
| RK-10 | **Framing text trips the project's own injection scanner** in skill-audit and agent-audit, failing a required check | P0-06 | run the static scanner on every edited file before the PR | S5 P0-06 (V-S5-15) |
| RK-11 | **Lost conveniences**: skill-guardian's one-command health check; repo-audit's gitingest fallback; copies of skill-guardian already installed in target projects are not removed by uninstall [Inf] | P0-04, P0-01 | README recipe; a one-line manual cleanup note; fallback loss accepted | S5 P0-04; S2 OPP-03 |
| RK-12 | **Installer and Hermes changes** touch security-sensitive areas (target registry creation; PAT delivery container, only if restored) | P1-14, P2-07, P1-16 | install/uninstall kept in sync with tests; Hermes changes under security review #12 and the CI-versioned checklist | S5 P1-14, P1-16 |
| RK-13 | **Perfunctory filling** of IDs, templates and decision tables; an analyst without a shell may be under-capable | P1-08, P1-14 | the reviewer checks IDs; licence and security rows verified first; the coordinator passes git metadata as text | S4 Increment 1 risks |
| RK-14 | **Hermes runs load the committed settings.** The proposer runs `claude -p` with workdir `/projects/claude_code` (`infra/hermes-agent/registry/projects.yaml:20-21`), so hooks and ask rules committed to the root `.claude/settings.json` would load there; a fail-closed guard or a prompt could stop an unattended run [Inf; UNVERIFIED whether the executor skips project settings] | P0-07, P0-09 | a box/container probe, with the Hermes impact sent through the Hermes checklist and security review #12, or Hermes runs explicitly excluded with evidence (OC-4) | S5 P0-07, P0-09 |
| RK-15 | **Fail-closed guard in subdirectory sessions.** Shared settings load from the session's primary working directory [Docs, settings, 2026-10-23], so a registration moved to the root `settings.json` may drop coverage for sessions started in `infra/hermes-agent/`, or coverage may already be absent today: the current local registration already uses `$CLAUDE_PROJECT_DIR/hooks/brain/brain-security-guard.sh` (`.claude/settings.local.json:110`), and the docs define that variable as "the project root where the session started", so what it resolves to in a subdirectory session is UNVERIFIED. With `onFailure: "block"`, a hook path that does not resolve would block every Write/Edit/Bash in such a session [Inf] | P0-09 | D-11 decides that coverage explicitly, with a hook path that resolves there (`hooks/brain/` does not exist under `infra/hermes-agent/`); P0-09 acceptance records what `$CLAUDE_PROJECT_DIR` resolves to in a session started in `infra/hermes-agent/` (OC-4, V2-RS-3) | S5 P0-09 |

### 3.2 Residuals that remain after P0

| Residual | Why it remains | Planned follow-up | Source |
|---|---|---|---|
| Orchestrators receive text derived from untrusted content: the repo-audit merge and its `--pipeline` write into `project-context.json`, and the scout parent's capped `description` | they must combine the readers' output | P2-06: closed-key, length-capped validation; main-session fetch delegated to a read-only reader | S2 OPP-02; S3 §2.3 |
| skill-synthesizer-agent and skill-adapt read audited but untrusted candidate text and must write | their role is to write | accepted; framing, audit before, eval after, staged deploy, PR review | S3 §2.3 |
| The agent account can merge an **approved** head; ask rules only prompt for it | it holds Contents write | P0-10 step 1a compares two merge-restriction candidates and step 1b tests them on a scratch branch pattern, never `main` (V2-ID-3). Step 1b found that candidate B (classic "Restrict who can push") refuses every agent-account merge (step-1b record §3.5); P0-10 step 5a puts it on `main` (OC-6). If B is removed, the merge stays as an explicit owner-accepted exception to `docs/REVIEW_PROTOCOL.md:22` ("Approve, don't merge") and the 2026-10-14 boundary, guarded by the D-09 ask rule, with `allow_auto_merge` kept false (OC-2) | S3 §2.2; S5 P0-10; OC-2, OC-6 |
| Even with B, a bot approval satisfies the review rule on owner-authored PRs, so the owner could merge an owner PR normally after a bot approval; it would look reviewed and not be counted as a bypass merge [Inf, untested] | the owner is the only code owner, so GitHub requires no code-owner review on the owner's own PRs (step-1b record §3.4) | runbook: the agent account never approves PRs; a monthly count of bot approvals on owner-authored PRs (S5 §3); probe (d), reworded, counts them and is re-run on `main` after step 5a (OC-6, OC-7) | step-1b record §3.4, §8; S5 P0-10 |
| Ask rules can be bypassed by other command forms (`git -C . push`, `$HOME/.claude/skills` or `rsync` deploys, a script calling the GitHub API) | a rule "isn't a security boundary around the program" [Docs via S2] | the GitHub boundary (P0-10) covers merges; local actions stay prompted | S5 P0-07; S3 §2.8 |
| Owner-authored PRs merged through the bypass skip code-owner review, judge paths included | the owner cannot approve their own PR | counted separately; runbook says to approve agent PRs rather than bypass | S3 §2.2 |
| Pre-approved local shell without isolation | isolation DEFER | OPP-36 trigger | S3 §3.1 |
| `npx` of a pinned version still downloads without lockfile integrity | accepted | none | S2 OPP-03 |
| Hermes PAT `/proc` window (only if draft-PR delivery is restored; dormant from 2026-10-23) and unrestricted proposer tools | outside P0 | P1-16 with review #12 | S3 §2.10 |
| Hermes draft-PR delivery is dormant | the owner let `dentaledge-bot-pat` expire (decision 2026-10-14), and the bot account is now the laptop agent's identity (OC-1) | restoring delivery is a separate Track A decision and needs its own identity (for example a GitHub App); the account stays single-consumer | §6 item 1; OC-1 |
| Reviewer independence stays within one model family | Codex is for evals only | P3-03, advisory only (D-27) | S3 §2.5 |
| Guard coverage for sessions started in a subdirectory (`infra/hermes-agent/`) or a worktree | shared settings load from the primary working directory; local settings in a git repository are read at the repository root, and "In a worktree, it uses the file at the main checkout's root" [Docs, settings, 2026-10-23]; the registration's `$CLAUDE_PROJECT_DIR` path ("the project root where the session started") may not resolve in a subdirectory session [UNVERIFIED], so coverage may already be absent there today | D-11 decides the subdirectory coverage explicitly (OC-4); the P0-09 test covers the shared-file case and records what `$CLAUDE_PROJECT_DIR` resolves to in `infra/hermes-agent/` (V2-RS-3, V2-RS-11) | S3 Limits; S5 P0-09 |

### 3.3 Risks of not acting

- **The breaches stay open** [S1 §4.2]:
  - outside text keeps reaching agents that can write (scout, guardian, analysts);
  - merges stay approved by habit only (10 of the last 10 PRs had no approval);
  - the brain guard keeps failing open (50 recorded fail-open calls in one day);
  - repo-audit keeps installing unpinned code at run time.
- **Self-improvement cannot be trusted or judged.** Eval reports are stale. A refine run can edit the harvester that
  judges it [S1 L-04]. KEEPs deploy themselves [S1 L-08]. Snapshot and revert have never been exercised by a real
  refine run (E16) [S1 §3.1].
- **Investment decisions stay without data.** App scope, orchestration and spend caps would be decided with no
  baseline [S2 DECISION-S2-8].
- **The Hermes proposal delivery path** is no longer a risk of not acting: the owner decided on 2026-10-14 to let the
  `dentaledge-bot` PAT expire on 2026-10-23, not renewed (`.project-brain/sessions/daily/2026-10-14.md:35-37`), so
  delivery is dormant by decision, not by accident (§6 item 1; OC-1).

---

## 4. Alternatives considered, and why they lost

| Alternative | Why it lost (evidence) | Source |
|---|---|---|
| **Adopt an external factory framework or spine wholesale** (R03 Super-Board runtime, R05 runner, R08 loop templates, R09 ADW chains, R10 + Archon) | One spine only: two loop owners mean two retry budgets and two sources of truth. The only outcome data show no quality gain from scripted orchestration (30/36 vs 29/36; 30/36 vs 31/36 on independent tests). Rejected 2026-10-14 (§4 items 15, 19). Archon is unevaluated and pinned to an unmerged branch | S2 §4.1 R-1, R-2; S3 §4; [Res P2-D5 P2] |
| **Any autonomous merge path** (R03 `merge_policy: "auto"`, R06 `/factory`, R01 approver auto-merge, R05 "no human in the loop") | 2026-10-14 rejection, reaffirmed by the value definition; REVIEW_PROTOCOL "Approve, don't merge" (`:22`). No researched repository demonstrates safe unattended merges. The plan moves the other way: D-12 makes the owner's approval of the last push a lock. It does not by itself remove the agent account's ability to merge an owner-approved head; P0-10 steps 1a-1b checked whether GitHub can restrict that: step 1b found candidate B, and step 5a adopts it (OC-6); the owner-accepted exception with `allow_auto_merge` kept false (OC-2) applies only if B is removed | S2 §4.1 R-3; S3 §4; OC-2, OC-6 |
| **Sandcastle (or any isolation runtime) now** | external runtime with high churn (pre-1.0, breaking `v1` pending); permission bypass by default, `.git` read-write, branch-name injection. Native Claude Code sandboxing has to be verified first | S2 OPP-36, §4.2 D-2; S3 §4 |
| **A general app-building pivot now** | no researched repository demonstrates it; this factory has built no client application; app-type verification has no consumer yet. DEFER, with a trigger, and measure first (§5) | S2 OPP-37; S3 §3.2; S5 P3-04 |
| **Reuse any of the 21 phase 2 REUSE components** | 0 become REUSE here: 8 DEFER, 10 REFERENCE ONLY, 3 REJECT. They are leaf components with no consumer, or claude_code already has a stronger native equivalent | S2 §3.1 |
| **Ask rules only, for approval** | a prompt, "not a security boundary around the program" [Docs] | S3 §5 |
| **One identity + 1 required approval** (S1's first option (c)) | impossible: "Pull request authors cannot approve their own pull requests" [Docs], so every merge would block | S2 DECISION-S2-1; S3 §5 |
| **Separate identity + any 1 approval** | any write-access approver the agent can reach (a bot PAT, the owner's laptop token) would count | S2 OPP-08; S3 §5 |
| **One ruleset with the owner bypass** | a bypass actor skips every rule in its ruleset, required checks included | S3 §5 (V-S3-5) |
| **An out-of-band approval service** | new service with no precedent; native review already binds approval to the last push | S3 §5 |
| **A new machine account for the agent** (D-13 option (i), the earlier recommendation) | GitHub's Terms allow "no more than one free machine account in addition to your free Personal Account" (ToS §B.3), and `dentaledge-bot` already is it, so a new one would mean deleting the bot or paying; reuse needs no new account (that it needs no paid seat is [Asm]: outside-collaborator billing is UNVERIFIED). The earlier "one blast radius" objection no longer applies while Hermes delivery stays dormant (its PAT is recorded to expire 2026-10-23 by the owner's decision; refusal to be proved by the owner in P0-10 step 2). Trade-off: restoring Hermes delivery would then need its own identity (for example a GitHub App). Owner choice OC-1, 2026-10-23 | S3 §5; DECISION-S3-1; OC-1 |
| **Run CI from the base branch (`pull_request_target`)**, or a separate verification repository, to protect the judge | runs base-trusted workflows against untrusted PR code with a write token [Asm]; a second repository is a second subsystem | S3 §5 |
| **Framing text only, for untrusted readers** | labelling is not enforcement [Res P2-D5 P7] | S3 §5 |
| **A new "external-reader" agent for all intake now** | adds a definition before the cheap tool cuts are measured; kept as P2-06 | S3 §5 |
| **A new reference-driven engineering skill, agent team or orchestrator** | every step has an existing owner; 10-14 rejection of a second factory subsystem. The only new piece is a read-only analyst | S2 §4.1 R-11; S4 §3.9 |
| **`claude -p --allowedTools … --permission-mode plan` as the analyst's sandbox** | `--allowedTools` only pre-approves; plan mode still runs read-only shell [Docs via S4 §3.7] | S3 §5; S4 §3.7 |
| **Built-in Plan subagent, or prompt-only, for the reviewer** | Plan's prompt is written for planning (kept as fallback); R01's prompt-only UX/UI reviewers skipped a required check in 3 of 4 reviews | S2 DECISION-S2-3; S3 §5 |
| **Independent acceptance on all tasks at once** | cost [Unk] before token data; pilot first | S2 DECISION-S2-4; S3 §5 |
| **An R09-style trace store** | R09 stores raw prompts, which violates the telemetry privacy rule | S3 §5; S2 §3.2 |
| **A spend cap now** | no baseline exists and no implementation exists anywhere; DEFER until P1-04 shows an overrun or usage limits recur | S2 OPP-28; S3 §2.7 |
| **A weighted numeric score for reuse verdicts** | the value definition treats weights as guidance, not formulas | S4 DECISION-S4-2 |
| **Three-layer verification by default; an automated licence scanner; signed evidence; REA integration; a visual-parity gate** | cost (about 152 findings over three layers); no consumer yet; new supply chain; REA churn and legal terms; no replication project | S4 §3.9; S2 §4.2 |
| **Register all 11 researched repositories now** | the registry has no licence or commit fields yet; entries with no consumer only add review load | S4 DECISION-S4-5 |
| **Stale-eval Stop hook; Codex review gate** | a hook would add a fail-open path (the warning goes in CI instead); a Codex review gate is prohibited by `CLAUDE.md` | S5 §4.2 |
| **Retire repo-audit, or make it the reference analyser** | it gives stack signals, not capabilities, and has never produced a committed audit; harden it and keep it off the reference workflow | S4 DECISION-S4-6 |

---

## 5. The open question: a factory that builds any kind of app

**Your words** (2026-10-22): "I would like the factory to 'build any kind of app,' but I'd rather wait for the
campaign to determine whether becoming a general app-building factory is worth it."
(`.project-brain/support/sources/software-factory-value-definition-2026-10-22.md`, addendum). The AI OS charter (canon
2026-07-17) stays unchanged until you decide.

**What the research found** [Res P2-D5 §6]:
- **Demonstrated:**
  - small, well-specified changes taken to a merged state on existing repositories (R01, n = 2; R08 on its own
    library);
  - code-owned gates refusing unverified merges (R03);
  - on small synthetic tasks, a prompted Claude Code session with a reviewer doing about as well as scripted
    orchestration (R05 v3);
  - independent acceptance checks catching false completions that tests and review accepted (R05).
- **Only claimed:** unattended delivery at scale (R03, R10); building or cloning a product in "weeks" (R11);
  issue → staging → deploy (R10 via Archon, not inspected); the R09 demo app built by the factory (partly verifiable).
- **Unmeasured anywhere:**
  - building apps of different types (web, mobile, backend, data, desktop), or of non-trivial size;
  - greenfield builds from a spec; large repositories;
  - production readiness of factory output;
  - interventions per task; time from spec to delivery; recovery;
  - cost per accepted application; maintenance burden; reuse effectiveness.
- **Largest evidenced outputs:**
  - two small features on a blog (R01);
  - a ~330-line demo app (R09);
  - 16 synthetic single-file Python tasks (R05);
  - library maintenance PRs (R08).
- **Verification breadth across app types is thin.** UI is compared mechanically only in R11 (layout diff) and R03
  (viewports, runtime comparison). Runtime verification is bound to the candidate only in R10, for Python and Node
  apps. No repository has a verification strategy that spans app types.
- **The projects closest to end-to-end delivery chose narrow scope:** issues on an *existing* repository, with
  project-supplied checks (R03, R10).
- **The three risks shared by every model do not depend on app type:** untrusted input, permissions and
  self-reported proof.

**Where claude_code stands** [S1 L-16, GAP-19]: it has built this toolkit and the Hermes infrastructure, and no client
application [Ver from plan titles; Asm that none exists outside the repo]. It has no visual, UI, runtime or
deploy verification. Its outcome measures are unmeasured (§2).

**What phase 3 does about it.** The target architecture is scope-neutral [S3 §3.2]. App-type verification (visual,
runtime) can be attached to the delivery lane's acceptance layer later, without changing the spine. It is DEFER with
a trigger: you choose a general scope, or the first UI project with references starts [S2 OPP-37; S5 §4.1]. The roadmap
builds the instruments first (P1-01 … P1-04). It then proposes a matched-baseline trial on at least 6 representative
real tasks: a prompted session with a reviewer, against the same plus independent acceptance tests. The trial keeps
negative results, and runs before any orchestration or app-scope change (P3-04) [S5 §1.4].

**The decision (D-28), with options.** S5 §1.5 lists the app-scope decision without options. The three options below
are **S6's own framing**, each built from cited sources:
- option A from the owner's stated aim (value-definition source, addendum `:100-102`) and S2 OPP-37's trigger;
- option B from the same addendum, which names the charter's specialized agent teams as the alternative, and from
  the 2026-10-14 evaluation's reading of the charter (`2026-10-14-software-factory-architecture-evaluation.md:34`);
- option C from DECISION-S2-8 (measure first), S3 §3.2 (a scope-neutral architecture) and S5 P3-04 (the matched
  trial).

One step in option C appears in no S1–S5 document: counting the first real reference project (P1-14) as evidence
[Inf].

| Option | What it means | For | Against |
|---|---|---|---|
| **A. Decide now to become a general app-building factory** | the charter is amended through `brain-promote --approve`; the OPP-37 trigger fires and app-type verification work (S2 §4.2 D-3) moves up | matches your stated aim; starts the verification work early | no researched project demonstrates it; there is no baseline to judge it by; it adds work before the P0 breaches are closed [Res P2-D5 §6.2; S2 DECISION-S2-8] |
| **B. Stay within the charter's specialized-teams reading** | close the question; app-type verification stays deferred | least work; consistent with the 10-14 reading of the charter | gives up your stated aim without evidence either way |
| **C. Decide on evidence (closest to phase 3's measure-first line)** | keep the scope-neutral architecture; run B0 and P1-01 … P1-04; approve the P3-04 trial; optionally count the first real project with references (P1-14) as evidence [Inf, S6's framing]; decide the charter afterwards | follows your instruction to decide on evidence; loses no work, because the architecture does not depend on scope [S3 §3.2] | the decision comes later; no deliverable defines in advance what trial result would justify a general scope (§9 CN-9) |

The decision and any charter change are yours, made only through `brain-promote --approve`. Two related canon
decisions travel with it: D-07 (the charter still names skill-guardian) and D-26 (the charter's body says
"candidate" although it is canon).

---

## 6. Time-sensitive items

1. **The `dentaledge-bot` PAT is recorded to expire on 2026-10-23, and letting it expire is a recorded owner decision** (OC-1, folding in R-A-1, R-A-2, R-B-4). The
   expiry is in `docs/superpowers/plans/2026-10-14-review-11-rollout.md:144` ("`dentaledge-bot-pat` expires on
   2026-10-23 (the operator's decision; the box holds no GitHub credential)"), repeated at `:187` [Ver]. The decision
   not to renew it is in `.project-brain/sessions/daily/2026-10-14.md:35-37`: "the bot account's organisation-scoped
   GitHub token dentaledge-bot-pat is left to expire on 2026-10-23, not renewed" [Ver by the coordinator,
   2026-10-23]. Whether GitHub already refuses the token was not checked [Unk]; the owner proves it (below).
   - What it is: the separate bot identity used only by the operator-run draft-PR delivery of Hermes proposals
     (`open-proposal-pr.sh`; Track A Increment 2) [S1 L11].
   - What follows: that delivery path is **dormant from 2026-10-23**. This is not an open decision any more. Restoring
     Hermes draft-PR delivery later is a separate Track A decision and would need its own identity (for example a
     GitHub App), because the bot is now the laptop agent's identity (OC-1); the account stays single-consumer
     (credential canon rule 1, "the isolation boundary is the ACCOUNT",
     `.project-brain/canon/2026-08-17-credential-governance-lessons.md:49-52`).
   - Owner steps, in P0-10 before the new token is minted:
     - confirm GitHub refuses the expired `dentaledge-bot-pat`, using it without printing it ("prove death, never
       infer it", `credential-governance-lessons.md:136-137`);
     - remove the dead value from `infra/hermes-agent/.env.pr` (the owner does this; the agent never reads that
       file);
     - mint the new agent token and store it only where the laptop agent's `gh` uses it.
   - How it bears on the plan:
     - D-13 now **reuses** this bot as the laptop agent's account (OC-1). The earlier "one blast radius" objection
       does not apply while Hermes delivery stays dormant.
     - The PAT `/proc` exposure window (S2 OPP-38, P1-16) matters only if delivery is ever restored; no reissue is
       planned.
     - The plan's rule that the agent must not be able to reach any other write-capable token still holds
       (D-13 (b)) [S3 §2.2].
2. **The Hermes proposer is not tool-restricted as believed.** `claude-code-proposer/SKILL.md:42` runs
   `claude -p … --allowedTools 'Read,Grep,Glob' --permission-mode plan`. The Ads audit jobs use the same flags
   (`run-ads-audit.sh:25`, `bin/run-client-audit.py:82`) [Ver].
   - What the docs say: `--allowedTools` lists "Tools that execute without prompting … To restrict which tools are
     available, use `--tools` instead". Plan mode still runs commands in "the built-in read-only set" [Docs via S4
     §3.7]. So Bash is **not removed**.
   - What still contains them: no write credential (D3.2), `:ro` project mounts, single-host egress and a gateway that
     never sees audit content; not the tool list [S3 §1.4].
   - Planned fix: P1-16 adds `--tools 'Read,Grep,Glob'` to the proposer, with a check that a run lists only those
     tools and refuses Bash. The same flag is to be considered for the Ads audits. Both go through security review
     #12 [S5 P1-16].
   - Consequence: S1 first described these agents as "tool-restricted", which overstated the control. The
     coordinator has since corrected every affected S1 line: ST-7, L11, §6 item 5, GAP-08 and the least-privilege
     rating row, recorded in S1's corrections list (§9 CN-2, resolved).
3. **Hermes Anthropic API key rotation is still open.** The records disagree on whether the key was exposed. The
   2026-10-14 handoff says it "was printed into the 2026-10-14 session transcript" (`…phase3-merged.md:92`). HR1 says
   "Nothing shows it was read into a conversation" and leaves rotation as an owner decision
   (`2026-10-19-hr1-secret-read-controls.md:168-170,190`) [Ver]. This is a different credential from the PAT (§9 CN-8,
   resolved in S5 §2.3).
4. **Uncommitted and untracked brain and eval files.** `evals/gstack-pattern-audit/evals.json` and
   `evals/reference-repo-pattern-extract/evals.json` are modified and uncommitted. They must be resolved before
   gstack-pattern-audit is retired (P1-17). The candidate `2026-08-05-hermes-post-p6-backlog.md` is untracked, so
   it is not in git at all [Ver `git status`; S1 §3.1].
5. **The weekly brain review is overdue** ("Last reviewed: 2026-10-12", `BRAIN.md:4` [Ver]). Two candidates are older
   than 30 days, and five canon entries are stale [S1 §3.1] (P2-09).
6. **Campaign rules stay in force until you approve the roadmap.** No skill, agent, script, hook or settings change.
   Evals stop at `refine-input.json`. Tracked eval reports stay uncommitted unless you approve [S5 Limits; value
   definition working rule 2]. After approval, the eval stop continues until P0-08 and P0-11 merge and P1-12 starts
   (D-03).

---

## 7. Consolidated decision register

**Method.** Every DECISION in S1–S5 is collected here.
- **Duplicates merged:**
  - DECISION-S1-4 = DECISION-S2-5 = DECISION-S4-7 (one decision);
  - DECISION-S1-2 = DECISION-S2-2;
  - DECISION-S3-3 is folded into DECISION-S4-3;
  - DECISION-S1-1 is superseded by DECISION-S2-1 and DECISION-S3-1.
- **One split.** DECISION-S2-1 is split into its two stages: (b) now, as D-09; (c) next, as D-12. S2 recommends
  them in sequence, and S5 runs them in different batches (B3, B5).
- **One decision without an S-number.** The app-scope decision is listed in S5 §1.5 without a DECISION number; it
  is D-28.
- **Order.** The order follows S5's batch order (B0 → B5 for P0). The decisions needed to start P0 come first.

**Column key.**
- **Owner acts:** the owner must personally do something beyond approving the decision.
- **Governance / canon:**
  - ⚙ changes existing governance: `CLAUDE.md`, the GitHub ruleset or settings, committed or local Claude Code
    settings, REVIEW_PROTOCOL, privacy or security docs;
  - 📜 touches canon, the charter, or supersedes an active decision, which only the owner can change, through
    `brain-promote --approve`.

**Owner choices, 2026-10-23.** After two independent reviews of D-01 … D-14, the owner made four choices. They are
the owner's decisions, recorded here and in the rows they change; the rest of each decision still goes through the
normal approval of the register.
- **OC-1 (D-13, account).** Option (ii): **reuse `dentaledge-bot` as the laptop agent's account**, with credentials
  (b) and bypass actor (x). The owner's choice is a new token without workflow rights. Token type (coordinator's
  wording, not the owner's): a fine-grained token (Contents + Pull requests, one repository, no Workflows) if P0-10 step 1b
  shows it works for this collaborator, since it is tested first; otherwise a classic PAT with `repo` scope and no
  `workflow` scope. That token type is superseded by OC-5 (2026-10-29): a classic PAT with `public_repo` only, no
  `workflow` scope, 90-day expiry. Owner steps before minting: prove the expired
  `dentaledge-bot-pat` is refused, remove its value from `infra/hermes-agent/.env.pr`, mint, store the new token only
  where the laptop agent's `gh` uses it. Measured access (P0-10 probe (g)) recorded and re-run at every rotation.
  Hermes draft-PR delivery is dormant from 2026-10-23; restoring it needs its own identity.
- **OC-2 (D-12, merge residual).** P0-10 step 1 first checks, with GitHub docs (1a) and owner-run tests on a scratch branch pattern, never `main` (1b), whether merging into
  `main` can be restricted to the owner alone without blocking the owner's normal merges. If yes, it is adopted in
  P0-10. If no, the agent account's ability to merge an owner-approved head is recorded as an explicit owner-accepted
  exception to `docs/REVIEW_PROTOCOL.md:22` and to the 2026-10-14 boundary
  (`2026-10-14-software-factory-architecture-evaluation.md:166,168`), guarded by the D-09 ask rule, with `allow_auto_merge` kept false (verified false 2026-10-23; added in round 3, V2-ID-3).
  Step 1b found a restriction that works (candidate B), and OC-6 (2026-10-29) adopts it; the exception applies only if
  B is removed.
- **OC-3 (revised by the owner, 2026-10-23; supersedes the round-2 OC-3).** P0-02 holds breach (d) for every scope
  through the required "Test suites" job; D-15 returns to §7.2 and covers only making the general scan of packs and
  Hermes skills a required check. The earlier OC-3 (D-15 into P0) rested on an incomplete premise (V2-RS-1, V3-RS-1)
  and is superseded. "Decide now" is D-01 … D-14; "before P1" is D-15 … D-22. P0-02 (PR-1, B1) adds a
  conformance-only pass in `scripts/ci-scan-skills.js` over `.claude/agents/*.md`, `packs/*/skills/`,
  `packs/*/tools/` and `infra/hermes-agent/skills/`; the general scan scope is unchanged until P1-06 (V4-RS-1).
  `scripts/ci-scan-skills.test.js` asserts the existing full diff for `skills/` and the conformance-pass findings for
  the four extra scopes; P1-06 (PR-10 with the owner's required-check edit) returns to P1 under D-15.
- **OC-4 (D-11 kept, reversal stated).** D-11 stays at (c) and states that it supersedes the P11 owner failure policy
  and the F1 non-adoption of `onFailure: "block"`, with the conditions listed in its row (weekly-review conflict,
  Hermes runs, subdirectory coverage, owner removal of the old local registration, regex rule, telemetry hooks stay
  fail-open).

**Owner choices, 2026-10-29.** The P0-10 step-1a record (`docs/evaluations/2026-10-27-p0-10-step-1a-github-docs-check.md`)
and step-1b record (`docs/evaluations/2026-10-29-p0-10-step-1b-results.md`, "the step-1b record" below) have returned.
On the step-1b record's open questions (its §8), the owner made four choices. They are recorded here and in the rows
they change (§1, §2.1, RK-3, RK-4, §3.2, §4, D-01 (pointer), D-12, D-13, CN-1, Limits, "Decisions requiring
approval"), and in S5 P0-10.
- **OC-5 (D-13, token).** The agent token is a **classic PAT with `public_repo` only, no `workflow` scope, 90-day
  expiry**. It replaces "fine-grained first, otherwise a classic PAT with `repo` and no `workflow`". Evidence: with
  `public_repo`, the bot's push, PR create and view, update-branch, approve and merge worked, and the push of a
  workflow file was refused (step-1b record §3.2, §3.3); a fine-grained token could not be minted, because the org
  was not offered as resource owner (§3.2). It depends on the repository staying public (owner decision,
  2026-10-28); if the repository went private, the token would stop working (fail closed). Within the bot's own
  permissions it still acts as the bot on any public repository [Docs, scopes for OAuth apps, accessed 2026-10-29],
  and the owner is responsible for the machine's actions (ToS §B.3).
- **OC-6 (D-12, merge restriction).** **Candidate B on `main`** as the P0-10 step-5a restriction, as tested: classic
  branch protection "Restrict who can push to matching branches" with users, teams and apps [], `enforce_admins`
  false and no other classic settings. Evidence: on the probe branch it refused every bot merge attempt through the
  API (`merge`, `merge-async`), including bot-approved owner PRs, while the owner's normal and bypass merges worked; its refusals appear in the rule suites
  as the `authorization` rule (`rule_source` type `protected_branch`) (step-1b record §3.5, §3.9); the org audit log
  shows B being turned on and off (owner-reported, 2026-10-29). The ruleset "Restrict updates" alternative was not
  tested (T5 not run). Open: the UI merge button and `gh pr merge` by the bot under B were not tested (step-1b
  record §9). The OC-2 "if none works" exception is no longer needed for bot merges; rollback removes B.
  Guards: a runbook rule that the agent account never approves PRs; a monthly S5 §3 measure counting bot approvals on
  owner-authored PRs; a re-run of probes (b), (d) as reworded, (e) and (i) on `main` after step 5a. Residual that
  holds even with B [Inf, untested]: a bot approval satisfies the review rule on owner-authored PRs, so the owner
  could merge an owner PR normally after a bot approval; that merge would look reviewed and would not be counted as a
  bypass merge. The guards address it. Later and optional: GitHub's team-based required reviewers in rulesets, after
  a docs check and a test.
- **OC-7 (D-12, probe (d)).** Probe (d) as written failed: its first part, `reviewDecision: REVIEW_REQUIRED`, is
  false on owner PRs, because the author is the only code owner (step-1b record §3.4). It now checks what B provides:
  an owner-authored PR approved by `dentaledge-bot` cannot be merged by the agent account (refused with the
  authorization message), and the owner's merge succeeds. The owner's merge is [Inf, untested in step 1b; first
  measured by this probe on `main`], and the probe records which route it took (normal merge or PR-only bypass).
  The probe also counts and reports any bot approval on owner-authored PRs (editor's wording, not the owner's),
  matching the OC-6 measure.
- **OC-8 (D-12, probe (a)).** Probe (a) now checks that the PR diff the owner approved equals the merged PR diff, in
  place of "approved commit = merged head": after an update-branch with an unchanged diff, a kept approval reports
  the new head as `commit_id` (step-1b record §6). A test on `main` after step 5 checks that an update which changes
  the PR's own diff dismisses the approval (untested in step 1b).

### 7.1 Decide now, to start P0

**Owner approval, 2026-10-23:** the owner approved D-01 … D-14 as written in this table, after the round 2-6 reviews.
Nothing is implemented yet. Each P0 item still goes through its own PR, review and the owner actions listed here.

| D | Question (plain language) | Options | Recommendation, and why | Unblocks | Source | Owner acts | Gov. / canon |
|---|---|---|---|---|---|---|---|
| **D-01** | Do you approve the P0 package and its order? | (a) P0-01 … P0-11 in batches B0-B5; (b) a subset; (c) defer | **(a).** P0 is everything the plan does on the four breach forms. Each PR is small or medium and reversible; B0 makes later claims comparable. You accept these exceptions explicitly, each with a revisit trigger: **(a)** pre-approved local shell stays open beyond your allow-list trim (isolation DEFER; revisit at the OPP-36 trigger). **(b)** narrowed, not closed; residuals: the capped scout `description` reaching the writer, the repo-audit merge and `--pipeline` write, other intake paths such as project-setup's WebFetch (revisit at P2-06); synthesizer/adapt accepted, reviewed when P2-06's inventory leaves only this residual. **(c)** closed at the GitHub boundary as far as the credential condition holds; residuals: the merge of an owner-approved head per OC-2 (revisit if GitHub's restriction check changes or an agent-account merge appears in the audit log; the OC-2 exception now applies only if B is removed (OC-6); the bot-approval residual is held by OC-6's guards), skill deploys and other local actions prompted only, not GitHub-bounded (revisit if `check-skill-deploy.js` or review shows a deploy the owner did not run or approve, or at the OPP-36 trigger), owner-bypass merges skip review (revisit when the separate bypass count, S5 §3, shows bypass used for agent PRs). **(d)** closed for the known cases, held for `skills/`, `.claude/agents/`, `packs/` and `infra/hermes-agent/skills/` by the required "Test suites" job through `ci-scan-skills.test.js` from P0-02 (B1); no ruleset change needed (OC-3, revised); `npx` without lockfile integrity accepted (revisit on a supply-chain advisory for a pinned package, or a new install form found in review or by P1-13). P0 deliberately adds routine human steps, so intervention measures rise (R-B-13). "P0 done" is declared after the P1-10 runs (B6) that measure part of P0-01's, P0-03's and P0-06's acceptance, not at the end of B5 | P0-01 … P0-11; B0-B5 | DECISION-S5-1 | approval; accepts the exceptions above; no ruleset edit for (d); owner deploys + `node scripts/check-skill-deploy.js` for P0-02 (skill-audit), P0-06 (9 skills: skill-scout, agent-scout, reference-repo-pattern-extract, gstack-pattern-audit, project-setup, skill-adapt, agent-adapt, skill-audit, agent-audit; skill-synthesizer-agent and `.claude/skills/codex-eval` are project-scoped and need no deploy; repo-audit is deployed in P0-03) and P0-11 | approves the ⚙ changes in D-06 and D-09 … D-14 (including D-14's REVIEW_PROTOCOL text) |
| **D-02** | Measure before adding new mechanisms? | (a) build a spend cap and orchestration changes now; (b) baseline first (git/PR outcomes, telemetry validation, tokens per accepted result) | **(b).** Your measures are unmeasured, no spend cap exists anywhere to copy, and orchestration was not shown to help [Res P2-D5 P2, P9] | B0; P1-01, P1-02, P1-04; keeps OPP-28 deferred; gates widening P1-09 | DECISION-S2-8 | labels about 20 telemetry samples (~30 min, P1-02) | — |
| **D-03** | How much eval spend, and which skills get a "before" measurement? | (a) re-baseline everything before any edit; (b) pre-edit runs only where a before/after claim is made, with evaluator hashes recorded by hand before P0-11; then critical tier, the 4 PENDING placeholders, the two new agents, the rest once tokens per run are known; (c) no pre-edit runs | **(b).** Old reports cannot be compared (decision 2026-10-21); a full run is 18-42 subagents per skill [Res: documented]. **Until P0-08 and P0-11 merge and P1-12 starts, every eval stops at `refine-input.json` and does not invoke skill-refine/agent-refine** (the handoff steps `skills/skill-eval/SKILL.md:109` and `skills/agent-eval/SKILL.md:106` are not followed), and tracked SKILL-EVAL/AGENT-EVAL reports stay uncommitted unless approved (value definition, `…value-definition…md:22`; PR #4 decision, `…pr-4-follow-ups…md:12`) (R-B-1). B0 first runs the D3 check, "recheck with --debug before skill-eval runs" (`decisions/active/2026-10-15-d3-skill-listing-overflow-…md:12`) (R-B-17) | B0 pre-edit runs; P1-10 tiers; before/after claims for P0-03, P0-05, P1-08, P1-14, P1-15 | DECISION-S5-2 | approves each spend tier; approves committing eval reports | campaign rule 2 (reports uncommitted unless approved) |
| **D-04** | Where do baselines live? | (a) only in gitignored `evals/`; (b) dated tracked records in `docs/evaluations/` (numbers, method, sources; no prompt text, no client data), raw data in `evals/` | **(b).** Later phases must compare against a versioned record; generated eval artifacts are never committed (`CLAUDE.md` Never list; 41 tracked files: 39 scenario specs, `evals/.gitignore` and `evals/project-context.json`, see D-06 and CN-13) | P1-01 record; every S5 §3 baseline | DECISION-S3-4 | — | consistent with `CLAUDE.md`; no change |
| **D-05** | What happens to repo-audit? | (A) keep it off the reference workflow and harden it (pin repomix, drop the gitingest runtime install, Read-only analysts, framing); (B) harden it and make it the reference analyser; (C) retire it | **A.** It extracts stack signals, not capabilities; it has never produced a committed audit; its unpinned installs are breach (d) | P0-01, P0-03, P2-05 | DECISION-S4-6 (S2 OPP-01/02a/03/31 agree) | owner deploys repo-audit and project-audit (P0-01, P0-03) + `node scripts/check-skill-deploy.js` | — |
| **D-06** | Retire skill-guardian? | (a) keep; (b) realign it to skill-eval-agent/skill-refine-agent; (c) retire it and `PROJECT-SKILL-HEALTH.md` | **(c).** A second, weaker eval and refine method; 0 invocations July-October; an agent holding WebFetch + Write/Edit/Bash that reads arbitrary pages (breach b). S1 offered (b) or (c); S2, S3 and S5 settle on (c). The charter line it leaves stale is D-07 📜 | P0-04, and P0-05 after it | DECISION-S1-3 | owner deploys the project-audit text change + `node scripts/check-skill-deploy.js`; approves the `CLAUDE.md:83` amendment | ⚙ P0-04 commits a deletion of tracked `evals/agents/skill-guardian/evals.json` and an edit to `evals/.gitignore`, which conflicts with the literal `CLAUDE.md:83`; `evals/project-context.json` is also tracked and generated. The plan proposes, as part of P0-04, either (recommended, smallest change) amending `CLAUDE.md:83` to "never commit generated eval artifacts; scenario specs (`evals/**/evals.json`), `evals/.gitignore` and `evals/project-context.json` (tracked as the toolkit's own context snapshot) are tracked", or the same amendment without `project-context.json` while P0-04 untracks it (resolves CN-13 once `project-context.json` is covered). ⚙ `install.sh:202` (the CLAUDE.md text written into target projects). See D-07 📜 |
| **D-07** | The charter still names skill-guardian as a capability (`canon/…charter.md:33` [Ver]); what to do when it is retired? | (a) accept the stale reference until your charter decision, recorded as a known stale item; (b) amend that line now through `brain-promote --approve` | **(a).** Consistent with leaving the charter unchanged until you decide; never edited directly. Note: canon already carries unapplied charter corrections (memory-corrections D-1, `canon/2026-07-23-hermes-memory-corrections-d1-d5.md`; the status line in D-26). One fact-only charter correction through `brain-promote`, separate from D-28, is offered, not recommended over (a) | P0-04 acceptance (its grep excludes `canon/`) | DECISION-S3-5 | (b) only | 📜 |
| **D-08** | How exactly is skill-scout-agent made read-only? | (a) it becomes a read-only fetcher (Read, WebFetch, WebSearch) returning fixed fields, a capped description and numeric body features, never the body; the calling session scores; the scorer gains a numeric input; (b) restricted fetch subagents under a scout agent that keeps Write/Bash/Agent; (c) framing only | **(a).** No new definition; removes Agent, Write and Bash from the reader. (b) needs a subagent type that does not exist, and its `Agent` tool still spawns all-tool subagents. Residual: the capped description reaches the writer | P0-05; P2-02; P2-06 | DECISION-S3-2 (refines S2 OPP-02 (b)) | owner deploys skill-scout (P0-05) + `node scripts/check-skill-deploy.js` | — |
| **D-09** | Add prompts for consequential commands now? | (a) keep as is; (b) native `ask` rules in the committed root and `infra/hermes-agent/` settings for push, `gh pr merge`, `gh pr review`, `gh api`, `gh auth`, branch deletion, canon promotion, skill deploys and running `install.sh`/`uninstall.sh`; the owner removes `git push *`, `gh pr *` and `git *` from the local allow list and reviews `python3 *` | **(b).** Ask rules beat allow rules and prompt even in auto mode [Docs via S2]; the smallest step. It is a prompt, not a boundary; the boundary is D-12. P0 deliberately adds routine human steps (prompts per PR, owner deploys, owner approvals), so the B0/P1-03 intervention measures are expected to rise; that is not a regression. Read-only `gh api` calls prompt too (R-B-13). Hermes proposer runs load the committed root settings; P0-07 resolves that with a probe or an evidenced exclusion (RK-14, OC-4) | P0-07; prerequisite of P0-10 | DECISION-S2-1 (b) (supersedes DECISION-S1-1) | **yes**: local allow-list trim | ⚙ committed and local settings |
| **D-10** | Stop adapt and refine deploying skills by themselves? | (a) keep the automatic sync and record an exception to working rule 1; (b) all three paths (skill-adapt step 10, skill-refine KEEP, skill-refine-agent KEEP) stage; the owner deploys after merge and runs `check-skill-deploy.js`; `CLAUDE.md:75` is rewritten | **(b).** Resolves the conflict between `CLAUDE.md:75` ("skill-adapt and skill-refine sync their own result", [Ver]) and working rule 1; needed before the first supervised refine. The mid-loop re-eval reads from `skills/`, so the loop still works. P0-08 rewrites all of `CLAUDE.md:75`, not only the sync sentence, and says that "owner deploys" means the owner runs or explicitly approves the deploy command; it adds `skills/skill-refine/SKILL.md:33` ("the keep step syncs that folder") to its change list. `install.sh:88-92` also deploys every skill: P0-07 adds an ask rule for running `install.sh`/`uninstall.sh`, or you accept that path explicitly. The CLAUDE.md text `install.sh:172-205` writes into target projects gets the deploy instruction, or the reason it does not is recorded (R-B-11) | P0-08; P1-12 | DECISION-S1-5 (widened per V-S1-2; S2 OPP-09) | **yes**: every deploy, from B1 | ⚙ `CLAUDE.md:75`; `install.sh` |
| **D-11** | Make the brain guard fail closed? | (a) keep it fail-open and local-only; (b) commit its registration, exit 2 on internal error, `onFailure: "block"`, break-glass; (c) (b) plus edit protection for `decisions/active/` and closing the brain-guard gap G1 (the `--approve` exemption) | **(c)**, kept by owner choice OC-4 (2026-10-23), on two conditions: the G3 "rm" false positive is fixed in the same change, and a written break-glass ships with it. It turns 50 recorded fail-open calls into blocks. **It reverses earlier decisions:** it supersedes the P11 owner failure policy (fail open but visibly, exit 1; `2026-10-15-pr4-hermes-proposal-triage.md:747-749`) and the F1 non-adoption of `onFailure: "block"` (`triage:626`), both recorded in the active decision `2026-10-21-pr-4-follow-ups-…`; after merge the replacement is recorded through capture → compile → `brain-promote --approve`, superseding the old decision (never editing canon or active decisions directly). Conditions: (1) edit protection for `decisions/active/` conflicts with `skills/brain-weekly-review/SKILL.md:21,31`, so P0-09 routes the weekly review's decision edits through `brain-promote` or defines a narrow exemption, and changes that skill; (2) Hermes proposer runs use workdir `/projects/claude_code` (`registry/projects.yaml:20-21`) and would load committed root hooks and ask rules: resolved by a box/container probe through the Hermes checklist and security review #12, or Hermes runs excluded with evidence [UNVERIFIED whether the executor skips project settings]; (3) shared settings load from the primary working directory [Docs, settings, 2026-10-23], so moving the registration to the committed root `settings.json` may drop coverage for sessions started in `infra/hermes-agent/`, or coverage may already be absent today (the current local registration uses `$CLAUDE_PROJECT_DIR/hooks/brain/brain-security-guard.sh`, `.claude/settings.local.json:110`; the docs define the variable as "the project root where the session started"; its resolution in a subdirectory session is UNVERIFIED): D-11 decides that coverage explicitly, with a hook path that resolves there (`hooks/brain/` does not exist under `infra/hermes-agent/`; with `onFailure: "block"` a wrong path would block every Write/Edit/Bash there [Inf]), and P0-09 acceptance records what `$CLAUDE_PROJECT_DIR` resolves to in a session started in `infra/hermes-agent/`; (4) regex rule: the G3 fix is intentionally not a superset, so acceptance requires that the differential's deny→allow set is limited to the intended class, a 1 MB timing sweep and a stated per-scan timeout (`decisions/active/2026-10-15-changing-a-regex-security-pattern-…md:12`); (5) telemetry hooks stay fail-open when registrations are merged ("a telemetry failure must never block", `docs/telemetry-privacy.md:117`) | P0-09; P1-13 | DECISION-S1-2 = DECISION-S2-2 (RR4) | break-glass if node breaks; removes the old local fail-open registration from `.claude/settings.local.json` (a handler defined in several files runs once; which copy's `onFailure` wins is not documented); deploys the brain-weekly-review change; approves the superseding decision | ⚙ committed `.claude/settings.json`; `infra/hermes-agent/.claude/settings.json`; `brain-self-install.sh`; `SECOND_BRAIN_SECURITY.md`; `skills/brain-weekly-review/SKILL.md`; `install.sh`/`uninstall.sh` kept in sync if the install.sh option is chosen; 📜 supersedes the active decision `2026-10-21-pr-4-follow-ups-…` through `brain-promote` |
| **D-12** | Build an approval lock the agent cannot open? | (a) keep as is; (b) prompts only (D-09); (c) five parts: a separate machine account for agent pushes and PRs (`dentaledge-bot`, OC-1); CODEOWNERS `* @<owner>` + `require_code_owner_review`, with `required_approving_review_count: 1`; `require_last_push_approval` + `dismiss_stale_reviews_on_push`; the owner's token out of agent reach; the review rule in a second ruleset with a "For pull requests only" bypass for the admin role or an owner-only team, the checks ruleset keeping no bypass | **(c), after D-09, approved in principle.** A plain "1 required approval" is not enough: any write-access approver the agent can reach would count, and one identity cannot approve its own PR. Order inside P0-10 is strict (RK-1). P0-10 step 1 is split (V2-ID-1): **1a**, a docs check (token semantics, bypass actor types, two-ruleset interaction, merge-restriction candidates, `gh` multi-account, the org's classic-PAT policy), recorded and returned to you, is the R-B-9 gate; **1b**, your own tests on a scratch target (test rulesets on a throwaway branch pattern such as `p0-10-probe/**`, never `main`; a short-lived test token minted from `dentaledge-bot`, fine-grained first, minted and used outside agent sessions, never printed into a transcript, revoked after; test rulesets and probe branches deleted after the test; the scratch layering mirrors `main` with a checks ruleset with no bypass, the review ruleset and the candidate restriction, and the required check is emulated by a test status context you set with the commit statuses API, since CI does not run on pull requests into `p0-10-probe/**`, `ci.yml:3-7`; V3-ID-1, V3-ID-2, V3-ID-4), with results returned to you. Both come back before any production account, token or ruleset step on `main`, with fallbacks if an assumption fails (credential option (c), a GitHub App, or a re-decision) (`CLAUDE.md:76`) (R-B-9). Both have returned (step-1a record of 2026-10-27, step-1b record of 2026-10-29). **Merge residual (OC-2, V2-ID-3):** step 1a compares a ruleset "Restrict updates" (the repository admin role, you the only admin, or an owner-only team as bypass actor, consistent with R-A-14, V3-ID-3; every owner merge then becomes a bypass event, which would inflate the owner-bypass measure) with classic branch protection "Restrict who can push to matching branches" (Team org repositories; specific users; admins can always push), recording how each appears in the audit log (whether a PR merge counts as an "update" is UNVERIFIED); step 1b tests them; if one works it is created in step 5a with the review ruleset and probe (i) shows the agent cannot merge an owner-approved head while your merge succeeds (recording whether it is logged as a bypass); if (i) fails, you remove the step-5a restriction at once and record the OC-2 exception (V3-ID-2); rollback disables the review ruleset and the step-5a restriction; if none works, `allow_auto_merge` stays false (false on 2026-10-23, otherwise an armed auto-merge would merge at approval with no prompt) and the agent's merge of an owner-approved head is your explicit exception to `REVIEW_PROTOCOL.md:22` and the 2026-10-14 boundary, guarded by the D-09 ask rule. **Result (OC-6, 2026-10-29):** step 1b found that candidate B works (step-1b record §3.5), and step 5a creates it on `main` as tested; "Restrict updates" was not tested. Guards: the agent account never approves PRs (runbook), bot approvals on owner-authored PRs are counted monthly, and probes (b), (d) as reworded (OC-7), (e) and (i) are re-run on `main` after step 5a; even with B, a bot approval satisfies the review rule on owner-authored PRs [Inf, untested]. Probe (a) compares the approved PR diff with the merged PR diff (OC-8). After committing CODEOWNERS, `GET /repos/{o}/{r}/codeowners/errors` must be empty (R-A-8). Runbook: you never push to agent branches; a probe covers branch updates ("Update branch" by you makes you the last pusher; an agent update may dismiss the approval) (R-A-15) | P0-10; P1-05; makes the merge part of reference gate G2, and reference gate G1 approvals recorded through an owner-approved PR, more than a norm (S4 §3.8); deploys stay prompted | DECISION-S2-1 (c) (supersedes DECISION-S1-1) | **yes**: GitHub settings, CODEOWNERS approval, probes; reviews the step-1 record | ⚙ GitHub ruleset (new review ruleset, flags; merge restriction: classic protection candidate B, OC-6), CODEOWNERS, REVIEW_PROTOCOL + `CLAUDE.md` runbook (and the OC-2 exception text if needed); committed `.claude/settings.json` deny rules extended to the new token location (P0-10 step 3, tested in `claude-settings.test.js`) |
| **D-13** | Which agent account, where do credentials live, and who may bypass review? | **Account:** (i) a new machine account (write, not admin; token minted from it; one repository; no Workflows); (ii) reuse `dentaledge-bot` (collaborator with write on claude_code only). **Credentials:** (a) owner `gh` login stays, guarded by rules; (b) the laptop holds only the agent account's credential, after every path to the owner's GitHub authority is enumerated and measured; the owner approves in the browser or mobile app outside agent control; no other bot token reachable; (c) as (b), approvals only from a second device. **Bypass actor:** (x) the admin role, owner the only admin; (y) an owner-only team | **(ii), (b), (x)** (owner choice OC-1, 2026-10-23, folding in R-A-1, R-A-2 and R-B-4; approved in principle until the step-1a docs record and step-1b scratch-target tests return, before any production account, token or ruleset step on `main`, R-B-9, V2-ID-1; both returned, 2026-10-27 and 2026-10-29, and the token type is OC-5). GitHub's Terms allow "no more than one free machine account in addition to your free Personal Account", and `dentaledge-bot` already is it, so a new machine account would mean deleting the bot or paying; reuse needs no new account (no paid seat is [Asm]: outside-collaborator billing UNVERIFIED). "The owner of the Account is ultimately responsible for the machine's actions" (ToS §B.3). The owner let `dentaledge-bot-pat` lapse: it is recorded to expire on 2026-10-23, not renewed (`sessions/daily/2026-10-14.md:35-37`), and its refusal was to be proved by the owner in P0-10 step 2 (R-B-4, V2-ID-5; the file held no value to try, so its death is not proved by use and is recorded as an exception, step-2 record §4); so Track A draft-PR delivery is dormant and the earlier "one blast radius" objection does not apply while it stays dormant; restoring delivery is a separate Track A decision needing its own identity (for example a GitHub App); the account stays single-consumer (credential canon rule 1, `canon/2026-08-17-credential-governance-lessons.md:49-52`). **Token (R-A-2):** the bot is an outside/repository collaborator on a public org repository, a documented fine-grained-token gap. Counter-evidence: PR #4's head was pushed into the org repository by the bot as an outside collaborator, `.env.pr.example` and `infra/hermes-agent/README.md:315-318` describe a fine-grained token, and the daily note calls the old token "organisation-scoped". So step 1b tested a fine-grained token first (Contents + Pull requests, one repository, no Workflows). **Result and owner choice OC-5 (2026-10-29):** the fine-grained token could not be minted, because the org was not offered as resource owner, while a classic PAT with `public_repo` only did every operation the agent needs (push, PR create and view, update-branch, approve, merge), and the push of a workflow file was refused (step-1b record §3.2, §3.3); the org's policy does not restrict classic tokens or require their approval (§4 check 1) [Owner-rep]; if that policy changes, the token choice is re-checked (editor's wording, not the owner's). The agent token is therefore a **classic PAT with `public_repo` only, no `workflow` scope, 90-day expiry**. It depends on the repository staying public (owner decision, 2026-10-28); if the repository went private, the token would stop working (fail closed). Scopes "do not grant any additional permission beyond that which the user already has", and `public_repo` "Limits access to public repositories" (read/write to code, commit statuses, repository projects, collaborators and deployment statuses "for public repositories and organizations", and starring) [Docs, scopes for OAuth apps, accessed 2026-10-29]. So the token is bounded by the bot's own permissions everywhere; what is specific to this org repository is that it is the bot's only collaborator grant. Within that bound it acts as the bot on any public GitHub repository (issues, comments, forks, PRs [Inf]) and in the bot's own public repositories, and gains any public repository the bot is later added to; you are responsible for those actions under ToS §B.3 (V2-ID-7). **Owner steps before minting:** prove the expired PAT is refused without printing it ("prove death, never infer it", `credential-governance-lessons.md:136-137`); remove its value from `infra/hermes-agent/.env.pr`; mint; store only where the laptop agent's `gh` uses it (storage mechanism: S5 P0-10 steps 2-3; `gh auth login --with-token` refused a `public_repo` test token in step 2, "missing required scopes 'repo', 'read:org'", so storage needs another mechanism, your choice; step-2 record of 2026-10-30, §3.4). The real token is minted in step 3, at the moment it is stored (owner order choice OC-9, 2026-10-30, S5 amendment log round 8); step 2 measured with a 1-day test token. **Credentials (b):** P0-10 step 3 enumerates every path to your authority and measures it before declaring it out of reach (`credential-governance-lessons.md:115-117,130-132`): `gh` login; git credential helper/keychain; SSH keys registered with GitHub [UNVERIFIED, owner checks]; `GH_TOKEN`/`GITHUB_TOKEN`-style variables; tokens printed into session transcripts (fingerprint-only scan); `infra/hermes-agent/.env.pr`; every agent-driven browser or desktop channel signed in to github.com (Claude in Chrome, the desktop built-in browser pane, desktop computer use). The committed deny rules on `.env.pr` cover Read/Edit, not Bash readers such as the pre-approved `python3 *`. **Measured access (OC-1 measurement):** probe (g) with the agent token, never printed, and no write attempts beyond the two probe pushes (workflow and control); the probe branch is deleted afterwards (V2-ID-2, V4-ID-3): after the step-1b test rulesets and probe branches are deleted, a push touching `.github/workflows/` on a `p0-10-probe/**` branch is refused with GitHub's workflow-scope or Workflows-permission message (recorded), while a control push of a non-workflow file to the same branch succeeds (V3-ID-1); a private org repository where the bot is not a collaborator (`claude-google-ads` or `claude-marketing-team`) returns 404; non-mutating admin-only reads such as `GET /repos/{o}/{r}/hooks` and `GET /repos/{o}/{r}/keys` return 403 or 404 [Docs, confirm in step 1a]; `current_user_can_bypass` on the **review** ruleset is `never` for the agent token while your read of the same ruleset returns `pull_requests_only`, so the probe can fail (on `main-protection` today it is `never` for you too); you read `bypass_actors`; every admin or org-owner account is listed (today only `dentaledgesolutions`); recorded in a dated `docs/evaluations/` record and re-run at every rotation (`canon/2026-08-18-credential-access-levels-are-measured-never-asserted.md:12`; `credential-governance-lessons.md`). (a) leaves only rules that are not a boundary; (c) if (b) cannot be verified; (x) needs no team | P0-10 steps 1a-5a | DECISION-S3-1 | **yes**: dead-token proof, `.env.pr` cleanup, token minting (no org approval needed for classic tokens), credential store, browser and desktop channel settings, access record per rotation | ⚙ GitHub collaborators and rulesets; laptop credential store; committed `.claude/settings.json` deny rules extended to the new token location (P0-10 step 3, tested in `claude-settings.test.js`) |
| **D-14** | How do we rebuild ideas from unlicensed or copyleft sources? | mandatory for no-licence and copyleft sources and replication projects, advisory otherwise; mandatory always; advisory only | **Mandatory for no-licence/copyleft sources and replication projects, advisory otherwise**; stated as "not a legal clean room". The implementer gets our behaviour spec, not the source. For P0-11 the interim instruction is "the implementer works from our spec, not the R05 source", until T2/T3 (P1-14) and the P2-03 procedure exist (R-A-11, R-B-14) | P2-03; also applies to P0-11 (R05 idea), P1-09 (R05) and P1-13 (R10) per S2 OPP-23 and S5 P1-09 | DECISION-S4-4 | — | ⚙ REVIEW_PROTOCOL rule text |

### 7.2 Decide before P1

| D | Question (plain language) | Options | Recommendation, and why | Unblocks | Source | Owner acts | Gov. / canon |
|---|---|---|---|---|---|---|---|
| **D-15** | Make the general static skill scan cover packs and Hermes skills, and make it required? | (a) keep it optional; (b) widen the scope only; (c) widen and require | **(c)**, after triaging new findings into the baseline. Closes the "Hermes and pack skills unscanned" hole for the general scan (injection, secrets, permissions); required checks 4 → 5. Back in §7.2 by owner choice OC-3 (revised 2026-10-23), number unchanged. Breach (d) does not depend on it: agents and pack tools (and every other scope) are already held for the conformance rule by P0-02 through the required "Test suites" job. The general scan does not add `.claude/agents/` (already under the required Security gate, `ci.yml:29-56`) or `packs/*/tools/` (12 declarative tool definitions, audited on demand by `scripts/packs/pack-audit.js`, not in CI); both stay covered for unpinned installs by P0-02's conformance pass (V4-RS-2) | P1-06 (PR-10, B6) | DECISION-S2-6 | **yes**: ruleset edit | ⚙ GitHub ruleset |
| **D-16** | Give delivery reviews a reviewer that cannot edit files? | (a) prompt-only, as today; (b) REVIEW_PROTOCOL names the built-in Plan subagent + tamper tripwire; (c) one project agent `reviewer.md` (Read, Grep, Glob, Bash) + tripwire (`git status --porcelain --ignored` and an eval-run hash list), evaluated by agent-eval | **(c)**, fallback (b). The reviewer role exists, the Superpowers reviewer is a user plugin we cannot edit, and R01's prompt-only UX/UI reviewers skipped a required check in 3 of 4 reviews [Res P2-D5 P6]. Residual: writes outside the repository | P1-07; P1-09 | DECISION-S2-3 | — | ⚙ REVIEW_PROTOCOL |
| **D-17** | Where do acceptance tests written apart from the builder apply? | (a) only reference REIMPLEMENT/BUILD NEW F-IDs; (b) all delivery tasks; (c) consequential paths (`scripts/`, `hooks/`, `skills/*/scripts/`, `infra/hermes-agent/bin/`) plus (a) | **(c), piloted on 5 tasks**, then widen, keep or narrow on false-completion and token data. The only measured quality gain belongs to this layer (with review and repair) | P1-09; S4 Increment 3 | DECISION-S2-4 (S4 §3.6 agrees) | decides after the pilot | ⚙ REVIEW_PROTOCOL procedure |
| **D-18** | Count prompts per session to measure human interventions? | (a) no new event; (b) a count-only per-session prompt count from the existing UserPromptSubmit hook | **(b).** Interventions per task are measured nowhere; counts only, never text | P1-03; P3-04 | DECISION-S5-4 | — | ⚙ telemetry schema + `docs/telemetry-privacy.md` (privacy rule unchanged: counts only) |
| **D-19** | When to retire gstack-pattern-audit? | (a) after S4 Increment 1; (b) after one test of the generic skill on a gstack request; (c) now; (d) keep both | **(b)**, after resolving the uncommitted `evals.json` edits. It is the condition already approved in the 2026-10-22 session note | P1-17 | DECISION-S1-4 = DECISION-S2-5 = DECISION-S4-7 | removes the runtime copy | — |
| **D-20** | Where does "decide REUSE … REJECT for supplied references" live? | (A) an app mode in `reference-repo-pattern-extract` with templates T1-T3, F-IDs in project-idea, a hand-off from project-setup; (B) a new skill; (C) a document only | **A.** No new skill or orchestrator; one read-only analyst agent; measurable by skill-eval and agent-eval | P1-14 (and the F-IDs in P1-08) | DECISION-S4-1 | — | — |
| **D-21** | What rules decide a verdict? | adopt S4 §3.5 (licence first, mandatory criteria, pattern vs text, COMPOSE/BUILD NEW limits, verified functionality, fit, DEFER with a trigger; eight criteria as tagged evidence cells), or a weighted numeric score | **Adopt §3.5 without numeric weights.** The value definition says guidance, not formulas; the rules were applied to 175 rows and verified | P1-14 (T3) | DECISION-S4-2 | — | — |
| **D-22** | Approval gate for reference work, and may we clone references? | Gate: reference gate G1 (S4 §3.8; not the brain-guard gap G1 of D-11) mandatory for every project using references, or only for ADAPT/REUSE of code. Clone posture: (i) a pinned, read-only, hooks-disabled clone in the scratch area, run by the coordinating session, analysts on Read/Grep/Glob; (ii) stay WebFetch-only | **Reference gate G1 mandatory; clone posture (i)**, with S3's amendment that `reference-repo-add`'s "never clone" rule is rescoped to registration; recorded under `CLAUDE.md:76`. WebFetch of single files cannot support per-component licence reading | P1-14 | DECISION-S4-3 (absorbs DECISION-S3-3) | **yes**: G1 approval per project | ⚙ security-posture change: the library is WebFetch-only today (`reference-repo-add/SKILL.md:6,33`) |

### 7.3 Later

| D | Question (plain language) | Options | Recommendation, and why | Unblocks | Source | Owner acts | Gov. / canon |
|---|---|---|---|---|---|---|---|
| **D-23** | Should scout scoring filter by licence and stop rewarding stars? | (a) keep; (b) licence class as a hard filter on "installable code" + capped star weight; (c) remove stars | **(b)**, then re-eval skill-scout. Stars are not a trustworthy signal [Res P2-D4 §5.1; R07 §16] | P2-02 | DECISION-S2-7 | — | — |
| **D-24** | How deep is verification of a reference analysis? | one verifier, licence and security/correctness rows first, plus a sample; or the campaign's three layers | **One verifier, risk rows first, plus a sample**; a second pass only on material errors | P2-04 | DECISION-S4-8 | — | — |
| **D-25** | Register the 11 researched repositories in the library? | all 11 now; only those an approved item uses, after the licence fields exist; none | **Only those used, after P2-01** | P2-10 | DECISION-S4-5 | — | — |
| **D-26** | The charter's body still says "Status: candidate" although it is canon (`charter.md:3` vs `:14` [Ver]) | (a) leave it until your charter decision; (b) correct the status line now through the promotion path, content unchanged | **(a)**, unless you prefer (b); any edit is a canon write | none (excluded from P2-09) | DECISION-S2-9 | (b) only | 📜 |
| **D-27** | Ask Codex for an advisory second-model review of consequential delivery PRs? | (a) no; (b) on demand, human-triggered, read-only, advisory, 5 PRs after the acceptance pilot; (c) as a gate | **(b), conditional on P1-09 data.** (c) is excluded by the `CLAUDE.md` Codex rules | P3-03 | DECISION-S5-3 | triggers each run | `CLAUDE.md` Codex rules unchanged |
| **D-28** | Become a factory that builds any kind of app? | A / B / C, as in §5 (S6's framing; S5 §1.5 lists no options) | **No recommendation is made for you.** The option closest to S1–S5 is **C**: measure first (DECISION-S2-8), then decide on the B0 baseline and the P3-04 trial. Counting the first real reference project as evidence is S6's framing [Inf]. Whichever option, D-28 should also weigh the commercial objective in canon (`canon/2026-07-23-hermes-memory-corrections-d1-d5.md`, D-5: "Future decisions should be judged against both the technical north-star and this commercial objective") (R-B-18) | P3-04 approval; the OPP-37 trigger (S2 §4.2 D-3) | S5 §1.5 ("the owner's app-scope decision"); S3 §3.2; S2 OPP-37; P2-D5 Q1 | **yes** | 📜 charter |

**Existing owner items that are not new decisions** (listed so nothing is lost):
- Hermes API key rotation (S1 §3.1; P1-16).
- The `dentaledge-bot` PAT: decided on 2026-10-14, left to expire on 2026-10-23 and not renewed
  (`sessions/daily/2026-10-14.md:35-37`); Hermes draft-PR delivery is dormant. New owner steps (P0-10, OC-1): prove
  the expired token is refused without printing it, remove its value from `infra/hermes-agent/.env.pr`, then mint the
  agent token (§6 item 1). Restoring Hermes delivery is a separate Track A decision with its own identity.
- Revisiting GSD decision D3, now that HR1 A-C are done (OPP-35, DEFER).
- P8 stays open (OPP-41, DEFER).
- The S11 scanner limit stays accepted (decision 2026-10-21).
- The weekly brain review (P2-09).

---

## 8. Traceability

| D | Source decisions | Roadmap items (S5) | OPP (S2) | Gaps (S1) |
|---|---|---|---|---|
| D-01 | DECISION-S5-1 | P0-01 … P0-11; B0-B5 | — | GAP-01, -02, -03, -04, -05, -07, -11 |
| D-02 | DECISION-S2-8 | B0, P1-01, P1-02, P1-04; OPP-28 deferred | OPP-25, -26, -27, -28 | GAP-09, -15 |
| D-03 | DECISION-S5-2 | B0, P1-10 | OPP-16 | GAP-10 |
| D-04 | DECISION-S3-4 | P1-01; S5 §3 | OPP-25 | GAP-09 |
| D-05 | DECISION-S4-6 | P0-01, P0-03, P2-05 | OPP-01, -02(a), -03, -31 | GAP-01, -02, -14 |
| D-06 | DECISION-S1-3 | P0-04 (→ P0-05) | OPP-30 | GAP-01, -14 |
| D-07 | DECISION-S3-5 | P0-04 | OPP-30 | GAP-23 |
| D-08 | DECISION-S3-2 | P0-05, P2-02, P2-06 | OPP-02(b) | GAP-01 |
| D-09 | DECISION-S2-1 (b); DECISION-S1-1 (superseded) | P0-07 | OPP-07 | GAP-03, -04 |
| D-10 | DECISION-S1-5 | P0-08, P1-12 | OPP-09 | GAP-04, -11 |
| D-11 | DECISION-S1-2 = DECISION-S2-2 | P0-09, P1-13 | OPP-06, -15 | GAP-07, -04 |
| D-12 | DECISION-S2-1 (c); DECISION-S1-1 (superseded) | P0-10, P1-05 | OPP-08, -13 | GAP-03, -05 |
| D-13 | DECISION-S3-1; DECISION-S1-1 (superseded) | P0-10 | OPP-08 | GAP-03 |
| D-14 | DECISION-S4-4 | P2-03 (and P0-11, P1-09, P1-13 by S2 OPP-23) | OPP-23 | GAP-12 |
| D-15 | DECISION-S2-6 | P1-06 (B6; back in P1 by OC-3, revised) | OPP-05 | GAP-16, -10 |
| D-16 | DECISION-S2-3 | P1-07 | OPP-10 | GAP-08 |
| D-17 | DECISION-S2-4 | P1-09 | OPP-11 | GAP-06 |
| D-18 | DECISION-S5-4 | P1-03 | (extends OPP-26) | GAP-09 |
| D-19 | DECISION-S1-4 = DECISION-S2-5 = DECISION-S4-7 | P1-17 | OPP-29 | GAP-14 |
| D-20 | DECISION-S4-1 | P1-14, P1-08 | OPP-19 | GAP-12, -13 |
| D-21 | DECISION-S4-2 | P1-14 | OPP-19 | GAP-12 |
| D-22 | DECISION-S4-3 (absorbs DECISION-S3-3) | P1-14 | OPP-19, -02(c) | GAP-12, -13, -01 |
| D-23 | DECISION-S2-7 | P2-02 | OPP-21 | GAP-12 |
| D-24 | DECISION-S4-8 | P2-04 | OPP-24 | GAP-12, -15 |
| D-25 | DECISION-S4-5 | P2-10 | (S2 §4.2 D-10) | GAP-13 |
| D-26 | DECISION-S2-9 | (excluded from P2-09) | OPP-34 (excluded) | GAP-23 |
| D-27 | DECISION-S5-3 | P3-03 | — | GAP-08 |
| D-28 | S5 §1.5 app-scope decision (no number) | P3-04; OPP-37 trigger | OPP-37 | GAP-19 |

**Coverage check.** Every decision ID in S1–S5 maps to a D-nn:
- **S1:** S1-1 → D-09/D-12/D-13; S1-2 → D-11; S1-3 → D-06; S1-4 → D-19; S1-5 → D-10.
- **S2:** S2-1 → D-09/D-12; S2-2 → D-11; S2-3 → D-16; S2-4 → D-17; S2-5 → D-19; S2-6 → D-15; S2-7 → D-23;
  S2-8 → D-02; S2-9 → D-26.
- **S3:** S3-1 → D-13; S3-2 → D-08; S3-3 → D-22; S3-4 → D-04; S3-5 → D-07.
- **S4:** S4-1 → D-20; S4-2 → D-21; S4-3 → D-22; S4-4 → D-14; S4-5 → D-25; S4-6 → D-05; S4-7 → D-19; S4-8 → D-24.
- **S5:** S5-1 → D-01; S5-2 → D-03; S5-3 → D-27; S5-4 → D-18.

That is 31 numbered source IDs onto D-01 … D-27. D-28 is the unnumbered app-scope decision from S5 §1.5.

---

## 9. Consistency notes

Recorded, not fixed. None changes a recommendation. (The round 2 owner choices of 2026-10-23 did change D-13's
recommendation and moved D-15, which OC-3 (revised) moved back; they are recorded in §7, and the notes below say where they resolve a note.)

- **CN-1. Agent identity wording (resolved during this work).** When first read, S3 and S5 Limits said S2's OPP-08
  part (1) "still reads 'bot or fine-grained token'", and S1's DECISION-S1-1 option (b) used the same phrase. The
  closure corrections of 21:02 aligned all of them: V-S2-19, V-S3-14, V-S5-16 and the coordinator note in S1. S1–S5
  now agree on a separate machine account with a token minted from it. Round 2: that account is the existing
  `dentaledge-bot` (OC-1), and the token is fine-grained if step 1b shows it works, otherwise a classic PAT. Round 7:
  step 1b could not mint a fine-grained token, and the token is a classic PAT with `public_repo` only (OC-5).
  S2 OPP-08 and S3 §2.2 / DECISION-S3-1 still state the pre-OC-5 token type and the old probe (d) premise; S6 §7
  OC-5 … OC-8 take precedence; alignment in a follow-up.
- **CN-2. Hermes tool restriction (resolved during this work).** When first read, S1 described the proposer and the
  audit jobs as "tool-restricted plan-mode" agents, and claimed no researched default branch had a tool-enforced
  read-only agent. This appeared in ST-7 (including its closing sentence), L11 (the Ads audit jobs), §6 item 5,
  GAP-08 and the least-privilege rating row. Per S4 §3.7 and S3 §1.4 (docs), `--allowedTools` removes no tool, and
  containment rests on missing credentials, mounts, egress and the gateway (§6 item 2). The coordinator has since
  corrected all of these S1 lines, as recorded in S1's corrections list.
- **CN-3. Count of known breach (d) cases.** S2 §0 says OPP-03 closes (d) "for the two known cases" (repomix,
  gitingest). S3 §3.1 and S5 P0-01 add a third, the unpinned `npx ecc-agentshield scan --fix` advice at
  `project-audit/SKILL.md:180`, and set the baseline as "at least 3; measure first".
- **CN-4. Decision timing for B0.** S5 §1.5 lists DECISION-S2-8, DECISION-S3-4 and DECISION-S5-2 under P1. Yet S5
  §2.2 runs B0, which they govern, before the first P0 PR. This register places them in "decide now" (D-02 … D-04).
  Resolved in round 2: S5 §1.5 now lists them under B0/P0 (R-A-13).
- **CN-5. Context separation is needed earlier than S5 §1.5 says.** S5 §1.5 lists DECISION-S4-4 under P2. But S5
  P1-09 traces to it, and S2 OPP-23 applies it to OPP-14 (P0-11) and OPP-15 (P1-13). This register places it in
  "decide now" (D-14). Round 2: S5 §1.5 now also lists it under B0/P0 as it applies to P0-11, and P0-11 carries the
  interim instruction (R-A-11, R-B-14).
- **CN-6. Reviewer tripwire wording.** S5 P1-07 "Changes" records `git status --porcelain`. Its acceptance line, S2
  OPP-10 and S3 §2.4 use `git status --porcelain --ignored` plus an eval-run hash list.
- **CN-7. Ask-rule list.** S3 §1.3's P0-07 row lists fewer ask rules than S5 P0-07: it omits `gh pr review`,
  `gh api` and `gh auth`. S5 P0-07 is a superset of S2 OPP-07 and S3 §2.2, since it also adds `Bash(gh auth *)`
  (`S5:218` after the round 7 edits; `S5:214` after the round 2-6 edits; `S5:175` when first checked). D-09 follows S5.
- **CN-8. Two different credentials in one line.** S5 §2.3 item 5 pairs "Rotate the Hermes key" with the
  `dentaledge-bot` PAT expiry. The key is an Anthropic API key from the laptop's local Hermes stack (HR1); the PAT is
  the GitHub bot token for Track A delivery. Resolved in round 2: S5 §2.3 now lists them as separate items.
- **CN-9. The app-scope trial has no success criterion.** P3-04 is meant to come "before any orchestration or
  app-scope change", yet its approval line is "owner's app-scope decision". No deliverable defines what trial
  result would justify a general scope; P2-D5 Q1 asked "what evidence would be enough". This register reads
  approving the trial as the first step of option C (§5) and leaves the success criterion to the owner.
- **CN-10. Track A delivery path at PAT expiry (resolved in round 2).** When first read, no S1–S5 item decided what
  happens to the delivery path when the `dentaledge-bot` PAT expires (2026-10-23). The decision already existed: on
  2026-10-14 the owner let the PAT expire, not renewed (`sessions/daily/2026-10-14.md:35-37`). Delivery is dormant
  from 2026-10-23, the bot becomes the laptop agent's account (OC-1), and restoring delivery is a separate Track A
  decision with its own identity. S3, S5 and §6 item 1 now say so.
- **CN-11. Fourth breach form.** S2 and S5 speak of "three" mandatory breaches, (b), (c) and (d). S1 §4.2 and
  S3 §3.1 also record (a) as "not met as operated". S5 §0 acknowledges that (a) stays open. §1 reports all four.
- **CN-12. Formatting.** S2 §5 repeats its table header once (`S2:386-391` after the round 2 edits; `S2:383-387` when first checked). Not material.
- **CN-13. Tracked files under `evals/`.** `CLAUDE.md:83` says never to commit anything under `evals/` ("it is
  gitignored"). Yet 41 files there are tracked [Ver `git ls-files evals`]:
  - 39 per-skill and per-agent `evals.json` scenario files;
  - `evals/.gitignore`;
  - `evals/project-context.json`.

  Two items touch them:
  - P0-04 (as corrected by V-S5-16) deletes `evals/agents/skill-guardian/` and edits `evals/.gitignore:20`;
  - P1-17 must first resolve the modified `evals/<skill>/evals.json` files.
  The plan does not say how these tracked edits square with the `CLAUDE.md` rule. This is a pre-existing
  repository fact; S6 does not resolve it. Round 2 (R-B-10): D-06 and S5 P0-04 now propose amending `CLAUDE.md:83`
  to "never commit generated eval artifacts; scenario specs (`evals/**/evals.json`) and `evals/.gitignore` are
  tracked", approved by the owner as part of P0-04. Round 3 (V2-RS-4): `evals/project-context.json` is also tracked
  (last commit 612c585, 2026-07-07) and generated; the amendment either names it ("tracked as the toolkit's own
  context snapshot", recommended) or P0-04 untracks it. The note is resolved once `project-context.json` is covered.

---

## Limits

- **Nothing was executed.** This report synthesizes S1–S5 and the phase 1/2 indexes. Its own checks are the
  read-only items in §0. Every other fact is cited as S1–S5 report it after their verification corrections.
- **[Docs] facts are second-hand here.** They are the GitHub, Claude Code permissions, hooks, sub-agents and CLI
  statements as S2 and S4 read them on 2026-10-22. These points stay [Asm] or [Unk] until P0-10's docs check and test
  PR: GitHub token semantics (including whether a fine-grained token works for an outside/repository collaborator),
  the two-ruleset bypass interaction, bypass-actor eligibility (the REST `bypass_actors.actor_type` enum includes
  `User` and `DeployKey`, while the rulesets UI doc lists roles, teams and apps, so "users cannot be bypass actors" is
  UNVERIFIED; recommendation (x) is unaffected, R-A-14), whether merging into `main` can be restricted to the owner
  (OC-2), `gh` multi-account behaviour, and the browser and desktop channels signed in to github.com. The step-1a
  (2026-10-27) and step-1b (2026-10-29) records have since returned; the token type and the merge restriction are
  settled by OC-5 and OC-6, as measured on a probe branch, not on `main`. Whether the
  Hermes executor skips project settings is UNVERIFIED (P0-07, P0-09).
- **Round 7 source** [Docs] (fetched by the round-7 reviewer, accessed 2026-10-29): GitHub "Scopes for OAuth apps",
  https://docs.github.com/en/apps/oauth-apps/building-oauth-apps/scopes-for-oauth-apps: verified that `public_repo` "Limits access to public repositories" and
  covers read/write to code, commit statuses, repository projects, collaborators and deployment statuses "for public
  repositories and organizations", that it is also required for starring, and that scopes "do not grant any
  additional permission beyond that which the user already has" (D-13 token, OC-5).
- **Round 2 sources** (read by the coordinator on 2026-10-23; cited here second-hand):
  - GitHub Terms of Service §B.3, https://docs.github.com/en/site-policy/github-terms/github-terms-of-service
    (accessed 2026-10-23): verified "no more than one free machine account in addition to your free Personal
    Account" and "the owner of the Account is ultimately responsible for the machine's actions" (D-13, OC-1).
  - Managing personal access tokens,
    https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/managing-your-personal-access-tokens
    (accessed 2026-10-23): verified the fine-grained token gaps for public repositories where the user is not a
    member and for outside or repository collaborators; "Outside collaborators can only use personal access tokens
    (classic) to access organization repositories that they are a collaborator on"; an org requiring approval leaves
    a fine-grained token `pending` until an administrator reviews it (D-13 token type). Counter-evidence:
    `dentaledge-bot` opened PR #4 on 2026-07-25 and `infra/hermes-agent/README.md:315-318` records a fine-grained
    PAT; whether that still works is UNVERIFIED.
  - Claude Code settings, https://code.claude.com/docs/en/settings (accessed 2026-10-23): verified that shared
    `.claude/settings.json` is read from the session's primary working directory and that `.claude/settings.local.json`
    in a git repository is read and written at the repository root, even when started in a subdirectory (D-11, RK-15).
  - Also re-checked by the coordinator on 2026-10-23 [Ver]: `dentaledge-bot` is a User account created 2026-07-25,
    collaborator with write; `dentaledgesolutions` is the only admin; the org has 1 of 1 seats filled; the ruleset
    `main-protection` has no bypass actors, `required_approving_review_count: 0`, 4 required checks and strict status
    checks, and "Static scan all skills" (`ci.yml:125-133`) is not required.
- **Machine-local facts** (local allow list, `gh` login, Claude in Chrome) describe the owner's laptop on 2026-10-22.
- **Expected benefits are estimates.** Several have no baseline yet ("measure first"). Token and dollar costs of the
  re-baseline and the pilot are [Unk].
- **The register order is derived** from S5's batch order and dependencies (with CN-4 and CN-5 applied; D-15 was
  moved into §7.1 by the round-2 OC-3 and back to §7.2 by its revision). It is a
  sequencing aid, not a priority ranking of the decisions' importance.
- **S3 and S5 were under a last closure check.** Both were re-read at the end of this work. Inputs changed while this
  report was being written, and each change was re-read:
  - S2 at 20:58 (V-S2-19);
  - S1, S3 and S5 at 21:02 (the S1 coordinator note on DECISION-S1-1, V-S3-14, V-S5-16);
  - S1 from 21:09 onwards: the coordinator's Hermes-wording corrections to ST-7, L11, §6 item 5, GAP-08 and the
    least-privilege rating row (S1 corrections list). With them, the coordinator updated S6 §6 item 2 (V-S6-2).

  The changes align the agent-identity wording (CN-1) and the Hermes tool-restriction wording (CN-2). They also add
  the deletion of `evals/agents/skill-guardian/` to P0-04 (CN-13). No decision, option or recommendation changed.
- **Licence statements** are technical readings, not legal advice. Context separation (D-14) is not a legal clean
  room.

## Decisions requiring approval (from this deliverable)

S6 introduces **no new decision**. It consolidates every decision from S1–S5 into the register in §7: **D-01 … D-28**.
- **Decide now, to start P0:** D-01 … D-14.
- **Decide before P1:** D-15 … D-22 (D-15 returned here by owner choice OC-3, revised; its number is unchanged).
- **Later:** D-23 … D-28.
- **Owner choices already made (2026-10-23):** OC-1 (D-13), OC-2 (D-12), OC-3 (D-15 and P0-02; revised the same day), OC-4 (D-11); (2026-10-29): OC-5 (D-13), OC-6, OC-7, OC-8 (D-12); recorded in §7.

§8 maps each entry to its source decisions and roadmap items. Not reopened: the 2026-10-14 rejections (no second
factory subsystem, no autonomous merge path), Track A, D3.2 and the AI OS charter. Any change to them is a separate
owner decision; for the charter, that decision is D-28.

## Verification corrections (2026-10-22)

Each finding was confirmed against the cited source before it was applied. All fourteen were accepted; none is
disputed.

- **V-S6-1** (confirmed against S1's corrections list, lines 820-821). CN-2 is marked resolved and names the
  corrected S1 lines: ST-7 including its closing sentence, L11, §6 item 5, GAP-08 and the least-privilege rating row.
- **V-S6-2.** §6 item 2's "Consequence" bullet now names the same corrected S1 lines and points to CN-2 as resolved.
  The coordinator had already updated this item; the wording is now aligned with CN-2.
- **V-S6-3.** The Limits bullet on input changes adds the S1 Hermes-wording edits from 21:09 onwards and the S6 §6
  item 2 update.
- **V-S6-4** (confirmed: S5 P2-06 acceptance, `S5:523`; S3 §2.3). §1 (b) now says P2-06 is the planned follow-up that
  narrows the breach further, and that synthesizer and adapt stay an accepted residual. This matches §3.2.
- **V-S6-5** (confirmed: S1 §4.2 C2). §1 now says nothing written independently of the builder checks the work, and
  false completions are not measured.
- **V-S6-6** (confirmed: P2-D5 `:71-72`, `:82-83`).
  - §1 research item 1 adds "on hand-picked hard cases, against no-review baselines".
  - Item 2 attributes the "3 of 4" figure to R01's UX/UI reviewers.
  - The same attribution is applied to the §4 reviewer row and to D-16.
- **V-S6-7** (confirmed: S5 §1.5 lists no options; value-definition source `:100-102`; 2026-10-14 evaluation `:34`).
  - §5 labels the D-28 options as S6's framing and cites a source for each.
  - The P1-14-as-evidence step is tagged [Inf].
  - Option C is renamed "closest to phase 3's measure-first line".
  - D-28 and §0 are adjusted to match.
- **V-S6-8** (confirmed: P3-01's entry condition is the P1-01 baseline, `S5:535`). "P3-01 baseline" is dropped from
  D-16.
- **V-S6-9.** The coverage line now reads "31 numbered source IDs onto D-01 … D-27; D-28 unnumbered". The §8 row for
  D-13 adds DECISION-S1-1 (superseded).
- **V-S6-10** (confirmed: `git ls-files evals`). CN-13 now counts 39 `evals.json` files, `evals/.gitignore` and
  `evals/project-context.json`.
- **V-S6-11** (confirmed: `S5:175`). CN-7 now says S5 P0-07 is a superset of S2 and S3, since it adds `gh auth *`,
  and that D-09 follows S5.
- **V-S6-12.**
  - §1 now points to §6's six items and singles out two: one deadline, and one correction with no deadline.
  - The PAT is described as "recorded as expiring 2026-10-23" (the operator's set expiry; current state unchecked).
    This wording is applied in §1, §3.3, §4, §6 item 1, D-13 and CN-10.
- **V-S6-13** (confirmed: `S5:227`). RK-6 now reads "resolved, or quarantined with a recorded reason".
- **V-S6-14.**
  - §2.2's lead-in now separates "not covered by any item" (delivery-lane recovery) from "covered only late" (reuse
    effectiveness, S4 M5).
  - §1 (d) now calls the CI check a pattern check for the known unpinned forms, and states the `npx`
    no-lockfile residual.
- V-S6-15 (coordinator): CN-13 list structure fixed ("Two items touch them:" on its own line).

### Round 2 (2026-10-23)

Applied by the editor from the corrections specification (two independent reviews of D-01 … D-14 and four owner
choices). These round 2-6 edits were verified and closed on 2026-10-23 by two independent verifiers (identity and credentials; everything else); see the index verification record.

- **OC-1** (D-13 account): §7 "Owner choices, 2026-10-23" added; D-13 recommendation is now (ii), (b), (x) with the ToS §B.3 rationale, the 2026-10-14 non-renewal decision, dormant delivery, single-consumer account, token type (classic PAT default; superseded by OC-5, round 7), owner steps and credential paths; §1 (c) and the decide list, §2.2 security row, §3.1 RK-1, RK-3, RK-4, RK-5, §3.2 (dormant-delivery row; `/proc` row conditional), §3.3, §4 (the "reuse" row replaced by "a new machine account" as the losing alternative), §6 item 1 (rewritten: recorded decision, dormant delivery, owner steps; no longer an open decision), §7 "Existing owner items" (PAT line replaced), §9 CN-1 and CN-10 (resolved).
- **OC-1 measurement** (R-B-2, R-A-16): D-13 cites probe (g) and both credential canon entries; RK-4 adds re-measurement at every rotation.
- **OC-1 credential paths** (R-B-3, R-A-9, R-A-10): D-13 (b) and RK-5 enumerate every path (including the desktop built-in browser pane and computer use) and note the Read/Edit-only reach of the `.env.pr` deny rules.
- **OC-2** (D-12; R-B-8): D-12 states the merge-restriction check and the owner-accepted exception; §1 (c), §2.1 (c), §3.2 approved-head row and §4 "autonomous merge path" row (formerly implying D-12 removes the agent's merge path) are qualified.
- **OC-3** (D-15 into P0; R-A-4): the D-15 row moved from §7.2 to §7.1 with its number unchanged; "decide now" is D-01 … D-15 and "before P1" D-16 … D-22 in §1 and "Decisions requiring approval"; D-01 names D-15; §1 (d), §2.1 (d), RK-2 and §8 (D-01, D-15 rows) updated.
- **OC-4** (D-11; R-B-5, R-B-6, R-B-7, R-A-3, R-A-7, R-B-16): D-11 states the supersession of P11 and the F1 non-adoption and its recording through `brain-promote`, the brain-weekly-review conflict, Hermes runs, subdirectory coverage, owner removal of the old local registration, install/uninstall sync, the regex rule and fail-open telemetry hooks; governance column adds `infra/hermes-agent/.claude/settings.json`; new RK-14 (Hermes) and RK-15 (subdirectory coverage); §3.2 settings-load row rewritten from the settings docs.
- **R-B-1**: D-03 and §6 item 6 add the stop at `refine-input.json` until P0-08 and P0-11 merge and P1-12 starts.
- **R-B-17**: D-03 adds the D3 "--debug" recheck in B0.
- **R-B-12, R-A-5**: D-01 names all four breach forms and their residuals as accepted exceptions, each with a revisit trigger; its ⚙ column is now D-09 … D-15.
- **R-B-13**: D-09 and the §2.2 autonomy row say the intervention measures are expected to rise and read-only `gh api` calls prompt.
- **R-A-6**: D-01, D-05, D-06, D-08 name the owner deploy plus `check-skill-deploy.js`; D-10 reads "every deploy, from B1"; RK-7 says "from B1".
- **R-B-11**: D-09 adds the `install.sh`/`uninstall.sh` ask rule; D-10 covers all of `CLAUDE.md:75`, "owner deploys", `skill-refine/SKILL.md:33` and `install.sh:172-205`; its ⚙ column gains `install.sh`.
- **R-B-10, R-A-12**: D-04 reads "generated eval artifacts are never committed"; D-06 carries the `CLAUDE.md:83` amendment note; CN-13 points to it.
- **R-B-15, R-A-17**: D-06 cross-references D-07 📜, `install.sh:202` and the evals change; D-12 and D-13 add the deny-rule extension to the new token location; D-07 adds the note on unapplied charter corrections (offered, not recommended over (a)).
- **R-B-9**: D-12 and D-13 are "approved in principle", with the step-1 record returning to the owner and fallbacks (`CLAUDE.md:76`).
- **R-A-8**: D-12 adds `required_approving_review_count: 1` and the `codeowners/errors` check.
- **R-A-14**: Limits marks user bypass-actor eligibility as UNVERIFIED.
- **R-A-15**: D-12 adds the branch-update probe and the "owner never pushes to agent branches" runbook line.
- **R-A-11, R-B-14**: D-14 adds the P0-11 interim instruction; D-14 stays in §7.1; CN-5 notes S5 §1.5.
- **R-A-13**: CN-4 marked resolved (S5 §1.5 fixed).
- **R-A-18**: §2.1 C1 row, RK-7, D-11, D-12 and D-22 now say "brain-guard gap G1" or "reference gate G1/G2".
- **R-A-19**: D-01 and §1 "Order" say P0 is declared done after the P1-10 runs (B6).
- **R-B-18**: D-28 adds the commercial objective from canon (memory-corrections D-5).
- **CN-8**: marked resolved (S5 §2.3 now separates the key and the PAT).
- **Sources**: Limits adds the three docs sources read on 2026-10-23 (GitHub ToS §B.3, "Managing personal access tokens", Claude Code settings) with access date and what each verified, plus the coordinator's `gh api` re-checks; §0 numbering note adds OC-n and R-A-n/R-B-n.

### Round 3 (2026-10-23)

Applied by the editor from the round 3 specification (two verifiers of the round 2 edits). These round 2-6 edits were verified and closed on 2026-10-23 by two independent verifiers (identity and credentials; everything else); see the index verification record.

- **OC-3 note**: the "Owner choices" OC-3 bullet records that the coordinator's premise was narrower than first stated (V2-RS-1) and that the owner will be asked to confirm OC-3 with the corrected facts; D-15 stays in §7.1.
- **V2-RS-1**: §1 (d), §2.1 (d), the OC-3 bullet, D-01 (d) and D-15 now say that for `skills/` (all known cases) a BLOCK-severity rule in `static-scan.js` is already held by the required "Test suites" job through `scripts/ci-scan-skills.test.js:104-110`, and for `.claude/agents/`, `packs/`, `infra/hermes-agent/skills/` only once "Static scan all skills" is required (D-15) or that test is extended.
- **V2-RS-2**: D-12's Unblocks now reads "makes the merge part of reference gate G2, and reference gate G1 approvals recorded through an owner-approved PR, more than a norm; deploys stay prompted".
- **V2-RS-3**: RK-15, the §3.2 subdirectory row and D-11 condition (3) now say the move "may drop coverage, or coverage may already be absent today" (the current registration already uses `$CLAUDE_PROJECT_DIR/hooks/brain/brain-security-guard.sh`, `.claude/settings.local.json:110`; its resolution in a subdirectory session is UNVERIFIED), and P0-09 acceptance records what `$CLAUDE_PROJECT_DIR` resolves to in `infra/hermes-agent/`.
- **V2-RS-4**: D-04 lists the 41 tracked files (39 scenario specs, `evals/.gitignore`, `evals/project-context.json`); D-06 presents both options for `project-context.json` (name it in the `CLAUDE.md:83` amendment, recommended, or untrack it); CN-13 is resolved once it is covered.
- **V2-RS-5**: D-01 revisit triggers rewritten for (b) synthesizer/adapt, (c) skill deploys and local actions, and (d).
- **V2-RS-6**: D-01's governance column is "approves the ⚙ changes in D-06 and D-09 … D-15".
- **V2-RS-7**: D-01's owner-acts column names the 9 skills P0-06 deploys and the two project-scoped definitions that need no deploy, instead of "~11 skills".
- **V2-RS-8**: D-01's owner-acts column adds the P0-02 skill-audit deploy.
- **V2-RS-10**: CN-7 now cites `S5:205` and CN-12 `S2:386-391` (old line numbers kept for reference).
- **V2-RS-11**: the §3.2 subdirectory row cites the docs for the local file in a worktree ("In a worktree, it uses the file at the main checkout's root") and leaves only the shared-file case for the P0-09 test; the column key's 📜 now covers superseding an active decision; D-01 includes P0-03 in "P0 done after B6".
- **V2-ID-1**: D-12 and D-13 describe P0-10 step 1 as 1a (docs check, the R-B-9 gate) and 1b (owner-run tests on a `p0-10-probe/**` branch pattern with a short-lived, revoked test token), both returned before any production account, token or ruleset step on `main`; D-13's Unblocks is "P0-10 steps 1a-5a"; §3.2, §4 and the OC-1/OC-2 bullets refer to steps 1a/1b.
- **V2-ID-2**: D-13's probe (g) now uses `current_user_can_bypass` on the review ruleset (agent `never`, owner `pull_requests_only`), non-mutating admin-only reads (`hooks`, `keys`) and a named private org repository (`claude-google-ads` or `claude-marketing-team`), with no write attempts beyond the probe push.
- **V2-ID-3**: D-12, §3.2, §4 and the OC-2 bullet now compare the two merge-restriction candidates (ruleset "Restrict updates" vs classic "Restrict who can push"), add step 5a and probe (i), and state that `allow_auto_merge` stays false.
- **V2-ID-5**: the §4 "new machine account" row says the PAT is recorded to expire 2026-10-23 (refusal to be proved by the owner), tags "no paid seat" as [Asm], and adds the restoration trade-off; D-13's "no seat" is tagged [Asm] too.
- **V2-ID-6**: the §2.2 security row's measure and baseline and RK-12 are qualified as applying only if delivery is restored.
- **V2-ID-7**: D-13 states the classic `repo` token's reach beyond org repositories (public repositories, the bot's namespace, future repositories) and the ToS §B.3 responsibility, cites the counter-evidence, and tests a fine-grained token first; RK-4 and CN-1 updated to match (token type superseded by OC-5, round 7).
- **V2-ID-9**: RK-3 says CI changes travel as owner-authored PRs made outside agent sessions and merged through the PR-only bypass, which skips review; the owner never pushes to agent branches.
- **R-A-1, R-A-2, R-B-4** (folded into OC-1 in round 2): §6 item 1's heading and D-13's recommendation now name them, so they can be traced.
- **Coordinator edit (round 3):** the OC-1 bullet in §7 now states the owner's choice as "a new token without workflow rights" and the token-type order as fine-grained first (if step 1b shows it works), otherwise classic `repo` without `workflow`, matching S3, S5 and D-13. The earlier "classic by default" wording was the coordinator's, not the owner's. (Token type superseded by OC-5, round 7.)

### Round 4 (2026-10-23)

Applied by the editor from the round 4 specification (round 3 verification and one owner re-decision). These round 2-6
edits were verified and closed on 2026-10-23 by two independent verifiers; see the index verification record.

- **OC-3 (revised by the owner, 2026-10-23)**: the "Owner choices" OC-3 bullet is replaced by the revised choice (P0-02 holds breach (d) for every scope through the required "Test suites" job; D-15 returns to §7.2 and covers only the general scan of packs and Hermes skills; the earlier OC-3 is superseded), and the "will be asked to confirm" note is removed. The D-15 row moved back to §7.2 (number unchanged), reworded to the general scan without the breach-(d) rationale. Ranges are D-01 … D-14 / D-15 … D-22 / D-23 … D-28 in §1 and "Decisions requiring approval". Breach (d) wording in §1, §2.1 and D-01 (d) reads "held for `skills/`, `.claude/agents/`, `packs/` and `infra/hermes-agent/skills/` by the required 'Test suites' job through `ci-scan-skills.test.js` from P0-02 (B1); no ruleset change needed". D-01 options drop P1-06, its governance column is "D-06 and D-09 … D-14", and its owner-acts column adds "no ruleset edit for (d)". RK-2, §1 "Order", §8 (D-01, D-15; GAP-02 stays on D-01), the Limits note and the §9 header are updated.
- **V3-ID-1**: RK-3 and D-13 probe (g) add the control push, the recorded refusal message and the deletion of step-1b test rulesets and probe branches first; D-12's step 1b adds the deletion.
- **V3-ID-2**: D-12's step 1b states the mirrored layering and the commit-status emulation (`ci.yml:3-7`); a failed probe (i) means immediate removal of the step-5a restriction and the OC-2 exception; rollback disables the review ruleset and the restriction.
- **V3-ID-3**: D-12's "Restrict updates" candidate uses the repository admin role or an owner-only team as bypass actor.
- **V3-ID-4**: D-12's step 1b test token is minted and used outside agent sessions and never printed into a transcript.
- **V3-RS-2**: the Round 2 and Round 3 headers above now say "These round 2, round 3 and round 4 edits are not yet verified by an independent reviewer."
- **CN-7 line**: CN-7 now cites `S5:206` (the `Bash(gh auth *)` line moved after the round 4 S5 edits).

### Round 5 (2026-10-23)

- **V4-RS-1**: the OC-3 (revised) bullet now says P0-02 adds a conformance-only pass in `scripts/ci-scan-skills.js` over `.claude/agents/*.md`, `packs/*/skills/`, `packs/*/tools/` and `infra/hermes-agent/skills/`, and the general scan scope is unchanged until P1-06.
- **V4-RS-2**: D-15 adds the short form: the general scan does not add `.claude/agents/` (required Security gate, `ci.yml:29-56`) or `packs/*/tools/` (audited on demand by `scripts/packs/pack-audit.js`); both stay covered for unpinned installs by P0-02's conformance pass.
- **V4-ID-3**: D-13's probe (g) says there are no write attempts beyond the two probe pushes (workflow and control), and the probe branch is deleted afterwards.
- **CN-7 line**: CN-7 now cites `S5:208` (the `Bash(gh auth *)` line moved after the round 5 S5 edits).

### Round 6 (2026-10-23, coordinator edits)

- **V6-RS-1**: CN-7 now cites `S5:214` (the `Bash(gh auth *)` line moved after the round 6 S5 edits).
- **Verification closed**: the "not yet verified" notes on the Round 2, Round 3 and Round 4 headers now say the round 2-6 edits were verified and closed on 2026-10-23 by two independent verifiers; both accepted (identity and credentials after round 5; everything else after V6-RS-1).

### Round 7 (2026-10-29, owner choices after P0-10 step 1b)

Four owner choices of 2026-10-29 on the step-1b record's open questions (`docs/evaluations/2026-10-29-p0-10-step-1b-results.md` §8). Verification: independent review rounds 1-2 on 2026-10-29: OC-R-1 … OC-R-19, closed by the reviewer.

- **OC-5** (D-13 token; step-1b record §3.2, §3.3, §4, §8 decision (1)): §7 adds "Owner choices, 2026-10-29" with the OC-5 bullet; the OC-1 bullet says its token type is superseded; D-13's "Token (R-A-2)" now records the step-1b result and the classic `public_repo` token (no `workflow`, 90-day expiry), its dependence on the repository staying public (fail closed) and the ToS §B.3 caveat adapted to `public_repo`; RK-3, RK-4 and CN-1 match; §0's numbering note names OC-5 … OC-8.
- **OC-6** (D-12 merge restriction; step-1b record §3.5, §3.6, §3.9, §8 decision (2)): the OC-6 bullet records candidate B on `main` as tested, its evidence, the untested "Restrict updates" alternative, the rollback (remove B), the guards (runbook rule "the agent account never approves PRs", the monthly S5 §3 count of bot approvals on owner-authored PRs, the re-run of probes (b), (d), (e) and (i) on `main`) and the residual that holds even with B [Inf, untested]; team-based required reviewers are later and optional. The OC-2 bullet, D-12 (result, guards, governance column), §1 (c), §1's decide list, §2.1 (c) and §3.2 (the approved-head row and a new row for the residual) match.
- **OC-7** (probe (d); step-1b record §3.4, §8 (d) row): the OC-7 bullet records the reworded probe (d) and its count of bot approvals; D-12 and the new §3.2 row cite it.
- **OC-8** (probe (a); step-1b record §6, §8 (a) row, decision (4)): the OC-8 bullet records the reworded probe (a) (approved PR diff = merged PR diff) and the test on `main` that a diff-changing update dismisses the approval; D-12 cites it. The §2.1 S (c) instrument now reads "approval covering the merged PR diff" and notes that a kept approval's `commit_id` is not evidence on its own.
- **OC-5 follow-up** (step-1b record §4 check 1): D-13 replaces "if the org requires token approval, you approve it" with the measured fact that the org's policy does not restrict classic tokens or require their approval [Owner-rep], and says the token choice is re-checked if that policy changes.
- **Step-1b record returned**: §7's new paragraph, D-12, D-13 and Limits say both the step-1a (2026-10-27) and step-1b (2026-10-29) records have returned. The round 3 V2-ID-7 and "Coordinator edit" entries above carry a "token type superseded by OC-5" pointer.
- **CN-7 line**: CN-7 now cites `S5:218` (the `Bash(gh auth *)` line moved after the round 7 S5 edits).

Review round 1 (2026-10-29), the editor's answers to OC-R-1 … OC-R-17; only the reviewer closes a finding:

- **OC-R-1**: the OC-7 bullet tags the owner's merge [Inf, untested in step 1b; first measured by this probe on `main`] and says the probe records its route (normal merge or PR-only bypass); the OC-7 wording is kept.
- **OC-R-2**: the §4 "Any autonomous merge path" row says step 1b found B and step 5a adopts it (OC-6), with the OC-2 exception only if B is removed; the §7 paragraph lists §4 among the changed rows.
- **OC-R-3**: "Decisions requiring approval" adds "(2026-10-29): OC-5 (D-13), OC-6, OC-7, OC-8 (D-12)".
- **OC-R-4**: D-01's OC-2 residual carries a pointer only (the exception applies only if B is removed, OC-6; the bot-approval residual is held by OC-6's guards); D-01 is not rewritten.
- **OC-R-5**: D-13 and the OC-5 bullet cite GitHub "Scopes for OAuth apps" [Docs, accessed 2026-10-29], state that the permission bound applies everywhere and that this repository is the bot's only collaborator grant, and tag "issues, comments, forks, PRs" [Inf]; Limits adds the source.
- **OC-R-6**: S5 only (§2.3 item 2 order).
- **OC-R-7**: S5 only (§3 count scope; step 6 note on probe (d)'s owner-run approval).
- **OC-R-8**: §2.1 S (c) says the method for "the approved PR diff" is open, to be defined and recorded before the first probe (a) run.
- **OC-R-9**: CN-1 adds the precedence note: S2 OPP-08 and S3 §2.2 / DECISION-S3-1 still state the pre-OC-5 token type and the old probe (d) premise; §7 OC-5 … OC-8 take precedence; alignment in a follow-up. S2 and S3 are not edited.
- **OC-R-10**: D-13's "if that policy changes, the token choice is re-checked" and OC-7's "also counts and reports any bot approval" are marked as the editor's wording.
- **OC-R-11**: S5 probe (i) only.
- **OC-R-12**: the round 2 OC-1 entry above carries "superseded by OC-5, round 7".
- **OC-R-13**: this round's header states the review status; the index adds a round-7 row.
- **OC-R-14**: index only.
- **OC-R-15**: D-13's owner-action column reads "token minting (no org approval needed for classic tokens)".
- **OC-R-16**: §1 (c) and the OC-6 bullet say "every bot merge attempt through the API (`merge`, `merge-async`)"; the OC-6 bullet records the untested UI merge button and `gh pr merge` as open (step-1b record §9); no probe step added.
- **OC-R-17**: nothing to do.

- Round 2 notes (coordinator, 2026-10-29): OC-R-18 (D-13 owner steps point to S5 P0-10 step 2 for the storage mechanism); OC-R-19 (round-7 status records the review outcome).

### Round 8 (2026-10-30, P0-10 step 2 results and the order choice)

The P0-10 step-2 record (`docs/evaluations/2026-10-30-p0-10-step-2-results.md`) and the owner's order choice OC-9 (recorded in the S5 amendment log, round 8). These edits await their own review.

- **D-13**: the owner steps replace "`gh auth login --with-token` may refuse a `public_repo` token, untested" with the measured refusal (step-2 record §3.4), point to S5 P0-10 steps 2-3 for the storage mechanism (the owner's choice), and say the real token is minted in step 3 at storage (OC-9). The dormant-delivery sentence says the expired `dentaledge-bot-pat` could not be tried (the file held no value), so its death is an exception, not proved by use (step-2 record §4).
