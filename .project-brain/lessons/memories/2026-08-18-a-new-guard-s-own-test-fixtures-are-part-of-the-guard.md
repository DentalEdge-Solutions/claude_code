---
type: lesson
title: A new guard's own test fixtures are part of the guard
description: Adding a provenance check to a script immediately broke that script's pre-existing tests, because their fixtures had nev
tags: []
timestamp: 2026-08-18T19:32:00
sources: [sessions/daily/2026-08-18.md]
status: candidate
---

Adding a provenance check to a script immediately broke that script's pre-existing tests, because their fixtures had never needed to declare the thing now being verified. That is the guard working, not a regression — but it means shipping a guard includes updating every fixture to state what it is pretending to be. Worse, in the same file an 'if __name__ == main: unittest.main()' sat in the MIDDLE of the module and short-circuited everything defined below it, so six newly added tests appeared to pass by never running at all; the suite went from 3 to 9 tests once moved to the end. Both belong to the same family as an unvalidated probe: a check that looks green because it never executed. After adding tests, confirm the reported test COUNT changed, not merely that the suite still says OK.
