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
  // cwd = tmpdir: a misparsed argument taken as a relative iteration dir lands
  // there, never in the repo (the red phase once created dirs in the repo root).
  const r = spawnSync(process.execPath, [CLI, ...args], { encoding: 'utf8', cwd: os.tmpdir() });
  return { status: r.status, out: (r.stdout || '') + (r.stderr || '') };
}
function runIn(cwd, ...args) {
  const r = spawnSync(process.execPath, [CLI, ...args], { encoding: 'utf8', cwd });
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

test('status says "subject=not recorded" when the manifest has no subject (E9)', () => {
  const dir = path.join(tmp(), 'iteration-1');
  assert.strictEqual(run('init', dir, '--baseline-method', 'none').status, 0);
  assert.match(run('status', dir).out, /^subject=not recorded$/m);
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
  assert.doesNotMatch(r.out, /subject=not recorded/);   // only when there is no subject (E9 review L3)
  assert.match(r.out, /commit=abcdef1/);
});

test('R5: --commit without --subject is refused, not silently dropped', () => {
  const root = tmp();
  const r = run('init', path.join(root, 'it'), '--baseline-method', 'none', '--commit', 'abc1234');
  assert.notStrictEqual(r.status, 0);
  assert.match(r.out, /--commit requires --subject/);
});

test('R6: a value flag with no value (or another flag as its value) is refused', () => {
  const root = tmp();
  let r = run('init', path.join(root, 'a'), '--baseline-method', 'none', '--subject');
  assert.notStrictEqual(r.status, 0);
  assert.match(r.out, /--subject needs a value/);
  r = run('init', path.join(root, 'b'), '--baseline-method', 'none', '--subject', '--commit', 'abc1234');
  assert.notStrictEqual(r.status, 0);
  assert.match(r.out, /--subject needs a value/);
});

test('R6: --subject pointing at a directory fails cleanly, without a stack trace', () => {
  const root = tmp();
  const r = run('init', path.join(root, 'it'), '--baseline-method', 'none', '--subject', root);
  assert.notStrictEqual(r.status, 0);
  assert.match(r.out, /not a file/);
  assert.doesNotMatch(r.out, /EISDIR|at Object\./);
});

// E10 (PR #4 triage): the subject's sha256 is taken once, at init. A resumed run must see when the definition
// changed since then, because the resumed scenarios would measure a different text. status re-hashes the
// subject and warns; its exit code is unchanged (it stays the artifacts-and-grading gate).
function gradedIteration() {
  const root = tmp();
  const subject = path.join(root, 'SKILL.md');
  fs.writeFileSync(subject, 'v1');
  const dir = path.join(root, 'iteration-1');
  run('init', dir, '--baseline-method', 'none', '--subject', subject, '--commit', 'abcdef1');
  for (const side of ['with_skill', 'without_skill']) {
    const d = path.join(dir, 's1-x-r1', side);
    fs.mkdirSync(d, { recursive: true });
    for (const f of ['output.md', 'timing.json', 'evidence.json']) fs.writeFileSync(path.join(d, f), '{}');
  }
  run('mark', dir, 's1-x-r1', 'graded');
  return { subject, dir };
}

test('E10: status says the subject is unchanged when it is', () => {
  const { dir } = gradedIteration();
  const r = run('status', dir);
  assert.strictEqual(r.status, 0, r.out);
  assert.match(r.out, /subject unchanged since init/);
  assert.doesNotMatch(r.out, /WARNING/);
});

test('E10: status warns when the subject changed since init, with the same exit code', () => {
  const { subject, dir } = gradedIteration();
  fs.writeFileSync(subject, 'v2');
  const r = run('status', dir);
  assert.strictEqual(r.status, 0, r.out);
  assert.match(r.out, /WARNING: the subject changed since init/);
  const now = crypto.createHash('sha256').update('v2').digest('hex').slice(0, 12);
  assert.ok(r.out.includes(now), `the current sha256 ${now} is not printed`);
  assert.match(r.out, /start a new iteration/);
  assert.doesNotMatch(r.out, /subject unchanged/);
});

test('E10: status warns when the subject is gone, with the same exit code', () => {
  const { subject, dir } = gradedIteration();
  fs.rmSync(subject);
  const r = run('status', dir);
  assert.strictEqual(r.status, 0, r.out);
  assert.match(r.out, /WARNING: the subject .*SKILL\.md is not found/);
});

test('E10: a changed subject does not turn a failing status into a passing one', () => {
  const { subject, dir } = gradedIteration();
  run('mark', dir, 's2-x-r1', 'pending');
  fs.writeFileSync(subject, 'v2');
  const r = run('status', dir);
  assert.notStrictEqual(r.status, 0);
  assert.match(r.out, /WARNING: the subject changed since init/);
});

test('E10 review R3: the not-found warning says to start a new iteration', () => {
  const { subject, dir } = gradedIteration();
  fs.rmSync(subject);
  assert.match(run('status', dir).out, /WARNING: the subject [^\n]*not found[^\n]*start a new iteration/);
});

test('E10 review R3: a relative subject resolves against the working directory, as at init', () => {
  const root = tmp();
  fs.writeFileSync(path.join(root, 'SKILL.md'), 'v1');
  fs.mkdirSync(path.join(root, 'sub'));
  runIn(root, 'init', 'iteration-1', '--baseline-method', 'none', '--subject', 'SKILL.md', '--commit', 'abcdef1');
  assert.match(runIn(root, 'status', 'iteration-1').out, /subject unchanged since init/);
  fs.writeFileSync(path.join(root, 'SKILL.md'), 'v2');
  assert.match(runIn(root, 'status', 'iteration-1').out, /WARNING: the subject changed since init/);
  assert.match(runIn(path.join(root, 'sub'), 'status', path.join('..', 'iteration-1')).out, /WARNING: the subject SKILL\.md is not found/);
});

// Review R1: after a warning, the closing line must not tell the reader to resume.
const RESUME_LINE = /Resume by dispatching only the incomplete scenarios/;
test('E10 review R1: a failing status after a subject change closes with "start a new iteration", not "Resume"', () => {
  const { subject, dir } = gradedIteration();
  run('mark', dir, 's2-x-r1', 'pending');
  fs.writeFileSync(subject, 'v2');
  const last = run('status', dir).out.trim().split('\n').pop();
  assert.match(last, /^STATUS: FAILED/);
  assert.match(last, /start a new iteration/);
  assert.doesNotMatch(last, RESUME_LINE);
});

test('E10 review R8: a failing status with the subject gone closes with "start a new iteration", not "Resume"', () => {
  const { subject, dir } = gradedIteration();
  run('mark', dir, 's2-x-r1', 'pending');
  fs.rmSync(subject);
  const last = run('status', dir).out.trim().split('\n').pop();
  assert.match(last, /^STATUS: FAILED/);
  assert.match(last, /start a new iteration/);
  assert.doesNotMatch(last, RESUME_LINE);
});

test('E12 review R1: a snapshot manifest (made before E12) is warned about and not resumed', () => {
  const root = tmp();
  const dir = path.join(root, 'iteration-1');
  run('init', dir, '--baseline-method', 'snapshot', '--snapshot-path', path.join(root, 'snap.md'));
  run('mark', dir, 's1-x-r1', 'pending');
  const out = run('status', dir).out;
  assert.match(out, /WARNING: this manifest records baseline_method=snapshot/);
  const last = out.trim().split('\n').pop();
  assert.match(last, /start a new iteration/);
  assert.doesNotMatch(last, RESUME_LINE);
});

test('E10 review R1: a plain failing status still says to resume', () => {
  const { dir } = gradedIteration();
  run('mark', dir, 's2-x-r1', 'pending');
  assert.match(run('status', dir).out.trim().split('\n').pop(), RESUME_LINE);
});

test('E10: no subject, no check line', () => {
  const root = tmp();
  const dir = path.join(root, 'iteration-1');
  run('init', dir, '--baseline-method', 'none');
  const r = run('status', dir);
  assert.doesNotMatch(r.out, /subject unchanged|WARNING: the subject/);
});

if (!ok) process.exit(1);
console.log('\nrun-manifest.test.js: all tests passed');
