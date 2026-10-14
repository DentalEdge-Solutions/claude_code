#!/usr/bin/env node
// scripts/run-manifest.test.js — end-to-end tests for
// skills/skill-eval/scripts/run-manifest.js. Lives under scripts/ (not the skill
// dir) because it spawns the CLI, and skills/ is held to the no-child_process
// static scan; see .github/skill-scan-baseline.json for why that matters.
'use strict';
const assert = require('assert');
const crypto = require('crypto');
const fs = require('fs');
const os = require('os');
const path = require('path');
const { spawnSync } = require('child_process');

const CLI = path.join(__dirname, '..', 'skills', 'skill-eval', 'scripts', 'run-manifest.js');

let ok = true;
function test(label, fn) {
  try { fn(); console.log(`PASS ${label}`); }
  catch (e) { console.error(`FAIL ${label}: ${e.message}`); ok = false; }
}
function run(...args) {
  const r = spawnSync(process.execPath, [CLI, ...args], { encoding: 'utf8' });
  return { status: r.status, out: (r.stdout || '') + (r.stderr || '') };
}
function tmp() { return fs.mkdtempSync(path.join(os.tmpdir(), 'run-manifest-')); }
function manifest(dir) { return JSON.parse(fs.readFileSync(path.join(dir, 'run-manifest.json'), 'utf8')); }

test('init without subject flags still works (backward compatible)', () => {
  const dir = path.join(tmp(), 'iteration-1');
  const r = run('init', dir, '--baseline-method', 'none');
  assert.strictEqual(r.status, 0, r.out);
  const m = manifest(dir);
  assert.strictEqual(m.baseline_method, 'none');
  assert.strictEqual(m.subject, null, 'subject recorded as null when not given');
});

test('init --subject records the path and sha256 of the definition under test', () => {
  const root = tmp();
  const subject = path.join(root, 'SKILL.md');
  fs.writeFileSync(subject, '---\nname: demo\n---\nbody\n');
  const dir = path.join(root, 'iteration-1');
  const r = run('init', dir, '--baseline-method', 'none', '--subject', subject, '--commit', 'bca59c5');
  assert.strictEqual(r.status, 0, r.out);
  const m = manifest(dir);
  assert.strictEqual(m.subject.path, subject);
  assert.strictEqual(m.subject.sha256, crypto.createHash('sha256').update(fs.readFileSync(subject)).digest('hex'));
  assert.strictEqual(m.subject.commit, 'bca59c5');
});

test('init --subject on a missing file fails instead of recording a bogus hash', () => {
  const root = tmp();
  const r = run('init', path.join(root, 'it'), '--baseline-method', 'none', '--subject', path.join(root, 'nope.md'));
  assert.notStrictEqual(r.status, 0);
  assert.match(r.out, /subject/i);
  assert.ok(!fs.existsSync(path.join(root, 'it', 'run-manifest.json')), 'no manifest written');
});

test('init --commit rejects a value that is not a hex SHA', () => {
  const root = tmp();
  const subject = path.join(root, 'SKILL.md');
  fs.writeFileSync(subject, 'x');
  const r = run('init', path.join(root, 'it'), '--baseline-method', 'none', '--subject', subject, '--commit', 'main; rm -rf /');
  assert.notStrictEqual(r.status, 0);
  assert.match(r.out, /commit/i);
});

test('the flag values are not mistaken for the iteration dir', () => {
  const root = tmp();
  const subject = path.join(root, 'SKILL.md');
  fs.writeFileSync(subject, 'x');
  const dir = path.join(root, 'iteration-2');
  const r = run('init', '--subject', subject, dir, '--baseline-method', 'none', '--commit', 'abcdef1');
  assert.strictEqual(r.status, 0, r.out);
  assert.ok(fs.existsSync(path.join(dir, 'run-manifest.json')));
});

test('status prints the subject revision', () => {
  const root = tmp();
  const subject = path.join(root, 'SKILL.md');
  fs.writeFileSync(subject, 'x');
  const dir = path.join(root, 'iteration-1');
  run('init', dir, '--baseline-method', 'none', '--subject', subject, '--commit', 'abcdef1');
  const r = run('status', dir);
  assert.match(r.out, /subject=.*SKILL\.md/);
  assert.match(r.out, /commit=abcdef1/);
});

if (!ok) process.exit(1);
console.log('\nrun-manifest.test.js: all tests passed');
