---
type: lesson
title: The gateway rewrites data/config.yaml; back up under a name of its own (2026-10-14)
description: The gateway rewrites data/config.yaml (layout and a show-once tip flag); a backup for a later job takes a name of its own and refuses one already taken.
tags: [hermes-box, gateway, config, runbook]
timestamp: 2026-10-14T14:08:00
sources: [sessions/daily/2026-10-14.md]
status: active
promoted_at: 2026-10-14
---

The gateway rewrites its settings file. The live file and the template differed by 18 lines: 17 were its own layout (quotes dropped, lists one item per line), and one was a key it wrote itself, `onboarding.seen.tool_progress_prompt`, which Hermes' source names a show-once tip flag. Installing the template removes that flag, and the only cost is that the tip shows once more. The runbook's backup name `/root/config.yaml.pre-optb2` is shared with the first job's install, so a backup for a later job takes a name of its own and refuses a name already taken.
