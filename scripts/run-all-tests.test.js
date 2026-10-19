#!/usr/bin/env node
// scripts/run-all-tests.test.js — tests for the failure report in scripts/run-all-tests.js.
//
// The runner used to print only the last 15 lines of a failing suite's stdout and stderr. Node prints an
// uncaught assertion's message above its stack trace and error fields, so the message was cut off: an
// intermittent scripts/brain/brain-hooks.test.js failure (2026-10-19) left only "actual: false, expected: true".
'use strict';
const assert = require('assert');
const { formatFailure } = require('./run-all-tests');

let ok = true;
function test(label, fn) {
  try { fn(); console.log(`PASS ${label}`); }
  catch (e) { console.error(`FAIL ${label}: ${e.message}`); ok = false; }
}

// What node prints for an uncaught AssertionError, below some suite output.
const nodeAssertion = msg => [
  ...Array.from({ length: 30 }, (_, i) => `PASS case ${i}`),
  '/repo/scripts/x.test.js:465',
  '    assert.ok(ms < 3000, `guard took ${ms} ms`);',
  '    ^',
  '',
  `AssertionError [ERR_ASSERTION]: ${msg}`,
  ...Array.from({ length: 12 }, (_, i) => `    at frame${i} (node:internal/x:${i}:1)`),
  '  generatedMessage: false,', "  code: 'ERR_ASSERTION',", '  actual: false,', '  expected: true,', "  operator: '=='", '}',
  '', 'Node.js v26.9.0', '',
].join('\n');

test('a failing suite keeps the assertion message, not only the tail', () => {
  const out = formatFailure({ status: 1, stdout: '', stderr: nodeAssertion('guard took 3120 ms on a 512 KB command') });
  assert.match(out, /AssertionError \[ERR_ASSERTION\]: guard took 3120 ms on a 512 KB command/);
  assert.match(out, /x\.test\.js:465/);
});

test('very long output keeps its head and tail and says how much was left out', () => {
  const stderr = Array.from({ length: 1000 }, (_, i) => `line ${i}`).join('\n');
  const out = formatFailure({ status: 1, stdout: '', stderr });
  assert.match(out, /^line 0$/m);
  assert.match(out, /^line 99$/m);
  assert.match(out, /^line 999$/m);
  assert.doesNotMatch(out, /^line 500$/m);
  assert.match(out, /800 lines omitted/);
});

test('stdout keeps its last 40 lines', () => {
  const stdout = Array.from({ length: 100 }, (_, i) => `out ${i}`).join('\n');
  const out = formatFailure({ status: 1, stdout, stderr: '' });
  assert.match(out, /^out 99$/m);
  assert.match(out, /^out 60$/m);
  assert.doesNotMatch(out, /^out 59$/m);
});

test('a suite killed by a signal or that could not start says so', () => {
  assert.match(formatFailure({ status: null, signal: 'SIGKILL', stdout: '', stderr: '' }), /killed by SIGKILL/);
  assert.match(formatFailure({ status: null, error: new Error('spawn node ENOENT'), stdout: '', stderr: '' }), /spawn error: spawn node ENOENT/);
});

test('short stderr is printed once and whole, with no omission marker (review R4)', () => {
  const out = formatFailure({ status: 1, stdout: '', stderr: 'only line' });
  assert.strictEqual(out.split('only line').length - 1, 1);
  assert.doesNotMatch(out, /omitted/);
});

test('200 stderr lines print whole; 201 print head, one marker and tail (review R4, R5)', () => {
  const lines = n => Array.from({ length: n }, (_, i) => `l${i}`).join('\n');
  assert.doesNotMatch(formatFailure({ status: 1, stdout: '', stderr: lines(200) }), /omitted/);
  const out = formatFailure({ status: 1, stdout: '', stderr: lines(201) });
  assert.strictEqual((out.match(/omitted/g) || []).length, 1);
  assert.match(out, /\.\.\. 1 line omitted \.\.\./);
});

test('a non-zero exit with no output says the exit code; a spawn error is not called "could not run" (review R2)', () => {
  assert.match(formatFailure({ status: 3, stdout: '', stderr: '' }), /\(exit 3\b/);
  const out = formatFailure({ status: null, signal: 'SIGTERM', error: new Error('spawnSync node ETIMEDOUT'), stdout: '', stderr: '' });
  assert.match(out, /spawn error: spawnSync node ETIMEDOUT/);
  assert.doesNotMatch(out, /could not run/);
});

test('a very long line is cut, so one huge line cannot flood the log (review R3)', () => {
  const out = formatFailure({ status: 1, stdout: 'x'.repeat(1e6), stderr: 'y'.repeat(1e6) });
  assert.ok(out.length < 20000, `report is ${out.length} chars`);
  assert.match(out, /characters cut/);
});

if (!ok) process.exit(1);
console.log('\nAll run-all-tests tests passed.');
