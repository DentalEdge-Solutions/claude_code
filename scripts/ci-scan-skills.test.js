#!/usr/bin/env node
// scripts/ci-scan-skills.test.js — tests for scripts/ci-scan-skills.js.
//
// Deliberately does NOT `require('child_process')` itself (this repo's own
// static-scan-skills gate only scans skills/*/, not scripts/, so it would not be
// caught anyway — but the diff/compare logic under test is pure, so there is no
// need to shell out to exercise it). Where a real scan is needed, it calls the
// exported `scanSkillDir` / `collectBlockFindings` functions directly — those
// functions use child_process internally, but that is code in ci-scan-skills.js,
// not in this test file.
'use strict';
const assert = require('assert');
const path = require('path');

const {
  diff,
  keyOf,
  loadBaseline,
  scanSkillDir,
  collectBlockFindings,
} = require('./ci-scan-skills');

const REPO = path.join(__dirname, '..');

let ok = true;
function test(label, fn) {
  try { fn(); console.log(`PASS ${label}`); }
  catch (e) { console.error(`FAIL ${label}: ${e.message}`); ok = false; }
}

// ── Pure diff logic ─────────────────────────────────────────────────────────

test('diff: matches an actual finding against an identical baseline entry', () => {
  const actual = [{ skill: 'agent-eval', file: 'scripts/x.test.js', check: 'child-process-require', severity: 'BLOCK', detail: 'd' }];
  const baseline = [{ skill: 'agent-eval', file: 'scripts/x.test.js', check: 'child-process-require' }];
  const { matched, unmatched, stale } = diff(actual, baseline);
  assert.strictEqual(matched.length, 1);
  assert.strictEqual(unmatched.length, 0);
  assert.strictEqual(stale.length, 0);
});

test('diff: a BLOCK finding not covered by the baseline is unmatched (would fail CI)', () => {
  const actual = [{ skill: 'some-skill', file: 'scripts/new.js', check: 'child-process-require', severity: 'BLOCK', detail: 'd' }];
  const { matched, unmatched, stale } = diff(actual, []);
  assert.strictEqual(matched.length, 0);
  assert.strictEqual(unmatched.length, 1);
  assert.strictEqual(stale.length, 0);
});

test('diff: a baseline entry the scanner no longer finds is stale (would fail CI)', () => {
  const baseline = [{ skill: 'agent-eval', file: 'scripts/x.test.js', check: 'child-process-require' }];
  const { matched, unmatched, stale } = diff([], baseline);
  assert.strictEqual(matched.length, 0);
  assert.strictEqual(unmatched.length, 0);
  assert.strictEqual(stale.length, 1);
});

test('diff: different skill with the same file/check is NOT matched (skill is part of the key)', () => {
  const actual = [{ skill: 'other-skill', file: 'scripts/x.test.js', check: 'child-process-require', severity: 'BLOCK', detail: 'd' }];
  const baseline = [{ skill: 'agent-eval', file: 'scripts/x.test.js', check: 'child-process-require' }];
  const { matched, unmatched, stale } = diff(actual, baseline);
  assert.strictEqual(matched.length, 0);
  assert.strictEqual(unmatched.length, 1);
  assert.strictEqual(stale.length, 1);
});

test('keyOf: joins skill, file, check into a stable string', () => {
  assert.strictEqual(
    keyOf({ skill: 'a', file: 'b', check: 'c' }),
    'a b c'
  );
});

// ── Baseline loading ─────────────────────────────────────────────────────────

test('loadBaseline: loads the committed .github/skill-scan-baseline.json with exactly the three known entries', () => {
  const baseline = loadBaseline(path.join(REPO, '.github', 'skill-scan-baseline.json'));
  assert.strictEqual(baseline.entries.length, 3, `expected 3 baseline entries, got ${baseline.entries.length}`);
  const keys = baseline.entries.map(keyOf).sort();
  assert.deepStrictEqual(keys, [
    'agent-eval scripts/generate-agent-evals.test.js child-process-require',
    'skill-eval scripts/generate-seed-evals.test.js child-process-require',
    'team-eval scripts/generate-team-evals.test.js child-process-require',
  ].sort());
});

test('loadBaseline: a missing file is treated as an empty baseline, not a crash', () => {
  const baseline = loadBaseline(path.join(REPO, '.github', 'does-not-exist.json'));
  assert.deepStrictEqual(baseline.entries, []);
});

// ── Real scan integration (calls exported functions directly; no child_process ──
// ── literal in this file — see file header) ─────────────────────────────────

test('scanSkillDir: real scanner run against skills/agent-eval reproduces the known BLOCK finding', () => {
  const result = scanSkillDir(path.join(REPO, 'skills', 'agent-eval'));
  assert.strictEqual(result.verdict, 'BLOCK');
  const blocks = result.findings.filter(f => f.severity === 'BLOCK');
  assert.strictEqual(blocks.length, 1);
  assert.strictEqual(blocks[0].file, 'scripts/generate-agent-evals.test.js');
  assert.strictEqual(blocks[0].check, 'child-process-require');
});

test('collectBlockFindings + diff: current repo state matches the committed baseline exactly (no unmatched, no stale)', () => {
  const actual = collectBlockFindings(path.join(REPO, 'skills'));
  const baseline = loadBaseline(path.join(REPO, '.github', 'skill-scan-baseline.json'));
  const { unmatched, stale } = diff(actual, baseline.entries);
  assert.strictEqual(unmatched.length, 0, `unexpected unmatched findings: ${JSON.stringify(unmatched)}`);
  assert.strictEqual(stale.length, 0, `unexpected stale baseline entries: ${JSON.stringify(stale)}`);
});

console.log(ok ? '\nAll tests passed.' : '\nSome tests FAILED.');
process.exit(ok ? 0 : 1);
