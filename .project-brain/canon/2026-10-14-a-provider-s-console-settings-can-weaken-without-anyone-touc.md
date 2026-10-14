---
type: lesson
title: A provider's console settings can weaken without anyone touching them (F62)
description: A provider's console settings can weaken without anyone changing them (F62, OpenRouter retention); compare every console screen with the last review's and keep the before screen.
tags: [security-review, openrouter, console, f62]
timestamp: 2026-10-14T17:59:00
sources: [sessions/daily/2026-10-14.md]
status: canon
promoted_at: 2026-10-14
---

Between review #10 and review #11, OpenRouter added a 'Zero retention only / Safety retention allowed' choice to its Zero Data Retention rows and set it to the weaker 'Safety retention allowed'. Only reading the whole privacy screenshot against the previous review's screenshot caught this; nothing on the box measures it. So: at each review, compare every console screen with the previous review's line by line, keep a screenshot of the 'before' state as its own file before changing anything, and record which providers served requests during any exposure window.
