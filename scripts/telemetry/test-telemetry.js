#!/usr/bin/env node
/**
 * Tests for scripts/telemetry/*.js. Mirrors the hand-rolled, no-AJV style of
 * scripts/codex/test-schemas.js and scripts/codex/test-runners.js.
 *
 * All tests run against an isolated temp "repo root" (under the OS temp dir),
 * never against this repo's own evals/telemetry/ — no cleanup of the real
 * repo is needed after running this file.
 */
'use strict';
const { spawnSync } = require('child_process');
const { mkdirSync, writeFileSync, readFileSync, existsSync, rmSync } = require('fs');
const os = require('os');
const path = require('path');

let ok = true;
function test(label, fn) {
  try { fn(); console.log(`PASS ${label}`); }
  catch (e) { console.error(`FAIL ${label}: ${e.message}`); ok = false; }
}
function assert(cond, msg) { if (!cond) throw new Error(msg); }

const redact = require('./redact');

// ── Isolated temp repo root ──────────────────────────────────────────────────

const TMP_ROOT = path.join(os.tmpdir(), `telemetry-test-${process.pid}-${Date.now()}`);

function freshRepo() {
  if (existsSync(TMP_ROOT)) rmSync(TMP_ROOT, { recursive: true });
  mkdirSync(TMP_ROOT, { recursive: true });
  mkdirSync(path.join(TMP_ROOT, 'skills', 'demo-skill'), { recursive: true });
  writeFileSync(path.join(TMP_ROOT, 'skills', 'demo-skill', 'SKILL.md'), '# demo\n');
  return TMP_ROOT;
}

function currentMonthFile(repoRoot) {
  const d = new Date();
  const y = d.getUTCFullYear();
  const m = String(d.getUTCMonth() + 1).padStart(2, '0');
  return path.join(repoRoot, 'evals', 'telemetry', `events-${y}-${m}.jsonl`);
}

function readEvents(repoRoot) {
  const f = currentMonthFile(repoRoot);
  if (!existsSync(f)) return [];
  return readFileSync(f, 'utf8').split('\n').filter(Boolean).map(l => JSON.parse(l));
}

function runHook(script, stdinObj, extraArgs, env) {
  const input = typeof stdinObj === 'string' ? stdinObj : JSON.stringify(stdinObj);
  return spawnSync('node', [script, ...(extraArgs || [])], {
    input,
    encoding: 'utf8',
    env: { ...process.env, ...(env || {}) },
    timeout: 10000,
  });
}

// ── Schema validation helper (hand-rolled, no AJV) ───────────────────────────

const schema = JSON.parse(readFileSync(path.join(__dirname, '..', '..', 'schemas', 'telemetry', 'invocation-event.schema.json'), 'utf8'));

function validateEvent(obj) {
  const errors = [];
  for (const req of schema.required) {
    if (!(req in obj)) errors.push(`missing required field: ${req}`);
  }
  for (const key of Object.keys(obj)) {
    if (!(key in schema.properties)) errors.push(`unexpected field: ${key}`);
  }
  for (const [key, val] of Object.entries(obj)) {
    const propSchema = schema.properties[key];
    if (propSchema && propSchema.enum && !propSchema.enum.includes(val)) {
      errors.push(`invalid enum value for ${key}: ${val}`);
    }
  }
  if (obj.event === 'outcome' && obj.outcome) {
    for (const req of schema.properties.outcome.required) {
      if (!(req in obj.outcome)) errors.push(`outcome missing required field: ${req}`);
    }
  }
  return errors;
}

// ══════════════════════════════════════════════════════════════════════════
// 1. Schema tests
// ══════════════════════════════════════════════════════════════════════════

test('schema: valid invocation event passes', () => {
  const errors = validateEvent({
    ts: new Date().toISOString(),
    session_id: 'sess-1',
    invocation_id: 'inv-1',
    name: 'demo-skill',
    kind: 'skill',
    event: 'invocation',
    artifacts: ['skills/demo-skill/SKILL.md'],
  });
  assert(errors.length === 0, `expected no errors, got: ${errors.join('; ')}`);
});

test('schema: missing required field fails', () => {
  const errors = validateEvent({
    // no session_id
    ts: new Date().toISOString(),
    event: 'invocation',
  });
  assert(errors.some(e => e.includes('session_id')), `expected session_id error, got: ${errors.join('; ')}`);
});

test('schema: outcome event requires nested outcome fields', () => {
  const errors = validateEvent({
    ts: new Date().toISOString(),
    session_id: 'sess-1',
    invocation_id: 'inv-1',
    name: 'demo-skill',
    kind: 'skill',
    event: 'outcome',
    outcome: { followed_by_correction: true }, // missing user_disposition, confidence
  });
  assert(errors.some(e => e.includes('user_disposition')), `expected nested error, got: ${errors.join('; ')}`);
});

// ══════════════════════════════════════════════════════════════════════════
// 2. redact.js
// ══════════════════════════════════════════════════════════════════════════

// Assembled at runtime so no token-shaped literal sits in the source (static-scan reads scripts, S12).
const FAKE_SECRET = 'sk-' + 'ant-api03-FAKE1234567890ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789';

test('redact: strips a planted fake API key', () => {
  const input = `Here is my key: ${FAKE_SECRET} — keep it secret.`;
  const out = redact.redactString(input);
  assert(!out.includes(FAKE_SECRET), 'raw secret must not survive redaction');
  assert(out.includes('[REDACTED]'), 'redacted output should contain the [REDACTED] marker');
});

test('redact: sha256Hex never returns the raw text', () => {
  const hash = redact.sha256Hex('some raw prompt text with secrets');
  assert(hash !== 'some raw prompt text with secrets', 'hash must not equal input');
  assert(/^[a-f0-9]{64}$/.test(hash), 'sha256 hex digest should be 64 hex chars');
});

test('redact: extractArtifactPaths only returns repo-relative paths', () => {
  const repoRoot = freshRepo();
  const text = `Wrote skills/demo-skill/SKILL.md and /etc/passwd and ../outside.md`;
  const paths = redact.extractArtifactPaths(text, repoRoot);
  assert(paths.includes('skills/demo-skill/SKILL.md'), 'should include the in-repo path');
  assert(!paths.some(p => p.includes('etc/passwd')), 'should not include absolute out-of-repo paths');
  assert(!paths.some(p => p.includes('..')), 'should not include paths that escape repo root');
});

// ══════════════════════════════════════════════════════════════════════════
// 3. log-invocation.js end-to-end
// ══════════════════════════════════════════════════════════════════════════

test('log-invocation: writes a valid JSONL line for a Skill call', () => {
  const repoRoot = freshRepo();
  const event = {
    session_id: 'sess-inv-1',
    cwd: repoRoot,
    hook_event_name: 'PostToolUse',
    tool_name: 'Skill',
    tool_input: { skill: 'demo-skill', prompt: 'do NOT store this raw text ' + FAKE_SECRET },
    tool_response: { status: 'ok', message: 'Wrote skills/demo-skill/SKILL.md successfully.' },
  };
  const r = runHook(path.join(__dirname, 'log-invocation.js'), event, [], { CLAUDE_PROJECT_DIR: repoRoot });
  assert(r.status === 0, `expected exit 0, got ${r.status}, stderr: ${r.stderr}`);

  const events = readEvents(repoRoot);
  assert(events.length === 1, `expected 1 event, got ${events.length}`);
  const e = events[0];
  const errors = validateEvent(e);
  assert(errors.length === 0, `schema errors: ${errors.join('; ')}`);
  assert(e.name === 'demo-skill', 'name should be demo-skill');
  assert(e.kind === 'skill', 'kind should be skill');
  assert(e.event === 'invocation', 'event should be invocation');
  assert(e.artifacts.includes('skills/demo-skill/SKILL.md'), 'artifact path should be extracted');
  assert(typeof e.context_hash === 'string' && e.context_hash.length === 64, 'context_hash should be a sha256 hex digest');

  const rawLine = readFileSync(currentMonthFile(repoRoot), 'utf8');
  assert(!rawLine.includes(FAKE_SECRET), 'raw prompt text/secret must never be written to the JSONL file');
  assert(!rawLine.includes('do NOT store this raw text'), 'raw prompt text must never be written to the JSONL file');
});

test('log-invocation: Task call records subagent_type as name/kind=agent', () => {
  const repoRoot = freshRepo();
  const event = {
    session_id: 'sess-inv-2',
    cwd: repoRoot,
    hook_event_name: 'PostToolUse',
    tool_name: 'Task',
    tool_input: { subagent_type: 'demo-agent', prompt: 'agent task prompt text' },
    tool_response: { result: 'done' },
  };
  const r = runHook(path.join(__dirname, 'log-invocation.js'), event, [], { CLAUDE_PROJECT_DIR: repoRoot });
  assert(r.status === 0, `expected exit 0, got ${r.status}`);
  const events = readEvents(repoRoot);
  assert(events.length === 1, 'expected 1 event');
  assert(events[0].name === 'demo-agent' && events[0].kind === 'agent', 'should record agent kind/name');
});

test('log-invocation: ignores non-Skill/Task tool calls (no file written)', () => {
  const repoRoot = freshRepo();
  const event = {
    session_id: 'sess-inv-3', cwd: repoRoot, hook_event_name: 'PostToolUse',
    tool_name: 'Bash', tool_input: { command: 'ls' }, tool_response: { output: 'ok' },
  };
  const r = runHook(path.join(__dirname, 'log-invocation.js'), event, [], { CLAUDE_PROJECT_DIR: repoRoot });
  assert(r.status === 0, `expected exit 0, got ${r.status}`);
  assert(!existsSync(currentMonthFile(repoRoot)), 'no telemetry file should be written for non-matching tools');
});

test('log-invocation: exits 0 on malformed stdin (fail-open)', () => {
  const repoRoot = freshRepo();
  const r = runHook(path.join(__dirname, 'log-invocation.js'), '{not valid json!!', [], { CLAUDE_PROJECT_DIR: repoRoot });
  assert(r.status === 0, `expected exit 0 on malformed stdin, got ${r.status}`);
});

test('log-invocation: exits 0 on empty stdin (fail-open)', () => {
  const repoRoot = freshRepo();
  const r = runHook(path.join(__dirname, 'log-invocation.js'), '', [], { CLAUDE_PROJECT_DIR: repoRoot });
  assert(r.status === 0, `expected exit 0 on empty stdin, got ${r.status}`);
});

// ══════════════════════════════════════════════════════════════════════════
// 4. log-outcome.js correction heuristic
// ══════════════════════════════════════════════════════════════════════════

test('log-outcome: correction heuristic fires on a synthetic follow-up', () => {
  const repoRoot = freshRepo();
  const sessionId = 'sess-corr-1';

  // Seed an invocation with an artifact.
  const invEvent = {
    session_id: sessionId, cwd: repoRoot, hook_event_name: 'PostToolUse',
    tool_name: 'Skill', tool_input: { skill: 'demo-skill' },
    tool_response: { message: 'Wrote skills/demo-skill/SKILL.md.' },
  };
  let r = runHook(path.join(__dirname, 'log-invocation.js'), invEvent, [], { CLAUDE_PROJECT_DIR: repoRoot });
  assert(r.status === 0, 'seed invocation should exit 0');

  const seeded = readEvents(repoRoot);
  assert(seeded.length === 1, 'seed invocation should be recorded');

  // Follow-up prompt: mentions the artifact basename + revision language.
  const promptEvent = {
    session_id: sessionId, cwd: repoRoot, hook_event_name: 'UserPromptSubmit',
    prompt: 'Actually SKILL.md is wrong, please fix it.',
  };
  r = runHook(path.join(__dirname, 'log-outcome.js'), promptEvent, ['--mode', 'correction'], { CLAUDE_PROJECT_DIR: repoRoot });
  assert(r.status === 0, `expected exit 0, got ${r.status}, stderr: ${r.stderr}`);

  const events = readEvents(repoRoot);
  const outcomeEvents = events.filter(e => e.event === 'outcome');
  assert(outcomeEvents.length === 1, `expected 1 outcome event, got ${outcomeEvents.length}`);
  const o = outcomeEvents[0];
  assert(o.outcome.followed_by_correction === true, 'followed_by_correction should be true');
  assert(o.invocation_id === seeded[0].invocation_id, 'outcome should link back to the seeded invocation_id');

  const rawLine = readFileSync(currentMonthFile(repoRoot), 'utf8');
  assert(!rawLine.includes('Actually SKILL.md is wrong'), 'raw prompt text must never be written to the JSONL file');
});

test('log-outcome: correction heuristic does NOT fire on an unrelated prompt', () => {
  const repoRoot = freshRepo();
  const sessionId = 'sess-corr-2';

  const invEvent = {
    session_id: sessionId, cwd: repoRoot, hook_event_name: 'PostToolUse',
    tool_name: 'Skill', tool_input: { skill: 'demo-skill' },
    tool_response: { message: 'Wrote skills/demo-skill/SKILL.md.' },
  };
  runHook(path.join(__dirname, 'log-invocation.js'), invEvent, [], { CLAUDE_PROJECT_DIR: repoRoot });

  const promptEvent = {
    session_id: sessionId, cwd: repoRoot, hook_event_name: 'UserPromptSubmit',
    prompt: 'What is the weather like today in San Francisco?',
  };
  const r = runHook(path.join(__dirname, 'log-outcome.js'), promptEvent, ['--mode', 'correction'], { CLAUDE_PROJECT_DIR: repoRoot });
  assert(r.status === 0, `expected exit 0, got ${r.status}`);

  const events = readEvents(repoRoot);
  const outcomeEvents = events.filter(e => e.event === 'outcome');
  assert(outcomeEvents.length === 0, `expected 0 outcome events, got ${outcomeEvents.length}`);
});

test('log-outcome: session-end mode writes an artifact census', () => {
  const repoRoot = freshRepo();
  const sessionId = 'sess-end-1';

  const invEvent = {
    session_id: sessionId, cwd: repoRoot, hook_event_name: 'PostToolUse',
    tool_name: 'Skill', tool_input: { skill: 'demo-skill' },
    tool_response: { message: 'Wrote skills/demo-skill/SKILL.md and skills/demo-skill/MISSING.md.' },
  };
  runHook(path.join(__dirname, 'log-invocation.js'), invEvent, [], { CLAUDE_PROJECT_DIR: repoRoot });

  const stopEvent = { session_id: sessionId, cwd: repoRoot, hook_event_name: 'Stop' };
  const r = runHook(path.join(__dirname, 'log-outcome.js'), stopEvent, ['--mode', 'session-end'], { CLAUDE_PROJECT_DIR: repoRoot });
  assert(r.status === 0, `expected exit 0, got ${r.status}, stderr: ${r.stderr}`);

  const events = readEvents(repoRoot);
  const se = events.find(e => e.event === 'session_end');
  assert(se, 'expected a session_end event');
  const census = se.artifact_census;
  const existing = census.find(c => c.path === 'skills/demo-skill/SKILL.md');
  const missing = census.find(c => c.path === 'skills/demo-skill/MISSING.md');
  assert(existing && existing.exists === true, 'SKILL.md should be recorded as existing');
  assert(missing && missing.exists === false, 'MISSING.md should be recorded as not existing');
});

test('log-outcome: exits 0 on malformed stdin (fail-open)', () => {
  const repoRoot = freshRepo();
  const r = runHook(path.join(__dirname, 'log-outcome.js'), '{{bad json', ['--mode', 'correction'], { CLAUDE_PROJECT_DIR: repoRoot });
  assert(r.status === 0, `expected exit 0 on malformed stdin, got ${r.status}`);
});

// ══════════════════════════════════════════════════════════════════════════
// 5. aggregate-usage.js
// ══════════════════════════════════════════════════════════════════════════

function writeMonthFile(repoRoot, monthLabel, lines) {
  const dir = path.join(repoRoot, 'evals', 'telemetry');
  mkdirSync(dir, { recursive: true });
  writeFileSync(path.join(dir, `events-${monthLabel}.jsonl`), lines.map(l => JSON.stringify(l)).join('\n') + '\n');
}

test('aggregate-usage: computes rates and flags REFINE_RECOMMENDED', () => {
  const repoRoot = freshRepo();
  const now = new Date('2026-07-06T12:00:00.000Z');
  const monthLabel = '2026-07';

  const lines = [];
  const invIds = [];
  // 12 invocations in the trailing 30 days for "flaky-skill" — 5 corrected (>0.3 of 12), triggers REFINE_RECOMMENDED.
  for (let i = 0; i < 12; i++) {
    const ts = new Date(now.getTime() - i * 24 * 60 * 60 * 1000).toISOString(); // spread across last 12 days
    const invId = `inv-flaky-${i}`;
    invIds.push(invId);
    lines.push({
      ts, session_id: `sess-${i}`, invocation_id: invId, name: 'flaky-skill', kind: 'skill',
      event: 'invocation', artifacts: [`skills/flaky-skill/output-${i}.md`],
    });
  }
  // 5 corrections -> correction_rate = 5/12 = 0.4167 > 0.3
  for (let i = 0; i < 5; i++) {
    lines.push({
      ts: new Date(now.getTime() - i * 24 * 60 * 60 * 1000 + 1000).toISOString(),
      session_id: `sess-${i}`, invocation_id: invIds[i], name: 'flaky-skill', kind: 'skill',
      event: 'outcome', outcome: { followed_by_correction: true, user_disposition: 'revised', confidence: 'medium' },
    });
  }
  // A healthy skill with only 3 invocations — below the 10-invocation floor, must NOT be flagged.
  for (let i = 0; i < 3; i++) {
    lines.push({
      ts: new Date(now.getTime() - i * 24 * 60 * 60 * 1000).toISOString(),
      session_id: `sess-h-${i}`, invocation_id: `inv-healthy-${i}`, name: 'healthy-skill', kind: 'skill',
      event: 'invocation', artifacts: [`skills/healthy-skill/output-${i}.md`],
    });
  }

  writeMonthFile(repoRoot, monthLabel, lines);

  const r = spawnSync('node', [
    path.join(__dirname, 'aggregate-usage.js'), '--repo-root', repoRoot, '--now', now.toISOString(),
  ], { encoding: 'utf8', timeout: 10000 });
  assert(r.status === 0, `aggregate-usage.js should exit 0, stderr: ${r.stderr}`);

  const summaryPath = path.join(repoRoot, 'evals', 'telemetry', 'usage-summary.json');
  assert(existsSync(summaryPath), 'usage-summary.json should be written');
  const summary = JSON.parse(readFileSync(summaryPath, 'utf8'));

  const flaky = summary.targets['skill::flaky-skill'];
  assert(flaky, 'flaky-skill should appear in summary');
  assert(flaky.trailing_30d.invocation_count === 12, `expected 12 invocations, got ${flaky.trailing_30d.invocation_count}`);
  assert(Math.abs(flaky.trailing_30d.correction_rate - (5 / 12)) < 0.001, `correction_rate mismatch: ${flaky.trailing_30d.correction_rate}`);
  assert(flaky.refine_recommended === true, 'flaky-skill should be flagged REFINE_RECOMMENDED');

  const healthy = summary.targets['skill::healthy-skill'];
  assert(healthy, 'healthy-skill should appear in summary');
  assert(healthy.refine_recommended === false, 'healthy-skill should NOT be flagged (below 10-invocation floor)');

  const refineInputPath = path.join(repoRoot, 'evals', 'flaky-skill', 'refine-input.json');
  assert(existsSync(refineInputPath), 'refine-input.json should be created for the flagged target');
  const refineInput = JSON.parse(readFileSync(refineInputPath, 'utf8'));
  assert(refineInput.real_usage.source === 'telemetry', 'real_usage.source should be "telemetry"');
  assert(refineInput.real_usage.recommendation === 'REFINE_RECOMMENDED', 'real_usage.recommendation should be REFINE_RECOMMENDED');

  const healthyRefineInputPath = path.join(repoRoot, 'evals', 'healthy-skill', 'refine-input.json');
  assert(!existsSync(healthyRefineInputPath), 'refine-input.json should NOT be created for a non-flagged target');
});

test('aggregate-usage: preserves existing refine-input.json content on merge', () => {
  const repoRoot = freshRepo();
  const now = new Date('2026-07-06T12:00:00.000Z');
  const monthLabel = '2026-07';

  mkdirSync(path.join(repoRoot, 'evals', 'flaky-skill'), { recursive: true });
  writeFileSync(
    path.join(repoRoot, 'evals', 'flaky-skill', 'refine-input.json'),
    JSON.stringify({ failing_scenarios: ['s1-direct'], existing_field: 'keep-me' }, null, 2)
  );

  const lines = [];
  for (let i = 0; i < 10; i++) {
    const ts = new Date(now.getTime() - i * 24 * 60 * 60 * 1000).toISOString();
    lines.push({
      ts, session_id: `sess-${i}`, invocation_id: `inv-${i}`, name: 'flaky-skill', kind: 'skill',
      event: 'invocation', artifacts: [`skills/flaky-skill/output-${i}.md`],
    });
    lines.push({
      ts, session_id: `sess-${i}`, invocation_id: `inv-${i}`, name: 'flaky-skill', kind: 'skill',
      event: 'outcome', outcome: { followed_by_correction: true, user_disposition: 'revised', confidence: 'medium' },
    });
  }
  writeMonthFile(repoRoot, monthLabel, lines);

  const r = spawnSync('node', [
    path.join(__dirname, 'aggregate-usage.js'), '--repo-root', repoRoot, '--now', now.toISOString(),
  ], { encoding: 'utf8', timeout: 10000 });
  assert(r.status === 0, `expected exit 0, stderr: ${r.stderr}`);

  const refineInput = JSON.parse(readFileSync(path.join(repoRoot, 'evals', 'flaky-skill', 'refine-input.json'), 'utf8'));
  assert(refineInput.existing_field === 'keep-me', 'existing content must be preserved on merge');
  assert(Array.isArray(refineInput.failing_scenarios), 'existing failing_scenarios must be preserved');
  assert(refineInput.real_usage.source === 'telemetry', 'real_usage block must be merged in');
});

test('aggregate-usage: prunes month files beyond the 6-month retention window', () => {
  const repoRoot = freshRepo();
  const dir = path.join(repoRoot, 'evals', 'telemetry');
  mkdirSync(dir, { recursive: true });
  const months = ['2025-10', '2025-11', '2025-12', '2026-01', '2026-02', '2026-03', '2026-04'];
  for (const m of months) writeFileSync(path.join(dir, `events-${m}.jsonl`), '');

  const r = spawnSync('node', [
    path.join(__dirname, 'aggregate-usage.js'), '--repo-root', repoRoot, '--now', '2026-04-15T00:00:00.000Z',
  ], { encoding: 'utf8', timeout: 10000 });
  assert(r.status === 0, `expected exit 0, stderr: ${r.stderr}`);

  assert(!existsSync(path.join(dir, 'events-2025-10.jsonl')), 'oldest month file should be pruned');
  for (const m of months.slice(1)) {
    assert(existsSync(path.join(dir, `events-${m}.jsonl`)), `${m} should be kept (within 6-month window)`);
  }
});

// ── Cleanup + summary ─────────────────────────────────────────────────────────

if (existsSync(TMP_ROOT)) rmSync(TMP_ROOT, { recursive: true });

process.exit(ok ? 0 : 1);
