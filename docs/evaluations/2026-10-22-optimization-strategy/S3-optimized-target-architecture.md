# S3 — Optimized Target Architecture
> Phase 3 of the Software Factory evaluation campaign · Date: 2026-10-22 · Status: proposal for owner approval; nothing implemented
> Inputs: phase 1 (docs/evaluations/2026-10-22-factory-research/), phase 2 (docs/evaluations/2026-10-22-factory-comparison/), claude_code at b8ed8a7
> Legend: [Ver] verified in claude_code · [Res] research finding · [Exp] expected benefit · [Asm] assumption · [Unk] unknown · [Inf] inference from verified facts · [Docs] official documentation, as read by the cited deliverable on 2026-10-22

Companion deliverable: S5 (roadmap). Every change named here has a roadmap ID in S5 (`P0-nn` … `P3-nn`), and the
two documents use the same IDs. Decisions new in this document are DECISION-S3-1, -2, -4 and -5; DECISION-S3-3 is
folded into DECISION-S4-3 (see the decisions table). S4's decisions are cited as DECISION-S4-1 … 8. The verifier's
findings on S1 and S4 (V-S1-n, V-S4-n) and on this document (V-S3-n) were incorporated; they are cited as such. This
version follows the corrected S1, S2 and S4.

## 0. Summary

1. **The target is the current architecture with its gates made real, its readers made read-only, and its outcomes
   measured.** It keeps the governance spine, both lanes, the eval/refine machinery, the brain, the reference library
   and Hermes. Agent definitions: +2 (a tool-restricted reviewer, DECISION-S2-3; the read-only `reference-analyst`,
   S4 Increment 1) and −1 (skill-guardian). Skills: −1 (gstack-pattern-audit). It adds 0 external runtime
   dependencies, 0 orchestrators and 0 services (§1, §4).
2. **Acceptance has three owners, each limited to what it can be trusted with** (§2.1). Code owns pass/fail
   (CI required checks on the head, run-manifest status, guard exit 2). Models own judgements only inside an
   evidence contract they cannot edit. The human owns merge, canon promotion, deploys and licence escalations,
   through a channel the agent cannot write to.
3. **The approval channel is the design's hinge.** Today the agent and the owner are one GitHub identity with
   0 required approvals, no code-owner review, no last-push approval and no stale-review dismissal [Ver ruleset read
   via `gh api` today]. The target follows S2's five-part OPP-08: a separate machine account for agent work (the
   existing `dentaledge-bot`, owner choice OC-1 of 2026-10-23), the owner as the only counted approver (CODEOWNERS
   `*` + code-owner review), approval bound to the last push, the owner's credential out of the agent's reach, and
   owner-authored PRs merging through a second ruleset whose PR-only owner bypass skips the review but never the
   checks. On this laptop "out of reach" covers every path to the owner's GitHub authority: the `gh` multi-account
   store, the keychain, SSH keys, tokens, and every agent-driven browser or desktop channel signed in to github.com
   (DECISION-S3-1, §2.2).
4. **Untrusted text is read only by agents that cannot write** (§2.3). For the three named instances of breach (b)
   (8 repo-audit analysts, skill-guardian, skill-scout-agent) the readers lose their write tools or are retired, so
   breach (b) is **narrowed, not closed** (S2 §0): the write-capable orchestrators still receive text derived from
   untrusted content (repo-audit's merge and `--pipeline` write; the scout parent's description field). Paths that
   run in the main session close by framing plus a human gate now and structurally later (P2-06). Synthesizer and
   adapt keep a stated residual: they must write, and they read audited-but-untrusted text.
5. **Self-improvement stays bounded by construction** (§2.8). Every model-run deploy step (skill-adapt,
   skill-refine, skill-refine-agent, and the sanction in `CLAUDE.md:75`) becomes "staged"; the remaining deploy
   forms are only prompted (residual, §2.8). The evaluator's own files are pinned in
   the run manifest. Re-baselining under E12 precedes any refine.
6. **Measurement comes before any new mechanism** (DECISION-S2-8). The owner's seven measures get an instrument and
   a dated, tracked baseline record (DECISION-S3-4, §2.6). Spend caps, isolation runtimes, orchestration and
   app-type verification stay DEFER, each with a trigger (§4).

---

## 1. Target architecture as an evolution of the current one

### 1.1 Labels

| Label | Meaning |
|---|---|
| **kept** | unchanged; proven and evidenced [S1 §2, §6] |
| **strengthened** | same component, a control made enforceable or a scope widened |
| **connected** | an existing link made automatic or an existing component joined to another |
| **added** | a new definition, template, field or check inside an existing component |
| **retired** | removed; its function is covered elsewhere |

### 1.2 Layer view

Solid arrows are enforced by code, CI, a hook or a GitHub rule. Dashed arrows are human or model actions.
`[P0-nn]` refers to S5.

```mermaid
flowchart TB
  classDef kept fill:#eef,stroke:#669;
  classDef str fill:#efe,stroke:#393;
  classDef con fill:#ffe,stroke:#993;
  classDef add fill:#fee,stroke:#c33;
  classDef ret fill:#ddd,stroke:#777,stroke-dasharray: 4 3;

  subgraph GOV["Governance spine"]
    RP["REVIEW_PROTOCOL<br/>strengthened: ID states, reviewer agent [P1-07/08]"]:::str
    RS["Rulesets: checks (no bypass) + review (owner PR-only bypass)<br/>strengthened: owner code-owner approval on the last push, 5 required checks [P0-10, P1-06]"]:::str
    ASK["Committed permission rules<br/>strengthened: ask on push/merge/promote/deploy [P0-07]"]:::str
    BRN["Brain + promotion gate<br/>kept; guard strengthened: fail closed, committed [P0-09]"]:::str
    KNOW["Verify-before-decide, CLAUDE_CODE_KNOWLEDGE<br/>kept"]:::kept
  end

  subgraph INTAKE["Untrusted intake (all external text)"]
    RAA["repo-audit analysts x8<br/>strengthened: Read only [P0-03]; packer pinned [P0-01]"]:::str
    SSA["skill-scout-agent<br/>strengthened: read-only fetcher; schema fields + capped description, no body [P0-05]"]:::str
    FR["Framing rule in every reader<br/>added [P0-06]"]:::add
    PS0["project-setup Phase 0<br/>strengthened: commit pinned, explicit yes [P1-15]"]:::str
    GUA["skill-guardian<br/>retired [P0-04]"]:::ret
  end

  subgraph CAP["Capability lane"]
    SC["scout"]:::str --> AU["audit (static scan)<br/>strengthened: scope packs + Hermes, required [P1-06]"]:::str --> AD["adapt<br/>strengthened: licence never omitted; deploy staged [P0-08, P2-01]"]:::str --> EV["eval / agent-eval / team-eval / Codex<br/>kept (E12)"]:::kept --> RF["refine<br/>strengthened: KEEP staged, evaluator pinned [P0-08, P0-11]"]:::str
  end

  subgraph REF["Reference-driven engineering"]
    RR["Registry + cards<br/>strengthened: licence/commit fields; created in targets [P1-14, P2-01]"]:::str
    PX["pattern-extract app mode<br/>added: T1-T3, rules, G1 [P1-14]"]:::add
    RAN["reference-analyst agent<br/>added: Read, Grep, Glob only [P1-14]"]:::add
    GS["gstack-pattern-audit<br/>retired [P1-17]"]:::ret
  end

  subgraph DEL["Delivery lane"]
    SP["spec/plan with F-/AC-IDs<br/>strengthened [P1-08]"]:::str --> ACC["independent acceptance tests<br/>added, pilot [P1-09]"]:::add --> IMP["subagent tasks + TDD<br/>kept"]:::kept --> REV["reviewer agent: no Edit/Write + tripwire<br/>added [P1-07]"]:::add --> PR["PR by the agent machine account<br/>strengthened [P0-10]"]:::str
  end

  subgraph MEAS["Measurement"]
    BASE["Outcome baseline from git/PR<br/>added [P1-01]"]:::add
    TEL["Telemetry<br/>connected: aggregator run, proxy validated, intervention count [P1-02, P1-03]"]:::con
    COST["Tokens per accepted result<br/>connected from timing.json [P1-04]"]:::con
    STALE["Eval staleness warning in CI<br/>added [P1-11]"]:::add
  end

  subgraph HER["Hermes VPS (Track A, D3.2 unchanged)"]
    HP["proposer + Kanban review, read-only by mode, mounts, prose<br/>strengthened: framing, --tools allowlist [P1-16]"]:::str
    HD["draft-PR delivery<br/>strengthened: no PAT /proc window [P1-16]"]:::str
    HB["Track B.1 Ads audits RO<br/>kept"]:::kept
  end

  RAA --> SC
  SSA -->|structured fields only| SC
  PS0 -.->|hand-off| PX
  RR --> PX
  PX -->|dispatch, foreground| RAN
  PX -.->|G1 owner approves verdicts| SP
  PX -.->|skill/agent verdicts| SC
  EV -->|refine-input.json| RF
  RF -.->|staged; owner deploys + check-skill-deploy| RT[("~/.claude/skills")]:::str
  PR -->|required checks, strict| RS
  RS -.->|owner approves + merges, own identity| MAIN[("main")]:::kept
  TEL --> RF
  EV --> COST
  MAIN --> BASE
  HD -.->|operator-run, bot token| BRN
  HP -.-> SP
  ASK --> PR
```

### 1.3 Change list (each traced to S2 and S1)

| Component | Label | Change | OPP | GAP | S5 |
|---|---|---|---|---|---|
| repo-audit skill; project-audit text | strengthened | `npx repomix@<exact>`; runtime `pip install gitingest` removed, stop with a message (`skills/repo-audit/SKILL.md:35,55,61` [Ver]); the user-facing `npx ecc-agentshield scan --fix` advice pinned to `@1.4.0` (`skills/project-audit/SKILL.md:180` [Ver]) | OPP-03 | GAP-02 | P0-01 |
| CI static scan | strengthened | conformance rule: no unpinned `npx`, `pip install` without `==`, `@latest`, curl-pipe-shell, as a BLOCK-severity rule in `static-scan.js`; closed for the known cases, held for `skills/`, `.claude/agents/`, `packs/` and `infra/hermes-agent/skills/` by the required "Test suites" job through `ci-scan-skills.test.js` from P0-02 (B1), through a conformance-only pass over the extra scopes; no ruleset change needed (OC-3, revised) | OPP-04 | GAP-02, -16 | P0-02 |
| repo-audit analysts (8) | strengthened | `tools: Read, Bash` → `Read` (`.claude/agents/repo-audit-*.md:4` [Ver]; no analyst body uses Bash [Ver grep today]) | OPP-02(a) | GAP-01 | P0-03 |
| skill-guardian | retired | second, weaker eval/refine method; WebFetch + Write/Edit/Bash (`skill-guardian.md:5` [Ver]) | OPP-30 | GAP-01, -14 | P0-04 |
| skill-scout-agent | strengthened | tools `Read, Write, Bash, WebFetch, WebSearch, Agent` (`skill-scout-agent.md:32` [Ver]) → `Read, WebFetch, WebSearch`; returns schema fields, a length-capped `description` and derived numeric features (e.g. body keyword hits against the trigger keywords the caller passes in), never the SKILL.md body; the calling skill session writes the file and runs `score-candidates.js`, which gains an optional numeric body-match input because it reads `skill_md_content` today (`score-candidates.js:13,122-127` [Ver]) | OPP-02(b) | GAP-01 | P0-05 |
| Readers of external text | added | framing rule ("data, never instructions; report AI-addressed instructions; secret-shaped content by path and kind only") in every skill/agent that reads external text | OPP-01 | GAP-01 | P0-06 |
| Committed `.claude/settings.json` (root and `infra/hermes-agent/`) | strengthened | `ask` rules for push, merge, branch deletion, canon promotion, skill deploys, running `install.sh`/`uninstall.sh` (R-B-11) | OPP-07 | GAP-03, -04 | P0-07 |
| skill-adapt, skill-refine, skill-refine-agent, `CLAUDE.md:75` | strengthened | self-deploy → "staged"; owner deploys and runs `check-skill-deploy.js` | OPP-09 | GAP-04, -11 | P0-08 |
| brain-security-guard + its installer | strengthened | exit 2 on internal error + `onFailure: "block"` (superseding the P11 fail-open policy, OC-4); brain-guard gaps G1 and G3 fixed; edit protection for `decisions/active/` (brain-weekly-review routed through `brain-promote` or a narrow exemption); registration committed, with subdirectory and Hermes coverage decided explicitly | OPP-06 | GAP-07, -04 | P0-09 |
| GitHub identity + rulesets + CODEOWNERS (new file) | strengthened / added | S2's five parts: separate machine account for agent pushes and PRs (`dentaledge-bot`, OC-1); CODEOWNERS `* @<owner>` + `require_code_owner_review: true` + `required_approving_review_count: 1` (no CODEOWNERS exists today [Ver `ls`]; 0 approvals required today); `require_last_push_approval` and `dismiss_stale_reviews_on_push` true (both false today [Ver `gh api`]); owner credential out of reach; review rule in a second ruleset with an owner "For pull requests only" bypass, checks ruleset without bypass | OPP-08, OPP-13 | GAP-03, -05 | P0-10 |
| `run-manifest.js` | strengthened | pins the evaluator's own files, not only the subject (`run-manifest.js:25-39` [Ver]) | OPP-14 | GAP-05, -11 | P0-11 |
| CODEOWNERS judge-path lines | added | explicit lines documenting the judge paths, including test files (covered by `*` already; needed if `*` is ever narrowed) | OPP-13 | GAP-05 | P1-05 |
| CI static scan | strengthened | general scan (injection, secrets, permissions): scope `skills/` → also packs and Hermes skills (P0-02 adds only a conformance-only pass there); `.claude/agents/` and `packs/*/tools/` are not added to the general scan (Security gate over `.claude/`; `pack-audit.js` on demand; both covered for unpinned installs by P0-02, V4-RS-2); findings triaged; job becomes required (D-15, before P1) | OPP-05 | GAP-16, -10 | P1-06 |
| `.claude/agents/reviewer.md` | added | Read, Grep, Glob, Bash; git HEAD/status tripwire | OPP-10 | GAP-08 | P1-07 |
| project-idea, PR template, REVIEW_PROTOCOL | strengthened | F-IDs/AC-IDs; per-ID verified/failed/unverified set by the reviewer; "requirement IDs covered" and "reused components + licences" lines | OPP-12 | GAP-17, -06, -12 | P1-08 |
| delivery flow | added | acceptance tests from the spec by a separate subagent, committed first (pilot) | OPP-11 | GAP-06 | P1-09 |
| measurement | added / connected | git/PR baseline; telemetry aggregator run and proxy labelled; intervention count; tokens per accepted result | OPP-25, -26, -27 | GAP-09, -15 | P1-01 … P1-04 |
| eval currency | connected | E12 re-baseline subset; CI staleness warning; first supervised refine | OPP-16, -17, -18 | GAP-10, -11 | P1-10 … P1-12 |
| guard regression tests | added | red-on-removal test per deny rule and BLOCK pattern | OPP-15 | GAP-16, -07, -05 | P1-13 |
| reference-repo-pattern-extract; `.claude/agents/reference-analyst.md` (new); installers | added | app mode, T1-T3, selection rules, G1; analysis only through `reference-analyst` (Read, Grep, Glob); mandatory registration; empty registry created in targets, removed by uninstall only while still empty | OPP-19, OPP-02(c) | GAP-12, -13, -01 | P1-14 |
| project-setup Phase 0 | strengthened | fetched commit recorded; reference-sourced rules and commands need an explicit yes; framing; hand-off to the app mode | OPP-22 | GAP-01, -12 | P1-15 |
| gstack-pattern-audit | retired | covered by the generic skill | OPP-29 | GAP-14 | P1-17 |
| Hermes Track A skills + delivery | strengthened | framing; `--tools 'Read,Grep,Glob'` on the proposer's `claude -p` (its `--allowedTools` only pre-approves); one-shot no-shell delivery container; key rotation (owner) | OPP-38 | GAP-20 | P1-16 |
| registry schema, adapt skills, scout scorer | strengthened | licence/commit fields; licence filter; star cap | OPP-20, -21 | GAP-12, -13 | P2-01, P2-02 |

### 1.4 Kept as is (and why)

- **E12 eval methodology**, `harvest-evidence.js`, run manifests, analyst pass, team-eval chain metrics [S1 ST-3]. No
  researched repository has an equivalent on its main branch [Res P2-D2 C4]. Not replaced by any external harness.
- **Calibration** (mutant fixtures, golden transcript) [S1 ST-4] and **Codex as second-model evaluator**, dry-run
  by default, read-only sandbox [S1 ST-5].
- **Required CI with `strict: true` and no bypass actors** [Ver ruleset today]. This is the native head-bound gate
  [S1 ST-2].
- **Superpowers as the delivery spine** and **Hermes Kanban as the only durable orchestrator** (10-14 §5, the C1
  one-spine rule [Res P2-D4 §3.2]).
- **Brain promotion gate**, decisions and canon [S1 ST-8]; **do-not-install-directly** library policy [S1 ST-10].
- **Hermes security posture** [S1 ST-7]: no write credential (D3.2), plan-mode `claude -p` with no approver in
  print mode, `:ro` project mounts, single-host egress on an internal network, a gateway that never sees audit
  content, digest pin, CI-versioned security checklist. Its `--allowedTools 'Read,Grep,Glob'` flag
  (`claude-code-proposer/SKILL.md:42`, `run-ads-audit.sh:25`, `bin/run-client-audit.py:82` [Ver]) only pre-approves
  and removes no tool; `--tools` restricts [Docs via S4 §3.7, V-S4-12]. So these agents are read-only by mode, mounts
  and missing credentials, not by tool list; P1-16 adds `--tools` to the proposer (V-S3-2).

---

## 2. Cross-cutting design decisions

### 2.1 Where acceptance decisions sit

Principle: put the pass/fail decision in code, make "no evidence" a failure, and check that the checks can fail
[Res P2-D5 P1, P4]. Models judge only inside an evidence contract they cannot edit [Res P2-D5 P5]. Humans decide
only consequential, irreversible or legal questions [value definition, working rule 1].

| Decision | Owner | Mechanism (target) | Today |
|---|---|---|---|
| A PR may merge | **code** (necessary) + **human** (sufficient) | 4 → 5 required checks, strict, on the head, in a checks ruleset with no bypass [P1-06]; the owner's code-owner approval of the last push, in a review ruleset [P0-10] | code part [Ver]; human part prose only, 0 approvals [Ver] |
| Judge files may change | **human** (code owner) | CODEOWNERS `* @<owner>` covers every path, test files included (`scripts/**/*.test.js`, `skills/**/*.test.js`, `scripts/codex/test-*.js`, `scripts/telemetry/test-telemetry.js`: `run-all-tests.js:4,17-19` discovers suites dynamically [Ver], so deleting a test weakens CI) [P0-10]; explicit judge-path lines `.github/`, `scripts/ci-*`, `scripts/run-all-tests.js`, `.github/skill-scan-baseline.json`, `skills/skill-eval/scripts/`, `skills/skill-audit/scripts/`, `hooks/brain/` and the test globs document the judge [P1-05]; agent account without the Workflows permission (DECISION-S3-1). Residual: owner-authored PRs merged through the review-ruleset bypass skip this review | unprotected [S1 L-04] |
| An eval iteration is valid | **code** | `run-manifest.js status` exit codes; subject **and** evaluator hashes [P0-11] | subject only [Ver `run-manifest.js:25-39`] |
| Trigger/workflow evidence | **code** | `harvest-evidence.js` from filesystem and transcript [kept]; E6 marker residual disclosed (decision 2026-10-21) | as target |
| Output quality, judgement items | **model** | LLM judge on `expected.judgment` only; Codex re-judging on demand; calibration | as target [Ver `skill-eval/SKILL.md:85`] |
| Each requirement ID is verified | **reviewer** (model, independent context, tool-restricted) | reviewer re-runs the check at head; three states; builder never sets them [P1-07, P1-08] | no IDs; reviewer is `general-purpose` [S1 L-05] |
| Acceptance tests are trustworthy | **code + reviewer** | written from the spec by a separate subagent, committed before implementation, shown to fail on the pre-implementation commit [P1-09] | builder-authored [S1 L-05] |
| Adapt / refine KEEP takes effect at runtime | **human** | staged; owner deploys, then `check-skill-deploy.js` [P0-08]; other copy forms only prompted by ask rules (residual) | model `cp -r` [Ver `skill-refine/SKILL.md:60`, `skill-refine-agent.md:124`, `skill-adapt/SKILL.md:84`, sanctioned by `CLAUDE.md:75`] |
| Canon promotion | **human** | `brain-promote.js --approve` behind an `ask` rule; brain-guard gap G1 (the `--approve` exemption) closed [P0-07, P0-09] | typed flag; brain-guard gap G1 exemption [S1 L-08] |
| Reuse verdicts, licence escalations | **human** | reference gate G1 on T3 [P1-14; DECISION-S4-3] | none |
| A guard blocks | **code** | exit 2, `onFailure: "block"`, red-on-removal tests [P0-09, P1-13] | fails open with exit 1 [Ver `brain-security-guard.sh:415-424`] |

Correctness criterion status after the target is in place [Exp]: C2 moves from "met for the merge-path floor, not
demonstrated above it" (S1 as corrected, V-S1-3) to "demonstrated per requirement ID on piloted tasks" once P1-08
and P1-09 have run on real PRs. That claim must be measured (S5 §3, first-pass acceptance and false completions),
not assumed.

### 2.2 Approval and identity model

**Target state** (S2 OPP-08 and DECISION-S2-1 (c), five parts, with the corrections below).
1. **Separate machine account.** Agent sessions (Claude Code on the laptop, worktrees, subagents) authenticate to
   GitHub only as a separate machine account: a collaborator with write (not admin) and a token minted **from that
   account**, with no `workflow` scope or Workflows permission [Asm: GitHub token semantics; verify per the
   primary-source rule before P0-10]. A token minted by the owner acts as the owner, so the owner would be the PR
   author and could not approve (V-S3-4). **The account is `dentaledge-bot`** (owner choice OC-1, 2026-10-23;
   DECISION-S3-1 (ii)): a User account, collaborator with write on this repository [Ver by the coordinator,
   2026-10-23; `infra/hermes-agent/.env.pr.example:2`; `infra/hermes-agent/README.md:315-318`]. GitHub's Terms allow
   "no more than one free machine account in addition to your free Personal Account" (ToS §B.3, accessed
   2026-10-23), and the bot already is it, so a new machine account would mean deleting the bot or paying. Its old
   token `dentaledge-bot-pat` is recorded to expire 2026-10-23 and is not renewed (owner decision of 2026-10-14,
   `.project-brain/sessions/daily/2026-10-14.md:35-37`; refusal to be proved by the owner, P0-10 step 2), so Hermes
   draft-PR delivery is dormant and the earlier "one blast radius" objection does not apply while it stays dormant
   (R-A-1, R-B-4). Token type (R-A-2): the bot is an outside/repository collaborator on a public org repository,
   which is a documented fine-grained-token gap, so the fallback is a **classic PAT with `repo` and no `workflow`
   scope**; a fine-grained token (Contents + Pull requests, one repository, no Workflows) is tested first in P0-10
   step 1b and used if it works [Docs, "Managing personal access tokens", accessed 2026-10-23]. Counter-evidence:
   PR #4's head was pushed into the org repository by the bot as an outside collaborator, and `.env.pr.example` and
   `README.md:315-318` describe a fine-grained token. A classic `repo` token is bounded by the bot's collaborator
   access only for org repositories: it also acts as the bot on any public GitHub repository (issues, comments,
   forks, PRs) and in the bot's own namespace, and gains any repository the bot is later added to; under ToS §B.3 the
   owner is responsible for those actions (V2-ID-7). The org's classic-PAT policy is [Asm] until step 1a.
2. **Only the owner's approval counts.** CODEOWNERS `* @<owner>` with `require_code_owner_review: true` and
   `required_approving_review_count: 1` (0 today [Ver]) (V2-ID-8). Without it,
   any write-access approval counts, including a second bot or any token a session can reach [Docs via S2]. GitHub
   forbids author self-approval [Docs via S2], so the agent account cannot approve its own PR, and no other bot can
   supply the code-owner approval.
3. **Approval bound to the last push.** `require_last_push_approval: true` and `dismiss_stale_reviews_on_push: true`;
   both are `false` today [Ver `gh api` today] (V-S3-3). Without them the agent account, which holds Contents write
   and can therefore merge, could push after the owner's approval and merge an unreviewed head. With them, a push
   after approval needs a new owner approval. **Residual:** merging an *approved* head stays possible for the agent
   account; only the `ask` rule on `gh pr merge` / `gh api` prompts for it, and that is not enforced. P0-10 step 1a
   compares two merge-restriction candidates (a ruleset "Restrict updates" with the repository admin role, owner the
   only admin, or an owner-only team as bypass actor, consistent with R-A-14 (V3-ID-3), which turns every owner merge
   into a bypass event; classic branch protection "Restrict who can push to matching branches") and step 1b tests them
   on a scratch branch pattern, never `main`, whose layering mirrors `main` (a checks ruleset with no bypass, the
   review ruleset and the candidate restriction), with the required check emulated by a test status context the owner
   sets through the commit statuses API because CI does not run on pull requests into `p0-10-probe/**` (`ci.yml:3-7`);
   test rulesets and probe branches are deleted after the test (V3-ID-1, V3-ID-2); whether a PR merge counts as an
   "update" is UNVERIFIED (V2-ID-3). If one works without blocking the owner's normal merges it is adopted (step 5a).
   If none works, or probe (i) fails on `main` (the owner then removes the step-5a restriction at once, V3-ID-2), this
   residual is an explicit owner-accepted exception to `docs/REVIEW_PROTOCOL.md:22` ("Approve, don't merge. Merging is
   a human action.") and the 2026-10-14 boundary, with `allow_auto_merge` kept false (false on 2026-10-23), since an
   armed auto-merge would merge at approval with no prompt (owner choice OC-2).
4. **The owner's credential is out of the agent's reach** [Asm: feasibility on the laptop not checked]; see below.
5. **Owner-authored PRs.** The owner cannot approve their own PR, so the review rule sits in a **second ruleset**
   whose bypass list allows the owner "For pull requests only". The rulesets UI doc lists roles (repository admin,
   maintain, write or custom roles), teams, GitHub Apps or Dependabot as bypass actors (V-S2-16); the REST
   `bypass_actors.actor_type` enum also includes `User` and `DeployKey`, so whether a user account can be one is
   UNVERIFIED (R-A-14). The choice is unaffected: the bypass actor is the **repository admin role, with the owner as the only admin**, or a
   **team whose only member is the owner**, on condition that the agent account holds no admin role and is in no
   bypass team [Asm: verify in the ruleset UI/API]. The checks ruleset (`main-protection`) keeps no bypass actors, so
   the bypass skips the review but never the required checks [Asm: per-ruleset bypass; S2 requires a test PR]. This
   keeps §1.4's "no bypass actors" strength for the checks (V-S3-5). Owner-bypass merges also skip code-owner review
   of judge paths. The same bypass would let the owner merge an agent PR without recording an approval; that is still
  a human merge, but bypass use is counted separately (S5 §3) and the runbook says to approve agent PRs rather than
  bypass.
- Locally, committed `ask` rules prompt for push, merge, review approval, `gh api`, branch deletion, promotion and
  deploys even in auto mode [Docs via S2]. They are a prompt, not a boundary (a rule "isn't a security boundary around
  the program"; `Bash(git push *)` "doesn't stop" `git -C . push` [Docs via S2]); the boundary is parts 1-5.
- Hermes' operator-run `dentaledge-bot` path for proposals (Track A Increment 2) is **dormant from 2026-10-23**: the
  owner let its PAT expire, not renewed, and the account is now the laptop agent's identity (OC-1). Restoring Hermes
  draft-PR delivery is a separate Track A decision and needs its own identity (for example a GitHub App); the account
  stays single-consumer (credential canon rule 1, "the isolation boundary is the ACCOUNT",
  `.project-brain/canon/2026-08-17-credential-governance-lessons.md:49-52`).
- Access is measured, never asserted (`canon/2026-08-18-credential-access-levels-are-measured-never-asserted.md:12`):
  P0-10 probe (g) checks with the agent token, after the step-1b test rulesets and probe branches are deleted, that a `.github/workflows/` push on a `p0-10-probe/**` branch is
  refused with GitHub's workflow-scope or Workflows-permission message (recorded) while a control push of a
  non-workflow file to the same branch succeeds (V3-ID-1), a private org repository where the bot is not a collaborator (`claude-google-ads` or
  `claude-marketing-team`) returns 404, non-mutating admin-only reads (`GET /repos/{o}/{r}/hooks`, `.../keys`) return
  403 or 404, and `current_user_can_bypass` on the **review** ruleset is `never` for the agent while the owner's read
  returns `pull_requests_only` (so the probe can fail); it lists every admin or org owner; no write attempts beyond
  the two probe pushes (workflow and control); the probe branch is deleted afterwards (V4-ID-3); the record is re-run
  at every rotation (V2-ID-2).

**Why the credential's reachability matters** [Inf]. The split fails if a session can act as the owner. P0-10 step 3
enumerates every path and measures its exposure before declaring it out of reach
(`credential-governance-lessons.md:115-117,130-132`):
- `gh` stores several accounts, and `gh auth switch` changes the active one [Asm: gh ≥ 2.40 behaviour]. Today
  sessions use the owner's login with `repo` and `workflow` scopes [S1 L-03].
- The git credential helper or keychain, SSH keys registered with GitHub [UNVERIFIED, owner checks],
  `GH_TOKEN`/`GITHUB_TOKEN`-style environment variables, and tokens already printed into session transcripts
  (fingerprint-only scan).
- The Claude in Chrome extension acts in the owner's real Chrome with the owner's sign-ins; its tools are offered to
  this session [Ver, machine-local]. Whether github.com is allowed in the extension is [Unk]. If it is, an agent
  could click "Approve" as the owner. The same holds for the Claude desktop app's built-in browser pane (persistent
  sign-ins) and desktop computer use.
- `infra/hermes-agent/.env.pr` still holds the expired bot token until the owner removes it (OC-1). The committed
  deny rules on it cover Read/Edit, not Bash readers such as the locally pre-approved `python3 *` (a rule "isn't a
  security boundary around the program" [Docs via S2]).
- `.claude/settings.local.json` pre-approves `Bash(gh pr *)`, `Bash(git push *)`, `Bash(git *)`
  (`:10,63,68` [Ver, machine-local]). Ask rules outrank these [Docs], but `git -C . push` matches the local
  `Bash(git *)` allow and not the ask rule, so the owner removes all three (DECISION-S2-1 (b)).
- Any other write-capable bot token reachable from a session (for example a copy of the Hermes PAT) could have
  approved agent PRs before part 2; with CODEOWNERS `*` it cannot supply the counted approval. The old Hermes token
  is recorded to expire 2026-10-23, with its refusal to be proved by the owner (P0-10 step 2), and the bot is now
  the agent account itself, which cannot approve its own PRs
  either (V2-ID-6).

**Workflows permission as judge protection** [Inf] (with a classic PAT: no `workflow` scope; measured by
P0-10 probe (g)). An agent account that cannot push changes under
`.github/workflows/` cannot weaken a required job by editing `ci.yml` in its own PR, which is the S1 GAP-05 path
[S1 L-04]. Trade-off: CI changes travel as owner-authored PRs made outside agent sessions and merged through the
PR-only bypass, which skips review; the owner never pushes to agent branches (V2-ID-9). CODEOWNERS `*` covers the remaining judge paths
(tests, scan baseline, CI scripts); P1-05 documents them explicitly.

**Sequencing constraint** [Docs via S2]: requiring an approval before agent PRs come from the separate account would
block every merge, since the owner would be both author and the only approver. The second ruleset with the owner
bypass must exist before the review rule takes effect. S5 orders P0-10 accordingly.

### 2.3 Untrusted-input handling

Pattern (internal precedent, Hermes Track B.1 [S1 ST-7]; research pattern R08 [Res P2-D5 P7]): **the reader of
untrusted text holds no write tool; the writer consumes only structured fields or a summary it treats as data.**
Framing alone is advisory [Res P2-D5 P6, P7]; it is required everywhere, but it is not counted as closure.

| Intake path | Reads | Today [Ver] | Target | Closure | S5 |
|---|---|---|---|---|---|
| repo-audit analysts | packed third-party repo slices | Read, Bash; no framing | Read only; framing | structural for the analysts. **Residual:** their JSON carries free text (patterns, gaps, notes) that the write-capable repo-audit session merges and, with `--pipeline`, writes into `project-context.json`; it also copies `ref_rules_always/never` from the reference (`repo-audit/SKILL.md:4,127-128,210-222`, per S2 OPP-02). Closed-key and length validation before the merge and the `--pipeline` write is P2-06 (V-S3-7) | P0-01, P0-03, P2-06 |
| skill-guardian | WebFetch arbitrary pages | Write, Edit, Bash, WebFetch | retired | structural | P0-04 |
| skill-scout-agent | registries, candidate SKILL.md bodies | Write, Bash, Agent, WebFetch | Read, WebFetch, WebSearch; schema fields, length-capped `description`, numeric body features out, never the body | structural for the agent. **Residual:** the parent still receives the capped `description` (free text); and skill-audit later reads the chosen candidate's full body in the main session (with framing) anyway (V-S3-6) | P0-05 |
| skill-scout / agent-scout run as skills | same, in the main session | main session (all tools) | framing now; fetch delegated to a read-only reader later | framing + human review now; structural in P2-06 | P0-06, P2-06 |
| project-setup Phase 0 | external CLAUDE.md, README, manifests at `HEAD` (`SKILL.md:58-68`) | main session; rules copied as suggestions | commit pinned; framing; reference-sourced rules and commands need an explicit yes | human gate | P1-15 |
| pattern-extract (library and app mode) | live repo by WebFetch; app mode: pinned clone | main session | app mode: analysis only through `reference-analyst` (`tools: Read, Grep, Glob`, foreground, enforced by the frontmatter allowlist [Docs via S4 §3.7]); the coordinating session clones and writes T1-T3 (V-S4-3, V-S4-12) | structural for the analyst; coordinator receives derived text (residual, as S4 §3.7) | P1-14 |
| skill-synthesizer-agent, skill-adapt | audited candidate bodies | Write (synthesizer); main session (adapt) | framing; audit before, eval after, staged deploy, PR review | **residual accepted**: these roles must write | P0-06, P0-08 |
| Hermes Track A reviewer and proposer | brain proposals, repo text | reviewer read-only by prose and `:ro` mounts, write capability [Unk] (V-S1-5); proposer plan mode with `--allowedTools`, which removes no tool (V-S3-2) | framing added; proposer gets `--tools 'Read,Grep,Glob'` under review #12 | not a breach instance (S1 corrected); framing + tool allowlist | P1-16 |

Note on WebFetch [Asm]: Claude Code's WebFetch returns content processed by a model rather than raw bytes. This may
buffer some injection, but it is undocumented as a security control here and is not counted.

**Intake method for reference analysis (DECISION-S4-3, clone posture).** S4's app mode reads a pinned shallow clone
with hooks disabled (S4 §2.4 recipe), but `reference-repo-add/SKILL.md:6,33` says "never clone or install the repo"
[Ver], and the library is WebFetch-only today. Cloning in a shipped skill is a security-posture change (V-S4-4). The
corrected S4 folds it into DECISION-S4-3 option (i), which is the same as this document's former DECISION-S3-3 (b),
so the owner decides it there (V-S3-9). S3 adds one amendment to it: `reference-repo-add`'s "never clone" rule is
rescoped to registration (registering never clones; app-mode analysis may, by the recipe only).

### 2.4 Least-privilege agent roles

| Agent (`.claude/agents/`) | Tools today [Ver frontmatter] | Target | Why |
|---|---|---|---|
| repo-audit-* (8) | Read, Bash | **Read** | untrusted reader; Bash unused [Ver] |
| skill-scout-agent | Read, Write, Bash, WebFetch, WebSearch, Agent | **Read, WebFetch, WebSearch** | untrusted reader; `Agent` spawns all-tool subagents |
| skill-guardian | Read, Write, Edit, Bash, Glob, Grep, WebSearch, WebFetch | **retired** | duplicate method; reader with write tools |
| reviewer (new) | — | **Read, Grep, Glob, Bash** + tamper tripwire (`git status --porcelain --ignored` plus an eval-run hash list; writes outside the repository are a residual, S2 OPP-10) | reviewers re-run checks (Bash); no Edit/Write [Res P2-D5 O1] |
| reference-analyst (new, S4 Increment 1) | — | **Read, Grep, Glob**, dispatched in the foreground; enforcement is the frontmatter `tools` allowlist [Docs via S4 §3.7]; agent-eval against a fresh no-agent baseline before first use | untrusted reader of reference clones; no shell, no write (V-S4-3, V-S3-1) |
| skill-synthesizer-agent | Read, Write | kept | must write the attribution map; framing added |
| skill-needs-analysis-agent | Read, Bash | kept; [Unk] whether Bash is needed | reads local project-context (which may hold repo-audit `ref_signals`) |
| skill-eval-agent, agent-eval-agent | Read, Write, Bash, Agent | kept | evaluators; protected by the evaluator pin (P0-11) and CODEOWNERS `*` (P0-10) |
| skill-refine-agent, agent-refine-agent | Read, Write, Edit, Bash, Agent | kept; deploy step removed (skill-refine-agent `:124`; `:72` only explains the copy-before-edit) | mutation is their job; bounded by staging and the evaluator pin |

Whether an agent's `tools` list can carry `Bash(pattern)` entries is [Unk]; the design does not rely on it. Each
changed agent gets an agent-audit and agent-eval re-run by normal practice; `CLAUDE.md:40` mandates the audit re-run
only for agent-refine's Lever E (V-S2-13).

### 2.5 Verification independence

Layers, from strongest to weakest, with what each is independent of:

1. **CI required checks on the head** — independent of the session; code. Strengthened by judge-path protection
   (CODEOWNERS `*` in P0-10, documented in P1-05; DECISION-S3-1 Workflows permission) so the judged PR cannot weaken
   its own job without the owner's approval of its last push.
2. **Independently authored acceptance tests** (P1-09) — independent of the builder's context; committed first, so
   git order shows they failed before implementation. The only measured quality gain in the research belongs to this
   layer, together with review and repair [Res P2-D5 §1 item 2: 6/9 vs 1-3/9 on hand-picked hard cases against
   no-review baselines].
3. **Tool-restricted reviewer** (P1-07) — independent context, no Edit/Write, tamper tripwire; same model family
   (residual). In R01, reviewers skipped required steps in 3 of 4 reviews, and its "read-only" reviewers hold Bash
   and Write [Res P2-D5 P6].
4. **Codex second-model evaluation** for skills and agents (kept) — different model family, read-only sandbox.
   Extending it to consequential delivery PRs, on demand and advisory, is an experiment (S5 P3-03, DECISION-S5-3),
   never a gate (`CLAUDE.md` Codex rules).
5. **Checker validation** — mutant fixtures and grader calibration (kept); guard red-on-removal tests (P1-13);
   "a check shown to fail" rule per requirement ID (P1-08).

### 2.6 Observability and outcome measurement

Instruments per measure are in S5 §3. Design rules:
- **Retrospective first.** Three of the owner's measures (time from spec to verified delivery, defect/rework proxy,
  review rounds) can be baselined today from git and PR history without code [S2 OPP-25]. The 10-14 evaluation
  planned the post-merge-fix proxy "to compute in P0" (`2026-10-14-…-evaluation.md:265`), and no computed value is
  recorded in the phase 3 implementation record [Ver grep]. P1-01 computes it.
- **Count, never content.** New telemetry fields are counts, enums and hashes only (`docs/telemetry-privacy.md`;
  `CLAUDE.md` Never list). The intervention count (P1-03) is one count per session from the existing
  UserPromptSubmit hook, keyed by `session_id`, which events already carry [Ver
  `schemas/telemetry/invocation-event.schema.json:14`].
- **Validate proxies before using them.** The correction flag fires on 49% of general-purpose agent invocations
  [S1 L-06], which is more likely the keyword heuristic than rework [Asm]. P1-02 labels a sample first.
- **Baselines are tracked records** (DECISION-S3-4): raw data stays under gitignored `evals/`; dated summary numbers
  and their method go to `docs/evaluations/` so later phases can compare against them.

### 2.7 Cost visibility

- Measure first: tokens and duration per eval run and per accepted scenario from the existing `timing.json`; tokens
  per delivery task from the Agent tool's usage output, recorded in the plan/PR record [S2 OPP-27].
- No spend cap yet. Attempt bounds stay (refine 10 iterations, eval 3 reps). A per-run ceiling is BUILD NEW with no
  implementation anywhere [Res P2-D5 P9], DEFER until P1-04 shows an overrun or usage-limit interruptions recur
  (S2 OPP-28; one occurred in phase 2 [Res COMPARATIVE_RESEARCH_INDEX §Process notes]).
- The re-baseline (P1-10) is the largest planned spend: 18-42 subagents per skill [Res: documented in
  `2026-10-14-phase3-implementation.md:50`]. It runs critical tier first and records tokens before the rest
  (DECISION-S5-2).

### 2.8 Continuous-improvement control

- **One deploy rule.** No definition contains a model-run deploy step: skill-adapt (`SKILL.md:84`), skill-refine
  (`SKILL.md:60`) and skill-refine-agent (`.md:124`; `:72` only explains the copy) end at "staged"; `CLAUDE.md:75`,
  which sanctions their self-sync today [Ver], is rewritten to match (V-S1-2; DECISION-S1-5 as widened; S2 OPP-09).
  Model-run deploy steps in definitions: 3 → 0. **Residual** (V-S3-12): a session can still copy to the runtime by
  another form (`rsync`, `$HOME/.claude/skills`, a `node` script) that the P0-07 ask rules do not match; staging
  removes the step from the workflow, it does not make a deploy impossible. The mid-loop re-eval is unaffected:
  with-skill subagents load `skills/<name>/SKILL.md` from the repo, not the runtime copy [Ver
  `skill-eval-agent.md:95`].
- **Evaluator out of the optimizer's reach.** The run manifest pins the evaluator files (P0-11); Lever E may not edit
  them, or works on a frozen copy when the subject is the evaluator [Res P2-D5 O20].
- **Fresh baseline before change.** Every skill or agent the roadmap edits gets a no-skill-baseline eval before the
  edit where a delta is claimed, and absolute thresholds otherwise (V-S4-2). Pre-E12 reports are never compared
  (decision 2026-10-21). 4 of the 29 SKILL-EVAL reports are PENDING placeholders (repo-audit, agent-scout,
  agent-audit, agent-adapt; V-S1-1), so for those the first measurement is the baseline.
- **First refine supervised** (E16): one iteration at a time, first revert checked by hand, `SKILL.md.baseline`
  created and never edited (P1-12).
- **Telemetry stays advisory.** REFINE_RECOMMENDED never invokes refine (kept).

### 2.9 Reference-driven workflow placement (from S4, corrected)

- Home: `reference-repo-pattern-extract` app mode with T1-T3 and the §3.5 selection rules (DECISION-S4-1, -2);
  F-IDs in `project-idea`; hand-off from `project-setup` Phase 0; G1 owner gate on verdicts (DECISION-S4-3); brain
  capture of decisions. No new skill or orchestrator; one new read-only agent, `reference-analyst` (DECISION-S4-1;
  S4 Increment 1 change 4).
- **Corrections carried into the design (as in the corrected S4):**
  - The skill's gate requires a clean `brain-reference-repo-audit.js` run (`SKILL.md:20-21` [Ver]), which needs a
    registry. Targets get none unless created: `install.sh` copies `scripts/brain` only with `--with-second-brain`
    (`install.sh:300-310` [Ver]) and never creates `reference-repositories/` [S4 IG-8]. Registration is mandatory, and
    P1-14 creates an empty registry in targets. `uninstall.sh` removes it **only while it is still the empty one
    install created**; a registry with entries is project data and is kept with a warning, like `.project-brain/`
    (S4 V-S4-13; V-S3-10). A target without the second brain cannot run the app mode.
  - Analysts are `reference-analyst` (Read/Grep/Glob only); the coordinating session clones, runs `git`/`gh api`
    metadata queries and writes T1-T3. A tool list cannot make Bash read-only or scope Write to one path (V-S4-3).
  - The clone posture is DECISION-S4-3 option (i) (§2.3).
  - G2 (merge, push, deploys) is an enforced gate only after P0-07/P0-10; until then it is a practice (V-S4-5).
- Routing by verdict: skill/agent verdicts go through scout → audit → adapt → eval; code verdicts go through the
  delivery lane with provenance headers and the PR template's licence line (P1-08); REIMPLEMENT from no-licence or
  copyleft sources uses context separation (P2-03, DECISION-S4-4).

### 2.10 Hermes boundaries

- **Unchanged:** Track A (Hermes proposes; the human and Claude Code build), D3.2 (no write credential for the Ads
  accounts), Track B.1 read-execute, the parked mutation tier, the charter. No item in S5 changes them; any change
  would be a separate owner decision.
- **Strengthened inside the boundary** (P1-16): framing text in `claude-code-reviewer` and the proposer;
  `--tools 'Read,Grep,Glob'` added to the proposer's `claude -p`, since `--allowedTools` removes no tool (V-S3-2); the PAT
  `/proc` window in `open-proposal-pr.sh:7-15` replaced by the one-shot no-shell container already designed in the
  Hermes README, if draft-PR delivery is ever restored (dormant from 2026-10-23, OC-1); key rotation (owner action).
- **Committed settings reach Hermes runs.** The proposer's workdir is `/projects/claude_code`
  (`registry/projects.yaml:20-21`), so hooks and ask rules committed to the root `.claude/settings.json` (P0-07,
  P0-09) would load there [UNVERIFIED whether the executor skips project settings]; P0-07/P0-09 resolve it with a
  box/container probe through the Hermes checklist and review #12, or exclude Hermes runs with evidence (OC-4). Hermes changes follow the CI-versioned security checklist and a
  security review #12.
- **Connected:** Hermes skills enter the CI static scan (P1-06). P8 evals are DEFER (S2 OPP-41, D-12) until the
  harness can load a Hermes-format skill [Unk].

---

## 3. Value dimensions and mandatory criteria

### 3.1 Mandatory criteria

| Criterion | Today [S1 §4.2, corrected] | Target mechanism | Expected status [Exp] | How measured |
|---|---|---|---|---|
| S (a) no pre-approved shell without isolation, no bypass | met as shipped; not met as operated (`Bash(python3 *)`, `Bash(git *)` local) | owner trims the local allow list (P0-07 owner part); isolation stays DEFER (OPP-36) | improved, not closed: auto mode remains the check for local shell | inventory of local allow entries before/after (owner) |
| S (b) untrusted text to write-capable agents | not met (8 analysts, guardian, scout-agent) | §2.3 | **narrowed, not closed**: no named agent both reads untrusted text and holds write tools; orchestrators still receive derived text (repo-audit merge and `--pipeline`, scout `description`); main-session paths framed + human-gated, structural in P2-06; synthesizer/adapt residual stated | inventory: tools × input source per agent, reviewed in each PR (write-capable direct readers 10 → 0; orchestrator residuals listed) |
| S (c) consequential actions enforced | not met as operated (0 approvals, shared identity, typed `--approve`, self-deploys) | §2.2, §2.8, P0-09 (brain-guard gap G1) | closed at the GitHub boundary after P0-10, as far as part 4 (every path to the owner's authority out of reach, measured in P0-10) holds [Asm]; merging an approved head restricted by GitHub if possible, otherwise an owner-accepted exception (OC-2); local actions only prompted (P0-07) | PRs merged without the owner's code-owner approval on the final push (10 of last 10 → 0; owner-bypass merges counted separately); model-run deploy steps in definitions 3 → 0, other deploy forms a residual (V-S3-12) |
| S (d) unpinned code in shipped default paths | not met (repomix, gitingest; plus the unpinned `npx ecc-agentshield scan --fix` advice at `project-audit/SKILL.md:180` [Ver]) | P0-01, held by P0-02: closed for the known cases, held for `skills/`, `.claude/agents/`, `packs/` and `infra/hermes-agent/skills/` by the required "Test suites" job through `ci-scan-skills.test.js` from P0-02 (B1); no ruleset change needed (owner choice OC-3, revised) | closed for known cases; npx fetch-without-lockfile residual accepted | conformance check red on a fixture; count measured by P0-02's differential (at least 3 known) → 0 |
| C1 own code correct | met with exceptions (installer, brain-guard gaps G1-G5, scan limits, F1 flake) | P0-09, P2-07, P2-08 | exceptions reduced | required CI; named exceptions closed per S5 acceptance criteria |
| C2 produced-work assurance | met for the merge-path floor; not demonstrated above it (V-S1-3) | §2.1, §2.5 | demonstrated on piloted tasks | per-ID verified-at-first-review rate; false completions caught by independent tests (S5 §3) |

### 3.2 Six value dimensions

| Dimension (weight) | How the target serves it | Expected effect [Exp] | Measure (S5 §3) |
|---|---|---|---|
| Engineering quality (30) | code-owned acceptance; independent acceptance tests; tool-restricted reviewer; judge protection; IDs with three states; fresh E12 baselines; guard regression tests | fewer false completions and post-merge fixes; checks known to fail | post-merge `fix(...)` within 7/30 days; false completions per piloted PR; first-pass verified-ID rate; eval pass rate (E12) |
| Autonomy and orchestration (20) | no new orchestration (the only measurement shows none helps [Res P2-D5 P2]); fewer manual links where safe (aggregator, staleness warning); approvals concentrated at decision points (merge, reference gate G1, deploy) | roughly +2-4 prompts per PR from ask rules (more with `gh api`), one approval click per PR (a deliberate cost); fewer rework loops if P1-09 works | intervention count per session (P1-03); review rounds per PR; dispatch accuracy unchanged |
| Productivity (15) | requirement-keyed reference analysis instead of generic breadth (S4 §2.4); reuse decisions recorded | shorter reference-to-plan time than this campaign's generic run (about 5.2 h, no target app [S4 M1]) | spec-to-merge time; S4 M1 |
| Security and reliability (15) | §2.2-§2.4; fail-closed guard; pinned packers; scan scope; Hermes PAT window | the four breach forms reduced as in §3.1 | breach inventory; fail-open entries in `guard-failures.log` (50 on 2026-10-15 [S1 §3.1]) → 0 unguarded calls |
| Maintainability and adaptability (10) | agent definitions +2 −1, skills −1; one deploy rule; doc drift fixed; no hardcoded counts | smaller surface, one eval method | definition count (dynamic `find`); drift items 4 → 0; stale-eval warnings falling |
| Resource efficiency (10) | tokens per accepted result measured; re-baseline staged by tier; verification depth by risk (DECISION-S4-8) | lower verification cost per reference project than the campaign's ~152 findings over three layers | tokens per accepted scenario and per delivery task; correction rounds per reference analysis |

The app-scope question (whether to become a general app-building factory, P2-D5 Q1) is not decided here. The
target is scope-neutral: app-type verification (visual, runtime) attaches to the delivery lane's acceptance layer
when its trigger fires (OPP-37), without changing the spine.

---

## 4. What is explicitly not added

| Not added | Why (evidence) |
|---|---|
| An external orchestration framework or second loop owner (R03 board runtime, R05 runner, R08 loop templates, R09 ADWs, R10 + Archon) | C1 one spine [Res P2-D4 §3.2]; no quality gain measured from scripted control (30/36 vs 29/36) [Res P2-D5 P2]; 10-14 §4 items 15, 19 [S2 R-1, R-2] |
| A second factory subsystem, a reference-driven orchestrator or team | 10-14 rejection; every step has an owner [S4 §3.3, §3.9; S2 R-11]. The one new reference component is a read-only analyst agent, not an orchestrator |
| **Any autonomous merge path** | 10-14 rejection, reaffirmed by the value definition; REVIEW_PROTOCOL "Approve, don't merge" [Ver `docs/REVIEW_PROTOCOL.md:22`]. The design moves the other way: a separate agent account and the owner's approval of the last push. That does not by itself stop the agent account merging an owner-approved head; P0-10 steps 1a-1b check for a GitHub merge restriction (step 5a adopts one), and otherwise that merge is an owner-accepted exception with `allow_auto_merge` kept false (OC-2, §2.2 part 3). Not reopened; no evidence would support it (no researched repository demonstrates safe unattended merges [Res P2-D5 §6.2]) |
| A second task store or Kanban (GitHub Projects) | C8 two truths [S2 R-5] |
| An isolation runtime (Sandcastle) | high churn, permission bypass by default [Res P2-D4 §1.8]; native options unverified (OPP-36 DEFER) |
| A spend-cap mechanism | no baseline; no implementation anywhere (OPP-28 DEFER) |
| Signed evidence, licence scanner, REA, parity gate, visual verification | no consumer yet; DEFER with triggers [S2 §4.2 D-1, D-3, D-4, D-8, D-9] |
| Codex review gate | prohibited by `CLAUDE.md` Codex rules; P3-03 is on-demand and advisory only |
| A second eval methodology | skill-guardian retired for exactly this reason [S1 L-10] |
| Stop hooks for eval staleness | the warning lives in the required CI job instead: no new hook, no fail-open path (OPP-17) |

---

## 5. Alternatives considered

| Choice | Chosen | Alternatives | Why they lost |
|---|---|---|---|
| Closing breach (c) | S2's five parts (separate machine account, owner-only code-owner approval, last-push binding, owner credential out of reach, two rulesets with a role- or team-based owner bypass for owner PRs), preceded by ask rules | (i) ask rules only; (ii) one identity + 1 approval (S1 option c); (iii) separate identity + any 1 approval; (iv) one ruleset with the owner bypass; (v) an out-of-band approval service | (i) prompts are not "a security boundary around the program" [Docs]; (ii) impossible: authors cannot approve their own PRs [Docs], so every merge would block; (iii) any write-access approver the agent can reach would count; (iv) a bypass actor skips every rule in its ruleset, required checks included (V-S3-5); (v) BUILD NEW service with no precedent; native review already binds approval to the PR's last push |
| Judge protection | CODEOWNERS `*` + agent account without Workflows + evaluator pin | (i) run CI from the base branch's workflow (`pull_request_target`); (ii) a separate verification repository | (i) runs base-trusted workflows against untrusted PR code with a write token, a known risk pattern [Asm]; (ii) a second repository is a second subsystem |
| Untrusted readers | tool cuts on existing agents; retire guardian | (i) framing only; (ii) a new "external-reader" agent for all intake now; (iii) container isolation | (i) labelling is not enforcement [Res P2-D5 P7]; (ii) adds a definition before the cheap cuts are measured (kept as P2-06); (iii) external runtime, DEFER |
| Scout split shape (DECISION-S3-2) | skill-scout-agent becomes the read-only fetcher returning fields, a capped description and numeric body features; the calling session scores | (i) S2 OPP-02 (b) as written: the fetch subagents return structured fields and the scout agent keeps Write/Bash/Agent; (ii) pass full bodies to the parent | (i) needs a restricted subagent type that does not exist (none of the 16 agents is WebFetch-only), and the parent's `Agent` tool still spawns all-tool subagents; (ii) re-creates the breach in the writer |
| Reference analysis tools | new `reference-analyst` agent, Read/Grep/Glob, foreground (DECISION-S4-1, S4 V-S4-12 option a) | `claude -p --allowedTools … --permission-mode plan` | `--allowedTools` only pre-approves and plan mode still runs read-only shell [Docs via S4 §3.7] |
| Reviewer | one project agent with Read/Grep/Glob/Bash + tripwire (DECISION-S2-3 c) | built-in Plan type; prompt-only | Plan's prompt is written for planning; prompt-only failed 3/4 [Res] |
| Independent acceptance scope | consequential paths + reference REIMPLEMENT/BUILD NEW, piloted (DECISION-S2-4 c) | all tasks; reference-driven only | all tasks: cost [Unk] before P1-04 data; reference-only misses the factory's own consequential code |
| Measurement | retrospective git/PR + count-only telemetry | an R09-style trace store | R09 stores raw prompts, violating the telemetry rule [S2 §3.2] |
| Reference home | extend pattern-extract (DECISION-S4-1 A) | new skill; repo-audit as analyser (DECISION-S4-6 B) | new component; repo-audit extracts stack signals, has never produced a committed audit [S4 §1.1] |
| Deploy control | staged deploys for every self-sync | keep self-sync with an ask rule only | the ask rule prompts on `cp`, but other forms escape it [Docs]; staging removes the step from the model's workflow (other forms stay a residual) |
| Agent account | reuse `dentaledge-bot` for laptop sessions (DECISION-S3-1 (ii); owner choice OC-1, 2026-10-23) | a new machine account | GitHub's Terms allow one free machine account per person (ToS §B.3) and `dentaledge-bot` already is it, so a new one means deleting the bot or paying; reuse needs no new account (no paid seat is [Asm]: outside-collaborator billing UNVERIFIED). The former objection (one blast radius with Hermes) does not apply while Hermes draft-PR delivery stays dormant (its PAT is recorded to expire 2026-10-23 by the owner's 2026-10-14 decision; refusal to be proved by the owner, P0-10 step 2); restoring delivery needs its own identity |

---

## Limits

- Nothing was executed. Feasibility claims come from reading files at `b8ed8a7`, `grep`, and a read-only `gh api`
  read of the ruleset today. Behaviour of GitHub tokens (Workflows permission; whether a fine-grained token works for
  an outside/repository collaborator), `gh auth switch`, ruleset bypass actors (roles or teams per V-S2-16; user
  eligibility UNVERIFIED because the REST `bypass_actors.actor_type` enum includes `User` and `DeployKey`, R-A-14),
  per-ruleset bypass, a merge restriction to the owner (OC-2), `pull_request_target` risk and WebFetch's
  processing are [Asm] until checked against official docs per `docs/CLAUDE_CODE_KNOWLEDGE.md` and the primary-source
  rule; S2 requires a test PR for the two-ruleset bypass.
- Settings load, corrected in round 2: the Claude Code settings docs (https://code.claude.com/docs/en/settings,
  accessed 2026-10-23) say shared `.claude/settings.json` is read from the session's primary working directory, and
  `.claude/settings.local.json` in a git repository is read and written at the repository root even when the session
  starts in a subdirectory; "In a worktree, it uses the file at the main checkout's root". So the local registration
  is read in `infra/hermes-agent/` and worktree sessions [Docs], but it uses
  `$CLAUDE_PROJECT_DIR/hooks/brain/brain-security-guard.sh` (`.claude/settings.local.json:110`), and the docs define
  that variable as "the project root where the session started", so whether the hook resolves in a subdirectory
  session is UNVERIFIED: coverage may already be absent there today (V2-RS-3). Moving it to the committed root
  `settings.json` may drop coverage for such sessions unless D-11 decides it (OC-4); only the shared-file case needs
  the P0-09 test, which also records what `$CLAUDE_PROJECT_DIR` resolves to (V2-RS-11). Whether the Hermes executor
  (workdir `/projects/claude_code`) skips project settings is UNVERIFIED.
- The Claude in Chrome residual is based on the tools being offered to this session; the extension's site permissions
  were not inspected [Unk]. The desktop built-in browser pane and computer use were not inspected either [Unk].
- This version follows the corrected S1, S2 and S4 (each with its "Verification corrections" section) and the
  verifier's findings on this document. S2's OPP-08 part (1) now also requires a separate machine account (V-S3-4). Expected effects are estimates; S5 §3
  says how each is measured.

## Decisions requiring approval (from this deliverable)

| # | Decision | Options | Recommendation | Evidence |
|---|---|---|---|---|
| **DECISION-S3-1** | Agent account and approval channel for DECISION-S2-1 (c) | **Account:** (i) a new machine account for Claude Code sessions (collaborator with write, not admin; token minted from it; one repository; **no Workflows**); (ii) reuse `dentaledge-bot` (collaborator with write; its old PAT is recorded to expire 2026-10-23 and is not renewed). **Credential placement:** (a) the owner's `gh` login stays on the laptop, guarded by ask/deny rules on `gh auth *`, `gh pr review *`, `gh api *`; (b) the laptop holds only the agent account's credential, after every path to the owner's GitHub authority is enumerated and measured (`gh` login, keychain, SSH keys, environment variables, transcripts, `.env.pr`, Claude in Chrome, the desktop built-in browser pane, desktop computer use); the owner approves and merges in the browser or GitHub mobile outside agent control; no other write-capable token is reachable from sessions; (c) as (b), approvals only from a second device. **Owner-PR bypass actor** (second ruleset, "For pull requests only"; V-S2-16 read roles or teams only, user eligibility UNVERIFIED per R-A-14): (x) the repository admin role, the owner being the only admin; (y) a team whose only member is the owner. Condition for both: the agent account holds no admin role and is in no bypass team | **(ii), (b), (x)** (owner choice OC-1, 2026-10-23; approved in principle until the P0-10 step-1a docs record and step-1b scratch-target test results return, before any production account, token or ruleset step on `main`; R-B-9, V2-ID-1). GitHub's Terms allow "no more than one free machine account in addition to your free Personal Account" and say "the owner of the Account is ultimately responsible for the machine's actions" (ToS §B.3, accessed 2026-10-23); `dentaledge-bot` already is that account, so (i) would mean deleting it or paying, while (ii) needs no new account (no paid seat is [Asm]: outside-collaborator billing UNVERIFIED). The owner let the old PAT expire (decision 2026-10-14, `sessions/daily/2026-10-14.md:35-37`), so Hermes draft-PR delivery is dormant and the "one blast radius" objection does not apply while it stays dormant; restoring delivery needs its own identity (for example a GitHub App), since the account stays single-consumer (`canon/2026-08-17-credential-governance-lessons.md:49-52`). Token: a fine-grained token is tested first in step 1b (it is a documented gap for outside/repository collaborators, against counter-evidence: PR #4, `.env.pr.example`, `README.md:315-318`); otherwise a classic PAT with `repo` and no `workflow` scope, after step 1a confirms the org's classic-PAT policy [Asm]. A classic `repo` token also acts as the bot on any public repository and in its own namespace and gains any repository the bot is later added to; the owner is responsible (ToS §B.3; V2-ID-7). The owner approves the token if the org requires approval. Owner steps first: prove the expired PAT dead without printing it (`credential-governance-lessons.md:136-137`) and remove it from `infra/hermes-agent/.env.pr`. Access is measured, never asserted (probe (g), re-run at every rotation; `canon/2026-08-18-credential-access-levels-are-measured-never-asserted.md:12`). (a) leaves the boundary as rules that are not a boundary [Docs]. (c) if (b)'s browser and desktop control cannot be verified. (x) needs no team; (y) if more admins are ever added. The bypass lives only in the review ruleset, so the checks ruleset keeps no bypass (V-S3-5) [Asm: verify with a test PR, as S2 requires]. A token minted by the owner is excluded: it acts as the owner (V-S3-4) | ruleset read today (0 approvals, no code-owner review, `require_last_push_approval` and `dismiss_stale_reviews_on_push` false, bypass `[]`); S1 L-03 (`gh` login, scopes, `settings.local.json:10,63,68`); `infra/hermes-agent/.env.pr.example:2`; `README.md:315-318`; `2026-10-14-review-11-rollout.md:144`; [Docs via S2] author self-approval forbidden, rulesets aggregate, PR-only bypass; V-S2-16 bypass actor types; Claude in Chrome tools offered to this session [Ver, machine-local]; round 2: GitHub ToS §B.3 and "Managing personal access tokens" [Docs, accessed 2026-10-23]; `.project-brain/sessions/daily/2026-10-14.md:35-37`; `gh api users/dentaledge-bot` and collaborator roles [Ver by the coordinator, 2026-10-23] |
| **DECISION-S3-2** | Shape of the scout privilege split (refines S2 OPP-02 b) | (a) skill-scout-agent becomes Read/WebFetch/WebSearch and returns schema fields, a length-capped `description` and numeric body features (keyword hits against the caller's trigger keywords), never the body; the calling session writes the JSON and runs `score-candidates.js`, which gains an optional numeric body-match input (TDD); (b) S2's form: restricted fetch subagents under a scout agent that keeps Write/Bash/Agent; (c) framing only | **(a).** No new definition; removes `Agent`, `Write`, `Bash` from the reader. Residual stated: the capped description reaches the writer, and skill-audit later reads the chosen body in the main session (V-S3-6). Re-run agent-audit and agent-eval (dispatch accuracy ≥ 85%) | `skill-scout-agent.md:32,58-84` [Ver]; `score-candidates.js:13,122-127` reads `description` and `skill_md_content` [Ver]; Hermes B.1 closed key sets [S1 ST-7] |
| ~~DECISION-S3-3~~ | Folded into **DECISION-S4-3** option (i) (clone posture), which is the same choice (V-S3-9) | — | Decide it there. S3's amendment travels with it: `reference-repo-add`'s "never clone" rule is rescoped to registration | `reference-repo-add/SKILL.md:6,33` [Ver]; S4 §3.7, DECISION-S4-3 |
| **DECISION-S3-4** | Where outcome baselines live | (a) only gitignored `evals/` artifacts; (b) dated tracked records in `docs/evaluations/` with numbers, method and sources (no prompt text, no client data), raw data staying in `evals/` | **(b).** Later phases must compare against a versioned baseline; generated eval artifacts are never committed (`CLAUDE.md` Never list; the scenario specs, `evals/.gitignore` and `evals/project-context.json` are tracked, see S5 P0-04, R-B-10, V2-RS-4) | value definition measures; `CLAUDE.md:76`; S2 OPP-25 |
| **DECISION-S3-5** | The canon charter names `skill-guardian` as a capability (`.project-brain/canon/2026-07-17-ai-os-charter.md:33` [Ver]); retiring it (P0-04) leaves canon stale (V-S3-11) | (a) accept the stale reference until the owner's charter decision, recorded as a known stale item; (b) the owner amends that line now through `brain-promote --approve` | **(a)**, consistent with DECISION-S2-9 (charter unchanged until the owner decides). Never edited directly; the P0-04 grep excludes `canon/` | charter `:33`; value definition (charter unchanged); promotion-only canon (BRAIN.md) |

Referenced, not renumbered: DECISION-S1-1 (superseded by DECISION-S2-1), DECISION-S1-2 / S2-2 (guard), DECISION-S1-3
(retire guardian, option c), DECISION-S1-4 = DECISION-S2-5 = DECISION-S4-7, option (b) (gstack timing; one decision),
DECISION-S1-5 (staged deploys, widened per V-S1-2 to skill-adapt, skill-refine-agent and `CLAUDE.md:75`),
DECISION-S2-1 (b now, c next: S2's five parts), DECISION-S2-3 (reviewer), DECISION-S2-4 (acceptance scope),
DECISION-S2-6 (scan required), DECISION-S2-7 (scout scoring), DECISION-S2-8 (measure first), DECISION-S2-9 (charter
status line), DECISION-S4-1 … 8 (DECISION-S4-3 includes the clone posture). Not reopened: the 2026-10-14 rejections,
Track A, D3.2, the charter.

## Verification corrections (2026-10-22)

Each finding was re-checked in the repository or against the corrected S1, S2 and S4 before it was applied. All were
accepted; none is disputed. The coordinator's V-S2-16 note was applied at the same time.

- **V-S3-1** (confirmed, S4 Increment 1 change 4): agent definitions are now +2 (reviewer, `reference-analyst`) and
  −1 (skill-guardian), skills −1 (gstack-pattern-audit) in §0 item 1, §2.9, §3.2 and §4. `reference-analyst` is
  added to the diagram, §1.3, §2.3 and §2.4, with enforcement by the frontmatter `tools` allowlist.
- **V-S3-2** (confirmed: `claude-code-proposer/SKILL.md:42`, and the same flags at `run-ads-audit.sh:25`,
  `bin/run-client-audit.py:82`; docs via S4 §3.7): §1.4 and §2.3 now describe the Hermes agents as read-only by mode,
  `:ro` mounts and missing credentials, not by tool list. `--tools 'Read,Grep,Glob'` for the proposer is added to
  §1.3, §2.10 and P1-16.
- **V-S3-3** (confirmed: `gh api` shows `dismiss_stale_reviews_on_push` and `require_last_push_approval` false):
  §2.2 part 3 sets both to true and states the residual (an approved head can be merged by the agent account, only
  prompted).
- **V-S3-4** (confirmed: `.env.pr.example:2`, `README.md:315-318`, `2026-10-14-review-11-rollout.md:144`): the agent
  identity is now a separate machine account; owner-minted tokens are excluded; reuse of `dentaledge-bot` is an
  option in DECISION-S3-1 (recommended against); bot-to-bot approval is blocked by CODEOWNERS `*` + code-owner review.
  **Decision change: DECISION-S3-1 is rewritten.**
- **V-S3-5** (resolved against S2's two-ruleset design and V-S2-16): the owner bypass lives only in a second, review
  ruleset, and its actor is the admin role (owner only admin) or an owner-only team, never a user account; the checks
  ruleset keeps no bypass, so §1.4's strength holds for the checks [Asm: test PR]. §2.2 part 5, §5 and DECISION-S3-1.
- **V-S3-6** (confirmed: `score-candidates.js:13,122-127`): the scout reader returns schema fields, a capped
  description and numeric body features, never the body; the scorer gains a numeric input; the residual is stated.
  **DECISION-S3-2 option (a) is redefined.**
- **V-S3-7** (confirmed via S2 OPP-02: `repo-audit/SKILL.md:4,127-128,210-222`): the repo-audit row now states the
  orchestrator residual, with closed-key and length validation assigned to P2-06.
- **V-S3-8** (confirmed: `run-all-tests.js:4,17-19`): CODEOWNERS `*` covers test files; the explicit judge-path list
  now includes the test globs, `skills/skill-audit/scripts/` and `hooks/brain/`, aligned with S5 P1-05.
- **V-S3-9** (confirmed: DECISION-S4-3 option (i)): DECISION-S3-3 is folded into DECISION-S4-3, keeping the
  "never clone" rescoping amendment. **Decision change: DECISION-S3-3 withdrawn.**
- **V-S3-10** (confirmed: S4 V-S4-13): §2.9 now says uninstall removes only the empty registry it created and keeps
  a registry with entries, with a warning.
- **V-S3-11** (confirmed: `canon/2026-07-17-ai-os-charter.md:33`): **new DECISION-S3-5** (accept the stale charter
  reference until the owner's charter decision, or amend through `brain-promote --approve`).
- **V-S3-12**: §0 item 5, §2.1, §2.8 and §3.1 now say "model-run deploy steps in definitions 3 → 0", with the
  other-forms residual.
- **V-S3-13**: [Inf]/[Docs] added to the legend; "retires 2" split into agents and skills; the skill-refine-agent
  deploy step is `:124` (`:72` explains); the P1-05 probe uses a non-workflow judge path (S5).
- **Trailing nits**: §1.3 now has a P1-15 row; DECISION-S4-7 is named with DECISION-S1-4 and DECISION-S2-5 as one
  decision.
- **Alignment with corrected S2**: breach (b) "narrowed, not closed"; ask rules add `gh pr review *` and `gh api *`,
  and the local `Bash(git *)` allow is removed; OPP-09 covers all three deploy paths and `CLAUDE.md:75`; OPP-19
  carries the registry, analyst agent, installer change and clone posture; OPP-41 is DEFER; DECISION-S2-9 referenced.
  S2's OPP-08 part (1) has since been aligned to the same "separate machine account" wording.
- V-S3-14 (coordinator): the stale notes about S2 OPP-08 part (1) are updated; S2 now requires a separate machine account.

### Round 2 (2026-10-23)

- OC-1: §0 item 3, §1.3 identity row, §2.2 part 1 (account is `dentaledge-bot`; ToS §B.3; expired PAT not renewed; classic PAT default with fine-grained only if shown to work), the Hermes bullet in §2.2 (delivery dormant; restoration needs its own identity; single-consumer account), §2.10 (`/proc` work conditional on restoration), §5 "Agent account" row (reuse chosen; a new machine account lost) and DECISION-S3-1 (recommendation now (ii), (b), (x), with rationale, token type, owner steps and evidence).
- OC-1 measurement (R-B-2): §2.2 adds that access is measured, never asserted (probe (g), re-run at every rotation), citing both credential canon entries.
- OC-1 credential paths (R-B-3, R-A-9, R-A-10): §2.2 "Why the credential's reachability matters" now lists keychain, SSH keys, environment variables, transcripts, `.env.pr`, the desktop built-in browser pane and computer use, and the Read/Edit-only reach of the `.env.pr` deny rules; DECISION-S3-1 (b) and Limits match.
- OC-2 (R-B-8): §2.2 part 3 residual, §3.1 (c) and the §4 "autonomous merge path" row now say the agent's merge of an owner-approved head is restricted by GitHub if possible, otherwise an owner-accepted exception to `REVIEW_PROTOCOL.md:22`.
- OC-3: §1.3 CI static scan row and §3.1 (d) now say breach (d) is held only once the scan job is required (P1-06 in P0).
- OC-4: §1.3 brain-guard row and §2.10 (committed settings reach Hermes runs) updated; Limits replaces the untested settings-load inference with the settings docs (accessed 2026-10-23) and states the subdirectory-coverage consequence.
- R-A-14: §2.2 part 5, DECISION-S3-1 and Limits mark user bypass-actor eligibility as UNVERIFIED; recommendation (x) unaffected.
- R-B-9: DECISION-S3-1 is marked approved in principle until the P0-10 step-1 record returns.
- R-B-10: DECISION-S3-4 now reads "generated eval artifacts are never committed".
- R-B-11: §1.3 ask-rule row adds running `install.sh`/`uninstall.sh`.
- R-A-18: §1.3 brain-guard row says "brain-guard gaps G1 and G3".

### Round 3 (2026-10-23)

- V2-RS-1: the §1.3 CI static scan row and §3.1 (d) now say the BLOCK rule in `static-scan.js` is already held for `skills/` by the required "Test suites" job through `scripts/ci-scan-skills.test.js:104-110`, and for agents, packs and Hermes skills only once "Static scan all skills" is required (D-15) or that test is extended.
- V2-RS-2: §2.1 rows now read "brain-guard gap G1" (canon promotion) and "reference gate G1" (reuse verdicts); §3.1 (c) reads "P0-09 (brain-guard gap G1)"; §3.2 autonomy row reads "reference gate G1"; §3.1 C1 reads "brain-guard gaps G1-G5".
- V2-RS-3, V2-RS-11: Limits' settings-load bullet cites the docs for the worktree local file, notes the current registration's `$CLAUDE_PROJECT_DIR` path (`.claude/settings.local.json:110`, resolution in a subdirectory UNVERIFIED), says coverage may already be absent today, and leaves only the shared-file case for the P0-09 test.
- V2-RS-4: DECISION-S3-4 adds `evals/project-context.json` to the tracked list.
- V2-ID-1: §2.2 part 3 and DECISION-S3-1 refer to P0-10 steps 1a (docs) and 1b (scratch-target tests, never `main`), returned before any production step on `main`.
- V2-ID-2: the §2.2 measured-access bullet now names the review-ruleset `current_user_can_bypass` check (agent `never`, owner `pull_requests_only`), non-mutating admin-only reads, a named private org repository and the `p0-10-probe/**` workflow push.
- V2-ID-3: §2.2 part 3 and the §4 autonomous-merge row compare the two merge-restriction candidates, add step 5a and keep `allow_auto_merge` false in the exception.
- V2-ID-5: §2.2 part 1, the §5 "Agent account" row and DECISION-S3-1 say the PAT is "recorded to expire 2026-10-23" (refusal to be proved by the owner); "no seat" is tagged [Asm] (outside-collaborator billing UNVERIFIED).
- V2-ID-6: §2.2's "other bot token" bullet notes the old token is recorded dead and the bot, now the agent account, cannot approve its own PRs either.
- V2-ID-7: §2.2 part 1 and DECISION-S3-1 test a fine-grained token first, cite the counter-evidence, and state the classic `repo` token's reach beyond org repositories and the ToS §B.3 responsibility.
- V2-ID-8: the §1.3 identity row and §2.2 part 2 add `required_approving_review_count: 1`.
- V2-ID-9: the "Workflows permission as judge protection" paragraph says CI changes travel as owner-authored PRs made outside agent sessions and merged through the PR-only bypass, which skips review; the owner never pushes to agent branches.
- R-A-1, R-A-2, R-B-4 (folded into OC-1 in round 2): §2.2 part 1 now names them.

### Round 4 (2026-10-23)

- OC-3 (revised): the §1.3 P0-02 row and §3.1 (d) now read "closed for the known cases, held for `skills/`, `.claude/agents/`, `packs/` and `infra/hermes-agent/skills/` by the required 'Test suites' job through `ci-scan-skills.test.js` from P0-02 (B1); no ruleset change needed"; the §1.3 P1-06 row describes only the general scan made required under D-15 (before P1).
- V3-ID-1: the §2.2 measured-access bullet adds that probe (g) runs after the step-1b test rulesets and probe branches are deleted, with a control push of a non-workflow file and GitHub's refusal message recorded; §2.2 part 3 says test rulesets and probe branches are deleted after the test.
- V3-ID-2: §2.2 part 3 says the step-1b layering mirrors `main`, the required check is emulated by a commit-status test context (CI does not run on PRs into `p0-10-probe/**`, `ci.yml:3-7`), and a failed probe (i) means the owner removes the step-5a restriction at once and records the exception.
- V3-ID-3: §2.2 part 3's "Restrict updates" candidate uses the repository admin role (owner the only admin) or an owner-only team as bypass actor, not "the owner".
- V3-ID-5: the §2.2 "other bot token" bullet says the old token is "recorded to expire 2026-10-23", with its refusal to be proved by the owner (P0-10 step 2).

### Round 5 (2026-10-23)

- V4-RS-1: the §1.3 P0-02 row reads "through a conformance-only pass over the extra scopes"; the §1.3 P1-06 row reads "(P0-02 adds only a conformance-only pass there)".
- V4-RS-2: the §1.3 P1-06 row adds that `.claude/agents/` and `packs/*/tools/` are not added to the general scan (Security gate over `.claude/`; `pack-audit.js` on demand), both covered for unpinned installs by P0-02.
- V4-ID-2: §2.2 part 3 now reads "If one works … it is adopted (step 5a). If none works, or probe (i) fails on `main` (the owner then removes the step-5a restriction at once, V3-ID-2), this residual is an explicit owner-accepted exception to …".
- V4-ID-3: the §2.2 measured-access bullet says there are no write attempts beyond the two probe pushes (workflow and control), and the probe branch is deleted afterwards.
