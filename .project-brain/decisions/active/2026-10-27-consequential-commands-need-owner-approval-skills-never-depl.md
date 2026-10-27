---
type: decision
title: Consequential commands need owner approval; skills never deploy themselves (P0-07, P0-08, 2026-10-26)
description: Consequential commands need the owner's approval at a prompt, and skills never deploy themselves: the owner deploys (B3
tags: []
timestamp: 2026-10-27T00:20:00
sources: [sessions/daily/2026-10-27.md]
status: active
promoted_at: 2026-10-27
---

Consequential commands need the owner's approval at a prompt, and skills never deploy themselves: the owner deploys (B3 PR-6, PR #181, merged 2026-10-26 as 1bec99e; roadmap P0-07 and P0-08, S6 D-10).

What holds:
- The committed root and infra/hermes-agent project settings carry an identical permissions.ask list of 23 rules: git push (also git -C forms and push --delete), gh pr merge, gh pr review, gh api, gh auth, git branch -D (also git -C), brain-promote.js (also with a path prefix), copies into ~/.claude/skills (cp, cp -r, cp -R, and $HOME forms), and running install.sh or uninstall.sh. Per the official docs, ask beats a local allow and still prompts in auto mode; under claude -p such a call is denied. scripts/claude-settings.test.js asserts the list.
- skill-adapt, skill-refine and skill-refine-agent stage their result in skills/<name>/ and never copy it to ~/.claude/skills; the owner deploys (runs the deploy command or approves it at the prompt) and runs node scripts/check-skill-deploy.js. The CLAUDE.md Always rule and the CLAUDE.md text install.sh writes into targets say so. scripts/staged-deploys.test.js fails if a definition or script under the definition trees deploys a skill.
- On 2026-10-26 the owner ran the fresh-session probe (prompts appeared as expected) and removed broad allow rules from the local settings: git push, gh pr, git, python3, python3 -c, three old skill-deploy copies and two old /tmp restore copies.

Residuals: ask rules are not a security boundary (the docs say so); forms such as git -c ... push, absolute-path or ${HOME} deploys, rsync, and a script calling the GitHub API escape them; install.sh is only prompted and still copies every skill. The GitHub-side lock is P0-10 (B5). Prompt counts rise by design. Not measured: skill-eval of skill-refine and skill-adapt (P1-10, B6). Record: docs/evaluations/2026-10-26-p0-07-p0-08-ask-rules-staged-deploys.md.
