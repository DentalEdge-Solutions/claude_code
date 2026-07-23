# Hermes H2 — Staging Enforcement + Budget Caps Implementation Plan

> **⚠ DEFERRED — Operate track.** Part of the credential-bearing **Hermes Operate track** (built
> just-in-time with the first operator project), not the kernel v1. Authoritative:
> `~/.claude/plans/iterative-squishing-church.md` and
> `.project-brain/decisions/candidates/2026-07-21-hermes-definitive-roadmap.md`.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Enforce that staging-autonomous packs write only to their declared staging target, and that money packs never exceed per-client cumulative daily budget caps.

**Architecture:** Add `lib/client-binding.js` (resolve per-client bindings + dotted field paths) and `lib/budget.js` (append-only ledger + cap checks), then extend `lib/policy.js` and `hooks/guard.js` with staging and budget rules driven by each pack's `guardrails/policy.json` `enforcement` map.

**Tech Stack:** Node ≥22, CommonJS, `node:sqlite`, `node:test`. No new runtime dependencies.

**Spec:** `docs/superpowers/specs/2026-07-20-hermes-h2-staging-budget-design.md` · **Master:** `docs/superpowers/specs/2026-07-20-hermes-master-architecture.md`

## Global Constraints

- Enforcement metadata is data-driven from `packs/<pack>/guardrails/policy.json`; never hardcode a pack.
- **Fail closed:** unresolvable target/cap, missing binding, or a write tool with no enforcement mapping → deny.
- Budget cap check is **cumulative daily** (`spentToday + proposed <= cap`), sourced from the ledger.
- Staging-autonomous writes run without per-action approval, but only to the resolved `staging_target`.
- CommonJS, `'use strict'`, no new runtime deps.

---

### Task 1: Client binding resolver (`lib/client-binding.js`)

**Files:**
- Create: `hermes/lib/client-binding.js`
- Test: `hermes/test/client-binding.test.js`

**Interfaces:**
- Produces:
  - `loadBinding(repoRoot, pack, client) → object` — reads `packs/<pack>/clients/<client>/binding.json`.
  - `resolveField(binding, dottedPath, client) → value|null` — resolves `clients.<client>.<field>` against the binding; unknown path → null.

- [ ] **Step 1: Write the failing tests**

Create `hermes/test/client-binding.test.js`:

```js
'use strict';
const { test } = require('node:test');
const assert = require('node:assert');
const fs = require('fs');
const os = require('os');
const path = require('path');
const { loadBinding, resolveField } = require('../lib/client-binding');

function fixture() {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'hermes-cb-'));
  const dir = path.join(root, 'packs', 'wordpress', 'clients', 'acme');
  fs.mkdirSync(dir, { recursive: true });
  fs.writeFileSync(path.join(dir, 'binding.json'), JSON.stringify({
    staging_site_url: 'https://staging.acme.test',
    max_daily_budget_usd: 50,
  }));
  return root;
}

test('loadBinding reads a client binding', () => {
  const root = fixture();
  const b = loadBinding(root, 'wordpress', 'acme');
  assert.equal(b.staging_site_url, 'https://staging.acme.test');
});

test('resolveField resolves clients.<client>.<field>', () => {
  const b = { staging_site_url: 'https://staging.acme.test' };
  assert.equal(resolveField(b, 'clients.<client>.staging_site_url', 'acme'), 'https://staging.acme.test');
});

test('resolveField returns null for an unknown field', () => {
  assert.equal(resolveField({}, 'clients.<client>.nope', 'acme'), null);
});
```

- [ ] **Step 2: Run to verify it fails** — `node hermes/test/client-binding.test.js` → `Cannot find module`.

- [ ] **Step 3: Write `lib/client-binding.js`**

```js
'use strict';
const fs = require('fs');
const path = require('path');

function loadBinding(repoRoot, pack, client) {
  const p = path.join(repoRoot, 'packs', pack, 'clients', client, 'binding.json');
  if (!fs.existsSync(p)) return null;
  return JSON.parse(fs.readFileSync(p, 'utf8'));
}

// Field paths in the pack contract look like "clients.<client>.staging_site_url".
// The binding object is already scoped to one client, so we take the trailing field.
function resolveField(binding, dottedPath, client) {
  if (!binding || !dottedPath) return null;
  const field = dottedPath.replace(/^clients\.<client>\./, '').replace(new RegExp(`^clients\\.${client}\\.`), '');
  return Object.prototype.hasOwnProperty.call(binding, field) ? binding[field] : null;
}

module.exports = { loadBinding, resolveField };
```

- [ ] **Step 4: Run to verify it passes** — `node hermes/test/client-binding.test.js` → PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add hermes/lib/client-binding.js hermes/test/client-binding.test.js
git commit -m "feat(hermes): per-client binding resolver for pack enforcement"
```

---

### Task 2: Budget ledger (`lib/budget.js`) + migration

**Files:**
- Create: `hermes/lib/budget.js`
- Create: `hermes/migrations/003-budget.sql`
- Test: `hermes/test/budget.test.js`

**Interfaces:**
- Consumes: `db` (H0.5).
- Produces:
  - `record(db, { runId, pack, client, kind, amount, currency }, now) → entryId`.
  - `spentToday(db, { pack, client, kind }, now) → number`.
  - `wouldExceed(db, { pack, client, kind, cap, proposed }, now) → boolean`.

- [ ] **Step 1: Write the migration**

Create `hermes/migrations/003-budget.sql`:

```sql
CREATE TABLE IF NOT EXISTS budget_ledger (
  entry_id    TEXT PRIMARY KEY,
  run_id      TEXT NOT NULL,
  pack        TEXT NOT NULL,
  client      TEXT NOT NULL,
  kind        TEXT NOT NULL,
  amount      REAL NOT NULL,
  currency    TEXT,
  created_at  TEXT NOT NULL
);
```

- [ ] **Step 2: Write the failing tests**

Create `hermes/test/budget.test.js`:

```js
'use strict';
const { test } = require('node:test');
const assert = require('node:assert');
const fs = require('fs');
const os = require('os');
const path = require('path');
const { openDb } = require('../lib/db');
const budget = require('../lib/budget');

function db() {
  return openDb(path.join(fs.mkdtempSync(path.join(os.tmpdir(), 'hermes-b-')), 'hermes.db'));
}
const base = { runId: 'r1', pack: 'google-ads', client: 'acme', kind: 'ad_spend', currency: 'USD' };

test('spentToday sums only today rows for that client/pack/kind', () => {
  const d = db();
  budget.record(d, { ...base, amount: 10 }, new Date('2026-07-20T09:00:00Z'));
  budget.record(d, { ...base, amount: 15 }, new Date('2026-07-20T10:00:00Z'));
  budget.record(d, { ...base, amount: 99 }, new Date('2026-07-19T10:00:00Z')); // yesterday
  assert.equal(budget.spentToday(d, base, new Date('2026-07-20T12:00:00Z')), 25);
});

test('wouldExceed is false at exactly the cap, true above it', () => {
  const d = db();
  budget.record(d, { ...base, amount: 40 }, new Date('2026-07-20T09:00:00Z'));
  assert.equal(budget.wouldExceed(d, { ...base, cap: 50, proposed: 10 }, new Date('2026-07-20T12:00:00Z')), false);
  assert.equal(budget.wouldExceed(d, { ...base, cap: 50, proposed: 11 }, new Date('2026-07-20T12:00:00Z')), true);
});

test('a null cap always exceeds (fail closed)', () => {
  assert.equal(budget.wouldExceed(db(), { ...base, cap: null, proposed: 1 }, new Date()), true);
});
```

- [ ] **Step 3: Run to verify it fails** — `node hermes/test/budget.test.js` → `Cannot find module '../lib/budget'`.

- [ ] **Step 4: Write `lib/budget.js`**

```js
'use strict';
const crypto = require('crypto');

function record(db, { runId, pack, client, kind, amount, currency }, now = new Date()) {
  const id = `led-${now.getTime()}-${crypto.randomBytes(3).toString('hex')}`;
  db.prepare(
    `INSERT INTO budget_ledger (entry_id, run_id, pack, client, kind, amount, currency, created_at)
     VALUES (?, ?, ?, ?, ?, ?, ?, ?)`
  ).run(id, runId, pack, client, kind, amount, currency || null, now.toISOString());
  return id;
}

function spentToday(db, { pack, client, kind }, now = new Date()) {
  const day = now.toISOString().slice(0, 10); // YYYY-MM-DD
  const row = db.prepare(
    `SELECT COALESCE(SUM(amount), 0) AS total FROM budget_ledger
     WHERE pack = ? AND client = ? AND kind = ? AND substr(created_at, 1, 10) = ?`
  ).get(pack, client, kind, day);
  return row.total;
}

function wouldExceed(db, { pack, client, kind, cap, proposed }, now = new Date()) {
  if (cap === null || cap === undefined || Number.isNaN(Number(cap))) return true; // fail closed
  return spentToday(db, { pack, client, kind }, now) + Number(proposed) > Number(cap);
}

module.exports = { record, spentToday, wouldExceed };
```

- [ ] **Step 5: Run to verify it passes** — `node hermes/test/budget.test.js` → PASS (3 tests).

- [ ] **Step 6: Commit**

```bash
git add hermes/lib/budget.js hermes/migrations/003-budget.sql hermes/test/budget.test.js
git commit -m "feat(hermes): append-only budget ledger with cumulative daily cap check"
```

---

### Task 3: Extend the policy engine with staging + budget rules

**Files:**
- Modify: `hermes/lib/policy.js`
- Test: `hermes/test/policy-h2.test.js`

**Interfaces:**
- Extend `evaluate(action, ctx)`; `ctx` now may include `{ packPolicy, binding, client, db, pack }`.
- Add helpers: `extractTarget(action, enforcement)` and `extractAmount(action, enforcement) → { amount, kind }` — read the arg fields named in the pack's `enforcement` map.

- [ ] **Step 1: Write the failing tests**

Create `hermes/test/policy-h2.test.js`:

```js
'use strict';
const { test } = require('node:test');
const assert = require('node:assert');
const fs = require('fs');
const os = require('os');
const path = require('path');
const { openDb } = require('../lib/db');
const { evaluate } = require('../lib/policy');

const enforcement = {
  wp_update_content: { target_field: 'site_url' },
  gads_update_campaign_budget: { amount_field: 'new_daily_budget_usd', budget_kind: 'ad_spend' },
};

test('staging write to the resolved staging target is allowed', () => {
  const r = evaluate(
    { tool: 'wp_update_content', args: { site_url: 'https://staging.acme.test' } },
    {
      runTier: 'staging-autonomous',
      packPolicy: { enforcement, staging_target: 'clients.<client>.staging_site_url' },
      binding: { staging_site_url: 'https://staging.acme.test' },
      client: 'acme',
      packMeta: { tools: { wp_update_content: 'staging-autonomous' } },
    }
  );
  assert.equal(r.decision, 'allow');
});

test('staging write to any other target is denied', () => {
  const r = evaluate(
    { tool: 'wp_update_content', args: { site_url: 'https://www.acme.com' } },
    {
      runTier: 'staging-autonomous',
      packPolicy: { enforcement, staging_target: 'clients.<client>.staging_site_url' },
      binding: { staging_site_url: 'https://staging.acme.test' },
      client: 'acme',
      packMeta: { tools: { wp_update_content: 'staging-autonomous' } },
    }
  );
  assert.equal(r.decision, 'deny');
});

test('a staging write tool with no enforcement mapping is denied', () => {
  const r = evaluate(
    { tool: 'wp_unmapped', args: {} },
    {
      runTier: 'staging-autonomous',
      packPolicy: { enforcement, staging_target: 'clients.<client>.staging_site_url' },
      binding: { staging_site_url: 'https://staging.acme.test' },
      client: 'acme',
      packMeta: { tools: { wp_unmapped: 'staging-autonomous' } },
    }
  );
  assert.equal(r.decision, 'deny');
});

test('a money action over the cumulative cap is denied', () => {
  const d = openDb(path.join(fs.mkdtempSync(path.join(os.tmpdir(), 'hermes-ph2-')), 'hermes.db'));
  const r = evaluate(
    { tool: 'gads_update_campaign_budget', args: { new_daily_budget_usd: 100 } },
    {
      runTier: 'hitl', db: d, pack: 'google-ads', client: 'acme',
      packPolicy: { enforcement, budget_caps: { max_daily_budget_field: 'clients.<client>.max_daily_budget_usd' } },
      binding: { max_daily_budget_usd: 50 },
      packMeta: { tools: { gads_update_campaign_budget: 'hitl' } },
    }
  );
  assert.equal(r.decision, 'deny');
});

test('a money action within cap still requires approval (H1 path)', () => {
  const d = openDb(path.join(fs.mkdtempSync(path.join(os.tmpdir(), 'hermes-ph2b-')), 'hermes.db'));
  const r = evaluate(
    { tool: 'gads_update_campaign_budget', args: { new_daily_budget_usd: 40 } },
    {
      runTier: 'hitl', db: d, pack: 'google-ads', client: 'acme',
      packPolicy: { enforcement, budget_caps: { max_daily_budget_field: 'clients.<client>.max_daily_budget_usd' } },
      binding: { max_daily_budget_usd: 50 },
      packMeta: { tools: { gads_update_campaign_budget: 'hitl' } },
    }
  );
  assert.equal(r.decision, 'require_approval');
});
```

- [ ] **Step 2: Run to verify it fails** — `node hermes/test/policy-h2.test.js` → FAIL (new rules not present; staging/budget branches missing).

- [ ] **Step 3: Extend `lib/policy.js`**

Add the helpers and the new branches; keep the H1 behavior intact:

```js
const { resolveField } = require('./client-binding');
const budget = require('./budget');

function extractTarget(action, enforcement) {
  const map = enforcement && enforcement[action.tool];
  if (!map || !map.target_field) return null;
  const v = action.args ? action.args[map.target_field] : undefined;
  return v === undefined ? null : v;
}

function extractAmount(action, enforcement) {
  const map = enforcement && enforcement[action.tool];
  if (!map || !map.amount_field) return null;
  const v = action.args ? action.args[map.amount_field] : undefined;
  return v === undefined ? null : { amount: Number(v), kind: map.budget_kind || 'ad_spend' };
}
```

Then, inside `evaluate`, after computing `tier` and handling `read` / `read-only`, replace the
`staging-autonomous` and money branches:

```js
// write-tier below:
if (ctx.runTier === 'staging-autonomous') {
  const target = extractTarget(action, ctx.packPolicy && ctx.packPolicy.enforcement);
  if (target === null) return { decision: 'deny', reason: 'no enforcement mapping for staging write' };
  const staging = resolveField(ctx.binding, ctx.packPolicy.staging_target, ctx.client);
  if (staging === null) return { decision: 'deny', reason: 'unresolvable staging_target' };
  return target === staging
    ? { decision: 'allow', reason: 'staging write to resolved staging_target' }
    : { decision: 'deny', reason: 'write target is not the staging_target' };
}

if (ctx.runTier === 'hitl') {
  const money = extractAmount(action, ctx.packPolicy && ctx.packPolicy.enforcement);
  if (money) {
    const capField = ctx.packPolicy.budget_caps && ctx.packPolicy.budget_caps.max_daily_budget_field;
    const cap = resolveField(ctx.binding, capField, ctx.client);
    if (budget.wouldExceed(ctx.db, { pack: ctx.pack, client: ctx.client, kind: money.kind, cap, proposed: money.amount }, new Date())) {
      return { decision: 'deny', reason: 'exceeds cumulative daily budget cap' };
    }
  }
  return { decision: 'require_approval', reason: 'write-tier under hitl' };
}
```

- [ ] **Step 4: Run to verify it passes** — `node hermes/test/policy-h2.test.js` → PASS; `node hermes/test/policy.test.js` (H1) → still PASS.

- [ ] **Step 5: Commit**

```bash
git add hermes/lib/policy.js hermes/test/policy-h2.test.js
git commit -m "feat(hermes): policy engine staging containment + cumulative budget cap"
```

---

### Task 4: Wire enforcement into the guard + ledger on execution, add enforcement maps

**Files:**
- Modify: `hermes/hooks/guard.js` (load pack policy/binding; pass to `evaluate`)
- Modify: `hermes/bin/hermes.js` (approve→execute path records a ledger entry for money actions)
- Modify: `packs/wordpress/guardrails/policy.json` and `packs/google-ads/guardrails/policy.json` (add `enforcement` maps)
- Test: `hermes/test/enforcement-integration.test.js`

**Interfaces:**
- Guard resolves `packPolicy` from `packs/<pack>/guardrails/policy.json`, `binding` via
  `client-binding.loadBinding`, and `client` from env (`HERMES_CLIENT`), then calls `evaluate` with
  the full context.
- The approve→execute path (H1 Task 7) calls `budget.record(...)` after a money action executes.

- [ ] **Step 1: Add enforcement maps to the two packs**

To `packs/wordpress/guardrails/policy.json`, add:

```json
"enforcement": {
  "wp_update_content": { "target_field": "site_url" },
  "wp_create_post":    { "target_field": "site_url" },
  "wp_update_bricks_template": { "target_field": "site_url" }
}
```

To `packs/google-ads/guardrails/policy.json`, add:

```json
"enforcement": {
  "gads_update_campaign_budget": { "amount_field": "new_daily_budget_usd", "budget_kind": "ad_spend" },
  "gads_create_campaign":        { "amount_field": "daily_budget_usd", "budget_kind": "ad_spend" }
}
```

(These are additive; `pack-audit` should be re-run to confirm the packs still pass — see Step 4.)

- [ ] **Step 2: Extend `hooks/guard.js` to load pack context**

In the `main()` wrapper, read `HERMES_PACK`, `HERMES_CLIENT` from env; load
`packs/<pack>/guardrails/policy.json` and the client binding; pass `packPolicy`, `binding`,
`client`, `pack`, `db` into `decide`/`evaluate`. Keep `decide` pure (extend its signature to accept
the extra ctx). The runner (H1 Task 6) sets `HERMES_PACK`/`HERMES_CLIENT` when the target is a pack.

- [ ] **Step 3: Write the integration test**

Create `hermes/test/enforcement-integration.test.js` covering: (a) a staging write to a non-staging
host is denied via the guard with a real fixture pack policy + binding; (b) a money action within
cap → approval path → on execute, a ledger row is written; (c) a second money action that would now
exceed the cumulative cap is denied. Use the `decide`/`evaluate` functions directly with a temp db
and fixture policy/binding (no live CLI needed).

- [ ] **Step 4: Verify packs still pass their audit**

Run: `node skills/skill-audit/scripts/static-scan.js packs/wordpress` and the pack-audit for the two
packs (per the repo's pack-audit tooling). Expected: PASS with the added `enforcement` blocks.
Then `node scripts/run-all-tests.js` → all green.

- [ ] **Step 5: Enable staging-autonomous**

In `hermes/hermes.config.json`, `allowed_tiers` may now include `"staging-autonomous"`.

- [ ] **Step 6: Commit**

```bash
git add hermes/hooks/guard.js hermes/bin/hermes.js packs/wordpress/guardrails/policy.json packs/google-ads/guardrails/policy.json hermes/test/enforcement-integration.test.js hermes/hermes.config.json
git commit -m "feat(hermes): wire staging+budget enforcement into guard; ledger on execute"
```

---

## Definition of done (H2)

- [ ] `node scripts/run-all-tests.js` → all suites green.
- [ ] Staging-autonomous write to the resolved `staging_target` → allowed; any other target → denied; unmapped tool → denied.
- [ ] Money action over the cumulative daily cap → denied; within cap → H1 approval path → ledger entry recorded on execution.
- [ ] Both packs still pass pack-audit with their new `enforcement` maps.
- [ ] `hitl` and `staging-autonomous` are both safe in `allowed_tiers`.

## Out of scope

VPS provisioning, real credentials, and the security-review gate → H3.
