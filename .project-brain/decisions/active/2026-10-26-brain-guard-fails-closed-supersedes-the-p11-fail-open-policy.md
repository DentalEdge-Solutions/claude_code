---
type: decision
title: Brain guard fails closed; supersedes the P11 fail-open policy (P0-09, 2026-10-26)
description: The brain security guard now fails closed (PR #182, merged 2026-10-26 as 592d0c2; roadmap P0-09, S6 D-11 kept per OC-4).
tags: [brain, security-guard, p0-09, software-factory]
timestamp: 2026-10-26T22:48:00
sources: [sessions/daily/2026-10-26.md]
status: active
promoted_at: 2026-10-27
---

The brain security guard now fails closed (PR #182, merged 2026-10-26 as 592d0c2; roadmap P0-09, S6 D-11 kept per OC-4). This supersedes the P11 owner failure policy (the guard failed open but visibly, exit 1) and the F1 non-adoption of onFailure "block", both recorded in the active decision of 2026-10-21 on the PR 4 follow-ups.

What now holds:
- The guard blocks (exit 2) on an internal error, node failure, timeout or truncated program. It is registered in the committed root settings in exec form with onFailure "block"; sessions started in infra/hermes-agent run a launcher that finds the guard or blocks.
- Write, Edit, MultiEdit and NotebookEdit into the protected capsule folders (canon and decisions/active) are denied; decisions/active now has edit protection, not only delete protection. A Bash or Monitor command that reaches those folders passes only as exactly one plain brain-promote call or a recognised read-only form with allowlisted options. PowerShell is denied where a capsule exists.
- brain-promote is the only writer to canon and decisions/active; the weekly review routes its decision changes through it (new --to superseded). Self-promotion is refused by file identity.
- Commit and PR messages that name the protected folders go through a file (git commit -F, gh --body-file); a literal-message exemption was tried and removed after the independent review showed a bash desync that deleted a test capsule.
- Break-glass: claude --safe-mode, or claude --settings with disableAllHooks, or removing the guard entries outside Claude Code (docs/SECOND_BRAIN_SECURITY.md).

Relation to the active decision of 2026-10-21 (PR 4 follow-ups): this closes brain-guard gaps G1 (the promote exemption now covers exactly one call) and G3 (the rm-word false positive), adopts RR4's remaining option (onFailure block together with a recovery path: the break-glass above), and quarantines F1 with a stated reason (not reproducible in about 3,430 runs; a stall now hits the guard's own deadline and blocks). Its statements that the guard fails open after the timeout and that onFailure block was not adopted no longer hold. G2, G5 and what remains of G4 (grep-family readers accept any option) stay open there. The weekly review updates that decision's status through brain-promote.

Still pending after merge: the owner's two Hermes checks (the CLAUDE_PROJECT_DIR probe from infra/hermes-agent and the gateway box probe for security review #12) and the 14-day watch of guard-failures.log. Done on 2026-10-26: the old local fail-open registration was removed from the owner's local settings, and brain-weekly-review was deployed.

Residuals and follow-ups are in docs/evaluations/2026-10-26-p0-09-brain-guard-fail-closed.md (archive extractors run outside protected folders, the guard not protecting its own script, ugrep options blocked only by the Claude Code wrapper, and others). Revisit if guard-failures.log shows real fails-closed entries in the 14 days after merge, or if a legitimate workflow is blocked.
