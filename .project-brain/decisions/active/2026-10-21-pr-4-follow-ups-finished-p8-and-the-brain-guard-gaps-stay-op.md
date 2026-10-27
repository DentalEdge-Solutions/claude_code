---
type: decision
title: PR #4 follow-ups finished; P8 and the brain guard gaps stay open (2026-10-21)
description: The PR #4 follow-ups finished with PR #168 (2026-10-21). Since PR #182 (2026-10-26) brain-guard gaps G1 and G3 are closed, RR4's onFailure-block option is adopted and F1 is quarantined. Still open are P8, G2, G5 and part of G4, a minor installer rewrite, the S11 research follow-up, E16's untested refine run and smaller recorded limits.
tags: [hermes, proposal, triage, static-scan, harvest-evidence, installers]
timestamp: 2026-10-21T23:31:00
reviewed_at: 2026-10-27
sources: [sessions/daily/2026-10-21.md, sessions/daily/2026-10-27.md]
status: active
promoted_at: 2026-10-27
originally_promoted_at: 2026-10-22
---

The follow-up work from PR #4 (the Hermes improvement proposal, closed 2026-10-15) finished on 2026-10-21 with PR #168 (merge 86677c6). Done: P1, P2, P3, P6, P7, P9, P10, P11, P12, P13 and P14 (P4 and P5 were done before the triage), and the gaps found in that work: scanner gaps S1-S10, S12 and S13, and eval and refine gaps E1-E5 and E7-E16. Kept or accepted by owner decision: E6 (an eval's skill_loaded comes from a marker the subagent is told to write; disclosed in the eval reports); Q5 (a token-like string packed in a binary, or a quoted private-key header, BLOCKs); V13 (in a file over about 536 MB, a new secret pattern's hit in an earlier chunk can hide the evidence line main would show from a later chunk; the verdict and check are unchanged); S11 (the rm check reads the first target only).

Updated at the weekly review of 2026-10-27: the brain-guard items moved on with P0-09 (PR #182, merged 2026-10-26; see the active decision "Brain guard fails closed; supersedes the P11 fail-open policy"). The guard now fails closed with onFailure block and a written break-glass, which adopts RR4's remaining option and supersedes P11's fail-open policy; G1 (the promote exemption now covers exactly one call) and G3 (the rm-word false positive) are closed; F1 (brain-hooks.test.js failing now and then on a guard timeout) was not reproducible in about 3,430 runs and is quarantined with a stated reason, and a stall now hits the guard's own deadline and blocks.

Still open: P8 (the Hermes skills have no evals); brain-guard gaps G2 and G5, and the rest of G4 (grep-family readers accept any option); the installers rewrite the settings file even when they added nothing (minor, to fold into the next installer change); the S11 research follow-up; E16's refine snapshot and revert, which no LLM refine run has exercised yet (the owner's plan, 2026-10-21: the first refine of the coming evaluation campaign runs one iteration at a time, with its first revert checked by hand); and smaller scanner, installer and eval limits recorded as open in the triage doc, for example injection phrasings and injection inside code blocks that still PASS, and an uninstall.sh crash under bash 3.2 when the repo has no agents. Lesson kept from the 2026-10-15 decision: recheck each item of a Hermes proposal against current main before merging, because a proposal is a dated snapshot. Record of every item: docs/evaluations/2026-10-15-pr4-hermes-proposal-triage.md. This replaces decisions/superseded/2026-10-15-pr-4-hermes-improvement-proposal-closed-10-open-items-carrie.md.
