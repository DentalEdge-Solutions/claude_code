# Hermes H2 — Staging Enforcement + Budget Caps (design spec)

> **⚠ DEFERRED — Operate track.** Per the definitive roadmap
> (`~/.claude/plans/iterative-squishing-church.md`, brain candidate
> `.project-brain/decisions/candidates/2026-07-21-hermes-definitive-roadmap.md`), this phase is part of
> the credential-bearing **Hermes Operate track**, built just-in-time with the first spawned operator
> project — **not** part of the credential-free kernel v1.

> **Date:** 2026-07-20 · **Status:** design (planning only) · **Depends on:** H1
> **Master:** `specs/2026-07-20-hermes-master-architecture.md`

H2 adds the last two policy rules the pack contract already declares but leaves to "the future
Hermes runtime": **staging containment** (staging-autonomous packs may only write to their declared
staging target) and **budget caps** (money packs may not exceed per-client spend limits). Both are
extensions of the H1 policy engine + guard — no new interception mechanism.

## Grounding in the real pack contract (verified 2026-07-17 packs)

- **WordPress pack** (`packs/wordpress/guardrails/policy.json`): `execution_mode:
  "staging-autonomous"`, `staging_target: "clients.<client>.staging_site_url"`, `production_guard`
  note: *"the runtime must refuse any write whose resolved target is not the client's
  staging_site_url."* Writes run **autonomously** (no per-action approval) — but only against staging.
- **Google Ads pack** (`packs/google-ads/guardrails/policy.json`, `risk_tier: critical`):
  `execution_mode: "hitl"`, `budget_caps.max_daily_budget_field:
  "clients.<client>.max_daily_budget_usd"`, note: *"the runtime must refuse (or re-prompt for
  approval on) any budget change that exceeds the client's cap."* Tools like
  `gads_update_campaign_budget` carry `new_daily_budget_usd`; `gads_create_campaign` must create
  campaigns **paused** within the cap.
- Per-client values live under `packs/<pack>/clients/<client>/` (the pack contract's client binding).

## Goal

1. **Staging containment** — for a `staging-autonomous` run, resolve the pack's `staging_target`
   from the client binding; allow a write **only if** its resolved target equals that staging value;
   otherwise deny. No per-action approval (that's the tier's point) — but no production write, ever.
2. **Budget caps** — for a money-affecting action, resolve the per-client cap; if the proposed
   amount exceeds it, **deny** (hard cap) or route to HITL (soft cap); record every spend/quota
   event in the `budget_ledger` so cumulative limits are enforceable and auditable.

Enabling these makes the `staging-autonomous` tier safe to run autonomously and hardens the `hitl`
money path from H1.

## Non-goals (deferred)

VPS deploy and real credentials (H3). Actual pack-tool implementations against live APIs (those are
the packs' own work; H2 provides the enforcement the tools run under). Production-promotion flows
(explicitly out of scope per the WordPress pack contract).

## Design decisions

- **Enforcement metadata is data-driven** — a pack's `guardrails/policy.json` gains an optional
  `enforcement` map: per tool, which arg field is the write **target** and which is the spend
  **amount/kind**. This keeps enforcement knowledge in the pack's guardrails (where `staging_target`
  and `budget_caps` already live), not hardcoded in Hermes. Fail closed: a `staging-autonomous`/money
  write tool with no enforcement mapping is **denied** (the runtime cannot verify it, so it must not
  run it).
- **Client resolution** — a small resolver reads `packs/<pack>/clients/<client>/binding.json` and
  resolves dotted field paths (`clients.<client>.staging_site_url`) to concrete values.
- **Budget ledger is append-only** — cumulative spend is `SUM(amount)` over the ledger for a
  client/pack/day; the check is `existing + proposed <= cap`.

## Architecture

```
hermes/
├── lib/
│   ├── client-binding.js  # [new] resolve clients/<client>/binding.json + dotted field paths
│   ├── budget.js          # [new] ledger record + wouldExceed over budget_ledger
│   ├── policy.js          # [extend] add staging + budget rules to evaluate()
│   └── ...
├── hooks/guard.js         # [extend] extract target/amount via pack enforcement map; call policy
└── migrations/003-budget.sql
```

### Extended policy decision (H2)

`evaluate(action, ctx)` gains `ctx.packPolicy`, `ctx.binding`, `ctx.client`, `ctx.db`:

```
write-tier action, runTier = staging-autonomous:
    target = extractTarget(action, packPolicy.enforcement)     # e.g. site URL
    if target === null                → deny (no enforcement mapping; fail closed)
    stagingTarget = resolve(binding, packPolicy.staging_target)
    if target === stagingTarget       → allow      (autonomous staging write)
    else                              → deny        (production/other → refused)

write-tier action, runTier = hitl, money-affecting:
    amount = extractAmount(action, packPolicy.enforcement)
    cap    = resolve(binding, packPolicy.budget_caps.max_daily_budget_field)
    spentToday = budget.spentToday(db, client, pack, day)
    if amount == null                 → require_approval   (unknown amount → human)
    if spentToday + amount > cap      → deny               (hard cap breach)
    else                              → require_approval   (H1 approval still applies)
```

Read-tier remains `allow`; `read-only` run tier still denies any write (unchanged from H1).

### Budget ledger

Recorded when an approved money action actually executes (in the approve→execute path from H1's
`action-runner`): `budget.record(db, { runId, pack, client, kind, amount, currency })`. Enforcement
reads `spentToday` before allowing/approving the next action, so cumulative daily spend is capped —
not just single actions.

## Data model

Adds migration `003-budget.sql` (the `budget_ledger` table from master §4).

## Error handling

- **Missing client binding / unresolvable field path** → deny (fail closed): a staging or money
  write cannot proceed if the runtime can't resolve the target or cap.
- **Tool with no enforcement mapping under an enforced tier** → deny, with a clear "no enforcement
  metadata for tool X" message (prompts the pack author to declare it).
- **Cap resolves to null/NaN** → deny (never treat a missing cap as unlimited).
- **Ledger write failure** after execution → the action already ran; record a reconciliation-needed
  marker on the run and surface it loudly (money moved but wasn't ledgered — must be visible).

## Security

- **No production write path** for staging-autonomous packs — enforced structurally, not by
  convention; a write to anything but the resolved staging target is denied.
- **Hard spend ceilings** — cumulative daily spend is enforced from the ledger; a single call can't
  exceed the cap and neither can a sequence of calls.
- **Money actions still pass H1 HITL** — budget enforcement is *in addition to* human approval for
  `hitl` packs, and campaigns are created paused (per the pack contract) — defense in depth.
- Everything is ledgered and audited (who, what, how much, which client, which run).

## Testing strategy

- **client-binding.js** — resolves a dotted path from a fixture `binding.json`; missing file →
  throws/null; unknown field → null.
- **budget.js** — `record` appends; `spentToday` sums only today's rows for that client/pack;
  `wouldExceed` boundary tests (`==cap` allowed, `>cap` blocked).
- **policy.js (extended)** — staging write to the staging target → allow; to any other target →
  deny; staging write tool with no enforcement mapping → deny; money action within cap →
  require_approval; over cumulative cap → deny; unresolvable cap → deny.
- **guard.js (extended)** — extracts target/amount from a fake tool event via a fixture enforcement
  map and produces the right decision; unmapped tool → deny.
- Integration: a simulated staging-autonomous write to the wrong host is denied and never executes;
  a money action over the cap is denied; one within cap follows the H1 approval path and, on
  approval+execution, writes a ledger row that a second over-budget attempt then trips.

## Definition of done

- [ ] `node scripts/run-all-tests.js` → all suites green.
- [ ] A staging-autonomous write to the resolved `staging_target` is allowed autonomously; to any
      other target it is denied.
- [ ] A staging/money write tool lacking enforcement metadata is denied (fail closed).
- [ ] A money action exceeding the per-client (cumulative daily) cap is denied; within-cap follows
      the H1 approval path and records a ledger entry.
- [ ] `staging-autonomous` is safe to add to `allowed_tiers`.

## Out of scope

VPS deploy, real credentials, security review gate → H3.
