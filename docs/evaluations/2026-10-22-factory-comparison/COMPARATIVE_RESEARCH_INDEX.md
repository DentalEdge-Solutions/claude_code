# Comparative research index: Comparative Architecture Intelligence (11 repositories)

> **Date:** 2026-10-22 · **Phase:** 2 of 3 of the Software Factory evaluation campaign. Phase 1 (Individual
> Repository Deep Dives) is in [`../2026-10-22-factory-research/`](../2026-10-22-factory-research/RESEARCH_INDEX.md);
> phase 3 (Consolidated Optimization Strategy) decides applicability to `DentalEdge-Solutions/claude_code`.
> **Framework:** the owner's Software Factory value definition (active decision
> `.project-brain/decisions/active/2026-10-22-software-factory-value-definition-the-yardstick-for-the-eval.md`;
> verbatim text in `.project-brain/support/sources/software-factory-value-definition-2026-10-22.md`).
> **Scope rule for this phase:** independent comparative research. No changes to `claude_code` (other than these
> research files), no dependencies installed, no external code executed, no project-specific adoption decisions.
> Reuse verdicts are generic and provisional ("candidate verdicts").

## Deliverables

| # | Deliverable | What it contains | Size |
|---|---|---|---|
| 1 | [Comparative Architecture Matrix](01-comparative-architecture-matrix.md) | Category grouping and which comparisons are meaningful; master matrix of all 11 over every dimension; execution-model comparison (deterministic, autonomous, hybrid, skill-driven); per-dimension ratings, not aggregated; mapping to the six value dimensions with mandatory security and correctness verdicts | 575 lines |
| 2 | [Capability & Engineering Matrix](02-capability-engineering-matrix.md) | 33 capabilities in 8 groups with a per-repository heatmap; strongest implementation, runner-up and claimed-but-not-implemented per capability; engineering-practice comparison; gaps across all 11 | 1,488 lines |
| 3 | [Best-Practice Assessment](03-best-practice-assessment.md) | 35 candidate practices with evidence strength (Validated (T: tests / M: measurements) / Implemented / Prompt-only / Claimed), advantages, limits and cost; 17 anti-patterns; the evidence base for value; the four execution models as practices | 878 lines |
| 4 | [Cross-Repository Reuse & Compatibility Matrix](04-reuse-compatibility-matrix.md) | 175 component rows with licence, dependencies, security notes, verification status and candidate verdict; overlaps; compatibility and conflicts; composition opportunities with effort, risks and maintenance; licence and provenance summary | 1,000 lines |
| 5 | [Architecture Intelligence Report](05-architecture-intelligence-report.md) | Executive summary; consolidated findings by theme; innovations (§2.10); synergies; architectural principles with evidence strength; generic optimization opportunities; implementation leverage, best approaches and trade-offs (§5a); evidence on the general app-building question (facts only); open questions for phase 3; cross-deliverable reconciliation; consolidated phase 1 errata | 958 lines |

**Where to start:** the Architecture Intelligence Report's executive summary (§1), then §7 (open questions for
phase 3). The four other deliverables hold the evidence the report cites.

## How to read the deliverables

- **Evidence tags:** [Obs] observed (verified [F] in a phase 1 report or re-verified in the clone) · [Docs]
  official Claude Code docs · [Claim] unverified project claim · [Inf] inference · [Unk] unknown.
- **Traceability:** statements cite a phase 1 report and section as `[R07 §11]`, a phase 2 deliverable as
  `[D4 §2.3]`, the phase 1 index as `[R-index …]`, and, where decisive, the repository path and line at the
  evaluated commit. Evaluated commits are in the phase 1 index and each report's header. **Label clash:** a
  bracketed `[Dn §x]` always means deliverable n. Bare codes inside the deliverables are different: D1–D15 in
  deliverable 1 are its rating dimensions, and A1–H2 (including D1–D6) in deliverable 2 are its capability codes;
  for example deliverable 5 X7 reads "D1 D6 Adequate; D2 D1 W" (deliverable 1 dimension D6 vs deliverable 2
  capability D1).
- **No cross-category ranking.** Comparisons stay within comparable groups. Deliverable 1 §1 uses seven overlapping
  purpose groups (G1–G7); deliverable 5 §0 uses three (G-ORCH orchestration factories, G-PACK skill and agent
  packs, G-RE reverse engineering) and explains how the two schemes fit together. Ratings use qualitative scales
  (Strong / Adequate / Weak / Absent / Unknown / n/a in deliverable 1; S / A / W / – / U / n/a in deliverable 2,
  with `b:` marking a branch-only rating) and are never summed across categories. Deliverable 1 §4d and
  deliverable 2's §1 note map the two scales: on the mapped cells they differ in four places (R08 approval gates,
  R09 permission model, R06 and R07 cost), all due to different capability boundaries; deliverable 2's A4 (timeout
  and failure recovery) is compared only partly, and deliverable 1 §4d names the three cells that differ there.
- **Licence rule:** code with no licence is never a REUSE or ADAPT candidate as code; at most REIMPLEMENT the idea
  or REFERENCE ONLY. GPL and other copyleft terms are flagged per component.
- **Unmerged work** is marked wherever a capability exists only on a branch.

## Key comparative findings (all nine from deliverable 5 §1, condensed)

1. **No repository meets the mandatory security criterion as shipped;** several individual components meet a
   security or correctness bar on their own, some only as ideas because they have no licence (deliverable 1
   §5.7–5.8).
2. **The only controlled outcome evidence (Lewis Factory, author data, synthetic tasks, unmerged) does not favour
   orchestration complexity.** In v3, against Claude Code running the same reviewer as a subagent, the Factory arm
   accepted 30/36 against 29/36 for the direct arm, code passed the independent tests 30/36 against 31/36, and the
   Factory arm was faster (48.6 s against 75.5 s median) at similar cost. In v1 (easy tasks, whose original tests
   were later found flawed) every mode passed, and Factory took about 2.1× the time and 2.5× the cost of a task-only
   baseline. The measured benefit of independent acceptance checks plus review and repair (6/9 against 1–3/9) holds
   on hand-picked hard cases against no-review baselines (v2), not against a reviewer-equipped baseline.
3. **Where the acceptance decision sits matters more than the orchestration label:** code-owned acceptance routes
   failures; LLM-owned steps were observed being skipped. Code ownership is necessary but not sufficient.
4. **Independent verification is mostly context separation within one model family** (exceptions: IndyDevDan's
   mixed-provider roster and Ras Mic's external review bot); no default branch keeps a reviewer read-only by tool
   restriction. The strongest correctness-proving ideas have no licence.
5. **Untrusted input is the weakest cross-cutting capability.**
6. **The owner's measures are almost entirely unmeasured** across the set, and no repository implements the
   REUSE / ADAPT / COMPOSE / REIMPLEMENT / BUILD NEW decision for supplied references.
7. **Reference-driven development exists at two non-overlapping levels** (REA: artifact level with a formal ledger;
   Replica: product level with a feature ledger); neither verifies parity independently of the builder.
8. **No repository demonstrates building arbitrary applications end to end,** and production readiness of
   factory-built software is evidenced nowhere (deliverable 5 §6; facts only, the question is left to phase 3).
9. **Maturity cuts both ways.** The most tested projects churn the most; several key mechanisms exist only on
   unmerged branches; documented properties are contradicted or unimplemented in seven repositories, several of
   them safety-related (Sandcastle ADR 0015, Rezvani's "blocking" hooks, REA's "must authenticate").

## Inputs for phase 3

- **Questions:** deliverable 5 §7 lists what phase 3 must decide or measure, each with its starting evidence.
- **Candidate verdicts:** deliverable 4 supplies the component-level candidate verdicts and composition options.
  Where deliverables 2 and 4 disagree on a verdict, **deliverable 4 governs** (deliverable 5 §8.1 X11, the one
  remaining disagreement marked material for reuse planning; it affects nine components, including `imgdiff.py`,
  Sandcastle, the IndyDevDan tracer, the Super-Board hooks and the REA ledger).
- **Leverage summary:** deliverable 5 §5a counts the 175 component rows by candidate verdict and lists the 21 REUSE
  components that pass the mandatory filters as shipped.
- **Other evidence:** deliverable 3 gives the evidence strength of each practice; deliverable 2 the capability gaps;
  deliverable 1 the mandatory-criteria verdicts.

## Phase 1 errata applied

Phase 2 analysts and verifiers re-checked many phase 1 claims and found ten discrepancies (E1–E10, deliverable 5
"Report discrepancies found"; E9 and E10 were raised by a phase 2 verifier). Nine were applied to the phase 1 reports
(01, 02, 03, 05, 07, 08, 10), one of them (E5) with a qualification, and to the phase 1 index; E8 (a test count
within the report's "~") needed no change. The most material: report 10 §13 still classed four no-licence components
as "needs adaptation" (now "reimplement the idea"); report 07 omitted third-party copyleft terms; report 02 omitted
that `github_review.py`'s tests are unlicensed; report 05 omitted the v3 code-pass figure that favours the direct
arm. Each report change is listed in that report's §17 "Verification corrections"; the phase 1 index records its
own change in its "Verification record" section.

## Verification record

| Item | Verification | Findings | Status |
|---|---|---|---|
| Deliverable 1 | independent verifier, ~30 statements re-checked | P1-1 … P1-10 (P1-9, P1-10 from the closure pass), plus P2-1 (shared) | closed; accurate |
| Deliverable 2 | same verifier, ~30 statements | P2-1 … P2-12 (P2-12 from the closure pass; P2-4 reopened twice before closing) | closed; accurate |
| Deliverable 3 | second verifier, 25 statements | P3-1 … P3-9 | closed; accurate |
| Deliverable 4 | second verifier, 24 statements | P4-1 … P4-10 | closed; accurate |
| Deliverable 5 | third verifier, 28 statements | S1 … S16 (S14–S16 closure-pass nits, applied by the coordinator) | closed; accurate |
| Phase 1 errata | second verifier, against `git diff` and the clones | E1–E10, plus two nits on the phase 1 index: N-1 (Ras Mic's `github_review.py` tests unlicensed) and N-2 (REA's bundled third-party tools carry LGPL, GPL and EULA terms), both added to its reusable lines | closed; applied accurately |
| This index | independent reviewer, three rounds | C1 … C17 | closed; approved |

Each deliverable ends with "Verification corrections (2026-10-22)" (deliverable 5: "Revision notes") listing every
change. Statement counts and closures are from the verifiers' returns to the coordinator.

**Process notes, disclosed.** No repository code was executed by anyone. The analysts for deliverables 1–4 were
interrupted by an API usage limit and resumed from their saved work (deliverables 1–3 were already on disk). The
deliverable 4 analyst used temporary part files in the session's temporary area. The coordinator made several
small edits to deliverables 1, 2 and 5 and to the phase 1 index with short Python exact-match replacements or
`sed`; each edit is recorded in the file's corrections or revision list, though the lists do not name the method.
The phase 1 errata agent edited report 01 after viewing it with `sed` rather than the read tool.

## Limits

- Nothing was executed: all runtime behaviour, costs and security impacts are read from code, tests and published
  data. Deliverables 1, 2, 3 and 5 reuse phase 1's official-docs citations; the deliverable 4 analyst read the hooks,
  permissions and Agent SDK docs on 2026-10-22, and the deliverable 4 verifier's P4-2 also cites them.
- Not inspected: Archon internals (report 10, out of scope by the brief), so Cole Medin's review, merge and
  permission behaviour stays unknown; Sandcastle's external daemon (not in the repository); most of REA's provider
  directories; Super-Board's auxiliary skills and docs site; Codex-side behaviour.
- The only outcome measurement is one author's benchmark on synthetic tasks (Lewis Factory). REA's efficiency
  checkpoints measure its own tools at tool level and are not outcome measures. The owner's measures are otherwise
  unmeasured.
- Synergies, compositions and optimization opportunities are inferences from the evidence; none was built or run.
- Licence statements are technical readings of the licence files, not legal advice.
- Six disagreements between deliverables remain and are documented in deliverable 5 §8.1 (four rating-boundary
  divergences, the deliverable 2 vs deliverable 4 candidate verdicts, and the status of Sandcastle's explore-workflow
  test).
