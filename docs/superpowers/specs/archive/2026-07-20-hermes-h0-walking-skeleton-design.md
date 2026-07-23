# Hermes H0 — Walking Skeleton (design spec)

> **Date:** 2026-07-20 · **Status:** design (awaiting implementation plan)
> **Scope:** the first runnable slice of the Hermes orchestrator. H1–H3 are roadmap only.

## Context & grounding

This spec is the first concrete design for **Hermes**, the persistent background orchestrator
named as deferred in the AI-OS charter. It formalizes and extends decisions already recorded in
the Second Brain — it does not reopen them:

- **AI-OS charter** (`canon/2026-07-17-ai-os-charter.md`) — Hermes = the runtime that runs
  agents/teams and executes pack tools (credential vault, HITL pause/resume, staging enforcement).
  Deferred; not yet started.
- **Eve filesystem-as-registry** (`decisions/active/vercel-eve-fs-architecture-adoption.md`) —
  adopt the **pattern only** (convention-over-config folder registry + `evals/` as deploy gate),
  not the Eve runtime. Framework-agnostic, VPS-friendly.
- **Hermes local-first** (`decisions/candidates/2026-07-17-hermes-local-first-deploy.md`) — build
  locally in Docker for dev/prod parity; the Hostinger VPS is a deploy target; real credentials
  only after the vault + HITL are hardened and security-reviewed.
- **Domain packs** (`docs/superpowers/specs/2026-07-17-domain-packs-design.md`) — contract-first,
  execution-mode tiers (`read-only` / `HITL` / `staging-autonomous`); the pack **runtime is
  deferred to Hermes**. Hermes must honor this existing contract; the contract is a fixed input.

**Operating-principle alignment:** governance-first, human-gated durability, filesystem-as-registry,
memory authority ranking, non-negotiable safety boundaries, and *measure before scaling
infrastructure* (charter §"Operating principles"). H0 is deliberately the smallest slice that
proves the pattern end-to-end while touching nothing security-sensitive.

## Goal

Deliver a **runnable Hermes** as fast as possible while de-risking the pattern, not the hard
security engineering. H0 = **a Node one-shot CLI, in Docker, that discovers governed targets, runs
a credential-free one through the `claude` CLI, gates the result to a durable manifest, and fails
closed on anything it is not explicitly allowed to run.**

### Non-goals (explicitly deferred to later phases)

- Credential vault, secret handling (H1)
- Human-in-the-loop pause/resume (H1)
- Staging enforcement, budget caps, HITL/staging-autonomous tiers (H2)
- VPS deploy, real client credentials, hardening/security review (H3)
- Persistent daemon, scheduler, HTTP/Slack channels (H0.5+)
- Retrieval upgrade (LangChain) and multi-session coordination (CrewAI) — see Future work

## Decisions locked in this session

| Decision | Choice | Rationale |
|---|---|---|
| Spec scope | H0 walking skeleton only | Fastest runnable Hermes; hard parts get focused specs |
| Execution engine | Claude Code **headless** (`claude -p`) | Reuses `.claude/agents`, skills, hooks, permission modes verbatim; near-zero new agent-loop code; same precedent as the Codex external-eval layer |
| Loader runtime | **Node ≥18** | Matches repo stack (`run-all-tests.js`, scripts-only), CLI ecosystem. H0 has no database dependency, so the standard `run-all-tests.js` floor of Node ≥18 is sufficient — no need for the higher `node:sqlite`-driven floor that H0.5 introduces |
| Packaging | **Docker from day one** | Dev/prod parity; "deploy" = run the same container on the VPS |
| First target | **Credential-free internal agent** (e.g. `repo-audit-testing`) | Proves the loop with zero credential exposure |
| Lifecycle | **One-shot CLI** `hermes run <target>` | Fewest moving parts; daemon becomes a thin H0.5 wrapper |
| Structure | **Approach A** — thin core + minimal Eve-vocabulary `hermes/` dir | Honors the Eve pattern minimally; gives H1 a foundation, not a rewrite |
| Target input | **Fixed prompt per target in `hermes.config.json`** | Deterministic skeleton, no interactive input |
| Test framework | House style — plain `require('assert')` + a minimal manual runner, standalone `node <file>` (see `scripts/run-calibration.test.js`), wired into `run-all-tests.js` | No new dependency; matches the repo's existing test idiom (not `node:test`) |
| `hermes.config.json` | **Committed to git** (allow-list, not a secret) | Reviewability; only `evals/hermes/runs/` is gitignored |

## Architecture

Hermes H0 is a one-shot Node CLI running *inside a Docker container* that orchestrates the `claude`
CLI to execute one already-governed target, then records the run. Four responsibilities, and
deliberately nothing else.

```
┌─────────────────────────────────────────────────────────────┐
│  Docker container (node + claude CLI bundled)                 │
│                                                               │
│   $ hermes run <target>                                       │
│        │                                                      │
│        ▼                                                      │
│   ┌──────────┐   registry    ┌──────────┐   spawn   ┌───────┐ │
│   │ loader   │──────────────▶│ runner   │──────────▶│ claude│ │
│   │ (discover│  {targets,    │ (build   │  child    │  -p   │ │
│   │  + valid)│   tiers}      │  argv,   │  process  └───┬───┘ │
│   └──────────┘               │  spawn)  │◀──────────────┘     │
│        ▲                     └────┬─────┘   JSON result        │
│        │ reads                    ▼                            │
│   .claude/agents/  packs/    ┌──────────┐                     │
│   hermes/hermes.config.json  │ result-  │─▶ evals/hermes/runs/│
│                              │ gate     │     <id>/{result,    │
│                              │ (parse + │      manifest}.json  │
│                              │  verify) │                      │
│                              └──────────┘                     │
└─────────────────────────────────────────────────────────────┘
```

### Module boundaries

- **loader** — walks `.claude/agents/` + `packs/registry.json`, cross-checks against
  `hermes.config.json` (the allow-list of runnable targets + their execution tier), returns an
  in-memory registry. Pure, no side effects, heavily tested.
- **runner** — takes a resolved target, builds the `claude -p` argv, spawns the child process,
  captures stdout/stderr/exit/duration. The only module that touches a subprocess.
- **result-gate** — parses the JSON result, verifies it against manifest invariants, writes
  artifacts to `evals/hermes/runs/<id>/`. The deploy-gate discipline, scaled to H0.

### What H0 does NOT do (the boundary as a feature)

No vault, no HITL, no network-exposed surface, no scheduler, no HITL/staging-autonomous execution.
The loader **refuses** any target whose tier is not credential-free `read-only`. Failing closed on
those is precisely what keeps H0 safe. Agents/packs are discovered in place (no duplication); the
only new registry artifact is the thin `hermes.config.json` allow-list.

## File layout

```
hermes/
├── hermes.config.json          # the allow-list (only new registry artifact; committed)
├── bin/hermes.js               # CLI entrypoint: `hermes run <target>`
├── lib/
│   ├── loader.js               # discover + validate → registry
│   ├── runner.js               # build argv + spawn claude -p
│   └── result-gate.js          # parse + verify + write artifacts
├── test/                       # house-style (plain assert) unit + stub-integration tests
├── Dockerfile
└── docker-compose.yml
evals/hermes/runs/<run-id>/     # result.json + manifest.json (generated, gitignored)
```

### `hermes.config.json` — the trust boundary as data

```json
{
  "runnable_targets": [
    {
      "id": "repo-audit-testing",
      "kind": "agent",
      "tier": "read-only",
      "prompt": "Audit the current repository"
    }
  ],
  "allowed_tiers": ["read-only"],
  "runs_dir": "evals/hermes/runs"
}
```

A target not listed here, or carrying a tier outside `allowed_tiers`, is unrunnable in H0. This is
the file H1 extends (not rewrites) when the vault arrives.

## Module interfaces

**`loader.js`** — `loadRegistry(config, repoRoot) → { targets: Map, errors: [] }`
- Walks `.claude/agents/*.md` and `packs/registry.json` **dynamically** (never hardcodes names —
  existing repo rule).
- Keeps only targets present in *both* the filesystem *and* `runnable_targets`.
- **Fails closed:** a configured target missing on disk, or any tier ∉ `allowed_tiers`, is a hard
  error — no partial run. Pure function.

**`runner.js`** — `run(target, opts) → { stdout, stderr, code, argv, durationMs, runId, error }`
- Builds argv: `["-p", "--output-format", "json", "--agent", target.id, target.prompt]` plus a
  read-only permission mode; agent runs non-interactively. The exact `--permission-mode` flag name
  is to be confirmed against `claude --help` at build time — the CLI's headless flags are not
  assumed to be stable across versions.
- Spawns via `child_process.spawnSync` with an **argv array** (never shell-interpolated —
  injection-safe), applies a timeout, captures streams. `runId` (timestamp+slug) generated here.
  `error` is `null` on a normal exit, or `{ type: 'ENOENT'|'TIMEOUT'|'SPAWN', message }` otherwise.

**`result-gate.js`** — `gate(target, runResult, config, ctx) → { status, manifest, artifactDir }`.
`ctx = { repoRoot, gitSha }`.
- Parses stdout as JSON; on parse failure → `status: "error"` with raw stderr preserved.
- Verifies manifest invariants: expected target ran, `code === 0`, tier respected, no unexpected
  write paths reported.
- Writes `result.json` (the `claude` payload) + `manifest.json` (Hermes's record: target, tier,
  argv, timing, gate verdict, git SHA) to `runs/<id>/`.

**`bin/hermes.js`** — thin orchestrator: parse argv → loader → runner → result-gate → print
summary + exit code. No business logic; wiring only.

## Data flow (one `hermes run repo-audit-testing`)

```
1. INVOKE     bin/hermes.js parses argv, reads hermes.config.json
2. DISCOVER   loader walks .claude/agents + packs; cross-checks allow-list
              ├─ not on disk / not allow-listed / bad tier → HARD ERROR (exit 2), nothing spawned
              └─ resolve → { id: repo-audit-testing, kind: agent, tier: read-only, prompt: ... }
3. RUN        runner: runId + argv (array) + spawn claude -p; capture streams
              ├─ ENOENT (claude missing) → exit 3
              ├─ timeout → kill child → exit 4
              └─ normal exit → downstream
4. GATE       result-gate: JSON.parse → verify invariants → write runs/<id>/{result,manifest}.json
              ├─ parse fail → exit 5 (raw output preserved)
              └─ ok → manifest verdict
5. REPORT     print [loader]/[run]/[gate] summary; exit 0
```

### Guaranteed properties

- **Fail-closed ordering** — validation happens *before* any subprocess exists. A disallowed or
  missing target can never reach `spawn`. Security precedes execution, structurally.
- **Distinct exit codes** — 2=validation, 3=engine-missing, 4=timeout, 5=bad-output — so any
  caller (a human today, the H0.5 daemon later) branches on *why* without parsing text.
- **Durable, reviewable trace** — every run (including failures) writes `manifest.json` with the
  git SHA, so runs are reproducible and auditable. Seed of the H1+ deploy gate.

## Error handling

| Failure | Detection | Behavior | Exit |
|---|---|---|---|
| Unknown/misconfigured target | loader validation | Hard stop before spawn; list valid targets | 2 |
| `claude` CLI absent | `spawn` ENOENT | "engine not found — is the CLI in the image?" | 3 |
| Run exceeds timeout | timer kills child | Child terminated, partial stderr preserved | 4 |
| Non-JSON / malformed output | `JSON.parse` throws | Raw stdout+stderr saved to run dir | 5 |
| Non-zero exit from `claude` | exit code check | `manifest.json` records failure verdict, artifacts kept | 5 |

Every path writes a `manifest.json`; no exception is swallowed. A crash in Hermes itself exits
non-zero with the stack — never a false green (`verification-before-completion` in code).

## Security

H0 is safe by having a **small surface** and **failing closed**, not by adding machinery:

1. **No secrets, anywhere.** Only credential-free `read-only` targets run; the loader fails closed
   on any higher tier. No vault because nothing that needs one can run — aligned with the
   local-first "harden before real creds" sequencing and the brain's no-secrets hard rule.
2. **No network-exposed surface.** One-shot CLI, no daemon, no HTTP. Nothing to attack remotely.
3. **Injection-safe subprocess.** `spawnSync` with an argv array; target ids/prompts are never
   concatenated into a shell string. The loader constrains `target` to the allow-list before use,
   so it cannot be a path-traversal or flag-injection vector.
4. **Contained writes.** Hermes writes only under `evals/hermes/runs/`. The spawned agent inherits
   Claude Code's read-only permission mode (passed on argv), so it cannot write outside its sandbox.
5. **Auditability as a control.** Every `manifest.json` records target, tier, exact argv, git SHA —
   "what did Hermes run, with what, when" is always answerable. H1's credential/HITL review builds
   on this.

The through-line: fortification (vault, HITL, staging enforcement) is H1–H3; H0's allow-list + tier
check is the hook they plug into.

## Testing strategy

Testing mirrors the module boundaries. All via the repo's house style (plain `require('assert')` + a
minimal manual runner, standalone `node <file>` — see `scripts/run-calibration.test.js`), wired into
`run-all-tests.js`.

**Layer 1 — Unit (pure, fast):**
- **loader.js** (security-critical, heaviest coverage): resolves a valid allow-listed target;
  **fails closed** on (a) target missing on disk, (b) target not in allow-list, (c) tier ∉
  `allowed_tiers` — each its own test; proves dynamic discovery using an invented fixture repo dir
  (no hardcoded names).
- **result-gate.js**: valid JSON → verdict; malformed JSON → `error` with raw output preserved;
  non-zero exit → failure verdict; asserts `manifest.json` shape.

**Layer 2 — Integration (runner, stubbed engine):**
- A fake `claude` on `PATH` (tiny stub echoing canned JSON) tests argv construction, stdout
  capture, exit-code propagation, timeout kill, and ENOENT — deterministic and **offline, zero API
  cost**.

**Layer 3 — End-to-end smoke (one real run, opt-in):**
- `hermes run <credential-free-agent>` against the real `claude` CLI; asserts a `runs/<id>/` dir
  with a passing manifest. Gated behind an env flag (like the Codex `--live` discipline) so
  `run-all-tests.js`/CI stay free and offline by default.

### Definition of done (verification gate)

```
✓ node --test hermes/           → unit + stub-integration green
✓ node scripts/run-all-tests.js → Hermes suite included, all green
✓ hermes run <agent> (live, once) → real run writes a passing manifest
✓ hermes run <disallowed>        → exits 2, spawns nothing (fail-closed proven)
```

The last line matters most: a *demonstrated refusal* is the evidence H0's safety boundary holds —
not just that the happy path works.

## Roadmap beyond H0

Each phase is its own spec → plan → build cycle. Later phases *extend* H0's files; they do not
rewrite them.

| Phase | Slice | Depends on |
|---|---|---|
| **H0.5** | Persistent daemon + scheduler (thin wrapper around the H0 core) | H0 |
| **H1** | Credential vault + HITL pause/resume; unlock `HITL` tier | H0 |
| **H2** | Staging enforcement + budget caps; unlock `staging-autonomous` tier | H1 |
| **H3** | VPS provision/harden, security review, real credentials, cutover | H1, H2 |

## Future work — governed, deferred (LangChain / CrewAI)

Per the brain's operating principles #1 (governance-first) and #6 (measure before scaling
infrastructure), these are recorded as **deferred candidates**, not H0 scope:

- **LangChain** — considered *only* when a retrieval need is *measurably* demonstrated (the
  charter's deferred "retrieval upgrade"). Would enter via `scout → audit → adapt → eval`, not be
  baked into the core. Hermes v1 stays framework-agnostic.
- **CrewAI** — considered *only* if multi-Hermes-session coordination with distinct memory
  namespaces becomes a measured need. It is a *second* orchestration framework layered on Hermes,
  in tension with the Eve decision's framework-agnostic, lock-in-free intent — so it carries a
  higher bar and must clear the same governed adoption path.

Trigger for revisiting either: a concrete, measured need surfaced during H1–H3, captured as a brain
candidate first.

## Open questions (for later phases, not H0)

- Durable-session backing store on the VPS (Redis vs SQLite vs Postgres; `gbrain` Postgres is a
  registered retrieval option) — H1.
- Where the tool-execution security guard lives (extend the existing PreToolUse hook pattern?) — H1.
- Daemon trigger surface (HTTP vs watch/queue) — H0.5.
