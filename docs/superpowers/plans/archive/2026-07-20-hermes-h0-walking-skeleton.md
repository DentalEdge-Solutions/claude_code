# Hermes H0 — Walking Skeleton Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a one-shot Node CLI, in Docker, that discovers governed targets, runs a credential-free one through the `claude` CLI headless, gates the result to a durable manifest, and fails closed on anything outside its read-only allow-list.

**Architecture:** Three focused Node modules — `loader` (discover + fail-closed validation, pure), `runner` (build argv + spawn `claude -p`, the only subprocess module), `result-gate` (parse + verify + write artifacts) — wired by a thin `bin/hermes.js`. The only new registry artifact is `hermes/hermes.config.json`, an allow-list. Agents/packs are discovered in place; nothing is duplicated or hardcoded.

**Tech Stack:** Node ≥18 (CommonJS, `'use strict'`), house-style tests (plain `assert`, standalone `node <file>` runner — see `scripts/run-calibration.test.js`), `child_process.spawnSync`, Docker. No new runtime dependencies.

**Spec:** `docs/superpowers/specs/2026-07-20-hermes-h0-walking-skeleton-design.md`

## Global Constraints

- **Runtime:** Node ≥18, CommonJS modules (`require`/`module.exports`, `'use strict'`) — match the existing `scripts/` style.
- **No new runtime dependencies** — tests use house-style plain `assert` + a manual runner (no `node:test`), runnable directly as `node hermes/test/<name>.test.js`, matching `scripts/run-calibration.test.js`; subprocess via built-in `child_process`.
- **Never hardcode target names** — agents/packs are discovered dynamically by walking the filesystem (existing repo rule).
- **Fail closed** — any target not explicitly allow-listed, missing on disk, or above the allowed tier is a hard error *before* any subprocess is spawned.
- **Artifacts only under `evals/hermes/runs/`** — this path is gitignored; never commit run artifacts.
- **Every run writes a `manifest.json`** — including failures; no exception is ever swallowed.
- **Distinct exit codes:** `0` success · `1` internal error · `2` validation · `3` engine-missing · `4` timeout · `5` bad-output/fail.

### Engine seam (D14)

`runner.js` builds its argv and picks a binary through a small **named adapter map**
(`ENGINE_ADAPTERS`), not a hardcoded `claude` call. Each target carries an optional `engine` field
(default `'claude'`); the H0 build ships exactly one adapter — `claude` → `claude -p` — so `codex`
or other open-model CLIs can be added later as new adapter entries without touching `loader.js` or
`result-gate.js`'s gate logic. The run manifest records which `engine` ran alongside the existing
`target`/`argv`/`gitSha` fields. `runner.test.js` (Task 2) gets one added assertion proving a stub
engine is injected *through* the adapter seam (via `opts.engineAdapters`), not hardcoded — see Task
2, Step 3.

---

### Task 1: Config allow-list + loader (discovery & fail-closed validation)

The security-critical core. Pure functions, no subprocess — so it gets the heaviest test coverage. This task is complete when discovery and every fail-closed branch are proven.

**Files:**
- Create: `hermes/hermes.config.json`
- Create: `hermes/lib/loader.js`
- Test: `hermes/test/loader.test.js`

**Interfaces:**
- Consumes: nothing (first task).
- Produces:
  - `loadConfig(repoRoot) → config` — reads/parses `hermes/hermes.config.json`.
  - `discoverAgents(repoRoot) → Set<string>` — basenames of `.claude/agents/*.md` without `.md`.
  - `discoverPacks(repoRoot) → Map<string, packObj>` — keyed by pack `name`, from `packs/registry.json`.
  - `resolveTarget(config, repoRoot, targetId) → { ok: true, target } | { ok: false, error }` where `target = { id, kind, tier, prompt, engine }` (`engine` defaults to `'claude'` when omitted from config — see "Engine seam (D14)" above).
  - `loadRegistry(config, repoRoot) → { targets: Map<string,target>, errors: string[] }`.

- [ ] **Step 1: Write the config allow-list**

Create `hermes/hermes.config.json`. The example target is a real credential-free agent (`repo-audit-testing` exists in `.claude/agents/`):

```json
{
  "runnable_targets": [
    {
      "id": "repo-audit-testing",
      "kind": "agent",
      "tier": "read-only",
      "prompt": "Summarize the testing setup you can identify in this repository."
    }
  ],
  "allowed_tiers": ["read-only"],
  "runs_dir": "evals/hermes/runs"
}
```

- [ ] **Step 2: Write the failing tests**

Create `hermes/test/loader.test.js`. House test style (plain `assert`, standalone runner — see
`scripts/run-calibration.test.js`), not `node:test`:

```js
'use strict';
const assert = require('assert');
const fs = require('fs');
const os = require('os');
const path = require('path');
const { resolveTarget, loadRegistry, discoverAgents } = require('../lib/loader');

// Minimal manual runner (house style — no node:test dependency).
const tests = [];
function test(name, fn) { tests.push([name, fn]); }

function makeFixtureRepo() {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'hermes-fx-'));
  fs.mkdirSync(path.join(root, '.claude', 'agents'), { recursive: true });
  fs.mkdirSync(path.join(root, 'packs'), { recursive: true });
  fs.writeFileSync(path.join(root, '.claude', 'agents', 'demo-agent.md'), '# demo');
  fs.writeFileSync(path.join(root, 'packs', 'registry.json'), JSON.stringify({
    packs: [
      { name: 'demo-pack', execution_mode: 'read-only' },
      { name: 'live-pack', execution_mode: 'staging-autonomous' },
    ],
  }));
  return root;
}

const baseConfig = {
  allowed_tiers: ['read-only'],
  runs_dir: 'evals/hermes/runs',
  runnable_targets: [
    { id: 'demo-agent', kind: 'agent', tier: 'read-only', prompt: 'do a thing' },
  ],
};

test('resolves a valid allow-listed agent target', () => {
  const root = makeFixtureRepo();
  const r = resolveTarget(baseConfig, root, 'demo-agent');
  assert.equal(r.ok, true);
  assert.equal(r.target.id, 'demo-agent');
  assert.equal(r.target.tier, 'read-only');
});

test('fails closed when target is not in runnable_targets', () => {
  const root = makeFixtureRepo();
  const r = resolveTarget(baseConfig, root, 'ghost-agent');
  assert.equal(r.ok, false);
  assert.match(r.error, /not in runnable_targets/);
});

test('fails closed when the agent is not on disk', () => {
  const root = makeFixtureRepo();
  const cfg = { ...baseConfig, runnable_targets: [{ id: 'missing-agent', kind: 'agent', tier: 'read-only', prompt: 'x' }] };
  const r = resolveTarget(cfg, root, 'missing-agent');
  assert.equal(r.ok, false);
  assert.match(r.error, /not found in \.claude\/agents/);
});

test('fails closed when the tier is not allowed', () => {
  const root = makeFixtureRepo();
  const cfg = { ...baseConfig, runnable_targets: [{ id: 'demo-agent', kind: 'agent', tier: 'staging-autonomous', prompt: 'x' }] };
  const r = resolveTarget(cfg, root, 'demo-agent');
  assert.equal(r.ok, false);
  assert.match(r.error, /not in allowed_tiers/);
});

test('fails closed when a pack execution_mode is above allowed tiers', () => {
  const root = makeFixtureRepo();
  const cfg = { ...baseConfig, runnable_targets: [{ id: 'live-pack', kind: 'pack', tier: 'read-only', prompt: 'x' }] };
  const r = resolveTarget(cfg, root, 'live-pack');
  assert.equal(r.ok, false);
  assert.match(r.error, /execution_mode/);
});

test('discoverAgents reads names dynamically (no hardcoding)', () => {
  const root = makeFixtureRepo();
  fs.writeFileSync(path.join(root, '.claude', 'agents', 'invented-xyz.md'), '# x');
  const agents = discoverAgents(root);
  assert.equal(agents.has('invented-xyz'), true);
  assert.equal(agents.has('demo-agent'), true);
});

test('loadRegistry collects valid targets and reports errors', () => {
  const root = makeFixtureRepo();
  const cfg = { ...baseConfig, runnable_targets: [
    { id: 'demo-agent', kind: 'agent', tier: 'read-only', prompt: 'x' },
    { id: 'ghost', kind: 'agent', tier: 'read-only', prompt: 'x' },
  ] };
  const { targets, errors } = loadRegistry(cfg, root);
  assert.equal(targets.size, 1);
  assert.equal(errors.length, 1);
});

let failed = 0;
for (const [name, fn] of tests) {
  try { fn(); console.log(`✓ ${name}`); }
  catch (e) { failed++; console.error(`✗ ${name}`); console.error(e); }
}
if (failed > 0) { console.error(`\n${failed} test(s) failed`); process.exit(1); }
console.log(`\n✅ All ${tests.length} tests passed`);
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `node hermes/test/loader.test.js`
Expected: FAIL — `Cannot find module '../lib/loader'`.

- [ ] **Step 4: Write the loader implementation**

Create `hermes/lib/loader.js`:

```js
'use strict';
const fs = require('fs');
const path = require('path');

function loadConfig(repoRoot) {
  const p = path.join(repoRoot, 'hermes', 'hermes.config.json');
  return JSON.parse(fs.readFileSync(p, 'utf8'));
}

function discoverAgents(repoRoot) {
  const dir = path.join(repoRoot, '.claude', 'agents');
  if (!fs.existsSync(dir)) return new Set();
  return new Set(
    fs.readdirSync(dir)
      .filter((f) => f.endsWith('.md'))
      .map((f) => f.slice(0, -3))
  );
}

function discoverPacks(repoRoot) {
  const p = path.join(repoRoot, 'packs', 'registry.json');
  if (!fs.existsSync(p)) return new Map();
  const reg = JSON.parse(fs.readFileSync(p, 'utf8'));
  const m = new Map();
  for (const pack of reg.packs || []) m.set(pack.name, pack);
  return m;
}

function resolveTarget(config, repoRoot, targetId) {
  const allowedTiers = config.allowed_tiers || [];
  const entry = (config.runnable_targets || []).find((t) => t.id === targetId);
  if (!entry) return { ok: false, error: `target "${targetId}" is not in runnable_targets` };
  if (!allowedTiers.includes(entry.tier)) {
    return { ok: false, error: `tier "${entry.tier}" is not in allowed_tiers` };
  }
  if (entry.kind === 'agent') {
    if (!discoverAgents(repoRoot).has(entry.id)) {
      return { ok: false, error: `agent "${entry.id}" not found in .claude/agents/` };
    }
  } else if (entry.kind === 'pack') {
    const pack = discoverPacks(repoRoot).get(entry.id);
    if (!pack) return { ok: false, error: `pack "${entry.id}" not found in packs/registry.json` };
    if (!allowedTiers.includes(pack.execution_mode)) {
      return { ok: false, error: `pack "${entry.id}" execution_mode "${pack.execution_mode}" is not in allowed_tiers` };
    }
  } else {
    return { ok: false, error: `unknown kind "${entry.kind}" for target "${entry.id}"` };
  }
  if (typeof entry.prompt !== 'string' || entry.prompt.trim() === '') {
    return { ok: false, error: `target "${entry.id}" has no prompt` };
  }
  // `engine` names the runner adapter (see "Engine seam (D14)"); defaults to the sole H0 adapter.
  return { ok: true, target: { id: entry.id, kind: entry.kind, tier: entry.tier, prompt: entry.prompt, engine: entry.engine || 'claude' } };
}

function loadRegistry(config, repoRoot) {
  const targets = new Map();
  const errors = [];
  for (const entry of config.runnable_targets || []) {
    const r = resolveTarget(config, repoRoot, entry.id);
    if (r.ok) targets.set(r.target.id, r.target);
    else errors.push(r.error);
  }
  return { targets, errors };
}

module.exports = { loadConfig, discoverAgents, discoverPacks, resolveTarget, loadRegistry };
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `node hermes/test/loader.test.js`
Expected: PASS — all 7 tests.

- [ ] **Step 6: Commit**

```bash
git add hermes/hermes.config.json hermes/lib/loader.js hermes/test/loader.test.js
git commit -m "feat(hermes): allow-list config + fail-closed discovery loader"
```

---

### Task 2: Runner (argv build + spawn `claude -p`)

The only module that touches a subprocess. Tested deterministically and offline with a fake `claude` stub — no API cost.

**Files:**
- Create: `hermes/lib/runner.js`
- Test: `hermes/test/runner.test.js`

**Interfaces:**
- Consumes: a resolved `target = { id, kind, tier, prompt, engine }` (from Task 1).
- Produces:
  - `makeRunId(target, now) → "YYYYMMDD-HHMMSS-<id>"`.
  - `buildArgv(target) → string[]`.
  - `run(target, opts) → { runId, argv, stdout, stderr, code, durationMs, error, engine }` where `error` is `null` or `{ type: 'ENOENT'|'TIMEOUT'|'SPAWN', message }`. `opts = { timeoutMs, cwd, claudeBin, now, engineAdapters }`. `engineAdapters` is the named-adapter map (default `ENGINE_ADAPTERS`, the sole `claude` adapter) — the seam through which `codex`/other engines plug in later (Engine seam D14).

- [ ] **Step 0: Confirm the real CLI flags**

Run: `claude --help` (this environment *is* Claude Code, so the CLI is present).
Confirm the headless flags for (a) selecting a specific project agent and (b) a read-only/non-writing permission mode. The plan assumes `--agent <id>` and `--permission-mode plan`. If the CLI differs, adjust `buildArgv` in Step 2 accordingly — the tests below deliberately assert only the stable parts (`-p`, the prompt, `--output-format json`, and that the target id appears somewhere in argv), so they stay green regardless of the exact agent/permission flag names.

- [ ] **Step 1: Write the failing tests**

Create `hermes/test/runner.test.js`. House test style (plain `assert`, standalone runner):

```js
'use strict';
const assert = require('assert');
const fs = require('fs');
const os = require('os');
const path = require('path');
const { makeRunId, buildArgv, run } = require('../lib/runner');

// Minimal manual runner (house style — no node:test dependency).
const tests = [];
function test(name, fn) { tests.push([name, fn]); }

const target = { id: 'demo-agent', kind: 'agent', tier: 'read-only', prompt: 'audit this' };

function writeStub(body) {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'hermes-stub-'));
  const p = path.join(dir, 'claude');
  fs.writeFileSync(p, `#!/usr/bin/env node\n${body}`, { mode: 0o755 });
  return p;
}

test('makeRunId is deterministic for a fixed clock', () => {
  assert.equal(makeRunId(target, new Date('2026-07-20T14:32:10')), '20260720-143210-demo-agent');
});

test('buildArgv includes -p, the prompt, json output, and the target id', () => {
  const argv = buildArgv(target);
  assert.ok(argv.includes('-p'));
  assert.ok(argv.includes('audit this'));
  assert.equal(argv[argv.indexOf('--output-format') + 1], 'json');
  assert.ok(argv.includes('demo-agent'));
});

test('run captures stdout and a zero exit code from the engine', () => {
  const stub = writeStub('process.stdout.write(JSON.stringify({ok:true}));process.exit(0);');
  const r = run(target, { claudeBin: stub });
  assert.equal(r.code, 0);
  assert.equal(r.error, null);
  assert.match(r.stdout, /"ok":true/);
});

test('run reports ENOENT when the engine is absent', () => {
  const r = run(target, { claudeBin: '/nonexistent/claude-xyz' });
  assert.ok(r.error);
  assert.equal(r.error.type, 'ENOENT');
});

test('run reports TIMEOUT when the engine exceeds the budget', () => {
  const stub = writeStub('setTimeout(() => process.exit(0), 5000);');
  const r = run(target, { claudeBin: stub, timeoutMs: 300 });
  assert.ok(r.error);
  assert.equal(r.error.type, 'TIMEOUT');
});

test('run propagates a non-zero exit code without an error object', () => {
  const stub = writeStub('process.stderr.write("boom");process.exit(7);');
  const r = run(target, { claudeBin: stub });
  assert.equal(r.code, 7);
  assert.equal(r.error, null);
});

test('the engine is resolved through the adapter seam, not hardcoded (Engine seam D14)', () => {
  const stub = writeStub('process.stdout.write(JSON.stringify({ok:true}));process.exit(0);');
  const r = run(target, { engineAdapters: { claude: () => stub } });
  assert.equal(r.code, 0);
  assert.equal(r.engine, 'claude');
});

let failed = 0;
for (const [name, fn] of tests) {
  try { fn(); console.log(`✓ ${name}`); }
  catch (e) { failed++; console.error(`✗ ${name}`); console.error(e); }
}
if (failed > 0) { console.error(`\n${failed} test(s) failed`); process.exit(1); }
console.log(`\n✅ All ${tests.length} tests passed`);
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `node hermes/test/runner.test.js`
Expected: FAIL — `Cannot find module '../lib/runner'`.

- [ ] **Step 3: Write the runner implementation**

Create `hermes/lib/runner.js`:

```js
'use strict';
const { spawnSync } = require('child_process');

// Engine seam (D14): each entry resolves an engine name to the binary to spawn. H0 ships one
// adapter — `claude` — so later engines (e.g. `codex`) plug in here without touching loader.js
// or result-gate.js.
const ENGINE_ADAPTERS = {
  claude: (opts) => opts.claudeBin || 'claude',
};

function makeRunId(target, now = new Date()) {
  const pad = (n) => String(n).padStart(2, '0');
  const stamp =
    `${now.getFullYear()}${pad(now.getMonth() + 1)}${pad(now.getDate())}` +
    `-${pad(now.getHours())}${pad(now.getMinutes())}${pad(now.getSeconds())}`;
  return `${stamp}-${target.id}`;
}

function buildArgv(target) {
  // Agent-selection and permission flags confirmed against `claude --help`
  // during implementation (Task 2, Step 0). Adjust here if the CLI differs.
  return [
    '-p', target.prompt,
    '--output-format', 'json',
    '--agent', target.id,
    '--permission-mode', 'plan',
  ];
}

function run(target, opts = {}) {
  const {
    timeoutMs = 120000,
    cwd = process.cwd(),
    claudeBin = 'claude',
    now = new Date(),
    engineAdapters = ENGINE_ADAPTERS,
  } = opts;

  const engine = target.engine || 'claude';
  const resolveBin = engineAdapters[engine];
  if (!resolveBin) throw new Error(`unknown engine adapter "${engine}"`);
  const bin = resolveBin({ claudeBin });

  const runId = makeRunId(target, now);
  const argv = buildArgv(target);
  const started = Date.now();
  const r = spawnSync(bin, argv, {
    cwd,
    encoding: 'utf8',
    timeout: timeoutMs,
    maxBuffer: 64 * 1024 * 1024,
  });
  const durationMs = Date.now() - started;

  let error = null;
  if (r.error) {
    if (r.error.code === 'ENOENT') error = { type: 'ENOENT', message: `engine not found: ${bin}` };
    else if (r.error.code === 'ETIMEDOUT') error = { type: 'TIMEOUT', message: `run exceeded ${timeoutMs}ms` };
    else error = { type: 'SPAWN', message: r.error.message };
  } else if (r.signal === 'SIGTERM') {
    error = { type: 'TIMEOUT', message: `run exceeded ${timeoutMs}ms` };
  }

  return { runId, argv, stdout: r.stdout || '', stderr: r.stderr || '', code: r.status, durationMs, error, engine };
}

module.exports = { makeRunId, buildArgv, run };
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `node hermes/test/runner.test.js`
Expected: PASS — all 7 tests.

- [ ] **Step 5: Commit**

```bash
git add hermes/lib/runner.js hermes/test/runner.test.js
git commit -m "feat(hermes): claude -p runner with timeout + ENOENT handling"
```

---

### Task 3: Result gate (parse + verify + write artifacts)

Turns a raw run into a durable, reviewable verdict. Every path writes a `manifest.json`.

**Files:**
- Create: `hermes/lib/result-gate.js`
- Test: `hermes/test/result-gate.test.js`

**Interfaces:**
- Consumes: `target` (Task 1) and the `runResult` object from `runner.run` (Task 2).
- Produces:
  - `getGitSha(repoRoot) → string` (`'unknown'` if not a git repo).
  - `gate(target, runResult, config, ctx) → { status: 'pass'|'fail'|'error', manifest, artifactDir }`. `ctx = { repoRoot, gitSha }`. Writes `result.json` + `manifest.json` under `<repoRoot>/<config.runs_dir>/<runId>/`.

- [ ] **Step 1: Write the failing tests**

Create `hermes/test/result-gate.test.js`. House test style (plain `assert`, standalone runner):

```js
'use strict';
const assert = require('assert');
const fs = require('fs');
const os = require('os');
const path = require('path');
const { gate } = require('../lib/result-gate');

// Minimal manual runner (house style — no node:test dependency).
const tests = [];
function test(name, fn) { tests.push([name, fn]); }

const target = { id: 'demo-agent', kind: 'agent', tier: 'read-only', prompt: 'x' };
const config = { runs_dir: 'evals/hermes/runs' };
const tmpRepo = () => fs.mkdtempSync(path.join(os.tmpdir(), 'hermes-gate-'));

test('valid JSON output yields a pass verdict and writes artifacts', () => {
  const repoRoot = tmpRepo();
  const runResult = { runId: 'r1', argv: ['-p', 'x'], stdout: '{"result":"ok"}', stderr: '', code: 0, durationMs: 10, error: null };
  const out = gate(target, runResult, config, { repoRoot, gitSha: 'abc123' });
  assert.equal(out.status, 'pass');
  const manifest = JSON.parse(fs.readFileSync(path.join(out.artifactDir, 'manifest.json'), 'utf8'));
  assert.equal(manifest.verdict, 'pass');
  assert.equal(manifest.gitSha, 'abc123');
  assert.deepEqual(manifest.target, { id: 'demo-agent', kind: 'agent', tier: 'read-only' });
  const result = JSON.parse(fs.readFileSync(path.join(out.artifactDir, 'result.json'), 'utf8'));
  assert.equal(result.result, 'ok');
});

test('malformed JSON yields error status and preserves raw output', () => {
  const repoRoot = tmpRepo();
  const runResult = { runId: 'r2', argv: [], stdout: 'not json', stderr: 'warn', code: 0, durationMs: 5, error: null };
  const out = gate(target, runResult, config, { repoRoot, gitSha: 'x' });
  assert.equal(out.status, 'error');
  const result = JSON.parse(fs.readFileSync(path.join(out.artifactDir, 'result.json'), 'utf8'));
  assert.equal(result.raw_stdout, 'not json');
  assert.equal(result.raw_stderr, 'warn');
});

test('non-zero exit yields a fail verdict', () => {
  const repoRoot = tmpRepo();
  const runResult = { runId: 'r3', argv: [], stdout: '', stderr: 'boom', code: 7, durationMs: 5, error: null };
  const out = gate(target, runResult, config, { repoRoot, gitSha: 'x' });
  assert.equal(out.status, 'fail');
});

test('an engine error yields an error verdict and still writes a manifest', () => {
  const repoRoot = tmpRepo();
  const runResult = { runId: 'r4', argv: [], stdout: '', stderr: '', code: null, durationMs: 0, error: { type: 'ENOENT', message: 'x' } };
  const out = gate(target, runResult, config, { repoRoot, gitSha: 'x' });
  assert.equal(out.status, 'error');
  assert.ok(fs.existsSync(path.join(out.artifactDir, 'manifest.json')));
});

let failed = 0;
for (const [name, fn] of tests) {
  try { fn(); console.log(`✓ ${name}`); }
  catch (e) { failed++; console.error(`✗ ${name}`); console.error(e); }
}
if (failed > 0) { console.error(`\n${failed} test(s) failed`); process.exit(1); }
console.log(`\n✅ All ${tests.length} tests passed`);
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `node hermes/test/result-gate.test.js`
Expected: FAIL — `Cannot find module '../lib/result-gate'`.

- [ ] **Step 3: Write the result-gate implementation**

Create `hermes/lib/result-gate.js`:

```js
'use strict';
const fs = require('fs');
const path = require('path');
const { spawnSync } = require('child_process');

function getGitSha(repoRoot) {
  const r = spawnSync('git', ['rev-parse', 'HEAD'], { cwd: repoRoot, encoding: 'utf8' });
  return r.status === 0 ? r.stdout.trim() : 'unknown';
}

function gate(target, runResult, config, ctx = {}) {
  const repoRoot = ctx.repoRoot || process.cwd();
  const gitSha = ctx.gitSha || getGitSha(repoRoot);
  const runsDir = path.join(repoRoot, config.runs_dir || 'evals/hermes/runs');
  const artifactDir = path.join(runsDir, runResult.runId);
  fs.mkdirSync(artifactDir, { recursive: true });

  let status = 'pass';
  let parsed = null;
  let parseError = null;

  if (runResult.error) {
    status = 'error';
  } else if (runResult.code !== 0) {
    status = 'fail';
  } else {
    try {
      parsed = JSON.parse(runResult.stdout);
    } catch (e) {
      status = 'error';
      parseError = e.message;
    }
  }

  const manifest = {
    runId: runResult.runId,
    timestamp: new Date().toISOString(),
    target: { id: target.id, kind: target.kind, tier: target.tier },
    engine: runResult.engine || target.engine || 'claude', // which engine adapter ran (D14)
    argv: runResult.argv,
    exitCode: runResult.code,
    durationMs: runResult.durationMs,
    engineError: runResult.error || null,
    parseError: parseError || null,
    verdict: status,
    gitSha,
  };

  const resultPayload =
    parsed !== null ? parsed : { raw_stdout: runResult.stdout, raw_stderr: runResult.stderr };

  fs.writeFileSync(path.join(artifactDir, 'result.json'), JSON.stringify(resultPayload, null, 2));
  fs.writeFileSync(path.join(artifactDir, 'manifest.json'), JSON.stringify(manifest, null, 2));

  return { status, manifest, artifactDir };
}

module.exports = { getGitSha, gate };
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `node hermes/test/result-gate.test.js`
Expected: PASS — all 4 tests.

- [ ] **Step 5: Commit**

```bash
git add hermes/lib/result-gate.js hermes/test/result-gate.test.js
git commit -m "feat(hermes): result gate writes durable run manifest + result"
```

---

### Task 4: CLI entrypoint (`bin/hermes.js`) + exit-code contract

Thin wiring: loader → runner → gate, mapping outcomes to the distinct exit codes. The fail-closed guarantee (disallowed target spawns nothing, exits 2) is proven here as an automated test.

**Files:**
- Create: `hermes/bin/hermes.js`
- Test: `hermes/test/hermes.test.js`

**Interfaces:**
- Consumes: `loadConfig`, `resolveTarget` (Task 1); `runner.run` (Task 2); `gate` (Task 3).
- Produces:
  - `main(argv, opts) → exitCode` where `argv` is the args after `run` command (e.g. `['run', 'demo-agent']`), `opts = { repoRoot, claudeBin }` (both injectable for tests).
  - `EXIT = { OK: 0, INTERNAL: 1, VALIDATION: 2, ENGINE_MISSING: 3, TIMEOUT: 4, BAD_OUTPUT: 5 }`.

- [ ] **Step 1: Write the failing tests**

Create `hermes/test/hermes.test.js`. House test style (plain `assert`, standalone runner):

```js
'use strict';
const assert = require('assert');
const fs = require('fs');
const os = require('os');
const path = require('path');
const { main, EXIT } = require('../bin/hermes');

// Minimal manual runner (house style — no node:test dependency).
const tests = [];
function test(name, fn) { tests.push([name, fn]); }

function fixtureRepo() {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'hermes-bin-'));
  fs.mkdirSync(path.join(root, '.claude', 'agents'), { recursive: true });
  fs.mkdirSync(path.join(root, 'hermes'), { recursive: true });
  fs.writeFileSync(path.join(root, '.claude', 'agents', 'demo-agent.md'), '# demo');
  fs.writeFileSync(path.join(root, 'hermes', 'hermes.config.json'), JSON.stringify({
    allowed_tiers: ['read-only'],
    runs_dir: 'evals/hermes/runs',
    runnable_targets: [{ id: 'demo-agent', kind: 'agent', tier: 'read-only', prompt: 'x' }],
  }));
  return root;
}

function stub(body) {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'hermes-binstub-'));
  const p = path.join(dir, 'claude');
  fs.writeFileSync(p, `#!/usr/bin/env node\n${body}`, { mode: 0o755 });
  return p;
}

test('a valid run exits 0 and writes exactly one run dir', () => {
  const root = fixtureRepo();
  const bin = stub('process.stdout.write(JSON.stringify({ok:true}));');
  const code = main(['run', 'demo-agent'], { repoRoot: root, claudeBin: bin });
  assert.equal(code, EXIT.OK);
  const runs = fs.readdirSync(path.join(root, 'evals', 'hermes', 'runs'));
  assert.equal(runs.length, 1);
});

test('a disallowed target exits 2 and spawns nothing', () => {
  const root = fixtureRepo();
  const code = main(['run', 'ghost'], { repoRoot: root, claudeBin: '/should/not/be/used' });
  assert.equal(code, EXIT.VALIDATION);
  assert.equal(fs.existsSync(path.join(root, 'evals', 'hermes', 'runs')), false);
});

test('a missing engine exits 3', () => {
  const root = fixtureRepo();
  const code = main(['run', 'demo-agent'], { repoRoot: root, claudeBin: '/nonexistent/claude' });
  assert.equal(code, EXIT.ENGINE_MISSING);
});

test('malformed engine output exits 5', () => {
  const root = fixtureRepo();
  const bin = stub('process.stdout.write("not json");');
  const code = main(['run', 'demo-agent'], { repoRoot: root, claudeBin: bin });
  assert.equal(code, EXIT.BAD_OUTPUT);
});

test('usage error (no target) exits 2', () => {
  const root = fixtureRepo();
  const code = main(['run'], { repoRoot: root });
  assert.equal(code, EXIT.VALIDATION);
});

let failed = 0;
for (const [name, fn] of tests) {
  try { fn(); console.log(`✓ ${name}`); }
  catch (e) { failed++; console.error(`✗ ${name}`); console.error(e); }
}
if (failed > 0) { console.error(`\n${failed} test(s) failed`); process.exit(1); }
console.log(`\n✅ All ${tests.length} tests passed`);
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `node hermes/test/hermes.test.js`
Expected: FAIL — `Cannot find module '../bin/hermes'`.

- [ ] **Step 3: Write the CLI entrypoint**

Create `hermes/bin/hermes.js`:

```js
#!/usr/bin/env node
'use strict';
const path = require('path');
const { loadConfig, resolveTarget } = require('../lib/loader');
const runner = require('../lib/runner');
const { gate } = require('../lib/result-gate');

const EXIT = { OK: 0, INTERNAL: 1, VALIDATION: 2, ENGINE_MISSING: 3, TIMEOUT: 4, BAD_OUTPUT: 5 };

function main(argv, opts = {}) {
  const repoRoot = opts.repoRoot || path.resolve(__dirname, '..', '..');
  const [command, targetId] = argv;

  if (command !== 'run' || !targetId) {
    console.error('usage: hermes run <target>');
    return EXIT.VALIDATION;
  }

  const config = loadConfig(repoRoot);
  const resolved = resolveTarget(config, repoRoot, targetId);
  if (!resolved.ok) {
    console.error(`[loader] ${resolved.error}`);
    const valid = (config.runnable_targets || []).map((t) => t.id).join(', ') || '(none)';
    console.error(`[loader] valid targets: ${valid}`);
    return EXIT.VALIDATION;
  }
  const target = resolved.target;
  console.log(`[loader] 1 target resolved (${target.tier})`);

  const runResult = runner.run(target, { cwd: repoRoot, claudeBin: opts.claudeBin });
  console.log(`[run]    ${runResult.argv.join(' ')}  (${(runResult.durationMs / 1000).toFixed(1)}s)`);

  // Always gate so a manifest is written, even for engine errors.
  const result = gate(target, runResult, config, { repoRoot });
  console.log(`[gate]   manifest ${result.status.toUpperCase()}  → ${path.relative(repoRoot, result.artifactDir)}/`);

  if (runResult.error && runResult.error.type === 'ENOENT') {
    console.error(`[run]    ${runResult.error.message} — is the claude CLI in the image/PATH?`);
    return EXIT.ENGINE_MISSING;
  }
  if (runResult.error && runResult.error.type === 'TIMEOUT') {
    console.error(`[run]    ${runResult.error.message}`);
    return EXIT.TIMEOUT;
  }
  return result.status === 'pass' ? EXIT.OK : EXIT.BAD_OUTPUT;
}

if (require.main === module) {
  try {
    process.exit(main(process.argv.slice(2)));
  } catch (e) {
    console.error(`[hermes] internal error: ${e.stack || e.message}`);
    process.exit(EXIT.INTERNAL);
  }
}

module.exports = { main, EXIT };
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `node hermes/test/hermes.test.js`
Expected: PASS — all 5 tests, including the fail-closed proof (disallowed target exits 2, no run dir created).

- [ ] **Step 5: Commit**

```bash
git add hermes/bin/hermes.js hermes/test/hermes.test.js
git commit -m "feat(hermes): CLI entrypoint with distinct exit-code contract"
```

---

### Task 5: Test-runner wiring, gitignore, Docker packaging

Makes the Hermes suite part of `run-all-tests.js`, protects run artifacts from git, and ships the container so "deploy" later = "run the same image on the VPS".

**Files:**
- Modify: `scripts/run-all-tests.js` (add `hermes/` to the discovery roots)
- Modify: `.gitignore` (ignore `evals/hermes/runs/`)
- Modify: `package.json` (add a `hermes` convenience script)
- Create: `hermes/Dockerfile`
- Create: `hermes/docker-compose.yml`

**Interfaces:**
- Consumes: all modules from Tasks 1–4.
- Produces: `npm run hermes -- run <target>` locally; `docker compose -f hermes/docker-compose.yml run --rm hermes run <target>` in the container.

- [ ] **Step 1: Add `hermes/` to the test-runner discovery roots**

In `scripts/run-all-tests.js`, replace the `discovered` array (currently lines ~32-35):

```js
const discovered = [
  ...discoverTestFiles(path.join(REPO, 'skills'), []),
  ...discoverTestFiles(path.join(REPO, 'scripts'), []),
  ...(fs.existsSync(path.join(REPO, 'hermes')) ? discoverTestFiles(path.join(REPO, 'hermes'), []) : []),
].map(p => path.relative(REPO, p));
```

- [ ] **Step 2: Verify the Hermes suite is now discovered and green**

Run: `node scripts/run-all-tests.js`
Expected: output includes `PASS  hermes/test/loader.test.js`, `PASS  hermes/test/runner.test.js`, `PASS  hermes/test/result-gate.test.js`, `PASS  hermes/test/hermes.test.js`, and the final line reports all suites passed.

- [ ] **Step 3: Ignore run artifacts in git**

Confirm `evals/hermes/runs/` is not tracked. Append to `.gitignore` (only if not already covered):

```
# Hermes run artifacts (generated, never committed)
evals/hermes/runs/
```

Run: `git check-ignore evals/hermes/runs/anything`
Expected: prints the path (confirming it is ignored).

- [ ] **Step 4: Add a convenience script**

In `package.json`, add to `"scripts"`:

```json
"hermes": "node hermes/bin/hermes.js",
"test": "node scripts/run-all-tests.js"
```

- [ ] **Step 5: Write the Dockerfile**

Create `hermes/Dockerfile`:

```dockerfile
FROM node:20-slim

# git is needed for run-manifest gitSha; ca-certificates for the CLI's network calls.
RUN apt-get update \
  && apt-get install -y --no-install-recommends git ca-certificates \
  && rm -rf /var/lib/apt/lists/*

# Bundle the Claude Code CLI so the container is self-sufficient (headless engine).
RUN npm install -g @anthropic-ai/claude-code

WORKDIR /app
COPY . .

ENTRYPOINT ["node", "hermes/bin/hermes.js"]
```

- [ ] **Step 6: Write the compose file**

Create `hermes/docker-compose.yml`:

```yaml
services:
  hermes:
    build:
      context: ..
      dockerfile: hermes/Dockerfile
    environment:
      - ANTHROPIC_API_KEY=${ANTHROPIC_API_KEY}
    volumes:
      # Persist run artifacts back to the host repo.
      - ../evals/hermes/runs:/app/evals/hermes/runs
    working_dir: /app
```

- [ ] **Step 7: Verify the image builds**

Run: `docker build -f hermes/Dockerfile -t hermes-h0 .`
Expected: build completes successfully (final `naming to docker.io/library/hermes-h0`).

- [ ] **Step 8: Commit**

```bash
git add scripts/run-all-tests.js .gitignore package.json hermes/Dockerfile hermes/docker-compose.yml
git commit -m "chore(hermes): wire tests into run-all-tests, gitignore runs, add Docker packaging"
```

---

## Definition of done (H0 verification gate)

Run these after Task 5. The last two are the ones that prove the *contract*, not just the happy path:

- [ ] `node scripts/run-all-tests.js` → all suites pass, Hermes suite included.
- [ ] `git check-ignore evals/hermes/runs/x` → path is ignored.
- [ ] **Fail-closed proof (automated):** the `hermes.test.js` "disallowed target exits 2 and spawns nothing" test passes — a demonstrated refusal.
- [ ] **Live smoke (opt-in, manual, needs `ANTHROPIC_API_KEY`):** `docker compose -f hermes/docker-compose.yml run --rm hermes run repo-audit-testing` → prints `[loader]/[run]/[gate]`, exits 0, and writes `evals/hermes/runs/<id>/{result,manifest}.json` with `verdict: "pass"`.

## Out of scope (roadmap — do NOT build here)

Credential vault, HITL pause/resume, staging/budget enforcement, HITL/staging-autonomous tiers, the persistent daemon + scheduler, HTTP/Slack channels, VPS deploy, and any LangChain/CrewAI integration. See the spec's "Roadmap beyond H0" and "Future work" sections. Later phases *extend* these files; they do not rewrite them.
