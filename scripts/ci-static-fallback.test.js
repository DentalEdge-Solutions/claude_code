#!/usr/bin/env node
// scripts/ci-static-fallback.test.js — tests for scripts/ci-static-fallback.js.
//
// Like ci-scan-skills.test.js, this file does not require child_process itself; the
// scans below go through the exported scanFile/runFallback, which own the process call.
// Stand-in scanners are written to a temp dir so a real crash can be exercised (U7).
'use strict';
const assert = require('assert');
const fs = require('fs');
const os = require('os');
const path = require('path');

const { classify, listTargets, scanFile, runFallback, main } = require('./ci-static-fallback');

const REPO = path.join(__dirname, '..');

let ok = true;
function test(label, fn) {
  try { fn(); console.log(`PASS ${label}`); }
  catch (e) { console.error(`FAIL ${label}: ${e.message}`); ok = false; }
}

const run = (verdict, status) => ({ status, stdout: JSON.stringify({ verdict, findings: [] }), stderr: '' });

// ── classify: pure ───────────────────────────────────────────────────────────

test('classify: PASS/FLAG/BLOCK with the matching exit code are taken as-is', () => {
  assert.strictEqual(classify(run('PASS', 0)).verdict, 'PASS');
  assert.strictEqual(classify(run('FLAG', 1)).verdict, 'FLAG');
  assert.strictEqual(classify(run('BLOCK', 2)).verdict, 'BLOCK');
});

test('classify: empty stdout (the scanner died before printing) is ERROR', () => {
  const c = classify({ status: 1, stdout: '', stderr: 'RangeError: Maximum call stack size exceeded' });
  assert.strictEqual(c.verdict, 'ERROR');
  assert.match(c.reason, /RangeError/);
});

test('classify: non-JSON stdout is ERROR', () => {
  assert.strictEqual(classify({ status: 0, stdout: 'Usage: …', stderr: '' }).verdict, 'ERROR');
});

test('classify: JSON without a known verdict is ERROR', () => {
  assert.strictEqual(classify({ status: 0, stdout: '{"findings":[]}', stderr: '' }).verdict, 'ERROR');
  assert.strictEqual(classify({ status: 0, stdout: '{"verdict":"OK"}', stderr: '' }).verdict, 'ERROR');
  assert.strictEqual(classify({ status: 0, stdout: 'null', stderr: '' }).verdict, 'ERROR');
});

test('classify: an exit code that disagrees with the verdict is ERROR', () => {
  assert.strictEqual(classify(run('PASS', 1)).verdict, 'ERROR');
  assert.strictEqual(classify(run('BLOCK', 0)).verdict, 'ERROR');
});

test('classify: a non-string verdict is ERROR (Y1: ["BLOCK"] passed the key check)', () => {
  for (const v of [['BLOCK'], ['PASS'], 2, true, { BLOCK: 1 }]) {
    assert.strictEqual(classify({ status: 2, stdout: JSON.stringify({ verdict: v }), stderr: '' }).verdict, 'ERROR', JSON.stringify(v));
  }
});

test('classify: the reason names the error, not the trailing "Node.js vN" line (Y3)', () => {
  const stderr = '/x/static-scan.js:1\nthrow new RangeError(\'boom\');\n^\n\nRangeError: boom\n    at Object.<anonymous> (/x:1:7)\n\nNode.js v24.0.0\n';
  const c = classify({ status: 1, stdout: '', stderr });
  assert.match(c.reason, /RangeError: boom/);
  assert.doesNotMatch(c.reason, /Node\.js v/);
  assert.match(classify({ status: 1, stdout: '', stderr: 'oops\n\nNode.js v24.0.0\n' }).reason, /— oops$/);
});

test('classify: killed by a signal (status null) or a spawn error is ERROR', () => {
  assert.strictEqual(classify({ ...run('PASS', 0), status: null, signal: 'SIGKILL' }).verdict, 'ERROR');
  assert.strictEqual(classify({ ...run('PASS', 0), error: new Error('spawnSync node ENOBUFS') }).verdict, 'ERROR');
});

// ── scanFile / runFallback with stand-in scanners ────────────────────────────

const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'ci-fallback-'));
const fake = (name, body) => { const p = path.join(tmp, name); fs.writeFileSync(p, body); return p; };
const CRASHES = fake('crash.js', "throw new RangeError('Maximum call stack size exceeded');\n");
const SILENT = fake('silent.js', 'process.exit(0);\n');
const BLOCKS = fake('block.js', "console.log(JSON.stringify({ verdict: 'BLOCK', findings: [] })); process.exit(2);\n");
const PASSES = fake('pass.js', "console.log(JSON.stringify({ verdict: 'PASS', findings: [] })); process.exit(0);\n");
const ARRAY_VERDICT = fake('array.js', "console.log(JSON.stringify({ verdict: ['BLOCK'] })); process.exit(2);\n");

test('scanFile: a scanner that crashes is ERROR (U7: was printed as PASS)', () => {
  assert.strictEqual(scanFile('x.md', CRASHES).verdict, 'ERROR');
});

test('scanFile: a scanner that exits 0 with no output is ERROR', () => {
  assert.strictEqual(scanFile('x.md', SILENT).verdict, 'ERROR');
});

test('runFallback: fails on any ERROR, prints it as ERROR and never as PASS', () => {
  const lines = [];
  const failed = runFallback(['a.md', 'b.md'], { scanner: CRASHES, log: l => lines.push(l) });
  assert.strictEqual(failed, true);
  assert.deepStrictEqual(lines.filter(l => /^PASS/.test(l)), []);
  assert.strictEqual(lines.filter(l => /^ERROR: a\.md/.test(l)).length, 1);
  assert.strictEqual(lines.filter(l => /^ERROR: b\.md/.test(l)).length, 1);
  assert.strictEqual(lines[lines.length - 1], 'Static fallback: FAILED');
});

test('runFallback: a scanner with a non-string verdict fails the gate (Y1)', () => {
  const lines = [];
  assert.strictEqual(runFallback(['a.md'], { scanner: ARRAY_VERDICT, log: l => lines.push(l) }), true);
  assert.deepStrictEqual(lines.filter(l => /^PASS/.test(l)), []);
});

test('main: exits 1 when the scanner crashes and 0 when all pass (the exit code CI reads, Y2)', () => {
  const repo = fs.mkdtempSync(path.join(tmp, 'main-'));
  fs.mkdirSync(path.join(repo, '.claude', 'agents'), { recursive: true });
  fs.writeFileSync(path.join(repo, '.claude', 'agents', 'a.md'), '');
  const quiet = { log: () => {} };
  assert.strictEqual(main(repo, { ...quiet, scanner: CRASHES }), 1);
  assert.strictEqual(main(repo, { ...quiet, scanner: BLOCKS }), 1);
  assert.strictEqual(main(repo, { ...quiet, scanner: PASSES }), 0);
  const lines = [];
  main(repo, { scanner: PASSES, log: l => lines.push(l) });
  assert.deepStrictEqual(lines, ['PASS:  .claude/agents/a.md', 'Static fallback: PASSED']);
});

test('runFallback: a BLOCK fails and prints one BLOCK line, not BLOCK plus FLAG', () => {
  const lines = [];
  const failed = runFallback(['a.md'], { scanner: BLOCKS, log: l => lines.push(l) });
  assert.strictEqual(failed, true);
  assert.deepStrictEqual(lines.filter(l => /a\.md/.test(l)), ['BLOCK: a.md']);
});

test('runFallback: all PASS succeeds', () => {
  const lines = [];
  assert.strictEqual(runFallback(['a.md'], { scanner: PASSES, log: l => lines.push(l) }), false);
  assert.ok(lines.includes('PASS:  a.md'));
  assert.ok(lines.includes('Static fallback: PASSED'));
});

// ── Targets and the real scanner ─────────────────────────────────────────────

test('listTargets: agent files sorted, then settings files that exist', () => {
  const repo = fs.mkdtempSync(path.join(tmp, 'repo-'));
  fs.mkdirSync(path.join(repo, '.claude', 'agents'), { recursive: true });
  for (const f of ['b.md', 'a.md', 'notes.txt']) fs.writeFileSync(path.join(repo, '.claude', 'agents', f), '');
  fs.writeFileSync(path.join(repo, '.claude', 'settings.local.json'), '{}');
  assert.deepStrictEqual(listTargets(repo), [
    '.claude/agents/a.md', '.claude/agents/b.md', '.claude/settings.local.json',
  ]);
});

test('listTargets: no .claude/agents directory is not a crash', () => {
  assert.deepStrictEqual(listTargets(fs.mkdtempSync(path.join(tmp, 'empty-'))), []);
});

test('runFallback: the real scanner gives no ERROR on this repo\'s .claude/ files', () => {
  const lines = [];
  runFallback(listTargets(REPO), { cwd: REPO, log: l => lines.push(l) });
  assert.deepStrictEqual(lines.filter(l => /^ERROR/.test(l)), []);
  assert.ok(lines.length > 1);
});

fs.rmSync(tmp, { recursive: true, force: true });
process.exit(ok ? 0 : 1);
