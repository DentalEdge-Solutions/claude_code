---
type: decision
title: D3 skill-listing overflow: options D and B applied (2026-10-14)
description: D3 = options D then B. The skill-listing budget was raised to 2%, GSD's 72 skills set to name-only, and 16 of its hook registrations removed, keeping the secret-read guard and injection scanner.
tags: [gsd, skills, settings, hooks, skill-eval]
timestamp: 2026-10-15T02:38:00
sources: [sessions/daily/2026-10-15.md]
status: active
promoted_at: 2026-10-15
---

Owner decision D3 = both options, in order. The skill listing overflowed its default 1% budget (154 skills, 45,657 > 30,000 chars), so rarely used skills such as codex-eval lost their descriptions, so skill-eval trigger accuracy could measure the budget instead of the description. Option D set skillListingBudgetFraction to 0.02 in ~/.claude/settings.json. Option B then set the 72 GSD skills to name-only (not off: a dormant GSD project still uses them and they call each other) and unregistered 16 GSD hook registrations, keeping only gsd-secret-read-guard (the only secret-read protection at user level and in this project) and gsd-read-injection-scanner. Both were verified in fresh --debug sessions and recorded in docs/evaluations/2026-10-14-gsd-global-install-audit.md §6-§8 (PR #133, merge 9cb9938). Rollback: restore ~/.claude/settings.json.bak-b-2026-10-14 (B) or settings.json.bak-d3-2026-10-14 (D and B); recheck after any /gsd-update, which may re-register the hooks. Headroom at 2% is about 14k chars, so recheck with --debug before skill-eval runs. Finding HR1 (a native secret guard that also covers settings.json-style key files) is the precondition for option C (uninstalling GSD).
