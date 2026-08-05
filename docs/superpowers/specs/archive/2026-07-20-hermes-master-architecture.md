# Hermes — Master Architecture & Roadmap

> **⚠ REVISED by the definitive roadmap.** This cross-cutting design is reframed into a credential-free
> **kernel** (build now: K0–K3) and a deferred, multi-tenant **Operate track**; decisions **D12–D15**
> were added and **D1/D9** revised. Authoritative now: `~/.claude/plans/iterative-squishing-church.md`
> and the brain candidate `.project-brain/decisions/candidates/2026-07-21-hermes-definitive-roadmap.md`.

> **Date:** 2026-07-20 · **Status:** design (planning only — nothing is built) · **Scope:** the full Hermes runtime, H0 → H3.

This is the umbrella document for the Hermes orchestrator. It locks the **cross-cutting
architecture** that every phase shares — the component model, the credential vault interface, the
execution guard, the persistence data model, and the run lifecycle — so the per-phase specs and
plans stay consistent and DRY. Read this first; then each phase's own spec/plan for the detail.

**Companion documents (this planning set):**

| Doc | Path | Status |
|---|---|---|
| Master architecture (this) | `specs/2026-07-20-hermes-master-architecture.md` | — |
| H0 spec | `specs/2026-07-20-hermes-h0-walking-skeleton-design.md` | written |
| H0 plan | `plans/2026-07-20-hermes-h0-walking-skeleton.md` | written |
| H0.5 spec + plan | `specs/2026-07-20-hermes-h05-daemon-scheduler-design.md` · `plans/…-h05-daemon-scheduler.md` | this set |
| H1 spec + plan | `specs/2026-07-20-hermes-h1-vault-hitl-design.md` · `plans/…-h1-vault-hitl.md` | this set |
| H2 spec + plan | `specs/2026-07-20-hermes-h2-staging-budget-design.md` · `plans/…-h2-staging-budget.md` | this set |
| H3 spec + plan | `specs/2026-07-20-hermes-h3-vps-deploy-design.md` · `plans/…-h3-vps-deploy.md` | this set |

## 1. What Hermes is

Hermes is the **persistent background orchestrator** named as deferred in the AI-OS charter
(`canon/2026-07-17-ai-os-charter.md`): the runtime that runs agents/teams and executes domain-pack
tools, with a credential vault, human-in-the-loop approval, staging enforcement, and budget caps.
It is **built local-first in Docker** and **deployed to a Hostinger VPS**
(`decisions/candidates/2026-07-17-hermes-local-first-deploy.md`), adopting the **Eve
filesystem-as-registry pattern only** (`decisions/active/vercel-eve-fs-architecture-adoption.md`).

The engine is **Claude Code headless** (`claude -p`): Hermes never embeds a model loop; it spawns
the CLI, which runs the agent/pack with its tools, hooks, and permission modes. This reuses the
entire existing `.claude/agents/` + `skills/` + `hooks/` substrate verbatim.

## 2. Design decisions locked here (cross-cutting)

Each is flagged **DECISION (recommended)** — the recommendation the per-phase plans assume. Any can
be overridden at review; overriding one only touches the phase that owns it plus this table.

| # | Area | Decision | Rationale |
|---|---|---|---|
| D1 | Engine | Claude Code headless (`claude -p --output-format json`) | Reuse the whole substrate; no bespoke agent loop (from H0) |
| D2 | Loader runtime | Node ≥20 (H0), **≥22 from H0.5** | H0.5+ uses built-in `node:sqlite` (stable in 22); pin in Docker |
| D3 | Persistence | **`node:sqlite`** (built-in), one file `hermes/state/hermes.db`, introduced at **H0.5** via a shared `hermes/lib/db.js` migration runner | Zero-ops, ACID, single-VPS fit; no server, no native-compile dep, no cloud lock-in |
| D4 | Credential vault | **Encrypted file**, AES-256-GCM via Node `crypto`; master key from env `HERMES_VAULT_KEY` (out-of-band) | VPS-friendly, no external KMS; swappable behind the `Vault` interface later |
| D5 | Execution guard | Two layers: (a) Hermes pre-spawn tier check (H0), (b) a Hermes-injected **PreToolUse hook** in the spawned CLI that queues/denies write-tier actions | Reuses the existing `hooks/` pattern; the guard lives where tool calls happen |
| D6 | HITL model | Approval gates **between plan and side-effecting execution**, not mid-LLM-turn; pending actions persisted in SQLite; resume via a follow-on run | `claude -p` is one-shot; matches the pack "approval-gated writes" contract |
| D7 | Daemon | Persistent process = a **thin supervisor over the H0 one-shot core**; scheduler enqueues runs | Keeps the core testable and unchanged; identity stays "runs H0 runs" |
| D8 | Deploy | **git pull + `docker compose build` on the VPS**; image not shipped via registry in v1 | Repo is source of truth; simplest for a single box; vault key injected out-of-band |
| D9 | Frameworks | **No LangChain / CrewAI in v1**; governed, deferred candidates | Charter principles #1 (governance-first) & #6 (measure before scaling) |

## 3. Component architecture (all phases)

Phases are additive. A component's phase tag says when it first appears; later phases extend it,
never rewrite it. `[H0]` components already have a written plan.

```
┌────────────────────────────────────────────────────────────────────────────┐
│  Hermes (Docker container on the VPS; local-first in dev)                     │
│                                                                              │
│  ┌─────────────┐   [H0.5] triggers   ┌──────────────────────────────────┐   │
│  │ scheduler   │────────────────────▶│ daemon / supervisor        [H0.5] │   │
│  │ (cron-like) │                     │  - run queue (SQLite)             │   │
│  └─────────────┘   [H0.5] enqueue    │  - one worker → invokes core      │   │
│  ┌─────────────┐───────────────────▶ │  - lifecycle + retries            │   │
│  │ CLI: hermes │  (H0 direct path)   └───────────────┬──────────────────┘   │
│  │  run <t>    │                                      │                       │
│  └─────────────┘                                      ▼                       │
│                          ┌───────────────────────────────────────────────┐  │
│                          │  RUN CORE                                       │  │
│   ┌──────────┐           │  ┌────────┐  ┌────────┐  ┌───────────────┐     │  │
│   │ loader   │──registry▶│  │ runner │─▶│ claude │  │ result-gate   │     │  │
│   │ +tier    │  [H0]     │  │  [H0]  │  │  -p    │  │   [H0]        │     │  │
│   │ chk [H0] │           │  └───┬────┘  └───┬────┘  └───────┬───────┘     │  │
│   └──────────┘           │      │ injects   │ PreToolUse    │ writes      │  │
│        ▲ reads           │      ▼           ▼ hook          ▼             │  │
│  .claude/agents/ packs/  │  ┌────────┐  ┌────────────┐  evals/hermes/runs/│  │
│  hermes.config.json      │  │ vault  │  │ guard hook │                    │  │
│                          │  │  [H1]  │  │   [H1]     │                    │  │
│                          │  └────────┘  └─────┬──────┘                    │  │
│                          │   secrets in        │ write-tier action?       │  │
│                          │   (scrubbed after)  ▼                          │  │
│                          │            ┌────────────────────┐             │  │
│                          │            │ policy engine [H1+]│             │  │
│                          │            │ - HITL approval[H1]│             │  │
│                          │            │ - staging chk [H2] │             │  │
│                          │            │ - budget ledger[H2]│             │  │
│                          │            └─────────┬──────────┘             │  │
│                          └──────────────────────┼────────────────────────┘  │
│                                                 ▼                            │
│                        ┌───────────────────────────────────────┐            │
│                        │  SQLite: hermes/state/hermes.db  [H1]  │            │
│                        │  runs · approvals · budget_ledger      │            │
│                        └───────────────────────────────────────┘            │
│                                                                              │
│  Secrets store (encrypted): hermes/state/vault.enc  [H1]                     │
└────────────────────────────────────────────────────────────────────────────┘
```

### Component responsibilities

- **loader** `[H0]` — discover governed targets, fail-closed tier check. (built plan exists)
- **runner** `[H0]` — build argv, spawn `claude -p`, capture. Extended `[H1]` to inject vault
  secrets as scoped env and a Hermes settings file that registers the guard hook.
- **result-gate** `[H0]` — parse, verify, write run manifest. Extended `[H2]` to record budget
  consumption into the ledger.
- **daemon/supervisor** `[H0.5]` — long-running process; pulls from the run queue; invokes the run
  core; handles lifecycle, retries, and (H1) resumes approved runs.
- **scheduler** `[H0.5]` — cron-like; enqueues runs on a schedule (Eve `schedules/` idea).
- **vault** `[H1]` — `get/set/list/delete` secrets in an encrypted file; decrypt only into a run's
  scoped process env; never to disk artifacts; scrub after.
- **guard hook** `[H1]` — a PreToolUse hook Hermes injects into the spawned CLI; classifies each
  tool call's tier and routes write-tier calls to the policy engine.
- **policy engine** `[H1+]` — decides allow / deny / require-approval for a proposed action:
  HITL approval `[H1]`, staging-target check `[H2]`, budget check `[H2]`.
- **SQLite** `[H0.5]` — durable state via `hermes/lib/db.js`: `runs` `[H0.5]`, `approvals` `[H1]`,
  `budget_ledger` `[H2]`.

## 4. Shared data model (SQLite `hermes.db`)

One file, opened via a shared `hermes/lib/db.js` migration runner introduced at **H0.5**. Each phase
adds its own migration; tables are created idempotently (`CREATE TABLE IF NOT EXISTS`).

```sql
-- [H0.5] every enqueued/executed run (the daemon and gate both write here)
CREATE TABLE IF NOT EXISTS runs (
  run_id      TEXT PRIMARY KEY,          -- YYYYMMDD-HHMMSS-<target>
  target_id   TEXT NOT NULL,
  kind        TEXT NOT NULL,             -- 'agent' | 'pack'
  tier        TEXT NOT NULL,             -- 'read-only' | 'hitl' | 'staging-autonomous'
  status      TEXT NOT NULL,             -- queued|running|awaiting_approval|resumed|done|failed
  exit_code   INTEGER,
  git_sha     TEXT,
  created_at  TEXT NOT NULL,
  updated_at  TEXT NOT NULL
);

-- [H1] a proposed write-tier action paused for human approval
CREATE TABLE IF NOT EXISTS approvals (
  approval_id TEXT PRIMARY KEY,
  run_id      TEXT NOT NULL REFERENCES runs(run_id),
  tool        TEXT NOT NULL,             -- e.g. 'Bash', pack tool name
  action      TEXT NOT NULL,             -- human-readable description of the side effect
  payload     TEXT NOT NULL,             -- JSON: exact args to execute on approval
  status      TEXT NOT NULL,             -- pending|approved|rejected|expired
  decided_by  TEXT,                      -- who approved (operator id/email)
  created_at  TEXT NOT NULL,
  decided_at  TEXT
);

-- [H2] money/quota ledger; append-only, one row per spend/quota event
CREATE TABLE IF NOT EXISTS budget_ledger (
  entry_id    TEXT PRIMARY KEY,
  run_id      TEXT NOT NULL REFERENCES runs(run_id),
  pack        TEXT NOT NULL,
  kind        TEXT NOT NULL,             -- 'ad_spend' | 'api_quota' | 'llm_tokens'
  amount      REAL NOT NULL,
  currency    TEXT,                      -- for ad_spend
  created_at  TEXT NOT NULL
);
```

## 5. Run lifecycle state machine

H0 has only the left column. H0.5 adds `queued`. H1 adds the approval branch.

```
[H0]     resolve ──▶ running ──▶ done | failed
[H0.5]   queued ──▶ running ──▶ done | failed          (+ retries)
[H1]     running ──▶ awaiting_approval ──(approve)──▶ resumed ──▶ done
                                        └─(reject)───▶ failed
                                        └─(expire)───▶ failed
```

A run that hits a write-tier action under the HITL tier: the guard hook denies the tool call in the
first `claude -p` pass, records an `approvals` row (`pending`) with the exact payload, and the run
ends `awaiting_approval`. On approval, the daemon executes the recorded payload (or launches a
resume run) and advances to `done`. This is D6 — the "pause" is between plan and execution, durable
across restarts.

## 6. Security posture (whole system)

Layered, and each layer is testable in isolation:

1. **Tier fail-closed** `[H0]` — nothing runs unless allow-listed at an allowed tier.
2. **No secrets at rest in the clear** `[H1]` — vault is AES-256-GCM; master key never in git,
   never in a run artifact; decrypted values live only in a child process's env and are scrubbed.
3. **Write-tier interception** `[H1]` — every side-effecting tool call passes the guard hook;
   unapproved writes are denied, not executed.
4. **Staging containment** `[H2]` — staging-autonomous packs may only target their declared
   `staging_target`; production destinations are denied.
5. **Budget hard stops** `[H2]` — spend/quota past a cap is denied; soft cap → HITL.
6. **Network isolation** `[H0–H2 local]` — no inbound surface until H3; H3 adds only SSH (keys) +
   the deploy path, behind UFW + fail2ban.
7. **Auditability** `[H0+]` — every run and every approval/spend is a durable, timestamped,
   git-SHA-stamped record. "What ran, with what secret scope, approved by whom, costing what" is
   always answerable.

**Non-negotiables (brain Hard Rules):** no secrets in `.project-brain/` or in `packs/`; no
stealth/ToS-evasion tooling; real credentials only reach the VPS after H1+H2 are hardened and
security-reviewed (H3 gate).

## 7. Phase dependency graph

```
H0 (skeleton, read-only) ─▶ H0.5 (daemon + scheduler; introduces SQLite/db.js)
                             └─▶ H1 (vault + HITL) ─▶ H2 (staging + budget) ─▶ H3 (VPS + real creds)
```

- The plan assumes a **linear order**. H0.5 introduces the shared `hermes/lib/db.js` (SQLite),
  which H1/H2 reuse for the `approvals` and `budget_ledger` tables. H0.5 and H1 *could* be
  parallelized (both need only H0's run core) if `db.js` is factored out first, but the linear
  order is simpler and is what the per-phase plans assume.
- H2 depends on H1 (guard hook + policy engine). H3 depends on H1 + H2 and uses H0.5's daemon for
  scheduled production runs.
- **H3 is the only phase that touches real, money-spending credentials**, and only after a security
  review gate.

## 8. What "done" means for the whole runtime

Hermes v1 is complete when: the daemon runs scheduled and on-demand runs on the VPS; read-only
packs run autonomously; HITL packs (Google Ads) pause for approval and resume; staging-autonomous
packs (WordPress/Bricks) write only to staging; budgets are enforced; all secrets are vaulted; and
every run/approval/spend is audited. Retrieval upgrade (LangChain) and multi-session coordination
(CrewAI) remain **out of scope**, revisited only on a measured need per D9.

## 9. Governance status

Every Hermes decision (local-first, Eve pattern, and all of §2) is currently **candidate** memory.
Per the brain Hard Rules, promotion to `active`/`canon` is a human-gated `brain-promote --approve`
call — not done here. This document and the per-phase docs are planning artifacts, not promoted
decisions.
