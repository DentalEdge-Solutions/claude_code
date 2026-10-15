# Review and evidence protocol

How work in this repo is verified before merge. It codifies the practice recent PRs already follow
(for example #130: an independent review, findings fixed with tests and confirmed closed on re-check).
Patterns are adapted, not copied, from the Phase 2 evaluation
(`docs/evaluations/2026-10-14-software-factory-architecture-evaluation.md`, items 7–8).

**The rule underneath:** the implementer is never the only authority on its own work. CI, which the
`main-protection` ruleset requires and runs on the merge commit, is the deterministic check. The
review is the independent one. A self-reported "done" or "passing" is not evidence.

## Reviewer

1. **Read the intent first.** Read the spec, plan or acceptance criteria and the diff *before* the
   author's account of it. Write down what you expect to be wrong, then check.
2. **Re-run, don't trust.** Run the stated test commands yourself on the reviewed commit, and record
   the commands and the short SHA. A claimed result you did not reproduce is marked *not reproduced*.
3. **Number the findings:** `R1`, `R2`, …, each with a severity (blocking / minor) and a file:line.
4. **Re-review against the same IDs.** Mark each one *fixed* (with the test that shows it),
   *not fixed*, or *no longer applies* (with the reason). Don't renumber.
5. **Only the reviewer closes a finding.** The author answers it; the author does not mark it resolved.
6. **Approve, don't merge.** Merging is a human action.

## Author: evidence types

| Change | Evidence |
|---|---|
| Bug fix | The failure captured **before** the fix (a failing test, a command and its output), then the same check passing |
| Behaviour or feature | Tests per acceptance criterion; the commands run and their results |
| No-UI change (scripts, config, docs that steer agents) | A measured probe (numbers), an input/output pair, or an excerpt of a transcript or log |
| Anything not verified | Listed as **untested**, with the reason. Never omitted silently |

Evals follow the same contract: the `Evidence and Limits` section of SKILL-EVAL, AGENT-EVAL and
TEAM-EVAL, with the revision pinned by `run-manifest.js init --subject`.

## Not used here

These were evaluated and rejected in Phase 2 (§4, items 15–18):
- a reviewer that merges its own approval;
- an author resolving the reviewer's threads;
- external review loops that pre-approve every `git` and `gh` command.
