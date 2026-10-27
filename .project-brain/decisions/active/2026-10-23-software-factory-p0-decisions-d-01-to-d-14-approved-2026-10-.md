---
type: decision
title: Software Factory P0 decisions D-01 to D-14 approved (2026-10-23)
description: The owner approved D-01 to D-14 of the phase 3 strategy as written (docs/evaluations/2026-10-22-optimization-strategy/S6
tags: []
timestamp: 2026-10-23T18:00:00
sources: [sessions/daily/2026-10-23.md]
status: active
promoted_at: 2026-10-27
---

The owner approved D-01 to D-14 of the phase 3 strategy as written (docs/evaluations/2026-10-22-optimization-strategy/S6-strategic-optimization-report.md section 7.1; PR #174, merge cbb6d4e), after two independent reviews and five correction rounds. Owner choices: OC-1 dentaledge-bot becomes the laptop agent's GitHub account, with a fine-grained access credential if a scratch test shows it works, otherwise a classic one without workflow scope, its access measured and re-measured at each rotation; OC-2 P0-10 first checks whether merges can be restricted to the owner, else the agent's merge of an approved head is a recorded exception; OC-3 revised: P0-02 holds breach (d) through the required Test suites job for skills, agents, packs and Hermes skills, and D-15 returns to before P1; OC-4 D-11 supersedes the P11 failure policy and the F1 non-adoption of onFailure block. D-15 to D-28 remain open. Nothing is implemented by the approval itself.

Key items, for retrieval (full list in S6 section 7.1): D-01 approves the P0 set (P0-01 to P0-11) and its batch order B0 to B5, with the stated exceptions accepted; D-10 stops skills deploying themselves (the owner deploys); D-11 makes the brain guard fail closed, reversing the P11 failure policy; D-12 and D-13 set the approval lock on GitHub and the agent's own account (dentaledge-bot). This stays within the 2026-10-22 value definition: Track A stands, and there is no autonomous merge path; under OC-2 an agent merge is at most a recorded exception for a head the owner approved. Implementation is tracked per PR in docs/evaluations/ (P0-01 to P0-09 and P0-11 merged as PRs 176 to 182 by 2026-10-26; P0-10 is batch B5).
