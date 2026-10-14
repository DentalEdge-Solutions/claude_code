# Claude Code knowledge sources: verification and classification (Phase 1)

> **Date:** 2026-10-14
>
> **Asked:** Which sources should this project trust for Claude Code, and how? What belongs in the brain, and what stays on demand? (Phase 1 of the knowledge and software-factory initiative; input: `docs/master-prompts/Claude_Code_Knowledge_Intelligence_Master_Prompt.md`.)
>
> **Answer:**
> - The trust tiers, source registry and research protocol are in `docs/CLAUDE_CODE_KNOWLEDGE.md`.
> - Five recurring sources are registered in the reference library.
> - Nothing goes into canon, and `CLAUDE.md` gets a one-line pointer.
>
> **Method:**
> - Official pages were fetched in their `.md` form.
> - GitHub metadata came from the API.
> - Each conflict was decided on the newest Tier A text plus a measurement on this machine.
> - Third-party content was read as data only: nothing was cloned, installed or run.
>
> **Runtime:**
> - Claude Code CLI 2.1.300, which is the latest release (published 2026-10-14). Claude Desktop 2.37337.1.

## 1 · Sources and what each verified (all accessed 2026-10-14)

| Source | Tier | Access | Verified there |
|---|---|---|---|
| `code.claude.com/docs/llms.txt` + 15 catalog pages | A | all HTTP 200, no redirects, `.md` form served | See §3. No page shows an update date, so each claim is pinned to the changelog version that introduced it. |
| Changelog (`/docs/en/changelog.md` = repo `CHANGELOG.md`) | A | 200 | Latest is 2.1.300 (2026-10-14). Agent teams arrived in 2.1.32 (2026-02-05) as a research preview. The Workflow tool arrived in 2.1.152, dynamic workflows in 2.1.154. The trigger keyword was renamed from `workflow` to `ultracode` in 2.1.160. `/batch` is bundled. |
| GitHub security advisories, anthropics/claude-code | A | API 200 | 37 advisories (18 for the CLI, 19 for Desktop and other packages). The highest CLI patch floor is 2.1.260 (GHSA-gfvf-j8jh-jxxw); the highest Desktop floor is 1.15962.0 (GHSA-v234-4jrq-mgg6). **Neither installed version is affected.** |
| anthropics/claude-code, skills, claude-plugins-official, claude-code-playground, claude-cookbooks | A/B | API 200 (rate-limited partway; every value listed was collected) | Licenses and SHAs are in the registry table. The playground repo is self-described as "not an official Anthropic product … not best-practice canon", so it is Tier B. Cookbooks was renamed from `anthropic-cookbook`. |
| AI-native SDLC playbook (Anthropic, 2026-08-21) | B | 200 | "A skill is an advisory control." Policies that must always hold need a deterministic hook. Every stage commits an artifact the next stage reads. Always give Claude a way to verify its own work. |
| Platform glossary | A (API terms) | 200 | Terminology only. The MCP connector is in beta. |
| OpenAI "Harness engineering" | primary for OpenAI's approach only | **HTTP 403 twice** | **Unverified.** Not summarized from memory. The guide's review of it (Tier C) is the only access, and that review is not primary. |
| Claude Code Ultimate Guide (repo + cc.bruniaux.com) | C, one publisher | 200; all 21 listed paths exist | `7e3509e` (2026-10-13), CC BY-SA 4.0. It tracks Claude Code 2.1.296. Claims checked are in §2. |
| awslabs/cli-agent-orchestrator, Runfusion/Fusion, bashebr/ai-native-sdlc, refute-or-promote | C | API 200 | See §4. |
| NousResearch/hermes-agent README | A for Hermes | 200 | Ships "Migrating from OpenClaw" (`hermes claw migrate`), which treats OpenClaw as a separate product. |

## 2 · Conflicts, resolution and status

| Topic | Competing claims | Resolution |
|---|---|---|
| CLAUDE.md size | **Guide:** "<100 lines", "4-8KB total", and elsewhere "<500 lines", so it contradicts itself. **Official** (memory.md, features-overview.md): "target under 200 lines per CLAUDE.md file". | **Official wins.** Our `CLAUDE.md` is 109 lines, so no trim is needed. |
| Hook input | **Guide** (`roles/agent-evaluation.md`): hooks read `$CLAUDE_TOOL_NAME` and similar env vars. **Official** (hooks.md): "For command hooks, input arrives on stdin" as JSON. | **Official wins.** The guide's example is wrong for native hooks; do not copy it. |
| Dynamic workflow concurrency | **Guide:** `min(16, cpu_cores - 2)`. **Official** (workflows.md): up to 16 by default, fewer with fewer CPUs; `CLAUDE_CODE_WORKFLOW_MAX_CONCURRENT_AGENTS` takes 1 to 256 (v2.1.269+). | The default agrees; the guide's exact formula is **unverified**. Our first research subagent misreported the range as "1–25"; re-reading the page corrected it. **Lesson: re-check numbers against the fetched page.** |
| Agent-teams status | **Changelog** 2.1.32: "research preview". **Current page:** "experimental and disabled by default". | Wording drift only; the env var (`CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1`) is the same in both. **Not enabled on this machine.** |
| "Hermes Agent (formerly OpenClaw)" | **Guide** (`ecosystem/agentic-tools.md`) vs **the Hermes README**, which ships a migration path *from* OpenClaw. | **Guide claim rejected.** The two are separate products. Our canon is unchanged. |
| Guide advisory IDs (`ADVISORY-CC-2026-001/002`) | The guide's security-hardening page uses them. | They are not GHSA IDs and so are **unverified**. The GHSA entries the guide cites do exist and match. |
| Security floor "update to 2.1.281" | The guide cites it. | Moot: the installed 2.1.300 is above every published patch floor. |

## 3 · Highest-value verified insights for this project

| # | Insight (source) | Applies to | Project impact |
|---|---|---|---|
| 1 | A multi-step procedure becomes a skill. A part-of-codebase rule becomes a `.claude/rules/` file with `paths:`. Anything that must always hold becomes a hook, because CLAUDE.md is advisory (memory.md, best-practices.md, SDLC playbook). | current | Confirms the existing design: brain guard hooks are the enforcement layer, and `codex-eval` keeps its detail in a skill. No change needed. |
| 2 | The skill listing budget is 1% of the context window. On overflow, descriptions of the least-invoked skills are dropped first. `description` + `when_to_use` are truncated at 1,536 characters (skills.md). | current | **Risk to eval validity.** This machine has 112 user-level skills plus plugin skills. If descriptions are being dropped, **trigger and dispatch accuracy measure the budget, not the description.** Unmeasured; see the recommendations in §6. |
| 3 | Subagent `memory:` has no effect while auto memory is off (sub-agents.md). User settings set `CLAUDE_CODE_DISABLE_AUTO_MEMORY=1` (measured). | current | **Conflict with BRAIN.md**, which routes "personal machine-local observations" to native auto-memory. That route is currently off. Owner decision. |
| 4 | Dynamic workflows (2.1.154+, keyword `ultracode`, `.claude/workflows/`, resumable, 16 concurrent agents by default) are native. Agent teams are experimental. Worktrees are native (`--worktree`, `isolation: worktree`) (workflows.md, agent-teams.md, worktrees.md). | 2.1.300 | **Phase 2 input:** compare native orchestration with any proposed third-party factory before adopting one. |
| 5 | In `-p` and SDK sessions, a repo's `.claude/settings.json` hooks run as trusted; `--bare` or `disableAllHooks` is advised for repos you didn't write (hooks.md). Plugins run code outside the sandbox (plugins/security.md). | current | Relevant to Codex and headless eval runs and to Hermes driving `claude -p` on the box. Phase 2 security review. |
| 6 | Changelog 2.1.299–2.1.300: hook `updatedInput` is now validated; UserPromptSubmit hooks run before a skill expands; MCP allow-rule matching is tightened. | 2.1.299+ | Our telemetry hooks (PostToolUse, UserPromptSubmit) should be re-checked once against the new ordering. Low risk; on-demand. |

## 4 · Classification decisions

| Item | Decision | Reason |
|---|---|---|
| Authority tiers + research protocol | **PROMOTE (pointer only)** — one `CLAUDE.md` line points to `docs/CLAUDE_CODE_KNOWLEDGE.md` | Needed whenever a task turns on Claude Code behaviour. The detail stays on demand. |
| Official docs, changelog, advisories | **ON-DEMAND REFERENCE** (registered: `claude-code-docs`, `anthropic-claude-code`) | Tier A. Too large and too changeable to load into context. |
| anthropics/skills, claude-plugins-official | **ON-DEMAND REFERENCE** (registered) | Structure patterns. Licensing caveats are on the source cards. |
| claude-code-playground, cookbooks, SDLC playbook, glossary | **ON-DEMAND** (listed in the doc table, not registered) | Occasional use; not recurring for this project. |
| Claude Code Ultimate Guide | **ON-DEMAND, corroboration only** (registered) | Useful vocabulary and maps. Its native-feature claims lag or conflict (§2). |
| awslabs/cli-agent-orchestrator | **WATCHLIST** (Phase 2) | Mature AWS Labs project, but it launches `claude --dangerously-skip-permissions` by default, auto-accepts the trust dialog and runs a local web server. **Revisit if** native agent teams and workflows can't cover a demonstrated multi-CLI need. |
| Runfusion/Fusion | **WATCHLIST** (Phase 2) | Beta. One author wrote about 95% of the commits, the org is unverified, it installs via `curl \| sh`, and it has a `--no-auth` dashboard flag. Its worktree-per-task model is already native. **Revisit for** the pattern of double-checkout adversarial verification only. |
| bashebr/ai-native-sdlc | **WATCHLIST** (Phase 2) | MIT, one author, 7 weeks old. Its phase-artifact and approval-gate patterns overlap the existing gates. Compare, don't adopt. |
| refute-or-promote | **ARCHIVE** | Docs-only paper companion, inactive since April. Dual-use content (exploit proofs of concept). Its idea of adversarial "kill rounds" is kept as a methodology note. |
| OpenAI harness engineering | **WATCHLIST — inaccessible** | Retry from a browser or the Drive copy if Phase 2 needs it. |
| Any brain canon entry | **None** | No Phase 1 finding justifies a canon change. A decision entry is captured in today's session log. |

## 5 · Smoke tests (protocol §4 run end to end)

**(a) CLAUDE.md vs skills.**
- **Answer:** keep facts every session needs in CLAUDE.md, target under 200 lines. Move procedures to skills; skill bodies load only on invocation. Use path-scoped rules for guidance that covers part of the codebase, and hooks for anything that must always hold.
- **Sources:** memory.md, features-overview.md, best-practices.md.
- **Status:** `supported` in 2.1.300.

**(b) Is an advertised agent or workflow capability supported?**
- **Asked** the built-in `claude-code-guide` subagent about agent teams and workflow concurrency in 2.1.300.
- **It returned** the agent-teams env var (experimental, disabled by default) and the concurrency range 1 to 256 (v2.1.269+), both matching the pages.
- **It marked** the agent-teams introduction version "unverified", because the page doesn't state it; the changelog gives 2.1.32.
- **Runtime:**
  - Agent teams are `documented-not-enabled` (no env var set).
  - Dynamic workflows are `supported` (the Workflow tool is present in this session).
- **Result:** routing works, and checking the changelog (protocol step 2) is necessary.

**(c) Community guide vs official docs.**
- **Conflict:** the guide says hooks read `$CLAUDE_TOOL_NAME`; official hooks.md says JSON arrives on stdin.
- **Resolved** in favour of the official docs, and the guide's example is marked unusable.

## 6 · Recommendations awaiting owner approval (not implemented)

1. **Measure the skill-listing budget effect on evals (insight 2).**
   - Run `/doctor` or check the startup warnings in an eval session.
   - If descriptions are dropped, run evals with a reduced skill set, or record the listing state in each `SKILL-EVAL.md`.
   - Phase 2 eval-methodology item.
2. **Resolve the auto-memory routing conflict (insight 3).** Either remove the route from BRAIN.md and MEMORY.md, or re-enable auto memory. Governance file, owner decision.
3. **Freshness automation** (`docs/CLAUDE_CODE_KNOWLEDGE.md` §5):
   - A read-only conditional-fetch script for the changelog, `llms.txt` and advisories, writing a digest under gitignored `evals/`, run on demand or weekly through the existing `schedule` routines or the Hermes box.
   - Cost: about 4 HTTP requests a week and no LLM tokens until a change is detected.
   - Decide in Phase 2 together with any factory automation.
4. **A dedicated research skill.** Deferred. The `claude-code-guide` subagent plus the protocol passed the smoke tests. A project skill would need the full skill-eval to meet this project's own bar, and a demonstrated gap first.
5. **Fix the comma-splitting in `brain-reference-repo-add.js --use/--risk`.**
   - Minor bug: the existing `nous-hermes-agent` `preferred_use` entry is fragmented by it.
   - Needs a test-backed change.

## 7 · Reuse in Phase 2 (software-factory evaluation)

- **Reuse the tiers, the protocol and the conflict method.** Evaluate the Phase 2 repositories (Ras Mic, Eric Tech Super-Board, Rezvani factory, REA) at Tier C, with the provenance fields used in §1 and §4.
- **Native baseline to compare against** (verified in §3):
  - skills, subagents, hooks, worktrees, MCP and plugins;
  - dynamic workflows, supported;
  - agent teams, experimental and off.
- **Security posture checks for any orchestrator:**
  - permission-bypass defaults;
  - trust-dialog auto-accept;
  - listening services;
  - `curl | sh` installers;
  - hooks running as trusted under `-p`;
  - plugin code outside the sandbox.
- **Already-watchlisted references for comparison:** CAO, Fusion, ai-native-sdlc.
