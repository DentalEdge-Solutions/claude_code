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
  assert.match(formatFailure({ status: null, error: new Error('spawn node ENOENT'), stdout: '', stderr: '' }), /spawn node ENOENT/);
});

if (!ok) process.exit(1);
console.log('\nAll run-all-tests tests passed.');
