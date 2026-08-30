---
name: project-idea
description: "Use when: starting a new project from scratch, clarifying a vague idea before building, not sure what to build or how to structure it, or wanting confirmation on an early-stage concept. Interviews the user one question at a time to define the problem, target user, core features, out-of-scope items, tech direction, and success criteria. Produces PROJECT-BRIEF.md. Run before project-setup on any greenfield project."
compatibility: "Claude Code."
---

# Project Idea

Turn a vague idea into a structured project brief through a short guided interview. Produces `PROJECT-BRIEF.md` that `project-setup` reads to pre-fill its recommendations.

## Quick Start

```
User: I have an idea for a project
User: I want to build something but I'm not sure where to start
User: help me figure out what to build
User: I want to start a new project
User: can you help me plan my idea
```

## Workflow

### Phase 0 — Existing Brief Check

Silently attempt to read `PROJECT-BRIEF.md`. If it exists:

> "I found an existing project brief. Do you want to update it, or start over?"

- **Update:** re-run the interview with current brief values as pre-filled recommendations; treat each existing answer as the recommended answer for that question.
- **Start over:** proceed as if no brief exists.

If no brief exists, proceed directly to Phase 1.

### Phase 1 — Three Anchor Questions

Ask one question at a time. Wait for the user's answer before continuing. Each anchor has one optional adaptive probe — use it only when the answer is vague or abstract. Never chain probes or ask two questions in the same message.

---

**Anchor 1 — Problem + who**

> "What problem does this project solve, and who experiences it?"

**Probe trigger:** Answer is vague — subject is generic ("it helps people", "it's for users", "for everyone", "for businesses").

**Probe:**
> "Can you give me a concrete example — who is the person, and what are they trying to do right now?"

Store: `problem` (the full picture of who + what problem), `target_user` (the concrete person).

---

**Anchor 2 — What it does**

> "Describe what the project does in one or two sentences — imagine explaining it to a friend."

**Probe trigger:** Answer is abstract or a feature list ("it does many things", "it has a dashboard, reports, notifications…").

**Probe:**
> "What would a user actually do when they first open it?"

Store: `what_it_does`.

---

**Anchor 3 — Out of scope**

> "What would you leave out of the first version?"

**Probe trigger:** Answer is "nothing", blank, or "I don't know".

**Probe:**
> "For example — would you skip user accounts? Payment processing? A mobile version?"

Store: `out_of_scope` (list of excluded items; may be empty if the user genuinely has none).

---

### Phase 2 — Tech Direction

After the three anchors, derive the platform type from what was described. Then suggest a concrete starting point in plain language — not bare framework names, but a description with named examples.

**Derive platform type from the user's description:**

| Signal in description | Platform type |
|---|---|
| "website", "web app", "browser", "online tool" | web app |
| "phone app", "mobile", "iOS", "Android" | mobile app |
| "API", "backend", "server", "service" | API / backend |
| "command line", "terminal", "script", "CLI" | CLI tool |
| "desktop app", "Windows app", "Mac app" | desktop app |
| "data", "pipeline", "spreadsheet", "analysis", "ML" | data pipeline |
| Unclear or mixed | Ask first: "Would this be a website, a mobile app, or something else?" |

**Suggested defaults by platform type:**

| Platform | Plain-language suggestion | Example tools to name |
|---|---|---|
| Web app | "a website with a database behind it" | Next.js, Supabase |
| Mobile app | "a cross-platform mobile app" | React Native, Expo |
| API / backend | "a server that responds to requests" | Node.js + Express, or FastAPI |
| CLI tool | "a command-line script" | Node.js or Python |
| Desktop app | "a desktop application" | Electron or Tauri |
| Data pipeline | "a script that processes and transforms data" | Python + pandas |

**Question framing:**

> "For [platform type] like this, a common approach is [plain-language suggestion]. Tools like [Example A] and [Example B] are popular and [relevant quality — beginner-friendly / free / fast to start]. Does that direction work, or do you already use specific tools — or need anything to be [free / offline-capable / in a specific language]?"

If the user has no preference and no constraints, accept the suggestion as-is. Store: `tech_direction`.

### Phase 3 — Name and Success Signal

**If the project name is not yet clear from context**, ask it as the first question in Phase 3:

> "What do you want to call this project?"

Then ask the success signal question (no adaptive probe — accept any answer):

> "How would you know this project succeeded? What would be different?"

Store: `project_name`, `success_looks_like`.

### Phase 4 — Write `PROJECT-BRIEF.md`

Write to the project root immediately after Phase 3. Use this exact structure:

```markdown
# Project Brief: <project_name>

## Problem
<problem — use the user's own words>

## What It Does
<what_it_does — use the user's own words>

## Target User
<target_user — concrete person from Anchor 1 or its probe>

## Core Features (v1)
<inferred from what_it_does minus out_of_scope — derive 3–5 bullets; never ask the user for this list>

## Out of Scope (v1)
<out_of_scope — each item as a bullet; write "None stated." if empty>

## Tech Direction
<tech_direction — plain-language description + named tools + any stated constraints>

## Success Looks Like
<success_looks_like — user's own words>

## Open Questions
<anything that came up but was not resolved — write "None." if empty>
```

**Writing rules:**
1. Use the user's own words wherever possible. Do not paraphrase into technical language they did not use.
2. Core Features are inferred — derived from `what_it_does` minus `out_of_scope`. Never ask the user for a feature list directly.
3. Open Questions are non-blocking — capture unresolved items here; the brief is always written regardless.
4. Never leave a section blank. Use "None stated." or "None." for empty sections rather than omitting them.

### Closing Message

After writing the file, show a one-paragraph summary of what was captured (project name, what it does, platform type), then:

> "`PROJECT-BRIEF.md` saved. Run `/project-setup` next — it will read your brief and pre-fill its questions so you just confirm rather than type."

---

## Rules

- **One question per message** — never ask two questions in the same message.
- **At most one probe per anchor** — if the probe answer is still vague, accept it and move on. Do not chain follow-ups.
- **Never ask for a feature list directly** — derive Core Features from the other answers.
- **Always write the brief** — even if some answers are vague or incomplete. Open Questions captures what's unresolved.
- **Plain language for tech** — always describe the stack in plain terms before naming tools. Never drop a bare framework name without context ("a tool for building websites called Next.js" beats "Next.js" alone for a non-technical user).
