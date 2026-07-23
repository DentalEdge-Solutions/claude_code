# Hermes H1 — Credential Vault + Human-in-the-Loop (design spec)

> **⚠ DEFERRED — Operate track.** Per the definitive roadmap
> (`~/.claude/plans/iterative-squishing-church.md`, brain candidate
> `.project-brain/decisions/candidates/2026-07-21-hermes-definitive-roadmap.md`), this phase is part of
> the credential-bearing **Hermes Operate track**, built just-in-time with the first spawned operator
> project — **not** part of the credential-free kernel v1. Review findings A–R are tracked in the
> roadmap and folded in when this track is built.

> **Date:** 2026-07-20 · **Status:** design (planning only) · **Depends on:** H0, H0.5
> **Master:** `specs/2026-07-20-hermes-master-architecture.md`

This is the "real engineering" the Eve adoption decision named: *"the folder pattern is easy; secure
self-hosted code execution is the hard part."* H1 makes Hermes able to hold secrets safely and to
pause a run for human approval before any side-effecting action executes.

## Goal

Two capabilities, one phase because they interlock:

1. **Credential vault** — store secrets encrypted at rest; decrypt them only into a single run's
   child-process environment; never write them to run artifacts; scrub after the run.
2. **HITL approval gate** — intercept every write-tier tool call, record it as a durable pending
   approval, deny it in-run, and end the run `awaiting_approval`. A human approves/rejects out of
   band; on approval Hermes executes the exact recorded action; on rejection the run fails.

Together these unlock the `hitl` execution tier (the Google Ads pack contract: approval-gated
writes).

## Non-goals (deferred)

Staging-target enforcement and budget caps (H2 — they are additional policy-engine rules on the
same guard). VPS + real credentials (H3). Mid-LLM-turn pause (explicitly rejected — master **D6**).

## Design decisions (from master §2)

- **D4 Vault:** encrypted file `hermes/state/vault.enc`, AES-256-GCM, 256-bit key from env
  `HERMES_VAULT_KEY` (base64). Key is provisioned out of band, never in git, never in a run
  artifact. The `Vault` interface is storage-agnostic so a KMS backend can replace the file later.
- **D5 Guard:** a Hermes-provided **PreToolUse hook** injected into the spawned `claude -p` via a
  Hermes-generated settings file. The hook classifies the tool call and calls the policy engine.
- **D6 HITL model:** approval sits **between plan and execution**. The guard denies the write-tier
  call, persists the exact action payload, and the run ends `awaiting_approval`. Approval executes
  the recorded payload deterministically (Hermes runs exactly what was approved — not a fresh LLM
  turn), which is the safe model for money-spending actions.

## Architecture

```
hermes/
├── lib/
│   ├── vault.js         # [new] AES-256-GCM get/set/list/delete over vault.enc
│   ├── policy.js        # [new] evaluate(action, ctx) → allow | deny | require_approval
│   ├── approvals.js     # [new] create / list / decide over the approvals table
│   ├── action-runner.js # [new] execute an approved action payload (argv) safely
│   ├── runner.js        # [extend] inject vault secrets as scoped env; write guard settings file
│   └── ... (H0/H0.5 modules)
├── hooks/
│   └── guard.js         # [new] PreToolUse hook: classify → policy → allow/deny + record approval
├── bin/
│   └── hermes.js        # [extend] vault + approvals subcommands
└── migrations/
    └── 002-approvals.sql
```

### The HITL flow (end to end)

```
1. daemon/core.execute(pack@hitl)
2. runner.run: decrypt the pack's declared secrets → child env; write a settings file that
   registers hooks/guard.js as a PreToolUse hook; spawn claude -p
3. agent decides to call a write-tier tool (e.g. a pack "create campaign" tool / a Bash mutation)
4. guard.js (PreToolUse) fires: classify tier
      read-tier   → allow (exit 0)
      write-tier  → policy.evaluate → require_approval:
                      approvals.create(run_id, tool, action, payload=argv)  [status pending]
                      deny the tool call (hook exit code / JSON per Claude Code hook contract)
5. agent cannot complete the write; claude -p returns; core marks run awaiting_approval
6. secrets scrubbed from env (process ends)
7. human: `hermes approvals list` → `hermes approvals approve <id>` (or reject)
8. approve → action-runner executes the recorded payload with the pack's secret scope;
   run row → done; rejection → run row → failed
```

### Vault interface

```
vault.set(name, value)        # encrypts + persists
vault.get(name) → value|null  # decrypts in memory only
vault.list() → string[]       # names only, never values
vault.delete(name)
```

Encryption detail: per-secret random 12-byte IV; AES-256-GCM; stored record is
`{ iv, authTag, ciphertext }` base64 in a JSON map inside `vault.enc`. Wrong/missing key → decrypt
throws a clear error; the run fails closed (never runs a pack without its required secret).

### Secret scoping

A pack declares required secrets in its contract (e.g. `pack.json: { "secrets": ["google_ads_token"] }`).
`runner.run` resolves only those names from the vault and injects them as env vars **for that one
child process**, then the child exits and the values are gone. Secrets are never written to
`result.json`/`manifest.json` (the gate already writes only parsed payload + metadata; add a scrub
assertion that no known secret value appears in artifacts).

### Guard tier classification

The guard maps a tool call to a tier:
- **read-tier:** `Read`, `Grep`, `Glob`, read-only pack tools (declared `read-only` in the pack).
- **write-tier:** `Write`, `Edit`, `Bash` (unless whitelisted read-only commands), and any pack tool
  declared `hitl`/`staging-autonomous`.
Classification is data-driven from the pack contract + a small built-in tool map — never hardcoded
per pack.

## Data model

Adds migration `002-approvals.sql` (the `approvals` table from master §4) and uses the `runs`
status values `awaiting_approval` and `resumed`.

## Error handling

- **Missing/invalid `HERMES_VAULT_KEY`:** vault ops throw; any run needing a secret fails closed
  with a clear message; no partial execution.
- **Guard hook cannot reach SQLite:** the guard **denies** (fail closed) — a write is never allowed
  when the approval couldn't be recorded.
- **Approving an already-decided/expired approval:** rejected with a clear message; idempotent.
- **action-runner failure on approved payload:** run → `failed`, error captured in the run row and a
  run artifact; the approval stays `approved` (audit trail of intent vs outcome).
- **Expiry:** approvals older than a configurable TTL are `expired` by the daemon reaper; their runs
  → `failed`.

## Security

This is the phase where the security posture becomes load-bearing:

- Secrets encrypted at rest (AES-256-GCM); key never persisted with the data.
- Decrypted secrets live only in a child process env for one run; scrubbed on exit; never in
  artifacts (asserted by test).
- Every write-tier action is *denied by default* and only executes after an explicit, recorded
  human decision — the guard fails closed on any uncertainty (unknown tool tier → treat as write).
- Full audit: who approved, what exact payload, when, tied to a run and git SHA.
- Still no inbound network surface (that's H3). Approvals are decided via the local CLI.

## Testing strategy

- **vault.js** — set→get round-trips; `get` of a missing name → null; `list` returns names not
  values; a wrong key makes `get` throw; the on-disk file contains no plaintext secret (grep the
  ciphertext file for the known value → absent).
- **policy.js** — read-tier → allow; write-tier under `hitl` → require_approval; unknown tool tier →
  require_approval (fail closed); `read-only` tier pack write attempt → deny.
- **approvals.js** — create → pending; list pending; approve sets approved+decided_by+decided_at;
  approving twice is idempotent/rejected; expire marks expired.
- **guard.js** — given a fake PreToolUse payload for a write tool, it records a pending approval and
  emits the deny decision; for a read tool it allows and records nothing. (Uses a temp db; the
  exact hook stdin/stdout contract is confirmed against Claude Code hook docs in a plan step.)
- **action-runner.js** — executes a recorded argv payload (a harmless marker-writing command),
  returns success; a failing payload → captured error, non-zero.
- **secret scrubbing** — after a stubbed run that injects a secret, assert the value is absent from
  both `result.json` and `manifest.json`.
- Integration: a stubbed HITL run creates a pending approval and ends `awaiting_approval`; `approve`
  then drives the recorded payload and flips the run to `done`.

## Definition of done

- [ ] Vault stores/retrieves secrets; nothing plaintext on disk; wrong key fails closed.
- [ ] A write-tier tool call under the `hitl` tier is intercepted, recorded as pending, denied; the
      run ends `awaiting_approval`.
- [ ] `hermes approvals approve <id>` executes exactly the recorded payload → run `done`; `reject`
      → run `failed`.
- [ ] No secret value appears in any run artifact (asserted).
- [ ] `hitl` added to `allowed_tiers` is now safe to enable for a pack.
- [ ] All suites green in `run-all-tests.js`.
