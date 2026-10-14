---
name: skill-scout
description: "Use when: user wants to find, source, search for, or discover an existing skill; asks 'is there a skill for X'; wants to avoid building from scratch; or needs a ranked shortlist of candidates before running skill-audit or skill-adapt."
compatibility: "Claude Code. Node.js ≥ 18. Requires WebSearch, WebFetch, and Agent tools."
---

# Skill Scout

Find the best existing skill for a capability rather than building from scratch.

## Quick start

```
User: find a skill for code review that fits our GSD workflow
```

## Workflow

0. **Pre-flight: check project context** — before asking the user anything:
   - Check if `evals/project-context.json` exists
   - If it exists, read it and check richness: context is **rich** if ANY of these is non-empty: `stack`, `workflow_terms`, `key_phrases`

   **If context is present and rich** (at least one of `stack`, `workflow_terms`, or `key_phrases` is non-empty): silently pre-fill search context from it. Use `stack` values as additional keyword signals in steps 4–5. Use `workflow_terms` and `key_phrases` to refine capability matching. Use `installed_skills` and `plugins` in the conflict check (step 7). Do not ask stack/framework questions — you already know. Jump to the capability question in step 2.

   **If `evals/project-context.json` is missing or sparse** (all of `stack`, `workflow_terms`, and `key_phrases` are empty arrays, or the file doesn't exist): tell the user:
   > "Your project context isn't configured yet — this helps me find skills that actually fit your project. Run `/project-setup` first (takes ~2 minutes), then come back.
   > Alternatively, I can search generically right now — results won't be project-tailored."

   Offer both paths and let the user choose.

1. **Capture the need** — ask: "What capability are you looking for?" If project context was pre-filled from `evals/project-context.json`, skip stack/framework questions — ask only about the specific capability needed. Otherwise ask: "What does the project use?" (GSD? custom workflow? specific stack?). One question at a time.

2. **Check known registries first** — before a generic search, WebFetch the README of these live registries and scan for a match:
   - `https://raw.githubusercontent.com/multica-ai/andrej-karpathy-skills/main/README.md`
   - `https://raw.githubusercontent.com/vercel-labs/skills/main/README.md`
   - `https://raw.githubusercontent.com/Evol-ai/SkillCompass/main/README.md`

   If a match is found here, skip step 3 and go directly to step 4.

   *(anthropics/claude-code-skills and ComposioHQ/awesome-claude-skills returned 404 as of 2026-06-22 — removed. Re-add if they become live.)*

3. **Search GitHub** — if registries don't cover the need, use WebSearch with:
   - `site:github.com filename:SKILL.md <capability>`
   - `github.com/search?type=code&q=filename:SKILL.md+<capability>`
   - `site:github.com "claude code" skill <capability>`

   If one query returns nothing, try alternative terms (e.g., "deploy" → "deployment", "review" → "audit").

4. **Fetch candidates** — WebFetch the raw `SKILL.md` for each candidate. Collect: name, description, full body text, line count, whether it has scripts/REFERENCE.md, repo age in days, star count, source org, license (from frontmatter `license:` field if present).

5. **Score candidates** — run `node skills/skill-scout/scripts/score-candidates.js <candidates.json>`. See scoring dimensions below.

6. **Conflict check** — list installed skills: `ls skills/`. Flag any candidate whose trigger words heavily overlap with an installed skill's description.

7. **Present top 3** — for each candidate show:

   ```
   1. <skill-name>  (score: N/10 — STRONG | GOOD | MARGINAL)
      <one-line description>
      Source: github.com/<org>/<repo>@<commit-hash>  ★ <stars>
      License: <license or unknown>
      Trade-off: <one sentence>
   ```

   Then ask: *"Would you like to audit just the top pick, or audit the top 2–3 so skill-adapt can synthesize the best elements from each?"*

8. **Hand off to skill-audit** — invoke `skill-audit` on every candidate the user selects. Run audits sequentially. Collect all results.

   - Any **BLOCK** verdict: remove that candidate from the set, tell the user why.
   - Any **FLAG** verdict: present findings and ask for explicit confirmation before keeping it in the set.
   - Any **PASS** verdict: keep in the set.

   Once all audits are complete, pass the full set of PASS candidates to `skill-adapt` together. If more than one PASS candidate exists, tell the user: *"skill-adapt will synthesize the best elements from all [N] candidates."*

9. **No results fallback** — if no candidate scores > 5 and no registry match was found:
   - Tell the user no suitable skill was found.
   - Offer to help with the task directly using general capabilities.
   - Recommend building a new skill: invoke `superpowers:writing-skills`, then run `skill-audit` → `skill-eval`
     on the result before installing — a generated skill passes the same gates as a sourced one.

## Scoring dimensions (0–10 each, weighted)

| Dimension | Weight | What to measure |
|-----------|--------|----------------|
| Trigger precision | 25% | Does description include "Use when" with specific triggers? |
| Instruction clarity | 20% | Has REFERENCE.md? Sufficient depth (≥20 lines)? |
| Context footprint | 15% | SKILL.md line count (≤50=10, ≤100=7, ≤200=4, >200=1) |
| Project fit | 15% | Keyword matches in description **and** SKILL.md body |
| Provenance | 10% | Repo age + stars (penalize <30 days; reward ≥100 stars) |
| Source reputation | 10% | Trusted orgs (anthropics, vercel-labs, microsoft…) score higher |
| Conflict risk | 5% | Word-overlap with installed skills |

**Total score = weighted average × 10**

## Common skill categories

| Category | Example search terms |
|----------|---------------------|
| Code quality | review, audit, lint, refactor |
| Testing | tdd, testing, jest, playwright, e2e |
| DevOps | deploy, docker, kubernetes, ci-cd |
| Documentation | docs, readme, changelog, api-docs |
| UI / Design | ui, ux, design-system, accessibility |
| Workflow | planning, phases, git, automation |
| AI integration | llm, agents, mcp, prompt |

## Rules

- Always pin the source commit hash in your recommendation (never just a branch name).
- Never write any files — that's skill-adapt's job (after skill-audit clears the candidate).
- Prefer skills from trusted source orgs; explicitly flag unknown authors with low stars.
- If no suitable candidate scores > 5, recommend building from scratch with `superpowers:writing-skills`, followed by `skill-audit` → `skill-eval`.
