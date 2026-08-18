---
type: lesson
title: 'No data' and 'zero data' are different events; row-emptiness cannot separate them
description: Three independent occurrences in one session, in unrelated code. A reader exited 1 whenever it loaded zero rows, which f
tags: []
timestamp: 2026-08-18T19:31:00
sources: [sessions/daily/2026-08-18.md]
status: candidate
---

Three independent occurrences in one session, in unrelated code. A reader exited 1 whenever it loaded zero rows, which failed an entire audit run for an account that was simply idle — the intent (a failed collection must never read as a reassuring 'nothing to report') was right, applied to the wrong signal. A second reader would have computed coverage percentages against an empty spec and printed a confident 0%. A measurement tool rounded an inconclusive probe toward a definite verdict. The discriminator is usually already present and unused: where a collector writes an output file on success INCLUDING a zero-row success, and deletes it on failure, file EXISTENCE separates the two while row count cannot. Rule: enumerate the three states (absent / present-but-empty / present-with-rows) explicitly, and never let 'could not tell' round toward the reassuring answer.
