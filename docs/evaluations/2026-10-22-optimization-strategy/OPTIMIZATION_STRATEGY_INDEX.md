# Optimization strategy index: Consolidated Optimization Strategy (phase 3)

> **Date:** 2026-10-22 · **Phase:** 3 of 3 of the Software Factory evaluation campaign · **Status:** the owner
> approved D-01 … D-14 as written on 2026-10-23; D-15 … D-28 are still open; nothing implemented yet.
> **Subject:** `DentalEdge-Solutions/claude_code` at `b8ed8a7`.
> **Framework:** the owner's Software Factory value definition (active decision
> `.project-brain/decisions/active/2026-10-22-software-factory-value-definition-the-yardstick-for-the-eval.md`;
> verbatim text in `.project-brain/support/sources/software-factory-value-definition-2026-10-22.md`).
> **Research it rests on:** phase 1, [`../2026-10-22-factory-research/RESEARCH_INDEX.md`](../2026-10-22-factory-research/RESEARCH_INDEX.md)
> (11 repository deep dives); phase 2, [`../2026-10-22-factory-comparison/COMPARATIVE_RESEARCH_INDEX.md`](../2026-10-22-factory-comparison/COMPARATIVE_RESEARCH_INDEX.md)
> (five comparative deliverables).

## Deliverables

| # | Deliverable | What it contains |
|---|---|---|
| S1 | [Current Architecture & Gap Analysis](S1-current-architecture-gap-analysis.md) | The factory as it is today, verified in the repository; strengths to preserve; limitations and open debts; ratings on the phase 2 scale; 23 gaps (GAP-01 … GAP-23), three of them mandatory-criterion breaches |
| S2 | [Consolidated Optimization & Capability Reuse Matrix](S2-optimization-reuse-matrix.md) | 41 opportunities (OPP-01 … OPP-41) with a verdict each (ADAPT 14, REIMPLEMENT 11, REUSE 5, BUILD NEW 3, DEFER 6, REJECT 2), rationale against the owner's eight criteria, REJECT and DEFER lists |
| S3 | [Optimized Target Architecture](S3-optimized-target-architecture.md) | The target as an evolution of the current architecture: what is kept, strengthened, connected, added (two agent definitions) or retired (one agent, one skill); approval and identity model; untrusted-input handling; alternatives considered |
| S4 | [Reference-Driven Engineering Integration Strategy](S4-reference-driven-engineering-strategy.md) | How supplied reference repositories become a standard input: intake, licence and provenance, capability map keyed to requirement IDs, the REUSE … REJECT decision, verified integration, owner gate; increments I1–I4 |
| S5 | [Prioritized P0–P3 Implementation Roadmap](S5-prioritized-roadmap.md) | 41 roadmap items (P0 11, P1 17, P2 10, P3 3) with acceptance criteria, baselines, tests, rollback and dependencies; batches B0–B5 for P0; measurement plan for the owner's metrics |
| S6 | [Strategic Optimization Report](S6-strategic-optimization-report.md) | Plain-language executive summary; expected benefits; risks and residuals; alternatives; the app-scope question; time-sensitive items; the consolidated decision register D-01 … D-28 |

**Where to start:** S6 §1 (executive summary), §6 (time-sensitive items) and §7 (decisions). S6 §8 maps each
decision to its sources and roadmap items.

## How to read the deliverables

- **Evidence tags:** [Ver] verified in claude_code now (with path:line) · [Res] from phase 1 or phase 2 research ·
  [Docs] official Claude Code or GitHub documentation (cited with access date) · [Exp] expected benefit, with how it
  will be measured · [Asm] assumption · [Inf] inference · [Unk] unknown. Expected benefits are never presented as
  verified.
- **Citations:** `[Rnn §x]` a phase 1 report; `[P2-Dn §x]` a phase 2 deliverable; `[Sn §x]` a phase 3 deliverable.
- **Identifiers:** GAP-nn (S1), OPP-nn (S2), P0-nn … P3-nn (S5), DECISION-Sn-m (in S1–S5), D-nn (S6's consolidated
  register, which merges duplicates; S6 §7 gives the mapping).
- **Corrections:** each deliverable ends with "Verification corrections (2026-10-22)" listing every change made after
  independent verification.

## Key conclusions (detail in S6 §1)

1. **Keep and strengthen; do not rebuild.** The factory is ahead of all 11 researched projects on governance,
   behavioural evals and Hermes security. No external framework is adopted; none of the 21 external components that
   passed phase 2's filters fills a real need here.
2. **The mandatory criteria are not met today.** Four breach forms, P0 acting on three: untrusted text reaching
   agents that can write, unpinned downloads at run time, and human approval that is a habit rather than a lock; the
   fourth, pre-approved local shell without isolation, is only trimmed. Correctness of
   produced work is shown only at the CI floor.
3. **P0 (11 items) acts on those three.** Unpinned downloads: closed
   for the known cases, held for `skills/`, `.claude/agents/`, `packs/` and `infra/hermes-agent/skills/` by the
   required "Test suites" job through `ci-scan-skills.test.js` from P0-02 (B1); no ruleset change needed (owner
   choice OC-3, revised). Approval: closed at the GitHub boundary only while every
   path to the owner's GitHub authority stays out of the agent's reach [Asm until measured in P0-10], with stated
   residuals the owner accepts explicitly (S6 D-01). Untrusted text: narrowed, not closed. Pre-approved local shell
   stays open beyond trimming the allow list.
4. **Research-led choices.** No new orchestrator (orchestration did not buy quality); checks written apart from the
   builder and reviewers that cannot edit (where the acceptance decision sits matters most); measure first, because
   none of the owner's outcome measures is measured yet.
5. **Reference-driven engineering becomes standard with small changes:** an app mode in the existing
   `reference-repo-pattern-extract`, three templates, requirement IDs, a licence field, one read-only analyst agent
   and an owner approval gate before planning.
6. **The app-scope question stays the owner's (D-28).** No repository demonstrated building arbitrary applications
   end to end; the suggested path is to decide on measured evidence.

## Decisions requiring approval

28 decisions (S6 §7): D-01 … D-27 consolidate the 31 numbered source decisions in S1–S5, and D-28 is the unnumbered
app-scope decision from S5 §1.5:
- **Decide now, to start P0:** D-01 … D-14 (including D-01 the P0 package, D-09 prompts for consequential commands,
  D-10 staged skill deploys, D-11 brain guard fail-closed, D-12 and D-13 the approval lock and agent account).
- **Decide before P1:** D-15 … D-22 (D-15, the required general skill scan, returned here by owner choice OC-3,
  revised, with its number unchanged).
- **Later:** D-23 … D-28.

**Owner choices of 2026-10-23 (S6 §7):** OC-1, D-13: reuse `dentaledge-bot` as the laptop agent's account
(a fine-grained token tested first on a scratch target, otherwise a classic PAT without `workflow` scope; access measured and re-run at every rotation). OC-2, D-12: check
first whether GitHub can restrict merging into `main` to the owner; otherwise the agent's merge of an owner-approved
head is an owner-accepted exception to "Approve, don't merge". OC-3 (revised the same day, superseding the first
OC-3 that moved D-15 into P0): P0-02 holds breach (d) for every scope through the required "Test suites" job, and
D-15 stays before P1, covering only the general scan of packs and Hermes skills. OC-4, D-11: kept, and it
explicitly supersedes the earlier fail-open policy (P11) and the non-adoption of `onFailure: "block"`.

Several need the owner's own action (GitHub settings, a new token for the existing `dentaledge-bot` account, the
dead-token check and `.env.pr` cleanup, the local allow list, credential storage, skill deploys from B1). Decisions
that change governance or touch canon are marked in S6 §7.

**Time-sensitive (S6 §6):** the Hermes `dentaledge-bot-pat` expires 2026-10-23; the owner decided on 2026-10-14 to
let it expire, not renewed, so Hermes draft-PR delivery is dormant from that date and the bot becomes the laptop
agent's account (OC-1); before a new token is minted the owner proves the old one is refused and removes its value
from `infra/hermes-agent/.env.pr`. The Hermes proposer and Ads audit runs pre-approve read tools but do not remove
Bash (P1-16 hardens the proposer and considers the Ads audits); Hermes API key rotation is still open.

## Verification record

| Item | Verification | Findings | Status |
|---|---|---|---|
| S1 | independent verifier, ~60 claims re-checked | V-S1-1 … V-S1-17, plus four coordinator alignments (incl. V-S6-2, V-S6-16) | closed; accurate |
| S4 | same verifier, ~40 claims | V-S4-1 … V-S4-15 | closed; accurate |
| S2 | second verifier; official GitHub and Claude Code docs re-read | V-S2-1 … V-S2-19 (V-S2-1, -2 and -16 security design) | closed |
| S3 | third verifier, 29 [Ver] claims; official docs | V-S3-1 … V-S3-14 | closed; accept |
| S5 | same verifier | V-S5-1 … V-S5-16 (V-S5-4 reopened once) | closed; accept |
| S6 | independent verifier; repo citations re-checked | V-S6-1 … V-S6-16 | closed; accept |
| This index | same verifier | V-IX-1 … V-IX-7 | closed; accept |
| Rounds 2-6 (2026-10-23): D-01 … D-14 review and corrections to S1-S3, S5, S6 and this index | two independent reviewers of D-01 … D-14 (completeness and correctness; alignment with governing rules), then two independent verifiers of the edits (identity, credentials and GitHub; everything else); official GitHub and Claude Code docs re-read; live GitHub settings read-only | R-A-1 … R-A-19, R-B-1 … R-B-18; owner choices OC-1 … OC-4 (OC-3 revised); V2-ID-1 … V2-ID-9, V2-RS-1 … V2-RS-12, V3-ID-1 … V3-ID-5, V3-RS-1 … V3-RS-2, V4-ID-1 … V4-ID-3, V4-RS-1 … V4-RS-2, V5-RS-1 … V5-RS-2, V6-RS-1 | closed; both verifiers accept |

Each deliverable, and this index, records its corrections in its own "Verification corrections (2026-10-22)" section. Claim counts
and closures are from the verifiers' returns to the coordinator. Round 2 (2026-10-23): two independent reviews of
D-01 … D-14 (findings R-A-n, R-B-n) and four owner choices (OC-1 … OC-4) were applied by the editor; each changed
file lists them under "Round 2" … "Round 6 (2026-10-23)" sub-headings. These round 2-6 edits were verified and closed
on 2026-10-23 by two independent verifiers (row above); the round 5 and 6 fixes to S5 and S6 were partly made by the
coordinator and checked by the verifiers.

**Process notes, disclosed.** Nothing in the project was modified; only these research files were written. No
external code was executed. Verifiers read local settings files and reported only non-secret keys. The coordinator
made small alignment edits to S1, S2, S3, S5 and S6 after verification, each recorded in that file's corrections
list or noted in S6 §9; one coordinator command was blocked by the brain guard as a false positive (its text named
the canon folder while editing only `docs/evaluations/`), and the edits were redone with the editing tool. One
analyst renamed six references in S2 with a single `sed` command (disclosed in S2).

## Limits

- Nothing was executed. Several points stay unverified until P0-10's step-1a docs record and step-1b scratch-target tests: GitHub token semantics
  (including whether the Workflows permission blocks pushes to `.github/workflows`, how tokens minted from the
  agent account behave, and whether a fine-grained token works for an outside/repository collaborator), the
  two-ruleset bypass interaction and bypass-actor eligibility (user accounts UNVERIFIED), whether merging can be
  restricted to the owner (OC-2), `gh` multi-account behaviour, and whether the browser and desktop channels
  (Claude in Chrome, the desktop built-in browser pane, computer use) reach github.com (S5 and S6 Limits). Whether
  the Hermes executor skips project settings is also unverified (P0-07, P0-09).
- Expected benefits are estimates; S5 §3 defines how each will be measured. Many baselines must be measured first:
  some in batch B0, others from the first P1-10 runs, the first 30 days after P1-03, the first 5 tasks after P1-04, or
  the first P1-14 project.
- The plan depends on owner-only actions. Until P0-07 merges and the owner trims the local allow list there are not
  even prompts; until P0-10's owner actions are done, the approval lock is prompts only.
- Phase 1 and phase 2 limits carry over (see their indexes).

## Verification corrections (2026-10-22)

- V-IX-1: the decision count now reads D-01 … D-27 from the 31 numbered source decisions, plus D-28 (unnumbered, S5 §1.5).
- V-IX-2: Limits now lists every point that stays unverified until P0-10 (token semantics, bypass interaction and actor eligibility, `gh` multi-account, Claude in Chrome), matching S5 and S6.
- V-IX-3: key conclusion 2 now names four breach forms, with P0 acting on three.
- V-IX-4: this section added; S6 carries its own.
- V-IX-5: the baseline sentence now names when each kind of baseline is measured.
- V-IX-6: the approval-lock limit now says there are no prompts until P0-07 merges and the local allow list is trimmed; P1-16 hardens the proposer and only considers the Ads audits.
- V-IX-7: the S1 row now counts four coordinator alignments; S6 and index rows closed after the closure check.

### Round 2 (2026-10-23)

- OC-1: the time-sensitive paragraph now records the owner's 2026-10-14 decision to let `dentaledge-bot-pat` expire (delivery dormant), the bot's reuse as the laptop agent's account, and the dead-token and `.env.pr` owner steps; the owner-action sentence says "a new token for the existing `dentaledge-bot` account" instead of a new machine account.
- OC-2: an "Owner choices of 2026-10-23" paragraph is added under the decisions; the Limits list adds the merge-restriction check.
- OC-3: "decide now" is D-01 … D-15 and "before P1" is D-16 … D-22; key conclusion 3 notes P1-06 runs in P0 as PR-10 and that (d) holds once the scan job is required.
- OC-4: the owner-choices paragraph records that D-11 supersedes the P11 fail-open policy; Limits adds the unverified Hermes settings load.
- R-B-3 / R-A-14: Limits adds the fine-grained-token collaborator gap, user bypass-actor eligibility as UNVERIFIED, and the desktop browser pane and computer use alongside Claude in Chrome.

### Round 3 (2026-10-23)

- V2-RS-1: key conclusion 3 now says the unpinned-download fix is already held for `skills/` (all known cases) by the required "Test suites" job, and for agents, packs and Hermes skills only once "Static scan all skills" is required (D-15) or that test is extended.
- V2-ID-1, V2-ID-7: the OC-1 summary says a fine-grained token is tested first on a scratch target, otherwise a classic PAT without `workflow` scope.
- V2-RS-12: the round 2 "not yet verified" wording is left unchanged until round 3 verification closes; the coordinator adds the verification-record row.

### Round 4 (2026-10-23)

- OC-3 (revised by the owner): "decide now" is D-01 … D-14 and "before P1" is D-15 … D-22; key conclusion 3 says breach (d) is held for all four scopes by the required "Test suites" job from P0-02 (B1), with no ruleset change; the owner-choice paragraph records the revision and that it supersedes the first OC-3.
- V3-ID-4: Limits now says "until P0-10's step-1a docs record and step-1b scratch-target tests".
- V3-RS-2: the verification-record paragraph says the round 2, round 3 and round 4 edits are not yet verified by an independent reviewer.

### Round 6 (2026-10-23, coordinator edits)

- Verification record: added the rounds 2-6 row; the verification paragraph now says the round 2-6 edits were verified and closed by two independent verifiers.
