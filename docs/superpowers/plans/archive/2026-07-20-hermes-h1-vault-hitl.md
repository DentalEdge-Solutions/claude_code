# Hermes H1 — Credential Vault + HITL Implementation Plan

> **⚠ DEFERRED — Operate track.** Part of the credential-bearing **Hermes Operate track** (built
> just-in-time with the first operator project), not the kernel v1. Authoritative:
> `~/.claude/plans/iterative-squishing-church.md` and
> `.project-brain/decisions/candidates/2026-07-21-hermes-definitive-roadmap.md`.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Store secrets encrypted at rest and inject them per-run, and gate every write-tier tool call behind a durable human approval before it executes.

**Architecture:** `vault.js` (AES-256-GCM) + `policy.js` (allow/deny/require_approval) + `approvals.js` (SQLite) + `action-runner.js` (execute an approved payload) + a `hooks/guard.js` PreToolUse hook injected into `claude -p`. The runner is extended to inject scoped secrets and register the guard.

**Tech Stack:** Node ≥22, CommonJS, built-in `crypto` + `node:sqlite`, `node:test`. No new runtime dependencies.

**Spec:** `docs/superpowers/specs/2026-07-20-hermes-h1-vault-hitl-design.md` · **Master:** `docs/superpowers/specs/2026-07-20-hermes-master-architecture.md`

## Global Constraints

- Encryption: AES-256-GCM, 256-bit key from env `HERMES_VAULT_KEY` (base64, 32 bytes decoded).
- Vault file `hermes/state/vault.enc`; SQLite `hermes/state/hermes.db`; both under gitignored `hermes/state/`.
- **Fail closed everywhere:** missing key, unrecordable approval, or unknown tool tier → deny/fail, never execute.
- No secret value may ever appear in a run artifact — assert it in a test.
- CommonJS, `'use strict'`, no new runtime deps.

---

### Task 1: Credential vault (`lib/vault.js`)

**Files:**
- Create: `hermes/lib/vault.js`
- Test: `hermes/test/vault.test.js`

**Interfaces:**
- Produces:
  - `set(name, value, opts)` · `get(name, opts) → string|null` · `list(opts) → string[]` · `delete(name, opts)`.
  - `opts = { vaultPath, key }` (both default from env/state for real use; injected in tests).

- [ ] **Step 1: Write the failing tests**

Create `hermes/test/vault.test.js`:

```js
'use strict';
const { test } = require('node:test');
const assert = require('node:assert');
const crypto = require('crypto');
const fs = require('fs');
const os = require('os');
const path = require('path');
const vault = require('../lib/vault');

function ctx() {
  const key = crypto.randomBytes(32).toString('base64');
  const vaultPath = path.join(fs.mkdtempSync(path.join(os.tmpdir(), 'hermes-v-')), 'vault.enc');
  return { key, vaultPath };
}

test('set then get round-trips a secret', () => {
  const o = ctx();
  vault.set('token', 's3cr3t-value', o);
  assert.equal(vault.get('token', o), 's3cr3t-value');
});

test('get of a missing name returns null', () => {
  assert.equal(vault.get('nope', ctx()), null);
});

test('list returns names but never values', () => {
  const o = ctx();
  vault.set('a', 'AAA', o); vault.set('b', 'BBB', o);
  assert.deepEqual(vault.list(o).sort(), ['a', 'b']);
});

test('the on-disk file contains no plaintext secret', () => {
  const o = ctx();
  vault.set('token', 'PLAINTEXT_MARKER', o);
  const disk = fs.readFileSync(o.vaultPath, 'utf8');
  assert.equal(disk.includes('PLAINTEXT_MARKER'), false);
});

test('a wrong key makes get throw (fail closed)', () => {
  const o = ctx();
  vault.set('token', 'x', o);
  const wrong = { vaultPath: o.vaultPath, key: crypto.randomBytes(32).toString('base64') };
  assert.throws(() => vault.get('token', wrong));
});
```

- [ ] **Step 2: Run to verify it fails** — `node hermes/test/vault.test.js` → `Cannot find module '../lib/vault'`.

- [ ] **Step 3: Write `lib/vault.js`**

```js
'use strict';
const crypto = require('crypto');
const fs = require('fs');
const path = require('path');

function resolveKey(opts) {
  const b64 = opts.key || process.env.HERMES_VAULT_KEY;
  if (!b64) throw new Error('HERMES_VAULT_KEY is not set — cannot open the vault');
  const key = Buffer.from(b64, 'base64');
  if (key.length !== 32) throw new Error('HERMES_VAULT_KEY must decode to 32 bytes (256-bit)');
  return key;
}

function vaultFile(opts) {
  return opts.vaultPath || path.join(__dirname, '..', 'state', 'vault.enc');
}

function readStore(opts) {
  const p = vaultFile(opts);
  if (!fs.existsSync(p)) return {};
  return JSON.parse(fs.readFileSync(p, 'utf8'));
}

function writeStore(store, opts) {
  const p = vaultFile(opts);
  fs.mkdirSync(path.dirname(p), { recursive: true });
  fs.writeFileSync(p, JSON.stringify(store, null, 2), { mode: 0o600 });
}

function set(name, value, opts = {}) {
  const key = resolveKey(opts);
  const iv = crypto.randomBytes(12);
  const cipher = crypto.createCipheriv('aes-256-gcm', key, iv);
  const ciphertext = Buffer.concat([cipher.update(String(value), 'utf8'), cipher.final()]);
  const store = readStore(opts);
  store[name] = {
    iv: iv.toString('base64'),
    authTag: cipher.getAuthTag().toString('base64'),
    ciphertext: ciphertext.toString('base64'),
  };
  writeStore(store, opts);
}

function get(name, opts = {}) {
  const store = readStore(opts);
  const rec = store[name];
  if (!rec) return null;
  const key = resolveKey(opts);
  const decipher = crypto.createDecipheriv('aes-256-gcm', key, Buffer.from(rec.iv, 'base64'));
  decipher.setAuthTag(Buffer.from(rec.authTag, 'base64'));
  const out = Buffer.concat([decipher.update(Buffer.from(rec.ciphertext, 'base64')), decipher.final()]);
  return out.toString('utf8');
}

function list(opts = {}) {
  return Object.keys(readStore(opts));
}

function del(name, opts = {}) {
  const store = readStore(opts);
  delete store[name];
  writeStore(store, opts);
}

module.exports = { set, get, list, delete: del };
```

- [ ] **Step 4: Run to verify it passes** — `node hermes/test/vault.test.js` → PASS (5 tests). The wrong-key test passes because GCM auth-tag verification throws on `final()`.

- [ ] **Step 5: Commit**

```bash
git add hermes/lib/vault.js hermes/test/vault.test.js
git commit -m "feat(hermes): AES-256-GCM encrypted credential vault"
```

---

### Task 2: Policy engine (`lib/policy.js`)

**Files:**
- Create: `hermes/lib/policy.js`
- Test: `hermes/test/policy.test.js`

**Interfaces:**
- Produces:
  - `classifyTier(action, packMeta) → 'read' | 'write'` — `action = { tool, args }`.
  - `evaluate(action, ctx) → { decision: 'allow'|'deny'|'require_approval', reason }`. `ctx = { runTier, packMeta }`.

- [ ] **Step 1: Write the failing tests**

Create `hermes/test/policy.test.js`:

```js
'use strict';
const { test } = require('node:test');
const assert = require('node:assert');
const { classifyTier, evaluate } = require('../lib/policy');

test('read tools classify as read-tier', () => {
  assert.equal(classifyTier({ tool: 'Read', args: {} }), 'read');
  assert.equal(classifyTier({ tool: 'Grep', args: {} }), 'read');
});

test('write tools classify as write-tier', () => {
  assert.equal(classifyTier({ tool: 'Write', args: {} }), 'write');
  assert.equal(classifyTier({ tool: 'Bash', args: { command: 'rm -rf x' } }), 'write');
});

test('read-tier action is allowed regardless of run tier', () => {
  const r = evaluate({ tool: 'Read', args: {} }, { runTier: 'hitl' });
  assert.equal(r.decision, 'allow');
});

test('write-tier action under hitl requires approval', () => {
  const r = evaluate({ tool: 'Write', args: {} }, { runTier: 'hitl' });
  assert.equal(r.decision, 'require_approval');
});

test('write-tier action under read-only is denied', () => {
  const r = evaluate({ tool: 'Write', args: {} }, { runTier: 'read-only' });
  assert.equal(r.decision, 'deny');
});

test('an unknown tool is treated as write-tier (fail closed)', () => {
  assert.equal(classifyTier({ tool: 'MysteryTool', args: {} }), 'write');
});
```

- [ ] **Step 2: Run to verify it fails** — `node hermes/test/policy.test.js` → `Cannot find module '../lib/policy'`.

- [ ] **Step 3: Write `lib/policy.js`**

```js
'use strict';

const READ_TOOLS = new Set(['Read', 'Grep', 'Glob', 'NotebookRead', 'WebFetch', 'WebSearch']);

function classifyTier(action, packMeta) {
  // Pack-declared tool tiers win (data-driven, never hardcoded per pack).
  if (packMeta && packMeta.tools && packMeta.tools[action.tool]) {
    return packMeta.tools[action.tool] === 'read-only' ? 'read' : 'write';
  }
  if (READ_TOOLS.has(action.tool)) return 'read';
  // Everything else — including unknown tools — is write-tier. Fail closed.
  return 'write';
}

function evaluate(action, ctx = {}) {
  const tier = classifyTier(action, ctx.packMeta);
  if (tier === 'read') return { decision: 'allow', reason: 'read-tier tool' };
  // write-tier:
  if (ctx.runTier === 'read-only') return { decision: 'deny', reason: 'write attempted in read-only run' };
  if (ctx.runTier === 'hitl' || ctx.runTier === 'staging-autonomous') {
    return { decision: 'require_approval', reason: `write-tier tool under ${ctx.runTier}` };
  }
  return { decision: 'deny', reason: 'unknown run tier' };
}

module.exports = { classifyTier, evaluate, READ_TOOLS };
```

- [ ] **Step 4: Run to verify it passes** — `node hermes/test/policy.test.js` → PASS (6 tests).

- [ ] **Step 5: Commit**

```bash
git add hermes/lib/policy.js hermes/test/policy.test.js
git commit -m "feat(hermes): fail-closed policy engine (tier classification + decision)"
```

---

### Task 3: Approvals store (`lib/approvals.js`) + migration

**Files:**
- Create: `hermes/lib/approvals.js`
- Create: `hermes/migrations/002-approvals.sql`
- Test: `hermes/test/approvals.test.js`

**Interfaces:**
- Consumes: `db` (H0.5 `openDb`).
- Produces:
  - `create(db, { runId, tool, action, payload }, now) → approvalId`.
  - `listPending(db) → row[]`.
  - `decide(db, approvalId, { status, decidedBy }, now) → { ok, error? }` — idempotent; only a `pending` row can be decided.
  - `expireOlderThan(db, ttlMs, now) → count`.

- [ ] **Step 1: Write the migration**

Create `hermes/migrations/002-approvals.sql`:

```sql
CREATE TABLE IF NOT EXISTS approvals (
  approval_id TEXT PRIMARY KEY,
  run_id      TEXT NOT NULL,
  tool        TEXT NOT NULL,
  action      TEXT NOT NULL,
  payload     TEXT NOT NULL,
  status      TEXT NOT NULL,
  decided_by  TEXT,
  created_at  TEXT NOT NULL,
  decided_at  TEXT
);
```

- [ ] **Step 2: Write the failing tests**

Create `hermes/test/approvals.test.js`:

```js
'use strict';
const { test } = require('node:test');
const assert = require('node:assert');
const fs = require('fs');
const os = require('os');
const path = require('path');
const { openDb } = require('../lib/db');
const approvals = require('../lib/approvals');

function db() {
  return openDb(path.join(fs.mkdtempSync(path.join(os.tmpdir(), 'hermes-a-')), 'hermes.db'));
}
const payload = { runId: 'r1', tool: 'Bash', action: 'create campaign', payload: JSON.stringify(['echo', 'hi']) };

test('create makes a pending approval that lists', () => {
  const d = db();
  const id = approvals.create(d, payload, new Date());
  const pending = approvals.listPending(d);
  assert.equal(pending.length, 1);
  assert.equal(pending[0].approval_id, id);
  assert.equal(pending[0].status, 'pending');
});

test('decide approves a pending row with who + when', () => {
  const d = db();
  const id = approvals.create(d, payload, new Date());
  const r = approvals.decide(d, id, { status: 'approved', decidedBy: 'erick' }, new Date());
  assert.equal(r.ok, true);
  const row = d.prepare('SELECT * FROM approvals WHERE approval_id = ?').get(id);
  assert.equal(row.status, 'approved');
  assert.equal(row.decided_by, 'erick');
  assert.ok(row.decided_at);
});

test('deciding an already-decided approval is rejected (idempotent-safe)', () => {
  const d = db();
  const id = approvals.create(d, payload, new Date());
  approvals.decide(d, id, { status: 'approved', decidedBy: 'a' }, new Date());
  const again = approvals.decide(d, id, { status: 'rejected', decidedBy: 'b' }, new Date());
  assert.equal(again.ok, false);
});

test('expireOlderThan marks old pending rows expired', () => {
  const d = db();
  approvals.create(d, payload, new Date('2026-07-20T00:00:00Z'));
  const n = approvals.expireOlderThan(d, 3600000, new Date('2026-07-20T02:00:00Z'));
  assert.equal(n, 1);
  assert.equal(approvals.listPending(d).length, 0);
});
```

- [ ] **Step 3: Run to verify it fails** — `node hermes/test/approvals.test.js` → `Cannot find module '../lib/approvals'`.

- [ ] **Step 4: Write `lib/approvals.js`**

```js
'use strict';
const crypto = require('crypto');

function create(db, { runId, tool, action, payload }, now = new Date()) {
  const id = `apr-${now.getTime()}-${crypto.randomBytes(3).toString('hex')}`;
  db.prepare(
    `INSERT INTO approvals (approval_id, run_id, tool, action, payload, status, created_at)
     VALUES (?, ?, ?, ?, ?, 'pending', ?)`
  ).run(id, runId, tool, action, payload, now.toISOString());
  return id;
}

function listPending(db) {
  return db.prepare(`SELECT * FROM approvals WHERE status = 'pending' ORDER BY created_at ASC`).all();
}

function decide(db, approvalId, { status, decidedBy }, now = new Date()) {
  const row = db.prepare('SELECT status FROM approvals WHERE approval_id = ?').get(approvalId);
  if (!row) return { ok: false, error: 'approval not found' };
  if (row.status !== 'pending') return { ok: false, error: `approval already ${row.status}` };
  if (status !== 'approved' && status !== 'rejected') return { ok: false, error: 'invalid decision' };
  db.prepare(`UPDATE approvals SET status = ?, decided_by = ?, decided_at = ? WHERE approval_id = ?`)
    .run(status, decidedBy || null, now.toISOString(), approvalId);
  return { ok: true };
}

function expireOlderThan(db, ttlMs, now = new Date()) {
  const cutoff = new Date(now.getTime() - ttlMs).toISOString();
  const rows = db.prepare(`SELECT approval_id FROM approvals WHERE status = 'pending' AND created_at < ?`).all(cutoff);
  const upd = db.prepare(`UPDATE approvals SET status = 'expired', decided_at = ? WHERE approval_id = ?`);
  for (const r of rows) upd.run(now.toISOString(), r.approval_id);
  return rows.length;
}

module.exports = { create, listPending, decide, expireOlderThan };
```

- [ ] **Step 5: Run to verify it passes** — `node hermes/test/approvals.test.js` → PASS (4 tests).

- [ ] **Step 6: Commit**

```bash
git add hermes/lib/approvals.js hermes/migrations/002-approvals.sql hermes/test/approvals.test.js
git commit -m "feat(hermes): durable approvals store with decide + expiry"
```

---

### Task 4: Action runner (`lib/action-runner.js`)

Executes exactly the payload a human approved — deterministic, no LLM.

**Files:**
- Create: `hermes/lib/action-runner.js`
- Test: `hermes/test/action-runner.test.js`

**Interfaces:**
- Produces: `runAction(payload, opts) → { ok, code, stdout, stderr }`. `payload` is a JSON argv array; `opts = { cwd, env, timeoutMs }`. Uses `spawnSync` with an argv array (injection-safe).

- [ ] **Step 1: Write the failing tests**

Create `hermes/test/action-runner.test.js`:

```js
'use strict';
const { test } = require('node:test');
const assert = require('node:assert');
const fs = require('fs');
const os = require('os');
const path = require('path');
const { runAction } = require('../lib/action-runner');

test('runAction executes an approved argv payload', () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'hermes-act-'));
  const marker = path.join(dir, 'done.txt');
  const payload = JSON.stringify(['node', '-e', `require('fs').writeFileSync(${JSON.stringify(marker)}, 'ok')`]);
  const r = runAction(payload, {});
  assert.equal(r.ok, true);
  assert.equal(fs.readFileSync(marker, 'utf8'), 'ok');
});

test('runAction reports failure for a non-zero payload', () => {
  const payload = JSON.stringify(['node', '-e', 'process.exit(3)']);
  const r = runAction(payload, {});
  assert.equal(r.ok, false);
  assert.equal(r.code, 3);
});
```

- [ ] **Step 2: Run to verify it fails** — `node hermes/test/action-runner.test.js` → `Cannot find module '../lib/action-runner'`.

- [ ] **Step 3: Write `lib/action-runner.js`**

```js
'use strict';
const { spawnSync } = require('child_process');

function runAction(payload, opts = {}) {
  let argv;
  try { argv = JSON.parse(payload); }
  catch { return { ok: false, code: null, stdout: '', stderr: 'invalid payload JSON' }; }
  if (!Array.isArray(argv) || argv.length === 0) {
    return { ok: false, code: null, stdout: '', stderr: 'payload is not a non-empty argv array' };
  }
  const [cmd, ...args] = argv;
  const r = spawnSync(cmd, args, {
    cwd: opts.cwd || process.cwd(),
    env: opts.env || process.env,
    encoding: 'utf8',
    timeout: opts.timeoutMs || 120000,
    maxBuffer: 64 * 1024 * 1024,
  });
  return { ok: r.status === 0 && !r.error, code: r.status, stdout: r.stdout || '', stderr: r.stderr || (r.error ? r.error.message : '') };
}

module.exports = { runAction };
```

- [ ] **Step 4: Run to verify it passes** — `node hermes/test/action-runner.test.js` → PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add hermes/lib/action-runner.js hermes/test/action-runner.test.js
git commit -m "feat(hermes): deterministic action runner for approved payloads"
```

---

### Task 5: Guard hook (`hooks/guard.js`) — PreToolUse interception

**Files:**
- Create: `hermes/hooks/guard.js`
- Test: `hermes/test/guard.test.js`

**Interfaces:**
- The guard is invoked by Claude Code as a PreToolUse hook: it reads a JSON tool-call event on stdin and emits an allow/deny decision per the Claude Code hook contract. It needs the current `runId`, `runTier`, and db path — passed via env (`HERMES_RUN_ID`, `HERMES_RUN_TIER`, `HERMES_DB_PATH`) set by the runner.
- Produces (for testability): `decide(event, ctx) → { permission: 'allow'|'deny', approvalId? }` — pure over an injected `{ db, runId, runTier, packMeta }`; the thin stdin/stdout wrapper calls it.

- [ ] **Step 0: Confirm the Claude Code hook contract**

Read the existing repo hooks (`hooks/brain/*`) and the Claude Code hooks docs to confirm the exact PreToolUse stdin event shape and the expected stdout/exit convention for allow vs deny. Mirror the existing hook's I/O style. Adjust only the thin wrapper in Step 3 — the `decide` function and its tests below are contract-independent.

- [ ] **Step 1: Write the failing tests**

Create `hermes/test/guard.test.js`:

```js
'use strict';
const { test } = require('node:test');
const assert = require('node:assert');
const fs = require('fs');
const os = require('os');
const path = require('path');
const { openDb } = require('../lib/db');
const { migrate } = require('../lib/db');
const { decide } = require('../hooks/guard');
const approvals = require('../lib/approvals');

function db() {
  return openDb(path.join(fs.mkdtempSync(path.join(os.tmpdir(), 'hermes-g-')), 'hermes.db'));
}

test('a read-tier tool call is allowed and records no approval', () => {
  const d = db();
  const r = decide({ tool: 'Read', args: { file: 'x' } }, { db: d, runId: 'r1', runTier: 'hitl' });
  assert.equal(r.permission, 'allow');
  assert.equal(approvals.listPending(d).length, 0);
});

test('a write-tier tool call under hitl is denied and records a pending approval', () => {
  const d = db();
  const r = decide({ tool: 'Bash', args: { command: 'echo hi' } }, { db: d, runId: 'r1', runTier: 'hitl' });
  assert.equal(r.permission, 'deny');
  assert.ok(r.approvalId);
  assert.equal(approvals.listPending(d).length, 1);
});

test('when the db is unavailable the guard denies (fail closed)', () => {
  const r = decide({ tool: 'Bash', args: {} }, { db: null, runId: 'r1', runTier: 'hitl' });
  assert.equal(r.permission, 'deny');
});
```

- [ ] **Step 2: Run to verify it fails** — `node hermes/test/guard.test.js` → `Cannot find module '../hooks/guard'`.

- [ ] **Step 3: Write `hooks/guard.js`**

```js
'use strict';
const { evaluate } = require('../lib/policy');
const approvals = require('../lib/approvals');

// Pure decision — unit-tested. The stdin/stdout wrapper (bottom) adapts the
// Claude Code PreToolUse hook contract confirmed in Step 0.
function decide(event, ctx) {
  const action = { tool: event.tool, args: event.args || {} };
  const verdict = evaluate(action, { runTier: ctx.runTier, packMeta: ctx.packMeta });
  if (verdict.decision === 'allow') return { permission: 'allow' };
  if (verdict.decision === 'require_approval') {
    if (!ctx.db) return { permission: 'deny' }; // fail closed: cannot record → cannot allow
    try {
      const approvalId = approvals.create(ctx.db, {
        runId: ctx.runId,
        tool: action.tool,
        action: `${action.tool}: ${JSON.stringify(action.args).slice(0, 200)}`,
        payload: JSON.stringify(event.approvedArgv || []),
      });
      return { permission: 'deny', approvalId };
    } catch {
      return { permission: 'deny' };
    }
  }
  return { permission: 'deny' };
}

function main() {
  const { openDb } = require('../lib/db');
  const chunks = [];
  process.stdin.on('data', (c) => chunks.push(c));
  process.stdin.on('end', () => {
    let event = {};
    try { event = JSON.parse(Buffer.concat(chunks).toString('utf8')); } catch { /* deny below */ }
    let db = null;
    try { db = openDb(process.env.HERMES_DB_PATH); } catch { /* fail closed */ }
    const r = decide(event, {
      db,
      runId: process.env.HERMES_RUN_ID,
      runTier: process.env.HERMES_RUN_TIER,
    });
    // Emit per the confirmed Claude Code hook contract (Step 0). Deny → non-zero / block JSON.
    process.stdout.write(JSON.stringify(r));
    process.exit(r.permission === 'allow' ? 0 : 2);
  });
}

if (require.main === module) main();
module.exports = { decide };
```

- [ ] **Step 4: Run to verify it passes** — `node hermes/test/guard.test.js` → PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add hermes/hooks/guard.js hermes/test/guard.test.js
git commit -m "feat(hermes): PreToolUse guard hook — deny+record write-tier, fail closed"
```

---

### Task 6: Runner secret injection + guard settings wiring

**Files:**
- Modify: `hermes/lib/runner.js`
- Test: `hermes/test/runner-secrets.test.js`

**Interfaces:**
- Extend `run(target, opts)` to accept `opts.secrets` (map of name→value, resolved from the vault by the caller) and `opts.guard = { dbPath, runTier }`. It injects secrets as child env, writes a temporary settings file registering `hooks/guard.js` as PreToolUse (with `HERMES_*` env), passes it to `claude -p`, and removes the settings file after.
- Produces: unchanged return shape; adds `env` scoping internally.

- [ ] **Step 0: Confirm the settings/hook injection flag**

Run `claude --help`; confirm how a headless invocation loads a settings file that registers hooks (e.g. `--settings <path>` or a project `.claude/settings.json` placed in `cwd`). Implement whichever the CLI supports in `buildSpawnEnvAndSettings`. The secret-scoping test below is independent of this flag.

- [ ] **Step 1: Write the failing test**

Create `hermes/test/runner-secrets.test.js`:

```js
'use strict';
const { test } = require('node:test');
const assert = require('node:assert');
const fs = require('fs');
const os = require('os');
const path = require('path');
const { run } = require('../lib/runner');

function stub(body) {
  const p = path.join(fs.mkdtempSync(path.join(os.tmpdir(), 'hermes-rs-')), 'claude');
  fs.writeFileSync(p, `#!/usr/bin/env node\n${body}`, { mode: 0o755 });
  return p;
}
const target = { id: 'demo-pack', kind: 'pack', tier: 'hitl', prompt: 'x' };

test('secrets are injected into the child env, not into argv', () => {
  // stub echoes back whether it saw the secret in its env
  const bin = stub('process.stdout.write(JSON.stringify({saw: process.env.MY_TOKEN || null}));');
  const r = run(target, { claudeBin: bin, secrets: { MY_TOKEN: 's3cret' } });
  const out = JSON.parse(r.stdout);
  assert.equal(out.saw, 's3cret');
  assert.equal(r.argv.join(' ').includes('s3cret'), false); // never on the command line
});
```

- [ ] **Step 2: Run to verify it fails** — `node hermes/test/runner-secrets.test.js` → FAIL (secret not injected yet).

- [ ] **Step 3: Extend `lib/runner.js`**

In `run`, before `spawnSync`, build the child env and (when `opts.guard` is set) a settings file:

```js
// inside run(), after computing argv:
const childEnv = { ...process.env, ...(opts.secrets || {}) };
let settingsPath = null;
if (opts.guard) {
  childEnv.HERMES_DB_PATH = opts.guard.dbPath;
  childEnv.HERMES_RUN_ID = runId;
  childEnv.HERMES_RUN_TIER = target.tier;
  settingsPath = writeGuardSettings(cwd, runId); // registers hooks/guard.js as PreToolUse
  argv.push('--settings', settingsPath); // exact flag confirmed in Step 0
}
const r = spawnSync(claudeBin, argv, { cwd, encoding: 'utf8', timeout: timeoutMs, maxBuffer: 64 * 1024 * 1024, env: childEnv });
if (settingsPath) { try { fs.unlinkSync(settingsPath); } catch {} }
```

Add a `writeGuardSettings(cwd, runId)` helper that writes a minimal settings JSON pointing PreToolUse at `node <abs path>/hooks/guard.js`, and `require('fs')`/`require('path')` at the top. Keep `buildArgv` unchanged; secrets go only through `env`.

- [ ] **Step 4: Run to verify it passes** — `node hermes/test/runner-secrets.test.js` → PASS; re-run `node hermes/test/runner.test.js` (H0) → still PASS (no secrets/guard path unaffected).

- [ ] **Step 5: Commit**

```bash
git add hermes/lib/runner.js hermes/test/runner-secrets.test.js
git commit -m "feat(hermes): inject vault secrets as scoped env + register guard hook"
```

---

### Task 7: CLI subcommands + approval-driven resume + artifact scrub assertion

**Files:**
- Modify: `hermes/bin/hermes.js` (`vault`, `approvals` subcommands)
- Modify: `hermes/lib/core.js` (mark `awaiting_approval`; approval → run `action-runner` → terminal status)
- Test: `hermes/test/hitl-integration.test.js`

**Interfaces:**
- `hermes vault set <name>` (reads value from stdin, never argv) · `vault list` · `vault rm <name>`.
- `hermes approvals list` · `hermes approvals approve <id> [--by <who>]` · `hermes approvals reject <id>`.
- `approve` loads the approval, runs `action-runner.runAction(payload, { env: scopedSecrets })`, and sets the run row to `done`/`failed`.

- [ ] **Step 1: Write the failing integration test**

Create `hermes/test/hitl-integration.test.js`:

```js
'use strict';
const { test } = require('node:test');
const assert = require('node:assert');
const fs = require('fs');
const os = require('os');
const path = require('path');
const { openDb } = require('../lib/db');
const approvals = require('../lib/approvals');
const { runAction } = require('../lib/action-runner');

// Simulates the post-run state: a pending approval exists; approving it executes the payload.
test('approving a pending action executes exactly the recorded payload', () => {
  const d = openDb(path.join(fs.mkdtempSync(path.join(os.tmpdir(), 'hermes-hitl-')), 'hermes.db'));
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'hermes-hitl-act-'));
  const marker = path.join(dir, 'ran.txt');
  const payload = JSON.stringify(['node', '-e', `require('fs').writeFileSync(${JSON.stringify(marker)},'y')`]);
  const id = approvals.create(d, { runId: 'r1', tool: 'Bash', action: 'x', payload }, new Date());

  const dec = approvals.decide(d, id, { status: 'approved', decidedBy: 'erick' }, new Date());
  assert.equal(dec.ok, true);
  const row = d.prepare('SELECT payload FROM approvals WHERE approval_id = ?').get(id);
  const r = runAction(row.payload, {});
  assert.equal(r.ok, true);
  assert.equal(fs.existsSync(marker), true);
});

test('no secret value appears in a run manifest or result', () => {
  // Reuse core.execute with a stub that emits JSON; inject a secret; assert artifacts are clean.
  // (Full wiring per Task 6; this asserts the scrubbing invariant.)
});
```

- [ ] **Step 2: Implement the CLI subcommands and the approve→execute path**

Extend `bin/hermes.js`:
- `vault set <name>`: read the secret value from **stdin** (never a CLI arg — avoids shell history), call `vault.set`.
- `vault list`/`vault rm`.
- `approvals list`: print `approvals.listPending(db)`.
- `approvals approve <id> [--by who]`: `approvals.decide(... approved ...)`; on ok, load the payload, resolve the run's pack secrets from the vault into an env map, `runAction(payload, { env })`, then set the run row `done`/`failed` via `queue.finish`.
- `approvals reject <id>`: `approvals.decide(... rejected ...)`; set the run row `failed`.

In `lib/core.js`: when a run ends because the guard recorded a pending approval (detect via a fresh pending approval for the run id, or the engine's block signal), set the run status to `awaiting_approval` instead of `failed`.

- [ ] **Step 3: Complete the scrub test**

Fill in the second test: run `core.execute` with a stub `claude` that echoes `{"ok":true}`, `opts.secrets = { MY_TOKEN: 'SEKRET' }`; after, read `result.json` and `manifest.json` and assert neither contains `SEKRET`.

- [ ] **Step 4: Run to verify everything passes** — `node scripts/run-all-tests.js` → all suites green.

- [ ] **Step 5: Enable the `hitl` tier**

In `hermes/hermes.config.json`, `allowed_tiers` may now include `"hitl"`. Leave the default target read-only; document that a pack target can be added at `hitl` once its secrets are vaulted.

- [ ] **Step 6: Commit**

```bash
git add hermes/bin/hermes.js hermes/lib/core.js hermes/hermes.config.json hermes/test/hitl-integration.test.js
git commit -m "feat(hermes): vault + approvals CLI, approval-driven execution, hitl tier"
```

---

## Definition of done (H1)

- [ ] `node scripts/run-all-tests.js` → all suites green.
- [ ] `hermes vault set/list/rm` works; `vault.enc` contains no plaintext secret.
- [ ] A write-tier tool call under `hitl` is denied in-run and recorded as a pending approval; the run ends `awaiting_approval`.
- [ ] `hermes approvals approve <id>` executes exactly the recorded payload → run `done`; `reject` → `failed`.
- [ ] No secret value appears in any run artifact (asserted).
- [ ] Wrong/missing `HERMES_VAULT_KEY` fails closed; guard with no db fails closed.

## Out of scope

Staging-target enforcement, budget caps (H2); VPS + real credentials (H3). The guard + policy engine are the extension points H2 builds on.
