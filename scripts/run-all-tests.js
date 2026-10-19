#!/usr/bin/env node
// scripts/run-all-tests.js — one command for "did I break the eval pipeline?".
//
// Discovers every *.test.js under skills/ and scripts/ (plus the named non-.test.js
// suites below) and runs each in its own node process. Run this after ANY change
// under skills/*/scripts/, scripts/codex/, scripts/telemetry/, or the calibration
// scripts (see fixtures/GATE-RUNBOOK.md). Exits non-zero if any suite fails.
'use strict';
const { spawnSync } = require('child_process');
const fs = require('fs');
const path = require('path');

const REPO = path.join(__dirname, '..');

// Suites that don't follow the *.test.js naming convention.
const NAMED_SUITES = [
  path.join('scripts', 'codex', 'test-schemas.js'),
  path.join('scripts', 'codex', 'test-runners.js'),
  path.join('scripts', 'telemetry', 'test-telemetry.js'),
];

function discoverTestFiles(dir, out) {
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    if (entry.name === 'node_modules' || entry.name.startsWith('.') || entry.name.startsWith('__')) continue;
    const p = path.join(dir, entry.name);
    if (entry.isDirectory()) discoverTestFiles(p, out);
    else if (entry.name.endsWith('.test.js')) out.push(p);
  }
  return out;
}

// The report printed for a failing suite. stderr is kept whole up to 200 lines, then head and tail: node
// prints an uncaught assertion's message ABOVE its stack and error fields, so a short tail loses it (an
// intermittent brain-hooks.test.js failure on 2026-10-19 left only "actual: false, expected: true").
const STDERR_HEAD = 100;
const STDERR_TAIL = 100;
const STDOUT_TAIL = 40;

function formatFailure(r) {
  const parts = [];
  if (r.error) parts.push(`(could not run: ${r.error.message})`);
  if (r.status === null && r.signal) parts.push(`(killed by ${r.signal})`);
  const out = (r.stdout || '').replace(/\n$/, '').split('\n');
  if (out.join('')) parts.push(out.slice(-STDOUT_TAIL).join('\n'));
  const err = (r.stderr || '').replace(/\n$/, '').split('\n');
  if (err.join('')) {
    parts.push(err.length <= STDERR_HEAD + STDERR_TAIL ? err.join('\n')
      : [...err.slice(0, STDERR_HEAD), `... ${err.length - STDERR_HEAD - STDERR_TAIL} lines omitted ...`, ...err.slice(-STDERR_TAIL)].join('\n'));
  }
  return parts.join('\n') + '\n';
}

function main() {
  const discovered = [
    ...discoverTestFiles(path.join(REPO, 'skills'), []),
    ...discoverTestFiles(path.join(REPO, 'scripts'), []),
  ].map(p => path.relative(REPO, p));

  const suites = [...new Set([...discovered, ...NAMED_SUITES])].sort()
    .filter(p => fs.existsSync(path.join(REPO, p)));

  if (suites.length === 0) {
    console.error('Error: no test suites found — expected *.test.js files under skills/ and scripts/.');
    process.exit(1);
  }

  let failed = 0;
  for (const suite of suites) {
    const r = spawnSync('node', [suite], { cwd: REPO, encoding: 'utf8', maxBuffer: 64 * 1024 * 1024 });
    const ok = r.status === 0;
    if (!ok) failed++;
    console.log(`${ok ? 'PASS' : 'FAIL'}  ${suite}`);
    if (!ok) process.stdout.write(formatFailure(r));
  }

  console.log(`\n${suites.length - failed}/${suites.length} suites passed`);
  process.exit(failed === 0 ? 0 : 1);
}

module.exports = { formatFailure };

if (require.main === module) main();
