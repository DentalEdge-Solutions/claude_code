---
type: lesson
title: A probe proves nothing until it has refused what it should refuse
description: Measuring whether a credential holds admin access took three attempts, and the first two returned confident wrong answer
tags: []
timestamp: 2026-08-18T19:31:00
sources: [sessions/daily/2026-08-18.md]
status: candidate
---

Measuring whether a credential holds admin access took three attempts, and the first two returned confident wrong answers rather than errors. (1) Reading the platform's user-access table was treated as proof of admin — it is not a discriminator at all, since a read-only credential reads it successfully; the tool reported ADMIN for a credential whose mutate was refused in the same run, an internal contradiction it never noticed. (2) It then concluded admin was unmeasurable without mutating, reasoning from a service that lacks a validate-only flag — true, but the wrong service; a neighbouring one has it. (3) The working probe is validate-only and, crucially, was verified DISCRIMINATING against a control known to lack the access: the control must be REFUSED before an acceptance means anything. Generalisation: a negative result from an unvalidated probe is worthless, and a positive one is worse because it looks like evidence. Every measurement needs a case it is known to reject.
