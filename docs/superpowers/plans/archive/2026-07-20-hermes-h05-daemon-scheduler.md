# Hermes H0.5 — Daemon + Scheduler Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the H0 one-shot CLI into a persistent daemon with a durable SQLite run queue and a cron-like scheduler, without changing the H0 run core.

**Architecture:** Introduce `lib/db.js` (`node:sqlite` + migrations) and `lib/queue.js` (durable queue over a `runs` table). Extract the H0 resolve→run→gate flow into `lib/core.js`, reused by both `bin/hermes.js` and the new `bin/hermesd.js` daemon loop. `lib/scheduler.js` reads `schedules.json` and enqueues due jobs.

**Tech Stack:** Node ≥22 minimum (built-in `node:sqlite`); the Docker base image is `node:24-slim`,
where `node:sqlite` is stable rather than experimental. CommonJS, house-style tests (plain `assert`,
standalone `node <file>` runner — see `scripts/run-calibration.test.js`). No new runtime
dependencies.

**Spec:** `docs/superpowers/specs/2026-07-20-hermes-h05-daemon-scheduler-design.md` · **Master:** `docs/superpowers/specs/2026-07-20-hermes-master-architecture.md`

## Global Constraints

- Node ≥22 (built-in `node:sqlite`) minimum to run Hermes DB-dependent code locally; the Docker base
  image is `node:24-slim`, where `node:sqlite` is stable. `scripts/run-all-tests.js` must skip the
  `hermes/` DB-dependent suites (`db`, `queue`, `core`, `scheduler`, `hermesd`) when the host Node
  version is <22 — see Task 1, Step 6.
- CommonJS, `'use strict'`, no new runtime deps; tests via house-style plain `assert` + a manual
  runner (no `node:test`), matching `scripts/run-calibration.test.js`.
- SQLite file at `hermes/state/hermes.db`; `hermes/state/` is gitignored.
- H0's `loader`/`runner`/`result-gate` are **unchanged** — only wrapped.
- Single worker: exactly one run executes at a time.
- Every run records a row in `runs` (lifecycle) in addition to its H0 file manifest.

---

### Task 1: Node bump + SQLite bootstrap (`lib/db.js` + migration runner)

**Files:**
- Create: `hermes/lib/db.js`
- Create: `hermes/migrations/001-runs.sql`
- Modify: `hermes/Dockerfile` (base image → `node:24-slim`)
- Modify: `.gitignore` (add `hermes/state/`)
- Modify: `scripts/run-all-tests.js` (skip Hermes DB-dependent suites when host Node <22)
- Test: `hermes/test/db.test.js`

**Interfaces:**
- Produces:
  - `openDb(dbPath) → db` — opens `node:sqlite` `DatabaseSync`, runs pending migrations, returns the handle.
  - `migrate(db, migrationsDir)` — applies `*.sql` files in lexical order, idempotently, tracked in a `_migrations` table.

- [ ] **Step 1: Write the migration SQL**

Create `hermes/migrations/001-runs.sql`:

```sql
CREATE TABLE IF NOT EXISTS runs (
  run_id      TEXT PRIMARY KEY,
  target_id   TEXT NOT NULL,
  kind        TEXT NOT NULL,
  tier        TEXT NOT NULL,
  status      TEXT NOT NULL,
  exit_code   INTEGER,
  git_sha     TEXT,
  created_at  TEXT NOT NULL,
  updated_at  TEXT NOT NULL
);
```

- [ ] **Step 2: Write the failing test**

Create `hermes/test/db.test.js`. House test style (plain `assert`, standalone runner — see
`scripts/run-calibration.test.js`), not `node:test`:

```js
'use strict';
const assert = require('assert');
const fs = require('fs');
const os = require('os');
const path = require('path');
const { openDb } = require('../lib/db');

function tmpDbPath() {
  return path.join(fs.mkdtempSync(path.join(os.tmpdir(), 'hermes-db-')), 'hermes.db');
}

// Minimal manual runner (house style — no node:test dependency).
const tests = [];
function test(name, fn) { tests.push([name, fn]); }

test('openDb creates the runs table and is idempotent on re-open', () => {
  const p = tmpDbPath();
  const db1 = openDb(p);
  const cols = db1.prepare("PRAGMA table_info(runs)").all().map((c) => c.name);
  assert.ok(cols.includes('run_id'));
  assert.ok(cols.includes('status'));
  db1.close();
  // Re-open must not throw (migrations already applied).
  const db2 = openDb(p);
  const applied = db2.prepare("SELECT COUNT(*) AS n FROM _migrations").get().n;
  assert.ok(applied >= 1);
  db2.close();
});

let failed = 0;
for (const [name, fn] of tests) {
  try { fn(); console.log(`✓ ${name}`); }
  catch (e) { failed++; console.error(`✗ ${name}`); console.error(e); }
}
if (failed > 0) { console.error(`\n${failed} test(s) failed`); process.exit(1); }
console.log(`\n✅ All ${tests.length} tests passed`);
```

- [ ] **Step 3: Run test to verify it fails**

Run: `node hermes/test/db.test.js`
Expected: FAIL — `Cannot find module '../lib/db'`.

- [ ] **Step 4: Write `lib/db.js`**

Create `hermes/lib/db.js`:

```js
'use strict';
const fs = require('fs');
const path = require('path');
const { DatabaseSync } = require('node:sqlite');

function migrate(db, migrationsDir) {
  db.exec('CREATE TABLE IF NOT EXISTS _migrations (name TEXT PRIMARY KEY, applied_at TEXT NOT NULL)');
  const applied = new Set(db.prepare('SELECT name FROM _migrations').all().map((r) => r.name));
  const files = fs.existsSync(migrationsDir)
    ? fs.readdirSync(migrationsDir).filter((f) => f.endsWith('.sql')).sort()
    : [];
  const insert = db.prepare('INSERT INTO _migrations (name, applied_at) VALUES (?, ?)');
  for (const f of files) {
    if (applied.has(f)) continue;
    db.exec(fs.readFileSync(path.join(migrationsDir, f), 'utf8'));
    insert.run(f, new Date().toISOString());
  }
}

function openDb(dbPath, opts = {}) {
  fs.mkdirSync(path.dirname(dbPath), { recursive: true });
  const db = new DatabaseSync(dbPath);
  db.exec('PRAGMA journal_mode = WAL');
  migrate(db, opts.migrationsDir || path.join(__dirname, '..', 'migrations'));
  return db;
}

module.exports = { openDb, migrate };
```

- [ ] **Step 5: Run test to verify it passes**

Run: `node hermes/test/db.test.js`
Expected: PASS. (If Node < 22, `node:sqlite` errors — install/switch to Node ≥22.)

- [ ] **Step 6: Bump Docker base, gitignore state, and skip DB suites on an older host Node**

In `hermes/Dockerfile`, change `FROM node:20-slim` → `FROM node:24-slim` (where `node:sqlite` is
stable, not experimental).
Append to `.gitignore`:

```
# Hermes durable state (SQLite, vault)
hermes/state/
```

In `scripts/run-all-tests.js`, guard the `hermes/` DB-dependent suites so a host Node <22 (no
`node:sqlite`) skips them instead of erroring out the whole run:

```js
const NODE_MAJOR = Number(process.versions.node.split('.')[0]);
const HERMES_DB_SUITES = ['db.test.js', 'queue.test.js', 'core.test.js', 'scheduler.test.js', 'hermesd.test.js'];

const hermesDir = path.join(REPO, 'hermes');
const hermesTests = fs.existsSync(hermesDir)
  ? discoverTestFiles(hermesDir, []).filter((p) => {
      if (NODE_MAJOR >= 22) return true;
      const needsDb = HERMES_DB_SUITES.some((name) => p.endsWith(name));
      if (needsDb) {
        console.log(`SKIP  ${path.relative(REPO, p)} (needs Node >=22 for node:sqlite; host is Node ${NODE_MAJOR})`);
      }
      return !needsDb;
    })
  : [];
```

The H0 suites (`loader`, `runner`, `result-gate`, `hermes.test.js`) have no `node:sqlite` dependency
and always run, on any host Node ≥18.

- [ ] **Step 7: Commit**

```bash
git add hermes/lib/db.js hermes/migrations/001-runs.sql hermes/Dockerfile .gitignore scripts/run-all-tests.js hermes/test/db.test.js
git commit -m "feat(hermes): SQLite bootstrap (node:sqlite) + runs migration + node24"
```

---

### Task 2: Durable run queue (`lib/queue.js`)

**Files:**
- Create: `hermes/lib/queue.js`
- Test: `hermes/test/queue.test.js`

**Interfaces:**
- Consumes: `db` from `openDb` (Task 1); a `target` (`{id,kind,tier,prompt}`) from the loader.
- Produces:
  - `enqueue(db, target, now) → runId` — inserts a `queued` row.
  - `claimNext(db, now) → { runId, target } | null` — atomically flips the oldest `queued` row to
    `running`. `target` here is the **partial** shape stored in the `runs` table
    (`{ id, kind, tier }` — no `prompt`, since the table doesn't persist it). Callers must re-resolve
    the full target (including `prompt`) by id before running it; `core.execute` (Task 3) does this
    automatically when given a target id string, so this is consistent, not an oversight.
  - `finish(db, runId, { status, exitCode, gitSha }, now)` — sets terminal status.
  - `reapStale(db, olderThanMs, now) → count` — marks `running` rows older than the threshold as `failed`.

- [ ] **Step 1: Write the failing tests**

Create `hermes/test/queue.test.js`. House test style (plain `assert`, standalone runner):

```js
'use strict';
const assert = require('assert');
const fs = require('fs');
const os = require('os');
const path = require('path');
const { openDb } = require('../lib/db');
const { enqueue, claimNext, finish, reapStale } = require('../lib/queue');

// Minimal manual runner (house style — no node:test dependency).
const tests = [];
function test(name, fn) { tests.push([name, fn]); }

function db() {
  const p = path.join(fs.mkdtempSync(path.join(os.tmpdir(), 'hermes-q-')), 'hermes.db');
  return openDb(p);
}
const target = { id: 'demo-agent', kind: 'agent', tier: 'read-only', prompt: 'x' };

test('enqueue then claimNext returns the job and flips it to running', () => {
  const d = db();
  const runId = enqueue(d, target, new Date('2026-07-20T03:00:00Z'));
  const job = claimNext(d, new Date());
  assert.equal(job.runId, runId);
  assert.equal(job.target.id, 'demo-agent');
  const row = d.prepare('SELECT status FROM runs WHERE run_id = ?').get(runId);
  assert.equal(row.status, 'running');
});

test('claimNext on an empty queue returns null', () => {
  assert.equal(claimNext(db(), new Date()), null);
});

test('finish sets the terminal status and exit code', () => {
  const d = db();
  const runId = enqueue(d, target, new Date());
  claimNext(d, new Date());
  finish(d, runId, { status: 'done', exitCode: 0, gitSha: 'abc' }, new Date());
  const row = d.prepare('SELECT status, exit_code FROM runs WHERE run_id = ?').get(runId);
  assert.equal(row.status, 'done');
  assert.equal(row.exit_code, 0);
});

test('reapStale marks old running rows as failed', () => {
  const d = db();
  const runId = enqueue(d, target, new Date('2026-07-20T00:00:00Z'));
  claimNext(d, new Date('2026-07-20T00:00:00Z'));
  const n = reapStale(d, 60000, new Date('2026-07-20T01:00:00Z'));
  assert.equal(n, 1);
  assert.equal(d.prepare('SELECT status FROM runs WHERE run_id = ?').get(runId).status, 'failed');
});

let failed = 0;
for (const [name, fn] of tests) {
  try { fn(); console.log(`✓ ${name}`); }
  catch (e) { failed++; console.error(`✗ ${name}`); console.error(e); }
}
if (failed > 0) { console.error(`\n${failed} test(s) failed`); process.exit(1); }
console.log(`\n✅ All ${tests.length} tests passed`);
```

- [ ] **Step 2: Run to verify it fails** — `node hermes/test/queue.test.js` → `Cannot find module '../lib/queue'`.

- [ ] **Step 3: Write `lib/queue.js`**

```js
'use strict';
const { makeRunId } = require('./runner');

function enqueue(db, target, now = new Date()) {
  const runId = makeRunId(target, now);
  const ts = now.toISOString();
  db.prepare(
    `INSERT INTO runs (run_id, target_id, kind, tier, status, created_at, updated_at)
     VALUES (?, ?, ?, ?, 'queued', ?, ?)`
  ).run(runId, target.id, target.kind, target.tier, ts, ts);
  // Store the resolvable target id; the daemon re-resolves via the loader before running.
  return runId;
}

function claimNext(db, now = new Date()) {
  const row = db.prepare(
    `SELECT * FROM runs WHERE status = 'queued' ORDER BY created_at ASC LIMIT 1`
  ).get();
  if (!row) return null;
  db.prepare(`UPDATE runs SET status = 'running', updated_at = ? WHERE run_id = ?`)
    .run(now.toISOString(), row.run_id);
  // `target` is intentionally partial — the `runs` table doesn't persist `prompt`. Callers
  // re-resolve the full target (with `prompt`) by `target.id` before executing it; see
  // core.execute's string-argument path (Task 3).
  return {
    runId: row.run_id,
    target: { id: row.target_id, kind: row.kind, tier: row.tier },
  };
}

function finish(db, runId, { status, exitCode, gitSha }, now = new Date()) {
  db.prepare(`UPDATE runs SET status = ?, exit_code = ?, git_sha = ?, updated_at = ? WHERE run_id = ?`)
    .run(status, exitCode ?? null, gitSha ?? null, now.toISOString(), runId);
}

function reapStale(db, olderThanMs, now = new Date()) {
  const cutoff = new Date(now.getTime() - olderThanMs).toISOString();
  const stale = db.prepare(`SELECT run_id FROM runs WHERE status = 'running' AND updated_at < ?`).all(cutoff);
  const upd = db.prepare(`UPDATE runs SET status = 'failed', updated_at = ? WHERE run_id = ?`);
  for (const r of stale) upd.run(now.toISOString(), r.run_id);
  return stale.length;
}

module.exports = { enqueue, claimNext, finish, reapStale };
```

- [ ] **Step 4: Run to verify it passes** — `node hermes/test/queue.test.js` → PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add hermes/lib/queue.js hermes/test/queue.test.js
git commit -m "feat(hermes): durable SQLite run queue with stale-run reaper"
```

---

### Task 3: Extract the run core (`lib/core.js`) + record to `runs`

Refactor H0's `bin/hermes.js` flow into a reusable function that both the CLI and daemon call, and that records lifecycle to the `runs` table when a db handle is supplied.

**Files:**
- Create: `hermes/lib/core.js`
- Modify: `hermes/bin/hermes.js` (delegate to `core.execute`)
- Test: `hermes/test/core.test.js`

**Interfaces:**
- Consumes: `loader.resolveTarget`, `runner.run`, `result-gate.gate` (H0); `openDb`, `finish` (Tasks 1-2).
- Produces:
  - `execute(targetIdOrTarget, opts) → { status, exitCode, runId, artifactDir }`. `opts = { repoRoot, claudeBin, config, db, runId }`. If `db` is passed, updates the matching `runs` row to
    `running`/terminal; if a `runs` row does not exist (direct `hermes run`), it upserts one. If
    `opts.runId` is supplied (the daemon's already-claimed queue row id), it is used in preference to
    re-deriving a fresh id via `runner`'s internal `makeRunId` — this is what lets the daemon's drain
    loop (Task 5) update the row it already claimed instead of creating a duplicate/orphan `runs`
    row. (Earlier drafts of this plan called this option `preResolvedRunId`; standardized on `runId`
    to match the field name everywhere else — `queue.claimNext`, `runner.run`, `result-gate.gate`.)

- [ ] **Step 1: Write the failing test**

Create `hermes/test/core.test.js`. House test style (plain `assert`, standalone runner):

```js
'use strict';
const assert = require('assert');
const fs = require('fs');
const os = require('os');
const path = require('path');
const { openDb } = require('../lib/db');
const { execute } = require('../lib/core');

// Minimal manual runner (house style — no node:test dependency).
const tests = [];
function test(name, fn) { tests.push([name, fn]); }

function fixtureRepo() {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'hermes-core-'));
  fs.mkdirSync(path.join(root, '.claude', 'agents'), { recursive: true });
  fs.mkdirSync(path.join(root, 'hermes'), { recursive: true });
  fs.writeFileSync(path.join(root, '.claude', 'agents', 'demo-agent.md'), '# demo');
  fs.writeFileSync(path.join(root, 'hermes', 'hermes.config.json'), JSON.stringify({
    allowed_tiers: ['read-only'], runs_dir: 'evals/hermes/runs',
    runnable_targets: [{ id: 'demo-agent', kind: 'agent', tier: 'read-only', prompt: 'x' }],
  }));
  return root;
}
function stub(body) {
  const p = path.join(fs.mkdtempSync(path.join(os.tmpdir(), 'hermes-cs-')), 'claude');
  fs.writeFileSync(p, `#!/usr/bin/env node\n${body}`, { mode: 0o755 });
  return p;
}

test('execute runs a target, writes a manifest, and records a runs row', () => {
  const root = fixtureRepo();
  const d = openDb(path.join(root, 'hermes', 'state', 'hermes.db'));
  const bin = stub('process.stdout.write(JSON.stringify({ok:true}));');
  const out = execute('demo-agent', { repoRoot: root, claudeBin: bin, db: d });
  assert.equal(out.status, 'pass');
  assert.ok(fs.existsSync(path.join(out.artifactDir, 'manifest.json')));
  const row = d.prepare('SELECT status FROM runs WHERE run_id = ?').get(out.runId);
  assert.equal(row.status, 'done');
});

test('execute prefers opts.runId over a freshly derived id, updating the claimed row (no duplicate)', () => {
  const root = fixtureRepo();
  const d = openDb(path.join(root, 'hermes', 'state', 'hermes.db'));
  const bin = stub('process.stdout.write(JSON.stringify({ok:true}));');
  const claimedRunId = 'pre-claimed-run-id';
  const now = new Date().toISOString();
  d.prepare(
    `INSERT INTO runs (run_id, target_id, kind, tier, status, created_at, updated_at)
     VALUES (?, 'demo-agent', 'agent', 'read-only', 'queued', ?, ?)`
  ).run(claimedRunId, now, now);
  const out = execute('demo-agent', { repoRoot: root, claudeBin: bin, db: d, runId: claimedRunId });
  assert.equal(out.runId, claimedRunId);
  const rows = d.prepare('SELECT run_id, status FROM runs').all();
  assert.equal(rows.length, 1, 'no duplicate/orphan runs row should be created');
  assert.equal(rows[0].status, 'done');
});

let failed = 0;
for (const [name, fn] of tests) {
  try { fn(); console.log(`✓ ${name}`); }
  catch (e) { failed++; console.error(`✗ ${name}`); console.error(e); }
}
if (failed > 0) { console.error(`\n${failed} test(s) failed`); process.exit(1); }
console.log(`\n✅ All ${tests.length} tests passed`);
```

- [ ] **Step 2: Run to verify it fails** — `node hermes/test/core.test.js` → `Cannot find module '../lib/core'`.

- [ ] **Step 3: Write `lib/core.js`**

```js
'use strict';
const path = require('path');
const { loadConfig, resolveTarget } = require('./loader');
const runner = require('./runner');
const { gate, getGitSha } = require('./result-gate');
const { finish } = require('./queue');

function upsertRunning(db, runId, target, now) {
  const ts = now.toISOString();
  db.prepare(
    `INSERT INTO runs (run_id, target_id, kind, tier, status, created_at, updated_at)
       VALUES (?, ?, ?, ?, 'running', ?, ?)
     ON CONFLICT(run_id) DO UPDATE SET status='running', updated_at=excluded.updated_at`
  ).run(runId, target.id, target.kind, target.tier, ts, ts);
}

function execute(targetArg, opts = {}) {
  const repoRoot = opts.repoRoot || path.resolve(__dirname, '..', '..');
  const config = opts.config || loadConfig(repoRoot);
  const now = opts.now || new Date();

  const target = typeof targetArg === 'string'
    ? (() => {
        const r = resolveTarget(config, repoRoot, targetArg);
        if (!r.ok) throw Object.assign(new Error(r.error), { code: 'VALIDATION' });
        return r.target;
      })()
    : targetArg;

  const rawResult = runner.run(target, { cwd: repoRoot, claudeBin: opts.claudeBin, now });
  // Prefer the caller-supplied (already-claimed) runId over runner's freshly derived one, so a
  // queue-drained execution updates its existing `runs` row instead of creating a duplicate/orphan.
  const runResult = opts.runId ? { ...rawResult, runId: opts.runId } : rawResult;
  const gitSha = getGitSha(repoRoot);

  if (opts.db) upsertRunning(opts.db, runResult.runId, target, now);
  const result = gate(target, runResult, config, { repoRoot, gitSha });

  const status =
    runResult.error?.type === 'ENOENT' ? 'failed'
    : runResult.error?.type === 'TIMEOUT' ? 'failed'
    : result.status === 'pass' ? 'done'
    : 'failed';

  if (opts.db) finish(opts.db, runResult.runId, { status, exitCode: runResult.code, gitSha }, now);

  return { status: result.status, exitCode: runResult.code, runId: runResult.runId, artifactDir: result.artifactDir, engineError: runResult.error };
}

module.exports = { execute };
```

- [ ] **Step 4: Refactor `bin/hermes.js` to delegate**

Replace the body of `main` after target resolution so it calls `core.execute(targetId, { repoRoot, claudeBin: opts.claudeBin })` and maps its result to the existing `EXIT` codes (ENOENT→3, TIMEOUT→4, pass→0, else→5). Keep the pre-spawn `resolveTarget` validation (exit 2) exactly as in H0 so the fail-closed test still passes. Re-run `node hermes/test/hermes.test.js` → all H0 CLI tests still PASS.

- [ ] **Step 5: Run to verify it passes** — `node hermes/test/core.test.js` (both tests, including the
  runId-threading/no-duplicate-row assertion) and `node hermes/test/hermes.test.js` → PASS.

- [ ] **Step 6: Commit**

```bash
git add hermes/lib/core.js hermes/bin/hermes.js hermes/test/core.test.js
git commit -m "refactor(hermes): extract run core, record lifecycle to runs table"
```

---

### Task 4: Scheduler (`lib/scheduler.js`) + cron matcher

**Files:**
- Create: `hermes/lib/scheduler.js`
- Create: `hermes/schedules.json`
- Test: `hermes/test/scheduler.test.js`

**Interfaces:**
- Produces:
  - `cronMatches(expr, date) → boolean` — 5-field cron (`min hour dom month dow`; supports `*`, `*/n`, comma lists, ranges `a-b`).
  - `dueJobs(schedules, date, alreadyRanThisMinute) → target[]` — enabled schedules whose cron matches `date` and that haven't run in the current minute.

- [ ] **Step 1: Write `schedules.json`**

```json
{
  "schedules": [
    { "id": "nightly-repo-audit", "target": "repo-audit-testing", "cron": "0 3 * * *", "enabled": true }
  ]
}
```

- [ ] **Step 2: Write the failing tests**

Create `hermes/test/scheduler.test.js`. House test style (plain `assert`, standalone runner):

```js
'use strict';
const assert = require('assert');
const { cronMatches, dueJobs } = require('../lib/scheduler');

// Minimal manual runner (house style — no node:test dependency).
const tests = [];
function test(name, fn) { tests.push([name, fn]); }

test('cron * * * * * always matches', () => {
  assert.equal(cronMatches('* * * * *', new Date('2026-07-20T03:00:00')), true);
});

test('cron 0 3 * * * matches 03:00 only', () => {
  assert.equal(cronMatches('0 3 * * *', new Date('2026-07-20T03:00:00')), true);
  assert.equal(cronMatches('0 3 * * *', new Date('2026-07-20T03:01:00')), false);
  assert.equal(cronMatches('0 3 * * *', new Date('2026-07-20T04:00:00')), false);
});

test('cron */15 matches quarter hours', () => {
  assert.equal(cronMatches('*/15 * * * *', new Date('2026-07-20T10:30:00')), true);
  assert.equal(cronMatches('*/15 * * * *', new Date('2026-07-20T10:31:00')), false);
});

test('dueJobs returns enabled matching targets not already run this minute', () => {
  const schedules = [
    { id: 'a', target: 'demo-agent', cron: '* * * * *', enabled: true },
    { id: 'b', target: 'other', cron: '* * * * *', enabled: false },
  ];
  const out = dueJobs(schedules, new Date('2026-07-20T03:00:00'), () => false);
  assert.deepEqual(out.map((t) => t.target), ['demo-agent']);
  const suppressed = dueJobs(schedules, new Date('2026-07-20T03:00:00'), () => true);
  assert.equal(suppressed.length, 0);
});

let failed = 0;
for (const [name, fn] of tests) {
  try { fn(); console.log(`✓ ${name}`); }
  catch (e) { failed++; console.error(`✗ ${name}`); console.error(e); }
}
if (failed > 0) { console.error(`\n${failed} test(s) failed`); process.exit(1); }
console.log(`\n✅ All ${tests.length} tests passed`);
```

- [ ] **Step 3: Run to verify it fails** — `node hermes/test/scheduler.test.js` → `Cannot find module '../lib/scheduler'`.

- [ ] **Step 4: Write `lib/scheduler.js`**

```js
'use strict';

function parseField(field, min, max) {
  const out = new Set();
  for (const part of field.split(',')) {
    if (part === '*') { for (let i = min; i <= max; i++) out.add(i); continue; }
    const stepMatch = part.match(/^(\*|\d+-\d+)\/(\d+)$/);
    if (stepMatch) {
      const step = Number(stepMatch[2]);
      let lo = min, hi = max;
      if (stepMatch[1] !== '*') { [lo, hi] = stepMatch[1].split('-').map(Number); }
      for (let i = lo; i <= hi; i += step) out.add(i);
      continue;
    }
    const rangeMatch = part.match(/^(\d+)-(\d+)$/);
    if (rangeMatch) { for (let i = Number(rangeMatch[1]); i <= Number(rangeMatch[2]); i++) out.add(i); continue; }
    out.add(Number(part));
  }
  return out;
}

function cronMatches(expr, date) {
  const [min, hour, dom, month, dow] = expr.trim().split(/\s+/);
  return (
    parseField(min, 0, 59).has(date.getMinutes()) &&
    parseField(hour, 0, 23).has(date.getHours()) &&
    parseField(dom, 1, 31).has(date.getDate()) &&
    parseField(month, 1, 12).has(date.getMonth() + 1) &&
    parseField(dow, 0, 6).has(date.getDay())
  );
}

function dueJobs(schedules, date, alreadyRanThisMinute) {
  return (schedules || [])
    .filter((s) => s.enabled && cronMatches(s.cron, date) && !alreadyRanThisMinute(s))
    .map((s) => ({ id: s.id, target: s.target }));
}

module.exports = { cronMatches, dueJobs, parseField };
```

- [ ] **Step 5: Run to verify it passes** — `node hermes/test/scheduler.test.js` → PASS (4 tests).

- [ ] **Step 6: Commit**

```bash
git add hermes/lib/scheduler.js hermes/schedules.json hermes/test/scheduler.test.js
git commit -m "feat(hermes): declarative scheduler with dependency-free cron matcher"
```

---

### Task 5: Daemon entrypoint (`bin/hermesd.js`) + `hermes enqueue`

**Files:**
- Create: `hermes/bin/hermesd.js`
- Modify: `hermes/bin/hermes.js` (add the `enqueue` subcommand)
- Modify: `hermes/docker-compose.yml` (add a `hermesd` service)
- Test: `hermes/test/hermesd.test.js`

**Interfaces:**
- Consumes: `openDb`, `queue.*`, `core.execute`, `scheduler.dueJobs`, `loader` (all prior).
- Produces:
  - `tick(ctx) → { enqueued, ran }` — one scheduler+drain cycle; `ctx = { db, repoRoot, config, schedules, claudeBin, now }`. Exported for testing (no infinite loop in the tested unit).
  - `main()` — boots the db, reaps stale runs, then loops `tick` every `TICK_MS`.

- [ ] **Step 1: Write the failing test**

Create `hermes/test/hermesd.test.js`. House test style (plain `assert`, standalone runner):

```js
'use strict';
const assert = require('assert');
const fs = require('fs');
const os = require('os');
const path = require('path');
const { openDb } = require('../lib/db');
const { tick } = require('../bin/hermesd');

// Minimal manual runner (house style — no node:test dependency).
const tests = [];
function test(name, fn) { tests.push([name, fn]); }

function fixtureRepo() {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'hermes-d-'));
  fs.mkdirSync(path.join(root, '.claude', 'agents'), { recursive: true });
  fs.mkdirSync(path.join(root, 'hermes'), { recursive: true });
  fs.writeFileSync(path.join(root, '.claude', 'agents', 'demo-agent.md'), '# demo');
  fs.writeFileSync(path.join(root, 'hermes', 'hermes.config.json'), JSON.stringify({
    allowed_tiers: ['read-only'], runs_dir: 'evals/hermes/runs',
    runnable_targets: [{ id: 'demo-agent', kind: 'agent', tier: 'read-only', prompt: 'x' }],
  }));
  return root;
}
function stub(body) {
  const p = path.join(fs.mkdtempSync(path.join(os.tmpdir(), 'hermes-ds-')), 'claude');
  fs.writeFileSync(p, `#!/usr/bin/env node\n${body}`, { mode: 0o755 });
  return p;
}

test('a tick enqueues a due schedule and drains it to done', () => {
  const root = fixtureRepo();
  const db = openDb(path.join(root, 'hermes', 'state', 'hermes.db'));
  const bin = stub('process.stdout.write(JSON.stringify({ok:true}));');
  const schedules = [{ id: 's', target: 'demo-agent', cron: '* * * * *', enabled: true }];
  const config = JSON.parse(fs.readFileSync(path.join(root, 'hermes', 'hermes.config.json'), 'utf8'));

  const r = tick({ db, repoRoot: root, config, schedules, claudeBin: bin, now: new Date() });
  assert.equal(r.enqueued, 1);
  assert.equal(r.ran, 1);
  const rows = db.prepare("SELECT run_id, status FROM runs WHERE target_id = 'demo-agent'").all();
  assert.equal(rows.length, 1, 'the claimed run_id must be reused — no duplicate/orphan runs row');
  assert.equal(rows[0].status, 'done');
});

let failed = 0;
for (const [name, fn] of tests) {
  try { fn(); console.log(`✓ ${name}`); }
  catch (e) { failed++; console.error(`✗ ${name}`); console.error(e); }
}
if (failed > 0) { console.error(`\n${failed} test(s) failed`); process.exit(1); }
console.log(`\n✅ All ${tests.length} tests passed`);
```

- [ ] **Step 2: Run to verify it fails** — `node hermes/test/hermesd.test.js` → `Cannot find module '../bin/hermesd'`.

- [ ] **Step 3: Write `bin/hermesd.js`**

```js
#!/usr/bin/env node
'use strict';
const path = require('path');
const fs = require('fs');
const { openDb } = require('../lib/db');
const queue = require('../lib/queue');
const { execute } = require('../lib/core');
const { dueJobs } = require('../lib/scheduler');
const { loadConfig, resolveTarget } = require('../lib/loader');

const TICK_MS = 60000;
const STALE_MS = 30 * 60000;

function ranThisMinute(db, now) {
  const minutePrefix = now.toISOString().slice(0, 16); // YYYY-MM-DDTHH:MM
  return (schedule) => {
    const row = db.prepare(
      "SELECT created_at FROM runs WHERE target_id = ? ORDER BY created_at DESC LIMIT 1"
    ).get(schedule.target);
    return !!row && row.created_at.slice(0, 16) === minutePrefix;
  };
}

function tick(ctx) {
  const { db, repoRoot, config, schedules, claudeBin, now = new Date() } = ctx;
  let enqueued = 0;
  for (const job of dueJobs(schedules, now, ranThisMinute(db, now))) {
    const r = resolveTarget(config, repoRoot, job.target);
    if (r.ok) { queue.enqueue(db, r.target, now); enqueued++; }
  }
  let ran = 0;
  let claimed;
  while ((claimed = queue.claimNext(db, new Date()))) {
    // Pass the id (not the partial queue-table target — see queue.js's claimNext note) so
    // core.execute re-resolves the full target, including prompt. Pass the already-claimed
    // runId through so execute updates this row instead of creating a duplicate/orphan one
    // (see core.js Task 3).
    execute(claimed.target.id, {
      repoRoot, config, claudeBin, db, runId: claimed.runId, now: new Date(),
    });
    ran++;
  }
  return { enqueued, ran };
}

function main() {
  const repoRoot = path.resolve(__dirname, '..', '..');
  const config = loadConfig(repoRoot);
  const db = openDb(path.join(repoRoot, 'hermes', 'state', 'hermes.db'));
  queue.reapStale(db, STALE_MS, new Date());
  const schedulesPath = path.join(repoRoot, 'hermes', 'schedules.json');
  console.log('[hermesd] started');
  const loop = () => {
    const schedules = fs.existsSync(schedulesPath)
      ? JSON.parse(fs.readFileSync(schedulesPath, 'utf8')).schedules
      : [];
    try { tick({ db, repoRoot, config, schedules, now: new Date() }); }
    catch (e) { console.error(`[hermesd] tick error: ${e.message}`); }
  };
  loop();
  setInterval(loop, TICK_MS);
}

if (require.main === module) main();
module.exports = { tick };
```

Note: `execute` re-resolves the target by id (Task 3) and reuses the already-claimed `runs` row via
the `runId` passed through above, rather than deriving a fresh one — this is what keeps the drain
loop from creating a duplicate/orphan `runs` row. Verified by the row-count assertion in
`hermesd.test.js` (Step 1) and the equivalent assertion in `core.test.js` (Task 3).

- [ ] **Step 4: Add the `enqueue` subcommand to `bin/hermes.js`**

Extend `main` to handle `['enqueue', <target>]`: resolve (exit 2 on failure), `openDb`, `queue.enqueue`, print the run id, exit 0.

- [ ] **Step 5: Run to verify it passes** — `node hermes/test/hermesd.test.js` → PASS; `node scripts/run-all-tests.js` → all suites green.

- [ ] **Step 6: Add the daemon service to compose**

In `hermes/docker-compose.yml`, add:

```yaml
  hermesd:
    build: { context: .., dockerfile: hermes/Dockerfile }
    command: ["node", "hermes/bin/hermesd.js"]
    environment: [ "ANTHROPIC_API_KEY=${ANTHROPIC_API_KEY}" ]
    volumes:
      - ../evals/hermes/runs:/app/evals/hermes/runs
      - ../hermes/state:/app/hermes/state
    restart: unless-stopped
    working_dir: /app
```

- [ ] **Step 7: Commit**

```bash
git add hermes/bin/hermesd.js hermes/bin/hermes.js hermes/docker-compose.yml hermes/test/hermesd.test.js
git commit -m "feat(hermes): persistent daemon (scheduler + queue drain) with enqueue command"
```

---

## Definition of done (H0.5)

- [ ] `node scripts/run-all-tests.js` → all suites green (db, queue, core, scheduler, hermesd + H0).
- [ ] `hermes run <target>` still behaves as in H0, now also recording a `runs` row.
- [ ] `hermes enqueue <target>` then a daemon tick drains it to `done`.
- [ ] Restart with a queued job intact → the job still runs (durable queue proven).
- [ ] A row stuck in `running` past `STALE_MS` is reaped to `failed` on next boot.
- [ ] Live (opt-in): `docker compose -f hermes/docker-compose.yml up hermesd` runs a scheduled `repo-audit-testing` at its cron time and writes a run dir + `done` row.

## Out of scope

Vault, HITL, staging/budget, HTTP/Slack channels, VPS deploy. See later phase docs.
